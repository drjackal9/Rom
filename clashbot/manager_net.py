from . import derby, familyroom, integrations, ledger, reasons, tournaments, tourney_ui, twitch
from . import settings as settings_mod
from .handlers import save_settings
from .platform_guard import IDLE_TTL
from .reasons import refuse

TOURNEY_KEY = "tourney:{alias}"
FAMILY_LOG = "family"
INTEGRATION_LOG = "integration"
OPEN = "go"
CANCEL = "cancel"
OFF = "off"
CLAN_SCOPE = "clan"
NETWORK_SCOPE = "network"
DISCORD_STATE = "discord"
TWITCH_BLOCK = "twitch"
ICS_FIELD = "ics"


def tourney_key(alias):
    return TOURNEY_KEY.format(alias=alias)


async def tourney_state(store, alias):
    kept = await store.kv_get(tourney_key(alias))
    return dict(kept) if isinstance(kept, dict) else tourney_ui.new_state(CLAN_SCOPE)


async def told(act, action, detail):
    await ledger.record(act.store, act.clan.alias, action, act.uid, act.name, detail, act.now)
    return True


async def family_create(act):
    name = str(act.body.get("name") or "").strip()
    if not name:
        return refuse(reasons.BAD)
    alias = await act.store.create_family(name, act.uid, act.clan.bot_alias)
    await act.store.add_family_clan(alias, act.clan.alias)
    return await told(act, FAMILY_LOG, name)


async def family_invite(act):
    alias = str(act.body.get("ref") or "")
    family = await act.store.family_by_alias(alias)
    if not family or family.bot_alias != act.clan.bot_alias:
        return refuse(reasons.GONE)
    await act.store.add_family_clan(alias, act.clan.alias)
    return await told(act, FAMILY_LOG, family.name)


def family_owner(family):
    return int(getattr(family, "owner_id", 0) or 0) if family else 0


def owns_family(act, family):
    return bool(family) and family_owner(family) == int(act.uid)


async def family_derby(act):
    family = await act.store.family_of_clan(act.clan.alias)
    if not owns_family(act, family):
        return refuse(reasons.NOT_MANAGER)
    saved = await act.store.kv_get(derby.saved_key(family.alias))
    doc = await act.store.tournament((saved or {}).get("alias")) if (saved or {}).get("alias") else None
    if not doc:
        return refuse(reasons.GONE)
    doc = derby.apply(doc, str(act.body.get("data") or ""))
    if derby.skipped(doc):
        await act.store.save_tournament(doc["alias"], doc, "done")
        await familyroom.drop_notice(act.store, family, familyroom.DERBY_KIND)
    else:
        await act.store.save_tournament(doc["alias"], doc)
    return await told(act, FAMILY_LOG, familyroom.DERBY_KIND)


async def open_tourney(act, state):
    family = await act.store.family_of_clan(act.clan.alias)
    doc = tourney_ui.to_doc(state, act.now)
    if doc["scope"] != CLAN_SCOPE and not family:
        return refuse(reasons.GONE)
    if doc["scope"] == NETWORK_SCOPE and not tournaments.network_ready(
            await act.store.network_get(act.clan.alias)):
        return refuse(reasons.CLOSED)
    doc["origin"] = act.clan.alias
    shared = family.alias if family and doc["scope"] != CLAN_SCOPE else None
    await act.store.create_tournament(doc, act.uid, family_alias=shared,
                                      clan_alias=None if shared else act.clan.alias)
    await act.store.kv_del(tourney_key(act.clan.alias))
    return True


async def family_tourney(act):
    data = str(act.body.get("data") or "")
    if data.split(":")[1:2] == [CANCEL]:
        await act.store.kv_del(tourney_key(act.clan.alias))
        return True
    state = await tourney_state(act.store, act.clan.alias)
    if data.split(":")[1:2] == [OPEN]:
        opened = await open_tourney(act, state)
        if not reasons.done(opened):
            return reasons.code_of(opened)
    else:
        await act.store.kv_set(tourney_key(act.clan.alias), tourney_ui.handle(state, data),
                               ref=act.clan.alias, ttl=IDLE_TTL)
    return await told(act, FAMILY_LOG, data)


async def twitch_act(act):
    wanted = str(act.body.get("channel") or "")
    login = twitch.normalize_login(wanted) if wanted else None
    if wanted and not login:
        return refuse(reasons.BAD)
    stored = dict(integrations.block(act.conf, TWITCH_BLOCK))
    if login:
        stored["channel"] = login
    else:
        stored.pop("channel", None)
    await save_settings(act.store, act.clan, {TWITCH_BLOCK: stored})
    return await told(act, INTEGRATION_LOG, TWITCH_BLOCK)


async def discord_act(act):
    if str(act.body.get("on") or "") != OFF:
        return refuse(reasons.BAD)
    await act.store.del_state(act.clan.alias, DISCORD_STATE)
    return await told(act, INTEGRATION_LOG, DISCORD_STATE)


async def ics_act(act):
    web = dict(settings_mod.web_conf(act.conf))
    web[ICS_FIELD] = str(act.body.get("on") or "") != OFF
    await save_settings(act.store, act.clan, {"web": web})
    return await told(act, INTEGRATION_LOG, ICS_FIELD)


HANDLERS = {"family.create": family_create, "family.invite": family_invite,
            "family.derby": family_derby, "family.tourney": family_tourney,
            "integration.twitch": twitch_act, "integration.discord": discord_act,
            "integration.ics": ics_act}
