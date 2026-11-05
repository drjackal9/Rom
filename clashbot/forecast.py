from . import render_live, scouting
from .events import member_stats, war_key, war_result
from .retention import WAR_HISTORY_KEEP
from .settings import route

STATE = "forecast"
LEDGER = "forecast_log"
BASE = 50
NEUTRAL_STARS = 2.0
FLOOR = 5
CEILING = 95


def stars_per_attack(records):
    stats = member_stats(records or [])
    attacks = sum(row["attacks"] for row in stats.values())
    stars = sum(row["stars"] for row in stats.values())
    return round(stars / attacks, 2) if attacks else NEUTRAL_STARS


def terms(report, history):
    clan, log = report.get("clan") or {}, report.get("log") or {}
    played = log.get("played") or 0
    return [
        ["th", round((report["our_avg"] - report["their_avg"]) * 10)],
        ["heroes", round((report["our_heroes"] - report["their_heroes"]) / 10) if report["their_heroes"] else 0],
        ["history", round((history - NEUTRAL_STARS) * 5)],
        ["streak", -(clan.get("streak") or 0)],
        ["log", round((log.get("wins", 0) - log.get("losses", 0)) / played * 10) if played else 0],
    ]


def estimate(war, report, history):
    rows = terms(report, history)
    size = war.get("teamSize") or report.get("size") or 0
    per_member = war.get("attacksPerMember") or 2
    return {
        "war": war_key(war),
        "opponent": (war.get("opponent") or {}).get("name"),
        "base": BASE,
        "terms": rows,
        "history": history,
        "partial": bool(report.get("partial")),
        "probability": max(FLOOR, min(CEILING, BASE + sum(value for _name, value in rows))),
        "stars_us": min(size * 3, round(size * per_member * history)),
        "stars_them": min(size * 3, round(size * per_member * NEUTRAL_STARS)),
    }


def compare(row, war):
    result = war_result(war)
    return {
        "probability": row.get("probability"),
        "guess_us": row.get("stars_us"),
        "guess_them": row.get("stars_them"),
        "stars_us": war["clan"]["stars"],
        "stars_them": war["opponent"]["stars"],
        "opponent": war["opponent"]["name"],
        "result": result,
        "hit": ((row.get("probability") or 0) >= BASE) == (result == "win"),
    }


def remember(ledger, row, keep=WAR_HISTORY_KEEP):
    rows = [r for r in (ledger or []) if isinstance(r, dict) and r.get("war") != row.get("war")]
    rows.append(row)
    return rows[-keep:]


def accuracy(ledger):
    rows = [r for r in (ledger or []) if isinstance(r, dict)]
    hits = sum(1 for r in rows if r.get("hit"))
    return {"total": len(rows), "hits": hits, "pct": round(hits * 100 / len(rows)) if rows else 0}


async def at_prep(poller, t, war, scout, kind, day):
    if kind != "war" or route(t.settings, "war.forecast")[0] == "off":
        return None
    stored = await poller.store.get_state(t.clan.alias, STATE)
    if isinstance(stored, dict) and stored.get("war") == war_key(war):
        return None
    players = (await poller.store.get_state(t.clan.alias, "players") or {}).get("tags") or {}
    history = stars_per_attack(await poller.store.recent_wars(t.clan.alias))
    row = estimate(war, scouting.report(scout, war, players), history)
    await poller.store.set_state(t.clan.alias, STATE, row)
    await poller.dispatch(t, "war.forecast",
                          lambda L: render_live.forecast_card(L, row, kind, day))
    return row


async def at_end(poller, t, war, kind, day):
    stored = await poller.store.get_state(t.clan.alias, STATE)
    if not isinstance(stored, dict) or stored.get("war") != war_key(war):
        return None
    row = compare(stored, war)
    ledger = remember(await poller.store.get_state(t.clan.alias, LEDGER), dict(row, war=stored["war"]))
    await poller.store.set_state(t.clan.alias, LEDGER, ledger)
    await poller.store.del_state(t.clan.alias, STATE)
    acc = accuracy(ledger)
    await poller.dispatch(t, "war.forecast_result",
                          lambda L: render_live.forecast_result_card(L, row, acc, kind, day))
    return row
