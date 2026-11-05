import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from clashbot import boards, i18n, night, setup_ui
from clashbot import settings as settings_mod
from clashbot.poller import Poller, Tick
from clashbot.util import now_utc

NOW = datetime(2026, 9, 13, 2, tzinfo=timezone.utc)
IT = i18n.locale("it")
EN = i18n.locale("en")
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")


class FakeStore:
    def __init__(self, state=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def links_by_user(self, user_id):
        return []


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, disable_notification=False, **kw):
        self.sent.append((chat_id, text, bool(disable_notification)))
        return SimpleNamespace(message_id=len(self.sent))


def fake_poller(state=None):
    bot = FakeBot()
    supervisor = SimpleNamespace(bot=lambda alias: bot, running=lambda: [CLAN.bot_alias],
                                 default_alias=CLAN.bot_alias, owner_bot=lambda: bot)
    store = FakeStore(state=state)
    return Poller(supervisor, store, None), store, bot


def tick(mode_value, in_quiet):
    t = Tick(CLAN, NOW)
    t.settings = settings_mod.effective(
        {"lang": "it", "tz": "Europe/Rome", "quiet": [23, 7], "night": mode_value}, None)
    t.L = IT
    t.tz = "Europe/Rome"
    t.quiet = in_quiet
    return t


def all_night(tz="Europe/Rome"):
    hour = now_utc().astimezone(ZoneInfo(tz)).hour
    return [hour, (hour + 1) % 24]


def setup_state(stored=None):
    conf = settings_mod.effective(dict({"lang": "it", "tz": "Europe/Rome"}, **(stored or {})), None)
    return setup_ui.from_settings(conf, CLAN.alias, 7)


def test_mode_falls_back_to_silent():
    assert night.mode(None) == "silent"
    assert night.mode({}) == "silent"
    assert night.mode({"night": "boh"}) == "silent"
    assert night.mode({"night": "digest"}) == "digest"
    assert night.mode({"night": "silent"}) == "silent"


def test_next_mode_cycles_the_two_modes():
    assert night.next_mode("silent") == "digest"
    assert night.next_mode("digest") == "silent"
    assert night.next_mode(None) == "digest"


def test_defers_only_in_digest_mode_and_only_at_night():
    assert night.defers({"night": "digest"}, True) is True
    assert night.defers({"night": "digest"}, False) is False
    assert night.defers({"night": "silent"}, True) is False
    assert night.defers(None, True) is False


def test_the_label_names_the_mode_in_the_language_of_the_clan():
    assert night.label(IT, {"night": "digest"}) == IT.t("night.mode.digest")
    assert night.label(IT, None) == IT.t("night.mode.silent")
    assert night.label(EN, {"night": "silent"}) == EN.t("night.mode.silent")
    assert IT.t("night.mode.digest") != EN.t("night.mode.digest")


def test_effective_drops_a_broken_night_mode():
    assert settings_mod.effective({"night": "boh"}, None)["night"] is None
    assert settings_mod.effective({"night": "digest"}, None)["night"] == "digest"


def test_migration_keeps_the_digest_for_who_already_sleeps():
    migrated = settings_mod.migrate({"quiet": [23, 7], "defenses": True})
    assert migrated["night"] == "digest"
    assert settings_mod.migrate(migrated)["night"] == "digest"
    assert settings_mod.migrate({"defenses": True})["night"] is None
    assert night.mode(settings_mod.migrate({"defenses": True})) == "silent"


def test_a_clan_that_already_answered_keeps_its_answer_when_it_picks_the_quiet_hours():
    assert settings_mod.migrate({"night": None, "quiet": [23, 7]})["night"] is None
    assert settings_mod.migrate({"night": "silent", "quiet": [23, 7]})["night"] == "silent"


def test_silent_mode_sends_everything_at_once_without_sound():
    poller, store, bot = fake_poller()
    t = tick("silent", True)
    t.chunks = [("reminder", "promemoria"), ("members", "movimenti")]
    asyncio.run(poller.flush(t))
    assert bot.sent == [(CLAN.chat_id, "promemoria\n\nmovimenti", True)]
    assert (CLAN.alias, "queue") not in store.state


def test_digest_mode_still_queues_and_the_urgent_goes_out_silent():
    poller, store, bot = fake_poller()
    t = tick("digest", True)
    t.chunks = [("reminder", "promemoria"), ("members", "movimenti")]
    asyncio.run(poller.flush(t))
    assert bot.sent == [(CLAN.chat_id, "promemoria", True)]
    assert store.state[(CLAN.alias, "queue")] == ["movimenti"]


def test_the_morning_digest_goes_out_with_its_sound():
    poller, store, bot = fake_poller(state={(CLAN.alias, "queue"): ["movimenti"]})
    asyncio.run(poller.flush(tick("digest", False)))
    assert bot.sent[0][0] == CLAN.chat_id
    assert bot.sent[0][2] is False
    assert (CLAN.alias, "queue") not in store.state


def test_a_queue_left_over_from_the_digest_empties_without_sound_at_night():
    poller, store, bot = fake_poller(state={(CLAN.alias, "queue"): ["movimenti"]})
    asyncio.run(poller.flush(tick("silent", True)))
    assert bot.sent and [silent for _, _, silent in bot.sent] == [True]
    assert (CLAN.alias, "queue") not in store.state


def test_deliver_follows_the_mode_too_for_the_urgent():
    conf = {"lang": "it", "tz": "Europe/Rome", "quiet": all_night(), "night": "silent"}
    poller, store, bot = fake_poller(state={(CLAN.alias, "settings"): conf})
    asyncio.run(poller.deliver(CLAN, "manca un'ora", "war.reminder"))
    assert bot.sent == [(CLAN.chat_id, "manca un'ora", True)]
    assert (CLAN.alias, "queue") not in store.state
    store.state[(CLAN.alias, "settings")]["night"] = "digest"
    bot.sent.clear()
    asyncio.run(poller.deliver(CLAN, "manca un'ora", "war.reminder"))
    assert bot.sent == []
    assert store.state[(CLAN.alias, "queue")] == ["manca un'ora"]


def test_deliver_keeps_its_sound_outside_the_quiet_hours():
    conf = {"lang": "it", "tz": "Europe/Rome", "quiet": None, "night": "digest"}
    poller, store, bot = fake_poller(state={(CLAN.alias, "settings"): conf})
    asyncio.run(poller.deliver(CLAN, "manca un'ora", "war.reminder"))
    assert bot.sent == [(CLAN.chat_id, "manca un'ora", False)]
    assert (CLAN.alias, "queue") not in store.state


def test_deliver_puts_what_is_not_urgent_in_its_section():
    conf = {"lang": "it", "tz": "Europe/Rome", "quiet": None, "night": "digest"}
    poller, store, bot = fake_poller(state={(CLAN.alias, "settings"): conf})
    asyncio.run(poller.deliver(CLAN, "avviso", "family.transfer"))
    assert bot.sent == []
    righe = boards.lines_of(store.state[(CLAN.alias, "boards")], "family")
    assert len(righe) == 1 and righe[0].endswith("· avviso")


def test_the_mode_sits_next_to_the_quiet_hours_in_its_step():
    state = setup_state()
    _, rows = setup_ui.reminders_screen(IT, state)
    buttons = [button for row in rows for button in row]
    assert f"{IT.t('settings.night.label')}: {night.label(IT, state)}" in [b.text for b in buttons]
    assert f"cfg:{CLAN.alias}:night" in [b.callback_data for b in buttons]
    assert f"{IT.t('settings.night.label')}: {night.label(IT, state)}" in setup_ui.summary_lines(IT, state)


def test_pressing_the_button_cycles_the_mode_and_saves_it():
    state = setup_state()
    state["step"] = "reminders"
    after, step = setup_ui.handle(state, f"cfg:{CLAN.alias}:night")
    assert step == "reminders" and night.mode(after) == "digest"
    assert setup_ui.to_settings(after)["night"] == "digest"
    back, _ = setup_ui.handle(after, f"cfg:{CLAN.alias}:night")
    assert night.mode(back) == "silent"
    assert setup_ui.to_settings(back)["night"] == "silent"


def test_the_screens_start_from_the_saved_mode():
    assert setup_state({"night": "digest"})["night"] == "digest"
    assert setup_state()["night"] is None


def test_a_new_clan_stays_silent_even_after_picking_the_quiet_hours():
    state = setup_ui.start(CLAN.alias, 7, "it", "Europe/Rome")
    state["step"] = "reminders"
    state, _ = setup_ui.handle(state, f"cfg:{CLAN.alias}:quiet")
    doc = setup_ui.to_settings(state)
    assert doc["quiet"] == settings_mod.next_quiet_preset(None)
    assert night.mode(doc) == "silent"
