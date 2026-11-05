from clashbot import events_registry as R
from clashbot import settings as S


FUTURO = {
    "lang": "it",
    "tz": "Europe/Rome",
    "defenses": True,
    "achievements": True,
    "agenda": True,
    "polls": True,
    "movements": True,
    "board": True,
    "reminders": [28800, 14400, 3600],
    "quiet": None,
    "min_th": None,
    "note": "",
}

LEGACY_KEYS = ("defenses", "achievements", "agenda", "polls", "movements", "board")


def test_schema_version_is_three():
    assert S.SCHEMA_VERSION == 3


def test_registry_events_are_the_ones_of_the_plan():
    assert set(R.EVENTS) == {
        "war.prep", "war.start", "war.attack", "war.defense", "war.end", "war.reminder", "war.board",
        "war.opponent_history", "war.record",
        "cwl.day", "cwl.reminder", "cwl.signup", "cwl.season", "cwl.roster", "cwl.scout",
        "cwl.standings", "cwl.bonus",
        "capital.start", "capital.reminder", "capital.end",
        "capital.gold", "capital.skipped", "capital.level",
        "games.start", "games.last_day", "games.board", "games.reminder", "games.end",
        "members.movement", "members.rejoin", "members.anniversary", "members.achievement",
        "members.report",
        "members.builder_board", "members.builder_goal", "members.legend",
        "members.goal", "members.progress",
        "boards.week", "boards.season", "boards.mvp", "boards.record", "boards.rank",
        "boards.donations",
        "challenges.poll", "challenges.season",
        "challenges.quiz", "challenges.duel", "challenges.mission", "challenges.bingo",
        "challenges.award", "challenges.vote", "challenges.badge", "challenges.ambassador",
        "family.transfer", "family.digest", "family.recruit",
        "system.notice", "system.diagnostic", "system.link_nudge",
        "war.cleanup", "war.last_call", "war.midway", "war.risk", "war.availability", "war.roster",
        "war.scout", "war.forecast", "war.forecast_result", "war.warning",
        "leaders.welcome", "leaders.rules", "leaders.scheduled", "leaders.gate",
        "leaders.exit", "leaders.promotion", "leaders.trial",
        "family.derby.open", "family.derby.end", "family.notice", "family.suggest",
        "family.tournament.signup", "family.tournament.round", "family.tournament.result",
        "family.tournament.final",
        "challenges.tournament.signup", "challenges.tournament.round",
        "challenges.tournament.result", "challenges.tournament.final",
        "recruit.application", "recruit.reminder",
        "bases.new", "bases.poll", "bases.pack",
        "system.stickers",
        "system.news",
        "system.survey",
        "platform.key_down", "platform.key_back", "platform.restore", "platform.ops",
        "web.ready",
        "integrations.twitch_live", "integrations.bridge", "integrations.notice",
    }


def test_registry_entries_are_coherent():
    assert R.DESTINATIONS == ("group", "topic", "leaders_dm", "staff_dm", "member_dm", "off",
                              "manager_dm")
    assert R.PACKS == ("wars", "cwl", "capital_games", "members", "challenges", "recruitment",
                       "family", "leaders", "bases", "platform", "integrations")
    assert R.CLAN_PACKS == ("wars", "cwl", "capital_games", "members", "challenges", "recruitment",
                            "family", "leaders", "bases", "integrations")
    for name, meta in R.EVENTS.items():
        assert meta["pack"] is None or meta["pack"] in R.PACKS, name
        assert meta["default"] in R.DESTINATIONS, name
        assert set(meta["allowed"]) <= set(R.DESTINATIONS), name
        assert meta["default"] in meta["allowed"], name
        assert meta["intensity"] is None or set(meta["intensity"]) <= set(R.INTENSITIES), name
        if meta["pack"] == R.PLATFORM_PACK:
            assert meta["allowed"] == ("manager_dm",), name
        else:
            assert "off" in meta["allowed"], name
            assert "manager_dm" not in meta["allowed"], name


def test_every_pack_has_at_least_one_event():
    used = {meta["pack"] for meta in R.EVENTS.values()}
    for pack in R.PACKS:
        assert pack in used, pack


def test_futuro_migrates_to_v3_keeping_todays_behaviour():
    conf = S.effective(FUTURO, {"location": {"countryCode": "IT"}})
    assert conf["version"] == 3
    assert conf["lang"] == "it"
    assert conf["tz"] == "Europe/Rome"
    assert conf["reminders"] == [28800, 14400, 3600]
    assert conf["quiet"] is None
    assert conf["mentions"] == "group"
    assert conf["setup_done"] is True
    assert conf["delegates"] == []
    assert all(conf["packs"][pack] is True for pack in R.CLAN_PACKS)
    assert S.route(conf, "war.defense") == ("group", "all")
    assert S.route(conf, "war.attack") == ("group", "all")
    assert S.route(conf, "members.achievement") == ("group", None)
    assert S.route(conf, "challenges.poll") == ("group", None)
    assert S.route(conf, "members.movement") == ("group", None)
    assert S.route(conf, "war.board") == ("group", None)
    assert S.route(conf, "cwl.signup") == ("group", None)
    assert all(conf[key] is True for key in LEGACY_KEYS)


def test_migrated_document_drops_the_legacy_keys():
    doc = S.migrate(FUTURO)
    assert doc["version"] == 3
    for key in LEGACY_KEYS:
        assert key not in doc


def test_migrate_is_idempotent():
    once = S.migrate(FUTURO)
    assert S.migrate(once) == once
    assert S.migrate(S.migrate(once)) == once


def test_migrate_of_nothing_is_idempotent_too():
    once = S.migrate(None)
    assert S.migrate(once) == once


def test_new_clan_has_no_mentions_and_setup_not_done():
    doc = S.migrate(None)
    assert doc["mentions"] is None
    assert doc["setup_done"] is False
    assert doc["preset"] is None
    assert S.migrate({})["mentions"] is None


def test_a_document_already_stamped_v3_stays_a_new_clan():
    stamped = {"version": S.SCHEMA_VERSION, "setup_done": False, "lang": "it", "tz": "Europe/Rome"}
    doc = S.migrate(stamped)
    assert doc["setup_done"] is False
    assert doc["mentions"] is None
    assert S.migrate(doc)["mentions"] is None
    assert S.effective(stamped, None)["mentions"] is None


def test_merge_stamps_the_document_of_a_clan_that_has_none():
    doc = S.merge(None, {"lang": "it", "tz": "Europe/Rome"})
    assert doc["version"] == S.SCHEMA_VERSION
    assert doc["setup_done"] is False
    assert doc["lang"] == "it" and doc["tz"] == "Europe/Rome"
    assert S.migrate(doc)["setup_done"] is False
    assert S.migrate(doc)["mentions"] is None
    assert S.effective(doc, {"location": {"countryCode": "IT"}})["mentions"] is None
    assert S.merge({}, {"lang": "it"})["setup_done"] is False


def test_merge_leaves_a_historic_document_migrated():
    doc = S.merge({"lang": "it", "tz": "Europe/Rome"}, {"polls": False})
    assert doc == {"lang": "it", "tz": "Europe/Rome", "polls": False}
    assert S.migrate(doc)["setup_done"] is True
    assert S.migrate(doc)["mentions"] == "group"
    assert S.merge(FUTURO, {"min_th": 13})["defenses"] is True


def test_merge_does_not_touch_the_document_it_receives():
    stored = {"lang": "it"}
    before = dict(stored)
    S.merge(stored, {"tz": "Europe/Rome"})
    assert stored == before
    assert S.merge(stored, None) == stored


def test_a_document_without_the_stamp_is_treated_as_migrated():
    doc = S.migrate({"lang": "it", "tz": "Europe/Rome"})
    assert doc["setup_done"] is True
    assert doc["mentions"] == "group"


def test_legacy_toggles_off_become_routes_off():
    stored = dict(FUTURO, defenses=False, achievements=False, agenda=False,
                  polls=False, movements=False, board=False)
    conf = S.effective(stored, None)
    assert S.route(conf, "war.defense") == ("group", "summary")
    assert S.route(conf, "war.start") == ("group", None)
    assert S.route(conf, "war.board")[0] == "off"
    assert S.route(conf, "members.achievement")[0] == "off"
    assert S.route(conf, "members.movement")[0] == "off"
    assert S.route(conf, "challenges.poll")[0] == "off"
    for event in ("cwl.signup", "games.start", "games.last_day", "challenges.season"):
        assert S.route(conf, event)[0] == "off", event
    assert all(conf[key] is False for key in LEGACY_KEYS)


def test_legacy_toggle_written_over_a_v2_document_is_honoured():
    doc = S.migrate(FUTURO)
    doc["polls"] = False
    conf = S.effective(doc, None)
    assert S.route(conf, "challenges.poll")[0] == "off"
    assert conf["polls"] is False
    assert "polls" not in S.migrate(doc)


def test_pack_off_switches_every_event_of_the_pack_off():
    doc = S.migrate(FUTURO)
    doc["packs"]["wars"] = False
    conf = S.effective(doc, None)
    assert S.route(conf, "war.start") == ("off", None)
    assert S.route(conf, "war.reminder") == ("off", None)
    assert S.route(conf, "members.movement")[0] == "group"
    assert conf["board"] is False


def test_pack_on_defaults_to_true_and_reads_the_document():
    conf = S.effective(None, None)
    assert S.pack_on(conf, "wars") is True
    assert S.pack_on(conf, None) is True
    assert S.pack_on({"packs": {"wars": False}}, "wars") is False
    assert S.pack_on({}, "family") is True


def test_route_rejects_a_destination_not_allowed():
    doc = S.migrate(FUTURO)
    doc["routes"]["members.report"] = {"to": "group", "intensity": None}
    conf = S.effective(doc, None)
    assert "group" not in R.EVENTS["members.report"]["allowed"]
    assert S.route(conf, "members.report") == (R.EVENTS["members.report"]["default"], None)
    assert conf["routes"]["members.report"]["to"] == R.EVENTS["members.report"]["default"]


def test_route_rejects_an_intensity_not_allowed():
    doc = S.migrate(FUTURO)
    doc["routes"]["war.attack"] = {"to": "group", "intensity": "every_single_one"}
    assert S.route(S.effective(doc, None), "war.attack") == ("group", "all")


def test_route_accepts_a_destination_allowed():
    doc = S.migrate(FUTURO)
    doc["routes"]["war.end"] = {"to": "leaders_dm"}
    assert S.route(S.effective(doc, None), "war.end") == ("leaders_dm", None)


def test_route_of_an_unknown_event_is_off():
    assert S.route(S.effective(None, None), "war.nothing") == ("off", None)


def test_route_survives_a_document_without_routes():
    assert S.route({}, "war.start") == ("group", None)


def test_migrate_survives_a_stored_routes_field_of_the_wrong_type():
    for broken in ("x", [], ["war.start"], 7, True):
        doc = S.migrate(dict(FUTURO, routes=broken))
        assert doc["routes"] == {}, broken
        conf = S.effective(dict(FUTURO, routes=broken), None)
        assert set(conf["routes"]) == set(R.CLAN_EVENTS), broken
        assert S.route(conf, "war.start") == ("group", None), broken


def test_allowed_refuses_an_unknown_action():
    conf = S.effective(FUTURO, None)
    assert S.allowed(conf, "everything", S.MANAGER) is False


def test_allowed_needs_no_stored_document_to_answer():
    assert S.allowed({}, "settings", S.MANAGER) is True
    assert S.allowed({}, "settings", S.LIMITED) is False
    assert S.allowed({}, "targets", S.LIMITED) is True


def test_presets_are_the_four_of_the_design():
    assert set(S.PRESETS) == {"war_clan", "casual_clan", "family", "leaders_only"}
    for name, preset in S.PRESETS.items():
        assert set(preset["packs"]) == set(R.CLAN_PACKS), name
        assert "mentions" not in preset, name
        for event, entry in preset["routes"].items():
            assert event in R.EVENTS, (name, event)
            assert entry["to"] in R.EVENTS[event]["allowed"], (name, event)
        assert all(seconds in S.REMINDER_CHOICES for seconds in preset["reminders"]), name
        assert preset["quiet"] in S.QUIET_PRESETS, name


def test_apply_preset_war_clan_keeps_every_attack():
    conf = S.effective(S.apply_preset(FUTURO, "war_clan"), None)
    assert conf["preset"] == "war_clan"
    assert S.route(conf, "war.attack") == ("group", "all")
    assert S.route(conf, "war.defense") == ("group", "all")
    assert conf["packs"]["wars"] is True
    assert conf["packs"]["cwl"] is True


def test_apply_preset_casual_clan_only_summaries():
    conf = S.effective(S.apply_preset(FUTURO, "casual_clan"), None)
    assert conf["preset"] == "casual_clan"
    assert S.route(conf, "war.attack") == ("group", "summary")
    assert S.route(conf, "war.defense") == ("group", "summary")
    assert conf["packs"]["cwl"] is False
    assert S.route(conf, "cwl.day") == ("off", None)


def test_apply_preset_family_turns_the_family_pack_on():
    conf = S.effective(S.apply_preset(FUTURO, "family"), None)
    assert conf["preset"] == "family"
    assert conf["packs"]["family"] is True
    assert S.route(conf, "family.digest")[0] != "off"
    assert S.route(conf, "family.transfer")[0] != "off"


def test_apply_preset_leaders_only_sends_everything_to_the_leaders():
    conf = S.effective(S.apply_preset(FUTURO, "leaders_only"), None)
    assert conf["preset"] == "leaders_only"
    assert S.route(conf, "war.start") == ("leaders_dm", None)
    assert S.route(conf, "war.attack") == ("leaders_dm", "summary")
    assert S.route(conf, "members.movement")[0] == "leaders_dm"
    assert S.route(conf, "members.report")[0] == "leaders_dm"


def test_apply_preset_keeps_the_clan_data_and_the_mentions():
    doc = S.migrate(dict(FUTURO, min_th=13, note="attivi"))
    doc["mentions"] = "never"
    doc["delegates"] = [11]
    applied = S.apply_preset(doc, "casual_clan")
    assert applied["lang"] == "it"
    assert applied["tz"] == "Europe/Rome"
    assert applied["min_th"] == 13
    assert applied["note"] == "attivi"
    assert applied["mentions"] == "never"
    assert applied["delegates"] == [11]
    assert applied["setup_done"] is True


def test_apply_preset_does_not_touch_the_stored_document():
    doc = S.migrate(FUTURO)
    before = S.migrate(doc)
    S.apply_preset(doc, "leaders_only")
    assert doc == before


def test_apply_preset_of_an_unknown_name_changes_nothing():
    doc = S.migrate(FUTURO)
    assert S.apply_preset(doc, "super_clan") == doc


def test_apply_preset_is_idempotent_through_migrate():
    applied = S.apply_preset(FUTURO, "casual_clan")
    assert S.migrate(applied) == applied


def test_mentions_out_of_the_set_falls_back():
    doc = S.migrate(FUTURO)
    doc["mentions"] = "shout"
    assert S.effective(doc, None)["mentions"] == "group"
    empty = S.migrate(None)
    empty["mentions"] = "shout"
    assert S.effective(empty, None)["mentions"] is None


def test_topics_are_kept_per_pack():
    doc = S.migrate(FUTURO)
    doc["topics"] = {"wars": 12, "nothing": 3, "members": "x"}
    conf = S.effective(doc, None)
    assert conf["topics"] == {"wars": 12}


def test_effective_fills_every_event_of_the_registry():
    conf = S.effective(None, None)
    assert set(conf["routes"]) == set(R.CLAN_EVENTS)
    for event, entry in conf["routes"].items():
        assert entry["to"] in R.EVENTS[event]["allowed"]
        assert set(entry) == {"to", "intensity"}


def test_effective_does_not_mutate_the_stored_document():
    stored = dict(FUTURO)
    before = dict(stored)
    conf = S.effective(stored, None)
    conf["packs"]["wars"] = False
    conf["routes"]["war.start"]["to"] = "off"
    assert stored == before


def test_effective_keeps_lang_and_tz_rules_of_today():
    conf = S.effective(None, {"location": {"countryCode": "IT"}})
    assert conf["lang"] == "it"
    assert conf["tz"] == "Europe/Rome"
    assert conf["version"] == 3
    assert conf["mentions"] is None


def test_the_board_and_the_poll_live_only_where_the_group_can_see_them():
    for event in ("war.board", "challenges.poll"):
        assert "leaders_dm" not in R.EVENTS[event]["allowed"], event
        assert "member_dm" not in R.EVENTS[event]["allowed"], event
        assert set(R.EVENTS[event]["allowed"]) == {"group", "topic", "off"}, event


def test_route_refuses_the_private_board_and_falls_back_to_the_group():
    doc = S.migrate(FUTURO)
    doc["routes"]["war.board"] = {"to": "leaders_dm", "intensity": None}
    doc["routes"]["challenges.poll"] = {"to": "leaders_dm", "intensity": None}
    conf = S.effective(doc, None)
    assert S.route(conf, "war.board") == ("group", None)
    assert S.route(conf, "challenges.poll") == ("group", None)
    assert conf["routes"]["war.board"]["to"] == "group"
    assert conf["routes"]["challenges.poll"]["to"] == "group"


def test_the_leaders_only_preset_turns_off_what_cannot_go_in_private():
    conf = S.effective(S.apply_preset(FUTURO, "leaders_only"), None)
    assert S.route(conf, "war.board") == ("off", None)
    assert S.route(conf, "challenges.poll") == ("off", None)
    assert S.route(conf, "bases.pack") == ("off", None)
    for event, meta in R.EVENTS.items():
        if event in R.URGENT:
            continue
        if "leaders_dm" in meta["allowed"] and S.pack_on(conf, meta["pack"]):
            assert S.route(conf, event)[0] == "leaders_dm", event


def test_staff_is_a_destination_for_member_events():
    for event in ("members.movement", "members.achievement", "members.report",
                  "family.transfer", "family.digest", "family.recruit", "system.diagnostic"):
        assert "staff_dm" in R.EVENTS[event]["allowed"], event
    assert "staff_dm" not in R.EVENTS["war.board"]["allowed"]
    assert "staff_dm" not in R.EVENTS["challenges.poll"]["allowed"]
    conf = S.migrate({"version": 2, "routes": {"members.movement": {"to": "staff_dm"}}})
    assert S.route(conf, "members.movement") == ("staff_dm", None)
    assert S.route(S.effective(conf, None), "members.report") == ("leaders_dm", None)


def test_the_staff_can_take_the_diagnostics_without_becoming_the_default():
    assert R.EVENTS["system.diagnostic"]["default"] == "leaders_dm"
    assert "member_dm" not in R.EVENTS["system.diagnostic"]["allowed"]
    fresh = S.migrate(None)
    assert S.route(fresh, "system.diagnostic") == ("leaders_dm", None)
    chosen = S.migrate({"version": 2, "routes": {"system.diagnostic": {"to": "staff_dm"}}})
    assert S.route(chosen, "system.diagnostic") == ("staff_dm", None)
    assert S.migrate(chosen)["routes"]["system.diagnostic"]["to"] == "staff_dm"
    assert S.route(S.migrate({"version": 2, "routes": {"system.diagnostic": {"to": "member_dm"}}}),
                   "system.diagnostic") == ("leaders_dm", None)
    assert S.route(S.apply_preset(chosen, "leaders_only"), "system.diagnostic") == ("leaders_dm", None)


WITH_A_MEMBER_OF_REFERENCE = ("war.reminder", "cwl.reminder", "capital.reminder", "capital.skipped",
                              "games.reminder", "members.achievement", "members.builder_goal",
                              "members.legend", "members.goal", "members.progress",
                              "challenges.duel", "challenges.badge", "challenges.ambassador")


def test_the_member_is_a_destination_only_where_an_event_has_a_member_of_reference():
    for event, meta in R.EVENTS.items():
        assert ("member_dm" in meta["allowed"]) is (event in WITH_A_MEMBER_OF_REFERENCE), event


def test_an_event_without_a_member_of_reference_falls_back_instead_of_going_silent():
    for event in ("members.movement", "members.report", "family.transfer", "family.digest", "family.recruit"):
        conf = S.effective(S.migrate({"version": 2, "routes": {event: {"to": "member_dm"}}}), None)
        assert S.route(conf, event) == (R.EVENTS[event]["default"], None), event
        assert "staff_dm" in R.EVENTS[event]["allowed"], event


def test_a_v2_document_climbs_to_schema_three_and_forgets_modes_and_permissions():
    doc = S.migrate({"version": 2, "lang": "it", "tz": "Europe/Rome", "mentions": "dm",
                     "modes": {"wars": "live"},
                     "permissions": {"settings": ["leader"], "targets": ["leader"]}})
    assert doc["version"] == 3
    assert "modes" not in doc and "permissions" not in doc
    assert doc["mentions"] == "group"
    assert doc["delegates"] == []
    assert S.migrate(doc) == doc
    assert S.MENTIONS == ("group", "never")


def test_the_two_levels_say_what_a_manager_may_do():
    conf = S.effective(FUTURO, None)
    assert S.ACTIONS == {"settings": S.MANAGER, "targets": S.LIMITED, "warnings": S.LIMITED,
                         "tools": S.MANAGER, "delegates": S.MANAGER, "pause": S.MANAGER,
                         "links": S.LIMITED, "views": S.MANAGER}
    for action in S.ACTIONS:
        assert S.allowed(conf, action, S.MANAGER) is True, action
    assert S.allowed(conf, "targets", S.LIMITED) is True
    assert S.allowed(conf, "warnings", S.LIMITED) is True
    assert S.allowed(conf, "settings", S.LIMITED) is False
    assert S.allowed(conf, "settings", None) is False
    assert S.allowed(conf, "settings", "leader") is False
    assert S.allowed(conf, "everything", S.MANAGER) is False


def test_the_delegates_are_kept_as_whole_telegram_ids():
    assert S.migrate({"version": 3, "delegates": [7, 9, 7]})["delegates"] == [7, 9]
    assert S.migrate({"version": 3, "delegates": "spazzatura"})["delegates"] == []
    assert S.migrate({"version": 3, "delegates": [True, "8", 9.5, None, 11]})["delegates"] == [11]
    kept = S.migrate({"version": 3, "delegates": [11]})
    assert S.apply_preset(kept, "casual_clan")["delegates"] == [11]


def test_the_urgent_events_are_the_ones_the_chat_still_hears():
    from clashbot import quiet
    from clashbot.poller import chunk_kind
    assert set(R.URGENT) == {event for event in R.EVENTS if chunk_kind(event) in quiet.URGENT}
    assert "war.last_call" in R.URGENT and "war.attack" not in R.URGENT


def test_the_leaders_preset_leaves_the_war_urgents_where_the_group_hears_them():
    conf = S.effective(S.apply_preset(FUTURO, "leaders_only"), None)
    assert S.route(conf, "war.last_call")[0] == "group"
    for event in R.URGENT:
        assert S.route(conf, event)[0] == R.EVENTS[event]["default"], event
        assert S.route(conf, event)[0] != "leaders_dm", event
    assert S.route(conf, "war.attack")[0] == "leaders_dm"
