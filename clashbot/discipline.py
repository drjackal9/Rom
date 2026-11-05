import secrets as pysecrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from . import feed, i18n, ledger, render, render_live
from .events import missing_attackers, war_key
from .retention import WAR_HISTORY_KEEP
from .util import now_utc

STATE = "discipline"
EVENT = "war.warning"
PREFIX = "warn:"
CODE_BYTES = 12
EDIT_WINDOW = 48 * 3600
YES = "1"
NO = "0"


def proposals(war):
    rows = [{"tag": m["tag"], "name": m["name"], "missed": m["left"]} for m in missing_attackers(war)]
    rows.sort(key=lambda row: (-row["missed"], row["name"] or ""))
    return rows


def register(entries, row, members=None, keep=WAR_HISTORY_KEEP):
    rows = [r for r in (entries or []) if isinstance(r, dict)]
    if members is not None:
        rows = [r for r in rows if r.get("tag") in members]
    rows.append(row)
    return rows[-keep:]


def counts(entries):
    out = {}
    for row in (entries or []):
        if isinstance(row, dict) and row.get("tag"):
            out[row["tag"]] = out.get(row["tag"], 0) + 1
    return out


def void(entries, ref):
    rows = [r for r in (entries or []) if isinstance(r, dict)]
    kept = [r for r in rows if r.get("id") != ref]
    return kept if len(kept) != len(rows) else None


def keyboard(L, code, rows, decided):
    buttons = []
    for index, row in enumerate(rows):
        if str(index) in (decided or {}):
            continue
        buttons.append([
            InlineKeyboardButton(L.t("warn.btn_yes", name=row["name"]),
                                 callback_data=f"w:{code}:{index}:{YES}"),
            InlineKeyboardButton(L.t("warn.btn_no", name=row["name"]),
                                 callback_data=f"w:{code}:{index}:{NO}"),
        ])
    return InlineKeyboardMarkup(buttons) if buttons else None


async def propose(poller, t, war, kind, day):
    rows = proposals(war)
    if not rows or poller.destination(t.settings, EVENT)[0] == "off":
        return None
    seen = counts(await poller.store.get_state(t.clan.alias, STATE))
    code = pysecrets.token_urlsafe(CODE_BYTES)
    payload = {"alias": t.clan.alias, "war": war_key(war), "rows": rows, "decided": {}, "messages": []}
    await poller.store.kv_set(PREFIX + code, payload, ref=t.clan.alias, ttl=EDIT_WINDOW)
    await poller.dispatch(t, EVENT,
                          lambda L: render_live.warning_proposal_card(L, rows, seen, kind, day))
    return code


async def refresh(context, code, payload):
    for user_id, message_id, lang in payload["messages"]:
        markup = keyboard(i18n.locale(lang), code, payload["rows"], payload["decided"])
        try:
            await context.bot.edit_message_reply_markup(chat_id=user_id, message_id=message_id,
                                                        reply_markup=markup)
        except TelegramError:
            pass


async def notify(store, conf, clan, row, now=None, by=None):
    from .poller import member_locale
    link = (await store.links_for_players([row["tag"]])).get(row["tag"])
    if not link:
        return
    L = await member_locale(store, link, conf)
    await feed.add(store, clan.alias, link.user_id, EVENT,
                   render_live.warning_notice_card(L, row, by), now or now_utc())


async def confirm(store, clan, conf, row, war, uid, now):
    from . import guard
    members = await store.get_state(clan.alias, "members")
    mine = await store.links_by_user(uid)
    entry = {"id": pysecrets.token_hex(CODE_BYTES),
             "tag": row["tag"], "name": row["name"], "war": war, "missed": row["missed"],
             "at": now.timestamp(),
             "by": next((link.tag for link in mine if link.tag in (members or {})), None)}
    by_name = ((members or {}).get(entry["by"]) or {}).get("name")
    entries = register(await store.get_state(clan.alias, STATE), entry,
                       members=set(members) if members else None)
    await store.set_state(clan.alias, STATE, entries)
    await ledger.acted(store, clan.alias, "warning", entry["id"], uid, by_name, now=now)
    await notify(store, conf, clan, entry, now=now, by=by_name)
    _, braked = await guard.destructive(store, clan.alias, uid, "warning", now)
    return entry, braked


async def on_warning_callback(update, context):
    from . import guard
    from .handlers import actor_locale, can_manage, clan_settings, services
    query = update.callback_query
    store, _ = services(context)
    parts = query.data.split(":")
    if len(parts) != 4 or parts[3] not in (YES, NO) or not parts[2].isdigit():
        await query.answer()
        return
    _prefix, code, index, choice = parts
    payload = await store.kv_get(PREFIX + code)
    clan = await store.clan_by_alias(payload["alias"]) if payload else None
    if not clan:
        await query.answer()
        return
    said = await actor_locale(store, update)
    if await guard.suspended(store, clan.alias, update.effective_user.id):
        await query.answer(said.t(guard.REFUSAL), show_alert=True)
        return
    if not await can_manage(update, context, clan, "warnings"):
        await query.answer(said.t("h.admin_only"), show_alert=True)
        return
    rows = payload["rows"]
    if int(index) >= len(rows) or index in payload["decided"]:
        await query.answer()
        return
    row = rows[int(index)]
    payload["decided"][index] = choice
    await store.kv_set(PREFIX + code, payload, ref=payload["alias"], ttl=EDIT_WINDOW)
    braked = False
    if choice == YES:
        conf = await clan_settings(store, clan)
        _, braked = await confirm(store, clan, conf, row, payload["war"],
                                  update.effective_user.id, now_utc())
    if braked:
        await query.answer(said.t(guard.NOTICE), show_alert=True)
    else:
        await query.answer(said.t("warn.saved" if choice == YES else "warn.skipped"))
    await refresh(context, code, payload)


async def cmd_warnings(update, context):
    from .handlers import can_manage, clan_for, services, user_locale, view_locale
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, tz = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan, "warnings"):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    entries = await store.get_state(clan.alias, STATE)
    await update.effective_message.reply_text(render_live.warnings_view(L, entries, tz))
