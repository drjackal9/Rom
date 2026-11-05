from datetime import datetime, timedelta, timezone

from . import agenda, progress as progress_mod, scoring

PERIODS = ("week", "month", "season")
TABS = ("mvp", "points", "farm", "upgrade", "wins", "games", "donations", "trophies", "capital",
        "stars", "hall", "network")
TAB_PERIODS = {
    "mvp": ("month", "season"),
    "points": ("month",),
    "farm": PERIODS,
    "upgrade": PERIODS,
    "wins": PERIODS,
    "games": PERIODS,
    "donations": PERIODS,
    "trophies": PERIODS,
    "capital": PERIODS,
    "stars": PERIODS,
    "hall": (),
    "network": ("week",),
}
STATE_KIND = "leaderboards"
TOP = 10
PODIUM = 3
METRIC_KEYS = {
    "farm": ("loot", "dark"),
    "upgrade": ("levels", "th_up"),
    "wins": ("wins", None),
    "games": ("games", None),
    "capital": ("raid_loot", "capital_gold"),
}
MVP_PARTS = ("attacks", "stars", "triples", "missed", "raid_attacks", "loot", "donations",
             "farm", "wins", "levels", "th_up", "games")
MVP_WEIGHTS = {
    "attacks": scoring.WEIGHTS["attack"],
    "stars": scoring.WEIGHTS["star"],
    "triples": scoring.WEIGHTS["triple"],
    "missed": scoring.WEIGHTS["missed"],
    "raid_attacks": scoring.WEIGHTS["raid_attack"],
    "loot": scoring.WEIGHTS["loot"],
    "donations": scoring.WEIGHTS["donations"],
    "farm": 2,
    "wins": 1,
    "levels": 3,
    "th_up": 25,
    "games": 100,
}
ACTIVITY_PARTS = {"farm": "loot", "wins": "wins", "levels": "levels", "th_up": "th_up", "games": "games"}
EMPTY_ENTRY = {"wars": 0, "attacks": 0, "stars": 0, "triples": 0, "missed": 0,
               "raid_attacks": 0, "loot": 0, "donations": 0}


def default_period(tab):
    periods = TAB_PERIODS.get(tab) or ()
    return periods[0] if periods else None


def window(now, tz, period, goldpass_end=None):
    if period == "season":
        return agenda.season_window(now.astimezone(timezone.utc), goldpass_end)
    start = datetime.fromtimestamp(progress_mod.period_start(now, tz, period), timezone.utc)
    return start, now


def period_id(now, tz, period, goldpass_end=None):
    start, end = window(now, tz, period, goldpass_end)
    if period == "week":
        return start.astimezone(progress_mod.zone(tz)).strftime("%G-W%V")
    if period == "season":
        return end.astimezone(timezone.utc).strftime("%Y-%m")
    return scoring.season_id(now, tz)


def closed_window(now, tz, period):
    end = datetime.fromtimestamp(progress_mod.period_start(now, tz, period), timezone.utc)
    start = datetime.fromtimestamp(progress_mod.period_start(end - timedelta(seconds=1), tz, period),
                                   timezone.utc)
    return start, end


def closed_period_id(now, tz, period):
    return period_id(closed_window(now, tz, period)[0], tz, period)


def _trophies(state):
    stored = state.get("trophies") if isinstance(state, dict) else None
    return stored if isinstance(stored, dict) else {}


def update_trophies(state, members, now, tz, goldpass_end=None):
    if not isinstance(state, dict):
        state = {}
    stored = _trophies(state)
    current = {tag: int(m.get("trophies") or 0) for tag, m in (members or {}).items()}
    for period in PERIODS:
        since = int(window(now, tz, period, goldpass_end)[0].timestamp())
        base = stored.get(period)
        if not isinstance(base, dict) or int(base.get("since") or 0) < since:
            if isinstance(base, dict) and period == "week":
                stored["last_week"] = {"until": since, "base": dict(base.get("base") or {}),
                                       "final": dict(current)}
            stored[period] = {"since": since, "base": dict(current)}
            continue
        kept = base.get("base") if isinstance(base.get("base"), dict) else {}
        stored[period] = {"since": int(base.get("since") or since),
                          "base": {tag: int(kept.get(tag, value)) for tag, value in current.items()}}
    state["trophies"] = stored
    return state


def _trophy_rows(base, values, members):
    rows = []
    for tag, m in (members or {}).items():
        if tag not in (values or {}):
            continue
        value = int(values.get(tag) or 0)
        rows.append({"tag": tag, "name": (m or {}).get("name") or tag, "value": value,
                     "delta": value - int((base or {}).get(tag, value)),
                     "extra": int((m or {}).get("th") or 0)})
    rows.sort(key=lambda r: (-r["value"], r["name"] or ""))
    return rows


def trophy_rows(state, members, period):
    base = (_trophies(state).get(period) or {}).get("base") or {}
    values = {tag: int((m or {}).get("trophies") or 0) for tag, m in (members or {}).items()}
    return _trophy_rows(base, values, members)


def closed_trophy_rows(state, members, until=None):
    stored = _trophies(state).get("last_week")
    stored = stored if isinstance(stored, dict) else {}
    if until is not None and int(stored.get("until") or 0) != int(until):
        return []
    return _trophy_rows(stored.get("base"), stored.get("final"), members)


def _keep(tag, excluded):
    return tag not in (excluded or ())


def metric_rows(tab, deltas, excluded=None):
    key, extra = METRIC_KEYS[tab]
    rows = []
    for r in deltas or ():
        value = int(r.get(key) or 0)
        if value <= 0 or not _keep(r.get("tag"), excluded):
            continue
        rows.append({"tag": r.get("tag"), "name": r.get("name") or r.get("tag"), "value": value,
                     "delta": value, "extra": int(r.get(extra) or 0) if extra else 0})
    rows.sort(key=lambda r: (-r["value"], r["name"] or ""))
    return rows[:TOP]


def donation_rows(period, deltas, season, members, excluded=None):
    if period == "month":
        source = [(tag, e.get("name"), int(e.get("donations") or 0))
                  for tag, e in ((season or {}).get("members") or {}).items()]
    else:
        source = [(r.get("tag"), r.get("name"), int(r.get("donated") or 0)) for r in deltas or ()]
    rows = []
    for tag, name, value in source:
        if value <= 0 or not _keep(tag, excluded):
            continue
        rows.append({"tag": tag, "name": name or tag, "value": value, "delta": value,
                     "extra": int(((members or {}).get(tag) or {}).get("received") or 0)})
    rows.sort(key=lambda r: (-r["value"], r["name"] or ""))
    return rows[:TOP]


def star_rows(stats, excluded=None):
    rows = []
    for tag, s in (stats or {}).items():
        value = int(s.get("stars") or 0)
        if value <= 0 or not _keep(tag, excluded):
            continue
        rows.append({"tag": tag, "name": s.get("name") or tag, "value": value,
                     "delta": int(s.get("triples") or 0), "extra": int(s.get("attacks") or 0)})
    rows.sort(key=lambda r: (-r["value"], -r["delta"], r["name"] or ""))
    return rows[:TOP]


def donation_debt(members, excluded=None):
    rows = []
    for tag, m in (members or {}).items():
        given, received = int(m.get("donations") or 0), int(m.get("received") or 0)
        if received <= given or not _keep(tag, excluded):
            continue
        rows.append({"tag": tag, "name": m.get("name") or tag, "value": given,
                     "delta": given - received, "extra": received})
    rows.sort(key=lambda r: (r["delta"], r["name"] or ""))
    return rows


def climbers(rows, n=3):
    gained = [r for r in rows or () if int(r.get("delta") or 0) > 0]
    gained.sort(key=lambda r: (-int(r.get("delta") or 0), r.get("name") or ""))
    return gained[:n]


def activity_climbers(deltas, excluded=None, n=3):
    rows = []
    for r in deltas or ():
        tag = r.get("tag")
        if not _keep(tag, excluded):
            continue
        rows.append({"tag": tag, "name": r.get("name") or tag, "delta": progress_mod.score(r)})
    return climbers(rows, n)


def _best(rows):
    for r in rows or ():
        value = int(r.get("value") or 0)
        if value > 0:
            return {"name": r.get("name"), "value": value}
    return None


def record_candidates(rows_farm, rows_donations, streaks):
    best_streak = None
    for s in (streaks or {}).values():
        value = int(s.get("streak") or 0)
        if value > 0 and (best_streak is None or value > best_streak["value"]):
            best_streak = {"name": s.get("name"), "value": value}
    return {"farm": _best(rows_farm), "donations": _best(rows_donations),
            "attack_streak": best_streak}


def window_entries(period, season, stats, deltas):
    if period == "month":
        return {tag: dict(e) for tag, e in ((season or {}).get("members") or {}).items()}
    entries = {}
    for tag, s in (stats or {}).items():
        entry = dict(EMPTY_ENTRY)
        entry.update({"name": s.get("name") or tag, "wars": int(s.get("wars") or 0),
                      "attacks": int(s.get("attacks") or 0), "stars": int(s.get("stars") or 0),
                      "triples": int(s.get("triples") or 0), "missed": int(s.get("missed") or 0)})
        entries[tag] = entry
    for r in deltas or ():
        tag = r.get("tag")
        entry = entries.get(tag)
        if entry is None:
            entry = dict(EMPTY_ENTRY)
            entry["name"] = r.get("name") or tag
            entries[tag] = entry
        entry["loot"] = int(r.get("raid_loot") or 0)
        entry["donations"] = int(r.get("donated") or 0)
    return entries


def week_report(state, members, deltas, season, excluded=None, until=None):
    hidden = set(excluded or ())
    farm = metric_rows("farm", deltas, hidden)
    donations = donation_rows("week", deltas, season, members, hidden)
    trophies = [r for r in closed_trophy_rows(state, members, until) if r["tag"] not in hidden][:TOP]
    return {
        "farm": farm,
        "donations": donations,
        "trophies": trophies,
        "blocks": [("farm", farm[:PODIUM]), ("donations", donations[:PODIUM]),
                   ("trophies", trophies[:PODIUM])],
        "climb": climbers(trophies),
        "climb_points": activity_climbers(deltas, hidden),
    }


def season_leagues(players, members):
    rows = []
    for tag, snap in (players or {}).items():
        if tag not in (members or {}) or not isinstance(snap, dict):
            continue
        league = snap.get("league")
        if not league:
            continue
        rows.append({"name": snap.get("name") or ((members[tag] or {}).get("name") or tag),
                     "league": league, "trophies": int(snap.get("trophies") or 0)})
    rows.sort(key=lambda r: (-r["trophies"], r["name"] or ""))
    return rows


def mvp_rows(period, season, stats, deltas, excluded=None):
    entries = window_entries(period, season, stats, deltas)
    by_tag = {r.get("tag"): r for r in deltas or ()}
    rows = []
    for tag, entry in entries.items():
        if not _keep(tag, excluded):
            continue
        parts = scoring.point_parts(entry)
        activity = progress_mod.parts(by_tag.get(tag) or {})
        for part, key in ACTIVITY_PARTS.items():
            parts[part] = activity[key]
        total = sum(parts.values())
        rows.append({"tag": tag, "name": entry.get("name") or tag, "value": total, "total": total,
                     "delta": total, "extra": int(entry.get("attacks") or 0), "parts": parts})
    rows.sort(key=lambda r: (-r["total"], r["name"] or ""))
    return rows[:TOP]


def network_payload(clan_name, tag, week, deltas, stats, members):
    rows = list(deltas or ())
    known = max(len(rows), len(members or {}))
    total = sum(progress_mod.score(r) for r in rows)
    return {
        "name": clan_name,
        "tag": tag,
        "week": week,
        "metrics": {
            "members": known,
            "avg": round(total / known, 1) if known else 0,
            "stars": sum(int(s.get("stars") or 0) for s in (stats or {}).values()),
            "donations": sum(int(r.get("donated") or 0) for r in rows),
        },
    }


def network_position(board, alias):
    for i, row in enumerate(board or (), start=1):
        if row.get("alias") == alias:
            return i
    return None
