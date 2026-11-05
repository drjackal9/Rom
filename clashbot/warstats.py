from datetime import datetime, timezone

from .agenda import next_month
from .retention import WAR_HISTORY_KEEP
from .util import parse_coc_time, zone

DELTA_CAP = 2
VALUE_RECORDS = ("farm", "donations", "attack_streak")
RECORD_KEYS = ("streak", "destr", "stars", "perfect") + VALUE_RECORDS


def war_defense(war):
    rows = {}
    for tag, m in ((war or {}).get("members") or {}).items():
        rows[tag] = {"tag": tag, "name": m.get("name"), "pos": m.get("pos"),
                     "stars": 0, "destr": 0, "hits": 0}
    for m in ((war or {}).get("defenders") or {}).values():
        for a in m.get("attacks") or []:
            row = rows.get(a.get("defender"))
            if not row:
                continue
            row["hits"] += 1
            if (a.get("stars") or 0, a.get("destr") or 0) > (row["stars"], row["destr"]):
                row["stars"] = a.get("stars") or 0
                row["destr"] = a.get("destr") or 0
    return sorted(rows.values(), key=lambda r: (r["pos"] or 99, r["tag"]))


def th_delta(mine, theirs):
    if not mine or not theirs:
        return None
    return max(-DELTA_CAP, min(DELTA_CAP, int(mine) - int(theirs)))


def _empty_opponent(tag, name):
    return {"tag": tag, "name": name, "wars": 0, "wins": 0, "losses": 0, "ties": 0,
            "stars": 0, "opp_stars": 0, "last": None, "last_result": None,
            "last_stars": 0, "last_opp_stars": 0}


def _add_opponent(row, record):
    row["tag"] = row["tag"] or record.get("opp_tag")
    row["name"] = record.get("opponent") or row["name"]
    row["wars"] += 1
    result = record.get("result")
    row["wins" if result == "win" else "losses" if result == "lose" else "ties"] += 1
    row["stars"] += int(record.get("stars") or 0)
    row["opp_stars"] += int(record.get("opp_stars") or 0)
    end = parse_coc_time(record.get("endTime"))
    if end and (row["last"] is None or end > row["last"]):
        row["last"] = end
        row["last_result"] = result
        row["last_stars"] = int(record.get("stars") or 0)
        row["last_opp_stars"] = int(record.get("opp_stars") or 0)


def _opponent_key(record):
    return record.get("opp_tag") or (record.get("opponent") or "").strip().lower()


def opponents(records):
    rows = {}
    for record in records or []:
        key = _opponent_key(record)
        if not key:
            continue
        row = rows.get(key)
        if row is None:
            row = rows[key] = _empty_opponent(record.get("opp_tag"), record.get("opponent"))
        _add_opponent(row, record)
    return sorted(rows.values(), key=lambda r: (-r["wars"], -(r["last"].timestamp() if r["last"] else 0),
                                                r["name"] or ""))


def opponent_row(records, tag=None, name=None):
    wanted = (name or "").strip().lower() or None
    row = _empty_opponent(tag, name)
    for record in records or []:
        stored = record.get("opp_tag")
        if stored and tag:
            match = stored == tag
        elif stored or not wanted:
            match = False
        else:
            match = (record.get("opponent") or "").strip().lower() == wanted
        if match:
            _add_opponent(row, record)
    return row if row["wars"] else None


def defense_rows(records):
    rows = {}
    for record in records or []:
        for m in record.get("members") or []:
            d = m.get("def")
            if not isinstance(d, dict) or not m.get("tag"):
                continue
            row = rows.get(m["tag"])
            if row is None:
                row = rows[m["tag"]] = {"tag": m["tag"], "name": m.get("name"), "wars": 0, "attacked": 0,
                                        "stars": 0, "hits": 0, "destr": 0.0, "clean": 0, "avg": None}
            row["name"] = m.get("name") or row["name"]
            hits = int(d.get("hits") or 0)
            stars = int(d.get("stars") or 0)
            row["wars"] += 1
            row["hits"] += hits
            if hits:
                row["attacked"] += 1
                row["stars"] += stars
                row["destr"] += float(d.get("destr") or 0)
                if not stars:
                    row["clean"] += 1
    for row in rows.values():
        row["avg"] = row["stars"] / row["attacked"] if row["attacked"] else None
    return sorted(rows.values(), key=lambda r: (r["avg"] is None, r["avg"] or 0.0, -r["attacked"],
                                                r["name"] or ""))


def wall(rows):
    picked = [r for r in rows or [] if r.get("attacked")]
    if not picked:
        return None
    prior = sum(r["stars"] for r in picked) / sum(r["attacked"] for r in picked)
    return min(picked, key=lambda r: ((r["stars"] + prior) / (r["attacked"] + 1), -r["attacked"],
                                      r["name"] or ""))


def triple_rates(records):
    buckets = {}
    for record in records or []:
        for m in record.get("members") or []:
            for a in m.get("attacks") or []:
                delta = th_delta(m.get("th"), a.get("d_th"))
                if delta is None:
                    continue
                bucket = buckets.get(delta)
                if bucket is None:
                    bucket = buckets[delta] = {"delta": delta, "attacks": 0, "triples": 0, "stars": 0}
                stars = int(a.get("stars") or 0)
                bucket["attacks"] += 1
                bucket["stars"] += stars
                bucket["triples"] += 1 if stars == 3 else 0
    return buckets


def th_rows(records):
    rows = list(triple_rates(records).values())
    for row in rows:
        row["rate"] = row["triples"] / row["attacks"] if row["attacks"] else 0.0
        row["avg"] = row["stars"] / row["attacks"] if row["attacks"] else 0.0
    return sorted(rows, key=lambda r: r["delta"])


def overall_rate(records):
    buckets = triple_rates(records).values()
    attacks = sum(b["attacks"] for b in buckets)
    return sum(b["triples"] for b in buckets) / attacks if attacks else 0.0


def smoothed_rate(buckets, delta, prior, weight):
    bucket = (buckets or {}).get(delta) or {"attacks": 0, "triples": 0}
    return (bucket["triples"] + prior * weight) / (bucket["attacks"] + weight)


def empty_records():
    return {"wars": 0, "wins": 0, "streak": {"current": 0, "best": 0},
            "destr": None, "stars": None, "perfect": {"n": 0, "last": None},
            "farm": None, "donations": None, "attack_streak": None}


def _records(previous):
    out = empty_records()
    stored = previous if isinstance(previous, dict) else {}
    out["wars"] = int(stored.get("wars") or 0)
    out["wins"] = int(stored.get("wins") or 0)
    streak = stored.get("streak") if isinstance(stored.get("streak"), dict) else {}
    out["streak"] = {"current": int(streak.get("current") or 0), "best": int(streak.get("best") or 0)}
    for key in ("destr", "stars") + VALUE_RECORDS:
        if isinstance(stored.get(key), dict):
            out[key] = dict(stored[key])
    perfect = stored.get("perfect") if isinstance(stored.get("perfect"), dict) else {}
    last = perfect.get("last")
    out["perfect"] = {"n": int(perfect.get("n") or 0), "last": dict(last) if isinstance(last, dict) else None}
    return out


def update_records(previous, record):
    out = _records(previous)
    out["wars"] += 1
    if record.get("result") == "win":
        out["wins"] += 1
    where = {"opponent": record.get("opponent"), "at": record.get("endTime")}
    destr = float(record.get("destr") or 0)
    if out["destr"] is None or destr > out["destr"]["destr"]:
        out["destr"] = dict(where, destr=destr)
    stars = int(record.get("stars") or 0)
    size = int(record.get("teamSize") or 0)
    if out["stars"] is None or stars > out["stars"]["stars"]:
        out["stars"] = dict(where, stars=stars, total=size * 3)
    if size and stars == size * 3 and destr >= 100:
        out["perfect"]["n"] += 1
        out["perfect"]["last"] = dict(where)
    return out


def update_streak(previous, streak):
    out = _records(previous)
    value = max(0, int(streak or 0))
    out["streak"]["current"] = value
    out["streak"]["best"] = max(out["streak"]["best"], value)
    return out


def update_board_records(previous, candidates):
    out = _records(previous)
    for key in VALUE_RECORDS:
        candidate = (candidates or {}).get(key) or {}
        value = int(candidate.get("value") or 0)
        if value <= 0:
            continue
        current = out.get(key) or {}
        if value > int(current.get("value") or 0):
            out[key] = {"name": candidate.get("name"), "value": value}
    return out


def beaten(before, after):
    old, new = _records(before), _records(after)
    names = []
    if old["streak"]["best"] and new["streak"]["best"] > old["streak"]["best"]:
        names.append("streak")
    for key in ("destr", "stars"):
        if old[key] and new[key] and new[key][key] > old[key][key]:
            names.append(key)
    for key in VALUE_RECORDS:
        if old[key] and new[key] and new[key]["value"] > old[key]["value"]:
            names.append(key)
    if new["perfect"]["n"] > old["perfect"]["n"]:
        names.append("perfect")
    return [name for name in RECORD_KEYS if name in names]


def hall_state(stored):
    if isinstance(stored, dict):
        seasons, records = stored.get("seasons"), stored.get("records")
    elif isinstance(stored, list):
        seasons, records = stored, None
    else:
        seasons, records = None, None
    kept = [s for s in (seasons or []) if isinstance(s, dict) and s.get("season")]
    return {"seasons": kept[-WAR_HISTORY_KEEP:], "records": _records(records)}


def _month_first(sid, tz):
    year, month = (int(part) for part in str(sid).split("-")[:2])
    return datetime(year, month, 1, tzinfo=zone(tz))


def month_start(sid, tz):
    return _month_first(sid, tz).astimezone(timezone.utc)


def month_end(sid, tz):
    return next_month(_month_first(sid, tz)).astimezone(timezone.utc)


def in_window(records, start, end):
    rows = []
    for record in records or ():
        ended = parse_coc_time(record.get("endTime"))
        if ended is None or ended < start or ended >= end:
            continue
        rows.append(record)
    return rows


def month_snapshot(sid, records):
    rows = defense_rows(records)
    best = wall(rows)
    return {
        "season": sid,
        "wars": len(records or []),
        "wins": sum(1 for r in records or [] if r.get("result") == "win"),
        "defense": [{"name": r["name"], "stars": r["stars"], "attacked": r["attacked"]}
                    for r in rows if r["attacked"]],
        "wall": {"name": best["name"], "stars": best["stars"], "attacked": best["attacked"]} if best else None,
        "th": [{"delta": r["delta"], "attacks": r["attacks"], "triples": r["triples"]} for r in th_rows(records)],
    }
