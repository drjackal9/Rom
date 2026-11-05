from .util import zone

WEIGHTS = {"attack": 2, "star": 1, "triple": 3, "missed": -3, "raid_attack": 1, "loot": 10000, "donations": 100, "prediction": 3, "challenge": 3}
POLL_OPTIONS = 4
TITLES = {
    "MVP": "🏆", "Cecchino": "🎯", "Donatore": "🎁", "Razziatore": "⛏️", "Costante": "🛡", "Veggente": "🔮",
    "Farmer": "🏹", "Costruttore": "🏗", "CampioneGiochi": "🎮", "Muro": "🧱",
    "Sapiente": "🧠", "Sfidante": "🤺", "Derby": "🚩", "Torneo": "🥊",
}


def season_id(now, tz="Europe/Rome"):
    return now.astimezone(zone(tz)).strftime("%Y-%m")


def empty_season(sid):
    return {"id": sid, "members": {}, "raids": [], "predictions": {}, "play": {}, "donations_day": None}


def play_entry(season, user_id, name):
    p = season.setdefault("play", {}).setdefault(str(user_id), {"name": name, "quiz": 0, "duels": 0, "points": 0})
    if name:
        p["name"] = name
    return p


def apply_play(season, user_id, name, kind=None, points=None):
    p = play_entry(season, user_id, name)
    if kind in ("quiz", "duels"):
        p[kind] += 1
    p["points"] += WEIGHTS["challenge"] if points is None else int(points)
    return p


def play_board(season):
    rows = list((season.get("play") or {}).items())
    rows.sort(key=lambda kv: (-kv[1]["points"], kv[1]["name"] or ""))
    return rows


def entry(season, tag, name):
    e = season["members"].setdefault(tag, {
        "name": name, "wars": 0, "attacks": 0, "stars": 0, "triples": 0, "missed": 0,
        "raid_attacks": 0, "loot": 0, "donations": 0,
    })
    if name:
        e["name"] = name
    return e


def apply_war(season, record):
    for m in record.get("members", []):
        e = entry(season, m["tag"], m["name"])
        e["wars"] += 1
        e["attacks"] += len(m["attacks"])
        e["stars"] += sum(a["stars"] for a in m["attacks"])
        e["triples"] += sum(1 for a in m["attacks"] if a["stars"] == 3)
        e["missed"] += m.get("missed", 0)


def apply_raid(season, raid):
    key = raid.get("startTime")
    if not key or key in season["raids"]:
        return False
    season["raids"].append(key)
    for m in raid.get("members", []):
        e = entry(season, m.get("tag"), m.get("name"))
        e["raid_attacks"] += m.get("attacks") or 0
        e["loot"] += m.get("capitalResourcesLooted") or 0
    return True


def apply_donations(season, members):
    for tag, m in members.items():
        e = entry(season, tag, m.get("name"))
        e["donations"] = max(e["donations"], m.get("donations") or 0)


def apply_prediction(season, user_id, name, correct):
    p = season["predictions"].setdefault(str(user_id), {"name": name, "correct": 0, "total": 0})
    p["name"] = name or p["name"]
    p["total"] += 1
    if correct:
        p["correct"] += 1


def point_parts(e):
    return {
        "attacks": e["attacks"] * WEIGHTS["attack"],
        "stars": e["stars"] * WEIGHTS["star"],
        "triples": e["triples"] * WEIGHTS["triple"],
        "missed": e["missed"] * WEIGHTS["missed"],
        "raid_attacks": e["raid_attacks"] * WEIGHTS["raid_attack"],
        "loot": e["loot"] // WEIGHTS["loot"],
        "donations": e["donations"] // WEIGHTS["donations"],
    }


def points(e):
    return sum(point_parts(e).values())


def leaderboard(season):
    rows = [(tag, e, points(e)) for tag, e in season["members"].items()]
    rows.sort(key=lambda r: (-r[2], -r[1]["stars"], r[1]["name"] or ""))
    return rows


def _value(row, key):
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def activity_titles(activity):
    rows = [r for r in (activity or []) if isinstance(r, dict)]
    result = {}
    if not rows:
        return result
    for title, metric, value in (
        ("Farmer", lambda r: _value(r, "loot"), lambda r: _value(r, "loot")),
        ("Costruttore", lambda r: _value(r, "levels") * 3 + _value(r, "th_up") * 25,
         lambda r: _value(r, "levels") + _value(r, "th_up")),
        ("CampioneGiochi", lambda r: _value(r, "games"), lambda r: _value(r, "games")),
    ):
        best = max(rows, key=metric)
        if metric(best) > 0:
            result[title] = (best.get("name"), value(best))
    return result


def titles(season, activity=None, *, wall=None, mvp=None):
    members = season["members"]
    result = {}
    board = leaderboard(season)
    if mvp:
        result["MVP"] = tuple(mvp)
    elif board and board[0][2] > 0:
        result["MVP"] = (board[0][1]["name"], board[0][2])
    for title, key in (("Cecchino", "triples"), ("Donatore", "donations"), ("Razziatore", "loot")):
        if members:
            best = max(members.values(), key=lambda e: e[key])
            if best[key] > 0:
                result[title] = (best["name"], best[key])
    steady = [e for e in members.values() if e["missed"] == 0 and e["attacks"] >= 4]
    if steady:
        best = max(steady, key=lambda e: e["attacks"])
        result["Costante"] = (best["name"], best["attacks"])
    seers = [p for p in season.get("predictions", {}).values() if p["correct"] > 0]
    if seers:
        best = max(seers, key=lambda p: (p["correct"], -p["total"]))
        result["Veggente"] = (best["name"], best["correct"])
    play = list((season.get("play") or {}).values())
    for title, key in (("Sapiente", "quiz"), ("Sfidante", "duels")):
        best = max(play, key=lambda p: p.get(key) or 0, default=None)
        if best and (best.get(key) or 0) > 0:
            result[title] = (best["name"], best[key])
    result.update(activity_titles(activity))
    if wall and wall.get("attacked"):
        result["Muro"] = (wall.get("name"), wall.get("stars"))
    return result


def streaks(records):
    streak = {}
    broken = set()
    for record in records:
        for m in record.get("members", []):
            tag = m["tag"]
            if tag in broken:
                continue
            s = streak.setdefault(tag, {"name": m["name"], "streak": 0})
            if m.get("missed", 0) == 0:
                s["streak"] += 1
            else:
                broken.add(tag)
    return streak


def prediction_bucket(stars, max_stars):
    if not max_stars:
        return None
    ratio = stars / max_stars
    if ratio >= 1:
        return 3
    if ratio >= 0.8:
        return 2
    if ratio >= 0.5:
        return 1
    return 0
