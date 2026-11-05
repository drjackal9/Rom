import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram import Update
from telegram.constants import ChatType
from telegram.error import TelegramError

from clashbot import __main__ as cli
from clashbot import handlers, i18n, privacy, render, support_cards, tips
from clashbot.bot import ALLOWED_UPDATES

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)


class FakeVault:
    def blind(self, label, value):
        return f"{label}-{value}-0123456789abcdef"


class FakeStore:
    def __init__(self, secrets=None):
        self.vault = FakeVault()
        self.secrets = dict(secrets or {})
        self.kv = {}
        self.ttls = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def get_state(self, alias, kind):
        return None

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

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
    def __init__(self, payment=None, refunded=None):
        self.text = ""
        self.successful_payment = payment
        self.refunded_payment = refunded
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


class FakeCheckout:
    def __init__(self, payload):
        self.invoice_payload = payload
        self.answers = []

    async def answer(self, ok=True, error_message=None):
        self.answers.append((ok, error_message))


class FakeBot:
    def __init__(self, fail=False, refund=True):
        self.username = "ClanBoardFuturoBot"
        self.invoices = []
        self.refunds = []
        self.fail = fail
        self.refund_ok = refund

    async def send_invoice(self, **kw):
        if self.fail:
            raise TelegramError("no")
        self.invoices.append(kw)

    async def refund_star_payment(self, user_id, telegram_payment_charge_id):
        self.refunds.append((user_id, telegram_payment_charge_id))
        return self.refund_ok


def update_for(data=None, chat_type=ChatType.PRIVATE, payment=None, refunded=None, checkout=None):
    return SimpleNamespace(
        callback_query=FakeQuery(data) if data else None,
        pre_checkout_query=checkout,
        effective_message=FakeMessage(payment, refunded),
        effective_chat=SimpleNamespace(id=7, type=chat_type),
        effective_user=SimpleNamespace(id=7, language_code="it", first_name="Mario"),
    )


def context_for(store, bot=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=[], user_data={}, bot=bot or FakeBot())


def test_i_tagli_sono_fissi_e_la_fattura_e_in_stelle():
    store, bot = FakeStore(), FakeBot()
    update = update_for(data="tip:100")
    asyncio.run(tips.on_tip_callback(update, context_for(store, bot)))
    invoice = bot.invoices[0]
    assert invoice["chat_id"] == 7 and invoice["currency"] == "XTR"
    assert invoice["payload"] == "clanboard-tip:100"
    assert [(price.label, price.amount) for price in invoice["prices"]] == [(IT.t("tip.label", n=100), 100)]
    assert "provider_token" not in invoice
    assert tips.amount("100") == 100 and tips.amount("7") is None and tips.amount("x") is None


def test_nel_gruppo_la_fattura_non_parte():
    store, bot = FakeStore(), FakeBot()
    update = update_for(data="tip:50", chat_type=ChatType.SUPERGROUP)
    asyncio.run(tips.on_tip_callback(update, context_for(store, bot)))
    assert bot.invoices == []
    assert update.callback_query.answers[-1] == (IT.t("tip.private_only", bot="ClanBoardFuturoBot"), True)


def test_il_prepagamento_passa_solo_per_le_nostre_fatture():
    good = FakeCheckout("clanboard-tip:100")
    asyncio.run(tips.on_pre_checkout(update_for(checkout=good), context_for(FakeStore())))
    assert good.answers == [(True, None)]
    bad = FakeCheckout("altro:1")
    asyncio.run(tips.on_pre_checkout(update_for(checkout=bad), context_for(FakeStore())))
    assert bad.answers[0][0] is False and bad.answers[0][1]


def test_il_ringraziamento_e_privato_e_non_mostra_l_identificativo_del_pagamento():
    store = FakeStore()
    payment = SimpleNamespace(invoice_payload="clanboard-tip:100", total_amount=100,
                              telegram_payment_charge_id="ch-1")
    update = update_for(payment=payment)
    asyncio.run(tips.on_paid(update, context_for(store)))
    text, markup = update.effective_message.sent[-1]
    assert IT.t("tip.thanks.title") in text and IT.t("tip.where") in text
    assert "ch-1" not in text
    key = privacy.user_key(store, "tip", 7)
    row = store.kv[key]["rows"][0]
    assert row["charge"] == "ch-1"
    assert [b.callback_data for r in markup.inline_keyboard for b in r] == [f"tip:r:{row['ref']}"]
    assert row["ref"] != "ch-1" and "ch-1" not in markup.inline_keyboard[0][0].callback_data
    assert len(markup.inline_keyboard[0][0].callback_data.encode()) < 64
    assert store.ttls[key] == tips.KEEP_DAYS * 86400


def test_la_ricevuta_tiene_solo_le_ultime_cinque():
    store = FakeStore()
    for n in range(7):
        asyncio.run(tips.remember(store, 7, 10, f"ch-{n}", NOW))
    rows = store.kv[privacy.user_key(store, "tip", 7)]["rows"]
    assert len(rows) == tips.MAX_RECORDS
    assert [row["charge"] for row in rows] == ["ch-2", "ch-3", "ch-4", "ch-5", "ch-6"]


def test_il_rimborso_parte_dal_bottone_e_la_ricevuta_si_svuota():
    store, bot = FakeStore(), FakeBot()
    ref = asyncio.run(tips.remember(store, 7, 100, "ch-1", NOW))
    update = update_for(data=f"tip:r:{ref}")
    asyncio.run(tips.on_tip_callback(update, context_for(store, bot)))
    assert bot.refunds == [(7, "ch-1")]
    assert IT.t("tip.refunded", n=100) in update.callback_query.edits[-1][0]
    assert store.kv[privacy.user_key(store, "tip", 7)]["rows"][0]["charge"] == ""
    again = update_for(data=f"tip:r:{ref}")
    asyncio.run(tips.on_tip_callback(again, context_for(store, FakeBot(refund=False))))
    assert again.callback_query.answers[-1] == (IT.t("tip.refund_failed"), True)


def test_il_bottone_resta_legato_alla_sua_mancia_anche_dopo_il_giro_della_ricevuta():
    store, bot = FakeStore(), FakeBot()
    refs = [asyncio.run(tips.remember(store, 7, 10 * (n + 1), f"ch-{n}", NOW)) for n in range(6)]
    assert len(set(refs)) == 6
    update = update_for(data=f"tip:r:{refs[1]}")
    asyncio.run(tips.on_tip_callback(update, context_for(store, bot)))
    assert bot.refunds == [(7, "ch-1")]
    assert IT.t("tip.refunded", n=20) in update.callback_query.edits[-1][0]
    gone = update_for(data=f"tip:r:{refs[0]}")
    asyncio.run(tips.on_tip_callback(gone, context_for(store, FakeBot())))
    assert gone.callback_query.answers[-1] == (IT.t("tip.refund_failed"), True)


def test_un_rimborso_arrivato_da_telegram_toglie_la_riga():
    store = FakeStore()
    asyncio.run(tips.remember(store, 7, 100, "ch-1", NOW))
    refunded = SimpleNamespace(telegram_payment_charge_id="ch-1", total_amount=100,
                               invoice_payload="clanboard-tip:100")
    asyncio.run(tips.on_refunded(update_for(refunded=refunded), context_for(store)))
    assert store.kv[privacy.user_key(store, "tip", 7)]["rows"] == []


def test_telegram_ci_manda_la_richiesta_di_prepagamento():
    assert Update.PRE_CHECKOUT_QUERY in ALLOWED_UPDATES


def test_la_card_di_supporto_aggiunge_twitch_solo_quando_c_e():
    plain = render.support_card(IT, "https://ko-fi.com/clanboard", "CLANBOARD")
    with_twitch = render.support_card(IT, "https://ko-fi.com/clanboard", "CLANBOARD", "https://twitch.tv/clanboard")
    assert IT.t("support.twitch", url="https://twitch.tv/clanboard") in with_twitch
    assert "twitch" not in plain.lower()
    assert render.support_card(IT, None, None, None) == render.support_card(IT, None, None)


def test_il_canale_twitch_e_un_segreto_del_gestore_validato():
    assert "twitch_url" in cli.SECRET_KINDS and "twitch_url" in cli.PLAIN_KINDS
    assert "twitch_url" in cli.CLEARABLE_KINDS and "twitch_url" not in cli.TOKEN_KINDS
    for good in ("https://twitch.tv/clanboard", "https://www.twitch.tv/clanboard"):
        assert cli.valid_twitch_url(good), good
    for bad in ("", None, "http://twitch.tv/x", "https://twitch.tv.evil.com/x", "https://youtube.com/x"):
        assert not cli.valid_twitch_url(bad), bad


def test_support_in_privato_offre_le_stelle_e_nel_gruppo_il_link():
    store = FakeStore(secrets={"support_url": "https://ko-fi.com/clanboard", "twitch_url": "https://twitch.tv/cb"})
    private = update_for()
    asyncio.run(handlers.cmd_support(private, context_for(store)))
    text, markup = private.effective_message.sent[-1]
    assert IT.t("support.twitch", url="https://twitch.tv/cb") in text
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == ["tip:10", "tip:50", "tip:100", "tip:500"]
    group = update_for(chat_type=ChatType.SUPERGROUP)
    asyncio.run(handlers.cmd_support(group, context_for(store)))
    assert group.effective_message.sent[-1][1].inline_keyboard[0][0].url == (
        "https://t.me/ClanBoardFuturoBot?start=sostieni"
    )
    assert set(handlers.START_SUPPORT) == {"sostieni", "support"}


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("tip.title", "tip.body", "tip.label", "tip.btn", "tip.btn_private", "tip.where",
                "tip.thanks.title", "tip.thanks.body", "tip.btn_refund", "tip.refunded",
                "tip.refund_failed", "tip.failed", "tip.private_only", "support.twitch"):
        assert key in EN, key


def test_le_carte_delle_mance_parlano_al_singolare_e_al_plurale():
    assert IT.t("tip.thanks.body", n=1) in support_cards.thanks_card(IT, 1)
    assert IT.t("tip.thanks.body", n=3) in support_cards.thanks_card(IT, 3)
    assert IT.t("tip.where") in support_cards.thanks_card(IT, 3)
    labels = [b.text for row in support_cards.tip_keyboard(IT, tips.AMOUNTS).inline_keyboard for b in row]
    assert labels == [IT.t("tip.btn", n=stars) for stars in tips.AMOUNTS]
