import asyncio
from types import SimpleNamespace

from telegram import Update
from telegram.constants import PollLimit
from telegram.ext import PollHandler
from test_flows import CLAN, FakeBot, FakeStore, fake_context
from test_routing import ENDED, FUTURO, PREP, STARTED, play
from test_routing import setup as routing_setup
from test_war_live import FakePoller, tick

from clashbot import bot as bot_mod
from clashbot import events_registry, handlers, i18n, survey

IT = i18n.locale("it")


def fake_poll(rows, poll_id="pid1"):
    return SimpleNamespace(
        id=poll_id,
        options=[SimpleNamespace(text=name, voter_count=votes) for name, votes in rows],
    )


VOTED = (("great", 2), ("good", 1), ("meh", 0), ("no", 0))


def test_the_survey_is_due_only_once_and_only_after_a_war():
    assert survey.due(None, war_ended=True)
    assert not survey.due(None, war_ended=False)
    assert not survey.due({"sent": 1000}, war_ended=True)


def test_totals_add_up_across_clans():
    a = survey.record({}, fake_poll([("great", 3), ("good", 1), ("meh", 0), ("no", 1)]))
    b = survey.record({}, fake_poll([("great", 2), ("good", 2), ("meh", 1), ("no", 0)]))
    assert survey.totals([a, b]) == {"great": 5, "good": 3, "meh": 1, "no": 1}
    assert survey.totals([]) == {"great": 0, "good": 0, "meh": 0, "no": 0}
    assert survey.answered([a, b]) == 2
    assert survey.answered([{}, {"counts": {"great": 0, "good": 0, "meh": 0, "no": 0}}]) == 0


def test_the_poll_opens_once_through_the_registry_and_nobody_is_named():
    store, bot = FakeStore(), FakeBot()
    poller = FakePoller(store, bot=bot)
    t = tick()
    assert asyncio.run(survey.open(poller, t))
    assert asyncio.run(survey.open(poller, t)) is None
    assert len(bot.polls) == 1
    chat_id, question, options, kw = bot.polls[0]
    assert chat_id == CLAN.chat_id and kw["is_anonymous"] is True
    assert question == IT.t("survey.question")
    assert options == [IT.t(f"survey.opt.{name}") for name in survey.OPTIONS]
    assert len(options) == 4
    assert len(question) <= PollLimit.MAX_QUESTION_LENGTH
    assert all(len(option) <= PollLimit.MAX_OPTION_LENGTH for option in options)
    assert store.state[(CLAN.alias, survey.STATE)]["sent"]
    assert store.kv["poll:pid1"] == {"state": survey.STATE}


def test_the_survey_stays_shut_when_the_clan_turned_the_event_off():
    store, bot = FakeStore(), FakeBot()
    poller = FakePoller(store, bot=bot)
    t = tick(stored={"lang": "it", "tz": "Europe/Rome",
                     "routes": {survey.EVENT: {"to": "off", "intensity": None}}})
    assert asyncio.run(survey.open(poller, t)) is None
    assert bot.polls == [] and store.kv == {}
    assert (CLAN.alias, survey.STATE) not in store.state


def test_the_totals_come_from_the_poll_update_of_telegram():
    store = FakeStore()
    asyncio.run(store.set_state(CLAN.alias, survey.STATE, {"poll_id": "pid1", "sent": 1000, "votes": {}}))
    asyncio.run(store.kv_set("poll:pid1", {"state": survey.STATE}, ref=CLAN.alias))
    asyncio.run(handlers.on_poll(SimpleNamespace(poll=fake_poll(VOTED)), fake_context(store)))
    assert store.state[(CLAN.alias, survey.STATE)]["counts"] == {"great": 2, "good": 1, "meh": 0, "no": 0}
    assert store.state[(CLAN.alias, survey.STATE)]["sent"] == 1000


def test_a_poll_that_is_not_the_survey_leaves_the_totals_alone():
    store = FakeStore()
    asyncio.run(store.set_state(CLAN.alias, survey.STATE, {"poll_id": "pid1", "sent": 1000}))
    asyncio.run(store.kv_set("poll:pid1", {"state": survey.STATE}, ref=CLAN.alias))
    asyncio.run(store.set_state(CLAN.alias, "poll_avail", {"poll_id": "pid2", "votes": {}}))
    asyncio.run(store.kv_set("poll:pid2", {"state": "poll_avail"}, ref=CLAN.alias))
    for update in (SimpleNamespace(poll=fake_poll(VOTED, poll_id="pid2")),
                   SimpleNamespace(poll=fake_poll(VOTED, poll_id="pid9")),
                   SimpleNamespace(poll=None)):
        asyncio.run(handlers.on_poll(update, fake_context(store)))
    assert "counts" not in store.state[(CLAN.alias, survey.STATE)]
    assert store.state[(CLAN.alias, "poll_avail")] == {"poll_id": "pid2", "votes": {}}


def test_the_bot_asks_telegram_for_the_poll_updates_and_wires_them():
    class App:
        def __init__(self):
            self.handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

    app = App()
    handlers.register(app)
    assert [h.callback for h in app.handlers if isinstance(h, PollHandler)] == [handlers.on_poll]
    assert Update.POLL in bot_mod.ALLOWED_UPDATES


def test_the_survey_is_a_group_event_of_the_registry():
    assert events_registry.EVENTS[survey.EVENT] == {
        "pack": None, "default": "group", "allowed": events_registry.GROUP_ONLY, "intensity": None,
    }


def test_the_real_poller_opens_the_survey_at_the_end_of_the_first_war_and_never_again():
    poller, store, bot, t = routing_setup(FUTURO)
    asyncio.run(play(poller, store, t, [PREP, STARTED, ENDED]))
    opened = store.state[(CLAN.alias, survey.STATE)]
    assert opened["sent"] and len(bot.polls) == 2
    asyncio.run(play(poller, store, t, [STARTED, ENDED]))
    assert store.state[(CLAN.alias, survey.STATE)] == opened
    assert len(bot.polls) == 2
