from . import platform_ban, reasons
from .leaders import ROLES as LEADER_ROLES
from .privacy import user_key, userclan_key
from .util import normalize_tag

TERMS = "terms"


def clan_roles(clan_json):
    return {m.get("tag"): m.get("role") for m in (clan_json or {}).get("memberList", [])}


async def linked_leader(store, user_id, roles):
    for link in await store.links_by_user(user_id):
        if link.verified and roles.get(link.tag) in LEADER_ROLES:
            return link
    return None


async def check_player(coc, roles, raw):
    tag = normalize_tag(raw)
    if not tag or roles.get(tag) not in LEADER_ROLES:
        return None, "not_leader"
    data, error = await coc.player(tag)
    if not data:
        return None, error
    return {"tag": tag, "name": data.get("name")}, None


async def check_token(coc, tag, token):
    ok, error = await coc.verify_token(tag, token)
    if error:
        return error
    return None if ok else "token_invalid"


def terms_key(store, user_id):
    return user_key(store, TERMS, user_id)


async def terms_day(store, user_id):
    found = await store.kv_get(terms_key(store, user_id))
    if not isinstance(found, dict) or not found.get("day"):
        return None
    return str(found["day"])


async def accept_terms(store, user_id, now):
    day = await terms_day(store, user_id)
    if day:
        return day
    day = now.date().isoformat()
    await store.kv_set(terms_key(store, user_id), {"day": day})
    return day


async def link_verified(store, user_id, tag, name, lang=None):
    if await platform_ban.refuses(store, user_id, [tag]):
        return reasons.BANNED
    if not await terms_day(store, user_id):
        return reasons.TERMS
    await store.kv_del(userclan_key(store, user_id))
    await store.link_player(user_id, tag, name, lang=lang)
    return None
