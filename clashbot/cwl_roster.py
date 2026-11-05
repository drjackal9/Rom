from .events import member_stats

STATE = "cwl_roster"
IN = "in"
OUT = "out"
UNKNOWN = "unknown"
LINEUP = "lineup"
BONUS = "bonus"
ORDER = {IN: 0, UNKNOWN: 1, OUT: 2}


def registered(cwl, our_tag):
    entry = ((cwl or {}).get("clans") or {}).get(our_tag) or {}
    return {m["tag"]: {"name": m.get("name"), "th": m.get("th")}
            for m in entry.get("members") or [] if m.get("tag")}


def new_state(season):
    return {"season": season, "avail": {}, "bonus": [], "sent": {}}


def for_season(state, season):
    if not state or state.get("season") != season:
        return new_state(season)
    state.setdefault("avail", {})
    state.setdefault("bonus", [])
    state.setdefault("sent", {})
    return state


def marked(state, key):
    return [tag for tag in ((state or {}).get(key) or []) if tag]


def mark(state, key, tag):
    current = marked(state, key)
    state[key] = [one for one in current if one != tag] if tag in current else current + [tag]
    return state


def picked(state):
    return marked(state, LINEUP)


def choose(state, tag):
    return mark(state, LINEUP, tag)


def declare(state, tag, value, user_id=None, ts=None):
    if value not in (IN, OUT) or not tag:
        return state
    state.setdefault("avail", {})[tag] = {"state": value, "by": user_id, "ts": ts}
    return state


def played_days(records, current=None):
    days = {}
    for record in records or []:
        day = record.get("day")
        for m in record.get("members") or []:
            days.setdefault(m["tag"], set()).add(day)
    if current and current.get("day"):
        for tag in (current.get("members") or {}):
            days.setdefault(tag, set()).add(current["day"])
    return {tag: sorted(d for d in values if d) for tag, values in days.items()}


def rows(reg, state, played, records=None, players=None):
    stats = member_stats(records or [])
    avail = (state or {}).get("avail") or {}
    out = []
    for tag, info in (reg or {}).items():
        snap = (players or {}).get(tag) or {}
        declared = (avail.get(tag) or {}).get("state")
        if declared not in (IN, OUT):
            declared = OUT if snap.get("warPref") == "out" else UNKNOWN
        s = stats.get(tag) or {}
        mine = list((played or {}).get(tag) or [])
        out.append({
            "tag": tag,
            "name": info.get("name") or snap.get("name") or "?",
            "th": info.get("th") or snap.get("th"),
            "state": declared,
            "declared": (avail.get(tag) or {}).get("state") in (IN, OUT),
            "days": len(mine),
            "day_list": mine,
            "stars": s.get("stars", 0),
            "missed": s.get("missed", 0),
        })
    out.sort(key=lambda r: (ORDER[r["state"]], r["days"], r["missed"], -r["stars"],
                            -(r["th"] or 0), r["name"]))
    return out


def lineup(rows, size=None, chosen=None):
    rows = list(rows)
    room = len(rows) if not size else max(0, int(size))
    wanted = set(chosen or ())
    keep = set()
    for row in rows:
        if row["tag"] in wanted and len(keep) < room:
            keep.add(row["tag"])
    for row in rows:
        if len(keep) >= room:
            break
        keep.add(row["tag"])
    return ([row for row in rows if row["tag"] in keep],
            [row for row in rows if row["tag"] not in keep])
