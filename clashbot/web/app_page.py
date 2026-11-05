from .. import agenda, challenges, duels, guess_attack, i18n, predictions, quiz
from ..quizbank import by_id
from . import payload

GOLDPASS = "goldpass"


def voters(poll, tags):
    votes = (poll or {}).get("votes") or {}
    return sorted(tag for uid, tag in tags.items() if uid in votes)


def war_row(record):
    return {
        "them": record.get("opponent"),
        "us_stars": int(record.get("stars") or 0),
        "them_stars": int(record.get("opp_stars") or 0),
        "us_destr": round(float(record.get("destr") or 0), 2),
        "them_destr": round(float(record.get("opp_destr") or 0), 2),
        "result": record.get("result"),
        "ended": payload.stamp(record.get("endTime")),
    }


def war_rows(records):
    return [war_row(record) for record in records or ()]


def duel_rows(state):
    return [{"id": duel.get("id"), "challenger": duel["a"].get("tag"),
             "rival": duel["b"].get("tag"), "metric": duel.get("metric"),
             "status": duel.get("status"), "ends": int(duel.get("ends") or 0)}
            for duel in duels._open(state)]


def quiz_row(state, L, tags):
    poll = (state.get("quiz") or {}).get("open")
    question = by_id((poll or {}).get("id"))
    if not question:
        return None
    text, options, _ = quiz.texts(L, question)
    return {"open": True, "question": text, "options": options, "answered": voters(poll, tags)}


def prediction_rows(polls, L, tags):
    return [{"poll": kind, "options": predictions.options(L), "voted": voters(poll, tags)}
            for kind, poll in polls.items()]


async def open_polls(store, alias):
    found = {}
    for kind in predictions.KINDS:
        poll = await store.get_state(alias, predictions.state_key(kind))
        if poll:
            found[kind] = poll
    return found


async def guess_row(store, clan, conf, now, tags, history=()):
    day = guess_attack.day_of(now, (conf or {}).get("tz"))
    found = guess_attack.round_for(history, clan.alias, day)
    if not found:
        return None
    state = await store.get_state(clan.alias, guess_attack.STATE)
    return dict(guess_attack.question(found),
                answered=guess_attack.answered(state, day, tags))


async def extras(store, clan, conf, links, now, wars=()):
    L = i18n.locale((conf or {}).get("lang"))
    tags = {str(link.user_id): tag for tag, link in (links or {}).items()}
    state = await challenges.load(store, clan.alias)
    goldpass = (await store.kv_get(GOLDPASS) or {}).get("end")
    rows = war_rows(wars)
    return {
        "agenda": payload.event_rows(agenda.upcoming(now, goldpass)),
        "wars": rows,
        "last_war": next(iter(rows), None),
        "games": {
            "duels": duel_rows(state),
            "quiz": quiz_row(state, L, tags),
            "predictions": prediction_rows(await open_polls(store, clan.alias), L, tags),
            "guess": await guess_row(store, clan, conf, now, tags, wars),
        },
    }
