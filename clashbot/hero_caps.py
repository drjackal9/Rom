from .util import to_int

ORDER = ("Barbarian King", "Archer Queen", "Minion Prince", "Grand Warden", "Royal Champion")

HERO_MAX = {
    "Barbarian King": {7: 5, 8: 10, 9: 30, 10: 40, 11: 50, 12: 65, 13: 75, 14: 80, 15: 90, 16: 95, 17: 100},
    "Archer Queen": {9: 30, 10: 40, 11: 50, 12: 65, 13: 75, 14: 80, 15: 90, 16: 95, 17: 100},
    "Minion Prince": {9: 20, 10: 30, 11: 40, 12: 50, 13: 60, 14: 65, 15: 70, 16: 75, 17: 90},
    "Grand Warden": {11: 20, 12: 40, 13: 50, 14: 55, 15: 65, 16: 70, 17: 75},
    "Royal Champion": {13: 25, 14: 30, 15: 40, 16: 45, 17: 50},
}

SLUGS = {"Barbarian King": "bk", "Archer Queen": "aq", "Minion Prince": "mp",
         "Grand Warden": "gw", "Royal Champion": "rc"}

TOP_TH = max(max(table) for table in HERO_MAX.values())


def cap(hero, th):
    table = HERO_MAX.get(hero)
    level = to_int(th)
    if not table or not level:
        return 0
    best = 0
    for known, value in table.items():
        if known <= level and value > best:
            best = value
    return best


def readiness(heroes, th):
    levels = heroes if isinstance(heroes, dict) else {}
    rows, have, total = [], 0, 0
    for hero in ORDER:
        ceiling = cap(hero, th)
        if not ceiling:
            continue
        level = to_int(levels.get(hero))
        rows.append({"hero": hero, "level": level, "max": ceiling})
        have += min(level, ceiling)
        total += ceiling
    return {"rows": rows, "pct": round(100 * have / total, 1) if total else 0.0}


def clan_readiness(players, members):
    known = members if isinstance(members, dict) else {}
    values = [
        readiness(snapshot.get("heroes"), snapshot.get("th"))["pct"]
        for tag, snapshot in (players if isinstance(players, dict) else {}).items()
        if tag in known and isinstance(snapshot, dict)
    ]
    return round(sum(values) / len(values), 1) if values else 0.0
