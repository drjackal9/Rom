import asyncio
import json
import logging
import pathlib
from types import SimpleNamespace

from telegram.constants import ChatType
from telegram.error import TelegramError

from clashbot import i18n, manager_alerts, platform, privacy, support_desk

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
HELPER = 7
MEMBER = 5


class FakeVault:
    def blind(self, label, value):
        return f"{label}-{value}-0123456789abcdef"


class FakeStore:
    def __init__(self, secrets=None, clan=None):
        self.vault = FakeVault()
        self.secrets = dict(secrets or {})
        self.clan = clan
        self.state = {("clan-1", "settings"): {"lang": "it", "tz": "Europe/Rome"}}
        self.kv = {}
        self.ttls = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return self.clan

    async def links_by_user(self, user_id):
        return []

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj
        self.ttls[key] = ttl

    async def kv_del(self, key):
        self.kv.pop(key, None)


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
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


class OwnerBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise TelegramError("no")
        self.sent.append((chat_id, text))


def update_for(text="", chat_type=ChatType.PRIVATE, chat_id=101, data=None, user_id=7):
    return SimpleNamespace(
        callback_query=FakeQuery(data) if data else None,
        effective_message=FakeMessage(text),
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"),
    )


def context_for(store, owner_bot=None, user_data=None):
    supervisor = SimpleNamespace(owner_bot=lambda: owner_bot)
    return SimpleNamespace(
        bot_data={"store": store, "coc": None, "bot_alias": "bot-1", "supervisor": supervisor},
        args=[], user_data=dict(user_data or {}),
        bot=SimpleNamespace(username="ClanBoardFuturoBot"),
    )


def test_la_guida_funziona_nel_gruppo_e_porta_a_collegarsi():
    update = update_for(chat_type=ChatType.SUPERGROUP)
    asyncio.run(support_desk.cmd_guide(update, context_for(FakeStore(clan=CLAN))))
    text, markup = update.effective_message.sent[-1]
    assert IT.t("guide.title") in text
    assert markup.inline_keyboard[0][0].url == "https://t.me/ClanBoardFuturoBot?start=collega"
    assert "<code>" not in text


def test_feedback_in_un_gruppo_rimanda_in_privato():
    update = update_for(chat_type=ChatType.SUPERGROUP)
    asyncio.run(support_desk.cmd_feedback(update, context_for(FakeStore())))
    assert update.effective_message.sent[-1][0] == IT.t("feedback.private_only", bot="ClanBoardFuturoBot")


def staff_store(secrets=None, clan=None):
    store = FakeStore(secrets=secrets, clan=clan)
    store.kv[platform.KEY] = [{"username": "aiuto", "user_id": HELPER}]
    return store


def buttons(update):
    markup = update.effective_message.sent[-1][1]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_il_delegato_sceglie_la_categoria_e_scrive_a_testo_libero():
    store = staff_store()
    ask = update_for()
    ctx = context_for(store)
    asyncio.run(support_desk.cmd_feedback(ask, ctx))
    assert buttons(ask) == ["f:idea", "f:bug", "f:translation", "f:other"]
    picked = update_for(data="f:bug")
    asyncio.run(support_desk.on_feedback_callback(picked, ctx))
    assert ctx.user_data["flow"] == {"kind": "feedback", "category": "bug"}
    assert IT.t("feedback.ask", n=support_desk.TEXT_MAX) in picked.callback_query.edits[-1][0]


def test_il_membro_vede_solo_le_quattro_scelte_fisse():
    ask = update_for(user_id=MEMBER)
    asyncio.run(support_desk.cmd_feedback(ask, context_for(staff_store())))
    assert buttons(ask) == ["f:bot_down", "f:war_stale", "f:link", "f:community"]
    assert IT.t("feedback.report") in ask.effective_message.sent[-1][0]


def test_la_segnalazione_a_scelta_fissa_arriva_con_chi_e_da_dove():
    store = staff_store(secrets={"owner_id": "99", "owner_lang": "it"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot)
    picked = update_for(data="f:war_stale", user_id=MEMBER)
    asyncio.run(support_desk.on_feedback_callback(picked, ctx))
    chat_id, text = bot.sent[0]
    assert chat_id == 99
    assert IT.t("feedback.cat.war_stale") in text
    assert f"<code>{MEMBER}</code>" in text and "clan-1" in text and "bot-1" in text
    assert picked.callback_query.edits[-1][0] == IT.t("feedback.sent")


def test_la_segnalazione_a_scelta_fissa_non_porta_testo_ne_si_salva():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot)
    asyncio.run(support_desk.on_feedback_callback(update_for(data="f:link", user_id=MEMBER), ctx))
    assert "<blockquote>" not in bot.sent[0][1]
    assert "flow" not in ctx.user_data
    key = privacy.user_key(store, "fb", MEMBER)
    assert sorted(store.kv) == sorted([platform.KEY, key]) and set(store.kv[key]) == {"ts"}


def test_una_seconda_segnalazione_troppo_presto_viene_fermata():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot)
    asyncio.run(support_desk.on_feedback_callback(update_for(data="f:link", user_id=MEMBER), ctx))
    second = update_for(data="f:bot_down", user_id=MEMBER)
    asyncio.run(support_desk.on_feedback_callback(second, ctx))
    assert len(bot.sent) == 1
    assert second.callback_query.edits[-1][0] == IT.t("feedback.too_soon", n=10)


def test_il_membro_non_manda_testo_libero():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot, {"flow": {"kind": "feedback", "category": "idea"}})
    update = update_for(text="un testo qualsiasi", user_id=MEMBER)
    asyncio.run(support_desk.on_text(update, ctx, ctx.user_data["flow"]))
    assert bot.sent == [] and "flow" not in ctx.user_data
    assert update.effective_message.sent[-1][0] == IT.t("feedback.fixed_only")
    assert list(store.kv) == [platform.KEY]


def test_il_membro_che_forgia_la_categoria_libera_non_scrive():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot)
    picked = update_for(data="f:idea", user_id=MEMBER)
    asyncio.run(support_desk.on_feedback_callback(picked, ctx))
    assert "flow" not in ctx.user_data and bot.sent == []
    assert picked.callback_query.edits == [] and list(store.kv) == [platform.KEY]


def test_una_scelta_inventata_non_manda_niente():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot)
    asyncio.run(support_desk.on_feedback_callback(update_for(data="f:nulla", user_id=MEMBER), ctx))
    assert bot.sent == [] and "flow" not in ctx.user_data


def test_il_messaggio_arriva_al_gestore_e_non_viene_salvato():
    store = staff_store(secrets={"owner_id": "99", "owner_lang": "it"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot, {"flow": {"kind": "feedback", "category": "idea"}})
    update = update_for(text="  il tabellone si potrebbe fissare  ")
    asyncio.run(support_desk.on_text(update, ctx, ctx.user_data["flow"]))
    chat_id, text = bot.sent[0]
    assert chat_id == 99
    assert "il tabellone si potrebbe fissare" in text
    assert IT.t("feedback.cat.idea") in text and "clan-1" in text and "bot-1" in text
    assert update.effective_message.sent[-1][0] == IT.t("feedback.sent")
    assert "flow" not in ctx.user_data
    assert sorted(store.kv) == sorted([platform.KEY, privacy.user_key(store, "fb", 7)])
    assert set(store.kv[privacy.user_key(store, "fb", 7)]) == {"ts"}
    assert store.ttls[privacy.user_key(store, "fb", 7)] == support_desk.COOLDOWN


def test_il_testo_e_tagliato_e_scappato():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    bot = OwnerBot()
    ctx = context_for(store, bot, {"flow": {"kind": "feedback", "category": "other"}})
    long = "<b>" + "x" * 900
    asyncio.run(support_desk.on_text(update_for(text=long), ctx, ctx.user_data["flow"]))
    body = bot.sent[0][1]
    assert "&lt;b&gt;" in body and "<b>x" not in body
    assert body.count("x") == support_desk.TEXT_MAX - 3


def test_un_secondo_invio_troppo_presto_viene_fermato():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    bot = OwnerBot()
    flow = {"kind": "feedback", "category": "bug"}
    ctx = context_for(store, bot, {"flow": dict(flow)})
    asyncio.run(support_desk.on_text(update_for(text="primo"), ctx, dict(flow)))
    second = update_for(text="secondo")
    asyncio.run(support_desk.on_text(second, ctx, dict(flow)))
    assert len(bot.sent) == 1
    assert second.effective_message.sent[-1][0] == IT.t("feedback.too_soon", n=10)


def test_se_il_console_non_risponde_non_fingiamo_di_aver_mandato():
    store = staff_store(secrets={"owner_id": "99"}, clan=CLAN)
    ctx = context_for(store, OwnerBot(fail=True), {"flow": {"kind": "feedback", "category": "bug"}})
    update = update_for(text="non passa")
    asyncio.run(support_desk.on_text(update, ctx, ctx.user_data["flow"]))
    assert update.effective_message.sent[-1][0] == IT.t("feedback.failed")
    assert list(store.kv) == [platform.KEY]
    assert asyncio.run(support_desk.deliver(context_for(FakeStore()), "bug", "x", None, None)) is False


def test_la_consegna_al_gestore_passa_dalla_strada_unica(caplog):
    testo = (pathlib.Path(support_desk.__file__)).read_text(encoding="utf-8")
    assert "send_message" not in testo and "owner_id" not in testo and "owner_lang" not in testo
    store = FakeStore(secrets={"owner_id": "99", "owner_lang": "it"}, clan=CLAN)
    ctx = context_for(store, OwnerBot(fail=True))
    with caplog.at_level(logging.WARNING, logger="clashbot.platform"):
        assert asyncio.run(support_desk.deliver(ctx, "bug", "segnalazione-riservata", None, CLAN)) is False
    assert [record.name for record in caplog.records] == ["clashbot.platform"]
    assert "TelegramError" in caplog.text and "segnalazione-riservata" not in caplog.text


def test_un_gestore_senza_identificativo_valido_non_riceve_niente():
    store = FakeStore(secrets={"owner_id": "non-un-numero"}, clan=CLAN)
    bot = OwnerBot()
    assert asyncio.run(support_desk.deliver(context_for(store, bot), "bug", "x", None, CLAN)) is False
    assert bot.sent == []
    assert asyncio.run(manager_alerts.owner_id(store)) is None


def test_la_guida_e_il_feedback_sono_agganciati_ai_comandi():
    from clashbot import handlers

    assert ("guide", ["guida"]) in handlers.COMMANDS
    assert ("feedback", ["idee"]) in handlers.COMMANDS
    assert handlers.HANDLERS["guide"] is support_desk.cmd_guide
    assert handlers.HANDLERS["feedback"] is support_desk.cmd_feedback


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("guide.title", "guide.body", "guide.btn_link", "feedback.title", "feedback.intro",
                "feedback.cat.idea", "feedback.cat.bug", "feedback.cat.translation", "feedback.cat.other",
                "feedback.ask", "feedback.sent", "feedback.failed", "feedback.too_soon",
                "feedback.private_only", "feedback.owner.title", "feedback.owner.row",
                "feedback.report", "feedback.fixed_only", "feedback.cat.bot_down",
                "feedback.cat.war_stale", "feedback.cat.link", "feedback.cat.community",
                "terms.title", "terms.body", "terms.btn", "terms.read", "terms.privacy",
                "terms.done", "cmd.guide", "cmd.feedback"):
        assert key in EN, key
