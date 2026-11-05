import asyncio
from types import SimpleNamespace

from telegram.constants import PollLimit

from clashbot import availability, boards, feed, handlers, polls, render_live, scoring
from clashbot.poller import Poller
from test_flows import CLAN, FakeBot, FakeStore, fake_context, fake_supervisor
from test_scouting import FakeCoc
from test_war_live import FakePoller, L, snap, tick


def link(tag, user_id, name):
    return SimpleNamespace(tag=tag, user_id=user_id, name=name, dm=True)


def test_the_availability_poll_opens_once_per_war_and_says_which_state_it_feeds():
    store, bot = FakeStore(), FakeBot()
    poller = FakePoller(store, bot=bot)
    t = tick()
    war = snap("preparation")
    asyncio.run(availability.open_for(poller, t, war))
    asyncio.run(availability.open_for(poller, t, war))
    assert len(bot.polls) == 1
    chat_id, question, options, kw = bot.polls[0]
    assert chat_id == CLAN.chat_id and len(options) == 3 and kw["is_anonymous"] is False
    assert len(question) <= PollLimit.MAX_QUESTION_LENGTH
    assert all(len(option) <= PollLimit.MAX_OPTION_LENGTH for option in options)
    assert store.kv["poll:pid1"] == {"state": "poll_avail"}
    assert store.refs["poll:pid1"] == CLAN.alias


def test_the_availability_poll_stays_shut_when_the_clan_turned_the_event_off():
    store, bot = FakeStore(), FakeBot()
    poller = FakePoller(store, bot=bot)
    t = tick(stored={"lang": "it", "tz": "Europe/Rome",
                     "routes": {"war.availability": {"to": "off", "intensity": None}}})
    asyncio.run(availability.open_for(poller, t, snap("preparation")))
    assert bot.polls == [] and store.kv == {}
    assert (CLAN.alias, availability.STATE) not in store.state


def test_a_vote_lands_in_the_state_named_by_the_payload():
    store = FakeStore()
    asyncio.run(store.set_state(CLAN.alias, "poll", {"poll_id": "pid9", "votes": {}}))
    asyncio.run(store.set_state(CLAN.alias, "poll_avail", {"poll_id": "pid1", "war": "w", "votes": {}}))
    asyncio.run(store.kv_set("poll:pid1", {"state": "poll_avail"}, ref=CLAN.alias))
    answer = SimpleNamespace(poll_id="pid1", option_ids=[availability.OUT],
                             user=SimpleNamespace(id=5, first_name="Luigi"))
    asyncio.run(polls.record_answer(store, answer))
    assert store.state[(CLAN.alias, "poll_avail")]["votes"] == {"5": {"name": "Luigi", "option": availability.OUT}}
    assert store.state[(CLAN.alias, "poll")]["votes"] == {}
    retracted = SimpleNamespace(poll_id="pid1", option_ids=[],
                                user=SimpleNamespace(id=5, first_name="Luigi"))
    asyncio.run(polls.record_answer(store, retracted))
    assert store.state[(CLAN.alias, "poll_avail")]["votes"] == {}


def test_the_poll_handler_hands_the_vote_to_the_shared_mechanism():
    store = FakeStore()
    asyncio.run(store.set_state(CLAN.alias, availability.STATE, {"poll_id": "pid1", "war": "w", "votes": {}}))
    asyncio.run(store.kv_set("poll:pid1", {"state": availability.STATE}, ref=CLAN.alias))
    answer = SimpleNamespace(poll_id="pid1", option_ids=[availability.IN],
                             user=SimpleNamespace(id=7, first_name="Mario"))
    asyncio.run(handlers.on_poll_answer(SimpleNamespace(poll_answer=answer), fake_context(store)))
    assert store.state[(CLAN.alias, availability.STATE)]["votes"] == {
        "7": {"name": "Mario", "option": availability.IN}}
    stray = SimpleNamespace(poll_id="pid7", option_ids=[availability.OUT],
                            user=SimpleNamespace(id=7, first_name="Mario"))
    asyncio.run(handlers.on_poll_answer(SimpleNamespace(poll_answer=stray), fake_context(store)))
    assert store.state[(CLAN.alias, availability.STATE)]["votes"] == {
        "7": {"name": "Mario", "option": availability.IN}}


def test_a_vote_on_a_poll_opened_before_the_payload_existed_still_feeds_the_prediction():
    store = FakeStore()
    asyncio.run(store.set_state(CLAN.alias, "poll", {"poll_id": "pid1", "votes": {}}))
    asyncio.run(store.kv_set("poll:pid1", {}, ref=CLAN.alias))
    answer = SimpleNamespace(poll_id="pid1", option_ids=[2],
                             user=SimpleNamespace(id=5, first_name="Luigi"))
    asyncio.run(polls.record_answer(store, answer))
    assert store.state[(CLAN.alias, "poll")]["votes"] == {"5": {"name": "Luigi", "option": 2}}


def test_the_roster_check_splits_who_said_no_who_is_out_and_who_kept_quiet():
    war = snap()
    poll = {"war": "w", "votes": {"5": {"name": "Luigi", "option": availability.OUT},
                                  "8": {"name": "Toad", "option": availability.IN}}}
    links = {"#P1": link("#P1", 7, "Mario"), "#P2": link("#P2", 5, "Luigi"), "#P4": link("#P4", 8, "Toad")}
    rows = availability.roster_check(poll, war, links)
    assert rows["out_in_war"] == ["Luigi"]
    assert rows["in_not_in_war"] == ["Toad"]
    assert rows["silent"] == ["Mario"]


def test_at_the_start_the_poll_is_closed_and_the_leaders_get_the_card():
    store, bot = FakeStore(), FakeBot()
    store.links = [link("#P2", 5, "Luigi")]
    poller = FakePoller(store, bot=bot)
    war = snap()
    t = tick(members={"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}})
    asyncio.run(store.set_state(CLAN.alias, availability.STATE, {
        "poll_id": "pid1", "message_id": 1, "war": "20260912T100000.000Z|#ENEMY",
        "votes": {"5": {"name": "Luigi", "option": availability.OUT}},
    }))
    asyncio.run(store.kv_set("poll:pid1", {"state": availability.STATE}, ref=CLAN.alias))
    asyncio.run(availability.settle(poller, t, war, "war", None))
    assert bot.stopped == [(CLAN.chat_id, 1)]
    assert (CLAN.alias, availability.STATE) not in store.state and "poll:pid1" not in store.kv
    assert [event for event, _tag, _text in poller.sent] == ["war.roster"]
    assert "Luigi" in poller.sent[0][2]


def test_when_nobody_is_out_of_step_the_leaders_are_left_alone():
    store, bot = FakeStore(), FakeBot()
    store.links = [link("#P2", 5, "Luigi")]
    poller = FakePoller(store, bot=bot)
    war = snap()
    t = tick(members={"#P2": {"name": "Luigi"}})
    asyncio.run(store.set_state(CLAN.alias, availability.STATE, {
        "poll_id": "pid1", "message_id": 1, "war": "20260912T100000.000Z|#ENEMY",
        "votes": {"5": {"name": "Luigi", "option": availability.IN}},
    }))
    asyncio.run(store.kv_set("poll:pid1", {"state": availability.STATE}, ref=CLAN.alias))
    asyncio.run(availability.settle(poller, t, war, "war", None))
    assert bot.stopped == [(CLAN.chat_id, 1)]
    assert poller.sent == []


def test_the_whole_preparation_to_start_path_opens_the_poll_and_reaches_the_leaders():
    store, bot = FakeStore(), FakeBot()
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    poller = Poller(fake_supervisor(bot), store, FakeCoc())
    t = tick(members={"#P1": {"name": "Mario", "role": "leader"}, "#P2": {"name": "Luigi", "role": "member"}})
    t.season = scoring.empty_season("2026-09")
    asyncio.run(store.set_state(CLAN.alias, "war", snap("notInWar")))
    asyncio.run(poller.track_war(t, snap("preparation"), "war", None))
    assert len(bot.polls) == 1
    assert store.state[(CLAN.alias, availability.STATE)]["war"] == "20260912T100000.000Z|#ENEMY"
    asyncio.run(polls.record_answer(store, SimpleNamespace(
        poll_id="pid1", option_ids=[availability.OUT], user=SimpleNamespace(id=7, first_name="Mario"))))
    t.chunks, t.threads = [], {}
    asyncio.run(poller.track_war(t, snap(), "war", None))
    assert bot.stopped == [(CLAN.chat_id, 1)]
    assert (CLAN.alias, availability.STATE) not in store.state and "poll:pid1" not in store.kv
    saved = store.kv.get(feed.key_of(CLAN.alias, 7)) or {}
    roster = [row["text"] for row in saved.get("rows") or [] if row["kind"] == "war.roster"]
    assert len(roster) == 1 and "Mario" in roster[0]


def test_the_roster_card_is_empty_when_there_is_nothing_to_say():
    assert render_live.roster_card(L, {"out_in_war": [], "in_not_in_war": [], "silent": []}) is None


def test_the_prediction_poll_keeps_scoring_and_announcing_when_it_is_settled():
    store, bot = FakeStore(), FakeBot()
    poller = Poller(fake_supervisor(bot), store, None)
    t = tick()
    t.season = scoring.empty_season("2026-09")
    war = snap("warEnded", our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)]})
    asyncio.run(store.set_state(CLAN.alias, "poll", {
        "war": "20260912T100000.000Z|#ENEMY", "poll_id": "pid1", "message_id": 3,
        "votes": {"5": {"name": "Luigi", "option": 1}, "8": {"name": "Toad", "option": 3}},
    }))
    asyncio.run(store.kv_set("poll:pid1", {"state": "poll"}, ref=CLAN.alias))
    asyncio.run(poller.settle_poll(t, war))
    righe = boards.lines_of(t.boards, "challenges")
    assert len(righe) == 1 and "Luigi" in righe[0] and "Toad" not in righe[0]
    assert t.season["predictions"]["5"] == {"name": "Luigi", "correct": 1, "total": 1}
    assert t.season["predictions"]["8"] == {"name": "Toad", "correct": 0, "total": 1}
    assert bot.stopped == [(CLAN.chat_id, 3)]
    assert (CLAN.alias, "poll") not in store.state and "poll:pid1" not in store.kv


def test_the_prediction_poll_opens_on_the_shared_mechanism_with_its_own_payload():
    store, bot = FakeStore(), FakeBot()
    poller = Poller(fake_supervisor(bot), store, None)
    t = tick()
    asyncio.run(poller.open_poll(t, snap()))
    assert len(bot.polls) == 1
    chat_id, question, options, kw = bot.polls[0]
    assert chat_id == CLAN.chat_id and kw["is_anonymous"] is False
    assert len(options) == scoring.POLL_OPTIONS
    assert store.kv["poll:pid1"] == {"state": "poll"}
    assert store.state[(CLAN.alias, "poll")]["war"] == "20260912T100000.000Z|#ENEMY"
