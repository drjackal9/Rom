import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .. import render
from ..db import BAN_KEEP, BAN_KEY
from ..i18n import locale
from ..manager_alerts import moment
from ..platform_guard import FLOOD_LIMIT, FLOOD_WINDOW, flood_state, flooding, recent
from ..util import day_of
from . import http, pages

log = logging.getLogger("clashbot.web")

ACTIONS = ("banned", "unban")
PREFIX = BAN_KEY
HIST = "banhist:"
MISS = "banmiss:"
DAY = 86400
STEPS = (FLOOD_WINDOW, DAY, None)
KEEP = BAN_KEEP
SHOWN = FLOOD_LIMIT
ICON = "🚷"
TITLE = "ban.title"
BACK = "panel:ops"
PROBES = ("/.env", "/.git", "/wp-login.php", "/wp-admin", "/xmlrpc.php", "/phpmyadmin",
          "/admin", "/administrator", "/config", "/.aws", "/panel", "/auth", "/login",
          "/cgi-bin", "/vendor", "/backup")
SPARED = ("/.well-known/security.txt", "/robots.txt")
LEVELS = ("banned_h", "banned_d", "banned_forever")


def is_spared(path):
    return str(path or "").lower() in SPARED


def is_probe(path):
    low = str(path or "").lower()
    return not is_spared(low) and any(low.startswith(one) for one in PROBES)


def key_of(ip):
    return PREFIX + str(ip)


def hist_of(ip):
    return HIST + str(ip)


def miss_of(ip):
    return MISS + str(ip)


def span_of(strikes):
    return STEPS[min(int(strikes), len(STEPS)) - 1]


async def state(store, ip, now):
    stored = await store.kv_get(key_of(ip))
    if not stored:
        return None
    until = stored.get("until")
    if until is not None and float(now) >= float(until):
        return None
    return stored


async def strike(store, ip, now):
    at = float(now)
    strikes = int((await store.kv_get(hist_of(ip)) or {}).get("strikes") or 0) + 1
    span = span_of(strikes)
    row = {"at": at, "until": None if span is None else at + span, "strikes": strikes}
    await store.kv_set(key_of(ip), row, ttl=span)
    await store.kv_set(hist_of(ip), {"strikes": strikes, "at": at},
                       ttl=None if span is None else span + DAY)
    await store.kv_del(miss_of(ip))
    log.info("un indirizzo e stato bandito, colpo numero %s", strikes)
    return row


async def lift(store, ip):
    for key in (key_of(ip), hist_of(ip), miss_of(ip)):
        await store.kv_del(key)


def refusal(L, ip, now):
    return http.Response(pages.warning_page(L or locale("en"), ip, now), 403,
                         headers=pages.headers("no-store", robots="noindex"))


async def unbanned(store, seen, ip, now):
    if await state(store, ip, now) is not None:
        return False
    if len(seen) < http.BUCKET_MAX:
        seen.add(str(ip))
    return True


async def check(store, seen, ip, path, now, L=None):
    if not ip or is_spared(path):
        return None
    if str(ip) in seen or await unbanned(store, seen, ip, now):
        if not is_probe(path):
            return None
        seen.discard(str(ip))
        await strike(store, ip, now)
    return refusal(L, ip, now)


async def miss(store, seen, ip, now):
    if not ip:
        return False
    if str(ip) not in seen and await state(store, ip, now) is not None:
        return False
    key = miss_of(ip)
    fresh = flood_state(await store.kv_get(key), float(now))
    await store.kv_set(key, fresh, ttl=FLOOD_WINDOW)
    if not flooding(fresh):
        return False
    seen.discard(str(ip))
    await strike(store, ip, now)
    return True


def levels(found, day, tz=None):
    made = dict.fromkeys(LEVELS, 0)
    for row in found or ():
        at = row.get("at")
        if at is None or day_of(at, tz) != day:
            continue
        made[LEVELS[min(int(row.get("strikes") or 1), len(LEVELS)) - 1]] += 1
    return made


async def summary(store, now, limit=KEEP):
    found = await store.banned(limit)
    return {"n": len(found), "window": FLOOD_WINDOW,
            "hour": len(recent([row.get("at") for row in found], float(now))),
            "last": found[:SHOWN]}


def line(L, row):
    return L.t("ban.row", ip=render.esc(row["ip"]), when=L.ago(moment(row.get("at"))),
               strikes=int(row.get("strikes") or 1))


def back_keyboard(L):
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t("console.btn_back"),
                                                       callback_data=BACK)]])


def page(L, found):
    if not found:
        return render.card(ICON, L.t(TITLE), L.t("ban.empty")), back_keyboard(L)
    body = L.t("ban.body") + "\n" + render.quote("\n".join(line(L, row) for row in found))
    buttons = [[InlineKeyboardButton(L.t("ban.lift_btn", ip=row["ip"]),
                                     callback_data=f"panel:unban:{row['ip']}")]
               for row in found]
    buttons.append([InlineKeyboardButton(L.t("console.btn_back"), callback_data=BACK)])
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup(buttons)


async def act(store, L, action, arg, limit):
    found = await store.banned(limit)
    if action == "unban" and any(row["ip"] == arg for row in found):
        await lift(store, arg)
        found = await store.banned(limit)
    return page(L, found)
