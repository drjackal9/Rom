import logging

from telegram.error import Forbidden, TelegramError

from .events import missing_attackers, war_key
from .util import parse_coc_time

log = logging.getLogger("clashbot.whisper")

STATE = "nudges"


async def send(bot, link, text, now):
    if not bot or not text or not getattr(link, "whisper", False):
        return None
    try:
        message = await bot.send_message(link.user_id, text, disable_notification=True)
    except Forbidden:
        link.whisper = False
        return None
    except TelegramError as e:
        log.warning("sussurro non consegnato: %s", type(e).__name__)
        return None
    message_id = getattr(message, "message_id", None)
    if not message_id:
        return None
    return {"chat_id": int(link.user_id), "message_id": int(message_id)}


def split_named(named, thread, chunks):
    marked = {nudged.get("kind") for at, nudged in named or () if at == thread}
    groups = []
    for chunk in chunks or ():
        kinds = {chunk[0]} & marked
        if groups and bool(groups[-1][1]) == bool(kinds):
            groups[-1][0].append(chunk)
            groups[-1][1] |= kinds
        else:
            groups.append([[chunk], kinds])
    return groups


def group_rows(named, thread, chat_id, message_id, kinds=None):
    if message_id is True or not message_id:
        return []
    rows = []
    for at, nudged in named or ():
        if at != thread or (kinds is not None and nudged.get("kind") not in kinds):
            continue
        rows.extend({"tag": tag, "chat_id": chat_id, "message_id": message_id, "war": nudged["war"]}
                    for tag in nudged["tags"])
    return rows


async def remember(store, alias, rows):
    if not rows:
        return
    state = await store.get_state(alias, STATE) or {}
    for row in rows:
        entries = state.setdefault(row["tag"], [])
        entry = {"chat_id": row["chat_id"], "message_id": row["message_id"], "war": row["war"]}
        if entry not in entries:
            entries.append(entry)
    await store.set_state(alias, STATE, state)


def _over(key, now):
    end = parse_coc_time((key or "").split("|")[0])
    return bool(end) and end <= now


def _settled(tag, entry, key, missing, now):
    if _over(entry.get("war"), now):
        return True
    return entry.get("war") == key and tag not in missing


async def _mute(store, tag, chat_id):
    link = (await store.links_for_players([tag])).get(tag)
    if link and int(link.user_id) == int(chat_id):
        await store.set_link_whisper(link.user_id, tag, False)


async def _forget(bot, store, tag, entry):
    try:
        await bot.delete_message(entry["chat_id"], entry["message_id"])
    except Forbidden:
        await _mute(store, tag, entry["chat_id"])
    except TelegramError as e:
        log.warning("menzione non cancellata: %s", type(e).__name__)


async def settle(bot, store, alias, war, now):
    state = await store.get_state(alias, STATE)
    if not bot or not state:
        return
    key = war_key(war) if war else None
    missing = {m["tag"] for m in missing_attackers(war)} if war else set()
    keep, done = {}, []
    for tag in sorted(state):
        for entry in state[tag] or ():
            if _settled(tag, entry, key, missing, now):
                done.append((tag, entry))
            else:
                keep.setdefault(tag, []).append(entry)
    alive = {(row["chat_id"], row["message_id"]) for rows in keep.values() for row in rows}
    gone = set()
    for tag, entry in done:
        mark = (entry["chat_id"], entry["message_id"])
        if mark in alive or mark in gone:
            continue
        gone.add(mark)
        await _forget(bot, store, tag, entry)
    if keep == state:
        return
    if keep:
        await store.set_state(alias, STATE, keep)
    else:
        await store.del_state(alias, STATE)
