import asyncio
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import discord
from telegram.constants import ChatType

from clashbot import bridge, db, discord_link, feed, i18n, integration_cards, integration_tools
from clashbot import settings as settings_mod
from clashbot.supervisor import Supervisor

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
CFG = {"token": "dtok-1", "guild_id": 5, "guild_name": "Server", "channel_id": 9, "channel_name": "clan"}


class FakeStore:
    def __init__(self, state=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.kv = {}

    async def bot_by_alias(self, alias):
        return None

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def active_clans(self, bot_alias=None):
        return [CLAN]

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def links_for_players(self, tags):
        return {tag: SimpleNamespace(tag=tag, user_id=700, name=tag, dm=True, lang=None)
                for tag in tags}

    async def links_by_user(self, user_id):
        return []


def warnings_of(store):
    saved = store.kv.get(feed.key_of(CLAN.alias, 700)) or {}
    return [row["text"] for row in saved.get("rows") or []]


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, message_thread_id=None, disable_notification=False):
        self.sent.append((chat_id, text, message_thread_id, disable_notification))


class FakeChannel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.sent = []

    async def send(self, content, allowed_mentions=None):
        self.sent.append((content, allowed_mentions))


class FakeClient:
    def __init__(self, alias, hub, error=None):
        self.alias = alias
        self.hub = hub
        self.error = error
        self.user = SimpleNamespace(id=1)
        self.channels = {9: FakeChannel(9)}
        self.closed = False
        self.started = None
        self.connected = True

    def is_ready(self):
        return self.connected

    async def start(self, token):
        self.started = token
        if self.error:
            raise self.error
        await asyncio.Event().wait()

    async def close(self):
        self.closed = True

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)


def store_with(settings=None, cfg=CFG):
    state = {(CLAN.alias, "settings"): settings or {"lang": "it", "tz": "Europe/Rome"},
             (CLAN.alias, "members"): {"#P1": {"name": "Mario", "role": "leader"}}}
    if cfg is not None:
        state[(CLAN.alias, "discord")] = dict(cfg)
    return FakeStore(state)


def hub_for(store, bot=None, error=None):
    clients = {}

    def factory(alias, hub):
        clients[alias] = FakeClient(alias, hub, error)
        return clients[alias]

    supervisor = SimpleNamespace(bot=lambda alias: bot or FakeBot(), running=lambda: ["bot-1"],
                                 default_alias="bot-1")
    return discord_link.Hub(supervisor, store, factory=factory, every=0), clients


def test_il_ponte_parte_per_il_clan_configurato_e_muore_quando_sparisce():
    store = store_with()
    hub, clients = hub_for(store)

    async def main():
        await hub.reconcile()
        await asyncio.sleep(0)
        assert hub.alive() == [CLAN.alias]
        assert clients[CLAN.alias].started == "dtok-1"
        await store.del_state(CLAN.alias, "discord")
        await hub.reconcile()
        assert hub.alive() == [] and clients[CLAN.alias].closed is True
        await hub.stop()

    asyncio.run(main())


def test_cambiare_canale_o_token_riapre_il_ponte():
    store = store_with()
    hub, clients = hub_for(store)

    async def main():
        await hub.reconcile()
        first = clients[CLAN.alias]
        await store.set_state(CLAN.alias, "discord", dict(CFG, channel_id=10))
        await hub.reconcile()
        assert first.closed is True and clients[CLAN.alias] is not first
        await hub.stop()

    asyncio.run(main())


def test_col_pacchetto_spento_il_ponte_non_parte():
    store = store_with({"lang": "it", "tz": "Europe/Rome", "packs": {"integrations": False}})
    hub, clients = hub_for(store)

    async def main():
        await hub.reconcile()
        assert hub.alive() == [] and clients == {}
        await hub.stop()

    asyncio.run(main())


def test_da_telegram_a_discord_senza_menzioni_di_massa():
    store = store_with()
    hub, clients = hub_for(store)

    async def main():
        await hub.reconcile()
        assert await hub.to_discord(CLAN, "Mario", "ciao @everyone", None) is True
        content, mentions = clients[CLAN.alias].channels[9].sent[0]
        assert content == "**Mario**: ciao @everyone"
        assert (mentions.everyone, mentions.users, mentions.roles) == (False, False, False)
        await hub.stop()

    asyncio.run(main())


def test_da_discord_a_telegram_passa_dalle_destinazioni_della_fase_sette():
    store, bot = store_with(), FakeBot()
    hub, _ = hub_for(store, bot=bot)
    message = SimpleNamespace(author=SimpleNamespace(id=2, bot=False, display_name="Toad"),
                              webhook_id=None, channel=SimpleNamespace(id=9),
                              content="ciao <b>a tutti</b>", attachments=[])

    async def main():
        await hub.reconcile()
        assert await hub.from_discord(CLAN.alias, message) == 1
        assert bot.sent[0][0] == 101
        assert bot.sent[0][1] == "💬 <b>Toad</b>: ciao &lt;b&gt;a tutti&lt;/b&gt;"
        assert await hub.from_discord(CLAN.alias, SimpleNamespace(
            author=SimpleNamespace(id=1, bot=True), webhook_id=None,
            channel=SimpleNamespace(id=9), content="eco", attachments=[])) == 0
        await hub.stop()

    asyncio.run(main())


def test_di_notte_il_ponte_e_silenzioso():
    store, bot = store_with({"lang": "it", "tz": "Europe/Rome", "quiet": [23, 7]}), FakeBot()
    hub, _ = hub_for(store, bot=bot)
    message = SimpleNamespace(author=SimpleNamespace(id=2, bot=False, display_name="Toad"),
                              webhook_id=None, channel=SimpleNamespace(id=9),
                              content="notturno", attachments=[])
    night = datetime(2026, 9, 15, 1, tzinfo=timezone.utc)

    async def main():
        await hub.reconcile()
        await hub.from_discord(CLAN.alias, message, night)
        assert bot.sent[0][3] is True
        await hub.from_discord(CLAN.alias, message, NOW)
        assert bot.sent[1][3] is False
        await hub.stop()

    asyncio.run(main())


def test_un_token_rifiutato_ferma_quel_ponte_e_avvisa_i_capi_una_volta():
    store, bot = store_with(), FakeBot()
    hub, _ = hub_for(store, bot=bot, error=discord.LoginFailure("no"))

    async def main():
        await hub.reconcile()
        await asyncio.sleep(0)
        await hub.reconcile()
        assert hub.alive() == []
        assert bot.sent == []
        assert IT.t("discord.error.token") in warnings_of(store)[0]
        await hub.reconcile()
        assert len(warnings_of(store)) == 1
        await hub.stop()

    asyncio.run(main())


def test_il_guasto_si_dice_una_volta_sola_anche_quando_scade_la_soglia():
    store, bot = store_with(), FakeBot()
    hub, _ = hub_for(store, bot=bot, error=discord.LoginFailure("no"))

    async def main():
        await hub.reconcile()
        await asyncio.sleep(0)
        await hub.reconcile()
        assert len(warnings_of(store)) == 1
        await store.del_state(CLAN.alias, "notices")
        await hub.reconcile()
        assert len(warnings_of(store)) == 1
        await hub.stop()

    asyncio.run(main())


def test_il_ponte_riparte_quando_il_capo_cambia_il_token_rotto():
    store, bot = store_with(), FakeBot()
    hub, clients = hub_for(store, bot=bot, error=discord.LoginFailure("no"))

    async def main():
        await hub.reconcile()
        await asyncio.sleep(0)
        await hub.reconcile()
        assert hub.alive() == []
        await store.set_state(CLAN.alias, "discord", dict(CFG, token="dtok-2"))
        await hub.reconcile()
        await asyncio.sleep(0)
        assert hub.alive() == [CLAN.alias] and clients[CLAN.alias].started == "dtok-2"
        await hub.stop()

    asyncio.run(main())


def test_un_guasto_di_rete_si_ritenta_da_solo():
    store, bot = store_with(), FakeBot()
    hub, clients = hub_for(store, bot=bot, error=OSError("rete giù"))

    async def main():
        await hub.reconcile()
        await asyncio.sleep(0)
        await hub.reconcile()
        assert IT.t("discord.error.network") in warnings_of(store)[0]
        assert hub.alive() == [CLAN.alias]
        await hub.stop()

    asyncio.run(main())


def test_un_ponte_che_si_chiude_da_solo_viene_riacceso():
    store, bot = store_with(), FakeBot()
    born = []

    class QuietClient(FakeClient):
        async def start(self, token):
            self.started = token

    def factory(alias, hub):
        born.append(QuietClient(alias, hub))
        return born[-1]

    supervisor = SimpleNamespace(bot=lambda alias: bot, running=lambda: ["bot-1"],
                                 default_alias="bot-1")
    hub = discord_link.Hub(supervisor, store, factory=factory, every=0)

    async def main():
        await hub.reconcile()
        await asyncio.sleep(0)
        await hub.reconcile()
        assert len(born) == 2 and hub.alive() == [CLAN.alias]
        await hub.stop()

    asyncio.run(main())


def test_il_canale_muto_ferma_il_ponte_solo_quando_il_client_e_pronto():
    store = store_with()
    hub, clients = hub_for(store)

    async def main():
        await hub.reconcile()
        client = clients[CLAN.alias]
        client.channels.clear()
        client.connected = False
        assert await hub.to_discord(CLAN, "Mario", "ciao", None) is False
        assert hub.broken == {}
        client.connected = True
        assert await hub.to_discord(CLAN, "Mario", "ciao", None) is False
        assert hub.broken == {CLAN.alias: "channel"}
        await hub.stop()

    asyncio.run(main())


def test_l_intent_mancante_dice_cosa_accendere():
    store, bot = store_with(), FakeBot()
    hub, _ = hub_for(store, bot=bot, error=discord.PrivilegedIntentsRequired(shard_id=None))

    async def main():
        await hub.reconcile()
        await asyncio.sleep(0)
        await hub.reconcile()
        assert IT.t("discord.error.intent") in warnings_of(store)[0]
        await hub.stop()

    asyncio.run(main())


class FakeMessage:
    def __init__(self, text="dtok-1"):
        self.text = text
        self.replies = []
        self.deleted = False

    async def delete(self):
        self.deleted = True

    async def reply_text(self, text, reply_markup=None, **kw):
        self.replies.append(text)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


class FakeTelegram:
    def __init__(self, sees_all=True):
        self.id = 99
        self.sees_all = sees_all

    async def get_me(self):
        return SimpleNamespace(can_read_all_group_messages=self.sees_all)


GUILDS = [{"id": 5, "name": "Server", "channels": [{"id": 9, "name": "clan"}]}]


def context_with(store, hub, flow=None, sees_all=True):
    return SimpleNamespace(
        bot_data={"store": store, "coc": None, "supervisor": SimpleNamespace(discord=hub),
                  "bot_alias": CLAN.bot_alias},
        user_data={"flow": flow} if flow else {}, bot=FakeTelegram(sees_all), args=[])


def private_update(message):
    return SimpleNamespace(callback_query=None, effective_message=message,
                           effective_chat=SimpleNamespace(id=7, type=ChatType.PRIVATE),
                           effective_user=SimpleNamespace(id=7, language_code="it", first_name="Mario"))


def callback_update(query):
    return SimpleNamespace(callback_query=query, effective_message=query.message,
                           effective_chat=SimpleNamespace(id=7, type=ChatType.PRIVATE),
                           effective_user=SimpleNamespace(id=7, language_code="it", first_name="Mario"))


def group_message(**kw):
    base = dict(from_user=SimpleNamespace(id=7, is_bot=False, first_name="Mario", last_name=None,
                                          username=None),
                text="ciao", caption=None, message_thread_id=None, photo=None, video=None,
                animation=None, document=None, audio=None, voice=None, sticker=None)
    base.update(kw)
    return SimpleNamespace(**base)


def group_update(message):
    return SimpleNamespace(callback_query=None, effective_message=message,
                           effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.GROUP),
                           effective_user=message.from_user)


def patch_probe(monkeypatch, result):
    async def probe(token):
        return result

    async def guard(update, context, manage=False):
        return CLAN, IT, settings_mod.effective({"lang": "it"}), None

    monkeypatch.setattr(discord_link, "probe", probe)
    monkeypatch.setattr(integration_tools, "guard", guard)


def test_le_tastiere_si_fermano_al_centinaio_di_bottoni_di_telegram():
    assert discord_link.BUTTON_LIMIT == 100
    assert not hasattr(discord_link, "GUILD_LIMIT")
    assert not hasattr(discord_link, "CHANNEL_LIMIT")
    many = [{"id": n, "name": f"c{n}"} for n in range(discord_link.BUTTON_LIMIT + 20)]
    keyboard = integration_cards.channels_keyboard(many[:discord_link.BUTTON_LIMIT])
    assert len(keyboard.inline_keyboard) == discord_link.BUTTON_LIMIT


def test_i_tre_esiti_della_prova_del_token_dicono_tre_cose_diverse(monkeypatch):
    context = SimpleNamespace(bot_data={"store": FakeStore()}, user_data={}, args=[])
    for result, key in ((([], "token"), "discord.token_bad"),
                        (([], "network"), "discord.error.network"),
                        (([], None), "discord.no_guild")):
        patch_probe(monkeypatch, result)
        message = FakeMessage()
        flow = {"kind": "discord", "step": "token"}
        asyncio.run(integration_tools.on_token(private_update(message), context, flow))
        assert message.replies == [IT.t(key)], key
        assert message.deleted is True and flow["step"] == "token" and "token" not in flow


def test_il_token_letto_apre_la_scelta_del_server(monkeypatch):
    patch_probe(monkeypatch, (GUILDS, None))
    context = SimpleNamespace(bot_data={"store": FakeStore()}, user_data={}, args=[])
    message = FakeMessage()
    flow = {"kind": "discord", "step": "token"}
    asyncio.run(integration_tools.on_token(private_update(message), context, flow))
    assert message.deleted is True and message.replies == [IT.t("discord.pick_guild")]
    assert flow["step"] == "guild" and flow["guilds"] == GUILDS


def test_il_token_non_si_incolla_nel_gruppo():
    store = store_with()
    hub, _ = hub_for(store)
    context = context_with(store, hub)
    update = group_update(group_message())
    assert asyncio.run(integration_tools.start_link(update, context, IT)) == IT.t("discord.private_only")
    assert "flow" not in context.user_data


def test_scegliere_server_e_canale_accende_il_ponte(monkeypatch):
    patch_probe(monkeypatch, ([], None))
    store = store_with(cfg=None)
    hub, clients = hub_for(store)
    flow = {"kind": "discord", "step": "guild", "token": "dtok-1", "guilds": GUILDS}
    context = context_with(store, hub, flow)

    async def main():
        first = FakeQuery("int:dc:g:5")
        await integration_tools.on_discord_callback(callback_update(first), context,
                                                    first.data.split(":"))
        assert flow["step"] == "channel" and flow["guild"]["id"] == 5
        assert first.message.replies == [IT.t("discord.pick_channel")]
        second = FakeQuery("int:dc:c:9")
        await integration_tools.on_discord_callback(callback_update(second), context,
                                                    second.data.split(":"))
        saved = await store.get_state(CLAN.alias, "discord")
        assert saved["token"] == "dtok-1" and saved["channel_id"] == 9 and saved["by"] == 7
        assert "flow" not in context.user_data
        assert hub.alive() == [CLAN.alias]
        await hub.stop()

    asyncio.run(main())


def test_staccare_il_ponte_butta_il_token_e_spegne_il_client(monkeypatch):
    patch_probe(monkeypatch, ([], None))
    store = store_with()
    hub, clients = hub_for(store)
    context = context_with(store, hub)

    async def main():
        await hub.reconcile()
        query = FakeQuery("int:dc:off")
        await integration_tools.on_discord_callback(callback_update(query), context,
                                                    query.data.split(":"))
        assert await store.get_state(CLAN.alias, "discord") is None
        assert hub.alive() == [] and clients[CLAN.alias].closed is True
        assert query.answers == [IT.t("discord.removed")]
        await hub.stop()

    asyncio.run(main())


def test_un_messaggio_del_gruppo_arriva_nel_canale_discord():
    store = store_with()
    hub, clients = hub_for(store)
    context = context_with(store, hub)

    async def main():
        await hub.reconcile()
        await integration_tools.on_group_text(group_update(group_message()), context)
        await integration_tools.on_group_text(
            group_update(group_message(text=None, caption="guarda", photo=[1])), context)
        assert [content for content, _ in clients[CLAN.alias].channels[9].sent] == [
            "**Mario**: ciao", "**Mario**: guarda [foto]"]
        await hub.stop()

    asyncio.run(main())


def test_il_gruppo_non_manda_niente_se_l_evento_e_spento():
    store = store_with({"lang": "it", "tz": "Europe/Rome",
                        "routes": {"integrations.bridge": {"to": "off"}}})
    hub, clients = hub_for(store)
    context = context_with(store, hub)

    async def main():
        await hub.reconcile()
        await integration_tools.on_group_text(group_update(group_message()), context)
        assert clients[CLAN.alias].channels[9].sent == []
        await hub.stop()

    asyncio.run(main())


def test_la_scheda_dice_lo_stato_del_ponte_e_avvisa_sulla_privacy():
    cfg = bridge.config(CFG)
    acceso = integration_cards.discord_card(IT, cfg)
    assert "Server" in acceso and "clan" in acceso and IT.t("discord.privacy") not in acceso
    assert IT.t("discord.privacy") in integration_cards.discord_card(IT, cfg, False)
    assert IT.t("discord.off") in integration_cards.discord_card(IT, None)
    assert integration_cards.discord_keyboard(IT, True).inline_keyboard[0][0].callback_data == "int:dc:off"
    assert integration_cards.discord_keyboard(IT, False).inline_keyboard[0][0].callback_data == "int:dc:link"


def test_la_configurazione_del_ponte_resta_al_ricollegamento():
    assert "discord" in db.KEEP_STATE


def test_il_supervisore_nasce_col_suo_ponte():
    store = FakeStore()
    supervisor = Supervisor(store, SimpleNamespace(keys_alive=lambda: 1))
    assert isinstance(supervisor.discord, discord_link.Hub)
    assert supervisor.discord.store is store


def test_gli_intent_sono_i_minimi_che_servono():
    intents = discord_link.make_intents()
    assert intents.guilds and intents.guild_messages and intents.message_content
    assert not intents.members and not intents.presences and not intents.dm_messages


def test_le_chiavi_del_ponte_esistono_in_inglese():
    for key in ("cmd.discord", "discord.title", "discord.off", "discord.on", "discord.help",
                "discord.privacy", "discord.btn_link", "discord.btn_unlink", "discord.private_only",
                "discord.ask_token", "discord.token_warning", "discord.token_bad", "discord.no_guild",
                "discord.pick_guild", "discord.pick_channel", "discord.saved", "discord.removed",
                "discord.error.token", "discord.error.intent", "discord.error.channel",
                "discord.error.permission", "discord.error.network"):
        assert key in EN, key
