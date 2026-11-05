from clashbot import events, handlers, i18n, render, suggest
from clashbot.targets import mirror_plan
from fixtures import war_json

L = i18n.locale("it")

WAR = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 70)]}))
WAR["members"]["#P1"]["th"] = 16
WAR["defenders"]["#E2"]["th"] = 14
WAR["defenders"]["#E3"]["th"] = 14
PLAYERS = {
    "#P1": {"th": 16, "heroes": {"Barbarian King": 95, "Archer Queen": 95}},
    "#P2": {"th": 14, "heroes": {"Barbarian King": 80, "Archer Queen": 80}},
    "#P3": {"th": 14, "heroes": {"Barbarian King": 60}},
}


def rec(members):
    return {"kind": "war", "day": None, "endTime": "20260901T100000.000Z", "opponent": "Vecchi",
            "opp_tag": "#OLD", "result": "win", "stars": 6, "destr": 90.0, "opp_stars": 2,
            "opp_destr": 40.0, "teamSize": 3, "attacksPerMember": 2, "members": members}


def mem(tag, name, th, attacks):
    return {"tag": tag, "name": name, "th": th, "missed": 0,
            "attacks": [{"stars": s, "destr": d, "d_th": t} for s, d, t in attacks],
            "def": {"stars": 0, "destr": 0, "hits": 0}}


HISTORY = [rec([
    mem("#P1", "Mario", 16, [(3, 100, 14), (3, 100, 14), (3, 100, 14), (3, 100, 14)]),
    mem("#P2", "Luigi", 14, [(1, 30, 14), (1, 30, 14), (0, 10, 14), (1, 20, 14)]),
])]


def test_suggerisce_solo_i_bersagli_ancora_da_triplare():
    rows = suggest.suggestions(WAR, PLAYERS, {}, HISTORY)
    assert [r["pos"] for r in rows] == [2, 3]
    assert all(r["best"] < 3 for r in rows)


def test_ordina_per_triple_allo_stesso_scarto_e_poi_per_eroi():
    rows = suggest.suggestions(WAR, PLAYERS, {}, HISTORY)
    picks = rows[0]["picks"]
    assert [p["name"] for p in picks] == ["Mario", "Luigi", "Peach"]
    assert picks[0]["delta"] == 2 and picks[1]["delta"] == 0
    assert picks[0]["rate"] > picks[-1]["rate"]
    assert picks[0]["power"] == 190 and picks[0]["ratio"] == 1.0
    assert picks[2]["ratio"] == 0.375


def test_chi_ha_finito_gli_attacchi_non_viene_suggerito():
    finito = events.war_snapshot(war_json("inWar", our_attacks={
        "#P1": [("#E1", 1, 30), ("#E2", 1, 30)],
    }))
    assert [a["name"] for a in suggest.free_attackers(finito, PLAYERS)] == ["Luigi", "Peach"]
    rows = suggest.suggestions(finito, PLAYERS, {}, HISTORY)
    assert all("Mario" not in [p["name"] for p in r["picks"]] for r in rows)


def test_senza_guerra_e_senza_storico_non_esplode():
    assert suggest.suggestions(None, PLAYERS, {}, HISTORY) == []
    rows = suggest.suggestions(WAR, {}, {}, [])
    assert rows and all(r["picks"] for r in rows)
    assert rows[0]["picks"][0]["ratio"] == 0.0
    assert rows[0]["picks"][0]["rate"] == 0.0


def test_la_card_mostra_bersagli_candidati_e_assegnatario():
    plan = mirror_plan(WAR)
    rows = suggest.suggestions(WAR, PLAYERS, plan, HISTORY)
    text = render.suggest_view(L, rows, WAR)
    assert "BERSAGLI SUGGERITI" in text
    assert "Wario" in text and "Mario" in text
    assert len(text) <= render.MAX_LEN
    assert L.t("suggest.none") in render.suggest_view(L, [], None)
    assert L.t("suggest.done") in render.suggest_view(L, [], WAR)
    many = [dict(rows[0], pos=i) for i in range(1, 15)]
    assert "e altri 4" in render.suggest_view(L, many, WAR)


def test_il_bottone_suggerimenti_sta_sulla_card_bersagli():
    assert "suggest" in handlers.VIEWS
    assert not any(name == "suggest" for name, _ in handlers.COMMANDS)
    for manage in (False, True):
        rows = handlers.targets_keyboard(L, manage).inline_keyboard
        assert "v:suggest" in [b.callback_data for row in rows for b in row]
