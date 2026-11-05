from urllib.parse import urlencode

from ..i18n import LANGUAGES
from ..recruit import is_verified
from ..util import esc
from .pages import BOARD, REFRESH, ROW, facts, foot, grid, shell, top_bar
from .payload import SLUG_LEN

PAGE_SIZE = 40
TH_MAX = 17
CODE_MAX = SLUG_LEN
BOT_MAX = 32
NONE = {"lang": None, "country": None, "min_th": None}


def wanted(query):
    raw_lang = (query.get("lang") or [""])[0]
    raw_country = str((query.get("country") or [""])[0]).upper()
    raw_th = str((query.get("th") or [""])[0])
    return {
        "lang": raw_lang if raw_lang in LANGUAGES else None,
        "country": raw_country if len(raw_country) == 2 and raw_country.isalpha() else None,
        "min_th": min(TH_MAX, int(raw_th)) or None if raw_th.isdigit() else None,
    }


def deep_link(target, code):
    bot = str((target or {}).get("bot") or "")
    if not bot or len(bot) > BOT_MAX or not bot.replace("_", "").isalnum():
        return ""
    if not code or len(code) > CODE_MAX or not str(code).isalnum():
        return ""
    return f"https://t.me/{bot}?start=apply_{code}"


def trail(picked, name, value):
    keep = {"lang": picked["lang"], "country": picked["country"], "th": picked["min_th"]}
    keep[name] = value
    query = urlencode([(key, one) for key, one in keep.items() if one])
    return f"/board?{query}" if query else "/board"


def chip(href, label, on):
    return f'<a class="chip{" on" if on else ""}" href="{esc(href)}">{esc(label)}</a>'


def offered(found, field, current):
    values = {str(row[field]) for row in found if row.get(field)}
    if current:
        values.add(str(current))
    return sorted(values)


def chip_row(L, label, name, choices, current, picked):
    chips = [chip(trail(picked, name, None), L.t("web.board.any"), current is None)]
    chips += [chip(trail(picked, name, value), text, value == current) for value, text in choices]
    return (f'<p class="chips"><span class="muted">{esc(L.t(label))}</span> '
            + "".join(chips) + "</p>")


def filters(L, found, picked):
    langs = [(code, LANGUAGES.get(code, code)) for code in offered(found, "lang", picked["lang"])]
    lands = [(code, code) for code in offered(found, "country", picked["country"])]
    halls = [(hall, L.n(hall)) for hall in range(TH_MAX, 0, -1)]
    return (chip_row(L, "web.board.filter_lang", "lang", langs, picked["lang"], picked)
            + chip_row(L, "web.board.filter_country", "country", lands, picked["country"], picked)
            + chip_row(L, "web.board.filter_th", "th", halls, picked["min_th"], picked))


def head_of(L, row):
    if row.get("name"):
        head = esc(row["name"])
        if row.get("tag"):
            head += f' <span class="muted">{esc(row["tag"])}</span>'
    else:
        head = esc(L.t("web.board.anon", code=str(row.get("code") or "")))
    if is_verified(row):
        head += f' <span class="muted">{esc(L.t("recruit.verified"))}</span>'
    return head


def bits_of(L, row):
    bits = [L.t("recruit.req_th", th=int(row["min_th"])) if row.get("min_th")
            else L.t("recruit.req_any")]
    if row.get("lang"):
        bits.append(L.t("web.board.lang", lang=LANGUAGES.get(row["lang"], row["lang"])))
    if row.get("country"):
        bits.append(str(row["country"]))
    return facts((esc(one) for one in bits), "muted")


def tile(L, row, live):
    code = str(row.get("code") or "")
    href = f"/c/{code}" if live else f"/r/{code}"
    goes = L.t("web.board.page") if live else L.t("web.board.contact")
    return (f'<a class="tile" href="{esc(href)}">'
            f'<span class="big">{head_of(L, row)}</span>'
            f'<span>{esc(L.t("web.board.free", n=int(row.get("free") or 0)))}</span>'
            f"{bits_of(L, row)}"
            f'<span class="muted">{esc(goes)}</span></a>')


def block(L, found, picked, codes=None, limit=None):
    known = set(codes or ())
    tiles = [tile(L, row, str(row.get("code") or "") in known) for row in found[:limit]]
    return filters(L, found, picked) + (
        grid(tiles, ROW) if tiles else f'<p class="muted">{esc(L.t("web.board.empty"))}</p>')


def board_page(L, found, picked, codes=None, links=None):
    body = (f"{top_bar(BOARD, links)}<h1>{esc(L.t('web.board.title'))}</h1>"
            f'<p class="lede">{esc(L.t("web.board.intro"))}</p>'
            f"{block(L, found, picked, codes)}"
            f"<footer>{foot(L)}</footer>")
    return shell(L.t("web.board.title"), body, L.code, meta=REFRESH)
