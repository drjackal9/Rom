from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import render
from .util import valid_telegram
from .web.payload import PUBLIC, SLUG_LEN

KEY = "site"
GROUP = "community_url"
EXAMPLE = "example_code"
FIELDS = (GROUP, EXAMPLE)
ACTIONS = ("site", "siteset", "siteclear")
WRITES = ("siteset", "siteclear")
FLOW = "site"
ICON = "🌐"
TITLE = "panel.site.title"
NONE = "panel.site.none"
BAD = "panel.site.bad"
HOME = "panel:site"
BACK = "panel:refresh"
ROWS = {GROUP: "panel.site.group", EXAMPLE: "panel.site.example"}
SETS = {GROUP: "panel.site.set_group", EXAMPLE: "panel.site.set_example"}
CLEARS = {GROUP: "panel.site.clear_group", EXAMPLE: "panel.site.clear_example"}
ASKS = {GROUP: "panel.site.ask_group", EXAMPLE: "panel.site.ask_example"}


def clean(name, value):
    raw = value.strip() if isinstance(value, str) else ""
    if name == GROUP:
        return raw if valid_telegram(raw) else ""
    if name == EXAMPLE:
        return raw if raw.isascii() and raw.isalnum() and len(raw) <= SLUG_LEN else ""
    return ""


async def read(store):
    stored = await store.kv_get(KEY)
    found = stored if isinstance(stored, dict) else {}
    return {name: clean(name, found.get(name)) for name in FIELDS}


async def write(store, name, value):
    if name not in FIELDS:
        return False
    found = await read(store)
    found[name] = clean(name, value)
    await store.kv_set(KEY, found)
    return True


async def accepted(store, name, raw):
    value = clean(name, raw)
    if name == EXAMPLE and value and not await store.web_page(value, PUBLIC):
        return ""
    return value


def asked(action, arg):
    return arg if action == "siteset" and arg in FIELDS else None


def page(L, found):
    body, buttons = [], []
    for name in FIELDS:
        value = found.get(name)
        body.append(L.t(ROWS[name], value=render.esc(value) if value else L.t(NONE)))
        buttons.append([InlineKeyboardButton(L.t(SETS[name]),
                                             callback_data=f"panel:siteset:{name}")])
        if value:
            buttons[-1].append(InlineKeyboardButton(L.t(CLEARS[name]),
                                                    callback_data=f"panel:siteclear:{name}"))
    buttons.append([InlineKeyboardButton(L.t("console.btn_back"), callback_data=BACK)])
    return render.card(ICON, L.t(TITLE), "\n".join(body)), InlineKeyboardMarkup(buttons)


def ask(L, name, bad=False):
    body = L.t(ASKS[name])
    if bad:
        body = L.t(BAD) + "\n" + body
    back = InlineKeyboardButton(L.t("console.btn_back"), callback_data=HOME)
    return render.card(ICON, L.t(TITLE), body), InlineKeyboardMarkup([[back]])


async def act(store, L, action, arg):
    name = arg if arg in FIELDS else None
    if action == "siteset" and name:
        return ask(L, name)
    if action == "siteclear" and name:
        await write(store, name, "")
    return page(L, await read(store))
