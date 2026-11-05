from datetime import datetime, timedelta, timezone

from clashbot import events, i18n, render
from clashbot.cwl import current_round, group_summary, standings, war_summary
from clashbot.util import normalize_tag
from fixtures import BASE_MEMBERS, clan_json, war_json

L = i18n.locale("it")
TZ = "Europe/Rome"


def test_member_events_join_leave_promote():
    old = events.member_snapshot(clan_json(BASE_MEMBERS))
    changed = [m for m in BASE_MEMBERS if m[0] != "#P4"]
    changed[2] = ("#P3", "Peach", "coLeader", 14, 4700, 400, 100)
    changed.append(("#P5", "Yoshi", "member", 12, 3900, 0, 0))
    new = events.member_snapshot(clan_json(changed))
    evs = events.member_events(old, new)
    kinds = {(e["type"], e["name"]) for e in evs}
    assert ("join", "Yoshi") in kinds
    assert ("leave", "Toad") in kinds
    assert ("promote", "Peach") in kinds
    text = render.render_member_events(L, evs)
    assert "Yoshi" in text and "Toad" in text and "Co-capo" in text


def test_cambio_nome_dello_stesso_tag_diventa_un_evento():
    old = {"#P1": {"name": "Mario", "role": "member"}}
    new = {"#P1": {"name": "Super Mario", "role": "member"}}
    assert events.member_events(old, new) == [
        {"type": "rename", "tag": "#P1", "old": "Mario", "name": "Super Mario"}
    ]
    text = render.render_member_events(L, events.member_events(old, new))
    assert "Mario" in text and "Super Mario" in text


def test_war_lifecycle_events_and_record():
    prep = events.war_snapshot(war_json("preparation"))
    assert events.war_events(None, prep) == []
    assert events.war_events(events.war_snapshot({"state": "notInWar"}), prep)[0]["type"] == "war_prep"
    started = events.war_snapshot(war_json("inWar"))
    assert [e["type"] for e in events.war_events(prep, started)] == ["war_start"]
    attacked = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]}, their_attacks={"#E2": [("#P3", 2, 78)]}))
    evs = events.war_events(started, attacked)
    assert {e["type"] for e in evs} == {"attack", "defense"}
    attack = next(e for e in evs if e["type"] == "attack")
    assert attack["defender"] == "Bowser" and attack["defender_pos"] == 1 and attack["n"] == 1
    text = render.render_war_events(L, TZ, evs, attacked, now=datetime(2026, 9, 11, 12, tzinfo=timezone.utc))
    assert "Mario" in text and "Bowser" in text and "⭐⭐⭐" in text and "Waluigi" not in text
    ended = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 60), ("#E3", 1, 40)]}, their_attacks={"#E2": [("#P3", 2, 78)]}))
    evs = events.war_events(attacked, ended)
    assert evs[-1]["type"] == "war_end" and evs[-1]["result"] == "win"
    record = events.war_record(ended)
    assert record["result"] == "win" and record["stars"] == 6
    missed = {m["name"]: m["missed"] for m in record["members"]}
    assert missed == {"Mario": 1, "Luigi": 0, "Peach": 2}
    stats = events.member_stats([record, record])
    assert stats["#P2"]["attacks"] == 4 and stats["#P3"]["missed"] == 4
    assert "Luigi" in render.stars_view(L, stats, 2)
    assert "Peach" in render.lazy_view(L, stats, 2)


def test_new_war_after_old_one_emits_prep_not_attacks():
    ended = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]}))
    new_prep = events.war_snapshot(war_json("preparation", end="20260915T100000.000Z", opp_tag="#OTHER"))
    assert [e["type"] for e in events.war_events(ended, new_prep)] == ["war_prep"]


def test_reminders_due_once():
    now = datetime(2026, 9, 12, 7, 30, tzinfo=timezone.utc)
    war = events.war_snapshot(war_json("inWar"))
    assert events.due_reminders(war, [], now) == [28800, 14400]
    assert events.due_reminders(war, [28800, 14400], now) == []
    text = render.render_reminder(L, TZ, war, 14400, now=now)
    assert "MANCANO 4 ORE" in text and "Mario" in text
    full = events.war_snapshot(war_json("inWar", our_attacks={t: [("#E1", 3, 100), ("#E2", 3, 100)] for t in ("#P1", "#P2", "#P3")}))
    assert render.render_reminder(L, TZ, full, 14400, now=now) is None
    assert "TUTTI" in render.render_reminder(L, TZ, full, 3600, now=now)


def test_board_digest_ignores_time():
    war = events.war_snapshot(war_json("inWar"))
    a = render.board_digest(war)
    war2 = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]}))
    assert a != render.board_digest(war2)
    text = render.render_board(L, TZ, war2, now=datetime(2026, 9, 11, 12, tzinfo=timezone.utc))
    left = text.split("Attacchi da fare")[1]
    assert "TABELLONE" in text and "Mario ·1" in left and "Luigi ·2" in left


def test_cwl_orientation_and_standings():
    raw = war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]}, their_attacks={"#E1": [("#P1", 1, 40)]})
    swapped = dict(raw)
    swapped["clan"], swapped["opponent"] = raw["opponent"], raw["clan"]
    oriented = events.orient_war(swapped, "#CLAN1")
    assert oriented["clan"]["tag"] == "#CLAN1"
    group = group_summary({"state": "inWar", "season": "2026-09", "clans": [{"tag": "#CLAN1", "name": "Nostro Clan"}, {"tag": "#ENEMY", "name": "Clan Nemico"}], "rounds": [{"warTags": ["#W1", "#0"]}, {"warTags": ["#0", "#0"]}]})
    assert group["rounds"] == [["#W1"], []]
    assert group["clans"]["#CLAN1"]["members"] == []
    wars = {"#W1": war_summary(oriented)}
    table = standings(group["clans"], wars)
    assert table[0][0] == "#CLAN1" and table[0][1]["stars"] == 13 and table[0][1]["wins"] == 1
    assert current_round(group["rounds"], {"0": "#W1"}, wars) == 0
    text = render.cwl_view(L, TZ, {"active": True, "rounds": group["rounds"], "clans": group["clans"], "wars": wars, "league": "Crystal League I"}, None, "#CLAN1")
    assert "Classifica" in text and "Nostro Clan" in text


def test_capital_events_flow():
    members = events.member_snapshot(clan_json(BASE_MEMBERS))
    now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    raid = {"state": "ongoing", "startTime": "20260911T070000.000Z", "endTime": "20260912T200000.000Z",
            "members": [{"tag": "#P1", "name": "Mario", "attacks": 6, "attackLimit": 5, "bonusAttackLimit": 1}],
            "capitalTotalLoot": 1000, "totalAttacks": 6, "enemyDistrictsDestroyed": 2}
    cap, evs = events.capital_events({}, raid, members, now)
    assert [e["type"] for e in evs] == ["capital_start", "capital_reminder"]
    lazy = {m["name"] for m in evs[1]["lazy"]}
    assert lazy == {"Luigi", "Peach", "Toad"}
    raid["state"] = "ended"
    cap, evs = events.capital_events(cap, raid, members, now)
    assert [e["type"] for e in evs] == ["capital_end"]
    assert "Mario" in render.render_capital_events(L, TZ, evs)


def test_util():
    assert normalize_tag(" #pyl o29 ") == "#PYL029"
    assert normalize_tag("#ZZZ") is None
    now = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)
    assert L.delta(now + timedelta(hours=26, minutes=5), now) == "1g 2h"
    assert L.delta(now + timedelta(minutes=5), now) == "5m"
