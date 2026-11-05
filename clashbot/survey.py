from . import polls

STATE = "survey"
EVENT = "system.survey"
OPTIONS = ("great", "good", "meh", "no")


def options(L):
    return [L.t(f"survey.opt.{name}") for name in OPTIONS]


def due(state, war_ended):
    return bool(war_ended) and not (state or {}).get("sent")


def record(state, poll):
    counts = dict((state or {}).get("counts") or {})
    rows = getattr(poll, "options", None) or []
    for index, name in enumerate(OPTIONS):
        if index < len(rows):
            counts[name] = int(getattr(rows[index], "voter_count", 0) or 0)
    return dict(state or {}, counts=counts)


def totals(states):
    summed = {name: 0 for name in OPTIONS}
    for state in states or ():
        counts = (state or {}).get("counts") or {}
        for name in OPTIONS:
            summed[name] += int(counts.get(name) or 0)
    return summed


def answered(states):
    return len([state for state in (states or ())
                if any(((state or {}).get("counts") or {}).values())])


async def open(poller, t):
    state = await poller.store.get_state(t.clan.alias, STATE)
    if not due(state, True):
        return None
    return await polls.open_poll(poller, t, STATE, EVENT, t.L.t("survey.question"), options(t.L),
                                 extra={"sent": int(t.now.timestamp())}, anonymous=True)


async def save(store, poll):
    poll_id = getattr(poll, "id", None)
    if not poll_id:
        return None
    key = f"poll:{poll_id}"
    alias = await store.kv_ref(key)
    if not alias or ((await store.kv_get(key)) or {}).get("state") != STATE:
        return None
    state = await store.get_state(alias, STATE)
    if not state or state.get("poll_id") != poll_id:
        return None
    state = record(state, poll)
    await store.set_state(alias, STATE, state)
    return state


async def summary(store):
    states = []
    for clan in await store.active_clans():
        state = await store.get_state(clan.alias, STATE)
        if state:
            states.append(state)
    return {"totals": totals(states), "clans": answered(states)}
