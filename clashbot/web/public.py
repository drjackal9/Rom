from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from ..base_videos import THUMB, THUMB_HOST, THUMB_SIZE, WATCH
from ..bases import LABELS, hall_name, label_name, parse_link
from ..news_feed import EVENT, GOLDPASS, VIDEO
from ..render import fixed
from ..util import esc
from . import art
from .board import TH_MAX, chip, offered
from .pages import (BASES, CSP_BASE, NEWS, RANK, RANK_TITLE, REFRESH, ROW, facts, foot, grid,
                    shell, top_bar)

CSP_MEDIA = CSP_BASE.replace("img-src data:", f"img-src data: {THUMB_HOST}")
TITLE = "web.home.tile.bases"
HALL = "web.page.th"
KIND = "web.app.bases.kind"
BY = "web.app.bases.by"
VIDEOS = "web.app.bases.videos"
EMPTY = "web.app.empty.screen"
ANY = "web.board.any"
NEWS_TITLE = "web.home.tile.news"
PASS = "web.news.pass"
ITEM = "agenda.item."
STATE = "web.page."
SEASON = "season"
ONGOING = "ongoing"
UPCOMING = "upcoming"
EMPTY_ART = "platform"
ANON = "network.anon"
RANK_NOTE = "Opted-in clans, points per member."
STARS_WORD = "war stars"
MEMBERS_WORD = "members"
WHOLE = 100


def wanted(query):
    raw_hall = str((query.get("th") or [""])[0])
    raw_kind = str((query.get("kind") or [""])[0]).strip().lower()
    hall = min(TH_MAX, int(raw_hall)) if raw_hall.isdigit() else 0
    return hall or None, raw_kind or None


def halls_of(rows, hall=None):
    return sorted((int(one) for one in offered(rows, "hall", hall)), reverse=True)


def kind_name(L, kind):
    return label_name(L, kind) if kind in LABELS else kind


def kinds_of(rows):
    return sorted({row["kind"] for row in rows if row.get("kind")})


def kept(rows, hall, kind):
    return [row for row in rows
            if (hall is None or int(row.get("hall") or 0) == hall)
            and (kind is None or row.get("kind") == kind)]


def trail(hall, kind):
    query = urlencode([(name, value) for name, value in (("th", hall), ("kind", kind)) if value])
    return f"{BASES}?{query}" if query else BASES


def chip_row(L, label, made):
    return (f'<p class="chips"><span class="muted">{esc(L.t(label))}</span> '
            + "".join(chip(href, text, on) for href, text, on in made) + "</p>")


def hall_chips(L, rows, hall, kind):
    made = [(trail(None, kind), L.t(ANY), hall is None)]
    made += [(trail(one, kind), L.n(one), one == hall) for one in halls_of(rows, hall)]
    return chip_row(L, HALL, made)


def kind_chips(L, rows, hall, kind):
    made = [(trail(hall, None), L.t(ANY), kind is None)]
    made += [(trail(hall, one), kind_name(L, one), one == kind) for one in kinds_of(rows)]
    return chip_row(L, KIND, made)


def out(href, inside):
    return f'<a class="tile" href="{esc(href)}" target="_blank" rel="noopener">{inside}</a>'


def base_tile(L, row):
    parts = [f'<span class="big">{esc(hall_name(row.get("village"), row.get("hall")))}</span>']
    if row.get("kind"):
        parts.append(f'<span>{esc(kind_name(L, row["kind"]))}</span>')
    if row.get("builder"):
        parts.append(f'<span class="muted">{esc(L.t(BY, name=row["builder"]))}</span>')
    return out(row["link"], "".join(parts))


def video_tile(row):
    found = quote(str(row.get("id")), safe="")
    return out(WATCH + found,
               f'<img class="shot" src="{esc(THUMB + found + THUMB_SIZE)}" alt="" loading="lazy">'
               f'<span>{esc(row.get("title") or "")}</span>')


def empty_tile(L):
    return (f'<div class="tile">{art.icon(EMPTY_ART)}'
            f'<span class="muted">{esc(L.t(EMPTY))}</span></div>')


def block(L, tiles):
    return grid(tiles if tiles else [empty_tile(L)], ROW)


def stats(row):
    found = row.get("metrics")
    return found if isinstance(found, dict) else {}


def rate(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def share(avg, top):
    return round(WHOLE * avg / top) if top else 0


def named(L, row):
    return row.get("name") or L.t(ANON, code=str(row.get("code") or ""))


def rank_tile(L, row, place, top):
    found = stats(row)
    avg = rate(found.get("avg"))
    return (f'<div class="tile"><span class="badge">{place}</span>'
            f'<span class="big">{esc(fixed(L, avg, 1))}</span>'
            f'<span>{esc(named(L, row))}</span>'
            f'<div class="bar"><div class="bar-fill" style="width:{share(avg, top)}%"></div></div>'
            + facts((esc(f'{L.n(found.get("stars") or 0)} {STARS_WORD}'),
                      esc(f'{L.n(found.get("members") or 0)} {MEMBERS_WORD}')), "muted")
            + "</div>")


def rank_block(L, rows, limit=None):
    found = [row for row in rows or () if isinstance(row, dict)]
    top = max((rate(stats(row).get("avg")) for row in found), default=0)
    return block(L, [rank_tile(L, row, place, top)
                     for place, row in enumerate(found[:limit], start=1)])


def rank_page(L, rows, links=None):
    body = (f"{top_bar(RANK, links)}<h1>{esc(RANK_TITLE)}</h1>"
            f'<p class="lede">{esc(RANK_NOTE)}</p>'
            f"{rank_block(L, rows)}"
            f"<footer>{foot(L)}</footer>")
    return shell(RANK_TITLE, body, L.code, meta=REFRESH)


def of_kind(rows, kind):
    return [row for row in rows or () if isinstance(row, dict) and row.get("kind") == kind]


def moment(value):
    try:
        return datetime.fromtimestamp(int(value), timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def count_tile(L, when, name, note, now):
    return (f'<div class="tile"><span class="big">{esc(L.delta(when, now))}</span>'
            f"<span>{esc(name)}</span>"
            f'<span class="muted">{esc(note)}</span></div>')


def pass_tile(L, row, now):
    end = moment(row.get("end"))
    return count_tile(L, end, L.t(PASS), L.when(end), now) if end else ""


def event_tile(L, row, now):
    state = ONGOING if row.get("state") == ONGOING else UPCOMING
    when = moment(row.get("end") if state == ONGOING else row.get("start"))
    if not when:
        return ""
    return count_tile(L, when, L.t(ITEM + str(row.get("key"))), L.t(STATE + state), now)


def news_page(L, rows, now, links=None):
    passes = of_kind(rows, GOLDPASS)
    tiles = [pass_tile(L, row, now) for row in passes]
    tiles += [event_tile(L, row, now) for row in of_kind(rows, EVENT)
              if not (passes and row.get("key") == SEASON)]
    clips = [video_tile(row) for row in of_kind(rows, VIDEO) if row.get("id")]
    title = L.t(NEWS_TITLE)
    body = (f"{top_bar(NEWS, links)}<h1>{esc(title)}</h1>"
            f"{block(L, [one for one in tiles if one])}"
            f"<h2>{esc(L.t(VIDEOS))}</h2>{block(L, clips)}"
            f"<footer>{foot(L)}</footer>")
    return shell(title, body, L.code)


def bases_page(L, rows, videos, hall=None, kind=None, links=None):
    found = [row for row in rows or () if parse_link(row.get("link"))]
    kind = kind if kind in kinds_of(found) else None
    title = L.t(TITLE)
    body = (f"{top_bar(BASES, links)}<h1>{esc(title)}</h1>"
            f"{hall_chips(L, found, hall, kind)}{kind_chips(L, found, hall, kind)}"
            f"{block(L, [base_tile(L, row) for row in kept(found, hall, kind)])}"
            f'<h2>{esc(L.t(VIDEOS))}</h2>'
            f"{block(L, [video_tile(row) for row in videos or () if row.get('id')])}"
            f"<footer>{foot(L)}</footer>")
    return shell(title, body, L.code)
