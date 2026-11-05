from .scouting import average_th, clan_facts, th_rows


def for_season(scout, season):
    if not scout or scout.get("season") != season:
        return {"season": season, "clans": {}, "sent": None}
    scout.setdefault("clans", {})
    return scout


def missing(cwl, scout):
    known = (scout or {}).get("clans") or {}
    return sorted(tag for tag in ((cwl or {}).get("clans") or {}) if tag not in known)


def remember(scout, tag, group_clan, clan_json, ts):
    members = (group_clan or {}).get("members") or []
    entry = {
        "name": (group_clan or {}).get("name"),
        "level": (group_clan or {}).get("level"),
        "members": len(members),
        "th": th_rows(members),
        "avg_th": average_th(members),
        "fetched": ts,
    }
    data = clan_facts(clan_json)
    if data.get("level") is None:
        data.pop("level")
    entry.update(data)
    scout.setdefault("clans", {})[tag] = entry
    return scout


def complete(cwl, scout):
    return bool((cwl or {}).get("clans")) and not missing(cwl, scout)


def rows(scout, our_tag):
    out = [dict(entry, tag=tag, us=tag == our_tag)
           for tag, entry in ((scout or {}).get("clans") or {}).items()]
    out.sort(key=lambda r: (-(r.get("avg_th") or 0), -(r.get("level") or 0), r.get("name") or ""))
    for i, row in enumerate(out):
        row["rank"] = i + 1
    return out
