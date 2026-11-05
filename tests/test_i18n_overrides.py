from clashbot import i18n


def teardown_function():
    i18n.clear_cache()


def test_an_override_changes_what_the_bot_says_and_nothing_else():
    before = i18n.locale("it").t("web.status.title")
    i18n.set_overrides("it", {"web.status.title": "Stato dei servizi ClanBoard"})
    L = i18n.locale("it")
    assert L.t("web.status.title") == "Stato dei servizi ClanBoard"
    assert L.t("web.status.up") == i18n.catalog("it")["web.status.up"]
    assert i18n.locale("en").t("web.status.title") != "Stato dei servizi ClanBoard"
    i18n.set_overrides("it", {})
    assert i18n.locale("it").t("web.status.title") == before


def test_overrides_survive_the_locale_cache_and_the_alias():
    i18n.locale("pt-BR").t("web.status.title")
    i18n.set_overrides("pt", {"web.status.title": "Estado dos serviços"})
    assert i18n.locale("pt-BR").t("web.status.title") == "Estado dos serviços"
    assert i18n.overrides()["pt-BR"] == {"web.status.title": "Estado dos serviços"}


def test_only_strings_get_through():
    i18n.set_overrides("it", {"web.status.title": 7, 9: "x", "web.status.up": "attivo"})
    assert i18n.overrides()["it"] == {"web.status.up": "attivo"}
    assert i18n.locale("it").t("web.status.up") == "attivo"


def test_clear_cache_forgets_the_overrides_too():
    i18n.set_overrides("it", {"web.status.up": "attivo"})
    i18n.clear_cache()
    assert i18n.overrides() == {}
    assert i18n.locale("it").t("web.status.up") != "attivo"


def test_the_catalog_is_a_copy_and_the_placeholders_stay():
    found = i18n.catalog("it")
    found["web.status.title"] = "pinco"
    assert i18n.locale("it").t("web.status.title") != "pinco"
    assert "{n}" in i18n.catalog("it")["web.status.checked"]
