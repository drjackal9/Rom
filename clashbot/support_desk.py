from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from . import manager_alerts, media, platform, privacy, render, support_cards, verify
from .util import now_utc

AREA = "support"
COMMANDS = [("guide", ["guida"]), ("feedback", ["idee"])]
CATEGORIES = ("idea", "bug", "translation", "other")
PROBLEMS = ("bot_down", "war_stale", "link", "community")
TEXT_MAX = 500
COOLDOWN = 600
TOO_SOON = "feedback.too_soon"
FAILED = "feedback.failed"
SENT = "feedback.sent"
TERMS_DATA = "tos:ok"
FIRST = {"link": ("tag", render.link_ask_tag), "onboard": ("clan", render.onboard_ask_clan)}


async def cmd_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    _, L, _ = await h.chat_locale(update, context)
    username = context.bot.username
    await update.effective_message.reply_text(
        support_cards.guide_card(L, username),
        reply_markup=support_cards.guide_keyboard(L, username))


async def staff(store, user):
    return bool(user) and await platform.level(store, user.id) is not None


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    L = h.user_locale(update)
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.effective_message.reply_text(L.t("feedback.private_only", bot=context.bot.username))
        return
    context.user_data.pop("flow", None)
    if await staff(store, update.effective_user):
        text, choices = support_cards.feedback_card(L), CATEGORIES
    else:
        text, choices = support_cards.report_card(L), PROBLEMS
    await update.effective_message.reply_text(
        text, reply_markup=support_cards.feedback_keyboard(L, choices))


async def on_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    query = update.callback_query
    L = h.user_locale(update)
    category = (query.data or "").split(":")[-1]
    await query.answer()
    if category in PROBLEMS:
        said = told(L, await report(update, context, category))
        await h.edit_or_log(query, said, None, "feedback")
        return
    if category not in CATEGORIES or not await staff(store, update.effective_user):
        return
    context.user_data["flow"] = {"kind": "feedback", "category": category}
    await h.edit_or_log(query, support_cards.feedback_ask(L, TEXT_MAX), None, "feedback")


async def report(update, context, category, text=None):
    from . import handlers as h
    store, _ = h.services(context)
    user = update.effective_user
    key = privacy.user_key(store, "fb", user.id)
    if await store.kv_get(key):
        return TOO_SOON
    clan = await h.clan_for(update, context)
    if not await deliver(context, category, text, user, clan):
        return FAILED
    await store.kv_set(key, {"ts": int(now_utc().timestamp())}, ttl=COOLDOWN)
    return SENT


def told(L, outcome):
    return L.t(outcome, n=COOLDOWN // 60)


async def deliver(context, category, text, user, clan):
    from . import handlers as h
    store, _ = h.services(context)
    if category not in CATEGORIES + PROBLEMS:
        return False
    supervisor = context.bot_data.get("supervisor")
    bot = supervisor.owner_bot() if supervisor else None
    if not bot:
        return False
    L = await manager_alerts.locale(store)
    text_card = support_cards.owner_feedback_card(
        L, category, text, user.id if user else 0,
        h.bot_alias(context) or "-", getattr(clan, "alias", None))
    return await manager_alerts.send(store, bot, text_card)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE, flow):
    from . import handlers as h
    store, _ = h.services(context)
    L = h.user_locale(update)
    reply = update.effective_message.reply_text
    if not await staff(store, update.effective_user):
        context.user_data.pop("flow", None)
        await reply(L.t("feedback.fixed_only"))
        return
    text = (update.effective_message.text or "").strip()[:TEXT_MAX]
    if not text:
        await reply(L.t("feedback.ask", n=TEXT_MAX))
        return
    category = flow.get("category")
    if category not in CATEGORIES:
        context.user_data.pop("flow", None)
        return
    outcome = await report(update, context, category, text)
    if outcome != TOO_SOON:
        context.user_data.pop("flow", None)
    await reply(told(L, outcome))


async def terms_screen(store, L):
    site = await media.site_base(store)
    return support_cards.terms_card(L), support_cards.terms_keyboard(L, TERMS_DATA, site)


async def open_flow(update, message, context, kind):
    from . import handlers as h
    store, _ = h.services(context)
    L = h.user_locale(update)
    step, ask = FIRST[kind]
    if await verify.terms_day(store, update.effective_user.id):
        context.user_data["flow"] = {"kind": kind, "step": step}
        await message.reply_text(ask(L))
        return
    context.user_data["flow"] = {"kind": kind, "step": verify.TERMS}
    text, keyboard = await terms_screen(store, L)
    await message.reply_text(text, reply_markup=keyboard)


async def remind_terms(update, context):
    from . import handlers as h
    store, _ = h.services(context)
    text, keyboard = await terms_screen(store, h.user_locale(update))
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def on_terms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    query = update.callback_query
    L = h.user_locale(update)
    await query.answer()
    if query.data != TERMS_DATA or not update.effective_user:
        return
    await verify.accept_terms(store, update.effective_user.id, now_utc())
    await h.edit_or_log(query, L.t("terms.done"), None, "terms")
    flow = context.user_data.get("flow") or {}
    if flow.get("step") != verify.TERMS or flow.get("kind") not in FIRST:
        return
    step, ask = FIRST[flow["kind"]]
    context.user_data["flow"] = {"kind": flow["kind"], "step": step}
    await update.effective_message.reply_text(ask(L))


HANDLERS = {"guide": cmd_guide, "feedback": cmd_feedback}
