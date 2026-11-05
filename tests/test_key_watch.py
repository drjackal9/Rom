import asyncio
import copy
import json

import httpx
import pytest
from telegram.error import TelegramError

from clashbot import events_registry, i18n, key_watch, manager_alerts, platform, render
from clashbot.coc import CocApi

K1 = "chiave-uno-finta"
K2 = "chiave-due-finta"
K3 = "chiave-tre-finta"
OK = (200, {"items": []})
BAD_IP = (403, {"reason": "accessDenied.invalidIp",
                "message": "Invalid authorization: API key does not allow access from IP"})
BAD_KEY = (403, {"reason": "accessDenied", "message": "Invalid authorization"})
PRIVATE = (403, {"reason": "accessDenied", "message": "war log is private"})
RATE = (429, {"reason": "requestThrottled"})
DOWN = (503, {"reason": "inMaintenance"})
DELEGATE = 7
IT = i18n.locale("it")
EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
AT = 1789000000.0


class Api:
    def __init__(self, rules=None):
        self.rules = dict(rules or {})

    def __call__(self, request):
        key = request.headers.get("Authorization", "").removeprefix("Bearer ")
        status, body = self.rules.get(key, OK)
        return httpx.Response(status, json=body)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


class BotFragile(FakeBot):
    def __init__(self, salta):
        super().__init__()
        self.salta = salta
        self.tentativi = 0

    async def send_message(self, chat_id, text, **kw):
        self.tentativi += 1
        if self.tentativi == self.salta:
            raise TelegramError("bloccato")
        await super().send_message(chat_id, text, **kw)


class FakeStore:
    def __init__(self):
        self.secrets = {"owner_id": "42", "owner_lang": "it"}
        self.kv = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)


def pool(token, rules=None):
    return CocApi(token, transport=httpx.MockTransport(Api(rules)))


def calls(coc, n):
    async def work():
        try:
            return [await coc.clan("#ABC") for _ in range(n)]
        finally:
            await coc.close()

    return asyncio.run(work())


def giro(coc, n=1):
    async def work():
        return [await coc.clan("#ABC") for _ in range(n)]

    return asyncio.run(work())


def con_delegato(store):
    store.kv[platform.KEY] = [{"username": "cyfren1", "user_id": DELEGATE}]
    return store


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    chiamate = []

    async def ip():
        chiamate.append(1)
        return "203.0.113.7"

    monkeypatch.setattr(key_watch, "public_ip", ip)
    return chiamate


def test_la_fotografia_dice_quante_chiavi_sono_morte_e_perche():
    coc = pool(f"{K1},{K2},{K3}", {K2: BAD_KEY})
    assert coc.key_report() == {"total": 3, "dead": {}}
    calls(coc, 4)
    assert coc.key_report() == {"total": 3, "dead": {1: "invalid_key"}}
    assert coc.keys_alive() == 2


def test_la_chiave_torna_viva_solo_dopo_una_chiamata_riuscita():
    api = Api({K1: BAD_KEY})
    coc = CocApi(f"{K1},{K2}", transport=httpx.MockTransport(api))

    async def work():
        await coc.clan("#ABC")
        assert coc.key_report()["dead"] == {0: "invalid_key"}
        api.rules.clear()
        coc.dead[0] = 0.0
        await coc.clan("#ABC")
        await coc.clan("#ABC")
        await coc.close()

    asyncio.run(work())
    assert coc.key_report() == {"total": 2, "dead": {}}


def test_la_firma_distingue_ogni_stato():
    assert key_watch.signature({"total": 3, "dead": {}}) == "ok:3"
    assert key_watch.signature({"total": 3, "dead": {1: "invalid_key"}}) == "1:invalid_key/3"
    assert key_watch.signature({"total": 3, "dead": {2: "invalid_ip", 0: "invalid_key"}}) == "0:invalid_key;2:invalid_ip/3"
    assert key_watch.alive({"total": 3, "dead": {1: "x"}}) == 2


def test_una_chiave_su_tre_da_la_card_nuova_senza_mai_scriverla():
    report = {"total": 3, "dead": {1: "invalid_key"}}
    text = key_watch.card(IT, report, "203.0.113.7")
    assert IT.t("owner.key.partial.title") in text
    assert IT.t("owner.key.line", n=2, total=3, why=IT.t("owner.key.rejected.short")) in text
    assert "2" in text and K1 not in text and K2 not in text and K3 not in text


def test_tutte_morte_danno_la_card_di_oggi_parola_per_parola():
    report = {"total": 2, "dead": {0: "invalid_ip", 1: "invalid_ip"}}
    text = key_watch.card(IT, report, "203.0.113.7")
    assert text == render.card(
        "🚫", IT.t("owner.key.invalid_ip.title"),
        IT.t("owner.key.body", why=IT.t("owner.key.invalid_ip.why", ip="203.0.113.7"), ip="203.0.113.7"),
    )


def test_il_ritorno_a_posto_ha_la_sua_card_e_non_nomina_l_ip():
    text = key_watch.card(IT, {"total": 3, "dead": {}}, None)
    assert IT.t("owner.key.back.title") in text
    assert IT.t("owner.key.back.body", alive=3, total=3) in text
    assert "None" not in text
    assert text == key_watch.card(IT, {"total": 3, "dead": {}}, "203.0.113.7")


def test_un_solo_avviso_per_cambio_di_stato(no_network):
    store, bot = FakeStore(), FakeBot()
    coc = pool(f"{K1},{K2},{K3}", {K2: BAD_KEY})
    calls(coc, 4)

    async def work():
        first = await key_watch.check(store, bot, coc, AT)
        again = await key_watch.check(store, bot, coc, AT + 60)
        coc.dead.clear()
        coc.reasons.clear()
        back = await key_watch.check(store, bot, coc, AT + 120)
        return first, again, back

    assert asyncio.run(work()) == (True, False, True)
    assert len(bot.sent) == 2
    assert IT.t("owner.key.partial.title") in bot.sent[0][1]
    assert IT.t("owner.key.back.title") in bot.sent[1][1]
    assert store.kv["platform:keys"]["history"][0]["dead"] == [1]
    assert store.kv["platform:keys"]["history"][-1]["alive"] == 3
    assert len(no_network) == 1


def test_il_ritorno_a_posto_non_consegnato_riparte_al_giro_dopo(no_network):
    store, bot = FakeStore(), BotFragile(2)
    coc = pool(f"{K1},{K2},{K3}", {K2: BAD_KEY})
    calls(coc, 4)

    async def work():
        morta = await key_watch.check(store, bot, coc, AT)
        coc.dead.clear()
        coc.reasons.clear()
        persa = await key_watch.check(store, bot, coc, AT + 60)
        ripresa = await key_watch.check(store, bot, coc, AT + 120)
        return morta, persa, ripresa

    assert asyncio.run(work()) == (True, False, True)
    assert bot.tentativi == 3
    assert len(bot.sent) == 2
    assert IT.t("owner.key.partial.title") in bot.sent[0][1]
    assert IT.t("owner.key.back.title") in bot.sent[1][1]
    assert store.kv["platform:keys"]["sent"] is True
    assert [row["alive"] for row in store.kv["platform:keys"]["history"]] == [2, 3]


def test_una_chiave_morta_non_consegnata_riparte_al_giro_dopo(no_network):
    store, bot = FakeStore(), BotFragile(1)
    coc = pool(f"{K1},{K2},{K3}", {K2: BAD_KEY})
    calls(coc, 4)

    async def work():
        return await key_watch.check(store, bot, coc, AT), await key_watch.check(store, bot, coc, AT + 60)

    assert asyncio.run(work()) == (False, True)
    assert len(bot.sent) == 1
    assert IT.t("owner.key.partial.title") in bot.sent[0][1]
    assert len(store.kv["platform:keys"]["history"]) == 1


def test_senza_chiavi_configurate_il_controllo_tace():
    store, bot = FakeStore(), FakeBot()
    coc = pool(None)
    assert asyncio.run(key_watch.check(store, bot, coc, AT)) is False
    assert bot.sent == [] and store.kv == {}
    asyncio.run(coc.close())


def test_al_primo_giro_con_tutto_a_posto_registra_e_tace():
    store, bot = FakeStore(), FakeBot()
    coc = pool(f"{K1},{K2}")
    calls(coc, 2)

    async def work():
        return await key_watch.check(store, bot, coc, AT), await key_watch.check(store, bot, coc, AT + 60)

    assert asyncio.run(work()) == (False, False)
    assert bot.sent == []
    assert store.kv["platform:keys"]["sig"] == "ok:2"
    assert len(store.kv["platform:keys"]["history"]) == 1
    assert key_watch.was_broken({}) is False
    assert key_watch.was_broken({"sig": "ok:3"}) is False
    assert key_watch.was_broken({"sig": "1:invalid_key/3"}) is True
    assert key_watch.settled({}) is True
    assert key_watch.settled({"sig": "ok:3", "sent": True}) is True
    assert key_watch.settled({"sig": "ok:3", "sent": False}) is False
    assert key_watch.settled({"sig": "1:invalid_key/3", "sent": True}) is False


def test_un_registro_guerre_privato_non_e_un_problema_di_chiavi():
    store, bot = FakeStore(), FakeBot()
    coc = pool(f"{K1},{K2}", {K1: PRIVATE, K2: PRIVATE})
    calls(coc, 2)
    assert coc.key_report()["dead"] == {}
    assert asyncio.run(key_watch.check(store, bot, coc, AT)) is False
    assert bot.sent == []


def test_gli_eventi_del_blocco_sono_nel_registro_della_fase_7():
    assert key_watch.PACK in events_registry.PACKS
    assert "manager_dm" in events_registry.DESTINATIONS
    for event in key_watch.EVENTS + ("platform.restore",):
        entry = events_registry.EVENTS[event]
        assert entry["pack"] == key_watch.PACK
        assert entry["default"] == "manager_dm"
        assert entry["allowed"] == ("manager_dm",)
        assert entry["intensity"] is None


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("owner.key.partial.title", "owner.key.partial.body", "owner.key.line",
                "owner.key.invalid_ip.short", "owner.key.rejected.short",
                "owner.key.back.title", "owner.key.back.body", "console.stats_keys"):
        assert key in EN, key


def test_lo_stato_scritto_non_contiene_mai_una_chiave():
    store, bot = FakeStore(), FakeBot()
    coc = pool(f"{K1},{K2}", {K1: BAD_IP})
    calls(coc, 2)
    asyncio.run(key_watch.check(store, bot, coc, AT))
    scritto = json.dumps(store.kv, default=str)
    for key in (K1, K2):
        assert key not in scritto
    assert manager_alerts.key_of("keys") in store.kv


def test_il_giro_del_motore_conta_pause_manutenzioni_e_risposte():
    coc = pool(f"{K1},{K2}", {K1: RATE, K2: RATE})
    giro(coc, 1)
    report = coc.round_report()
    assert report["stall"] == "rate" and report["keys"] == 2 and report["calls"] > 0
    assert coc.round_report() == {"stall": None, "keys": 2, "calls": 0}
    asyncio.run(coc.close())


def test_il_giro_tutto_in_pausa_avvisa_gestore_e_delegato(no_network):
    store, bot = con_delegato(FakeStore()), FakeBot()
    coc = pool(f"{K1},{K2}", {K1: RATE, K2: RATE})
    giro(coc, 1)
    assert asyncio.run(key_watch.check(store, bot, coc, AT)) is True
    asyncio.run(coc.close())
    assert [chat for chat, _ in bot.sent] == [42, DELEGATE]
    text = bot.sent[0][1]
    assert IT.t("owner.api.rate.title") in text
    assert IT.t("owner.api.rate.what") in text
    assert IT.when(manager_alerts.moment(AT)) in text
    assert "2" in text


def test_la_manutenzione_del_gioco_ha_il_suo_avviso(no_network):
    store, bot = FakeStore(), FakeBot()
    coc = pool(K1, {K1: DOWN})
    giro(coc, 1)
    assert asyncio.run(key_watch.check(store, bot, coc, AT)) is True
    asyncio.run(coc.close())
    assert len(bot.sent) == 1
    assert IT.t("owner.api.maintenance.title") in bot.sent[0][1]
    assert IT.t("owner.api.maintenance.what") in bot.sent[0][1]


def test_un_avviso_per_episodio_e_uno_alla_fine(no_network):
    store, bot = FakeStore(), FakeBot()
    api = Api({K1: RATE})
    coc = CocApi(K1, transport=httpx.MockTransport(api))
    giro(coc, 1)
    primo = asyncio.run(key_watch.check(store, bot, coc, AT))
    giro(coc, 1)
    ancora = asyncio.run(key_watch.check(store, bot, coc, AT + 60))
    api.rules.clear()
    coc.cooling.clear()
    giro(coc, 1)
    fine = asyncio.run(key_watch.check(store, bot, coc, AT + 120))
    asyncio.run(coc.close())
    assert (primo, ancora, fine) == (True, False, True)
    assert len(bot.sent) == 2
    assert IT.t("owner.api.rate.title") in bot.sent[0][1]
    assert IT.t("owner.api.back.title") in bot.sent[1][1]
    assert IT.delta(manager_alerts.moment(AT + 120), manager_alerts.moment(AT)) in bot.sent[1][1]


def test_un_giro_con_una_risposta_buona_non_e_un_episodio(no_network):
    store, bot = FakeStore(), FakeBot()
    coc = pool(f"{K1},{K2}", {K1: RATE})
    giro(coc, 2)
    assert asyncio.run(key_watch.check(store, bot, coc, AT)) is False
    asyncio.run(coc.close())
    assert bot.sent == []
    assert store.kv[manager_alerts.key_of(key_watch.API_KIND)]["sig"] == "ok:2"


def test_un_giro_senza_chiamate_non_scrive_lo_stato_dell_api(no_network):
    store, bot = FakeStore(), FakeBot()
    coc = pool(K1)
    assert asyncio.run(key_watch.check(store, bot, coc, AT)) is False
    asyncio.run(coc.close())
    assert manager_alerts.key_of(key_watch.API_KIND) not in store.kv


def test_un_delegato_non_ancora_legato_non_riceve_l_avviso(no_network):
    store, bot = FakeStore(), FakeBot()
    store.kv[platform.KEY] = [{"username": "cyfren1", "user_id": None}]
    coc = pool(K1, {K1: RATE})
    giro(coc, 1)
    assert asyncio.run(key_watch.check(store, bot, coc, AT)) is True
    asyncio.run(coc.close())
    assert [chat for chat, _ in bot.sent] == [42]


def test_lo_stato_dell_api_non_nomina_mai_una_chiave(no_network):
    store, bot = con_delegato(FakeStore()), FakeBot()
    coc = pool(f"{K1},{K2}", {K1: RATE, K2: RATE})
    giro(coc, 1)
    asyncio.run(key_watch.check(store, bot, coc, AT))
    asyncio.run(coc.close())
    scritto = json.dumps(store.kv, default=str) + json.dumps(bot.sent, default=str)
    assert K1 not in scritto and K2 not in scritto


def test_le_chiavi_dell_avviso_api_esistono_in_inglese():
    for key in ("owner.api.rate.title", "owner.api.rate.what", "owner.api.maintenance.title",
                "owner.api.maintenance.what", "owner.api.body", "owner.api.back.title",
                "owner.api.back.body"):
        assert key in EN, key
