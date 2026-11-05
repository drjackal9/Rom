import asyncio
import logging

from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

log = logging.getLogger("clashbot.delivery")

GONE = ("chat not found", "upgraded")


def gone(error):
    reason = str(error).lower()
    return any(mark in reason for mark in GONE)


def words(thread_id=None, silent=False, reply_markup=None, extra=None):
    out = {}
    if thread_id is not None:
        out["message_thread_id"] = thread_id
    if silent:
        out["disable_notification"] = True
    if reply_markup is not None:
        out["reply_markup"] = reply_markup
    out.update(extra or {})
    return out


async def wait_flood(error):
    await asyncio.sleep(error.retry_after + 1)
    return True


async def to_chat(store, bot, clan, text, thread_id=None, silent=False, reply_markup=None,
                  extra=None, on_flood=None, on_refused=None, on_sent=None):
    if not bot or not text:
        return False
    kw = words(thread_id, silent, reply_markup, extra)
    try:
        try:
            message = await bot.send_message(clan.chat_id, text, **kw)
        except RetryAfter as e:
            if not await (on_flood or wait_flood)(e):
                return False
            message = await bot.send_message(clan.chat_id, text, **kw)
        if on_sent is not None:
            on_sent(message)
        return True
    except Forbidden as e:
        row = await store.mark_failure(clan.alias)
        log.warning("%s: invio vietato (%s), errori %s, attivo %s", clan.alias, e, row["failures"], row["active"])
    except BadRequest as e:
        answer = await on_refused(e) if on_refused is not None else None
        if answer is not None:
            return answer
        if gone(e):
            row = await store.mark_failure(clan.alias)
            log.warning("%s: chat irraggiungibile (%s), errori %s", clan.alias, e, row["failures"])
        else:
            log.warning("%s: invio rifiutato: %s", clan.alias, e)
    except TelegramError as e:
        log.warning("%s: invio fallito: %s", clan.alias, e)
    return False
