import asyncio
import io
import logging
from types import SimpleNamespace

import httpx
import pytest

from clashbot import __main__ as main_mod, coc as coc_mod, poller as poller_mod
from clashbot.coc import CocApi, parse_keys
from clashbot.poller import Poller, poll_interval

K1 = "chiave-uno-segreta"
K2 = "chiave-due-segreta"
K3 = "chiave-tre-segreta"
OK = (200, {"items": [], "tag": "#ABC", "name": "Clan"})
THROTTLED = (429, {"reason": "requestThrottled", "message": "Request was throttled"})
BAD_IP = (403, {"reason": "accessDenied.invalidIp",
                "message": "Invalid authorization: API key does not allow access from IP 203.0.113.7"})
BAD_KEY = (403, {"reason": "accessDenied", "message": "Invalid authorization"})


class Api:
    def __init__(self, rules=None):
        self.rules = dict(rules or {})
        self.seen = []

    def __call__(self, request):
        auth = request.headers.get("Authorization", "")
        key = auth.removeprefix("Bearer ")
        self.seen.append(key)
        status, body = self.rules.get(key, OK)
        return httpx.Response(status, json=body)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(coc_mod, "monotonic", fake)
    return fake


def pool(token, api):
    return CocApi(token, transport=httpx.MockTransport(api))


def calls(coc, n, method="clan"):
    async def work():
        try:
            return [await getattr(coc, method)("#ABC") for _ in range(n)]
        finally:
            await coc.close()

    return asyncio.run(work())


def test_parse_keys_su_input_sporchi():
    assert parse_keys(f"  {K1} , {K2}\n\n{K3},,{K1}\r\n  ") == [K1, K2, K3]
    assert parse_keys(f"{K2}\n{K1}") == [K2, K1]
    assert parse_keys(None) == [] and parse_keys("") == [] and parse_keys(" ,\n , ") == []
    assert parse_keys([f" {K1} ", f"{K2},{K3}", K1, "", None]) == [K1, K2, K3]


def test_le_chiamate_ruotano_tra_le_chiavi(clock):
    api = Api()
    coc = pool(f"{K1},{K2}", api)
    assert coc.keys_alive() == 2
    results = calls(coc, 4)
    assert [error for _, error in results] == [None] * 4
    assert api.seen == [K1, K2, K1, K2]


def test_set_token_sostituisce_il_pool(clock):
    api = Api()
    coc = pool(K1, api)
    coc.set_token([K2, K3])
    assert coc.keys_alive() == 2
    calls(coc, 2)
    assert api.seen == [K2, K3]


def test_set_token_dimentica_chiavi_rifiutate_e_in_pausa(clock):
    api = Api({K1: BAD_KEY, K2: THROTTLED})
    coc = pool(f"{K1},{K2},{K3}", api)

    async def work():
        try:
            first = await coc.clan("#ABC")
            assert first[1] is None and api.seen == [K1, K2, K3]
            assert coc.keys_alive() == 2
            api.rules.clear()
            api.seen.clear()
            coc.set_token([K1, K2])
            assert coc.keys_alive() == 2
            results = [await coc.clan("#ABC") for _ in range(2)]
            assert [error for _, error in results] == [None, None]
            assert api.seen == [K1, K2]
        finally:
            await coc.close()

    asyncio.run(work())


def test_una_chiave_rifiutata_o_non_ascii_si_salta_nella_stessa_chiamata(clock):
    api = Api({K1: BAD_KEY})
    coc = pool(f"{K1},chiave-è-sbagliata,{K2}", api)
    results = calls(coc, 2)
    assert [error for _, error in results] == [None, None]
    assert api.seen == [K1, K2, K2]
    assert coc.keys_alive() == 1


def test_un_429_raffredda_solo_quella_chiave(clock):
    api = Api({K1: THROTTLED})
    coc = pool(f"{K1}\n{K2}", api)

    async def work():
        first = await coc.clan("#ABC")
        assert first[1] is None and api.seen == [K1, K2]
        api.seen.clear()
        for _ in range(3):
            assert (await coc.clan("#ABC"))[1] is None
        assert api.seen == [K2, K2, K2]
        assert coc.keys_alive() == 2
        api.rules.pop(K1)
        api.seen.clear()
        clock.now += 31
        for _ in range(2):
            assert (await coc.clan("#ABC"))[1] is None
        assert api.seen == [K1, K2]
        await coc.close()

    asyncio.run(work())


def test_tutte_in_raffreddamento_rispondono_rate_senza_chiamare(clock):
    api = Api({K1: THROTTLED, K2: THROTTLED})
    coc = pool([K1, K2], api)
    results = calls(coc, 3)
    assert results == [(None, "rate")] * 3
    assert api.seen == [K1, K2]


def test_una_chiave_rifiutata_viene_saltata_nella_stessa_chiamata(clock, caplog):
    api = Api({K1: BAD_IP})
    coc = pool(f"{K1},{K2}", api)
    with caplog.at_level(logging.INFO, logger="clashbot.coc"):
        results = calls(coc, 3)
    assert [error for _, error in results] == [None] * 3
    assert results[0][0]["name"] == "Clan"
    assert api.seen == [K1, K2, K2, K2]
    assert coc.keys_alive() == 1
    assert "invalid_ip" in caplog.text
    assert K1 not in caplog.text and K2 not in caplog.text


def test_tutte_rifiutate_ritorna_l_errore_dell_ultima(clock):
    api = Api({K1: BAD_IP, K2: BAD_KEY})
    coc = pool([K1, K2], api)
    results = calls(coc, 2)
    assert results == [(None, "invalid_key")] * 2
    assert api.seen == [K1, K2]
    assert coc.keys_alive() == 0


def test_una_chiave_rifiutata_viene_riprovata_piu_tardi(clock):
    api = Api({K1: BAD_IP})
    coc = pool(K1, api)

    async def work():
        assert await coc.check() == (None, "invalid_ip")
        assert await coc.check() == (None, "invalid_ip")
        assert api.seen == [K1] and coc.keys_alive() == 0
        api.rules.pop(K1)
        clock.now += coc_mod.DEAD_RETRY + 1
        assert (await coc.check())[1] is None
        assert api.seen == [K1, K1] and coc.keys_alive() == 1
        await coc.close()

    asyncio.run(work())


def test_senza_chiavi_non_parte_nessuna_richiesta(clock):
    api = Api()
    coc = pool(None, api)
    assert coc.keys_alive() == 0
    assert calls(coc, 1) == [(None, "invalid_key")]
    assert api.seen == []


def test_verify_token_usa_il_pool(clock):
    seen = []

    def handler(request):
        key = request.headers.get("Authorization", "").removeprefix("Bearer ")
        seen.append((request.method, key))
        if key == K1:
            return httpx.Response(BAD_IP[0], json=BAD_IP[1])
        return httpx.Response(200, json={"status": "ok"})

    coc = CocApi([K1, K2], transport=httpx.MockTransport(handler))

    async def work():
        try:
            return await coc.verify_token("#P1", "abc")
        finally:
            await coc.close()

    assert asyncio.run(work()) == (True, None)
    assert seen == [("POST", K1), ("POST", K2)]


def test_molte_chiamate_concorrenti_con_una_chiave_rifiutata(clock, caplog):
    seen = []

    async def handler(request):
        key = request.headers.get("Authorization", "").removeprefix("Bearer ")
        seen.append(key)
        await asyncio.sleep(0)
        status, body = BAD_IP if key == K1 else OK
        return httpx.Response(status, json=body)

    coc = CocApi([K1, K2], transport=httpx.MockTransport(handler))
    limit, total = 8, 200

    async def work():
        sem = asyncio.Semaphore(limit)

        async def one(n):
            async with sem:
                return await coc.get("/locations", limit=n)

        try:
            return await asyncio.gather(*(one(n) for n in range(total)))
        finally:
            await coc.close()

    with caplog.at_level(logging.INFO, logger="clashbot.coc"):
        results = asyncio.run(work())
    assert len(results) == total
    assert all(error is None and data["name"] == "Clan" for data, error in results)
    assert seen.count(K2) == total
    assert 1 <= seen.count(K1) <= limit
    assert coc.keys_alive() == 1
    rejected = [record.getMessage() for record in caplog.records if "rifiutata" in record.getMessage()]
    assert rejected == ["chiave Clash 1 di 2 rifiutata (invalid_ip)"]
    assert K1 not in caplog.text and K2 not in caplog.text


def test_le_chiamate_al_minuto_contano_solo_l_ultimo_minuto(clock):
    api = Api()
    coc = pool(f"{K1},{K2}", api)

    async def work():
        try:
            assert coc.calls_per_minute() == 0
            for _ in range(5):
                await coc.clan("#ABC")
            assert coc.calls_per_minute() == 5
            clock.now += 61
            await coc.clan("#ABC")
            assert len(coc.calls) == 1
            assert coc.calls_per_minute() == 1
        finally:
            await coc.close()

    asyncio.run(work())


def test_le_chiamate_al_minuto_sopravvivono_al_cambio_di_chiavi(clock):
    api = Api()
    coc = pool(K1, api)

    async def work():
        try:
            await coc.clan("#ABC")
            coc.set_token([K2])
            assert coc.calls_per_minute() == 1
        finally:
            await coc.close()

    asyncio.run(work())


def test_soglia_dell_intervallo_del_poller():
    assert poll_interval(0, 1) == 60
    assert poll_interval(200, 1) == 60
    assert poll_interval(201, 1) == 120
    assert poll_interval(400, 2) == 60
    assert poll_interval(401, 2) == 120
    assert poll_interval(1, 0) == 120
    assert poll_interval(0, 0) == 60


def test_il_poller_ricalcola_l_intervallo_a_ogni_giro():
    coc = SimpleNamespace(alive=1)
    coc.keys_alive = lambda: coc.alive
    poller = Poller(SimpleNamespace(), None, coc)
    assert poller.interval == 60
    poller.pace(201)
    assert poller.interval == 120
    coc.alive = 2
    poller.pace(201)
    assert poller.interval == 60


def test_il_giro_del_poller_ricalcola_l_intervallo(monkeypatch):
    coc = SimpleNamespace(alive=1)
    coc.keys_alive = lambda: coc.alive
    coc.key_report = lambda: {"total": coc.alive, "dead": {}}
    clans = [SimpleNamespace(alias=f"clan-{i}", bot_alias="bot-a") for i in range(201)]
    ticked = []

    async def active_clans():
        return clans

    async def kv_purge():
        return 0

    async def kv_get(key):
        return None

    async def kv_set(key, obj, ref=None, ttl=None):
        return None

    async def get_secret(kind):
        return None

    async def tick(clan, sem):
        ticked.append(clan.alias)

    async def family_jobs(now):
        return None

    def stop():
        raise asyncio.CancelledError

    store = SimpleNamespace(active_clans=active_clans, kv_purge=kv_purge, kv_get=kv_get,
                            kv_set=kv_set, get_secret=get_secret)
    supervisor = SimpleNamespace(default_alias="bot-a", running=lambda: ["bot-a"], owner_bot=lambda: None)
    poller = Poller(supervisor, store, coc)
    monkeypatch.setattr(poller, "tick", tick)
    monkeypatch.setattr(poller, "family_jobs", family_jobs)
    monkeypatch.setattr(poller_mod, "HEARTBEAT", SimpleNamespace(touch=stop))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(poller.run())
    assert poller.interval == 120 and len(ticked) == 201
    coc.alive = 2
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(poller.run())
    assert poller.interval == 60


class SecretStore:
    def __init__(self):
        self.saved = []

    async def set_secret(self, kind, value):
        self.saved.append((kind, value))
        return "alias-1"


def patch_main(monkeypatch, api):
    monkeypatch.setattr(main_mod, "CocApi", lambda token=None: CocApi(token, transport=httpx.MockTransport(api)))

    async def ip():
        return "203.0.113.7"

    monkeypatch.setattr(main_mod, "public_ip", ip)


def test_secret_coc_api_key_salva_tutte_le_chiavi_valide(monkeypatch, capsys, clock):
    api = Api()
    patch_main(monkeypatch, api)
    store = SecretStore()
    asyncio.run(main_mod.store_secret(store, "coc_api_key", f" {K1},\n{K2}\n{K1}\n"))
    assert store.saved == [("coc_api_key", f"{K1},{K2}")]
    assert set(api.seen) == {K1, K2}
    out = capsys.readouterr().out
    assert "2" in out and K1 not in out and K2 not in out


def test_secret_coc_api_key_rifiuta_l_insieme_e_dice_quale_per_posizione(monkeypatch, capsys, clock):
    api = Api({K2: BAD_IP, K3: BAD_KEY})
    patch_main(monkeypatch, api)
    store = SecretStore()
    with pytest.raises(SystemExit) as exc:
        asyncio.run(main_mod.store_secret(store, "coc_api_key", f"{K1},{K2},{K3}"))
    message = str(exc.value)
    out = capsys.readouterr().out
    assert store.saved == []
    assert "n.2 (invalid_ip)" in message and "n.3 (invalid_key)" in message and "n.1" not in message
    assert "203.0.113.7" in message
    for key in (K1, K2, K3):
        assert key not in message and key not in out


def test_secret_coc_api_key_vuoto_viene_rifiutato(monkeypatch, clock):
    api = Api()
    patch_main(monkeypatch, api)
    store = SecretStore()
    with pytest.raises(SystemExit):
        asyncio.run(main_mod.store_secret(store, "coc_api_key", " ,\n "))
    assert store.saved == [] and api.seen == []


def test_secret_coc_api_key_legge_una_chiave_per_riga_da_stdin(monkeypatch, clock):
    api = Api()
    patch_main(monkeypatch, api)
    monkeypatch.setattr(main_mod.sys, "stdin", io.StringIO(f"{K1}\n{K2}\n\n{K3}\n"))
    store = SecretStore()
    asyncio.run(main_mod.secret(store, "coc_api_key"))
    assert store.saved == [("coc_api_key", f"{K1},{K2},{K3}")]


class StatusStore:
    def __init__(self, keys):
        self.vault = SimpleNamespace(key_id="k1")
        self.keys = keys

    async def list_secrets(self):
        return []

    async def get_secret(self, kind):
        return self.keys if kind == "coc_api_key" else None

    async def bots(self):
        return []

    async def counts(self):
        return {"active": 0, "total": 0}

    async def active_clans(self):
        return []


def test_status_conta_le_chiavi_senza_mostrarle(capsys):
    asyncio.run(main_mod.status(StatusStore(f"{K1},{K2}\n{K3}")))
    out = capsys.readouterr().out
    assert "chiavi Clash: 3" in out
    assert K1 not in out and K2 not in out and K3 not in out
    asyncio.run(main_mod.status(StatusStore(None)))
    assert "chiavi Clash: 0" in capsys.readouterr().out
