from . import render

CATALOG = {
    "th": "🏯", "hero": "👑", "league": "🏆", "warstars": "⭐", "record": "📈",
    "quiz": "🧠", "duello": "🤺", "veggente": "🔮", "missione": "🎯", "bingo": "🎲",
    "ambasciatore": "🤝", "premio": "🎖", "attacco": "💥",
}
FROM_EVENTS = {"th": "th", "hero": "hero", "league": "league", "warstars": "warstars", "record": "record"}
NAME_KEY = "badge.name."
HOW_KEY = "badge.how."


def catalog():
    return [{"badge": badge, "glyph": glyph, "name": NAME_KEY + badge, "how": HOW_KEY + badge}
            for badge, glyph in CATALOG.items()]


def grant(state, who, badge, ts):
    if badge not in CATALOG:
        return False
    owned = state.setdefault("badges", {}).setdefault(str(who), {})
    row = owned.get(badge)
    if row:
        row["n"] = int(row.get("n") or 1) + 1
        row["ts"] = int(ts)
        return False
    owned[badge] = {"n": 1, "ts": int(ts)}
    return True


def grant_all(state, who_list, badge, ts):
    fresh, seen = [], set()
    for who in who_list or ():
        key = str(who)
        if key in seen:
            continue
        seen.add(key)
        if grant(state, who, badge, ts):
            fresh.append(who)
    return fresh


def from_player_events(state, tag, events, ts):
    fresh = []
    for event in events or ():
        badge = FROM_EVENTS.get(event.get("type"))
        if badge and grant(state, tag, badge, ts):
            fresh.append(badge)
    return sorted(fresh)


def of(state, who):
    return sorted((state.get("badges") or {}).get(str(who)) or {})


def rows(state, who):
    owned = (state.get("badges") or {}).get(str(who)) or {}
    return [{"badge": badge, "ts": int((owned.get(badge) or {}).get("ts") or 0)}
            for badge in of(state, who)]


def rows_for(state, keys):
    seen = {}
    for key in keys or ():
        for row in rows(state, key):
            kept = seen.get(row["badge"])
            if not kept or row["ts"] > kept["ts"]:
                seen[row["badge"]] = row
    return [seen[badge] for badge in sorted(seen)]


def by_player(state, tags, owners=None):
    found = {}
    held = owners or {}
    for tag in sorted(tags or ()):
        uid = held.get(tag)
        marks = rows_for(state, [tag] + ([uid] if uid is not None else []))
        if marks:
            found[tag] = marks
    return found


def line(L, state, who):
    owned = (state.get("badges") or {}).get(str(who)) or {}
    parts = []
    for badge in sorted(owned):
        times = int((owned[badge] or {}).get("n") or 1)
        parts.append(CATALOG[badge] + (L.t("badge.times", n=times) if times > 1 else ""))
    return " ".join(parts)


def section(L, state):
    owned = state.get("badges") or {}
    if not owned:
        return None
    rows = sorted(owned.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:5]
    return L.t("badge.section.head") + "\n" + render.quote("\n".join(
        L.t("badge.section.row", who=render.esc(who), badges=" ".join(CATALOG[b] for b in sorted(items)))
        for who, items in rows))
