import asyncio
import copy
import json
from types import SimpleNamespace
from urllib.parse import unquote

from telegram.constants import ChatType

from clashbot import ambassadors, handlers, i18n, render, share

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
CONSOLE = "ClanBoardBot"
KEYS = ("share.title", "share.body", "share.text", "share.btn_share", "share.btn_newbot")
CLAN = SimpleNamespace(alias="clan-1", bot_alias="bot-1", chat_id=101, tag="#CLAN1",
                       name="Futuro", active=True)


class FakeVault:
    key_id = "k1"

    def blind(self, label, value):
        return f"{label}:{value}"


class FakeStore:
    def __init__(self, secrets=None):
        self.vault = FakeVault()
        self.kv = {}
        self.state = {(CLAN.alias, "settings"): {"lang": "it", "tz": "UTC"}}
        self.secrets = dict(secrets or {})

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def bot_by_alias(self, alias):
        return None

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def links_by_user(self, user_id):
        return []


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


def update_for(chat_id=CLAN.chat_id, chat_type=ChatType.SUPERGROUP, user_id=7):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id, first_name="Alex", language_code="it"),
        effective_message=FakeMessage(),
    )


def context_for(store, console=CONSOLE, args=None):
    manager = SimpleNamespace(username=console) if console else None
    return SimpleNamespace(
        bot_data={"store": store, "coc": None, "bot_alias": CLAN.bot_alias,
                  "supervisor": SimpleNamespace(owner_bot=lambda: manager)},
        args=args if args is not None else [],
        bot=SimpleNamespace(username="ClanBoardFuturoBot"),
        user_data={},
    )


def buttons_of(markup):
    return [button for row in markup.inline_keyboard for button in row]


def shared_text(url):
    return unquote(url.split("&text=")[1])


def test_il_link_di_condivisione_porta_il_console_e_il_testo_nella_lingua_del_clan():
    url = share.link(CONSOLE, IT)
    assert url.startswith(f"https://t.me/share/url?url=https%3A%2F%2Ft.me%2F{CONSOLE}&text=")
    assert shared_text(url) == IT.t("share.text", console=CONSOLE)
    assert f"@{CONSOLE}" in shared_text(url) and "/newbot" in shared_text(url)
    english = share.link(CONSOLE, i18n.locale("en"))
    assert shared_text(english) == i18n.locale("en").t("share.text", console=CONSOLE)
    assert shared_text(english) != shared_text(url)
    assert " " not in url and "#" not in url


def test_il_bottone_crea_il_bot_apre_il_console_su_newbot():
    assert share.newbot_link(CONSOLE) == f"https://t.me/{CONSOLE}?start=newbot"


def test_invita_risponde_con_la_card_e_i_due_bottoni():
    store = FakeStore()
    update = update_for()
    asyncio.run(handlers.cmd_invite(update, context_for(store)))
    text, markup = update.effective_message.sent[-1]
    buttons = buttons_of(markup)
    assert [b.url.split("?")[0] for b in buttons] == ["https://t.me/share/url", f"https://t.me/{CONSOLE}"]
    assert [b.text for b in buttons] == [IT.t("share.btn_share"), IT.t("share.btn_newbot")]
    assert IT.t("share.title") in text and IT.t("share.body") in text
    assert buttons[1].url == share.newbot_link(CONSOLE)


def test_invita_continua_a_regalare_il_link_personale_dell_ambasciatore():
    store = FakeStore()
    update = update_for()
    asyncio.run(handlers.cmd_invite(update, context_for(store)))
    text, markup = update.effective_message.sent[-1]
    code = text.split("?start=amb")[1].strip()
    assert store.kv[f"amb:{code}"]["clan"] == CLAN.alias and store.kv[f"amb:{code}"]["by"] == "user:7"
    assert ambassadors.link(CONSOLE, code) in text
    assert ambassadors.link(CONSOLE, code) in unquote(buttons_of(markup)[0].url)


def test_senza_console_invita_lo_dice_e_non_consuma_codici():
    store = FakeStore()
    update = update_for()
    asyncio.run(handlers.cmd_invite(update, context_for(store, console=None)))
    assert update.effective_message.sent[-1] == (IT.t("amb.unavailable"), None)
    assert store.kv == {}


def test_la_card_di_sostegno_offre_la_condivisione_in_coda():
    store = FakeStore(secrets={"support_url": "https://ko-fi.com/clanboard"})
    update = update_for()
    asyncio.run(handlers.cmd_support(update, context_for(store)))
    rows = update.effective_message.sent[-1][1].inline_keyboard
    assert rows[0][0].url.endswith("?start=sostieni")
    assert [b.text for b in rows[-1]] == [IT.t("share.btn_share")]
    assert rows[-1][0].url == share.link(CONSOLE, IT)
    private = update_for(chat_id=999, chat_type=ChatType.PRIVATE)
    asyncio.run(handlers.cmd_support(private, context_for(store)))
    stars = private.effective_message.sent[-1][1].inline_keyboard
    assert [b.callback_data for b in stars[0]] == [f"tip:{n}" for n in (10, 50, 100, 500)]
    assert [b.text for b in stars[-1]] == [IT.t("share.btn_share")]


def test_senza_console_la_card_di_sostegno_resta_com_era():
    store = FakeStore(secrets={"support_url": "https://ko-fi.com/clanboard"})
    update = update_for()
    asyncio.run(handlers.cmd_support(update, context_for(store, console=None)))
    rows = update.effective_message.sent[-1][1].inline_keyboard
    assert len(rows) == 1 and rows[0][0].url.endswith("?start=sostieni")


def test_lo_start_privato_di_chi_gestisce_offre_la_condivisione():
    store = FakeStore(secrets={"owner_id": "7"})
    update = update_for(chat_id=999, chat_type=ChatType.PRIVATE)
    asyncio.run(handlers.cmd_start(update, context_for(store)))
    text, markup = update.effective_message.sent[-1]
    rows = markup.inline_keyboard
    assert text == render.help_view(IT, handlers.COMMANDS_BY_AREA, 7)[0]
    assert len(rows) == 3
    assert [b.text for b in rows[-1]] == [IT.t("share.btn_share")]
    assert rows[-1][0].url == share.link(CONSOLE, IT)
    bare = update_for(chat_id=999, chat_type=ChatType.PRIVATE)
    asyncio.run(handlers.cmd_start(bare, context_for(store, console=None)))
    assert len(bare.effective_message.sent[-1][1].inline_keyboard) == 2


def test_il_comando_risponde_anche_a_condividi_e_a_share():
    assert ("invite", ["invita", "condividi", "share"]) in handlers.COMMANDS
    assert handlers.HANDLERS["invite"] is handlers.cmd_invite
    assert "cmd.invite" in EN


def test_le_chiavi_nuove_esistono_in_italiano_e_in_inglese():
    english = i18n.locale("en")
    for key in KEYS:
        assert key in EN, key
        assert IT.t(key, console=CONSOLE) != english.t(key, console=CONSOLE), key
