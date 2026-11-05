import logging

from . import (acts, app_actions, base_packs, linking, manager_actions, manager_net,
               manager_staff, manager_tools, manager_war, mydata, reasons, recruit_block, roles)
from .events import war_key
from .handlers import active_war, current_plan
from .reasons import refuse
from .settings import allowed, effective
from .targets import assign, member_at, mirror_plan, noted, swapped
from .web.auth import MINIAPP_MAX_AGE

log = logging.getLogger("clashbot.intents")

NOTE = "target.note"
SWAP = "target.swap"
SET = "target.set"
FREE = "target.free"
MIRROR = "target.mirror"
CLEAR = "target.clear"
SWAP_LINE = "feed.target.swap"
REFUSED_KEY = "web:refused:"
DONE = "fatto"
KINDS_MEMBER = acts.KINDS_MEMBER
KINDS_MANAGER = acts.KINDS_MANAGER
SENSITIVE = acts.SENSITIVE_KINDS
REGISTRY = {}


def register(kind, action, handler):
    REGISTRY[kind] = (action, handler)
    return handler


def next_plan(kind, plan, war, body, tag):
    pos = str(body.get("pos") or "")
    if kind == MIRROR:
        return mirror_plan(war)
    if kind == CLEAR:
        return {}
    if kind == FREE:
        return assign(plan, pos, None)
    if kind == NOTE:
        return noted(plan, pos, str(body.get("text") or ""))
    if kind == SWAP:
        return swapped(plan, pos, tag)
    if kind == SET:
        found = member_at(war, str(body.get("who") or ""))
        return assign(plan, pos, found) if found else None
    return None


async def tell_holder(act, plan):
    pos = str(act.body.get("pos") or "")
    tag = ((plan or {}).get(pos) or {}).get("tag")
    link = (await act.store.links_for_players([tag])).get(tag) if tag else None
    if not link:
        return
    await linking.tell(act.store, act.clan.alias, link.user_id, act.conf,
                       lambda L: L.t(SWAP_LINE, name=act.name, pos=pos), act.now, SWAP)


def seat_pos(war, tag):
    member = ((war or {}).get("members") or {}).get(tag) or {}
    return str(member.get("pos") or "")


def free_at(plan, pos, tag):
    held = (plan or {}).get(str(pos)) or {}
    return not held.get("tag") or held.get("tag") == tag


def held_by(plan, pos, tag):
    return ((plan or {}).get(str(pos)) or {}).get("tag") == tag


def booked_at(plan, tag):
    return next((pos for pos, row in (plan or {}).items() if (row or {}).get("tag") == tag), "")


def own_plan(kind, plan, war, body, tag):
    seat = seat_pos(war, tag)
    if not seat:
        return None
    pos = str(body.get("pos") or "")
    held = booked_at(plan, tag)
    if kind == MIRROR:
        if held and held != seat:
            return None
        return assign(plan, seat, member_at(war, seat)) if free_at(plan, seat, tag) else None
    if kind == SET:
        if str(body.get("who") or "") != seat or not free_at(plan, pos, tag):
            return None
        if held and held != pos:
            return None
        return assign(plan, pos, member_at(war, seat))
    if kind in (FREE, NOTE) and not held_by(plan, pos, tag):
        return None
    return next_plan(kind, plan, war, body, tag)


async def targets_level(act):
    if act.level:
        return act.level
    return await roles.level(act.store, act.clan, act.conf, act.members or {}, act.uid)


async def targets_act(act):
    war, _, _ = await active_war(act.store, act.clan)
    if not war:
        return refuse(reasons.NOT_IN_WAR)
    held = await current_plan(act.store, act.clan, war)
    if allowed(act.conf, acts.TARGETS, await targets_level(act)):
        plan = next_plan(act.kind, held, war, act.body, act.tag)
    else:
        plan = own_plan(act.kind, held, war, act.body, act.tag)
    if plan is None:
        return refuse(reasons.TAKEN)
    if plan:
        await act.store.set_state(act.clan.alias, "plan",
                                  {"war": war_key(war), "targets": plan})
    else:
        await act.store.del_state(act.clan.alias, "plan")
    if act.kind == SWAP:
        await tell_holder(act, plan)
    return True


def wire():
    for handlers in (app_actions.HANDLERS, base_packs.HANDLERS, linking.HANDLERS,
                     manager_actions.HANDLERS, manager_net.HANDLERS, manager_staff.HANDLERS,
                     manager_tools.HANDLERS, manager_war.HANDLERS, mydata.HANDLERS,
                     recruit_block.HANDLERS):
        for kind, handler in handlers.items():
            register(kind, acts.ACTIONS[kind], handler)
    for kind in acts.TARGET_KINDS:
        register(kind, acts.ACTIONS[kind], targets_act)


def once_key(store, body):
    row = body or {}
    ident = str(row.get("id") or "")
    if not ident:
        return ""
    mark = f"{row.get('by')}:{ident}"
    return f"intent:{store.vault.blind('intent', mark)}"


async def live_enough(store, coc, clan, conf, members, uid, kind, action):
    if kind not in SENSITIVE or not coc:
        return True
    if kind == manager_actions.PRESS and not await manager_actions.first_write(
            store, clan.alias, uid):
        return True
    level, live = await roles.live_level(coc, store, clan, conf, members, uid)
    return live and allowed(conf, action, level)


def owner_bot(beat):
    supervisor = getattr(beat, "supervisor", None)
    return supervisor.owner_bot() if supervisor else None


async def apply_one(store, beat, row, now):
    found = REGISTRY.get(row["kind"])
    if row["kind"] in acts.TOKEN_ONLY:
        return refuse(reasons.NEEDS_TOKEN)
    if not found:
        return refuse(reasons.BAD)
    action, handler = found
    clan = await store.clan_by_alias(row["clan"])
    if not clan:
        return refuse(reasons.GONE)
    body = row["body"] or {}
    once = once_key(store, body)
    if once and await store.kv_get(once):
        return refuse(reasons.TAKEN)
    uid = int(body.get("by") or 0)
    members = await store.get_state(clan.alias, "members") or {}
    link = acts.seat(await store.links_by_user(uid), members)
    if not link and row["kind"] not in acts.NO_SEAT:
        return refuse(reasons.NOT_LINKED)
    conf = effective(await store.get_state(clan.alias, "settings"), None)
    level = await roles.level(store, clan, conf, members, uid) if action else None
    if action and not allowed(conf, action, level):
        return refuse(reasons.NOT_MANAGER)
    if not await live_enough(store, beat.coc, clan, conf, members, uid, row["kind"], action):
        return refuse(reasons.NOT_MANAGER)
    act = acts.Act(store=store, clan=clan, conf=conf, kind=row["kind"], body=body, uid=uid,
                   tag=link.tag if link else "", name=link.name if link else "", level=level,
                   now=now, coc=beat.coc, bot=owner_bot(beat), members=members)
    outcome = await handler(act)
    if not reasons.done(outcome):
        return reasons.code_of(outcome)
    if once:
        await store.kv_set(once, {"at": int(now.timestamp())}, ref=clan.alias,
                           ttl=MINIAPP_MAX_AGE)
    fresh = effective(await store.get_state(clan.alias, "settings"), None)
    await beat.app(clan, fresh, members, await store.get_state(clan.alias, "info"), now)
    return True


def refused_key(intent_id):
    return f"{REFUSED_KEY}{int(intent_id)}"


async def close_one(store, row, now, code):
    if code is not None:
        await store.kv_set(refused_key(row["id"]),
                           {"at": int(now.timestamp()), "code": code},
                           ref=row["clan"], ttl=MINIAPP_MAX_AGE)
    await store.web_intent_done(row["id"])


async def drain(store, beat, now, limit=50):
    done = 0
    for row in await store.web_intents_take(limit):
        try:
            answered = await apply_one(store, beat, row, now)
        except Exception:
            log.exception("gesto %s: rotto", row["kind"])
            await close_one(store, row, now, reasons.REFUSED)
            continue
        made = reasons.done(answered)
        code = DONE if made else reasons.code_of(answered)
        log.info("gesto %s: %s", row["kind"], code)
        await close_one(store, row, now, None if made else code)
        done += 1 if made else 0
    return done


wire()
