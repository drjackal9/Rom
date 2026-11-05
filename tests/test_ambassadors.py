import asyncio
import copy
import pathlib
from types import SimpleNamespace

from telegram.constants import ChatType
from telegram.error import Forbidden

from clashbot import ambassadors, badges, challenges, console, feed, handlers, i18n, render

IT = i18n.locale("it")
CLAN = SimpleNamespace(alias="clan-1", bot_alias="bot-1", chat_id=101, name="Futuro")


class FakeVault:
    key_id = "k1"

    def blind(self, label, value):
        return f"{label}:{value}"


class FakeStore:
    def __init__(self, links=None):
        self.vault = FakeVault()
        self.kv = {}
        self.state = {}
        self.links = list(links or [])

    async def get_secret(self, kind):
        return None

    async def links_by_user(self, user_id):
        return [link for link in self.links if link.user_id == int(user_id)]

    async def update_link(self, link):
        return True

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

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None


class FakeBot:
    username = "ClanBoardBot"

    def __init__(self, error=None):
        self.sent = []
        self.error = error

    async def send_message(self, chat_id, text, **kw):
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text))


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))


def group_update(user_id=7):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.GROUP),
        effective_user=SimpleNamespace(id=user_id, first_name="Alex", language_code="it"),
        effective_message=FakeMessage(),
    )


def context(store, bot=None, args=None):
    console_bot = bot or FakeBot()
    return SimpleNamespace(
        bot_data={"store": store, "coc": None, "bot_alias": CLAN.bot_alias,
                  "supervisor": SimpleNamespace(bot=lambda alias: console_bot,
                                                owner_bot=lambda: console_bot)},
        args=args if args is not None else [],
        bot=console_bot,
        user_data={},
    )


def test_ambasciatori_anonimi_di_default_e_visibili_solo_con_l_opt_in():
    store = FakeStore()
    code = asyncio.run(ambassadors.invite(store, 7, CLAN.alias))
    assert code and f"amb:{code}" in store.kv
    assert store.kv[f"amb:{code}"]["by"] == "user:7"
    assert asyncio.run(ambassadors.remember(store, 9, code)) is True
    assert asyncio.run(ambassadors.remember(store, 9, "codice-finto")) is False
    row = asyncio.run(ambassadors.credit(store, 9))
    assert row["n"] == 1 and row["uid"] == 7 and row["clan"] == CLAN.alias
    assert asyncio.run(ambassadors.credit(store, 9)) is None
    rows = asyncio.run(ambassadors.board(store))
    assert rows[0]["n"] == 1 and rows[0]["name"] is None
    assert "uid" not in rows[0] and "uid" not in store.kv[ambassadors.BOARD]["user:7"]
    asyncio.run(ambassadors.set_visible(store, 7, "Alex", True))
    assert asyncio.run(ambassadors.board(store))[0]["name"] == "Alex"
    asyncio.run(ambassadors.set_visible(store, 7, "Alex", False))
    assert asyncio.run(ambassadors.board(store))[0]["name"] is None


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_il_credito_premia_chi_ha_invitato_non_chi_ha_collegato():
    store, bot = FakeStore(), FakeBot()
    code = asyncio.run(ambassadors.invite(store, 7, CLAN.alias))
    asyncio.run(ambassadors.remember(store, 9, code))
    row = asyncio.run(ambassadors.credit(store, 9))
    assert asyncio.run(ambassadors.reward(store, row)) is True
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(state, 7) == ["ambasciatore"] and badges.of(state, 9) == []
    assert bot.sent == [] and len(feed_rows(store, 7)) == 1
    assert asyncio.run(ambassadors.reward(store, {"uid": 0, "clan": None})) is False


def test_con_l_evento_spento_il_badge_resta_e_la_riga_no():
    store, bot = FakeStore(), FakeBot()
    store.state[(CLAN.alias, "settings")] = {
        "lang": "it", "routes": {ambassadors.EVENT: {"to": "off", "intensity": None}}}
    code = asyncio.run(ambassadors.invite(store, 7, CLAN.alias))
    asyncio.run(ambassadors.remember(store, 9, code))
    row = asyncio.run(ambassadors.credit(store, 9))
    assert asyncio.run(ambassadors.reward(store, row)) is False
    assert bot.sent == [] and feed_rows(store, 7) == []
    assert badges.of(asyncio.run(challenges.load(store, CLAN.alias)), 7) == ["ambasciatore"]


def test_chi_non_ha_portato_nessuno_non_entra_nella_classifica():
    store = FakeStore()
    assert asyncio.run(ambassadors.set_visible(store, 7, "Alex", True)) is False
    assert asyncio.run(ambassadors.board(store)) == []
    assert asyncio.run(ambassadors.brought(store, 7)) == 0


def test_la_classifica_degli_ambasciatori_dice_ambasciatore_senza_opt_in():
    assert render.ambassadors_section(IT, []) is None
    rows = [{"who": "user:7", "n": 2, "name": None}, {"who": "user:8", "n": 1, "name": "Alex"}]
    text = render.ambassadors_section(IT, rows)
    assert IT.t("amb.anonymous") in text and "Alex" in text


def test_il_comando_invita_passa_dal_link_del_console():
    store = FakeStore()
    update = group_update()
    asyncio.run(handlers.cmd_invite(update, context(store)))
    text = update.effective_message.sent[-1][0]
    code = text.split("?start=amb")[1].strip()
    assert f"https://t.me/{FakeBot.username}?start=amb{code}" in text
    assert store.kv[f"amb:{code}"]["clan"] == CLAN.alias
    assert "invita" in dict(handlers.COMMANDS)["invite"]
    assert handlers.HANDLERS["invite"] is handlers.cmd_invite


def test_il_console_mette_da_parte_il_codice_e_non_dice_altro():
    store = FakeStore()
    asyncio.run(ambassadors.invite(store, 7, CLAN.alias))
    code = next(key.split(":", 1)[1] for key in store.kv if key.startswith("amb:"))
    update = SimpleNamespace(
        callback_query=None, managed_bot=None,
        effective_chat=SimpleNamespace(id=9, type=ChatType.PRIVATE),
        effective_user=SimpleNamespace(id=9, first_name="Luigi", language_code="it"),
        effective_message=FakeMessage(),
    )
    asyncio.run(console.cmd_start(update, context(store, args=[f"amb{code}"])))
    assert store.kv["ambpend:user:9"]["clan"] == CLAN.alias
    assert len(update.effective_message.sent) == 1


def test_l_opt_in_del_nome_si_accende_e_si_spegne_dal_bottone():
    store = FakeStore()
    code = asyncio.run(ambassadors.invite(store, 7, CLAN.alias))
    asyncio.run(ambassadors.remember(store, 9, code))
    asyncio.run(ambassadors.credit(store, 9))
    update = group_update()
    update.callback_query = SimpleNamespace(
        data="a:show", message=FakeMessage(), answer=_answer)
    asyncio.run(handlers.on_ambassador_callback(update, context(store)))
    assert asyncio.run(ambassadors.board(store))[0]["name"] == "Alex"
    update.callback_query = SimpleNamespace(
        data="a:hide", message=FakeMessage(), answer=_answer)
    asyncio.run(handlers.on_ambassador_callback(update, context(store)))
    assert asyncio.run(ambassadors.board(store))[0]["name"] is None


async def _answer(text=None, show_alert=False):
    return None


def test_chi_ha_chiuso_il_privato_tiene_il_badge_e_legge_la_riga_nel_feed():
    store = FakeStore(links=[SimpleNamespace(user_id=7, tag="#A1", dm=False)])
    bot = FakeBot()
    code = asyncio.run(ambassadors.invite(store, 7, CLAN.alias))
    asyncio.run(ambassadors.remember(store, 9, code))
    row = asyncio.run(ambassadors.credit(store, 9))
    assert asyncio.run(ambassadors.reward(store, row)) is True
    assert bot.sent == [] and len(feed_rows(store, 7)) == 1
    assert badges.of(asyncio.run(challenges.load(store, CLAN.alias)), 7) == ["ambasciatore"]


def test_il_premio_dell_ambasciatore_non_passa_piu_dal_privato():
    link = SimpleNamespace(user_id=7, tag="#A1", dm=True)
    store = FakeStore(links=[link])
    bot = FakeBot(error=Forbidden("bot was blocked by the user"))
    code = asyncio.run(ambassadors.invite(store, 7, CLAN.alias))
    asyncio.run(ambassadors.remember(store, 9, code))
    row = asyncio.run(ambassadors.credit(store, 9))
    assert asyncio.run(ambassadors.reward(store, row)) is True
    assert link.dm is True and bot.sent == []


def test_il_credito_non_manda_messaggi_per_conto_suo():
    testo = pathlib.Path(ambassadors.__file__).read_text(encoding="utf-8")
    assert "send_message" not in testo
