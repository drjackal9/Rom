from . import (base_videos, brake, guard, i18n, leaders, ledger, linking, manager_staff, media,
               reasons, roles, setup_ui, views, webmenu)
from . import texts as free_text
from .acts import STAFF, SWITCH
from .events_registry import TEXT_REFUSED
from .handlers import save_settings, save_settings_state, settings_state_at
from .reasons import refuse
from .platform_guard import IDLE_TTL
from .settings import MANAGER, web_conf

STEP_KEY = "settings_step:{alias}:{uid}"
PRESS = "settings.press"
TEXT_FIELDS = {"welcome.set": "welcome", "rules.set": "rules"}
PAGE_FIELD = "page"
SETTINGS_LOG = "settings"
INTEGRATION_LOG = "integration"
VIEWS_LOG = "views"
CHANNELS_PER_CLAN = MANAGER


def step_key(alias, uid):
    return STEP_KEY.format(alias=alias, uid=int(uid))


async def kept_at(store, alias, uid):
    return await store.kv_get(step_key(alias, uid)) or {}


async def step_of(store, alias, uid):
    return setup_ui.valid_step((await kept_at(store, alias, uid)).get("step"))


async def first_write(store, alias, uid):
    return not (await kept_at(store, alias, uid)).get(brake.KEY)


async def remember(store, alias, uid, step, counted=False):
    await store.kv_set(step_key(alias, uid),
                       {"step": setup_ui.valid_step(step), brake.KEY: bool(counted)},
                       ref=alias, ttl=IDLE_TTL)


async def screen_of(store, clan, conf, uid, L):
    step = await step_of(store, clan.alias, uid)
    return setup_ui.to_json(L, await settings_state_at(store, clan, conf, uid, step), step)


async def screens(store, clan, conf, members, levels):
    L = i18n.locale((conf or {}).get("lang"))
    staff = await manager_staff.of(store, clan, conf, members, levels, L)
    chiefs = staff.pop(manager_staff.CHIEFS, ())
    waiting = manager_staff.pending_only(staff)
    found = {}
    for uid, level in sorted((levels or {}).items()):
        if level != MANAGER:
            if waiting:
                found[str(uid)] = {STAFF: waiting}
            continue
        found[str(uid)] = {"settings": await screen_of(store, clan, conf, uid, L)}
        if staff:
            found[str(uid)][STAFF] = manager_staff.for_uid(staff, chiefs, uid)
    return found


async def open_act(act):
    await remember(act.store, act.clan.alias, act.uid, setup_ui.STEPS[0])
    return True


async def press_act(act):
    data = str(act.body.get("data") or "")
    if setup_ui.code_of(data) != act.clan.alias:
        return refuse(reasons.BAD)
    kept = await kept_at(act.store, act.clan.alias, act.uid)
    state = await settings_state_at(act.store, act.clan, act.conf, act.uid,
                                    setup_ui.valid_step(kept.get("step")))
    state, step = setup_ui.handle(state, data)
    before, after, written = await save_settings_state(act.store, act.clan, state)
    if written:
        kind, ref = ledger.pressed(data)
        await ledger.acted(act.store, act.clan.alias, kind, ref, act.uid, act.name, now=act.now)
    await remember(act.store, act.clan.alias, act.uid, step, written or kept.get(brake.KEY))
    hit = brake.kind_at(kept.get(brake.KEY), before, after) if written else None
    if hit:
        await guard.destructive(act.store, act.clan.alias, act.uid, hit, act.now)
    return True


async def text_limits(store, clan):
    bot = await store.bot_by_alias(clan.bot_alias)
    return str(getattr(bot, "username", "") or ""), media.host(await media.site_base(store))


async def refuse_text(act, refused):
    await linking.tell(act.store, act.clan.alias, act.uid, act.conf,
                       lambda L: free_text.reason(L, str(refused)), act.now, TEXT_REFUSED)
    return refuse(reasons.TEXT_REFUSED)


async def text_act(act):
    username, site_host = await text_limits(act.store, act.clan)
    try:
        clean = leaders.sanitize(act.body.get("text"), leaders.TEXT_MAX, username, site_host)
    except ValueError as refused:
        return await refuse_text(act, refused)
    field = TEXT_FIELDS[act.kind]
    texts = dict(act.conf.get("texts") or {})
    texts[field] = clean
    await save_settings(act.store, act.clan, {"texts": texts})
    await ledger.record(act.store, act.clan.alias, field, act.uid, act.name, None, act.now)
    return True


async def page_act(act):
    web = web_conf(act.conf)
    if web[PAGE_FIELD] != (str(act.body.get("on") or "") == SWITCH[0]):
        web = web_conf(webmenu.apply(act.conf, PAGE_FIELD))
    await save_settings(act.store, act.clan, {"web": web})
    await ledger.record(act.store, act.clan.alias, SETTINGS_LOG, act.uid, act.name, PAGE_FIELD,
                        act.now)
    return True


async def clan_channels(act):
    return base_videos.clean(await base_videos.stored_channels(act.store, act.clan.alias))


async def channels_cap(act):
    members = await act.store.get_state(act.clan.alias, "members") or {}
    levels = await roles.managers(act.store, act.clan, act.conf, members)
    return sum(1 for level in levels.values() if level == CHANNELS_PER_CLAN)


async def save_channels(act, rows, channel):
    stored = await act.store.get_state(act.clan.alias, base_videos.STATE_KIND)
    kept = dict(stored) if isinstance(stored, dict) else {}
    kept[base_videos.STATE_FIELD] = rows
    await act.store.set_state(act.clan.alias, base_videos.STATE_KIND, kept)
    await ledger.record(act.store, act.clan.alias, INTEGRATION_LOG, act.uid, act.name, channel,
                        act.now)
    return True


async def channel_add(act):
    channel = str(act.body.get("channel") or "")
    rows = await clan_channels(act)
    if not any(row["id"] == channel for row in rows) and len(rows) >= await channels_cap(act):
        return refuse(reasons.CLOSED)
    return await save_channels(act, base_videos.clean(rows + [{"id": channel}]), channel)


async def channel_drop(act):
    channel = str(act.body.get("channel") or "")
    kept = [row for row in await clan_channels(act) if row["id"] != channel]
    return await save_channels(act, kept, channel)


async def saved_views(act, fresh, ref):
    await act.store.set_state(act.clan.alias, views.KIND, fresh)
    await ledger.record(act.store, act.clan.alias, VIEWS_LOG, act.uid, act.name, ref, act.now)
    return True


async def view_act(act):
    stored = await act.store.get_state(act.clan.alias, views.KIND)
    section = str(act.body.get("section") or "")
    try:
        fresh = views.set_one(stored, section, str(act.body.get("value") or ""))
    except ValueError:
        return refuse(reasons.BAD)
    return await saved_views(act, fresh, section)


async def family_score_act(act):
    stored = await act.store.get_state(act.clan.alias, views.KIND)
    return await saved_views(act, views.toggle_family(stored), views.FAMILY)


HANDLERS = {"settings.open": open_act, PRESS: press_act,
            "view.set": view_act, "family.score.toggle": family_score_act,
            "welcome.set": text_act, "rules.set": text_act,
            "page.toggle": page_act, "channel.add": channel_add, "channel.drop": channel_drop}
