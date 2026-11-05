import json

from clashbot.leaderboards import PODIUM
from clashbot.web import app_people

PAGE = {"members": [{"tag": "#P1", "name": "Mario", "role": "leader", "th": 16, "trophies": 5100,
                     "donations": 40, "received": 10, "linked": True, "verified": True,
                     "avail": "in"},
                    {"tag": "#P2", "name": "Luigi", "role": "member", "th": 15, "trophies": 4800,
                     "donations": 20, "received": 30, "linked": False, "verified": False,
                     "avail": None},
                    {"tag": "#P3", "name": "Peach", "role": "member", "th": 14, "trophies": 4500,
                     "donations": 10, "received": 5, "linked": True, "verified": False,
                     "avail": "maybe"},
                    {"tag": "#P4", "name": "Toad", "role": "member", "th": 13, "trophies": 4200,
                     "donations": 5, "received": 0, "linked": False, "verified": False,
                     "avail": None}],
        "record": {"wars": 10, "wins": 7, "streak": {"current": 2, "best": 5}},
        "growth": {"days": ["d1", "d2"],
                   "players": {"#P1": {"trophies": [5000, 5100], "th": [16, 16]}},
                   "clan": {"trophies": [5000, 5100]},
                   "period": {"week": {"#P3": {"donated": 10, "war_stars": 1, "levels": 0,
                                               "score": 5},
                                       "#P1": {"donated": 40, "war_stars": 5, "levels": 1,
                                               "score": 9},
                                       "#P4": {"donated": 5, "war_stars": 0, "levels": 0,
                                               "score": 3},
                                       "#P2": {"donated": 20, "war_stars": 3, "levels": 2,
                                               "score": 7}},
                              "month": {"#P1": {"donated": 90, "war_stars": 12, "levels": 4,
                                                "score": 20}}}},
        "medals": {"#P1": [{"badge": "first_war", "ts": 1}]},
        "profiles": {"777": {"name": "Mario", "tag": "#P1", "th": 16},
                     "888": {"name": "Peach", "tag": "#P3", "th": 14}}}
MINE = {"uid": 777, "tag": "#P1", "name": "Mario", "verified": True, "whisper": False,
        "avail": "in"}


def test_members_view_has_rows_climbers_and_record():
    found = app_people.members_view(PAGE)
    assert found["rows"][0]["name"] == "Mario" and found["record"]["wins"] == 7
    assert found["climb"]["week"][0] == {"tag": "#P1", "name": "Mario", "score": 9, "donated": 40,
                                         "war_stars": 5, "levels": 1}


def test_the_climb_keeps_the_podium_of_the_week_in_order():
    found = app_people.members_view(PAGE)["climb"]["week"]
    assert len(found) == PODIUM
    assert [row["name"] for row in found] == ["Mario", "Luigi", "Peach"]


def test_an_empty_page_has_nothing_to_show():
    found = app_people.members_view({})
    assert found == {"rows": [], "climb": {"week": [], "month": []}, "chronicle": [],
                     "record": {}}


def test_me_view_is_only_about_me():
    found = app_people.me_view(PAGE, MINE)
    assert found["growth"] == {"days": ["d1", "d2"], "trophies": [5000, 5100], "th": [16, 16]}
    assert found["medals"][0]["badge"] == "first_war" and found["profile"]["th"] == 16
    assert found["period"]["donated"] == 40
    assert found["villages"] == [{"tag": "#P1", "name": "Mario", "verified": True}]
    assert found["whisper"] is False and found["avail"] == "in"
    nobody = app_people.me_view(PAGE, {"uid": 5, "tag": None, "name": "Nuovo"})
    assert nobody["growth"] is None and nobody["villages"] == [] and nobody["medals"] == []
    assert nobody["profile"] is None and nobody["period"] is None


def test_my_corner_carries_all_my_villages():
    seat = dict(MINE, villages=[{"tag": "#P1", "name": "Mario", "verified": True},
                                {"tag": "#P4", "name": "Toad", "verified": False}])
    assert app_people.me_view(PAGE, seat)["villages"] == seat["villages"]


def test_my_corner_never_carries_the_others():
    text = json.dumps(app_people.me_view(PAGE, MINE), ensure_ascii=False)
    for other in ("#P2", "#P3", "Luigi", "Peach", "888"):
        assert other not in text


def test_growth_of_answers_only_for_who_has_days():
    assert app_people.growth_of(PAGE, "#P2") is None
    assert app_people.growth_of({}, "#P1") is None


def test_le_tessere_dei_membri_portano_assenza_e_rapporto_donazioni():
    found = app_people.members_view(dict(PAGE, idle=[{"tag": "#P2", "name": "Luigi", "days": 4}]))
    rows = {row["tag"]: row for row in found["rows"]}
    assert rows["#P2"]["absent_days"] == 4 and rows["#P1"]["absent_days"] == 0
    assert rows["#P1"]["ratio"] == 4.0 and rows["#P2"]["ratio"] == 0.67
    assert rows["#P4"]["ratio"] is None
    assert PAGE["members"][0].get("absent_days") is None


def test_chi_cresce_porta_la_settimana_e_il_mese():
    found = app_people.members_view(PAGE)["climb"]
    assert [row["name"] for row in found["week"]] == ["Mario", "Luigi", "Peach"]
    assert [row["name"] for row in found["month"]] == ["Mario"]
    assert len(found["week"]) == PODIUM


def test_la_cronaca_mette_prima_l_evento_piu_fresco():
    page = dict(PAGE, events=[
        {"pack": "members", "kind": "join", "who": "Toad", "n": 13, "at": 30},
        {"pack": "wars", "kind": "war_end", "who": "Clan Nemico", "n": 3, "at": 50},
        {"pack": "members", "kind": "leave", "who": "Peach", "n": None, "at": 40}])
    found = app_people.members_view(page)["chronicle"]
    assert [row["at"] for row in found] == [50, 40, 30]
    assert found[0] == {"pack": "wars", "kind": "war_end", "who": "Clan Nemico", "n": 3, "at": 50}
    assert app_people.members_view(PAGE)["chronicle"] == []


def test_sei_tu_non_esiste_piu_e_non_propone_nessun_nome():
    page = dict(PAGE, roster=[{"tag": "#P2", "name": "Luigi"},
                              {"tag": "#P4", "name": "Toad"},
                              {"tag": "#P7", "name": "Luigii"},
                              {"tag": "#P8", "name": "Luig"}])
    nuovo = {"uid": 5, "tag": None, "who": "Luigi"}
    assert not hasattr(app_people, "candidates")
    assert "candidates" not in app_people.me_view(page, nuovo)
    assert "Luigii" not in str(app_people.me_view(page, nuovo))


def test_il_mio_angolo_porta_l_obiettivo_e_la_lingua():
    page = dict(PAGE, roster=[{"tag": "#P2", "name": "Luigi"}])
    seat = dict(MINE, lang="it", goal={"kind": "trophies", "hero": None, "target": 5500,
                                       "value": 5400, "picks": []})
    found = app_people.me_view(page, seat)
    assert found["goal"]["target"] == 5500 and found["lang"] == "it"
    assert "candidates" not in found


def test_il_rivale_consigliato_e_il_collegato_piu_vicino_di_trofei():
    found = app_people.rival_for(PAGE, MINE)
    assert found == {"tag": "#P3", "name": "Peach", "trophies": 4500}
    assert "777" not in str(found) and "uid" not in str(found)


def test_a_parita_di_distanza_il_rivale_e_il_primo_per_nome():
    page = {"members": [dict(PAGE["members"][0], trophies=5000),
                        dict(PAGE["members"][1], name="Anna", linked=True, trophies=4900),
                        dict(PAGE["members"][2], name="Zeno", linked=True, trophies=5100)]}
    assert app_people.rival_for(page, MINE)["name"] == "Anna"


def test_senza_compagni_collegati_il_rivale_non_si_inventa():
    solo = {"members": [dict(PAGE["members"][0])]}
    assert app_people.rival_for(solo, MINE) is None
    assert app_people.rival_for(PAGE, {"uid": 5, "tag": None}) is None
    assert app_people.rival_for({}, MINE) is None
