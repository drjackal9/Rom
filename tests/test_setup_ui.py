import asyncio
import json
import secrets
from types import SimpleNamespace

from telegram import InlineKeyboardMarkup
from telegram.constants import ChatType

from clashbot import console, handlers, i18n, setup_ui
from clashbot import settings as settings_mod
from clashbot.events_registry import CLAN_PACKS as PACKS, EVENTS, PLATFORM_PACK, events_of
from test_console import (CLAN, FakeCoc, FakeStore, FakeSupervisor, FakeTelegramBot, TAG, USER, account,
                          born, context, pressed)

IT = i18n.locale("it")
EN = i18n.locale("en")
CODE = "Ab3Cd4Ef5Gh6Ij7K"
OTHER = 42
TAIL = ["next", "next", "next", "men:group", "next", "next", "next", "next"]


def load(code):
    with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def fresh(preset=None, lang="it", tz="Europe/Rome"):
    state = setup_ui.start(CODE, USER, lang, tz)
    if preset:
        state, _ = setup_ui.handle(state, f"cfg:{CODE}:preset:{preset}")
    return state


def walk(state, presses):
    for press in presses:
        state, _ = setup_ui.handle(state, f"cfg:{CODE}:{press}")
    return state


def finish(preset, mentions="group"):
    return walk(fresh(preset),
                ["next", "next", "next", f"men:{mentions}", "next", "next", "next", "next"])


def datas_of(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_the_path_has_the_nine_steps_of_the_plan():
    assert setup_ui.STEPS == (
        "preset", "packs", "routes", "reminders", "mentions", "delegates", "locale", "web",
        "summary",
    )


def test_a_fresh_configuration_already_carries_the_default_preset():
    state = setup_ui.start(CODE, USER, "it", "Europe/Rome")
    assert state["code"] == CODE and state["user_id"] == USER
    assert state["step"] == "preset"
    assert state["preset"] == setup_ui.DEFAULT_PRESET
    assert state["mentions"] is None
    assert set(state["packs"]) == set(PACKS)
    assert state["lang"] == "it" and state["tz"] == "Europe/Rome"


def test_every_preset_walks_the_whole_path_and_lands_on_settings_ready_to_save():
    for preset in settings_mod.PRESETS:
        state = finish(preset)
        assert state["step"] == "done", preset
        doc = setup_ui.to_settings(state)
        assert doc["version"] == settings_mod.SCHEMA_VERSION, preset
        assert doc["preset"] == preset and doc["setup_done"] is True, preset
        assert doc["mentions"] == "group", preset
        assert doc["lang"] == "it" and doc["tz"] == "Europe/Rome", preset
        expected = settings_mod.apply_preset(None, preset)
        assert doc["packs"] == expected["packs"], preset
        assert doc["reminders"] == expected["reminders"], preset
        assert doc["quiet"] == expected["quiet"], preset


def test_skipping_every_step_keeps_the_values_of_the_preset():
    for preset in settings_mod.PRESETS:
        doc = settings_mod.effective(setup_ui.to_settings(finish(preset)))
        expected = settings_mod.effective(settings_mod.apply_preset(None, preset))
        assert doc["routes"] == expected["routes"], preset


def test_the_tag_step_does_not_move_on_without_a_choice():
    state = walk(fresh("war_clan"), ["next", "next", "next"])
    assert state["step"] == "mentions"
    moved, step = setup_ui.handle(state, f"cfg:{CODE}:next")
    assert step == "mentions" and moved["mentions"] is None
    chosen, step = setup_ui.handle(state, f"cfg:{CODE}:men:never")
    assert step == "delegates" and chosen["mentions"] == "never"


def test_a_configuration_left_at_the_tag_step_is_applied_but_not_marked_done():
    state = walk(fresh("war_clan"), ["next", "next", "next"])
    doc = setup_ui.to_settings(state)
    assert doc["setup_done"] is False and doc["mentions"] is None
    assert doc["preset"] == "war_clan"


def test_turning_a_pack_off_silences_all_its_events():
    state = walk(fresh("war_clan"), ["pack:cwl"])
    assert state["step"] == "packs" and state["packs"]["cwl"] is False
    conf = settings_mod.effective(setup_ui.to_settings(walk(state, TAIL)))
    for event in events_of("cwl"):
        assert settings_mod.route(conf, event) == ("off", None), event
    assert settings_mod.route(conf, "war.start")[0] == "group"


def test_the_destination_of_a_pack_cycles_and_reaches_every_event_that_accepts_it():
    state = walk(dict(walk(fresh("war_clan"), ["next"]), thread=77), ["dest:members"])
    assert state["step"] == "routes" and state["dests"]["members"] == "topic"
    state = walk(state, ["dest:members"])
    assert state["dests"]["members"] == "leaders_dm"
    conf = settings_mod.effective(setup_ui.to_settings(walk(state, TAIL[1:])))
    assert settings_mod.route(conf, "members.movement")[0] == "leaders_dm"
    assert settings_mod.route(conf, "members.report")[0] == "leaders_dm"
    assert settings_mod.route(conf, "war.start")[0] == "group"


def test_a_destination_an_event_cannot_take_leaves_that_event_on_its_own():
    state = walk(fresh("war_clan"), ["next", "dest:members", "dest:members"])
    assert state["dests"]["members"] == "member_dm"
    conf = settings_mod.effective(setup_ui.to_settings(walk(state, TAIL[1:])))
    assert settings_mod.route(conf, "members.achievement")[0] == "member_dm"
    assert "member_dm" not in EVENTS["system.link_nudge"]["allowed"]
    assert settings_mod.route(conf, "system.link_nudge")[0] == EVENTS["system.link_nudge"]["default"]


def test_the_topic_destination_is_offered_only_inside_a_topic():
    outside = walk(fresh("war_clan"), ["next"])
    seen = set()
    for _ in range(len(setup_ui.DEST_ORDER) + 1):
        outside = walk(outside, ["dest:members"])
        seen.add(outside["dests"]["members"])
    assert "topic" not in seen and "group" in seen
    inside = dict(walk(fresh("war_clan"), ["next"]), thread=77)
    inside = walk(inside, ["dest:members"])
    assert inside["dests"]["members"] == "topic"


def test_a_saved_topic_without_a_thread_is_shown_and_saved_as_group():
    conf = settings_mod.effective(setup_ui.to_settings(walk(fresh("war_clan"), TAIL)))
    conf = settings_mod.effective(settings_mod.merge(conf, {"routes": {
        event: {"to": "topic", "intensity": conf["routes"][event]["intensity"]} for event in events_of("wars")}}))
    assert settings_mod.route(conf, "war.start")[0] == "topic" and conf["topics"] == {}
    outside = setup_ui.from_settings(conf, CODE, USER, None)
    assert outside["dests"]["wars"] == "group"
    assert setup_ui.dest_label(IT, outside, "wars") == IT.t("setup.dest.group")
    saved = settings_mod.effective(setup_ui.to_settings(outside))
    assert settings_mod.route(saved, "war.start")[0] == "group"
    inside = setup_ui.from_settings(conf, CODE, USER, 77)
    assert inside["dests"]["wars"] == "topic"


def test_the_routes_step_no_longer_asks_where_a_pack_is_delivered_twice():
    state = walk(fresh("war_clan"), ["next"])
    assert state["step"] == "routes"
    datas = datas_of(setup_ui.screen(IT, state, "routes")[1])
    assert not [data for data in datas if ":mode:" in data or ":modeall:" in data]
    assert f"cfg:{CODE}:dest:wars" in datas
    doc = setup_ui.to_settings(walk(state, TAIL[1:]))
    assert "modes" not in doc


def test_the_guided_path_leaves_the_advanced_screen_to_the_settings():
    state = walk(fresh("war_clan"), ["next"])
    _, keyboard = setup_ui.screen(IT, state, "routes")
    assert not [data for data in datas_of(keyboard) if f"cfg:{CODE}:adv:" in data]
    live = setup_ui.from_settings(settings_mod.effective(None, None), CODE, USER)
    _, keyboard = setup_ui.screen(IT, live, "routes")
    datas = datas_of(keyboard)
    assert f"cfg:{CODE}:adv:wars" in datas
    assert all(len(data.encode()) <= 64 for data in datas)


def test_the_advanced_screen_cycles_an_event_destination_within_its_allowed_set():
    state, step = setup_ui.handle(fresh("war_clan"), f"cfg:{CODE}:ev:members:members.report")
    assert step == "adv:members"
    doc = setup_ui.to_settings(state)
    assert doc["routes"]["members.report"]["to"] in EVENTS["members.report"]["allowed"]
    assert doc["routes"]["members.report"]["to"] == "staff_dm"
    conf = settings_mod.effective(doc)
    assert settings_mod.route(conf, "members.movement")[0] == "group"


def test_the_advanced_screen_of_every_pack_renders_in_italian_and_english():
    state = setup_ui.from_settings(settings_mod.effective(None, None), CODE, USER)
    for pack in PACKS:
        for L in (IT, EN):
            text, keyboard = setup_ui.screen(L, state, f"adv:{pack}")
            assert text and "[setup." not in text, (pack, L.code)
            labels = [button.text for row in keyboard.inline_keyboard for button in row]
            assert not [label for label in labels if "[setup." in label], (pack, L.code)
            datas = datas_of(keyboard)
            assert len(datas) == len(events_of(pack)) + 1, pack
            assert all(data.startswith(f"cfg:{CODE}:") for data in datas), pack
            assert all(len(data.encode()) <= 64 for data in datas), pack


def test_the_names_of_the_events_are_written_in_italian_and_in_english():
    italian, english = load("it"), load("en")
    for event, meta in EVENTS.items():
        if meta["pack"] == PLATFORM_PACK:
            continue
        key = f"setup.event.{event}"
        assert key in italian and key in english, key
        assert italian[key] != english[key], key


def test_the_war_detail_switches_between_every_attack_and_the_summary_only():
    state = walk(fresh("war_clan"), ["next"])
    assert state["intensity"] == "all"
    state = walk(state, ["war"])
    assert state["intensity"] == "summary"
    conf = settings_mod.effective(setup_ui.to_settings(walk(state, TAIL[1:])))
    assert settings_mod.route(conf, "war.attack") == ("group", "summary")
    assert settings_mod.route(conf, "war.defense") == ("group", "summary")


def test_the_reminders_and_the_quiet_hours_can_be_changed_in_their_step():
    state = walk(fresh("war_clan"), ["next", "next"])
    assert state["step"] == "reminders" and state["reminders"] == [28800, 14400, 3600]
    state = walk(state, ["rem:14400", "quiet"])
    assert 14400 not in state["reminders"]
    assert state["quiet"] == settings_mod.next_quiet_preset(None)
    doc = setup_ui.to_settings(walk(state, TAIL[2:]))
    assert doc["reminders"] == [28800, 3600]
    assert doc["quiet"] == settings_mod.next_quiet_preset(None)


def test_the_delegates_step_ticks_who_linked_a_village():
    state = walk(fresh("war_clan"), ["next", "next", "next", "men:group"])
    assert state["step"] == "delegates" and state["delegates"] == []
    text, keyboard = setup_ui.screen(IT, state, "delegates")
    assert IT.t("setup.delegates.none") in text
    assert datas_of(keyboard) == [f"cfg:{CODE}:next"]
    state = dict(state, candidates=[("ab12", "Mario", 11), ("cd34", "Luigi", 22)])
    text, keyboard = setup_ui.screen(IT, state, "delegates")
    assert IT.t("setup.delegates.none") not in text
    assert datas_of(keyboard) == [f"cfg:{CODE}:dlg:ab12", f"cfg:{CODE}:dlg:cd34",
                                  f"cfg:{CODE}:next"]
    assert "11" not in str(datas_of(keyboard)) and "22" not in str(datas_of(keyboard))
    state = walk(state, ["dlg:cd34"])
    assert state["delegates"] == [22]
    rows = setup_ui.screen(IT, state, "delegates")[1].inline_keyboard
    assert rows[1][0].text == f"{setup_ui.ON} Luigi"
    assert rows[0][0].text == f"{setup_ui.OFF} Mario"
    doc = setup_ui.to_settings(walk(state, ["next", "next", "next"]))
    assert doc["delegates"] == [22]


def test_a_delegate_outside_the_linked_members_is_not_taken():
    state = walk(fresh("war_clan"), ["next", "next", "next", "men:group"])
    state = dict(state, candidates=[("ab12", "Mario", 11)])
    assert walk(state, ["dlg:zz99"])["delegates"] == []
    picked = walk(state, ["dlg:ab12", "dlg:ab12"])
    assert picked["delegates"] == []


def test_the_language_step_proposes_the_country_and_can_be_changed():
    state = walk(fresh("war_clan"), ["next", "next", "next", "men:group", "next"])
    assert state["step"] == "locale"
    text, keyboard = setup_ui.screen(IT, state, "locale")
    assert "Europe/Rome" in text
    assert f"cfg:{CODE}:lang:de" in datas_of(keyboard)
    state = walk(state, ["lang:de"])
    assert state["lang"] == "de" and state["step"] == "locale"
    doc = setup_ui.to_settings(walk(state, ["next", "next"]))
    assert doc["lang"] == "de" and doc["tz"] == "Europe/Rome"


def test_the_summary_lists_what_is_on_and_leaves_out_what_is_off():
    state = walk(fresh("war_clan"), ["pack:recruitment"])
    state = walk(state, ["next", "next", "next", "men:group", "next", "next", "next"])
    assert state["step"] == "summary"
    text, keyboard = setup_ui.screen(IT, state, "summary")
    assert IT.t("setup.pack.wars") in text
    assert IT.t("setup.pack.recruitment") not in text
    assert IT.t("setup.mentions.group") in text
    assert datas_of(keyboard) == [f"cfg:{CODE}:next"]


def test_the_summary_counts_the_delegates():
    state = walk(fresh("war_clan"), ["next", "next", "next", "men:group"])
    state = dict(state, candidates=[("ab12", "Mario", 11)])
    state = walk(state, ["dlg:ab12", "next", "next", "next"])
    assert state["step"] == "summary"
    text, _ = setup_ui.screen(IT, state, "summary")
    riga = [line for line in text.splitlines() if IT.t("setup.delegates.label") in line][0]
    assert riga.endswith(": 1")


def test_the_last_screen_says_it_is_saved_and_leaves_no_buttons():
    text, keyboard = setup_ui.screen(IT, finish("war_clan"), "done")
    assert IT.t("setup.done") in text and keyboard is None


def test_ogni_schermata_va_nell_app_come_testo_e_bottoni():
    state = fresh("family")
    for step in setup_ui.STEPS:
        text, keyboard = setup_ui.screen(IT, state, step)
        found = setup_ui.to_json(IT, state, step)
        assert found["text"] == text, step
        assert found["buttons"] == [
            [{"label": button.text, "data": button.callback_data} for button in line]
            for line in keyboard.inline_keyboard], step
        assert all(button["data"].startswith(f"cfg:{CODE}:")
                   for line in found["buttons"] for button in line), step
    done = setup_ui.to_json(IT, finish("family"), setup_ui.DONE)
    assert done["buttons"] == [] and IT.t("setup.done") in done["text"]


def test_every_screen_of_every_step_renders_in_italian_and_english():
    assert len(CODE) == len(secrets.token_urlsafe(12))
    state = fresh("family")
    for step in setup_ui.STEPS:
        for L in (IT, EN):
            text, keyboard = setup_ui.screen(L, state, step)
            assert text and "[setup." not in text, (step, L.code)
            assert isinstance(keyboard, InlineKeyboardMarkup), (step, L.code)
            assert all(data.startswith(f"cfg:{CODE}:") for data in datas_of(keyboard)), step
            assert all(len(data.encode()) <= 64 for data in datas_of(keyboard)), step


def test_an_unknown_press_changes_nothing():
    state = fresh("war_clan")
    same, step = setup_ui.handle(state, f"cfg:{CODE}:nonsense")
    assert same == state and step == "packs"


def test_the_configuration_keys_are_written_in_italian_and_in_english():
    italian, english = load("it"), load("en")
    keys = sorted(key for key in english if key.startswith("setup."))
    assert len(keys) >= 40
    assert set(keys) <= set(italian)
    for key in ("setup.title", "setup.preset.q", "setup.mentions.q", "setup.done", "setup.needed"):
        assert italian[key] != english[key], key


def newbot_context(user_data=None):
    store = FakeStore(accounts=[account()])
    flow = {"request_id": 7, "tag": TAG, "clan": CLAN, "country": "IT"}
    return store, context(store, FakeSupervisor(), bot=FakeTelegramBot(), coc=FakeCoc(),
                          user_data={"newbot": flow} if user_data is None else user_data)


def code_of(store):
    return next(key.split(":", 1)[1] for key in store.kv if key.startswith("ob:"))


def test_after_the_bot_is_born_the_console_opens_the_configuration():
    store, ctx = newbot_context()
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    code = code_of(store)
    text, keyboard = update.effective_message.sent[-1]
    assert IT.t("setup.preset.q") in text
    assert datas_of(keyboard)[0] == f"cfg:{code}:preset:war_clan"
    state = ctx.user_data["setup"]
    assert state["code"] == code and state["user_id"] == USER
    assert store.kv[f"ob:{code}"]["setup"] == state
    assert store.kv[f"ob:{code}"]["tag"] == TAG


def test_the_configuration_of_a_clan_without_a_country_still_starts():
    store, ctx = newbot_context(user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    asyncio.run(console.on_managed_created(born(), ctx))
    assert ctx.user_data["setup"]["lang"] == "en" and ctx.user_data["setup"]["tz"] == "UTC"


def test_without_a_clan_tag_there_is_nothing_to_configure():
    store, ctx = newbot_context(user_data={"newbot": {"request_id": 7}})
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    assert "setup" not in ctx.user_data
    assert IT.t("setup.preset.q") not in update.effective_message.sent[-1][0]


def started_console():
    store, ctx = newbot_context()
    asyncio.run(console.on_managed_created(born(), ctx))
    return store, ctx, code_of(store)


def test_every_step_is_written_into_the_pending_code():
    store, ctx, code = started_console()
    update, query = pressed(f"cfg:{code}:preset:family")
    asyncio.run(console.on_setup_callback(update, ctx))
    assert ctx.user_data["setup"]["preset"] == "family"
    assert store.kv[f"ob:{code}"]["setup"]["step"] == "packs"
    assert IT.t("setup.packs.q") in query.edits[-1][0]


def test_the_configuration_survives_a_restart_of_the_console():
    store, ctx, code = started_console()
    update, _ = pressed(f"cfg:{code}:preset:family")
    asyncio.run(console.on_setup_callback(update, ctx))
    ctx.user_data.pop("setup")
    update, query = pressed(f"cfg:{code}:next")
    asyncio.run(console.on_setup_callback(update, ctx))
    assert ctx.user_data["setup"]["preset"] == "family"
    assert store.kv[f"ob:{code}"]["setup"]["step"] == "routes"
    assert IT.t("setup.routes.q") in query.edits[-1][0]


def test_the_tag_step_warns_that_it_cannot_be_skipped():
    store, ctx, code = started_console()
    for _ in range(5):
        update, query = pressed(f"cfg:{code}:next")
        asyncio.run(console.on_setup_callback(update, ctx))
    assert ctx.user_data["setup"]["step"] == "mentions"
    assert query.answers[-1] == (IT.t("setup.mentions.required"), True)


def test_the_web_switches_of_the_guided_path_answer_and_are_saved():
    store, ctx, code = started_console()
    for press in ("next", "next", "next", "next", "men:group", "next", "next"):
        update, query = pressed(f"cfg:{code}:{press}")
        asyncio.run(console.on_setup_callback(update, ctx))
    assert store.kv[f"ob:{code}"]["setup"]["step"] == "web"
    assert IT.t("web.set.title") in query.edits[-1][0]
    update, query = pressed(f"cfg:{code}:web:widget")
    asyncio.run(console.on_setup_callback(update, ctx))
    assert query.answers == [(None, False)]
    state = store.kv[f"ob:{code}"]["setup"]
    assert settings_mod.web_conf(state)["widget"] is True
    assert settings_mod.web_conf(setup_ui.to_settings(state))["widget"] is True
    assert IT.t("web.set.widget") in query.edits[-1][0]
    update, query = pressed(f"cfg:{code}:web:widget")
    asyncio.run(console.on_setup_callback(update, ctx))
    assert settings_mod.web_conf(store.kv[f"ob:{code}"]["setup"])["widget"] is False


def test_somebody_else_cannot_touch_the_configuration():
    store, ctx, code = started_console()
    update, query = pressed(f"cfg:{code}:preset:family", user_id=OTHER)
    asyncio.run(console.on_setup_callback(update, ctx))
    assert query.answers == [(IT.t("setup.expired"), True)]
    assert store.kv[f"ob:{code}"]["setup"]["preset"] == setup_ui.DEFAULT_PRESET


def test_a_code_that_is_gone_says_so_instead_of_breaking():
    store = FakeStore()
    ctx = context(store, FakeSupervisor(), bot=FakeTelegramBot(), user_data={})
    update, query = pressed(f"cfg:{CODE}:preset:family")
    asyncio.run(console.on_setup_callback(update, ctx))
    assert query.answers == [(IT.t("setup.expired"), True)]
    assert query.edits == []


LINKED = SimpleNamespace(alias="clan-9", chat_id=-100, tag="#CLAN1", name="Nostro Clan", bot_alias="bot-1")
CAPO_TAG = "#L1"


class LinkStore:
    def __init__(self, settings=None, served=None, verified=True, owner=None):
        self.state = {} if settings is None else {(LINKED.alias, "settings"): dict(settings)}
        self.added = []
        self.log = []
        self.served = served
        self.verified = verified
        self.owner = owner
        self.kv = {}

    async def bot_for_tag(self, tag):
        return self.served

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag=CAPO_TAG, user_id=USER, name="Capo", verified=self.verified)
                ] if user_id == USER else []

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def add_log(self, alias, entry, at=None):
        self.log.append(entry)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

    async def count_clans(self, bot_alias):
        return 0

    async def get_secret(self, kind):
        return self.owner if kind == "owner_id" else None

    async def add_clan(self, chat_id, tag, name, user_id, bot_alias):
        self.added.append((chat_id, tag, name, user_id, bot_alias))
        return LINKED

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = obj


class LinkCoc:
    def __init__(self, ruolo="leader"):
        self.ruolo = ruolo

    async def clan(self, tag):
        rosa = [{"tag": CAPO_TAG, "name": "Capo", "role": self.ruolo}] if self.ruolo else []
        return {"tag": tag, "name": LINKED.name, "memberList": rosa,
                "location": {"countryCode": "IT"}}, None


def group_update(sent, user_id=USER):
    async def reply_text(text, reply_markup=None, **kw):
        sent.append((text, reply_markup))

    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=LINKED.chat_id, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=SimpleNamespace(sent=sent, reply_text=reply_text),
    )


def run_link(store, setup=None, ruolo="leader"):
    sent = []
    update = group_update(sent)
    ctx = SimpleNamespace(
        bot_data={"store": store, "coc": LinkCoc(ruolo), "bot_alias": "bot-1"},
        user_data={}, args=[], bot=FakeTelegramBot(),
    )
    asyncio.run(handlers.link_clan(update, ctx, update.effective_chat, LINKED.tag, USER, setup))
    return sent, store.state.get((LINKED.alias, "settings"))


def run_code(store, ruolo, sender=USER):
    sent = []
    update = group_update(sent, sender)
    store.kv["ob:codice"] = {"tag": LINKED.tag, "name": LINKED.name, "user_id": USER, "bot_alias": "bot-1"}
    ctx = SimpleNamespace(
        bot_data={"store": store, "coc": LinkCoc(ruolo), "bot_alias": "bot-1"},
        user_data={}, args=["codice"], bot=FakeTelegramBot(),
    )
    asyncio.run(handlers.cmd_start(update, ctx))
    return [text for text, _ in sent]


def test_linking_with_a_pending_configuration_applies_it_and_marks_the_setup_done():
    sent, stored = run_link(LinkStore(), finish("leaders_only", mentions="never"))
    conf = settings_mod.effective(stored)
    assert conf["setup_done"] is True and conf["mentions"] == "never"
    assert conf["preset"] == "leaders_only"
    assert settings_mod.route(conf, "war.attack") == ("leaders_dm", "summary")
    assert IT.t("setup.applied") in sent[-1][0]


def test_linking_without_a_configuration_asks_the_leaders_to_finish_it():
    sent, stored = run_link(LinkStore())
    assert settings_mod.effective(stored)["setup_done"] is False
    assert IT.t("setup.needed") in sent[-1][0]


def test_a_clan_that_already_finished_the_setup_is_not_nagged_again():
    store = LinkStore({"version": settings_mod.SCHEMA_VERSION, "setup_done": True,
                       "lang": "it", "tz": "Europe/Rome", "mentions": "group"})
    sent, _ = run_link(store)
    assert IT.t("setup.needed") not in sent[-1][0]
    assert IT.t("setup.applied") not in sent[-1][0]


def test_an_unfinished_configuration_is_applied_and_still_asks_to_finish():
    state = walk(fresh("casual_clan"), ["next", "next", "next"])
    sent, stored = run_link(LinkStore(), state)
    conf = settings_mod.effective(stored)
    assert conf["preset"] == "casual_clan" and conf["setup_done"] is False
    assert IT.t("setup.needed") in sent[-1][0]


def test_the_language_grid_is_the_same_one_the_clan_settings_use():
    rows = setup_ui.language_rows("de", f"cfg:{CODE}:lang:")
    assert [button.callback_data for row in rows for button in row] == [
        f"cfg:{CODE}:lang:{code}" for code in i18n.LANGUAGES
    ]
    _, keyboard = setup_ui.screen(IT, walk(fresh("war_clan"), ["lang:de"]), "locale")
    assert keyboard.inline_keyboard[:-1] == tuple(tuple(row) for row in rows)


def test_il_codice_di_un_clan_servito_da_un_altro_bot_non_collega():
    store = LinkStore(served="bot-9")
    sent, _ = run_link(store)
    assert store.added == []
    assert [text for text, _ in sent] == [IT.t("console.newbot_clan_taken")]


def test_il_codice_del_clan_di_questo_bot_collega():
    store = LinkStore(served="bot-1")
    run_link(store)
    assert store.added == [(LINKED.chat_id, LINKED.tag, LINKED.name, USER, "bot-1")]


NON_GUIDA = IT.t("h.onboard_not_leader", clan=LINKED.name)


def test_chi_non_e_piu_nella_rosa_non_porta_il_bot_nel_gruppo_col_codice():
    store = LinkStore(served="bot-1")
    sent, _ = run_link(store, ruolo=None)
    assert store.added == [] and [text for text, _ in sent] == [NON_GUIDA]


def test_chi_e_sceso_a_membro_non_porta_il_bot_nel_gruppo_col_codice():
    for ruolo in ("member", "admin"):
        store = LinkStore(served="bot-1")
        sent, _ = run_link(store, ruolo=ruolo)
        assert store.added == [] and [text for text, _ in sent] == [NON_GUIDA], ruolo


def test_il_capo_solo_rivendicato_non_porta_il_bot_nel_gruppo_col_codice():
    store = LinkStore(served="bot-1", verified=False)
    sent, _ = run_link(store)
    assert store.added == [] and [text for text, _ in sent] == [NON_GUIDA]


def test_il_co_capo_in_carica_porta_il_bot_nel_gruppo_col_codice():
    store = LinkStore(served="bot-1")
    run_link(store, ruolo="coLeader")
    assert store.added == [(LINKED.chat_id, LINKED.tag, LINKED.name, USER, "bot-1")]


def test_il_gestore_della_piattaforma_collega_anche_fuori_dalla_rosa():
    store = LinkStore(served="bot-9", owner=str(USER))
    run_link(store, ruolo=None)
    assert store.added == [(LINKED.chat_id, LINKED.tag, LINKED.name, USER, "bot-1")]


def test_start_col_codice_nel_gruppo_rilegge_il_ruolo_e_tiene_il_codice():
    store = LinkStore(served="bot-1")
    assert run_code(store, None) == [NON_GUIDA]
    assert store.added == [] and "ob:codice" in store.kv


def test_start_col_codice_di_chi_non_guida_piu_non_collega_nemmeno_se_lo_manda_un_altro():
    store = LinkStore(served="bot-1")
    assert run_code(store, None, sender=OTHER) == [NON_GUIDA]
    assert store.added == [] and "ob:codice" in store.kv


def test_start_col_codice_del_capo_in_carica_collega_e_consuma_il_codice():
    store = LinkStore(served="bot-1")
    run_code(store, "leader")
    assert store.added == [(LINKED.chat_id, LINKED.tag, LINKED.name, USER, "bot-1")]
    assert "ob:codice" not in store.kv
