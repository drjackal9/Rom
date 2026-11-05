from . import hero_caps
from .util import to_int

PLAYER_FIELDS = (
    ("th", "plain"), ("trophies", "n"), ("best", "n"), ("warstars", "n"), ("heroes", "n"),
    ("ready", "pct"), ("donations", "n"), ("attackwins", "n"), ("capital", "n"), ("exp", "plain"),
)

CLAN_FIELDS = (
    ("level", "plain"), ("members", "plain"), ("points", "n"), ("streak", "plain"),
    ("wins", "n"), ("minth", "plain"), ("mintrophies", "n"),
)


def player_values(snapshot):
    p = snapshot if isinstance(snapshot, dict) else {}
    heroes = p.get("heroes") if isinstance(p.get("heroes"), dict) else {}
    return {
        "th": to_int(p.get("th")),
        "trophies": to_int(p.get("trophies")),
        "best": to_int(p.get("best")),
        "warstars": to_int(p.get("warStars")),
        "heroes": sum(to_int(v) for v in heroes.values()),
        "ready": hero_caps.readiness(heroes, p.get("th"))["pct"],
        "donations": to_int(p.get("donations")),
        "attackwins": to_int(p.get("attackWins")),
        "capital": to_int(p.get("capital")),
        "exp": to_int(p.get("exp")),
    }


def clan_values(clan_json):
    c = clan_json if isinstance(clan_json, dict) else {}
    return {
        "level": to_int(c.get("clanLevel")),
        "members": to_int(c.get("members")),
        "points": to_int(c.get("clanPoints")),
        "streak": to_int(c.get("warWinStreak")),
        "wins": to_int(c.get("warWins")),
        "minth": to_int(c.get("requiredTownhallLevel")),
        "mintrophies": to_int(c.get("requiredTrophies")),
    }


def compare(fields, left, right):
    rows = []
    for key, mode in fields:
        a = (left or {}).get(key) or 0
        b = (right or {}).get(key) or 0
        winner = "left" if a > b else "right" if b > a else None
        rows.append({"key": key, "mode": mode, "left": a, "right": b, "winner": winner})
    return rows
