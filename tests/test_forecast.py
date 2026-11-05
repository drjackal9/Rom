import asyncio

from clashbot import forecast, render, render_live, scouting
from clashbot.events_registry import EVENTS
from test_flows import CLAN, FakeStore
from test_scouting import CLAN_JSON, LOG_JSON, with_ths
from test_war_live import FakePoller, L, snap, tick


def report_for(ours, theirs, our_heroes=0.0, their_heroes=0.0, scout=None):
    war = with_ths(snap("preparation"), ours, theirs)
    data = scouting.report(scout or {"clan": scouting.clan_facts(CLAN_JSON),
                                     "log": scouting.log_facts(LOG_JSON), "players": {}}, war, {})
    data["our_heroes"], data["their_heroes"] = our_heroes, their_heroes
    return war, data


def scout_for(data):
    return {"war": "20260912T100000.000Z|#ENEMY", "clan": data["clan"], "log": data["log"],
            "players": {}, "cursor": 3, "sent": True}


def test_the_stars_per_attack_come_from_the_stored_wars():
    records = [{"attacksPerMember": 2, "members": [
        {"tag": "#P1", "name": "Mario", "attacks": [{"stars": 3, "destr": 100}, {"stars": 2, "destr": 70}], "missed": 0},
        {"tag": "#P2", "name": "Luigi", "attacks": [{"stars": 1, "destr": 40}], "missed": 1},
    ]}]
    assert forecast.stars_per_attack(records) == 2.0
    assert forecast.stars_per_attack([]) == forecast.NEUTRAL_STARS


def test_every_term_of_the_estimate_is_visible_and_the_total_stays_between_five_and_ninety_five():
    war, data = report_for([15, 15, 15], [16, 16, 16], our_heroes=200.0, their_heroes=250.0)
    row = forecast.estimate(war, data, 2.4)
    assert dict(row["terms"]) == {"th": -10, "heroes": -5, "history": 2, "streak": -4, "log": 0}
    assert row["probability"] == 33 and row["base"] == 50
    assert row["stars_us"] == 9 and row["stars_them"] == 9
    war, data = report_for([16, 16, 16], [10, 10, 10], our_heroes=400.0, their_heroes=100.0)
    assert forecast.estimate(war, data, 3.0)["probability"] == forecast.CEILING


def test_the_comparison_says_if_the_bot_got_it_right_and_the_ledger_keeps_the_score():
    ended = snap("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]})
    row = forecast.compare({"probability": 70, "stars_us": 9, "stars_them": 6}, ended)
    assert row["result"] == "win" and row["hit"] is True and row["stars_us"] == 3
    ledger = forecast.remember([], dict(row, war="w1"))
    ledger = forecast.remember(ledger, dict(row, war="w2", hit=False))
    assert forecast.accuracy(ledger) == {"total": 2, "hits": 1, "pct": 50}
    assert len(forecast.remember(ledger * 80, dict(row, war="w3"))) == 100


def test_the_estimate_can_only_reach_the_leaders_or_nobody():
    assert EVENTS["war.forecast"]["default"] == "leaders_dm"
    assert set(EVENTS["war.forecast"]["allowed"]) == {"leaders_dm", "off"}
    assert EVENTS["war.forecast_result"]["default"] == "group"


def test_the_estimate_reaches_the_leaders_once_and_the_comparison_goes_out_at_the_end():
    store = FakeStore()
    poller = FakePoller(store)
    war, data = report_for([15, 15, 15], [16, 16, 16])
    scout = scout_for(data)
    t = tick()
    asyncio.run(forecast.at_prep(poller, t, war, scout, "war", None))
    asyncio.run(forecast.at_prep(poller, t, war, scout, "war", None))
    assert [event for event, _tag, _text in poller.sent] == ["war.forecast"]
    ended = snap("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]})
    asyncio.run(forecast.at_end(poller, t, ended, "war", None))
    assert [event for event, _tag, _text in poller.sent] == ["war.forecast", "war.forecast_result"]
    assert (CLAN.alias, forecast.STATE) not in store.state
    assert len(store.state[(CLAN.alias, forecast.LEDGER)]) == 1


def test_the_stored_wars_move_the_estimate_and_with_the_event_off_nothing_is_kept(monkeypatch):
    war, data = report_for([15, 15, 15], [16, 16, 16])
    records = [{"attacksPerMember": 2, "members": [
        {"tag": "#P1", "name": "Mario", "attacks": [{"stars": 3, "destr": 100}, {"stars": 3, "destr": 100}],
         "missed": 0},
    ]}]
    store = FakeStore(wars=records)
    poller = FakePoller(store)
    row = asyncio.run(forecast.at_prep(poller, tick(), war, scout_for(data), "war", None))
    assert dict(row["terms"])["history"] == 5 and row["history"] == 3.0
    monkeypatch.setattr(forecast, "route", lambda conf, event: ("off", None))
    silent = FakePoller(FakeStore())
    assert asyncio.run(forecast.at_prep(silent, tick(), war, scout_for(data), "war", None)) is None
    assert silent.sent == [] and silent.store.state == {}


def test_the_cards_show_how_the_estimate_is_built_and_how_often_the_bot_is_right():
    war, data = report_for([15, 15, 15], [16, 16, 16], our_heroes=200.0, their_heroes=250.0)
    row = forecast.estimate(war, data, 2.4)
    text = render_live.forecast_card(L, row)
    assert "33" in text and "Clan Nemico" in text and len(text) <= render.MAX_LEN
    assert L.t("forecast.term.th", value="-10") in text and L.t("forecast.partial") in text
    result = forecast.compare(row, snap("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]}))
    text = render_live.forecast_result_card(L, result, {"total": 4, "hits": 3, "pct": 75})
    assert "75" in text and len(text) <= render.MAX_LEN
