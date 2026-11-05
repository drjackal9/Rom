from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes

from . import family as family_mod, i18n, leaders, recruit, recruit_block, recruit_cards
from . import render, roles
from .achievements import player_snapshot
from .recruit_jobs import publish_now
from .util import normalize_tag, now_utc

AREA = "recruitment"
COMMANDS = [("apply", ["candidati"]), ("applications", ["candidature"])]
START_APPLY = "apply"


async def clan_conf(store, clan):
    from . import handlers as h
    conf = await h.clan_settings(store, clan)
    return conf, i18n.locale(conf["lang"])


async def target_clans(store, context, code=None):
    clans = list(await store.active_clans(context.bot_data.get("bot_alias")))
    if not code:
        return clans
    return [clan for clan in clans if store.recruit_code(clan.alias) == code] or clans


async def start_for(update, context, clan):
    from . import handlers as h
    store, _ = h.services(context)
    conf, L = await clan_conf(store, clan)
    user = update.effective_user
    reply = update.effective_message.reply_text
    if await recruit_block.refuses(store, clan.alias, user.id):
        context.user_data.pop("flow", None)
        await reply(L.t("recruit.apply.blocked"))
        return
    members = await store.get_state(clan.alias, "members") or {}
    links = await store.links_by_user(user.id)
    if any(link.tag in members for link in links):
        context.user_data.pop("flow", None)
        await reply(L.t("recruit.apply.already_member"))
        return
    state = recruit.state_of(await store.get_state(clan.alias, recruit.KIND))
    if recruit.pending(state, user.id):
        context.user_data.pop("flow", None)
        await reply(L.t("recruit.apply.already_pending"))
        return
    if not await roles.chiefs(store, members):
        context.user_data.pop("flow", None)
        await reply(L.t("recruit.unverified"))
        return
    flow = {"kind": "apply", "clan": clan.alias, "goals": [], "below": False}
    context.user_data["flow"] = flow
    await reply(recruit_cards.intro_card(L, clan.name, recruit.requirement(conf)))
    if links:
        flow["step"] = "account"
        flow["tags"] = [link.tag for link in links]
        await reply(L.t("recruit.apply.pick_account"),
                    reply_markup=recruit_cards.accounts_keyboard(L, links))
        return
    flow["step"] = "tag"
    await reply(L.t("recruit.apply.ask_tag"))


async def cmd_apply(update: Update, context: ContextTypes.DEFAULT_TYPE, code=None):
    from . import handlers as h
    store, _ = h.services(context)
    L = h.user_locale(update)
    if update.effective_chat.type != ChatType.PRIVATE:
        clan = await store.clan_by_chat(update.effective_chat.id, context.bot_data.get("bot_alias"))
        if clan:
            _, L = await clan_conf(store, clan)
            code = store.recruit_code(clan.alias)
        payload = f"{START_APPLY}_{code}" if code else START_APPLY
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
            L.t("recruit.apply.btn_private"),
            url=f"https://t.me/{context.bot.username}?start={payload}")]])
        await update.effective_message.reply_text(
            L.t("recruit.apply.private", bot=context.bot.username), reply_markup=keyboard)
        return
    clans = await target_clans(store, context, code)
    if not clans:
        await update.effective_message.reply_text(L.t("recruit.apply.no_clan"))
        return
    if len(clans) > 1:
        context.user_data["flow"] = {"kind": "apply", "step": "clan",
                                     "clans": [clan.alias for clan in clans]}
        await update.effective_message.reply_text(
            L.t("recruit.apply.pick_clan"),
            reply_markup=recruit_cards.clans_keyboard([clan.name for clan in clans]))
        return
    await start_for(update, context, clans[0])


async def chosen_tag(update, context, flow, tag, verified):
    from . import handlers as h
    store, coc = h.services(context)
    clan = await store.clan_by_alias(flow["clan"])
    conf, L = await clan_conf(store, clan)
    reply = update.effective_message.reply_text
    data, error = await coc.player(tag)
    if not data:
        await reply(render.api_error(L, error, tag))
        return
    members = await store.get_state(clan.alias, "members") or {}
    if tag in members:
        context.user_data.pop("flow", None)
        await reply(L.t("recruit.apply.already_member"))
        return
    flow.update(tag=tag, verified=bool(verified), snap=player_snapshot(data))
    if not recruit.meets(conf, flow["snap"]):
        flow["step"] = "below"
        await reply(recruit_cards.below_card(L, flow["snap"].get("th") or "?",
                                             recruit.requirement(conf)),
                    reply_markup=recruit_cards.below_keyboard(L))
        return
    flow["step"] = "goals"
    await reply(recruit_cards.goals_card(L, clan.name, flow["goals"]),
                reply_markup=recruit_cards.goals_keyboard(L, flow["goals"]))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE, flow):
    from . import handlers as h
    if flow.get("step") != "tag":
        return
    tag = normalize_tag(update.effective_message.text or "")
    if not tag:
        await update.effective_message.reply_text(h.user_locale(update).t("h.tag_invalid"))
        return
    await chosen_tag(update, context, flow, tag, False)


async def submit(update, context, flow):
    from . import handlers as h
    store, _ = h.services(context)
    clan = await store.clan_by_alias(flow["clan"])
    conf, L = await clan_conf(store, clan)
    if await recruit_block.refuses(store, clan.alias, update.effective_user.id):
        context.user_data.pop("flow", None)
        await update.effective_message.reply_text(L.t("recruit.apply.blocked"))
        return
    state = recruit.state_of(await store.get_state(clan.alias, recruit.KIND))
    state, app = recruit.add(state, flow["tag"], flow["snap"], update.effective_user.id,
                             flow["verified"], flow["goals"], flow["below"], now_utc())
    await store.set_state(clan.alias, recruit.KIND, state)
    context.user_data.pop("flow", None)
    text = recruit_cards.applicant_card(L, app, clan.name, recruit.requirement(conf))
    await leaders.notify(store, context.bot, clan, conf, "recruit.application", text,
                         reply_markup=recruit_cards.decision_keyboard(L, app["id"]))
    await update.effective_message.reply_text(recruit_cards.sent_card(L, clan.name))


async def on_apply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    query = update.callback_query
    store, _ = h.services(context)
    flow = context.user_data.get("flow")
    await query.answer()
    if not flow or flow.get("kind") != "apply":
        return
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""
    if action == "clan":
        picked = [clan for clan in await target_clans(store, context)
                  if clan.alias in flow.get("clans", [])]
        index = int(value) if value.isdigit() else -1
        if 0 <= index < len(picked):
            await start_for(update, context, picked[index])
        return
    if action == "acc":
        index = int(value) if value.isdigit() else -1
        tags = flow.get("tags") or []
        if 0 <= index < len(tags):
            await chosen_tag(update, context, flow, tags[index], True)
        return
    clan = await store.clan_by_alias(flow.get("clan"))
    if not clan:
        return
    _, L = await clan_conf(store, clan)
    if action == "anyway":
        flow.update(below=True, step="goals")
        await query.message.reply_text(recruit_cards.goals_card(L, clan.name, flow["goals"]),
                                       reply_markup=recruit_cards.goals_keyboard(L, flow["goals"]))
        return
    if action == "stop":
        context.user_data.pop("flow", None)
        await query.message.reply_text(L.t("recruit.apply.stopped"))
        return
    if action == "g" and value in recruit.GOALS:
        picked = set(flow.get("goals") or ())
        picked.symmetric_difference_update({value})
        flow["goals"] = recruit.goals_of(picked)
        await h.edit_or_log(query, recruit_cards.goals_card(L, clan.name, flow["goals"]),
                            recruit_cards.goals_keyboard(L, flow["goals"]), clan.alias)
        return
    if action == "send" and flow.get("step") == "goals":
        await submit(update, context, flow)


async def leader_clan(update, context):
    from . import handlers as h
    store, _ = h.services(context)
    clan = await h.clan_for(update, context)
    if not clan:
        return None, h.user_locale(update)
    L, _ = await h.clan_locale(store, clan)
    return clan, L


async def cmd_applications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    clan, L = await leader_clan(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(L))
        return
    if not await h.can_lead(update, context, clan):
        await update.effective_message.reply_text(L.t("recruit.only_leaders"))
        return
    rows = recruit.pending(recruit.state_of(await store.get_state(clan.alias, recruit.KIND)))
    await update.effective_message.reply_text(
        recruit_cards.applications_card(L, rows),
        reply_markup=recruit_cards.applications_keyboard(L, rows))


async def on_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    from . import ledger
    query = update.callback_query
    store, _ = h.services(context)
    clan, L = await leader_clan(update, context)
    if not clan:
        await query.answer()
        return
    if not await h.can_lead(update, context, clan):
        await query.answer(L.t("recruit.only_leaders"), show_alert=True)
        return
    parts = query.data.split(":")
    action, app_id = parts[1], parts[2] if len(parts) > 2 else ""
    state = recruit.state_of(await store.get_state(clan.alias, recruit.KIND))
    app = recruit.find(state, app_id)
    if not app or (action in ("y", "n") and app["state"] != "pending"):
        await query.answer(L.t("recruit.gone"), show_alert=True)
        return
    if action == "o":
        conf = await h.clan_settings(store, clan)
        await query.answer()
        await h.edit_or_log(query, recruit_cards.applicant_card(L, app, clan.name,
                                                                recruit.requirement(conf)),
                            recruit_cards.decision_keyboard(L, app["id"]), clan.alias)
        return
    if action not in ("y", "n"):
        await query.answer()
        return
    user = update.effective_user
    accepted = action == "y"
    state, decided = recruit.decide(state, app_id, "accepted" if accepted else "rejected",
                                    user.id if user else None,
                                    user.first_name if user else None, now_utc())
    await store.set_state(clan.alias, recruit.KIND, state)
    await ledger.record(store, clan.alias, "apply", user.id if user else None,
                        user.first_name if user else None,
                        (decided.get("snap") or {}).get("name"), now_utc())
    await query.answer()
    try:
        await context.bot.send_message(decided["user_id"],
                                       recruit_cards.answer_card(L, clan.name, clan.tag, accepted))
    except TelegramError:
        pass
    await h.edit_or_log(query, L.t("recruit.decided.accepted" if accepted
                                   else "recruit.decided.rejected"), None, clan.alias)


async def my_filters(store, clan, update, picked):
    if picked == "country":
        info = await store.get_state(clan.alias, "info") or {}
        return {"country": info.get("country")}
    if picked == "th":
        user = update.effective_user
        players = (await store.get_state(clan.alias, "players") or {}).get("tags") or {}
        levels = [players[link.tag]["th"] for link in await store.links_by_user(user.id)
                  if link.tag in players and players[link.tag].get("th")]
        return {"min_th": max(levels)} if levels else {}
    return {}


async def board_for(update, context, clan, picked="all"):
    from . import handlers as h
    store, _ = h.services(context)
    L, tz = await h.clan_locale(store, clan)
    row = await store.recruit_row(clan.alias)
    rows = await store.recruit_board(**(await my_filters(store, clan, update, picked)))
    manage = await h.can_manage(update, context, clan)
    return (recruit_cards.board_view(L, tz, rows, bool(row), now_utc()),
            recruit_cards.board_keyboard(L, manage, bool(row), picked))


async def cmd_recruit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    chat = update.effective_chat
    clan, L, _ = await h.chat_locale(update, context)
    family = (await store.family_of_clan(clan.alias) if clan
              else await store.family_by_chat(chat.id, h.bot_alias(context)))
    if family:
        FL, tz = await h.family_locale(store, family, update)
        await update.effective_message.reply_text(
            render.recruit_board(FL, tz, family, await family_mod.rows(store, family), now_utc()),
            reply_markup=recruit_cards.open_keyboard(L) if clan else None)
        return
    if not clan:
        await update.effective_message.reply_text(L.t("h.recruit_none"))
        return
    text, keyboard = await board_for(update, context, clan)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def on_board_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    from . import ledger
    query = update.callback_query
    store, _ = h.services(context)
    clan, L = await leader_clan(update, context)
    if not clan:
        await query.answer()
        return
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    picked = parts[2] if len(parts) > 2 else "all"
    if action == "open":
        await query.answer()
        text, keyboard = await board_for(update, context, clan)
        await query.message.reply_text(text, reply_markup=keyboard)
        return
    if action in ("on", "off"):
        if not await h.can_manage(update, context, clan):
            await query.answer(L.t("h.admin_only"), show_alert=True)
            return
        user = update.effective_user
        if action == "off":
            await store.recruit_stop(clan.alias)
        else:
            await publish_now(store, clan, await h.clan_settings(store, clan))
        await ledger.record(store, clan.alias, "apply", user.id if user else None,
                            user.first_name if user else None, action, now_utc())
        await query.answer(L.t("recruit.net.left" if action == "off" else "recruit.net.joined"),
                           show_alert=True)
    else:
        await query.answer()
    text, keyboard = await board_for(update, context, clan, picked if action == "f" else "all")
    await h.edit_or_log(query, text, keyboard, clan.alias)


def extra_handlers():
    return [CallbackQueryHandler(on_apply_callback, pattern=r"^rc:"),
            CallbackQueryHandler(on_decision_callback, pattern=r"^ap:"),
            CallbackQueryHandler(on_board_callback, pattern=r"^rb:")]


HANDLERS = {"apply": cmd_apply, "applications": cmd_applications, "recruit": cmd_recruit}
