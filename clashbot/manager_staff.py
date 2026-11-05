from . import brake, door, guard, ledger, reasons, roles, seats, undo
from .acts import DELEGATES, SWITCH
from .handlers import save_settings
from .reasons import refuse
from .settings import MANAGER
from .web.payload import mark_for, slug_for, stamp

CHIEFS = "chiefs"
PENDING = "pending"
YES = "approved"
REPORTS = "reports"
LOG_PAUSE = "pause"
LOG_SEAT = "seat"
LOG_SETTINGS = "settings"
LOG_DELEGATE = "delegate"
LOG_PERSON = "views"
KNOWN = ledger.ACTIONS + ledger.KINDS


def picked_of(conf):
    return [int(uid) for uid in ((conf or {}).get("delegates") or [])]


async def known_seats(act):
    members = await members_of(act)
    links = await act.store.links_for_players(sorted(members))
    found = set(names_of(links)) | set(picked_of(act.conf))
    creator = await roles.creator_id(act.store, act.clan)
    if creator:
        found.add(int(creator))
    return found


async def who_of(act):
    return seats.uid_of(act.store.vault, act.clan.alias, act.body.get("who"),
                        await known_seats(act))


async def members_of(act):
    return await act.store.get_state(act.clan.alias, "members") or {}


async def chief(act):
    return await roles.live_chief(act.coc, act.store, act.clan, await members_of(act), act.uid)


async def keep_delegates(act, picked, kind, ref):
    await save_settings(act.store, act.clan, {DELEGATES: picked})
    await ledger.acted(act.store, act.clan.alias, kind, ref, act.uid, act.name, now=act.now)
    return True


async def add_act(act):
    uid = await who_of(act)
    picked = picked_of(act.conf)
    if uid in picked:
        return refuse(reasons.TAKEN)
    names = dict(await roles.linked_members(act.store, await members_of(act)))
    if uid not in names and uid != await roles.creator_id(act.store, act.clan):
        return refuse(reasons.NOT_LINKED)
    return await keep_delegates(act, picked + [uid], LOG_DELEGATE,
                                seats.seat_ref(act.store.vault, act.clan.alias, uid))


async def revoked(act, picked):
    done = await keep_delegates(act, picked, LOG_SETTINGS, DELEGATES)
    await guard.destructive(act.store, act.clan.alias, act.uid, brake.DELEGATE, act.now)
    return done


async def remove_act(act):
    uid = await who_of(act)
    picked = picked_of(act.conf)
    if uid not in picked:
        return refuse(reasons.GONE)
    return await revoked(act, [one for one in picked if one != uid])


async def clear_act(act):
    if not picked_of(act.conf):
        return refuse(reasons.GONE)
    if not await chief(act):
        return refuse(reasons.CHIEF_ONLY)
    return await revoked(act, [])


async def pause_act(act):
    if not await chief(act):
        return refuse(reasons.CHIEF_ONLY)
    await guard.pause(act.store, act.clan.alias, act.uid, act.now)
    await ledger.record(act.store, act.clan.alias, LOG_PAUSE, act.uid, act.name, SWITCH[0],
                        act.now)
    return True


async def resume_act(act):
    if not await chief(act):
        return refuse(reasons.CHIEF_ONLY)
    await guard.resume(act.store, act.clan.alias)
    await ledger.record(act.store, act.clan.alias, LOG_PAUSE, act.uid, act.name, SWITCH[1],
                        act.now)
    return True


async def undo_act(act):
    if not await undo.apply(act.store, act.clan, act.conf, str(act.body.get("of") or ""),
                            str(act.body.get("ref") or ""), act.uid, act.now, act.coc):
        return refuse(reasons.GONE)
    return True


async def lift_act(act):
    uid = await who_of(act)
    members = await members_of(act)
    if not await roles.live_chief(act.coc, act.store, act.clan, members, act.uid):
        return refuse(reasons.CHIEF_ONLY)
    if not await guard.lift(act.store, act.clan.alias, uid):
        return refuse(reasons.GONE)
    links = await act.store.links_for_players(sorted(members))
    await ledger.record(act.store, act.clan.alias, LOG_SEAT, act.uid, act.name,
                        guard.village(links, uid), act.now)
    return True


def mark_of(store, alias, uid):
    return mark_for(store.vault, slug_for(store.vault, alias), uid)


def person_of(act, uids):
    wanted = str(act.body.get("who") or "")
    return next((uid for uid in uids
                 if mark_of(act.store, act.clan.alias, uid) == wanted), None)


async def door_now(store, alias):
    return door.state_of(await store.get_state(alias, door.KIND))


async def proven_uids(store, members):
    links = await store.links_for_players(sorted(members or {}))
    return sorted({int(link.user_id) for link in roles.verified_only(links).values()})


async def door_saved(act, fresh):
    await act.store.set_state(act.clan.alias, door.KIND, fresh)
    await ledger.record(act.store, act.clan.alias, LOG_PERSON, act.uid, act.name, act.kind,
                        act.now)
    return True


async def person_approve(act):
    state = await door_now(act.store, act.clan.alias)
    uid = person_of(act, await proven_uids(act.store, await members_of(act)))
    if uid is None:
        return refuse(reasons.NOT_LINKED)
    if uid in door.shut_out(state):
        return refuse(reasons.BANNED)
    if str(uid) in state[door.YES]:
        return refuse(reasons.TAKEN)
    try:
        since = door.war_from(str(act.body.get("war_from") or ""), act.now.timestamp())
    except ValueError:
        return refuse(reasons.BAD)
    return await door_saved(act, door.approve(state, uid, act.now.timestamp(), since))


async def person_revoke(act):
    state = await door_now(act.store, act.clan.alias)
    uid = person_of(act, [int(one) for one in state[door.YES]])
    if uid is None:
        return refuse(reasons.GONE)
    return await door_saved(act, door.revoke(state, uid))


async def person_trust(act):
    state = await door_now(act.store, act.clan.alias)
    uid = person_of(act, sorted({int(one) for one in state[door.YES]} | set(state[door.TRUST])))
    if uid is None:
        return refuse(reasons.GONE)
    on = str(act.body.get("value") or "") == SWITCH[0]
    return await door_saved(act, door.trust(state, uid, on))


def log_rows(L, rows, names):
    found = []
    for row in rows or ():
        kind = row.get("kind")
        name = kind or row.get("action")
        if name not in KNOWN:
            continue
        ref = str(row.get("ref") or "")
        back = kind in undo.KINDS and bool(ref or kind == LOG_SETTINGS)
        found.append({
            "what": L.t(f"leaders.log.action.{name}"),
            "who": names.get(row.get("by")) or row.get("by_name"),
            "at": stamp(row.get("at")),
            "of": kind if back else None,
            "ref": (undo.PREV if kind == LOG_SETTINGS else ref) if back else None,
        })
    return found


def for_uid(staff, chiefs, uid):
    return dict(staff, undo=uid in (chiefs or ()))


def pending_only(staff):
    rows = (staff or {}).get(PENDING) or []
    return {PENDING: list(rows)} if rows else None


async def door_rows(store, clan, links, names):
    state = await door_now(store, clan.alias)
    tags = {int(link.user_id): tag for tag, link in roles.verified_only(links).items()}
    waiting = door.pending(state, sorted(tags))
    approved = sorted(int(uid) for uid in state[door.YES] if int(uid) in names)
    return {
        PENDING: [{"who": mark_of(store, clan.alias, uid), "name": names.get(uid),
                   "tag": tags[uid]} for uid in waiting],
        YES: [{"who": mark_of(store, clan.alias, uid), "name": names[uid],
               "trusted": uid in state[door.TRUST]} for uid in approved],
    }


def names_of(links):
    found = {}
    for tag in sorted(links or {}):
        found.setdefault(links[tag].user_id, links[tag].name)
    return found


async def of(store, clan, conf, members, levels, L):
    if not any(level == MANAGER for level in (levels or {}).values()):
        return {}
    members = members or {}
    links = await store.links_for_players(sorted(members))
    names = names_of(links)
    picked = picked_of(conf)
    creator = await roles.creator_id(store, clan)
    watch = set(roles.game_levels(members, links)) | set(picked)
    if creator:
        watch.add(int(creator))
    stopped = await seats.suspended_from(store, clan.alias, sorted(watch))

    def ref(uid):
        return seats.seat_ref(store.vault, clan.alias, uid)

    return {
        DELEGATES: [{"who": ref(uid), "name": names.get(uid)} for uid in picked],
        "people": [{"who": ref(uid), "name": name} for uid, name in sorted(names.items())
                   if uid not in picked],
        "suspended": [{"who": ref(uid), "name": names.get(uid)} for uid in stopped],
        "paused": bool(await guard.paused(store, clan.alias)),
        **await door_rows(store, clan, links, names),
        REPORTS: await store.reports_for(clan.alias),
        "log": log_rows(L, await store.recent_log(clan.alias), names),
        CHIEFS: sorted(roles.chiefs_of(members, links)),
    }


HANDLERS = {"delegate.add": add_act, "delegate.remove": remove_act, "delegates.clear": clear_act,
            "clan.pause": pause_act, "clan.resume": resume_act, "undo.apply": undo_act,
            "suspension.lift": lift_act,
            "person.approve": person_approve, "person.revoke": person_revoke,
            "person.trust": person_trust}
