from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .leaderboards import TOP as BOARD_TOP
from .render import card, clip, esc, quote
from .ttl import GONE_TTL
from .util import CLAN_SLOTS

NOTICE_KEEP = 5
NOTICE_TTL = GONE_TTL
MESSAGE_MAX = 700
MESSAGE_EVERY = 3600
CHECK_EVERY = 600
SUGGEST_KEEP = BOARD_TOP
DERBY_KIND = "derby"


def _int(value):
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _key(family):
    return f"fam:{family.alias}:notices"


async def notices_of(store, family):
    saved = await store.kv_get(_key(family))
    return [row for row in (saved or []) if isinstance(row, dict)][:NOTICE_KEEP]


async def push_notice(store, family, kind, text, now):
    notices = [{"kind": kind, "text": str(text)[:MESSAGE_MAX], "ts": int(now.timestamp())}]
    notices += await notices_of(store, family)
    notices = notices[:NOTICE_KEEP]
    await store.kv_set(_key(family), notices, ttl=NOTICE_TTL)
    return notices


async def drop_notice(store, family, kind):
    notices = [row for row in await notices_of(store, family) if row.get("kind") != kind]
    await store.kv_set(_key(family), notices, ttl=NOTICE_TTL)
    return notices


def notice_lines(L, notices, derby_lines=None):
    out = []
    for row in notices or ():
        if row.get("kind") == DERBY_KIND and derby_lines:
            out += list(derby_lines)
            continue
        out.append(L.t("family.notice.row", icon=L.t(f"family.notice.icon.{row.get('kind')}"),
                       text=esc(row.get("text"))))
    return out


def _target(clans, alias, level):
    here = _int(clans[alias].get("min_th"))
    best, why = None, None
    for other_alias, other in clans.items():
        if other_alias == alias or CLAN_SLOTS - _int(other.get("members")) <= 0:
            continue
        there = _int(other.get("min_th"))
        if here and level < here and level >= there:
            reason = "below"
        elif there > here and level >= there:
            reason = "up"
        else:
            continue
        if (best is None or (reason == "below" and why == "up")
                or (reason == why and there > _int(best.get("min_th")))):
            best, why = other, reason
    return best, why


def suggestions(rows, members):
    clans = {row["alias"]: row for row in rows or () if row.get("alias")}
    out = []
    for alias, row in clans.items():
        for member in (members.get(alias) or {}).values():
            level = _int(member.get("th"))
            if not level:
                continue
            best, why = _target(clans, alias, level)
            if best:
                out.append({"name": member.get("name"), "th": level, "from": row.get("name"),
                            "from_alias": alias, "to": best.get("name"),
                            "to_alias": best.get("alias"), "why": why})
    out.sort(key=lambda item: (-item["th"], item["name"] or ""))
    return out[:SUGGEST_KEEP]


def suggest_digest(rows):
    return repr([(row["name"], row["from"], row["to"], row["why"]) for row in rows or ()])


def suggest_card(L, family, rows):
    lines = [L.t(f"family.suggest.row.{row['why']}", name=esc(row["name"]), th=row["th"],
                 from_clan=esc(row["from"]), to_clan=esc(row["to"])) for row in rows or ()]
    body = quote("\n".join(lines)) if lines else L.t("family.suggest.none")
    return clip(card("🔁", L.t("family.suggest.title", name=esc(family.name).upper()), body))


def preview_card(L, family, text, n):
    body = quote(esc(text)) + "\n\n" + L.t("family.message.preview", n=n, name=esc(family.name))
    return clip(card("📣", L.t("family.message.title", name=esc(family.name).upper()), body))


def preview_keyboard(L):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("family.message.btn.send"), callback_data="fa:send"),
        InlineKeyboardButton(L.t("family.message.btn.cancel"), callback_data="fa:cancel"),
    ]])


def message_card(L, family, text):
    return clip(card("📣", L.t("family.message.title", name=esc(family.name).upper()),
                     quote(esc(text))))
