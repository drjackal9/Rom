from datetime import datetime, timezone

from clashbot import events, i18n, progress, scoring, util, warstats
from clashbot.retention import WAR_HISTORY_KEEP
from fixtures import war_json

ENDED = events.war_snapshot(war_json(
    "warEnded",
    our_attacks={"#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 60), ("#E3", 1, 40)]},
    their_attacks={"#E2": [("#P3", 2, 78)], "#E1": [("#P3", 1, 30)]},
))


def test_la_difesa_conta_il_miglior_attacco_ricevuto():
    rows = warstats.war_defense(ENDED)
    assert [r["tag"] for r in rows] == ["#P1", "#P2", "#P3"]
    by_tag = {r["tag"]: r for r in rows}
    assert by_tag["#P3"] == {"tag": "#P3", "name": "Peach", "pos": 3, "stars": 2, "destr": 78, "hits": 2}
    assert by_tag["#P1"]["stars"] == 0 and by_tag["#P1"]["hits"] == 0


def test_il_record_porta_tag_avversario_municipi_e_difese():
    record = events.war_record(ENDED)
    assert record["opp_tag"] == "#ENEMY"
    mario = next(m for m in record["members"] if m["tag"] == "#P1")
    assert mario["th"] == 14 and mario["pos"] == 1
    assert mario["attacks"] == [{"stars": 3, "destr": 100, "defender": "#E1",
                                 "d_pos": 1, "d_th": 14}]
    assert mario["def"] == {"stars": 0, "destr": 0, "hits": 0}
    peach = next(m for m in record["members"] if m["tag"] == "#P3")
    assert peach["def"] == {"stars": 2, "destr": 78, "hits": 2}
    assert peach["missed"] == 2


def test_il_record_resta_leggibile_dalle_funzioni_di_oggi():
    record = events.war_record(ENDED)
    stats = events.member_stats([record])
    assert stats["#P2"]["attacks"] == 2 and stats["#P2"]["triples"] == 0
    assert stats["#P3"]["missed"] == 2


def test_il_fuso_orario_ha_un_aiutante_solo():
    assert str(util.zone("Europe/Rome")) == "Europe/Rome"
    assert util.zone("Non/Esiste") is timezone.utc
    assert util.zone(None) is timezone.utc
    assert i18n._zone is util.zone and progress.zone is util.zone
    assert scoring.season_id(datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc), "Asia/Tokyo") == "2026-10"
    assert scoring.season_id(datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc), "Non/Esiste") == "2026-09"


def rec(opponent="Clan Nemico", opp_tag="#ENEMY", result="win", end="20260912T100000.000Z",
        stars=6, opp_stars=2, destr=100.0, size=3, members=()):
    record = {"kind": "war", "day": None, "endTime": end, "opponent": opponent, "result": result,
              "stars": stars, "destr": destr, "opp_stars": opp_stars, "opp_destr": 26.0,
              "teamSize": size, "attacksPerMember": 2, "members": list(members)}
    if opp_tag is not None:
        record["opp_tag"] = opp_tag
    return record


def mem(tag="#P1", name="Mario", th=15, attacks=(), missed=0, conceded=(0, 0, 0)):
    return {"tag": tag, "name": name, "th": th, "missed": missed,
            "attacks": [{"stars": s, "destr": d, "d_th": t} for s, d, t in attacks],
            "def": {"stars": conceded[0], "destr": conceded[1], "hits": conceded[2]}}


def test_gli_avversari_si_sommano_per_tag_e_ordinano_per_incontri():
    records = [
        rec(end="20260912T100000.000Z", result="win", stars=6, opp_stars=2),
        rec(end="20260905T100000.000Z", result="lose", stars=3, opp_stars=8),
        rec(opponent="Altro Clan", opp_tag="#OTHER", end="20260908T100000.000Z", result="tie", stars=5, opp_stars=5),
    ]
    rows = warstats.opponents(records)
    assert [r["name"] for r in rows] == ["Clan Nemico", "Altro Clan"]
    first = rows[0]
    assert (first["wars"], first["wins"], first["losses"], first["ties"]) == (2, 1, 1, 0)
    assert (first["stars"], first["opp_stars"]) == (9, 10)
    assert first["last"] == datetime(2026, 9, 12, 10, tzinfo=timezone.utc)
    assert first["last_result"] == "win" and first["last_stars"] == 6 and first["last_opp_stars"] == 2
    assert rows[1]["ties"] == 1


def test_il_bilancio_contro_un_avversario_si_trova_per_tag_o_per_nome_vecchio():
    records = [rec(), rec(opp_tag=None, end="20260901T100000.000Z", result="lose")]
    by_tag = warstats.opponent_row(records, "#ENEMY", "Clan Nemico")
    assert by_tag["wars"] == 2 and by_tag["wins"] == 1 and by_tag["losses"] == 1
    assert warstats.opponent_row(records, "#NUOVO", "Clan Mai Visto") is None
    assert warstats.opponent_row([], "#ENEMY", "Clan Nemico") is None


def test_le_difese_contano_solo_le_guerre_in_cui_la_base_e_stata_attaccata():
    records = [
        rec(members=[mem("#P1", "Mario", conceded=(0, 0, 1)), mem("#P2", "Luigi", conceded=(3, 100, 1)),
                     mem("#P3", "Peach", conceded=(0, 0, 0))]),
        rec(end="20260905T100000.000Z",
            members=[mem("#P1", "Mario", conceded=(1, 50, 1)), mem("#P2", "Luigi", conceded=(3, 100, 2)),
                     mem("#P3", "Peach", conceded=(0, 0, 0))]),
    ]
    rows = {r["tag"]: r for r in warstats.defense_rows(records)}
    assert rows["#P1"]["wars"] == 2 and rows["#P1"]["attacked"] == 2 and rows["#P1"]["stars"] == 1
    assert rows["#P1"]["avg"] == 0.5 and rows["#P1"]["clean"] == 1
    assert rows["#P2"]["hits"] == 3 and rows["#P2"]["avg"] == 3.0
    assert rows["#P3"]["attacked"] == 0 and rows["#P3"]["avg"] is None
    assert [r["tag"] for r in warstats.defense_rows(records)] == ["#P1", "#P2", "#P3"]
    assert warstats.wall(warstats.defense_rows(records))["tag"] == "#P1"
    assert warstats.wall([]) is None


def test_il_muro_non_lo_vince_chi_ha_difeso_una_volta_sola_per_fortuna():
    forte = {"tag": "#P1", "name": "Mario", "wars": 10, "attacked": 10, "stars": 2, "hits": 12,
             "destr": 0.0, "clean": 8, "avg": 0.2}
    debole = {"tag": "#P2", "name": "Luigi", "wars": 10, "attacked": 10, "stars": 10, "hits": 14,
              "destr": 0.0, "clean": 2, "avg": 1.0}
    fortunato = {"tag": "#P3", "name": "Peach", "wars": 1, "attacked": 1, "stars": 0, "hits": 1,
                 "destr": 0.0, "clean": 1, "avg": 0.0}
    assert warstats.wall([forte, debole, fortunato])["tag"] == "#P1"


def test_le_triple_si_dividono_per_scarto_di_municipio_tagliato_a_due():
    records = [rec(members=[mem("#P1", "Mario", th=15, attacks=[
        (3, 100, 15), (2, 80, 15), (3, 100, 16), (3, 100, 12), (1, 40, None),
    ])])]
    rows = {r["delta"]: r for r in warstats.th_rows(records)}
    assert rows[0]["attacks"] == 2 and rows[0]["triples"] == 1 and rows[0]["rate"] == 0.5
    assert rows[0]["avg"] == 2.5
    assert rows[-1]["attacks"] == 1 and rows[-1]["rate"] == 1.0
    assert rows[2]["attacks"] == 1
    assert [r["delta"] for r in warstats.th_rows(records)] == [-1, 0, 2]
    assert warstats.overall_rate(records) == 0.75
    assert warstats.th_delta(15, 12) == 2 and warstats.th_delta(12, 15) == -2
    assert warstats.th_delta(None, 15) is None and warstats.th_delta(15, None) is None


def test_il_tasso_lisciato_si_appoggia_alla_media_del_clan():
    buckets = warstats.triple_rates([rec(members=[mem(attacks=[(3, 100, 15), (3, 100, 15)])])])
    assert warstats.smoothed_rate(buckets, 0, 0.5, 2) == 0.75
    assert warstats.smoothed_rate(buckets, 1, 0.5, 2) == 0.5


def test_i_record_del_clan_crescono_solo_quando_qualcosa_migliora():
    first = warstats.update_records(None, rec(stars=9, destr=100.0, size=3))
    assert first["wars"] == 1 and first["wins"] == 1
    assert first["perfect"]["n"] == 1 and first["perfect"]["last"]["opponent"] == "Clan Nemico"
    assert first["stars"] == {"stars": 9, "total": 9, "opponent": "Clan Nemico", "at": "20260912T100000.000Z"}
    assert warstats.beaten(warstats.empty_records(), first) == ["perfect"]
    second = warstats.update_records(first, rec(opponent="Altro", result="lose", stars=4, destr=60.0))
    assert second["wars"] == 2 and second["wins"] == 1 and second["perfect"]["n"] == 1
    assert second["destr"]["destr"] == 100.0 and warstats.beaten(first, second) == []
    third = warstats.update_records(second, rec(opponent="Terzo", stars=12, destr=100.0, size=4))
    assert warstats.beaten(second, third) == ["stars", "perfect"]
    assert third["stars"] == {"stars": 12, "total": 12, "opponent": "Terzo", "at": "20260912T100000.000Z"}


def test_la_striscia_viene_dallapi_e_il_primo_valore_non_e_un_record():
    first = warstats.update_streak(None, 7)
    assert first["streak"] == {"current": 7, "best": 7}
    assert warstats.beaten(warstats.empty_records(), first) == []
    second = warstats.update_streak(first, 9)
    assert second["streak"] == {"current": 9, "best": 9}
    assert warstats.beaten(first, second) == ["streak"]
    third = warstats.update_streak(second, 0)
    assert third["streak"] == {"current": 0, "best": 9}
    assert warstats.beaten(second, third) == []


def test_lalbo_vecchio_diventa_il_documento_nuovo_senza_perdere_titoli():
    legacy = [{"season": "2026-08", "titles": {"MVP": ["Mario", 120]}}]
    state = warstats.hall_state(legacy)
    assert state["seasons"] == legacy
    assert state["records"] == warstats.empty_records()
    assert warstats.hall_state(state) == state
    assert warstats.hall_state(None)["seasons"] == []
    assert warstats.hall_state("rotto")["seasons"] == []
    troppe = [{"season": f"2020-{i:02d}", "titles": {}} for i in range(1, 13)] * 12
    assert len(warstats.hall_state(troppe)["seasons"]) == WAR_HISTORY_KEEP


def test_la_fotografia_del_mese_tiene_difese_muro_e_triple():
    records = [rec(members=[mem("#P1", "Mario", th=15, attacks=[(3, 100, 15)], conceded=(0, 0, 1)),
                            mem("#P2", "Luigi", th=14, attacks=[(1, 30, 15)], conceded=(3, 100, 1))])]
    snap = warstats.month_snapshot("2026-09", records)
    assert snap["season"] == "2026-09" and snap["wars"] == 1 and snap["wins"] == 1
    assert snap["wall"] == {"name": "Mario", "stars": 0, "attacked": 1}
    assert {"name": "Luigi", "stars": 3, "attacked": 1} in snap["defense"]
    assert {"delta": 0, "attacks": 1, "triples": 1} in snap["th"]
    assert warstats.month_start("2026-09", "Europe/Rome").isoformat() == "2026-08-31T22:00:00+00:00"
    assert warstats.month_start("2026-09", "Marte/Olympus").isoformat() == "2026-09-01T00:00:00+00:00"
