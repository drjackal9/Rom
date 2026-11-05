from . import leaderboards, progress, warstats

PERIOD = "month"
FIELDS = ("score", "wins", "war_stars", "donated", "levels")


def season_of(now, tz):
    return leaderboards.closed_period_id(now, tz, PERIOD)


def won_in(medals, start, end):
    found = {}
    for tag, marks in (medals or {}).items():
        kept = [row["badge"] for row in marks or ()
                if start <= int((row or {}).get("ts") or 0) < end]
        if kept:
            found[tag] = kept
    return found


def build(walked, medals, members, now, tz):
    sid = season_of(now, tz)
    rows = [row for row in progress.closed(walked, PERIOD, progress.period_start(now, tz, PERIOD))
            if row["tag"] in (members or {})]
    if not rows:
        return None
    start = int(warstats.month_start(sid, tz).timestamp())
    end = int(warstats.month_end(sid, tz).timestamp())
    return {
        "season": sid,
        "players": [dict({"tag": row["tag"], "name": row["name"]},
                         **{name: int(row.get(name) or 0) for name in FIELDS}) for row in rows],
        "medals": won_in(medals, start, end),
    }
