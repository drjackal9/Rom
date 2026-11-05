from . import cwl_bonus, cwl_roster, discipline, ledger, undo
from .events import war_key
from .handlers import active_war

LOG = "cwl"


async def season_state(store, clan):
    cwl = await store.get_state(clan.alias, "cwl") or {}
    state = cwl_roster.for_season(await store.get_state(clan.alias, cwl_roster.STATE),
                                  cwl.get("season"))
    return cwl, state


async def keep(act, state, tag):
    await act.store.set_state(act.clan.alias, cwl_roster.STATE, state)
    await ledger.record(act.store, act.clan.alias, LOG, act.uid, act.name, tag, act.now)
    return True


async def registered_state(act):
    cwl, state = await season_state(act.store, act.clan)
    tag = str(act.body.get("village") or "")
    if tag not in cwl_roster.registered(cwl, act.clan.tag):
        return cwl, None, tag
    return cwl, state, tag


async def confirm_act(act):
    war, _, _ = await active_war(act.store, act.clan)
    wanted = str(act.body.get("village") or "")
    row = next((one for one in discipline.proposals(war or {}) if one["tag"] == wanted), None)
    if not row:
        return False
    await discipline.confirm(act.store, act.clan, act.conf, row, war_key(war), act.uid, act.now)
    return True


async def void_act(act):
    return await undo.apply(act.store, act.clan, act.conf, "warning",
                            str(act.body.get("ref") or ""), act.uid, act.now, act.coc)


async def roster_act(act):
    _, state, tag = await registered_state(act)
    if state is None:
        return False
    cwl_roster.declare(state, tag, str(act.body.get("choice") or ""), act.uid,
                       act.now.timestamp())
    return await keep(act, state, tag)


async def lineup_act(act):
    _, state, tag = await registered_state(act)
    if state is None:
        return False
    return await keep(act, cwl_roster.choose(state, tag), tag)


async def bonus_act(act):
    cwl, state, tag = await registered_state(act)
    if state is None:
        return False
    cwl_bonus.toggle(state, tag)
    done = await keep(act, state, tag)
    await cwl_bonus.sync_season(act.store, act.clan.alias, cwl.get("season"),
                                cwl_roster.marked(state, cwl_roster.BONUS))
    return done


HANDLERS = {"warning.confirm": confirm_act, "warning.void": void_act,
            "cwl.roster.set": roster_act, "cwl.lineup.set": lineup_act,
            "cwl.bonus.toggle": bonus_act}
