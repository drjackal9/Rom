from . import exports, leaders, ledger, manager_actions, reasons, recruit
from .acts import SWITCH
from .guard import destructive
from .handlers import save_settings
from .leader_tools import export_payload
from .reasons import refuse
from .retention import WAR_HISTORY_KEEP
from .web.auth import MINIAPP_MAX_AGE


def weekdays(raw):
    return [int(day) for day in str(raw or "")]


async def schedule_add(act):
    entries = leaders.schedule(act.conf)
    username, site_host = await manager_actions.text_limits(act.store, act.clan)
    try:
        entry = leaders.new_entry(entries, str(act.body.get("hhmm") or ""),
                                  weekdays(act.body.get("days")), act.body.get("text"),
                                  act.uid, username, site_host)
    except ValueError as refused:
        return await manager_actions.refuse_text(act, refused)
    if not entry:
        return refuse(reasons.CLOSED)
    await save_settings(act.store, act.clan, {"scheduled": entries + [entry]})
    await ledger.record(act.store, act.clan.alias, "schedule", act.uid, act.name, entry["hhmm"],
                        act.now)
    return True


async def schedule_drop(act):
    entries = leaders.schedule(act.conf)
    ref = str(act.body.get("ref") or "")
    kept = [entry for entry in entries if entry["id"] != ref]
    if len(kept) == len(entries):
        return refuse(reasons.GONE)
    await save_settings(act.store, act.clan, {"scheduled": kept})
    await ledger.record(act.store, act.clan.alias, "schedule", act.uid, act.name, ref, act.now)
    await destructive(act.store, act.clan.alias, act.uid, "schedule.delete", act.now)
    return True


async def gate_act(act):
    on = str(act.body.get("on") or "") == SWITCH[0]
    await save_settings(act.store, act.clan, {"gate": on})
    await ledger.record(act.store, act.clan.alias, "gate", act.uid, act.name,
                        str(act.body.get("on") or ""), act.now)
    return True


async def note_act(act):
    members = await act.store.get_state(act.clan.alias, "members") or {}
    tag = str(act.body.get("village") or "")
    if tag not in members:
        return refuse(reasons.GONE)
    name = (members[tag] or {}).get("name")
    text = str(act.body.get("text") or "").strip()
    if text:
        if not await ledger.note_set(act.store, act.clan.alias, tag, name, text, act.uid,
                                     act.name, act.now):
            return refuse(reasons.TEXT_REFUSED)
    elif not await ledger.note_del(act.store, act.clan.alias, tag):
        return refuse(reasons.GONE)
    await ledger.record(act.store, act.clan.alias, "note", act.uid, act.name, name, act.now)
    if not text:
        await destructive(act.store, act.clan.alias, act.uid, "text.delete", act.now)
    return True


async def export_act(act):
    sheet = str(act.body.get("sheet") or "")
    if sheet not in exports.KINDS:
        return refuse(reasons.BAD)
    records = await act.store.recent_wars(act.clan.alias, WAR_HISTORY_KEEP)
    sheet_text = (await export_payload(act.store, act.clan, sheet, records)).decode("utf-8-sig")
    if not exports.filled(sheet_text):
        return refuse(reasons.GONE)
    await act.store.kv_set(exports.ready_key(act.clan.alias, act.uid),
                           {"sheet": sheet, "text": sheet_text, "at": int(act.now.timestamp())},
                           ref=act.clan.alias, ttl=MINIAPP_MAX_AGE)
    await ledger.record(act.store, act.clan.alias, "export", act.uid, act.name, sheet, act.now)
    return True


async def requirements_act(act):
    wanted = int(str(act.body.get("th") or "0"))
    await save_settings(act.store, act.clan, {"min_th": wanted or None})
    await ledger.record(act.store, act.clan.alias, "settings", act.uid, act.name, "min_th",
                        act.now)
    return True


async def decide_act(act):
    state = recruit.state_of(await act.store.get_state(act.clan.alias, recruit.KIND))
    state, decided = recruit.decide(state, str(act.body.get("ref") or ""),
                                    str(act.body.get("choice") or ""), act.uid, act.name, act.now)
    if not decided:
        return refuse(reasons.GONE)
    await act.store.set_state(act.clan.alias, recruit.KIND, state)
    await ledger.record(act.store, act.clan.alias, "apply", act.uid, act.name,
                        (decided.get("snap") or {}).get("name"), act.now)
    return True


HANDLERS = {"schedule.add": schedule_add, "schedule.delete": schedule_drop,
            "gate.toggle": gate_act, "note.set": note_act, "export.csv": export_act,
            "recruit.requirements.set": requirements_act, "application.decide": decide_act}
