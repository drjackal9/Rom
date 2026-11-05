import asyncio
import logging
from types import SimpleNamespace

import pytest
from telegram.constants import UpdateType
from telegram.error import InvalidToken, TelegramError

from clashbot import i18n, poller as poller_mod, publish, supervisor as supervisor_mod
from clashbot.bot import ALLOWED_UPDATES
from clashbot.db import Bot
from clashbot.poller import CONSOLE_NAME, Poller
from clashbot.supervisor import Supervisor

IT = i18n.locale("it")


@pytest.fixture(autouse=True)
def heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor_mod, "HEARTBEAT", tmp_path / "beat")
    monkeypatch.setattr(poller_mod, "HEARTBEAT", tmp_path / "beat")


class FakeUpdater:
    def __init__(self, app):
        self.app = app
        self.running = False
        self.done = asyncio.Event()
        self._Updater__polling_task = None

    async def start_polling(self, allowed_updates=None, drop_pending_updates=None):
        self.app.calls.append("start_polling")
        self.app.polling = (allowed_updates, drop_pending_updates)
        self.running = True
        self._Updater__polling_task = asyncio.create_task(self.done.wait())

    async def die(self):
        self.done.set()
        await asyncio.sleep(0)

    async def stop(self):
        self.app.calls.append("updater_stop")
        self.running = False
        self.done.set()
        await asyncio.sleep(0)


class FakeApp:
    def __init__(self, token, kind, alias, error=None, delay=0, can_manage_bots=True, me_error=None):
        self.token = token
        self.kind = kind
        self.alias = alias
        self.error = error
        self.delay = delay
        self.calls = []
        self.polling = None
        self.bot_data = {}
        self.sent = []
        self.me_error = me_error
        self.me_calls = 0
        self.replaced = []
        self.replace_error = TelegramError("non gestito")
        self.bot = SimpleNamespace(
            username=alias.upper(), send_message=self.send_message, get_me=self.get_me,
            shutdown=self.bot_shutdown, can_manage_bots=can_manage_bots,
            replace_managed_bot_token=self.replace_managed_bot_token,
        )
        self.updater = FakeUpdater(self)

    async def bot_shutdown(self):
        self.calls.append("bot_shutdown")

    async def replace_managed_bot_token(self, user_id):
        self.replaced.append(user_id)
        if self.replace_error:
            raise self.replace_error
        return f"nuovo-{user_id}"

    async def post_init(self, app):
        self.calls.append("post_init")

    async def post_shutdown(self, app):
        self.calls.append("post_shutdown")

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    async def get_me(self):
        self.me_calls += 1
        if self.me_error:
            raise self.me_error
        return self.bot

    async def initialize(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append("initialize")
        if self.error:
            raise self.error

    async def start(self):
        self.calls.append("start")

    async def stop(self):
        self.calls.append("stop")

    async def shutdown(self):
        self.calls.append("shutdown")
        self.updater.done.set()


class Factory:
    def __init__(self, errors=None, delay=0, sticky=False, can_manage_bots=True, me_error=None):
        self.errors = dict(errors or {})
        self.delay = delay
        self.sticky = sticky
        self.can_manage_bots = can_manage_bots
        self.me_error = me_error
        self.built = []
        self.apps = {}

    def __call__(self, token, kind, alias):
        error = self.errors.get(alias) if self.sticky else self.errors.pop(alias, None)
        app = FakeApp(token, kind, alias, error, self.delay, self.can_manage_bots, self.me_error)
        self.built.append((token, kind, alias))
        self.apps[alias] = app
        return app

    def count(self, alias):
        return [built for _, _, built in self.built].count(alias)


class FakeStore:
    def __init__(self, bots=(), secrets=None):
        self.pool = None
        self.rows = {bot.alias: bot for bot in bots}
        self.secrets = dict(secrets or {})
        self.tokens = {}
        self.opened = 0
        self.closed = 0
        self.touched = []
        self.deactivated = []
        self.bumped = []
        self.added = []
        self.notes = {}
        self.kv = {}

    async def open(self):
        self.opened += 1
        self.pool = object()

    async def close(self):
        self.closed += 1

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def bots(self, active_only=False):
        return [bot for bot in self.rows.values() if bot.active or not active_only]

    async def bot_by_alias(self, alias):
        return self.rows.get(alias)

    async def bot_token(self, alias):
        if alias in self.tokens:
            return self.tokens[alias]
        return f"token-{alias}" if alias in self.rows else None

    async def set_bot_active(self, alias, active, reason=None):
        bot = self.rows.get(alias)
        if not bot:
            return None
        bot.active, bot.reason = active, reason
        self.deactivated.append((alias, active, reason))
        return bot

    async def add_bot(self, owner_id, token, username, bot_id, kind="worker", allow_disabled=False, trusted=False):
        bot = next((b for b in self.rows.values() if b.bot_id == bot_id), None)
        if not bot:
            raise ValueError("sconosciuto")
        self.added.append((owner_id, username, bot_id, kind, trusted))
        self.tokens[bot.alias] = token
        bot.active, bot.reason = True, None
        return bot

    async def bump_bot_failure(self, alias, limit=5):
        self.bumped.append(alias)
        return self.rows.get(alias)

    async def touch_bot(self, alias):
        self.touched.append(alias)

    async def counts(self):
        return {"active": 3, "total": 4}

    async def active_clans(self, bot_alias=None):
        return []

    async def families(self, bot_alias=None):
        return []

    async def kv_purge(self):
        return 0

    async def web_note_set(self, name, body):
        self.notes[name] = body

    async def web_intents_take(self, limit=50):
        return []


class FakeCoc:
    def __init__(self):
        self.closed = 0
        self.keys = ["una"]

    def keys_alive(self):
        return 1

    async def close(self):
        self.closed += 1


def make_bot(alias, owner_id=7, active=True, kind="worker"):
    return Bot(alias=alias, owner_id=owner_id, username=alias.upper(), bot_id=int(alias[-1]),
               kind=kind, active=active)


def make(bots=(), secrets=None, errors=None, delay=0, sticky=False, can_manage_bots=True, me_error=None):
    store = FakeStore(bots, secrets)
    factory = Factory(errors, delay, sticky, can_manage_bots, me_error)
    return Supervisor(store, FakeCoc(), factory), store, factory


def cycle(supervisor, work=None):
    async def main():
        await supervisor.start()
        result = await work(supervisor) if work else None
        await supervisor.stop()
        return result

    return asyncio.run(main())


LIVE = ["initialize", "post_init", "start", "start_polling"]
GONE = ["stop", "shutdown", "post_shutdown", "bot_shutdown"]
CLOSED = LIVE + ["updater_stop"] + GONE
DIED = LIVE + GONE


def test_start_avvia_la_console_e_tutti_i_worker_attivi():
    bots = [make_bot("b1"), make_bot("b2"), make_bot("b3", active=False)]
    supervisor, store, factory = make(bots, {"console_token": "tk-console", "owner_id": "42", "owner_lang": "it"})
    cycle(supervisor)
    assert factory.built == [("tk-console", "console", "console"), ("token-b1", "worker", "b1"),
                             ("token-b2", "worker", "b2")]
    assert store.opened == 1 and store.touched == ["b1", "b2"]
    assert store.kv[CONSOLE_NAME] == "CONSOLE"
    for alias in ("console", "b1", "b2"):
        assert factory.apps[alias].calls == CLOSED, alias
    assert factory.apps["b1"].polling == (ALLOWED_UPDATES, True)
    assert supervisor.running() == [] and supervisor.tasks == {}
    assert store.closed == 1 and supervisor.coc.closed == 1


def test_il_giro_web_e_uno_dei_compiti_del_supervisore():
    supervisor, store, _ = make([make_bot("b1")], {"console_token": "tk", "owner_id": "42", "owner_lang": "it"})

    async def guarda(s):
        await asyncio.sleep(0)
        return sorted(s.tasks), isinstance(s.web, publish.Beat)

    nomi, acceso = cycle(supervisor, guarda)
    assert "web" in nomi and acceso
    assert store.notes["services"]["services"]


def test_l_avviso_al_proprietario_parte_una_volta_sola_dalla_console():
    bots = [make_bot("b1"), make_bot("b2")]
    supervisor, store, factory = make(bots, {"console_token": "tk", "owner_id": "42", "owner_lang": "it"})
    cycle(supervisor)
    assert factory.apps["b1"].sent == [] and factory.apps["b2"].sent == []
    assert factory.apps["console"].sent == [
        (42, IT.t("bot.started", n=3) + "\n" + IT.t("bot.started_bots", n=3))
    ]


def test_start_bot_e_stop_bot_a_caldo():
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"})

    async def work(sup):
        store.rows["b2"] = make_bot("b2")
        assert await sup.start_bot("b2") is True
        assert await sup.start_bot("b2") is False
        assert await sup.start_bot("ignoto") is False
        store.rows["b3"] = make_bot("b3", active=False)
        assert await sup.start_bot("b3") is False
        assert sorted(sup.running()) == ["b1", "b2", "console"]
        assert sup.bot("b2") is factory.apps["b2"].bot
        assert await sup.stop_bot("b2", "owner_stopped") is True
        assert sorted(sup.running()) == ["b1", "console"]
        assert sup.bot("b2") is None

    cycle(supervisor, work)
    assert store.touched == ["b1", "b2"]
    assert store.deactivated == [("b2", False, "owner_stopped")]
    assert factory.apps["b2"].calls == CLOSED
    assert "b3" not in factory.apps


def test_un_token_non_valido_non_ferma_gli_altri_bot():
    bots = [make_bot("b1"), make_bot("b2"), make_bot("b3")]
    supervisor, store, factory = make(
        bots, {"console_token": "tk", "owner_lang": "it"},
        errors={"b1": InvalidToken("no"), "b2": RuntimeError("rete")},
    )

    async def work(sup):
        assert sorted(sup.running()) == ["b3", "console"]
        return None

    cycle(supervisor, work)
    assert store.deactivated == [("b1", False, "token_invalid")]
    assert store.touched == ["b3"]
    assert factory.apps["b1"].calls == ["initialize"] + GONE
    assert factory.apps["console"].sent == [
        (7, IT.t("console.bot_invalid", alias="b1", username="B1"))
    ]


def test_watch_avvia_i_nuovi_e_ferma_quelli_disattivati():
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"})

    async def work(sup):
        store.rows["b2"] = make_bot("b2")
        store.rows["b1"].active = False
        await sup.watch_once()
        assert sorted(sup.running()) == ["b2", "console"]
        assert store.deactivated == []
        assert factory.apps["b1"].calls == CLOSED
        assert factory.apps["b2"].calls == LIVE

    cycle(supervisor, work)


def test_watch_riavvia_il_polling_fermo_e_poi_lo_mette_da_parte():
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"})

    async def work(sup):
        first = factory.apps["b1"]
        first.updater.running = False
        await sup.watch_once()
        assert factory.apps["b1"] is not first and first.calls == DIED
        assert sorted(sup.running()) == ["b1", "console"]
        assert store.bumped == []
        factory.apps["b1"].updater.running = False
        await sup.watch_once()
        assert store.bumped == ["b1"]
        assert sup.running() == ["console"]

    cycle(supervisor, work)


def test_modalita_compatibile_senza_console_e_senza_bot():
    supervisor, store, factory = make([], {"telegram_token": "tk-futuro", "owner_id": "42", "owner_lang": "it"})

    async def work(sup):
        assert factory.built == [("tk-futuro", "worker", "single")]
        assert sup.default_alias == "single" and sup.running() == ["single"]
        poller = Poller(sup, store, sup.coc)
        assert poller.bot_for(SimpleNamespace(bot_alias=None)) is factory.apps["single"].bot
        assert poller.served(SimpleNamespace(bot_alias=None))
        assert sup.bot(None) is None
        assert factory.apps["single"].sent == [(42, IT.t("bot.started", n=3) + "\n" + IT.t("bot.started_bots", n=1))]

    cycle(supervisor, work)


def test_modalita_compatibile_non_tocca_il_database_e_non_viene_fermata_dal_watch():
    supervisor, store, factory = make([], {"telegram_token": "tk-futuro"})

    async def work(sup):
        await sup.watch_once()
        assert sup.running() == ["single"]
        assert store.touched == [] and store.deactivated == []

    cycle(supervisor, work)


def test_due_avvii_contemporanei_costruiscono_una_sola_applicazione():
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"}, delay=0.01)

    async def work(sup):
        store.rows["b2"] = make_bot("b2")
        first, second, _ = await asyncio.gather(sup.start_bot("b2"), sup.start_bot("b2"), sup.watch_once())
        assert sorted([first, second]) == [False, True]
        assert factory.count("b2") == 1
        assert sup.running().count("b2") == 1 and sup.starting == set()

    cycle(supervisor, work)
    assert store.touched.count("b2") == 1


def test_un_polling_morto_viene_riavviato_una_volta_e_poi_messo_da_parte():
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"})

    async def work(sup):
        first = factory.apps["b1"]
        await first.updater.die()
        assert first.updater.running is True and sup.dead("b1") is True
        await sup.watch_once()
        assert factory.apps["b1"] is not first and first.calls == CLOSED
        assert sorted(sup.running()) == ["b1", "console"] and store.bumped == []
        await factory.apps["b1"].updater.die()
        await sup.watch_once()
        assert store.bumped == ["b1"] and sup.running() == ["console"]
        assert store.deactivated[-1] == ("b1", False, "too_many_failures")

    cycle(supervisor, work)


def test_un_fisso_che_muore_due_volte_viene_sempre_riacceso():
    supervisor, store, factory = make([], {"console_token": "tk"})

    async def work(sup):
        for _ in range(2):
            await factory.apps["console"].updater.die()
            await sup.watch_once()
            assert sup.running() == ["console"]
        assert factory.count("console") == 3 and store.bumped == []

    cycle(supervisor, work)


def test_il_token_revocato_a_caldo_lo_scopre_il_controllo_periodico(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "PROBE_EVERY", 0)
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk", "owner_lang": "it"})

    async def work(sup):
        factory.apps["b1"].me_error = InvalidToken("revocato")
        await sup.watch_once()
        assert sup.running() == ["console"]
        assert store.deactivated == [("b1", False, "token_invalid")]
        assert factory.apps["b1"].calls == CLOSED
        assert factory.apps["console"].sent[-1] == (
            7, IT.t("console.bot_invalid", alias="b1", username="B1")
        )

    cycle(supervisor, work)


def test_un_errore_di_rete_nel_controllo_periodico_non_spegne_niente(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "PROBE_EVERY", 0)
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"})

    async def work(sup):
        factory.apps["b1"].me_error = TelegramError("rete")
        await sup.watch_once()
        assert sorted(sup.running()) == ["b1", "console"]
        assert store.deactivated == [] and factory.apps["b1"].me_calls == 1

    cycle(supervisor, work)


def test_un_avvio_fallito_non_viene_ritentato_a_ogni_giro():
    supervisor, store, factory = make(
        [], {"console_token": "tk"}, errors={"b2": RuntimeError("rete")}, sticky=True
    )

    async def work(sup):
        store.rows["b2"] = make_bot("b2")
        await sup.watch_once()
        assert factory.count("b2") == 1 and sup.retry["b2"][1] == supervisor_mod.BACKOFF_START
        await sup.watch_once()
        assert factory.count("b2") == 1
        sup.retry["b2"] = (0.0, supervisor_mod.BACKOFF_START)
        await sup.watch_once()
        assert factory.count("b2") == 2
        assert sup.retry["b2"][1] == supervisor_mod.BACKOFF_START * 2
        factory.errors.pop("b2")
        sup.retry["b2"] = (0.0, supervisor_mod.BACKOFF_START * 2)
        await sup.watch_once()
        assert sorted(sup.running()) == ["b2", "console"] and "b2" not in sup.retry

    cycle(supervisor, work)


def test_una_console_che_non_riparte_viene_ritentata_col_backoff():
    supervisor, store, factory = make(
        [], {"console_token": "tk"}, errors={"console": RuntimeError("rete")}, sticky=True
    )

    async def work(sup):
        assert sup.running() == [] and factory.count("console") == 1
        await sup.watch_once()
        assert factory.count("console") == 2 and sup.retry["console"][1] == supervisor_mod.BACKOFF_START
        await sup.watch_once()
        assert factory.count("console") == 2
        factory.errors.pop("console")
        sup.retry["console"] = (0.0, supervisor_mod.BACKOFF_START)
        await sup.watch_once()
        assert sup.running() == ["console"] and "console" not in sup.retry

    cycle(supervisor, work)


def test_il_tetto_del_backoff_non_viene_superato():
    supervisor, _, _ = make([], {})
    for _ in range(20):
        supervisor.hold("b9")
        supervisor.retry["b9"] = (0.0, supervisor.retry["b9"][1])
    assert supervisor.retry["b9"][1] == supervisor_mod.BACKOFF_MAX


def test_il_task_del_polling_si_trova_anche_se_cambia_nome():
    async def main():
        updater = SimpleNamespace()
        updater.qualunque = asyncio.create_task(asyncio.sleep(0))
        found = supervisor_mod.polling_task(SimpleNamespace(updater=updater))
        await updater.qualunque
        return found is updater.qualunque

    assert asyncio.run(main())
    assert supervisor_mod.polling_task(SimpleNamespace(updater=None)) is None


def test_il_battito_c_e_anche_senza_nessun_bot(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "BEAT_EVERY", 0.01)
    supervisor, store, factory = make([], {})

    async def work(sup):
        await asyncio.sleep(0.05)
        assert supervisor_mod.HEARTBEAT.exists()

    cycle(supervisor, work)
    assert factory.built == [] and store.closed == 1


def test_senza_nessun_token_il_supervisore_resta_vuoto_ma_vivo():
    supervisor, store, factory = make([], {})
    cycle(supervisor)
    assert factory.built == [] and store.closed == 1


def test_un_bot_del_database_con_il_token_di_un_fisso_non_parte():
    supervisor, store, factory = make([], {"telegram_token": "tk-futuro"})

    async def work(sup):
        store.rows["bot-1"] = make_bot("bot-1")
        store.tokens["bot-1"] = "tk-futuro"
        await sup.watch_once()
        assert factory.count("bot-1") == 0
        assert sup.running() == ["single"] and "bot-1" in sup.retry
        await sup.watch_once()
        assert factory.count("bot-1") == 0 and store.touched == []

    cycle(supervisor, work)


def test_con_la_console_e_nessun_bot_parte_anche_la_modalita_compatibile():
    supervisor, store, factory = make([], {"console_token": "tk", "telegram_token": "tk-futuro"})

    async def work(sup):
        assert factory.built == [("tk", "console", "console"), ("tk-futuro", "worker", "single")]
        assert sorted(sup.running()) == ["console", "single"] and sup.default_alias == "single"

    cycle(supervisor, work)


def test_gli_hook_del_profilo_girano_anche_sotto_il_supervisore():
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"})
    cycle(supervisor)
    assert factory.apps["b1"].calls == CLOSED
    assert factory.apps["b1"].calls.index("post_init") == 1
    assert factory.apps["b1"].calls[-2:] == ["post_shutdown", "bot_shutdown"]


def test_un_app_senza_hook_parte_e_si_chiude_lo_stesso():
    supervisor, store, factory = make([], {"console_token": "tk"})
    inner = supervisor.app_factory

    def bare(token, kind, alias):
        app = inner(token, kind, alias)
        app.post_init = None
        app.post_shutdown = None
        return app

    supervisor.app_factory = bare
    cycle(supervisor)
    assert factory.apps["console"].calls == [
        "initialize", "start", "start_polling", "updater_stop", "stop", "shutdown", "bot_shutdown"
    ]


def test_restart_bot_replaces_the_application():
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk"}, delay=0.01)

    async def work(sup):
        first = factory.apps["b1"]
        assert await sup.restart_bot("b1") is True
        assert factory.apps["b1"] is not first and first.calls == CLOSED
        assert factory.apps["b1"].calls == LIVE
        assert factory.count("b1") == 2 and sup.running().count("b1") == 1
        assert store.deactivated == [] and sup.starting == set()
        secondo = factory.apps["b1"]
        insieme = await asyncio.gather(sup.restart_bot("b1"), sup.start_bot("b1"), sup.restart_bot("b1"))
        assert sorted(insieme) == [False, False, True]
        assert factory.count("b1") == 3 and factory.apps["b1"] is not secondo
        assert sup.running().count("b1") == 1 and sup.starting == set()
        assert await sup.restart_bot("ignoto") is False

    cycle(supervisor, work)
    assert store.touched == ["b1", "b1", "b1"]


def test_restart_bot_non_spegne_i_bot_fissi():
    supervisor, store, factory = make([], {"console_token": "tk"})

    async def work(sup):
        primo = factory.apps["console"]
        assert await sup.restart_bot("console") is True
        assert factory.apps["console"] is not primo and primo.calls == CLOSED
        assert factory.count("console") == 2 and sup.running() == ["console"]

    cycle(supervisor, work)


def test_un_token_morto_lo_sostituisce_la_console(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "PROBE_EVERY", 0)
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk", "owner_lang": "it"})

    async def work(sup):
        factory.apps["console"].replace_error = None
        factory.apps["b1"].me_error = InvalidToken("revocato")
        await sup.watch_once()
        assert factory.apps["console"].replaced == [1]
        assert store.added == [(7, "B1", 1, "worker", True)]
        assert store.tokens["b1"] == "nuovo-1"
        assert sorted(sup.running()) == ["b1", "console"]
        assert factory.count("b1") == 2 and store.rows["b1"].active
        assert factory.apps["console"].sent[-1] == (
            7, IT.t("console.bot_recovered", alias="b1", username="B1")
        )

    cycle(supervisor, work)


def test_un_bot_gia_curato_una_volta_non_viene_curato_di_nuovo(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "PROBE_EVERY", 0)
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk", "owner_lang": "it"})

    async def work(sup):
        console = factory.apps["console"]
        console.replace_error = None
        factory.apps["b1"].me_error = InvalidToken("revocato")
        await sup.watch_once()
        factory.apps["b1"].me_error = InvalidToken("di nuovo")
        await sup.watch_once()
        assert console.replaced == [1] and len(store.added) == 1
        assert console.sent[-1] == (7, IT.t("console.bot_invalid", alias="b1", username="B1"))
        assert sup.running() == ["console"] and not store.rows["b1"].active

    cycle(supervisor, work)


def test_un_token_morto_allo_start_viene_sostituito_e_riparte_al_giro_dopo():
    supervisor, store, factory = make(
        [make_bot("b1")], {"console_token": "tk", "owner_lang": "it"}, errors={"b1": InvalidToken("no")}
    )
    base = supervisor.app_factory

    def gestibile(token, kind, alias):
        app = base(token, kind, alias)
        app.replace_error = None
        return app

    supervisor.app_factory = gestibile

    async def work(sup):
        assert sup.running() == ["console"]
        assert store.tokens["b1"] == "nuovo-1" and store.rows["b1"].active
        assert factory.apps["console"].sent[-1] == (
            7, IT.t("console.bot_recovered", alias="b1", username="B1")
        )
        await sup.watch_once()
        assert sorted(sup.running()) == ["b1", "console"]

    cycle(supervisor, work)


def test_un_bot_che_telegram_non_gestisce_resta_spento_con_le_istruzioni(monkeypatch):
    monkeypatch.setattr(supervisor_mod, "PROBE_EVERY", 0)
    supervisor, store, factory = make([make_bot("b1")], {"console_token": "tk", "owner_lang": "it"})

    async def work(sup):
        factory.apps["b1"].me_error = InvalidToken("revocato")
        await sup.watch_once()
        assert factory.apps["console"].replaced == [1]
        assert store.added == [] and sup.running() == ["console"]
        assert store.deactivated == [("b1", False, "token_invalid")]
        avviso = factory.apps["console"].sent[-1]
        assert avviso == (7, IT.t("console.bot_invalid", alias="b1", username="B1"))
        assert "BotFather" not in avviso[1]

    cycle(supervisor, work)


def test_warns_when_manager_cannot_create_bots(caplog):
    spento, store, factory = make([], {"console_token": "tk", "owner_id": "42", "owner_lang": "it"}, can_manage_bots=False)

    async def work(sup):
        await sup.check_manager()
        await sup.check_manager()

    with caplog.at_level(logging.WARNING, logger="clashbot.supervisor"):
        cycle(spento, work)
    console = factory.apps["console"]
    assert [text for _, text in console.sent].count(IT.t("console.manager_off")) == 1
    assert console.sent[0] == (42, IT.t("console.manager_off"))
    assert console.me_calls == 1
    assert "can_manage_bots" in caplog.text

    acceso, _, factory = make([], {"console_token": "tk", "owner_id": "42", "owner_lang": "it"})
    cycle(acceso, work)
    console = factory.apps["console"]
    assert IT.t("console.manager_off") not in [text for _, text in console.sent]
    assert console.me_calls == 1


def test_gli_aggiornamenti_ascoltati_comprendono_i_bot_gestiti():
    assert UpdateType.MANAGED_BOT in ALLOWED_UPDATES


def test_un_errore_di_rete_allo_start_non_perde_il_controllo_del_permesso():
    supervisor, store, factory = make([], {"console_token": "tk", "owner_id": "42", "owner_lang": "it"},
                                      can_manage_bots=False, me_error=TelegramError("rete"))

    async def work(sup):
        console = factory.apps["console"]
        assert console.me_calls == 1 and not sup.manager_checked
        assert IT.t("console.manager_off") not in [text for _, text in console.sent]
        console.me_error = None
        await sup.watch_once()
        assert console.me_calls == 2 and sup.manager_checked
        assert console.sent[-1] == (42, IT.t("console.manager_off"))
        await sup.watch_once()
        assert console.me_calls == 2

    cycle(supervisor, work)
