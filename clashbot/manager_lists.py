from . import cwl_roster, cwl_season, derby, discipline, i18n, integrations, leaders, ledger
from . import base_packs, base_videos, manager_net, recruit, recruit_block, tourney_ui
from . import settings as settings_mod
from .acts import MANAGE_PACKS
from .settings import MANAGER, pack_on
from .web.payload import screen_of

PACKS = MANAGE_PACKS


async def war_rows(store, clan, war):
    entries = await store.get_state(clan.alias, discipline.STATE) or []
    return {
        "proposals": [dict(row) for row in discipline.proposals(war or {})],
        "warnings": [{"id": row.get("id"), "name": row.get("name"),
                      "missed": row.get("missed"), "at": int(row.get("at") or 0)}
                     for row in entries if isinstance(row, dict)],
    }


async def cwl_lists(store, clan):
    cwl = await store.get_state(clan.alias, "cwl") or {}
    signed = cwl_roster.registered(cwl, clan.tag)
    if not signed:
        return None
    state = cwl_roster.for_season(await store.get_state(clan.alias, cwl_roster.STATE),
                                  cwl.get("season"))
    cwl_war = await store.get_state(clan.alias, "cwl_war") or {}
    records = cwl_season.season_wars(await store.recent_wars(clan.alias,
                                                             cwl_season.SEASON_WARS),
                                     cwl.get("season"))
    players = (await store.get_state(clan.alias, "players") or {}).get("tags") or {}
    chosen = cwl_roster.picked(state)
    bonus = cwl_roster.marked(state, cwl_roster.BONUS)
    rows = cwl_roster.rows(signed, state, cwl_roster.played_days(records, cwl_war), records,
                           players)
    return {"size": cwl_war.get("teamSize"),
            "rows": [{"tag": row["tag"], "name": row["name"], "th": row["th"],
                      "state": row["state"], "days": row["days"],
                      "picked": row["tag"] in chosen, "bonus": row["tag"] in bonus}
                     for row in rows]}


def tool_lists(conf, notes, channels, proposed=()):
    return {
        "texts": leaders.texts(conf),
        "gate": leaders.gate_on(conf),
        "scheduled": [{"id": one["id"], "hhmm": one["hhmm"], "days": one["days"],
                       "text": one["text"]} for one in leaders.schedule(conf)],
        "notes": [{"tag": tag, "name": note.get("name"), "text": note.get("text")}
                  for tag, note in sorted((notes or {}).items())],
        "channels": base_videos.clean(channels),
        "bases": [dict(row) for row in proposed or ()],
    }


async def recruit_lists(store, clan, conf):
    state = recruit.state_of(await store.get_state(clan.alias, recruit.KIND))
    return {"min_th": recruit.requirement(conf),
            "applications": [{"id": one["id"], "name": (one.get("snap") or {}).get("name"),
                              "th": (one.get("snap") or {}).get("th"),
                              "goals": one.get("goals") or []}
                             for one in recruit.pending(state)],
            "blocked": recruit_block.lists(await recruit_block.load(store, clan.alias))}


async def family_lists(store, clan, L):
    family = await store.family_of_clan(clan.alias)
    found = {"name": family.name if family else None,
             "code": family.alias if family else None, "derby": None,
             "owner": manager_net.family_owner(family)}
    if family:
        saved = await store.kv_get(derby.saved_key(family.alias)) or {}
        doc = await store.tournament(saved["alias"]) if saved.get("alias") else None
        if doc:
            found["derby"] = screen_of(derby.view(L, family, doc, True), derby.keyboard(L, doc))
    state = await manager_net.tourney_state(store, clan.alias)
    found["tourney"] = screen_of(tourney_ui.open_view(L, state),
                                 tourney_ui.open_keyboard(L, state))
    return found


async def integration_lists(store, clan, conf):
    return {"twitch": integrations.block(conf, manager_net.TWITCH_BLOCK).get("channel") or "",
            "discord": bool(await store.get_state(clan.alias, manager_net.DISCORD_STATE)),
            "ics": bool(settings_mod.web_conf(conf).get(manager_net.ICS_FIELD))}


async def of(store, clan, conf, war, levels):
    found = {}
    if not levels:
        return found
    if pack_on(conf, "wars"):
        found["wars"] = await war_rows(store, clan, war)
    if not any(level == MANAGER for level in levels.values()):
        return found
    if pack_on(conf, "cwl"):
        league = await cwl_lists(store, clan)
        if league:
            found["cwl"] = league
    found["leaders"] = tool_lists(conf, await ledger.notes_all(store, clan.alias),
                                  await base_videos.stored_channels(store, clan.alias),
                                  await base_packs.proposals(store, clan.alias))
    if pack_on(conf, "recruitment"):
        found["recruitment"] = await recruit_lists(store, clan, conf)
    if pack_on(conf, "family"):
        found["family"] = await family_lists(store, clan, i18n.locale(conf.get("lang")))
    if pack_on(conf, "integrations"):
        found["integrations"] = await integration_lists(store, clan, conf)
    return found
