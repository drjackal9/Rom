from datetime import timedelta

from . import progress as progress_mod
from . import views


async def rows(store, family):
    out = []
    for clan in await store.family_clans(family.alias):
        info = await store.get_state(clan.alias, "info") or {}
        settings = await store.get_state(clan.alias, "settings") or {}
        out.append({
            "alias": clan.alias, "chat_id": clan.chat_id, "tag": clan.tag, "name": clan.name,
            "level": info.get("level"), "members": info.get("members"), "league": info.get("league"),
            "min_th": settings.get("min_th"), "note": settings.get("note"),
            "labels": info.get("labels"),
        })
    return out


def recruit_digest(rows_, notices=None):
    return repr([(r["name"], r["members"], r["min_th"], r["note"]) for r in rows_]
                + list(notices or ()))


async def digest_data(store, family, now):
    since = now - timedelta(days=7)
    clan_rows, stars, donors, loot = [], {}, [], []
    for clan in await store.family_clans(family.alias):
        if not await shows_score(store, clan):
            continue
        records = await store.wars_since(clan.alias, since)
        clan_rows.append({
            "alias": clan.alias,
            "name": clan.name,
            "wars": len(records),
            "wins": sum(1 for r in records if r["result"] == "win"),
            "losses": sum(1 for r in records if r["result"] == "lose"),
            "ties": sum(1 for r in records if r["result"] == "tie"),
            "stars": sum(r["stars"] for r in records),
        })
        for r in records:
            for m in r.get("members", []):
                key = (m["name"], clan.name)
                stars[key] = stars.get(key, 0) + sum(a["stars"] for a in m["attacks"])
        members = await store.get_state(clan.alias, "members") or {}
        donors += [(m["name"], m.get("donations") or 0, clan.name) for m in members.values() if m.get("donations")]
        season = await store.get_state(clan.alias, "season") or {}
        loot += [(e["name"], e["loot"], clan.name) for e in season.get("members", {}).values() if e.get("loot")]
    top_stars = sorted(((n, v, c) for (n, c), v in stars.items() if v), key=lambda x: -x[1])[:5]
    top_donors = sorted(donors, key=lambda x: -x[1])[:5]
    top_loot = sorted(loot, key=lambda x: -x[1])[:5]
    return clan_rows, top_stars, top_donors, top_loot


async def clan_activity(store, clan, period="week", start=None):
    stored = await store.get_state(clan.alias, "progress")
    board = progress_mod.window(stored if isinstance(stored, dict) else {}, period, start)
    info = await store.get_state(clan.alias, "info")
    try:
        known = int((info or {}).get("members") or 0)
    except (AttributeError, TypeError, ValueError):
        known = 0
    members = max(len(board), known)
    total = sum(r["score"] for r in board)
    return round(total / members, 1) if members else 0


async def shows_score(store, clan):
    state = views.state_of(await store.get_state(clan.alias, views.KIND))
    return bool(state[views.FAMILY])


async def activity_rows(store, family, period="week"):
    out = []
    for clan in await store.family_clans(family.alias):
        if not await shows_score(store, clan):
            continue
        out.append({"name": clan.name, "avg": await clan_activity(store, clan, period)})
    out.sort(key=lambda r: (-r["avg"], r["name"] or ""))
    return out
