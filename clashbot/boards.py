import hashlib
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import MessageLimit

from . import i18n
from .events import missing_attackers
from .events_registry import CLAN_PACKS as PACKS
from .progress import DAY
from .quiet import SEPARATOR, total_length
from .render import board_card, clip
from .util import parse_coc_time

LIMIT = int(MessageLimit.MAX_TEXT_LENGTH)
FALLBACK = i18n.locale(i18n.DEFAULT)
SECTION_ORDER = ("wars", "cwl", "capital_games", "members", "challenges", "family",
                 "recruitment", "bases")
PIN_KEYS = ("message_id", "digest", "updated")
IDLE = "idle"
TELLS_MISSING = ("war", "cwl")
LOST = "lost"
REBUILDS = 1
DOT = " · "
FOUGHT = ("inWar", "warEnded")
HOUR = DAY // 24
MINUTE = HOUR // 60


def lines_of(state, pack):
    return list(((state or {}).get(pack) or {}).get("lines") or [])


def message_of(state, pack):
    return ((state or {}).get(pack) or {}).get("message_id")


def fit(L, pack, lines, reserve=0):
    kept = [line for line in lines if line]
    while kept and len(board_card(L, pack, SEPARATOR.join(kept))) + reserve > LIMIT:
        kept.pop(0)
    return kept


def epoch(now):
    try:
        return int(now.timestamp())
    except (AttributeError, OSError, OverflowError, TypeError, ValueError):
        return None


def events_of(state, packs=None):
    rows = []
    for pack in SECTION_ORDER:
        if packs is not None and pack not in packs:
            continue
        rows.extend(dict(row) for row in ((state or {}).get(pack) or {}).get("events") or ())
    rows.sort(key=lambda row: row.get("at") or 0, reverse=True)
    return rows


def _told(state, pack, facts, at, keep):
    told = list(((state or {}).get(pack) or {}).get("events") or ())
    for fact in facts or ():
        told.append({"pack": pack, "kind": fact.get("kind"), "who": fact.get("who"),
                     "n": fact.get("n"), "at": at})
    return told[-keep:] if keep else []


def append(state, pack, lines, now, tz, digest=None, facts=None):
    stamp = FALLBACK.clock(now, tz)
    fresh = [f"{stamp} · {line}" for line in lines if line]
    if not fresh:
        return state
    entry = dict((state or {}).get(pack) or {})
    entry["lines"] = fit(FALLBACK, pack, lines_of(state, pack) + fresh)
    entry["dirty"] = True
    at = epoch(now)
    if at:
        entry["at"] = at
    if digest is not None:
        entry["digest"] = digest
    told = _told(state, pack, facts, at, len(entry["lines"]))
    if told:
        entry["events"] = told
    elif "events" in entry:
        entry.pop("events")
    updated = dict(state or {})
    updated[pack] = entry
    return updated


def digest_of(state, pack):
    return ((state or {}).get(pack) or {}).get("digest")


def text_digest(text):
    return hashlib.sha256((text or "").encode()).hexdigest()


def keyboard_digest(text, markup):
    rows = markup.inline_keyboard if markup else ()
    links = [button.url or "" for row in rows for button in row]
    return text_digest("".join([text or ""] + links))


def render(L, pack, state):
    return board_card(L, pack, SEPARATOR.join(fit(L, pack, lines_of(state, pack))))


def updated_at(state, packs):
    stamps = [((state or {}).get(pack) or {}).get("at") for pack in packs]
    return max([at for at in stamps if at], default=None)


def head_all(L, state, packs, clan, tz, snapshot=None):
    line = ticker(L, snapshot) if snapshot else None
    lines = [line] if line else []
    if (snapshot or {}).get("kind") != IDLE:
        lines.append(L.t("board.all.title", clan=clan))
    at = updated_at(state, packs)
    if at:
        when = L.clock(datetime.fromtimestamp(at, timezone.utc), tz)
        lines.append(L.t("board.all.updated", time=when))
    return "\n".join(lines)


def fighting(war):
    return bool(war) and war.get("state") == "inWar"


def ticker_snapshot(clan, war, cwl_war, capital, now):
    if fighting(war):
        attacks = sum(int(m["left"]) for m in missing_attackers(war))
        if attacks:
            return {"kind": "war", "missing": attacks, "end": war.get("endTime"), "now": now}
    if fighting(cwl_war):
        lazy = len(missing_attackers(cwl_war))
        if lazy:
            return {"kind": "cwl", "day": cwl_war.get("day"), "missing": lazy}
    if (capital or {}).get("state") == "ongoing":
        free = int((capital or {}).get("free") or 0)
        if free:
            return {"kind": "raid", "free": free}
    return {"kind": IDLE, "clan": clan}


def ticker(L, snapshot):
    kind = (snapshot or {}).get("kind")
    if kind == "war":
        return L.t("ticker.war", missing=snapshot["missing"],
                   left=L.delta(parse_coc_time(snapshot.get("end")), snapshot.get("now")))
    if kind == "cwl":
        return L.t("ticker.cwl", day=snapshot.get("day"), missing=snapshot["missing"])
    if kind == "raid":
        return L.t("ticker.raid", free=snapshot["free"])
    return L.t("ticker.idle", clan=(snapshot or {}).get("clan") or "")


MINI_APP = "ClanBoard"


def open_url(console, slug):
    return f"https://t.me/{console}/{MINI_APP}?startapp={slug}"


def open_markup(L, console, slug):
    if not console or not slug:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        L.t("board.all.open"), url=open_url(console, slug))]])


def numbers_of(war, agenda, now):
    stars = None
    if war and war.get("state") in FOUGHT:
        stars = (int((war.get("clan") or {}).get("stars") or 0),
                 int((war.get("opponent") or {}).get("stars") or 0))
    missing = sum(int(row["left"]) for row in missing_attackers(war)) if fighting(war) else 0
    soon = None
    for item in agenda or ():
        start = item.get("start")
        if start and start > now and (soon is None or start < soon["start"]):
            soon = item
    ahead = {"key": soon["key"], "in_seconds": int((soon["start"] - now).total_seconds())} \
        if soon else None
    return {"stars": stars, "missing": missing, "next": ahead}


def left_in(L, seconds):
    left = max(0, int(seconds or 0))
    if left >= DAY:
        return f"{left // DAY}{L.t('unit.d')}"
    if left >= HOUR:
        return f"{left // HOUR}{L.t('unit.h')}"
    return f"{left // MINUTE}{L.t('unit.m')}"


def numbers_row(L, numbers, told=False):
    parts = []
    stars = (numbers or {}).get("stars")
    if stars:
        parts.append(L.t("board.short.stars", us=stars[0], them=stars[1]))
    missing = int((numbers or {}).get("missing") or 0)
    if missing and not told:
        parts.append(L.t("board.short.missing", n=missing))
    ahead = (numbers or {}).get("next")
    if ahead:
        parts.append(L.t("board.short.next", what=L.t(f"agenda.item.{ahead['key']}"),
                         left=left_in(L, ahead.get("in_seconds"))))
    return DOT.join(parts)


def render_short(L, header, snapshot, numbers):
    head = ticker(L, snapshot) if snapshot else L.t("board.all.title", clan=header)
    row = numbers_row(L, numbers, (snapshot or {}).get("kind") in TELLS_MISSING)
    return f"{head}\n{row}" if row else head


def section(L, pack, lines, empty):
    return board_card(L, pack, SEPARATOR.join(lines) or empty)


def render_all(L, state, packs, header, tz, snapshot=None):
    chosen = [pack for pack in SECTION_ORDER if pack in (packs or ())]
    kept = {pack: lines_of(state, pack) for pack in chosen}
    empty = L.t("board.all.empty")
    cards = {pack: section(L, pack, kept[pack], empty) for pack in chosen}
    head = head_all(L, state, chosen, header, tz, snapshot)
    while True:
        parts = [head] + [cards[pack] for pack in chosen]
        if total_length(parts) <= LIMIT:
            return SEPARATOR.join(parts)
        widest = max((pack for pack in chosen if len(kept[pack]) > 1),
                     key=lambda pack: len(cards[pack]), default=None)
        if not widest:
            return clip(SEPARATOR.join(parts))
        kept[widest] = kept[widest][1:]
        cards[widest] = section(L, widest, kept[widest], empty)


def dirty(state):
    return [pack for pack in PACKS if ((state or {}).get(pack) or {}).get("dirty")]


def retire(state, pack):
    entry = dict((state or {}).get(pack) or {})
    entry.pop("message_id", None)
    updated = dict(state or {})
    updated[pack] = entry
    return updated


def published(state, pack, message_id=None):
    entry = dict((state or {}).get(pack) or {})
    if message_id:
        entry["message_id"] = message_id
    entry["dirty"] = False
    updated = dict(state or {})
    updated[pack] = entry
    return updated


def message_id(state):
    return (state or {}).get("message_id")


def legacy_packs(state):
    return [pack for pack in PACKS if message_of(state, pack)]


def legacy_ids(state):
    return [message_of(state, pack) for pack in legacy_packs(state)]


def publish_all(state, message_id):
    updated = dict(state or {})
    if message_id:
        updated["message_id"] = message_id
    for pack in PACKS:
        entry = (state or {}).get(pack)
        if not entry:
            continue
        entry = dict(entry)
        entry.pop("message_id", None)
        entry["dirty"] = False
        updated[pack] = entry
    return updated


def pin_of(state):
    found = {key: (state or {}).get(key) for key in PIN_KEYS}
    return {key: value for key, value in found.items() if value is not None}


def drop_pin(state):
    updated = dict(state or {})
    for key in PIN_KEYS:
        updated.pop(key, None)
    return updated


def keep_pin(state, pin):
    updated = publish_all(state, (pin or {}).get("message_id"))
    for key in PIN_KEYS:
        value = (pin or {}).get(key)
        if value is not None:
            updated[key] = value
    return updated


def losses(state, now_ts, window):
    saved = (state or {}).get(LOST) or {}
    at = float(saved.get("at") or 0)
    return dict(saved) if float(now_ts) - at < float(window) else {}


def lost(state, now_ts, window):
    saved = losses(state, now_ts, window)
    updated = dict(state or {})
    updated[LOST] = {"at": float(saved.get("at") or now_ts), "n": int(saved.get("n") or 0) + 1}
    return updated


def rebuilt(state, now_ts, window):
    return int(losses(state, now_ts, window).get("n") or 0) >= REBUILDS


def given_up(state, now_ts, window):
    return int(losses(state, now_ts, window).get("n") or 0) > REBUILDS
