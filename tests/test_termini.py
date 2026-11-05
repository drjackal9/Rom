import asyncio
from datetime import datetime, timezone

from telegram import InlineKeyboardMarkup

from clashbot import console, handlers, i18n, privacy, reasons, render, support_desk, verify
from test_console import (NEW_ID, OWNER, TAG, FakeStore as ConsoleStore, FakeSupervisor,
                          FakeTelegramBot, born, context as console_context, pressed, private)
from test_handlers import L as HL, MARIO, FlowStore, TokenCoc, chat_update, worker_context
from test_link_flow import STRANGER, TOKEN, FakeCoc, store_with
from test_intents import applied

IT = i18n.locale("it")
PRIMO = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
DOPO = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)
NUOVO = 8
SITO = "https://clanboard.example"


def giorno(store, uid):
    return asyncio.run(verify.terms_day(store, uid))


def datas(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row
            if button.callback_data]


def urls(markup):
    return [button.url for row in markup.inline_keyboard for button in row if button.url]


def test_la_data_dei_termini_si_salva_una_volta_e_non_si_riscrive(tmp_path):
    store = store_with(tmp_path)
    assert giorno(store, STRANGER) is None
    assert asyncio.run(verify.accept_terms(store, STRANGER, PRIMO)) == "2026-09-29"
    assert asyncio.run(verify.accept_terms(store, STRANGER, DOPO)) == "2026-09-29"
    assert giorno(store, STRANGER) == "2026-09-29"
    chiave = verify.terms_key(store, STRANGER)
    assert chiave == privacy.user_key(store, "terms", STRANGER)
    impronta = store.vault.blind("user", STRANGER)
    assert chiave == f"terms:{impronta}" and len(impronta) == 64
    assert chiave != f"terms:{STRANGER}" and store.kv[chiave] == {"day": "2026-09-29"}


def test_dimenticami_toglie_anche_la_data_dei_termini(tmp_path):
    store = store_with(tmp_path)
    assert verify.terms_key(store, STRANGER) in privacy.user_keys(store, STRANGER)


def test_il_collegamento_senza_il_tasto_non_scrive(tmp_path):
    store = store_with(tmp_path)
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN}, uid=STRANGER,
                   coc=coc) == reasons.TERMS
    assert store.find("#P2") is None and coc.asked == []
    assert giorno(store, STRANGER) is None
    assert asyncio.run(verify.link_verified(store, STRANGER, "#P2", "Luigi")) == reasons.TERMS
    assert store.find("#P2") is None


def test_il_collegamento_col_tasto_salva_la_data_e_collega(tmp_path):
    store = store_with(tmp_path)
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "on"},
                   uid=STRANGER, coc=coc) is True
    assert store.find("#P2").user_id == STRANGER and giorno(store, STRANGER)


def test_chi_ha_gia_accettato_collega_senza_ripremere(tmp_path):
    store = store_with(tmp_path)
    asyncio.run(verify.accept_terms(store, STRANGER, PRIMO))
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN}, uid=STRANGER,
                   coc=coc) is True
    assert giorno(store, STRANGER) == "2026-09-29"


def test_il_bandito_col_tasto_non_lascia_neanche_la_data(tmp_path):
    from clashbot import platform_ban
    store = store_with(tmp_path)
    asyncio.run(platform_ban.ban(store, STRANGER, [], 1789000000.0))
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "on"},
                   uid=STRANGER, coc=coc) == reasons.BANNED
    assert giorno(store, STRANGER) is None and store.find("#P2") is None


def test_un_valore_inventato_al_posto_del_tasto_non_passa(tmp_path):
    store = store_with(tmp_path)
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "si"},
                   uid=STRANGER, coc=FakeCoc({"#P2": TOKEN})) != True
    assert giorno(store, STRANGER) is None and store.find("#P2") is None


def test_la_creazione_senza_il_tasto_non_scrive():
    store, supervisor = ConsoleStore(), FakeSupervisor()
    tg = FakeTelegramBot()
    ctx = console_context(store, supervisor, bot=tg,
                          user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": "Futuro"}})
    update = born(user_id=NUOVO)
    asyncio.run(console.on_managed_created(update, ctx))
    assert store.added == [] and supervisor.started == []
    text, markup = update.effective_message.sent[-1]
    assert IT.t("terms.body") in text
    assert datas(markup) == [support_desk.TERMS_DATA]


def test_la_piattaforma_crea_senza_il_tasto():
    store, supervisor = ConsoleStore(owner=str(NUOVO)), FakeSupervisor()
    ctx = console_context(store, supervisor, bot=FakeTelegramBot(),
                          user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": "Futuro"}})
    asyncio.run(console.on_managed_created(born(user_id=NUOVO), ctx))
    assert supervisor.started == [f"bot-{NEW_ID}"]


def test_newbot_chiede_i_termini_prima_del_clan_e_il_tasto_li_salva():
    store = ConsoleStore(secrets={"site_base": SITO})
    ctx = console_context(store)
    ask = private(user_id=NUOVO)
    asyncio.run(console.cmd_newbot(ask, ctx))
    text, markup = ask.effective_message.sent[-1]
    assert IT.t("terms.body") in text
    assert datas(markup) == [support_desk.TERMS_DATA]
    assert urls(markup) == [SITO + "/terms", SITO + "/privacy"]
    assert ctx.user_data["newbot"]["step"] == verify.TERMS
    typed = private(user_id=NUOVO, text=TAG)
    asyncio.run(console.on_newbot_text(typed, ctx))
    assert ctx.user_data["newbot"]["step"] == verify.TERMS and giorno(store, NUOVO) is None
    update, query = pressed(support_desk.TERMS_DATA, user_id=NUOVO)
    asyncio.run(console.on_terms_callback(update, ctx))
    assert giorno(store, NUOVO)
    assert ctx.user_data["newbot"] == {"step": "tag"}


def test_il_tasto_premuto_due_volte_non_riscrive_la_data():
    store = ConsoleStore()
    ctx = console_context(store)
    asyncio.run(verify.accept_terms(store, NUOVO, PRIMO))
    update, _ = pressed(support_desk.TERMS_DATA, user_id=NUOVO)
    asyncio.run(console.on_terms_callback(update, ctx))
    assert giorno(store, NUOVO) == "2026-09-29"


def test_il_primo_collegamento_nel_bot_chiede_i_termini():
    store = FlowStore()
    store.kv.pop(verify.terms_key(store, 7), None)
    ctx = worker_context(store)
    ctx.bot_data["coc"] = TokenCoc((True, None))
    update = chat_update()
    asyncio.run(handlers.cmd_link(update, ctx))
    text, markup = update.effective_message.sent[-1]
    assert IT.t("terms.body") in text and datas(markup) == [support_desk.TERMS_DATA]
    assert ctx.user_data["flow"] == {"kind": "link", "step": verify.TERMS}
    typed = chat_update()
    typed.effective_message.text = MARIO
    asyncio.run(handlers.on_private_text(typed, ctx))
    assert store.linked == [] and ctx.user_data["flow"]["step"] == verify.TERMS
    tap = chat_update(data=support_desk.TERMS_DATA)
    asyncio.run(support_desk.on_terms_callback(tap, ctx))
    assert store.kv.get(verify.terms_key(store, 7))
    assert ctx.user_data["flow"] == {"kind": "link", "step": "tag"}
    assert tap.effective_message.sent[-1][0] == render.link_ask_tag(HL)


def test_chi_ha_gia_accettato_va_dritto_al_tag():
    store = FlowStore()
    asyncio.run(verify.accept_terms(store, 7, PRIMO))
    ctx = worker_context(store)
    update = chat_update()
    asyncio.run(handlers.cmd_link(update, ctx))
    assert ctx.user_data["flow"] == {"kind": "link", "step": "tag"}
    assert not isinstance(update.effective_message.sent[-1][1], InlineKeyboardMarkup)


class Raccolta:
    def __init__(self):
        self.presi = []

    def add_handler(self, handler, *args, **kw):
        pattern = getattr(handler, "pattern", None)
        self.presi.append((getattr(handler, "callback", None), getattr(pattern, "pattern", None)))

    def add_error_handler(self, *args, **kw):
        return None


def test_il_tasto_dei_termini_e_agganciato_nei_due_bot():
    assert support_desk.TERMS_DATA == "tos:ok"
    for modulo, preso in ((handlers, support_desk.on_terms_callback),
                          (console, console.on_terms_callback)):
        raccolta = Raccolta()
        modulo.register(raccolta)
        assert (preso, r"^tos:") in raccolta.presi, modulo.__name__
    assert OWNER != NUOVO


def test_l_app_dice_il_motivo_quando_manca_il_tasto():
    from clashbot.web import miniapp
    assert reasons.TERMS == "terms" and reasons.TERMS in reasons.REASONS
    assert reasons.TERMS not in reasons.RESERVED
    for lang in ("it", "en"):
        detto = miniapp.denied_words(i18n.locale(lang))["denied_terms"]
        assert detto and detto != "web.app.denied_terms"
