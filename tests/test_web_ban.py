import asyncio
import copy
from datetime import datetime, timezone

import pytest

from clashbot import i18n
from clashbot.platform_guard import FLOOD_LIMIT, FLOOD_WINDOW
from clashbot.web import app as web_app, ban, http, pages

AT = 1789000000.0
IP = "203.0.113.9"
OTHER = "198.51.100.7"
TUNNEL = "127.0.0.2"
IT = i18n.locale("it")
EN = i18n.locale("en")


class Kv:
    def __init__(self, now=AT):
        self.now = float(now)
        self.rows = {}
        self.ttls = {}

    def tick(self, seconds):
        self.now += float(seconds)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.ttls[key] = ttl
        self.rows[key] = (copy.deepcopy(obj), None if ttl is None else self.now + float(ttl))

    async def kv_get(self, key):
        found = self.rows.get(key)
        if not found:
            return None
        body, until = found
        if until is not None and self.now >= until:
            self.rows.pop(key, None)
            self.ttls.pop(key, None)
            return None
        return copy.deepcopy(body)

    async def kv_del(self, key):
        self.rows.pop(key, None)
        self.ttls.pop(key, None)

    async def get_secret(self, kind):
        return None

    async def web_note(self, name):
        return None

    async def web_page(self, slug, kind):
        return None

    async def web_app_alias(self, slug):
        return None

    async def recruit_target(self, code):
        return None

    async def banned(self, limit=ban.KEEP):
        found = []
        for key in sorted(self.rows):
            if not key.startswith(ban.PREFIX):
                continue
            body = await self.kv_get(key)
            if body is None:
                continue
            found.append({"ip": key[len(ban.PREFIX):], "at": body.get("at"),
                          "until": body.get("until"), "strikes": body.get("strikes")})
        found.sort(key=lambda row: -(row.get("at") or 0))
        return found[:limit]


@pytest.fixture
def negozio():
    return Kv()


@pytest.fixture
def sito(negozio, monkeypatch):
    monkeypatch.setattr(web_app, "now_utc",
                        lambda: datetime.fromtimestamp(negozio.now, timezone.utc))
    return web_app.Site(negozio)


def chiedi(sito, path, ip=IP, method="GET", peer=TUNNEL, extra=None):
    headers = {"accept-language": "it-IT,it;q=0.9"}
    if ip:
        headers["cf-connecting-ip"] = ip
    headers.update(extra or {})
    req = http.Request(method, path, {}, headers, b"", peer)
    return asyncio.run(sito.router(req))


def riga(negozio, ip=IP):
    return asyncio.run(negozio.kv_get(ban.PREFIX + ip))


def test_i_percorsi_da_scansione_e_i_tempi_sono_quelli_gia_decisi():
    assert ban.PROBES == ("/.env", "/.git", "/wp-login.php", "/wp-admin", "/xmlrpc.php",
                          "/phpmyadmin", "/admin", "/administrator", "/config", "/.aws",
                          "/panel", "/auth", "/login", "/cgi-bin", "/vendor", "/backup")
    assert (FLOOD_LIMIT, FLOOD_WINDOW, ban.DAY) == (5, 3600, 86400)
    assert ban.STEPS == (FLOOD_WINDOW, ban.DAY, None)
    assert ban.KEEP == 100


def test_chi_chiede_una_porta_da_scansione_e_bandito_un_ora_e_vede_l_avvertimento(sito, negozio):
    res = chiedi(sito, "/.env")
    assert res.status == 403 and res.kind == http.HTML
    testo = res.body.decode()
    assert EN.t("ban.page.title") in testo and IP in testo
    assert res.headers["Cache-Control"] == "no-store"
    stato = riga(negozio)
    assert stato["strikes"] == 1 and stato["until"] == AT + FLOOD_WINDOW
    assert negozio.ttls[ban.PREFIX + IP] == FLOOD_WINDOW


def test_dopo_il_bando_anche_la_home_risponde_col_divieto(sito, negozio):
    assert chiedi(sito, "/.env").status == 403
    assert chiedi(sito, "/").status == 403
    assert chiedi(sito, "/status").status == 403
    assert chiedi(sito, "/", ip=OTHER).status == 200


def test_la_maiuscola_e_il_prefisso_non_salvano_chi_scansiona(sito, negozio):
    assert chiedi(sito, "/WP-Login.php").status == 403
    assert chiedi(sito, "/.git/config", ip=OTHER).status == 403
    assert riga(negozio, OTHER)["strikes"] == 1


def test_chi_cerca_le_regole_per_segnalare_non_e_mai_bandito(sito, negozio):
    assert ban.SPARED == ("/.well-known/security.txt", "/robots.txt")
    assert chiedi(sito, "/.env").status == 403
    for path in ban.SPARED:
        assert chiedi(sito, path).status != 403, path
    assert chiedi(sito, "/robots.txt").status == 200
    assert riga(negozio)["strikes"] == 1
    assert asyncio.run(negozio.kv_get(ban.MISS + IP)) is None


def test_le_regole_per_segnalare_non_contano_nel_conto_dei_quattrocentoquattro(sito, negozio):
    for _ in range(FLOOD_LIMIT + 2):
        assert chiedi(sito, "/.well-known/security.txt", ip=OTHER).status == 404
    assert riga(negozio, OTHER) is None


def test_il_bando_scade_e_la_home_torna_a_rispondere(sito, negozio):
    assert chiedi(sito, "/.env").status == 403
    negozio.tick(FLOOD_WINDOW + 1)
    assert chiedi(sito, "/").status == 200


def test_cinque_quattrocentoquattro_in_un_ora_bandiscono_e_quattro_no(sito, negozio):
    for numero in range(FLOOD_LIMIT - 1):
        assert chiedi(sito, f"/pinco{numero}").status == 404
    assert riga(negozio) is None
    assert chiedi(sito, "/pinco9").status == 404
    assert riga(negozio)["strikes"] == 1
    assert chiedi(sito, "/").status == 403


def test_le_rotte_conosciute_non_bandiscono_chi_arriva_tardi(sito, negozio):
    conosciute = ("/c/nessuno", "/c/nessuno/widget", "/c/nessuno/calendar.ics",
                  "/app/nessuno/state", "/app/nessuno/feed", "/app/nessuno/mydata.json",
                  "/app/nessuno/export.csv", "/r/codicevecchio")
    for percorso in conosciute:
        for _ in range(FLOOD_LIMIT):
            assert chiedi(sito, percorso).status == 404, percorso
        assert riga(negozio) is None, percorso
    assert asyncio.run(negozio.kv_get(ban.MISS + IP)) is None
    for numero in range(FLOOD_LIMIT - 1):
        assert chiedi(sito, f"/pinco{numero}").status == 404
    assert riga(negozio) is None
    assert chiedi(sito, "/pinco9").status == 404
    assert riga(negozio)["strikes"] == 1


def test_il_metodo_sbagliato_su_una_rotta_conosciuta_non_bandisce(sito, negozio):
    for _ in range(FLOOD_LIMIT + 2):
        assert chiedi(sito, "/app/nessuno/act").status == 405
    assert riga(negozio) is None
    assert asyncio.run(negozio.kv_get(ban.MISS + IP)) is None


def test_i_quattrocentoquattro_vecchi_non_contano(sito, negozio):
    for numero in range(FLOOD_LIMIT - 1):
        assert chiedi(sito, f"/pinco{numero}").status == 404
    negozio.tick(FLOOD_WINDOW + 1)
    assert chiedi(sito, "/pinco9").status == 404
    assert riga(negozio) is None


def test_il_secondo_colpo_dura_un_giorno_e_il_terzo_non_scade(negozio):
    asyncio.run(ban.strike(negozio, IP, negozio.now))
    assert riga(negozio)["strikes"] == 1
    negozio.tick(FLOOD_WINDOW + 1)
    asyncio.run(ban.strike(negozio, IP, negozio.now))
    stato = riga(negozio)
    assert stato["strikes"] == 2 and stato["until"] == negozio.now + ban.DAY
    negozio.tick(ban.DAY + 1)
    assert riga(negozio) is None
    asyncio.run(ban.strike(negozio, IP, negozio.now))
    stato = riga(negozio)
    assert stato["strikes"] == 3 and stato["until"] is None
    assert negozio.ttls[ban.PREFIX + IP] is None
    negozio.tick(30 * ban.DAY)
    assert riga(negozio)["strikes"] == 3


def test_sbandire_toglie_tutto_e_l_indirizzo_riparte_da_zero(sito, negozio):
    assert chiedi(sito, "/.env").status == 403
    asyncio.run(ban.lift(negozio, IP))
    assert riga(negozio) is None
    assert asyncio.run(negozio.kv_get(ban.HIST + IP)) is None
    assert asyncio.run(negozio.kv_get(ban.MISS + IP)) is None
    assert chiedi(sito, "/").status == 200
    assert chiedi(sito, "/.env").status == 403
    assert riga(negozio)["strikes"] == 1


def test_un_altro_indirizzo_non_e_toccato(sito, negozio):
    assert chiedi(sito, "/.env").status == 403
    assert riga(negozio, OTHER) is None
    assert chiedi(sito, "/", ip=OTHER).status == 200
    for numero in range(FLOOD_LIMIT):
        chiedi(sito, f"/pinco{numero}", ip=OTHER)
    assert riga(negozio, OTHER)["strikes"] == 1
    assert riga(negozio, IP)["strikes"] == 1


def test_l_indirizzo_e_quello_che_passa_cloudflare_non_quello_del_tunnel():
    req = http.Request("GET", "/", {}, {"cf-connecting-ip": IP, "x-forwarded-for": OTHER},
                       b"", TUNNEL)
    assert req.ip == IP
    da_fuori = http.Request("GET", "/", {}, {"cf-connecting-ip": IP}, b"", OTHER)
    assert da_fuori.ip == OTHER


def test_la_pagina_di_avvertimento_non_ha_script_ne_richiami_di_fuori():
    testo = pages.warning_page(IT, IP, AT)
    assert "<script" not in testo and "onclick" not in testo
    assert "http://" not in testo and "https://" not in testo
    assert "//" not in testo.replace("<!doctype html>", "")
    assert IP in testo and "/.well-known/security.txt" in testo
    assert IT.t("ban.page.logged") in testo
    assert EN.t("ban.page.title") in pages.warning_page(EN, IP, AT)


def test_l_avvertimento_dice_l_ora_del_tentativo():
    testo = pages.warning_page(IT, IP, AT)
    quando = IT.when(datetime.fromtimestamp(int(AT), timezone.utc), "UTC")
    assert quando in testo


def test_il_riassunto_conta_i_banditi_di_adesso_e_dell_ultima_ora(negozio):
    for numero in range(3):
        asyncio.run(ban.strike(negozio, f"203.0.113.{numero}", negozio.now))
    negozio.tick(FLOOD_WINDOW + 1)
    asyncio.run(ban.strike(negozio, "203.0.113.9", negozio.now))
    corpo = asyncio.run(ban.summary(negozio, negozio.now))
    assert corpo["n"] == 1 and corpo["hour"] == 1
    assert corpo["window"] == FLOOD_WINDOW
    assert corpo["last"][0]["ip"] == "203.0.113.9"


def test_un_indirizzo_inventato_non_entra_nella_pagina_come_codice():
    testo = pages.warning_page(IT, '<img src=x onerror="rubo()">', AT)
    assert "<img" not in testo and 'onerror="' not in testo
    assert "&lt;img src=x onerror=&quot;rubo()&quot;&gt;" in testo


def test_il_divieto_non_scatta_senza_indirizzo(negozio):
    assert asyncio.run(ban.check(negozio, set(), "", "/.env", negozio.now, IT)) is None
    assert asyncio.run(ban.miss(negozio, set(), "", negozio.now)) is False
    assert negozio.rows == {}


class Contato(Kv):
    def __init__(self, now=AT):
        super().__init__(now)
        self.letti = []

    async def kv_get(self, key):
        if key.startswith(ban.PREFIX):
            self.letti.append(key)
        return await super().kv_get(key)


@pytest.fixture
def contato(monkeypatch):
    negozio = Contato()
    monkeypatch.setattr(web_app, "now_utc",
                        lambda: datetime.fromtimestamp(negozio.now, timezone.utc))
    return negozio


def test_il_bando_si_rilegge_una_volta_per_battito_non_a_ogni_richiesta(contato):
    sito = web_app.Site(contato)
    for _ in range(FLOOD_LIMIT):
        assert chiedi(sito, "/").status == 200
    assert contato.letti == [ban.PREFIX + IP]
    assert chiedi(sito, "/", ip=OTHER).status == 200
    assert contato.letti == [ban.PREFIX + IP, ban.PREFIX + OTHER]
    asyncio.run(sito.refresh())
    assert sito.seen == set()
    assert chiedi(sito, "/").status == 200
    assert contato.letti == [ban.PREFIX + IP, ban.PREFIX + OTHER, ban.PREFIX + IP]


def test_chi_e_bandito_lo_resta_a_ogni_richiesta_e_lo_sbando_vale_subito(contato):
    sito = web_app.Site(contato)
    assert chiedi(sito, "/.env").status == 403
    assert sito.seen == set()
    assert chiedi(sito, "/").status == 403
    assert chiedi(sito, "/").status == 403
    asyncio.run(ban.lift(contato, IP))
    assert chiedi(sito, "/").status == 200


def documentazione(quanti):
    blocchi = ("203.0.113", "198.51.100", "192.0.2")
    return [f"{blocchi[numero // 256]}.{numero % 256}" for numero in range(quanti)]


def test_il_sito_non_ricorda_piu_indirizzi_del_secchiello(contato):
    sito = web_app.Site(contato)
    for indirizzo in documentazione(http.BUCKET_MAX + 2):
        assert chiedi(sito, "/", ip=indirizzo).status == 200
    assert len(sito.seen) == http.BUCKET_MAX
