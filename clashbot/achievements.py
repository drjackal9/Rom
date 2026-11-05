from .progress import counters

HERO_IT = {
    "Barbarian King": "Re Barbaro",
    "Archer Queen": "Regina degli Arcieri",
    "Grand Warden": "Gran Custode",
    "Royal Champion": "Campionessa Reale",
    "Minion Prince": "Principe dei Tirapiedi",
}
HERO_STEP = 5
STAR_STEP = 500
BEST_STEP = 500
FULL_STARS = 3


def legend_stats(p):
    stats = p.get("legendStatistics") or {}
    current = stats.get("currentSeason") or {}
    best = stats.get("bestSeason") or {}
    return {
        "trophies": current.get("trophies"),
        "rank": current.get("rank"),
        "best_trophies": best.get("trophies"),
        "best_rank": best.get("rank"),
        "best_season": best.get("id"),
    }


def achievement_map(p):
    out = {}
    for item in p.get("achievements") or []:
        if not isinstance(item, dict) or item.get("village") != "home":
            continue
        name = item.get("name")
        stars = item.get("stars")
        if not name or not isinstance(stars, int) or isinstance(stars, bool):
            continue
        if stars < FULL_STARS:
            out[name] = stars
    return out


def achievement_events(old, new):
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []
    before_map, after_map = old.get("ach"), new.get("ach")
    if not isinstance(before_map, dict) or not isinstance(after_map, dict):
        return []
    events = []
    for goal in sorted(set(before_map) | set(after_map)):
        before = before_map.get(goal, FULL_STARS)
        after = after_map.get(goal, FULL_STARS)
        if after > before:
            events.append({"type": "stars", "name": new.get("name"), "goal": goal,
                           "stars": after, "gained": after - before})
    return events


def player_snapshot(p):
    heroes = {h.get("name"): h.get("level") for h in p.get("heroes", []) if h.get("village") == "home"}
    league = p.get("league") or {}
    return {
        "name": p.get("name"),
        "th": p.get("townHallLevel"),
        "trophies": p.get("trophies"),
        "best": p.get("bestTrophies"),
        "bh": p.get("builderHallLevel"),
        "bb": p.get("builderBaseTrophies"),
        "bb_best": p.get("bestBuilderBaseTrophies"),
        "warStars": p.get("warStars"),
        "league_id": league.get("id"),
        "league": league.get("name"),
        "heroes": heroes,
        "warPref": p.get("warPreference"),
        "donations": p.get("donations"),
        "received": p.get("donationsReceived"),
        "attackWins": p.get("attackWins"),
        "capital": p.get("clanCapitalContributions"),
        "exp": p.get("expLevel"),
        "role": p.get("role"),
        "clan": (p.get("clan") or {}).get("tag"),
        "labels": [lab.get("name") for lab in (p.get("labels") or []) if lab.get("name")],
        "legend": legend_stats(p),
        "ach": achievement_map(p),
        "counters": counters(p),
    }


def _crossed(old, new, step):
    if old is None or new is None:
        return None
    before, after = int(old) // step, int(new) // step
    return after * step if after > before else None


def player_events(old, new):
    events = []
    if not old or not new:
        return events
    name = new.get("name")
    if old.get("th") and new.get("th") and new["th"] > old["th"]:
        events.append({"type": "th", "name": name, "level": new["th"]})
    for hero, level in (new.get("heroes") or {}).items():
        before = (old.get("heroes") or {}).get(hero)
        if before is not None and level is not None and level > before and level % HERO_STEP == 0:
            events.append({"type": "hero", "name": name, "hero": HERO_IT.get(hero, hero), "level": level})
    if old.get("league_id") and new.get("league_id") and new["league_id"] > old["league_id"]:
        events.append({"type": "league", "name": name, "league": new.get("league")})
    milestone = _crossed(old.get("warStars"), new.get("warStars"), STAR_STEP)
    if milestone:
        events.append({"type": "warstars", "name": name, "value": milestone})
    milestone = _crossed(old.get("best"), new.get("best"), BEST_STEP)
    if milestone:
        events.append({"type": "record", "name": name, "value": new.get("best")})
    events += achievement_events(old, new)
    return events
