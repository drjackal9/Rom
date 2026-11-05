from .leaderboards import PODIUM
from .retention import WAR_HISTORY_KEEP

BEST = PODIUM


def _hits(wars):
    found = {}
    for war in (wars or ())[:WAR_HISTORY_KEEP]:
        for member in (war or {}).get("members") or ():
            name = member.get("name")
            for hit in member.get("attacks") or ():
                hall = hit.get("d_th")
                if not hall or not name:
                    continue
                found.setdefault(str(hall), []).append((name, int(hit.get("stars") or 0)))
    return found


def _best(hits):
    people = {}
    for name, stars in hits:
        seen = people.setdefault(name, {"name": name, "stars": 0, "count": 0})
        seen["stars"] += stars
        seen["count"] += 1
    rows = [{"name": row["name"], "stars": round(row["stars"] / row["count"], 2),
             "count": row["count"]} for row in people.values()]
    rows.sort(key=lambda row: (-row["stars"], -row["count"], row["name"]))
    return rows[:BEST]


def by_th(wars):
    return {hall: {"avg_stars": round(sum(stars for _, stars in hits) / len(hits), 2),
                   "best": _best(hits)}
            for hall, hits in _hits(wars).items()}
