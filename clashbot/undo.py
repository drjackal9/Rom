from . import discipline, ledger, roles, seats
from . import settings as settings_mod
from .db import SETTINGS_PREV, SETTINGS_STATE

KINDS = ("warning", "delegate", "settings")
PREV = "prev"
GAME_LEADER = "leader"


def can(members, links, by):
    for tag, link in (links or {}).items():
        if link.user_id == by and ((members or {}).get(tag) or {}).get("role") == GAME_LEADER:
            return True
    return False


async def keep_prev(store, alias, doc):
    current = await store.get_state(alias, SETTINGS_STATE)
    if current is None or current == doc:
        return False
    await store.set_state(alias, SETTINGS_PREV, current)
    return True


async def drop_warning(store, clan, ref):
    kept = discipline.void(await store.get_state(clan.alias, discipline.STATE), ref)
    if kept is None:
        return False
    await store.set_state(clan.alias, discipline.STATE, kept)
    return True


def picked_uid(vault, alias, ref, picked):
    found = seats.uid_of(vault, alias, ref, picked)
    if found:
        return found
    raw = str(ref or "")
    return int(raw) if raw.isdigit() and int(raw) in picked else 0


async def drop_delegate(store, clan, conf, members, ref, by):
    level = await roles.level(store, clan, conf, members, by)
    if not settings_mod.allowed(conf, "delegates", level):
        return False
    picked = [int(found) for found in (conf.get("delegates") or [])]
    uid = picked_uid(store.vault, clan.alias, ref, picked)
    if not uid:
        return False
    stored = await store.get_state(clan.alias, SETTINGS_STATE)
    doc = settings_mod.merge(stored, {"delegates": [f for f in picked if f != uid]})
    await keep_prev(store, clan.alias, doc)
    await store.set_state(clan.alias, SETTINGS_STATE, doc)
    return True


async def restore_settings(store, clan, ref):
    if ref != PREV:
        return False
    previous = await store.get_state(clan.alias, SETTINGS_PREV)
    if previous is None:
        return False
    await store.set_state(clan.alias, SETTINGS_STATE, previous)
    return True


async def apply(store, clan, conf, kind, ref, by, now=None, coc=None):
    if kind not in KINDS:
        return False
    members = await store.get_state(clan.alias, "members") or {}
    if not await roles.live_chief(coc, store, clan, members, by):
        return False
    links = await store.links_for_players(sorted(members))
    if kind == "warning":
        done = await drop_warning(store, clan, ref)
    elif kind == "delegate":
        done = await drop_delegate(store, clan, conf, members, ref, by)
    else:
        done = await restore_settings(store, clan, ref)
    if not done:
        return False
    from . import guard
    await guard.destructive(store, clan.alias, by, "undo", now)
    await ledger.acted(store, clan.alias, "undo", ref, by,
                       next((link.name for link in links.values() if link.user_id == by), None),
                       of=kind, now=now)
    return True
