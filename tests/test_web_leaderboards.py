import asyncio
from urllib.robotparser import RobotFileParser

from clashbot import i18n
from clashbot.util import esc
from clashbot.web import app as web_app, pages, public
from test_web_status import ITALIAN, FakeStore, request, same_dress

L = i18n.locale("en")
PATH = "/leaderboards"
CODE = "ab12cd"
OTHER = "ef34gh"
ALIAS = "clan-a1"


def riga(code=CODE, name=None, avg=12.4, stars=124, members=46, alias=ALIAS):
    return {"alias": alias, "visible": True, "named": bool(name), "code": code, "name": name,
            "week": "2026-W39", "verified": True, "updated_at": None,
            "metrics": {"members": members, "avg": avg, "stars": stars, "donations": 9000}}


class RankStore(FakeStore):
    def __init__(self, rows=()):
        super().__init__()
        self.rows = list(rows)
        self.reads = 0

    async def network_board(self, limit=20):
        self.reads += 1
        return list(self.rows)


class Clock:
    def __init__(self, at=0.0):
        self.at = at

    def __call__(self):
        return self.at


def sito(rows=(), clock=None):
    return web_app.Site(RankStore(rows), clock or Clock())


def risposta(place, path=PATH):
    res = asyncio.run(place.router(request(path, headers=ITALIAN)))
    assert res.status == 200, path
    return res


def pagina(place, path=PATH):
    return risposta(place, path).body.decode()


def test_le_classifiche_sono_tessere_per_clan_senza_nessuna_persona():
    text = pagina(sito([riga(name="Futuro"), riga(code=OTHER, avg=6.2)]))
    same_dress(text)
    assert public.RANK_TITLE in text and public.RANK_NOTE in text
    assert text.count('class="tile"') == 2 and text.count('class="grid three"') == 1
    assert "Futuro" in text and "124" in text and "46" in text
    assert "<ul" not in text and "<ol" not in text
    assert "[web." not in text


def test_il_clan_senza_nome_resta_un_codice_e_l_alias_non_esce():
    text = pagina(sito([riga(), riga(code=OTHER, name="Futuro", alias="clan-b2")]))
    assert esc(L.t("network.anon", code=CODE)) in text
    assert ALIAS not in text and "clan-b2" not in text
    assert "2026-W39" not in text and "9000" not in text


def test_la_posizione_e_un_distintivo_e_la_barra_misura_la_media_sul_primo():
    text = pagina(sito([riga(avg=12.4), riga(code=OTHER, avg=6.2)]))
    assert text.count('class="badge"') == 2
    assert '<span class="badge">1</span>' in text and '<span class="badge">2</span>' in text
    assert text.count('class="bar"') == 2
    assert 'style="width:100%"' in text and 'style="width:50%"' in text


def test_la_pagina_lascia_la_fila_che_lo_store_ha_gia_fatto():
    text = pagina(sito([riga(code=CODE, avg=6.2), riga(code=OTHER, avg=12.4)]))
    assert text.index(CODE) < text.index(OTHER)
    assert not hasattr(public, "ranked")


def test_senza_clan_la_pagina_lo_dice_in_due_parole():
    text = pagina(sito())
    assert esc(L.t(public.EMPTY)) in text and text.count('class="tile"') == 1


def test_una_media_a_zero_non_rompe_la_barra():
    text = pagina(sito([riga(avg=0, stars=0), riga(code=OTHER, avg=0)]))
    assert 'style="width:0%"' in text and text.count('class="bar"') == 2


def test_le_classifiche_si_ricaricano_da_sole_e_restano_in_cache_un_minuto():
    res = risposta(sito([riga()]))
    assert res.headers["Cache-Control"] == pages.LIVE_HEAD
    assert f'<meta http-equiv="refresh" content="{pages.FRESH_EVERY}">' in res.body.decode()


def test_la_seconda_richiesta_non_rilegge_il_database():
    clock = Clock()
    place = sito([riga()], clock)
    risposta(place)
    risposta(place)
    assert place.store.reads == 1
    clock.at += web_app.PAGE_CACHE
    risposta(place)
    assert place.store.reads == 2


def test_i_motori_possono_leggere_le_classifiche():
    testo = asyncio.run(sito().router(request("/robots.txt"))).body.decode()
    regole = RobotFileParser()
    regole.parse(testo.splitlines())
    assert f"Allow: {PATH}" in testo and regole.can_fetch("*", PATH)


def test_una_riga_storta_non_porta_giu_la_classifica():
    storte = [{"code": CODE, "metrics": {"avg": "dodici", "stars": None, "members": "tanti"}},
              {"code": OTHER, "metrics": "boh"}, "non un dizionario"]
    text = pagina(sito(storte))
    assert text.count('class="tile"') == 2 and text.count('style="width:0%"') == 2
    assert "[web." not in text and "dodici" not in text
