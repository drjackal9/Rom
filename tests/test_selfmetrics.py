import asyncio
from types import SimpleNamespace

import pytest

from clashbot import poller as poller_mod, selfmetrics, supervisor as supervisor_mod
from clashbot.web import app as web_app
from tests.test_supervisor import cycle, make, make_bot
from tests.test_web_panel import PanelStore

MEM = 94371840
LIMIT = 3221225472
USEC = 41000000
BURST = 5000000
AVAILABLE = 1048576


@pytest.fixture(autouse=True)
def heartbeats(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor_mod, "HEARTBEAT", tmp_path / "beat")
    monkeypatch.setattr(poller_mod, "HEARTBEAT", tmp_path / "beat")
    monkeypatch.setattr(web_app, "HEARTBEAT", tmp_path / "web-beat")


def cgroup2(tmp_path, usec=USEC, limit=str(LIMIT)):
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "memory.current").write_text(f"{MEM}\n", encoding="utf-8")
    (root / "memory.max").write_text(f"{limit}\n", encoding="utf-8")
    (root / "cpu.stat").write_text(f"usage_usec {usec}\nuser_usec 3\nsystem_usec 4\n", encoding="utf-8")
    return root


def cgroup1(tmp_path, usec=USEC):
    root = tmp_path / "vecchi"
    (root / "memory").mkdir(parents=True)
    (root / "cpuacct").mkdir()
    (root / "memory" / "memory.usage_in_bytes").write_text(f"{MEM}\n", encoding="utf-8")
    (root / "memory" / "memory.limit_in_bytes").write_text(f"{LIMIT}\n", encoding="utf-8")
    (root / "cpuacct" / "cpuacct.usage").write_text(f"{usec * 1000}\n", encoding="utf-8")
    return root


def procfs(tmp_path, up=5000.0, started=1000.0):
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    (proc / "loadavg").write_text("0.42 0.31 0.25 2/511 9\n", encoding="utf-8")
    (proc / "meminfo").write_text(
        f"MemTotal:        8123456 kB\nMemAvailable:    {AVAILABLE} kB\nBuffers:            1 kB\n",
        encoding="utf-8",
    )
    (proc / "uptime").write_text(f"{up} 4000.00\n", encoding="utf-8")
    ticks = int(started * selfmetrics.TICKS)
    (proc / "self" / "stat").write_text("9 (py thon) S " + "0 " * 18 + f"{ticks} 0 0\n", encoding="utf-8")
    return proc


def vuota(tmp_path):
    empty = tmp_path / "vuota"
    empty.mkdir()
    return empty


class KvStore:
    def __init__(self, boom=None):
        self.kv = {}
        self.calls = []
        self.boom = boom

    async def kv_set(self, key, obj, ref=None, ttl=None):
        if self.boom:
            raise self.boom
        self.kv[key] = obj
        self.calls.append((key, ttl))


class AscoltoStore(PanelStore):
    async def listen(self, channel, callback, connect=None):
        return SimpleNamespace(is_closed=lambda: False)


def test_il_campione_legge_memoria_e_limite_dai_propri_cgroup(tmp_path):
    campione = selfmetrics.sample(root=cgroup2(tmp_path), proc=procfs(tmp_path), now=100.0)
    assert campione["mem_bytes"] == MEM
    assert campione["mem_limit"] == LIMIT
    assert campione["cpu_usec"] == USEC
    assert campione["cpu_cores"] is None
    assert campione["ts"] == 100.0


def test_due_campioni_dicono_quanti_core_sta_usando(tmp_path):
    root = cgroup2(tmp_path)
    proc = procfs(tmp_path)
    prima = selfmetrics.sample(root=root, proc=proc, now=0.0)
    (root / "cpu.stat").write_text(f"usage_usec {USEC + BURST}\n", encoding="utf-8")
    dopo = selfmetrics.sample(root=root, proc=proc, previous=prima, now=10.0)
    assert dopo["cpu_cores"] == 0.5


def test_senza_limite_di_memoria_il_campo_resta_vuoto(tmp_path):
    campione = selfmetrics.sample(root=cgroup2(tmp_path, limit="max"), proc=procfs(tmp_path), now=1.0)
    assert campione["mem_limit"] is None
    assert campione["mem_bytes"] == MEM


def test_senza_cgroup_il_campione_e_vuoto_e_non_esplode(tmp_path):
    nulla = vuota(tmp_path)
    assert selfmetrics.sample(root=nulla, proc=nulla, now=7.0) == {
        "ts": 7.0, "mem_bytes": None, "mem_limit": None, "cpu_usec": None, "cpu_cores": None,
        "load1": None, "host_mem_available": None, "uptime_s": None, "pid_started": None,
    }


def test_il_campione_guarda_anche_carico_e_memoria_della_macchina(tmp_path):
    campione = selfmetrics.sample(root=cgroup2(tmp_path), proc=procfs(tmp_path), now=9000.0)
    assert campione["load1"] == 0.42
    assert campione["host_mem_available"] == AVAILABLE * 1024
    assert campione["uptime_s"] == 4000.0
    assert campione["pid_started"] == 5000.0


def test_i_cgroup_di_prima_maniera_si_leggono_lo_stesso(tmp_path):
    root = cgroup1(tmp_path)
    nulla = vuota(tmp_path)
    prima = selfmetrics.sample(root=root, proc=nulla, now=0.0)
    (root / "cpuacct" / "cpuacct.usage").write_text(f"{(USEC + BURST) * 1000}\n", encoding="utf-8")
    dopo = selfmetrics.sample(root=root, proc=nulla, previous=prima, now=10.0)
    assert dopo["mem_bytes"] == MEM
    assert dopo["mem_limit"] == LIMIT
    assert dopo["cpu_cores"] == 0.5


def test_il_registratore_scrive_il_campione_con_la_scadenza_doppia():
    store = KvStore()
    recorder = selfmetrics.Recorder(store, selfmetrics.BOT_KEY)
    campione = asyncio.run(recorder.once())
    assert store.calls == [(selfmetrics.BOT_KEY, 2 * selfmetrics.PLATFORM_INTERVAL)]
    assert store.kv[selfmetrics.BOT_KEY] is campione


def test_il_registratore_rispetta_la_cadenza_della_piattaforma():
    store = KvStore()
    recorder = selfmetrics.Recorder(store, selfmetrics.WEB_KEY)

    async def giro():
        await recorder.tick(now=0.0)
        await recorder.tick(now=100.0)
        await recorder.tick(now=float(selfmetrics.PLATFORM_INTERVAL))

    asyncio.run(giro())
    assert [key for key, _ in store.calls] == [selfmetrics.WEB_KEY, selfmetrics.WEB_KEY]


def test_il_registratore_aggiunge_le_misure_di_chi_lo_chiama():
    store = KvStore()
    recorder = selfmetrics.Recorder(store, selfmetrics.WEB_KEY, interval=10,
                                    extra=lambda: {"live": 3, "pages": 2, "notified": 9})
    campione = asyncio.run(recorder.tick(now=100.0))
    assert campione["live"] == 3 and campione["pages"] == 2 and campione["notified"] == 9
    assert campione["ts"] > 0
    assert store.kv[selfmetrics.WEB_KEY]["live"] == 3
    assert store.calls == [(selfmetrics.WEB_KEY, 20)]


def test_un_guasto_del_database_non_ferma_il_registratore():
    store = KvStore(boom=RuntimeError("database giù"))
    recorder = selfmetrics.Recorder(store, selfmetrics.BOT_KEY)
    assert asyncio.run(recorder.once()) is None
    assert store.kv == {}


def test_il_bot_misura_se_stesso_nel_suo_giro():
    supervisor, store, _ = make([make_bot("b1")], {"console_token": "tk", "owner_id": "42", "owner_lang": "it"})

    async def guarda(s):
        for _ in range(20):
            if selfmetrics.BOT_KEY in store.kv:
                break
            await asyncio.sleep(0)
        return sorted(s.tasks)

    nomi = cycle(supervisor, guarda)
    assert "ops" in nomi
    assert store.kv[selfmetrics.BOT_KEY]["ts"] > 0


def test_il_web_misura_se_stesso_nel_battito(tmp_path):
    store = PanelStore(tmp_path)
    stop = asyncio.Event()

    async def un_giro():
        task = asyncio.create_task(web_app.beat(stop, web_app.Site(store)))
        for _ in range(20):
            if selfmetrics.WEB_KEY in store.kv:
                break
            await asyncio.sleep(0)
        stop.set()
        task.cancel()

    asyncio.run(un_giro())
    assert store.kv[selfmetrics.WEB_KEY]["ts"] > 0


def test_il_battito_conta_app_aperte_pagine_in_memoria_e_avvisi_ricevuti(tmp_path):
    store = AscoltoStore(tmp_path)
    site = web_app.Site(store)
    stop = asyncio.Event()

    async def un_giro():
        await site.listen()
        site.pages.update({"alfa": {}, "beta": {}})
        site.live["alfa"] = {object(), object()}
        site.live["beta"] = {object()}
        site.notified = 4
        task = asyncio.create_task(web_app.beat(stop, site))
        for _ in range(20):
            if selfmetrics.WEB_KEY in store.kv:
                break
            await asyncio.sleep(0)
        stop.set()
        task.cancel()

    asyncio.run(un_giro())
    campione = store.kv[selfmetrics.WEB_KEY]
    assert campione["live"] == 3 and campione["pages"] == 2 and campione["notified"] == 4
    assert campione["ts"] > 0


def test_la_cadenza_della_piattaforma_ha_un_numero_solo():
    assert poller_mod.PLATFORM_INTERVAL is selfmetrics.PLATFORM_INTERVAL
