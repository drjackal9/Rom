from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .settings import web_conf
from .util import esc

FIELDS = ("page", "members", "stats", "widget", "ics")
LOCKED = ("members", "stats", "widget", "ics")
PATHS = {"page": "", "widget": "/widget", "ics": "/calendar.ics"}
ON = "✅"
OFF = "🚫"


def apply(conf, field):
    if field not in FIELDS:
        return dict(conf or {})
    web = web_conf(conf)
    web[field] = not web[field]
    if field == "page" and not web["page"]:
        for name in LOCKED:
            web[name] = False
    if field in LOCKED and web[field]:
        web["page"] = True
    updated = dict(conf or {})
    updated["web"] = web
    return updated


def links(url, code, web):
    if not url or not web.get("page"):
        return {}
    found = {}
    for field, path in PATHS.items():
        if web.get(field):
            found[field] = f"{url.rstrip('/')}/c/{code}{path}"
    return found


def label(L, web, field):
    return f"{ON if web[field] else OFF} {L.t('web.set.' + field)}"


def rows(L, web, cb):
    return [[InlineKeyboardButton(label(L, web, field), callback_data=cb(field))]
            for field in FIELDS]


def text(L, web, url, code):
    found = links(url, code, web)
    lines = [L.t("web.set.title")]
    lines.append(esc(found["page"]) if found.get("page") else L.t("web.set.no_url"))
    lines += [label(L, web, field) for field in FIELDS]
    lines.append(L.t("web.set.hint"))
    return "\n".join(lines)


def screen(L, conf, url, code, cb):
    web = web_conf(conf)
    return text(L, web, url, code), InlineKeyboardMarkup(rows(L, web, cb))


def ready_text(L, url, code, web):
    found = links(url, code, web)
    if not found:
        return L.t("web.ready.off")
    lines = [L.t("web.ready.title")]
    for field in ("page", "widget", "ics"):
        if field in found:
            lines.append(L.t("web.ready." + field, url=esc(found[field])))
    lines.append(L.t("web.ready.hint"))
    return "\n".join(lines)
