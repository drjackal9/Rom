from pathlib import Path

import pytest

from clashbot import db, i18n, publish, restore_check, retention
from clashbot.db import Store
from tests.test_web_panel import PanelStore, serve

CONTRIBUTING = Path(__file__).resolve().parents[1] / "CONTRIBUTING.md"


def test_the_translation_portal_is_not_on_the_domain(tmp_path):
    store = PanelStore(tmp_path)
    for path in ("/translate", "/translate/it", "/translate/de"):
        assert serve(store, path).status == 404, path
    assert serve(store, "/translate/de", "POST",
                 body={"name": "web.status.title", "text": "pinco"}).status == 404


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_no_catalog_carries_the_words_of_the_portal_any_more(code):
    for key in i18n.catalog(code):
        assert not key.startswith("web.tr."), (code, key)
        assert not key.startswith("web.panel."), (code, key)


def test_la_tabella_delle_proposte_non_si_crea_piu_e_lo_schema_la_toglie():
    schema = db.SCHEMA
    assert "create table if not exists web_strings" not in schema
    assert "web_strings" not in schema.split("drop table if exists web_strings;")[0]
    assert schema.count("drop table if exists web_strings;") == 1
    assert "web_strings" not in "".join(retention.COUNT_SQL.values())
    assert "web_strings" not in "".join(retention.DELETE_SQL.values())
    assert "web_strings" not in restore_check.TABLES
    assert all(name != "web_strings" for name, *_ in restore_check.CHECKS)


def test_the_live_overwrite_of_the_catalogs_is_gone():
    assert not hasattr(publish.Beat, "strings")
    for name in ("web_string_add", "web_string_open", "web_string_decide", "web_strings_open",
                 "web_strings_live", "web_strings_live_rows", "web_strings_today"):
        assert not hasattr(Store, name), name


def test_contributing_sends_a_translation_through_a_pull_request():
    text = CONTRIBUTING.read_text(encoding="utf-8")
    assert "pull request" in text
    assert "clashbot/locales/<lingua>.json" in text
    assert "CLA.md" in text
    assert "/translate" not in text
