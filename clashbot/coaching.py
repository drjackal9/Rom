from .scoring import leaderboard, points as season_points

TRIAL_DAYS = 14
TOP = 3
DAY = 86400
MIN_ATTACKS = 1


def joined(players):
    data = (players or {}).get("joined")
    return data if isinstance(data, dict) else {}


def track(players, members, events, now):
    data = dict(joined(players))
    for event in events or ():
        if event.get("type") == "join" and event.get("tag"):
            data.setdefault(event["tag"], {"ts": now.timestamp(), "told": False})
    for tag in list(data):
        if tag not in (members or {}):
            del data[tag]
    out = dict(players or {})
    out["joined"] = data
    return out


def trial_due(players, members, now):
    cutoff = now.timestamp() - TRIAL_DAYS * DAY
    rows = []
    for tag, info in joined(players).items():
        if info.get("told") or not info.get("ts") or info["ts"] > cutoff:
            continue
        member = (members or {}).get(tag)
        if member is None:
            continue
        rows.append({"tag": tag, "name": member.get("name") or tag, "since": info["ts"]})
    rows.sort(key=lambda row: row["since"])
    return rows


def mark_told(players, tags):
    data = dict(joined(players))
    for tag in tags:
        if tag in data:
            data[tag] = {**data[tag], "told": True}
    out = dict(players or {})
    out["joined"] = data
    return out


def record_of(tag, stats, season, activity):
    war = (stats or {}).get(tag) or {}
    entry = ((season or {}).get("members") or {}).get(tag) or {}
    score = next((row.get("score") or 0 for row in (activity or ()) if row.get("tag") == tag), 0)
    return {
        "wars": war.get("wars", 0), "attacks": war.get("attacks", 0), "stars": war.get("stars", 0),
        "triples": war.get("triples", 0), "missed": war.get("missed", 0),
        "donations": entry.get("donations", 0), "score": score,
        "points": season_points(entry) if entry else 0,
    }


def promotions(members, stats, season, activity, players, now, top=TOP):
    entries = (season or {}).get("members") or {}
    rank = {tag: place + 1 for place, (tag, _, _) in enumerate(leaderboard({"members": entries}))}
    since = joined(players)
    rows = []
    for tag, member in (members or {}).items():
        if (member or {}).get("role") != "member":
            continue
        info = since.get(tag) or {}
        days = int((now.timestamp() - info["ts"]) // DAY) if info.get("ts") else None
        if days is not None and days < TRIAL_DAYS:
            continue
        row = record_of(tag, stats, season, activity)
        if row["missed"] or row["attacks"] < MIN_ATTACKS or row["points"] <= 0:
            continue
        rows.append({"tag": tag, "name": (member or {}).get("name") or tag, "days": days,
                     "rank": rank.get(tag), **row})
    rows.sort(key=lambda row: row["rank"])
    return rows[:top]
