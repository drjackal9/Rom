from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import codes, guard, render, roles
from . import settings as settings_mod
from .acts import FIELD_MAX

SEAT_REF = "seat"
ACTIONS = ("seats", "seat")
ICON = "🪑"
TITLE = "panel.seats.title"
BACK = "panel:refresh"


def seat_ref(vault, alias, uid):
    return vault.blind(SEAT_REF, f"{alias}:{int(uid)}")[:FIELD_MAX]


def uid_of(vault, alias, ref, known):
    wanted = str(ref or "")
    return next((int(uid) for uid in sorted(known or ())
                 if seat_ref(vault, alias, uid) == wanted), 0)


async def candidates(store, clan):
    members = await store.get_state(clan.alias, "members") or {}
    links = await store.links_for_players(sorted(members))
    found = {link.user_id for link in links.values()}
    conf = settings_mod.effective(await store.get_state(clan.alias, "settings"), None)
    found.update(int(uid) for uid in (conf.get("delegates") or []))
    creator = await roles.creator_id(store, clan)
    if creator:
        found.add(int(creator))
    return sorted(found)


async def suspended_from(store, alias, uids):
    found = []
    for uid in uids or ():
        if await guard.suspended(store, alias, uid):
            found.append(uid)
    return found


async def suspended_of(store, clan):
    return await suspended_from(store, clan.alias, await candidates(store, clan))


async def rows(store, limit):
    found = []
    for clan in await store.active_clans():
        seats = await suspended_of(store, clan)
        if seats:
            found.append({"alias": clan.alias, "code": store.recruit_code(clan.alias),
                          "seats": seats})
        if len(found) >= limit:
            break
    return found


def back_keyboard(L):
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t("console.btn_back"),
                                                       callback_data=BACK)]])


def page(L, found):
    if not found:
        return render.card(ICON, L.t(TITLE), L.t("panel.seats.empty")), back_keyboard(L)
    body = render.quote("\n".join(
        L.t("panel.seats.row", code=render.esc(row["code"]), n=len(row["seats"]))
        for row in found))
    buttons = [[InlineKeyboardButton(row["code"], callback_data=f"panel:seat:{row['code']}")]
               for row in found]
    buttons.append([InlineKeyboardButton(L.t("console.btn_back"), callback_data=BACK)])
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup(buttons)


async def lift(store, code):
    clan = await codes.clan_for(store, code)
    found = await suspended_of(store, clan) if clan else []
    if not found:
        return None
    done = 0
    for uid in found:
        if await guard.lift(store, clan.alias, uid):
            done += 1
    return done


async def act(store, L, action, code, limit):
    if action == "seats":
        return page(L, await rows(store, limit))
    done = await lift(store, code)
    if done is None:
        return render.card(ICON, L.t(TITLE), L.t("panel.seats.empty")), back_keyboard(L)
    return (render.card(ICON, L.t(TITLE),
                        L.t("panel.seats.lifted", code=render.esc(code), n=done)),
            back_keyboard(L))
