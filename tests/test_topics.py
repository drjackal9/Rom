import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest

from clashbot import handlers, i18n, topics
from clashbot import settings as settings_mod
from clashbot.poller import Poller, Tick
from test_flows import FakeStore as ChatStore
from test_routing import CLAN, FUTURO, NOW, FakeBot, FakeStore, supervisor_for
from test_settings_ui import SAVED, USER, context, group_update, press_update

IT = i18n.locale("it")
EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))


class ForumBot(FakeBot):
    def __init__(self, forum=True, manage=True):
        super().__init__()
        self.id = 4242
        self.forum = forum
        self.manage = manage
        self.asked = []
        self.created = []
        self.markups = []
        self.dead = None

    async def get_chat(self, chat_id):
        self.asked.append(chat_id)
        return SimpleNamespace(id=chat_id, is_forum=self.forum)

    async def get_chat_member(self, chat_id, user_id):
        self.asked.append((chat_id, user_id))
        return SimpleNamespace(
            status=ChatMemberStatus.ADMINISTRATOR if self.manage else ChatMemberStatus.MEMBER,
            can_manage_topics=self.manage, can_pin_messages=True)

    async def create_forum_topic(self, chat_id, name, icon_color=None):
        self.created.append((chat_id, name, icon_color))
        return SimpleNamespace(message_thread_id=100 + len(self.created))

    async def send_message(self, chat_id, text, message_thread_id=None, disable_notification=None,
                           reply_markup=None, **kw):
        if message_thread_id is not None and message_thread_id == self.dead:
            raise BadRequest("Bad Request: message thread not found")
        self.sent.append((chat_id, text, message_thread_id))
        self.markups.append(reply_markup)
        return SimpleNamespace(message_id=100 + len(self.sent))


def setup(stored=None, bot=None, state=None, now=NOW):
    bot = bot or ForumBot()
    store = FakeStore(state=state)
    poller = Poller(supervisor_for(bot), store, None)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(FUTURO if stored is None else stored, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    return poller, store, bot, t


def with_topics(threads):
    doc = settings_mod.migrate(FUTURO)
    doc["topics"] = dict(threads)
    return doc


def data_of(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


class TopicStore(ChatStore):
    def __init__(self, stored, role="coLeader"):
        super().__init__(state={(CLAN.alias, "settings"): stored,
                                (CLAN.alias, "members"): {"#P1": {"role": role}}},
                         links=[SimpleNamespace(tag="#P1", user_id=USER, dm=True)])
        self.logs = []

    async def add_log(self, alias, entry, at=None):
        self.logs.append(entry)


def ui(stored, bot=None, role="coLeader"):
    store = TopicStore(stored, role)
    ctx = context(store)
    ctx.bot = bot or ForumBot()
    return store, ctx


def press(data):
    update, query = press_update(data)
    update.effective_user.first_name = "Mario"
    return update, query


def test_missing_lists_only_the_packs_without_a_topic():
    assert topics.missing(None) == topics.PACKS
    assert topics.missing({"topics": {"wars": 12}}) == tuple(p for p in topics.PACKS if p != "wars")
    assert topics.missing({"topics": {pack: 1 for pack in topics.PACKS}}) == ()


def test_every_pack_with_a_topic_is_a_pack_the_settings_can_keep():
    assert set(topics.PACKS) <= set(settings_mod.PACKS)
    assert topics.PACKS[:5] == ("wars", "cwl", "capital_games", "members", "challenges")


def test_names_stay_inside_the_telegram_limit_in_every_language():
    for code in i18n.LANGUAGES:
        L = i18n.locale(code)
        for pack in topics.WANTED:
            text = topics.name(L, pack)
            assert text and not text.startswith("[") and len(text) <= topics.NAME_LIMIT


def test_every_topic_has_a_colour_telegram_accepts():
    for pack in topics.WANTED:
        assert topics.COLORS[pack] in set(topics.ICON_COLORS)


def test_thread_for_moves_only_the_group_traffic_of_that_pack():
    conf = with_topics({"wars": 77})
    assert topics.thread_for(conf, "war.start") == 77
    assert topics.thread_for(conf, "members.movement") is None
    assert topics.thread_for(with_topics({}), "war.start") is None
    assert topics.thread_for(None, "war.start") is None


def test_a_thread_bound_by_hand_to_another_pack_keeps_working():
    conf = with_topics({"leaders": 55})
    assert "leaders" not in topics.PACKS
    assert topics.thread_for(conf, "leaders.welcome") == 55


def test_thread_for_leaves_alone_who_chose_another_destination():
    conf = with_topics({"wars": 77})
    conf["routes"]["war.start"] = {"to": "leaders_dm", "intensity": None}
    assert topics.thread_for(conf, "war.start") is None


def test_the_urgent_traffic_lands_in_the_topic_once_it_is_there():
    poller, _, _, t = setup(with_topics({"wars": 42}))
    asyncio.run(poller.dispatch(t, "war.reminder", lambda L: "manca un'ora"))
    assert t.threads == {42: [("reminder", "manca un'ora")]}
    assert t.chunks == []


def test_forget_drops_only_the_dead_thread():
    conf = {"topics": {"wars": 77, "cwl": 78}}
    assert topics.forget(conf, 77) == {"cwl": 78}
    assert topics.forget(conf, 99) == {"wars": 77, "cwl": 78}
    assert topics.forget(None, 77) == {}


def test_is_missing_thread_recognises_the_telegram_wording():
    assert topics.is_missing_thread(BadRequest("Bad Request: message thread not found")) is True
    assert topics.is_missing_thread(BadRequest("TOPIC_DELETED")) is True
    assert topics.is_missing_thread(BadRequest("Chat not found")) is False


def test_can_open_wants_a_forum_and_the_right_to_manage_it():
    assert asyncio.run(topics.can_open(ForumBot(), CLAN.chat_id)) is True
    assert asyncio.run(topics.can_open(ForumBot(forum=False), CLAN.chat_id)) is False
    assert asyncio.run(topics.can_open(ForumBot(manage=False), CLAN.chat_id)) is False
    assert asyncio.run(topics.can_open(FakeBot(), CLAN.chat_id)) is False


def test_open_topic_creates_it_with_its_colour():
    bot = ForumBot()
    thread = asyncio.run(topics.open_topic(bot, CLAN.chat_id, IT, "wars"))
    assert thread == 101
    assert bot.created == [(CLAN.chat_id, topics.name(IT, "wars"), topics.COLORS["wars"])]


def test_the_proposal_carries_the_card_and_its_buttons():
    poller, _, bot, t = setup(with_topics({}))
    assert asyncio.run(topics.propose(poller, t)) is True
    chat, text, thread = bot.sent[0]
    assert (chat, thread) == (CLAN.chat_id, None)
    assert IT.t("topics.title") in text and IT.t("topics.name.wars") in text
    assert data_of(bot.markups[0]) == ["tp:all"] + [f"tp:p:{pack}" for pack in topics.PACKS] + ["tp:no"]


def test_the_proposal_is_made_once_and_never_again():
    poller, store, bot, t = setup(with_topics({}))
    assert asyncio.run(topics.propose(poller, t)) is True
    assert len(bot.sent) == 1
    later = Tick(CLAN, NOW + timedelta(days=3))
    later.settings, later.L, later.tz = t.settings, t.L, t.tz
    assert asyncio.run(topics.propose(poller, later)) is False
    assert len(bot.sent) == 1
    assert store.kv[f"topics:{CLAN.alias}"]["asked"]


def test_the_proposal_stays_quiet_outside_a_forum_and_with_every_topic_already_there():
    poller, _, bot, t = setup(with_topics({}), bot=ForumBot(forum=False))
    assert asyncio.run(topics.propose(poller, t)) is False
    assert bot.sent == []
    poller, _, bot, t = setup(with_topics({pack: 7 for pack in topics.PACKS}))
    assert asyncio.run(topics.propose(poller, t)) is False
    assert bot.sent == [] and bot.asked == []


def test_the_proposal_asks_telegram_at_most_once_a_day_per_clan():
    poller, store, bot, t = setup(with_topics({}), bot=ForumBot(forum=False))
    for _ in range(3):
        assert asyncio.run(topics.propose(poller, t)) is False
    assert bot.asked == [CLAN.chat_id]
    tomorrow = Tick(CLAN, NOW + timedelta(days=1))
    tomorrow.settings, tomorrow.L, tomorrow.tz = t.settings, t.L, t.tz
    assert asyncio.run(topics.propose(poller, tomorrow)) is False
    assert bot.asked == [CLAN.chat_id, CLAN.chat_id]
    assert store.kv[f"topics:{CLAN.alias}"]["day"] == "2026-09-12"


def test_the_daily_diagnosis_is_the_one_that_proposes_them():
    poller, _, bot, t = setup(with_topics({}))
    t.members = {}
    asyncio.run(poller.diagnose(t, False))
    assert [text for _, text, _ in bot.sent if IT.t("topics.title") in text]
    asyncio.run(poller.diagnose(t, False))
    assert len([text for _, text, _ in bot.sent if IT.t("topics.title") in text]) == 1


def test_a_deleted_topic_falls_back_to_the_group_and_is_forgotten():
    bot = ForumBot()
    bot.dead = 77
    poller, store, _, _ = setup(bot=bot, state={(CLAN.alias, "settings"): with_topics({"wars": 77, "cwl": 78})})
    assert asyncio.run(poller.send(CLAN, "guerra", 77)) is True
    assert bot.sent == [(CLAN.chat_id, "guerra", None)]
    assert store.state[(CLAN.alias, "settings")]["topics"] == {"cwl": 78}


def test_the_command_is_in_the_menu_with_its_italian_alias():
    assert ("topics", ["argomenti"]) in handlers.COMMANDS
    assert "cmd.topics" in EN and handlers.HANDLERS["topics"] is handlers.cmd_topics


def test_the_command_shows_what_is_missing_and_what_is_there():
    _, ctx = ui(dict(SAVED, topics={"wars": 42}))
    update = group_update()
    asyncio.run(handlers.cmd_topics(update, ctx))
    text, markup = update.effective_message.sent[0]
    assert IT.t("topics.have") in text and IT.t("topics.none") in text
    assert "tp:p:wars" not in data_of(markup)
    assert "tp:p:cwl" in data_of(markup)


def test_the_command_says_so_when_the_group_has_no_topics():
    _, ctx = ui(dict(SAVED, topics={}), bot=ForumBot(forum=False))
    update = group_update()
    asyncio.run(handlers.cmd_topics(update, ctx))
    assert update.effective_message.sent[0][0] == IT.t("topics.not_forum")


def test_the_command_is_for_who_can_change_the_settings():
    _, ctx = ui(dict(SAVED, topics={}), role="member")
    update = group_update()
    asyncio.run(handlers.cmd_topics(update, ctx))
    assert update.effective_message.sent[0][0] == IT.t("h.admin_only")


def test_the_button_creates_every_missing_topic_and_saves_it():
    store, ctx = ui(dict(SAVED, topics={}))
    update, query = press("tp:all")
    asyncio.run(handlers.on_topics_callback(update, ctx))
    assert [name for _, name, _ in ctx.bot.created] == [topics.name(IT, pack) for pack in topics.PACKS]
    saved = store.state[(CLAN.alias, "settings")]["topics"]
    assert saved == {pack: 101 + index for index, pack in enumerate(topics.PACKS)}
    assert query.answers[0][0] == IT.t("topics.done")


def test_one_button_creates_only_its_own_topic():
    store, ctx = ui(dict(SAVED, topics={}))
    update, query = press("tp:p:cwl")
    asyncio.run(handlers.on_topics_callback(update, ctx))
    assert store.state[(CLAN.alias, "settings")]["topics"] == {"cwl": 101}
    assert data_of(query.edits[0][1]) == ["tp:all"] + [f"tp:p:{pack}" for pack in topics.PACKS
                                                       if pack != "cwl"] + ["tp:no"]


def test_not_now_closes_the_proposal_without_creating_anything():
    _, ctx = ui(dict(SAVED, topics={}))
    update, query = press("tp:no")
    asyncio.run(handlers.on_topics_callback(update, ctx))
    assert ctx.bot.created == []
    assert query.answers[0][0] == IT.t("topics.later")
    assert query.edits[0][1] is None


def test_the_buttons_are_for_who_can_change_the_settings():
    _, ctx = ui(dict(SAVED, topics={}), role="member")
    update, query = press("tp:all")
    asyncio.run(handlers.on_topics_callback(update, ctx))
    assert ctx.bot.created == []
    assert query.answers == [(IT.t("h.admin_only"), True)]


def test_the_group_voice_is_asked_to_say_who_it_is_not_that_it_is_not_an_admin():
    _, ctx = ui(dict(SAVED, topics={}))
    update, query = press_update("tp:all", user_id=handlers.ANONYMOUS_ADMIN_ID)
    asyncio.run(handlers.on_topics_callback(update, ctx))
    assert ctx.bot.created == []
    assert query.answers == [(IT.t("h.anonymous"), True)]
    assert query.edits == []
