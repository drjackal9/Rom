import asyncio
from types import SimpleNamespace

from clashbot import handlers, i18n, media, render
from clashbot.poller import Poller

ALIAS = "bot-1"
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias=ALIAS)
IT = i18n.locale("it")


class FakeStore:
    def __init__(self, secrets=None, links=()):
        self.secrets = dict(secrets or {})
        self.links = list(links)
        self.state = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

    async def links_by_user(self, user_id):
        return list(self.links)

    async def mark_failure(self, alias):
        return {"failures": 1, "active": True}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))
        return SimpleNamespace(message_id=1)


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, kw))
        return SimpleNamespace(message_id=1)


def fake_supervisor(bot):
    return SimpleNamespace(bot=lambda alias: bot if alias == ALIAS else None,
                           running=lambda: [ALIAS], default_alias=ALIAS, owner_bot=lambda: bot)


def private_update():
    return SimpleNamespace(callback_query=None, effective_message=FakeMessage(),
                           effective_chat=SimpleNamespace(id=7, type="private"),
                           effective_user=SimpleNamespace(id=7, language_code="it"))


def group_update():
    return SimpleNamespace(callback_query=None, effective_message=FakeMessage(),
                           effective_chat=SimpleNamespace(id=-100, type="supergroup"),
                           effective_user=SimpleNamespace(id=7, language_code="it"))


def test_il_poller_manda_lanteprima_solo_per_i_link_di_clanboard():
    media.forget()
    bot, store = FakeBot(), FakeStore()
    poller = Poller(fake_supervisor(bot), store, None)
    invito = IT.t("h.link_private", bot="FuturoCoCBot")
    assert asyncio.run(poller.send(CLAN, invito)) is True
    opzioni = bot.sent[0][2]["link_preview_options"]
    assert opzioni.is_disabled is False and opzioni.url.endswith("start=collega")
    asyncio.run(poller.send(CLAN, render.card("⚔️", "GUERRA", "nessun link")))
    assert bot.sent[1][2]["link_preview_options"].is_disabled is True
    asyncio.run(poller.send_to(bot, 202, invito))
    assert bot.sent[2][2]["link_preview_options"].is_disabled is False


def test_il_poller_accende_lanteprima_anche_per_il_sito_del_gestore():
    media.forget()
    bot, store = FakeBot(), FakeStore(secrets={"site_base": "https://clanboard.it"})
    poller = Poller(fake_supervisor(bot), store, None)
    poller.site = asyncio.run(media.site_base(store))
    asyncio.run(poller.send(CLAN, "la pagina del clan: https://clanboard.it/c/abc"))
    assert bot.sent[0][2]["link_preview_options"].url == "https://clanboard.it/c/abc"
    poller.site = None
    asyncio.run(poller.send(CLAN, "la pagina del clan: https://clanboard.it/c/abc"))
    assert bot.sent[1][2]["link_preview_options"].is_disabled is True


def test_gli_inviti_a_collegarsi_hanno_lanteprima_curata():
    media.forget()
    store = FakeStore()
    update = private_update()
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": ALIAS},
                              bot=SimpleNamespace(username="FuturoCoCBot"))
    asyncio.run(handlers.cmd_me(update, context))
    text, kw = update.effective_message.sent[0]
    assert text == render.not_linked_me(IT, "FuturoCoCBot")
    assert kw["link_preview_options"].is_disabled is False
    assert kw["link_preview_options"].url.endswith("start=collega")


def test_link_e_newclan_scritti_nel_gruppo_rispondono_e_non_scoppiano():
    media.forget()
    store = FakeStore()
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": ALIAS},
                              bot=SimpleNamespace(username="FuturoCoCBot"))
    for comando, chiave in ((handlers.cmd_link, "h.link_private"),
                            (handlers.cmd_newclan, "h.newclan_private")):
        update = group_update()
        asyncio.run(comando(update, context))
        text, kw = update.effective_message.sent[0]
        assert text == IT.t(chiave, bot="FuturoCoCBot"), chiave
        assert kw["link_preview_options"].is_disabled is False, chiave
        assert kw["link_preview_options"].url.startswith("https://t.me/FuturoCoCBot?start="), chiave
