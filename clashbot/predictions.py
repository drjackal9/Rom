from . import badges, challenges, polls, render, scoring
from .retention import STAT_HISTORY_KEEP

POLL_TTL = polls.TTL
EVENT = "challenges.poll"
CWL_OPEN_STATES = ("preparation", "inWar")
KINDS = {
    "war": {"state": "poll", "question": "poll.question"},
    "cwl": {"state": "poll_cwl", "question": "poll.question.cwl"},
    "capital": {"state": "poll_capital", "question": "poll.question.capital"},
}


def options(L):
    return [L.t(f"poll.option.{i}") for i in range(scoring.POLL_OPTIONS)]


def state_key(kind):
    return KINDS[kind]["state"]


async def start(poller, t, kind, key, reference=0, **question_args):
    stored = await poller.store.get_state(t.clan.alias, state_key(kind))
    if stored and stored.get("war") == key:
        return False
    extra = {"war": key}
    if reference:
        extra["reference"] = int(reference)
    poll = await polls.open_poll(poller, t, state_key(kind), EVENT,
                                 t.L.t(KINDS[kind]["question"], **question_args), options(t.L),
                                 extra=extra)
    return poll is not None


async def settle(poller, t, kind, key, value, reference=None):
    poll = await poller.store.get_state(t.clan.alias, state_key(kind))
    if not poll or poll.get("war") != key:
        return False
    top = int((poll.get("reference") if reference is None else reference) or 0)
    bucket = scoring.prediction_bucket(value, top)
    winners, seers = [], []
    for user_id, row in (poll.get("votes") or {}).items():
        right = row.get("option") == bucket
        scoring.apply_prediction(t.season, user_id, row.get("name"), right)
        if right:
            winners.append(row.get("name"))
            seers.append(user_id)
    if seers:
        state = await challenges.load(poller.store, t.clan.alias)
        badges.grant_all(state, seers, "veggente", int(t.now.timestamp()))
        await challenges.save(poller.store, t.clan.alias, state)
    if poll.get("votes"):
        await poller.dispatch(t, EVENT,
                              lambda L: render.prediction_result(L, bucket, options(L), winners))
    await polls.close_poll(poller, t, state_key(kind))
    return True


async def cwl_open(poller, t, cwl, war):
    if (war or {}).get("day") != 1 or (war or {}).get("state") not in CWL_OPEN_STATES:
        return False
    return await start(poller, t, "cwl", (cwl or {}).get("season") or "")


async def cwl_settle(poller, t, record, records):
    days = (record or {}).get("days") or []
    team = max((int(row.get("teamSize") or 0) for row in records or ()), default=0)
    return await settle(poller, t, "cwl", (record or {}).get("season") or "",
                        sum(int(day.get("stars") or 0) for day in days), len(days) * team * 3)


async def capital_reference(store, alias):
    rows = await store.recent_stats(alias, "capital", STAT_HISTORY_KEEP)
    return max((int(row.get("loot") or 0) for row in rows or ()), default=0)


async def capital_open(poller, t, raid):
    best = await capital_reference(poller.store, t.clan.alias)
    if not best:
        return False
    return await start(poller, t, "capital", raid.get("startTime") or "", reference=best,
                       record=t.L.n(best))


async def capital_settle(poller, t, raid):
    return await settle(poller, t, "capital", raid.get("startTime") or "",
                        int(raid.get("capitalTotalLoot") or 0))
