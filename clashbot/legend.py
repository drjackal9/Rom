from .trend import series
from .util import to_int

LEAGUE_ID = 29000022
LEAGUE_NAME = "Legend League"


def in_legend(snapshot):
    if not isinstance(snapshot, dict):
        return False
    return to_int(snapshot.get("league_id")) == LEAGUE_ID or snapshot.get("league") == LEAGUE_NAME


def rows(players, trend_state, members):
    known = members if isinstance(members, dict) else {}
    out = []
    for tag, snapshot in (players if isinstance(players, dict) else {}).items():
        if tag not in known or not in_legend(snapshot):
            continue
        stats = snapshot.get("legend") or {}
        today = to_int(stats.get("trophies")) or to_int(snapshot.get("trophies"))
        samples = series(trend_state, tag)
        before = to_int(samples[-2].get("legend")) if len(samples) >= 2 else 0
        out.append({
            "tag": tag,
            "name": snapshot.get("name"),
            "trophies": today,
            "gained": today - before if before else 0,
            "rank": stats.get("rank"),
            "best_trophies": stats.get("best_trophies"),
            "best_rank": stats.get("best_rank"),
            "best_season": stats.get("best_season"),
        })
    out.sort(key=lambda r: (-r["trophies"], r["name"] or ""))
    return out
