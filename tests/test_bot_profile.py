import asyncio

import pytest

from clashbot import bot as bot_mod
from clashbot import i18n

PRIVATE = "all_private_chats"
GROUPS = "all_group_chats"


class ProfileBot:
    id = 8950684403

    def __init__(self):
        self.calls = []

    async def set_my_commands(self, commands, scope=None, language_code=None):
        self.calls.append((getattr(scope, "type", None), language_code,
                           [entry.command for entry in commands]))

    async def set_my_short_description(self, text, language_code=None):
        return None

    async def set_my_description(self, text, language_code=None):
        return None


class FakeStore:
    def __init__(self):
        self.kv = {}

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj


@pytest.fixture
def published(monkeypatch):
    monkeypatch.setattr(bot_mod, "PROFILE_GAP", 0)
    monkeypatch.setattr(bot_mod, "RETRY_PAUSE", 0)

    def run(profile=bot_mod.WORKER_PROFILE):
        bot = ProfileBot()
        asyncio.run(bot_mod.publish_profile(bot, FakeStore(), profile))
        return bot

    return run


def languages():
    codes = [None] + [code for code in i18n.LANGUAGES if code != "en"]
    return [bot_mod.telegram_code(code) if code else None for code in codes
            if code is None or bot_mod.telegram_code(code)]


def test_the_menu_of_the_clan_bot_lives_only_in_the_private_chats(published):
    bot = published()
    private = [(language, names) for scope, language, names in bot.calls if scope == PRIVATE]
    assert [language for language, _ in private] == languages()
    assert all(names == [name for name, _ in bot_mod.COMMANDS] for _, names in private)


def test_the_group_menu_is_emptied_once_per_language(published):
    bot = published()
    groups = [(language, names) for scope, language, names in bot.calls if scope == GROUPS]
    assert [language for language, _ in groups] == languages()
    assert all(names == [] for _, names in groups)


def test_no_menu_is_published_without_a_scope(published):
    assert all(scope is not None for scope, _, _ in published().calls)


def test_the_menu_no_longer_offers_the_group_commands_that_went_away(published):
    names = {name for _, _, published_names in published().calls for name in published_names}
    assert "menu" not in names and "alerts" not in names


def test_the_digest_of_the_clan_bot_changed_with_the_scopes():
    payload = bot_mod.profile_payload(i18n.locale("it"), bot_mod.WORKER_PROFILE)
    assert payload["scope"] == [PRIVATE, GROUPS]
    assert bot_mod.profile_digest(i18n.locale("it")) != bot_mod.profile_digest(i18n.locale("en"))


def test_the_console_keeps_the_one_menu_it_has_always_had(published):
    bot = published(bot_mod.CONSOLE_PROFILE)
    assert all(scope is None for scope, _, _ in bot.calls)
    assert "scope" not in bot_mod.profile_payload(i18n.locale("it"), bot_mod.CONSOLE_PROFILE)
