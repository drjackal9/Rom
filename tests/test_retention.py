import asyncio
import re
from datetime import datetime, timezone

import pytest

from clashbot import retention
from clashbot import __main__ as cli
from clashbot.__main__ import parse_retention_args, run_retention_command
from clashbot.crypto import Vault
from clashbot.db import Store

NAMES = ("guerre_oltre_tetto", "basi_oltre_tetto", "ex_membri_oltre_tetto", "registro_oltre_tetto",
         "cwl_oltre_tetto", "clan_inattivi", "kv_scaduti", "rete_vecchia",
         "statistiche_oltre_tetto", "tornei_oltre_tetto", "intenti_appesi")


def all_sql():
    return [
        *retention.COUNT_SQL.values(),
        *retention.DELETE_SQL.values(),
        retention.PRUNE_CLAN_BASES_SQL,
        retention.PRUNE_CLAN_WARS_SQL,
        retention.PRUNE_CWL_SEASONS_SQL,
        retention.PRUNE_CLAN_STATS_SQL,
        retention.PRUNE_CLAN_MEMBERS_SQL,
        retention.PRUNE_CLAN_LOG_SQL,
    ]


def flat(sql):
    return " ".join(sql.split())


def test_costanti():
    assert retention.WAR_HISTORY_KEEP == 100
    assert retention.INACTIVE_CLAN_DAYS == 90
    assert retention.STAT_HISTORY_KEEP == 100


def test_count_e_delete_hanno_gli_stessi_nomi():
    assert tuple(retention.COUNT_SQL) == NAMES
    assert tuple(retention.DELETE_SQL) == NAMES
    for name in NAMES:
        assert flat(retention.COUNT_SQL[name]).startswith("select count(*)")
        assert flat(retention.DELETE_SQL[name]).startswith("delete from")


def test_clan_inattivi_solo_disattivati_da_90_giorni():
    for sql in (retention.COUNT_SQL["clan_inattivi"], retention.DELETE_SQL["clan_inattivi"]):
        sql = flat(sql)
        assert "from clans" in sql
        assert "active = false" in sql
        assert "coalesce(last_seen, created_at) < now() - interval '90 days'" in sql
    assert flat(retention.DELETE_SQL["clan_inattivi"]).startswith("delete from clans where active = false and ")


def test_kv_scaduti_solo_con_scadenza_passata():
    for sql in (retention.COUNT_SQL["kv_scaduti"], retention.DELETE_SQL["kv_scaduti"]):
        sql = flat(sql)
        assert "from kv" in sql
        assert "expires_at is not null and expires_at <= now()" in sql


def test_guerre_oltre_tetto_tengono_le_100_piu_recenti_per_clan():
    for sql in (retention.COUNT_SQL["guerre_oltre_tetto"], retention.DELETE_SQL["guerre_oltre_tetto"]):
        sql = flat(sql)
        assert "from war_history" in sql
        assert "partition by clan_alias order by ended_at desc" in sql
        assert "> 100" in sql
    prune = flat(retention.PRUNE_CLAN_WARS_SQL)
    assert prune.startswith("delete from war_history where clan_alias = $1")
    assert "order by ended_at desc" in prune and "offset $2" in prune


def test_le_tabelle_web_si_potano_da_sole():
    assert "interval '1 hour'" in flat(retention.DELETE_SQL["intenti_appesi"])
    assert "proposte_vecchie" not in retention.DELETE_SQL
    assert "proposte_vecchie" not in retention.COUNT_SQL
    for sql in list(retention.DELETE_SQL.values()) + list(retention.COUNT_SQL.values()):
        assert "web_strings" not in flat(sql)
    assert not any("web_listings" in flat(sql) for sql in retention.DELETE_SQL.values())


def test_nessuna_istruzione_nomina_i_bot():
    for sql in all_sql():
        assert not re.search(r"\bbots\b", sql)
        assert "bot_alias" not in sql
        assert not re.search(r"\b(drop|truncate|update|alter)\b", sql, re.I)


def test_summary_in_una_riga():
    counts = {"clan_inattivi": 1, "kv_scaduti": 20, "guerre_oltre_tetto": 0}
    assert retention.summary(counts) == "clan_inattivi=1 kv_scaduti=20 guerre_oltre_tetto=0"


def test_parse_retention_args():
    assert parse_retention_args([]) is False
    assert parse_retention_args(["--dry-run"]) is True


def test_main_rifiuta_argomenti_sbagliati_prima_di_aprire_il_db(monkeypatch):
    def vietato(*args, **kwargs):
        raise AssertionError("database aperto")

    monkeypatch.setattr(cli, "with_store", vietato)
    with pytest.raises(SystemExit, match="retention"):
        cli.main(["retention", "--yes"])


def test_parse_retention_args_rifiuta_il_resto():
    for argv in (["--dry"], ["--yes"], ["--dry-run", "--dry-run", "x"], ["dry-run"], ["--dry-run=1"]):
        with pytest.raises(SystemExit):
            parse_retention_args(argv)


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.log.append("begin")

    async def __aexit__(self, kind, exc, tb):
        self.conn.log.append("rollback" if kind else "commit")
        return False


class FakeConn:
    def __init__(self, log, statuses):
        self.log = log
        self.statuses = statuses

    def transaction(self):
        return FakeTransaction(self)

    def answer(self, method, sql, args):
        self.log.append((flat(sql), args))
        status = self.statuses.pop(0)
        if isinstance(status, dict):
            status = status[method]
        if isinstance(status, Exception):
            raise status
        return status

    async def execute(self, sql, *args):
        return self.answer("execute", sql, args)

    async def fetchval(self, sql, *args):
        return self.answer("fetchval", sql, args)

    async def fetch(self, sql, *args):
        return self.answer("fetch", sql, args)


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, kind, exc, tb):
        return False


class FakePool:
    def __init__(self, statuses=(), values=()):
        self.log = []
        self.conn = FakeConn(self.log, list(statuses))
        self.values = list(values)

    def acquire(self):
        return FakeAcquire(self.conn)

    async def fetchval(self, sql, *args):
        self.log.append(("fetchval", flat(sql), args))
        return self.values.pop(0)

    async def fetch(self, sql, *args):
        self.log.append(("fetch", flat(sql), args))
        return self.values.pop(0)

    async def execute(self, sql, *args):
        raise AssertionError("fuori transazione")


def store_with(tmp_path, **kw):
    store = Store(Vault(tmp_path))
    store.pool = FakePool(**kw)
    return store


def test_retention_counts_conta_senza_cancellare(tmp_path):
    store = store_with(tmp_path, values=[7, 8, 6, 3, 4, 2, 5, 6, 3, 1, 2])
    assert asyncio.run(store.retention_counts()) == {
        "guerre_oltre_tetto": 7,
        "basi_oltre_tetto": 8,
        "ex_membri_oltre_tetto": 6,
        "registro_oltre_tetto": 3,
        "cwl_oltre_tetto": 4,
        "clan_inattivi": 2,
        "kv_scaduti": 5,
        "rete_vecchia": 6,
        "statistiche_oltre_tetto": 3,
        "tornei_oltre_tetto": 1,
        "intenti_appesi": 2,
    }
    assert [entry[1] for entry in store.pool.log] == [flat(retention.COUNT_SQL[n]) for n in NAMES]
    assert all(not entry[1].startswith("delete") for entry in store.pool.log)


def test_run_retention_in_una_transazione(tmp_path):
    store = store_with(tmp_path,
                       statuses=["DELETE 340", "DELETE 5", "DELETE 12", "DELETE 7", "DELETE 9",
                                 "DELETE 1", "DELETE 0", "DELETE 2", "DELETE 4", "DELETE 5",
                                 "DELETE 6"])
    assert asyncio.run(store.run_retention()) == {
        "guerre_oltre_tetto": 340,
        "basi_oltre_tetto": 5,
        "ex_membri_oltre_tetto": 12,
        "registro_oltre_tetto": 7,
        "cwl_oltre_tetto": 9,
        "clan_inattivi": 1,
        "kv_scaduti": 0,
        "rete_vecchia": 2,
        "statistiche_oltre_tetto": 4,
        "tornei_oltre_tetto": 5,
        "intenti_appesi": 6,
    }
    log = store.pool.log
    assert log[0] == "begin" and log[-1] == "commit"
    assert [entry[0] for entry in log[1:-1]] == [flat(retention.DELETE_SQL[n]) for n in NAMES]


def test_run_retention_annulla_tutto_se_un_delete_fallisce(tmp_path):
    store = store_with(tmp_path, statuses=["DELETE 3", RuntimeError("boom")])
    with pytest.raises(RuntimeError):
        asyncio.run(store.run_retention())
    assert store.pool.log[-1] == "rollback"


def test_add_war_pota_lo_stesso_clan_a_100(tmp_path):
    store = store_with(tmp_path, statuses=[41, [{"id": 3}]])
    ended = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)
    assert asyncio.run(store.add_war("clan-1", "war-key", ended, {"stars": 3})) is True
    log = store.pool.log
    assert log[0] == "begin" and log[-1] == "commit"
    insert, prune = log[1], log[2]
    assert insert[0].startswith("insert into war_history") and insert[0].endswith("returning id")
    assert insert[1][0] == "clan-1" and insert[1][2] == ended
    assert prune == (flat(retention.PRUNE_CLAN_WARS_SQL), ("clan-1", 100))
    assert flat(retention.PRUNE_CLAN_WARS_SQL).endswith("returning id")


def test_add_war_senza_potatura_conta(tmp_path):
    store = store_with(tmp_path, statuses=[41, []])
    ended = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)
    assert asyncio.run(store.add_war("clan-1", "war-key", ended, {"stars": 3})) is True
    assert store.pool.log[-1] == "commit"


def test_add_war_fuori_ordine_potata_subito_non_conta(tmp_path):
    inserted = {"execute": "INSERT 0 1", "fetchval": 41}
    pruned_itself = {"execute": "DELETE 1", "fetch": [{"id": 41}]}
    store = store_with(tmp_path, statuses=[inserted, pruned_itself])
    ended = datetime(2025, 1, 1, 10, tzinfo=timezone.utc)
    assert asyncio.run(store.add_war("clan-1", "war-key", ended, {"stars": 3})) is False
    log = store.pool.log
    assert log[0] == "begin" and log[-1] == "commit" and len(log) == 4
    assert log[2] == (flat(retention.PRUNE_CLAN_WARS_SQL), ("clan-1", 100))


def test_add_war_duplicata_non_pota(tmp_path):
    store = store_with(tmp_path, statuses=[None])
    ended = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)
    assert asyncio.run(store.add_war("clan-1", "war-key", ended, {"stars": 3})) is False
    assert [entry for entry in store.pool.log if isinstance(entry, tuple)][1:] == []


class FakeRetentionStore:
    def __init__(self):
        self.calls = []

    async def retention_counts(self):
        self.calls.append("counts")
        return {"guerre_oltre_tetto": 12, "basi_oltre_tetto": 3, "registro_oltre_tetto": 9,
                "clan_inattivi": 0, "kv_scaduti": 4}

    async def run_retention(self):
        self.calls.append("run")
        return {"guerre_oltre_tetto": 12, "basi_oltre_tetto": 3, "registro_oltre_tetto": 9,
                "clan_inattivi": 0, "kv_scaduti": 4}


def test_comando_dry_run_non_cancella(capsys):
    store = FakeRetentionStore()
    asyncio.run(run_retention_command(store, True))
    assert store.calls == ["counts"]
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert ("guerre_oltre_tetto=12 basi_oltre_tetto=3 registro_oltre_tetto=9 "
            "clan_inattivi=0 kv_scaduti=4") in out


def test_comando_esegue_e_stampa_le_righe_cancellate(capsys):
    store = FakeRetentionStore()
    asyncio.run(run_retention_command(store, False))
    assert store.calls == ["run"]
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert ("guerre_oltre_tetto=12 basi_oltre_tetto=3 registro_oltre_tetto=9 "
            "clan_inattivi=0 kv_scaduti=4") in out


def test_main_retention_passa_dal_database_e_rispetta_la_prova(monkeypatch, capsys):
    for argv, expected in ((["retention", "--dry-run"], ["counts"]), (["retention"], ["run"])):
        store = FakeRetentionStore()

        async def fake_with_store(fn, database=None):
            return await fn(store)

        monkeypatch.setattr(cli, "with_store", fake_with_store)
        cli.main(argv)
        assert store.calls == expected, argv
    out = capsys.readouterr().out
    assert out.startswith("prova, nulla cancellato: ") and "\nrighe cancellate: " in out


def test_costante_ex_membri():
    assert retention.MEMBER_HISTORY_KEEP == 100


def test_ex_membri_oltre_tetto_tengono_i_100_piu_recenti_per_clan():
    for sql in (retention.COUNT_SQL["ex_membri_oltre_tetto"], retention.DELETE_SQL["ex_membri_oltre_tetto"]):
        sql = flat(sql)
        assert "from member_history" in sql
        assert "partition by clan_alias order by left_at desc" in sql
        assert "> 100" in sql
    prune = flat(retention.PRUNE_CLAN_MEMBERS_SQL)
    assert prune.startswith("delete from member_history where clan_alias = $1")
    assert "order by left_at desc" in prune and "offset $2" in prune


def test_schema_crea_member_history():
    from clashbot.db import SCHEMA
    assert "create table if not exists member_history (" in SCHEMA
    for piece in ("clan_alias text not null references clans(alias) on delete cascade",
                  "member_index text not null", "left_at timestamptz not null",
                  "unique (clan_alias, member_index)"):
        assert piece in SCHEMA
    assert "create index if not exists member_history_clan_idx on member_history (clan_alias, left_at desc)" in SCHEMA


def test_archive_member_pota_lo_stesso_clan_a_100(tmp_path):
    store = store_with(tmp_path, statuses=["INSERT 0 1", "DELETE 0"])
    left = datetime(2026, 9, 13, 10, tzinfo=timezone.utc)
    asyncio.run(store.archive_member("clan-1", "#P2", {"name": "Luigi"}, left))
    log = store.pool.log
    assert log[0] == "begin" and log[-1] == "commit"
    insert, prune = log[1], log[2]
    assert insert[0].startswith("insert into member_history")
    assert insert[1][0] == "clan-1" and insert[1][2] == left
    assert prune == (flat(retention.PRUNE_CLAN_MEMBERS_SQL), ("clan-1", 100))


def test_cwl_oltre_tetto_tiene_le_100_stagioni_piu_recenti_per_clan():
    assert retention.CWL_SEASONS_KEEP == 100
    for sql in (retention.COUNT_SQL["cwl_oltre_tetto"], retention.DELETE_SQL["cwl_oltre_tetto"]):
        sql = flat(sql)
        assert "from cwl_seasons" in sql
        assert "partition by clan_alias order by ended_at desc" in sql
        assert "> 100" in sql
    prune = flat(retention.PRUNE_CWL_SEASONS_SQL)
    assert prune.startswith("delete from cwl_seasons where clan_alias = $1")
    assert "order by ended_at desc" in prune and "offset $2" in prune


def test_registro_oltre_tetto_tiene_le_100_righe_piu_recenti_per_clan():
    assert retention.LEADER_LOG_KEEP == 100
    for sql in (retention.COUNT_SQL["registro_oltre_tetto"], retention.DELETE_SQL["registro_oltre_tetto"]):
        flattened = flat(sql)
        assert "from leader_log" in flattened
        assert "partition by clan_alias order by at desc, id desc" in flattened
        assert "rn > 100" in flattened
    prune = flat(retention.PRUNE_CLAN_LOG_SQL)
    assert prune.startswith("delete from leader_log where clan_alias = $1")
    assert "order by at desc, id desc" in prune and "offset $2" in prune


def test_add_log_pota_lo_stesso_clan_a_100(tmp_path):
    store = store_with(tmp_path, statuses=["INSERT 0 1", "DELETE 2"])
    at = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
    asyncio.run(store.add_log("clan-1", {"action": "note", "by": 7}, at=at))
    log = store.pool.log
    assert log[0] == "begin" and log[-1] == "commit"
    assert log[1][0].startswith("insert into leader_log")
    assert log[1][1][0] == "clan-1" and log[1][1][1] == at
    assert log[2] == (flat(retention.PRUNE_CLAN_LOG_SQL), ("clan-1", 100))


def test_recent_log_decifra_e_aggiunge_il_momento(tmp_path):
    store = Store(Vault(tmp_path))
    at = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
    blob = store.vault.encrypt_json({"action": "export", "by": 7}, "log:clan-1")
    store.pool = FakePool(values=[[{"at": at, "data": blob}]])
    rows = asyncio.run(store.recent_log("clan-1", 5))
    assert rows == [{"action": "export", "by": 7, "at": at}]
    assert store.pool.log[0][2] == ("clan-1", 5)


def test_il_registro_di_un_clan_non_finisce_in_chiaro(tmp_path):
    store = store_with(tmp_path, statuses=["INSERT 0 1", "DELETE 0"])
    asyncio.run(store.add_log("clan-1", {"action": "note", "detail": "Toad dorme"}))
    written = store.pool.log[1][1]
    assert all(b"Toad" not in bytes(value) for value in written if isinstance(value, (bytes, bytearray)))
    assert "Toad" not in " ".join(str(value) for value in written)
