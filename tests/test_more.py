from datetime import datetime, timezone

from clashbot import achievements, agenda, scoring, targets, events
from fixtures import war_json


def test_player_events():
    old = achievements.player_snapshot({"name": "Mario", "townHallLevel": 14, "bestTrophies": 4990, "warStars": 998,
        "league": {"id": 29000010, "name": "Crystal I"}, "heroes": [{"name": "Archer Queen", "level": 64, "village": "home"}]})
    new = achievements.player_snapshot({"name": "Mario", "townHallLevel": 15, "bestTrophies": 5010, "warStars": 1001,
        "league": {"id": 29000011, "name": "Master III"}, "heroes": [{"name": "Archer Queen", "level": 65, "village": "home"}]})
    kinds = [e["type"] for e in achievements.player_events(old, new)]
    assert kinds == ["th", "hero", "league", "warstars", "record"]
    assert achievements.player_events(None, new) == []
    assert achievements.player_events(new, new) == []


def test_agenda_windows_and_announcements():
    now = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)
    items = {i["key"]: i for i in agenda.upcoming(now)}
    assert items["games"]["start"] == datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    assert items["cwl"]["start"] == datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    assert items["raid"]["start"] == datetime(2026, 9, 11, 7, tzinfo=timezone.utc) and items["raid"]["state"] == "ongoing"
    assert items["season"]["start"] == datetime(2026, 9, 28, 5, tzinfo=timezone.utc)
    assert agenda.season_end(now, "20260930T070000.000Z") == datetime(2026, 9, 30, 7, tzinfo=timezone.utc)
    eve = datetime(2026, 9, 21, 9, tzinfo=timezone.utc)
    due = agenda.due_announcements(eve, None, {})
    assert [(k.split(":")[0], phase) for k, _, phase in due] == [("games", "tomorrow")]
    sent = {k: 1 for k, _, _ in due}
    assert agenda.due_announcements(eve, None, sent) == []
    start = datetime(2026, 9, 22, 9, tzinfo=timezone.utc)
    assert [phase for _, _, phase in agenda.due_announcements(start, None, sent)] == ["start"]


def test_scoring_and_titles():
    season = scoring.empty_season("2026-09")
    ended = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)], "#P2": [("#E3", 1, 40)]}))
    scoring.apply_war(season, events.war_record(ended))
    raid = {"startTime": "20260911T070000.000Z", "members": [{"tag": "#P3", "name": "Peach", "attacks": 6, "capitalResourcesLooted": 45000}]}
    assert scoring.apply_raid(season, raid) and not scoring.apply_raid(season, raid)
    scoring.apply_donations(season, {"#P2": {"name": "Luigi", "donations": 1250}})
    scoring.apply_donations(season, {"#P2": {"name": "Luigi", "donations": 900}})
    board = scoring.leaderboard(season)
    assert board[0][0] == "#P1" and board[0][2] == 2 * 2 + 6 + 2 * 3
    assert season["members"]["#P2"]["donations"] == 1250
    scoring.apply_prediction(season, 42, "Alex", True)
    t = scoring.titles(season)
    assert t["MVP"][0] == "Mario" and t["Cecchino"] == ("Mario", 2) and t["Donatore"] == ("Luigi", 1250)
    assert t["Razziatore"] == ("Peach", 45000) and t["Veggente"] == ("Alex", 1)
    assert scoring.season_id(datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc), "Asia/Tokyo") == "2026-10"
    assert scoring.season_id(datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc), "America/Sao_Paulo") == "2026-09"
    assert scoring.season_id(datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc), "Non/Esiste") == "2026-09"
    assert scoring.prediction_bucket(9, 9) == 3 and scoring.prediction_bucket(4, 9) == 0 and scoring.prediction_bucket(5, 9) == 1


def test_streaks():
    good = events.war_record(events.war_snapshot(war_json("warEnded", our_attacks={t: [("#E1", 3, 100), ("#E2", 3, 100)] for t in ("#P1", "#P2", "#P3")})))
    bad = events.war_record(events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)]})))
    s = scoring.streaks([good, good, bad, good])
    assert s["#P1"]["streak"] == 4 and s["#P2"]["streak"] == 2


def test_targets():
    war = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E2", 2, 70)]}))
    plan = targets.mirror_plan(war)
    assert plan["1"]["name"] == "Mario" and plan["3"]["name"] == "Peach"
    rows = targets.plan_rows(war, plan)
    assert rows[1]["assignee"] == "Luigi" and rows[1]["best"] == 2 and rows[1]["by"] == ["Mario"]
    assert targets.targets_for(plan, "#P2") == [2]


def player(*items):
    return {"name": "Mario", "achievements": [
        {"name": name, "stars": stars, "village": "home"} for name, stars in items
    ]}


def test_la_mappa_tiene_solo_gli_obiettivi_non_finiti():
    mapped = achievements.achievement_map(player(("Gold Grab", 3), ("Sweet Victory!", 1)))
    assert mapped == {"Sweet Victory!": 1}


def test_la_mappa_ignora_la_base_del_costruttore():
    raw = player(("Sweet Victory!", 1))
    raw["achievements"].append({"name": "Un-Build It", "stars": 0, "village": "builderBase"})
    assert achievements.achievement_map(raw) == {"Sweet Victory!": 1}


def test_una_stella_guadagnata_diventa_un_evento():
    old = {"name": "Mario", "ach": {"Sweet Victory!": 1}}
    new = {"name": "Mario", "ach": {"Sweet Victory!": 2}}
    assert achievements.achievement_events(old, new) == [
        {"type": "stars", "name": "Mario", "goal": "Sweet Victory!", "stars": 2, "gained": 1}
    ]


def test_l_obiettivo_completato_sparisce_dalla_mappa_e_vale_tre_stelle():
    old = {"name": "Mario", "ach": {"Sweet Victory!": 2}}
    new = {"name": "Mario", "ach": {}}
    assert achievements.achievement_events(old, new) == [
        {"type": "stars", "name": "Mario", "goal": "Sweet Victory!", "stars": 3, "gained": 1}
    ]


def test_un_obiettivo_nuovo_del_gioco_non_produce_annunci_finti():
    old = {"name": "Mario", "ach": {}}
    new = {"name": "Mario", "ach": {"Obiettivo Nuovo": 0}}
    assert achievements.achievement_events(old, new) == []


def test_senza_mappa_precedente_non_si_annuncia_niente():
    assert achievements.achievement_events(None, {"ach": {"X": 1}}) == []
    assert achievements.achievement_events({"ach": {"X": 1}}, None) == []


def test_gli_eventi_delle_stelle_entrano_in_player_events():
    old = {"name": "Mario", "th": 13, "heroes": {}, "ach": {"Sweet Victory!": 1}}
    new = {"name": "Mario", "th": 13, "heroes": {}, "ach": {"Sweet Victory!": 2}}
    assert any(e["type"] == "stars" for e in achievements.player_events(old, new))


def test_lo_snapshot_tiene_la_mappa_degli_obiettivi():
    snapshot = achievements.player_snapshot(player(("Gold Grab", 3), ("Sweet Victory!", 1)))
    assert snapshot["ach"] == {"Sweet Victory!": 1}
