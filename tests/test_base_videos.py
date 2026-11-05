import asyncio
import io
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
from test_retention import FakeAcquire, FakeTransaction, flat

from clashbot import __main__ as main_mod, base_videos, supervisor as supervisor_mod
from clashbot.crypto import Vault
from clashbot.db import SCHEMA, Store
from clashbot.retention import WAR_HISTORY_KEEP
from clashbot.supervisor import Supervisor

GOOD = "https://link.clashofclans.com/en?action=OpenLayout&id=TH16%3AHV%3AAAAABBBBCCCCDDDD"
OTHER = "https://link.clashofclans.com/en?action=OpenLayout&id=BH10%3ABB%3AZZZZ1111WWWW"
FINTA = "chiave-finta-di-prova"
NOW = 1758556800.0
PACIFIC = ZoneInfo(base_videos.PACIFIC)
UPLOADS = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUplat"}}}]}
DENIED = {"error": {"errors": [{"reason": "quotaExceeded", "domain": "youtube.quota"}]}}
VIDEOS = {"items": [
    {"snippet": {"resourceId": {"videoId": "vid1"}, "title": "Anti tre stelle",
                 "publishedAt": "2026-09-20T10:00:00Z",
                 "description": f"Il layout {GOOD} e il canale https://www.youtube.com/@tizio"}},
    {"snippet": {"resourceId": {"videoId": "vid2"}, "title": "Due chiacchiere",
                 "publishedAt": "2026-09-19T10:00:00Z", "description": "nessun link qui"}},
]}


def test_links_in_keeps_only_the_official_links_of_the_description():
    text = f"Base nuova {GOOD}. Iscriviti https://www.youtube.com/@tizio e {OTHER} ({GOOD})"
    assert base_videos.links_in(text) == [GOOD, OTHER]
    assert base_videos.links_in(None) == [] and base_videos.links_in("") == []
    assert base_videos.links_in("https://link.clashofclans.com/en?action=Altro&id=x") == []


class FakeStore:
    def __init__(self, platform=(), clans=(), states=None):
        self.kv = {}
        self.states = dict(states or {})
        self.clans = [SimpleNamespace(alias=alias) for alias in clans]
        self.saved = []
        self.secret = None
        if platform:
            self.kv[base_videos.CHANNELS_KEY] = list(platform)

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def active_clans(self):
        return list(self.clans)

    async def get_state(self, alias, kind):
        return self.states.get((alias, kind))

    async def get_secret(self, kind):
        return self.secret

    async def videos_put(self, rows):
        self.saved.extend(rows)
        return len(rows)


class FakeClient:
    def __init__(self, replies=(), error=None):
        self.replies = list(replies)
        self.error = error
        self.urls = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        for piece, status, body in self.replies:
            if piece in url:
                return SimpleNamespace(status_code=status, json=lambda body=body: body)
        raise AssertionError(f"nessuna risposta per {base_videos.masked(url)}")


def answering(*pairs):
    return FakeClient([(f"/{path}?", status, body) for path, status, body in pairs])


def whole(store):
    return json.dumps({str(key): value for key, value in store.kv.items()})


def test_channels_joins_the_platform_list_with_the_ones_of_every_clan():
    store = FakeStore(
        platform=[{"id": "UCplat", "title": "Builder"}, {"id": "UCplat", "title": "doppio"},
                  {"title": "senza id"}, "rotta"],
        clans=("clan-1", "clan-2"),
        states={("clan-1", base_videos.STATE_KIND): {"channels": [{"id": "UCuno", "title": "Uno"}]}})
    assert asyncio.run(base_videos.channels(store)) == {
        "platform": [{"id": "UCplat", "title": "Builder"}],
        "clans": {"clan-1": [{"id": "UCuno", "title": "Uno"}]}}


def test_channels_reads_a_bare_list_of_the_clan_state_too():
    store = FakeStore(clans=("clan-1",),
                      states={("clan-1", base_videos.STATE_KIND): [{"id": "UCuno"}]})
    assert asyncio.run(base_videos.channels(store)) == {
        "platform": [], "clans": {"clan-1": [{"id": "UCuno", "title": ""}]}}


def test_refresh_saves_the_videos_with_the_links_of_the_description():
    store = FakeStore(platform=[{"id": "UCplat", "title": "Builder"}])
    client = answering(("channels", 200, UPLOADS), ("playlistItems", 200, VIDEOS))
    assert asyncio.run(base_videos.refresh(store, client, FINTA, NOW)) == {
        "status": "fresh", "videos": 2}
    assert [row["id"] for row in store.saved] == ["vid1", "vid2"]
    assert store.saved[0] == {"id": "vid1", "scope": base_videos.PLATFORM, "channel": "UCplat",
                              "title": "Anti tre stelle", "published": "2026-09-20T10:00:00Z",
                              "links": [GOOD]}
    assert store.saved[1]["links"] == []


def test_refresh_puts_the_key_only_in_the_url_and_never_in_the_kv_or_in_the_answer():
    store = FakeStore(platform=[{"id": "UCplat"}])
    client = answering(("channels", 200, UPLOADS), ("playlistItems", 200, VIDEOS))
    answer = asyncio.run(base_videos.refresh(store, client, FINTA, NOW))
    assert all(f"key={FINTA}" in url for url in client.urls)
    assert FINTA not in whole(store) and FINTA not in json.dumps(answer)
    assert FINTA not in json.dumps(store.saved)
    assert all(FINTA not in base_videos.masked(url) for url in client.urls)


def test_refresh_asks_the_uploads_playlist_once_and_then_only_the_videos():
    store = FakeStore(platform=[{"id": "UCplat"}])
    first = answering(("channels", 200, UPLOADS), ("playlistItems", 200, VIDEOS))
    asyncio.run(base_videos.refresh(store, first, FINTA, NOW))
    assert store.kv[base_videos.UPLOADS_KEY + "UCplat"] == {"playlist": "UUplat"}
    assert [url.split("?")[0].rsplit("/", 1)[-1] for url in first.urls] == [
        base_videos.CHANNELS_PATH, base_videos.ITEMS_PATH]
    again = answering(("playlistItems", 200, VIDEOS))
    assert asyncio.run(base_videos.refresh(store, again, FINTA, NOW)) == {
        "status": "fresh", "videos": 2}
    assert len(again.urls) == 1 and "playlistId=UUplat" in again.urls[0]


def test_refresh_writes_a_row_for_every_scope_that_asked_for_the_channel():
    store = FakeStore(platform=[{"id": "UCplat"}], clans=("clan-1",),
                      states={("clan-1", base_videos.STATE_KIND): {"channels": [{"id": "UCplat"}]}})
    client = answering(("channels", 200, UPLOADS), ("playlistItems", 200, VIDEOS))
    assert asyncio.run(base_videos.refresh(store, client, FINTA, NOW))["videos"] == 4
    assert sorted({row["scope"] for row in store.saved}) == ["clan-1", base_videos.PLATFORM]
    assert len(client.urls) == 2


def test_refresh_shares_the_cap_among_the_channels_and_never_goes_under_one():
    assert base_videos.per_channel(1) == base_videos.PAGE_MAX
    assert base_videos.per_channel(3) == WAR_HISTORY_KEEP // 3
    assert base_videos.per_channel(WAR_HISTORY_KEEP * 2) == 1
    store = FakeStore(platform=[{"id": "UCplat"}])
    client = answering(("channels", 200, UPLOADS), ("playlistItems", 200, VIDEOS))
    asyncio.run(base_videos.refresh(store, client, FINTA, NOW))
    assert f"maxResults={base_videos.PAGE_MAX}" in client.urls[-1]
    assert "part=snippet" in client.urls[-1]


def test_the_quota_stops_the_round_until_the_midnight_of_google_in_california():
    store = FakeStore(platform=[{"id": "UCplat"}])
    denied = answering(("channels", 200, UPLOADS), ("playlistItems", 403, DENIED))
    assert asyncio.run(base_videos.refresh(store, denied, FINTA, NOW)) == {
        "status": "quota", "videos": 0}
    until = store.kv[base_videos.QUOTA_KEY]["until"]
    local = datetime.fromtimestamp(until, PACIFIC)
    assert (local.hour, local.minute, local.second) == (0, 0, 0)
    assert local.date() > datetime.fromtimestamp(NOW, PACIFIC).date()
    assert FINTA not in whole(store)
    quiet = FakeClient()
    assert asyncio.run(base_videos.refresh(store, quiet, FINTA, until - 1)) == {
        "status": "quota", "videos": 0}
    assert quiet.urls == []
    after = answering(("playlistItems", 200, VIDEOS))
    assert asyncio.run(base_videos.refresh(store, after, FINTA, until))["status"] == "fresh"


def test_refresh_says_nokey_and_asks_nothing_without_the_key():
    store = FakeStore(platform=[{"id": "UCplat"}])
    quiet = FakeClient()
    assert asyncio.run(base_videos.refresh(store, quiet, None, NOW)) == {
        "status": "nokey", "videos": 0}
    assert quiet.urls == [] and store.saved == []


def test_refresh_asks_nothing_when_nobody_added_a_channel():
    quiet = FakeClient()
    assert asyncio.run(base_videos.refresh(FakeStore(), quiet, FINTA, NOW)) == {
        "status": "fresh", "videos": 0}
    assert quiet.urls == []


def test_refresh_survives_a_broken_source_a_missing_playlist_and_a_broken_store():
    store = FakeStore(platform=[{"id": "UCplat"}])
    broken = FakeClient(error=httpx.ConnectError("giu"))
    assert asyncio.run(base_videos.refresh(store, broken, FINTA, NOW)) == {
        "status": "down", "videos": 0}
    assert store.saved == [] and len(broken.urls) == 1
    empty = answering(("channels", 200, {"items": []}))
    assert asyncio.run(base_videos.refresh(store, empty, FINTA, NOW))["status"] == "down"
    lost = answering(("channels", 200, UPLOADS), ("playlistItems", 500, {}))
    assert asyncio.run(base_videos.refresh(store, lost, FINTA, NOW))["status"] == "down"


def test_refresh_keeps_the_good_channel_when_another_one_is_down():
    store = FakeStore(platform=[{"id": "UCplat"}, {"id": "UCrotto"}])
    store.kv[base_videos.UPLOADS_KEY + "UCplat"] = {"playlist": "UUplat"}
    store.kv[base_videos.UPLOADS_KEY + "UCrotto"] = {"playlist": "UUrotto"}
    client = FakeClient([("playlistId=UUplat", 200, VIDEOS), ("playlistId=UUrotto", 500, {})])
    assert asyncio.run(base_videos.refresh(store, client, FINTA, NOW)) == {
        "status": "fresh", "videos": 2}
    assert [row["channel"] for row in store.saved] == ["UCplat", "UCplat"]


def test_masked_takes_the_key_away_and_keeps_the_rest():
    url = base_videos.call_url(base_videos.ITEMS_PATH, {"part": "snippet"}, FINTA)
    assert f"key={FINTA}" in url
    assert base_videos.masked(url) == f"{base_videos.API}/{base_videos.ITEMS_PATH}?part=snippet"
    assert base_videos.masked(None) == "" and base_videos.masked("") == ""


def test_api_key_reads_the_vault_and_stays_quiet_when_it_cannot(caplog):
    store = FakeStore()
    store.secret = FINTA
    assert asyncio.run(base_videos.api_key(store)) == FINTA

    class Broken:
        async def get_secret(self, kind):
            raise RuntimeError("vault giu")

    with caplog.at_level("WARNING"):
        assert asyncio.run(base_videos.api_key(Broken())) is None
    assert "vault giu" not in caplog.text and FINTA not in caplog.text


FOUND = {"items": [{"id": "UCtizio", "snippet": {"title": "Tizio"}}]}


def test_the_channel_comes_from_the_bare_id_without_asking_anybody():
    store = FakeStore()
    store.secret = FINTA
    quiet = FakeClient()
    assert asyncio.run(base_videos.found_channel(store, " UCplat ", quiet)) == {
        "id": "UCplat", "title": ""}
    assert quiet.urls == []
    for raw in ("chi va là?", "https://www.youtube.com/watch?v=vid1", "http://www.youtube.com/@tizio",
                "https://esempio.test/@tizio", None):
        assert asyncio.run(base_videos.found_channel(store, raw, quiet)) is None, raw
    assert quiet.urls == []


def test_the_channel_of_a_youtube_link_is_asked_by_its_handle():
    store = FakeStore()
    store.secret = FINTA
    client = answering(("channels", 200, FOUND))
    assert asyncio.run(base_videos.found_channel(
        store, "https://www.youtube.com/@tizio", client)) == {"id": "UCtizio", "title": "Tizio"}
    assert f"{base_videos.HANDLE_PARAM}=%40tizio" in client.urls[0]
    assert f"key={FINTA}" in client.urls[0]
    assert FINTA not in base_videos.masked(client.urls[0]) and FINTA not in whole(store)


def test_without_the_key_or_with_a_source_that_says_no_the_channel_stays_unknown():
    store = FakeStore()
    quiet = FakeClient()
    assert asyncio.run(base_videos.found_channel(
        store, "https://m.youtube.com/@tizio", quiet)) is None
    assert quiet.urls == []
    store.secret = FINTA
    for reply in (("channels", 403, DENIED), ("channels", 200, {"items": []}),
                  ("channels", 500, {})):
        assert asyncio.run(base_videos.found_channel(
            store, "https://youtube.com/@tizio", answering(reply))) is None, reply


def test_the_platform_channels_are_added_once_and_taken_away_when_asked():
    store = FakeStore(platform=[{"id": "UCplat", "title": "Builder"}])
    assert asyncio.run(base_videos.add_channel(store, {"id": "UCplat", "title": "doppio"})) is False
    assert asyncio.run(base_videos.add_channel(store, {"id": "UCuno", "title": "Uno"})) is True
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": "UCplat", "title": "Builder"},
                                                  {"id": "UCuno", "title": "Uno"}]
    assert asyncio.run(base_videos.drop_channel(store, "UCplat")) is True
    assert asyncio.run(base_videos.drop_channel(store, "UCplat")) is False
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": "UCuno", "title": "Uno"}]
    assert asyncio.run(base_videos.platform_rows(store)) == [{"id": "UCuno", "title": "Uno"}]


def test_the_supervisor_reads_the_videos_with_the_key_of_the_vault(monkeypatch):
    calls = []

    class Meter:
        def __init__(self, store, key):
            self.store = store

        async def once(self):
            calls.append(("meter", None, None))

    async def check(store, bot, client):
        calls.append(("ops", client, None))
        return False

    async def library(store, client, now):
        calls.append(("library", client, None))
        return {"status": "down", "count": 0}

    async def videos(store, client, key, now):
        calls.append(("videos", client, key))
        return {"status": "nokey", "videos": 0}

    async def news(store, client, key, coc, now):
        calls.append(("news", client, key))
        supervisor.stopping = True
        return []

    monkeypatch.setattr(supervisor_mod, "PLATFORM_INTERVAL", 0)
    monkeypatch.setattr(supervisor_mod.selfmetrics, "Recorder", Meter)
    monkeypatch.setattr(supervisor_mod.ops, "check", check)
    monkeypatch.setattr(supervisor_mod.base_library, "refresh", library)
    monkeypatch.setattr(supervisor_mod.base_videos, "refresh", videos)
    monkeypatch.setattr(supervisor_mod.news_feed, "collect", news)
    store = FakeStore()
    store.secret = FINTA
    supervisor = Supervisor(store, None)
    asyncio.run(supervisor.measure())
    assert [name for name, _, _ in calls] == ["meter", "ops", "library", "videos", "news"]
    assert calls[-1][1] is calls[-2][1] and calls[-1][1] is not None
    assert calls[-1][2] == FINTA


class Conn:
    def __init__(self):
        self.log = []

    def transaction(self):
        return FakeTransaction(self)

    async def executemany(self, sql, rows):
        self.log.append((flat(sql), list(rows)))

    async def execute(self, sql, *args):
        self.log.append((flat(sql), args))
        return "DELETE 1"


class Pool:
    def __init__(self, rows=()):
        self.conn = Conn()
        self.rows = list(rows)
        self.fetched = []

    def acquire(self):
        return FakeAcquire(self.conn)

    async def fetch(self, sql, *args):
        self.fetched.append((flat(sql), args))
        return self.rows


def store_with(tmp_path, rows=()):
    store = Store(Vault(tmp_path))
    store.pool = Pool(rows)
    return store


class VaultStore:
    def __init__(self):
        self.saved = []

    async def set_secret(self, kind, value):
        self.saved.append((kind, value))
        return "alias-dei-video"


def test_the_key_of_the_videos_goes_in_the_vault_with_the_secret_command(monkeypatch, capsys):
    store = VaultStore()
    monkeypatch.setattr(main_mod.sys, "stdin", io.StringIO(FINTA + "\n"))
    asyncio.run(main_mod.secret(store, base_videos.SECRET))
    assert store.saved == [(base_videos.SECRET, FINTA)]
    assert FINTA not in capsys.readouterr().out
    assert base_videos.SECRET not in main_mod.PLAIN_KINDS


def test_the_schema_creates_the_videos_table_only_if_it_is_missing():
    assert "create table if not exists base_videos (" in SCHEMA
    piece = SCHEMA.split("base_videos (")[1][:600]
    for column in ("video_id text not null", "scope text not null", "channel_id text not null",
                   "title text not null", "published_at text not null", "links text[] not null",
                   "seen_at timestamptz not null", "primary key (video_id, scope)"):
        assert column in piece
    assert ("create index if not exists base_videos_pick_idx on base_videos"
            " (scope, published_at desc)") in SCHEMA


def test_videos_put_writes_every_scope_and_prunes_the_oldest_of_each_channel(tmp_path):
    store = store_with(tmp_path)
    rows = [{"id": "vid1", "scope": "platform", "channel": "UCplat", "title": "Anti tre stelle",
             "published": "2026-09-20T10:00:00Z", "links": [GOOD]},
            {"id": "vid2", "scope": "platform", "channel": "UCplat", "title": "Due chiacchiere",
             "published": "2026-09-19T10:00:00Z", "links": []},
            {"id": "vid3", "scope": "clan-1", "channel": "UCuno", "title": "", "published": "",
             "links": []}]
    assert asyncio.run(store.videos_put(rows)) == 3
    log = store.pool.conn.log
    assert log[0] == "begin" and log[-1] == "commit"
    upsert = log[1]
    assert upsert[0].startswith("insert into base_videos(")
    assert "on conflict (video_id, scope) do update" in upsert[0]
    assert upsert[1][0] == ("vid1", "platform", "UCplat", "Anti tre stelle",
                            "2026-09-20T10:00:00Z", [GOOD])
    prunes = [(sql, args) for sql, args in log[2:-1]]
    assert all(sql.startswith("delete from base_videos where channel_id") for sql, _ in prunes)
    assert sorted(args for _, args in prunes) == [("UCplat", "platform", WAR_HISTORY_KEEP),
                                                  ("UCuno", "clan-1", WAR_HISTORY_KEEP)]


def test_videos_put_writes_nothing_when_there_is_nothing(tmp_path):
    store = store_with(tmp_path)
    assert asyncio.run(store.videos_put([])) == 0
    assert store.pool.conn.log == []


def test_videos_rows_reads_one_scope_at_a_time(tmp_path):
    row = {"video_id": "vid1", "channel_id": "UCplat", "title": "Anti tre stelle",
           "published_at": "2026-09-20T10:00:00Z", "links": [GOOD]}
    store = store_with(tmp_path, rows=[row])
    assert asyncio.run(store.videos_rows("platform")) == [
        {"id": "vid1", "channel": "UCplat", "title": "Anti tre stelle",
         "published": "2026-09-20T10:00:00Z", "links": [GOOD]}]
    sql, args = store.pool.fetched[0]
    assert sql.startswith("select video_id, channel_id, title, published_at, links")
    assert args == ("platform", WAR_HISTORY_KEEP)
    asyncio.run(store.videos_rows())
    assert store.pool.fetched[1][1] == (None, WAR_HISTORY_KEEP)


VIDEO_ROWS = [
    {"id": "vid1", "channel": "UCplat", "title": "TH16 attacco anti tre stelle", "published": "3"},
    {"id": "vid2", "channel": "UCclan", "title": "th15 e TH16 a confronto", "published": "2"},
    {"id": "vid3", "channel": "UCplat", "title": "BH10 villaggio dei costruttori", "published": "1"},
    {"id": "vid4", "channel": "UCplat", "title": "TH09 di una volta", "published": "0"},
]


def test_i_video_d_attacco_si_dividono_per_municipio():
    found = base_videos.attack_videos(VIDEO_ROWS)
    assert set(found) == {"16", "15", "9"}
    assert found["16"] == [{"video_id": "vid1", "title": VIDEO_ROWS[0]["title"],
                            "channel": "UCplat"},
                           {"video_id": "vid2", "title": VIDEO_ROWS[1]["title"],
                            "channel": "UCclan"}]
    assert [row["video_id"] for row in found["15"]] == ["vid2"]
    assert [row["video_id"] for row in found["9"]] == ["vid4"]


def test_un_titolo_senza_municipio_non_finisce_da_nessuna_parte():
    assert base_videos.attack_videos([]) == {}
    assert base_videos.attack_videos(None) == {}
    assert base_videos.attack_videos([{"id": "vid5", "title": "basi nuove", "channel": "UCplat"},
                                      {"id": "vid6", "title": "", "channel": "UCplat"}]) == {}


def test_il_video_si_apre_dal_suo_indirizzo():
    assert base_videos.WATCH.startswith("https://www.youtube.com/")
    assert base_videos.WATCH.endswith("=")
