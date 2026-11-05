import asyncio
import logging
import secrets
import time
from urllib.parse import quote

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      KeyboardButtonRequestManagedBot, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update)
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes, ManagedBotUpdatedHandler,
                          MessageHandler, filters)

from . import (ambassadors, base_library, base_videos, incidents, manager_alerts, metrics, news,
               ops, otp, platform, platform_ban, platform_guard, reasons, render, reports, roles,
               seats, settings as settings_mod, setup_ui, site_conf, source, support_desk, survey,
               usage, verify)
from .handlers import parse_lang
from .i18n import locale, resolve
from .ttl import GONE_TTL, MANAGED_TTL, MANAGER_TTL, ONBOARD_TTL, RETRY_TTL
from .util import normalize_tag, now_utc
from .web import ban

log = logging.getLogger("clashbot.console")

BRAND = "ClanBoard"
PAGE_SIZE = 20
BROADCAST_DELAY = 1.0
NAME_MAX = 64
USERNAME_MAX = 32
USERNAME_SUFFIX = "Bot"
NEWBOT_ARG = "newbot"
HOME = "home"
OTP_SEED = "otp_seed"
BOT_WRITES = ("stop", "start", "remove2")
MEDIA_ICON = "📺"
OFFICIAL_MARK = "⭐"
MEDIA_BACK = "panel:media"
PANEL_FLOWS = ("delegates", "media", incidents.FLOW, site_conf.FLOW)


def services(context):
    data = context.bot_data
    return data["store"], data["supervisor"]


def user_locale(update):
    user = update.effective_user
    return locale(resolve(user.language_code if user else None))


async def is_platform_owner(store, user):
    owner = await store.get_secret("owner_id")
    return bool(owner and user and str(user.id) == owner)


def is_private(update):
    chat = update.effective_chat
    return bool(chat) and chat.type == ChatType.PRIVATE


async def private_only(update):
    if is_private(update):
        return True
    await update.effective_message.reply_text(user_locale(update).t("console.private_only"))
    return False


async def owner_gate(update, context):
    store, _ = services(context)
    if await is_platform_owner(store, update.effective_user):
        return True
    await update.effective_message.reply_text(user_locale(update).t("console.owner_only"))
    return False


async def edit(query, text, keyboard=None):
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except TelegramError:
        pass


def otp_screen(context, screen):
    text, keyboard, ask = screen
    context.user_data.pop("otp", None)
    if ask:
        context.user_data["otp"] = True
    return text, keyboard


def panel_flow(context, name=None):
    for flow in PANEL_FLOWS:
        context.user_data.pop(flow, None)
    if name:
        context.user_data[name] = True


def seed_ref(query):
    message = getattr(query, "message", None)
    chat = getattr(message, "chat_id", None)
    number = getattr(message, "message_id", None)
    return (chat, number) if chat is not None and number is not None else None


async def hide_seed(context, store, L, uid):
    ref = context.user_data.pop(OTP_SEED, None)
    if not ref:
        return True
    text, keyboard, _ = await otp.page(store, L, uid)
    try:
        await context.bot.edit_message_text(text, chat_id=ref[0], message_id=ref[1],
                                            reply_markup=keyboard)
        return True
    except TelegramError:
        log.warning("la chiave dell'Authenticator non e stata coperta nel pannello")
    try:
        await context.bot.delete_message(chat_id=ref[0], message_id=ref[1])
        return True
    except TelegramError:
        log.warning("il messaggio con la chiave dell'Authenticator non e stato tolto")
    return False


def seed_note(L, text, hidden):
    return text if hidden else text + "\n" + L.t("otp.seed_left")


async def otp_open(update, context, store):
    lvl = await panel_level(update, context)
    if not lvl:
        return True
    user = update.effective_user
    return await otp.cleared(store, user.id, lvl == platform.OWNER, time.time())


async def otp_told(update, context, store, L):
    text, keyboard = otp_screen(context, await otp.wall(store, L, update.effective_user.id))
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def otp_shown(update, context, store, L, query):
    await query.answer()
    await edit(query, *otp_screen(context, await otp.wall(store, L, update.effective_user.id)))


def status_icon(alias, running):
    return "🟢" if alias in running else "🔴"


def reason_note(L, bot, running):
    if bot.alias in running or not bot.reason:
        return ""
    return " · " + render.reason_label(L, bot.reason)


def bot_line(L, bot, running, clans):
    return L.t(
        "console.bot_row",
        status=status_icon(bot.alias, running),
        username=render.esc(bot.username),
        n=clans,
        alias=bot.alias,
        reason=reason_note(L, bot, running),
    )


def locked(bot):
    return bot.reason == "disabled"


async def bots_card(L, store, supervisor, user_id):
    running = set(supervisor.running())
    mine = [b for b in await store.bots_by_owner(user_id) if b.kind != "console"]
    if not mine:
        return render.card("🤖", L.t("console.mybots_title"), L.t("console.mybots_empty")), None
    lines, rows = [], []
    for bot in mine:
        clans = await store.count_clans(bot.alias)
        lines.append(bot_line(L, bot, running, clans))
        toggle = None
        if bot.alias in running:
            toggle = InlineKeyboardButton(
                f"{L.t('console.btn_stop')} @{bot.username}", callback_data=f"b:stop:{bot.alias}"
            )
        elif not locked(bot):
            toggle = InlineKeyboardButton(
                f"{L.t('console.btn_start')} @{bot.username}", callback_data=f"b:start:{bot.alias}"
            )
        remove = InlineKeyboardButton(
            f"{L.t('console.btn_remove')} @{bot.username}", callback_data=f"b:remove:{bot.alias}"
        )
        rows.append([toggle, remove] if toggle else [remove])
    body = render.quote("\n".join(lines))
    return render.card("🤖", L.t("console.mybots_title"), body), InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    if list(context.args or []) == [NEWBOT_ARG]:
        context.args = []
        await cmd_newbot(update, context)
        return
    store, _ = services(context)
    code = ambassadors.code_of(context.args[0] if context.args else None)
    if code:
        await ambassadors.remember(store, update.effective_user.id, code)
    L = user_locale(update)
    await update.effective_message.reply_text(*await home_screen(store, L, update.effective_user))
    if await platform.bind(store, update.effective_user, time.time()):
        await update.effective_message.reply_text(
            render.card(platform.ICON, BRAND, L.t("console.delegate.welcome")))


async def home_screen(store, L, user):
    body = L.t("console.start") + "\n\n" + render.quote(L.t("console.attribution")) + "\n" + render.quote(source.notice(L))
    rows = [[InlineKeyboardButton(L.t("console.btn_create"), callback_data=f"{HOME}:new")],
            [InlineKeyboardButton(L.t("console.btn_clans"), callback_data=f"{HOME}:clans")]]
    if await is_platform_owner(store, user):
        rows.append([InlineKeyboardButton(L.t("ops.btn"), callback_data="panel:ops")])
    return render.card("🤖", BRAND, body), InlineKeyboardMarkup(rows)


async def on_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_private(update):
        return
    store, _ = services(context)
    L = user_locale(update)
    action = (query.data or "").partition(":")[2]
    if action == "new":
        await cmd_newbot(update, context)
    elif action == "clans":
        back = InlineKeyboardMarkup([[
            InlineKeyboardButton(L.t("console.btn_back"), callback_data=f"{HOME}:back")]])
        await edit(query, render.served_card(L, await store.recruit_board(limit=PAGE_SIZE)), back)
    elif action == "back":
        await edit(query, *await home_screen(store, L, update.effective_user))


def suggestions(clan_name):
    name = (clan_name or "").strip()
    if not name:
        return None, None
    core = "".join(c for c in name if c.isascii() and c.isalnum())
    while core and not core[0].isalpha():
        core = core[1:]
    if len(core) < 2:
        return name[:NAME_MAX], generic_username()
    return name[:NAME_MAX], core[:USERNAME_MAX - len(USERNAME_SUFFIX)] + USERNAME_SUFFIX


def generic_username():
    return f"{BRAND}{secrets.randbelow(9000) + 1000}{USERNAME_SUFFIX}"


def creation_link(manager, username, name):
    url = f"https://t.me/newbot/{manager}/{username}"
    return f"{url}?name={quote(name, safe='')}" if name else url


async def clan_data(context, tag):
    coc = context.bot_data.get("coc")
    if not coc:
        return None
    data, _ = await coc.clan(tag)
    return data or None


async def can_manage(context, fresh=False):
    now = time.monotonic()
    cached = context.bot_data.get("can_manage")
    if cached and not fresh and now - cached[0] < MANAGER_TTL:
        return cached[1]
    try:
        me = await context.bot.get_me()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("permesso di creare bot non verificato (%s)", type(e).__name__)
        return None if fresh else (cached[1] if cached else True)
    context.bot_data["can_manage"] = (now, bool(getattr(me, "can_manage_bots", None)))
    return context.bot_data["can_manage"][1]


async def newbot_off(L, reply, user_id, platform=False):
    key = "console.manager_off" if platform else "console.newbot_unavailable"
    try:
        await reply(L.t(key), reply_markup=ReplyKeyboardRemove())
    except TelegramError:
        log.warning("utente %s non raggiungibile", user_id)


async def offer_link(context, L, reply, username, name):
    try:
        url = creation_link(context.bot.username, username, name)
        button = InlineKeyboardButton(L.t("console.btn_create_link"), url=url)
        hint = L.t("console.newbot_link_hint", button=L.t("console.btn_create"))
        await reply(hint, reply_markup=InlineKeyboardMarkup([[button]]))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("link di creazione non inviato (%s)", type(e).__name__)


async def cmd_newbot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    L = user_locale(update)
    store, _ = services(context)
    user = update.effective_user
    reply = update.effective_message.reply_text
    context.user_data.pop("newbot", None)
    platform = await is_platform_owner(store, user)
    if not platform and await banned(store, user.id):
        await reply(L.t("console.newbot_banned"), reply_markup=ReplyKeyboardRemove())
        return
    if not await can_manage(context):
        log.warning("console senza can_manage_bots: /newbot non può creare")
        await newbot_off(L, reply, user.id, platform)
        return
    raw = " ".join(context.args or []).strip()
    if not platform and not await verify.terms_day(store, user.id):
        context.user_data["newbot"] = {"step": verify.TERMS, "args": raw}
        await ask_terms(store, L, reply)
        return
    await newbot_from(update, context, L, raw)


async def ask_terms(store, L, reply):
    text, keyboard = await support_desk.terms_screen(store, L)
    await reply(text, reply_markup=keyboard)


async def newbot_from(update, context, L, raw):
    reply = update.effective_message.reply_text
    if not raw:
        context.user_data["newbot"] = {"step": "tag"}
        await reply(render.onboard_ask_clan(L), reply_markup=ReplyKeyboardRemove())
        return
    tag = normalize_tag(raw)
    if not tag:
        await reply(L.t("console.newbot_bad_tag"), reply_markup=ReplyKeyboardRemove())
        return
    await open_gate(update, context, L, tag)


async def open_gate(update, context, L, tag):
    store, _ = services(context)
    user = update.effective_user
    reply = update.effective_message.reply_text
    data = await clan_data(context, tag)
    if not data:
        context.user_data.pop("newbot", None)
        await reply(L.t("console.newbot_bad_tag"), reply_markup=ReplyKeyboardRemove())
        return
    platform = await is_platform_owner(store, user)
    roles = verify.clan_roles(data)
    if not platform and await holds_clan(store, await store.bot_for_tag(tag), roles):
        context.user_data.pop("newbot", None)
        await reply(L.t("console.newbot_clan_taken"), reply_markup=ReplyKeyboardRemove())
        return
    flow = {"tag": tag, "clan": data.get("name"), "country": (data.get("location") or {}).get("countryCode")}
    if not platform and not await verify.linked_leader(store, user.id, roles):
        flow.update(step="player", roles=roles)
        context.user_data["newbot"] = flow
        await reply(render.onboard_ask_player(L, flow["clan"]))
        return
    await offer_creation(update, context, L, flow)


async def offer_creation(update, context, L, flow):
    user = update.effective_user
    reply = update.effective_message.reply_text
    ready = {
        "request_id": secrets.randbelow(2_000_000_000) + 1,
        "tag": flow["tag"],
        "clan": flow["clan"],
        "country": flow.get("country"),
    }
    context.user_data["newbot"] = ready
    suggested_name, suggested_username = suggestions(ready["clan"])
    button = KeyboardButton(
        L.t("console.btn_create"),
        request_managed_bot=KeyboardButtonRequestManagedBot(
            ready["request_id"], suggested_name=suggested_name, suggested_username=suggested_username
        ),
    )
    keyboard = ReplyKeyboardMarkup(
        [[button]], resize_keyboard=True, one_time_keyboard=True, is_persistent=False
    )
    body = render.card("🤖", BRAND, L.t("console.newbot_ask_native"))
    try:
        await reply(body, reply_markup=keyboard)
    except TelegramError as e:
        log.warning("finestra di creazione rifiutata (%s)", type(e).__name__)
        context.user_data.pop("newbot", None)
        await newbot_off(L, reply, user.id)
        return
    await offer_link(context, L, reply, suggested_username or generic_username(), suggested_name)


async def on_delegate_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("delegates") or not is_private(update):
        return False
    store, _ = services(context)
    if not await is_platform_owner(store, update.effective_user):
        context.user_data.pop("delegates", None)
        return False
    raw = (update.effective_message.text or "").strip()
    if platform.clean(raw):
        context.user_data.pop("delegates", None)
    L = await platform_guard.owner_locale(store)
    text, keyboard = await platform.act(store, L, "deladd", raw, time.time())
    await update.effective_message.reply_text(text, reply_markup=keyboard)
    return True


async def on_media_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("media") or not is_private(update):
        return False
    store, _ = services(context)
    lvl = await panel_level(update, context)
    if not lvl:
        context.user_data.pop("media", None)
        return False
    L = await panel_locale(store, update, lvl)
    row = await base_videos.found_channel(store, update.effective_message.text)
    if not row:
        text, keyboard = media_ask(L, bad=True)
        await update.effective_message.reply_text(text, reply_markup=keyboard)
        return True
    context.user_data.pop("media", None)
    await base_videos.add_channel(store, row)
    text, keyboard = await media_page(store, L)
    await update.effective_message.reply_text(text, reply_markup=keyboard)
    return True


async def incident_screen(store, L, context, action, rest, full):
    arg = ":".join(rest)
    kind = incidents.picked(arg) if action == "incpick" else None
    panel_flow(context)
    if kind:
        context.user_data[incidents.FLOW] = kind
    return await incidents.act(store, L, action, arg, now_utc(), full)


async def on_incident_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = context.user_data.get(incidents.FLOW)
    if not incidents.picked(kind) or not is_private(update):
        return False
    store, _ = services(context)
    user = update.effective_user
    if await panel_level(update, context) != platform.OWNER:
        context.user_data.pop(incidents.FLOW, None)
        return False
    L = await platform_guard.owner_locale(store)
    context.user_data.pop(incidents.FLOW, None)
    if not await otp.cleared(store, user.id, True, time.time()):
        text, keyboard = otp_screen(context, await otp.wall(store, L, user.id))
    else:
        await incidents.add(store, kind, update.effective_message.text, now_utc())
        text, keyboard = await incidents.act(store, L, "incidents", "", now_utc())
    await update.effective_message.reply_text(text, reply_markup=keyboard)
    return True


async def site_answer(context, store, L, user, name, raw):
    if not await otp.cleared(store, user.id, True, time.time()):
        context.user_data.pop(site_conf.FLOW, None)
        return otp_screen(context, await otp.wall(store, L, user.id))
    value = await site_conf.accepted(store, name, raw)
    if not value:
        return site_conf.ask(L, name, bad=True)
    context.user_data.pop(site_conf.FLOW, None)
    await site_conf.write(store, name, value)
    return site_conf.page(L, await site_conf.read(store))


async def on_site_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get(site_conf.FLOW)
    if not name or not is_private(update):
        return False
    store, _ = services(context)
    if name not in site_conf.FIELDS or await panel_level(update, context) != platform.OWNER:
        context.user_data.pop(site_conf.FLOW, None)
        return False
    L = await platform_guard.owner_locale(store)
    text, keyboard = await site_answer(context, store, L, update.effective_user, name,
                                       update.effective_message.text)
    await update.effective_message.reply_text(text, reply_markup=keyboard)
    return True


async def site_screen(store, L, context, action, arg):
    panel_flow(context)
    name = site_conf.asked(action, arg)
    if name:
        context.user_data[site_conf.FLOW] = name
    return await site_conf.act(store, L, action, arg)


async def on_otp_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("otp") or not is_private(update):
        return False
    store, _ = services(context)
    lvl = await panel_level(update, context)
    if not lvl:
        context.user_data.pop("otp", None)
        return False
    L = await panel_locale(store, update, lvl)
    uid = update.effective_user.id
    checked = await otp.check(store, L, uid, update.effective_message.text, time.time())
    hidden = True
    if not await store.kv_get(otp.pending_of(uid)):
        hidden = await hide_seed(context, store, L, uid)
    text, keyboard = otp_screen(context, checked)
    await update.effective_message.reply_text(seed_note(L, text, hidden), reply_markup=keyboard)
    return True


async def on_newbot_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (await on_otp_text(update, context) or await on_delegate_text(update, context)
            or await on_media_text(update, context) or await on_incident_text(update, context)
            or await on_site_text(update, context)):
        return
    flow = context.user_data.get("newbot")
    if not flow or not flow.get("step") or not is_private(update):
        return
    L = user_locale(update)
    store, _ = services(context)
    if flow["step"] == verify.TERMS:
        await ask_terms(store, L, update.effective_message.reply_text)
        return
    coc = context.bot_data.get("coc")
    reply = update.effective_message.reply_text
    text = (update.effective_message.text or "").strip()
    if flow["step"] == "tag":
        tag = normalize_tag(text)
        if not tag:
            await reply(L.t("console.newbot_bad_tag"))
            return
        await open_gate(update, context, L, tag)
        return
    if flow["step"] == "player":
        player, error = await verify.check_player(coc, flow["roles"], text)
        if error == "not_leader":
            await reply(L.t("h.onboard_not_leader", clan=render.esc(flow["clan"])))
            return
        if error:
            await reply(render.api_error(L, error, normalize_tag(text)))
            return
        flow.update(step="token", player=player["tag"], player_name=player["name"])
        await reply(render.onboard_ask_token(L, player["name"]))
        return
    error = await verify.check_token(coc, flow["player"], text)
    if error == "token_invalid":
        await reply(L.t("h.token_invalid"))
        return
    if error:
        await reply(render.api_error(L, error, flow["player"]))
        return
    refused = await verify.link_verified(store, update.effective_user.id, flow["player"],
                                         flow["player_name"],
                                         parse_lang(update.effective_user.language_code))
    if refused == reasons.TERMS:
        await ask_terms(store, L, reply)
        return
    if refused:
        await reply(L.t("h.link_banned"))
        return
    await offer_creation(update, context, L, flow)


async def on_terms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    L = user_locale(update)
    await query.answer()
    user = update.effective_user
    if query.data != support_desk.TERMS_DATA or not user or not is_private(update):
        return
    await verify.accept_terms(store, user.id, now_utc())
    await edit(query, L.t("terms.done"))
    flow = context.user_data.get("newbot") or {}
    if flow.get("step") != verify.TERMS:
        return
    await newbot_from(update, context, L, str(flow.get("args") or ""))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    hidden = True
    if context.user_data.get(OTP_SEED):
        store, _ = services(context)
        lvl = await panel_level(update, context)
        hidden = await hide_seed(context, store, await panel_locale(store, update, lvl),
                                 update.effective_user.id)
    context.user_data.pop("newbot", None)
    context.user_data.pop("broadcast", None)
    context.user_data.pop("setup", None)
    context.user_data.pop("otp", None)
    panel_flow(context)
    L = user_locale(update)
    await update.effective_message.reply_text(seed_note(L, L.t("console.cancelled"), hidden),
                                              reply_markup=ReplyKeyboardRemove())


async def find_bot(store, bot_id):
    return next((b for b in await store.bots() if b.bot_id == bot_id), None)


async def tell(context, user_id, reply, text, keyboard=None):
    if reply:
        await reply(text, reply_markup=keyboard)
        return
    try:
        await context.bot.send_message(user_id, text, reply_markup=keyboard)
    except TelegramError:
        log.warning("utente %s non raggiungibile", user_id)


async def forget(store, key):
    try:
        await store.kv_del(key)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("segno %s non tolto", key)


async def remember(store, key, value, ttl):
    try:
        await store.kv_set(key, value, ttl=ttl)
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("segno %s non salvato", key)
        return False


async def may_register(context, store, bot_id, owner_id=None):
    tomb = await store.kv_get(f"gone:{bot_id}")
    if not tomb:
        return True
    if owner_id is not None and tomb.get("user_id") not in (None, owner_id):
        log.info("bot %s: lapide di un altro proprietario, non lo registro", bot_id)
        return False
    if not context.user_data.get("newbot"):
        log.info("bot %s: tolto da ClanBoard, non lo registro da solo", bot_id)
        return False
    await store.kv_del(f"gone:{bot_id}")
    return True


async def banned(store, user_id):
    villages = [link.tag for link in await store.links_by_user(user_id) or ()]
    return await platform_ban.refuses(store, user_id, villages)


class RosterUnread(Exception):
    pass


async def holds_clan(store, alias, roles=None):
    if not alias:
        return False
    if await store.count_clans(alias):
        return True
    if roles is None:
        return False
    bot = await store.bot_by_alias(alias)
    return not bot or bool(await verify.linked_leader(store, bot.owner_id, roles))


async def creation_refused(context, L, owner, flow):
    store, _ = services(context)
    tag = flow.get("tag")
    if not tag:
        return L.t("console.newbot_limit")
    alias = await store.bot_for_tag(tag)
    if await holds_clan(store, alias):
        return L.t("console.newbot_clan_taken")
    coc = context.bot_data.get("coc")
    data, error = await coc.clan(tag) if coc else (None, None)
    if not data:
        raise RosterUnread(error, tag)
    roles = verify.clan_roles(data)
    if await holds_clan(store, alias, roles):
        return L.t("console.newbot_clan_taken")
    if not await verify.linked_leader(store, owner.id, roles):
        return L.t("h.onboard_not_leader", clan=render.esc(data.get("name") or tag))
    return None


async def register_managed(context, owner, bot_id, username, reply=None, retried=False):
    if not owner or not bot_id:
        return
    store, _ = services(context)
    if await banned(store, owner.id):
        L = locale(resolve(getattr(owner, "language_code", None)))
        await tell(context, owner.id, reply, L.t("console.newbot_banned"), ReplyKeyboardRemove())
        return
    if await store.kv_get(f"managed:{bot_id}"):
        return
    known = await find_bot(store, bot_id)
    if not known and not await may_register(context, store, bot_id, owner.id):
        return
    L = locale(resolve(getattr(owner, "language_code", None)))
    try:
        token = await context.bot.get_managed_bot_token(user_id=bot_id)
    except TelegramError:
        log.warning("bot %s: Telegram non consegna il token", bot_id)
        await remember(store, f"managed:{bot_id}", {"bot_id": bot_id}, MANAGED_TTL)
        await offer_retry(context, L, owner, bot_id, username, reply)
        return
    name = username or (known.username if known else "?")
    if known:
        await renew_managed(context, L, owner, known, token, name, retried)
        return
    await remember(store, f"managed:{bot_id}", {"bot_id": bot_id}, MANAGED_TTL)
    try:
        await create_managed(context, L, owner, bot_id, token, name, reply)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("bot %s: registrazione interrotta (%s)", bot_id, type(e).__name__)
        await forget(store, f"managed:{bot_id}")
        why = render.api_error(L, *e.args) if isinstance(e, RosterUnread) else None
        await offer_retry(context, L, owner, bot_id, name, reply, why)


async def offer_retry(context, L, owner, bot_id, username, reply, why=None):
    store, _ = services(context)
    if await store.kv_get(f"retry:{bot_id}"):
        return
    saved = await remember(store, f"retry:{bot_id}", {"user_id": owner.id, "username": username}, RETRY_TTL)
    safe = render.esc(username or "?")
    card = why or render.card("⚠️", BRAND, L.t("console.newbot_failed", username=safe))
    await tell(context, owner.id, reply, card, ReplyKeyboardRemove())
    if not saved:
        return
    button = InlineKeyboardButton(L.t("console.btn_retry"), callback_data=f"b:retry:{bot_id}")
    await tell(context, owner.id, reply, L.t("console.newbot_retry"), InlineKeyboardMarkup([[button]]))


async def retry_managed(update, context, L, raw):
    store, _ = services(context)
    query, user = update.callback_query, update.effective_user
    pending = await store.kv_get(f"retry:{raw}") if raw.isdigit() else None
    if not pending:
        await query.answer(L.t("console.retry_expired"), show_alert=True)
        return
    if pending.get("user_id") != user.id:
        await query.answer(L.t("console.owner_only"), show_alert=True)
        return
    await query.answer()
    await store.kv_del(f"retry:{raw}")
    await store.kv_del(f"managed:{raw}")
    await register_managed(context, user, int(raw), pending.get("username"), retried=True)


async def create_managed(context, L, owner, bot_id, token, username, reply):
    store, supervisor = services(context)
    platform = await is_platform_owner(store, owner)
    if not platform and not await verify.terms_day(store, owner.id):
        await forget(store, f"managed:{bot_id}")
        text, keyboard = await support_desk.terms_screen(store, L)
        await tell(context, owner.id, reply, text, keyboard)
        return
    flow = context.user_data.get("newbot") or {}
    refused = None if platform else await creation_refused(context, L, owner, flow)
    if refused:
        context.user_data.pop("newbot", None)
        await tell(context, owner.id, reply, refused, ReplyKeyboardRemove())
        return
    old = None if platform else await store.bot_for_tag(flow.get("tag"))
    try:
        bot = await store.add_bot(owner.id, token, username, bot_id, trusted=True, allow_disabled=platform,
                                  clan_tag=flow.get("tag"), replaces=old)
    except ValueError:
        context.user_data.pop("newbot", None)
        log.warning("bot %s: registrazione rifiutata", bot_id)
        await tell(context, owner.id, reply, L.t("console.newbot_disabled"), ReplyKeyboardRemove())
        return
    context.user_data.pop("newbot", None)
    if old:
        log.info("%s: il clan passa al capo di adesso, il bot resta senza clan", old)
    safe = render.esc(username)
    if not await supervisor.start_bot(bot.alias):
        body = L.t("console.newbot_not_started", username=safe, alias=bot.alias)
        await tell(context, owner.id, reply, body, ReplyKeyboardRemove())
        return
    url, code = await group_link(store, flow, owner, bot, username)
    done = render.card("🤖", BRAND, L.t("console.newbot_done_native", username=safe, alias=bot.alias))
    await tell(context, owner.id, reply, done, ReplyKeyboardRemove())
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(L.t("h.btn_add_group"), url=url)]])
    await tell(context, owner.id, reply, L.t("console.newbot_add_group", username=safe), keyboard)
    if code:
        await start_setup(context, L, owner, code, flow, reply)


async def group_link(store, flow, owner, bot, username):
    tag = flow.get("tag")
    if not tag:
        return f"https://t.me/{username}?startgroup=true", None
    code = secrets.token_urlsafe(12)
    pending = {"tag": tag, "name": flow.get("clan"), "user_id": owner.id, "bot_alias": bot.alias}
    if not await remember(store, f"ob:{code}", pending, ONBOARD_TTL):
        return f"https://t.me/{username}?startgroup=true", None
    return f"https://t.me/{username}?startgroup={code}", code


async def save_setup(store, code, state):
    pending = await store.kv_get(f"ob:{code}")
    if not pending:
        return False
    pending["setup"] = state
    return await remember(store, f"ob:{code}", pending, ONBOARD_TTL)


async def start_setup(context, L, owner, code, flow, reply):
    store, _ = services(context)
    conf = settings_mod.effective(None, {"location": {"countryCode": flow.get("country")}})
    state = setup_ui.start(code, owner.id, conf["lang"], conf["tz"])
    context.user_data["setup"] = state
    await save_setup(store, code, state)
    text, keyboard = setup_ui.screen(L, state, state["step"])
    await tell(context, owner.id, reply, text, keyboard)


async def on_setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    L = user_locale(update)
    user = update.effective_user
    data = query.data or ""
    code = setup_ui.code_of(data)
    state = context.user_data.get("setup")
    if not state or state.get("code") != code:
        pending = await store.kv_get(f"ob:{code}") if code else None
        state = (pending or {}).get("setup")
    if not state or state.get("user_id") != (user.id if user else None):
        await query.answer(L.t("setup.expired"), show_alert=True)
        return
    before = state.get("step")
    state, step = setup_ui.handle(state, data)
    blocked = step == "mentions" and before == "mentions" and state.get("mentions") not in settings_mod.MENTIONS
    context.user_data["setup"] = state
    await save_setup(store, code, state)
    await query.answer(L.t("setup.mentions.required") if blocked else None, show_alert=blocked)
    text, keyboard = setup_ui.screen(L, state, step)
    await edit(query, text, keyboard)


async def renew_managed(context, L, owner, known, token, username, retried=False):
    store, supervisor = services(context)
    previous, stopped = known.owner_id, known.reason == "owner_stopped"
    if previous == owner.id and await store.bot_token(known.alias) == token:
        if retried:
            if known.active and known.alias not in supervisor.running():
                await supervisor.start_bot(known.alias)
            body = L.t("console.newbot_done_native", username=render.esc(username), alias=known.alias)
            await tell(context, owner.id, None, render.card("✅", BRAND, body))
        return
    platform = await is_platform_owner(store, owner)
    try:
        bot = await store.add_bot(
            owner.id, token, username, known.bot_id, trusted=True, allow_disabled=platform
        )
    except ValueError:
        log.warning("%s: aggiornamento rifiutato", known.alias)
        return
    if stopped:
        await store.set_bot_active(bot.alias, False, "owner_stopped")
        log.info("%s: token aggiornato, resta fermo come vuole il proprietario", bot.alias)
        return
    await supervisor.restart_bot(bot.alias)
    safe = render.esc(username)
    body = L.t("console.bot_token_changed", username=safe, alias=bot.alias)
    await tell(context, owner.id, None, render.card("🔁", BRAND, body))
    if previous != owner.id:
        P = locale(resolve(None))
        old = P.t("console.bot_token_changed", username=safe, alias=bot.alias)
        await tell(context, previous, None, render.card("🔁", BRAND, old))


async def on_managed_created(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    created = getattr(message, "managed_bot_created", None) if message else None
    if not created or not created.bot:
        return
    bot_user = created.bot
    await register_managed(context, update.effective_user, bot_user.id, bot_user.username, message.reply_text)


async def on_managed_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event = update.managed_bot
    if not event or not event.bot:
        return
    await register_managed(context, event.user, event.bot.id, event.bot.username)


async def cmd_mybots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    store, supervisor = services(context)
    text, keyboard = await bots_card(user_locale(update), store, supervisor, update.effective_user.id)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    store, _ = services(context)
    url = await store.get_secret("support_url")
    code = await store.get_secret("creator_code")
    twitch = await store.get_secret("twitch_url")
    where = await store.get_secret(source.SECRET)
    channel = await store.get_secret("channel_url")
    await update.effective_message.reply_text(
        render.support_card(user_locale(update), url, code, twitch, where, channel))


async def may_touch(update, context, store, bot, action):
    user = update.effective_user
    if await is_platform_owner(store, user):
        return bot.owner_id == user.id or platform.held(context.user_data, bot.alias)
    if action not in BOT_WRITES:
        return bot.owner_id == user.id
    return await roles.keeps_bot(store, context.bot_data.get("coc"), bot, user.id)


def why_screen(L, alias):
    rows = [[InlineKeyboardButton(L.t("platform.reason." + reason),
                                  callback_data=f"b:open:{alias}:{reason}")]
            for reason in platform.OPEN_REASONS]
    rows.append([InlineKeyboardButton(L.t("console.btn_back"), callback_data="b:back")])
    body = render.card(platform.ICON, L.t("console.mybots_title"), L.t("console.open_ask"))
    return body, InlineKeyboardMarkup(rows)


async def open_for(update, context, store, L, query, bot, reason):
    if not await is_platform_owner(store, update.effective_user):
        await query.answer(L.t("console.owner_only"), show_alert=True)
        return
    await query.answer()
    if reason not in platform.OPEN_REASONS:
        await edit(query, *why_screen(L, bot.alias))
        return
    if not await platform.open_bot(store, bot.alias, update.effective_user.id, reason, now_utc()):
        await edit(query, *why_screen(L, bot.alias))
        return
    platform.hold(context.user_data, bot.alias)
    note = L.t("console.opened", reason=L.t("platform.reason." + reason))
    await edit(query, render.card(platform.ICON, L.t("console.mybots_title"), note))


async def allow_bot(update, context, store, L, query, bot, action):
    if not await may_touch(update, context, store, bot, action):
        if await is_platform_owner(store, update.effective_user):
            await query.answer()
            await edit(query, *why_screen(L, bot.alias))
            return False
        await query.answer(L.t("console.owner_only"), show_alert=True)
        return False
    if action in BOT_WRITES and not await otp_open(update, context, store):
        await otp_shown(update, context, store, L, query)
        return False
    platform.spend(context.user_data, bot.alias)
    return True


async def on_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, supervisor = services(context)
    L = user_locale(update)
    user = update.effective_user
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "back":
        await query.answer()
        text, keyboard = await bots_card(L, store, supervisor, user.id)
        await edit(query, text, keyboard)
        return
    if action == "retry":
        await retry_managed(update, context, L, parts[2] if len(parts) > 2 else "")
        return
    alias = parts[2] if len(parts) > 2 else ""
    bot = await store.bot_by_alias(alias)
    if not bot:
        await query.answer(L.t("console.not_found", alias=alias), show_alert=True)
        return
    if action == "open":
        await open_for(update, context, store, L, query, bot, parts[3] if len(parts) > 3 else "")
        return
    if not await allow_bot(update, context, store, L, query, bot, action):
        return
    if action == "remove":
        await query.answer()
        clans = await store.count_clans(alias)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(L.t("console.btn_remove"), callback_data=f"b:remove2:{alias}"),
            InlineKeyboardButton(L.t("console.btn_back"), callback_data="b:back"),
        ]])
        body = L.t("console.remove_confirm", username=render.esc(bot.username), n=clans)
        await edit(query, render.card("⚠️", L.t("console.mybots_title"), body), keyboard)
        return
    if action == "remove2":
        await supervisor.stop_bot(alias)
        await store.remove_bot(alias)
        await remember(store, f"gone:{bot.bot_id}", {"user_id": bot.owner_id}, GONE_TTL)
        await query.answer()
        body = L.t("console.removed", username=render.esc(bot.username))
        await edit(query, render.card("🤖", L.t("console.mybots_title"), body))
        return
    if action == "stop":
        await supervisor.stop_bot(alias, "owner_stopped")
        await query.answer(L.t("console.stopped", username=bot.username))
    elif action == "start":
        if locked(bot) and not await is_platform_owner(store, user):
            await query.answer(L.t("console.reason.disabled"), show_alert=True)
            return
        await store.set_bot_active(alias, True)
        await supervisor.start_bot(alias)
        await query.answer(L.t("console.started", username=bot.username))
    else:
        await query.answer()
        return
    text, keyboard = await bots_card(L, store, supervisor, bot.owner_id)
    await edit(query, text, keyboard)


async def bots_page(L, store, supervisor, page=1):
    every = await store.bots()
    pages = max(1, (len(every) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    running = set(supervisor.running())
    lines = []
    for bot in every[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]:
        clans = await store.count_clans(bot.alias)
        lines.append(bot_line(L, bot, running, clans) + L.t("console.bot_owner", id=bot.owner_id))
    body = render.quote("\n".join(lines)) if lines else L.t("console.mybots_empty")
    title = L.t("console.bots_title", n=len(every))
    return render.card("🛰", title, body, subtitle=f"{page}/{pages}")


async def cmd_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update) or not await owner_gate(update, context):
        return
    store, supervisor = services(context)
    args = context.args or []
    page = int(args[0]) if args and args[0].isdigit() and int(args[0]) > 0 else 1
    await update.effective_message.reply_text(await bots_page(user_locale(update), store, supervisor, page))


def wanted_uid(args):
    raw = str(args[0]) if args else ""
    return int(raw) if raw.lstrip("-").isdigit() else None


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update) or not await owner_gate(update, context):
        return
    store, _ = services(context)
    L = user_locale(update)
    args = context.args or []
    uid = wanted_uid(args)
    if uid is None:
        await update.effective_message.reply_text(L.t("console.usage", usage="/ban 123456789 #TAG"))
        return
    if not await otp_open(update, context, store):
        await otp_told(update, context, store, L)
        return
    tags = list(args[1:]) + [link.tag for link in await store.links_by_user(uid)]
    await platform_ban.ban(store, uid, tags, time.time())
    rows = (await platform_ban.load(store))[platform_ban.ROWS]
    n = len(rows.get(str(uid), {}).get(platform_ban.TAGS) or [])
    await update.effective_message.reply_text(L.t("console.banned", uid=uid, n=n))


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update) or not await owner_gate(update, context):
        return
    store, _ = services(context)
    L = user_locale(update)
    uid = wanted_uid(context.args or [])
    if uid is None:
        await update.effective_message.reply_text(L.t("console.usage", usage="/unban 123456789"))
        return
    if not await otp_open(update, context, store):
        await otp_told(update, context, store, L)
        return
    if not await platform_ban.lift(store, uid):
        await update.effective_message.reply_text(L.t("console.ban_none", uid=uid))
        return
    await update.effective_message.reply_text(L.t("console.unbanned", uid=uid))


async def cmd_disable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update) or not await owner_gate(update, context):
        return
    store, supervisor = services(context)
    L = user_locale(update)
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(L.t("console.usage", usage="/disable bot-xxxxxx"))
        return
    alias = args[0]
    bot = await store.bot_by_alias(alias)
    if not bot:
        await update.effective_message.reply_text(L.t("console.not_found", alias=alias))
        return
    if not await otp_open(update, context, store):
        await otp_told(update, context, store, L)
        return
    note = " ".join(args[1:]).strip()
    await store.set_bot_active(alias, False, "disabled")
    await supervisor.stop_bot(alias)
    reason = render.esc(note) if note else L.t("console.reason.disabled")
    body = L.t("console.disabled_notice", username=render.esc(bot.username), reason=reason)
    try:
        await context.bot.send_message(bot.owner_id, render.card("⛔", BRAND, body))
    except TelegramError:
        log.warning("%s: proprietario non raggiungibile", alias)
    await update.effective_message.reply_text(L.t("console.disabled", username=bot.username, alias=alias))


async def cmd_enable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update) or not await owner_gate(update, context):
        return
    store, supervisor = services(context)
    L = user_locale(update)
    args = context.args or []
    if not args:
        await update.effective_message.reply_text(L.t("console.usage", usage="/enable bot-xxxxxx"))
        return
    alias = args[0]
    bot = await store.bot_by_alias(alias)
    if not bot:
        await update.effective_message.reply_text(L.t("console.not_found", alias=alias))
        return
    if not await otp_open(update, context, store):
        await otp_told(update, context, store, L)
        return
    await store.set_bot_active(alias, True)
    await supervisor.start_bot(alias)
    await update.effective_message.reply_text(L.t("console.enabled", username=bot.username, alias=alias))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update) or not await owner_gate(update, context):
        return
    store, supervisor = services(context)
    L = user_locale(update)
    body = usage.snapshot_text(L, await usage.snapshot(store, supervisor, now_utc()))
    coc = context.bot_data.get("coc")
    keys = coc.key_report() if coc else {"total": 0, "dead": {}}
    body += "\n" + L.t("console.stats_keys", alive=keys["total"] - len(keys["dead"]), total=keys["total"])
    prova = await manager_alerts.last(store, "restore")
    if not prova:
        body += "\n" + L.t("console.stats_restore_never")
    else:
        when = L.ago(manager_alerts.moment(prova.get("at")))
        body += "\n" + L.t("console.stats_restore_ok" if prova.get("ok") else "console.stats_restore_ko", when=when)
    active = await can_manage(context, fresh=True)
    if active is None:
        body += "\n" + L.t("console.stats_creation_unknown")
    else:
        body += "\n" + L.t("console.stats_creation_on" if active else "console.stats_creation_off")
    await update.effective_message.reply_text(render.card("📊", BRAND, render.quote(body)))


def summed(counters):
    return sum(int(n) for n in (counters or {}).values())


def freshest(now_stats, stats, field):
    value = now_stats.get(field)
    return stats.get(field) if value is None else value


def panel_keyboard(L, lvl=platform.OWNER):
    refresh = InlineKeyboardButton(L.t("menu.refresh"), callback_data="panel:refresh")
    signals = InlineKeyboardButton(L.t("panel.reports.btn"), callback_data="panel:reports")
    numbers = InlineKeyboardButton(L.t("panel.usage.btn"), callback_data="panel:usage")
    security = InlineKeyboardButton(L.t("otp.btn"), callback_data="panel:otp")
    bases = InlineKeyboardButton(L.t("panel.media.btn"), callback_data=MEDIA_BACK)
    if lvl != platform.OWNER:
        return InlineKeyboardMarkup([[refresh, signals], [numbers, security, bases]])
    return InlineKeyboardMarkup([
        [refresh, InlineKeyboardButton(L.t("panel.btn_bots"), callback_data="panel:bots"), signals],
        [InlineKeyboardButton(L.t("panel.seats.btn"), callback_data="panel:seats"),
         InlineKeyboardButton(L.t("ops.btn"), callback_data="panel:ops"),
         InlineKeyboardButton(L.t("panel.delegates.btn"), callback_data="panel:delegates")],
        [numbers, security, bases],
        [InlineKeyboardButton(L.t("panel.site.btn"), callback_data=site_conf.HOME)],
    ])


def media_name(row):
    return render.esc(row.get("title") or row["id"])


def media_line(L, row):
    title = media_name(row)
    if row.get(base_videos.OFFICIAL):
        title = f"{OFFICIAL_MARK} {title}"
    return L.t("panel.media.channels", title=title, id=render.esc(row["id"]))


def media_quota(L, stopped, moment):
    until = manager_alerts.moment(stopped.get("until"))
    if not until or until.timestamp() <= moment:
        return None
    return L.t("panel.media.quota", when=L.when(until))


async def media_page(store, L):
    rows = await base_videos.platform_rows(store)
    last = await store.kv_get(base_library.LAST_KEY) or {}
    stopped = await store.kv_get(base_videos.QUOTA_KEY) or {}
    body = [L.t("panel.media.library", n=int(last.get("count") or 0),
                when=L.ago(manager_alerts.moment(last.get("at"))))]
    quota = media_quota(L, stopped, time.time())
    if quota:
        body.append(quota)
    body.append(render.quote("\n".join(media_line(L, row) for row in rows)) if rows
                else L.t("panel.media.empty"))
    buttons = [[InlineKeyboardButton(L.t("panel.media.official", title=media_name(row)),
                                     callback_data=f"panel:mediaofficial:{row['id']}"),
                InlineKeyboardButton(L.t("panel.media.drop", title=media_name(row)),
                                     callback_data=f"panel:mediadrop:{row['id']}")]
               for row in rows]
    buttons.append([InlineKeyboardButton(L.t("panel.media.add"), callback_data="panel:mediaadd"),
                    InlineKeyboardButton(L.t("console.btn_back"), callback_data="panel:refresh")])
    return (render.card(MEDIA_ICON, L.t("panel.media.title"), "\n".join(body)),
            InlineKeyboardMarkup(buttons))


def media_ask(L, bad=False):
    body = L.t("panel.media.ask")
    if bad:
        body = L.t("panel.media.bad") + "\n" + body
    back = InlineKeyboardButton(L.t("console.btn_back"), callback_data=MEDIA_BACK)
    return render.card(MEDIA_ICON, L.t("panel.media.title"), body), InlineKeyboardMarkup([[back]])


async def panel_resources(store, moment):
    samples = metrics.read_samples(metrics.SAMPLES)
    last = metrics.latest(samples) or {}
    peaks = metrics.peaks(samples, moment)
    sampled = last.get("containers") or {}
    fresh = await ops.containers(store)
    containers = []
    for name in sorted(set(sampled) | set(fresh)):
        stats, now_stats = sampled.get(name) or {}, fresh.get(name) or {}
        peak = peaks.get(name) or {}
        containers.append({
            "name": name,
            "mem_mb": freshest(now_stats, stats, "mem_mb"),
            "cpu": freshest(now_stats, stats, "cpu"),
            "peak_mem_mb": peak.get("mem_mb"),
            "peak_cpu": peak.get("cpu"),
        })
    return {
        "containers": containers,
        "backup_age_h": last.get("backup_age_h"),
        "retention": last.get("retention"),
        "alerts": metrics.alerts(samples, moment),
    }


async def panel_data(context, resources=True):
    store, supervisor = services(context)
    running = set(supervisor.running())
    rows = [bot for bot in await store.bots() if bot.kind != "console"]
    counts = await store.counts()
    coc = context.bot_data.get("coc")
    alive = coc.keys_alive() if coc else 0
    state = await store.kv_get(platform_guard.STATE_KEY) or {}
    data = {
        "bots": {
            "running": len([bot for bot in rows if bot.alias in running]),
            "total": len(rows),
            "stopped": [{"name": bot.username, "reason": bot.reason} for bot in rows if not bot.active],
        },
        "clans": {"active": counts["active"], "total": counts["total"]},
        "keys": {"alive": alive, "dead": len(coc.keys) - alive if coc else 0},
        "api_per_minute": coc.calls_per_minute() if coc else 0,
        "sends": {kind: summed(state.get(kind)) for kind in ("sent", "delayed", "dropped")},
        "survey": await survey.summary(store),
    }
    if resources:
        data.update(await panel_resources(store, time.time()))
    return data


async def panel_level(update, context):
    store, _ = services(context)
    user = update.effective_user
    return await platform.level(store, user.id if user else None)


async def panel_locale(store, update, lvl):
    return await platform_guard.owner_locale(store) if lvl == platform.OWNER else user_locale(update)


async def panel_gate(update, context):
    lvl = await panel_level(update, context)
    if not lvl:
        await update.effective_message.reply_text(user_locale(update).t("console.owner_only"))
    return lvl


async def panel_text(context, store, L, lvl, user_id):
    full = lvl == platform.OWNER
    text = render.panel_card(L, await panel_data(context, full), full)
    if await otp.active(store, user_id):
        return text
    return render.clip(text + "\n" + L.t("otp.hint"))


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update):
        return
    lvl = await panel_gate(update, context)
    if not lvl:
        return
    store, _ = services(context)
    L = await panel_locale(store, update, lvl)
    text = await panel_text(context, store, L, lvl, update.effective_user.id)
    await update.effective_message.reply_text(text, reply_markup=panel_keyboard(L, lvl))


async def ops_screen(store, L):
    back = InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("ban.btn"), callback_data="panel:banned"),
        InlineKeyboardButton(L.t("panel.incidents.btn"), callback_data="panel:incidents"),
        InlineKeyboardButton(L.t("console.btn_back"), callback_data="panel:refresh"),
    ]])
    return render.ops_card(L, ops.board(await ops.snapshot(store, time.time()))), back


async def on_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, supervisor = services(context)
    lvl = await panel_level(update, context)
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    if not lvl:
        await query.answer(user_locale(update).t("console.owner_only"), show_alert=True)
        return
    if not platform.allowed(action, lvl):
        await query.answer(user_locale(update).t("console.not_owner"), show_alert=True)
        return
    await query.answer()
    full = lvl == platform.OWNER
    L = await panel_locale(store, update, lvl)
    user = update.effective_user
    if action in otp.GUARDED and not await otp.cleared(store, user.id, full, time.time()):
        await edit(query, *otp_screen(context, await otp.wall(store, L, user.id)))
        return
    if action in otp.ACTIONS:
        await edit(query, *otp_screen(context, await otp.act(store, L, action, user, time.time())))
        ref = seed_ref(query) if action == "otpnew" else None
        if ref and await store.kv_get(otp.pending_of(user.id)):
            context.user_data[OTP_SEED] = ref
        return
    if action in platform.ACTIONS:
        panel_flow(context, "delegates" if action == "deladd" else None)
        text, keyboard = await platform.act(store, L, action, ":".join(parts[2:]), time.time())
        await edit(query, text, keyboard)
        return
    if action in platform.MEDIA:
        panel_flow(context, "media" if action == "mediaadd" else None)
        if action == "mediaadd":
            await edit(query, *media_ask(L))
            return
        if action == "mediadrop":
            await base_videos.drop_channel(store, ":".join(parts[2:]))
        if action == "mediaofficial":
            await base_videos.mark_official(store, ":".join(parts[2:]))
        await edit(query, *await media_page(store, L))
        return
    if action == "bots":
        back = InlineKeyboardMarkup([[
            InlineKeyboardButton(L.t("console.btn_back"), callback_data="panel:refresh")
        ]])
        await edit(query, await bots_page(L, store, supervisor), back)
        return
    if action == "ops":
        await edit(query, *await ops_screen(store, L))
        return
    if action in incidents.ACTIONS:
        await edit(query, *await incident_screen(store, L, context, action, parts[2:], full))
        return
    if action in site_conf.ACTIONS:
        await edit(query, *await site_screen(store, L, context, action, ":".join(parts[2:])))
        return
    if action == "usage":
        back = InlineKeyboardMarkup([[
            InlineKeyboardButton(L.t("console.btn_back"), callback_data="panel:refresh")
        ]])
        await edit(query, usage.panel_card(L, await store.web_note("usage")), back)
        return
    if action in ban.ACTIONS:
        text, keyboard = await ban.act(store, L, action, ":".join(parts[2:]), PAGE_SIZE)
        await edit(query, text, keyboard)
        return
    if action in seats.ACTIONS:
        text, keyboard = await seats.act(store, L, action, parts[2] if len(parts) > 2 else "",
                                         PAGE_SIZE)
        await edit(query, text, keyboard)
        return
    if action in reports.ACTIONS:
        text, keyboard = await reports.act(
            store, supervisor, context.bot, L, action, parts[2] if len(parts) > 2 else "",
            await store.reports(PAGE_SIZE), now_utc(), full)
        await edit(query, text, keyboard)
        return
    await edit(query, await panel_text(context, store, L, lvl, user.id), panel_keyboard(L, lvl))


async def broadcast_targets(store, supervisor):
    running = set(supervisor.running())
    targets = []
    for clan in await store.active_clans():
        if clan.bot_alias not in running:
            continue
        conf = settings_mod.effective(await store.get_state(clan.alias, "settings"))
        if not news.wanted(conf):
            continue
        where = news.destination(conf)
        if where == "off":
            continue
        targets.append((clan, conf, where))
    return targets


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await private_only(update) or not await panel_gate(update, context):
        return
    store, supervisor = services(context)
    L = user_locale(update)
    text = " ".join(context.args or []).strip()
    if not text:
        await update.effective_message.reply_text(L.t("console.broadcast_usage"))
        return
    context.user_data["broadcast"] = text
    targets = await broadcast_targets(store, supervisor)
    body = render.quote(render.esc(text)) + "\n\n" + L.t("console.broadcast_preview", n=len(targets))
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("console.btn_send"), callback_data="bc:send"),
        InlineKeyboardButton(L.t("console.btn_cancel"), callback_data="bc:cancel"),
    ]])
    card = render.card("📣", L.t("console.broadcast_title"), body)
    await update.effective_message.reply_text(card, reply_markup=keyboard)


async def on_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, supervisor = services(context)
    L = user_locale(update)
    lvl = await panel_level(update, context)
    if not lvl:
        await query.answer(L.t("console.owner_only"), show_alert=True)
        return
    user = update.effective_user
    action = (query.data or "").split(":")[-1]
    if action == "send" and not await otp.cleared(store, user.id, lvl == platform.OWNER,
                                                  time.time()):
        await query.answer()
        await edit(query, *otp_screen(context, await otp.wall(store, L, user.id)))
        return
    text = context.user_data.pop("broadcast", None)
    await query.answer()
    if action != "send" or not text:
        await edit(query, render.card("📣", L.t("console.broadcast_title"), L.t("console.cancelled")))
        return
    sent, failed = 0, 0
    for clan, conf, _ in await broadcast_targets(store, supervisor):
        bot = supervisor.bot(clan.bot_alias)
        if not bot:
            failed += 1
            continue
        CL = locale(conf["lang"])
        card = render.card("📣", CL.t("console.broadcast_title"), render.quote(render.esc(text)))
        try:
            await bot.send_message(clan.chat_id, card, message_thread_id=news.thread(conf))
            sent += 1
        except TelegramError:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY)
    log.info("comunicazione inviata a %s clan, %s non riusciti", sent, failed)
    await platform.note_action(store, platform.NEWS, update.effective_user.id, time.time())
    body = L.t("console.broadcast_sent", sent=sent, failed=failed)
    await edit(query, render.card("📣", L.t("console.broadcast_title"), body))


def register(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("newbot", cmd_newbot))
    app.add_handler(CommandHandler("mybots", cmd_mybots))
    app.add_handler(CommandHandler("support", cmd_support))
    app.add_handler(CommandHandler(["cancel", "annulla"], cmd_cancel))
    app.add_handler(CommandHandler("bots", cmd_bots))
    app.add_handler(CommandHandler("disable", cmd_disable))
    app.add_handler(CommandHandler("enable", cmd_enable))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler(["pannello", "panel"], cmd_panel))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(on_bot_callback, pattern=r"^b:"))
    app.add_handler(CallbackQueryHandler(on_home_callback, pattern=rf"^{HOME}:"))
    app.add_handler(CallbackQueryHandler(on_panel_callback, pattern=r"^panel:"))
    app.add_handler(CallbackQueryHandler(on_broadcast_callback, pattern=r"^bc:"))
    app.add_handler(CallbackQueryHandler(on_setup_callback, pattern=r"^cfg:"))
    app.add_handler(CallbackQueryHandler(on_terms_callback, pattern=r"^tos:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.MANAGED_BOT_CREATED, on_managed_created))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_newbot_text))
    app.add_handler(ManagedBotUpdatedHandler(on_managed_updated))
