import logging

from telegram.error import TelegramError

from . import boards, pinned, roles

log = logging.getLogger("clashbot.one_group")

REFUSAL = "gate.other_group"
BOARDS = "boards"


async def elsewhere(store, alias, chat_id):
    if not alias:
        return None
    for clan in await store.active_clans(alias):
        if clan.chat_id != chat_id:
            return clan
    return None


async def step_out(bot, chat_id):
    try:
        await bot.leave_chat(chat_id)
        return True
    except TelegramError as e:
        log.warning("uscita dalla chat non riuscita: %s", type(e).__name__)
        return False


async def forget_pin(store, bot, clan):
    state = await store.get_state(clan.alias, BOARDS) or {}
    message_id = boards.message_id(state)
    if not message_id:
        return False
    await pinned.erase(bot, clan.chat_id, message_id)
    await store.set_state(clan.alias, BOARDS, boards.drop_pin(state))
    return True


async def chief_now(store, coc, clan, members, user_id):
    fresh = members
    if coc:
        fresh, _ = await roles.live_members(coc, store, clan, members, user_id)
    return user_id in await roles.chiefs(store, fresh)


async def move(store, alias, chat_id, user_id, bot=None, coc=None):
    other = await elsewhere(store, alias, chat_id)
    if not other:
        return None
    members = await store.get_state(other.alias, "members") or {}
    if user_id is None or not await chief_now(store, coc, other, members, user_id):
        return False
    await forget_pin(store, bot, other)
    return await store.move_clan(other.chat_id, chat_id, alias)
