DAY = 86400
YEAR_DAYS = 365
FORMER_SHOWN = 40


def _int(value):
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def new_row(name, now_ts):
    return {"name": name, "first": now_ts, "joined": now_ts, "seen": now_ts,
            "stints": 1, "days": 0, "anniv": 0, "optout": False}


def tenure_days(row, now_ts):
    if not isinstance(row, dict):
        return 0
    joined = _int(row.get("joined")) or _int(row.get("first"))
    if not joined:
        return _int(row.get("days"))
    return _int(row.get("days")) + max(0, (now_ts - joined) // DAY)


def apply(roster, members, events, now_ts):
    state = roster if isinstance(roster, dict) else {}
    present = members if isinstance(members, dict) else {}
    joined, gone = [], []
    for event in events or ():
        kind = event.get("type")
        tag = event.get("tag")
        if kind == "join" and tag:
            joined.append(tag)
        elif kind == "rename" and isinstance(state.get(tag), dict):
            state[tag]["name"] = event.get("name")
    for tag, member in present.items():
        row = state.get(tag)
        if not isinstance(row, dict):
            state[tag] = new_row(member.get("name"), now_ts)
            continue
        row["seen"] = now_ts
        if member.get("name"):
            row["name"] = member.get("name")
    for tag in [t for t in state if t not in present]:
        row = state.pop(tag)
        if isinstance(row, dict):
            gone.append((tag, row))
    return state, joined, gone


def archive(row, now_ts):
    source = row if isinstance(row, dict) else {}
    joined = _int(source.get("joined")) or _int(source.get("first")) or now_ts
    return {
        "name": source.get("name"),
        "first": _int(source.get("first")) or joined,
        "joined": joined,
        "left": now_ts,
        "stints": max(1, _int(source.get("stints"))),
        "days": tenure_days(source, now_ts),
        "anniv": _int(source.get("anniv")),
        "optout": bool(source.get("optout")),
    }


def readmit(roster, tag, history, now_ts):
    state = roster if isinstance(roster, dict) else {}
    source = history if isinstance(history, dict) else {}
    state[tag] = {
        "name": source.get("name"),
        "first": _int(source.get("first")) or now_ts,
        "joined": now_ts,
        "seen": now_ts,
        "stints": max(1, _int(source.get("stints"))) + 1,
        "days": _int(source.get("days")),
        "anniv": _int(source.get("anniv")),
        "optout": bool(source.get("optout")),
    }
    return state


def return_facts(history, now_ts):
    source = history if isinstance(history, dict) else {}
    return {
        "name": source.get("name"),
        "away": max(0, (now_ts - _int(source.get("left"))) // DAY),
        "days": _int(source.get("days")),
        "stints": max(1, _int(source.get("stints"))),
    }


def anniversaries(roster, now_ts):
    rows = []
    for tag, row in (roster if isinstance(roster, dict) else {}).items():
        if not isinstance(row, dict) or row.get("optout"):
            continue
        first = _int(row.get("first"))
        if not first:
            continue
        years = (now_ts - first) // (YEAR_DAYS * DAY)
        if years >= 1 and years > _int(row.get("anniv")):
            rows.append({"tag": tag, "name": row.get("name"), "years": int(years),
                         "days": (now_ts - first) // DAY})
    rows.sort(key=lambda r: (-r["years"], r["name"] or ""))
    return rows


def mark(roster, tag, years):
    state = roster if isinstance(roster, dict) else {}
    row = state.get(tag)
    if isinstance(row, dict):
        row["anniv"] = _int(years)
    return state


def set_optout(roster, tag, value):
    state = roster if isinstance(roster, dict) else {}
    row = state.get(tag)
    if isinstance(row, dict):
        row["optout"] = bool(value)
    return state


def optout(roster, tag):
    row = (roster if isinstance(roster, dict) else {}).get(tag)
    return bool(row.get("optout")) if isinstance(row, dict) else False


def former_rows(records, now_ts):
    rows = []
    for record in records or ():
        if not isinstance(record, dict):
            continue
        rows.append({
            "name": record.get("name"),
            "away": max(0, (now_ts - _int(record.get("left"))) // DAY),
            "days": _int(record.get("days")),
            "stints": max(1, _int(record.get("stints"))),
        })
    rows.sort(key=lambda r: (r["away"], r["name"] or ""))
    return rows
