from clashbot import handlers, i18n, settings, setup_ui, webmenu
from test_settings_ui import CLAN, USER, clan_store, context, press

L = i18n.locale("it")
URL = "https://esempio.test"
SLUG = "abcdef0123456789"


def test_the_defaults_follow_the_authority():
    assert settings.WEB_DEFAULTS == {"page": False, "members": False, "stats": False,
                                     "widget": False, "ics": False}
    assert settings.web_conf(None) == settings.WEB_DEFAULTS
    assert settings.web_conf({"web": {"members": True, "pinco": True}})["members"] is True
    assert "pinco" not in settings.web_conf({"web": {"pinco": True}})


def test_the_board_opt_in_is_not_a_switch_of_this_step():
    for field in ("listing", "named", "recruiting"):
        assert field not in settings.WEB_DEFAULTS and field not in webmenu.FIELDS
        assert field not in settings.web_conf({"web": {field: True}})
    assert webmenu.apply({}, "listing") == {}


def test_every_switch_flips_and_nothing_else_moves():
    conf = {"lang": "it"}
    flipped = webmenu.apply(conf, "members")
    assert flipped["web"]["members"] is True and flipped["lang"] == "it"
    assert settings.web_conf(webmenu.apply(flipped, "members"))["members"] is False
    assert webmenu.apply(conf, "pinco") == conf


def test_turning_the_page_off_takes_everything_else_with_it():
    conf = {}
    for field in webmenu.FIELDS:
        conf = webmenu.apply(conf, field)
    assert all(settings.web_conf(conf)[field] for field in webmenu.LOCKED)
    off = webmenu.apply(conf, "page")
    web = settings.web_conf(off)
    assert web["page"] is False and not any(web[field] for field in webmenu.LOCKED)


def test_the_links_exist_only_for_what_is_on():
    web = settings.web_conf({"web": {"page": True, "widget": True}})
    found = webmenu.links(URL, SLUG, web)
    assert found["page"] == f"{URL}/c/{SLUG}"
    assert found["widget"] == f"{URL}/c/{SLUG}/widget"
    assert "ics" not in found
    assert webmenu.links(None, SLUG, web) == {}


def data_for(field):
    return f"cfg:{CLAN.alias}:web:{field}"


def test_the_screen_shows_a_button_for_each_switch_and_short_callbacks():
    text, markup = webmenu.screen(L, {"web": {"page": True, "members": True}}, URL, SLUG, data_for)
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert [b.callback_data for b in buttons] == [data_for(field) for field in webmenu.FIELDS]
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons)
    assert not hasattr(webmenu, "PREFIX")
    assert L.t("web.set.title") in text and URL in text
    assert L.t("web.set.members") in text
    assert L.t("web.set.no_url") in webmenu.screen(L, {}, None, SLUG, data_for)[0]
    for code in ("it", "en"):
        spoken = i18n.locale(code)
        assert "[web." not in webmenu.screen(spoken, {}, URL, SLUG, data_for)[0], code


def test_the_leaders_message_lists_only_the_live_links():
    web = settings.web_conf({"web": {"page": True, "ics": True}})
    text = webmenu.ready_text(L, URL, SLUG, web)
    assert f"{URL}/c/{SLUG}" in text and "calendar.ics" in text
    assert "/widget" not in text and "[web." not in text
    assert webmenu.ready_text(L, None, SLUG, web) == L.t("web.ready.off")


def test_the_web_step_belongs_to_the_guided_path_and_keeps_its_way_out():
    assert setup_ui.STEPS.index("web") == setup_ui.STEPS.index("summary") - 1
    state = setup_ui.from_settings(settings.effective({"web": {"members": True}}, None),
                                   CLAN.alias, USER)
    text, keyboard = setup_ui.screen(L, state, "web")
    datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert datas == [data_for(field) for field in webmenu.FIELDS] + [f"cfg:{CLAN.alias}:next"]
    assert L.t("web.set.members") in text
    assert setup_ui.advance("web", state) == "summary"


def test_the_guided_path_really_saves_the_switch_it_shows():
    state = setup_ui.start("Ab3Cd4Ef5Gh6Ij7K", USER, "it", "Europe/Rome")
    assert settings.web_conf(setup_ui.to_settings(state))["widget"] is False
    moved, step = setup_ui.handle(state, "cfg:Ab3Cd4Ef5Gh6Ij7K:web:widget")
    assert step == "preset"
    web = settings.web_conf(setup_ui.to_settings(moved))
    assert web["widget"] is True and web["page"] is True
    assert settings.web_conf(setup_ui.updates(moved))["widget"] is True
    back, _ = setup_ui.handle(moved, "cfg:Ab3Cd4Ef5Gh6Ij7K:web:widget")
    assert settings.web_conf(setup_ui.to_settings(back))["widget"] is False
    same, _ = setup_ui.handle(moved, "cfg:Ab3Cd4Ef5Gh6Ij7K:web:pinco")
    assert same["web"] == moved["web"]


def test_a_switch_pressed_by_the_leader_is_saved_and_the_screen_comes_back():
    store = clan_store()
    ctx = context(store)
    query, stored = press(store, ctx, data_for("members"))
    assert settings.web_conf(stored)["members"] is True
    assert handlers.remembered_step(ctx, CLAN.alias) == "web"
    assert L.t("web.set.members") in query.edits[-1][0]
    query, stored = press(store, ctx, data_for("members"))
    assert settings.web_conf(stored)["members"] is False
    assert settings.web_conf(settings.effective(stored, None)) == settings.web_conf(stored)


def test_a_switch_that_does_not_exist_writes_nothing():
    store = clan_store()
    before = settings.web_conf(store.state[(CLAN.alias, "settings")])
    press(store, context(store), data_for("pinco"))
    assert settings.web_conf(store.state[(CLAN.alias, "settings")]) == before
