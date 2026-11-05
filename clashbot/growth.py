from . import progress, trend
from .util import to_int

PERIODS = progress.CLOSED
FIELDS = ("donated", "war_stars", "levels", "score")
LINES = ("trophies", "th")


def days_of(trend_state, tags):
    found = set()
    for tag in tags:
        for sample in trend.series(trend_state, tag):
            if sample.get("d"):
                found.add(str(sample["d"]))
    return sorted(found)[-trend.DAYS:]


def _line(samples, days, key):
    by_day = {str(sample.get("d")): sample for sample in samples}
    return [to_int(by_day[day].get(key)) if day in by_day else None for day in days]


def players_of(trend_state, days, tags):
    found = {}
    for tag in tags:
        samples = trend.series(trend_state, tag)
        lines = {key: _line(samples, days, key) for key in LINES}
        if any(value is not None for value in lines["trophies"]):
            found[tag] = lines
    return found


def clan_line(players, days):
    return [sum(row["trophies"][slot] for row in players.values()
                if row["trophies"][slot] is not None) for slot in range(len(days))]


def period_of(progress_state, tags):
    found = {}
    for period in PERIODS:
        rows = {}
        for row in progress.deltas(progress_state, period):
            if row["tag"] in tags:
                rows[row["tag"]] = {field: to_int(row.get(field)) for field in FIELDS}
        found[period] = rows
    return found


def growth_of(trend_state, progress_state, members):
    tags = sorted(members or ())
    days = days_of(trend_state, tags)
    players = players_of(trend_state, days, tags)
    return {"days": days, "players": players,
            "clan": {"trophies": clan_line(players, days)},
            "period": period_of(progress_state, set(tags))}
