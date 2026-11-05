from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ChatJoinRequestHandler

from . import door, exports, gate, i18n, leader_cards, leaders, ledger, media, progress, render
from . import texts as free_text
from .events import member_stats
from .guard import NOTICE, REFUSAL, destructive, suspended
from .retention import WAR_HISTORY_KEEP
from .util import esc, normalize_tag, now_utc

FLOW = "leader"
WIZARD_STEPS = ("h", "m", "d", "ok")
TEXT_CARDS = {"rules": leader_cards.rules_card, "welcome": leader_cards.welcome_preview}


def wizard(context):
    flow = context.user_data.get("flow") or {}
    if flow.get("kind") != FLOW or flow.get("step") != "schedule":
        return None
    return flow


async def guard(update, context, manage=True):
    from . import handlers as h
    store, _ = h.services(context)
    clan = await h.clan_for(update, context)
    if not clan:
        return None, h.user_locale(update), None, "unlinked"
    conf = await h.clan_settings(store, clan)
    L = await h.actor_locale(store, update) if h.private_chat(update) else i18n.locale(conf["lang"])
    if manage and not await h.can_lead(update, context, clan):
        return None, L, None, "denied"
    by, _ = who(update)
    if by is not None and await suspended(store, clan.alias, by):
        return None, L, None, "suspended"
    return clan, L, conf, None


def refusal(L, reason):
    if reason == "suspended":
        return L.t(REFUSAL)
    return L.t("leaders.only") if reason == "denied" else render.not_linked_view(L)


async def refuse(query, L, reason):
    from . import handlers as h
    if reason in ("denied", "suspended"):
        await query.answer(refusal(L, reason), show_alert=True)
        return
    await query.answer()
    await h.edit_or_log(query, render.not_linked_view(L), None, "?")


def who(update):
    from . import handlers as h
    user = h.actor(update)
    return getattr(user, "id", None), getattr(user, "first_name", None)


async def text_limits(context, store):
    return context.bot.username, media.host(await media.site_base(store))


async def save_text(update, context, clan, conf, key, raw):
    from . import handlers as h
    store, _ = h.services(context)
    bot_username, site_host = await text_limits(context, store)
    texts = dict(conf.get("texts") or {})
    texts[key] = leaders.sanitize(raw, leaders.TEXT_MAX, bot_username, site_host)
    by, by_name = who(update)
    await h.save_settings(store, clan, {"texts": texts})
    await ledger.record(store, clan.alias, key, by, by_name, None, now_utc())


async def save_schedule(store, clan, entries):
    from . import handlers as h
    await h.save_settings(store, clan, {"scheduled": entries})


async def open_text(update, context, L, conf, key, leads):
    from . import handlers as h
    text = TEXT_CARDS[key](L, leaders.texts(conf)[key])
    if leads and h.private_chat(update):
        context.user_data["flow"] = {"kind": FLOW, "step": key}
        text += "\n" + L.t("leaders.ask_text")
    elif leads:
        text += "\n" + L.t("leaders.private_only", bot=context.bot.username)
    await update.effective_message.reply_text(text)


async def cmd_text(update, context, key, manage):
    from . import handlers as h
    clan, L, conf, why = await guard(update, context, manage=manage)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    leads = True if manage else await h.can_lead(update, context, clan)
    raw = " ".join(context.args or [])
    if not raw:
        await open_text(update, context, L, conf, key, leads)
        return
    if not leads:
        await update.effective_message.reply_text(refusal(L, "denied"))
        return
    try:
        await save_text(update, context, clan, conf, key, raw)
    except ValueError as rejected:
        await update.effective_message.reply_text(free_text.reason(L, str(rejected)))
        return
    await update.effective_message.reply_text(L.t(f"leaders.{key}.saved"))


async def cmd_rules(update, context):
    await cmd_text(update, context, "rules", False)


async def cmd_welcome(update, context):
    await cmd_text(update, context, "welcome", True)


async def cmd_schedule(update, context):
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    entries = leaders.schedule(conf)
    await update.effective_message.reply_text(leader_cards.schedule_card(L, entries),
                                              reply_markup=leader_cards.schedule_keyboard(L, entries))


async def show_schedule(query, L, entries, alias):
    from . import handlers as h
    await h.edit_or_log(query, leader_cards.schedule_card(L, entries),
                        leader_cards.schedule_keyboard(L, entries), alias)


async def drop_entry(update, context, clan, L, conf, entry_id):
    from . import handlers as h
    store, _ = h.services(context)
    entries = [entry for entry in leaders.schedule(conf) if entry["id"] != entry_id]
    by, by_name = who(update)
    await save_schedule(store, clan, entries)
    await ledger.record(store, clan.alias, "schedule", by, by_name, entry_id, now_utc())
    _, braked = await destructive(store, clan.alias, by, "schedule.delete")
    await update.callback_query.answer(L.t(NOTICE) if braked else L.t("leaders.schedule.removed"),
                                       show_alert=braked)
    await show_schedule(update.callback_query, L, entries, clan.alias)


async def on_leader_callback(update, context):
    from . import handlers as h
    query = update.callback_query
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await refuse(query, L, why)
        return
    parts = (query.data or "").split(":")
    step = parts[2] if len(parts) > 2 else ""
    value = ":".join(parts[3:])
    if step == "del":
        await drop_entry(update, context, clan, L, conf, value)
        return
    if step == "add" and len(leaders.schedule(conf)) >= leaders.SCHEDULE_MAX:
        await query.answer(L.t("leaders.schedule.full", n=leaders.SCHEDULE_MAX), show_alert=True)
        return
    await query.answer()
    if step == "add":
        if not h.private_chat(update):
            await h.edit_or_log(query, L.t("leaders.private_only", bot=context.bot.username),
                                None, clan.alias)
            return
        context.user_data["flow"] = {"kind": FLOW, "step": "schedule", "days": []}
        await h.edit_or_log(query, L.t("leaders.schedule.pick_hour"),
                            leader_cards.hours_keyboard(L), clan.alias)
        return
    flow = wizard(context)
    if step in WIZARD_STEPS and flow is None:
        await show_schedule(query, L, leaders.schedule(conf), clan.alias)
        return
    if step == "h":
        await h.edit_or_log(query, L.t("leaders.schedule.pick_minute"),
                            leader_cards.minutes_keyboard(L, value), clan.alias)
        return
    if step == "m":
        flow["hhmm"] = leaders.slot(value)
        await h.edit_or_log(query, L.t("leaders.schedule.pick_days"),
                            leader_cards.days_keyboard(L, flow.get("days") or []), clan.alias)
        return
    if step == "d":
        picked = list(flow.get("days") or [])
        if value == "all":
            picked = []
        elif value.isdigit():
            day = int(value)
            picked = [d for d in picked if d != day] if day in picked else sorted(picked + [day])
        flow["days"] = picked
        await h.edit_or_log(query, L.t("leaders.schedule.pick_days"),
                            leader_cards.days_keyboard(L, picked), clan.alias)
        return
    if step == "ok":
        await h.edit_or_log(query, L.t("leaders.schedule.ask_text"), None, clan.alias)


async def on_text(update, context, flow):
    from . import handlers as h
    message = update.effective_message
    clan, L, conf, why = await guard(update, context)
    if not clan:
        context.user_data.pop("flow", None)
        await message.reply_text(refusal(L, why))
        return
    raw = (message.text or "").strip()
    step = flow.get("step")
    if step in TEXT_CARDS:
        try:
            await save_text(update, context, clan, conf, step, raw)
        except ValueError as rejected:
            await message.reply_text(free_text.reason(L, str(rejected)))
            return
        context.user_data.pop("flow", None)
        await message.reply_text(L.t(f"leaders.{step}.saved"))
        return
    if step != "schedule" or not flow.get("hhmm"):
        return
    store, _ = h.services(context)
    entries = leaders.schedule(conf)
    by, by_name = who(update)
    bot_username, site_host = await text_limits(context, store)
    try:
        entry = leaders.new_entry(entries, flow["hhmm"], flow.get("days") or [], raw, by,
                                  bot_username, site_host)
    except ValueError as rejected:
        await message.reply_text(free_text.reason(L, str(rejected)))
        return
    if not entry:
        if len(entries) >= leaders.SCHEDULE_MAX:
            context.user_data.pop("flow", None)
            await message.reply_text(L.t("leaders.schedule.full", n=leaders.SCHEDULE_MAX))
            return
        await message.reply_text(L.t("leaders.schedule.ask_text"))
        return
    context.user_data.pop("flow", None)
    entries.append(entry)
    await save_schedule(store, clan, entries)
    await ledger.record(store, clan.alias, "schedule", by, by_name, entry["hhmm"], now_utc())
    await message.reply_text(L.t("leaders.schedule.added", hhmm=entry["hhmm"]),
                             reply_markup=leader_cards.schedule_keyboard(L, entries))


async def cmd_gate(update, context):
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    on = leaders.gate_on(conf)
    await update.effective_message.reply_text(leader_cards.gate_card(L, on),
                                              reply_markup=leader_cards.gate_keyboard(L, on))


async def greet(bot, L, conf, clan, chat_id, player):
    texts = leaders.texts(conf)
    hello = (leader_cards.welcome_card(L, texts["welcome"], player, clan.name) if texts["welcome"]
             else L.t("leaders.gate.hello", clan=esc(clan.name)))
    parts = [hello] + ([leader_cards.rules_card(L, texts["rules"])] if texts["rules"] else [])
    for part in parts:
        try:
            await bot.send_message(chat_id, part)
        except TelegramError:
            break


async def on_join_request(update, context):
    from . import handlers as h
    request = update.chat_join_request
    store, _ = h.services(context)
    clan = await store.clan_by_chat(request.chat.id, h.bot_alias(context))
    if not clan:
        return
    conf = await h.clan_settings(store, clan)
    if not leaders.gate_on(conf):
        return
    L = i18n.locale(conf["lang"])
    call, player = await gate.verdict(store, clan, request.from_user.id)
    if call != "approve":
        await leaders.to_feed(
            store, clan, conf, "leaders.gate",
            leader_cards.gate_request_card(L, request.from_user.first_name, request.from_user.username))
        await store.kv_set(gate.pending_key(clan.alias, request.from_user.id),
                           {"chat_id": request.chat.id, "name": request.from_user.first_name},
                           ref=clan.alias, ttl=gate.PENDING_TTL)
        return
    try:
        await request.approve()
    except TelegramError:
        await leaders.notify(store, context.bot, clan, conf, "leaders.gate",
                             leader_cards.gate_needs_admin(L))
        return
    await door.note_seen(store, clan.alias, request.from_user.id)
    await leaders.notify(store, context.bot, clan, conf, "leaders.gate",
                         leader_cards.gate_auto(L, request.from_user.first_name, player))
    await greet(context.bot, L, conf, clan, request.user_chat_id, player)


async def on_gate_callback(update, context):
    from . import handlers as h
    query = update.callback_query
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await refuse(query, L, why)
        return
    store, _ = h.services(context)
    action, raw = query.data.split(":")[1:3]
    key = gate.pending_key(clan.alias, raw)
    pending = await store.kv_get(key) or {}
    by, by_name = who(update)
    await query.answer()
    if not pending:
        await h.edit_or_log(query, leader_cards.gate_gone(L), None, clan.alias)
        return
    decide = (context.bot.approve_chat_join_request if action == "ok"
              else context.bot.decline_chat_join_request)
    try:
        await decide(pending.get("chat_id") or clan.chat_id, int(raw))
    except TelegramError:
        await h.edit_or_log(query, leader_cards.gate_needs_admin(L), None, clan.alias)
        return
    await store.kv_del(key)
    if action == "ok":
        await door.note_seen(store, clan.alias, int(raw))
    await ledger.record(store, clan.alias, "gate", by, by_name, action, now_utc())
    await h.edit_or_log(query, leader_cards.gate_done(L, pending.get("name") or raw,
                                                      action == "ok", by_name), None, clan.alias)


async def on_gate_switch(update, context):
    from . import handlers as h
    query = update.callback_query
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await refuse(query, L, why)
        return
    store, _ = h.services(context)
    by, by_name = who(update)
    on = not leaders.gate_on(conf)
    await h.save_settings(store, clan, {"gate": on})
    await ledger.record(store, clan.alias, "gate", by, by_name, "on" if on else "off", now_utc())
    await query.answer()
    await h.edit_or_log(query, leader_cards.gate_card(L, on), leader_cards.gate_keyboard(L, on),
                        clan.alias)


async def cmd_note(update, context):
    from . import handlers as h
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    store, _ = h.services(context)
    args = list(context.args or [])
    if not args:
        rows = sorted((await ledger.notes_all(store, clan.alias)).items(),
                      key=lambda item: (item[1].get("name") or item[0]))
        await update.effective_message.reply_text(leader_cards.notes_card(L, rows))
        return
    members = await store.get_state(clan.alias, "members") or {}
    tag = normalize_tag(args[0])
    if not tag or tag not in members:
        await update.effective_message.reply_text(L.t("leaders.note.unknown"))
        return
    name = (members[tag] or {}).get("name")
    rest = " ".join(args[1:]).strip()
    if not rest:
        note = await ledger.note_get(store, clan.alias, tag)
        await update.effective_message.reply_text(
            leader_cards.note_card(L, conf["tz"], tag, name, note))
        return
    by, by_name = who(update)
    if rest == "-":
        if not await ledger.note_del(store, clan.alias, tag):
            await update.effective_message.reply_text(L.t("leaders.note.none"))
            return
        await ledger.record(store, clan.alias, "note", by, by_name, name, now_utc())
        _, braked = await destructive(store, clan.alias, by, "text.delete")
        await update.effective_message.reply_text(L.t(NOTICE) if braked else L.t("leaders.note.removed"))
        return
    await ledger.note_set(store, clan.alias, tag, name, rest, by, by_name, now_utc())
    await ledger.record(store, clan.alias, "note", by, by_name, name, now_utc())
    await update.effective_message.reply_text(L.t("leaders.note.saved"))


async def cmd_log(update, context):
    from . import handlers as h
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    store, _ = h.services(context)
    await update.effective_message.reply_text(
        leader_cards.log_card(L, conf["tz"], await ledger.history(store, clan.alias)))


async def cmd_export(update, context):
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    await update.effective_message.reply_text(leader_cards.export_card(L),
                                              reply_markup=leader_cards.export_keyboard(L))


async def export_payload(store, clan, kind, records):
    if kind == "wars":
        return exports.wars_csv(records)
    stored = await store.get_state(clan.alias, "progress")
    return exports.members_csv(
        await store.get_state(clan.alias, "members") or {},
        member_stats(records),
        await store.get_state(clan.alias, "season") or {},
        progress.deltas(stored if isinstance(stored, dict) else {}, "month"),
    )


async def on_export_callback(update, context):
    from . import handlers as h
    query = update.callback_query
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await refuse(query, L, why)
        return
    store, _ = h.services(context)
    kind = query.data.split(":")[1]
    await query.answer()
    records = await store.recent_wars(clan.alias, WAR_HISTORY_KEEP)
    payload = await export_payload(store, clan, kind, records)
    if not exports.filled(payload):
        await query.message.reply_text(L.t("leaders.export.empty"))
        return
    now = now_utc()
    by, by_name = who(update)
    await ledger.record(store, clan.alias, "export", by, by_name, kind, now)
    await context.bot.send_document(query.message.chat_id, payload,
                                    filename=f"{kind}-{now.strftime('%Y-%m-%d')}.csv",
                                    caption=L.t("leaders.export.caption"))


AREA = "leaders"
COMMANDS = [("rules", ["regole"]), ("welcome", ["benvenuto"]), ("schedule", ["programma"]),
            ("gate", ["ingresso"]), ("note", ["nota"]), ("log", ["registro"]),
            ("export", ["esporta"])]
HANDLERS = {"rules": cmd_rules, "welcome": cmd_welcome, "schedule": cmd_schedule, "gate": cmd_gate,
            "note": cmd_note, "log": cmd_log, "export": cmd_export}


def extra_handlers():
    return [CallbackQueryHandler(on_leader_callback, pattern=r"^lt:"),
            CallbackQueryHandler(on_gate_switch, pattern=r"^gt:switch$"),
            CallbackQueryHandler(on_gate_callback, pattern=r"^gt:(ok|no):\d+$"),
            CallbackQueryHandler(on_export_callback, pattern=r"^ex:(wars|members)$"),
            ChatJoinRequestHandler(on_join_request)]
