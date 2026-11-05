import asyncio
from datetime import datetime, timezone

from clashbot import cwl_store, db, retention
from clashbot.crypto import Vault
from clashbot.db import Store

ENDED = datetime(2026, 9, 3, 10, tzinfo=timezone.utc)


def flat(sql):
    return " ".join(sql.split())


class FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, log, row_id=1, pruned=()):
        self.log = log
        self.row_id = row_id
        self.pruned = list(pruned)

    def transaction(self):
        return FakeTx()

    async def fetchval(self, sql, *args):
        self.log.append((flat(sql), args))
        return self.row_id

    async def fetch(self, sql, *args):
        self.log.append((flat(sql), args))
        return [{"id": value} for value in self.pruned]

    async def execute(self, sql, *args):
        self.log.append((flat(sql), args))
        return "DELETE 0"


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, conn, rows=()):
        self.conn = conn
        self.rows = list(rows)

    def acquire(self):
        return FakeAcquire(self.conn)

    async def fetch(self, sql, *args):
        self.conn.log.append((flat(sql), args))
        return self.rows


class FakeClansPool(FakePool):
    def __init__(self, conn, existing):
        super().__init__(conn)
        self.existing = existing

    async def fetchrow(self, sql, *args):
        self.conn.log.append((flat(sql), args))
        return self.existing if "select alias, tag_index" in flat(sql) else None


def store_with(tmp_path, conn, rows=()):
    store = Store(Vault(tmp_path))
    store.pool = FakePool(conn, rows)
    return store


def relink(tmp_path, conn, same_tag):
    store = Store(Vault(tmp_path))
    index = store.vault.blind("tag", "#C9")
    store.pool = FakeClansPool(conn, {"alias": "clan-1", "tag_index": index if same_tag else "altro"})
    asyncio.run(store.add_clan(101, "#C9", "Nuovo", bot_alias="bot-1"))
    return [sql for sql, _ in conn.log if sql.startswith("delete from")]


def test_lo_schema_e_idempotente_ed_e_montato_nel_database():
    assert db.SCHEMA.count("create table if not exists cwl_seasons") == 1
    tabella = db.SCHEMA.split("create table if not exists cwl_seasons (")[1].split(");")[0]
    assert "references clans(alias) on delete cascade" in tabella
    assert "unique (clan_alias, season_index)" in tabella
    assert "create index if not exists cwl_seasons_clan_idx on cwl_seasons (clan_alias, ended_at desc)" in db.SCHEMA
    assert db.SCHEMA.index("create table if not exists clans (") < db.SCHEMA.index("create table if not exists cwl_seasons")
    assert not hasattr(cwl_store, "SCHEMA") and not hasattr(db, "EXTRA_SCHEMA")


def test_salva_la_stagione_cifrata_e_pota_oltre_il_tetto(tmp_path):
    log = []
    store = store_with(tmp_path, FakeConn(log, row_id=7, pruned=[3]))
    record = {"season": "2026-09", "league": "Crystal League I", "rank": 1}
    assert asyncio.run(cwl_store.save_season(store, "clan-1", "2026-09", ENDED, record)) is True
    insert, prune = log[0], log[1]
    assert insert[0].startswith("insert into cwl_seasons")
    assert "on conflict (clan_alias, season_index) do update" in insert[0]
    index = insert[1][1]
    assert index == store.vault.blind("cwl", "clan-1:2026-09")
    assert "2026-09" not in index and "clan-1" not in index
    assert store.vault.decrypt_json(insert[1][4], f"cwl:clan-1:{index}") == record
    assert prune[1] == ("clan-1", retention.CWL_SEASONS_KEEP)


def test_la_stagione_potata_subito_non_conta(tmp_path):
    store = store_with(tmp_path, FakeConn([], row_id=7, pruned=[7]))
    assert asyncio.run(cwl_store.save_season(store, "clan-1", "2026-09", ENDED, {})) is False


def test_rilegge_le_stagioni_piu_recenti_prima(tmp_path):
    log = []
    store = store_with(tmp_path, FakeConn(log))
    index = cwl_store.index_for(store.vault, "clan-1", "2026-09")
    store.pool.rows = [{"season_index": index,
                        "data": store.vault.encrypt_json({"season": "2026-09"}, f"cwl:clan-1:{index}")}]
    assert asyncio.run(cwl_store.seasons(store, "clan-1", 5)) == [{"season": "2026-09"}]
    assert "order by ended_at desc" in log[-1][0] and log[-1][1] == ("clan-1", 5)


KEPT_STATE = "delete from clan_state where clan_alias=$1 and not (kind = any($2::text[]))"


def test_ricollegare_un_altro_clan_porta_via_anche_le_stagioni(tmp_path):
    deletes = relink(tmp_path, FakeConn([]), same_tag=False)
    assert KEPT_STATE in deletes
    assert "delete from war_history where clan_alias=$1" in deletes
    assert "delete from cwl_seasons where clan_alias=$1" in deletes
    assert "delete from clan_state where clan_alias=$1 and kind = any($2::text[])" in deletes
    assert "delete from leader_log where clan_alias=$1" in deletes


def test_stesso_clan_non_perde_lo_storico(tmp_path):
    deletes = relink(tmp_path, FakeConn([]), same_tag=True)
    assert deletes == [KEPT_STATE]


def test_i_compleanni_restano_finche_non_cambia_il_tag(tmp_path):
    conn = FakeConn([])
    relink(tmp_path, conn, same_tag=True)
    wipe = "delete from clan_state where clan_alias=$1 and kind = any($2::text[])"
    assert [args for sql, args in conn.log if sql == wipe] == []
    conn = FakeConn([])
    relink(tmp_path, conn, same_tag=False)
    assert [args for sql, args in conn.log if sql == wipe] == [("clan-1", ["notes", "roster", "discord"])]


def test_ricollegare_lo_stesso_clan_conserva_impostazioni_e_note(tmp_path):
    conn = FakeConn([])
    relink(tmp_path, conn, same_tag=True)
    kept = [args for sql, args in conn.log if sql == KEPT_STATE]
    assert kept == [("clan-1", list(db.KEEP_STATE))]
    assert db.KEEP_STATE == ("settings", "notes", "roster", "discord")
