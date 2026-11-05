import asyncio
import json
import re
from datetime import datetime, timezone

import pytest

from clashbot import db, i18n, manager_alerts, restore_check
from clashbot import __main__ as cli
from clashbot.crypto import Vault

SEGRETO = "tk-finto-42"
FRESH = datetime(2026, 9, 13, 4, 31, tzinfo=timezone.utc)
AT = 1789000000.0


def cifrate(text):
    trovate, dentro = [], None
    for line in text.splitlines():
        line = line.strip()
        apre = re.match(r"create table if not exists (\w+) \($", line)
        if apre:
            dentro = apre.group(1)
            continue
        if line.startswith(")"):
            dentro = None
            continue
        aggiunge = re.match(r"alter table (\w+) add column if not exists (\w+) bytea", line)
        if aggiunge:
            trovate.append((aggiunge.group(1), aggiunge.group(2)))
            continue
        colonna = re.match(r"(\w+) bytea", line)
        if dentro and colonna:
            trovate.append((dentro, colonna.group(1)))
    return trovate


class Pool:
    def __init__(self, tables, orphans=None, fresh=FRESH):
        self.tables = tables
        self.orphans = dict(orphans or {})
        self.fresh = fresh
        self.asked = []

    async def fetch(self, sql, *args):
        self.asked.append(sql)
        if sql == restore_check.PRESENT_SQL:
            return [{"table_name": name} for name in self.tables]
        for table, column, query, _, _ in restore_check.CHECKS:
            if query == sql:
                return [row for row in self.tables[table] if row.get(column) is not None]
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        self.asked.append(sql)
        for name, query in restore_check.ORPHANS_SQL.items():
            if query == sql:
                return self.orphans.get(name, 0)
        if sql == restore_check.FRESH_SQL:
            return self.fresh
        return len(self.tables[sql.removeprefix("select count(*) from ")])


class FakeStore:
    def __init__(self, vault, pool):
        self.vault = vault
        self.pool = pool
        self.kv = {}

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj


def tables(vault):
    return {
        "secrets": [{"alias": "sec-1", "data": vault.encrypt(SEGRETO, "secret:sec-1")}],
        "clans": [{"alias": "clan-1",
                   "identity": vault.encrypt_json({"chat_id": -100, "tag": "#C1"}, "clan:clan-1")}],
        "clan_state": [{"clan_alias": "clan-1", "kind": "settings",
                        "data": vault.encrypt_json({"lang": "it"}, "state:clan-1:settings")}],
        "war_history": [{"clan_alias": "clan-1", "war_index": "w1",
                         "data": vault.encrypt_json({"stars": 3}, "war:clan-1:w1")}],
        "links": [{"alias": "link-1",
                   "identity": vault.encrypt_json({"user_id": 9, "tag": "#P1"}, "link:link-1")}],
        "families": [{"alias": "fam-1", "identity": vault.encrypt_json({"owner_id": 42}, "family:fam-1")}],
        "family_clans": [{"family_alias": "fam-1", "clan_alias": "clan-1"}],
        "kv": [{"k": "platform:keys", "data": vault.encrypt_json({"sig": "ok:3"}, "kv:platform:keys")}],
        "bots": [{"alias": "bot-1",
                  "identity": vault.encrypt_json({"owner_id": 42, "bot_id": 7}, "bot:bot-1")}],
        "stat_history": [{"clan_alias": "clan-1", "stat_index": "s1",
                          "data": vault.encrypt_json({"raids": 2}, "stat:clan-1:s1")}],
        "member_history": [{"clan_alias": "clan-1", "member_index": "m1",
                            "data": vault.encrypt_json({"name": "Mario"}, "member:clan-1:m1")}],
        "network_clans": [{"clan_alias": "clan-1",
                           "data": vault.encrypt_json({"visible": True}, "network:clan-1"),
                           "recruit_data": vault.encrypt_json({"th": 15}, "recruit:clan-1")}],
        "leader_log": [{"clan_alias": "clan-1",
                        "data": vault.encrypt_json({"action": "settings"}, "log:clan-1")}],
        "tournaments": [{"alias": "tour-1", "data": vault.encrypt_json({"name": "Coppa"}, "tour:tour-1")}],
        "base_layouts": [{"alias": "base-1", "data": vault.encrypt_json({"hall": 15}, "base:base-1")}],
        "cwl_seasons": [{"clan_alias": "clan-1", "season_index": "c1",
                         "data": vault.encrypt_json({"stars": 40}, "cwl:clan-1:c1")}],
        "web_notes": [{"name": "services", "data": vault.encrypt_json({"v": 1}, "web:services")}],
        "web_pages": [{"clan_alias": "clan-1", "kind": "public",
                       "data": vault.encrypt_json({"name": "Futuro"}, "page:clan-1:public")}],
        "web_intents": [{"id": 1, "data": vault.encrypt_json({"pos": 2}, "intent:1")}],
        "base_library": [{"id": "th16-anti-3", "hall": 16, "village": "home", "kind": "war"}],
        "base_videos": [{"video_id": "vid-1", "scope": "platform", "channel_id": "UCplat"}],
        "site_days": [{"day": "2026-09-27", "requests": 10}],
        "incidents": [{"id": 1, "data": vault.encrypt_json({"kind": "outage"},
                                                           db.INCIDENT_AAD)}],
    }


def guasta(raw):
    data = bytes(raw)
    return data[:-1] + bytes([data[-1] ^ 0xFF])


def look(tmp_path, **kw):
    vault = Vault(tmp_path)
    store = FakeStore(vault, Pool(kw.pop("tables", None) or tables(vault), **kw))
    return store, asyncio.run(restore_check.inspect(store))


def test_il_database_di_produzione_non_e_un_bersaglio():
    assert restore_check.PRODUCTION == db.DATABASE == "clashbot"


def test_l_evento_della_prova_e_dichiarato_come_gli_altri():
    from clashbot import events_registry

    assert restore_check.EVENTS == ("platform.restore",)
    assert events_registry.EVENTS["platform.restore"]["pack"] == restore_check.PACK == "platform"


def test_le_tabelle_controllate_sono_quelle_dello_schema(tmp_path):
    attese = tuple(re.findall(r"create table if not exists (\w+)", db.SCHEMA))
    assert restore_check.TABLES == attese and len(attese) == 23
    assert set(tables(Vault(tmp_path))) == set(attese)


def test_ogni_colonna_cifrata_dello_schema_ha_il_suo_controllo():
    coperte = {(name, column) for name, column, _, _, _ in restore_check.CHECKS}
    assert coperte == set(cifrate(db.SCHEMA))
    assert ("network_clans", "data") in coperte and ("network_clans", "recruit_data") in coperte


def test_un_backup_sano_si_legge_tutto(tmp_path):
    _, report = look(tmp_path)
    assert report["missing"] == [] and report["unreadable"] == {}
    assert report["tables"] == {name: 1 for name in restore_check.TABLES}
    assert report["checked"] == len(restore_check.CHECKS) == 20
    assert sum(report["orphans"].values()) == 0
    assert report["fresh"] == FRESH
    assert report["ok"] is True
    assert restore_check.rows(report) == 23


def test_il_riassunto_e_una_riga_e_non_contiene_valori(tmp_path):
    _, report = look(tmp_path)
    riga = restore_check.summary(report)
    assert riga == ("tabelle=23/23 righe=23 decifrate=20 illeggibili=0 orfani=0"
                    " ultimo_giro=2026-09-13 04:31 esito=ok")
    assert "\n" not in riga and SEGRETO not in riga


def test_una_riga_illeggibile_boccia_il_backup(tmp_path):
    vault = Vault(tmp_path)
    rotte = tables(vault)
    rotte["war_history"][0]["data"] = guasta(rotte["war_history"][0]["data"])
    _, report = look(tmp_path, tables=rotte)
    assert report["unreadable"] == {"war_history": 1}
    assert report["ok"] is False
    assert "illeggibili=1" in restore_check.summary(report)
    assert restore_check.signature(report) == "ko:war_history"


@pytest.mark.parametrize("table,column", [("cwl_seasons", "data"), ("base_layouts", "data"),
                                          ("leader_log", "data"), ("stat_history", "data"),
                                          ("member_history", "data"), ("tournaments", "data"),
                                          ("network_clans", "recruit_data"), ("web_notes", "data"),
                                          ("web_pages", "data"), ("web_intents", "data")])
def test_una_riga_rotta_nelle_tabelle_aggiunte_non_passa_piu(tmp_path, table, column):
    vault = Vault(tmp_path)
    rotte = tables(vault)
    rotte[table][0][column] = guasta(rotte[table][0][column])
    _, report = look(tmp_path, tables=rotte)
    assert report["unreadable"] == {table: 1}
    assert report["ok"] is False and restore_check.signature(report) == f"ko:{table}"


def test_le_due_colonne_di_network_clans_si_sommano(tmp_path):
    vault = Vault(tmp_path)
    rotte = tables(vault)
    for column in ("data", "recruit_data"):
        rotte["network_clans"][0][column] = guasta(rotte["network_clans"][0][column])
    _, report = look(tmp_path, tables=rotte)
    assert report["unreadable"] == {"network_clans": 2}
    assert "illeggibili=2 " in restore_check.summary(report)


def test_una_scheda_di_reclutamento_vuota_non_viene_contata(tmp_path):
    vault = Vault(tmp_path)
    senza = tables(vault)
    senza["network_clans"][0]["recruit_data"] = None
    _, report = look(tmp_path, tables=senza)
    assert report["checked"] == len(restore_check.CHECKS) - 1
    assert report["ok"] is True


def test_una_tabella_mancante_boccia_il_backup_senza_ricrearla(tmp_path):
    vault = Vault(tmp_path)
    parziale = tables(vault)
    del parziale["war_history"]
    store, report = look(tmp_path, tables=parziale)
    assert report["missing"] == ["war_history"]
    assert report["ok"] is False and report["orphans"] == {}
    assert not [sql for sql in store.pool.asked if "create" in sql.lower()]


def test_un_riferimento_orfano_boccia_il_backup(tmp_path):
    _, report = look(tmp_path, orphans={"clan_senza_bot": 2})
    assert report["orphans"]["clan_senza_bot"] == 2
    assert report["ok"] is False
    assert "orfani=2" in restore_check.summary(report)
    assert restore_check.signature(report) == "ko:clan_senza_bot"


def test_un_database_vuoto_non_e_un_backup_buono(tmp_path):
    vuote = {name: [] for name in restore_check.TABLES}
    _, report = look(tmp_path, tables=vuote, fresh=None)
    assert report["ok"] is False
    assert "ultimo_giro=mai" in restore_check.summary(report)
    assert restore_check.verdict({**report, "tables": {**report["tables"], "secrets": 1, "bots": 1}}) is True


def test_l_esito_finisce_nella_memoria_della_piattaforma(tmp_path):
    store, report = look(tmp_path)
    assert asyncio.run(restore_check.record(store, report, AT)) is True
    stored = store.kv[manager_alerts.key_of("restore")]
    assert stored["sig"] == "ok" and stored["sent"] is True
    assert stored["history"] == [{"ok": True, "righe": 23, "decifrate": 20, "illeggibili": 0,
                                  "orfani": 0, "at": AT}]
    assert SEGRETO not in json.dumps(stored, default=str)


def test_la_cassaforte_in_sola_lettura_non_crea_una_chiave(tmp_path):
    with pytest.raises(OSError):
        Vault(tmp_path, create=False)
    assert list(tmp_path.iterdir()) == []
    vault = Vault(tmp_path)
    assert Vault(tmp_path, create=False).key_id == vault.key_id


def test_parse_restore_args():
    assert cli.parse_restore_args(["--database", "clashbot_prova"]) == "clashbot_prova"
    assert cli.parse_restore_args(["--database=clashbot_prova"]) == "clashbot_prova"
    for argv in ([], ["--database"], ["--database="], ["clashbot_prova"], ["--db", "x"],
                 ["--database", "clashbot_prova", "extra"]):
        with pytest.raises(SystemExit):
            cli.parse_restore_args(argv)
    with pytest.raises(SystemExit, match="produzione"):
        cli.parse_restore_args(["--database", "clashbot"])


def test_main_rifiuta_il_database_di_produzione_prima_di_aprire_qualsiasi_cosa(monkeypatch):
    def vietato(*args, **kwargs):
        raise AssertionError("database aperto")

    monkeypatch.setattr(cli, "Vault", vietato)
    monkeypatch.setattr(cli, "Store", vietato)
    with pytest.raises(SystemExit, match="produzione"):
        cli.main(["restore-check", "--database", "clashbot"])


class CliStore:
    opened = []

    def __init__(self, vault, database=db.DATABASE):
        self.vault = vault
        self.database = database
        self.closed = 0
        self.kv = {}

    async def open(self, schema=True):
        CliStore.opened.append((self.database, schema))

    async def close(self):
        self.closed += 1

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj


def wire(monkeypatch, ok=True):
    CliStore.opened = []
    made = []

    def store(vault, database=db.DATABASE):
        made.append(CliStore(vault, database))
        return made[-1]

    async def inspect(store):
        return {"tables": {"secrets": 1}, "missing": [], "unreadable": {}, "checked": 1,
                "orphans": {}, "fresh": None, "ok": ok}

    monkeypatch.setattr(cli, "Vault", lambda *a, **kw: "cassaforte")
    monkeypatch.setattr(cli, "Store", store)
    monkeypatch.setattr(restore_check, "inspect", inspect)
    return made


def test_il_comando_apre_la_prova_senza_schema_e_scrive_solo_in_produzione(monkeypatch, capsys):
    made = wire(monkeypatch)
    cli.main(["restore-check", "--database", "clashbot_prova"])
    assert CliStore.opened == [("clashbot_prova", False), ("clashbot", True)]
    assert [s.closed for s in made] == [1, 1]
    assert manager_alerts.key_of("restore") in made[1].kv
    assert "esito=ok" in capsys.readouterr().out


def test_un_esito_fallito_esce_con_codice_uno(monkeypatch, capsys):
    wire(monkeypatch, ok=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["restore-check", "--database", "clashbot_prova"])
    assert exc.value.code == 1
    assert "esito=FALLITA" in capsys.readouterr().out


def test_le_chiavi_della_prova_esistono_in_inglese():
    catalogo = json.loads((i18n.LOCALE_DIR / "en.json").read_text(encoding="utf-8"))
    for key in ("console.stats_restore_ok", "console.stats_restore_ko", "console.stats_restore_never"):
        assert key in catalogo, key
