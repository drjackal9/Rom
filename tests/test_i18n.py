from datetime import datetime, timedelta, timezone

import json

import pytest

from clashbot import i18n


@pytest.fixture
def overrides(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "OVERRIDE_DIR", tmp_path)
    i18n.clear_cache()
    yield tmp_path
    i18n.clear_cache()


def write(path, code, data):
    (path / f"{code}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def partial(tmp_path, monkeypatch):
    (tmp_path / "en.json").write_text((i18n.LOCALE_DIR / "en.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    monkeypatch.setattr(i18n, "OVERRIDE_DIR", tmp_path / "override")
    i18n.clear_cache()
    yield tmp_path
    i18n.clear_cache()


NOW = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)


def test_languages_are_the_twenty_of_the_spec():
    assert set(i18n.LANGUAGES) == {
        "en", "it", "es", "pt-BR", "de", "fr", "tr", "ru", "ar", "fa",
        "zh-Hans", "zh-Hant", "ja", "ko", "id", "vi", "th", "hi", "pl", "nl",
    }
    assert i18n.LANGUAGES["it"] == "Italiano"
    assert i18n.LANGUAGES["zh-Hans"] == "简体中文"
    assert all(isinstance(name, str) and name for name in i18n.LANGUAGES.values())


def test_resolve_telegram_codes():
    assert i18n.resolve("it") == "it"
    assert i18n.resolve("it-IT") == "it"
    assert i18n.resolve("en-US") == "en"
    assert i18n.resolve("en-gb") == "en"
    assert i18n.resolve("pt-br") == "pt-BR"
    assert i18n.resolve("pt") == "pt-BR"
    assert i18n.resolve("zh-cn") == "zh-Hans"
    assert i18n.resolve("zh-hans") == "zh-Hans"
    assert i18n.resolve("zh") == "zh-Hans"
    assert i18n.resolve("zh-tw") == "zh-Hant"
    assert i18n.resolve("zh-hant") == "zh-Hant"
    assert i18n.resolve("zh-hk") == "zh-Hant"
    assert i18n.resolve(None) == "en"
    assert i18n.resolve("") == "en"
    assert i18n.resolve("klingon") == "en"


def test_locale_is_cached_and_normalized():
    assert i18n.locale("it-IT") is i18n.locale("it")
    assert i18n.locale(None).code == "en"
    assert i18n.locale("zh-TW").code == "zh-Hant"


def test_missing_key_falls_back_to_english_then_brackets(partial):
    write(partial, "ja", {"ago.now": "いま"})
    assert i18n.locale("ja").t("ago.now") == "いま"
    assert i18n.locale("ja").t("ago.yesterday") == "yesterday"
    assert i18n.locale("it").t("chiave.inesistente") == "[chiave.inesistente]"
    assert i18n.locale("en").t("nope") == "[nope]"


def test_placeholders_never_raise():
    L = i18n.locale("it")
    assert L.t("time.when") == "{weekday} {date} alle {time}"
    assert L.t("date.short") == "{d:02d}/{m:02d}"
    assert L.t("ago.now", n=3, extra="x") == "poco fa"
    assert L.t("ago.hours", n=3) == "3h fa"


def test_plural_default_rules():
    assert i18n.locale("it").t("plural.attack", n=1) == "attacco"
    assert i18n.locale("it").t("plural.attack", n=2) == "attacchi"
    assert i18n.locale("it").t("plural.attack", n=0) == "attacchi"
    assert i18n.locale("en").t("plural.attack", n=1) == "attack"
    assert i18n.locale("en").t("plural.attack", n=5) == "attacks"


def test_plural_slavic_and_arabic(overrides):
    write(overrides, "ru", {"plural.attack": {"one": "one", "few": "few", "many": "many", "other": "other"}})
    write(overrides, "ar", {"plural.attack": {"zero": "zero", "one": "one", "two": "two", "few": "few", "many": "many", "other": "other"}})
    write(overrides, "fr", {"plural.attack": {"one": "one", "other": "other"}})
    write(overrides, "ja", {"plural.attack": {"one": "one", "other": "other"}})
    ru = i18n.locale("ru")
    assert ru.t("plural.attack", n=1) == "one"
    assert ru.t("plural.attack", n=3) == "few"
    assert ru.t("plural.attack", n=5) == "many"
    assert ru.t("plural.attack", n=11) == "many"
    assert ru.t("plural.attack", n=22) == "few"
    ar = i18n.locale("ar")
    assert ar.t("plural.attack", n=0) == "zero"
    assert ar.t("plural.attack", n=1) == "one"
    assert ar.t("plural.attack", n=2) == "two"
    assert ar.t("plural.attack", n=4) == "few"
    assert ar.t("plural.attack", n=25) == "many"
    fr = i18n.locale("fr")
    assert fr.t("plural.attack", n=0) == "one"
    assert fr.t("plural.attack", n=1) == "one"
    assert fr.t("plural.attack", n=2) == "other"
    ja = i18n.locale("ja")
    assert ja.t("plural.attack", n=1) == "other"


def test_plural_form_falls_back_to_other_then_one(overrides):
    write(overrides, "ru", {"plural.attack": {"one": "one", "other": "other"}})
    write(overrides, "pl", {"plural.attack": {"one": "jeden"}})
    assert i18n.locale("ru").t("plural.attack", n=5) == "other"
    assert i18n.locale("pl").t("plural.attack", n=5) == "jeden"


def test_numbers():
    assert i18n.locale("it").n(12345) == "12.345"
    assert i18n.locale("de").n(12345) == "12.345"
    assert i18n.locale("en").n(12345) == "12,345"
    assert i18n.locale("ja").n(12345) == "12,345"
    assert i18n.locale("fr").n(12345) == "12\u202f345"
    assert i18n.locale("ru").n(12345) == "12\u202f345"
    assert i18n.locale("it").n(-12345) == "-12.345"
    assert i18n.locale("it").n(7) == "7"
    assert i18n.locale("it").n(None) == "?"
    assert i18n.locale("it").n("abc") == "?"


def test_percentages():
    assert i18n.locale("it").pct(78.25) == "78,3%"
    assert i18n.locale("en").pct(78.25) == "78.3%"
    assert i18n.locale("fr").pct(50) == "50,0%"
    assert i18n.locale("en").pct(66.666, digits=2) == "66.67%"
    assert i18n.locale("en").pct(100, digits=0) == "100%"
    assert i18n.locale("it").pct(None) == "?"


def test_delta():
    assert i18n.locale("it").delta(NOW + timedelta(hours=26, minutes=5), NOW) == "1g 2h"
    assert i18n.locale("en").delta(NOW + timedelta(hours=26, minutes=5), NOW) == "1d 2h"
    assert i18n.locale("it").delta(NOW + timedelta(minutes=5), NOW) == "5m"
    assert i18n.locale("it").delta(NOW + timedelta(hours=3, minutes=5), NOW) == "3h 05m"
    assert i18n.locale("en").delta(NOW + timedelta(hours=3, minutes=5), NOW) == "3h 05m"
    assert i18n.locale("it").delta(NOW - timedelta(minutes=1), NOW) == "0m"
    assert i18n.locale("it").delta(None) == "?"


def test_ago():
    it = i18n.locale("it")
    en = i18n.locale("en")
    assert it.ago(NOW - timedelta(minutes=30), NOW) == "poco fa"
    assert en.ago(NOW - timedelta(minutes=30), NOW) == "just now"
    assert it.ago(NOW - timedelta(hours=3), NOW) == "3h fa"
    assert en.ago(NOW - timedelta(hours=3), NOW) == "3h ago"
    assert it.ago(NOW - timedelta(hours=26), NOW) == "ieri"
    assert en.ago(NOW - timedelta(hours=26), NOW) == "yesterday"
    assert it.ago(NOW - timedelta(days=5, hours=1), NOW) == "5 gg fa"
    assert en.ago(NOW - timedelta(days=5, hours=1), NOW) == "5 days ago"
    assert it.ago(None) == "?"


def test_when_and_clock():
    target = datetime(2026, 9, 13, 8, 30, tzinfo=timezone.utc)
    assert i18n.locale("it").when(target, "Europe/Rome") == "dom 13/09 alle 10:30"
    assert i18n.locale("en").when(target, "Europe/Rome") == "Sun 13/09 at 10:30"
    assert i18n.locale("en").when(target, "Asia/Tokyo") == "Sun 13/09 at 17:30"
    assert i18n.locale("it").clock(target, "Europe/Rome") == "10:30"
    assert i18n.locale("it").clock(target, "Asia/Tokyo") == "17:30"
    assert i18n.locale("it").when(None, "Europe/Rome") == "?"
    assert i18n.locale("it").when(target, "Mordor/Barad-dur") == "dom 13/09 alle 08:30"


def test_weekdays_and_months_present():
    it = i18n.locale("it")
    en = i18n.locale("en")
    assert [it.t(f"weekday.{i}") for i in range(7)] == ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
    assert [en.t(f"weekday.{i}") for i in range(7)] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert it.t("month.1") == "gennaio" and it.t("month.12") == "dicembre"
    assert en.t("month.1") == "January" and en.t("month.12") == "December"


def test_stars():
    assert i18n.locale("it").stars(2) == "⭐⭐☆"
    assert i18n.locale("en").stars(2) == "⭐⭐☆"
    assert i18n.locale("en").stars(9, total=6) == "⭐" * 6
    assert i18n.locale("en").stars(None) == "☆☆☆"


def test_override_directory_merges_on_top(overrides):
    write(overrides, "it", {"ago.now": "adesso"})
    it = i18n.locale("it")
    assert it.t("ago.now") == "adesso"
    assert it.t("ago.yesterday") == "ieri"


def test_override_replaces_only_its_keys(overrides):
    shipped = json.loads((i18n.LOCALE_DIR / "ja.json").read_text(encoding="utf-8"))
    write(overrides, "ja", {"ago.now": "いま"})
    ja = i18n.locale("ja")
    assert ja.t("ago.now") == "いま"
    assert ja.t("ago.yesterday") == shipped["ago.yesterday"]


def test_broken_override_file_does_not_crash(overrides):
    (overrides / "it.json").write_text("{ not json", encoding="utf-8")
    assert i18n.locale("it").t("ago.now") == "poco fa"


def test_language_without_catalog_behaves_as_english(partial):
    th = i18n.locale("th")
    assert th.code == "th"
    assert th.t("ago.yesterday") == "yesterday"
    assert th.delta(NOW + timedelta(hours=26, minutes=5), NOW) == "1d 2h"


def test_non_finite_and_non_datetime_inputs_degrade():
    from clashbot import i18n
    L = i18n.locale("it")
    assert L.pct(float("nan")) == "?"
    assert L.pct(float("inf")) == "?"
    assert L.when("non una data", "Europe/Rome") == "?"
    assert L.clock("non una data", "Europe/Rome") == "?"
