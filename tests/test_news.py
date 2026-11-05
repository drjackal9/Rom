import asyncio
import json
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import console, events_registry, handlers, i18n, news
from clashbot import settings as settings_mod

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", active=True, bot_alias="bot-1")
OTHER = SimpleNamespace(alias="clan-2", chat_id=202, tag="#CLAN2", name="Altro", active=True, bot_alias="bot-1")


class FakeStore:
    def __init__(self, state=None):
        self.state = dict(state or {})
        self.saved = []

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = obj
        self.saved.append((alias, kind, obj))

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return next((c for c in (CLAN, OTHER) if c.chat_id == chat_id), None)

    async def active_clans(self, bot_alias=None):
        return [CLAN, OTHER]

    async def links_by_user(self, user_id):
        return [SimpleNamespace(alias="link-1", user_id=user_id, tag="#P1", name="Mario", dm=False)]

    async def links_for_players(self, tags):
        link = SimpleNamespace(alias="link-1", user_id=7, tag="#P1", name="Mario", dm=False)
        return {link.tag: link} if link.tag in set(tags or ()) else {}

    async def bot_by_alias(self, alias):
        return None

    async def kv_get(self, key):
        return None

    async def get_secret(self, kind):
        return "99" if kind == "owner_id" else None


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


def update_for(data=None, chat_id=101, user_id=7):
    return SimpleNamespace(
        callback_query=FakeQuery(data) if data else None,
        effective_message=FakeMessage(),
        effective_chat=SimpleNamespace(id=chat_id, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"),
    )


def context_for(store):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=[], user_data={}, bot=SimpleNamespace(username="ClanBoardFuturoBot"))


def members_state():
    return {("clan-1", "settings"): {"lang": "it", "tz": "Europe/Rome"},
            ("clan-1", "members"): {"#P1": {"name": "Mario", "role": "leader"}}}


def test_l_evento_esiste_nel_registro_col_pacchetto_degli_avvisi_di_piattaforma():
    entry = events_registry.EVENTS[news.EVENT]
    assert entry["pack"] == events_registry.EVENTS["system.notice"]["pack"]
    assert entry["default"] == "group"
    assert set(entry["allowed"]) == set(events_registry.GROUP_ONLY)
    assert set(entry["allowed"]) <= set(events_registry.DESTINATIONS)
    assert not [where for where in entry["allowed"] if where.endswith("_dm")]


def test_le_novita_nascono_spente_e_l_interruttore_e_uno_solo():
    assert settings_mod.DEFAULTS[news.KEY] is False
    conf = settings_mod.effective({})
    assert news.wanted(conf) is False
    assert news.wanted(settings_mod.effective({"news": True})) is True
    assert news.destination(settings_mod.effective({"news": True})) in ("group", "topic", "off")


def test_spegnere_le_novita_non_spegne_gli_avvisi_di_servizio():
    conf = settings_mod.effective({"news": False})
    assert settings_mod.route(conf, "system.notice")[0] != "off"


def test_solo_chi_comanda_accende_le_novita():
    store = FakeStore(state=members_state())
    update = update_for()
    asyncio.run(news.cmd_news(update, context_for(store)))
    text, markup = update.effective_message.sent[-1]
    assert IT.t("news.title") in text and IT.t("news.off") in text
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == ["n:on"]
    store.state[("clan-1", "members")] = {"#P1": {"name": "Mario", "role": "member"}}
    plain = update_for()
    asyncio.run(news.cmd_news(plain, context_for(store)))
    assert plain.effective_message.sent[-1][0] == IT.t("news.only_leaders")


def test_il_bottone_salva_e_mostra_il_nuovo_stato():
    store = FakeStore(state=members_state())
    on = update_for(data="n:on")
    asyncio.run(news.on_news_callback(on, context_for(store)))
    assert store.state[("clan-1", "settings")]["news"] is True
    assert IT.t("news.on") in on.callback_query.edits[-1][0]
    off = update_for(data="n:off")
    asyncio.run(news.on_news_callback(off, context_for(store)))
    assert store.state[("clan-1", "settings")]["news"] is False


def test_l_annuncio_va_solo_ai_gruppi_che_lo_hanno_attivato():
    store = FakeStore(state={
        ("clan-1", "settings"): {"lang": "it", "news": True},
        ("clan-2", "settings"): {"lang": "en"},
    })
    supervisor = SimpleNamespace(running=lambda: ["bot-1"], bot=lambda alias: object())
    targets = asyncio.run(console.broadcast_targets(store, supervisor))
    assert [clan.alias for clan, _, _ in targets] == ["clan-1"]
    assert targets[0][2] == "group"


def test_un_bot_fermo_resta_fuori_anche_se_le_novita_sono_accese():
    store = FakeStore(state={("clan-1", "settings"): {"news": True}, ("clan-2", "settings"): {"news": True}})
    supervisor = SimpleNamespace(running=lambda: [], bot=lambda alias: None)
    assert asyncio.run(console.broadcast_targets(store, supervisor)) == []


def test_il_comando_e_agganciato_una_volta_sola():
    assert ("news", ["novita"]) in handlers.COMMANDS
    assert [name for name, _ in handlers.COMMANDS].count("news") == 1
    assert handlers.HANDLERS["news"] is news.cmd_news


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("news.title", "news.body", "news.on", "news.off", "news.btn_on", "news.btn_off",
                "news.only_leaders", "cmd.news", "setup.event.system.news"):
        assert key in EN, key
