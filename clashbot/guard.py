from . import feed, i18n, roles, undo
from .events_registry import LEADERS_SUSPENDED
from .platform_guard import FLOOD_WINDOW, flood_state, flooding
from .settings import MANAGER, effective
from .util import now_utc

DESTRUCTIVE = ("warning", "settings", "delegate.remove", "text.delete", "schedule.delete", "undo")
ABUSE_KEY = "abuse:{alias}:{uid}"
SUSPENDED_KEY = "suspended:{alias}:{uid}"
PAUSE = "pause"
EVENT = LEADERS_SUSPENDED
REFUSAL = "h.suspended"
NOTICE = "h.suspend_notice"
FEED_LINE = "feed.suspended"
PAUSED_LINE = "board.all.paused"
STAFF = "staff_dm"


def abuse_key(alias, uid):
    return ABUSE_KEY.format(alias=alias or "-", uid=int(uid))


def suspended_key(alias, uid):
    return SUSPENDED_KEY.format(alias=alias or "-", uid=int(uid))


def village(links, uid):
    return next((link.name for link in (links or {}).values() if link.user_id == uid), None)


async def suspended(store, alias, uid):
    return bool(await store.kv_get(suspended_key(alias, uid)))


async def lift(store, alias, uid):
    was = await suspended(store, alias, uid)
    await store.kv_del(suspended_key(alias, uid))
    return was


async def tell_staff(store, clan, conf, staff, name, now):
    from .poller import member_locale
    for uid in staff:
        links = await store.links_by_user(uid)
        L = await member_locale(store, links[0], conf) if links else i18n.locale(conf["lang"])
        await feed.add(store, clan.alias, uid, EVENT, L.t(FEED_LINE, name=name), now)


async def untouchable(store, clan, members, links, uid):
    if undo.can(members, links, uid):
        return True
    if any(found == MANAGER for found in roles.game_levels(members, links).values()):
        return False
    return uid == await roles.creator_id(store, clan)


async def destructive(store, alias, uid, kind, now=None):
    if kind not in DESTRUCTIVE:
        return 0, False
    moment = now or now_utc()
    who = int(uid)
    key = abuse_key(alias, who)
    state = flood_state(await store.kv_get(key), moment.timestamp())
    await store.kv_set(key, state, ref=alias, ttl=FLOOD_WINDOW)
    count = len(state["hits"])
    clan = await store.clan_by_alias(alias)
    if not flooding(state) or not clan:
        return count, False
    await store.kv_del(key)
    conf = effective(await store.get_state(alias, "settings"), None)
    members = await store.get_state(alias, "members") or {}
    links = await store.links_for_players(sorted(members))
    staff = await roles.managers_for(store, clan, conf, members, STAFF)
    chief = await untouchable(store, clan, members, links, who)
    if not chief:
        await store.kv_set(suspended_key(alias, who), {"at": moment.timestamp()}, ref=alias)
    await tell_staff(store, clan, conf, staff, village(links, who) or str(who), moment)
    return count, not chief


async def paused(store, alias):
    return await store.get_state(alias, PAUSE)


async def pause(store, alias, by, now=None):
    await store.set_state(alias, PAUSE, {"by": int(by), "at": (now or now_utc()).timestamp()})


async def resume(store, alias):
    await store.del_state(alias, PAUSE)
