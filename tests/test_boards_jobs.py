import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from clashbot import boards as board_rows, feed, i18n, leaderboards as boards
from clashbot import progress as progress_mod, rankings, render, scoring
from clashbot import settings as settings_mod
from clashbot.poller import Poller, Tick
from test_flows import CLAN, FakeBot, FakeStore, fake_supervisor

L = i18n.locale("it")
TZ = "Europe/Rome"
MONDAY = datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc)
SUNDAY = datetime(2026, 9, 13, 10, tzinfo=timezone.utc)
WEDNESDAY = datetime(2026, 9, 9, 10, tzinfo=timezone.utc)

DELTAS = [{"tag": "#P1", "name": "Mario", "loot": 12_000_000, "dark": 0, "levels": 0, "th_up": 0,
           "wins": 0, "games": 0, "raid_loot": 0, "capital_gold": 0, "donated": 900},
          {"tag": "#P2", "name": "Luigi", "loot": 1_000_000, "dark": 0, "levels": 0, "th_up": 0,
           "wins": 0, "games": 0, "raid_loot": 0, "capital_gold": 0, "donated": 200}]
MEMBERS = {"#P1": {"name": "Mario", "trophies": 5300, "th": 16, "donations": 1200, "received": 300},
           "#P2": {"name": "Luigi", "trophies": 4800, "th": 15, "donations": 800, "received": 900}}
OLD_TROPHIES = {"#P1": {"trophies": 5000}, "#P2": {"trophies": 4900}}


def boards_state():
    state = boards.update_trophies({}, OLD_TROPHIES, SUNDAY, TZ)
    return boards.update_trophies(state, MEMBERS, MONDAY, TZ)


def progress_state():
    counters = {"#P1": ("Mario", 12_000_000, 900, 16), "#P2": ("Luigi", 1_000_000, 200, 15)}
    state = {}
    for tag, (name, _, _, th) in counters.items():
        state = progress_mod.update(state, tag, name, {"gold": 0, "donated": 0, "th": th},
                                    WEDNESDAY, TZ)
    for now in (SUNDAY, MONDAY):
        for tag, (name, gold, donated, th) in counters.items():
            state = progress_mod.update(state, tag, name,
                                        {"gold": gold, "donated": donated, "th": th}, now, TZ)
    return state


STATE = boards_state()

CLAN_RANKING = {"items": [
    {"tag": "#AAA", "name": "Altro", "rank": 3, "clanPoints": 50000},
    {"tag": "#CLAN1", "name": "Nostro Clan", "rank": 42, "clanPoints": 41000},
]}
PLAYER_RANKING = {"items": [
    {"tag": "#P1", "name": "Mario", "rank": 7, "trophies": 6000},
    {"tag": "#X9", "name": "Ignoto", "rank": 9, "trophies": 5900},
]}
PROGRESS = progress_state()
LEADERS = {"#P1": dict(MEMBERS["#P1"], role="leader"), "#P2": dict(MEMBERS["#P2"], role="member")}


def test_place_keeps_only_who_is_in_the_top_the_api_gives():
    assert rankings.place(1) == 1 and rankings.place(rankings.TOP_N) == rankings.TOP_N
    assert rankings.place(rankings.TOP_N + 1) is None
    assert rankings.place(0) is None and rankings.place("x") is None


def test_clan_entry_finds_us_or_nothing():
    assert rankings.clan_entry(CLAN_RANKING, "#CLAN1") == {
        "tag": "#CLAN1", "name": "Nostro Clan", "rank": 42, "best": 42}
    assert rankings.clan_entry(CLAN_RANKING, "#NOPE") is None
    assert rankings.clan_entry({}, "#CLAN1") is None


def test_player_entries_keep_only_our_members():
    found = rankings.player_entries(PLAYER_RANKING, ["#P1", "#P2"])
    assert found == {"#P1": {"tag": "#P1", "name": "Mario", "rank": 7, "best": 7}}
    assert rankings.player_entries(PLAYER_RANKING, []) == {}


def test_changes_report_entries_and_personal_bests_only():
    previous = {"clan": {"rank": 42, "best": 40}, "players": {"#P1": {"rank": 90, "best": 90}}}
    current = {"clan": {"tag": "#CLAN1", "name": "Nostro Clan", "rank": 41, "best": 41},
               "players": {"#P1": {"tag": "#P1", "name": "Mario", "rank": 7, "best": 7},
                           "#P2": {"tag": "#P2", "name": "Luigi", "rank": 150, "best": 150}}}
    merged = rankings.merge(previous, current)
    assert merged["clan"]["best"] == 40 and merged["players"]["#P1"]["best"] == 7
    moves = rankings.changes(previous, merged)
    assert {(m["kind"], m["name"], m["rank"]) for m in moves} == {
        ("player", "Mario", 7), ("player", "Luigi", 150)}
    assert rankings.changes(merged, merged) == []
    assert [m["kind"] for m in rankings.changes({}, merged)] == ["clan", "player", "player"]


def test_a_worse_position_than_the_best_says_nothing():
    previous = {"clan": {"rank": 40, "best": 40}, "players": {}}
    current = {"clan": {"tag": "#CLAN1", "name": "Nostro Clan", "rank": 42, "best": 42},
               "players": {}}
    merged = rankings.merge(previous, current)
    assert merged["clan"]["best"] == 40
    assert rankings.changes(previous, merged) == []
    assert rankings.changes(previous, {"clan": None, "players": {}}) == []


def test_the_closed_window_is_the_period_that_has_just_ended():
    rome = ZoneInfo(TZ)
    start, end = boards.closed_window(MONDAY, TZ, "week")
    assert start.astimezone(rome).strftime("%Y-%m-%d %H:%M") == "2026-09-07 00:00"
    assert end.astimezone(rome).strftime("%Y-%m-%d %H:%M") == "2026-09-14 00:00"
    assert boards.closed_period_id(MONDAY, TZ, "week") == "2026-W37"
    assert boards.period_id(MONDAY, TZ, "week") == "2026-W38"
    first = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    start, end = boards.closed_window(first, TZ, "month")
    assert start.astimezone(rome).strftime("%Y-%m-%d") == "2026-09-01"
    assert end.astimezone(rome).strftime("%Y-%m-%d") == "2026-10-01"


def test_the_week_report_reads_the_trophies_of_the_closed_week():
    rows = boards.closed_trophy_rows(STATE, MEMBERS)
    assert [(r["name"], r["value"], r["delta"]) for r in rows] == [
        ("Mario", 5300, 300), ("Luigi", 4800, -100)]
    assert all(r["delta"] == 0 for r in boards.trophy_rows(STATE, MEMBERS, "week"))
    until = boards.closed_window(MONDAY, TZ, "week")[1].timestamp()
    assert boards.closed_trophy_rows(STATE, MEMBERS, until) == rows
    assert boards.closed_trophy_rows(STATE, MEMBERS, until - 1) == []
    assert boards.closed_trophy_rows({}, MEMBERS) == []


def test_week_report_builds_the_blocks_the_summary_needs():
    report = boards.week_report(STATE, MEMBERS, DELTAS, scoring.empty_season("2026-09"))
    assert [tab for tab, _ in report["blocks"]] == ["farm", "donations", "trophies"]
    assert [r["name"] for r in report["farm"]] == ["Mario", "Luigi"]
    assert [r["name"] for r in report["donations"]] == ["Mario", "Luigi"]
    assert [(r["name"], r["delta"]) for r in report["climb"]] == [("Mario", 300)]
    assert all(len(rows) <= 3 for _, rows in report["blocks"])
    hidden = boards.week_report(STATE, MEMBERS, DELTAS, scoring.empty_season("2026-09"),
                                excluded={"#P1"})
    assert [r["name"] for r in hidden["farm"]] == ["Luigi"] and hidden["climb"] == []


def test_week_report_climbs_by_trophies_and_by_activity_points():
    report = boards.week_report(STATE, MEMBERS, DELTAS, scoring.empty_season("2026-09"))
    assert [(r["name"], r["delta"]) for r in report["climb"]] == [("Mario", 300)]
    assert [(r["name"], r["delta"]) for r in report["climb_points"]] == [("Mario", 24), ("Luigi", 2)]
    hidden = boards.week_report(STATE, MEMBERS, DELTAS, scoring.empty_season("2026-09"),
                                excluded={"#P1"})
    assert [r["name"] for r in hidden["climb_points"]] == ["Luigi"]
    still = boards.week_report(STATE, MEMBERS, [dict(DELTAS[0], loot=0)],
                               scoring.empty_season("2026-09"))
    assert still["climb_points"] == []


def test_week_summary_shows_the_two_climbs_apart():
    blocks = [("farm", [{"name": "Mario", "value": 12_000_000, "delta": 12_000_000, "extra": 0}])]
    text = render.week_summary(L, "questa settimana", blocks, [{"name": "Peach", "delta": 300}],
                               [{"name": "Toad", "delta": 24}])
    assert L.t("boards.climbers") in text and L.t("boards.climbers.points") in text
    assert "Peach" in text and "Toad" in text and "24" in text
    assert len(text) <= render.MAX_LEN
    assert render.week_summary(L, "questa settimana", blocks, [], []) == \
        render.week_summary(L, "questa settimana", blocks, [])


def test_season_leagues_keep_only_who_is_still_in_the_clan():
    players = {"#P1": {"name": "Mario", "league": "Legend League", "trophies": 5600},
               "#P2": {"name": "Luigi", "league": None, "trophies": 4800},
               "#P9": {"name": "Uscito", "league": "Titan League I", "trophies": 5000}}
    assert boards.season_leagues(players, MEMBERS) == [
        {"name": "Mario", "league": "Legend League", "trophies": 5600}]
    assert boards.season_leagues({}, MEMBERS) == []


def test_rank_card_and_summaries_render():
    card = render.rank_card(L, [{"kind": "clan", "name": "Nostro Clan", "rank": 40, "best": 40}])
    assert "Nostro Clan" in card and L.t(f"rank.band.{rankings.TOP_N}") in card
    assert render.rank_card(L, []) is None
    blocks = [("farm", [{"name": "Mario", "value": 12_000_000, "delta": 12_000_000, "extra": 0}]),
              ("donations", [{"name": "Luigi", "value": 900, "delta": 900, "extra": 200}])]
    climb = [{"name": "Peach", "delta": 300}]
    text = render.week_summary(L, "questa settimana", blocks, climb)
    assert "Mario" in text and "Luigi" in text and "Peach" in text
    assert L.t("boards.climbers") in text and L.t("boards.encourage.week") in text
    assert len(text) <= render.MAX_LEN
    mvp = [{"name": "Mario", "total": 207, "parts": {"attacks": 12, "stars": 15, "triples": 9,
                                                     "missed": 0, "raid_attacks": 0, "loot": 12,
                                                     "donations": 9, "farm": 24, "wins": 37,
                                                     "levels": 18, "th_up": 25, "games": 46}}]
    leagues = [{"name": "Mario", "league": "Legend League", "trophies": 5600}]
    text = render.season_summary(L, "2026-09", mvp, leagues)
    assert "Legend League" in text and "Mario" in text and L.t("boards.mvp.title") in text


def test_the_month_titles_card_shows_where_the_mvp_points_come_from():
    titles = {"MVP": ("Mario", 207)}
    parts = {"attacks": 12, "stars": 15, "triples": 9, "missed": -3, "raid_attacks": 6, "loot": 45,
             "donations": 12, "farm": 24, "wins": 37, "levels": 18, "th_up": 25, "games": 7}
    plain = render.season_end_card(L, "2026-09", titles, [])
    text = render.season_end_card(L, "2026-09", titles, [], parts)
    assert L.t("boards.mvp.detail", name="Mario") in text
    assert all(L.t(f"boards.part.{part}") in text for part in boards.MVP_PARTS)
    assert L.t("boards.mvp.detail", name="Mario") not in plain
    assert L.t("season_end.tail") in text and len(text) <= render.MAX_LEN


def test_leader_report_gains_the_donation_debt_without_changing_the_old_output():
    clan = type("C", (), {"name": "Futuro", "tag": "#CLAN1"})()
    assert render.leader_report(L, clan, [], [], [], idle=None, debt=None) == \
        render.leader_report(L, clan, [], [], [])
    text = render.leader_report(L, clan, [], [], [], debt=[{"name": "Toad", "value": 50, "extra": 700}])
    assert L.t("report.debt") in text and "Toad" in text


class Coc:
    def __init__(self, clans=None, players=None, error=None):
        self.clans = clans
        self.players = players
        self.error = error
        self.calls = []

    async def goldpass(self):
        return {"endTime": None}, None

    async def location_clans(self, location_id, limit=200):
        self.calls.append(("clans", location_id, limit))
        return copy.deepcopy(self.clans), self.error

    async def location_players(self, location_id, limit=200):
        self.calls.append(("players", location_id, limit))
        return copy.deepcopy(self.players), self.error


def setup(now=MONDAY, state=None, coc=None, stored=None, links=(), board_state=None):
    stored_state = {(CLAN.alias, "progress"): copy.deepcopy(PROGRESS),
                    (CLAN.alias, boards.STATE_KIND): copy.deepcopy(
                        STATE if board_state is None else board_state)}
    stored_state.update(state or {})
    store = FakeStore(state=stored_state, links=list(links))
    bot = FakeBot()
    poller = Poller(fake_supervisor(bot), store, coc or Coc())
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(stored or {"lang": "it", "tz": TZ}, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.members = copy.deepcopy(MEMBERS)
    t.season = scoring.empty_season("2026-09")
    return poller, store, t


def section(t, pack):
    return board_rows.lines_of(t.boards, pack)


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_track_boards_publishes_the_week_once_on_monday_morning():
    poller, store, t = setup()
    assert progress_mod.deltas(PROGRESS, "week")[0]["score"] == 0
    asyncio.run(poller.track_boards(t))
    texts = section(t, "challenges")
    assert len(texts) == 1 and "Mario" in texts[0]
    assert L.t("boards.climbers.points") in texts[0] and "Luigi" in texts[0]
    assert "12,0M" in texts[0] and "+300" in texts[0]
    state = store.state[(CLAN.alias, boards.STATE_KIND)]
    assert state["sent"]["week"] == boards.closed_period_id(t.now, TZ, "week")
    assert state["sent"]["week"] != boards.period_id(t.now, TZ, "week")
    assert state["trophies"]["week"]["base"] == {"#P1": 5300, "#P2": 4800}
    assert store.stats[(CLAN.alias, "boards_week", state["sent"]["week"])][1]["farm"]
    asyncio.run(poller.track_boards(t))
    assert len(section(t, "challenges")) == 1


def test_without_the_closed_week_the_summary_has_nothing_to_say():
    poller, store, t = setup(state={(CLAN.alias, "progress"): {}}, board_state={})
    asyncio.run(poller.track_boards(t))
    texts = section(t, "challenges")
    assert len(texts) == 1 and L.t("boards.empty") in texts[0]
    assert "Mario" not in texts[0] and "Luigi" not in texts[0]


def test_the_weekly_report_refreshes_the_network_load_of_who_joined():
    poller, store, t = setup()
    asyncio.run(store.network_set(CLAN.alias, True, True, {"name": CLAN.name, "week": "vecchia"}))
    asyncio.run(poller.track_boards(t))
    row = store.network[CLAN.alias]
    assert row["week"] == boards.closed_period_id(t.now, TZ, "week") and row["named"] is True
    assert row["metrics"] == {"members": 2, "avg": 13.0, "stars": 0, "donations": 1100}
    assert "#P1" not in repr(row["metrics"])


def test_the_weekly_report_leaves_alone_who_is_out_of_the_network():
    poller, store, t = setup()
    asyncio.run(poller.track_boards(t))
    assert store.network == {}


def test_track_boards_says_nothing_before_monday_morning():
    poller, store, t = setup(now=MONDAY - timedelta(days=1))
    asyncio.run(poller.track_boards(t))
    assert t.chunks == [] and t.boards is None
    assert store.state[(CLAN.alias, boards.STATE_KIND)]["trophies"]["week"]["base"]


def test_check_rankings_needs_a_country_and_talks_only_when_we_climb():
    coc = Coc(clans=CLAN_RANKING, players=PLAYER_RANKING)
    poller, store, t = setup(state={(CLAN.alias, "info"): {"location": {"id": 32000113,
                                                                       "isCountry": False}}}, coc=coc)
    assert asyncio.run(poller.check_rankings(t, {})) == {}
    assert coc.calls == [] and t.boards is None
    poller, store, t = setup(state={(CLAN.alias, "info"): {"location": {"id": 32000113,
                                                                       "isCountry": True}}}, coc=coc)
    state = asyncio.run(poller.check_rankings(t, {}))
    assert coc.calls == [("clans", 32000113, rankings.TOP_N), ("players", 32000113, rankings.TOP_N)]
    assert state["ranks"]["clan"]["rank"] == 42 and list(state["ranks"]["players"]) == ["#P1"]
    righe = section(t, "members")
    assert len(righe) == 1 and "Nostro Clan" in righe[0] and "Mario" in righe[0]
    assert asyncio.run(poller.check_rankings(t, state))["ranks"] == state["ranks"]
    assert len(section(t, "members")) == 1


def test_the_leader_report_carries_the_donation_debt():
    link = SimpleNamespace(tag="#P1", user_id=7, dm=True, lang=None)
    poller, store, t = setup(state={(CLAN.alias, "members"): copy.deepcopy(LEADERS)}, links=[link])
    t.members = copy.deepcopy(LEADERS)
    asyncio.run(poller.leader_report(t))
    assert len(feed_rows(store, 7)) == 1
    assert L.t("report.debt") in feed_rows(store, 7)[0] and "Luigi" in feed_rows(store, 7)[0]
    poller, store, t = setup(state={(CLAN.alias, "members"): copy.deepcopy(LEADERS)}, links=[link],
                             stored={"lang": "it", "tz": TZ,
                                     "routes": {"boards.donations": {"to": "off", "intensity": None}}})
    t.members = copy.deepcopy(LEADERS)
    asyncio.run(poller.leader_report(t))
    assert len(feed_rows(store, 7)) == 1 and L.t("report.debt") not in feed_rows(store, 7)[0]
