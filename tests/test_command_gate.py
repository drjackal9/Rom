import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram.constants import ChatType
from telegram.ext import CommandHandler, InlineQueryHandler

from clashbot import command_gate, guard, handlers, i18n, render
from clashbot import settings as settings_mod

IT = i18n.locale("it")
ALIAS = "bot-1"
CONSOLE = "ClanBoardBot"
SITE = "https://clanboard.cloud"

CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#C1", name="Futuro", bot_alias=ALIAS,
                       active=True, linked_by=555)

MEMBERS = {"#L": {"name": "Capo", "role": "leader"}, "#E": {"name": "Anziano", "role": "admin"},
           "#M": {"name": "Mario", "role": "member"}}

LEADER, ELDER, MEMBER, STRANGER = 7, 10, 42, 99

LINKS = {"#L": LEADER, "#E": ELDER, "#M": MEMBER}


class FakeStore:
    def __init__(self, site=None, console=None, owner=None):
        self.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
        self.kv = {}
        self.ttls = {}
        self.secrets = {"site_base": site, "owner_id": owner}
        self.console = console
        if console:
            self.kv["console:username"] = console

    async def clan_by_chat(self, chat_id, alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def active_clans(self, alias=None):
        return [CLAN]

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag=tag, user_id=uid, name=tag, lang="it", dm=False)
                for tag, uid in LINKS.items() if uid == user_id]

    async def links_for_players(self, tags):
        return {tag: SimpleNamespace(tag=tag, user_id=uid, name=tag)
                for tag, uid in LINKS.items() if tag in tags}

    async def get_state(self, alias, kind):
        return dict(MEMBERS) if kind == "members" else {}

    async def kv_get(self, key):
        if key.startswith("terms:") and key not in self.kv:
            return {"day": "2026-09-01"}
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj
        self.ttls[key] = ttl

    async def get_secret(self, name):
        return self.secrets.get(name)

    async def bot_by_alias(self, alias):
        return SimpleNamespace(alias=alias, owner_id=None)

    async def set_link_lang(self, user_id, lang):
        return None


class FakeMessage:
    def __init__(self, text=""):
        self.sent = []
        self.text = text

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=len(self.sent))


def update_for(user_id, private=True, text=""):
    message = FakeMessage(text)
    chat = SimpleNamespace(id=900 if private else CLAN.chat_id,
                           type=ChatType.PRIVATE if private else ChatType.SUPERGROUP)
    return SimpleNamespace(effective_message=message, effective_chat=chat,
                           effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                          first_name="Tizio"),
                           callback_query=None)


def pressed_by(user_id, data):
    update = update_for(user_id)
    update.callback_query = SimpleNamespace(data=data, message=update.effective_message,
                                            answer=lambda: asyncio.sleep(0))
    return update


def context_for(store, args=None, coc=None):
    return SimpleNamespace(bot_data={"store": store, "coc": coc, "bot_alias": ALIAS},
                           bot=SimpleNamespace(username="botdelclan"), args=list(args or []),
                           user_data={})


class App:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)


def registered(monkeypatch, recorder):
    monkeypatch.setattr(handlers, "HANDLERS", {name: recorder for name in handlers.HANDLERS})
    app = App()
    handlers.register(app)
    found = {}
    for handler in app.handlers:
        if isinstance(handler, CommandHandler):
            for name in handler.commands:
                found[name] = handler.callback
    return app, found


@pytest.fixture
def recorder():
    seen = []

    async def handler(update, context):
        seen.append(update.effective_user.id)

    handler.seen = seen
    return handler


def texts(update):
    return [text for text, _ in update.effective_message.sent]


def test_a_command_in_the_group_gets_no_answer_not_even_from_a_manager(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore()
    update = update_for(LEADER, private=False)
    asyncio.run(commands["war"](update, context_for(store)))
    assert update.effective_message.sent == [] and recorder.seen == []
    asyncio.run(commands["settings"](update, context_for(store)))
    assert update.effective_message.sent == [] and recorder.seen == []


def test_in_private_someone_without_a_level_gets_the_courtesy_line_once_a_day(monkeypatch,
                                                                             recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore()
    context = context_for(store)
    first = update_for(MEMBER)
    asyncio.run(commands["war"](first, context))
    assert texts(first) == [IT.t("h.private_only")]
    assert first.effective_message.sent[0][1] is None
    again = update_for(MEMBER)
    asyncio.run(commands["war"](again, context))
    assert again.effective_message.sent == []
    assert store.ttls[command_gate.courtesy_key(ALIAS, MEMBER)] == command_gate.COURTESY_TTL
    assert recorder.seen == []


def test_someone_who_never_linked_a_village_gets_the_courtesy_line_too(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore()
    update = update_for(STRANGER)
    asyncio.run(commands["war"](update, context_for(store)))
    assert texts(update) == [IT.t("h.private_only")]


def test_the_courtesy_line_carries_the_board_button_when_the_site_answers(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore(site=SITE, console=CONSOLE)
    update = update_for(MEMBER)
    asyncio.run(commands["war"](update, context_for(store)))
    text, markup = update.effective_message.sent[0]
    button = markup.inline_keyboard[0][0]
    assert text == IT.t("h.private_only") and button.text == IT.t("board.all.open")
    assert button.url.startswith(f"https://t.me/{CONSOLE}/ClanBoard?startapp=")


def test_a_limited_manager_confirms_warnings_but_does_not_touch_the_settings(monkeypatch,
                                                                            recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore()
    context = context_for(store)
    allowed = update_for(ELDER)
    asyncio.run(commands["warnings"](allowed, context))
    assert recorder.seen == [ELDER] and allowed.effective_message.sent == []
    refused = update_for(ELDER)
    asyncio.run(commands["settings"](refused, context))
    assert texts(refused) == [IT.t("h.not_allowed")] and recorder.seen == [ELDER]


def test_a_manager_passes_the_gate_in_private(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore()
    update = update_for(LEADER)
    asyncio.run(commands["settings"](update, context_for(store)))
    assert recorder.seen == [LEADER] and update.effective_message.sent == []


def test_the_gate_hands_back_the_clan_and_the_level():
    assert handlers.gate is command_gate.gate
    store = FakeStore()
    update, context = update_for(LEADER), context_for(store)
    assert asyncio.run(command_gate.gate(update, context)) == (CLAN, settings_mod.MANAGER)
    elder = update_for(ELDER)
    assert asyncio.run(command_gate.gate(elder, context)) == (CLAN, settings_mod.LIMITED)
    assert asyncio.run(command_gate.gate(elder, context, "warnings")) == (CLAN,
                                                                         settings_mod.LIMITED)
    assert asyncio.run(command_gate.gate(update_for(ELDER), context, "settings")) is None


def test_the_courtesy_key_is_reachable_from_handlers_without_a_second_copy():
    assert handlers.COURTESY_KEY == "courtesy:{alias}:{uid}"
    assert handlers.COURTESY_KEY is command_gate.COURTESY_KEY
    assert handlers.COURTESY_KEY.format(alias=ALIAS,
                                        uid=MEMBER) == command_gate.courtesy_key(ALIAS, MEMBER)


def test_the_actions_of_the_gate_are_the_ones_the_settings_know():
    assert set(command_gate.ACTION_BY_COMMAND.values()) <= set(settings_mod.ACTIONS)
    assert command_gate.ACTION_BY_COMMAND["settings"] == "settings"
    assert command_gate.ACTION_BY_COMMAND["warnings"] == "warnings"
    known = {name for name, _ in handlers.COMMANDS}
    assert set(command_gate.ACTION_BY_COMMAND) <= known


def test_the_menu_and_the_alerts_commands_are_gone():
    names = {name for name, _ in handlers.COMMANDS}
    assert "menu" not in names and "alerts" not in names
    assert "menu" not in handlers.HANDLERS and "alerts" not in handlers.HANDLERS
    assert not hasattr(handlers, "cmd_alerts")


def test_nobody_answers_inline_any_more(monkeypatch, recorder):
    app, _ = registered(monkeypatch, recorder)
    assert not any(isinstance(handler, InlineQueryHandler) for handler in app.handlers)


def test_no_trace_of_inline_is_left_in_the_package_or_in_the_catalogs():
    package = Path(handlers.__file__).parent
    assert not (package / "inline.py").exists()
    assert "inline" not in render.CHECK_FIX
    for code in i18n.LANGUAGES:
        catalog = json.loads((i18n.LOCALE_DIR / f"{code}.json").read_text(encoding="utf-8"))
        assert not [key for key in catalog if key.startswith("inline.")], code
        assert "check.label.inline" not in catalog and "check.fix.inline" not in catalog, code


def test_the_new_lines_are_written_in_italian_and_in_english_and_in_english_elsewhere():
    for key in ("h.private_only", "h.not_allowed"):
        italian, english = i18n.locale("it").t(key), i18n.locale("en").t(key)
        assert italian and english and italian != english, key
        for code in i18n.LANGUAGES:
            if code not in ("it", "en"):
                assert i18n.locale(code).t(key) == english, (code, key)


def test_a_suspended_manager_is_told_why_instead_of_the_courtesy_line(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore()
    store.kv[guard.suspended_key(CLAN.alias, ELDER)] = {"at": 0}
    update = update_for(ELDER)
    asyncio.run(commands["warnings"](update, context_for(store)))
    assert texts(update) == [IT.t("h.suspended")] and recorder.seen == []
    assert command_gate.courtesy_key(ALIAS, ELDER) not in store.kv


def test_a_suspended_manager_who_owns_the_bot_is_stopped_the_same_way(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    platform = FakeStore(owner=str(ELDER))
    platform.kv[guard.suspended_key(CLAN.alias, ELDER)] = {"at": 0}
    update = update_for(ELDER)
    asyncio.run(commands["settings"](update, context_for(platform)))
    assert texts(update) == [IT.t("h.suspended")] and recorder.seen == []
    assert asyncio.run(command_gate.gate(update_for(ELDER), context_for(platform),
                                         "settings")) is None

    async def owned(alias):
        return SimpleNamespace(alias=alias, owner_id=ELDER)

    registrar = FakeStore()
    registrar.bot_by_alias = owned
    registrar.kv[guard.suspended_key(CLAN.alias, ELDER)] = {"at": 0}
    refused = update_for(ELDER)
    asyncio.run(commands["warnings"](refused, context_for(registrar)))
    assert texts(refused) == [IT.t("h.suspended")] and recorder.seen == []
    assert asyncio.run(command_gate.gate(update_for(ELDER), context_for(registrar),
                                         "settings")) is None


def test_lo_start_che_collega_resta_aperto_a_chiunque(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    for arg in handlers.START_LINK:
        store = FakeStore()
        context = context_for(store, args=[arg])
        update = update_for(STRANGER)
        asyncio.run(commands["start"](update, context))
        assert texts(update) == [render.link_ask_tag(IT)], arg
        assert context.user_data["flow"] == {"kind": "link", "step": "tag"}, arg
        assert command_gate.courtesy_key(ALIAS, STRANGER) not in store.kv


def test_gli_altri_ponti_dello_start_passano_dal_cancello(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    payloads = list(handlers.START_NEWCLAN) + list(handlers.START_SUPPORT) + ["apply_abc", ""]
    for arg in payloads:
        store = FakeStore()
        context = context_for(store, args=[arg] if arg else [])
        update = update_for(STRANGER)
        asyncio.run(commands["start"](update, context))
        assert texts(update) == [IT.t("h.private_only")], arg
        assert context.user_data == {} and recorder.seen == [], arg


def test_lo_start_che_crea_il_clan_vuole_il_livello_delle_impostazioni(monkeypatch, recorder):
    _, commands = registered(monkeypatch, recorder)
    store = FakeStore()
    refused = update_for(ELDER)
    limited = context_for(store, args=["nuovoclan"])
    asyncio.run(commands["start"](refused, limited))
    assert texts(refused) == [IT.t("h.not_allowed")] and limited.user_data == {}
    allowed = update_for(LEADER)
    managing = context_for(store, args=["nuovoclan"])
    asyncio.run(commands["start"](allowed, managing))
    assert texts(allowed) == [render.onboard_ask_clan(IT)]
    assert managing.user_data["flow"] == {"kind": "onboard", "step": "clan"}


def test_il_bottone_che_crea_il_clan_passa_dal_cancello_anche_se_lo_rigiocano():
    replayed, context = pressed_by(STRANGER, "ob:start"), context_for(FakeStore())
    asyncio.run(handlers.on_onboard_callback(replayed, context))
    assert texts(replayed) == [IT.t("h.private_only")] and context.user_data == {}
    linking, open_door = pressed_by(STRANGER, "ob:link"), context_for(FakeStore())
    asyncio.run(handlers.on_onboard_callback(linking, open_door))
    assert texts(linking) == [render.link_ask_tag(IT)]
    assert open_door.user_data["flow"] == {"kind": "link", "step": "tag"}
    manager, managing = pressed_by(LEADER, "ob:start"), context_for(FakeStore())
    asyncio.run(handlers.on_onboard_callback(manager, managing))
    assert texts(manager) == [render.onboard_ask_clan(IT)]
    assert managing.user_data["flow"] == {"kind": "onboard", "step": "clan"}


def test_il_testo_dell_onboarding_in_privato_ricontrolla_il_cancello():
    context = context_for(FakeStore())
    context.user_data["flow"] = {"kind": "onboard", "step": "clan"}
    stranger = update_for(STRANGER, text="#2PP")
    asyncio.run(handlers.on_private_text(stranger, context))
    assert texts(stranger) == [IT.t("h.private_only")] and context.user_data == {}
    managing = context_for(FakeStore())
    managing.user_data["flow"] = {"kind": "onboard", "step": "clan"}
    manager = update_for(LEADER, text="non un tag")
    asyncio.run(handlers.on_private_text(manager, managing))
    assert texts(manager) == [IT.t("h.tag_invalid")]
    assert managing.user_data["flow"] == {"kind": "onboard", "step": "clan"}


def test_il_testo_che_collega_va_avanti_anche_per_chi_non_gestisce():
    asked = []

    async def player(tag):
        asked.append(tag)
        return None, "network"

    context = context_for(FakeStore(), coc=SimpleNamespace(player=player))
    context.user_data["flow"] = {"kind": "link", "step": "tag"}
    update = update_for(STRANGER, text="#2PP")
    asyncio.run(handlers.on_private_text(update, context))
    assert texts(update) == [render.api_error(IT, "network", "#2PP")] and asked == ["#2PP"]
    assert context.user_data["flow"] == {"kind": "link", "step": "tag"}


NUOVO_TAG = "#2PP"


class CreaStore(FakeStore):
    def __init__(self, served=None, verified=True):
        super().__init__()
        self.served = dict(served or {})
        self.verified = verified

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag=tag, user_id=uid, name=tag, lang="it", dm=False,
                                verified=self.verified)
                for tag, uid in LINKS.items() if uid == user_id]

    async def bot_for_tag(self, tag):
        return self.served.get(tag)


class NuovoCoc:
    async def clan(self, tag):
        return {"tag": tag, "name": "Nuovo", "memberList": [{"tag": "#L", "role": "leader"}]}, None


def newclan(store, alias=ALIAS):
    context = context_for(store, coc=NuovoCoc())
    context.bot_data["bot_alias"] = alias
    context.user_data["flow"] = {"kind": "onboard", "step": "clan"}
    update = update_for(LEADER, text=NUOVO_TAG)
    asyncio.run(handlers.on_private_text(update, context))
    return update, context


def codici(store):
    return [key for key in store.kv if key.startswith("ob:")]


def test_newclan_del_capo_verificato_prepara_il_codice_del_gruppo():
    store = CreaStore()
    update, context = newclan(store)
    assert texts(update) == [render.onboard_ready(IT, "Nuovo", NUOVO_TAG)]
    assert len(codici(store)) == 1 and "flow" not in context.user_data


def test_newclan_riprende_il_clan_che_questo_bot_gia_serve():
    store = CreaStore(served={NUOVO_TAG: ALIAS})
    update, _ = newclan(store)
    assert texts(update) == [render.onboard_ready(IT, "Nuovo", NUOVO_TAG)]


def test_newclan_non_prende_il_clan_di_un_altro_bot():
    store = CreaStore(served={NUOVO_TAG: "bot-9"})
    update, context = newclan(store)
    assert texts(update) == [IT.t("console.newbot_clan_taken")]
    assert codici(store) == [] and "flow" not in context.user_data


def test_newclan_col_capo_solo_rivendicato_chiede_il_villaggio():
    store = CreaStore(verified=False)
    update, context = newclan(store)
    assert texts(update) == [render.onboard_ask_player(IT, "Nuovo")]
    assert codici(store) == [] and context.user_data["flow"]["step"] == "player"


def test_newclan_del_gestore_della_piattaforma_prende_anche_il_clan_di_un_altro_bot():
    store = CreaStore(served={NUOVO_TAG: "bot-9"})
    store.secrets["owner_id"] = str(LEADER)
    update, context = newclan(store)
    assert texts(update) == [render.onboard_ready(IT, "Nuovo", NUOVO_TAG)]
    assert len(codici(store)) == 1 and "flow" not in context.user_data


def test_newclan_del_bot_senza_alias_non_ha_la_guardia_come_link_clan():
    store = CreaStore(served={NUOVO_TAG: "bot-9"})
    update, context = newclan(store, alias=None)
    assert texts(update) == [render.onboard_ready(IT, "Nuovo", NUOVO_TAG)]
    assert len(codici(store)) == 1 and "flow" not in context.user_data
