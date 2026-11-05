import logging
import uuid

from telegram import LabeledPrice, Update
from telegram.constants import ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from . import privacy, support_cards
from .util import now_utc

log = logging.getLogger("clashbot.tips")

CURRENCY = "XTR"
AMOUNTS = (10, 50, 100, 500)
PAYLOAD = "clanboard-tip"
KEEP_DAYS = 21
MAX_RECORDS = 5


def amount(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value in AMOUNTS else None


async def send_invoice(context, user_id, stars, L):
    await context.bot.send_invoice(
        chat_id=user_id,
        title=L.t("tip.title"),
        description=L.t("tip.body"),
        payload=f"{PAYLOAD}:{stars}",
        currency=CURRENCY,
        prices=[LabeledPrice(L.t("tip.label", n=stars), stars)],
    )


def new_ref(rows):
    taken = {row.get("ref") for row in rows}
    ref = uuid.uuid4().hex[:8]
    while ref in taken:
        ref = uuid.uuid4().hex[:8]
    return ref


def _rows(stored):
    return [row for row in ((stored or {}).get("rows") or []) if isinstance(row, dict)]


async def remember(store, user_id, stars, charge, now):
    key = privacy.user_key(store, "tip", user_id)
    rows = _rows(await store.kv_get(key))[-(MAX_RECORDS - 1):]
    ref = new_ref(rows)
    rows.append({"ref": ref, "stars": int(stars), "charge": str(charge), "ts": int(now.timestamp())})
    await store.kv_set(key, {"user_id": int(user_id), "rows": rows}, ttl=KEEP_DAYS * 86400)
    return ref


async def on_tip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    query = update.callback_query
    L = h.user_locale(update)
    parts = (query.data or "").split(":")
    if len(parts) > 2 and parts[1] == "r":
        await refund(update, context, parts[2])
        return
    stars = amount(parts[1] if len(parts) > 1 else "")
    if not stars:
        await query.answer()
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        await query.answer(L.t("tip.private_only", bot=context.bot.username), show_alert=True)
        return
    await query.answer()
    try:
        await send_invoice(context, update.effective_user.id, stars, L)
    except TelegramError:
        await h.edit_or_log(query, L.t("tip.failed"), None, "tip")


async def on_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    query = update.pre_checkout_query
    payload = query.invoice_payload or ""
    if payload.startswith(f"{PAYLOAD}:") and amount(payload.split(":")[-1]):
        await query.answer(ok=True)
        return
    await query.answer(ok=False, error_message=h.user_locale(update).t("tip.failed"))


async def on_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    message = update.effective_message
    payment = getattr(message, "successful_payment", None)
    if not payment or (payment.invoice_payload or "").split(":")[0] != PAYLOAD:
        return
    L = h.user_locale(update)
    stars = int(payment.total_amount or 0)
    ref = await remember(store, update.effective_user.id, stars,
                         payment.telegram_payment_charge_id, now_utc())
    log.info("mancia ricevuta di %s stelle", stars)
    await message.reply_text(support_cards.thanks_card(L, stars),
                             reply_markup=support_cards.refund_keyboard(L, ref))


async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE, raw):
    from . import handlers as h
    store, _ = h.services(context)
    query = update.callback_query
    L = h.user_locale(update)
    user = update.effective_user
    key = privacy.user_key(store, "tip", user.id)
    stored = await store.kv_get(key)
    rows = _rows(stored)
    row = next((entry for entry in rows if entry.get("ref") == raw), None)
    if not row or not row.get("charge") or int((stored or {}).get("user_id") or 0) != user.id:
        await query.answer(L.t("tip.refund_failed"), show_alert=True)
        return
    try:
        done = await context.bot.refund_star_payment(user.id, row["charge"])
    except TelegramError:
        done = False
    if not done:
        await query.answer(L.t("tip.refund_failed"), show_alert=True)
        return
    row["charge"] = ""
    await store.kv_set(key, {"user_id": user.id, "rows": rows}, ttl=KEEP_DAYS * 86400)
    await query.answer()
    await h.edit_or_log(query, L.t("tip.refunded", n=row["stars"]), None, "tip")


async def on_refunded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import handlers as h
    store, _ = h.services(context)
    refunded = getattr(update.effective_message, "refunded_payment", None)
    user = update.effective_user
    if not refunded or not user:
        return
    key = privacy.user_key(store, "tip", user.id)
    stored = await store.kv_get(key)
    if not stored:
        return
    charge = refunded.telegram_payment_charge_id
    rows = [row for row in _rows(stored) if row.get("charge") != charge]
    await store.kv_set(key, {"user_id": user.id, "rows": rows}, ttl=KEEP_DAYS * 86400)
