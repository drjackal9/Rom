from clashbot.web import app_war

LAST_ATTACKS = [{"tag": "#P2", "stars": 1, "destr": 45.0, "at": 2},
                {"tag": "#P1", "stars": 3, "destr": 100.0, "at": 1}]
BRIEF = {"kind": "war", "day": None, "state": "inWar", "size": 3, "per_member": 2,
         "start": 1000, "end": 5000,
         "us": {"name": "Noi", "stars": 4, "destr": 61.5, "attacks": 3},
         "them": {"name": "Loro", "stars": 2, "destr": 40.0, "attacks": 2},
         "last_attacks": LAST_ATTACKS}
ROWS = [{"pos": 1, "name": "E1", "th": 16, "best": 3, "by": ["Mario"], "assignee": None, "assignee_tag": None,
         "history": [{"name": "Mario", "stars": 3, "destr": 100.0}]},
        {"pos": 2, "name": "E2", "th": 15, "best": 1, "by": ["Luigi"], "assignee": "Peach", "assignee_tag": "#P3",
         "history": [{"name": "Luigi", "stars": 1, "destr": 45.0}], "note": "regine", "swap": True},
        {"pos": 3, "name": "E3", "th": 15, "best": 0, "by": [], "assignee": None, "assignee_tag": None}]
OURS = [{"pos": 1, "name": "Mario", "th": 16, "left": 1, "tag": "#P1", "stars": 3,
         "destr": 100.0},
        {"pos": 2, "name": "Luigi", "th": 15, "left": 0, "tag": "#P2", "stars": 1,
         "destr": 45.0},
        {"pos": 3, "name": "Peach", "th": 15, "left": 2, "tag": "#P3", "stars": 0,
         "destr": 0.0}]
PAGE = {"war": BRIEF, "rows": ROWS, "ours": OURS}
OURS_SENZA_TAG = [{"pos": 1, "name": "Mario", "th": 16, "left": 1},
                  {"pos": 2, "name": "Luigi", "th": 15, "left": 0},
                  {"pos": 3, "name": "Peach", "th": 15, "left": 2}]
GAMES = {"duels": [{"id": "d1", "rival": "#P1", "challenger": "#P2", "metric": "donated",
                    "status": "proposed", "ends": 0}],
         "quiz": {"open": True, "question": "Q?", "options": ["a", "b"], "answered": ["#P9"]},
         "predictions": [{"poll": "war", "options": ["x", "y"], "voted": ["#P1"]}]}
AGENDA = [{"key": "cwl", "start": 50, "end": 60, "state": "upcoming"},
          {"key": "raid", "start": 10, "end": 30, "state": "ongoing"}]


def test_the_war_view_is_personal():
    found = app_war.war_view(PAGE, {"tag": "#P3"}, 2000)
    assert found["phase"] == "inWar" and found["us"]["stars"] == 4
    assert found["mine"] == {"pos": 3, "th": 15, "left": 2, "used": 0, "stars": 0, "destr": 0.0,
                             "target": {"pos": 2, "th": 15, "best": 1}, "last_attack": None}
    assert [row["pos"] for row in found["free"]] == [3]
    assert found["missing"] == [{"name": "Mario", "left": 1}, {"name": "Peach", "left": 2}]
    assert found["enemy"][1]["assignee"] == "Peach" and found["enemy"][0]["best"] == 3


def test_without_a_seat_or_a_war_there_is_no_view():
    assert app_war.war_view({"war": None, "rows": [], "ours": []}, {"tag": "#P1"}, 0) is None
    found = app_war.war_view(PAGE, {"tag": None}, 2000)
    assert found["mine"] is None and len(found["enemy"]) == 3


def test_the_phase_follows_the_clock():
    assert app_war.war_view(PAGE, {"tag": "#P1"}, 9000)["phase"] == "warEnded"
    prep = dict(PAGE, war=dict(BRIEF, state="preparation"))
    assert app_war.war_view(prep, {"tag": "#P1"}, 500)["phase"] == "preparation"


def test_without_the_tag_in_the_rows_the_name_finds_the_village():
    page = dict(PAGE, ours=OURS_SENZA_TAG)
    found = app_war.war_view(page, {"tag": "#P3", "name": "Peach"}, 2000)
    assert found["mine"] == {"pos": 3, "th": 15, "left": 2, "used": 0, "stars": 0, "destr": 0.0,
                             "target": {"pos": 2, "th": 15, "best": 1}, "last_attack": None}
    assert app_war.war_view(page, {"tag": "#P9", "name": "Bowser"}, 2000)["mine"] is None


def test_next_event_prefers_what_is_ongoing_then_the_nearest():
    page = {"agenda": AGENDA}
    assert app_war.next_event(page, 20)["key"] == "raid"
    assert app_war.next_event(page, 40)["key"] == "cwl"
    assert app_war.next_event(page, 70) is None
    assert app_war.next_event({"agenda": []}, 0) is None


def test_todo_lists_only_what_waits_for_me():
    page = {"games": GAMES}
    mine = app_war.todo_for(page, {"tag": "#P1", "verified": True})
    assert [row["kind"] for row in mine] == ["duel", "quiz"]
    assert mine[0] == {"kind": "duel", "id": "d1", "rival": "#P2", "metric": "donated"}
    assert mine[1] == {"kind": "quiz", "question": "Q?", "options": ["a", "b"]}
    other = app_war.todo_for(page, {"tag": "#P2", "verified": False})
    assert [row["kind"] for row in other] == ["quiz", "prediction", "link"]
    assert other[1] == {"kind": "prediction", "poll": "war", "options": ["x", "y"]}
    assert app_war.todo_for({"games": None}, {"tag": None}) == [{"kind": "link"}]


def test_a_duel_already_begun_waits_for_nobody():
    started = dict(GAMES, duels=[dict(GAMES["duels"][0], status="pending")])
    assert [row["kind"] for row in app_war.todo_for({"games": started},
                                                    {"tag": "#P1", "verified": True})] == ["quiz"]


def test_without_a_village_only_the_link_waits():
    assert app_war.todo_for({"games": GAMES}, {"uid": 5, "level": None}) == [{"kind": "link"}]


def test_la_base_nemica_porta_storia_piano_e_cambio_chiesto():
    found = app_war.war_view(PAGE, {"tag": "#P3"}, 2000)
    assert found["enemy"][0]["history"] == [{"name": "Mario", "stars": 3, "destr": 100.0}]
    assert found["enemy"][0]["note"] is None and found["enemy"][0]["swap_pending"] is False
    assert found["enemy"][1]["note"] == "regine" and found["enemy"][1]["swap_pending"] is True
    assert found["enemy"][2]["history"] == []


def test_il_mio_ultimo_attacco_arriva_nel_mio_posto():
    found = app_war.war_view(PAGE, {"tag": "#P1"}, 2000)
    assert found["mine"]["last_attack"] == {"tag": "#P1", "stars": 3, "destr": 100.0, "at": 1}
    assert found["mine"]["stars"] == 3 and found["mine"]["destr"] == 100.0
    assert app_war.war_view(PAGE, {"tag": "#P3"}, 2000)["mine"]["last_attack"] is None
    senza = dict(PAGE, war={key: value for key, value in BRIEF.items() if key != "last_attacks"})
    assert app_war.war_view(senza, {"tag": "#P1"}, 2000)["mine"]["last_attack"] is None


def test_a_guerra_finita_la_vista_porta_esito_e_miglior_attacco():
    aperta = app_war.war_view(PAGE, {"tag": "#P1"}, 2000)
    assert aperta["ended"] is None
    finita = app_war.war_view(PAGE, {"tag": "#P1"}, 9000)
    assert finita["phase"] == "warEnded"
    assert finita["ended"]["result"] == "win"
    assert finita["ended"]["best"] == {"pos": 1, "name": "Mario", "stars": 3, "destr": 100.0}


def test_l_esito_segue_le_stelle_e_poi_la_percentuale():
    persa = dict(PAGE, war=dict(BRIEF, us={"name": "Noi", "stars": 2, "destr": 61.5},
                                them={"name": "Loro", "stars": 4, "destr": 40.0}))
    assert app_war.war_view(persa, {"tag": "#P1"}, 9000)["ended"]["result"] == "lose"
    pari = dict(PAGE, war=dict(BRIEF, us={"name": "Noi", "stars": 2, "destr": 40.0},
                               them={"name": "Loro", "stars": 2, "destr": 40.0}))
    assert app_war.war_view(pari, {"tag": "#P1"}, 9000)["ended"]["result"] == "tie"
    senza_colpi = dict(PAGE, rows=[dict(ROWS[2])])
    assert app_war.war_view(senza_colpi, {"tag": "#P1"}, 9000)["ended"]["best"] is None
