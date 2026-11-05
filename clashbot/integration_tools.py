from io import BytesIO

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

from . import (bridge, discord_link, ics, integration_cards, integrations, media, news_feed,
               render, topics, twitch, webmenu)
from . import settings as settings_mod
from .util import now_utc

AREA = "integrations"
COMMANDS = [("calendar", ["calendario"]), ("twitch", []), ("discord", [])]
ICS_FILENAME = "clanboard.ics"


async def guard(update, context, manage=False):
    from . import handlers as h
    store, _ = h.services(context)
    clan = await h.clan_for(update, context)
    if not clan:
        return None, h.user_locale(update), None, "unlinked"
    L, _ = await h.clan_locale(store, clan)
    conf = await h.clan_settings(store, clan)
    if manage and not await h.can_manage(update, context, clan):
        return None, L, conf, "denied"
    return clan, L, conf, None


def refusal(L, reason):
    return L.t("int.only") if reason == "denied" else render.not_linked_view(L)


async def goldpass_end(store):
    return (await news_feed.season(store, None, now_utc())).get("end")


async def calendar_document(store, clan, conf, L):
    code = store.recruit_code(clan.alias)
    text = ics.build(L, code, clan.name, now_utc(), await goldpass_end(store),
                     await store.get_state(clan.alias, "war"))
    links = webmenu.links(await media.site_base(store), code, settings_mod.web_conf(conf))
    return text, links.get("ics")


async def cmd_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    clan, L, conf, why = await guard(update, context)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    text, url = await calendar_document(store, clan, conf, L)
    head, rest = media.caption(integration_cards.calendar_card(L, url))
    await update.effective_message.reply_document(
        document=BytesIO(text.encode()), filename=ICS_FILENAME, caption=head,
    )
    if rest:
        await update.effective_message.reply_text(rest)


async def on_integration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = (query.data or "").split(":")
    if len(parts) >= 3 and parts[1] == "dc":
        await on_discord_callback(update, context, parts)
        return
    await query.answer()


async def twitch_api(store):
    return twitch.TwitchApi(await store.get_secret("twitch_client_id"),
                            await store.get_secret("twitch_client_secret"))


async def own_tag(store, update, clan):
    members = await store.get_state(clan.alias, "members") or {}
    user = update.effective_user
    for link in (await store.links_by_user(user.id) if user else ()):
        if link.tag in members:
            return link.tag
    return None


async def save_channel(store, clan, conf, for_clan, tag, login):
    from . import handlers as h
    stored = dict(integrations.block(conf, "twitch"))
    members = dict(stored.get("members") or {})
    if for_clan:
        stored["channel"] = login
    elif login:
        members[tag] = login
        stored["members"] = members
    else:
        members.pop(tag, None)
        stored["members"] = members
    await h.save_settings(store, clan, {"twitch": stored})


async def cmd_twitch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    args = [part for part in (context.args or []) if part]
    for_clan = bool(args) and args[0].lower() == "clan"
    value = " ".join(args[1:] if for_clan else args).strip()
    clan, L, conf, why = await guard(update, context, manage=for_clan)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    api = await twitch_api(store)
    try:
        if not value:
            state = await store.get_state(clan.alias, "twitch") or {}
            await update.effective_message.reply_text(integration_cards.twitch_card(
                L, conf, await store.get_state(clan.alias, "members"),
                (state.get("live") or {}).keys(), api.ready()))
            return
        tag = None if for_clan else await own_tag(store, update, clan)
        if not for_clan and not tag:
            await update.effective_message.reply_text(L.t("twitch.not_linked"))
            return
        if value == "-":
            await save_channel(store, clan, conf, for_clan, tag, None)
            await update.effective_message.reply_text(L.t("twitch.removed"))
            return
        login = twitch.normalize_login(value)
        if not login:
            await update.effective_message.reply_text(L.t("twitch.invalid"))
            return
        if await api.channel_exists(store, login, now_utc()) is False:
            await update.effective_message.reply_text(L.t("twitch.unknown"))
            return
        await save_channel(store, clan, conf, for_clan, tag, login)
        note = "" if api.ready() else "\n\n" + L.t("twitch.not_ready")
        await update.effective_message.reply_text(L.t("twitch.saved") + note)
    finally:
        await api.close()


def hub_of(context):
    return getattr(context.bot_data.get("supervisor"), "discord", None)


async def privacy_ok(context):
    try:
        me = await context.bot.get_me()
    except TelegramError:
        return True
    return bool(getattr(me, "can_read_all_group_messages", True))


async def cmd_discord(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    clan, L, conf, why = await guard(update, context, manage=True)
    if not clan:
        await update.effective_message.reply_text(refusal(L, why))
        return
    cfg = bridge.config(await store.get_state(clan.alias, "discord"))
    await update.effective_message.reply_text(
        integration_cards.discord_card(L, cfg, await privacy_ok(context)),
        reply_markup=integration_cards.discord_keyboard(L, bool(cfg)))


async def start_link(update, context, L):
    if update.effective_chat.type != ChatType.PRIVATE:
        return L.t("discord.private_only")
    context.user_data["flow"] = {"kind": "discord", "step": "token"}
    return L.t("discord.ask_token")


async def on_token(update, context, flow):
    from . import handlers as h
    message = update.effective_message
    token = (message.text or "").strip()
    L = h.user_locale(update)
    try:
        await message.delete()
    except TelegramError:
        await message.reply_text(L.t("discord.token_warning"))
    clan, L, conf, why = await guard(update, context, manage=True)
    if not clan:
        context.user_data.pop("flow", None)
        await message.reply_text(refusal(L, why))
        return
    guilds, error = await discord_link.probe(token)
    if error == "token":
        await message.reply_text(L.t("discord.token_bad"))
        return
    if error:
        await message.reply_text(L.t("discord.error.network"))
        return
    if not guilds:
        await message.reply_text(L.t("discord.no_guild"))
        return
    flow.update(step="guild", token=token, guilds=guilds)
    await message.reply_text(L.t("discord.pick_guild"),
                             reply_markup=integration_cards.guilds_keyboard(guilds))


async def save_bridge(update, context, clan, flow, guild, channel):
    from . import handlers as h
    store, _ = h.services(context)
    await store.set_state(clan.alias, "discord", {
        "token": flow["token"], "guild_id": guild["id"], "guild_name": guild["name"],
        "channel_id": channel["id"], "channel_name": channel["name"],
        "by": update.effective_user.id, "ts": now_utc().timestamp()})
    context.user_data.pop("flow", None)
    hub = hub_of(context)
    if hub is not None:
        await hub.reconcile()


async def on_discord_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    from . import handlers as h
    store, _ = h.services(context)
    query = update.callback_query
    clan, L, conf, why = await guard(update, context, manage=True)
    if not clan:
        await query.answer(refusal(L, why))
        return
    flow = context.user_data.get("flow") or {}
    action = parts[2]
    if action == "link":
        await query.answer()
        await query.message.reply_text(await start_link(update, context, L))
        return
    if action == "off":
        await store.del_state(clan.alias, "discord")
        hub = hub_of(context)
        if hub is not None:
            await hub.reconcile()
        await query.answer(L.t("discord.removed"))
        await query.message.reply_text(integration_cards.discord_card(L, None),
                                       reply_markup=integration_cards.discord_keyboard(L, False))
        return
    if action == "g" and flow.get("guilds"):
        guild = next((g for g in flow["guilds"] if str(g["id"]) == parts[3]), None)
        if not guild or not guild["channels"]:
            await query.answer(L.t("discord.no_guild"))
            return
        flow.update(step="channel", guild=guild)
        await query.answer()
        await query.message.reply_text(L.t("discord.pick_channel"),
                                       reply_markup=integration_cards.channels_keyboard(guild["channels"]))
        return
    if action == "c" and flow.get("guild"):
        channel = next((c for c in flow["guild"]["channels"] if str(c["id"]) == parts[3]), None)
        if not channel:
            await query.answer(L.t("discord.pick_channel"))
            return
        await save_bridge(update, context, clan, flow, flow["guild"], channel)
        await query.answer(L.t("discord.saved"))
        cfg = bridge.config(await store.get_state(clan.alias, "discord"))
        await query.message.reply_text(integration_cards.discord_card(L, cfg, await privacy_ok(context)),
                                       reply_markup=integration_cards.discord_keyboard(L, True))
        return
    await query.answer()


async def on_group_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    hub = hub_of(context)
    message = update.effective_message
    if hub is None or message is None or not hub.clients:
        return
    store, _ = h.services(context)
    clan = await store.clan_by_chat(update.effective_chat.id, h.bot_alias(context))
    if not clan or clan.alias not in hub.clients:
        return
    if not bridge.from_telegram_ok(message, context.bot.id):
        return
    conf = await h.clan_settings(store, clan)
    where, _ = settings_mod.route(conf, integrations.BRIDGE_EVENT)
    if where == "off":
        return
    if not bridge.in_scope(getattr(message, "message_thread_id", None),
                           topics.thread_for(conf, integrations.BRIDGE_EVENT)):
        return
    L, _ = await h.clan_locale(store, clan)
    user = message.from_user
    name = " ".join(part for part in (user.first_name, user.last_name) if part) or user.username
    await hub.to_discord(clan, name, message.text or message.caption or "",
                         bridge.media_label(L, bridge.kinds_of(message)))


HANDLERS = {"calendar": cmd_calendar, "twitch": cmd_twitch, "discord": cmd_discord}


def extra_handlers():
    return [
        CallbackQueryHandler(on_integration_callback, pattern=r"^int:"),
        MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND
                       & (filters.TEXT | filters.CAPTION | filters.ATTACHMENT), on_group_text),
    ]
