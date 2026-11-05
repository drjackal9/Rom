from . import ledger, platform_ban, recruit
from .retention import WAR_HISTORY_KEEP

KIND = "recruit_blocks"
KEEP = WAR_HISTORY_KEEP
LOG = "apply"


def state_of(stored):
    stored = stored if isinstance(stored, dict) else {}
    kept = stored.get("rows")
    out = {"next": 1, "rows": {}}
    for key, row in (kept if isinstance(kept, dict) else {}).items():
        who = int(row.get("who") or 0) if isinstance(row, dict) else 0
        if not who:
            continue
        out["rows"][str(key)] = {"id": str(key), "who": who, "name": row.get("name"),
                                 "at": float(row.get("at") or 0)}
    try:
        nxt = int(stored.get("next") or 1)
    except (TypeError, ValueError):
        nxt = 1
    used = [int(key) for key in out["rows"] if key.isdigit()]
    out["next"] = max(1, nxt, (max(used) + 1) if used else 1)
    return out


def rows(state):
    return sorted(state["rows"].values(), key=lambda row: (row["at"], int(row["id"])))


def blocked(state, user_id):
    who = int(user_id or 0)
    return bool(who) and any(row["who"] == who for row in state["rows"].values())


def add(state, who, name, now):
    who = int(who or 0)
    if not who or blocked(state, who):
        return state, None
    ref = str(state["next"])
    state["next"] = state["next"] + 1
    state["rows"][ref] = {"id": ref, "who": who, "name": name or None, "at": now.timestamp()}
    for extra in rows(state)[:max(0, len(state["rows"]) - KEEP)]:
        state["rows"].pop(extra["id"], None)
    return state, state["rows"].get(ref)


def drop(state, ref):
    return state, state["rows"].pop(str(ref), None)


def lists(state):
    return [{"id": row["id"], "name": row["name"]} for row in rows(state)]


async def load(store, alias):
    return state_of(await store.get_state(alias, KIND))


async def refuses(store, alias, user_id):
    if await platform_ban.refuses(store, user_id):
        return True
    return blocked(await load(store, alias), user_id)


async def block_act(act):
    applications = recruit.state_of(await act.store.get_state(act.clan.alias, recruit.KIND))
    application = recruit.find(applications, str(act.body.get("ref") or ""))
    if not application:
        return False
    state, row = add(await load(act.store, act.clan.alias), application.get("user_id"),
                     (application.get("snap") or {}).get("name"), act.now)
    if not row:
        return False
    await act.store.set_state(act.clan.alias, KIND, state)
    applications, decided = recruit.decide(applications, application["id"], "rejected", act.uid,
                                           act.name, act.now)
    if decided:
        await act.store.set_state(act.clan.alias, recruit.KIND, applications)
    await ledger.record(act.store, act.clan.alias, LOG, act.uid, act.name, row["name"], act.now)
    return True


async def unblock_act(act):
    state, row = drop(await load(act.store, act.clan.alias), str(act.body.get("ref") or ""))
    if not row:
        return False
    await act.store.set_state(act.clan.alias, KIND, state)
    await ledger.record(act.store, act.clan.alias, LOG, act.uid, act.name, row["name"], act.now)
    return True


HANDLERS = {"sender.block": block_act, "sender.unblock": unblock_act}
