from . import awards, base_videos, bases, challenges, duels, i18n, recruit
from .retention import BASE_KEEP, WAR_HISTORY_KEEP
from .settings import web_conf
from .util import CLAN_SLOTS

HALLS_SHOWN = 3
DUEL_FIELDS = ("id", "metric", "status", "ends")
DUEL_SIDES = ("a", "b")


def halls_of(members):
    counts = {}
    for member in (members or {}).values():
        hall = int((member or {}).get("th") or 0)
        if hall > 0:
            counts[hall] = counts.get(hall, 0) + 1
    if not counts:
        return []
    top = max(counts.items(), key=lambda pair: (pair[1], pair[0]))[0]
    return [hall for hall in range(top, top - HALLS_SHOWN, -1) if hall > 0]


def newest(rows, field, limit):
    ordered = sorted(rows, key=lambda row: str(row.get("id") or ""))
    ordered.sort(key=lambda row: str(row.get(field) or ""), reverse=True)
    return ordered[:limit]


def clan_row(L, row):
    link = bases.link_url(L, row.get("id") or "")
    if not bases.parse_link(link):
        return None
    return {"alias": row.get("alias"), "label": row.get("label"), "village": row.get("village"),
            "hall": row.get("hall"), "link": link, "by": row.get("name")}


async def clan_rows(store, clan, L):
    found = [clan_row(L, row) for row in await store.clan_bases(clan.alias, limit=BASE_KEEP)]
    return [row for row in found if row]


def checked_links(links):
    return [link for link in links or () if bases.parse_link(link)]


async def library_of(store, halls):
    rows = []
    for hall in halls:
        rows.extend(await store.library_rows(hall=hall, limit=WAR_HISTORY_KEEP))
    kept = [row for row in rows if bases.parse_link(row.get("link"))]
    return newest(kept, "added", WAR_HISTORY_KEEP)


async def videos_of(store, clan):
    rows = list(await store.videos_rows(scope=base_videos.PLATFORM, limit=WAR_HISTORY_KEEP))
    seen = {row.get("id") for row in rows}
    rows += [row for row in await store.videos_rows(scope=clan.alias, limit=WAR_HISTORY_KEEP)
             if row.get("id") not in seen]
    return [{**row, "links": checked_links(row.get("links"))}
            for row in newest(rows, "published", WAR_HISTORY_KEEP)]


async def bases_of(store, clan, members, L):
    halls = halls_of(members)
    return {"clan": await clan_rows(store, clan, L),
            "library": {"halls": halls, "rows": await library_of(store, halls),
                        "videos": await videos_of(store, clan)}}


async def recruit_of(store, clan, conf, members):
    return {"open": bool(await store.recruit_row(clan.alias)),
            "free": max(0, CLAN_SLOTS - len(members or {})),
            "requirement": recruit.requirement(conf),
            "page_on": bool(web_conf(conf).get("page")),
            "code": store.recruit_code(clan.alias)}


async def family_of(store, clan):
    family = await store.family_of_clan(clan.alias)
    if not family:
        return None
    return {"name": family.name, "code": family.alias,
            "clans": [{"name": one.name, "code": store.recruit_code(one.alias)}
                      for one in await store.family_clans(family.alias)]}


def duel_row(duel):
    row = {name: duel.get(name) for name in DUEL_FIELDS}
    row.update({side: {"tag": (duel.get(side) or {}).get("tag"),
                       "name": (duel.get(side) or {}).get("name")} for side in DUEL_SIDES})
    return row


async def duels_of(store, clan):
    return [duel_row(duel) for duel in duels.running(await challenges.load(store, clan.alias))]


async def award_of(store, clan):
    poll = await awards.load_poll(store, clan.alias) or {}
    rows = [{"name": row.get("name"), "stars": row.get("stars"), "destr": row.get("destr")}
            for row in poll.get("rows") or ()]
    return {"rows": rows, "ends": int(poll.get("ends") or 0)} if rows else None


async def of(store, clan, conf, members):
    L = i18n.locale((conf or {}).get("lang"))
    return {"bases": await bases_of(store, clan, members, L),
            "recruit": await recruit_of(store, clan, conf, members),
            "family": await family_of(store, clan),
            "award": await award_of(store, clan),
            "duels": await duels_of(store, clan)}
