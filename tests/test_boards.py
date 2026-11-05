from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from clashbot import agenda, leaderboards as boards, progress, scoring

TZ = "Europe/Rome"
ROME = ZoneInfo(TZ)


def test_season_window_brackets_now():
    now = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
    start, end = agenda.season_window(now)
    assert start.weekday() == 0 and end.weekday() == 0
    assert start.hour == 5 and end.hour == 5
    assert start <= now < end
    assert start == datetime(2026, 8, 31, 5, tzinfo=timezone.utc)
    assert end == agenda.season_end(now)


def test_season_window_after_the_last_monday_moves_to_the_new_season():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    start, end = agenda.season_window(now)
    assert start == datetime(2026, 9, 28, 5, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 26, 5, tzinfo=timezone.utc)


def test_season_end_is_unchanged():
    for day in range(1, 29):
        now = datetime(2026, 9, day, 12, tzinfo=timezone.utc)
        assert agenda.season_end(now) > now
        assert agenda.season_window(now)[1] == agenda.season_end(now)
    end = "20260920T050000.000Z"
    assert agenda.season_end(datetime(2026, 9, 13, 12, tzinfo=timezone.utc), end).day == 20


def test_progress_gains_a_season_period():
    assert progress.PERIODS == ("week", "month", "season")
    now = datetime(2026, 9, 13, 12, tzinfo=ROME)
    counters = {k: 0 for k in progress.COUNTERS}
    counters["gold"] = 1000
    state = progress.update({}, "#P1", "Mario", counters, now, TZ)
    assert set(progress.PERIODS) <= set(state["#P1"])
    assert state["#P1"]["season"]["since"] == int(now.timestamp())
    assert state["#P1"]["season"]["gold"] == 1000
    counters["gold"] = 4000
    progress.update(state, "#P1", "Mario", counters, now + timedelta(days=1), TZ)
    assert progress.deltas(state, "season")[0]["gold"] == 3000
    assert progress.period_start(now, TZ, "season") == int(
        agenda.season_start(now.astimezone(timezone.utc)).timestamp())


def test_progress_entries_already_stored_gain_the_season_key():
    now = datetime(2026, 9, 13, 12, tzinfo=ROME)
    counters = {k: 0 for k in progress.COUNTERS}
    counters["gold"] = 1000
    state = progress.update({}, "#P2", "Luigi", counters, now, TZ)
    del state["#P2"]["season"]
    later = now + timedelta(hours=1)
    progress.update(state, "#P2", "Luigi", counters, later, TZ)
    assert state["#P2"]["season"]["since"] == int(later.timestamp())
    assert state["#P2"]["week"]["since"] == int(now.timestamp())


def test_point_parts_sum_to_points():
    e = {"name": "Mario", "wars": 3, "attacks": 6, "stars": 15, "triples": 3, "missed": 1,
         "raid_attacks": 6, "loot": 450_000, "donations": 12_345}
    parts = scoring.point_parts(e)
    assert parts == {"attacks": 12, "stars": 15, "triples": 9, "missed": -3,
                     "raid_attacks": 6, "loot": 45, "donations": 123}
    assert scoring.points(e) == sum(parts.values()) == 207


def test_progress_parts_sum_to_score():
    delta = {"loot": 12_300_000, "wins": 37, "levels": 6, "th_up": 1, "games": 4000, "raid_loot": 120_000}
    parts = progress.parts(delta)
    assert parts == {"loot": 24, "wins": 37, "levels": 18, "th_up": 25, "games": 40, "raid_loot": 1}
    assert progress.score(delta) == sum(parts.values())
    assert progress.parts({}) == {"loot": 0, "wins": 0, "levels": 0, "th_up": 0, "games": 0, "raid_loot": 0}


def test_window_and_period_id():
    now = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
    start, end = boards.window(now, TZ, "week")
    assert start == datetime(2026, 9, 7, 0, tzinfo=ROME) and end == now
    assert boards.window(now, TZ, "month")[0] == datetime(2026, 9, 1, 0, tzinfo=ROME)
    assert boards.window(now, TZ, "season") == agenda.season_window(now)
    assert boards.period_id(now, TZ, "week") == "2026-W37"
    assert boards.period_id(now, TZ, "month") == "2026-09"
    assert boards.period_id(now, TZ, "season") == "2026-09"
    assert boards.default_period("mvp") == "month" and boards.default_period("hall") is None
    assert boards.TAB_PERIODS["points"] == ("month",)


def test_the_state_kind_does_not_step_on_the_pinned_boards():
    from clashbot import boards as pinned
    assert boards is not pinned
    assert boards.STATE_KIND != "boards"
    assert not hasattr(pinned, "TAB_PERIODS")


def members_snapshot(**trophies):
    return {tag: {"name": name, "trophies": value, "th": 15}
            for tag, (name, value) in trophies.items()}


def test_update_trophies_creates_then_keeps_the_baseline():
    now = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
    members = members_snapshot(P1=("Mario", 5000), P2=("Luigi", 4000))
    state = boards.update_trophies({}, members, now, TZ)
    assert set(state["trophies"]) == set(boards.PERIODS)
    assert state["trophies"]["week"]["base"] == {"P1": 5000, "P2": 4000}
    grown = members_snapshot(P1=("Mario", 5300), P2=("Luigi", 3800))
    state = boards.update_trophies(state, grown, now, TZ)
    rows = boards.trophy_rows(state, grown, "week")
    assert [(r["name"], r["value"], r["delta"]) for r in rows] == [("Mario", 5300, 300), ("Luigi", 3800, -200)]


def test_update_trophies_rebases_on_the_new_week_and_drops_former_members():
    monday = datetime(2026, 9, 7, 9, tzinfo=ROME)
    state = boards.update_trophies({}, members_snapshot(P1=("Mario", 5000), P2=("Luigi", 4000)), monday, TZ)
    next_monday = monday + timedelta(days=7)
    state = boards.update_trophies(state, members_snapshot(P1=("Mario", 5400)), next_monday, TZ)
    assert state["trophies"]["week"]["base"] == {"P1": 5400}
    assert state["trophies"]["month"]["base"] == {"P1": 5000}
    assert boards.trophy_rows(state, members_snapshot(P1=("Mario", 5400)), "week")[0]["delta"] == 0
    assert boards.trophy_rows(state, members_snapshot(P1=("Mario", 5400)), "month")[0]["delta"] == 400


def test_new_member_joins_with_his_own_baseline():
    now = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
    state = boards.update_trophies({}, members_snapshot(P1=("Mario", 5000)), now, TZ)
    later = members_snapshot(P1=("Mario", 5100), P3=("Peach", 4700))
    state = boards.update_trophies(state, later, now, TZ)
    rows = {r["name"]: r["delta"] for r in boards.trophy_rows(state, later, "week")}
    assert rows == {"Mario": 100, "Peach": 0}
