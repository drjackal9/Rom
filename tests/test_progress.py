from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from clashbot import achievements, progress

TZ = "Europe/Rome"
ROME = ZoneInfo(TZ)


def player_json(**over):
    p = {
        "tag": "#P1", "name": "Mario", "townHallLevel": 16, "warStars": 1234,
        "achievements": [
            {"name": "Gold Grab", "value": 1_500_000_000},
            {"name": "Elixir Escapade", "value": 1_400_000_000},
            {"name": "Heroic Heist", "value": 9_000_000},
            {"name": "Conqueror", "value": 4200},
            {"name": "Games Champion", "value": 25_000},
            {"name": "Aggressive Capitalism", "value": 3_000_000},
            {"name": "Most Valuable Clanmate", "value": 850_000},
            {"name": "Friend in Need", "value": 120_000},
            {"name": "Sweet Victory!", "value": 5_000},
        ],
        "heroes": [
            {"name": "Barbarian King", "level": 90, "village": "home"},
            {"name": "Archer Queen", "level": 90, "village": "home"},
            {"name": "Battle Machine", "level": 30, "village": "builderBase"},
        ],
        "troops": [
            {"name": "Barbarian", "level": 11, "village": "home"},
            {"name": "Archer", "level": 11, "village": "home"},
            {"name": "Super Barbarian", "level": 11, "village": "home", "superTroopIsActive": True},
            {"name": "Super Archer", "level": 9, "village": "home"},
            {"name": "Raged Barbarian", "level": 18, "village": "builderBase"},
            {"name": "L.A.S.S.I", "level": 10, "village": "home"},
        ],
        "spells": [
            {"name": "Lightning Spell", "level": 11, "village": "home"},
            {"name": "Healing Spell", "level": 10, "village": "home"},
        ],
    }
    p.update(over)
    return p


def base_counters(**over):
    c = {k: 0 for k in progress.COUNTERS}
    c["th"] = 14
    c.update(over)
    return c


def test_counters_from_player_json():
    c = progress.counters(player_json())
    assert c == {
        "gold": 1_500_000_000, "elixir": 1_400_000_000, "dark": 9_000_000, "wins": 4200,
        "games": 25_000, "raid_loot": 3_000_000, "capital_gold": 850_000, "donated": 120_000,
        "war_stars": 1234, "levels": 233, "th": 16,
    }
    assert set(c) == set(progress.COUNTERS)
    assert all(isinstance(v, int) for v in c.values())


def test_counters_missing_fields_default_to_zero():
    c = progress.counters({"achievements": [{"name": "Gold Grab", "value": 100}]})
    assert c["gold"] == 100
    assert c["games"] == 0 and c["war_stars"] == 0 and c["levels"] == 0 and c["th"] == 0
    assert progress.counters({}) == {k: 0 for k in progress.COUNTERS}


def test_player_snapshot_carries_counters():
    snap = achievements.player_snapshot(player_json())
    assert snap["counters"] == progress.counters(player_json())
    assert snap["th"] == 16 and snap["name"] == "Mario"


def test_update_creates_bases_for_new_member():
    now = datetime(2026, 9, 12, 12, 0, tzinfo=ROME)
    state = progress.update({}, "#P1", "Mario", base_counters(gold=1000, levels=100), now, TZ)
    entry = state["#P1"]
    assert entry["name"] == "Mario"
    assert entry["now"]["gold"] == 1000
    assert entry["week"]["since"] == int(now.timestamp())
    assert entry["month"]["since"] == int(now.timestamp())
    assert entry["week"]["gold"] == 1000 and entry["month"]["levels"] == 100


def test_update_same_week_keeps_base():
    state = progress.update({}, "#P1", "Mario", base_counters(gold=1000), datetime(2026, 9, 8, 9, 0, tzinfo=ROME), TZ)
    since = state["#P1"]["week"]["since"]
    progress.update(state, "#P1", "Mario", base_counters(gold=4000), datetime(2026, 9, 11, 22, 0, tzinfo=ROME), TZ)
    entry = state["#P1"]
    assert entry["week"]["since"] == since and entry["week"]["gold"] == 1000
    assert entry["month"]["gold"] == 1000
    assert entry["now"]["gold"] == 4000
    assert progress.deltas(state, "week")[0]["gold"] == 3000


def test_new_week_rebases_week_only():
    state = progress.update({}, "#P1", "Mario", base_counters(gold=1000, wins=10),
                            datetime(2026, 9, 8, 9, 0, tzinfo=ROME), TZ)
    progress.update(state, "#P1", "Mario", base_counters(gold=4000, wins=20),
                    datetime(2026, 9, 12, 12, 0, tzinfo=ROME), TZ)
    progress.update(state, "#P1", "Mario", base_counters(gold=9000, wins=30),
                    datetime(2026, 9, 14, 0, 30, tzinfo=ROME), TZ)
    entry = state["#P1"]
    assert entry["week"]["since"] == int(datetime(2026, 9, 14, 0, 0, tzinfo=ROME).timestamp())
    assert entry["week"]["gold"] == 4000 and entry["week"]["wins"] == 20
    assert entry["month"]["since"] == int(datetime(2026, 9, 8, 9, 0, tzinfo=ROME).timestamp())
    assert entry["month"]["gold"] == 1000
    assert progress.deltas(state, "week")[0]["gold"] == 5000
    assert progress.deltas(state, "month")[0]["gold"] == 8000


def test_new_month_rebases_month_only():
    state = progress.update({}, "#P1", "Mario", base_counters(gold=1000),
                            datetime(2026, 9, 27, 9, 0, tzinfo=ROME), TZ)
    progress.update(state, "#P1", "Mario", base_counters(gold=4000), datetime(2026, 9, 30, 9, 0, tzinfo=ROME), TZ)
    progress.update(state, "#P1", "Mario", base_counters(gold=7000), datetime(2026, 10, 1, 10, 0, tzinfo=ROME), TZ)
    entry = state["#P1"]
    assert entry["month"]["since"] == int(datetime(2026, 10, 1, 0, 0, tzinfo=ROME).timestamp())
    assert entry["month"]["gold"] == 4000
    assert entry["week"]["since"] == int(datetime(2026, 9, 28, 0, 0, tzinfo=ROME).timestamp())
    assert entry["week"]["gold"] == 1000
    assert progress.deltas(state, "month")[0]["gold"] == 3000
    assert progress.deltas(state, "week")[0]["gold"] == 6000


def test_invalid_tz_falls_back_to_utc():
    state = progress.update({}, "#P1", "Mario", base_counters(gold=10),
                            datetime(2026, 9, 12, 12, 0, tzinfo=ROME), "Mars/Olympus")
    progress.update(state, "#P1", "Mario", base_counters(gold=20),
                    datetime(2026, 9, 14, 0, 30, tzinfo=ZoneInfo("UTC")), "Mars/Olympus")
    assert state["#P1"]["week"]["since"] == int(datetime(2026, 9, 14, 0, 0, tzinfo=ZoneInfo("UTC")).timestamp())


def test_a_lower_reading_never_lowers_the_base_nor_the_now():
    state = progress.update({}, "#P1", "Mario", base_counters(gold=5000, donated=900, th=15),
                            datetime(2026, 9, 8, 9, 0, tzinfo=ROME), TZ)
    progress.update(state, "#P1", "Mario", base_counters(gold=5400, donated=120, th=15),
                    datetime(2026, 9, 9, 9, 0, tzinfo=ROME), TZ)
    entry = state["#P1"]
    assert entry["week"]["donated"] == 900 and entry["month"]["donated"] == 900
    assert entry["now"]["donated"] == 900 and entry["now"]["gold"] == 5400
    row = progress.deltas(state, "week")[0]
    assert row["donated"] == 0 and row["gold"] == 400
    progress.update(state, "#P1", "Mario", base_counters(gold=5400, donated=1500, th=15),
                    datetime(2026, 9, 10, 9, 0, tzinfo=ROME), TZ)
    assert progress.deltas(state, "week")[0]["donated"] == 600


def test_an_empty_reading_is_not_an_observation():
    start = datetime(2026, 9, 8, 9, 0, tzinfo=ROME)
    state = progress.update({}, "#P1", "Mario", base_counters(gold=1_500_000_000, wins=4200, th=16), start, TZ)
    progress.update(state, "#P1", "Mario", base_counters(gold=0, wins=0, th=0),
                    datetime(2026, 9, 9, 9, 0, tzinfo=ROME), TZ)
    entry = state["#P1"]
    assert entry["now"]["gold"] == 1_500_000_000 and entry["now"]["wins"] == 4200 and entry["now"]["th"] == 16
    assert entry["last_active"] == int(start.timestamp())
    progress.update(state, "#P1", "Mario", base_counters(gold=1_500_000_100, wins=4201, th=16),
                    datetime(2026, 9, 10, 9, 0, tzinfo=ROME), TZ)
    row = progress.deltas(state, "week")[0]
    assert row["gold"] == 100 and row["wins"] == 1 and row["score"] == 1


def test_last_active_moves_only_on_an_increase():
    first = datetime(2026, 9, 8, 9, 0, tzinfo=ROME)
    third = datetime(2026, 9, 10, 9, 0, tzinfo=ROME)
    state = progress.update({}, "#P1", "Mario", base_counters(gold=5000, th=14), first, TZ)
    assert state["#P1"]["last_active"] == int(first.timestamp())
    progress.update(state, "#P1", "Mario", base_counters(gold=5000, th=14),
                    datetime(2026, 9, 9, 9, 0, tzinfo=ROME), TZ)
    assert state["#P1"]["last_active"] == int(first.timestamp())
    progress.update(state, "#P1", "Mario", base_counters(gold=5000, donated=10, th=14), third, TZ)
    assert state["#P1"]["last_active"] == int(third.timestamp())
    progress.update(state, "#P1", "Mario", base_counters(th=0), datetime(2026, 9, 11, 9, 0, tzinfo=ROME), TZ)
    assert state["#P1"]["last_active"] == int(third.timestamp())


def test_an_entry_written_before_last_active_gets_one():
    now = datetime(2026, 9, 12, 9, 0, tzinfo=ROME)
    state = {"#P1": {"name": "Mario", "now": {"gold": 100, "th": 14}}}
    assert progress.idle(state, now) == []
    progress.update(state, "#P1", "Mario", base_counters(gold=100, th=14), now, TZ)
    assert state["#P1"]["last_active"] == int(now.timestamp())


def test_deltas_rows_and_ordering():
    start = datetime(2026, 9, 8, 9, 0, tzinfo=ROME)
    later = datetime(2026, 9, 10, 9, 0, tzinfo=ROME)
    state = {}
    progress.update(state, "#P1", "Mario", base_counters(gold=0, elixir=0, th=15), start, TZ)
    progress.update(state, "#P2", "Luigi", base_counters(gold=0, elixir=0, th=14), start, TZ)
    progress.update(state, "#P3", "Peach", base_counters(gold=0, elixir=0, th=14), start, TZ)
    progress.update(state, "#P1", "Mario", base_counters(
        gold=3_000_000, elixir=2_500_000, dark=90_000, wins=12, games=2500, raid_loot=450_000,
        capital_gold=30_000, donated=4000, war_stars=15, levels=6, th=16), later, TZ)
    progress.update(state, "#P2", "Luigi", base_counters(gold=1_000_000, elixir=200_000, wins=4, th=14), later, TZ)
    progress.update(state, "#P3", "Peach", base_counters(gold=1_000_000, elixir=200_000, wins=4, th=14), later, TZ)
    rows = progress.deltas(state, "week")
    assert [r["name"] for r in rows] == ["Mario", "Luigi", "Peach"]
    mario = rows[0]
    assert mario["tag"] == "#P1" and mario["loot"] == 5_500_000
    assert mario["dark"] == 90_000 and mario["capital_gold"] == 30_000 and mario["war_stars"] == 15
    assert mario["donated"] == 4000 and mario["th_up"] == 1 and mario["since"] == int(start.timestamp())
    assert mario["score"] == 10 + 12 + 18 + 25 + 25 + 4
    assert rows[1]["score"] == rows[2]["score"] == 6
    assert set(mario) == {"tag", "name", "gold", "elixir", "dark", "loot", "wins", "games", "raid_loot",
                          "capital_gold", "donated", "war_stars", "levels", "th_up", "score", "since"}
    assert progress.deltas({}, "month") == []


def test_score_arithmetic():
    assert progress.score({"loot": 0, "wins": 0, "levels": 0, "th_up": 0, "games": 0, "raid_loot": 0}) == 0
    assert progress.score({"loot": 1_999_999, "wins": 3, "levels": 2, "th_up": 1, "games": 250,
                           "raid_loot": 250_000}) == 2 + 3 + 6 + 25 + 2 + 2
    assert progress.score({}) == 0


def test_idle_honours_minimum_age():
    start = datetime(2026, 9, 7, 9, 0, tzinfo=ROME)
    now = datetime(2026, 9, 12, 9, 0, tzinfo=ROME)
    state = {}
    progress.update(state, "#P1", "Mario", base_counters(gold=0, th=15), start, TZ)
    progress.update(state, "#P2", "Luigi", base_counters(gold=0, th=14), start, TZ)
    progress.update(state, "#P3", "Peach", base_counters(gold=0, th=14), datetime(2026, 9, 11, 9, 0, tzinfo=ROME), TZ)
    progress.update(state, "#P4", "Toad", base_counters(gold=0, th=14), start, TZ)
    progress.update(state, "#P1", "Mario", base_counters(gold=3_000_000, th=15), now, TZ)
    progress.update(state, "#P2", "Luigi", base_counters(gold=0, th=14), now, TZ)
    progress.update(state, "#P3", "Peach", base_counters(gold=0, th=14), now, TZ)
    progress.update(state, "#P4", "Toad", base_counters(gold=0, levels=3, th=14), now, TZ)
    rows = progress.idle(state, now)
    assert [r["tag"] for r in rows] == ["#P2"]
    assert rows[0] == {"tag": "#P2", "name": "Luigi", "days": 5}
    wins_only = {}
    progress.update(wins_only, "#P5", "Yoshi", base_counters(wins=1, th=13), start, TZ)
    progress.update(wins_only, "#P5", "Yoshi", base_counters(wins=4, th=13), now, TZ)
    assert progress.idle(wins_only, now) == []


def test_idle_sorted_by_days_then_name():
    now = datetime(2026, 9, 20, 9, 0, tzinfo=ROME)
    state = {}
    progress.update(state, "#A", "Anna", base_counters(th=13), datetime(2026, 9, 10, 9, 0, tzinfo=ROME), TZ)
    progress.update(state, "#B", "Bruno", base_counters(th=13), datetime(2026, 9, 14, 9, 0, tzinfo=ROME), TZ)
    progress.update(state, "#C", "Carla", base_counters(th=13), datetime(2026, 9, 14, 9, 0, tzinfo=ROME), TZ)
    for tag, name in (("#A", "Anna"), ("#B", "Bruno"), ("#C", "Carla")):
        progress.update(state, tag, name, base_counters(th=13), now, TZ)
    rows = progress.idle(state, now)
    assert [(r["name"], r["days"]) for r in rows] == [("Anna", 10), ("Bruno", 6), ("Carla", 6)]


def test_idle_ignores_the_period_boundaries():
    day = datetime(2026, 8, 20, 9, 0, tzinfo=ROME)
    monday = datetime(2026, 9, 7, 9, 0, tzinfo=ROME)
    assert monday.weekday() == 0 and monday.day <= 7
    state = {}
    while day <= monday:
        for tag, name in (("#P1", "Mario"), ("#P2", "Luigi")):
            progress.update(state, tag, name, base_counters(gold=1000, th=14), day, TZ)
        day += timedelta(days=1)
    progress.update(state, "#P2", "Luigi", base_counters(gold=9_000_000, th=14), monday, TZ)
    assert progress.idle(state, monday) == [{"tag": "#P1", "name": "Mario", "days": 18}]
    month = [r for r in progress.deltas(state, "month") if r["tag"] == "#P1"][0]
    assert month["since"] == int(datetime(2026, 9, 1, 0, 0, tzinfo=ROME).timestamp())


def test_prune_removes_former_members():
    now = datetime(2026, 9, 12, 9, 0, tzinfo=ROME)
    state = {}
    progress.update(state, "#P1", "Mario", base_counters(th=15), now, TZ)
    progress.update(state, "#P2", "Luigi", base_counters(th=14), now, TZ)
    out = progress.prune(state, ["#P1", "#P9"])
    assert out is state and list(state) == ["#P1"]
    assert progress.prune(state, []) == {}


def test_la_settimana_chiusa_viene_conservata_al_cambio_periodo():
    tz = "Europe/Rome"
    monday = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    state = progress.update({}, "#P1", "Mario", {"gold": 0, "wins": 0, "levels": 0}, monday, tz)
    state = progress.update(state, "#P1", "Mario", {"gold": 3_000_000, "wins": 9, "levels": 4},
                            monday + timedelta(days=3), tz)
    assert progress.closed(state, "week") == []
    after = monday + timedelta(days=7)
    state = progress.update(state, "#P1", "Mario", {"gold": 3_500_000, "wins": 10, "levels": 4},
                            after, tz)
    rows = progress.closed(state, "week")
    assert len(rows) == 1
    assert rows[0]["tag"] == "#P1" and rows[0]["name"] == "Mario"
    assert rows[0]["loot"] == 3_000_000 and rows[0]["wins"] == 9 and rows[0]["levels"] == 4
    assert rows[0]["score"] == progress.score(rows[0])
    assert rows[0]["until"] == progress.period_start(after, tz, "week")
    assert progress.closed(state, "week", rows[0]["until"]) == rows
    assert progress.closed(state, "week", rows[0]["until"] - progress.DAY * 7) == []


def test_il_mese_chiuso_si_conserva_come_la_settimana():
    tz = "Europe/Rome"
    first = datetime(2026, 9, 27, 9, tzinfo=timezone.utc)
    october = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    state = progress.update({}, "#P1", "Mario", {"gold": 1_000_000}, first, tz)
    state = progress.update(state, "#P1", "Mario", {"gold": 4_000_000},
                            datetime(2026, 9, 30, 9, tzinfo=timezone.utc), tz)
    state = progress.update(state, "#P1", "Mario", {"gold": 4_200_000}, october, tz)
    rows = progress.closed(state, "month", progress.period_start(october, tz, "month"))
    assert [(r["tag"], r["loot"]) for r in rows] == [("#P1", 3_000_000)]
    assert progress.closed(state, "season") == []


def test_una_riga_senza_base_di_periodo_non_conta_i_cumulativi():
    state = {"#P1": {"name": "Mario", "now": {"gold": 1_500_000_000, "donated": 120_000}}}
    assert progress.deltas(state, "week") == [] and progress.deltas(state, "month") == []
    state["#P1"]["week"] = {"since": 100, "gold": 1_400_000_000, "donated": 119_000}
    assert progress.deltas(state, "week")[0]["gold"] == 100_000_000
    assert progress.deltas(state, "week", 100)[0]["donated"] == 1000
    assert progress.deltas(state, "week", 101) == []


def test_la_settimana_in_corso_riparte_da_zero_dopo_il_cambio():
    tz = "Europe/Rome"
    monday = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    state = progress.update({}, "#P1", "Mario", {"gold": 0}, monday, tz)
    state = progress.update(state, "#P1", "Mario", {"gold": 3_000_000}, monday + timedelta(days=3), tz)
    state = progress.update(state, "#P1", "Mario", {"gold": 3_000_000}, monday + timedelta(days=7), tz)
    assert progress.deltas(state, "week")[0]["loot"] == 0


def test_closed_regge_uno_stato_rotto():
    assert progress.closed(None, "week") == []
    assert progress.closed({"#P1": "rotto"}, "week") == []
    assert progress.closed({"#P1": {"last_week": "rotto"}}, "week") == []
