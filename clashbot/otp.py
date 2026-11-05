import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import incidents, platform, render, site_conf, source
from .selfmetrics import PLATFORM_INTERVAL

ACTIONS = ("otp", "otpnew")
GUARDED = ("deladd", "deldrop", "seat", "unban", "stop", "token", "mediaadd",
           "mediadrop") + incidents.WRITES + site_conf.WRITES
SEED = "otp:{uid}"
WINDOW = "otpwin:{uid}"
PENDING = "otpnew:{uid}"
ISSUER = source.NAME
DIGITS = 6
STEP = 30
LENGTH = 20
MINUTES = PLATFORM_INTERVAL // 60
ICON = "🔐"
TITLE = "otp.title"
BACK = "panel:refresh"
START = "panel:otpnew"


def seed_of(uid):
    return SEED.format(uid=int(uid))


def window_of(uid):
    return WINDOW.format(uid=int(uid))


def pending_of(uid):
    return PENDING.format(uid=int(uid))


def secret():
    return base64.b32encode(secrets.token_bytes(LENGTH)).decode("ascii")


def step_of(at):
    return int(float(at)) // STEP


def at_step(key, step):
    digest = hmac.new(base64.b32decode(str(key)), struct.pack(">Q", int(step)),
                      hashlib.sha1).digest()
    start = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[start:start + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** DIGITS)).zfill(DIGITS)


def code(key, at):
    return at_step(key, step_of(at))


def verify(key, given, at, last=None):
    want = "".join(str(given or "").split())
    if not key or len(want) != DIGITS or not want.isdigit():
        return None
    now = step_of(at)
    for step in (now, now - 1):
        if last is not None and step <= int(last):
            continue
        if hmac.compare_digest(at_step(key, step), want):
            return step
    return None


def uri(key, label):
    return f"otpauth://totp/{quote(f'{ISSUER}:{label}', safe=':')}?secret={key}&issuer={ISSUER}"


async def stored(store, uid):
    return await store.get_secret(seed_of(uid))


async def active(store, uid):
    return bool(await stored(store, uid))


async def mark(store, uid, step, at):
    await store.kv_set(window_of(uid), {"at": float(at), "step": int(step)},
                       ttl=PLATFORM_INTERVAL)


async def cleared(store, uid, owner, at):
    if not await active(store, uid):
        return bool(owner)
    opened = (await store.kv_get(window_of(uid)) or {}).get("at")
    return opened is not None and float(at) - float(opened) < PLATFORM_INTERVAL


async def forget(store, uid):
    gone = await store.delete_secret(seed_of(uid))
    await store.kv_del(window_of(uid))
    await store.kv_del(pending_of(uid))
    return gone


async def find(store, who):
    name = str(who or "").strip().lstrip("@")
    if name.isdigit():
        return int(name)
    for row in await platform.delegates(store):
        if row.get("user_id") is not None and platform.same(row, name):
            return int(row["user_id"])
    return None


def back_keyboard(L):
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t("console.btn_back"),
                                                       callback_data=BACK)]])


def start_keyboard(L):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(L.t("otp.btn_new"), callback_data=START)],
        [InlineKeyboardButton(L.t("console.btn_back"), callback_data=BACK)],
    ])


def screen(L, name, keyboard, ask, **kw):
    return render.card(ICON, L.t(TITLE), L.t(name, **kw)), keyboard, ask


async def page(store, L, uid):
    if await active(store, uid):
        return screen(L, "otp.on", back_keyboard(L), False, n=MINUTES)
    return screen(L, "otp.off", start_keyboard(L), False)


async def offer(store, L, uid, label, at):
    key = secret()
    await store.kv_set(pending_of(uid), {"key": key, "at": float(at)}, ttl=PLATFORM_INTERVAL)
    return screen(L, "otp.new", back_keyboard(L), True, seed=render.esc(key),
                  uri=render.esc(uri(key, label)))


async def wall(store, L, uid):
    if await active(store, uid):
        return screen(L, "otp.ask", back_keyboard(L), True)
    return screen(L, "otp.needed", start_keyboard(L), False)


def label_of(user):
    return str(getattr(user, "username", None) or getattr(user, "id", ""))


async def act(store, L, action, user, at):
    uid = int(user.id)
    if action == "otpnew" and not await active(store, uid):
        return await offer(store, L, uid, label_of(user), at)
    return await page(store, L, uid)


async def check(store, L, uid, given, at):
    key = await stored(store, uid)
    if key:
        last = (await store.kv_get(window_of(uid)) or {}).get("step")
        step = verify(key, given, at, last)
        if step is None:
            return screen(L, "otp.bad", back_keyboard(L), True)
        await mark(store, uid, step, at)
        return screen(L, "otp.ok", back_keyboard(L), False, n=MINUTES)
    waiting = await store.kv_get(pending_of(uid))
    step = verify((waiting or {}).get("key"), given, at)
    if step is None:
        return screen(L, "otp.bad", back_keyboard(L), True)
    await store.set_secret(seed_of(uid), waiting["key"])
    await store.kv_del(pending_of(uid))
    await mark(store, uid, step, at)
    return screen(L, "otp.ready", back_keyboard(L), False, n=MINUTES)
