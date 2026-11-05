import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from telegram.constants import ChatMemberStatus, ChatType

from clashbot import (__main__ as cli, handlers, hub, i18n, leaderboards as boards, recruit_tools,
                      render, settings as settings_mod, setup_ui, tips, util)
from clashbot.events_registry import PACKS
from fixtures import BASE_MEMBERS, clan_json

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
L = i18n.locale("it")


def fake_update(language_code):
    return SimpleNamespace(effective_user=SimpleNamespace(language_code=language_code))


def test_user_locale_from_telegram_language():
    assert handlers.user_locale(fake_update("it")).code == "it"
    assert handlers.user_locale(fake_update("en-US")).code == "en"
    assert handlers.user_locale(fake_update("pt-br")).code == "pt-BR"
    assert handlers.user_locale(fake_update("zh-TW")).code == "zh-Hant"


def test_user_locale_falls_back_to_english():
    assert handlers.user_locale(fake_update(None)).code == "en"
    assert handlers.user_locale(fake_update("xx")).code == "en"
    assert handlers.user_locale(SimpleNamespace(effective_user=None)).code == "en"
    assert handlers.user_locale(SimpleNamespace()).code == "en"


def test_parse_lang_accepts_known_codes_and_aliases():
    assert handlers.parse_lang("it") == "it"
    assert handlers.parse_lang(" EN ") == "en"
    assert handlers.parse_lang("pt") == "pt-BR"
    assert handlers.parse_lang("zh-Hant") == "zh-Hant"
    assert handlers.parse_lang("zh_TW") == "zh-Hant"
    assert handlers.parse_lang("de-AT") == "de"


def test_parse_lang_rejects_unknown_codes():
    assert handlers.parse_lang("xx") is None
    assert handlers.parse_lang("") is None
    assert handlers.parse_lang(None) is None
    assert handlers.parse_lang("klingon") is None


def test_known_zone_is_case_insensitive():
    assert handlers.known_zone("europe/rome") == "Europe/Rome"
    assert handlers.known_zone("Asia/Tokyo") == "Asia/Tokyo"
    assert handlers.known_zone("Mars/Olympus") is None


def rows_of(keyboard):
    return [[(b.text, b.callback_data) for b in row] for row in keyboard.inline_keyboard]


def test_menu_keyboard_uses_catalog_labels_and_view_keys():
    keyboard = rows_of(handlers.menu_keyboard(L))
    for row, keys in zip(keyboard, handlers.MENU_ROWS):
        assert [b[1] for b in row] == [f"v:{key}" for key in keys]
        assert [b[0] for b in row] == [L.t(f"menu.{key}") for key in keys]
    assert {key for row in handlers.MENU_ROWS for key in row} <= set(handlers.VIEWS)


def test_back_keyboard_uses_menu_keys():
    keyboard = rows_of(handlers.back_keyboard(L, "war"))
    assert keyboard[-1] == [(L.t("menu.back"), "v:menu"), (L.t("menu.refresh"), "v:war")]


def test_command_names_are_unique():
    names = [name for name, aliases in handlers.COMMANDS for name in [name] + aliases]
    assert len(names) == len(set(names))
    assert all(name.isascii() and name.islower() for name in names)


def test_every_command_has_a_description_and_a_handler():
    for name, _ in handlers.COMMANDS:
        assert f"cmd.{name}" in EN, name
        assert name in handlers.VIEWS or name in handlers.HANDLERS, name


def test_italian_aliases_are_kept():
    aliases = {alias for _, extra in handlers.COMMANDS for alias in extra}
    assert {"guerra", "attacchi", "bersagli", "mio", "capitale", "punti", "albo", "pronti", "eroi",
            "membri", "donazioni", "storico", "stelle", "pigri", "io", "collega",
            "famiglia", "reclutamento", "requisiti", "nuovoclan", "rimuovi", "stato",
            "impostazioni", "lingua", "fuso", "annulla", "scollega", "sostieni"} <= aliases


def test_start_payloads_cover_both_languages():
    assert set(handlers.START_LINK) == {"collega", "link"}
    assert set(handlers.START_NEWCLAN) == {"nuovoclan", "newclan"}
    for key in ("h.link_private", "h.newclan_private"):
        assert "?start=" in EN[key]


def test_la_porta_laterale_degli_avvisi_privati_non_esiste_piu():
    assert not hasattr(handlers, "START_ALERTS") and not hasattr(handlers, "set_alerts")
    assert [key for key in EN if key.startswith("h.alerts")] == []
    assert "alerts" not in dict(handlers.COMMANDS) and "avvisi" not in {
        alias for _, extra in handlers.COMMANDS for alias in extra}


def test_toggles_match_settings_defaults():
    assert set(settings_mod.LEGACY_OFF) | set(settings_mod.LEGACY_SUMMARY) <= set(settings_mod.DEFAULTS)
    assert [seconds for seconds, _ in setup_ui.REMINDER_BUTTONS] == settings_mod.DEFAULTS["reminders"]


def test_the_hub_replaces_the_six_old_menu_entries():
    assert ("boards", ["classifiche"]) in handlers.COMMANDS
    assert "boards" in handlers.VIEWS and ["boards", "agenda"] in handlers.MENU_ROWS
    for key in ("cmd.boards", "menu.boards", "boards.tab.farm", "boards.period.week"):
        assert key in EN, key
    flat = [key for row in handlers.MENU_ROWS for key in row]
    for gone in ("points", "hall", "activity", "top", "donations", "stars", "lazy", "capital"):
        assert gone not in flat, gone
        assert gone not in handlers.VIEWS, gone
        assert gone in handlers.HANDLERS, gone
    for command, (tab, _) in hub.COMMAND_TABS.items():
        assert tab in boards.TABS, command


ALIAS = "bot-1"
KEY = "userclan:user:7"


class LinkStore:
    def __init__(self, members=None):
        self.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
        self.kv = {}
        self.clans = [SimpleNamespace(alias="clan-a", active=True), SimpleNamespace(alias="clan-b", active=True)]
        self.members = members or {"clan-a": {"#X": {}}, "clan-b": {"#P1": {}, "#P2": {}}}
        self.scans = 0
        self.scoped = []

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag="#P2")] if user_id == 7 else []

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ttl=None):
        self.kv[key] = obj

    async def clan_by_alias(self, alias):
        return next((c for c in self.clans if c.alias == alias), None)

    async def active_clans(self, bot_alias=None):
        self.scans += 1
        self.scoped.append(bot_alias)
        return list(self.clans)

    async def get_state(self, alias, kind):
        return self.members.get(alias)


def test_clan_of_user_resolves_from_linked_account_and_caches():
    store = LinkStore()
    assert asyncio.run(handlers.clan_of_user(store, 1, ALIAS)) is None
    first = asyncio.run(handlers.clan_of_user(store, 7, ALIAS))
    assert first.alias == "clan-b" and store.scans == 1
    second = asyncio.run(handlers.clan_of_user(store, 7, ALIAS))
    assert second.alias == "clan-b" and store.scans == 1
    assert store.kv[KEY] == {"alias": "clan-b", "bot_alias": ALIAS}
    assert store.scoped == [ALIAS]


def test_clan_of_user_keeps_one_key_and_revalidates_it_per_bot():
    store = LinkStore()
    assert asyncio.run(handlers.clan_of_user(store, 7, ALIAS)).alias == "clan-b"
    assert asyncio.run(handlers.clan_of_user(store, 7, "bot-2")).alias == "clan-b"
    assert store.scans == 2 and store.scoped == [ALIAS, "bot-2"]
    assert set(store.kv) == {KEY}
    assert store.kv[KEY] == {"alias": "clan-b", "bot_alias": "bot-2"}
    assert asyncio.run(handlers.clan_of_user(store, 7)).alias == "clan-b"
    assert store.kv[KEY] == {"alias": "clan-b", "bot_alias": None}


def test_linking_an_account_on_one_bot_clears_the_cache_of_every_bot():
    store = LinkStore()
    assert asyncio.run(handlers.clan_of_user(store, 7, ALIAS)).alias == "clan-b"
    assert handlers.userclan_key(store, 7) == KEY
    store.kv.pop(KEY)
    assert asyncio.run(handlers.clan_of_user(store, 7, "bot-2")).alias == "clan-b"
    assert store.scans == 2


def test_clan_of_user_rescans_and_refreshes_a_stale_cache():
    store = LinkStore(members={"clan-a": {"#P2": {}}, "clan-b": {"#P1": {}}})
    store.kv[KEY] = {"alias": "clan-b", "bot_alias": ALIAS}
    clan = asyncio.run(handlers.clan_of_user(store, 7, ALIAS))
    assert clan.alias == "clan-a" and store.scans == 1
    assert store.kv[KEY] == {"alias": "clan-a", "bot_alias": ALIAS}
    assert asyncio.run(handlers.clan_of_user(store, 7, ALIAS)).alias == "clan-a"
    assert store.scans == 1


def test_clan_of_user_caches_the_absence_of_a_clan():
    store = LinkStore(members={"clan-a": {"#X": {}}, "clan-b": {"#P1": {}}})
    assert asyncio.run(handlers.clan_of_user(store, 7, ALIAS)) is None
    assert store.scans == 1 and store.kv[KEY] == {"alias": None, "bot_alias": ALIAS}
    assert asyncio.run(handlers.clan_of_user(store, 7, ALIAS)) is None
    assert store.scans == 1


MARIO = "#2YRLQPC0"
LUIGI = "#PQL0289"
PEACH = "#LQ2PCUV"
IT_CATALOG = json.load(open(i18n.LOCALE_DIR / "it.json", encoding="utf-8"))


def link_row(alias, user_id, tag, name, lang=None):
    return SimpleNamespace(alias=alias, user_id=user_id, tag=tag, name=name, dm=True, lang=lang,
                           verified=True)


class AccountStore:
    def __init__(self, secrets=None, clan=None, settings=None, members=None):
        self.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
        self.members = members
        self.rows = [
            link_row("link-1", 7, MARIO, "Mario"),
            link_row("link-2", 7, LUIGI, "Luigi"),
            link_row("link-3", 8, PEACH, "Peach"),
        ]
        self.kv = {"userclan:user:7": {"alias": "clan-a", "bot_alias": "bot-1"},
                   "userclan:user:8": {"alias": "clan-a", "bot_alias": "bot-1"}}
        self.secrets = dict(secrets or {})
        self.clan = clan
        self.settings = settings
        self.unlinked = []
        self.langs = []
        self.logs = []

    async def links_by_user(self, user_id):
        return [row for row in self.rows if row.user_id == user_id]

    async def links_for_players(self, tags):
        wanted = set(tags or ())
        return {row.tag: row for row in self.rows if row.tag in wanted}

    async def set_link_lang(self, user_id, lang):
        self.langs.append((user_id, lang))
        for row in self.rows:
            if row.user_id == user_id:
                row.lang = lang

    async def unlink(self, user_id, tag):
        before = len(self.rows)
        self.rows = [row for row in self.rows if not (row.user_id == user_id and row.tag == tag)]
        if len(self.rows) == before:
            return False
        self.unlinked.append((user_id, tag))
        return True

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return self.clan if self.clan and chat_id == self.clan.chat_id else None

    async def clan_by_alias(self, alias):
        return self.clan if self.clan and self.clan.alias == alias else None

    async def active_clans(self, bot_alias=None):
        return [self.clan] if self.clan else []

    async def get_state(self, alias, kind):
        if kind == "settings":
            return self.settings
        return self.members if kind == "members" else None

    async def set_state(self, alias, kind, doc):
        if kind == "settings":
            self.settings = doc

    async def add_log(self, alias, entry, at=None):
        self.logs.append({**entry, "at": at})

    async def bot_by_alias(self, alias):
        return None


class Sent:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))


class Pressed:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


def chat_update(user_id=7, chat_id=None, chat_type=ChatType.PRIVATE, data=None, sender_chat=False):
    chat = SimpleNamespace(id=chat_id if chat_id is not None else user_id, type=chat_type)
    message = Sent()
    message.sender_chat = chat if sender_chat else None
    return SimpleNamespace(
        effective_chat=chat,
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Utente"),
        effective_message=message,
        callback_query=Pressed(data) if data else None,
    )


def worker_context(store, args=None):
    return SimpleNamespace(
        bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
        args=args if args is not None else [],
        user_data={},
        bot=SimpleNamespace(username="ClanBot"),
    )


def callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def test_support_secrets_are_known_and_typed_in_clear():
    assert {"support_url", "creator_code", "source_url"} <= set(cli.SECRET_KINDS)
    assert {"support_url", "creator_code", "source_url"} <= set(cli.PLAIN_KINDS)
    assert not {"support_url", "creator_code"} & set(cli.TOKEN_KINDS)


def test_support_url_must_be_https_with_a_host():
    for good in ("https://ko-fi.com/clanboard", "https://t.me/ClanBoard", "HTTPS://Ko-fi.com/x?y=1"):
        assert util.valid_https(good), good
    for bad in ("", None, "http://ko-fi.com/clanboard", "ko-fi.com/clanboard", "https://", "https:///path",
                "https://ko fi.com", "javascript:alert(1)", "ftp://ko-fi.com", "https://[::1", "https:// ko-fi.com"):
        assert not util.valid_https(bad), bad


def test_creator_code_is_three_to_twenty_letters_or_digits():
    for good in ("ABC", "clanboard", "Clan2026", "A" * 20):
        assert cli.valid_creator_code(good), good
    for bad in ("", None, "AB", "A" * 21, "CLAN-BOARD", "CLAN BOARD", "clàn", "ＡＢＣ", "<b>x</b>"):
        assert not cli.valid_creator_code(bad), bad


class SecretStore:
    def __init__(self):
        self.saved = {}

    async def set_secret(self, kind, value):
        self.saved[kind] = value
        return "sec-1"


def test_store_secret_refuses_bad_support_values_without_echoing_them():
    store = SecretStore()
    for kind, value in (("support_url", "http://ko-fi.com/segreto"), ("creator_code", "NO-VALIDO")):
        with pytest.raises(SystemExit) as refused:
            asyncio.run(cli.store_secret(store, kind, value))
        assert value not in str(refused.value) and kind in str(refused.value)
    assert store.saved == {}
    asyncio.run(cli.store_secret(store, "support_url", "https://ko-fi.com/clanboard"))
    asyncio.run(cli.store_secret(store, "creator_code", "CLANBOARD"))
    assert store.saved == {"support_url": "https://ko-fi.com/clanboard", "creator_code": "CLANBOARD"}


def test_unlink_and_support_are_commands_with_italian_aliases_and_descriptions():
    assert ("unlink", ["scollega"]) in handlers.COMMANDS
    assert ("support", ["sostieni"]) in handlers.COMMANDS
    assert handlers.HANDLERS["unlink"] is handlers.cmd_unlink
    assert handlers.HANDLERS["support"] is handlers.cmd_support
    for key in ("cmd.unlink", "cmd.support"):
        assert key in EN and key in IT_CATALOG, key
        assert IT_CATALOG[key] != EN[key]


def registered():
    class App:
        def __init__(self):
            self.handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

    app = App()
    handlers.register(app)
    commands = set()
    patterns = set()
    for handler in app.handlers:
        commands |= set(getattr(handler, "commands", []) or [])
        pattern = getattr(handler, "pattern", None)
        if pattern is not None:
            patterns.add(pattern.pattern)
    return commands, patterns


def test_register_wires_the_unlink_buttons():
    commands, patterns = registered()
    assert {"unlink", "scollega", "support", "sostieni"} <= commands
    assert "^u:" in patterns


def test_support_in_a_clan_bot_shows_the_support_card():
    store = AccountStore(secrets={"support_url": "https://ko-fi.com/clanboard", "creator_code": "CLANBOARD"})
    update = chat_update()
    asyncio.run(handlers.cmd_support(update, worker_context(store)))
    text, markup = update.effective_message.sent[-1]
    assert text == render.support_card(L, "https://ko-fi.com/clanboard", "CLANBOARD")
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == [
        f"tip:{stars}" for stars in tips.AMOUNTS
    ]
    empty = chat_update()
    asyncio.run(handlers.cmd_support(empty, worker_context(AccountStore())))
    assert empty.effective_message.sent[0][0] == render.support_card(L, None, None)


def test_support_in_a_group_speaks_the_language_of_the_clan():
    clan = SimpleNamespace(alias="clan-a", chat_id=-100, tag="#C1", name="Clan", active=True, bot_alias="bot-1")
    store = AccountStore(secrets={"creator_code": "CLANBOARD"}, clan=clan, settings={"lang": "en", "tz": "UTC"})
    update = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.cmd_support(update, worker_context(store)))
    assert update.effective_message.sent[0][0] == render.support_card(i18n.locale("en"), None, "CLANBOARD")
    assert update.effective_message.sent[0][1].inline_keyboard[0][0].url.endswith("?start=sostieni")


def test_unlink_without_arguments_lists_only_the_accounts_of_the_user():
    store = AccountStore()
    update = chat_update()
    asyncio.run(handlers.cmd_unlink(update, worker_context(store)))
    text, markup = update.effective_message.sent[-1]
    assert L.t("unlink.choose") in text and L.t("unlink.title") in text
    assert callbacks(markup) == [[f"u:{MARIO}"], [f"u:{LUIGI}"]]
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert "Mario" in labels[0] and MARIO in labels[0] and "Luigi" in labels[1]
    assert PEACH not in str(callbacks(markup)) and store.unlinked == []


def test_unlink_asks_for_confirmation_before_unlinking():
    store = AccountStore()
    update = chat_update(data=f"u:{MARIO}")
    asyncio.run(handlers.on_unlink_callback(update, worker_context(store)))
    query = update.callback_query
    text, markup = query.edits[-1]
    assert L.t("unlink.confirm", name="Mario", tag=MARIO) in text
    assert callbacks(markup) == [[f"u:{MARIO}:yes", f"u:{MARIO}:no"]]
    labels = [button.text for button in markup.inline_keyboard[0]]
    assert labels == [L.t("unlink.btn_confirm"), L.t("console.btn_cancel")]
    assert store.unlinked == [] and "userclan:user:7" in store.kv
    assert query.answers == [(None, False)]


def test_confirming_unlinks_the_account_and_clears_the_clan_cache():
    store = AccountStore()
    update = chat_update(data=f"u:{MARIO}:yes")
    asyncio.run(handlers.on_unlink_callback(update, worker_context(store)))
    assert store.unlinked == [(7, MARIO)]
    assert "userclan:user:7" not in store.kv and "userclan:user:8" in store.kv
    text, markup = update.callback_query.edits[-1]
    assert L.t("unlink.done", name="Mario", tag=MARIO) in text and markup is None
    assert [row.tag for row in store.rows] == [LUIGI, PEACH]


def test_cancelling_keeps_the_account():
    store = AccountStore()
    update = chat_update(data=f"u:{MARIO}:no")
    asyncio.run(handlers.on_unlink_callback(update, worker_context(store)))
    assert store.unlinked == [] and "userclan:user:7" in store.kv
    assert update.callback_query.edits[-1] == (L.t("h.cancelled"), None)


def test_another_user_cannot_press_the_unlink_buttons():
    store = AccountStore()
    for data in (f"u:{MARIO}", f"u:{MARIO}:yes", f"u:{MARIO}:no"):
        update = chat_update(user_id=8, chat_id=-100, chat_type=ChatType.SUPERGROUP, data=data)
        asyncio.run(handlers.on_unlink_callback(update, worker_context(store)))
        assert update.callback_query.answers == [(L.t("unlink.not_yours"), True)]
        assert update.callback_query.edits == []
    assert store.unlinked == [] and len(store.rows) == 3
    assert store.kv.keys() == {"userclan:user:7", "userclan:user:8"}


def test_the_group_voice_cannot_press_the_unlink_buttons():
    store = AccountStore()
    for sender_chat in (True, False):
        update = anonymous_update(data=f"u:{MARIO}:yes", sender_chat=sender_chat)
        asyncio.run(handlers.on_unlink_callback(update, worker_context(store)))
        assert update.callback_query.answers == [(L.t("h.anonymous"), True)]
        assert update.callback_query.edits == []
    assert store.unlinked == [] and len(store.rows) == 3


def test_pressing_the_unlink_button_in_private_records_the_language():
    store = AccountStore()
    update = speaking_update("fr", data=f"u:{MARIO}")
    asyncio.run(handlers.on_unlink_callback(update, worker_context(store)))
    assert store.langs == [(7, "fr")]
    assert i18n.locale("fr").t("unlink.title") in update.callback_query.edits[-1][0]


def test_a_stale_button_does_not_unlink_twice():
    store = AccountStore()
    asyncio.run(handlers.on_unlink_callback(chat_update(data=f"u:{MARIO}:yes"), worker_context(store)))
    again = chat_update(data=f"u:{MARIO}:yes")
    asyncio.run(handlers.on_unlink_callback(again, worker_context(store)))
    assert store.unlinked == [(7, MARIO)]
    assert again.callback_query.answers == [(L.t("unlink.not_yours"), True)]


def test_unlink_with_a_tag_unlinks_that_account_of_the_user():
    store = AccountStore()
    update = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.cmd_unlink(update, worker_context(store, args=[LUIGI.lower().lstrip("#")])))
    assert store.unlinked == [(7, LUIGI)]
    assert "userclan:user:7" not in store.kv
    text, markup = update.effective_message.sent[-1]
    assert L.t("unlink.done", name="Luigi", tag=LUIGI) in text and markup is None


def test_unlink_with_the_tag_of_someone_else_changes_nothing():
    store = AccountStore()
    for args in ([PEACH], ["#NONVALIDO"]):
        update = chat_update()
        asyncio.run(handlers.cmd_unlink(update, worker_context(store, args=args)))
        assert update.effective_message.sent[-1] == (L.t("unlink.not_yours"), None)
    assert store.unlinked == [] and len(store.rows) == 3
    assert store.kv.keys() == {"userclan:user:7", "userclan:user:8"}


class SilentCoc:
    async def player(self, tag):
        return None, "not_found"


def speaking_update(language_code, **kw):
    update = chat_update(**kw)
    update.effective_user.language_code = language_code
    return update


def me_context(store):
    context = worker_context(store)
    context.bot_data["coc"] = SilentCoc()
    return context


def test_a_private_command_records_the_language_of_the_member():
    store = AccountStore()
    update = speaking_update("fr")
    asyncio.run(handlers.cmd_me(update, me_context(store)))
    assert store.langs == [(7, "fr")]
    assert [row.lang for row in store.rows] == ["fr", "fr", None]
    asyncio.run(handlers.cmd_me(speaking_update("fr"), me_context(store)))
    assert store.langs == [(7, "fr")]
    asyncio.run(handlers.cmd_me(speaking_update("de"), me_context(store)))
    assert store.langs == [(7, "fr"), (7, "de")]


def test_a_command_in_the_group_does_not_record_the_language_of_the_member():
    store = AccountStore(clan=group_clan(), settings={"lang": "it", "tz": "UTC"})
    update = speaking_update("fr", chat_id=-100, chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.cmd_me(update, me_context(store)))
    assert store.langs == [] and [row.lang for row in store.rows] == [None, None, None]


def test_a_language_the_bot_does_not_speak_leaves_the_member_on_the_clan_language():
    store = AccountStore()
    asyncio.run(handlers.cmd_me(speaking_update("xx"), me_context(store)))
    asyncio.run(handlers.cmd_me(speaking_update(None), me_context(store)))
    assert store.langs == [] and [row.lang for row in store.rows] == [None, None, None]


def test_the_recorded_language_is_the_one_of_the_catalogs():
    store = AccountStore()
    asyncio.run(handlers.cmd_me(speaking_update("pt-br"), me_context(store)))
    assert store.langs == [(7, "pt-BR")]
    asyncio.run(handlers.cmd_me(speaking_update("pt"), me_context(store)))
    assert store.langs == [(7, "pt-BR")]


def test_a_private_command_without_links_writes_nothing():
    store = AccountStore()
    asyncio.run(handlers.cmd_me(speaking_update("fr", user_id=9), me_context(store)))
    assert store.langs == []


def member_clan_store(lang="it", tz="Europe/Rome"):
    return AccountStore(clan=group_clan(), settings={"lang": lang, "tz": tz},
                        members={MARIO: {"name": "Mario", "role": "member"},
                                 LUIGI: {"name": "Luigi", "role": "member"}})


def in_the_group(language_code):
    return speaking_update(language_code, chat_id=-100, chat_type=ChatType.SUPERGROUP)


def test_in_private_the_view_speaks_the_member_and_keeps_the_hours_of_the_clan():
    store = member_clan_store()
    L_, tz = asyncio.run(handlers.view_locale(speaking_update("de"), worker_context(store), group_clan()))
    assert (L_.code, tz) == ("de", "Europe/Rome")
    L_, tz = asyncio.run(handlers.view_locale(in_the_group("de"), worker_context(store), group_clan()))
    assert (L_.code, tz) == ("it", "Europe/Rome")


def test_an_unknown_telegram_language_falls_back_to_the_recorded_one():
    store = member_clan_store()
    store.rows[0].lang = "de"
    L_, _ = asyncio.run(handlers.view_locale(speaking_update("xx"), worker_context(store), group_clan()))
    assert L_.code == "de"
    L_, _ = asyncio.run(handlers.view_locale(speaking_update("xx", user_id=9), worker_context(store), group_clan()))
    assert L_.code == "en"


def requirements_text(L):
    return L.t("h.requirements_current", current=L.t("h.requirements_none")) + "\n" + L.t("h.requirements_hint")


def test_a_clan_command_answers_in_private_to_the_member_and_in_the_group_to_the_clan():
    store = member_clan_store()
    private = speaking_update("de")
    asyncio.run(handlers.cmd_requirements(private, worker_context(store)))
    assert private.effective_message.sent == [(requirements_text(i18n.locale("de")), None)]
    group = in_the_group("de")
    asyncio.run(handlers.cmd_requirements(group, worker_context(store)))
    assert group.effective_message.sent == [(requirements_text(L), None)]


def test_a_clan_view_in_private_speaks_the_language_of_who_manages_it():
    store = member_clan_store()
    store.members[MARIO]["role"] = "leader"
    context = worker_context(store)
    context.bot_data["coc"] = QuietCoc()
    update = speaking_update("de")
    asyncio.run(handlers.show(update, context, "war"))
    text, markup = update.effective_message.sent[-1]
    assert text == render.war_view(i18n.locale("de"), "Europe/Rome", None) and markup is not None


def test_choosing_the_clan_language_in_private_leaves_the_screen_to_the_member():
    clan = group_clan()
    store = member_clan_store()
    store.members[MARIO]["role"] = "leader"
    update = speaking_update("de", data=f"cfg:{clan.alias}:lang:en")
    asyncio.run(handlers.on_settings_callback(update, worker_context(store)))
    assert store.settings["lang"] == "en"
    assert update.callback_query.answers == [(i18n.locale("de").t("settings.saved"), False)]


def test_the_family_follows_the_same_rule_as_the_clan():
    store = member_clan_store()

    async def family_clans(alias):
        return [group_clan()]

    store.family_clans = family_clans
    family = SimpleNamespace(alias="fam-1")
    L_, tz = asyncio.run(handlers.family_locale(store, family, speaking_update("de")))
    assert (L_.code, tz) == ("de", "Europe/Rome")
    L_, tz = asyncio.run(handlers.family_locale(store, family, in_the_group("de")))
    assert (L_.code, tz) == ("it", "Europe/Rome")


def test_a_clan_view_in_private_records_the_language_of_the_member():
    store = member_clan_store()
    asyncio.run(handlers.cmd_requirements(speaking_update("fr"), worker_context(store)))
    assert store.langs == [(7, "fr")]
    asyncio.run(handlers.cmd_requirements(in_the_group("es"), worker_context(store)))
    assert store.langs == [(7, "fr")]


def test_linking_an_account_records_the_language_right_away():
    store = FlowStore()
    context = token_context(store, TokenCoc((True, None)), LINK_FLOW)
    paste(context, TOKEN)
    assert store.linked == [(7, MARIO, "Mario")] and store.link_langs == ["it"]


def test_unlink_without_linked_accounts_explains_how_to_link():
    store = AccountStore()
    update = chat_update(user_id=9)
    asyncio.run(handlers.cmd_unlink(update, worker_context(store)))
    assert update.effective_message.sent == [(render.not_linked_me(L, "ClanBot"), None)]


class ClearableStore(SecretStore):
    def __init__(self, saved=None):
        self.saved = dict(saved or {})
        self.deleted = []

    async def delete_secret(self, kind):
        self.deleted.append(kind)
        return self.saved.pop(kind, None) is not None


def no_network(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("rete")

    monkeypatch.setattr(cli, "telegram_me", forbidden)
    monkeypatch.setattr(cli, "check_coc_keys", forbidden)


def test_a_dash_removes_the_support_secrets_without_printing_them(monkeypatch, capsys):
    no_network(monkeypatch)
    store = ClearableStore({"support_url": "https://ko-fi.com/vecchio-indirizzo", "creator_code": "VECCHIOCODICE"})
    for kind in ("support_url", "creator_code"):
        asyncio.run(cli.store_secret(store, kind, "-"))
    assert store.deleted == ["support_url", "creator_code"] and store.saved == {}
    out = capsys.readouterr().out
    assert "support_url rimosso" in out and "creator_code rimosso" in out
    assert "vecchio-indirizzo" not in out and "VECCHIOCODICE" not in out


def test_the_secret_command_reads_the_dash_and_removes(monkeypatch, capsys):
    no_network(monkeypatch)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("-\n"))
    store = ClearableStore({"support_url": "https://ko-fi.com/vecchio-indirizzo"})
    asyncio.run(cli.secret(store, "support_url"))
    assert store.deleted == ["support_url"] and store.saved == {}
    out = capsys.readouterr().out
    assert "support_url rimosso" in out and "vecchio-indirizzo" not in out


def test_a_dash_on_a_missing_support_secret_changes_nothing(monkeypatch, capsys):
    no_network(monkeypatch)
    store = ClearableStore({"owner_id": "7"})
    asyncio.run(cli.store_secret(store, "creator_code", "-"))
    assert store.deleted == ["creator_code"] and store.saved == {"owner_id": "7"}
    out = capsys.readouterr().out
    assert "creator_code" in out and "rimosso" not in out and "nulla da rimuovere" in out


def test_a_dash_or_nothing_is_refused_for_the_other_secrets(monkeypatch, capsys):
    no_network(monkeypatch)
    store = ClearableStore({"owner_id": "7"})
    for kind in ("telegram_token", "console_token", "coc_api_key", "owner_id", "owner_lang"):
        for value in ("-", ""):
            with pytest.raises(SystemExit):
                asyncio.run(cli.store_secret(store, kind, value))
    for kind in ("support_url", "creator_code"):
        with pytest.raises(SystemExit):
            asyncio.run(cli.store_secret(store, kind, ""))
    assert store.deleted == [] and store.saved == {"owner_id": "7"}


class TokenCoc:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.verified = []

    async def verify_token(self, tag, token):
        self.verified.append((tag, token))
        return self.answers.pop(0)


class FlowStore(AccountStore):
    def __init__(self):
        super().__init__()
        self.linked = []
        self.link_langs = []
        self.onboards = {}
        self.kv["terms:user:7"] = {"day": "2026-09-01"}

    async def link_player(self, user_id, tag, name, dm=False, lang=None):
        self.linked.append((user_id, tag, name))
        self.link_langs.append(lang)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        if key.startswith("ob:"):
            self.onboards[key] = obj
            return
        self.kv[key] = obj


def paste(context, text):
    update = chat_update()
    update.effective_message.text = text
    asyncio.run(handlers.on_private_text(update, context))
    return [text for text, _ in update.effective_message.sent]


def token_context(store, coc, flow, owner=None):
    context = worker_context(store)
    context.bot_data["coc"] = coc
    if owner:
        context.bot_data["bot_owner"] = owner
    context.user_data["flow"] = dict(flow)
    return context


LINK_FLOW = {"kind": "link", "step": "token", "tag": MARIO, "name": "Mario"}
ONBOARD_FLOW = {"kind": "onboard", "step": "token", "player": MARIO, "name": "Mario",
                "clan_tag": "#CLAN1", "clan_name": "Nostro Clan", "roles": {MARIO: "leader"}}
TOKEN = "tok3n-in-gioco"


@pytest.mark.parametrize("error", ["rate", "maintenance", "network"])
def test_link_keeps_the_flow_when_the_token_cannot_be_checked(error):
    store = FlowStore()
    coc = TokenCoc((None, error), (True, None))
    context = token_context(store, coc, LINK_FLOW)
    sent = paste(context, TOKEN)
    assert sent == [render.api_error(L, error, MARIO)]
    assert sent[0] != L.t("h.token_invalid") and TOKEN not in sent[0]
    assert context.user_data["flow"] == LINK_FLOW and store.linked == []
    sent = paste(context, TOKEN)
    assert store.linked == [(7, MARIO, "Mario")] and "flow" not in context.user_data
    assert coc.verified == [(MARIO, TOKEN), (MARIO, TOKEN)]
    assert sent == [render.link_done(L, "Mario", MARIO)]


def test_link_says_the_token_is_invalid_only_on_a_clean_refusal():
    store = FlowStore()
    context = token_context(store, TokenCoc((False, None)), LINK_FLOW)
    assert paste(context, TOKEN) == [L.t("h.token_invalid")]
    assert context.user_data["flow"] == LINK_FLOW and store.linked == []


@pytest.mark.parametrize("error", ["rate", "maintenance", "network"])
def test_onboarding_keeps_the_flow_when_the_leader_token_cannot_be_checked(error):
    store = FlowStore()
    coc = TokenCoc((None, error), (True, None))
    context = token_context(store, coc, ONBOARD_FLOW, owner=7)
    sent = paste(context, TOKEN)
    assert sent == [render.api_error(L, error, MARIO)]
    assert sent[0] != L.t("h.token_invalid") and TOKEN not in sent[0]
    assert context.user_data["flow"] == ONBOARD_FLOW and store.linked == [] and store.onboards == {}
    sent = paste(context, TOKEN)
    assert store.linked == [(7, MARIO, "Mario")] and "flow" not in context.user_data
    assert coc.verified == [(MARIO, TOKEN), (MARIO, TOKEN)]
    assert sent == [render.onboard_ready(L, "Nostro Clan", "#CLAN1")]
    assert [value["tag"] for value in store.onboards.values()] == ["#CLAN1"]


def test_onboarding_says_the_token_is_invalid_only_on_a_clean_refusal():
    store = FlowStore()
    context = token_context(store, TokenCoc((False, None)), ONBOARD_FLOW, owner=7)
    assert paste(context, TOKEN) == [L.t("h.token_invalid")]
    assert context.user_data["flow"] == ONBOARD_FLOW and store.linked == [] and store.onboards == {}


GROUP_ANONYMOUS_ID = 1087968824


def anonymous_update(data=None, sender_chat=True):
    return chat_update(user_id=GROUP_ANONYMOUS_ID, chat_id=-100, chat_type=ChatType.SUPERGROUP,
                       data=data, sender_chat=sender_chat)


def group_clan():
    return SimpleNamespace(alias="clan-a", chat_id=-100, tag="#C1", name="Clan", active=True, bot_alias="bot-1")


def test_the_anonymous_notice_is_written_in_italian_and_english():
    assert "a nome del gruppo" in IT_CATALOG["h.anonymous"]
    assert "as the group" in EN["h.anonymous"]
    assert IT_CATALOG["h.anonymous"] != EN["h.anonymous"]


def test_the_actor_is_nobody_when_the_group_signs_the_message():
    assert handlers.ANONYMOUS_ADMIN_ID == GROUP_ANONYMOUS_ID
    assert handlers.actor(anonymous_update()) is None
    assert handlers.actor(chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP, sender_chat=True)) is None
    assert handlers.actor(anonymous_update(sender_chat=False)) is None
    assert handlers.actor(SimpleNamespace()) is None
    speaking = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP)
    assert handlers.actor(speaking) is speaking.effective_user
    private = chat_update()
    assert handlers.actor(private) is private.effective_user


@pytest.mark.parametrize("name", ["cmd_link", "cmd_me", "cmd_unlink", "cmd_check",
                                  "cmd_settings", "cmd_lang", "cmd_cancel"])
def test_the_group_voice_cannot_run_a_personal_command(name):
    store = AccountStore()
    update = anonymous_update()
    context = worker_context(store)
    context.user_data["flow"] = {"kind": "link", "step": "tag"}
    asyncio.run(getattr(handlers, name)(update, context))
    assert update.effective_message.sent == [(L.t("h.anonymous"), None)]
    assert store.unlinked == [] and [row.tag for row in store.rows] == [MARIO, LUIGI, PEACH]
    assert context.user_data["flow"] == {"kind": "link", "step": "tag"}


def test_the_group_voice_cannot_press_the_settings_buttons():
    clan = group_clan()
    store = AccountStore(clan=clan, settings={"lang": "en", "tz": "UTC"})
    update = anonymous_update(data=f"cfg:{clan.alias}:mentions", sender_chat=False)
    asyncio.run(handlers.on_settings_callback(update, worker_context(store)))
    query = update.callback_query
    assert query.answers == [(i18n.locale("en").t("h.anonymous"), True)]
    assert query.edits == []


class QuietCoc:
    async def current_war(self, tag):
        return None, "not_found"


def test_the_clan_views_say_nothing_in_the_group():
    store = AccountStore(clan=group_clan(), settings={"lang": "it", "tz": "UTC"})
    context = worker_context(store)
    context.bot_data["coc"] = QuietCoc()
    update = anonymous_update()
    asyncio.run(handlers.show(update, context, "war"))
    assert update.effective_message.sent == []
    speaking = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.show(speaking, context, "war"))
    assert speaking.effective_message.sent == []


class GroupBot:
    def __init__(self):
        self.username = "ClanBot"
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))


class JoinStore(AccountStore):
    def __init__(self):
        super().__init__()
        self.added = []

    async def links_by_user(self, user_id):
        return [link_row("link-9", user_id, MARIO, "Mario")]

    async def bot_for_tag(self, tag):
        return None

    async def count_clans(self, bot_alias=None):
        return 0

    async def add_clan(self, chat_id, tag, name, user_id, bot_alias=None):
        self.added.append((chat_id, tag, user_id))
        return SimpleNamespace(alias="clan-new", chat_id=chat_id, tag=tag, name=name, active=True)

    async def set_state(self, alias, kind, value):
        pass


class LeaderCoc:
    async def player(self, tag):
        return {"tag": tag, "name": "Mario", "role": "leader",
                "clan": {"tag": "#CLAN1", "name": "Nostro Clan"}}, None

    async def clan(self, tag):
        return clan_json([(MARIO, "Mario", "leader", 16, 5400, 1200, 300)] + BASE_MEMBERS[1:]), None


def joined_update(user_id):
    chat = SimpleNamespace(id=-100, type=ChatType.SUPERGROUP)
    from_user = SimpleNamespace(id=user_id, language_code="it", first_name="Utente")
    change = SimpleNamespace(chat=chat, from_user=from_user,
                             new_chat_member=SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR),
                             old_chat_member=SimpleNamespace(status=ChatMemberStatus.LEFT))
    return SimpleNamespace(my_chat_member=change, effective_chat=chat, effective_user=from_user,
                           effective_message=None, callback_query=None)


def test_a_clan_is_linked_by_itself_only_for_a_leader_with_a_name():
    store, bot = JoinStore(), GroupBot()
    context = worker_context(store)
    context.bot = bot
    context.bot_data["coc"] = LeaderCoc()
    asyncio.run(handlers.on_my_chat_member(joined_update(GROUP_ANONYMOUS_ID), context))
    assert store.added == []
    assert [text for _, text in bot.sent] == [render.not_linked_view(L)]
    asyncio.run(handlers.on_my_chat_member(joined_update(7), context))
    assert store.added == [(-100, "#CLAN1", 7)]


MANAGER = 42


class ConsoleBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def linking_context(store, bot, console=None):
    context = worker_context(store)
    context.bot = bot
    context.bot_data["coc"] = LeaderCoc()
    if console is not None:
        context.bot_data["supervisor"] = SimpleNamespace(owner_bot=lambda: console)
    return context


def test_il_nuovo_clan_lo_annuncia_il_console_e_il_bot_del_clan_non_scrive_in_privato():
    store, bot, console = JoinStore(), GroupBot(), ConsoleBot()
    store.secrets["owner_id"] = str(MANAGER)
    asyncio.run(handlers.on_my_chat_member(joined_update(7), linking_context(store, bot, console)))
    assert store.added == [(-100, "#CLAN1", 7)]
    assert bot.sent and {chat_id for chat_id, _ in bot.sent} == {-100}
    assert len(console.sent) == 1
    chat_id, text = console.sent[0]
    assert chat_id == MANAGER
    assert "Nostro Clan" in text and "clan-new" in text


def test_il_clan_collegato_dal_gestore_stesso_non_si_annuncia_da_solo():
    store, bot, console = JoinStore(), GroupBot(), ConsoleBot()
    store.secrets["owner_id"] = str(MANAGER)
    asyncio.run(handlers.on_my_chat_member(joined_update(MANAGER),
                                           linking_context(store, bot, console)))
    assert store.added == [(-100, "#CLAN1", MANAGER)]
    assert console.sent == []


def test_senza_console_il_collegamento_riesce_lo_stesso_e_resta_muto():
    store, bot = JoinStore(), GroupBot()
    store.secrets["owner_id"] = str(MANAGER)
    asyncio.run(handlers.on_my_chat_member(joined_update(7), linking_context(store, bot)))
    assert store.added == [(-100, "#CLAN1", 7)]
    assert {chat_id for chat_id, _ in bot.sent} == {-100}


class RosterAccountStore(AccountStore):
    def __init__(self, roster=None):
        super().__init__(clan=group_clan(), settings={"lang": "it", "tz": "Europe/Rome"},
                         members={MARIO: {}, LUIGI: {}})
        self.roster = roster if roster is not None else {}

    async def get_state(self, alias, kind):
        if kind == "roster":
            return self.roster
        return await super().get_state(alias, kind)

    async def set_state(self, alias, kind, doc):
        if kind == "roster":
            self.roster = doc
            return
        await super().set_state(alias, kind, doc)


def test_tastiera_me_ha_un_bottone_per_account_con_indice_corto():
    links = [SimpleNamespace(tag="#P1", name="Mario"), SimpleNamespace(tag="#P2", name="Luigi")]
    state = {"#P1": {"optout": False}, "#P2": {"optout": True}}
    rows = rows_of(handlers.me_keyboard(L, links, state))
    assert [b[1] for b in rows[0]] == ["m:a:0"]
    assert [b[1] for b in rows[1]] == ["m:a:1"]
    assert rows[0][0][0] == L.t("me.anniv_on", name="Mario")
    assert rows[1][0][0] == L.t("me.anniv_off", name="Luigi")
    assert rows[-1] == [(L.t("menu.back"), "v:menu"), (L.t("menu.refresh"), "v:me")]
    assert all(len(b[1].encode()) <= 64 for row in rows for b in row)


def test_gli_account_mostrati_sono_quelli_del_tetto_dichiarato():
    links = [SimpleNamespace(tag=f"#P{i}", name=f"Nome {i}") for i in range(handlers.ME_ACCOUNTS + 2)]
    rows = rows_of(handlers.me_keyboard(L, links, {}))
    assert len(rows) == handlers.ME_ACCOUNTS + 1
    members = {link.tag: {"name": link.name} for link in links}
    assert len(handlers.goal_accounts(links, members)) == handlers.ME_ACCOUNTS


def test_la_vista_me_porta_i_bottoni_dellanniversario():
    store = RosterAccountStore({MARIO: {"optout": True}})
    update = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP)
    _, markup = asyncio.run(handlers.build_view("me", store.clan, me_context(store), update))
    assert callbacks(markup) == [["m:a:0"], ["m:a:1"], ["v:menu", "v:me"]]
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert labels[0] == L.t("me.anniv_off", name="Mario")
    assert labels[1] == L.t("me.anniv_on", name="Luigi")


def test_il_bottone_dellanniversario_accende_e_spegne_solo_il_proprio_account():
    store = RosterAccountStore({MARIO: {"optout": False}, LUIGI: {"optout": False}})
    update = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP, data="m:a:0")
    asyncio.run(handlers.on_me_callback(update, me_context(store)))
    assert store.roster[MARIO]["optout"] is True and store.roster[LUIGI]["optout"] is False
    assert update.callback_query.answers == [(L.t("me.anniv_saved"), False)]
    _, markup = update.callback_query.edits[-1]
    assert markup.inline_keyboard[0][0].text == L.t("me.anniv_off", name="Mario")
    again = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP, data="m:a:0")
    asyncio.run(handlers.on_me_callback(again, me_context(store)))
    assert store.roster[MARIO]["optout"] is False


def test_un_bottone_dellanniversario_fuori_indice_non_scrive_nulla():
    store = RosterAccountStore({MARIO: {"optout": False}})
    for data in ("m:a:9", "m:a:", "m:a:-1"):
        update = chat_update(chat_id=-100, chat_type=ChatType.SUPERGROUP, data=data)
        asyncio.run(handlers.on_me_callback(update, me_context(store)))
        assert update.callback_query.edits == []
        assert update.callback_query.answers == [(None, False)]
    assert store.roster[MARIO]["optout"] is False


def test_register_wires_the_anniversary_buttons():
    assert "^m:" in registered()[1]


def duel_player(name, tag, th=15, trophies=5000, labels=("Farming",)):
    return {"tag": tag, "name": name, "townHallLevel": th, "trophies": trophies,
            "bestTrophies": trophies + 200, "warStars": 900, "expLevel": 220,
            "league": {"id": 29000022, "name": "Legend League"},
            "heroes": [{"name": "Barbarian King", "level": 85, "village": "home"}],
            "warPreference": "in", "donations": 1200, "donationsReceived": 900,
            "attackWins": 40, "clanCapitalContributions": 90000,
            "labels": [{"name": n} for n in labels]}


def duel_clan(name, tag, level=12, streak=5):
    return {"tag": tag, "name": name, "clanLevel": level, "members": 47, "clanPoints": 41000,
            "warWinStreak": streak, "warWins": 300, "requiredTownhallLevel": 13,
            "requiredTrophies": 2000, "warLeague": {"name": "Crystal I"}}


class DuelCoc:
    def __init__(self, players=None, clans=None):
        self.players = players or {}
        self.clans = clans or {}
        self.asked = []

    async def player(self, tag):
        self.asked.append(tag)
        data = self.players.get(tag)
        return (data, None) if data else (None, "not_found")

    async def clan(self, tag):
        self.asked.append(tag)
        data = self.clans.get(tag)
        return (data, None) if data else (None, "not_found")


def duel_context(store, coc, args=None):
    context = worker_context(store, args)
    context.bot_data["coc"] = coc
    return context


def test_i_tre_comandi_di_confronto_sono_nel_menu_con_gli_alias_italiani():
    names = [name for name, _ in handlers.COMMANDS]
    assert names.index("player") == names.index("me") + 1
    assert names[names.index("player"):names.index("player") + 3] == ["player", "vs", "clanvs"]
    assert ("player", ["giocatore"]) in handlers.COMMANDS
    assert ("vs", []) in handlers.COMMANDS
    assert ("clanvs", ["clansfida"]) in handlers.COMMANDS


def test_player_senza_tag_spiega_come_si_usa():
    store = AccountStore()
    update = chat_update()
    asyncio.run(handlers.cmd_player(update, duel_context(store, DuelCoc())))
    assert update.effective_message.sent == [(L.t("player.usage"), None)]


def test_player_mostra_il_profilo_di_chiunque_con_le_etichette():
    coc = DuelCoc(players={MARIO: duel_player("Mario", MARIO, th=13)})
    update = chat_update()
    asyncio.run(handlers.cmd_player(update, duel_context(AccountStore(), coc, [MARIO.lower()])))
    text = update.effective_message.sent[0][0]
    assert L.t("player.title") in text and "Mario" in text and "🏷 Farming" in text
    assert coc.asked == [MARIO]


def test_player_su_un_tag_sconosciuto_riporta_lerrore_dellapi():
    update = chat_update()
    asyncio.run(handlers.cmd_player(update, duel_context(AccountStore(), DuelCoc(), ["#CCCC"])))
    assert update.effective_message.sent == [(render.api_error(L, "not_found", "#CCCC"), None)]


def test_vs_con_un_solo_tag_mette_a_confronto_il_proprio_account():
    coc = DuelCoc(players={MARIO: duel_player("Mario", MARIO, trophies=5000),
                           PEACH: duel_player("Peach", PEACH, trophies=4800)})
    update = chat_update()
    asyncio.run(handlers.cmd_vs(update, duel_context(AccountStore(), coc, [PEACH])))
    text = update.effective_message.sent[0][0]
    assert coc.asked == [MARIO, PEACH]
    assert L.t("vs.title") in text and "Mario" in text and "Peach" in text
    assert "◀ " + L.t("vs.field.trophies") in text
    assert "= " + L.t("vs.field.th") in text


def test_vs_mostra_le_etichette_dei_due_giocatori():
    coc = DuelCoc(players={MARIO: duel_player("Mario", MARIO, labels=("Farming",)),
                           PEACH: duel_player("Peach", PEACH, labels=("Clan Wars",))})
    update = chat_update()
    asyncio.run(handlers.cmd_vs(update, duel_context(AccountStore(), coc, [MARIO, PEACH])))
    text = update.effective_message.sent[0][0]
    assert "Mario 🏷 Farming" in text and "Peach 🏷 Clan Wars" in text


def test_vs_con_due_tag_non_ha_bisogno_dellaccount_collegato():
    coc = DuelCoc(players={MARIO: duel_player("Mario", MARIO), PEACH: duel_player("Peach", PEACH)})
    store = AccountStore()
    store.rows = []
    update = chat_update()
    asyncio.run(handlers.cmd_vs(update, duel_context(store, coc, [PEACH, MARIO])))
    assert coc.asked == [PEACH, MARIO]
    assert L.t("vs.title") in update.effective_message.sent[0][0]


def test_vs_senza_account_collegato_chiede_di_collegarsi():
    store = AccountStore()
    store.rows = []
    update = chat_update()
    asyncio.run(handlers.cmd_vs(update, duel_context(store, DuelCoc(), [PEACH])))
    assert update.effective_message.sent == [(L.t("vs.not_linked", bot="ClanBot"), None)]


def test_vs_senza_tag_spiega_come_si_usa():
    update = chat_update()
    asyncio.run(handlers.cmd_vs(update, duel_context(AccountStore(), DuelCoc())))
    assert update.effective_message.sent == [(L.t("vs.usage"), None)]


def test_clanvs_confronta_il_clan_del_gruppo_con_quello_scritto():
    clan = group_clan()
    coc = DuelCoc(clans={clan.tag: duel_clan("Clan", clan.tag, level=12, streak=5),
                         "#2PP0": duel_clan("Altro", "#2PP0", level=9, streak=7)})
    store = AccountStore(clan=clan, settings={"lang": "it", "tz": "UTC"})
    update = chat_update(chat_id=clan.chat_id, chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.cmd_clanvs(update, duel_context(store, coc, ["#2PP0"])))
    text = update.effective_message.sent[0][0]
    assert coc.asked == [clan.tag, "#2PP0"]
    assert L.t("clanvs.title") in text and "Clan" in text and "Altro" in text
    assert "◀ " + L.t("vs.field.level") in text
    assert "▶ " + L.t("vs.field.streak") in text


def test_clanvs_senza_tag_spiega_come_si_usa():
    clan = group_clan()
    store = AccountStore(clan=clan, settings={"lang": "it", "tz": "UTC"})
    update = chat_update(chat_id=clan.chat_id, chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.cmd_clanvs(update, duel_context(store, DuelCoc())))
    assert update.effective_message.sent == [(L.t("clanvs.usage"), None)]


def test_clanvs_senza_clan_collegato_lo_dice():
    store = AccountStore()
    update = chat_update(chat_id=-999, chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.cmd_clanvs(update, duel_context(store, DuelCoc(), ["#2PP0"])))
    assert update.effective_message.sent == [(render.not_linked_view(L), None)]


def test_solo_gli_account_collegati_che_sono_nel_clan_hanno_un_obiettivo():
    links = [SimpleNamespace(tag="#P1", name="Mario"), SimpleNamespace(tag="#PX", name="Fuori")]
    assert [l.tag for l in handlers.goal_accounts(links, {"#P1": {"name": "Mario"}})] == ["#P1"]
    assert handlers.goal_accounts(links, None) == []
    assert handlers.goal_accounts(None, {"#P1": {}}) == []


def test_le_tastiere_degli_obiettivi_portano_l_indice_dell_account():
    accounts = [SimpleNamespace(tag="#P1", name="Mario"), SimpleNamespace(tag="#P2", name="Luigi")]
    rows = rows_of(handlers.goal_account_keyboard(L, accounts))
    assert [b[1] for row in rows for b in row] == ["g:a:0", "g:a:1"]
    rows = rows_of(handlers.goal_kind_keyboard(L, 1, ["trophies", "th"], True, True))
    assert [b[1] for row in rows for b in row] == ["g:k:1:0", "g:k:1:1", "g:x:1", "g:a"]
    rows = rows_of(handlers.goal_kind_keyboard(L, 0, ["trophies"], False, False))
    assert [b[1] for row in rows for b in row] == ["g:k:0:0"]
    picks = [{"target": 5000, "hero": None}, {"target": 5500, "hero": None}]
    rows = rows_of(handlers.goal_target_keyboard(L, 1, 0, picks))
    assert [b[1] for row in rows for b in row] == ["g:t:1:0:0", "g:t:1:0:1", "g:b:1"]
    assert all(len(b[1].encode()) <= 64 for row in rows for b in row)


def test_il_comando_degli_obiettivi_chiude_la_fila_dei_comandi_nuovi():
    names = [name for name, _ in handlers.COMMANDS]
    assert names[names.index("me"):names.index("me") + 5] == ["me", "player", "vs", "clanvs", "goal"]
    assert ("goal", ["obiettivo"]) in handlers.COMMANDS


def test_recruit_passa_da_recruit_tools_e_apply_e_registrato():
    assert handlers.HANDLERS["recruit"] is recruit_tools.cmd_recruit
    for name in ("apply", "applications"):
        assert any(entry[0] == name for entry in handlers.COMMANDS), name
        assert handlers.HANDLERS[name] is not None
    assert not hasattr(handlers, "cmd_recruit")


def help_context():
    return SimpleNamespace(bot_data={"supervisor": None})


def test_l_aiuto_elenca_ogni_comando_registrato_raggruppato_per_area():
    piatto = [name for rows in handlers.COMMANDS_BY_AREA.values() for name, _ in rows]
    assert piatto == [name for name, _ in handlers.COMMANDS]
    assert len(piatto) == len(set(piatto))
    for code in ("it", "en"):
        locale = i18n.locale(code)
        text, offered = render.help_view(locale, handlers.COMMANDS_BY_AREA, 7)
        assert offered == [] and len(text) <= render.MAX_LEN
        for name, _ in handlers.COMMANDS:
            assert locale.t("help.cmd", name=name, text=locale.t(f"cmd.{name}")) in text, name
        for area, rows in handlers.COMMANDS_BY_AREA.items():
            if rows:
                assert f"<b>{render.help_area_title(locale, area)}</b>" in text, area
        assert locale.t("help.your_id", id=7) in text


def test_le_aree_dell_aiuto_prendono_il_nome_gia_usato_dai_pacchetti():
    for area in handlers.COMMANDS_BY_AREA:
        chiave = f"setup.pack.{area}" if area in PACKS else f"help.area.{area}"
        assert chiave in EN, area
        assert render.help_area_title(i18n.locale("en"), area) == EN[chiave]
    assert {"leaders", "data", "integrations"} <= set(handlers.COMMANDS_BY_AREA)


def test_l_aiuto_troppo_lungo_si_divide_per_area_coi_bottoni_del_menu():
    aree = [area for area, rows in handlers.COMMANDS_BY_AREA.items() if rows]
    intero, _ = render.help_view(L, handlers.COMMANDS_BY_AREA, 7)
    text, offered = render.help_view(L, handlers.COMMANDS_BY_AREA, 7, limit=len(intero) - 1)
    assert offered == aree and len(text) < len(intero)
    for name, _ in handlers.COMMANDS_BY_AREA[aree[0]]:
        assert L.t("help.cmd", name=name, text=L.t(f"cmd.{name}")) in text
    for name, _ in handlers.COMMANDS_BY_AREA[aree[1]]:
        assert L.t("help.cmd", name=name, text=L.t(f"cmd.{name}")) not in text
    seconda, _ = render.help_view(L, handlers.COMMANDS_BY_AREA, 7, area=aree[1])
    for name, _ in handlers.COMMANDS_BY_AREA[aree[1]]:
        assert L.t("help.cmd", name=name, text=L.t(f"cmd.{name}")) in seconda
    rows = rows_of(handlers.help_keyboard(L, help_context(), offered, aree[1]))
    bottoni = [button for row in rows[:-2] for button in row]
    assert [data for _, data in bottoni] == [f"h:{area}" for area in aree]
    assert all(len(row) <= handlers.HELP_COLUMNS for row in rows)
    assert handlers.HELP_COLUMNS == max(len(row) for row in handlers.MENU_ROWS)
    assert ("✓ " + render.help_area_title(L, aree[1]), f"h:{aree[1]}") in bottoni


def test_il_bottone_di_un_area_riscrive_l_aiuto_sul_posto():
    query = SimpleNamespace(data="h:wars", answers=[], edits=[])

    async def answer(text=None, show_alert=False):
        query.answers.append(text)

    async def edit_message_text(text, reply_markup=None):
        query.edits.append((text, reply_markup))

    query.answer = answer
    query.edit_message_text = edit_message_text
    update = SimpleNamespace(callback_query=query,
                             effective_user=SimpleNamespace(id=7, language_code="it"))
    asyncio.run(handlers.on_help_callback(update, help_context()))
    text, keyboard = query.edits[-1]
    assert query.answers == [None]
    for name, _ in handlers.COMMANDS_BY_AREA["wars"]:
        assert L.t("help.cmd", name=name, text=L.t(f"cmd.{name}")) in text
    assert ("✓ " + render.help_area_title(L, "wars"), "h:wars") in [
        button for row in rows_of(keyboard) for button in row]
