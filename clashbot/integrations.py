from . import leaders

PACK = "integrations"
EVENTS = ("integrations.twitch_live", "integrations.bridge", "integrations.notice")
BRIDGE_EVENT = "integrations.bridge"
NOTICE_EVENT = "integrations.notice"
NOTICE_EVERY = 86400
NOTICE_KIND = "notices"
NOTICE_MARK = "int:"


def block(conf, key):
    value = (conf or {}).get(key)
    return dict(value) if isinstance(value, dict) else {}


async def send_event(store, bot, clan, conf, event, text, silent=False, now=None):
    return await leaders.notify(store, bot, clan, conf, event, text, now=now, silent=silent)


async def notice(store, bot, clan, conf, key, text, now):
    state = await store.get_state(clan.alias, NOTICE_KIND) or {}
    mark = f"{NOTICE_MARK}{key}"
    last = state.get(mark)
    if isinstance(last, (int, float)) and not isinstance(last, bool) and now.timestamp() - last < NOTICE_EVERY:
        return 0
    sent = await send_event(store, bot, clan, conf, NOTICE_EVENT, text)
    state[mark] = now.timestamp()
    await store.set_state(clan.alias, NOTICE_KIND, state)
    return sent


async def clear_notice(store, alias, key):
    state = await store.get_state(alias, NOTICE_KIND) or {}
    if state.pop(f"{NOTICE_MARK}{key}", None) is not None:
        await store.set_state(alias, NOTICE_KIND, state)
