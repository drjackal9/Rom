from datetime import datetime
from zoneinfo import ZoneInfo

from clashbot import progress, render, scoring

TZ = "Europe/Rome"
ROME = ZoneInfo(TZ)
NEW_TITLES = ("Farmer", "Costruttore", "CampioneGiochi")


def war_season():
    season = scoring.empty_season("2026-08")
    for tag, name, attacks, stars, triples, missed, loot, donations in (
        ("#P1", "Mario", 6, 15, 3, 0, 400_000, 12_000),
        ("#P2", "Luigi", 4, 8, 1, 1, 900_000, 3_000),
        ("#P3", "Peach", 5, 10, 2, 0, 100_000, 25_000),
    ):
        e = scoring.entry(season, tag, name)
        e.update({"wars": 3, "attacks": attacks, "stars": stars, "triples": triples,
                  "missed": missed, "raid_attacks": 6, "loot": loot, "donations": donations})
    scoring.apply_prediction(season, 7, "Toad", True)
    return season


def row(name, **over):
    base = {"name": name, "tag": "#" + name.upper(), "loot": 0, "levels": 0, "th_up": 0, "games": 0,
            "wins": 0, "raid_loot": 0, "score": 0}
    base.update(over)
    base["score"] = progress.score(base)
    return base


def test_titles_without_activity_are_the_old_ones():
    season = war_season()
    plain = scoring.titles(season)
    assert set(plain) == {"MVP", "Cecchino", "Donatore", "Razziatore", "Costante", "Veggente"}
    assert plain["Cecchino"] == ("Mario", 3)
    assert scoring.titles(season, None) == plain
    assert scoring.titles(season, []) == plain


def test_titles_add_the_three_activity_ones_without_touching_the_others():
    season = war_season()
    plain = scoring.titles(season)
    rows = [
        row("Mario", loot=48_000_000, levels=4, games=1_200),
        row("Luigi", loot=12_000_000, levels=31, games=900),
        row("Peach", loot=30_000_000, levels=12, games=4_000),
    ]
    full = scoring.titles(season, rows)
    assert all(full[key] == value for key, value in plain.items())
    assert full["Farmer"] == ("Mario", 48_000_000)
    assert full["Costruttore"] == ("Luigi", 31)
    assert full["CampioneGiochi"] == ("Peach", 4_000)


def test_costruttore_counts_a_town_hall_as_twenty_five_levels():
    rows = [row("Mario", levels=10), row("Luigi", levels=2, th_up=1)]
    assert scoring.activity_titles(rows)["Costruttore"] == ("Luigi", 3)
    rows = [row("Mario", levels=10), row("Luigi", levels=0, th_up=0)]
    assert scoring.activity_titles(rows)["Costruttore"] == ("Mario", 10)


def test_activity_rows_at_zero_give_no_new_titles():
    season = war_season()
    rows = [row("Mario"), row("Luigi")]
    assert scoring.activity_titles(rows) == {}
    assert scoring.titles(season, rows) == scoring.titles(season)
    assert scoring.titles(scoring.empty_season("2026-08"), rows) == {}


def test_activity_titles_ignore_broken_rows():
    assert scoring.activity_titles(["x", None]) == {}
    assert scoring.activity_titles([{"name": "Mario", "loot": None, "games": "boh"}]) == {}
    assert scoring.activity_titles([{"name": "Mario", "loot": 5_000_000}])["Farmer"] == ("Mario", 5_000_000)


def test_titles_consume_the_rows_of_progress_deltas():
    state = {}
    august = datetime(2026, 8, 1, 10, 0, tzinfo=ROME)
    later = datetime(2026, 8, 28, 10, 0, tzinfo=ROME)
    for tag, name in (("#P1", "Mario"), ("#P2", "Luigi")):
        progress.update(state, tag, name, {"gold": 0, "elixir": 0, "games": 0, "levels": 100, "th": 14}, august, TZ)
    progress.update(state, "#P1", "Mario",
                    {"gold": 30_000_000, "elixir": 10_000_000, "games": 3_000, "levels": 104, "th": 15}, later, TZ)
    progress.update(state, "#P2", "Luigi",
                    {"gold": 5_000_000, "elixir": 1_000_000, "games": 100, "levels": 130, "th": 14}, later, TZ)
    result = scoring.titles(scoring.empty_season("2026-08"), progress.deltas(state, "month"))
    assert result["Farmer"] == ("Mario", 40_000_000)
    assert result["Costruttore"] == ("Luigi", 30)
    assert result["CampioneGiochi"] == ("Mario", 3_000)


def test_the_new_titles_have_an_icon_and_a_name():
    for key in NEW_TITLES:
        assert scoring.TITLES[key] == render.title_icon(key)
    assert [scoring.TITLES[key] for key in NEW_TITLES] == ["🏹", "🏗", "🎮"]


def test_the_season_card_shows_the_new_titles():
    from clashbot import i18n
    L = i18n.locale("it")
    season = war_season()
    rows = [row("Mario", loot=48_000_000, levels=4, games=1_200)]
    text = render.season_end_card(L, "2026-08", scoring.titles(season, rows), scoring.leaderboard(season))
    assert "🏹" in text and L.t("title.Farmer") in text
    assert "🎮" in text and L.t("title.CampioneGiochi") in text
