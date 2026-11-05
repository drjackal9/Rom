from . import boards, guard, media, roles
from . import settings as settings_mod
from .web import payload as payload_mod

COURTESY_KEY = "courtesy:{alias}:{uid}"
COURTESY_TTL = 86400

ACTION_BY_COMMAND = {
    "settings": "settings",
    "topics": "settings",
    "stickers": "settings",
    "lang": "settings",
    "tz": "settings",
    "setclan": "settings",
    "remove": "settings",
    "newclan": "settings",
    "warnings": "warnings",
    "rules": "tools",
    "welcome": "tools",
    "schedule": "tools",
    "gate": "tools",
    "note": "tools",
    "log": "tools",
    "export": "tools",
    "applications": "tools",
    "requirements": "tools",
    "family": "tools",
    "calendar": "tools",
    "twitch": "tools",
    "discord": "tools",
}


def courtesy_key(alias, uid):
    return COURTESY_KEY.format(alias=alias or "-", uid=int(uid))


async def open_markup(store, L, clan):
    from .poller import CONSOLE_NAME
    if not clan or not await media.site_base(store):
        return None
    console = await store.kv_get(CONSOLE_NAME)
    if not console:
        return None
    return boards.open_markup(L, console, payload_mod.slug_for(store.vault, clan.alias))


async def courtesy(update, context, store, clan, user):
    from . import handlers as h
    message = getattr(update, "effective_message", None)
    if message is None:
        return
    key = courtesy_key(h.bot_alias(context), user.id)
    if await store.kv_get(key):
        return
    await store.kv_set(key, 1, ref=clan.alias if clan else None, ttl=COURTESY_TTL)
    L = await h.actor_locale(store, update)
    await message.reply_text(L.t("h.private_only"),
                             reply_markup=await open_markup(store, L, clan))


async def refuse(update, context, store, key="h.not_allowed"):
    from . import handlers as h
    message = getattr(update, "effective_message", None)
    if message is None:
        return
    L = await h.actor_locale(store, update)
    await message.reply_text(L.t(key))


async def gate(update, context, action=None):
    from . import handlers as h
    if not h.private_chat(update):
        return None
    user = h.actor(update)
    if not user:
        return None
    store, _ = h.services(context)
    clan = await h.clan_for(update, context)
    if clan and await guard.suspended(store, clan.alias, user.id):
        await refuse(update, context, store, guard.REFUSAL)
        return None
    conf = await h.clan_settings(store, clan) if clan else None
    level = None
    if clan:
        members = await store.get_state(clan.alias, "members") or {}
        level = await roles.level(store, clan, conf, members, user.id)
    if not level and await h.is_owner(update, context):
        level = settings_mod.MANAGER
    if not level:
        await courtesy(update, context, store, clan, user)
        return None
    if action and not settings_mod.allowed(conf or {}, action, level):
        await refuse(update, context, store)
        return None
    return clan, level


def gated(action=None):
    def wrap(handler):
        async def guarded(update, context):
            if await gate(update, context, action) is None:
                return
            await handler(update, context)
        return guarded
    return wrap
