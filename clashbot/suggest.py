from .events import missing_attackers
from .targets import plan_rows
from .warstats import overall_rate, smoothed_rate, th_delta, triple_rates


def power(snapshot):
    return sum(int(level or 0) for level in ((snapshot or {}).get("heroes") or {}).values())


def free_attackers(war, players):
    rows = []
    for m in missing_attackers(war or {}):
        snapshot = (players or {}).get(m["tag"]) or {}
        th = ((war.get("members") or {}).get(m["tag"]) or {}).get("th") or snapshot.get("th")
        rows.append({"name": m["name"], "th": th, "power": power(snapshot), "ratio": 0.0})
    best = {}
    for row in rows:
        best[row["th"]] = max(best.get(row["th"]) or 0, row["power"])
    for row in rows:
        top = best.get(row["th"]) or 0
        row["ratio"] = row["power"] / top if top else 0.0
    return rows


def suggestions(war, players, plan=None, records=None, per_target=3):
    if not war:
        return []
    buckets = triple_rates(records)
    prior = overall_rate(records)
    weight = int(war.get("attacksPerMember") or 2)
    free = free_attackers(war, players)
    rows = []
    for target in plan_rows(war, plan):
        if target["best"] >= 3:
            continue
        picks = []
        for candidate in free:
            delta = th_delta(candidate["th"], target.get("th"))
            if delta is None:
                continue
            picks.append({
                "name": candidate["name"], "th": candidate["th"], "delta": delta,
                "rate": smoothed_rate(buckets, delta, prior, weight),
                "ratio": candidate["ratio"], "power": candidate["power"],
            })
        picks.sort(key=lambda p: (-p["rate"], -p["ratio"], p["name"] or ""))
        rows.append({"pos": target["pos"], "name": target["name"], "th": target.get("th"),
                     "best": target["best"], "assignee": target.get("assignee"),
                     "picks": picks[:per_target]})
    return rows
