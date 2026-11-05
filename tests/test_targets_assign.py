from clashbot import targets
from clashbot.events import war_snapshot
from fixtures import war_json

WAR = war_snapshot(war_json("inWar", {"#P1": [("#E1", 2, 80.0)]}))


def test_member_at_finds_our_man_by_map_position():
    tag, member = targets.member_at(WAR, 2)
    assert tag == "#P2" and member["name"] == "Luigi"
    assert targets.member_at(WAR, "2")[0] == "#P2"
    assert targets.member_at(WAR, 99) is None
    assert targets.member_at({}, 1) is None


def test_assign_writes_frees_and_never_touches_the_old_plan():
    plan = {}
    filled = targets.assign(plan, 3, targets.member_at(WAR, 1))
    assert filled == {"3": {"tag": "#P1", "name": "Mario"}} and plan == {}
    assert targets.assign(filled, 3, None) == {}
    assert targets.assign(filled, 9, None) == filled


def test_attacks_left_counts_what_the_api_says():
    assert targets.attacks_left(WAR, "#P1") == 1
    assert targets.attacks_left(WAR, "#P2") == 2
    assert targets.attacks_left(WAR, "#NOPE") == 0
    assert targets.attacks_left({"attacksPerMember": 2}, "#P1") == 0


def test_la_riga_del_piano_porta_la_storia_il_piano_scritto_e_il_cambio():
    plan = {"1": {"tag": "#P2", "name": "Luigi", "note": "regine prima", "swap": True}}
    rows = targets.plan_rows(WAR, plan)
    assert rows[0]["history"] == [{"name": "Mario", "stars": 2, "destr": 80.0}]
    assert rows[0]["note"] == "regine prima" and rows[0]["swap"] is True
    assert rows[1]["history"] == [] and rows[1]["note"] is None and rows[1]["swap"] is False


def test_il_piano_scritto_sta_sulla_prenotazione_e_si_cancella():
    plan = {"3": {"tag": "#P1", "name": "Mario"}}
    written = targets.noted(plan, 3, "regine prima")
    assert written == {"3": {"tag": "#P1", "name": "Mario", "note": "regine prima"}}
    assert plan == {"3": {"tag": "#P1", "name": "Mario"}}
    assert targets.noted(written, "3", "") == {"3": {"tag": "#P1", "name": "Mario"}}
    assert targets.noted(plan, 9, "niente") is None
    assert targets.noted({}, 3, "niente") is None


def test_il_cambio_si_chiede_solo_sulla_base_di_un_altro():
    plan = {"3": {"tag": "#P1", "name": "Mario"}}
    asked = targets.swapped(plan, 3, "#P2")
    assert asked == {"3": {"tag": "#P1", "name": "Mario", "swap": True}}
    assert plan == {"3": {"tag": "#P1", "name": "Mario"}}
    assert targets.swapped(plan, 3, "#P1") is None
    assert targets.swapped(plan, 9, "#P2") is None


def test_riassegnare_la_base_azzera_piano_scritto_e_cambio():
    plan = {"3": {"tag": "#P1", "name": "Mario", "note": "regine", "swap": True}}
    assert targets.assign(plan, 3, targets.member_at(WAR, 2)) == {"3": {"tag": "#P2",
                                                                       "name": "Luigi"}}
    assert targets.assign(plan, 3, None) == {}
