from .settings import LIMITED, MANAGER
from .verify import LEADER_ROLES

LEVELS = {role: MANAGER for role in LEADER_ROLES} | {"admin": LIMITED}


async def creator_id(store, clan):
    linked_by = getattr(clan, "linked_by", None)
    if linked_by:
        return int(linked_by)
    bot = await store.bot_by_alias(clan.bot_alias)
    owner = getattr(bot, "owner_id", None)
    return int(owner) if owner else None


def verified_only(links):
    return {tag: link for tag, link in (links or {}).items()
            if getattr(link, "verified", True)}


def game_levels(members, links):
    found = {}
    for tag, link in verified_only(links).items():
        level = LEVELS.get((members.get(tag) or {}).get("role"))
        if level and found.get(link.user_id) != MANAGER:
            found[link.user_id] = level
    return found


async def without_suspended(store, clan, levels):
    from . import guard
    kept = {}
    for uid, found in levels.items():
        if not await guard.suspended(store, clan.alias, uid):
            kept[uid] = found
    return kept


async def managers(store, clan, conf, members):
    links = await store.links_for_players(sorted(members))
    levels = game_levels(members, links)
    creator = await creator_id(store, clan)
    if not any(level == MANAGER for level in levels.values()):
        if creator:
            levels[creator] = MANAGER
        return await without_suspended(store, clan, levels)
    linked = {link.user_id for link in verified_only(links).values()}
    for uid in (conf or {}).get("delegates") or []:
        if uid == creator or uid in linked:
            levels[uid] = MANAGER
    return await without_suspended(store, clan, levels)


async def level(store, clan, conf, members, uid):
    return (await managers(store, clan, conf, members)).get(uid)


def chiefs_of(members, links):
    from . import undo
    kept = verified_only(links)
    return {link.user_id for link in kept.values() if undo.can(members, kept, link.user_id)}


async def chiefs(store, members):
    return chiefs_of(members, await store.links_for_players(sorted(members or {})))


async def linked_members(store, members):
    links = await store.links_for_players(sorted(members or {}))
    found = {}
    for tag in sorted(links):
        found.setdefault(links[tag].user_id, links[tag].name)
    return sorted(found.items())


async def managers_for(store, clan, conf, members, to):
    levels = await managers(store, clan, conf, members or {})
    if to == "staff_dm":
        return sorted(levels)
    return sorted(uid for uid, found in levels.items() if found == MANAGER)


def still_in_clan(clan, data):
    here = str(getattr(clan, "tag", "") or "").lstrip("#").upper()
    there = str(((data or {}).get("clan") or {}).get("tag") or "").lstrip("#").upper()
    return not there or there == here


async def live_members(coc, store, clan, members, uid):
    fresh = dict(members)
    for link in await store.links_by_user(uid):
        if link.tag not in fresh:
            continue
        data, error = await coc.player(link.tag)
        if error or not data:
            return members, False
        role = data.get("role") if still_in_clan(clan, data) else None
        fresh[link.tag] = dict(fresh.get(link.tag) or {}, role=role)
    return fresh, True


async def live_level(coc, store, clan, conf, members, uid):
    fresh, live = await live_members(coc, store, clan, members, uid)
    return await level(store, clan, conf, fresh, uid), live


async def live_chief(coc, store, clan, members, uid):
    if not coc:
        return uid in chiefs_of(members, await store.links_for_players(sorted(members or {})))
    fresh, live = await live_members(coc, store, clan, members, uid)
    if not live:
        return False
    return uid in chiefs_of(fresh, await store.links_for_players(sorted(fresh or {})))


async def in_clan(store, members, uid):
    links = await store.links_for_players(sorted(members or {}))
    return any(int(link.user_id) == int(uid) for link in verified_only(links).values())


async def keeps_clan(coc, store, clan, uid):
    members = await store.get_state(clan.alias, "members") or {}
    if await live_chief(coc, store, clan, members, uid):
        return True
    creator = await creator_id(store, clan)
    if creator is None or int(creator) != int(uid):
        return False
    return await in_clan(store, members, uid)


async def keeps_bot(store, coc, bot, uid):
    served = await store.active_clans(bot.alias)
    if not served:
        owner = getattr(bot, "owner_id", None)
        return owner is not None and int(owner) == int(uid)
    for clan in served:
        if await keeps_clan(coc, store, clan, uid):
            return True
    return False
