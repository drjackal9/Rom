import asyncio
import copy
import logging
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram.error import TelegramError

from clashbot import i18n, manager_alerts, platform_guard, retention

TOKEN = "1:tk-finto"
AT = 1789000000.0


class FakeBot:
    def __init__(self, error=None):
        self.error = error
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text))


class FakeStore:
    def __init__(self, owner="42", lang="it"):
        self.secrets = {"owner_id": owner, "owner_lang": lang}
        self.kv = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)


def test_il_tetto_dello_storico_e_quello_delle_guerre():
    assert manager_alerts.KEEP == retention.WAR_HISTORY_KEEP == 100
    assert manager_alerts.key_of("keys") == "platform:keys"


def test_il_gestore_si_legge_dai_segreti_e_regge_i_valori_rotti():
    assert asyncio.run(manager_alerts.owner_id(FakeStore())) == 42
    assert asyncio.run(manager_alerts.owner_id(FakeStore(owner=None))) is None
    assert asyncio.run(manager_alerts.owner_id(FakeStore(owner="quarantadue"))) is None


def test_senza_gestore_o_senza_bot_non_parte_niente():
    bot = FakeBot()
    assert asyncio.run(manager_alerts.send(FakeStore(owner=None), bot, "ciao")) is False
    assert asyncio.run(manager_alerts.send(FakeStore(), None, "ciao")) is False
    assert asyncio.run(manager_alerts.send(FakeStore(), bot, "")) is False
    assert bot.sent == []


def test_un_avviso_per_firma_e_silenzio_finche_non_cambia():
    store, bot = FakeStore(), FakeBot()

    async def work():
        first = await manager_alerts.on_change(store, bot, "keys", "1:invalid_key/3", {"alive": 2}, "morta", AT)
        again = await manager_alerts.on_change(store, bot, "keys", "1:invalid_key/3", {"alive": 2}, "morta", AT + 60)
        back = await manager_alerts.on_change(store, bot, "keys", "ok:3", {"alive": 3}, "tornata", AT + 120)
        return first, again, back

    assert asyncio.run(work()) == (True, False, True)
    assert [text for _, text in bot.sent] == ["morta", "tornata"]
    assert [row["alive"] for row in store.kv["platform:keys"]["history"]] == [2, 3]
    assert store.kv["platform:keys"]["sig"] == "ok:3"


def test_un_avviso_non_consegnato_si_riprova_al_giro_dopo():
    store, rotto = FakeStore(), FakeBot(error=TelegramError("bloccato"))

    async def work():
        assert await manager_alerts.on_change(store, rotto, "keys", "1:invalid_key/3", {"alive": 2}, "morta", AT) is False
        assert store.kv["platform:keys"]["sent"] is False
        buono = FakeBot()
        assert await manager_alerts.on_change(store, buono, "keys", "1:invalid_key/3", {"alive": 2}, "morta", AT + 60) is True
        assert store.kv["platform:keys"]["sent"] is True
        return buono

    buono = asyncio.run(work())
    assert [text for _, text in buono.sent] == ["morta"]
    assert len(store.kv["platform:keys"]["history"]) == 1


def test_l_errore_di_telegram_non_finisce_nei_log_con_il_testo(caplog):
    store = FakeStore()
    bot = FakeBot(error=TelegramError(f"token {TOKEN} rifiutato"))
    with caplog.at_level(logging.WARNING, logger="clashbot.manager"):
        assert asyncio.run(manager_alerts.send(store, bot, "morta")) is False
    assert "TelegramError" in caplog.text
    assert TOKEN not in caplog.text and "rifiutato" not in caplog.text


def test_lo_storico_si_ferma_a_cento_voci_e_record_aggiunge_sempre():
    store = FakeStore()

    async def work():
        for n in range(manager_alerts.KEEP + 5):
            await manager_alerts.record(store, "restore", "ok", {"righe": n}, AT + n)

    asyncio.run(work())
    rows = store.kv["platform:restore"]["history"]
    assert len(rows) == manager_alerts.KEEP
    assert rows[0]["righe"] == 5 and rows[-1]["righe"] == manager_alerts.KEEP + 4
    assert asyncio.run(manager_alerts.last(store, "restore"))["righe"] == manager_alerts.KEEP + 4
    assert [row["righe"] for row in asyncio.run(manager_alerts.history(store, "restore", 2))] == [
        manager_alerts.KEEP + 4, manager_alerts.KEEP + 3
    ]


def test_solo_i_tipi_dichiarati_scrivono_nello_spazio_della_piattaforma():
    store, bot = FakeStore(), FakeBot()

    async def work():
        assert await manager_alerts.record(store, "qualunque", "x", {}, AT) is False
        assert await manager_alerts.on_change(store, bot, "qualunque", "x", {}, "no", AT) is False

    asyncio.run(work())
    assert store.kv == {} and bot.sent == []


def test_il_quadro_ops_e_un_tipo_dichiarato_come_gli_altri():
    assert manager_alerts.KINDS == ("keys", "restore", "ops", "actions", "api")
    store, bot = FakeStore(), FakeBot()

    async def work():
        primo = await manager_alerts.on_change(store, bot, "ops", "poll_slow",
                                               {"keys": ["poll_slow"]}, "lento", AT)
        rientro = await manager_alerts.record(store, "ops", "ok", {"keys": []}, AT + 60)
        return primo, rientro

    assert asyncio.run(work()) == (True, True)
    assert store.kv["platform:ops"]["sig"] == "ok"
    assert [row["keys"] for row in store.kv["platform:ops"]["history"]] == [["poll_slow"], []]
    assert [text for _, text in bot.sent] == ["lento"]


def test_uno_stato_mai_scritto_si_legge_vuoto():
    store = FakeStore()
    assert asyncio.run(manager_alerts.state(store, "keys")) == {}
    assert asyncio.run(manager_alerts.last(store, "keys")) is None
    assert asyncio.run(manager_alerts.pending(store, "keys", "ok:3")) is True
    assert manager_alerts.moment(None) is None
    assert manager_alerts.moment(AT).year == 2026


def test_la_lingua_del_gestore_e_quella_gia_usata_dalla_piattaforma():
    L = asyncio.run(manager_alerts.locale(FakeStore(lang="en")))
    assert L.code == "en"
    assert L.t("bot.started", n=1) == i18n.locale("en").t("bot.started", n=1)


def test_l_avviso_al_gestore_passa_dalla_consegna_della_piattaforma(monkeypatch):
    testo = pathlib.Path(manager_alerts.__file__).read_text(encoding="utf-8")
    assert "send_message" not in testo
    assert manager_alerts.notify is platform_guard.notify
    visti = []

    async def finta(bot, chat_id, text, **extra):
        visti.append((bot, chat_id, text, extra))
        return True

    monkeypatch.setattr(manager_alerts, "notify", finta)
    bot = FakeBot()
    assert asyncio.run(manager_alerts.send(FakeStore(), bot, "ciao")) is True
    assert visti == [(bot, 42, "ciao", {})]


def test_l_avviso_dal_console_esce_dal_bot_del_console():
    store, console = FakeStore(), FakeBot()
    supervisor = SimpleNamespace(owner_bot=lambda: console)
    assert asyncio.run(manager_alerts.from_console(store, supervisor, "nuovo clan")) is True
    assert console.sent == [(42, "nuovo clan")]


def test_senza_console_acceso_l_avviso_del_gestore_non_parte():
    store, console = FakeStore(), FakeBot()
    spento = SimpleNamespace(owner_bot=lambda: None)
    assert asyncio.run(manager_alerts.from_console(store, None, "nuovo clan")) is False
    assert asyncio.run(manager_alerts.from_console(store, spento, "nuovo clan")) is False
    assert console.sent == []


def test_senza_testo_la_consegna_della_piattaforma_non_prova_nemmeno():
    bot = FakeBot(error=TelegramError("mai chiamato"))
    assert asyncio.run(platform_guard.notify(bot, 42, "")) is False
    assert bot.sent == []


def test_un_apertura_retrodatata_fuori_dalla_finestra_conta_zero_e_non_esplode():
    store = FakeStore()
    pieni = {"%d-%02d" % (2026 + passo // 12, passo % 12 + 1): 1
             for passo in range(retention.WAR_HISTORY_KEEP)}
    assert len(pieni) == retention.WAR_HISTORY_KEEP
    store.kv[manager_alerts.OPENS_KEY] = pieni
    vecchio = datetime(2025, 1, 5, tzinfo=timezone.utc)
    assert asyncio.run(manager_alerts.opened(store, vecchio)) == 0
    tenuti = store.kv[manager_alerts.OPENS_KEY]
    assert len(tenuti) == retention.WAR_HISTORY_KEEP and "2025-01" not in tenuti
