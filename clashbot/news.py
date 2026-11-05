from telegram import Update
from telegram.ext import ContextTypes

from . import render, support_cards, topics
from . import settings as settings_mod

AREA = "support"
COMMANDS = [("news", ["novita"])]
EVENT = "system.news"
KEY = "news"


def wanted(conf):
    return bool((conf or {}).get(KEY))


def destination(conf):
    where, _ = settings_mod.route(conf or {}, EVENT)
    return where


def thread(conf):
    return topics.thread_for(conf, EVENT)


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    clan = await h.clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(h.user_locale(update)))
        return
    L, _ = await h.clan_locale(store, clan)
    if not await h.can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("news.only_leaders"))
        return
    on = wanted(await h.clan_settings(store, clan))
    await update.effective_message.reply_text(support_cards.news_card(L, on),
                                              reply_markup=support_cards.news_keyboard(L, on))


async def on_news_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    query = update.callback_query
    clan = await h.clan_for(update, context)
    if not clan:
        await query.answer(h.user_locale(update).t("not_linked.title"), show_alert=True)
        return
    L, _ = await h.clan_locale(store, clan)
    if not await h.can_manage(update, context, clan):
        await query.answer(L.t("news.only_leaders"), show_alert=True)
        return
    on = (query.data or "").endswith(":on")
    await h.save_settings(store, clan, {KEY: on})
    await query.answer()
    await h.edit_or_log(query, support_cards.news_card(L, on), support_cards.news_keyboard(L, on), clan.alias)


HANDLERS = {"news": cmd_news}
