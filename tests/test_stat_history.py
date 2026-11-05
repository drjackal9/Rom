import asyncio
from datetime import datetime, timezone
from inspect import signature

from clashbot import retention
from clashbot.crypto import Vault
from clashbot.db import SCHEMA, Store
from test_retention import flat, store_with

ENDED = datetime(2026, 9, 14, 7, tzinfo=timezone.utc)


def test_il_confine_col_blocco_classifiche_resta_scritto_nel_codice():
    schema = SCHEMA
    assert schema.count("create table if not exists stat_history") == 1
    assert schema.count("create index if not exists stat_history_clan_idx") == 1
    table = schema.split("create table if not exists stat_history (")[1].split(");")[0]
    for colonna in ("period", "made_at"):
        assert colonna not in table
    assert list(signature(Store.add_stat).parameters) == [
        "self", "alias", "kind", "stat_key", "ended_at", "obj"]
    assert list(signature(Store.recent_stats).parameters) == ["self", "alias", "kind", "limit"]
    assert retention.STAT_HISTORY_KEEP == retention.WAR_HISTORY_KEEP == 100


def test_schema_crea_stat_history_idempotente():
    assert "create table if not exists stat_history (" in SCHEMA
    for piece in (
        "clan_alias text not null references clans(alias) on delete cascade",
        "kind text not null",
        "stat_index text not null",
        "ended_at timestamptz not null",
        "key_id text not null",
        "data bytea not null",
        "unique (clan_alias, kind, stat_index)",
    ):
        assert piece in SCHEMA
    assert "create index if not exists stat_history_clan_idx on stat_history (clan_alias, kind, ended_at desc)" in SCHEMA


def test_add_stat_pota_per_clan_e_tipo(tmp_path):
    store = store_with(tmp_path, statuses=[12, [{"id": 5}]])
    assert asyncio.run(store.add_stat("clan-1", "games", "2026-09", ENDED, {"total": 4200})) is True
    log = store.pool.log
    assert log[0] == "begin" and log[-1] == "commit"
    insert, prune = log[1], log[2]
    assert insert[0].startswith("insert into stat_history") and insert[0].endswith("returning id")
    assert insert[1][0] == "clan-1" and insert[1][1] == "games" and insert[1][3] == ENDED
    assert prune == (flat(retention.PRUNE_CLAN_STATS_SQL), ("clan-1", "games", 100))


def test_add_stat_potata_subito_non_conta(tmp_path):
    store = store_with(tmp_path, statuses=[12, [{"id": 12}]])
    assert asyncio.run(store.add_stat("clan-1", "capital", "20260911T070000.000Z", ENDED, {"loot": 1})) is False


def test_add_stat_duplicata_non_pota(tmp_path):
    store = store_with(tmp_path, statuses=[None])
    assert asyncio.run(store.add_stat("clan-1", "games", "2026-09", ENDED, {"total": 1})) is False
    assert [entry for entry in store.pool.log if isinstance(entry, tuple)][1:] == []


def test_chiave_naturale_non_finisce_in_chiaro(tmp_path):
    store = store_with(tmp_path, statuses=[12, []])
    asyncio.run(store.add_stat("clan-1", "games", "2026-09", ENDED, {"total": 1}))
    insert = store.pool.log[1]
    assert "2026-09" not in insert[1]
    assert insert[1][2] == Vault(tmp_path).blind("stat", "clan-1:games:2026-09")


def test_recent_stats_decifra_in_ordine(tmp_path):
    vault = Vault(tmp_path)
    store = Store(vault)
    index = vault.blind("stat", "clan-1:games:2026-09")
    rows = [{"stat_index": index, "data": vault.encrypt_json({"total": 4200}, f"stat:clan-1:{index}")}]

    class Pool:
        def __init__(self):
            self.seen = None

        async def fetch(self, sql, *args):
            self.seen = (flat(sql), args)
            return rows

    store.pool = Pool()
    assert asyncio.run(store.recent_stats("clan-1", "games", 12)) == [{"total": 4200}]
    assert store.pool.seen[0].startswith("select stat_index, data from stat_history where clan_alias=$1 and kind=$2")
    assert "order by ended_at desc limit $3" in store.pool.seen[0]
    assert store.pool.seen[1] == ("clan-1", "games", 12)


def test_cambio_tag_dimentica_anche_le_statistiche(tmp_path):
    store = store_with(tmp_path,
                       statuses=["UPDATE 1", "DELETE 4", "DELETE 9", "DELETE 2", "DELETE 3",
                                 "DELETE 6", "DELETE 1", "DELETE 5"])

    async def fetchrow(sql, *args):
        return {"alias": "clan-1", "tag_index": "altro"}

    async def clan_by_chat(chat_id, bot_alias=None):
        return "clan"

    store.pool.fetchrow = fetchrow
    store.clan_by_chat = clan_by_chat
    assert asyncio.run(store.add_clan(-100, "#AAA", "Clan", bot_alias="bot-1")) == "clan"
    statements = [entry[0] for entry in store.pool.log if isinstance(entry, tuple)]
    assert "delete from war_history where clan_alias=$1" in statements
    assert "delete from cwl_seasons where clan_alias=$1" in statements
    assert "delete from stat_history where clan_alias=$1" in statements
    assert "delete from member_history where clan_alias=$1" in statements


def test_stesso_tag_non_tocca_le_statistiche(tmp_path):
    store = store_with(tmp_path, statuses=["UPDATE 1", "DELETE 4"])

    async def fetchrow(sql, *args):
        return {"alias": "clan-1", "tag_index": store.vault.blind("tag", "#AAA")}

    async def clan_by_chat(chat_id, bot_alias=None):
        return "clan"

    store.pool.fetchrow = fetchrow
    store.clan_by_chat = clan_by_chat
    asyncio.run(store.add_clan(-100, "#AAA", "Clan", bot_alias="bot-1"))
    statements = [entry[0] for entry in store.pool.log if isinstance(entry, tuple)]
    assert not [s for s in statements if "stat_history" in s]


def test_ritenzione_tiene_le_100_piu_recenti_per_clan_e_tipo():
    for sql in (retention.COUNT_SQL["statistiche_oltre_tetto"], retention.DELETE_SQL["statistiche_oltre_tetto"]):
        sql = flat(sql)
        assert "from stat_history" in sql
        assert "partition by clan_alias, kind order by ended_at desc" in sql
        assert "> 100" in sql
    prune = flat(retention.PRUNE_CLAN_STATS_SQL)
    assert prune.startswith("delete from stat_history where clan_alias = $1 and kind = $2")
    assert "offset $3" in prune and prune.endswith("returning id")
