import asyncio
from datetime import datetime, timezone
from urllib.robotparser import RobotFileParser

from clashbot import base_videos, i18n, news_feed
from clashbot.util import esc
from clashbot.web import app as web_app, pages, public
from test_web_status import ITALIAN, FakeStore, request, same_dress

L = i18n.locale("en")
WAR = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16%3AHV%3AAAAABBBBCCCC"
FARM = "https://link.clashofclans.com/it?action=OpenLayout&id=TH15%3AHV%3ADDDDEEEEFFFF"
FUORI = "https://esempio.invalido/base.png"
CLIP = "AbcDef12345"


def row(code="a", hall=16, kind="war", link=WAR, builder="Pino", name="Anti 3"):
    return {"id": code, "name": name, "hall": hall, "village": "home", "kind": kind,
            "link": link, "builder": builder, "tags": [], "added": "2026-09-01"}


def video(code=CLIP, title="TH16 tre stelle"):
    return {"id": code, "channel": "UCpinco", "title": title,
            "published": "2026-09-02T10:00:00Z", "links": [WAR]}


class ShelfStore(FakeStore):
    def __init__(self, rows=(), videos=(), secrets=None):
        super().__init__(secrets=secrets)
        self.rows = list(rows)
        self.videos = list(videos)
        self.touched = []
        self.asked = None
        self.scopes = []

    async def library_rows(self, hall=None, village=None, kind=None, limit=None):
        self.touched.append("library_rows")
        self.asked = {"hall": hall, "village": village, "kind": kind}
        return list(self.rows)

    async def videos_rows(self, scope=None, limit=None):
        self.touched.append("videos_rows")
        self.scopes.append(scope)
        return list(self.videos)


class Clock:
    def __init__(self, at=0.0):
        self.at = at

    def __call__(self):
        return self.at


def site(store, clock=None):
    return web_app.Site(store, clock or Clock())


def answer(place, path="/bases"):
    res = asyncio.run(place.router(request(path, headers=ITALIAN)))
    assert res.status == 200, path
    return res


def page(place, path="/bases"):
    return answer(place, path).body.decode()


def test_ogni_base_e_una_tessera_col_link_del_gioco_e_il_credito_di_chi_l_ha_fatta():
    text = page(site(ShelfStore([row()], [video()])))
    same_dress(text)
    assert esc(L.t(public.TITLE)) in text
    assert "[web." not in text
    assert text.count('class="tile"') == 2
    assert f'href="{esc(WAR)}"' in text and "TH16" in text
    assert esc(L.t(public.BY, name="Pino")) in text
    assert esc(L.t("bases.label.war")) in text
    assert "<ul" not in text and "<ol" not in text


def test_le_basi_non_chiedono_niente_dei_clan():
    store = ShelfStore([row()], [video()])
    answer(site(store))
    assert store.touched == ["library_rows", "videos_rows"]
    assert store.scopes == [base_videos.PLATFORM]


def test_il_municipio_scelto_lascia_solo_le_sue_basi():
    store = ShelfStore([row(), row("b", hall=15, kind="farm", link=FARM)])
    text = page(site(store), "/bases?th=16")
    assert esc(WAR) in text and esc(FARM) not in text
    assert store.asked == {"hall": None, "village": None, "kind": None}


def test_il_tipo_scelto_lascia_solo_le_sue_basi():
    store = ShelfStore([row(), row("b", hall=15, kind="farm", link=FARM)])
    text = page(site(store), "/bases?kind=farm")
    assert esc(FARM) in text and esc(WAR) not in text


def test_un_filtro_inventato_non_toglie_niente_e_non_finisce_in_pagina():
    store = ShelfStore([row()])
    text = page(site(store), "/bases?th=pinco&kind=<pinco>")
    assert esc(WAR) in text and "pinco" not in text


def test_un_municipio_senza_basi_tiene_il_filtro_e_mostra_la_griglia_vuota():
    store = ShelfStore([row()])
    text = page(site(store), "/bases?th=15")
    assert esc(WAR) not in text
    assert esc(L.t(public.EMPTY)) in text
    assert 'class="chip on" href="/bases?th=15"' in text
    assert f'class="chip" href="/bases">{esc(L.t(public.ANY))}' in text


def test_le_pedine_portano_al_filtro_e_a_toglierlo():
    store = ShelfStore([row(), row("b", hall=15, kind="farm", link=FARM)])
    text = page(site(store), "/bases?th=16")
    assert 'href="/bases?th=15"' in text and 'href="/bases"' in text
    assert 'class="chip on"' in text
    assert esc(L.t(public.HALL)) in text and esc(L.t(public.KIND)) in text
    assert text.count(esc(L.t(public.ANY))) == 2
    assert esc(L.t("bases.label.farm")) in text


def test_i_video_hanno_l_anteprima_e_portano_al_canale():
    res = answer(site(ShelfStore([], [video()])))
    text = res.body.decode()
    assert base_videos.THUMB + CLIP + base_videos.THUMB_SIZE in text
    assert base_videos.WATCH + CLIP in text
    assert esc(L.t(public.VIDEOS)) in text
    csp = res.headers["Content-Security-Policy"]
    assert base_videos.THUMB_HOST in csp and "frame-ancestors 'none'" in csp


def test_una_riga_senza_link_del_gioco_non_arriva_in_pagina():
    text = page(site(ShelfStore([row("z", link=FUORI), row()])))
    assert FUORI not in text and esc(WAR) in text


def test_senza_righe_la_pagina_lo_dice_in_due_parole():
    text = page(site(ShelfStore()))
    assert text.count(esc(L.t(public.EMPTY))) == 2
    assert text.count(public.empty_tile(L)) == 2
    vuote = page(site(ShelfStore()), "/news")
    assert vuote.count(public.empty_tile(L)) == 2


def test_le_parole_della_pagina_sono_quelle_che_il_catalogo_ha_gia():
    for key in (public.TITLE, public.HALL, public.KIND, public.BY, public.VIDEOS, public.EMPTY,
                public.ANY):
        for code in ("it", "en"):
            assert not i18n.locale(code).t(key).startswith("["), (code, key)


def test_la_seconda_richiesta_entro_la_cache_non_rilegge_il_database():
    store = ShelfStore([row()], [video()])
    clock = Clock()
    place = site(store, clock)
    answer(place)
    answer(place, "/bases?th=16")
    assert store.touched == ["library_rows", "videos_rows"]
    clock.at += web_app.PAGE_CACHE
    answer(place)
    assert store.touched == ["library_rows", "videos_rows"] * 2


def test_la_pagina_delle_basi_resta_in_cache_anche_per_chi_legge():
    res = answer(site(ShelfStore([row()])))
    assert res.headers["Cache-Control"] == web_app.PAGE_HEAD


def test_i_motori_possono_leggere_le_basi():
    res = asyncio.run(site(ShelfStore()).router(request("/robots.txt")))
    testo = res.body.decode()
    regole = RobotFileParser()
    regole.parse(testo.splitlines())
    assert "Allow: /bases" in testo and regole.can_fetch("*", "/bases")


def test_la_tessera_delle_basi_in_home_ha_la_sua_meta():
    text = pages.community_page(L, {})
    assert '<a class="tile go" href="/bases"' in text
    assert esc(L.t("web.home.tile.bases")) in text and esc(L.t("web.home.tile.bases_body")) in text
    assert 'href="/bases"' not in page(site(ShelfStore()), "/")


def test_la_pagina_legge_il_municipio_e_il_tipo_dalla_richiesta():
    assert public.wanted({}) == (None, None)
    assert public.wanted({"th": ["16"], "kind": ["War"]}) == (16, "war")
    assert public.wanted({"th": ["pinco"]}) == (None, None)
    assert public.wanted({"th": ["99"]})[0] == public.TH_MAX
    assert public.wanted({"th": ["0"]}) == (None, None)


class NewsStore(FakeStore):
    def __init__(self, rows=None):
        super().__init__()
        self.kv[news_feed.ROWS_KEY] = rows
        self.reads = 0

    async def kv_get(self, key):
        if key == news_feed.ROWS_KEY:
            self.reads += 1
        return self.kv.get(key)


def moment(day=23, hour=12):
    return datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc)


NOW = moment()
FINE_PASS = moment(29, 5)
INIZIO_CWL = moment(25, 8)
FINE_GIOCHI = moment(28, 8)
NOTIZIE = [
    {"kind": news_feed.GOLDPASS, "start": int(moment(1, 8).timestamp()),
     "end": int(FINE_PASS.timestamp())},
    {"kind": news_feed.EVENT, "key": "games", "state": "ongoing",
     "start": int(moment(22, 8).timestamp()), "end": int(FINE_GIOCHI.timestamp())},
    {"kind": news_feed.EVENT, "key": "cwl", "state": "upcoming",
     "start": int(INIZIO_CWL.timestamp()), "end": int(moment(27, 8).timestamp())},
    {"kind": news_feed.VIDEO, "id": CLIP, "title": "Aggiornamento di ottobre",
     "published": "2026-09-22T10:00:00Z"},
]


def test_ogni_notizia_e_una_tessera_col_conto_alla_rovescia():
    text = public.news_page(L, NOTIZIE, NOW)
    same_dress(text)
    assert "[web." not in text and "[agenda." not in text
    assert text.count('class="tile"') == 4
    assert esc(L.t(public.PASS)) in text and esc(L.when(FINE_PASS)) in text
    assert esc(L.delta(FINE_PASS, NOW)) in text
    assert esc(L.t("agenda.item.games")) in text and esc(L.t("web.page.ongoing")) in text
    assert esc(L.delta(FINE_GIOCHI, NOW)) in text
    assert esc(L.t("agenda.item.cwl")) in text and esc(L.t("web.page.upcoming")) in text
    assert esc(L.delta(INIZIO_CWL, NOW)) in text
    assert base_videos.THUMB + CLIP + base_videos.THUMB_SIZE in text
    assert base_videos.WATCH + CLIP in text
    assert "<ul" not in text and "<ol" not in text


def test_una_riga_storta_non_porta_giu_la_pagina():
    storte = [{"kind": news_feed.GOLDPASS, "end": "domani"},
              {"kind": news_feed.EVENT, "key": "cwl", "state": "boh", "start": None},
              {"kind": news_feed.VIDEO, "title": "senza id"}, "non un dizionario"]
    text = public.news_page(L, storte, NOW)
    assert text.count(esc(L.t(public.EMPTY))) == 2
    assert "[web." not in text


def test_senza_notizie_la_pagina_mostra_una_tessera_vuota_illustrata():
    res = answer(site(NewsStore()), "/news")
    text = res.body.decode()
    same_dress(text)
    assert text.count(esc(L.t(public.EMPTY))) == 2
    assert text.count('class="tile"') == 2 and text.count("<svg") == 2


def test_le_notizie_hanno_la_csp_delle_anteprime_e_restano_in_cache():
    res = answer(site(NewsStore(NOTIZIE)), "/news")
    csp = res.headers["Content-Security-Policy"]
    assert base_videos.THUMB_HOST in csp and "frame-ancestors 'none'" in csp
    assert res.headers["Cache-Control"] == web_app.PAGE_HEAD


def test_la_seconda_richiesta_delle_notizie_non_rilegge_il_database():
    store = NewsStore(NOTIZIE)
    clock = Clock()
    place = site(store, clock)
    answer(place, "/news")
    answer(place, "/news")
    assert store.reads == 1
    clock.at += web_app.PAGE_CACHE
    answer(place, "/news")
    assert store.reads == 2


def test_i_motori_possono_leggere_le_notizie():
    res = asyncio.run(site(NewsStore()).router(request("/robots.txt")))
    testo = res.body.decode()
    regole = RobotFileParser()
    regole.parse(testo.splitlines())
    assert "Allow: /news" in testo and regole.can_fetch("*", "/news")


def test_la_tessera_delle_notizie_in_home_ha_la_sua_meta():
    text = pages.community_page(L, {})
    assert '<a class="tile go" href="/news"' in text
    assert esc(L.t("web.home.tile.news")) in text and esc(L.t("web.home.tile.news_body")) in text
    assert 'href="/news"' not in page(site(NewsStore()), "/")


def test_la_fine_stagione_non_si_ripete_sotto_al_pass_oro():
    fine = {"kind": news_feed.EVENT, "key": "season", "state": "upcoming",
            "start": int(FINE_PASS.timestamp()), "end": int(FINE_PASS.timestamp())}
    with_pass = public.news_page(L, NOTIZIE + [fine], NOW)
    assert esc(L.t("agenda.item.season")) not in with_pass
    assert with_pass.count('class="tile"') == 4
    senza_pass = public.news_page(L, NOTIZIE[1:] + [fine], NOW)
    assert esc(L.t("agenda.item.season")) in senza_pass
