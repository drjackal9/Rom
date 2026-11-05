import asyncio
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import events, guard, handlers, i18n, seats, setup_ui
from clashbot import settings as settings_mod
from fixtures import war_json
from test_flows import ALIAS, CLAN, FakeStore

IT = i18n.locale("it")
DE = i18n.locale("de")
USER = 7
THREAD = 99
OTHER = SimpleNamespace(alias="clan-2", chat_id=202, tag="#CLAN2", name="Secondo", bot_alias=ALIAS)

SAVED = {
    "version": settings_mod.SCHEMA_VERSION,
    "lang": "it",
    "tz": "Europe/Rome",
    "preset": "casual_clan",
    "packs": {"wars": True, "cwl": False, "capital_games": True, "members": True,
              "challenges": True, "recruitment": True, "family": True},
    "routes": {"war.board": {"to": "off", "intensity": None},
               "war.attack": {"to": "group", "intensity": "summary"}},
    "topics": {},
    "mentions": "group",
    "delegates": [],
    "setup_done": True,
    "reminders": [3600],
    "quiet": [23, 7],
    "min_th": 13,
    "note": "attivi",
}


class Message:
    def __init__(self, thread=None):
        self.message_thread_id = thread
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


class Query:
    def __init__(self, data, thread=None):
        self.data = data
        self.message = Message(thread)
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


def group_update(user_id=USER, thread=None):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=Message(thread),
    )


def press_update(data, user_id=USER, thread=None):
    query = Query(data, thread)
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"),
        effective_message=query.message,
    )
    return update, query


def clan_store(stored=None, role="coLeader", owner=None, linked=True):
    return FakeStore(
        state={(CLAN.alias, "settings"): stored if stored is not None else dict(SAVED),
               (CLAN.alias, "members"): {"#P1": {"role": role}}},
        links=[SimpleNamespace(tag="#P1", user_id=USER, name="Mario", dm=True, lang=None)]
        if linked else [],
        owner=owner,
    )


class FamilyStore(FakeStore):
    async def clan_by_chat(self, chat_id, bot_alias=None):
        for clan in (CLAN, OTHER):
            if chat_id == clan.chat_id:
                return clan
        return None


def family_store(role="coLeader"):
    return FamilyStore(
        state={(CLAN.alias, "settings"): dict(SAVED),
               (CLAN.alias, "members"): {"#P1": {"role": role}},
               (OTHER.alias, "settings"): dict(SAVED),
               (OTHER.alias, "members"): {"#P1": {"role": role}}},
        links=[SimpleNamespace(tag="#P1", user_id=USER, name="Mario", dm=True)],
    )


def context(store, user_data=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": ALIAS},
                           user_data={} if user_data is None else user_data)


def press_clan(clan, ctx, action, value=None, thread=None):
    query = Query(f"cfg:{clan.alias}:{action}" + (f":{value}" if value is not None else ""), thread)
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=clan.chat_id, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=USER, language_code="it"),
        effective_message=query.message,
    )
    asyncio.run(handlers.on_settings_callback(update, ctx))
    return query


def press(store, ctx, data, thread=None, user_id=USER):
    update, query = press_update(data, user_id, thread)
    asyncio.run(handlers.on_settings_callback(update, ctx))
    return query, store.state.get((CLAN.alias, "settings"))


def datas_of(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def cb(action, value=None):
    return f"cfg:{CLAN.alias}:{action}" + (f":{value}" if value is not None else "")


def seat_cb(store, uid=USER):
    return cb("dlg", seats.seat_ref(store.vault, CLAN.alias, uid))


def saved_conf(store):
    return settings_mod.effective(store.state.get((CLAN.alias, "settings")), None)


def test_the_screens_start_from_the_saved_settings():
    state = setup_ui.from_settings(settings_mod.effective(SAVED, None), CLAN.alias, USER)
    assert state["code"] == CLAN.alias and state["user_id"] == USER
    assert state["step"] == setup_ui.STEPS[0]
    assert state["preset"] == "casual_clan"
    assert state["packs"]["cwl"] is False and state["packs"]["wars"] is True
    assert state["mentions"] == "group"
    assert state["reminders"] == [3600] and state["quiet"] == [23, 7]
    assert state["intensity"] == "summary"
    assert state["lang"] == "it" and state["tz"] == "Europe/Rome"


def test_opening_and_leaving_the_screens_changes_nothing_that_was_saved():
    state = setup_ui.from_settings(settings_mod.effective(SAVED, None), CLAN.alias, USER)
    stored = settings_mod.migrate(SAVED)
    assert settings_mod.migrate(settings_mod.merge(stored, setup_ui.updates(state))) == stored


def test_a_clan_of_the_first_version_keeps_every_choice_it_had():
    legacy = {"lang": "it", "tz": "Europe/Rome", "defenses": False, "achievements": True, "agenda": True,
              "polls": True, "movements": True, "board": False, "reminders": [28800, 14400, 3600],
              "quiet": None, "min_th": None, "note": ""}
    stored = settings_mod.migrate(legacy)
    state = setup_ui.from_settings(settings_mod.effective(legacy, None), CLAN.alias, USER)
    assert settings_mod.migrate(settings_mod.merge(stored, setup_ui.updates(state))) == stored
    conf = settings_mod.effective(stored)
    assert conf["defenses"] is False and conf["board"] is False
    assert settings_mod.route(conf, "war.board") == ("off", None)
    assert settings_mod.route(conf, "war.defense") == ("group", "summary")


def test_a_clan_of_the_first_version_is_not_rewritten_by_a_skipped_step():
    legacy = {"lang": "it", "tz": "Europe/Rome", "defenses": False, "board": False, "min_th": 13}
    store = clan_store(legacy)
    ctx = context(store)
    query, stored = press(store, ctx, cb("next"))
    assert query.answers[-1] == (None, False)
    assert stored == legacy


def test_changing_a_destination_leaves_alone_an_event_that_was_off():
    state = setup_ui.from_settings(settings_mod.effective(SAVED, None), CLAN.alias, USER, 77)
    state, _ = setup_ui.handle(state, cb("dest", "wars"))
    assert state["dests"]["wars"] == "topic"
    conf = settings_mod.effective(settings_mod.merge(settings_mod.migrate(SAVED), setup_ui.updates(state)))
    assert settings_mod.route(conf, "war.board") == ("off", None)
    assert settings_mod.route(conf, "war.start")[0] == "topic"
    assert settings_mod.route(conf, "war.attack") == ("topic", "summary")


def test_the_language_is_written_only_when_it_is_chosen():
    state = setup_ui.from_settings(settings_mod.effective({"version": 2}, None), CLAN.alias, USER)
    assert "lang" not in setup_ui.updates(state)
    chosen, _ = setup_ui.handle(state, cb("lang", "de"))
    assert setup_ui.updates(chosen)["lang"] == "de"


def test_the_settings_command_opens_the_first_screen():
    store = clan_store()
    ctx = context(store)
    update = group_update()
    asyncio.run(handlers.cmd_settings(update, ctx))
    text, keyboard = update.effective_message.sent[0]
    assert IT.t("settings.title") in text and IT.t("setup.preset.q") in text
    assert datas_of(keyboard)[0] == cb("preset", "war_clan")


def test_the_last_screen_of_a_linked_clan_talks_about_saved_settings():
    store = clan_store()
    ctx = context(store)
    for _ in range(8):
        press(store, ctx, cb("next"))
    query, _ = press(store, ctx, cb("next"))
    text, keyboard = query.edits[-1]
    assert IT.t("settings.saved") in text and keyboard is None
    assert IT.t("setup.done") not in text


def test_every_press_is_written_right_away():
    store = clan_store()
    ctx = context(store)
    query, stored = press(store, ctx, cb("next"))
    assert IT.t("setup.packs.q") in query.edits[-1][0]
    query, stored = press(store, ctx, cb("pack", "members"))
    assert stored["packs"]["members"] is False
    assert stored["min_th"] == 13 and stored["note"] == "attivi"
    assert query.answers[-1] == (IT.t("settings.saved"), False)
    _, stored = press(store, ctx, cb("pack", "members"))
    assert stored["packs"]["members"] is True


def test_skipping_a_step_saves_nothing_and_says_nothing():
    store = clan_store()
    ctx = context(store)
    before = dict(store.state[(CLAN.alias, "settings")])
    query, stored = press(store, ctx, cb("next"))
    assert stored == before
    assert query.answers[-1] == (None, False)


def test_the_reminders_and_the_quiet_hours_are_saved_from_their_step():
    store = clan_store()
    ctx = context(store)
    for _ in range(3):
        press(store, ctx, cb("next"))
    _, stored = press(store, ctx, cb("rem", 14400))
    assert stored["reminders"] == [14400, 3600]
    _, stored = press(store, ctx, cb("rem", 14400))
    assert stored["reminders"] == [3600]
    _, stored = press(store, ctx, cb("rem", 99))
    assert stored["reminders"] == [3600]
    _, stored = press(store, ctx, cb("quiet"))
    assert stored["quiet"] == settings_mod.next_quiet_preset([23, 7])


def test_a_preset_pressed_again_rewrites_every_route():
    store = clan_store()
    ctx = context(store)
    _, stored = press(store, ctx, cb("preset", "war_clan"))
    conf = settings_mod.effective(stored, None)
    expected = settings_mod.effective(settings_mod.apply_preset(None, "war_clan"))
    assert conf["routes"] == expected["routes"] and conf["packs"] == expected["packs"]
    assert stored["min_th"] == 13 and stored["mentions"] == "group"


def test_the_topic_of_the_group_is_bound_to_a_pack():
    store = clan_store()
    ctx = context(store)
    press(store, ctx, cb("next"), thread=THREAD)
    press(store, ctx, cb("next"), thread=THREAD)
    query, stored = press(store, ctx, cb("dest", "wars"), thread=THREAD)
    assert cb("topic", "wars") in datas_of(query.edits[-1][1])
    _, stored = press(store, ctx, cb("topic", "wars"), thread=THREAD)
    assert stored["topics"] == {"wars": THREAD}
    _, stored = press(store, ctx, cb("topic", "wars"), thread=THREAD)
    assert stored["topics"] == {}


def test_without_a_topic_the_group_screen_offers_no_topic_button():
    store = clan_store()
    ctx = context(store)
    press(store, ctx, cb("next"))
    press(store, ctx, cb("next"))
    query, _ = press(store, ctx, cb("dest", "wars"))
    assert cb("topic", "wars") not in datas_of(query.edits[-1][1])


def test_the_advanced_button_opens_the_events_of_the_pack():
    store = clan_store()
    ctx = context(store)
    press(store, ctx, cb("next"))
    query, _ = press(store, ctx, cb("next"))
    assert cb("adv", "members") in datas_of(query.edits[-1][1])
    query, _ = press(store, ctx, cb("adv", "members"))
    assert query.answers[-1] == (None, False)
    assert IT.t("setup.pack.members") in query.edits[-1][0]
    assert cb("ev", "members:members.report") in datas_of(query.edits[-1][1])
    assert handlers.remembered_step(ctx, CLAN.alias) == "adv:members"


def test_the_advanced_screen_stays_open_while_the_events_are_touched():
    store = clan_store()
    ctx = context(store)
    press(store, ctx, cb("adv", "members"))
    query, _ = press(store, ctx, cb("ev", "members:members.movement"))
    assert handlers.remembered_step(ctx, CLAN.alias) == "adv:members"
    assert cb("ev", "members:members.report") in datas_of(query.edits[-1][1])
    query, _ = press(store, ctx, cb("next"))
    assert handlers.remembered_step(ctx, CLAN.alias) == "routes"
    assert IT.t("setup.routes.q") in query.edits[-1][0]


def test_an_event_destination_chosen_in_the_advanced_screen_is_saved():
    store = clan_store()
    ctx = context(store)
    assert "staff_dm" not in setup_ui.choices_for("members")
    _, stored = press(store, ctx, cb("ev", "members:members.movement"), thread=77)
    assert stored["routes"]["members.movement"]["to"] == "topic"
    _, stored = press(store, ctx, cb("ev", "members:members.movement"), thread=77)
    assert stored["routes"]["members.movement"]["to"] == "leaders_dm"
    _, stored = press(store, ctx, cb("ev", "members:members.movement"), thread=77)
    assert stored["routes"]["members.movement"]["to"] == "staff_dm"
    other = clan_store()
    _, outside = press(other, context(other), cb("ev", "members:members.movement"))
    assert outside["routes"]["members.movement"]["to"] == "leaders_dm"
    conf = saved_conf(store)
    assert settings_mod.route(conf, "members.movement")[0] == "staff_dm"
    assert settings_mod.route(conf, "members.achievement")[0] == "group"


def test_a_limited_manager_does_not_reach_the_advanced_screen():
    stored = dict(SAVED)
    store = clan_store(stored, role="admin")
    ctx = context(store)
    query, kept = press(store, ctx, cb("adv", "members"))
    assert query.answers == [(IT.t("h.admin_only"), True)]
    assert query.edits == [] and kept == stored
    query, kept = press(store, ctx, cb("ev", "members:members.report"))
    assert query.answers == [(IT.t("h.admin_only"), True)]
    assert query.edits == [] and kept == stored


def test_a_limited_manager_cannot_change_the_settings():
    stored = dict(SAVED)
    store = clan_store(stored, role="admin")
    ctx = context(store)
    query, kept = press(store, ctx, cb("pack", "members"))
    assert query.answers == [(IT.t("h.admin_only"), True)]
    assert query.edits == [] and kept == stored


def test_an_elder_keeps_the_targets_and_the_warnings_but_nothing_else():
    store = clan_store(dict(SAVED), role="admin")
    ctx = context(store)
    update, _ = press_update("t:pick")
    assert asyncio.run(handlers.can_manage(update, ctx, CLAN, "targets")) is True
    assert asyncio.run(handlers.can_manage(update, ctx, CLAN, "warnings")) is True
    assert asyncio.run(handlers.can_manage(update, ctx, CLAN, "settings")) is False
    assert asyncio.run(handlers.can_manage(update, ctx, CLAN, "delegates")) is False


def test_someone_without_a_linked_village_commands_nothing():
    store = clan_store(dict(SAVED), linked=False)
    ctx = context(store)
    update, _ = press_update("t:pick")
    assert asyncio.run(handlers.can_manage(update, ctx, CLAN, "targets")) is False
    assert asyncio.run(handlers.can_manage(update, ctx, CLAN, "settings")) is False


def test_an_elder_reaches_the_targets_and_a_member_does_not():
    store = clan_store(dict(SAVED), role="admin")
    update, query = press_update("t:pick")
    asyncio.run(handlers.on_targets_callback(update, context(store)))
    assert query.answers == [(IT.t("h.no_war"), True)]
    store = clan_store(dict(SAVED), role="member")
    update, query = press_update("t:pick")
    asyncio.run(handlers.on_targets_callback(update, context(store)))
    assert query.answers == [(IT.t("h.admin_only"), True)]


def test_the_owner_of_the_bot_and_the_manager_always_get_in():
    stored = dict(SAVED)
    store = clan_store(stored, linked=False, owner=str(USER))
    ctx = context(store)
    _, saved = press(store, ctx, cb("pack", "members"))
    assert saved["packs"]["members"] is False


def test_the_mentions_step_still_asks_for_an_answer():
    stored = dict(SAVED, mentions=None, setup_done=False)
    store = clan_store(stored)
    ctx = context(store)
    for _ in range(4):
        press(store, ctx, cb("next"))
    query, saved = press(store, ctx, cb("next"))
    assert query.answers[-1] == (IT.t("setup.mentions.required"), True)
    assert saved["mentions"] is None and saved["setup_done"] is False
    _, saved = press(store, ctx, cb("men", "never"))
    assert saved["mentions"] == "never" and saved["setup_done"] is True


def test_the_language_press_redraws_in_the_new_language():
    store = clan_store()
    ctx = context(store)
    query, stored = press(store, ctx, cb("lang", "de"))
    assert stored["lang"] == "de"
    assert query.answers[-1] == (DE.t("settings.saved"), False)
    assert DE.t("setup.preset.q") in query.edits[-1][0]


def test_an_old_settings_button_only_redraws_the_screen():
    store = clan_store()
    ctx = context(store)
    before = dict(store.state[(CLAN.alias, "settings")])
    query, stored = press(store, ctx, "s:t:polls")
    assert stored == before
    assert IT.t("setup.preset.q") in query.edits[-1][0]


def test_the_delegates_screen_lists_who_linked_a_village():
    store = clan_store()
    ctx = context(store)
    for _ in range(4):
        press(store, ctx, cb("next"))
    query, _ = press(store, ctx, cb("men", "group"))
    assert handlers.remembered_step(ctx, CLAN.alias) == "delegates"
    assert seat_cb(store) in datas_of(query.edits[-1][1])
    assert cb("dlg", USER) not in datas_of(query.edits[-1][1])
    _, stored = press(store, ctx, seat_cb(store))
    assert stored["delegates"] == [USER]
    _, stored = press(store, ctx, seat_cb(store))
    assert stored["delegates"] == []


def test_the_saved_screens_show_what_the_clan_already_has():
    store = clan_store()
    ctx = context(store)
    press(store, ctx, cb("next"))
    query, _ = press(store, ctx, cb("next"))
    labels = [button.text for row in query.edits[-1][1].inline_keyboard for button in row]
    assert not [label for label in labels if IT.t("setup.pack.cwl") in label]
    assert [label for label in labels if IT.t("setup.pack.wars") in label]
    assert [label for label in labels if IT.t("setup.war.summary") in label]


def test_the_screen_of_one_clan_survives_the_settings_of_another_clan():
    store = family_store()
    ctx = context(store)
    press_clan(CLAN, ctx, "next")
    press_clan(CLAN, ctx, "next")
    assert handlers.remembered_step(ctx, CLAN.alias) == "routes"
    press_clan(OTHER, ctx, "next")
    assert handlers.remembered_step(ctx, OTHER.alias) == "packs"
    assert handlers.remembered_step(ctx, CLAN.alias) == "routes"
    query = press_clan(CLAN, ctx, "next")
    assert IT.t("setup.reminders.q") in query.edits[-1][0]
    assert handlers.remembered_step(ctx, CLAN.alias) == "reminders"
    assert handlers.remembered_step(ctx, OTHER.alias) == "packs"


def test_the_topic_key_is_written_in_italian_and_in_english():
    assert IT.t("setup.topic.use", pack="Guerre") != i18n.locale("en").t("setup.topic.use", pack="Guerre")
    assert "Guerre" in IT.t("setup.topic.use", pack="Guerre")


def test_le_deleghe_e_le_impostazioni_lasciano_il_nome_nel_registro():
    store = clan_store(dict(SAVED))
    ctx = context(store)
    press(store, ctx, cb("men", "group"))
    press(store, ctx, seat_cb(store))
    press(store, ctx, cb("pack", "members"))
    righe = [entry for _, entry in store.logs]
    assert [(row["kind"], row["ref"], row["by"], row["by_name"]) for row in righe] == [
        ("delegate", seats.seat_ref(store.vault, CLAN.alias, USER), USER, "Mario"),
        ("settings", "members", USER, "Mario")]


def test_i_bersagli_lasciano_la_loro_riga_nel_registro():
    store = clan_store(dict(SAVED))
    store.state[(CLAN.alias, "war")] = events.war_snapshot(war_json("inWar"))
    update, _ = press_update("t:mirror")
    asyncio.run(handlers.on_targets_callback(update, context(store)))
    righe = [entry for _, entry in store.logs]
    assert [(row["kind"], row["ref"], row["by"], row["by_name"]) for row in righe] == [
        ("target", "mirror", USER, "Mario")]


def suspend(store, user_id=USER):
    asyncio.run(store.kv_set(guard.suspended_key(CLAN.alias, user_id), {"at": 0}))


def test_il_gestore_sospeso_non_tocca_le_impostazioni():
    store = clan_store(dict(SAVED))
    suspend(store)
    query, saved = press(store, context(store), cb("pack", "members"))
    assert query.answers == [(IT.t("h.suspended"), True)]
    assert saved == SAVED and store.logs == []


def test_dieci_tocchi_nel_wizard_in_un_ora_non_sospendono_nessuno():
    store = clan_store(dict(SAVED))
    ctx = context(store)
    risposte = []
    for pack in ("wars", "cwl", "capital_games", "members", "challenges"):
        for _ in range(2):
            query, _ = press(store, ctx, cb("pack", pack))
            risposte.append(query.answers[-1])
    assert risposte == [(IT.t("settings.saved"), False)] * 10
    assert not asyncio.run(guard.suspended(store, CLAN.alias, USER))
    assert len(asyncio.run(store.kv_get(guard.abuse_key(CLAN.alias, USER)))["hits"]) == 1


def test_alla_quinta_sessione_di_impostazioni_nell_ora_il_posto_si_sospende():
    store = clan_store(dict(SAVED))
    risposte = []
    for pack in ("wars", "cwl", "capital_games", "members", "challenges"):
        ctx = context(store)
        query, _ = press(store, ctx, cb("pack", pack))
        risposte.append(query.answers[-1])
    assert risposte[:4] == [(IT.t("settings.saved"), False)] * 4
    assert risposte[-1] == (IT.t("h.suspend_notice"), True)
    assert asyncio.run(guard.suspended(store, CLAN.alias, USER))


def test_riaprire_le_impostazioni_apre_una_sessione_nuova():
    store = clan_store(dict(SAVED))
    ctx = context(store)
    for pack in ("wars", "cwl", "capital_games", "members", "challenges"):
        asyncio.run(handlers.cmd_settings(group_update(), ctx))
        press(store, ctx, cb("pack", pack))
    assert asyncio.run(guard.suspended(store, CLAN.alias, USER))


def hits_of(store, user_id=USER):
    stored = asyncio.run(store.kv_get(guard.abuse_key(CLAN.alias, user_id)))
    return len((stored or {}).get("hits") or ())


def test_aggiungere_un_delegato_non_e_un_azione_distruttiva_toglierlo_si():
    store = clan_store(dict(SAVED))
    ctx = context(store)
    press(store, ctx, cb("men", "never"))
    assert hits_of(store) == 1
    _, saved = press(store, ctx, seat_cb(store))
    assert saved["delegates"] == [USER] and hits_of(store) == 1
    _, saved = press(store, ctx, seat_cb(store))
    assert saved["delegates"] == [] and hits_of(store) == 2
