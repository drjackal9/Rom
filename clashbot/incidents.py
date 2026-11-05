from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import render
from .db import INCIDENT_KINDS, INCIDENTS_KEEP
from .leaders import NOTE_MAX, sanitize

ACTIONS = ("incidents", "incopen", "incpick", "incclose")
OPEN = ("incidents",)
WRITES = ("incopen", "incpick", "incclose")
FLOW = "incidents"
KINDS = INCIDENT_KINDS
KEEP = INCIDENTS_KEEP
ICON = "🚨"
TITLE = "panel.incidents.title"
BACK = "panel:ops"
HOME = "panel:incidents"
HOUR = 3600


def kind_label(L, kind):
    return L.t(f"panel.incidents.kind_{kind}")


def hours_of(row):
    opened, closed = row.get("opened"), row.get("closed")
    try:
        return int((closed - opened).total_seconds() // HOUR)
    except (AttributeError, TypeError):
        return None


def line(L, row, now):
    kind = kind_label(L, row.get("kind"))
    if not row.get("closed"):
        head = L.t("panel.incidents.open", kind=kind, when=L.ago(row.get("opened"), now))
    else:
        head = L.t("panel.incidents.closed", kind=kind, n=L.n(hours_of(row) or 0))
    note = str(row.get("note") or "").strip()
    return f"{head}\n{render.esc(note)}" if note else head


def page(L, found, now, full=True):
    body = (render.quote("\n".join(line(L, row, now) for row in found)) if found
            else L.t("panel.incidents.empty"))
    buttons = []
    if full:
        buttons = [[InlineKeyboardButton(L.t("panel.incidents.btn_close",
                                             kind=kind_label(L, row.get("kind"))),
                                         callback_data=f"panel:incclose:{row['id']}")]
                   for row in found if not row.get("closed")]
        buttons.append([InlineKeyboardButton(L.t("panel.incidents.btn_open"),
                                             callback_data="panel:incopen"),
                        InlineKeyboardButton(L.t("console.btn_back"), callback_data=BACK)])
    else:
        buttons.append([InlineKeyboardButton(L.t("console.btn_back"), callback_data=BACK)])
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup(buttons)


def kinds_page(L):
    buttons = [[InlineKeyboardButton(kind_label(L, kind), callback_data=f"panel:incpick:{kind}")]
               for kind in KINDS]
    buttons.append([InlineKeyboardButton(L.t("console.btn_back"), callback_data=HOME)])
    return render.card(ICON, L.t(TITLE), L.t("panel.incidents.pick")), InlineKeyboardMarkup(buttons)


def ask(L, kind):
    back = InlineKeyboardButton(L.t("console.btn_back"), callback_data=HOME)
    body = L.t("panel.incidents.ask", n=NOTE_MAX, kind=kind_label(L, kind))
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup([[back]])


def picked(raw):
    kind = str(raw or "").strip()
    return kind if kind in KINDS else None


async def add(store, kind, raw, now):
    note = sanitize(raw, NOTE_MAX)
    if not picked(kind) or not note:
        return None
    return await store.incident_add(kind, note, now)


async def close(store, raw, now):
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return False
    return await store.incident_close(number, now)


async def act(store, L, action, arg, now, full=True):
    if not full or action == "incidents":
        return page(L, await store.incidents(KEEP), now, full)
    if action == "incopen":
        return kinds_page(L)
    if action == "incpick":
        kind = picked(arg)
        if kind:
            return ask(L, kind)
    elif action == "incclose":
        await close(store, arg, now)
    return page(L, await store.incidents(KEEP), now, full)
