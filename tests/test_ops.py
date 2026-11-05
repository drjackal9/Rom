import asyncio
import copy
import inspect
import os
import re
from types import SimpleNamespace

import pytest

from clashbot import (events_registry, i18n, key_watch, manager_alerts, media, ops,
                      poller as poller_mod, publish, render, selfmetrics)
from clashbot.crypto import Vault
from clashbot.db import Store
from clashbot.platform_guard import FLOOD_LIMIT, FLOOD_WINDOW

AT = 1789000000.0
SITE = "https://clan.example"
TOKEN = "1:tk-finto"
IT = i18n.locale("it")
EN = i18n.locale("en")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


class FakeStore:
    def __init__(self, kv=None, secrets=None, db_bytes=None, intents=None, bans=None):
        self.kv = copy.deepcopy(kv or {})
        self.secrets = {"owner_id": "42", "owner_lang": "it", **(secrets or {})}
        self.db_bytes = db_bytes
        self.intents = intents
        self.bans = None if bans is None else list(bans)

    async def banned(self, limit=100):
        if self.bans is None:
            raise RuntimeError("nessun elenco di banditi")
        return copy.deepcopy(self.bans[:limit])

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def db_size_bytes(self):
        if self.db_bytes is None:
            raise RuntimeError("database muto")
        return self.db_bytes

    async def intent_oldest_age(self, now):
        return self.intents


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = dict(headers or {})


class FakeClient:
    def __init__(self, status=200, error=None, server="cloudflare"):
        self.status = status
        self.error = error
        self.server = server
        self.urls = []

    async def get(self, url):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status, {"server": self.server})


@pytest.fixture(autouse=True)
def log_pulito():
    publish.RECENT.rows = []
    yield
    publish.RECENT.rows = []


def chiavi(found):
    return [row["key"] for row in found]


def campione(mem=1024, cores=0.1, uptime=5000.0):
    return {"mem_bytes": mem, "mem_limit": ops.MEM_LIMIT, "cpu_cores": cores, "uptime_s": uptime,
            "load1": 0.2, "host_mem_available": 1048576, "ts": AT}


def quadro(**extra):
    base = {"bot": campione(), "web": campione(), "db_bytes": 1024, "dump_age_h": None,
            "poll": {"took": 5.0, "interval": 60, "clans": 3, "at": AT}, "intents_age_s": 1.0,
            "errors": {"n": 0, "window": ops.ERRORS_WINDOW, "last": None},
            "probe": {"ok": True, "ms": 40, "status": 200, "at": AT}, "keys": {"alive": 3, "total": 3},
            "banned": {"n": 0, "hour": 0, "window": ops.ERRORS_WINDOW, "last": []},
            "alerts": []}
    base.update(extra)
    return base


def banditi(quanti, at=AT):
    return [{"ip": f"203.0.113.{numero}", "at": at, "until": at + 3600, "strikes": 1}
            for numero in range(quanti)]


def test_i_numeri_sono_quelli_gia_decisi_e_non_ce_ne_sono_di_nuovi():
    assert ops.MEM_LIMIT == 2 * 1024 * 1024 * 1024
    assert ops.CPU_LIMIT == 2
    assert ops.ERRORS_WINDOW == 3600
    assert ops.PLATFORM_INTERVAL is selfmetrics.PLATFORM_INTERVAL
    assert publish.KEEP_ERRORS == 100


def test_le_chiavi_del_quadro_stanno_tutte_in_un_posto_solo():
    assert (selfmetrics.POLL_KEY, selfmetrics.PROBE_KEY) == ("ops:poll", "ops:probe")
    assert selfmetrics.LAST_KEY == "ops:last"
    assert ops.KIND in manager_alerts.KINDS


def test_l_evento_del_blocco_e_nel_registro_come_gli_altri_della_piattaforma():
    assert ops.EVENTS == ("platform.ops",)
    entry = events_registry.EVENTS["platform.ops"]
    assert entry["pack"] == ops.PACK == events_registry.PLATFORM_PACK
    assert entry["default"] == "manager_dm"
    assert entry["allowed"] == ("manager_dm",)
    assert entry["intensity"] is None


def test_il_quadro_mette_insieme_le_misure_gia_scritte():
    store = FakeStore(kv={
        selfmetrics.BOT_KEY: campione(mem=200 * 1024 * 1024),
        selfmetrics.WEB_KEY: campione(mem=90 * 1024 * 1024),
        selfmetrics.POLL_KEY: {"took": 12.5, "interval": 60, "clans": 4, "at": AT},
        selfmetrics.PROBE_KEY: {"ok": True, "ms": 88, "status": 200, "at": AT},
        manager_alerts.key_of(key_watch.KIND): {"sig": "ok:3", "sent": True,
                                                "history": [{"alive": 3, "total": 3, "at": AT}]},
    }, db_bytes=5 * 1024 * 1024, intents=3.0, bans=banditi(2))
    body = asyncio.run(ops.snapshot(store, AT))
    assert sorted(body) == ["alerts", "banned", "bot", "db_bytes", "dump_age_h", "errors",
                            "intents_age_s", "keys", "poll", "probe", "web"]
    assert body["bot"]["mem_bytes"] == 200 * 1024 * 1024
    assert body["web"]["mem_bytes"] == 90 * 1024 * 1024
    assert body["db_bytes"] == 5 * 1024 * 1024
    assert body["poll"]["took"] == 12.5
    assert body["intents_age_s"] == 3.0
    assert body["probe"]["ms"] == 88
    assert body["keys"]["alive"] == 3
    assert body["errors"] == {"n": 0, "window": ops.ERRORS_WINDOW, "last": None}
    assert body["alerts"] == []


def test_un_database_muto_non_rompe_il_quadro():
    body = asyncio.run(ops.snapshot(FakeStore(), AT))
    assert body["db_bytes"] is None and body["intents_age_s"] is None
    assert body["bot"] is None and body["keys"] is None


def test_l_eta_dell_ultimo_dump_viene_dal_registro_dei_backup(tmp_path, monkeypatch):
    log = tmp_path / "backup.log"
    log.write_text(
        "[2026-09-20 03:00:01] db-ok 12M /opt/clashbot-backups/db/clashbot-20260920-030001.dump\n"
        "[2026-09-20 03:00:05] key-ok\n"
        "[2026-09-20 03:01:00] done\n",
        encoding="utf-8",
    )
    scritto = AT
    os.utime(log, (scritto, scritto))
    monkeypatch.setattr(ops, "BACKUP_LOG", str(log))
    body = asyncio.run(ops.snapshot(FakeStore(), scritto + 3600))
    assert round(body["dump_age_h"], 4) == round((3600 + 59) / 3600, 4)


def test_senza_registro_montato_l_eta_del_dump_resta_vuota(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "BACKUP_LOG", str(tmp_path / "manca.log"))
    assert asyncio.run(ops.snapshot(FakeStore(), AT))["dump_age_h"] is None
    vuoto = tmp_path / "vuoto.log"
    vuoto.write_text("righe senza data\n", encoding="utf-8")
    monkeypatch.setattr(ops, "BACKUP_LOG", str(vuoto))
    assert asyncio.run(ops.snapshot(FakeStore(), AT))["dump_age_h"] is None


def test_gli_errori_recenti_si_contano_nella_finestra_gia_usata():
    publish.RECENT.rows = [
        {"at": int(AT - ops.ERRORS_WINDOW - 10), "level": "ERROR", "who": "clashbot", "text": "vecchio"},
        {"at": int(AT - 10), "level": "ERROR", "who": "clashbot", "text": "nuovo"},
    ]
    assert len(publish.RECENT.errors_in(ops.ERRORS_WINDOW, AT)) == 1
    body = asyncio.run(ops.snapshot(FakeStore(), AT))
    assert body["errors"]["n"] == 1 and body["errors"]["last"]["text"] == "nuovo"


def test_la_sonda_pubblica_chiede_lo_stato_e_misura_il_tempo():
    client = FakeClient()
    esito = asyncio.run(ops.probe(SITE + "/", client, AT))
    assert client.urls == [SITE + "/status.json"]
    assert esito["ok"] is True and esito["status"] == 200 and esito["at"] == AT
    assert esito["ms"] >= 0


def test_una_sonda_caduta_non_alza_eccezioni_e_non_scrive_l_indirizzo(caplog):
    with caplog.at_level("WARNING", logger="clashbot.ops"):
        esito = asyncio.run(ops.probe(SITE, FakeClient(error=OSError("rete giù")), AT))
    assert esito == {"ok": False, "ms": None, "status": None, "at": AT, "cdn": False}
    assert SITE not in caplog.text and "rete giù" not in caplog.text
    assert "OSError" in caplog.text
    fuori = asyncio.run(ops.probe(SITE, FakeClient(status=502), AT))
    assert fuori["ok"] is False and fuori["status"] == 502


def test_il_giro_lento_del_poller_e_una_cosa_strana():
    lento = quadro(poll={"took": 90.0, "interval": 60, "clans": 3, "at": AT})
    found = ops.strange(lento, quadro())
    assert chiavi(found) == ["poll_slow"]
    assert found[0]["value"] == 90 and found[0]["limit"] == 60
    assert ops.strange(quadro(), quadro()) == []


def test_la_sonda_avvisa_solo_al_secondo_fallimento_di_fila():
    prima = quadro(probe={"ok": False, "ms": None, "status": None, "at": AT})
    assert chiavi(ops.strange(prima, quadro())) == []
    seconda = quadro(probe={"ok": False, "ms": None, "status": None, "at": AT + 600})
    assert chiavi(ops.strange(seconda, prima)) == ["probe_down"]
    assert chiavi(ops.strange(seconda, seconda)) == []


def test_un_contenitore_ripartito_si_vede_dall_uptime_che_scende():
    ripartito = quadro(bot=campione(uptime=30.0))
    assert chiavi(ops.strange(ripartito, quadro())) == ["restarted"]
    assert ops.strange(ripartito, quadro())[0]["who"] == "bot"
    web = quadro(web=campione(uptime=12.0))
    assert [row["who"] for row in ops.strange(web, quadro())] == ["web"]
    assert chiavi(ops.strange(quadro(), None)) == []


def test_il_database_avvisa_a_ogni_gb_intero_mai_superato():
    uno = quadro(db_bytes=ops.GB + 10)
    assert chiavi(ops.strange(uno, quadro())) == ["db_gb"]
    assert ops.strange(uno, quadro())[0]["value"] == 1
    assert chiavi(ops.strange(uno, uno)) == []
    due = quadro(db_bytes=2 * ops.GB + 10)
    assert ops.strange(due, uno)[0]["value"] == 2
    sceso = quadro(db_bytes=ops.GB + 10)
    assert chiavi(ops.strange(sceso, due)) == []


def test_memoria_cpu_intenti_chiavi_ed_errori_hanno_i_tetti_gia_scritti():
    grasso = quadro(bot=campione(mem=ops.MEM_LIMIT + 1))
    assert chiavi(ops.strange(grasso, quadro())) == ["bot_mem"]
    assert ops.strange(grasso, quadro())[0]["value"] == (ops.MEM_LIMIT + 1) // ops.MB
    caldo = quadro(bot=campione(cores=2.5))
    assert chiavi(ops.strange(caldo, quadro())) == ["bot_cpu"]
    fermo = quadro(intents_age_s=selfmetrics.PLATFORM_INTERVAL + 1)
    assert chiavi(ops.strange(fermo, quadro())) == ["intents_stuck"]
    spente = quadro(keys={"alive": 1, "total": 3})
    assert chiavi(ops.strange(spente, quadro())) == ["keys_dead"]
    raffica = quadro(errors={"n": publish.KEEP_ERRORS, "window": ops.ERRORS_WINDOW, "last": None})
    assert chiavi(ops.strange(raffica, quadro())) == ["errors_burst"]
    calma = quadro(errors={"n": publish.KEEP_ERRORS - 1, "window": ops.ERRORS_WINDOW, "last": None})
    assert chiavi(ops.strange(calma, quadro())) == []


def test_il_quadro_conta_i_banditi_di_adesso_e_dell_ultima_ora():
    store = FakeStore(bans=banditi(3, AT) + banditi(2, AT - FLOOD_WINDOW - 10))
    body = asyncio.run(ops.snapshot(store, AT))
    assert body["banned"]["n"] == 5 and body["banned"]["hour"] == 3
    assert body["banned"]["window"] == FLOOD_WINDOW
    assert len(body["banned"]["last"]) == 5
    assert asyncio.run(ops.snapshot(FakeStore(), AT))["banned"] is None


def test_troppi_banditi_in_un_ora_sono_una_cosa_strana():
    tanti = quadro(banned={"n": FLOOD_LIMIT + 1, "hour": FLOOD_LIMIT + 1,
                           "window": FLOOD_WINDOW, "last": []})
    assert chiavi(ops.strange(tanti, quadro())) == ["probes_burst"]
    assert ops.strange(tanti, quadro())[0]["limit"] == FLOOD_LIMIT
    pochi = quadro(banned={"n": FLOOD_LIMIT, "hour": FLOOD_LIMIT,
                           "window": FLOOD_WINDOW, "last": []})
    assert chiavi(ops.strange(pochi, quadro())) == []
    assert chiavi(ops.strange(quadro(banned=None), quadro())) == []


def test_l_avviso_dei_banditi_parte_una_volta_sola():
    store, bot = FakeStore(), FakeBot()
    tanti = quadro(banned={"n": FLOOD_LIMIT + 2, "hour": FLOOD_LIMIT + 2,
                           "window": FLOOD_WINDOW, "last": []})

    async def work():
        primo = await ops.watch(store, bot, tanti, quadro(), AT)
        secondo = await ops.watch(store, bot, tanti, tanti, AT + 600)
        return primo, secondo

    assert asyncio.run(work()) == (True, False)
    assert IT.t("owner.ops.probes_burst", n=str(FLOOD_LIMIT + 2), limit=str(FLOOD_LIMIT),
                who="") in bot.sent[0][1]


def test_il_quadro_mostra_la_riga_dei_banditi():
    rows = ops.board(quadro(banned={"n": 7, "hour": 2, "window": FLOOD_WINDOW, "last": []}))["rows"]
    riga = next(row for row in rows if row["key"] == "banned")
    assert riga["level"] == ops.OK and riga["args"] == {"n": 7, "hour": 2}
    raffica = ops.board(quadro(banned={"n": 9, "hour": FLOOD_LIMIT + 1,
                                       "window": FLOOD_WINDOW, "last": []}))["rows"]
    assert next(row for row in raffica if row["key"] == "banned")["level"] == ops.BAD
    muto = ops.board(quadro(banned=None))["rows"]
    assert next(row for row in muto if row["key"] == "banned")["level"] == ops.UNKNOWN


def misure_del_web(rows):
    return {row["key"]: row for row in rows if row["key"].startswith("web.")}


def test_il_quadro_mostra_le_misure_del_canale_vivo_del_web():
    vivo = dict(campione(), live=3, pages=2, notified=9)
    rows = ops.board(quadro(web=vivo))["rows"]
    assert [row["key"] for row in rows][:5] == ["bot", "web", "web.live", "web.pages", "web.notified"]
    misure = misure_del_web(rows)
    assert misure["web.live"]["args"] == {"n": 3} and misure["web.live"]["level"] == ops.OK
    assert misure["web.pages"]["args"] == {"n": 2} and misure["web.pages"]["level"] == ops.OK
    assert misure["web.notified"]["args"] == {"n": 9} and misure["web.notified"]["level"] == ops.OK


def test_le_misure_del_canale_vivo_che_mancano_restano_gialle():
    mute = misure_del_web(ops.board(quadro(web=campione()))["rows"])
    assert [row["level"] for row in mute.values()] == [ops.UNKNOWN] * 3
    assert all(row["args"] == {"n": None} for row in mute.values())
    spento = misure_del_web(ops.board(quadro(web=None))["rows"])
    assert [row["level"] for row in spento.values()] == [ops.UNKNOWN] * 3


def test_ogni_misura_del_canale_vivo_ha_la_sua_riga_scritta():
    misure = misure_del_web(ops.board(quadro(web=dict(campione(), live=3, pages=2, notified=9)))["rows"])
    for chiave, atteso in (("web.live", "3"), ("web.pages", "2"), ("web.notified", "9")):
        riga = render.ops_line(IT, misure[chiave])
        assert riga.startswith("🟢 ") and atteso in riga and "[" not in riga
        assert render.ops_line(EN, misure[chiave]) != riga


def test_ogni_avviso_parte_una_volta_sola_finche_non_rientra():
    store, bot = FakeStore(), FakeBot()
    lento = quadro(poll={"took": 90.0, "interval": 60, "clans": 3, "at": AT})

    async def work():
        primo = await ops.watch(store, bot, lento, quadro(), AT)
        secondo = await ops.watch(store, bot, lento, lento, AT + 600)
        rientro = await ops.watch(store, bot, quadro(), lento, AT + 1200)
        ancora = await ops.watch(store, bot, lento, quadro(), AT + 1800)
        return primo, secondo, rientro, ancora

    assert asyncio.run(work()) == (True, False, False, True)
    assert len(bot.sent) == 2
    assert store.kv[manager_alerts.key_of(ops.KIND)]["sig"] == "poll_slow"


def test_nel_quadro_restano_gli_avvisi_veri_non_i_rientri():
    store, bot = FakeStore(), FakeBot()
    lento = quadro(poll={"took": 90.0, "interval": 60, "clans": 3, "at": AT})

    async def work():
        await ops.watch(store, bot, lento, quadro(), AT)
        await ops.watch(store, bot, quadro(), lento, AT + 600)
        return await ops.snapshot(store, AT + 900)

    body = asyncio.run(work())
    assert [row["keys"] for row in body["alerts"]] == [["poll_slow"]]


def test_le_chiavi_spente_le_racconta_gia_il_guardiano_delle_chiavi():
    store, bot = FakeStore(), FakeBot()
    spente = quadro(keys={"alive": 0, "total": 3})
    assert asyncio.run(ops.watch(store, bot, spente, quadro(), AT)) is False
    assert bot.sent == []
    assert store.kv[manager_alerts.key_of(ops.KIND)]["sig"] == "keys_dead"


def test_l_avviso_non_dice_segreti_ne_percorsi():
    rows = ops.strange(quadro(bot=campione(mem=ops.MEM_LIMIT + 1, cores=3.0, uptime=1.0),
                              db_bytes=2 * ops.GB,
                              poll={"took": 90.0, "interval": 60, "clans": 3, "at": AT},
                              intents_age_s=selfmetrics.PLATFORM_INTERVAL + 5,
                              probe={"ok": False, "ms": None, "status": None, "at": AT + 1},
                              keys={"alive": 0, "total": 3},
                              errors={"n": publish.KEEP_ERRORS, "window": ops.ERRORS_WINDOW,
                                      "last": None}),
                       quadro(probe={"ok": False, "ms": None, "status": None, "at": AT}))
    assert sorted(chiavi(rows)) == ["bot_cpu", "bot_mem", "db_gb", "errors_burst", "intents_stuck",
                                    "keys_dead", "poll_slow", "probe_down", "restarted"]
    text = ops.card(IT, rows)
    parole = re.sub(r"</?[a-z]+>", "", text)
    for vietato in ("/", "\\", TOKEN, SITE, ops.BACKUP_LOG, "clashbot-backups"):
        assert vietato not in parole, vietato
    assert "[owner.ops." not in text


def test_il_giro_completo_sonda_misura_e_ricorda_il_quadro_di_prima():
    store = FakeStore(secrets={"site_base": SITE}, db_bytes=1024, intents=1.0)
    store.kv[selfmetrics.BOT_KEY] = campione()
    client = FakeClient()
    media.forget()
    assert asyncio.run(ops.check(store, FakeBot(), client, AT)) is False
    assert client.urls == [SITE + "/status.json"]
    assert store.kv[selfmetrics.PROBE_KEY]["ok"] is True
    ricordo = store.kv[selfmetrics.LAST_KEY]
    assert ricordo["bot"]["uptime_s"] == 5000.0 and "alerts" not in ricordo


def test_senza_indirizzo_del_sito_la_sonda_non_parte():
    store = FakeStore(db_bytes=1024)
    client = FakeClient()
    media.forget()
    asyncio.run(ops.check(store, FakeBot(), client, AT))
    assert client.urls == []
    assert selfmetrics.PROBE_KEY not in store.kv


def test_un_guasto_nel_giro_del_quadro_non_alza_eccezioni(caplog):
    rotto = SimpleNamespace(get_secret=None)
    with caplog.at_level("WARNING", logger="clashbot.ops"):
        assert asyncio.run(ops.check(rotto, FakeBot(), None, AT)) is False
    assert "quadro ops" in caplog.text


def test_il_poller_scrive_quanto_e_durato_il_giro():
    store = FakeStore()
    fake = SimpleNamespace(web=None)
    p = poller_mod.Poller(fake, store, SimpleNamespace())
    p.interval = 60
    asyncio.run(p.note_round(12.5, 4, AT))
    assert store.kv[selfmetrics.POLL_KEY] == {"took": 12.5, "interval": 60, "clans": 4, "at": AT}
    assert "note_round" in inspect.getsource(poller_mod.Poller.run)


def test_il_poller_non_cade_se_la_misura_non_si_salva(caplog):
    class Muto(FakeStore):
        async def kv_set(self, key, obj, ref=None, ttl=None):
            raise RuntimeError("niente database")

    p = poller_mod.Poller(SimpleNamespace(web=None), Muto(), SimpleNamespace())
    with caplog.at_level("WARNING", logger="clashbot.poller"):
        asyncio.run(p.note_round(1.0, 0, AT))
    assert "RuntimeError" in caplog.text


class FakePool:
    def __init__(self, value=None):
        self.value = value
        self.log = []

    async def fetchval(self, sql, *args):
        self.log.append(" ".join(sql.split()))
        return self.value


def test_il_database_si_misura_con_una_domanda_sola(tmp_path):
    store = Store(Vault(tmp_path))
    store.pool = FakePool(value=7 * 1024 * 1024)
    assert asyncio.run(store.db_size_bytes()) == 7 * 1024 * 1024
    assert store.pool.log == ["select pg_database_size(current_database())"]


def test_l_intento_piu_vecchio_si_misura_dal_suo_momento(tmp_path):
    from datetime import datetime, timezone

    store = Store(Vault(tmp_path))
    store.pool = FakePool(value=datetime.fromtimestamp(AT - 42, timezone.utc))
    assert asyncio.run(store.intent_oldest_age(AT)) == 42.0
    assert store.pool.log == ["select min(created_at) from web_intents"]
    store.pool = FakePool(value=None)
    assert asyncio.run(store.intent_oldest_age(AT)) is None


def test_le_frasi_nuove_ci_sono_in_italiano_e_in_inglese():
    chiavi_nuove = ("owner.ops.title", "owner.ops.bot_mem", "owner.ops.bot_cpu", "owner.ops.db_gb",
                    "owner.ops.poll_slow", "owner.ops.intents_stuck", "owner.ops.probe_down",
                    "owner.ops.restarted", "owner.ops.keys_dead", "owner.ops.errors_burst")
    for code in ("it", "en"):
        catalogo = i18n.catalog(code)
        for key in chiavi_nuove:
            assert key in catalogo, (code, key)
            assert not re.search(r"/opt|/metrics|\.dump", catalogo[key]), (code, key)
