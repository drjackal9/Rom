import asyncio
import copy
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram.constants import ChatType
from telegram.error import TelegramError, TimedOut

from clashbot import bot as bot_mod
from clashbot import boards, feed
from clashbot import family as family_mod
from clashbot import handlers, i18n, progress as progress_mod, render, scoring, settings as settings_mod, views
from clashbot.poller import Poller, Tick

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
ALIAS = "bot-1"
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias=ALIAS)
IT = i18n.locale("it")
EN = i18n.locale("en")


class FakeVault:
    key_id = "test"

    def blind(self, label, value):
        return hashlib.sha256(f"{label}:{value}".encode()).hexdigest()


class FakeStore:
    def __init__(self, state=None, links=(), owner=None, wars=()):
        self.vault = FakeVault()
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.links = list(links)
        self.owner = owner
        self.kv = {}
        self.refs = {}
        self.wars = list(wars)
        self.stats = {}
        self.network = {}
        self.logs = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def recent_wars(self, alias, limit=10):
        return copy.deepcopy(self.wars[:limit])

    async def add_log(self, alias, entry, at=None):
        self.logs.append((alias, {**copy.deepcopy(entry), "at": at}))

    async def recent_log(self, alias, limit=20):
        return [copy.deepcopy(entry) for found, entry in reversed(self.logs) if found == alias][:limit]

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def bot_by_alias(self, alias):
        return None

    async def family_of_clan(self, clan_alias):
        return None

    async def claims_pending(self, clan_alias):
        return []

    async def tournament(self, alias):
        return None

    async def get_secret(self, kind):
        return self.owner if kind == "owner_id" else None

    async def links_by_user(self, user_id):
        return list(self.links)

    async def links_for_players(self, tags):
        wanted = set(tags or ())
        return {link.tag: link for link in self.links if link.tag in wanted}

    async def update_link(self, link):
        return link

    async def set_link_lang(self, user_id, lang):
        for link in self.links:
            if link.user_id == user_id:
                link.lang = lang

    async def mark_failure(self, alias):
        return {"failures": 1, "active": True}

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)
        self.refs[key] = ref

    async def kv_ref(self, key):
        return self.refs.get(key)

    async def kv_del(self, key):
        self.kv.pop(key, None)
        self.refs.pop(key, None)

    async def wars_since(self, alias, since):
        return copy.deepcopy(self.wars)

    async def add_stat(self, alias, kind, stat_key, ended_at, obj):
        self.stats[(alias, kind, stat_key)] = (ended_at, copy.deepcopy(obj))
        return True

    async def network_set(self, alias, visible, named, payload):
        self.network[alias] = {
            "alias": alias, "visible": visible, "named": named, "code": alias[-6:],
            "name": payload.get("name") if named else None, "week": payload.get("week"),
            "metrics": copy.deepcopy(payload.get("metrics") or {}), "updated_at": None,
        }

    async def network_get(self, alias):
        return copy.deepcopy(self.network.get(alias))

    async def network_board(self, limit=20):
        rows = [copy.deepcopy(r) for r in self.network.values() if r["visible"]]
        return rows[:limit]

    async def network_forget(self, alias):
        return self.network.pop(alias, None) is not None


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []
        self.silent = []
        self.fail = False
        self.polls = []
        self.stopped = []
        self.options = []
        self.edited = []

    async def send_message(self, chat_id, text, disable_notification=False, **kw):
        if self.fail:
            raise TelegramError("invio rifiutato")
        self.sent.append((chat_id, text))
        self.silent.append(bool(disable_notification))
        self.options.append(dict(kw, disable_notification=disable_notification))
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_reply_markup(self, chat_id=None, message_id=None, reply_markup=None):
        self.edited.append((chat_id, message_id))

    async def send_poll(self, chat_id, question, options, **kw):
        self.polls.append((chat_id, question, list(options), kw))
        index = len(self.polls)
        return SimpleNamespace(message_id=index, poll=SimpleNamespace(id=f"pid{index}"))

    async def stop_poll(self, chat_id, message_id):
        self.stopped.append((chat_id, message_id))


NO_LANGUAGE = object()


class ProfileBot:
    id = 8950684403
    def __init__(self, flaky=NO_LANGUAGE):
        self.commands = []
        self.shorts = []
        self.descriptions = []
        self.flaky = flaky
        self.attempts = 0

    async def set_my_commands(self, commands, scope=None, language_code=None):
        if language_code == self.flaky:
            self.attempts += 1
            raise TimedOut()
        if commands:
            self.commands.append(language_code)

    async def set_my_short_description(self, text, language_code=None):
        self.shorts.append(language_code)

    async def set_my_description(self, text, language_code=None):
        self.descriptions.append(language_code)


def fake_context(store):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": ALIAS})


def fake_supervisor(bot=None):
    bot = bot if bot is not None else FakeBot()
    return SimpleNamespace(bot=lambda alias: bot if alias == ALIAS else None,
                           running=lambda: [ALIAS], default_alias=ALIAS, owner_bot=lambda: bot)


def fake_update(query, user_id=7, chat_type=None):
    return SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
    )


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


def private_update(user_id=7):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=FakeMessage(),
    )


LINKED_CLAN = SimpleNamespace(alias=CLAN.alias, chat_id=CLAN.chat_id, tag=CLAN.tag, name=CLAN.name,
                              active=True, bot_alias=ALIAS)


def linked_private_store():
    store = manager_store({"lang": "it", "tz": "Europe/Rome"})
    store.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")

    async def clan_by_alias(alias):
        return LINKED_CLAN if alias == CLAN.alias else None

    async def active_clans(bot_alias=None):
        assert bot_alias == ALIAS
        return [LINKED_CLAN]

    store.clan_by_alias = clan_by_alias
    store.active_clans = active_clans
    return store


def manager_store(stored, manager=True):
    return FakeStore(
        state={(CLAN.alias, "settings"): stored, (CLAN.alias, "members"): {"#P1": {"role": "coLeader"}}},
        links=[SimpleNamespace(tag="#P1", user_id=7, dm=True, lang=None)] if manager else [],
    )


def press(store, data):
    query = FakeQuery(data)
    asyncio.run(handlers.on_settings_callback(fake_update(query), fake_context(store)))
    return query, store.state.get((CLAN.alias, "settings"))


def test_settings_in_private_uses_the_clan_of_the_linked_account():
    store = linked_private_store()
    update = private_update()
    asyncio.run(handlers.cmd_settings(update, fake_context(store)))
    text, keyboard = update.effective_message.sent[0]
    assert IT.t("settings.title") in text and keyboard is not None
    assert render.not_linked_view(IT) not in text


def test_help_in_private_shows_the_help_card_also_to_a_linked_member():
    store = linked_private_store()
    update = private_update()
    asyncio.run(handlers.cmd_help(update, fake_context(store)))
    text, keyboard = update.effective_message.sent[0]
    assert text == render.help_view(IT, handlers.COMMANDS_BY_AREA, 7)[0]
    assert len(keyboard.inline_keyboard) == 2
    start = private_update()
    context = fake_context(store)
    context.args = []
    asyncio.run(handlers.cmd_start(start, context))
    menu_text, menu_keyboard = start.effective_message.sent[0]
    assert menu_text != text and CLAN.name in menu_text and menu_keyboard is not None


def quiet_tick(is_quiet):
    t = Tick(CLAN, NOW)
    t.settings = settings_mod.effective({"lang": "it", "tz": "Europe/Rome", "quiet": [23, 7]}, None)
    t.L = IT
    t.tz = "Europe/Rome"
    t.quiet = is_quiet
    return t


def test_save_settings_merges_only_the_changed_key():
    store = manager_store({"min_th": 13, "note": "attivi", "lang": "it", "tz": "Europe/Rome"})
    stored = asyncio.run(handlers.save_settings(store, CLAN, {"polls": False}))
    assert stored == {"min_th": 13, "note": "attivi", "lang": "it", "tz": "Europe/Rome", "polls": False}
    assert store.state[(CLAN.alias, "settings")] == stored


def test_save_settings_stamps_a_clan_that_has_no_document_yet():
    store = FakeStore()
    stored = asyncio.run(handlers.save_settings(store, CLAN, {"lang": "it", "tz": "Europe/Rome"}))
    assert stored["version"] == settings_mod.SCHEMA_VERSION
    assert stored["setup_done"] is False
    assert store.state[(CLAN.alias, "settings")] == stored
    conf = settings_mod.effective(store.state[(CLAN.alias, "settings")], None)
    assert conf["mentions"] is None and conf["setup_done"] is False


def test_settings_callback_refuses_a_non_manager():
    store = manager_store({"min_th": 13}, manager=False)
    query, stored = press(store, "s:t:polls")
    assert stored == {"min_th": 13}
    assert query.answers == [(EN.t("h.admin_only"), True)]
    assert query.edits == []


def run_load_settings(stored, clan_json):
    store = FakeStore(state={(CLAN.alias, "settings"): stored} if stored is not None else None)
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    asyncio.run(poller.load_settings(t, clan_json))
    return t, store.state.get((CLAN.alias, "settings"))


def test_load_settings_derives_and_persists_with_country():
    t, stored = run_load_settings(None, {"location": {"countryCode": "IT"}})
    assert stored["lang"] == "it" and stored["tz"] == "Europe/Rome"
    assert stored["version"] == settings_mod.SCHEMA_VERSION and stored["setup_done"] is False
    assert settings_mod.effective(stored, None)["mentions"] is None
    assert t.L.code == "it" and t.tz == "Europe/Rome"
    assert t.settings["lang"] == "it"


def test_load_settings_completes_a_partial_row():
    t, stored = run_load_settings({"lang": "it", "min_th": 13}, {"location": {"countryCode": "JP"}})
    assert stored == settings_mod.migrate({"lang": "it", "min_th": 13, "tz": "Asia/Tokyo"})
    assert stored["lang"] == "it" and stored["tz"] == "Asia/Tokyo" and stored["min_th"] == 13
    assert t.L.code == "it" and t.tz == "Asia/Tokyo"


def test_load_settings_does_not_persist_without_location():
    t, stored = run_load_settings(None, {"name": "Futuro"})
    assert stored is None
    assert t.L.code == "en" and t.tz == "UTC"
    t, stored = run_load_settings(None, None)
    assert stored is None
    assert t.L.code == "en" and t.tz == "UTC"


def test_load_settings_leaves_a_chosen_language_alone():
    t, stored = run_load_settings({"lang": "en", "tz": "UTC"}, {"location": {"countryCode": "IT"}})
    assert stored == settings_mod.migrate({"lang": "en", "tz": "UTC"})
    assert stored["lang"] == "en" and stored["tz"] == "UTC"
    assert t.L.code == "en" and t.tz == "UTC"


def test_load_settings_saves_the_migration_only_the_first_time():
    store = FakeStore(state={(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"}})
    poller = Poller(fake_supervisor(), store, None)
    asyncio.run(poller.load_settings(Tick(CLAN, NOW), None))
    saved = store.state[(CLAN.alias, "settings")]
    assert saved["version"] == settings_mod.SCHEMA_VERSION and saved["setup_done"] is True
    asyncio.run(poller.load_settings(Tick(CLAN, NOW), None))
    assert store.state[(CLAN.alias, "settings")] == saved


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def quiet_poller(state=None):
    store = FakeStore(state=state)
    bot = FakeBot()
    return Poller(fake_supervisor(bot), store, None), store, bot


def test_flush_defers_everything_but_urgent_during_quiet_hours():
    poller, store, bot = quiet_poller()
    t = quiet_tick(True)
    t.chunks = [("reminder", "promemoria"), ("members", "movimenti"), ("agenda", "agenda")]
    asyncio.run(poller.flush(t))
    assert bot.sent == [(CLAN.chat_id, "promemoria")]
    assert store.state[(CLAN.alias, "queue")] == ["movimenti", "agenda"]


def test_the_urgent_messages_of_the_night_go_out_without_sound():
    poller, _, bot = quiet_poller()
    night = quiet_tick(True)
    night.chunks = [("war.risk", "rischio"), ("war.last_call", "ultima chiamata")]
    asyncio.run(poller.flush(night))
    assert bot.sent == [(CLAN.chat_id, "rischio\n\nultima chiamata")]
    assert bot.silent == [True]
    day = quiet_tick(False)
    day.chunks = [("war.risk", "rischio"), ("war.last_call", "ultima chiamata")]
    asyncio.run(poller.flush(day))
    assert bot.silent == [True, False]


def test_flush_sends_the_digest_once_and_clears_the_queue():
    poller, store, bot = quiet_poller({
        (CLAN.alias, "queue"): ["movimenti", "agenda"],
    })
    t = quiet_tick(False)
    t.chunks = [("members", "nuovo")]
    asyncio.run(poller.flush(t))
    digest = bot.sent[0][1]
    assert bot.sent[0][0] == CLAN.chat_id
    assert IT.t("quiet.digest.title") in digest and "movimenti" in digest and "agenda" in digest
    assert bot.sent[1] == (CLAN.chat_id, "nuovo")
    assert (CLAN.alias, "queue") not in store.state
    asyncio.run(poller.flush(quiet_tick(False)))
    assert len(bot.sent) == 2


def test_flush_queues_keeps_the_queue_when_the_send_fails():
    poller, store, bot = quiet_poller({
        (CLAN.alias, "queue"): ["movimenti"],
        (CLAN.alias, "queue_topics"): {"42": ["nel topic"]},
    })
    bot.fail = True
    asyncio.run(poller.flush_queues(quiet_tick(False)))
    assert bot.sent == []
    assert store.state[(CLAN.alias, "queue")] == ["movimenti"]
    assert store.state[(CLAN.alias, "queue_topics")] == {"42": ["nel topic"]}
    bot.fail = False
    asyncio.run(poller.flush_queues(quiet_tick(False)))
    assert len(bot.sent) == 2
    assert (CLAN.alias, "queue") not in store.state
    assert (CLAN.alias, "queue_topics") not in store.state


def test_flush_queues_sends_entry_by_entry_when_the_digest_is_too_long():
    entries = ["A" * 2500, "B" * 2500]
    poller, store, bot = quiet_poller({(CLAN.alias, "queue"): entries})
    asyncio.run(poller.flush_queues(quiet_tick(False)))
    assert [text for _, text in bot.sent] == entries
    assert all(len(text) <= render.MAX_LEN for _, text in bot.sent)
    assert (CLAN.alias, "queue") not in store.state


def test_digest_parts_clips_a_single_oversized_entry():
    poller, _, _ = quiet_poller()
    parts = poller.digest_parts(IT, ["C" * 5000])
    assert len(parts) == 1 and len(parts[0]) == render.MAX_LEN - 1
    assert poller.digest_parts(IT, []) == []
    assert poller.digest_parts(IT, ["", None]) == []


def expected_languages():
    codes = [None] + [code for code in i18n.LANGUAGES if code != "en"]
    return [bot_mod.telegram_code(code) if code else None for code in codes
            if code is None or bot_mod.telegram_code(code)]


def test_publish_profile_isolates_a_failing_language(monkeypatch, caplog):
    monkeypatch.setattr(bot_mod, "PROFILE_GAP", 0)
    monkeypatch.setattr(bot_mod, "RETRY_PAUSE", 0)
    bot = ProfileBot(flaky="de")
    store = FakeStore()
    with caplog.at_level(logging.WARNING, logger="clashbot"):
        asyncio.run(bot_mod.publish_profile(bot, store))
    assert bot.attempts == 2
    assert bot.commands == [code for code in expected_languages() if code != "de"]
    assert bot.shorts == bot.commands and bot.descriptions == bot.commands
    assert "de" in caplog.text
    assert "profile:8950684403:de" not in store.kv
    assert set(store.kv) == {f"profile:8950684403:{code or 'default'}" for code in bot.commands}


def test_publish_profile_registers_english_once(monkeypatch):
    monkeypatch.setattr(bot_mod, "PROFILE_GAP", 0)
    monkeypatch.setattr(bot_mod, "RETRY_PAUSE", 0)
    bot = ProfileBot()
    asyncio.run(bot_mod.publish_profile(bot, FakeStore()))
    assert bot.commands == expected_languages()
    assert bot.commands.count(None) == 1 and "en" not in bot.commands
    assert bot_mod.profile_digest(IT) != bot_mod.profile_digest(EN)


def test_publish_profile_skips_unchanged_languages(monkeypatch):
    monkeypatch.setattr(bot_mod, "PROFILE_GAP", 0)
    monkeypatch.setattr(bot_mod, "RETRY_PAUSE", 0)
    store = FakeStore()
    asyncio.run(bot_mod.publish_profile(ProfileBot(), store))
    again = ProfileBot()
    asyncio.run(bot_mod.publish_profile(again, store))
    assert again.commands == []
    store.kv["profile:8950684403:it"] = "vecchio"
    third = ProfileBot()
    asyncio.run(bot_mod.publish_profile(third, store))
    assert third.commands == ["it"]


def sweep_player_json(name, gold=0, elixir=0, games=0, level=50, th=14):
    return {
        "tag": "#X", "name": name, "townHallLevel": th, "warStars": 100, "trophies": 5000,
        "warPreference": "in",
        "achievements": [
            {"name": "Gold Grab", "value": gold},
            {"name": "Elixir Escapade", "value": elixir},
            {"name": "Games Champion", "value": games},
        ],
        "heroes": [{"name": "Barbarian King", "level": level, "village": "home"}],
    }


class FakeCoc:
    def __init__(self, players):
        self.players = players
        self.asked = []

    async def player(self, tag):
        self.asked.append(tag)
        return copy.deepcopy(self.players.get(tag)), None


def sweep_tick(members=("#P1", "#P2")):
    t = Tick(CLAN, NOW)
    t.members = {tag: {"name": {"#P1": "Mario", "#P2": "Luigi"}.get(tag, tag), "role": "member"} for tag in members}
    return t


def run_sweep(store, coc, t, per_tick=2):
    poller = Poller(fake_supervisor(), store, coc)
    asyncio.run(poller.sweep_players(t, per_tick=per_tick))
    return store.state.get((CLAN.alias, "progress"))


def test_sweep_players_records_the_progress_and_prunes_who_left():
    old = progress_mod.update({}, "#P9", "Peach", {"gold": 10, "th": 13}, NOW, "UTC")
    store = FakeStore(state={(CLAN.alias, "progress"): old})
    coc = FakeCoc({
        "#P1": sweep_player_json("Mario", gold=40_000_000, games=3_000, th=15),
        "#P2": sweep_player_json("Luigi", gold=1_000_000, level=60),
    })
    progress = run_sweep(store, coc, sweep_tick())
    assert sorted(progress) == ["#P1", "#P2"]
    assert progress["#P1"]["name"] == "Mario"
    assert progress["#P1"]["now"]["gold"] == 40_000_000 and progress["#P1"]["now"]["th"] == 15
    assert progress["#P2"]["now"]["levels"] == 60
    assert progress["#P1"]["week"]["since"] == int(NOW.timestamp())
    assert progress_mod.deltas(progress, "week")[0]["loot"] == 0


def test_sweep_players_accumulates_between_two_sweeps():
    store = FakeStore()
    coc = FakeCoc({"#P1": sweep_player_json("Mario", gold=10_000_000), "#P2": sweep_player_json("Luigi")})
    run_sweep(store, coc, sweep_tick())
    coc.players["#P1"] = sweep_player_json("Mario", gold=13_000_000, level=51)
    progress = run_sweep(store, coc, sweep_tick())
    row = [r for r in progress_mod.deltas(progress, "week") if r["tag"] == "#P1"][0]
    assert row["loot"] == 3_000_000 and row["levels"] == 1
    assert coc.asked == ["#P1", "#P2", "#P1", "#P2"]


def test_sweep_players_survives_a_broken_stored_progress(caplog):
    store = FakeStore(state={(CLAN.alias, "progress"): "rotto"})
    coc = FakeCoc({"#P1": sweep_player_json("Mario", gold=5_000_000), "#P2": sweep_player_json("Luigi")})
    with caplog.at_level(logging.WARNING, logger="clashbot.poller"):
        progress = run_sweep(store, coc, sweep_tick())
    assert sorted(progress) == ["#P1", "#P2"]
    assert "clan-1" in caplog.text
    assert store.state[(CLAN.alias, "players")]["tags"]["#P1"]["name"] == "Mario"


def test_sweep_players_logs_and_goes_on_when_the_progress_cannot_be_saved(caplog):
    class BrokenStore(FakeStore):
        async def set_state(self, alias, kind, obj):
            if kind == "progress":
                raise RuntimeError("scrittura rifiutata")
            await FakeStore.set_state(self, alias, kind, obj)

    store = BrokenStore()
    coc = FakeCoc({"#P1": sweep_player_json("Mario"), "#P2": sweep_player_json("Luigi")})
    with caplog.at_level(logging.ERROR, logger="clashbot.poller"):
        assert run_sweep(store, coc, sweep_tick()) is None
    assert "scrittura rifiutata" in caplog.text
    assert sorted(store.state[(CLAN.alias, "players")]["tags"]) == ["#P1", "#P2"]


def test_sweep_players_ignores_a_profile_without_the_achievements():
    partial = sweep_player_json("Mario", gold=0)
    partial.pop("achievements")
    store = FakeStore()
    coc = FakeCoc({"#P1": partial, "#P2": sweep_player_json("Luigi", gold=1_000_000)})
    progress = run_sweep(store, coc, sweep_tick())
    assert sorted(progress) == ["#P2"]
    assert store.state[(CLAN.alias, "players")]["tags"]["#P1"]["name"] == "Mario"
    coc.players["#P1"] = sweep_player_json("Mario", gold=5_000_000)
    progress = run_sweep(store, coc, sweep_tick())
    assert progress["#P1"]["now"]["gold"] == 5_000_000


class CountingStore(FakeStore):
    def __init__(self, **kw):
        FakeStore.__init__(self, **kw)
        self.writes = 0

    async def set_state(self, alias, kind, obj):
        if kind == "progress":
            self.writes += 1
        await FakeStore.set_state(self, alias, kind, obj)


def test_the_progress_is_not_rewritten_when_nothing_was_swept():
    stored = progress_mod.update({}, "#P1", "Mario", {"gold": 10, "th": 13}, NOW, "UTC")
    store = CountingStore(state={(CLAN.alias, "progress"): stored})
    coc = FakeCoc({})
    run_sweep(store, coc, sweep_tick(("#P1",)))
    assert store.writes == 0 and coc.asked == ["#P1"]
    coc.players["#P1"] = sweep_player_json("Mario", gold=20)
    run_sweep(store, coc, sweep_tick(("#P1",)))
    assert store.writes == 1


def test_the_progress_is_rewritten_when_only_a_prune_is_due():
    stored = progress_mod.update({}, "#P9", "Peach", {"gold": 10, "th": 13}, NOW, "UTC")
    store = CountingStore(state={(CLAN.alias, "progress"): stored})
    run_sweep(store, FakeCoc({}), sweep_tick(("#P1",)))
    assert store.writes == 1 and store.state[(CLAN.alias, "progress")] == {}


def month_progress():
    august = datetime(2026, 8, 2, 10, tzinfo=timezone.utc)
    later = datetime(2026, 8, 29, 10, tzinfo=timezone.utc)
    state = {}
    for tag, name in (("#P1", "Mario"), ("#P2", "Luigi")):
        progress_mod.update(state, tag, name, {"gold": 0, "levels": 100, "games": 0, "th": 14}, august, "UTC")
    progress_mod.update(state, "#P1", "Mario", {"gold": 40_000_000, "levels": 101, "games": 2_000, "th": 14}, later, "UTC")
    progress_mod.update(state, "#P2", "Luigi", {"gold": 2_000_000, "levels": 140, "games": 0, "th": 14}, later, "UTC")
    return state


def test_season_rollover_hands_the_month_activity_to_the_titles():
    season = scoring.empty_season("2026-08")
    e = scoring.entry(season, "#P1", "Mario")
    e.update({"wars": 2, "attacks": 4, "stars": 10, "triples": 2, "missed": 0, "raid_attacks": 4,
              "loot": 100_000, "donations": 5_000})
    store = FakeStore(state={(CLAN.alias, "season"): season, (CLAN.alias, "progress"): month_progress()})
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    asyncio.run(poller.season_for(t))
    seasons = store.state[(CLAN.alias, "hall")]["seasons"]
    assert seasons[0]["season"] == "2026-08"
    assert seasons[0]["titles"]["Farmer"] == ["Mario", 40_000_000]
    assert seasons[0]["titles"]["Costruttore"] == ["Luigi", 40]
    assert seasons[0]["titles"]["CampioneGiochi"] == ["Mario", 2_000]
    assert t.season["id"] == "2026-09" and t.season["members"] == {}
    card = boards.lines_of(t.boards, "challenges")[0]
    assert "🏹" in card
    assert t.L.t("boards.mvp.detail", name="Mario") in card
    assert t.L.t("boards.part.farm") in card and t.L.t("boards.part.stars") in card


def test_season_rollover_ignores_a_broken_progress(caplog):
    season = scoring.empty_season("2026-08")
    scoring.entry(season, "#P1", "Mario").update({"attacks": 4, "stars": 9, "triples": 2})
    store = FakeStore(state={(CLAN.alias, "season"): season, (CLAN.alias, "progress"): ["rotto"]})
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    with caplog.at_level(logging.WARNING, logger="clashbot.poller"):
        asyncio.run(poller.season_for(t))
    titles = store.state[(CLAN.alias, "hall")]["seasons"][0]["titles"]
    assert "Cecchino" in titles
    assert not set(titles) & {"Farmer", "Costruttore", "CampioneGiochi"}
    assert "clan-1" in caplog.text


def test_leader_report_carries_the_idle_members():
    monday = datetime(2026, 9, 7, 9, 30, tzinfo=timezone.utc)
    day = datetime(2026, 8, 20, 9, tzinfo=timezone.utc)
    state = {}
    while day <= monday:
        for tag, name in (("#P1", "Mario"), ("#P2", "Luigi")):
            progress_mod.update(state, tag, name, {"gold": 0, "th": 14}, day, "UTC")
        day += timedelta(days=1)
    progress_mod.update(state, "#P3", "Peach", {"gold": 0, "th": 14}, datetime(2026, 9, 4, 9, tzinfo=timezone.utc), "UTC")
    progress_mod.update(state, "#P2", "Luigi", {"gold": 9_000_000, "th": 14}, monday, "UTC")
    progress_mod.update(state, "#P3", "Peach", {"gold": 0, "th": 14}, monday, "UTC")
    store = FakeStore(state={(CLAN.alias, "progress"): state})

    async def links_for_players(tags):
        return {"#P1": SimpleNamespace(user_id=42, lang=None, dm=True)}

    async def wars_since(alias, since):
        return []

    store.links_for_players = links_for_players
    store.wars_since = wars_since
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, monday)
    t.members = {tag: {"name": name, "role": "leader"} for tag, name in
                 (("#P1", "Mario"), ("#P2", "Luigi"), ("#P3", "Peach"))}
    asyncio.run(poller.leader_report(t))
    text = feed_rows(store, 42)[0]
    assert EN.t("activity.report.idle") in text
    assert "Mario" in text and "Luigi" not in text and "Peach" not in text
    assert EN.t("activity.days", n=18) in text


def test_family_activity_rows_average_the_score_per_member():
    week = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
    alfa, beta = {}, {}
    progress_mod.update(alfa, "#A1", "Mario", {"gold": 0, "th": 14}, week, "UTC")
    progress_mod.update(alfa, "#A2", "Luigi", {"gold": 0, "th": 14}, week, "UTC")
    progress_mod.update(alfa, "#A1", "Mario", {"gold": 10_000_000, "th": 14}, NOW, "UTC")
    progress_mod.update(beta, "#B1", "Peach", {"gold": 0, "th": 14}, week, "UTC")
    progress_mod.update(beta, "#B1", "Peach", {"gold": 30_000_000, "th": 14}, NOW, "UTC")
    store = FakeStore(state={("a", "progress"): alfa, ("b", "progress"): beta, ("c", "progress"): "rotto",
                             ("a", views.KIND): {views.FAMILY: True},
                             ("b", views.KIND): {views.FAMILY: True},
                             ("c", views.KIND): {views.FAMILY: True}})

    async def family_clans(alias):
        return [SimpleNamespace(alias="a", name="Alfa"), SimpleNamespace(alias="b", name="Beta"),
                SimpleNamespace(alias="c", name="Gamma")]

    store.family_clans = family_clans
    family = SimpleNamespace(alias="fam")
    rows = asyncio.run(family_mod.activity_rows(store, family))
    assert rows == [
        {"name": "Beta", "avg": 60.0},
        {"name": "Alfa", "avg": 10.0},
        {"name": "Gamma", "avg": 0},
    ]
    assert asyncio.run(family_mod.activity_rows(store, family, "month")) == rows
    card = render.digest_card(IT, SimpleNamespace(name="Fam"), [], [], [], [], activity=rows)
    assert IT.t("activity.family.section") in card and "Beta" in card


def test_family_activity_uses_the_clan_size_as_denominator():
    week = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
    alfa = {}
    progress_mod.update(alfa, "#A1", "Mario", {"gold": 0, "th": 14}, week, "UTC")
    progress_mod.update(alfa, "#A1", "Mario", {"gold": 30_000_000, "th": 14}, NOW, "UTC")
    store = FakeStore(state={("a", "progress"): alfa, ("a", "info"): {"members": 45},
                             ("b", "progress"): alfa, ("b", "info"): {"members": None},
                             ("a", views.KIND): {views.FAMILY: True},
                             ("b", views.KIND): {views.FAMILY: True}})

    async def family_clans(alias):
        return [SimpleNamespace(alias="a", name="Alfa"), SimpleNamespace(alias="b", name="Beta")]

    store.family_clans = family_clans
    rows = asyncio.run(family_mod.activity_rows(store, SimpleNamespace(alias="fam")))
    assert rows == [{"name": "Beta", "avg": 60.0}, {"name": "Alfa", "avg": 1.3}]


def test_family_digest_passes_the_month_activity():
    family = SimpleNamespace(alias="fam", chat_id=202, name="Fam")
    monday = datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc)
    state = {}
    progress_mod.update(state, "#A1", "Mario", {"gold": 0, "th": 14}, datetime(2026, 9, 1, 9, tzinfo=timezone.utc), "UTC")
    progress_mod.update(state, "#A1", "Mario", {"gold": 20_000_000, "th": 14},
                        datetime(2026, 9, 13, 23, 59, tzinfo=timezone.utc), "UTC")
    progress_mod.update(state, "#A1", "Mario", {"gold": 20_000_000, "th": 14}, monday, "UTC")
    store = FakeStore(state={("a", "progress"): state, ("a", views.KIND): {views.FAMILY: True}})

    async def family_clans(alias):
        return [SimpleNamespace(alias="a", chat_id=1, tag="#A", name="Alfa")]

    async def wars_since(alias, since):
        return []

    store.family_clans = family_clans
    store.wars_since = wars_since
    bot = FakeBot()
    poller = Poller(fake_supervisor(bot), store, None)
    asyncio.run(poller.family_digest(family, monday))
    assert bot.sent and bot.sent[0][0] == 202
    assert EN.t("activity.family.section") in bot.sent[0][1]
    assert "40" in bot.sent[0][1]


def test_le_righe_della_famiglia_portano_le_etichette_del_clan():
    store = FakeStore(state={("a", "info"): {"level": 12, "members": 46, "league": "Crystal I",
                                             "labels": ["Clan Wars"]},
                             ("a", "settings"): {"min_th": 13, "note": "attivi"},
                             ("b", "info"): {"level": 3, "members": 10}})

    async def family_clans(alias):
        return [SimpleNamespace(alias="a", chat_id=1, tag="#A", name="Alfa"),
                SimpleNamespace(alias="b", chat_id=2, tag="#B", name="Beta")]

    store.family_clans = family_clans
    rows = asyncio.run(family_mod.rows(store, SimpleNamespace(alias="fam")))
    assert rows[0]["labels"] == ["Clan Wars"] and rows[1]["labels"] is None
    board = render.recruit_board(IT, "UTC", SimpleNamespace(name="Alfa"), rows, NOW)
    assert "attivi · 🏷 Clan Wars" in board


def famiglia_con_punteggio(acceso_su):
    week = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
    alfa, beta = {}, {}
    progress_mod.update(alfa, "#A1", "Mario", {"gold": 0, "th": 14}, week, "UTC")
    progress_mod.update(alfa, "#A1", "Mario", {"gold": 10_000_000, "th": 14}, NOW, "UTC")
    progress_mod.update(beta, "#B1", "Peach", {"gold": 0, "th": 14}, week, "UTC")
    progress_mod.update(beta, "#B1", "Peach", {"gold": 30_000_000, "th": 14}, NOW, "UTC")
    state = {("a", "progress"): alfa, ("b", "progress"): beta}
    for alias in acceso_su:
        state[(alias, views.KIND)] = {views.FAMILY: True}
    store = FakeStore(state=state)

    async def family_clans(alias):
        return [SimpleNamespace(alias="a", name="Alfa"), SimpleNamespace(alias="b", name="Beta")]

    store.family_clans = family_clans
    return store


def test_il_punteggio_alla_famiglia_parte_spento_e_il_clan_non_compare():
    store = famiglia_con_punteggio(())
    assert asyncio.run(family_mod.activity_rows(store, SimpleNamespace(alias="fam"))) == []


def test_alla_famiglia_esce_solo_il_clan_che_ha_acceso_il_punteggio():
    store = famiglia_con_punteggio(("b",))
    rows = asyncio.run(family_mod.activity_rows(store, SimpleNamespace(alias="fam")))
    assert rows == [{"name": "Beta", "avg": 60.0}]
    card = render.family_view(IT, SimpleNamespace(alias="fam", name="Fam", chat_id=None),
                              [], activity=rows)
    assert "Beta" in card and "Alfa" not in card


def test_lo_spegnimento_toglie_il_clan_dal_riepilogo_della_famiglia():
    store = famiglia_con_punteggio(("a", "b"))
    prima = asyncio.run(family_mod.activity_rows(store, SimpleNamespace(alias="fam")))
    assert [r["name"] for r in prima] == ["Beta", "Alfa"]
    store.state[("b", views.KIND)] = views.toggle_family(store.state[("b", views.KIND)])
    dopo = asyncio.run(family_mod.activity_rows(store, SimpleNamespace(alias="fam")))
    assert [r["name"] for r in dopo] == ["Alfa"]


def digest_della_famiglia(acceso_su):
    store = famiglia_con_punteggio(acceso_su)

    async def wars_since(alias, since):
        if alias == "a":
            return [{"result": "win", "stars": 42,
                     "members": [{"name": "Mario", "attacks": [{"stars": 3}]}]}]
        return [{"result": "lose", "stars": 7,
                 "members": [{"name": "Peach", "attacks": [{"stars": 1}]}]}]

    store.wars_since = wars_since
    bot = FakeBot()
    poller = Poller(fake_supervisor(bot), store, None)
    asyncio.run(poller.family_digest(SimpleNamespace(alias="fam", chat_id=202, name="Fam"),
                                     datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc)))
    return bot


def test_il_digest_della_famiglia_non_esce_se_nessun_clan_mostra_il_punteggio():
    assert digest_della_famiglia(()).sent == []


def test_il_digest_della_famiglia_porta_solo_il_clan_che_mostra_il_punteggio():
    text = digest_della_famiglia(("b",)).sent[0][1]
    assert "Beta" in text and "Peach" in text
    assert "Alfa" not in text and "Mario" not in text and "42" not in text
