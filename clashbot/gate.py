from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError

from . import ttl

IN_GROUP = (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER, ChatMemberStatus.RESTRICTED)
PENDING_TTL = ttl.RETRY_TTL


def pending_key(alias, user_id):
    return f"gate:{alias}:{user_id}"


async def clan_and_family_members(store, clan):
    members = dict(await store.get_state(clan.alias, "members") or {})
    family = await store.family_of_clan(clan.alias)
    if family:
        for other in await store.family_clans(family.alias):
            if other.alias == clan.alias:
                continue
            members.update(await store.get_state(other.alias, "members") or {})
    return members


async def member_name(store, clan, user_id):
    links = await store.links_by_user(user_id)
    if not links:
        return None
    members = await clan_and_family_members(store, clan)
    for link in links:
        if link.tag in members:
            return (members[link.tag] or {}).get("name") or link.name
    return None


async def verdict(store, clan, user_id):
    name = await member_name(store, clan, user_id)
    return ("approve", name) if name else ("ask", None)


async def still_in_group(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramError:
        return False
    return getattr(member, "status", None) in IN_GROUP


def leave_rows(events):
    return [e for e in (events or ())
            if isinstance(e, dict) and e.get("type") == "leave" and e.get("tag")]


async def leavers_to_report(bot, store, clan, events):
    names = {e["tag"]: e.get("name") for e in leave_rows(events)}
    if not names:
        return []
    rows = []
    for tag, link in (await store.links_for_players(list(names))).items():
        if await still_in_group(bot, clan.chat_id, link.user_id):
            rows.append({"name": names.get(tag) or link.name, "user_id": link.user_id})
    return rows
