from . import availability, discipline, forecast, render_live, scouting
from .events import due_reminders, missing_attackers, new_attacks, war_key, war_result
from .settings import route
from .targets import best_by_defender
from .util import parse_coc_time

LAST_CALL = 1800
RISK_CHECKPOINTS = (14400, 3600)
STATE = "war_live"


def state_key(kind):
    return STATE if kind == "war" else f"cwl_{STATE}"


def _left_by(old, tag, stars):
    for m in (old.get("members") or {}).values():
        for a in m.get("attacks", []):
            if a.get("defender") == tag and a.get("stars", 0) == stars:
                return m.get("name")
    return None


def cleanups(old, new):
    if not old or not new:
        return []
    before = best_by_defender(old.get("members"))
    fresh = sorted(new_attacks(old.get("members") or {}, new.get("members") or {}),
                   key=lambda row: row[1].get("order", 0))
    who = {}
    rows = []
    for m, a, _n in fresh:
        tag = a.get("defender")
        if not tag:
            continue
        stars = a.get("stars", 0)
        was = before.get(tag, 0)
        if 1 <= was <= 2 and stars > was:
            defender = (new.get("defenders") or {}).get(tag) or {}
            rows.append({
                "name": m.get("name"), "pos": defender.get("pos"), "defender": defender.get("name"),
                "stars": stars, "was": was, "left_by": who.get(tag) or _left_by(old, tag, was),
                "finished": stars == 3, "order": a.get("order", 0),
            })
        if stars > was:
            before[tag] = stars
            who[tag] = m.get("name")
    return rows


def state_for(stored, war):
    key = war_key(war)
    if not isinstance(stored, dict) or stored.get("war") != key:
        return {"war": key, "midway": False, "risk": False, "last_call": [], "cleaned": 0}
    state = dict(stored)
    state["last_call"] = list(state.get("last_call") or ())
    state.setdefault("midway", False)
    state.setdefault("risk", False)
    state.setdefault("cleaned", 0)
    return state


def last_call(war, done, now):
    if war.get("state") != "inWar":
        return []
    if not due_reminders(war, [], now, checkpoints=(LAST_CALL,)):
        return []
    already = set(done or ())
    return [m for m in missing_attackers(war) if m["tag"] not in already]


def stars_to_win(war):
    return max(0, war["opponent"]["stars"] - war["clan"]["stars"] + 1)


def reachable(war):
    best = best_by_defender(war.get("members"))
    room = sorted((3 - best.get(tag, 0) for tag in (war.get("defenders") or {})), reverse=True)
    left = sum(m["left"] for m in missing_attackers(war))
    return sum(room[:left])


def midway_at(war):
    start = parse_coc_time(war.get("startTime"))
    end = parse_coc_time(war.get("endTime"))
    if not start or not end:
        return None
    return start + (end - start) / 2


def midway(war, now):
    at = midway_at(war)
    if war.get("state") != "inWar" or not at or now < at:
        return None
    return {"need": stars_to_win(war), "reachable": reachable(war), "missing": missing_attackers(war)}


def risk(war, now):
    if war.get("state") != "inWar" or war_result(war) == "win":
        return None
    if not due_reminders(war, [], now, checkpoints=RISK_CHECKPOINTS):
        return None
    missing = missing_attackers(war)
    if not missing:
        return None
    return {"need": stars_to_win(war), "reachable": reachable(war), "missing": missing}


async def run(poller, t, old, new, kind, day, events):
    key = state_key(kind)
    stored = await poller.store.get_state(t.clan.alias, key)
    state = state_for(stored, new)
    kinds = {e["type"] for e in events or ()}
    if kind == "war" and "war_prep" in kinds:
        await availability.open_for(poller, t, new)
    if kind == "war" and "war_start" in kinds:
        await availability.settle(poller, t, new, kind, day)
    if kind == "war":
        scout = await scouting.tick(poller, t, new, kind, day)
        if "war_start" in kinds:
            scout = await scouting.at_start(poller, t, new, kind, day) or scout
        if scout and scout.get("sent"):
            await forecast.at_prep(poller, t, new, scout, kind, day)
        if "war_end" in kinds:
            await forecast.at_end(poller, t, new, kind, day)
            await discipline.propose(poller, t, new, kind, day)
            await scouting.forget(poller, t)
    rows = cleanups(old, new)
    if rows:
        state["cleaned"] += len(rows)
        if route(t.settings, "war.attack")[1] != "summary":
            await poller.dispatch(t, "war.cleanup",
                                  lambda L: render_live.cleanup_card(L, rows, kind, day))
    if not state["midway"]:
        info = midway(new, t.now)
        if info:
            await poller.dispatch(
                t, "war.midway",
                lambda L, info=info: render_live.midway_card(L, t.tz, new, info, state["cleaned"], kind, day, t.now),
            )
            state["midway"] = True
    if not state["risk"]:
        info = risk(new, t.now)
        if info:
            await poller.dispatch(
                t, "war.risk",
                lambda L, info=info: render_live.risk_card(L, t.tz, new, info, kind, day, t.now),
            )
            state["risk"] = True
    pending = last_call(new, state["last_call"], t.now)
    if pending:
        names = await poller.names_map(t, new)
        rows = [m for m in pending if t.links.get(m["tag"])]
        if rows:
            plan = await poller.plan_for(t, new)
            await poller.dispatch(
                t, "war.last_call",
                lambda L: render_live.last_call_card(L, new, rows, kind, day, t.now, plan, names),
                nudged={"war": war_key(new),
                        "tags": [m["tag"] for m in rows if names.get(m["tag"])]},
            )
            await poller.whisper_war(t, "war.last_call", new, rows, kind, day, plan)
            state["last_call"].extend(m["tag"] for m in rows)
    if state != stored:
        await poller.store.set_state(t.clan.alias, key, state)
