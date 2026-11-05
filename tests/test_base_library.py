import asyncio
from types import SimpleNamespace

import httpx
from test_retention import FakeAcquire, FakeTransaction, flat

from clashbot import base_library, supervisor as supervisor_mod
from clashbot.crypto import Vault
from clashbot.db import SCHEMA, Store
from clashbot.retention import WAR_HISTORY_KEEP
from clashbot.supervisor import Supervisor

GOOD = "https://link.clashofclans.com/en?action=OpenLayout&id=TH16%3AHV%3AAAAABBBBCCCCDDDD"
BUILDER = "https://link.clashofclans.com/en?action=OpenLayout&id=BH10%3ABB%3AZZZZ1111WWWW"
NOW = 1758556800.0


def test_parse_keeps_only_official_links_and_drops_images():
    rows = base_library.parse([
        {"id": "a", "name": "Anti 3", "town_hall": 16, "type": "War", "link": GOOD,
         "image": "http://x/y.png", "description": "due torri veleno", "builder": "Pino",
         "tags": ["anti-air"], "added": "2026-09-01"},
        {"id": "b", "name": "Rotta", "town_hall": 16, "type": "War",
         "link": "https://evil.example/x"},
    ])
    assert [row["id"] for row in rows] == ["a"]
    assert "image" not in rows[0] and "description" not in rows[0]
    assert rows[0] == {"id": "a", "name": "Anti 3", "hall": 16, "village": "home", "kind": "war",
                       "link": GOOD, "builder": "Pino", "tags": ["anti-air"],
                       "added": "2026-09-01"}


def test_parse_reads_village_and_hall_from_the_link_and_lowers_the_kind():
    rows = base_library.parse([
        {"id": "c", "name": "Notte", "town_hall": 10, "type": "Home Village", "link": BUILDER,
         "builder": "Gino", "tags": [], "added": "2026-09-02"},
        {"id": "d", "link": GOOD},
        {"name": "senza id", "link": GOOD},
        None,
    ])
    assert rows[0]["village"] == "builder" and rows[0]["hall"] == 10
    assert rows[0]["kind"] == "home village"
    assert rows[1] == {"id": "d", "name": "", "hall": 16, "village": "home", "kind": "",
                       "link": GOOD, "builder": "", "tags": [], "added": ""}
    assert len(rows) == 2


class KvStore:
    def __init__(self, broken=False):
        self.kv = {}
        self.library = []
        self.puts = 0
        self.broken = broken

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        if self.broken:
            raise RuntimeError("kv giu")
        self.kv[key] = obj

    async def library_put(self, rows):
        self.puts += 1
        if not rows:
            return 0
        self.library = list(rows)
        return len(rows)


class FakeClient:
    def __init__(self, status, body=None, etag="W/1", error=None):
        self.status, self.body, self.etag, self.error = status, body, etag, error
        self.sent = []
        self.urls = []

    async def get(self, url, headers=None, timeout=None):
        self.sent.append(headers or {})
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(status_code=self.status, headers={"ETag": self.etag},
                               json=lambda: self.body)


def file_of(*rows):
    return {"bases": list(rows)}


ONE = {"id": "a", "name": "Anti 3", "town_hall": 16, "type": "War", "link": GOOD,
       "builder": "Pino", "tags": ["anti-air"], "added": "2026-09-01"}


def test_refresh_sends_the_etag_and_skips_when_unchanged():
    store = KvStore()
    client = FakeClient(200, file_of(ONE))
    first = asyncio.run(base_library.refresh(store, client, NOW))
    assert first == {"status": "fresh", "count": 1}
    assert store.library[0]["id"] == "a" and client.urls == [base_library.URL]
    assert "If-None-Match" not in client.sent[0]
    unchanged = FakeClient(304)
    second = asyncio.run(base_library.refresh(store, unchanged, NOW))
    assert second == {"status": "same", "count": 1}
    assert unchanged.sent[0].get("If-None-Match") == "W/1"
    down = asyncio.run(base_library.refresh(store, FakeClient(500), NOW))
    assert down["status"] == "down" and store.library[0]["id"] == "a"


def test_refresh_reads_a_bare_list_too_and_records_the_round_for_the_panel():
    store = KvStore()
    assert asyncio.run(base_library.refresh(store, FakeClient(200, [ONE]), NOW)) == {
        "status": "fresh", "count": 1}
    assert store.kv[base_library.LAST_KEY] == {"status": "fresh", "count": 1, "at": NOW}
    asyncio.run(base_library.refresh(store, FakeClient(304), NOW + 1))
    assert store.kv[base_library.LAST_KEY] == {"status": "same", "count": 1, "at": NOW + 1}


def test_refresh_keeps_the_last_copy_when_the_source_gives_nothing():
    store = KvStore()
    asyncio.run(base_library.refresh(store, FakeClient(200, file_of(ONE)), NOW))
    empty = FakeClient(200, file_of(), etag="W/2")
    assert asyncio.run(base_library.refresh(store, empty, NOW)) == {"status": "down", "count": 1}
    assert store.library[0]["id"] == "a" and store.puts == 1
    assert store.kv[base_library.ETAG_KEY] == {"etag": "W/1"}


def test_refresh_survives_a_broken_source_and_a_broken_store():
    store = KvStore()
    broken = FakeClient(200, error=httpx.ConnectError("giu"))
    assert asyncio.run(base_library.refresh(store, broken, NOW)) == {"status": "down", "count": 0}
    assert store.library == [] and store.puts == 0
    assert asyncio.run(base_library.refresh(KvStore(broken=True), FakeClient(304), NOW)) == {
        "status": "down", "count": 0}


def test_the_supervisor_refreshes_the_library_right_after_the_ops_round(monkeypatch):
    calls = []

    class Meter:
        def __init__(self, store, key):
            self.store = store

        async def once(self):
            calls.append(("meter", None))

    async def check(store, bot, client):
        calls.append(("ops", client))
        return False

    async def refresh(store, client, now):
        calls.append(("library", client))
        supervisor.stopping = True
        return {"status": "down", "count": 0}

    monkeypatch.setattr(supervisor_mod, "PLATFORM_INTERVAL", 0)
    monkeypatch.setattr(supervisor_mod.selfmetrics, "Recorder", Meter)
    monkeypatch.setattr(supervisor_mod.ops, "check", check)
    monkeypatch.setattr(supervisor_mod.base_library, "refresh", refresh)
    supervisor = Supervisor(SimpleNamespace(), None)
    asyncio.run(supervisor.measure())
    assert [name for name, _ in calls] == ["meter", "ops", "library"]
    assert calls[-1][1] is calls[-2][1] and calls[-1][1] is not None


class Conn:
    def __init__(self):
        self.log = []

    def transaction(self):
        return FakeTransaction(self)

    async def executemany(self, sql, rows):
        self.log.append((flat(sql), list(rows)))

    async def execute(self, sql, *args):
        self.log.append((flat(sql), args))
        return "DELETE 2"


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


def test_the_schema_creates_the_library_table_only_if_it_is_missing():
    assert "create table if not exists base_library (" in SCHEMA
    for piece in ("id text primary key", "hall int not null", "village text not null",
                  "kind text not null", "link text not null", "builder text not null",
                  "tags text[] not null", "name text not null", "added text not null",
                  "seen_at timestamptz not null"):
        assert piece in SCHEMA.split("base_library")[1][:600]
    assert "create index if not exists base_library_pick_idx on base_library (village, hall, kind)" in SCHEMA


def test_library_put_writes_the_file_and_forgets_what_the_source_dropped(tmp_path):
    store = store_with(tmp_path)
    rows = base_library.parse([ONE, {"id": "c", "name": "Notte", "town_hall": 10,
                                     "type": "Farm", "link": BUILDER, "builder": "Gino",
                                     "tags": ["fwa"], "added": "2026-09-02"}])
    assert asyncio.run(store.library_put(rows)) == 2
    log = store.pool.conn.log
    assert log[0] == "begin" and log[-1] == "commit"
    upsert, cleanup = log[1], log[2]
    assert upsert[0].startswith("insert into base_library(")
    assert "on conflict (id) do update" in upsert[0]
    assert [values[0] for values in upsert[1]] == ["a", "c"]
    assert upsert[1][0] == ("a", 16, "home", "war", GOOD, "Pino", ["anti-air"], "Anti 3",
                            "2026-09-01")
    assert cleanup[0].startswith("delete from base_library where not")
    assert cleanup[1] == (["a", "c"],)


def test_library_put_keeps_the_copy_when_there_is_nothing_to_write(tmp_path):
    store = store_with(tmp_path)
    assert asyncio.run(store.library_put([])) == 0
    assert store.pool.conn.log == []


def test_library_rows_filters_by_hall_village_and_kind(tmp_path):
    row = {"id": "a", "name": "Anti 3", "hall": 16, "village": "home", "kind": "war",
           "link": GOOD, "builder": "Pino", "tags": ["anti-air"], "added": "2026-09-01"}
    store = store_with(tmp_path, rows=[row])
    assert asyncio.run(store.library_rows(hall=16, village="home", kind="war")) == [row]
    sql, args = store.pool.fetched[0]
    assert sql.startswith("select id, hall, village, kind, link, builder, tags, name, added")
    assert args == (16, "home", "war", WAR_HISTORY_KEEP)
    asyncio.run(store.library_rows())
    assert store.pool.fetched[1][1] == (None, None, None, WAR_HISTORY_KEEP)
