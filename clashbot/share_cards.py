import base64

from telegram import InlineQueryResultPhoto
from telegram.error import TelegramError

from . import cards, media
from .acts import FIELD_MAX
from .events import war_result
from .web.auth import MINIAPP_MAX_AGE

WEEK = "week"
SEASON = "season"
CLAN_WEEK = "clan_week"
WAR = "war_end"
WAR_KIND = "war"
COUNTERS = ("donated", "war_stars", "levels")
CARD_KEY = "share:card:"
READY_KEY = "share:ready:"
SUFFIX = ".png"


def week_card(L, me_view):
    view = me_view or {}
    profile = view.get("profile") or {}
    period = view.get("period") or {}
    chips = [{"label": L.t("web.app.growth." + field), "value": L.n(period.get(field))}
             for field in COUNTERS]
    chips.append({"label": L.t("card.label.trophies"), "value": L.n(profile.get("trophies"))})
    return {"kind": WEEK, "code": L.code,
            "title": view.get("name") or view.get("tag") or "",
            "subtitle": L.t("web.app.growth.week"),
            "rows": [], "chips": chips, "footer": cards.footer(L)}


def season_card(L, view, name):
    found = view or {}
    me = found.get("me") or {}
    chips = [{"label": L.t("web.app.growth." + field), "value": L.n(me.get(field))}
             for field in COUNTERS]
    chips.append({"label": L.t("web.page.points"), "value": L.n(me.get("score"))})
    return {"kind": SEASON, "code": L.code, "title": name or "",
            "subtitle": L.t("web.app.recap.title", season=found.get("season") or ""),
            "rows": [], "chips": chips, "footer": cards.footer(L)}


def clan_card(L, people):
    rows = ((people or {}).get("climb") or {}).get(WEEK) or ()
    return {"kind": CLAN_WEEK, "code": L.code,
            "title": L.t("web.app.clan.climb"),
            "subtitle": L.t("web.app.clan.week"),
            "rows": [{"rank": L.t("rank.n", n=seat + 1), "name": row.get("name"),
                      "value": L.n(row.get("score"))} for seat, row in enumerate(rows)],
            "footer": cards.footer(L)}


def war_card(L, war, kind=None, day=None):
    return cards.build_war_end(L, war, war_result(war), kind or WAR_KIND, day)


def card_key(token):
    return CARD_KEY + str(token or "")


def ready_key(alias, uid):
    return f"{READY_KEY}{alias}:{int(uid)}"


def token_for(vault, alias, uid, kind):
    return vault.blind("share", f"{alias}:{uid}:{kind}")


def card_url(base, token):
    return f"{base.rstrip('/')}/card/{token}{SUFFIX}"


def token_of(name):
    raw = str(name or "")
    return raw[: -len(SUFFIX)] if raw.endswith(SUFFIX) else raw


async def prepare(bot, store, alias, uid, spec, mark):
    base = await media.site_base(store)
    if not bot or not base:
        return None
    png = await media.render_card(spec, None)
    token = token_for(store.vault, alias, uid, spec["kind"])
    await store.kv_set(card_key(token), {"png": base64.b64encode(png).decode()},
                       ref=alias, ttl=MINIAPP_MAX_AGE)
    url = card_url(base, token)
    result = InlineQueryResultPhoto(id=token[:FIELD_MAX], photo_url=url, thumbnail_url=url,
                                    photo_width=cards.SIZE[0], photo_height=cards.SIZE[1])
    try:
        found = await bot.save_prepared_inline_message(uid, result, allow_user_chats=True,
                                                      allow_group_chats=True,
                                                      allow_channel_chats=True)
    except TelegramError:
        return None
    ident = getattr(found, "id", None)
    if ident:
        await store.kv_set(ready_key(alias, uid), {"id": ident, "mark": str(mark or "")},
                           ref=alias, ttl=MINIAPP_MAX_AGE)
    return ident


def png_of(row):
    found = (row or {}).get("png")
    return base64.b64decode(found) if found else None
