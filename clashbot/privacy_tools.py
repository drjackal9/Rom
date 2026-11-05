import io

from telegram import InputFile, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from . import privacy, privacy_cards, render
from .util import now_utc

EXPORT_COOLDOWN = 3600
AREA = "data"
COMMANDS = [("mydata", ["mieidati"]), ("forgetme", ["dimenticami"])]


async def gate(update, context):
    from . import handlers as h
    store, _ = h.services(context)
    L = h.user_locale(update)
    if update.effective_chat.type != ChatType.PRIVATE:
        return None, L, "group"
    user = update.effective_user
    links = await store.links_by_user(user.id) if user else []
    if not links:
        return None, L, "unlinked"
    clan = await h.clan_for(update, context)
    if clan:
        L, _ = await h.clan_locale(store, clan)
    return links, L, None


def refusal(L, reason, username):
    if reason == "group":
        return L.t("privacy.private_only", bot=username)
    return render.not_linked_me(L, username)


async def throttled(store, user, now):
    stored = await store.kv_get(privacy.user_key(store, "md", user.id)) or {}
    stamp = int(stored.get("ts") or 0)
    left = EXPORT_COOLDOWN - int(now.timestamp()) + stamp
    if stamp and left > 0:
        return max(1, -(-left // 60))
    return 0


async def mark_sent(store, user, now):
    await store.kv_set(privacy.user_key(store, "md", user.id),
                       {"ts": int(now.timestamp())}, ttl=EXPORT_COOLDOWN)


async def cmd_mydata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    links, L, why = await gate(update, context)
    reply = update.effective_message.reply_text
    if why:
        await reply(refusal(L, why, context.bot.username))
        return
    now = now_utc()
    user = update.effective_user
    wait = await throttled(store, user, now)
    if wait:
        await reply(L.t("privacy.throttle", n=wait))
        return
    payload = await privacy.collect(store, user.id, links, now)
    hidden = any(account["hidden_from_boards"] for account in payload["accounts"])
    await reply(privacy_cards.data_card(L, payload), reply_markup=privacy_cards.data_keyboard(L, hidden))
    await mark_sent(store, user, now)
    document = InputFile(io.BytesIO(privacy.export_bytes(payload)), filename=privacy_cards.FILENAME)
    try:
        await context.bot.send_document(user.id, document=document)
    except TelegramError:
        await reply(L.t("privacy.file_failed"))


async def cmd_forgetme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, L, why = await gate(update, context)
    reply = update.effective_message.reply_text
    if why == "unlinked":
        await reply(L.t("privacy.forget.nothing"))
        return
    if why:
        await reply(refusal(L, why, context.bot.username))
        return
    await reply(privacy_cards.forget_card(L), reply_markup=privacy_cards.forget_keyboard(L))


async def on_privacy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    query = update.callback_query
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    step = parts[2] if len(parts) > 2 else ""
    links, L, why = await gate(update, context)
    if why:
        await query.answer()
        await h.edit_or_log(query, refusal(L, why, context.bot.username), None, "privacy")
        return
    now = now_utc()
    user = update.effective_user
    if action in ("hide", "show"):
        on = action == "hide"
        spots = await privacy.places(store, user.id, links)
        if not spots:
            await query.answer(L.t("privacy.no_clan"), show_alert=True)
            return
        for clan, data in spots:
            here = privacy.member_tags(data, {row.tag for row in links})
            for row in links:
                if row.tag in here or not on:
                    await privacy.set_excluded(store, clan.alias, row.tag, on, row.name, now)
        await query.answer()
        await h.edit_or_log(query, privacy_cards.hidden_card(L, on), None, "privacy")
        return
    if action == "forget" and step == "yes":
        counts = await privacy.erase(store, user.id, links, now)
        await query.answer()
        await h.edit_or_log(query, privacy_cards.forget_done(L, counts), None, "privacy")
        return
    await query.answer()
    if action == "forget" and step == "no":
        await h.edit_or_log(query, L.t("h.cancelled"), None, "privacy")
        return
    await h.edit_or_log(query, privacy_cards.forget_card(L), privacy_cards.forget_keyboard(L), "privacy")


HANDLERS = {"mydata": cmd_mydata, "forgetme": cmd_forgetme}
