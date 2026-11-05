from . import badges, challenges, render
from .progress import closed, deltas, period_start
from .settings import route
from .util import REPORT_HOUR, bar, zone

EVENT = "challenges.mission"
METRICS = ("donated", "war_stars", "loot", "capital_gold", "games", "levels")
HALF = 50
NAMES = 5
NOBODY = "—"


def total(rows, metric):
    return sum(max(0, int(row.get(metric) or 0)) for row in rows or ())


def contributors(rows, metric):
    return sorted([row for row in rows or () if int(row.get(metric) or 0) > 0],
                  key=lambda row: -int(row.get(metric) or 0))


def _best(state, metric):
    return int(((state.get("mission") or {}).get("best") or {}).get(metric) or 0)


def open_week(state, week, metric, total_now):
    best = _best(state, metric)
    mission = {
        "week": week,
        "metric": metric,
        "goal": best,
        "start": int(total_now),
        "now": int(total_now),
        "sent": [],
        "measuring": best <= 0,
        "best": dict((state.get("mission") or {}).get("best") or {}),
    }
    state["mission"] = mission
    return mission


def set_metric(state, metric, total_now):
    week = (state.get("mission") or {}).get("week")
    if metric not in METRICS or not week:
        return None
    return open_week(state, week, metric, total_now)


def standing(mission, total_now):
    done = max(0, int(total_now) - int(mission.get("start") or 0))
    goal = int(mission.get("goal") or 0)
    if not goal:
        return done, goal, 0
    return done, goal, 100 if done >= goal else int(done * 100 / goal)


def due_notices(mission, done, goal):
    sent = mission.setdefault("sent", [])
    if not goal:
        return []
    if done >= goal:
        if "done" in sent:
            return []
        sent.append("done")
        return ["done"]
    if done * 100 >= goal * HALF and "half" not in sent:
        sent.append("half")
        return ["half"]
    return []


def _label(L, metric):
    return L.t(f"mission.metric.{metric}")


def section(L, state):
    mission = state.get("mission") or {}
    if not mission.get("metric"):
        return None
    done, goal, pct = standing(mission, mission.get("now") or mission.get("start") or 0)
    if mission.get("measuring"):
        return L.t("mission.section.measuring", metric=_label(L, mission["metric"]), done=L.n(done))
    return L.t("mission.section.head", metric=_label(L, mission["metric"])) + "\n" + render.quote(
        L.t("mission.section.row", bar=bar(pct), done=L.n(done), goal=L.n(goal), pct=pct))


def open_card(L, mission):
    return render.card("🎯", L.t("mission.title"), L.t(
        "mission.open.measuring" if mission["measuring"] else "mission.open",
        metric=_label(L, mission["metric"]), goal=L.n(mission["goal"])))


def notice_card(L, notice, metric, done, goal, pct):
    return render.card("🎯", L.t("mission.title"), L.t(
        f"mission.{notice}", metric=_label(L, metric), done=L.n(done), goal=L.n(goal), bar=bar(pct)))


def closed_card(L, metric, done, goal, names, won):
    return render.card("🎯", L.t("mission.title"), L.t(
        "mission.closed.win" if won else "mission.closed.end",
        metric=_label(L, metric), done=L.n(done), goal=L.n(goal),
        names=", ".join(render.esc(name) for name in names) or NOBODY))


def _metric_for(week, rows):
    ranked = [metric for metric in METRICS if total(rows, metric) > 0] or list(METRICS)
    return ranked[sum(ord(letter) for letter in week) % len(ranked)]


async def current_total(store, alias, metric, now, tz):
    stored = await store.get_state(alias, "progress") or {}
    return total(deltas(stored, "week", period_start(now, tz, "week")), metric)


async def run(poller, t):
    if route(t.settings, EVENT)[0] == "off":
        return
    state = await challenges.load(poller.store, t.clan.alias)
    progress = await poller.read_progress(t)
    start = period_start(t.now, t.tz, "week")
    rows = deltas(progress, "week", start)
    week = challenges.week_id(t.now, t.tz)
    mission = state["mission"]
    if mission.get("week") and mission.get("metric") and mission["week"] != week:
        if t.now.astimezone(zone(t.tz)).hour < REPORT_HOUR:
            return
        await _close(poller, t, state, closed(progress, "week", start))
        mission = state["mission"]
    if not mission.get("week") or not mission.get("metric"):
        metric = _metric_for(week, rows)
        fresh = open_week(state, week, metric, 0)
        await poller.dispatch(t, EVENT, lambda L: open_card(L, fresh))
        await challenges.save(poller.store, t.clan.alias, state)
        return
    now_total = total(rows, mission["metric"])
    mission["now"] = now_total
    done, goal, pct = standing(mission, now_total)
    for notice in due_notices(mission, done, goal):
        await poller.dispatch(t, EVENT, lambda L, notice=notice: notice_card(
            L, notice, mission["metric"], done, goal, pct))
    await challenges.save(poller.store, t.clan.alias, state)


async def _close(poller, t, state, rows):
    mission = state["mission"]
    metric = mission["metric"]
    done, goal, _ = standing(mission, total(rows, metric))
    best = dict(mission.get("best") or {})
    best[metric] = max(int(best.get(metric) or 0), done)
    won = bool(goal) and done >= goal
    helpers = contributors(rows, metric)
    names = [row["name"] for row in helpers[:NAMES]]
    if won:
        badges.grant_all(state, [row["tag"] for row in helpers], "missione", int(t.now.timestamp()))
    await poller.dispatch(t, EVENT, lambda L: closed_card(L, metric, done, goal, names, won))
    challenges.note(state, "mission", metric=metric, done=done, goal=goal, won=won,
                    ts=int(t.now.timestamp()))
    state["mission"] = {"best": best}
