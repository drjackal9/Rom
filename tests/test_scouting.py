import asyncio

from clashbot import render, render_live, scouting, targets
from test_flows import CLAN, FakeStore
from test_war_live import FakePoller, L, snap, tick

CLAN_JSON = {"tag": "#ENEMY", "name": "Clan Nemico", "clanLevel": 18, "warWinStreak": 4,
             "warWins": 120, "warLosses": 60, "warTies": 4, "isWarLogPublic": True,
             "warLeague": {"name": "Master League II"}}
LOG_JSON = {"items": [
    {"result": "win", "clan": {"stars": 28, "attacks": 15}},
    {"result": "lose", "clan": {"stars": 20, "attacks": 15}},
    {"result": None, "clan": {"stars": 12, "attacks": 5}},
]}


def player_json(tag, th, queen):
    return {"tag": tag, "name": tag, "townHallLevel": th, "warStars": 900,
            "heroes": [{"name": "Archer Queen", "level": queen, "village": "home"},
                       {"name": "Battle Machine", "level": 30, "village": "builderBase"}]}


class FakeCoc:
    def __init__(self, clan=CLAN_JSON, log=LOG_JSON, players=None, clan_error=None, log_error=None):
        self.clan_data, self.log_data, self.players = clan, log, players or {}
        self.clan_error, self.log_error = clan_error, log_error
        self.calls = []

    async def clan(self, tag):
        self.calls.append(("clan", tag))
        return self.clan_data, self.clan_error

    async def war_log(self, tag, limit=10):
        self.calls.append(("log", tag))
        return self.log_data, self.log_error

    async def player(self, tag):
        self.calls.append(("player", tag))
        return self.players.get(tag), None


def with_ths(war, ours, theirs):
    for th, m in zip(ours, sorted(war["members"].values(), key=lambda m: m["pos"])):
        m["th"] = th
    for th, m in zip(theirs, sorted(war["defenders"].values(), key=lambda m: m["pos"])):
        m["th"] = th
    return war


def roster_war(size, name_len):
    war = snap("preparation")
    war["members"] = {f"#P{i}": {"name": f"P{i}".ljust(name_len, "o"), "pos": i, "th": 14, "attacks": []}
                      for i in range(1, size + 1)}
    war["defenders"] = {f"#E{i}": {"name": f"E{i}".ljust(name_len, "o"), "pos": i, "th": 16, "attacks": []}
                        for i in range(1, size + 1)}
    return war


def test_the_facts_of_the_opponent_clan_and_of_its_war_log():
    assert scouting.clan_facts(CLAN_JSON)["streak"] == 4
    assert scouting.clan_facts(CLAN_JSON)["public"] is True
    facts = scouting.log_facts(LOG_JSON)
    assert (facts["wins"], facts["losses"], facts["ties"], facts["played"]) == (1, 1, 0, 2)
    assert facts["stars_per_attack"] == 1.6


def test_a_private_war_register_is_declared_not_rounded_to_zero():
    facts = scouting.clan_facts(dict(CLAN_JSON, isWarLogPublic=False))
    assert facts["losses"] is None and facts["ties"] is None and facts["public"] is False
    assert facts["wins"] == 120 and facts["streak"] == 4
    assert scouting.clan_facts(None)["wins"] is None


def test_the_town_hall_picture_and_the_gap_warning():
    war = with_ths(snap("preparation"), [14, 14, 13], [16, 16, 16])
    data = scouting.report({"players": {}}, war, {})
    assert data["ours"] == [[14, 2], [13, 1]] and data["theirs"] == [[16, 3]]
    assert data["our_avg"] == 13.67 and data["their_avg"] == 16.0
    assert data["gap"] == 2
    assert data["harder"] is True and data["easier"] is False
    assert data["mirrors"][0] == {"pos": 1, "name": "Mario", "th": 14, "target": "Bowser",
                                  "target_th": 16, "delta": 2}


def test_a_gap_under_two_says_nothing_and_the_warning_is_symmetric():
    near = scouting.report({"players": {}}, with_ths(snap("preparation"), [15, 15, 14], [16, 16, 16]), {})
    assert near["our_avg"] == 14.67 and near["their_avg"] == 16.0
    assert near["harder"] is False and near["easier"] is False
    ours_up = scouting.report({"players": {}}, with_ths(snap("preparation"), [16, 16, 16], [14, 14, 14]), {})
    assert ours_up["easier"] is True and ours_up["harder"] is False


def test_the_heroes_are_marked_partial_until_the_opponent_roster_is_covered():
    war = with_ths(snap("preparation"), [15, 15, 15], [15, 15, 15])
    ours = {"#P1": {"heroes": {"Archer Queen": 90}}, "#P2": {"heroes": {"Archer Queen": 80}}}
    data = scouting.report({"players": {"#E1": {"heroes": {"Archer Queen": 70}}}}, war, ours)
    assert data["our_heroes"] == 85.0 and data["their_heroes"] == 70.0
    assert data["partial"] is True


def test_the_opponent_roster_is_swept_one_player_per_round_and_only_during_preparation():
    coc = FakeCoc(players={tag: player_json(tag, 16, 90) for tag in ("#E1", "#E2", "#E3")})
    store = FakeStore()
    poller = FakePoller(store, coc=coc)
    t = tick()
    war = with_ths(snap("preparation"), [15, 15, 15], [16, 16, 16])
    for _ in range(3):
        asyncio.run(scouting.tick(poller, t, war, "war", None))
    scout = store.state[(CLAN.alias, scouting.STATE)]
    assert sorted(scout["players"]) == ["#E1", "#E2", "#E3"] and scout["cursor"] == 3
    assert coc.calls.count(("clan", "#ENEMY")) == 1 and coc.calls.count(("log", "#ENEMY")) == 1
    assert [event for event, _tag, _text in poller.sent] == ["war.scout"]
    asyncio.run(scouting.tick(poller, t, war, "war", None))
    assert len(poller.sent) == 1 and len(coc.calls) == 5
    assert asyncio.run(scouting.tick(poller, t, snap(), "war", None)) is None


def test_once_the_card_is_out_the_round_stops_writing_and_stops_calling():
    coc = FakeCoc(players={tag: player_json(tag, 16, 90) for tag in ("#E1", "#E2", "#E3")})
    store = FakeStore()
    poller = FakePoller(store, coc=coc)
    t = tick()
    war = with_ths(snap("preparation"), [15, 15, 15], [16, 16, 16])
    for _ in range(3):
        asyncio.run(scouting.tick(poller, t, war, "war", None))
    written, saved, calls = [], store.set_state, len(coc.calls)

    async def spy(alias, kind, obj):
        written.append(kind)
        await saved(alias, kind, obj)

    store.set_state = spy
    for _ in range(5):
        assert asyncio.run(scouting.tick(poller, t, war, "war", None))["sent"] is True
    assert written == [] and len(coc.calls) == calls


def test_a_private_war_log_does_not_stop_the_scouting():
    coc = FakeCoc(log=None, log_error="private", players={"#E1": player_json("#E1", 16, 90)})
    store = FakeStore()
    poller = FakePoller(store, coc=coc)
    war = with_ths(snap("preparation"), [15, 15, 15], [16, 16, 16])
    asyncio.run(scouting.tick(poller, tick(), war, "war", None))
    assert store.state[(CLAN.alias, scouting.STATE)]["log"] == {"error": "private"}


def test_the_card_started_at_war_time_declares_the_roster_it_could_not_cover():
    coc = FakeCoc(players={"#E1": player_json("#E1", 16, 90)})
    store = FakeStore()
    poller = FakePoller(store, coc=coc)
    t = tick()
    prep = with_ths(snap("preparation"), [15, 15, 15], [16, 16, 16])
    asyncio.run(scouting.tick(poller, t, prep, "war", None))
    assert poller.sent == []
    war = with_ths(snap(), [15, 15, 15], [16, 16, 16])
    asyncio.run(scouting.at_start(poller, t, war, "war", None))
    assert [event for event, _tag, _text in poller.sent] == ["war.scout"]
    assert L.t("scout.partial") in poller.sent[0][2]
    asyncio.run(scouting.at_start(poller, t, war, "war", None))
    assert len(poller.sent) == 1
    asyncio.run(scouting.forget(poller, t))
    assert (CLAN.alias, scouting.STATE) not in store.state


def test_the_scout_card_says_the_gap_and_stays_inside_the_telegram_limit():
    war = with_ths(snap("preparation"), [14, 14, 14], [16, 16, 16])
    scout = {"clan": scouting.clan_facts(CLAN_JSON), "log": scouting.log_facts(LOG_JSON),
             "players": {"#E1": {"heroes": {"Archer Queen": 90}}}}
    text = render_live.scout_card(L, scouting.report(scout, war, {}))
    assert "16" in text and "Bowser" in text and len(text) <= render.MAX_LEN


def test_the_mirrors_are_the_same_positions_of_the_targets_plan():
    war = with_ths(snap("preparation"), [14, 14, 13], [16, 16, 16])
    plan = targets.mirror_plan(war)
    rows = scouting.mirrors(war)
    assert [row["pos"] for row in rows] == sorted(int(pos) for pos in plan)
    assert all(plan[str(row["pos"])]["name"] == row["name"] for row in rows)


def test_every_mismatch_of_a_full_war_stays_on_the_card():
    data = scouting.report({"players": {}}, roster_war(50, 3), {})
    text = render_live.scout_card(L, data)
    assert len(data["mirrors"]) == 50
    assert text.count("➜") == 50 and len(text) <= render.MAX_LEN
    assert "#50" in text


def test_the_mirrors_that_do_not_fit_the_message_are_counted_not_hidden():
    scout = {"clan": scouting.clan_facts(CLAN_JSON), "log": scouting.log_facts(LOG_JSON), "players": {}}
    data = scouting.report(scout, roster_war(50, 15), {})
    text = render_live.scout_card(L, data)
    shown = text.count("➜")
    assert 0 < shown < 50 and len(text) <= render.MAX_LEN
    assert L.t("scout.more", n=50 - shown) in text
