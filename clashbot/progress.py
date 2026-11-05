from datetime import datetime, timedelta, timezone

from . import agenda
from .util import zone

COUNTERS = ("gold", "elixir", "dark", "wins", "games", "raid_loot", "capital_gold", "donated", "war_stars", "levels", "th")

ACHIEVEMENTS = {
    "Gold Grab": "gold",
    "Elixir Escapade": "elixir",
    "Heroic Heist": "dark",
    "Conqueror": "wins",
    "Games Champion": "games",
    "Aggressive Capitalism": "raid_loot",
    "Most Valuable Clanmate": "capital_gold",
    "Friend in Need": "donated",
}
UNITS = ("heroes", "troops", "spells")
PERIODS = ("week", "month", "season")
CLOSED = ("week", "month")
CARRIED = tuple(key for key in COUNTERS if key != "th") + ("loot", "th_up")
DAY = 86400
IDLE_MIN_DAYS = 3


def _int(value):
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _levels(player):
    total = 0
    for key in UNITS:
        for unit in player.get(key) or []:
            if not isinstance(unit, dict) or unit.get("village") != "home":
                continue
            if unit.get("superTroopIsActive"):
                continue
            if str(unit.get("name") or "").startswith("Super "):
                continue
            total += _int(unit.get("level"))
    return total


def counters(player_json):
    player = player_json if isinstance(player_json, dict) else {}
    out = {key: 0 for key in COUNTERS}
    for item in player.get("achievements") or []:
        if not isinstance(item, dict):
            continue
        key = ACHIEVEMENTS.get(item.get("name"))
        if key:
            out[key] = _int(item.get("value"))
    out["war_stars"] = _int(player.get("warStars"))
    out["levels"] = _levels(player)
    out["th"] = _int(player.get("townHallLevel"))
    return out


def _normalize(values):
    source = values if isinstance(values, dict) else {}
    return {key: _int(source.get(key)) for key in COUNTERS}


def _base(values, since):
    base = {"since": int(since)}
    base.update(_normalize(values))
    return base


def period_start(now, tz, period):
    if period == "season":
        return int(agenda.season_start(now.astimezone(timezone.utc)).timestamp())
    local = now.astimezone(zone(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "month":
        local = local.replace(day=1)
    else:
        local = local - timedelta(days=local.weekday())
    return int(local.timestamp())


def update(progress, tag, name, now_counters, now, tz):
    if progress is None:
        progress = {}
    current = _normalize(now_counters)
    now_ts = int(now.timestamp())
    entry = progress.get(tag)
    if not isinstance(entry, dict):
        progress[tag] = {
            "name": name,
            "now": dict(current),
            "last_active": now_ts,
            **{period: _base(current, now_ts) for period in PERIODS},
        }
        return progress
    stored = entry.get("now")
    previous = _normalize(stored) if isinstance(stored, dict) and stored else None
    latest = dict(current) if previous is None else {key: max(current[key], previous[key]) for key in COUNTERS}
    entry.setdefault("last_active", now_ts)
    if previous is not None and any(latest[key] > previous[key] for key in COUNTERS):
        entry["last_active"] = now_ts
    for period in PERIODS:
        base = entry.get(period)
        if not isinstance(base, dict):
            entry[period] = _base(latest, now_ts)
            continue
        start = period_start(now, tz, period)
        if _int(base.get("since")) < start:
            ended = previous if previous is not None else latest
            if period in CLOSED:
                entry[f"last_{period}"] = dict(_row(base, ended), until=start)
            entry[period] = _base(ended, start)
    if name:
        entry["name"] = name
    entry["now"] = latest
    return progress


def parts(delta):
    row = delta if isinstance(delta, dict) else {}
    return {
        "loot": _int(row.get("loot")) // 1_000_000 * 2,
        "wins": _int(row.get("wins")),
        "levels": _int(row.get("levels")) * 3,
        "th_up": _int(row.get("th_up")) * 25,
        "games": _int(row.get("games")) // 100,
        "raid_loot": _int(row.get("raid_loot")) // 100_000,
    }


def score(delta):
    return sum(parts(delta).values())


def _row(base, values):
    row = {"since": _int((base or {}).get("since"))}
    for key in COUNTERS:
        if key == "th":
            continue
        row[key] = max(0, _int((values or {}).get(key)) - _int((base or {}).get(key)))
    row["loot"] = row["gold"] + row["elixir"]
    row["th_up"] = max(0, _int((values or {}).get("th")) - _int((base or {}).get("th")))
    row["score"] = score(row)
    return row


def deltas(progress, period, since=None):
    key_period = period if period in PERIODS else "week"
    floor = _int(since)
    rows = []
    for tag, entry in (progress or {}).items():
        if not isinstance(entry, dict):
            continue
        base = entry.get(key_period)
        if not isinstance(base, dict) or _int(base.get("since")) < floor:
            continue
        row = _row(base, entry.get("now") or {})
        row["tag"] = tag
        row["name"] = entry.get("name") or tag
        rows.append(row)
    rows.sort(key=lambda r: (-r["score"], r["name"] or ""))
    return rows


def window(progress, period, start=None):
    rows = {row["tag"]: row for row in deltas(progress, period)}
    if start is not None:
        floor = _int(start)
        for past in closed(progress, period):
            row = rows.get(past.get("tag"))
            if row is None or _int(past.get("until")) <= floor:
                continue
            for key in CARRIED:
                row[key] = _int(row.get(key)) + _int(past.get(key))
            row["score"] = score(row)
    out = list(rows.values())
    out.sort(key=lambda r: (-r["score"], r["name"] or ""))
    return out


def snapshot(progress, tags, keys):
    out = {}
    for tag in sorted(tags or ()):
        entry = (progress or {}).get(tag)
        if not isinstance(entry, dict):
            continue
        now = entry.get("now")
        if not isinstance(now, dict) or any(key not in now for key in keys):
            continue
        out[tag] = {key: _int(now.get(key)) for key in keys}
    return out


def since(progress, base, keys):
    rows = []
    for tag, start in (base or {}).items():
        entry = (progress or {}).get(tag)
        if not isinstance(entry, dict):
            continue
        now = entry.get("now") or {}
        row = {"tag": tag, "name": entry.get("name") or tag}
        for key in keys:
            row[key] = max(0, _int(now.get(key)) - _int((start or {}).get(key)))
        rows.append(row)
    rows.sort(key=lambda r: r["name"] or "")
    return rows


def idle(progress, now=None):
    if now is None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
    elif isinstance(now, datetime):
        now_ts = int(now.timestamp())
    else:
        now_ts = _int(now)
    rows = []
    for tag, entry in (progress or {}).items():
        if not isinstance(entry, dict):
            continue
        last_active = _int(entry.get("last_active"))
        if not last_active:
            continue
        age = now_ts - last_active
        if age < IDLE_MIN_DAYS * DAY:
            continue
        rows.append({"tag": tag, "name": entry.get("name") or tag, "days": int(age // DAY)})
    rows.sort(key=lambda r: (-r["days"], r["name"] or ""))
    return rows


def prune(progress, member_tags):
    if not isinstance(progress, dict):
        return {}
    keep = set(member_tags or ())
    for tag in [t for t in progress if t not in keep]:
        del progress[tag]
    return progress


def closed(progress, period, until=None):
    key = f"last_{period}"
    end = None if until is None else _int(until)
    rows = []
    for tag, entry in (progress or {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get(key), dict):
            continue
        row = dict(entry[key])
        if end is not None and _int(row.get("until")) != end:
            continue
        row["tag"] = tag
        row["name"] = entry.get("name") or tag
        rows.append(row)
    rows.sort(key=lambda r: (-_int(r.get("score")), r.get("name") or ""))
    return rows
