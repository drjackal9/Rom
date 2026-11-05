import asyncio
import html
import logging
import re
import signal
import time
from pathlib import Path

from .. import (base_videos, db, exports, feed, mydata, news_feed, selfmetrics, share_cards,
                site_conf, source)
from ..acts import SHARE_KINDS, SHARE_MANAGER
from ..base_videos import THUMB_HOST
from ..crypto import KEY_DIR, MASTER, Vault
from ..db import Store
from ..i18n import ALIASES, LANGUAGES, locale
from ..intents import DONE, refused_key
from ..media import BADGE_HOST
from ..reasons import BAD, BANNED, NEEDS_TOKEN, REFUSED
from ..recruit import is_verified
from ..settings import MANAGER
from ..util import day_of, now_utc
from . import (app_manage, auth, ban, board as web_board, http, live, miniapp, pages, payload,
               public, security as web_security, static, wellknown)

log = logging.getLogger("clashbot.web")

PORT = 8080
HEARTBEAT = Path("/tmp/clashbot-web.heartbeat")
BEAT_EVERY = 30
KEY_STEP = 2
APP_WAIT = 3.0
APP_STEP = 0.25
NAME_MAX = 32
PAGE_CACHE = pages.PAGE_CACHE
PAGE_HEAD = pages.PAGE_HEAD
CONSOLE_NOTE = "login"
START_QUERY = "tgWebAppStartParam"
WAITING = "in coda"
SITE_LANG = "en"
LEGAL_LANGS = ("it", "en")
KNOWN = {code.lower() for code in LANGUAGES} | set(ALIASES)
COUNTERS = ("own_requests", "misses", "limited", "probes")
AUDIT_KEY = "web:audit"
AUDIT_PEER = "127.0.0.1"
AUDIT_PATHS = ("/", pages.CREATE, pages.COMMUNITY, "/privacy", "/terms", "/status", "/board",
               "/leaderboards", "/bases", "/news", web_security.PATH)
AUDIT_HEADS = ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy")
HSTS = "Strict-Transport-Security"
HEADS = AUDIT_HEADS + (HSTS,)
COOKIE = "set-cookie"
ALLOWED_HOSTS = (THUMB_HOST, f"https://{BADGE_HOST}")
ALLOWED_LOW = tuple(host.lower() for host in ALLOWED_HOSTS)
NEAR_SCHEMES = ("data:",)
HOST_END = ("/", "?", "#")
ATTR = r'\s{name}\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))'
SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.I)
SRC = re.compile(ATTR.format(name="src"), re.I)
SHEET = re.compile(r"<link\b[^>]*" + ATTR.format(name="href"), re.I)
SCRIPT = re.compile(r"<script\b[^>]*" + ATTR.format(name="src"), re.I)
SRCSET = re.compile(ATTR.format(name="srcset"), re.I)
OBJECT = re.compile(r"<object\b[^>]*" + ATTR.format(name="data"), re.I)


def links_of(pattern, text):
    found = []
    for parts in pattern.findall(text):
        url = next((one for one in parts if one), "")
        if url:
            found.append(html.unescape(url).strip())
    return found


def sets_of(text):
    found = []
    for raw in links_of(SRCSET, text):
        for part in raw.split(","):
            one = part.split()
            if one:
                found.append(one[0])
    return found


def remote(url):
    raw = str(url or "").strip()
    return raw.startswith("//") or bool(SCHEME.match(raw))


def near(url):
    raw = str(url or "").strip().lower()
    if raw.startswith(NEAR_SCHEMES):
        return True
    for host in ALLOWED_LOW:
        rest = raw[len(host):]
        if raw.startswith(host) and (not rest or rest[0] in HOST_END):
            return True
    return False


def outside(text):
    found = (links_of(SCRIPT, text) + links_of(SRC, text) + links_of(SHEET, text)
             + sets_of(text) + links_of(OBJECT, text))
    seen = []
    for url in found:
        if remote(url) and not near(url) and url not in seen:
            seen.append(url)
    return seen


def audit_page(res):
    text = res.body.decode("utf-8", "replace")
    heads = dict(http.BASE_HEADERS, **res.headers)
    names = {name.lower() for name in heads}
    return {"cookies": 1 if COOKIE in names else 0,
            "scripts": len([url for url in links_of(SCRIPT, text) if remote(url)]),
            "outside": outside(text),
            "missing": [name for name in AUDIT_HEADS if name.lower() not in names],
            "hsts": HSTS.lower() in names}


def match(pattern, path):
    parts = path.strip("/").split("/")
    wanted = pattern.strip("/").split("/")
    if wanted[-1].startswith("<") and wanted[-1].endswith("...>"):
        if len(parts) < len(wanted):
            return None
        parts = parts[:len(wanted) - 1] + ["/".join(parts[len(wanted) - 1:])]
    if len(parts) != len(wanted):
        return None
    found = {}
    for got, want in zip(parts, wanted):
        if want.startswith("<") and want.endswith(">"):
            if not got:
                return None
            found[want[1:-1].rstrip(".")] = got
        elif got != want:
            return None
    return found


def base_tag(tag):
    return str(tag).replace("_", "-").lower()


def known_tag(tag):
    raw = base_tag(tag)
    return raw in KNOWN or raw.split("-")[0] in KNOWN


def pick_locale(req, code=None, among=None):
    if code:
        return locale(code)
    for chunk in req.header("accept-language").split(","):
        tag = base_tag(chunk.split(";")[0].strip())
        if tag and known_tag(tag) and (among is None or tag.split("-")[0] in among):
            return locale(tag)
    return locale(SITE_LANG)


async def home(site, req):
    L = pick_locale(req, SITE_LANG)
    return http.Response(pages.home_page(L, await site.links()),
                         headers=pages.headers(PAGE_HEAD))


async def create(site, req):
    L = pick_locale(req, SITE_LANG)
    return http.Response(pages.create_page(L, await site.links()),
                         headers=pages.headers(PAGE_HEAD))


async def community(site, req):
    L = pick_locale(req, SITE_LANG)
    found = await site.store.recruit_board(limit=web_board.PAGE_SIZE)
    clans = web_board.block(L, found, web_board.NONE, await site.store.public_codes(),
                            pages.ROW)
    ranks = public.rank_block(L, await site.ranks(), pages.ROW)
    return http.Response(pages.community_page(L, await site.links(), clans, ranks),
                         headers=pages.headers(pages.LIVE_HEAD))


async def privacy(site, req):
    L = pick_locale(req, among=LEGAL_LANGS)
    return http.Response(pages.privacy_page(L, await site.links()),
                         headers=pages.headers(PAGE_HEAD))


async def terms(site, req):
    L = pick_locale(req, among=LEGAL_LANGS)
    return http.Response(pages.terms_page(L, await site.links()),
                         headers=pages.headers(PAGE_HEAD))


async def status_page(site, req):
    L = pick_locale(req, SITE_LANG)
    now = now_utc()
    body = payload.status_body(await site.store.web_note("services"), now)
    return http.Response(pages.status_page(L, body, now, await site.links()),
                         headers=pages.headers("public, max-age=15"))


async def status_json(site, req):
    body = payload.status_body(await site.store.web_note("services"), now_utc())
    return http.data(body, headers=pages.headers("public, max-age=15"))


async def clan_page(site, req, code):
    page = await site.store.web_page(code, payload.PUBLIC)
    if not page:
        return http.text("", 404)
    L = pick_locale(req, SITE_LANG)
    apply_url = web_board.deep_link({"bot": page.get("bot")}, page.get("code"))
    return http.Response(
        pages.clan_page(L, page, now_utc(), code, apply_url, await site.links()),
        headers=pages.headers(PAGE_HEAD, robots="index", csp=pages.CSP_CLAN))


async def clan_widget(site, req, code):
    page = await site.store.web_page(code, payload.PUBLIC)
    if not page or not page.get("extras", {}).get("widget"):
        return http.text("", 404)
    L = pick_locale(req, SITE_LANG)
    return http.Response(
        pages.widget_page(L, page, now_utc()),
        headers=pages.headers("public, max-age=60", frameable=True, robots="noindex"),
    )


async def clan_ics(site, req, code):
    page = await site.store.web_page(code, payload.PUBLIC)
    if not page or not page.get("extras", {}).get("ics") or not page.get("ics"):
        return http.text("", 404)
    return http.Response(page["ics"], kind=http.CALENDAR,
                         headers=pages.headers("public, max-age=900", robots="noindex"))


async def board(site, req):
    L = pick_locale(req, SITE_LANG)
    picked = web_board.wanted(req.query)
    found = await site.store.recruit_board(limit=web_board.PAGE_SIZE, **picked)
    codes = await site.store.public_codes()
    return http.Response(web_board.board_page(L, found, picked, codes, await site.links()),
                         headers=pages.headers(pages.LIVE_HEAD))


async def leaderboards(site, req):
    L = pick_locale(req, SITE_LANG)
    return http.Response(public.rank_page(L, await site.ranks(), await site.links()),
                         headers=pages.headers(pages.LIVE_HEAD))


async def bases(site, req):
    L = pick_locale(req, SITE_LANG)
    hall, kind = public.wanted(req.query)

    async def read():
        return (await site.store.library_rows(),
                await site.store.videos_rows(base_videos.PLATFORM))

    rows, videos = await site.cached("bases", read)
    return http.Response(public.bases_page(L, rows, videos, hall, kind, await site.links()),
                         headers=pages.headers(PAGE_HEAD, csp=public.CSP_MEDIA))


async def news(site, req):
    L = pick_locale(req, SITE_LANG)

    async def read():
        return await site.store.kv_get(news_feed.ROWS_KEY)

    rows = await site.cached("news", read)
    return http.Response(public.news_page(L, rows, now_utc(), await site.links()),
                         headers=pages.headers(PAGE_HEAD, csp=public.CSP_MEDIA))


async def security(site, req):
    L = pick_locale(req, SITE_LANG)
    now = now_utc()

    async def read():
        return await web_security.numbers(site.store, now, await site.store.kv_get(AUDIT_KEY),
                                          HEADS, await site.links())

    found = dict(await site.cached("security", read), links=await site.links())
    return http.Response(web_security.security_page(L, found, now),
                         headers=pages.headers(PAGE_HEAD))


async def contact_hop(site, req, code):
    if not code.isalnum() or len(code) > web_board.CODE_MAX:
        return http.text("", 404)
    target = await site.store.recruit_target(code)
    if target and not is_verified(target):
        return http.text(pick_locale(req, SITE_LANG).t("recruit.unverified"), 403,
                         {"Cache-Control": "no-store"})
    deep = web_board.deep_link(target, code)
    if not deep:
        return http.text("", 404)
    return http.text("", 302, {"Location": deep, "Cache-Control": "no-store"})


async def static_file(site, req, stamp, name):
    body = static.read(name)
    if body is None:
        return http.text("", 404)
    fresh = stamp == static.manifest()["hash"]
    cache = f"public, max-age={static.STATIC_MAX_AGE}, immutable" if fresh else PAGE_HEAD
    return http.Response(body, kind=static.kind_of(name),
                         headers=pages.headers(cache, frameable=True, csp=miniapp.CSP))


def denial(kind, code, status):
    log.info("gesto %s: %s", kind or "", code)
    return http.data({"error": code}, status, headers=pages.headers("no-store"))


async def at_door(site, req, slug, allow_query=False):
    page, seat = await site.viewer(req, slug, allow_query=allow_query)
    if not page:
        return None, None, http.text("", 404)
    if miniapp.shut(page, seat):
        return page, seat, denial(None, BANNED, 403)
    return page, seat, None


async def started(site, req):
    code = req.one(START_QUERY)
    return bool(code.isalnum() and await site.page_of(code))


async def app_page(site, req, slug=None):
    page, _, stop = await at_door(site, req, slug)
    if stop is not None and page is not None:
        return stop
    if not slug and not await started(site, req):
        return http.text("", 303, {"Location": "/", "Cache-Control": "no-store"})
    if slug and not page:
        return http.text("", 404)
    L = pick_locale(req, page.get("lang") if page else None)
    return http.Response(miniapp.app_page(L, page, slug or ""),
                         headers=pages.headers("no-store", frameable=True, robots="noindex",
                                               csp=miniapp.CSP))


async def app_state(site, req, slug):
    page, seat, stop = await at_door(site, req, slug)
    if stop:
        return stop
    if not seat:
        return http.text("", 401)
    return http.data(miniapp.state_body(page, seat, await site.unread(slug, seat, page),
                                        help=await site.links(),
                                        clans=await site.clans_of(seat)),
                     headers=pages.headers("no-store"))


async def app_live(site, req, slug):
    page, seat, stop = await at_door(site, req, slug, allow_query=True)
    if stop:
        return stop
    if not seat:
        return http.text("", 401)

    mine = await site.clans_of(seat)

    async def shape(fresh):
        now = site.seat_in(fresh, seat)
        if miniapp.shut(fresh, now):
            return None
        return miniapp.state_body(fresh, now, await site.unread(slug, now, fresh),
                                  help=await site.links(), clans=mine)

    async def first():
        found = await shape(await site.page_of(slug) or page)
        return None if found is None else live.event("state", found)

    return http.StreamResponse(live.stream(site, slug, str(seat["uid"]), first, shape=shape))


async def app_feed(site, req, slug):
    page, seat, stop = await at_door(site, req, slug)
    if stop:
        return stop
    if not seat or not miniapp.reads_feed(page, seat):
        return http.text("", 401)
    alias = await site.alias_of(slug)
    if not alias:
        return http.text("", 404)
    rows = await feed.rows(site.store, alias, seat["uid"])
    await feed.mark_read(site.store, alias, seat["uid"], now_utc())
    return http.data({"rows": rows}, headers=pages.headers("no-store"))


async def app_mydata(site, req, slug):
    page, seat, stop = await at_door(site, req, slug, allow_query=True)
    if stop:
        return stop
    if not seat or not seat.get("tag"):
        return http.text("", 401)
    alias = await site.alias_of(slug)
    found = await mydata.bundle(site.store, alias, seat["uid"], now_utc()) if alias else None
    if not found:
        return http.text("", 404)
    return http.data(found, headers=pages.headers("no-store"))


async def app_export(site, req, slug):
    page, seat, stop = await at_door(site, req, slug, allow_query=True)
    if stop:
        return stop
    if not seat or seat.get("level") != MANAGER:
        return http.text("", 401)
    alias = await site.alias_of(slug)
    ready = await site.store.kv_get(exports.ready_key(alias, seat["uid"])) if alias else None
    if not ready:
        return http.text("", 404)
    name = f"{ready['sheet']}-{ready['at']}.csv"
    return http.Response(ready["text"].encode("utf-8-sig"), kind=http.SHEET, headers=pages.headers(
        "no-store", extra={"Content-Disposition": f'attachment; filename="{name}"'}))


async def app_preview(site, req, slug):
    page, seat, stop = await at_door(site, req, slug)
    if stop:
        return stop
    if not seat or seat.get("level") != MANAGER:
        return http.text("", 401)
    drafted = req.one("text") if "text" in req.query else None
    found = app_manage.preview_of(pick_locale(req, page.get("lang")), page,
                                  req.one("kind"), drafted)
    if found is None:
        return http.data({"error": "bad"}, 400, headers=pages.headers("no-store"))
    return http.data({"text": found}, headers=pages.headers("no-store"))


async def app_card(site, req, name):
    found = await site.store.kv_get(share_cards.card_key(share_cards.token_of(name)))
    png = share_cards.png_of(found)
    if not png:
        return http.text("", 404)
    return http.Response(png, kind=http.PHOTO, headers=pages.headers("no-store"))


async def app_act(site, req, slug):
    page, seat, stop = await at_door(site, req, slug)
    if stop:
        return stop
    if not seat:
        return http.text("", 401)
    raw = req.payload()
    if miniapp.token_only(raw):
        return denial(None, NEEDS_TOKEN, 403)
    body = miniapp.intent(raw, seat.get("tag") or "", seat["uid"])
    if not body:
        return denial(None, BAD, 400)
    refused = miniapp.why(page, seat, body["kind"])
    if refused:
        return denial(body["kind"], refused, 403)
    intent_id = await site.store.web_intent_for(slug, body["kind"], body)
    if not intent_id:
        return http.text("", 404)
    waited = 0.0
    pending = await site.store.web_intent_pending(intent_id)
    while waited < APP_WAIT and pending:
        await asyncio.sleep(APP_STEP)
        waited += APP_STEP
        pending = await site.store.web_intent_pending(intent_id)
    if pending:
        log.info("gesto %s: %s", body["kind"], WAITING)
    else:
        told = await site.store.kv_get(refused_key(intent_id))
        if told:
            return denial(body["kind"], str(told.get("code") or REFUSED), 403)
        log.info("gesto %s: %s", body["kind"], DONE)
    prepared = None
    if body["kind"] in SHARE_KINDS + SHARE_MANAGER:
        prepared = await site.prepared(slug, seat, body["id"])
    fresh = await site.store.web_page(slug, payload.APP) or page
    seat = site.seat_in(fresh, seat)
    answer = miniapp.state_body(fresh, seat, await site.unread(slug, seat, fresh),
                                help=await site.links(), clans=await site.clans_of(seat))
    if prepared:
        answer["prepared"] = prepared
    if pending:
        answer["pending"] = True
    return http.data(answer, headers=pages.headers("no-store"))


ROUTES = (
    ("GET", "/", home),
    ("GET", pages.CREATE, create),
    ("GET", pages.COMMUNITY, community),
    ("GET", "/privacy", privacy),
    ("GET", "/terms", terms),
    ("GET", "/.well-known/security.txt", wellknown.security),
    ("GET", "/robots.txt", wellknown.robots),
    ("GET", "/status", status_page),
    ("GET", "/status.json", status_json),
    ("GET", "/c/<code>", clan_page),
    ("GET", "/c/<code>/widget", clan_widget),
    ("GET", "/c/<code>/calendar.ics", clan_ics),
    ("GET", "/board", board),
    ("GET", "/leaderboards", leaderboards),
    ("GET", "/bases", bases),
    ("GET", "/news", news),
    ("GET", web_security.PATH, security),
    ("GET", "/r/<code>", contact_hop),
    ("GET", "/static/<stamp>/<name...>", static_file),
    ("GET", "/app", app_page),
    ("GET", "/app/<slug>", app_page),
    ("GET", "/app/<slug>/state", app_state),
    ("GET", "/app/<slug>/live", app_live),
    ("GET", "/app/<slug>/feed", app_feed),
    ("GET", "/app/<slug>/mydata.json", app_mydata),
    ("GET", "/app/<slug>/export.csv", app_export),
    ("GET", "/app/<slug>/preview", app_preview),
    ("POST", "/app/<slug>/act", app_act),
    ("GET", "/card/<name>", app_card),
)


class Site:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or time.monotonic
        self.reads = http.Bucket(http.READ_RATE, self.clock)
        self.writes = http.Bucket(http.WRITE_RATE, self.clock)
        self.console = None
        self.source = None
        self.found = None
        self.shelf = {}
        self.aliases = {}
        self.seen = set()
        self.pages = {}
        self.live = {}
        self.tasks = set()
        self.notified = 0
        self.ear = None
        self.counters = dict.fromkeys(COUNTERS, 0)
        self.zone = None

    def bump(self, name):
        self.counters[name] = self.counters.get(name, 0) + 1

    async def flush(self, at):
        day = day_of(at, self.zone)
        key = selfmetrics.WEB_DAY + str(day)
        stored = await self.store.kv_get(key) or {}
        body = {name: int(stored.get(name) or 0) + self.counters[name] for name in COUNTERS}
        for name, value in ban.levels(await self.store.banned(), day, self.zone).items():
            body[name] = max(int(stored.get(name) or 0), value)
        await self.store.kv_set(key, body, ttl=selfmetrics.DAY_TTL)
        for name in COUNTERS:
            self.counters[name] = 0
        return body

    async def audit(self, at):
        seen = {"pages": 0, "cookies": 0, "scripts": 0, "outside": [], "missing": [],
                "broken": [], "hsts": True}
        for path in AUDIT_PATHS:
            res, _ = await self.route(http.Request("GET", path, {}, {}, b"", AUDIT_PEER))
            if not isinstance(res, http.Response) or res.status != 200:
                seen["broken"].append(path)
                continue
            found = audit_page(res)
            seen["pages"] += 1
            for name in ("cookies", "scripts"):
                seen[name] += found[name]
            for name in ("outside", "missing"):
                seen[name] += found[name]
            seen["hsts"] = seen["hsts"] and found["hsts"]
        body = dict(seen, version=static.manifest()["hash"], day=str(day_of(at, self.zone)))
        body["ok"] = not (seen["cookies"] or seen["scripts"] or seen["outside"]
                          or seen["missing"] or seen["broken"])
        await self.store.kv_set(AUDIT_KEY, body)
        return body

    async def audit_once(self, at):
        stored = await self.store.kv_get(AUDIT_KEY) or {}
        if stored.get("version") == static.manifest()["hash"]:
            return None
        return await self.audit(at)

    async def links(self):
        if self.found is None:
            note = await self.store.web_note(CONSOLE_NOTE) or {}
            source = await self.source_url()
            chosen = await site_conf.read(self.store)
            self.found = {
                "group": chosen[site_conf.GROUP],
                "example": await self.example(chosen[site_conf.EXAMPLE]),
                "console": note.get("bot") or "",
                "base": await self.store.get_secret("site_base") or "",
                "community": await self.store.get_secret("channel_url") or "",
                "support": await self.store.get_secret("support_url") or "",
                "creator": await self.store.get_secret("creator_code") or "",
                "source": source,
                "thanks": wellknown.thanks_url(source),
                "checklist": wellknown.checklist_url(source),
            }
        return self.found

    async def example(self, code):
        return code if code and await self.store.web_page(code, payload.PUBLIC) else ""

    async def ranks(self):
        return await self.cached("rank", self.store.network_board)

    async def cached(self, name, read):
        at = self.clock()
        found = self.shelf.get(name)
        if found and at - found[0] < PAGE_CACHE:
            return found[1]
        fresh = await read()
        self.shelf[name] = (at, fresh)
        return fresh

    async def console_token(self):
        if self.console is None:
            self.console = await self.store.get_secret("console_token")
        return self.console

    async def source_url(self):
        if self.source is None:
            self.source = await self.store.get_secret(source.SECRET) or ""
        return self.source

    async def page_of(self, slug):
        if slug not in self.pages:
            page = await self.store.web_page(slug, payload.APP)
            if page is None:
                return None
            self.pages[slug] = page
        return self.pages[slug]

    def on_page(self, slug):
        self.notified += 1
        self.pages.pop(slug, None)
        self.aliases.pop(slug, None)
        if self.live.get(slug):
            task = asyncio.get_running_loop().create_task(self.refresh_page(slug))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def refresh_page(self, slug):
        page = await self.page_of(slug)
        for queue in list(self.live.get(slug, ())):
            queue.put_nowait(page)

    async def listen(self):
        self.ear = await self.store.listen(db.PAGE_CHANNEL, self.on_page)

    def listening(self):
        return self.ear is not None and not self.ear.is_closed()

    async def alias_of(self, slug):
        if slug not in self.aliases:
            found = await self.store.web_app_alias(slug)
            if not found:
                return None
            self.aliases[slug] = found
        return self.aliases[slug]

    def seat_in(self, page, seat):
        uid = (seat or {}).get("uid")
        found = ((page or {}).get("seats") or {}).get(str(uid))
        known = {"uid": uid, "who": seat.get("who"), payload.MARK: seat.get(payload.MARK)}
        return dict(found, **known) if found else dict(known, level=None)

    async def viewer(self, req, slug=None, allow_query=False):
        signed = req.header("x-init-data") or (req.one("init") if allow_query else "")
        checked = auth.init_data(signed, await self.console_token(), int(time.time()))
        code = auth.start_param(checked)
        if code and slug and code != slug:
            return None, None
        wanted = code or slug
        if not wanted:
            return None, None
        page = await self.page_of(wanted)
        if not page:
            return None, None
        uid = auth.user_id(checked)
        if not uid:
            return page, None
        who = auth.user_name(checked)[:NAME_MAX]
        mark = payload.mark_for(self.store.vault, wanted, uid) if self.store.vault else None
        return page, self.seat_in(page, {"uid": uid, "who": who, payload.MARK: mark})

    async def clans_of(self, seat):
        uid = (seat or {}).get("uid")
        return await miniapp.clans_of(self.store, uid) if uid else []

    async def prepared(self, slug, seat, mark):
        alias = await self.alias_of(slug)
        if not alias:
            return None
        key = share_cards.ready_key(alias, seat["uid"])
        waited = 0.0
        while True:
            ready = await self.store.kv_get(key)
            if ready and ready.get("mark") == mark:
                return ready["id"]
            if waited >= APP_WAIT:
                return None
            await asyncio.sleep(APP_STEP)
            waited += APP_STEP

    async def unread(self, slug, seat, page=None):
        if not miniapp.reads_feed(page, seat):
            return 0
        alias = await self.alias_of(slug)
        return await feed.unread(self.store, alias, seat["uid"]) if alias else 0

    async def refresh(self):
        self.console = await self.store.get_secret("console_token")
        self.zone = await self.store.get_secret("owner_tz")
        self.source = None
        self.found = None
        self.seen.clear()

    async def router(self, req):
        self.bump("own_requests")
        if ban.is_probe(req.path):
            self.bump("probes")
        if req.method not in ("GET", "HEAD", "POST"):
            return http.text("", 405, {"Allow": "GET, HEAD, POST"})
        bucket = self.writes if req.method == "POST" else self.reads
        ip = req.ip
        if not bucket.allow(ip):
            self.bump("limited")
            return http.text("", 429, {"Retry-After": "60"})
        at = now_utc().timestamp()
        refused = await ban.check(self.store, self.seen, ip, req.path, at,
                                  pick_locale(req, SITE_LANG))
        if refused is not None:
            return refused
        res, known = await self.route(req)
        if isinstance(res, http.Response):
            res = http.revalidate(req, res)
        if res.status == 404 and not known and not ban.is_spared(req.path):
            self.bump("misses")
            await ban.miss(self.store, self.seen, ip, at)
        return res

    async def route(self, req):
        seen = False
        for method, pattern, handler in ROUTES:
            found = match(pattern, req.path)
            if found is None:
                continue
            seen = True
            if method != req.method and not (method == "GET" and req.method == "HEAD"):
                continue
            try:
                return await handler(self, req, **found), True
            except Exception:
                log.exception("pagina non costruita: %s", req.path[:120])
                return http.text("", 500), True
        return http.text("", 405 if seen else 404), seen


def measures(site):
    return {"live": sum(len(clients) for clients in site.live.values()),
            "pages": len(site.pages),
            "notified": site.notified}


async def beat(stop, site):
    recorder = selfmetrics.Recorder(site.store, selfmetrics.WEB_KEY, extra=lambda: measures(site))
    while not stop.is_set():
        try:
            HEARTBEAT.touch()
        except OSError:
            pass
        try:
            await site.refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("firma della Mini App non riletta")
        if not site.listening():
            try:
                await site.listen()
                site.pages.clear()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ascolto delle pagine non riaperto")
        try:
            at = now_utc().timestamp()
            await site.flush(at)
            await site.audit_once(at)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("contatori del giorno non aggiornati")
        await recorder.tick()
        await asyncio.sleep(BEAT_EVERY)


async def wait_for_key(step=KEY_STEP):
    path = Path(KEY_DIR) / MASTER
    if path.exists():
        return
    log.info("chiave maestra non ancora scritta: il servizio web aspetta il bot")
    while not path.exists():
        await asyncio.sleep(step)
    log.info("chiave maestra trovata")


def open_vault():
    return Vault(create=False)


async def run():
    await wait_for_key()
    store = Store(open_vault())
    await store.open(schema=False)
    site = Site(store)
    await site.listen()
    server = await http.serve(site.router, port=PORT)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    log.info("servizio web in ascolto sulla porta %s", PORT)
    heart = asyncio.create_task(beat(stop, site))
    try:
        await stop.wait()
    finally:
        heart.cancel()
        server.close()
        await server.wait_closed()
        await store.close()
