from . import retention
from .util import API_LABELS, CLAN_SLOTS

PACK = "recruitment"
EVENTS = ("recruit.application", "recruit.reminder")
KIND = "applications"
STATES = ("pending", "accepted", "rejected", "joined")
DECIDED = ("accepted", "rejected")
GOALS = ("war", "cwl", "capital", "calm")
KEEP = retention.WAR_HISTORY_KEEP
DECIDED_DAYS = retention.APPLICATION_DECIDED_DAYS
STALE_HOURS = 24


def state_of(stored):
    stored = stored if isinstance(stored, dict) else {}
    items = stored.get("items")
    out = {"next": 1, "items": {}, "reminded": stored.get("reminded") or None}
    for key, item in (items if isinstance(items, dict) else {}).items():
        if isinstance(item, dict) and item.get("tag") and item.get("state") in STATES:
            item["id"] = str(key)
            out["items"][str(key)] = item
    try:
        nxt = int(stored.get("next") or 1)
    except (TypeError, ValueError):
        nxt = 1
    used = [int(key) for key in out["items"] if key.isdigit()]
    out["next"] = max(1, nxt, (max(used) + 1) if used else 1)
    return out


def requirement(conf):
    value = (conf or {}).get("min_th")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def meets(conf, snap):
    need = requirement(conf)
    level = (snap or {}).get("th")
    if not need or not isinstance(level, int) or isinstance(level, bool):
        return True
    return level >= need


def goals_of(raw):
    picked = set(raw or ())
    return [goal for goal in GOALS if goal in picked]


def pending(state, user_id=None):
    rows = [item for item in state["items"].values() if item["state"] == "pending"]
    if user_id is not None:
        rows = [item for item in rows if item.get("user_id") == user_id]
    return sorted(rows, key=lambda item: (item.get("ts") or 0, item["id"]))


def find(state, app_id):
    return state["items"].get(str(app_id))


def add(state, tag, snap, user_id, verified, goals, below, now):
    app_id = str(state["next"])
    item = {"id": app_id, "tag": tag, "user_id": user_id, "verified": bool(verified),
            "goals": goals_of(goals), "below": bool(below), "snap": snap or {},
            "state": "pending", "ts": now.timestamp(), "decided": None,
            "by": None, "by_name": None}
    state["next"] = state["next"] + 1
    state["items"][app_id] = item
    return prune(state, now), item


def decide(state, app_id, outcome, by, by_name, now):
    item = find(state, app_id)
    if not item or item["state"] != "pending" or outcome not in DECIDED:
        return state, None
    item.update(state=outcome, decided=now.timestamp(), by=by, by_name=by_name)
    return state, item


def close_joined(state, members, now):
    arrived = []
    for item in state["items"].values():
        if item["state"] in ("pending", "accepted") and item["tag"] in (members or {}):
            item.update(state="joined", decided=item.get("decided") or now.timestamp())
            arrived.append(item)
    return state, arrived


def stale(state, now):
    cutoff = now.timestamp() - STALE_HOURS * 3600
    return [item for item in pending(state) if (item.get("ts") or 0) < cutoff]


def prune(state, now):
    cutoff = now.timestamp() - DECIDED_DAYS * 86400
    for key, item in list(state["items"].items()):
        if item["state"] != "pending" and (item.get("decided") or item.get("ts") or 0) < cutoff:
            del state["items"][key]
    extra = len(state["items"]) - KEEP
    if extra > 0:
        order = sorted((item for item in state["items"].values() if item["state"] != "pending"),
                       key=lambda item: item.get("ts") or 0)
        for item in order[:extra]:
            state["items"].pop(item["id"], None)
    return state


def counts(state):
    rows = pending(state)
    return {"pending": len(rows),
            "below": sum(1 for item in rows if item.get("below")),
            "unverified": sum(1 for item in rows if not item.get("verified"))}


def mark_via(players, tag, now):
    players = dict(players if isinstance(players, dict) else {})
    joined = dict(players.get("joined") or {})
    row = dict(joined.get(tag) or {"ts": now.timestamp(), "told": False})
    row["via"] = "apply"
    joined[tag] = row
    players["joined"] = joined
    return players


def info_fields(clan_json):
    clan_json = clan_json if isinstance(clan_json, dict) else {}
    return {"country": (clan_json.get("location") or {}).get("countryCode"),
            "type": clan_json.get("type"),
            "war_frequency": clan_json.get("warFrequency"),
            "labels": [label["name"] for label in (clan_json.get("labels") or ())
                       if isinstance(label, dict) and label.get("name")]}


def board_row(info, conf, named, code, name=None, tag=None):
    info = info if isinstance(info, dict) else None
    if not info or (info.get("type") or "open") == "closed":
        return None
    try:
        members = int(info.get("members") or 0)
    except (TypeError, ValueError):
        members = 0
    free = CLAN_SLOTS - members
    if free <= 0:
        return None
    labels = [label for label in (info.get("labels") or ()) if isinstance(label, str)]
    return {"code": code, "level": info.get("level"), "members": members, "free": free,
            "league": info.get("league"), "min_th": requirement(conf),
            "country": info.get("country"), "lang": (conf or {}).get("lang"),
            "type": info.get("type"), "war_frequency": info.get("war_frequency"),
            "labels": labels[:API_LABELS],
            "name": name if named else None, "tag": tag if named else None}


def is_verified(row):
    return bool((row or {}).get("verified"))


def matches(row, country=None, min_th=None, lang=None):
    if country and str(row.get("country") or "").upper() != str(country).upper():
        return False
    if lang and row.get("lang") != lang:
        return False
    need = row.get("min_th")
    if min_th is not None and need:
        try:
            return int(min_th) >= int(need)
        except (TypeError, ValueError):
            return True
    return True


def ordered(rows):
    return sorted(rows, key=lambda row: -(row.get("free") or 0))
