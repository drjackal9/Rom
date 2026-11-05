import inspect

from clashbot import leaderboards as boards, progress, scoring

DELTAS = [
    {"tag": "#P1", "name": "Mario", "loot": 12_300_000, "dark": 800_000, "levels": 6, "th_up": 0,
     "wins": 37, "games": 4000, "raid_loot": 120_000, "capital_gold": 50_000, "donated": 900},
    {"tag": "#P2", "name": "Luigi", "loot": 2_000_000, "dark": 0, "levels": 14, "th_up": 1,
     "wins": 3, "games": 0, "raid_loot": 0, "capital_gold": 0, "donated": 200},
    {"tag": "#P3", "name": "Peach", "loot": 0, "dark": 0, "levels": 0, "th_up": 0,
     "wins": 12, "games": 500, "raid_loot": 0, "capital_gold": 0, "donated": 0},
]
MEMBERS = {
    "#P1": {"name": "Mario", "trophies": 5400, "th": 16, "donations": 1200, "received": 300},
    "#P2": {"name": "Luigi", "trophies": 5100, "th": 15, "donations": 800, "received": 900},
    "#P3": {"name": "Peach", "trophies": 4700, "th": 14, "donations": 400, "received": 100},
    "#P4": {"name": "Toad", "trophies": 4200, "th": 13, "donations": 50, "received": 700},
}
STATS = {
    "#P1": {"name": "Mario", "wars": 3, "attacks": 6, "stars": 15, "triples": 3, "missed": 0,
            "destr": 540.0, "expected": 6},
    "#P2": {"name": "Luigi", "wars": 3, "attacks": 4, "stars": 8, "triples": 1, "missed": 1,
            "destr": 300.0, "expected": 6},
}


def season_state():
    season = scoring.empty_season("2026-09")
    for tag, name, attacks, stars, triples, missed, loot, donations in (
        ("#P1", "Mario", 6, 15, 3, 0, 450_000, 1200),
        ("#P2", "Luigi", 4, 8, 1, 1, 100_000, 800),
    ):
        e = scoring.entry(season, tag, name)
        e.update({"wars": 3, "attacks": attacks, "stars": stars, "triples": triples, "missed": missed,
                  "raid_attacks": 6, "loot": loot, "donations": donations})
    return season


def test_metric_rows_drop_zeroes_and_sort():
    farm = boards.metric_rows("farm", DELTAS)
    assert [(r["name"], r["value"], r["extra"]) for r in farm] == [
        ("Mario", 12_300_000, 800_000), ("Luigi", 2_000_000, 0)]
    upgrade = boards.metric_rows("upgrade", DELTAS)
    assert [(r["name"], r["value"], r["extra"]) for r in upgrade] == [("Luigi", 14, 1), ("Mario", 6, 0)]
    capital = boards.metric_rows("capital", DELTAS)
    assert [(r["name"], r["value"]) for r in capital] == [("Mario", 120_000)]
    wins = boards.metric_rows("wins", DELTAS)
    assert [(r["name"], r["value"], r["extra"]) for r in wins] == [("Mario", 37, 0), ("Peach", 12, 0), ("Luigi", 3, 0)]
    games = boards.metric_rows("games", DELTAS)
    assert [(r["name"], r["value"]) for r in games] == [("Mario", 4000), ("Peach", 500)]


def test_metric_rows_honour_the_exclusion_list():
    assert boards.metric_rows("farm", DELTAS, excluded={"#P1"})[0]["name"] == "Luigi"


def test_donation_rows_use_the_month_counter_and_the_week_delta():
    month = boards.donation_rows("month", DELTAS, season_state(), MEMBERS)
    assert [(r["name"], r["value"], r["extra"]) for r in month] == [
        ("Mario", 1200, 300), ("Luigi", 800, 900)]
    week = boards.donation_rows("week", DELTAS, season_state(), MEMBERS)
    assert [(r["name"], r["value"], r["extra"]) for r in week] == [
        ("Mario", 900, 300), ("Luigi", 200, 900)]


def test_star_rows_rank_by_stars_then_triples():
    rows = boards.star_rows(STATS)
    assert [(r["name"], r["value"], r["delta"], r["extra"]) for r in rows] == [
        ("Mario", 15, 3, 6), ("Luigi", 8, 1, 4)]
    assert boards.star_rows({}) == []


def test_donation_debt_lists_only_who_received_more():
    rows = boards.donation_debt(MEMBERS)
    assert [(r["name"], r["value"], r["extra"]) for r in rows] == [("Toad", 50, 700), ("Luigi", 800, 900)]
    assert boards.donation_debt(MEMBERS, excluded={"#P4"})[0]["name"] == "Luigi"


def test_window_entries_month_is_the_stored_season():
    season = season_state()
    entries = boards.window_entries("month", season, STATS, DELTAS)
    assert entries["#P1"]["loot"] == 450_000 and entries["#P1"]["raid_attacks"] == 6
    assert entries is not season["members"]


def test_window_entries_week_are_rebuilt_from_wars_and_deltas():
    entries = boards.window_entries("week", season_state(), STATS, DELTAS)
    assert entries["#P1"]["attacks"] == 6 and entries["#P1"]["stars"] == 15
    assert entries["#P1"]["loot"] == 120_000 and entries["#P1"]["donations"] == 900
    assert entries["#P1"]["raid_attacks"] == 0
    assert entries["#P3"]["attacks"] == 0 and entries["#P3"]["name"] == "Peach"


def test_mvp_parts_are_declared_and_sum_to_the_total():
    rows = boards.mvp_rows("month", season_state(), STATS, DELTAS)
    top = rows[0]
    assert top["name"] == "Mario"
    assert set(top["parts"]) == set(boards.MVP_PARTS)
    assert top["total"] == sum(top["parts"].values()) == top["value"]
    assert top["parts"]["loot"] == 45
    assert top["parts"]["farm"] == 24 and top["parts"]["wins"] == 37
    assert top["parts"]["levels"] == 18 and top["parts"]["games"] == 40
    assert "raid_loot" not in top["parts"]
    assert set(boards.MVP_WEIGHTS) == set(boards.MVP_PARTS)


def test_mvp_counts_capital_loot_once_in_every_window():
    week = {r["name"]: r for r in boards.mvp_rows("week", season_state(), STATS, DELTAS)}
    assert week["Mario"]["parts"]["loot"] == 12
    assert week["Mario"]["parts"]["raid_attacks"] == 0
    assert week["Mario"]["total"] == sum(week["Mario"]["parts"].values())


def test_mvp_ranks_and_excludes():
    rows = boards.mvp_rows("month", season_state(), STATS, DELTAS)
    assert [r["name"] for r in rows] == ["Mario", "Luigi"]
    assert all(rows[i]["total"] >= rows[i + 1]["total"] for i in range(len(rows) - 1))
    assert "Mario" not in [r["name"] for r in boards.mvp_rows("month", season_state(), STATS, DELTAS,
                                                              excluded={"#P1"})]
    week = boards.mvp_rows("week", season_state(), STATS, DELTAS)
    assert [r["name"] for r in week] == ["Mario", "Luigi", "Peach"]


def test_climbers_take_the_three_biggest_gains():
    rows = [{"name": "A", "delta": 300}, {"name": "B", "delta": -50},
            {"name": "C", "delta": 120}, {"name": "D", "delta": 0}, {"name": "E", "delta": 900}]
    assert [r["name"] for r in boards.climbers(rows)] == ["E", "A", "C"]
    assert boards.climbers([{"name": "B", "delta": -1}]) == []


def test_titles_take_the_mvp_from_outside_when_given():
    season = season_state()
    plain = scoring.titles(season)
    assert plain["MVP"][0] == "Mario"
    given = scoring.titles(season, None, mvp=("Luigi", 999))
    assert given["MVP"] == ("Luigi", 999)
    assert {k: v for k, v in given.items() if k != "MVP"} == {k: v for k, v in plain.items() if k != "MVP"}


def test_the_mvp_keeps_the_place_free_like_the_wall():
    params = inspect.signature(scoring.titles).parameters
    assert [p.name for p in params.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)] == ["season", "activity"]
    assert params["mvp"].kind is params["mvp"].KEYWORD_ONLY
    assert params["wall"].kind is params["wall"].KEYWORD_ONLY


def test_progress_parts_and_mvp_weights_agree():
    assert boards.MVP_WEIGHTS["farm"] == 2 and boards.MVP_WEIGHTS["th_up"] == 25
    assert progress.parts({"loot": 1_000_000})["loot"] == boards.MVP_WEIGHTS["farm"]
