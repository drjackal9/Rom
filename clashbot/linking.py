from collections import namedtuple

from . import feed, i18n, platform_ban, reasons, verify
from .events_registry import LINK_NEWS
from .reasons import refuse
from .settings import effective

ON = "on"
TAKEN = "link.taken"
BAD_TOKEN = "link.bad_token"
LOST = "feed.link.lost"
NOTES = {TAKEN: "feed.link.taken", BAD_TOKEN: "feed.link.bad_token"}
FAULTS = {TAKEN: reasons.TAKEN, reasons.BANNED: reasons.BANNED, reasons.TERMS: reasons.TERMS}

Who = namedtuple("Who", "id lang")


async def tell(store, alias, uid, conf, render_text, now, kind=LINK_NEWS):
    from .poller import member_locale
    links = await store.links_by_user(int(uid))
    L = (await member_locale(store, links[0], conf) if links
         else i18n.locale((conf or {}).get("lang")))
    await feed.add(store, alias, int(uid), kind, render_text(L), now)


async def owner_of(store, tag):
    return (await store.links_for_players([tag])).get(tag)


async def warn_owner(store, clan, uid, name, now, key="feed.link.owner"):
    from .handlers import clan_of_user
    found = clan or await clan_of_user(store, uid)
    if not found:
        return
    conf = effective(await store.get_state(found.alias, "settings"), None)
    await tell(store, found.alias, uid, conf, lambda L: L.t(key, name=name), now)


def former_of(owner, who):
    if not owner or int(owner.user_id) == int(who.id):
        return None
    return int(owner.user_id)


async def link_player(store, coc, who, tag, name, token, now, clan=None):
    if await platform_ban.refuses(store, who.id, [tag]):
        return None, reasons.BANNED
    owner = await owner_of(store, tag)
    former = former_of(owner, who)
    if former is not None and getattr(owner, "verified", True):
        await warn_owner(store, clan, former, name, now)
        return owner, TAKEN
    error = await verify.check_token(coc, tag, token)
    if error:
        return None, BAD_TOKEN if error == "token_invalid" else error
    refused = await verify.link_verified(store, who.id, tag, name, who.lang)
    if refused:
        return None, refused
    if former is not None:
        await warn_owner(store, clan, former, name, now, LOST)
    return await owner_of(store, tag), None


def village_of(act):
    return str(act.body.get("village") or "")


async def name_of(act, tag):
    members = await act.store.get_state(act.clan.alias, "members") or {}
    return (members.get(tag) or {}).get("name")


async def mine(act):
    return {link.tag for link in await act.store.links_by_user(act.uid)}


async def agreed(act):
    if str(act.body.get("terms") or "") == ON:
        return bool(await verify.accept_terms(act.store, act.uid, act.now))
    return bool(await verify.terms_day(act.store, act.uid))


async def verify_act(act):
    tag = village_of(act)
    name = await name_of(act, tag)
    if not name or not act.coc:
        return refuse(reasons.GONE)
    if await platform_ban.refuses(act.store, act.uid, [tag]):
        return refuse(reasons.BANNED)
    if not await agreed(act):
        return refuse(reasons.TERMS)
    _, error = await link_player(act.store, act.coc, Who(act.uid, None), tag, name,
                                 str(act.body.get("token") or ""), act.now, act.clan)
    if error:
        if error in NOTES:
            await tell(act.store, act.clan.alias, act.uid, act.conf,
                       lambda L: L.t(NOTES[error], name=name), act.now)
        return refuse(FAULTS.get(error, reasons.BAD))
    await tell(act.store, act.clan.alias, act.uid, act.conf,
               lambda L: L.t("feed.link.verified", name=name), act.now)
    return True


async def whisper_act(act):
    tag = village_of(act)
    if tag not in await mine(act):
        return refuse(reasons.NOT_LINKED)
    await act.store.set_link_whisper(act.uid, tag, str(act.body.get("on") or "") == ON)
    return True


async def drop_act(act):
    tag = village_of(act)
    if tag not in await mine(act):
        return refuse(reasons.NOT_LINKED)
    if not await act.store.unlink(act.uid, tag):
        return refuse(reasons.GONE)
    return True


HANDLERS = {
    "link.verify": verify_act,
    "link.whisper": whisper_act,
    "link.drop": drop_act,
}
