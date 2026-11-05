import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.robotparser import RobotFileParser

import pytest

from clashbot import i18n, publish
from clashbot import __main__ as cli
from clashbot.crypto import Vault
from clashbot.util import now_utc
from clashbot.web import (app as web_app, http, pages, payload, static, style,
                          wellknown)

L = i18n.locale("en")
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
ITALIAN = b"Accept-Language: it-IT,it;q=0.9\r\n"
COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
SOURCE = "https://example.org/clanboard"


class FakeStore:
    def __init__(self, notes=None, secrets=None):
        self.notes = dict(notes or {})
        self.secrets = dict(secrets or {})
        self.kv = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def web_note(self, name):
        return self.notes.get(name)

    async def web_note_set(self, name, body):
        self.notes[name] = body

    async def web_intents_take(self, limit=50):
        return []

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def kv_del(self, key):
        self.kv.pop(key, None)


def beat_bot(alias, kind="worker", username="UnoBot"):
    return SimpleNamespace(alias=alias, username=username, kind=kind, active=True, reason=None,
                           failures=0, last_seen=NOW)


class BeatStore(FakeStore):
    def __init__(self, bots=(), alive=True, clans=(), secrets=None):
        super().__init__(secrets=secrets)
        self.rows = list(bots)
        self.alive = alive
        self.clans = list(clans)
        self.pool = SimpleNamespace(fetchval=self.fetchval)

    async def fetchval(self, sql, *args):
        if not self.alive:
            raise RuntimeError("giù")
        return 1

    async def bots(self, active_only=False):
        return list(self.rows)

    async def count_clans(self, bot_alias):
        return len([clan for clan in self.clans if clan.bot_alias == bot_alias])

    async def active_clans(self, bot_alias=None):
        return list(self.clans)

    async def counts(self):
        return {"active": len(self.clans), "total": len(self.clans)}

    async def families(self, bot_alias=None):
        return []

    async def count_links(self):
        return 0

    async def get_state(self, alias, kind):
        return None

    async def wars_since(self, alias, since):
        return []


class BeatSupervisor:
    def __init__(self, fixed=(), running=(), interval=120):
        self.fixed = {alias: None for alias in fixed}
        self.apps = list(running)
        self.poller = SimpleNamespace(interval=interval)

    def running(self):
        return list(self.apps)


class BeatCoc:
    def __init__(self, keys=("una",), dead=0):
        self.keys = list(keys)
        self.dead = dead

    def keys_alive(self):
        return len(self.keys) - self.dead


def request(path, method="GET", peer="127.0.0.2", headers=b""):
    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(f"{method} {path} HTTP/1.1\r\n".encode() + headers + b"\r\n")
        reader.feed_eof()
        return await http.read_request(reader, peer)
    return asyncio.run(go())


def serve(site, path, method="GET", headers=b""):
    return asyncio.run(site.router(request(path, method, headers=headers)))


def fresh_note(running=1, wanted=1):
    return payload.services_note(now_utc(), 30, 60, True, 2, 2, running, wanted)


def same_dress(text):
    body = text.split("<body>")[1]
    marchio = static.manifest()["hash"]
    assert text.count("<style>") == 1 and text.count("<link") == len(pages.SHEETS)
    for foglio in pages.SHEETS:
        assert f'<link rel="stylesheet" href="/static/{marchio}/{foglio}">' in text, foglio
    assert style.CSS in text
    assert body.startswith(pages.TOP_OPEN) and body.count(pages.TOP_OPEN) == 1
    assert pages.BRAND in body
    assert "<footer>" in body and "<script" not in text


def test_match_reads_the_parts_of_the_path():
    assert web_app.match("/c/<slug>", "/c/abc123") == {"slug": "abc123"}
    assert web_app.match("/c/<slug>/widget", "/c/abc123/widget") == {"slug": "abc123"}
    assert web_app.match("/c/<slug>", "/c/abc123/widget") is None
    assert web_app.match("/c/<slug>", "/c/") is None
    assert web_app.match("/status", "/status") == {}
    assert web_app.match("/", "/") == {}


def test_match_gives_the_rest_of_the_path_to_the_last_part():
    assert web_app.match("/static/<stamp>/<name...>", "/static/abc/app/main.js") == {
        "stamp": "abc", "name": "app/main.js"}
    assert web_app.match("/static/<stamp>/<name...>", "/static/abc/main.js") == {
        "stamp": "abc", "name": "main.js"}
    assert web_app.match("/static/<stamp>/<name...>", "/static/abc") is None
    assert web_app.match("/static/<stamp>/<name...>", "/static/abc/") is None


def test_the_locale_comes_from_the_browser_when_nobody_says_otherwise():
    req = request("/status", headers=b"Accept-Language: it-IT,it;q=0.9,en;q=0.8\r\n")
    assert web_app.pick_locale(req).code == "it"
    assert web_app.pick_locale(req, "pt-BR").code == "pt-BR"
    assert web_app.pick_locale(request("/status", headers=b"Accept-Language: xx\r\n")).code == "en"
    assert web_app.pick_locale(request("/status")).code == "en"
    assert web_app.known_tag("zh-TW") and web_app.known_tag("pt") and not web_app.known_tag("xx")


def test_services_note_reads_every_state_from_real_numbers():
    note = payload.services_note(NOW, 30, 60, True, 2, 2, 1, 1)
    assert note["updated"] == int(NOW.timestamp()) and note["interval"] == 60
    assert {s["name"]: s["state"] for s in note["services"]} == {
        "bot": "up", "poller": "up", "db": "up", "clash": "up"}
    degraded = payload.services_note(NOW, 150, 60, True, 1, 3, 1, 2)
    assert {s["name"]: s["state"] for s in degraded["services"]} == {
        "bot": "degraded", "poller": "degraded", "db": "up", "clash": "degraded"}
    down = payload.services_note(NOW, 9999, 60, False, 0, 3, 0, 2)
    assert {s["name"]: s["state"] for s in down["services"]} == {
        "bot": "down", "poller": "down", "db": "down", "clash": "down"}
    assert payload.services_note(NOW, 10, 60, True, 0, 0, 0, 0)["services"][0]["state"] == "up"


def test_status_body_adds_the_web_and_takes_the_worst():
    note = payload.services_note(NOW, 30, 60, True, 2, 2, 1, 1)
    body = payload.status_body(note, NOW)
    assert [s["name"] for s in body["services"]] == ["bot", "poller", "db", "clash", "web"]
    assert body["state"] == "up" and body["checked"] == int(NOW.timestamp())
    assert all(key in ("state", "checked", "services") for key in body)


def test_a_stale_note_is_not_shown_as_fresh():
    note = payload.services_note(NOW, 30, 60, True, 2, 2, 1, 1)
    body = payload.status_body(note, NOW + timedelta(minutes=10))
    assert {s["state"] for s in body["services"] if s["name"] != "web"} == {"down"}
    assert body["state"] == "down"


def test_without_any_note_the_page_says_down_and_does_not_break():
    body = payload.status_body(None, NOW)
    assert body["state"] == "down"
    assert [s["name"] for s in body["services"]] == list(payload.SERVICES)
    assert body["services"][-1] == {"name": "web", "state": "up"}


def test_the_slug_is_short_stable_and_says_nothing_about_the_clan(tmp_path):
    vault = Vault(tmp_path)
    slug = payload.slug_for(vault, "clan-abc123")
    assert len(slug) == 16 and slug.isalnum()
    assert slug == payload.slug_for(vault, "clan-abc123")
    assert slug != payload.slug_for(vault, "clan-def456")
    assert "clan-abc123" not in slug


def test_the_digest_ignores_the_stamp_and_follows_the_content():
    first = payload.digest({"updated": 1, "services": [{"name": "bot", "state": "up"}]})
    assert first == payload.digest({"updated": 2, "services": [{"name": "bot", "state": "up"}]})
    assert first != payload.digest({"updated": 1, "services": [{"name": "bot", "state": "down"}]})


def test_the_status_page_shows_services_and_no_numbers():
    site = web_app.Site(FakeStore({"services": fresh_note(running=3, wanted=3)}))
    res = serve(site, "/status", headers=ITALIAN)
    assert res.status == 200 and res.kind == http.HTML
    text = res.body.decode()
    for name in payload.SERVICES:
        assert L.t(f"web.status.{name}") in text
    assert L.t("web.status.up") in text
    assert "3" not in text.split("<body")[1].replace("&#x27;", "")
    assert res.headers["Cache-Control"] == "public, max-age=15"


def test_lo_stato_porta_lo_stesso_vestito_della_home():
    site = web_app.Site(FakeStore({"services": fresh_note()}))
    same_dress(serve(site, "/status", headers=ITALIAN).body.decode())
    same_dress(serve(site, "/", headers=ITALIAN).body.decode())
    same_dress(serve(site, "/privacy", headers=ITALIAN).body.decode())


def test_the_status_is_also_json():
    res = serve(web_app.Site(FakeStore({"services": fresh_note()})), "/status.json")
    assert res.status == 200 and res.kind == http.JSON
    assert b'"state":"up"' in res.body


def test_the_home_says_what_this_is_and_credits_supercell():
    res = serve(web_app.Site(FakeStore()), "/", headers=ITALIAN)
    assert res.status == 200
    text = res.body.decode()
    assert "ClanBoard" in text and L.t("web.home.unofficial") in text
    assert "/status" in text


def test_the_home_points_at_the_two_places_with_their_own_names():
    text = serve(web_app.Site(FakeStore()), "/", headers=ITALIAN).body.decode()
    for path, key in (("/status", "web.status.title"), ("/community", "web.community.title")):
        assert f'href="{path}"' in text and L.t(key) in text
    assert "/translate" not in text


def test_security_txt_says_where_to_report_and_when_it_stops_being_true():
    res = serve(web_app.Site(FakeStore(secrets={"source_url": SOURCE})),
                "/.well-known/security.txt")
    assert res.status == 200 and res.kind == http.TEXT
    assert res.headers["Cache-Control"] == pages.PAGE_HEAD == wellknown.CACHE
    assert str(pages.PAGE_CACHE) in pages.PAGE_HEAD
    righe = res.body.decode().splitlines()
    assert f"Contact: {SOURCE}/security/advisories/new" in righe
    assert f"Policy: {SOURCE}/blob/main/SECURITY.md" in righe
    assert "Preferred-Languages: it, en" in righe
    scadenze = [riga for riga in righe if riga.startswith("Expires: ")]
    assert len(scadenze) == 1
    quando = datetime.strptime(scadenze[0].split(" ", 1)[1], "%Y-%m-%dT%H:%M:%SZ")
    assert quando.replace(tzinfo=timezone.utc) == wellknown.EXPIRES.replace(microsecond=0)
    assert wellknown.EXPIRES == wellknown.START.replace(year=wellknown.START.year + 1)
    assert wellknown.EXPIRES > now_utc()


def test_the_expiry_survives_the_leap_day():
    salto = datetime(2028, 2, 29, 12, tzinfo=timezone.utc)
    assert wellknown.expires(salto) == datetime(2029, 2, 28, 12, tzinfo=timezone.utc)


def test_without_a_repository_no_contact_is_invented():
    res = serve(web_app.Site(FakeStore()), "/.well-known/security.txt")
    assert res.status == 404 and res.body == b""


def test_robots_keeps_the_crawlers_on_the_home_and_the_clan_pages():
    res = serve(web_app.Site(FakeStore()), "/robots.txt")
    assert res.status == 200 and res.kind == http.TEXT
    regole = RobotFileParser()
    regole.parse(res.body.decode().splitlines())
    for path in ("/", "/status", "/status.json", "/c/abc123"):
        assert regole.can_fetch("*", path), path
    for path in ("/app/abc123", "/r/abc123", "/board"):
        assert not regole.can_fetch("*", path), path


def test_the_home_asks_to_report_first_and_points_at_the_public_thanks():
    site = web_app.Site(FakeStore(secrets={"source_url": SOURCE}))
    text = serve(site, "/", headers=ITALIAN).body.decode()
    assert L.t("web.home.security") in text
    assert 'href="/.well-known/security.txt"' in text
    assert f'href="{SOURCE}/blob/main/docs/ringraziamenti.md"' in text
    assert L.t("web.home.thanks") in text
    senza = serve(web_app.Site(FakeStore()), "/", headers=ITALIAN).body.decode()
    assert L.t("web.home.security") in senza and "ringraziamenti" not in senza


def test_the_site_has_no_panel_no_login_and_no_translation_portal():
    gone = ("/panel", "/auth", "/logout", "/translate")
    for _, path, _ in web_app.ROUTES:
        assert not path.startswith(gone), path
    for path in ("/translate", "/translate/it"):
        assert serve(web_app.Site(FakeStore()), path).status == 404, path
    assert serve(web_app.Site(FakeStore()), "/logout", method="POST").status == 404
    for path in ("/panel", "/panel/usage.json", "/auth"):
        assert serve(web_app.Site(FakeStore()), path).status == 403, path


def test_no_answer_of_the_site_hands_out_a_cookie():
    site = web_app.Site(FakeStore({"services": fresh_note()}))
    for path, method in (("/", "GET"), ("/status", "GET"), ("/status.json", "GET"),
                         ("/panel", "GET"), ("/auth", "GET"), ("/logout", "POST")):
        assert "Set-Cookie" not in serve(site, path, method=method).headers, path
    for name in ("session", "is_manager", "may_approve", "fresh_strings"):
        assert not hasattr(web_app.Site, name), name


def test_the_web_container_never_creates_the_master_key(monkeypatch):
    seen = {}
    monkeypatch.setattr(web_app, "Vault", lambda **kw: seen.update(kw) or "vault")
    assert web_app.open_vault() == "vault"
    assert seen == {"create": False}
    with pytest.raises(FileNotFoundError):
        Vault(Path("/tmp/clashbot-chiave-che-non-esiste"), create=False)


def test_unknown_paths_and_wrong_methods_are_answered_properly():
    site = web_app.Site(FakeStore())
    assert serve(site, "/pinco").status == 404
    assert serve(site, "/status", method="POST").status == 405
    assert serve(site, "/status", method="DELETE").status == 405
    assert serve(site, "/status", method="HEAD").status == 200


def test_too_many_requests_get_a_429_with_retry_after():
    site = web_app.Site(FakeStore(), clock=lambda: 0.0)
    for _ in range(http.READ_RATE):
        assert serve(site, "/status").status == 200
    res = serve(site, "/status")
    assert res.status == 429 and res.headers["Retry-After"] == "60"


def test_a_page_that_explodes_answers_500_and_says_nothing_else():
    class Broken(FakeStore):
        async def web_note(self, name):
            raise RuntimeError("pinco")

    res = serve(web_app.Site(Broken()), "/status")
    assert res.status == 500 and res.body == b""


def test_the_server_really_answers_on_a_socket():
    async def go():
        site = web_app.Site(FakeStore())
        server = await http.serve(site.router, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /status.json HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        server.close()
        await server.wait_closed()
        return raw

    raw = asyncio.run(go())
    assert raw.startswith(b"HTTP/1.1 200 OK") and b'"services"' in raw


def test_the_beat_writes_the_note_and_then_waits_its_turn(tmp_path):
    heartbeat = tmp_path / "beat"
    heartbeat.touch()
    clock = [0.0]
    pulse = publish.Beat(BeatStore(bots=[beat_bot("b1")]),
                         BeatSupervisor(running=["b1"]), BeatCoc(), heartbeat,
                         clock=lambda: clock[0])
    assert asyncio.run(pulse.once()) is True
    note = pulse.store.notes["services"]
    assert note["interval"] == 120
    assert {s["name"]: s["state"] for s in note["services"]} == {
        "bot": "up", "poller": "up", "db": "up", "clash": "up"}
    assert asyncio.run(pulse.once()) is False
    clock[0] = publish.NOTES_EVERY
    assert asyncio.run(pulse.once()) is True


def test_the_beat_says_down_when_the_database_and_the_heartbeat_are_gone(tmp_path):
    pulse = publish.Beat(BeatStore(alive=False), BeatSupervisor(fixed=["console"]),
                         BeatCoc(dead=1), tmp_path / "mai")
    assert asyncio.run(pulse.once()) is True
    assert {s["name"]: s["state"] for s in pulse.store.notes["services"]["services"]} == {
        "bot": "down", "poller": "down", "db": "down", "clash": "down"}


def test_the_health_command_looks_at_the_heartbeat_it_is_asked_for(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "HEARTBEAT", tmp_path / "bot")
    monkeypatch.setattr(cli, "WEB_HEARTBEAT", tmp_path / "web")
    for argv in ([], ["--web"]):
        with pytest.raises(SystemExit) as fermo:
            cli.health(argv)
        assert fermo.value.code == 1
    (tmp_path / "web").touch()
    with pytest.raises(SystemExit) as vivo:
        cli.health(["--web"])
    assert vivo.value.code == 0
    with pytest.raises(SystemExit) as senza_bot:
        cli.health()
    assert senza_bot.value.code == 1


def test_the_web_container_is_not_exposed_and_reads_the_keys_only():
    web = COMPOSE.read_text(encoding="utf-8").split("\n  web:")[1].split("\n\nnetworks:")[0]
    assert 'command: ["web"]' in web and "ports:" not in web
    assert "clashbot-keys:/keys:ro" in web and "clashbot-locales:/locales:ro" in web
    assert '"health", "--web"' in web


def test_the_web_waits_for_the_master_key_instead_of_writing_it(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "KEY_DIR", str(tmp_path))
    path = tmp_path / web_app.MASTER

    async def go():
        waiting = asyncio.create_task(web_app.wait_for_key(step=0.01))
        await asyncio.sleep(0.05)
        assert not waiting.done() and not path.exists()
        path.write_text("finta")
        await asyncio.wait_for(waiting, 2)

    asyncio.run(go())
    assert path.read_text() == "finta"
