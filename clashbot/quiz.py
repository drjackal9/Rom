import hashlib

from . import badges, challenges, polls, render, scoring
from .agenda import raid_weekend
from .quizbank import OPTIONS, QUESTIONS, by_id

EVENT = "challenges.quiz"
STATE_KEY = "challenges.quiz"


def window(now):
    start, end = raid_weekend(now)
    return start, end, start.strftime("%Y%m%d")


def pick(alias, occurrence, used):
    taken = set(used or ())
    pool = [q for q in QUESTIONS if q["id"] not in taken] or list(QUESTIONS)
    seed = int(hashlib.sha256(f"{alias}:{occurrence}".encode()).hexdigest()[:8], 16)
    return pool[seed % len(pool)]


def texts(L, question):
    return (
        L.t(f"quiz.q.{question['id']}"),
        [L.t(f"quiz.q.{question['id']}.{i}") for i in range(OPTIONS)],
        L.t(f"quiz.q.{question['id']}.why"),
    )


def result_card(L, question, winners):
    right = render.esc(texts(L, question)[1][question["answer"]]) if question else "?"
    if winners:
        body = L.t("quiz.result.win", answer=right,
                   winners=", ".join(render.esc(name) for name in winners))
    else:
        body = L.t("quiz.result.none", answer=right)
    return render.card("🧠", L.t("quiz.title"), body)


def section(L, state):
    open_quiz = (state.get("quiz") or {}).get("open")
    if not open_quiz:
        return None
    return L.t("quiz.section", n=len(open_quiz.get("votes") or {}))


async def load_poll(store, alias):
    return (await challenges.load(store, alias))["quiz"].get("open")


async def save_poll(store, alias, poll):
    state = await challenges.load(store, alias)
    state["quiz"]["open"] = poll
    await challenges.save(store, alias, state)


polls.keeper(STATE_KEY, load_poll, save_poll)


async def run(poller, t):
    if poller.destination(t.settings, EVENT)[0] == "off":
        return
    state = await challenges.load(poller.store, t.clan.alias)
    changed = await _open(poller, t, state)
    changed = await _close(poller, t, state) or changed
    if changed:
        await challenges.save(poller.store, t.clan.alias, state)


async def _open(poller, t, state):
    quiz_state = state["quiz"]
    start, end, occurrence = window(t.now)
    if quiz_state.get("open") or quiz_state.get("last") == occurrence or not start <= t.now < end:
        return False
    question = pick(t.clan.alias, occurrence, quiz_state.get("used"))
    text, options, why = texts(t.L, question)
    poll = await polls.open_poll(poller, t, STATE_KEY, EVENT, text, options,
                                 extra={"id": question["id"], "occurrence": occurrence},
                                 type="quiz", correct_option_id=question["answer"],
                                 explanation=why)
    if not poll:
        return False
    quiz_state["open"] = poll
    used = [qid for qid in (quiz_state.get("used") or []) if qid != question["id"]] + [question["id"]]
    quiz_state["used"] = [] if len(used) >= len(QUESTIONS) else used
    return True


async def _close(poller, t, state):
    quiz_state = state["quiz"]
    open_quiz = quiz_state.get("open")
    if not open_quiz:
        return False
    _, end, occurrence = window(t.now)
    if open_quiz.get("occurrence") == occurrence and t.now < end:
        return False
    await polls.close_poll(poller, t, STATE_KEY)
    question = by_id(open_quiz["id"])
    winners, right_users = [], []
    for user_id, vote in (open_quiz.get("votes") or {}).items():
        if question and vote.get("option") == question["answer"]:
            scoring.apply_play(t.season, user_id, vote.get("name"), "quiz")
            winners.append(vote.get("name"))
            right_users.append(user_id)
    badges.grant_all(state, right_users, "quiz", int(t.now.timestamp()))
    await poller.dispatch(t, EVENT, lambda L: result_card(L, question, winners))
    challenges.note(state, "quiz", id=open_quiz["id"], winners=len(winners), ts=int(t.now.timestamp()))
    quiz_state["open"] = None
    quiz_state["last"] = open_quiz.get("occurrence")
    return True
