from datetime import datetime, timezone

from ..i18n import LANGUAGES
from ..media import BADGE_HOST
from ..retention import INACTIVE_CLAN_DAYS, WAR_HISTORY_KEEP
from ..util import esc
from . import art, static
from .style import CSS

PAGE_CACHE = 300
PAGE_HEAD = f"public, max-age={PAGE_CACHE}"
FRESH_EVERY = 60
LIVE_HEAD = f"public, max-age={FRESH_EVERY}"
REFRESH = (("http-equiv", "refresh", str(FRESH_EVERY)),)
SHEETS = ("base.css", "site.css")
CSP_BASE = ("default-src 'none'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
            "img-src data:; form-action 'self'; base-uri 'none'")
CSP_CLAN = CSP_BASE.replace("img-src data:", f"img-src data: https://{BADGE_HOST}")
TOP_OPEN = '<header class="top">'
BRAND = '<a class="brand" href="/">ClanBoard</a>'
SECURITY_TXT = "/.well-known/security.txt"
SECURITY = "/security"
RANK = "/leaderboards"
BOARD = "/board"
STATUS = "/status"
BASES = "/bases"
NEWS = "/news"
CREATE = "/create"
COMMUNITY = "/community"
LIVE = "/c/"
RANK_TITLE = "Leaderboards"
MENU = (("Home", "/"), ("Create your bot", CREATE), ("Community", COMMUNITY),
        ("A clan live", LIVE), ("Security", SECURITY), ("Status", STATUS))
SUB = (("Find a clan", BOARD), (RANK_TITLE, RANK), ("Bases", BASES), ("News", NEWS))
SUB_LABEL = "Community"
UNDER = (COMMUNITY,) + tuple(href for _, href in SUB)
MATCH = (("Your clan", 39), ("Rival", 27))
LIVE_WORD = "in progress"
TENS = 6
UNITS = 10
COLS = {2: "two", 3: "three", 4: "four"}
ROW = 3
NUMBERS = 4
WHAT = (("web.home.tile.war", "web.home.tile.war_body"),
        ("web.home.tile.clan", "web.home.tile.clan_body"))
SECTIONS = (("cwl", "web.create.title", "web.create.who", CREATE),
            ("family", "web.community.title", "web.home.network_body", COMMUNITY),
            ("clan", "web.home.live", "web.home.live_body", LIVE),
            ("wars", "web.home.safety", "web.home.safety.data", SECURITY),
            ("platform", "web.status.title", "web.home.status_body", STATUS))
CREATE_STEPS = (("web.create.open", "web.create.open_body"),
                ("web.create.clan", "web.create.clan_body"),
                ("web.create.village", "web.create.village_body"),
                ("web.create.terms", "web.create.terms_body"))
SHARED = (("bases", "web.home.tile.bases", "web.home.tile.bases_body", BASES),
          ("platform", "web.home.tile.news", "web.home.tile.news_body", NEWS))
GROUP = ("members", "web.home.community", "web.community.group")
FAME = ("challenges", "web.community.fame", "web.home.thanks")
PRIVACY = (("web.privacy.collect.title", "web.privacy.collect.body"),
           ("web.privacy.where.title", "web.privacy.where.body"),
           ("web.privacy.keep.title", "web.privacy.keep.body"),
           ("web.privacy.rights.title", "web.privacy.rights.body"),
           ("web.privacy.never.title", "web.privacy.never.body"),
           ("web.privacy.contact.title", "web.privacy.contact.body"))
TERMS = (("web.terms.who.title", "web.terms.who.body"),
         ("web.terms.rules.title", "web.terms.rules.body"),
         ("web.terms.service.title", "web.terms.service.body"),
         ("web.terms.stop.title", "web.terms.stop.body"))


def shell(title, body, lang="en", css="", scripts=(), meta=(), modules=(), preload=(),
          styles=None):
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{esc(title)}</title>",
    ]
    for attr, key, content in meta:
        head.append(f'<meta {esc(attr)}="{esc(key)}" content="{esc(content)}">')
    for sheet in (SHEETS if styles is None else styles):
        head.append(f'<link rel="stylesheet" href="{esc(static.url_for(sheet))}">')
    head.append(f"<style>{CSS}{css}</style>")
    for src in preload:
        head.append(f'<link rel="modulepreload" href="{esc(src)}">')
    for src in scripts:
        head.append(f'<script src="{esc(src)}" defer></script>')
    for src in modules:
        head.append(f'<script type="module" src="{esc(src)}" defer></script>')
    parts = [f'<!doctype html><html lang="{esc(lang)}"><head>', "".join(head), "</head><body>", body,
             "</body></html>"]
    return "".join(parts)


def headers(cache="no-store", frameable=False, robots=None, csp=None, extra=None):
    out = {"Cache-Control": cache, "Content-Security-Policy": (csp or CSP_BASE) + (
        "" if frameable else "; frame-ancestors 'none'")}
    if robots:
        out["X-Robots-Tag"] = robots
    out.update(extra or {})
    return out


def foot(L, policy=False):
    lines = [L.t("web.home.unofficial")]
    if policy:
        lines.append(L.t("web.legal.fanpolicy"))
    return (bits((link("/privacy", L.t("web.privacy.title")),
                  link("/terms", L.t("web.terms.title"))))
            + f'<p class="muted">{esc(" ".join(lines))}</p>')


def link(href, label):
    return f'<a href="{esc(href)}">{esc(label)}</a>'


def btn(href, label):
    return f'<p><a class="btn" href="{esc(href)}">{esc(label)}</a></p>'


def facts(parts, more=""):
    return (f'<span class="facts{" " + more if more else ""}">'
            + "".join(f"<span>{one}</span>" for one in parts if one) + "</span>")


def bits(parts):
    return f'<p class="bits">{facts(parts)}</p>'


def grid(tiles, cols):
    return f'<div class="grid {COLS[cols]}">' + "".join(tiles) + "</div>"


def nav_link(label, href, here):
    return (f'<a href="{esc(href)}"' + (' aria-current="page"' if href == here else "")
            + f">{esc(label)}</a>")


def live_href(links):
    code = (links or {}).get("example")
    return LIVE + str(code) if code else ""


def menu(links=None):
    made = []
    for label, href in MENU:
        target = live_href(links) if href == LIVE else href
        if target:
            made.append((label, target))
    return made


def sub_bar(here):
    nav = "".join(nav_link(label, href, here) for label, href in SUB)
    return f'<nav class="sub" aria-label="{SUB_LABEL}">{nav}</nav>'


def top_bar(here="", links=None):
    under = here in UNDER
    lit = COMMUNITY if under else here
    nav = "".join(nav_link(label, href, lit) for label, href in menu(links))
    return f"{TOP_OPEN}{BRAND}<nav>{nav}</nav></header>" + (sub_bar(here) if under else "")


def preview_meta(about, title="ClanBoard"):
    return (("name", "description", about),
            ("property", "og:title", title),
            ("property", "og:description", about),
            ("property", "og:type", "website"),
            ("name", "twitter:card", "summary"))


def go_tile(L, drawing, name, line, href, lead=False, out=False):
    return (f'<a class="tile go{" lead" if lead else ""}" href="{esc(href)}"'
            + (' rel="noopener"' if out else "") + f'>{art.icon(drawing)}'
            f'<span class="say"><span class="big">{esc(L.t(name))}</span>'
            f'<span class="muted">{esc(L.t(line))}</span></span></a>')


def tiles_row(made):
    return '<div class="sections">' + "".join(made) + "</div>"


def sections(L, links):
    made = []
    for drawing, name, line, href in SECTIONS:
        target = live_href(links) if href == LIVE else href
        if target:
            made.append(go_tile(L, drawing, name, line, target, lead=href == CREATE))
    return tiles_row(made)


def what(L):
    return "".join(f'<p class="pair"><strong>{esc(L.t(name))}</strong> <span>{esc(L.t(line))}</span></p>'
                   for name, line in WHAT)


def dial(css, digits):
    return (f'<span class="tick"><span class="dial {css}">'
            + "".join(f"<b>{one}</b>" for one in digits) + "</span></span>")


def clock(L):
    return ('<span class="clock" aria-hidden="true">' + dial("tens", range(TENS - 1, -1, -1))
            + dial("units", range(UNITS - 1, -1, -1))
            + f'<span>{esc(L.t("unit.s"))}</span></span>')


def side(label, score):
    return (f'<div class="side"><span class="score">{score}</span>'
            f'<span class="muted">{esc(label)}</span></div>')


def match_card(L):
    (left, ours), (right, theirs) = MATCH
    middle = f'<div class="vs"><span class="chip live">{esc(LIVE_WORD)}</span>{clock(L)}</div>'
    return ('<div class="card hero match stripe"><div class="score-row">'
            + side(left, ours) + middle + side(right, theirs) + "</div></div>")


def home_foot(L, found):
    nav = [esc(L.t("web.home.languages", n=len(LANGUAGES)))]
    watch = [esc(L.t("web.home.security")), link(SECURITY_TXT, SECURITY_TXT)]
    if found.get("checklist"):
        watch.append(link(found["checklist"], L.t("web.home.checklist")))
    if found.get("thanks"):
        watch.append(link(found["thanks"], L.t("web.home.thanks")))
    ways = [esc(L.t("web.home.stars"))]
    if found.get("support"):
        ways.insert(0, link(found["support"], L.t("web.home.donate")))
    if found.get("creator"):
        ways.append(esc(L.t("web.home.creator", code=found["creator"])))
    end = [bits(nav), bits(watch), bits([esc(L.t("web.home.support"))] + ways)]
    if found.get("creator"):
        end.append(f'<p class="muted">{esc(L.t("web.home.credits", name=found["creator"]))}</p>')
    end.append(foot(L, policy=True))
    return "<footer>" + "".join(end) + "</footer>"


def newbot_url(console):
    return f"https://t.me/{console}?start=newbot"


def home_page(L, links=None):
    found = links or {}
    console = found.get("console")
    intro = [f'<h1>ClanBoard</h1><p class="lede">{esc(L.t("web.home.tagline"))}</p>', what(L),
             f'<p class="muted">{esc(L.t("web.home.start"))}</p>']
    if console:
        intro.append(btn(newbot_url(console), L.t("web.home.newbot")))
    body = [top_bar("/", found),
            f'<div class="split"><div>{"".join(intro)}</div>{match_card(L)}</div>',
            sections(L, found), home_foot(L, found)]
    return shell("ClanBoard", "".join(body), L.code, meta=preview_meta(L.t("web.home.tagline")))


def step_tile(L, number, name, line):
    return (f'<div class="tile step"><span class="big">{number}</span>'
            f'<span>{esc(L.t(name))}</span>'
            f'<span class="muted">{esc(L.t(line))}</span></div>')


def create_page(L, links=None):
    found = links or {}
    title = L.t("web.create.title")
    steps = [step_tile(L, number, name, line)
             for number, (name, line) in enumerate(CREATE_STEPS, start=1)]
    body = [top_bar(CREATE, found), f"<h1>{esc(title)}</h1>",
            f'<p class="lede">{esc(L.t("web.create.who"))}</p>', grid(steps, NUMBERS)]
    if found.get("console"):
        body.append(btn(newbot_url(found["console"]), L.t("web.home.newbot")))
    body.append(f"<footer>{foot(L)}</footer>")
    return shell(f"{title} · ClanBoard", "".join(body), L.code,
                 meta=preview_meta(L.t("web.create.who"), title))


def more(L, href):
    return f'<p class="more">{link(href, L.t("web.community.more"))}</p>'


def community_tiles(L, found):
    made = [go_tile(L, *row) for row in SHARED]
    if found.get("group"):
        made.append(go_tile(L, *GROUP, found["group"], out=True))
    made.append(go_tile(L, *FAME, found.get("thanks") or SECURITY))
    return tiles_row(made)


def community_page(L, links=None, board="", ranks=""):
    found = links or {}
    title = L.t("web.community.title")
    body = [top_bar(COMMUNITY, found), f"<h1>{esc(title)}</h1>",
            f"<h2>{esc(L.t('web.board.title'))}</h2>", board, more(L, BOARD),
            f"<h2>{esc(RANK_TITLE)}</h2>", ranks, more(L, RANK),
            community_tiles(L, found), f"<footer>{foot(L)}</footer>"]
    return shell(f"{title} · ClanBoard", "".join(body), L.code,
                 meta=preview_meta(L.t("web.home.network_body"), title))


def legal_page(L, name, sections, tail, links=None):
    fills = {"wars": L.n(WAR_HISTORY_KEEP), "days": L.n(INACTIVE_CLAN_DAYS)}
    title = L.t(name + ".title")
    parts = [top_bar("", links), f"<h1>{esc(title)}</h1>",
             f'<p class="lede">{esc(L.t(name + ".intro"))}</p>']
    for head, body in sections:
        parts.append(f"<h2>{esc(L.t(head))}</h2><p>{esc(L.t(body, **fills))}</p>")
    parts.extend(tail)
    source = (links or {}).get("source")
    parts.append(f'<p>{esc(L.t(name + ".license"))}'
                 + (f" {link(source, source)}" if source else "") + "</p>")
    parts.append("<footer>"
                 + f'<p class="muted">'
                 f'{esc(L.t("web.legal.updated", date=L.t("web.legal.date")))}</p>'
                 f'{foot(L, policy=True)}</footer>')
    return shell(f"{title} · ClanBoard", "".join(parts), L.code)


def privacy_page(L, links=None):
    return legal_page(L, "web.privacy", PRIVACY,
                      [f"<p>{link(SECURITY_TXT, SECURITY_TXT)}</p>"], links)


def terms_page(L, links=None):
    return legal_page(L, "web.terms", TERMS,
                      [f'<p>{esc(L.t("web.terms.changes"))}</p>'], links)


def service_tile(L, service):
    state = str(service["state"])
    return (f'<div class="tile"><span class="dot {state}"></span>'
            f'<span>{esc(L.t("web.status." + str(service["name"])))}</span>'
            f'<span class="muted">{esc(L.t("web.status." + state))}</span></div>')


def status_page(L, body, now, links=None):
    tiles = [service_tile(L, service) for service in body["services"]]
    checked = ""
    if body["checked"]:
        minutes = max(0, int(now.timestamp()) - body["checked"]) // 60
        checked = f'<p class="muted">{esc(L.t("web.status.checked", n=minutes))}</p>'
    page = [top_bar(STATUS, links), f"<h1>{esc(L.t('web.status.title'))}</h1>",
            f'<p><span class="state {body["state"]}">'
            f'{esc(L.t("web.status." + body["state"]))}</span></p>',
            grid(tiles, ROW), checked,
            f"<footer>{foot(L)}</footer>"]
    return shell(L.t("web.status.title"), "".join(page), L.code, meta=REFRESH)


def _when(L, ts, tz):
    return L.when(datetime.fromtimestamp(int(ts), timezone.utc), tz) if ts else "?"


def record_of(L, page):
    record = page.get("record") or {}
    return L.t("web.page.record", wins=L.n(record.get("wins") or 0),
               wars=L.n(record.get("wars") or 0))


def _preview(L, page, clan):
    bits = [L.t("web.page.level", n=clan.get("level") or 0), clan.get("league") or "-",
            record_of(L, page)]
    return ", ".join(str(bit) for bit in bits if bit)


def fact(L, value, label):
    return (f'<div class="tile"><span class="big">{esc(L.n(value))}</span>'
            f'<span class="muted">{esc(L.t(label))}</span></div>')


def chips(parts):
    return '<p class="chips">' + "".join(
        f'<span class="chip">{esc(one)}</span>' for one in parts if one) + "</p>"


def crest(clan):
    url = clan.get("badge")
    return f'<img class="crest" src="{esc(url)}" alt="">' if url else ""


def clan_facts(L, page, clan):
    return grid((fact(L, clan.get("level") or 0, "web.page.lvl"),
                 fact(L, clan.get("members") or 0, "web.page.members"),
                 fact(L, page.get("free") or 0, "web.page.free"),
                 fact(L, clan.get("wins") or 0, "web.page.wins")), NUMBERS)


def clan_chips(L, page, clan):
    need = page.get("min_th")
    return chips((clan.get("league"),
                  L.t("recruit.req_th", th=need) if need else L.t("recruit.req_any")))


def clan_head(L, clan, shown):
    mark = f' <span class="chip mark">{esc(L.t("web.page.example"))}</span>' if shown else ""
    return (f'<div class="head">{crest(clan)}<div><h1>{esc(clan["name"])}</h1>{mark}</div>'
            "</div>")


def event_tile(L, item, tz):
    return (f'<div class="tile"><span class="big">'
            f'{esc(L.t("agenda.item." + str(item["key"])))}</span>'
            + facts((esc(_when(L, item["start"], tz)),
                      esc(L.t("web.page." + item["state"]))), "muted") + "</div>")


def event_tiles(L, items, tz):
    return grid([event_tile(L, item, tz) for item in items], ROW)


def clan_page(L, page, now, code="", apply_url="", links=None):
    clan, tz = page["clan"], page.get("tz") or "UTC"
    shown = bool(code) and (links or {}).get("example") == code
    body = [top_bar(LIVE + code if shown else "", links), clan_head(L, clan, shown),
            clan_facts(L, page, clan), clan_chips(L, page, clan)]
    if apply_url:
        body.append(btn(apply_url, L.t("web.page.apply")))
    body.append(f"<h2>{esc(L.t('web.page.war'))}</h2>")
    body.append(chips((record_of(L, page),)))
    if page.get("events"):
        body.append(f"<h2>{esc(L.t('web.page.events'))}</h2>")
        body.append(event_tiles(L, page["events"], tz))
    if page["extras"].get("ics"):
        body.append(f'<p><a href="/c/{esc(code)}/calendar.ics">'
                    f'{esc(L.t("web.page.ics"))}</a></p>')
    minutes = max(0, int(now.timestamp()) - int(page["updated"])) // 60
    body.append(f'<footer><p class="muted">{esc(L.t("web.page.updated", n=minutes))}</p>'
                f"{foot(L)}</footer>")
    return shell(f"{clan['name']} · ClanBoard", "".join(body), L.code,
                 meta=preview_meta(_preview(L, page, clan), clan["name"]))


def warning_page(L, ip, at):
    body = [top_bar(), f"<h1>{esc(L.t('ban.page.title'))}</h1>",
            f"<p>{esc(L.t('ban.page.body'))}</p>",
            f'<div class="card">{esc(L.t("ban.page.ip", ip=ip))}<br>'
            f'{esc(L.t("ban.page.at", when=_when(L, at, "UTC")))}</div>',
            f"<p><b>{esc(L.t('ban.page.logged'))}</b></p>",
            f'<p class="muted">{esc(L.t("ban.page.research"))} '
            f'<a href="/.well-known/security.txt">/.well-known/security.txt</a></p>']
    return shell(L.t("ban.page.title"), "".join(body), L.code)


WIDGET_CSS = ("body{padding:12px;max-width:none}.w{font-size:.95rem}"
              ".w b{font-size:1.1rem}.w div{margin:.15rem 0}")
WIDGET_BRAND = '<a href="/" target="_blank" rel="noopener">ClanBoard</a>'


def widget_page(L, page, now):
    clan, war = page["clan"], page.get("war")
    lines = [f'<div class="w"><b>{esc(clan["name"])}</b>',
             '<div class="muted">'
             + facts((esc(L.t("web.page.level", n=clan.get("level") or 0)),
                      esc(clan.get("league") or "-"))) + "</div>"]
    if war:
        lines.append("<div>" + facts((
            f'&#9876; {war["us"]["stars"]}&#11088; &mdash; {war["them"]["stars"]}&#11088;',
            esc(war["them"]["name"]))) + "</div>")
    else:
        lines.append(f'<div class="muted">{esc(L.t("web.page.no_war"))}</div>')
    item = (page.get("events") or [None])[0]
    if item:
        lines.append("<div>" + facts((
            f'&#128197; {esc(L.t("agenda.item." + str(item["key"])))}',
            esc(_when(L, item["start"], page.get("tz") or "UTC")))) + "</div>")
    minutes = max(0, int(now.timestamp()) - int(page["updated"])) // 60
    lines.append('<div class="muted">'
                 + facts((esc(L.t("web.page.updated", n=minutes)), WIDGET_BRAND))
                 + "</div></div>")
    return shell(clan["name"], "".join(lines), L.code, WIDGET_CSS)
