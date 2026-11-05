import logging

from telegram.error import TelegramError

log = logging.getLogger("clashbot.polls")
TTL = 4 * 86400
KEEPERS = {}


def keeper(state_key, load, save):
    KEEPERS[state_key] = (load, save)


def keepers_for(state_key):
    if state_key in KEEPERS:
        return KEEPERS[state_key]

    async def load(store, alias):
        return await store.get_state(alias, state_key)

    async def save(store, alias, poll):
        if poll is None:
            await store.del_state(alias, state_key)
        else:
            await store.set_state(alias, state_key, poll)

    return load, save


async def open_poll(poller, t, state_key, event, question, options, extra=None, ttl=TTL,
                    anonymous=False, **poll_kwargs):
    to, thread, _ = poller.destination(t.settings, event)
    bot = poller.bot_for(t.clan)
    if to == "off" or not bot:
        return None
    try:
        message = await bot.send_poll(
            t.clan.chat_id, question, options, is_anonymous=anonymous,
            disable_notification=t.quiet, question_parse_mode=None, message_thread_id=thread,
            **poll_kwargs,
        )
    except TelegramError as e:
        log.warning("%s: sondaggio non inviato: %s", t.clan.alias, e)
        return None
    poll = {"poll_id": message.poll.id, "message_id": message.message_id, "votes": {}}
    poll.update(extra or {})
    await keepers_for(state_key)[1](poller.store, t.clan.alias, poll)
    await poller.store.kv_set(f"poll:{message.poll.id}", {"state": state_key}, ref=t.clan.alias, ttl=ttl)
    return poll


async def close_poll(poller, t, state_key):
    load, save = keepers_for(state_key)
    poll = await load(poller.store, t.clan.alias)
    if not poll:
        return None
    bot = poller.bot_for(t.clan)
    if bot:
        try:
            await bot.stop_poll(t.clan.chat_id, poll["message_id"])
        except TelegramError as e:
            log.warning("%s: sondaggio non chiuso: %s", t.clan.alias, e)
    await save(poller.store, t.clan.alias, None)
    await poller.store.kv_del(f"poll:{poll['poll_id']}")
    return poll


def vote(poll, user_id, name, option):
    votes = poll.setdefault("votes", {})
    if option is None:
        votes.pop(str(user_id), None)
    else:
        votes[str(user_id)] = {"name": name, "option": option}
    return poll


async def set_vote(store, alias, state_key, user_id, name, option, size=None):
    load, save = keepers_for(state_key)
    poll = await load(store, alias)
    if not poll or option < 0 or (size is not None and option >= size):
        return None
    await save(store, alias, vote(poll, user_id, name, option))
    return poll


async def record_answer(store, answer):
    key = f"poll:{answer.poll_id}"
    alias = await store.kv_ref(key)
    if not alias:
        return None
    state_key = ((await store.kv_get(key)) or {}).get("state") or "poll"
    load, save = keepers_for(state_key)
    poll = await load(store, alias)
    if not poll or poll.get("poll_id") != answer.poll_id:
        return None
    vote(poll, answer.user.id, answer.user.first_name,
         answer.option_ids[0] if answer.option_ids else None)
    await save(store, alias, poll)
    return poll
