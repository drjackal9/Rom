from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import incidents, ledger, linking, manager_alerts, render, roles
from . import settings as settings_mod
from .events_registry import PLATFORM_OPENED
from .util import CLAN_SLOTS

KEY = "platform_delegates"
OWNER = "owner"
DELEGATE = "delegate"
ACTIONS = ("delegates", "deladd", "deldrop")
MEDIA = ("media", "mediaadd", "mediadrop", "mediaofficial")
OPEN = ("refresh", "reports", "rep", "usage", "otp", "otpnew") + MEDIA + incidents.OPEN
LOG_KIND = manager_alerts.ACTIONS
OPEN_REASONS = ("support", "abuse", "legal", "bug")
OPEN_LOG = "platform"
OPEN_HELD = "platform_open"
OPENED = PLATFORM_OPENED
NEWS = "news"
ICON = "🎖"
TITLE = "panel.delegates.title"
BACK = "panel:refresh"
BOUND = "✅"
WAITING = "⏳"


def clean(raw):
    name = str(raw or "").strip().lstrip("@").strip()
    if not name or not name.isascii():
        return None
    return name if all(ch.isalnum() or ch == "_" for ch in name) else None


def same(row, name):
    return str(row.get("username") or "").lower() == str(name or "").lower()


async def delegates(store):
    stored = await store.kv_get(KEY)
    return [dict(row) for row in stored or [] if isinstance(row, dict) and clean(row.get("username"))]


async def level(store, uid):
    if uid is None:
        return None
    owner = await store.get_secret("owner_id")
    if owner and str(uid) == str(owner):
        return OWNER
    for row in await delegates(store):
        if row.get("user_id") is not None and str(row["user_id"]) == str(uid):
            return DELEGATE
    return None


def allowed(action, lvl):
    return lvl == OWNER or (lvl == DELEGATE and action in OPEN)


async def bind(store, user, at):
    name = clean(getattr(user, "username", None))
    if not name:
        return False
    rows = await delegates(store)
    fresh = [row for row in rows if same(row, name) and row.get("user_id") is None]
    if not fresh:
        return False
    for row in fresh:
        row["user_id"] = int(user.id)
        row["bound"] = float(at)
    await store.kv_set(KEY, rows)
    return True


async def add(store, raw, at):
    name = clean(raw)
    if not name:
        return None
    rows = await delegates(store)
    if not any(same(row, name) for row in rows):
        rows.append({"username": name, "user_id": None, "since": float(at)})
        await store.kv_set(KEY, rows)
    return name


async def drop(store, raw):
    name = clean(raw)
    rows = await delegates(store)
    kept = [row for row in rows if not same(row, name)]
    if not name or len(kept) == len(rows):
        return None
    await store.kv_set(KEY, kept)
    return name


def mark(row):
    return BOUND if row.get("user_id") is not None else WAITING


def line(L, row):
    name = render.esc(row.get("username"))
    if row.get("user_id") is None:
        return L.t("panel.delegates.row", mark=mark(row), username=name)
    return L.t("panel.delegates.bound", mark=mark(row), username=name, uid=int(row["user_id"]),
               when=L.ago(manager_alerts.moment(row.get("bound"))))


def page(L, rows, note=None):
    body = [note] if note else []
    body.append(L.t("panel.delegates.body"))
    body.append(render.quote("\n".join(line(L, row) for row in rows)) if rows
                else L.t("panel.delegates.empty"))
    buttons = [[InlineKeyboardButton(L.t("panel.delegates.btn_drop", username=row["username"]),
                                     callback_data=f"panel:deldrop:{row['username']}")]
               for row in rows]
    buttons.append([InlineKeyboardButton(L.t("panel.delegates.btn_add"), callback_data="panel:deladd"),
                    InlineKeyboardButton(L.t("console.btn_back"), callback_data=BACK)])
    return render.card(ICON, L.t(TITLE), "\n".join(body)), InlineKeyboardMarkup(buttons)


def ask(L, bad=False):
    body = L.t("panel.delegates.ask")
    if bad:
        body = L.t("panel.delegates.bad") + "\n" + body
    back = InlineKeyboardButton(L.t("console.btn_back"), callback_data="panel:delegates")
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup([[back]])


async def act(store, L, action, arg, at):
    raw = str(arg or "").strip()
    if action == "deladd" and not raw:
        return ask(L)
    if action == "deladd":
        name = await add(store, raw, at)
        if not name:
            return ask(L, bad=True)
        return page(L, await delegates(store),
                    L.t("panel.delegates.added", username=render.esc(name)))
    if action == "deldrop":
        name = await drop(store, raw)
        note = L.t("panel.delegates.dropped", username=render.esc(name)) if name else None
        return page(L, await delegates(store), note)
    return page(L, await delegates(store))


async def note_action(store, what, uid, at):
    entry = {"what": what, "who": int(uid)}
    return await manager_alerts.record(store, LOG_KIND, f"{what}:{uid}:{at}", entry, float(at))


def open_note(reason):
    return lambda L: L.t("feed.platform.opened", reason=L.t("platform.reason." + reason))


async def open_data(store, clan, conf, uid, reason, at):
    if reason not in OPEN_REASONS:
        return None
    await ledger.record(store, clan.alias, OPEN_LOG, uid, None, reason, at)
    await manager_alerts.opened(store, at)
    members = await store.get_state(clan.alias, "members") or {}
    for chief in sorted(await roles.chiefs(store, members))[:CLAN_SLOTS]:
        await linking.tell(store, clan.alias, chief, conf, open_note(reason), at, OPENED)
    return {"reason": reason, "at": float(at.timestamp())}


async def open_bot(store, alias, uid, reason, at):
    if reason not in OPEN_REASONS:
        return []
    opened = []
    for clan in (await store.active_clans(alias))[:CLAN_SLOTS]:
        conf = settings_mod.effective(await store.get_state(clan.alias, "settings"))
        if await open_data(store, clan, conf, uid, reason, at):
            opened.append(clan.alias)
    return opened


def hold(data, alias):
    if isinstance(data, dict):
        data[OPEN_HELD] = str(alias)


def held(data, alias):
    return str((data or {}).get(OPEN_HELD) or "") == str(alias)


def spend(data, alias):
    if not isinstance(data, dict) or not held(data, alias):
        return False
    data.pop(OPEN_HELD, None)
    return True
