import asyncio
import json
from types import SimpleNamespace

from telegram.constants import ChatType
from telegram.error import TelegramError

from clashbot import diagnostics, feed, handlers, i18n, render
from clashbot import settings as settings_mod
from clashbot.poller import Poller, Tick
from test_flows import ALIAS, CLAN, FakeStore as ChatStore
from test_routing import FUTURO, MEMBERS, NOW, FakeBot, FakeStore, supervisor_for

IT = i18n.locale("it")
USER = 7
EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))


def conf_of(stored=None):
    return settings_mod.effective(stored or FUTURO, None)


def board_off():
    stored = settings_mod.migrate(FUTURO)
    stored["routes"]["war.board"] = {"to": "off", "intensity": None}
    return stored


class Member:
    def __init__(self, status="administrator", can_pin=True):
        self.status = status
        self.can_pin_messages = can_pin


class CheckBot(FakeBot):
    def __init__(self, member=None, broken=False):
        super().__init__()
        self.id = 4242
        self.member = member if member is not None else Member()
        self.asked = []
        self.broken = broken
        self.supports_inline_queries = True

    async def get_chat_member(self, chat_id, user_id):
        self.asked.append((chat_id, user_id))
        if self.broken:
            raise TelegramError("niente")
        return self.member


def setup(stored=None, member=None, broken=False, state=None, now=NOW):
    store = FakeStore(state=state)
    bot = CheckBot(member, broken)
    poller = Poller(supervisor_for(bot), store, None)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(stored if stored is not None else FUTURO, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.members = dict(MEMBERS)
    return poller, store, bot, t


async def diagnose(poller, t, private=False):
    await poller.diagnose(t, private)
    await poller.flush(t)
    t.chunks, t.threads = [], {}


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_the_board_check_asks_for_the_pin_only_when_the_board_is_on():
    assert diagnostics.board_wanted(conf_of()) is True
    assert diagnostics.board_wanted(conf_of(board_off())) is False


def test_the_inspection_reads_the_membership_of_the_bot():
    bot = CheckBot()
    results = asyncio.run(diagnostics.inspect(bot, CLAN.chat_id, conf_of(), False))
    assert results == {"war_log": True, "admin": True, "pin": True}
    assert bot.asked == [(CLAN.chat_id, bot.id)]


def test_a_bot_that_is_only_a_member_fails_the_administrator_check():
    results = asyncio.run(diagnostics.inspect(CheckBot(Member("member", False)), CLAN.chat_id, conf_of(), False))
    assert results["admin"] is False and results["pin"] is False


def test_an_administrator_without_the_pin_fails_only_the_pin():
    results = asyncio.run(diagnostics.inspect(CheckBot(Member(can_pin=False)), CLAN.chat_id, conf_of(), False))
    assert results["admin"] is True and results["pin"] is False


def test_a_pin_permission_that_telegram_does_not_say_is_not_invented():
    results = asyncio.run(diagnostics.inspect(CheckBot(Member(can_pin=None)), CLAN.chat_id, conf_of(), False))
    assert "pin" not in results and results["admin"] is True


def test_the_pin_is_not_checked_when_the_board_is_off():
    results = asyncio.run(diagnostics.inspect(CheckBot(Member(can_pin=False)), CLAN.chat_id,
                                              conf_of(board_off()), False))
    assert "pin" not in results and results["admin"] is True


def test_the_war_log_is_checked_only_when_we_know_it():
    assert "war_log" not in asyncio.run(diagnostics.inspect(CheckBot(), CLAN.chat_id, conf_of(), None))
    assert asyncio.run(diagnostics.inspect(CheckBot(), CLAN.chat_id, conf_of(), True))["war_log"] is False


def test_a_group_we_cannot_read_leaves_the_checks_unknown():
    results = asyncio.run(diagnostics.inspect(CheckBot(broken=True), CLAN.chat_id, conf_of(), False))
    assert results == {"war_log": True}


def test_only_the_problems_that_are_new_are_told():
    state = {"checked": 0, "checks": {"admin": False, "war_log": True}}
    assert diagnostics.fresh(state, {"admin": False, "war_log": True}) == []
    assert diagnostics.fresh(state, {"admin": False, "war_log": False}) == ["war_log"]
    assert diagnostics.fresh(None, {"admin": False}) == ["admin"]


def test_a_problem_that_goes_away_can_be_told_again():
    state = diagnostics.merged(None, {"admin": False}, 100)
    assert diagnostics.fresh(state, {"admin": True}) == []
    healed = diagnostics.merged(state, {"admin": True}, 200)
    assert diagnostics.fresh(healed, {"admin": False}) == ["admin"]
    assert healed["checked"] == 200


def test_the_diagnosis_waits_a_day():
    assert diagnostics.due(None, 0) is True
    assert diagnostics.due({"checked": 100.0}, 100.0 + diagnostics.PERIOD) is True
    assert diagnostics.due({"checked": 100.0}, 100.0 + diagnostics.PERIOD - 1) is False


def test_the_diagnosis_looks_at_the_group_once_a_day():
    poller, store, bot, t = setup(member=Member(can_pin=False))
    asyncio.run(diagnose(poller, t))
    asyncio.run(diagnose(poller, t))
    assert len(bot.asked) == 1
    assert store.state[(CLAN.alias, "diagnostics")]["checks"] == {"admin": True, "pin": False,
                                                                 "war_log": True}


def test_the_diagnosis_writes_to_the_feed_of_the_managers():
    poller, store, bot, t = setup(member=Member(can_pin=False))
    asyncio.run(diagnose(poller, t))
    assert bot.sent == []
    assert feed_rows(store, 7) == [render.diagnostic_card(IT, ["pin"])]
    assert feed_rows(store, 8) == [render.diagnostic_card(IT, ["pin"])]


def test_the_same_problem_is_not_repeated_the_day_after():
    poller, store, bot, t = setup(member=Member(can_pin=False))
    asyncio.run(diagnose(poller, t))
    bot.sent.clear()
    t.now = NOW.replace(day=NOW.day + 2)
    asyncio.run(diagnose(poller, t))
    assert bot.sent == [] and len(bot.asked) == 2


def test_a_problem_that_comes_back_is_told_again():
    poller, store, bot, t = setup(member=Member(can_pin=False))
    asyncio.run(diagnose(poller, t))
    assert len(feed_rows(store, 7)) == 1
    bot.member = Member()
    t.now = NOW.replace(day=NOW.day + 2)
    asyncio.run(diagnose(poller, t))
    assert len(feed_rows(store, 7)) == 1
    bot.member = Member(can_pin=False)
    t.now = NOW.replace(day=NOW.day + 4)
    asyncio.run(diagnose(poller, t))
    assert feed_rows(store, 7) == [render.diagnostic_card(IT, ["pin"])] * 2


def test_a_clan_without_problems_hears_nothing():
    poller, store, bot, t = setup()
    asyncio.run(diagnose(poller, t))
    assert bot.sent == []
    assert store.state[(CLAN.alias, "diagnostics")]["checks"]["admin"] is True


def test_the_private_war_log_is_a_problem_of_the_diagnosis():
    poller, store, bot, t = setup()
    asyncio.run(diagnose(poller, t, private=True))
    assert bot.sent == []
    assert feed_rows(store, 7) == [render.diagnostic_card(IT, ["war_log"])]
    assert feed_rows(store, 8) == [render.diagnostic_card(IT, ["war_log"])]
    assert render.check_line(IT, "war_log", False).endswith(render.quote(IT.t("war_log.body")))


def test_the_diagnosis_can_be_turned_off_by_the_destination():
    stored = settings_mod.migrate(FUTURO)
    stored["routes"]["system.diagnostic"] = {"to": "off", "intensity": None}
    poller, store, bot, t = setup(stored, member=Member("member", False))
    asyncio.run(diagnose(poller, t))
    assert bot.sent == []


class CheckCoc:
    def __init__(self, error=None):
        self.error = error

    async def current_war(self, tag):
        return (None, self.error) if self.error else ({"state": "inWar"}, None)


class Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)
        return SimpleNamespace(message_id=1)


def check_update(user_id=USER):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=Message(),
    )


def check_context(store, bot=None, coc=None):
    return SimpleNamespace(bot=bot or CheckBot(), bot_data={"store": store, "coc": coc or CheckCoc(),
                                                            "bot_alias": ALIAS},
                           user_data={})


def check_store(role="coLeader", linked=True):
    return ChatStore(
        state={(CLAN.alias, "settings"): settings_mod.migrate(FUTURO),
               (CLAN.alias, "members"): {"#P1": {"role": role}}},
        links=[SimpleNamespace(tag="#P1", user_id=USER, dm=True)] if linked else [],
    )


def run_check(store, bot=None, coc=None, user_id=USER):
    update = check_update(user_id)
    asyncio.run(handlers.cmd_check(update, check_context(store, bot, coc)))
    return update.effective_message.sent


def test_the_check_command_shows_every_control():
    bot = CheckBot(Member(can_pin=False))
    sent = run_check(check_store(), bot)
    assert sent == [render.check_view(IT, {"war_log": True, "admin": True, "pin": False})]
    assert IT.t("check.label.pin") in sent[0] and IT.t("check.fix.pin") in sent[0]
    assert bot.asked == [(CLAN.chat_id, bot.id)]


def test_the_check_command_says_when_all_is_well():
    sent = run_check(check_store())
    assert IT.t("check.ok") in sent[0]


def test_the_check_command_reports_the_private_war_log():
    sent = run_check(check_store(), coc=CheckCoc("private"))
    assert IT.t("war_log.body") in sent[0]


def test_the_check_command_is_for_who_can_change_the_settings():
    sent = run_check(check_store(role="member"))
    assert sent == [IT.t("h.admin_only")]


def test_the_check_command_needs_a_linked_clan():
    store = ChatStore()
    update = SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=999, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=USER, language_code="it"),
        effective_message=Message(),
    )
    asyncio.run(handlers.cmd_check(update, check_context(store)))
    assert update.effective_message.sent == [render.not_linked_view(i18n.locale("it"))]


def test_the_check_command_is_registered_with_its_description():
    assert ("check", ["controllo"]) in handlers.COMMANDS
    assert handlers.HANDLERS["check"] is handlers.cmd_check
    assert "cmd.check" in EN


def test_the_new_keys_are_written_in_italian_and_in_english():
    catalogs = {code: json.load(open(i18n.LOCALE_DIR / f"{code}.json", encoding="utf-8"))
                for code in ("it", "en")}
    keys = ["check.title", "check.ok", "check.unknown", "diagnostic.title", "cmd.check"]
    keys += [f"check.label.{name}" for name in diagnostics.CHECKS]
    keys += ["check.fix.admin", "check.fix.pin"]
    for key in keys:
        assert catalogs["it"][key] and catalogs["en"][key], key
        assert catalogs["it"][key] != catalogs["en"][key], key
