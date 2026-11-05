import asyncio
from datetime import datetime, timezone

from clashbot import events, retention, tournaments
from clashbot.crypto import Vault
from clashbot.db import SCHEMA, Store
from fixtures import war_json

NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
TS = int(NOW.timestamp())


def doc_with(n, fmt="bracket", kind="clash", scope="family"):
    doc = tournaments.empty(kind, scope, "stars", fmt, TS, TS + 86400, TS + 86400 * 8, size=32)
    doc["alias"] = "trn-aaaaaa"
    for i in range(n):
        doc, _ = tournaments.join(doc, "clan", f"clan-{i}", f"Clan {i}")
    return doc


def test_empty_e_ensure_sono_idempotenti():
    doc = tournaments.empty("derby", "family", "both", "table", TS, TS, TS + 10)
    assert tournaments.ensure(doc) == tournaments.ensure(tournaments.ensure(doc))
    assert tournaments.ensure(None)["v"] == tournaments.VERSION
    assert tournaments.ensure({"kind": "boh", "entries": "rotto"})["kind"] == "internal"
    keeps = tournaments.ensure({"alias": "trn-1", "status": "running", "clan_alias": "clan-1",
                                "family_alias": "fam-1"})
    assert (keeps["alias"], keeps["status"], keeps["clan_alias"], keeps["family_alias"]) == (
        "trn-1", "running", "clan-1", "fam-1")
    broken = {"entries": [{"id": "c:1", "type": "clan", "ref": "1", "name": "A"}, "spazzatura",
                          {"id": "c:1", "type": "clan", "ref": "1", "name": "A"}],
              "rounds": [[{"a": "c:1", "b": "ignoto", "winner": "ignoto", "score": "x"}]],
              "scores": {"c:1": "3", "ignoto": 9}}
    fixed = tournaments.ensure(broken)
    assert [e["id"] for e in fixed["entries"]] == ["c:1"]
    assert fixed["rounds"] == [[{"a": "c:1", "b": None, "score": [0, 0], "winner": "c:1", "done": True}]]
    assert fixed["scores"] == {"c:1": 3}


def test_iscrizioni_rifiutano_doppioni_e_oltre_la_capienza():
    doc = tournaments.empty("internal", "clan", "loot", "bracket", TS, TS + 10, TS + 20, size=4)
    for i in range(4):
        doc, result = tournaments.join(doc, "member", f"#P{i}", f"P{i}")
        assert result == "ok"
    assert tournaments.join(doc, "member", "#P0", "P0")[1] == "dup"
    assert tournaments.join(doc, "member", "#P9", "P9")[1] == "full"
    doc, removed = tournaments.leave(doc, tournaments.entry_id("member", "#P0"))
    assert removed and len(doc["entries"]) == 3
    assert tournaments.join(doc, "member", "#P9", "P9", now=TS + 999)[1] == "closed"


def test_esclusi_dalle_classifiche_restano_fuori():
    doc = doc_with(3)
    doc = tournaments.eligible(doc, ["clan-1"])
    assert [e["ref"] for e in doc["entries"]] == ["clan-0", "clan-2"]


def test_semina_deterministica_e_gironi_a_serpente():
    first = tournaments.seed(doc_with(8))
    second = tournaments.seed(doc_with(8))
    assert [e["id"] for e in first["entries"]] == [e["id"] for e in second["entries"]]
    assert sorted(e["seed"] for e in first["entries"]) == list(range(1, 9))
    grouped = tournaments.make_groups(first, 2)
    assert sorted(len(g) for g in grouped["groups"]) == [4, 4]
    assert grouped["groups"][0][0] == first["entries"][0]["id"]
    assert grouped["groups"][1][1] == first["entries"][2]["id"]
    for rotto in (None, 0, -3, "due", True):
        assert len(tournaments.make_groups(doc_with(8), rotto)["groups"]) == 1


def test_tabellone_con_bye_e_avanzamento():
    doc = tournaments.make_bracket(doc_with(3))
    assert len(doc["rounds"]) == 1 and len(doc["rounds"][0]) == 2
    bye = [m for m in doc["rounds"][0] if m["b"] is None]
    assert len(bye) == 1 and bye[0]["done"] and bye[0]["winner"] == bye[0]["a"]
    open_index = next(i for i, m in enumerate(doc["rounds"][0]) if not m["done"])
    match = doc["rounds"][0][open_index]
    doc = tournaments.record_result(doc, 0, open_index, 5, 5, 40, 90)
    assert doc["rounds"][0][open_index]["winner"] == match["b"]
    assert tournaments.next_round(doc) is None
    doc = tournaments.close_round(doc, 0)
    assert len(doc["rounds"]) == 2 and tournaments.next_round(doc) == 1


def test_parita_piena_la_rompe_la_semina():
    doc = tournaments.make_bracket(doc_with(4))
    first, second = doc["rounds"][0][0]["a"], doc["rounds"][0][0]["b"]
    doc = tournaments.record_result(doc, 0, 0, 7, 7, 50, 50)
    seeds = {e["id"]: e["seed"] for e in doc["entries"]}
    assert doc["rounds"][0][0]["winner"] == (first if seeds[first] < seeds[second] else second)


def test_advance_apre_le_iscrizioni_poi_il_primo_turno_poi_la_finale():
    doc = doc_with(4)
    doc, evs = tournaments.advance(doc, TS)
    assert [e["type"] for e in evs] == ["signup"]
    doc, evs = tournaments.advance(doc, TS)
    assert evs == []
    doc, evs = tournaments.advance(doc, TS + 86400)
    assert [e["type"] for e in evs] == ["round"] and len(doc["rounds"]) == 1
    for index in range(len(doc["rounds"][0])):
        doc = tournaments.record_result(doc, 0, index, 3, 1)
    doc = tournaments.close_round(doc, 0)
    doc = tournaments.record_result(doc, 1, 0, 4, 2)
    doc, evs = tournaments.advance(doc, TS + 86400 * 9)
    assert [e["type"] for e in evs] == ["final"] and evs[0]["winner"] == doc["rounds"][1][0]["winner"]
    assert tournaments.advance(doc, TS + 86400 * 10)[1] == []


def test_advance_con_meno_di_due_iscritti_chiude_senza_bloccarsi():
    doc = doc_with(1)
    doc, evs = tournaments.advance(doc, TS + 86400)
    assert [e["type"] for e in evs] == ["empty"]


def test_il_motore_generico_non_tocca_il_derby():
    doc = tournaments.ensure(doc_with(5, fmt="table", kind="derby"))
    for ts in (TS, TS + 86400, TS + 86400 * 9):
        after, evs = tournaments.advance(doc, ts)
        assert evs == []
        assert after == doc
        assert len(after["entries"]) == 5
        assert after["groups"] == [] and after["rounds"] == [] and after["sent"] == []


def test_classifica_dei_clan_usa_i_punti_della_cwl():
    doc = tournaments.make_groups(tournaments.seed(doc_with(4, fmt="groups")), 1)
    ids = [e["id"] for e in doc["entries"]]
    doc = tournaments.apply_clash(doc, [
        {"a": ids[0], "b": ids[1], "stars_a": 9, "destr_a": 100.0, "stars_b": 6, "destr_b": 80.0},
        {"a": ids[2], "b": ids[3], "stars_a": 4, "destr_a": 60.0, "stars_b": 4, "destr_b": 61.0},
    ])
    rows = tournaments.table(doc)
    assert rows[0]["id"] == ids[0] and rows[0]["value"] == 19
    assert doc["scores"][ids[1]] == 6
    assert doc["scores"][ids[3]] == 14 and doc["scores"][ids[2]] == 4


def test_finestra_dei_turni_divide_la_durata():
    doc = tournaments.make_bracket(doc_with(4))
    for index in range(len(doc["rounds"][0])):
        doc = tournaments.record_result(doc, 0, index, 3, 1)
    doc = tournaments.close_round(doc, 0)
    assert len(doc["rounds"]) == 2
    span = (doc["ends"] - doc["starts"]) // 2
    assert tournaments.round_window(doc, 0) == (doc["starts"], doc["starts"] + span)
    assert tournaments.round_window(doc, 1) == (doc["starts"] + span, doc["starts"] + span * 2)


def test_il_numero_dei_turni_si_fissa_alla_partenza():
    assert tournaments.planned_rounds("bracket", 4) == 2
    assert tournaments.planned_rounds("bracket", 32) == 5
    assert tournaments.planned_rounds("groups", 32) == 1
    assert tournaments.planned_rounds("table", 8) == 1
    doc = tournaments.make_bracket(doc_with(4))
    assert doc["rounds_total"] == 2
    assert tournaments.ensure(doc)["rounds_total"] == 2
    assert tournaments.make_groups(doc_with(8), 2)["rounds_total"] == 1


def test_il_turno_dura_quanto_scelto_anche_con_meno_iscritti():
    doc = doc_with(5, fmt="bracket")
    span = (doc["ends"] - doc["starts"]) // doc["rounds_total"]
    assert doc["rounds_total"] == tournaments.planned_rounds("bracket", 32)
    doc, events = tournaments.advance(doc, doc["starts"])
    assert [event["type"] for event in events] == ["round"]
    assert doc["size"] == 4 and doc["rounds_total"] == 2
    assert doc["ends"] == doc["starts"] + span * 2
    assert tournaments.round_window(doc, 0) == (doc["starts"], doc["starts"] + span)
    assert tournaments.round_window(doc, 1) == (doc["starts"] + span, doc["ends"])


def test_la_finestra_del_primo_turno_non_si_mangia_tutto_il_torneo():
    doc = tournaments.make_bracket(doc_with(4))
    span = (doc["ends"] - doc["starts"]) // 2
    first = tournaments.round_window(doc, 0)
    assert first == (doc["starts"], doc["starts"] + span)
    for index in range(len(doc["rounds"][0])):
        doc = tournaments.record_result(doc, 0, index, 3, 1)
    doc = tournaments.close_round(doc, 0)
    second = tournaments.round_window(doc, 1)
    assert second[0] == first[1] and second[1] > second[0]
    assert tournaments.round_window(doc, 0) == first


def test_eventi_prendono_il_pacchetto_dallo_scopo():
    assert tournaments.event("round", "clan") == "challenges.tournament.round"
    assert tournaments.event("round", "family") == "family.tournament.round"
    assert tournaments.event("final", "network") == "family.tournament.final"


def test_la_rete_serve_accesa_dal_capo():
    assert tournaments.network_ready(None) is False
    assert tournaments.network_ready({"alias": "clan-1", "visible": False, "named": True}) is False
    assert tournaments.network_ready({"alias": "clan-1", "visible": True, "named": False}) is True
    assert tournaments.network_ready({"network": {"visible": True}}) is False


def test_log_tiene_le_ultime_cento_voci():
    doc = doc_with(2)
    for i in range(120):
        doc = tournaments.note(doc, "round", index=i)
    assert len(doc["log"]) == retention.WAR_HISTORY_KEEP
    assert doc["log"][-1]["index"] == 119


def test_schema_crea_la_tabella_tornei_in_modo_idempotente():
    assert "create table if not exists tournaments (" in SCHEMA
    for piece in ("alias text primary key", "owner_index text not null", "scope text not null",
                  "kind text not null", "status text not null default 'signup'",
                  "family_alias text references families(alias) on delete cascade",
                  "clan_alias text references clans(alias) on delete cascade",
                  "key_id text not null", "data bytea not null", "ends_at timestamptz"):
        assert piece in SCHEMA
    assert "create index if not exists tournaments_family_idx on tournaments (family_alias, status)" in SCHEMA
    assert "create index if not exists tournaments_clan_idx on tournaments (clan_alias, status)" in SCHEMA
    assert SCHEMA.index("create table if not exists families") < SCHEMA.index("create table if not exists tournaments")


def test_ritenzione_tiene_i_cento_tornei_chiusi_piu_recenti():
    sql = " ".join(retention.DELETE_SQL["tornei_oltre_tetto"].split())
    assert sql.startswith("delete from tournaments where alias in (")
    assert "status = 'done'" in sql and f"rn > {retention.WAR_HISTORY_KEEP}" in sql
    assert "partition by coalesce(family_alias, clan_alias, owner_index)" in sql
    assert " ".join(retention.COUNT_SQL["tornei_oltre_tetto"].split()).startswith("select count(*)")


def test_verbale_di_guerra_porta_il_tag_avversario():
    record = events.war_record(events.war_snapshot(war_json("warEnded", opp_tag="#NEMICO")))
    assert record["opp_tag"] == "#NEMICO"
    assert events.member_stats([record])


class FakePool:
    def __init__(self):
        self.rows = {}
        self.log = []

    async def execute(self, sql, *args):
        self.log.append(" ".join(sql.split()))
        if "insert into tournaments" in self.log[-1]:
            self.rows[args[0]] = {"alias": args[0], "owner_index": args[1], "scope": args[2], "kind": args[3],
                                  "status": args[4], "family_alias": args[5], "clan_alias": args[6],
                                  "key_id": args[7], "data": args[8], "ends_at": args[9]}
        elif "update tournaments" in self.log[-1]:
            row = self.rows[args[0]]
            row["data"], row["key_id"] = args[1], args[2]
            row["status"] = args[3] or row["status"]
        elif "delete from tournaments" in self.log[-1]:
            return "DELETE 1" if self.rows.pop(args[0], None) else "DELETE 0"
        return "OK"

    async def fetchrow(self, sql, *args):
        return self.rows.get(args[0])

    async def fetch(self, sql, *args):
        text = " ".join(sql.split())
        rows = list(self.rows.values())
        if "kind <> 'derby'" in text:
            rows = [r for r in rows if r["kind"] != "derby"]
        if "status <> 'done'" in text:
            rows = [r for r in rows if r["status"] != "done"]
        if args and args[0]:
            rows = [r for r in rows if r["family_alias"] == args[0]]
        return rows


def store_with(tmp_path):
    store = Store(Vault(tmp_path))
    store.pool = FakePool()
    return store


def test_il_torneo_si_salva_cifrato_e_si_rilegge(tmp_path):
    store = store_with(tmp_path)
    doc = doc_with(2)
    alias = asyncio.run(store.create_tournament(doc, 42, family_alias="fam-1"))
    raw = store.pool.rows[alias]["data"]
    assert b"Clan 0" not in bytes(raw)
    back = asyncio.run(store.tournament(alias))
    assert back["alias"] == alias and back["status"] == "signup" and back["family_alias"] == "fam-1"
    assert [e["name"] for e in back["entries"]] == ["Clan 0", "Clan 1"]
    back["scores"][back["entries"][0]["id"]] = 12
    asyncio.run(store.save_tournament(alias, back, "running"))
    again = asyncio.run(store.tournament(alias))
    assert again["status"] == "running" and again["scores"][again["entries"][0]["id"]] == 12
    assert [d["alias"] for d in asyncio.run(store.tournaments_for(family_alias="fam-1"))] == [alias]
    assert [d["alias"] for d in asyncio.run(store.live_tournaments())] == [alias]
    assert asyncio.run(store.delete_tournament(alias)) is True


def test_il_derby_resta_fuori_dal_giro_generico(tmp_path):
    store = store_with(tmp_path)
    alias = asyncio.run(store.create_tournament(doc_with(2), 42, family_alias="fam-1"))
    derby_alias = asyncio.run(store.create_tournament(
        doc_with(5, fmt="table", kind="derby"), 42, family_alias="fam-1"))
    assert [d["alias"] for d in asyncio.run(store.live_tournaments())] == [alias]
    assert [d["alias"] for d in asyncio.run(store.tournaments_for(family_alias="fam-1"))] == [alias]
    assert asyncio.run(store.tournament(derby_alias))["kind"] == "derby"


def test_la_sonda_del_costo_del_torneo_conta_le_letture_al_deposito():
    from tests.sonde import costo_torneo

    acceso = costo_torneo.conta("family", 4, "stars", True)
    spento = costo_torneo.conta("family", 4, "stars", False)
    for conti in (acceso, spento):
        assert conti["totale"] == sum(v for k, v in conti.items() if k != "totale") > 0
        assert conti["clan_by_alias"] >= 4
    assert "Totale" not in costo_torneo.riassunto("family", 4, "stars", True, acceso)
    assert "totale: %d" % acceso["totale"] in costo_torneo.riassunto(
        "family", 4, "stars", True, acceso)
