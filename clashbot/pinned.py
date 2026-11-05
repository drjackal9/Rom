import logging

from telegram.error import BadRequest, TelegramError

log = logging.getLogger("clashbot.pinned")
STALE = 600


async def upkeep(bot, chat_id, state, text, digest, now_ts, quiet=False, stale=STALE, create=True,
                 thread_id=None, force=False, pin=True, markup=None):
    if not bot:
        return state
    if not force and state and state.get("digest") == digest \
            and now_ts - float(state.get("updated") or 0) <= stale:
        return state
    extra = {"reply_markup": markup} if markup else {}
    message_id = (state or {}).get("message_id")
    if message_id:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, **extra)
            return {"message_id": message_id, "digest": digest, "updated": now_ts}
        except BadRequest as e:
            reason = str(e).lower()
            if "not modified" in reason:
                return {"message_id": message_id, "digest": digest, "updated": now_ts}
            if "not found" not in reason and "can't be edited" not in reason:
                log.warning("tabellone non aggiornato: %s", e)
                return state
        except TelegramError as e:
            log.warning("tabellone non aggiornato: %s", e)
            return state
    if not create:
        return None
    try:
        message = await bot.send_message(chat_id, text, disable_notification=bool(quiet),
                                         message_thread_id=thread_id, **extra)
    except TelegramError as e:
        log.warning("tabellone non inviato: %s", e)
        return None
    if pin:
        try:
            await bot.pin_chat_message(chat_id, message.message_id, disable_notification=True)
        except TelegramError:
            pass
    return {"message_id": message.message_id, "digest": digest, "updated": now_ts}


async def drop(bot, chat_id, state):
    message_id = (state or {}).get("message_id")
    if not bot or not message_id:
        return None
    try:
        await bot.unpin_chat_message(chat_id, message_id)
    except TelegramError:
        pass
    return None


async def erase(bot, chat_id, message_id):
    if not bot or not message_id:
        return False
    await drop(bot, chat_id, {"message_id": message_id})
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramError as e:
        log.info("vecchia bacheca non cancellata: %s", type(e).__name__)
        return False
    return True
