import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from clashbot import handlers, poller, settings as S


def rome_now(hour, minute=0):
    rome = ZoneInfo("Europe/Rome")
    local = datetime(2026, 9, 11, hour, minute, tzinfo=rome)
    return local.astimezone(timezone.utc)


def test_effective_derives_lang_and_tz_from_location():
    clan = {"location": {"countryCode": "IT"}}
    result = S.effective(None, clan)
    assert result["lang"] == "it"
    assert result["tz"] == "Europe/Rome"


def test_effective_explicit_settings_win_over_location():
    clan = {"location": {"countryCode": "IT"}}
    result = S.effective({"lang": "en", "tz": "Asia/Tokyo"}, clan)
    assert result["lang"] == "en"
    assert result["tz"] == "Asia/Tokyo"


def test_effective_unknown_country_falls_back():
    clan = {"location": {"countryCode": "ZZ"}}
    result = S.effective(None, clan)
    assert result["lang"] == "en"
    assert result["tz"] == "UTC"


def test_effective_no_clan_json_falls_back():
    result = S.effective(None, None)
    assert result["lang"] == "en"
    assert result["tz"] == "UTC"


def test_effective_no_location_falls_back():
    result = S.effective(None, {})
    assert result["lang"] == "en"
    assert result["tz"] == "UTC"


def test_effective_invalid_tz_string_falls_back_to_utc():
    result = S.effective({"tz": "Not/AZone"}, None)
    assert result["tz"] == "UTC"


def test_effective_explicit_false_survives():
    result = S.effective({"defenses": False}, {"location": {"countryCode": "IT"}})
    assert result["defenses"] is False


def test_effective_returns_new_dict_and_does_not_mutate_defaults():
    result = S.effective(None, None)
    result["reminders"].append(1)
    result["defenses"] = False
    assert S.DEFAULTS["reminders"] == [28800, 14400, 3600]
    assert S.DEFAULTS["defenses"] is True


def test_effective_sanitizes_invalid_reminders():
    result = S.effective({"reminders": [999, "x", 3600]}, None)
    assert result["reminders"] == S.DEFAULTS["reminders"]


def test_effective_keeps_valid_partial_reminders():
    result = S.effective({"reminders": [3600]}, None)
    assert result["reminders"] == [3600]


def test_effective_keeps_empty_reminders():
    result = S.effective({"reminders": []}, None)
    assert result["reminders"] == []


def test_country_tz_has_at_least_60_entries():
    assert len(S.COUNTRY_TZ) >= 60
    for code, tz in S.COUNTRY_TZ.items():
        assert len(code) == 2
        ZoneInfo(tz)


def test_country_lang_codes_are_from_allowed_set():
    allowed = {"en", "it", "es", "pt-BR", "de", "fr", "tr", "ru", "ar", "fa",
        "zh-Hans", "zh-Hant", "ja", "ko", "id", "vi", "th", "hi", "pl", "nl"}
    for code, lang in S.COUNTRY_LANG.items():
        assert lang in allowed


def test_is_quiet_wraps_midnight_23_to_7():
    settings = {"tz": "Europe/Rome", "quiet": [23, 7]}
    assert S.is_quiet(settings, rome_now(23, 30)) is True
    assert S.is_quiet(settings, rome_now(3, 0)) is True
    assert S.is_quiet(settings, rome_now(7, 0)) is False
    assert S.is_quiet(settings, rome_now(12, 0)) is False


def test_is_quiet_simple_range_0_to_8():
    settings = {"tz": "Europe/Rome", "quiet": [0, 8]}
    assert S.is_quiet(settings, rome_now(0, 10)) is True
    assert S.is_quiet(settings, rome_now(7, 59)) is True
    assert S.is_quiet(settings, rome_now(8, 0)) is False


def test_is_quiet_start_equals_end_is_never_quiet():
    settings = {"tz": "Europe/Rome", "quiet": [5, 5]}
    assert S.is_quiet(settings, rome_now(5, 0)) is False
    assert S.is_quiet(settings, rome_now(23, 0)) is False


def test_is_quiet_none_is_never_quiet():
    settings = {"tz": "Europe/Rome", "quiet": None}
    assert S.is_quiet(settings, rome_now(23, 30)) is False


def test_quiet_presets_cycle():
    assert S.QUIET_PRESETS == [None, [23, 7], [0, 8], [22, 8]]
    assert S.next_quiet_preset(None) == [23, 7]
    assert S.next_quiet_preset([23, 7]) == [0, 8]
    assert S.next_quiet_preset([0, 8]) == [22, 8]
    assert S.next_quiet_preset([22, 8]) is None


def test_next_quiet_preset_unknown_value_goes_to_first():
    assert S.next_quiet_preset([1, 2]) == [23, 7]


class SettingsStore:
    def __init__(self, stored):
        self.stored = stored

    async def get_state(self, alias, kind):
        return self.stored if kind == "settings" else None


def test_clan_locale_is_one_implementation():
    assert handlers.clan_locale is S.clan_locale
    assert poller.clan_locale is S.clan_locale


def test_clan_locale_reads_the_language_and_the_hour_of_the_clan():
    clan = SimpleNamespace(alias="clan-1")
    L, tz = asyncio.run(S.clan_locale(SettingsStore({"lang": "de", "tz": "Europe/Berlin"}), clan))
    assert L.code == "de" and tz == "Europe/Berlin"
    L, tz = asyncio.run(S.clan_locale(SettingsStore(None), clan))
    assert L.code == "en" and tz == "UTC"
