import html
import io
import math
import re

from PIL import Image, ImageDraw, ImageFont, features

from . import render
from .events import performances

SIZE = (1200, 630)
MARGIN = 56
KINDS = ("war_end", "season", "player", "week", "clan_week")
BASE = (14, 18, 27)
PANEL = (25, 31, 45)
INK = (238, 242, 250)
MUTED = (150, 162, 184)
DEFAULT_ACCENT = (240, 186, 70)
RESULT_COLORS = {"win": (86, 196, 122), "lose": (226, 100, 100), "tie": (150, 162, 184)}
BADGE_BOX = 108
CONTENT_TOP = 198
CONTENT_BOTTOM = 544
FOOTER_BASE = 590
SCORE_HEIGHT = 140
ROW_HEIGHT = 44
PANEL_PAD = 36
GAP = 18
CHIP_HEIGHT = 88
CHIP_COLUMNS = 4
TOP_ROWS = 3
TAGS = re.compile(r"<[^>]+>")
MAX_BADGE_SIDE = 512

SCRIPTS = {
    "it": "latin", "en": "latin", "es": "latin", "pt-BR": "latin", "de": "latin", "fr": "latin",
    "tr": "latin", "id": "latin", "vi": "latin", "nl": "latin", "pl": "latin", "ru": "cyrillic",
    "ar": "arabic", "fa": "arabic", "hi": "devanagari", "th": "thai", "zh-Hans": "hans",
    "zh-Hant": "hant", "ja": "japanese", "ko": "korean",
}
RTL = ("arabic",)
FACES = {
    "latin": (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ),
    "cyrillic": (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ),
    "arabic": (
        ("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ),
    "devanagari": (
        ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ),
    "thai": (
        ("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ),
    "hans": (
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    ),
}
FACES["hant"] = FACES["hans"]
FACES["japanese"] = FACES["hans"]
FACES["korean"] = FACES["hans"]

_FONTS = {}


def plain(text):
    return html.unescape(TAGS.sub("", str(text if text is not None else ""))).strip()


def _load(script, bold, size):
    for path in FACES.get(script, FACES["latin"])[1 if bold else 0]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def font(code, size, bold=False):
    script = SCRIPTS.get(code, "latin")
    key = (script, bold, size)
    if key not in _FONTS:
        _FONTS[key] = _load(script, bold, size) or ImageFont.load_default(size)
    return _FONTS[key]


def missing_scripts():
    return tuple(script for script in sorted(set(SCRIPTS.values())) if _load(script, False, 20) is None)


def direction(code):
    if features.check("raqm") and SCRIPTS.get(code) in RTL:
        return "rtl"
    return None


def fit(text, face, width):
    body = str(text or "")
    if face.getlength(body) <= width:
        return body
    while body and face.getlength(body + "…") > width:
        body = body[:-1]
    return body + "…" if body else ""


def _lift(color, floor=150):
    r, g, b = color
    light = (r * 299 + g * 587 + b * 114) // 1000
    if light >= floor or light == 0:
        return (r, g, b)
    gain = floor / max(1, light)
    return tuple(min(255, int(v * gain)) for v in (r, g, b))


def accent(badge):
    if not badge:
        return DEFAULT_ACCENT
    try:
        with Image.open(io.BytesIO(badge)) as img:
            counted = img.convert("RGBA").resize((16, 16)).getcolors(256)
    except (OSError, ValueError, Image.DecompressionBombError):
        return DEFAULT_ACCENT
    best, score = DEFAULT_ACCENT, -1
    for _, pixel in counted or ():
        r, g, b, a = pixel
        if a < 200:
            continue
        weight = (max(r, g, b) - min(r, g, b)) * 2 + max(r, g, b)
        if weight > score:
            best, score = (r, g, b), weight
    return _lift(best)


def _mix(one, two, ratio):
    return tuple(int(a + (b - a) * ratio) for a, b in zip(one, two))


def _canvas(tone):
    image = Image.new("RGB", SIZE, BASE)
    d = ImageDraw.Draw(image)
    top = _mix(BASE, tone, 0.16)
    for y in range(SIZE[1]):
        d.line([(0, y), (SIZE[0], y)], fill=_mix(top, BASE, y / SIZE[1]))
    d.rectangle([(0, 0), (SIZE[0], 8)], fill=tone)
    return image, d


def _star(d, x, y, radius, fill):
    points = []
    for step in range(10):
        angle = -math.pi / 2 + step * math.pi / 5
        length = radius if step % 2 == 0 else radius * 0.42
        points.append((x + length * math.cos(angle), y + length * math.sin(angle)))
    d.polygon(points, fill=fill)


def _badge(image, badge, box):
    if not badge:
        return False
    try:
        with Image.open(io.BytesIO(badge)) as raw:
            if max(raw.size) > MAX_BADGE_SIDE:
                return False
            art = raw.convert("RGBA").resize((box, box), Image.LANCZOS)
    except (OSError, ValueError, Image.DecompressionBombError):
        return False
    image.paste(art, (MARGIN, MARGIN), art)
    return True


def room(spec):
    used = SCORE_HEIGHT + GAP if spec.get("score") else 0
    used += (CHIP_HEIGHT + GAP) * min(2, -(-len(spec.get("chips") or []) // CHIP_COLUMNS))
    return max(0, (CONTENT_BOTTOM - CONTENT_TOP - used - PANEL_PAD) // ROW_HEIGHT)


def draw(spec, badge=None):
    code = spec.get("code") or "en"
    tone = spec.get("accent") or accent(badge)
    rtl = direction(code)
    image, d = _canvas(tone)
    placed = _badge(image, badge, BADGE_BOX)
    left = MARGIN + (BADGE_BOX + 28 if placed else 0)
    width = SIZE[0] - left - MARGIN
    d.text((left, MARGIN + 2), fit(spec.get("title"), font(code, 52, True), width),
           font=font(code, 52, True), fill=INK, direction=rtl)
    if spec.get("subtitle"):
        d.text((left, MARGIN + 72), fit(spec["subtitle"], font(code, 28), width),
               font=font(code, 28), fill=MUTED, direction=rtl)
    top = CONTENT_TOP
    if spec.get("score"):
        top = _score(d, code, spec["score"], top, tone, rtl, spec.get("result"))
    rows = (spec.get("rows") or [])[: room(spec)]
    if rows:
        top = _rows(d, code, rows, top, tone, rtl)
    if spec.get("chips"):
        _chips(d, code, spec["chips"], top, tone, rtl)
    d.text((MARGIN, FOOTER_BASE), fit(spec.get("footer"), font(code, 24), SIZE[0] - 2 * MARGIN),
           font=font(code, 24), fill=MUTED, anchor="ls", direction=rtl)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _panel(d, top, height, tone):
    d.rounded_rectangle([(MARGIN, top), (SIZE[0] - MARGIN, top + height)], 24, fill=PANEL)
    d.rounded_rectangle([(MARGIN, top), (MARGIN + 8, top + height)], 4, fill=tone)


def _score(d, code, score, top, tone, rtl, result=None):
    _panel(d, top, SCORE_HEIGHT, tone)
    middle = SIZE[0] // 2
    d.line([(middle, top + 28), (middle, top + SCORE_HEIGHT - 28)], fill=_mix(PANEL, INK, 0.18), width=2)
    for side, anchor, x in (("left", "lm", MARGIN + 40), ("right", "rm", SIZE[0] - MARGIN - 40)):
        part = score.get(side) or {}
        color = RESULT_COLORS.get(result, tone) if side == "left" else MUTED
        d.text((x, top + 44), fit(part.get("name"), font(code, 32, True), 420),
               font=font(code, 32, True), fill=INK, anchor=anchor, direction=rtl)
        number = str(part.get("stars", 0))
        d.text((x, top + 98), number, font=font(code, 42, True), fill=color, anchor=anchor)
        span = font(code, 42, True).getlength(number)
        star_x = x + span + 28 if side == "left" else x - span - 28
        _star(d, star_x, top + 95, 18, color)
        d.text((star_x + (30 if side == "left" else -30), top + 98), part.get("destr") or "",
               font=font(code, 28), fill=MUTED, anchor="lm" if side == "left" else "rm")
    return top + SCORE_HEIGHT + GAP


def _rows(d, code, rows, top, tone, rtl):
    height = PANEL_PAD + ROW_HEIGHT * len(rows)
    _panel(d, top, height, tone)
    y = top + PANEL_PAD // 2 + ROW_HEIGHT // 2
    for row in rows:
        if row.get("rank"):
            d.text((MARGIN + 36, y), row["rank"], font=font(code, 28, True), fill=tone, anchor="lm")
        d.text((MARGIN + 92, y), fit(row.get("name"), font(code, 30, True), 540),
               font=font(code, 30, True), fill=INK, anchor="lm", direction=rtl)
        d.text((SIZE[0] - MARGIN - 36, y), fit(row.get("value"), font(code, 30, True), 240),
               font=font(code, 30, True), fill=tone, anchor="rm", direction=rtl)
        if row.get("extra"):
            d.text((SIZE[0] - MARGIN - 196, y), fit(row["extra"], font(code, 26), 200),
                   font=font(code, 26), fill=MUTED, anchor="rm", direction=rtl)
        y += ROW_HEIGHT
    return top + height + GAP


def _chips(d, code, chips, top, tone, rtl):
    width = (SIZE[0] - 2 * MARGIN - 24 * (CHIP_COLUMNS - 1)) // CHIP_COLUMNS
    for index, chip in enumerate(chips[: CHIP_COLUMNS * 2]):
        column, line = index % CHIP_COLUMNS, index // CHIP_COLUMNS
        x = MARGIN + column * (width + 24)
        y = top + line * (CHIP_HEIGHT + GAP)
        d.rounded_rectangle([(x, y), (x + width, y + CHIP_HEIGHT)], 20, fill=PANEL)
        d.text((x + 22, y + 26), fit(chip.get("label"), font(code, 22), width - 44),
               font=font(code, 22), fill=MUTED, anchor="lm", direction=rtl)
        d.text((x + 22, y + 62), fit(chip.get("value"), font(code, 30, True), width - 44),
               font=font(code, 30, True), fill=tone if line == 0 else INK, anchor="lm", direction=rtl)


def footer(L, tag=None, site=None):
    if site:
        return L.t("card.footer_site", brand=L.t("card.brand"), site=site)
    if tag:
        return L.t("card.footer", brand=L.t("card.brand"), tag=tag)
    return L.t("card.brand")


def build_war_end(L, war, result, kind="war", day=None, tag=None, site=None):
    ours, theirs = war["clan"], war["opponent"]
    best = [p for p in performances(war) if p["attacks"]][:TOP_ROWS]
    key = "card.war.subtitle_cwl" if kind == "cwl" else "card.war.subtitle"
    return {
        "kind": "war_end",
        "code": L.code,
        "result": result,
        "title": L.t("card.war.title", result=plain(L.t(f"war_end.{result}.title")),
                     stars=ours["stars"], opp_stars=theirs["stars"]),
        "subtitle": L.t(key, day=plain(render.war_title(L, kind, day)),
                        ours=ours["name"], theirs=theirs["name"]),
        "score": {
            "left": {"name": ours["name"], "stars": ours["stars"], "destr": L.pct(ours["destr"])},
            "right": {"name": theirs["name"], "stars": theirs["stars"], "destr": L.pct(theirs["destr"])},
        },
        "rows": [{"rank": L.t("rank.n", n=i + 1), "name": p["name"], "value": str(p["stars"]),
                  "extra": L.pct(p["destr"] / p["attacks"], 0)} for i, p in enumerate(best)],
        "footer": footer(L, tag, site),
    }


def build_season(L, sid, titles, tag=None, site=None):
    rows = []
    for name, pair in (titles or {}).items():
        who, value = tuple(pair)[:2]
        rows.append({"rank": None, "name": L.t("card.title_row", title=L.t(f"title.{name}"), name=who),
                     "value": L.n(value)})
    return {
        "kind": "season",
        "code": L.code,
        "title": plain(L.t("season_end.title")),
        "subtitle": render.season_label(L, sid),
        "rows": rows,
        "footer": footer(L, tag, site),
    }


def build_player(L, snapshot, tag, clan_name=None, site=None):
    p = snapshot or {}
    heroes = "/".join(str(level) for level in (p.get("heroes") or {}).values() if level)
    pref = p.get("warPref") if p.get("warPref") in ("in", "out") else "unknown"
    return {
        "kind": "player",
        "code": L.code,
        "title": p.get("name") or tag,
        "subtitle": L.t("card.player.subtitle", tag=tag, clan=clan_name) if clan_name else tag,
        "rows": [],
        "chips": [
            {"label": L.t("card.label.th"), "value": str(p.get("th") or "?")},
            {"label": L.t("card.label.league"), "value": p.get("league") or L.t("me.no_league")},
            {"label": L.t("card.label.trophies"), "value": L.n(p.get("trophies"))},
            {"label": L.t("card.label.best"), "value": L.n(p.get("best"))},
            {"label": L.t("card.label.war_stars"), "value": L.n(p.get("warStars"))},
            {"label": L.t("card.label.donations"), "value": L.n(p.get("donations"))},
            {"label": L.t("card.label.heroes"), "value": heroes or "?"},
            {"label": L.t("card.label.war"), "value": L.t(f"card.war_pref.{pref}")},
        ],
        "footer": footer(L, None, site),
    }
