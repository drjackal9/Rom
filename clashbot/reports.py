import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import codes, manager_alerts, render
from .manager_alerts import REPORT_MARK
from .platform_guard import FLOOD_WINDOW, flood_state, flooding, recent

log = logging.getLogger("clashbot.reports")

REASONS = ("spam", "scam", "harassment", "impersonation", "other_no_text")
ACTIONS = ("reports", "rep", "stop", "token")
FLOOD_KEY = "reported:{alias}:{uid}"
STOP_REASON = "reported"
ICON = "🚩"
TITLE = "panel.reports.title"
BACK = "panel:refresh"


def flood_key(alias, uid):
    return FLOOD_KEY.format(alias=alias or "-", uid=int(uid))


async def add(store, alias, uid, reason, now):
    if reason not in REASONS:
        raise ValueError("reason")
    key = flood_key(alias, uid)
    stored = await store.kv_get(key)
    if flooding({"hits": recent((stored or {}).get("hits"), now.timestamp())}):
        return False
    await store.kv_set(key, flood_state(stored, now.timestamp()), ref=alias, ttl=FLOOD_WINDOW)
    await store.report_add(alias, uid, reason, now)
    return True


async def forget(store, alias, uid):
    await store.kv_del(flood_key(alias, uid))
    return await store.report_forget(alias, uid)


def label(L, reason):
    return L.t(f"report.reasons.{reason}") if reason in REASONS else render.esc(str(reason))


def listed(rows):
    found = []
    for row in rows:
        if row.get("code") and row["code"] not in found:
            found.append(row["code"])
    return found


def line(L, row, now):
    return L.t("panel.reports.row", code=render.esc(row.get("code")),
               reason=label(L, row.get("reason")),
               when=L.ago(manager_alerts.moment(row.get("at")), now))


def back_keyboard(L):
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t("panel.reports.btn_close"),
                                                       callback_data=BACK)]])


def page(L, rows, now):
    if not rows:
        return render.card(ICON, L.t(TITLE), L.t("panel.reports.empty")), back_keyboard(L)
    body = render.quote("\n".join(line(L, row, now) for row in rows))
    buttons = [[InlineKeyboardButton(code, callback_data=f"panel:rep:{code}")]
               for code in listed(rows)]
    buttons.append([InlineKeyboardButton(L.t("panel.reports.btn_close"), callback_data=BACK)])
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup(buttons)


def clan_page(L, code, rows, now, full=True):
    picked = [row for row in rows if row.get("code") == code]
    body = L.t("panel.reports.clan", code=render.esc(code), n=len(picked))
    if picked:
        body += "\n" + render.quote("\n".join(line(L, row, now) for row in picked))
    buttons = []
    if full:
        buttons.append(
            [InlineKeyboardButton(L.t("panel.reports.btn_suspend"), callback_data=f"panel:stop:{code}"),
             InlineKeyboardButton(L.t("panel.reports.btn_token"), callback_data=f"panel:token:{code}")])
    buttons.append([InlineKeyboardButton(L.t("panel.reports.btn_close"), callback_data=BACK)])
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup(buttons)


async def note_decision(store, code, at):
    entry = {"what": REPORT_MARK, "code": str(code)}
    return await manager_alerts.record(store, manager_alerts.ACTIONS,
                                       f"{REPORT_MARK}:{code}:{at}", entry, float(at))


async def bot_of(store, code):
    clan = await codes.clan_for(store, code)
    owner = getattr(clan, "bot_alias", None) if clan else None
    return await store.bot_by_alias(owner) if owner else None


async def suspend(store, supervisor, bot):
    await store.set_bot_active(bot.alias, False, STOP_REASON)
    await supervisor.stop_bot(bot.alias)


async def swap(store, supervisor, manager, bot):
    try:
        await supervisor.swap_token(manager, bot)
    except Exception as e:
        log.warning("%s: token non sostituito (%s)", bot.alias, type(e).__name__)
        return False
    if bot.active:
        await supervisor.restart_bot(bot.alias)
    else:
        await store.set_bot_active(bot.alias, False, bot.reason)
    return True


async def act(store, supervisor, manager, L, action, code, rows, now, full=True):
    if action == "reports":
        return page(L, rows, now)
    if not full:
        return clan_page(L, code, rows, now, full)
    bot = await bot_of(store, code)
    if not bot:
        return render.card(ICON, L.t(TITLE), L.t("panel.reports.gone")), back_keyboard(L)
    if action == "stop":
        await suspend(store, supervisor, bot)
        await note_decision(store, code, now.timestamp())
        note = L.t("panel.reports.suspended", code=render.esc(code))
    elif action == "token":
        done = await swap(store, supervisor, manager, bot)
        await note_decision(store, code, now.timestamp())
        note = L.t("panel.reports.token_ok" if done else "panel.reports.token_ko",
                   code=render.esc(code))
    else:
        return clan_page(L, code, rows, now, full)
    return render.card(ICON, L.t(TITLE), note), back_keyboard(L)
