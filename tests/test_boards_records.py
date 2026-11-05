import asyncio
from datetime import datetime, timezone

from clashbot import hub, i18n, leaderboards as boards, render, warstats
from test_flows import CLAN, FakeStore

L = i18n.locale("it")
TZ = "Europe/Rome"
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)

FARM = [{"tag": "#P1", "name": "Mario", "value": 12_000_000}]
DONATIONS = [{"tag": "#P2", "name": "Luigi", "value": 4000}]
STREAKS = {"#P3": {"name": "Peach", "streak": 9}, "#P1": {"name": "Mario", "streak": 2}}


def test_record_candidates_reads_the_rows_we_already_build():
    candidates = boards.record_candidates(FARM, DONATIONS, STREAKS)
    assert candidates["farm"] == {"name": "Mario", "value": 12_000_000}
    assert candidates["donations"] == {"name": "Luigi", "value": 4000}
    assert candidates["attack_streak"] == {"name": "Peach", "value": 9}
    assert set(candidates) == set(warstats.VALUE_RECORDS) <= set(warstats.RECORD_KEYS)
    assert boards.record_candidates([], [], {}) == {"farm": None, "donations": None,
                                                    "attack_streak": None}


def test_the_new_records_live_in_the_only_records_dictionary():
    before = warstats.empty_records()
    after = warstats.update_board_records(before, boards.record_candidates(FARM, DONATIONS, STREAKS))
    assert after["farm"] == {"name": "Mario", "value": 12_000_000}
    assert after["perfect"] == before["perfect"] and after["streak"] == before["streak"]
    assert warstats.beaten(before, after) == []
    better = warstats.update_board_records(after, {"farm": {"name": "Luigi", "value": 20_000_000}})
    assert warstats.beaten(after, better) == ["farm"]
    worse = warstats.update_board_records(better, {"farm": {"name": "Toad", "value": 1}})
    assert worse["farm"]["name"] == "Luigi" and warstats.beaten(better, worse) == []
    assert warstats.hall_state({"records": better})["records"]["farm"]["value"] == 20_000_000


def test_the_record_card_says_only_what_broke():
    records = warstats.update_board_records(warstats.empty_records(),
                                            {"farm": {"name": "Mario", "value": 12_000_000}})
    text = render.record_card(L, ["farm"], records)
    assert "Mario" in text and L.t("records.farm").split("{")[0] in text
    assert L.t("records.donations").split("{")[0] not in text
    assert render.record_card(L, [], records) is None


def test_the_hall_shows_the_new_records_next_to_the_old_titles():
    hall = warstats.hall_state({"seasons": [{"season": "2026-08", "titles": {"MVP": ["Mario", 80]}}],
                                "records": {"farm": {"name": "Mario", "value": 12_000_000}}})
    text = render.hall_view(L, hall)
    assert "agosto 2026" in text and "Mario" in text
    assert L.t("records.title") in text
    assert "Vuoto" in render.hall_view(L, warstats.hall_state(None))


def test_the_hall_tab_receives_the_whole_document_titles_and_records():
    stored = warstats.hall_state({"seasons": [{"season": "2026-08", "titles": {"MVP": ["Mario", 80]}}],
                                  "records": {"farm": {"name": "Mario", "value": 12_000_000}}})
    store = FakeStore(state={(CLAN.alias, "hall"): stored})
    data = asyncio.run(hub.sources(store, None, CLAN, "hall", None, NOW, TZ))
    assert data["hall"]["records"]["farm"] == {"name": "Mario", "value": 12_000_000}
    text = asyncio.run(hub.view(L, TZ, "hall", None, data, NOW))
    assert L.t("records.title") in text and "agosto 2026" in text
    empty = asyncio.run(hub.sources(FakeStore(), None, CLAN, "hall", None, NOW, TZ))
    assert "Vuoto" in asyncio.run(hub.view(L, TZ, "hall", None, empty, NOW))
