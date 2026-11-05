import asyncio
import importlib
import re

from clashbot import boards, i18n
from clashbot.util import esc
from clashbot.web import (app as web_app, board as web_board, http, miniapp, pages, payload,
                          static, style)
from test_web_publish import built as published
from test_web_status import FakeStore, request, same_dress

L = i18n.locale("en")
IT = i18n.locale("it")
SLUG = "abcdef0123456789"
CONSOLE = "ClanBoardBot"
BASE = "https://clanboard.example"
CLAN_BOT = "ClanUnoBot"
CODE = "ab12cd"
BADGE = "https://api-assets.clashofclans.com/badges/200/uno.png"


def conf():
    return importlib.import_module("clashbot.site_conf")


def built(conf_web=None, **kw):
    return published(dict({"page": True}, **(conf_web or {})), **kw)


class PageStore(FakeStore):
    def __init__(self, pages=None, secrets=None, console=None):
        super().__init__(secrets=secrets)
        self.pages = dict(pages or {})
        if console:
            self.notes["login"] = {"bot": console, "url": None}

    async def web_page(self, slug, kind):
        return self.pages.get((slug, kind))


def serve(store, path):
    return asyncio.run(web_app.Site(store).router(request(path)))


def dressed(**kw):
    return PageStore({(CODE, payload.PUBLIC): built({"widget": True})}, **kw)


def test_a_clan_without_a_page_is_a_404():
    assert serve(PageStore(), f"/c/{CODE}").status == 404


def test_la_pagina_spenta_non_esiste_e_accesa_si_fa_indicizzare():
    assert serve(PageStore({(SLUG, payload.APP): published()}), f"/c/{SLUG}").status == 404
    body = built()
    assert "public" not in body
    res = serve(PageStore({(CODE, payload.PUBLIC): body}), f"/c/{CODE}")
    assert res.status == 200 and res.headers["X-Robots-Tag"] == "index"
    assert res.headers["Cache-Control"] == web_app.PAGE_HEAD


def con_candidatura(**kw):
    body = built(kw.pop("conf_web", None), **kw)
    body["clan"]["badge"] = BADGE
    return dict(body, bot=CLAN_BOT, code=CODE, min_th=15,
                record={"wars": 8, "wins": 5}, free=6)


def test_la_pagina_mette_quattro_numeri_grandi_i_requisiti_a_chip_e_il_bottone_candidati():
    text = serve(PageStore({(CODE, payload.PUBLIC): con_candidatura()}), f"/c/{CODE}").body.decode()
    quadro = text.split('<div class="grid four">')[1].split("</div></div>")[0]
    assert quadro.count('<span class="big">') == 4
    for label in ("web.page.lvl", "web.page.members", "web.page.free", "web.page.wins"):
        assert esc(L.t(label)) in quadro, label
    assert "<table>" not in text and "<ul" not in text
    assert f'<span class="chip">{esc(L.t("recruit.req_th", th=15))}</span>' in text
    vinte = L.t("web.page.record", wins=L.n(5), wars=L.n(8))
    assert f'<span class="chip">{esc(vinte)}</span>' in text
    assert f'href="{web_board.deep_link({"bot": CLAN_BOT}, CODE)}"' in text
    assert esc(L.t("web.page.apply")) in text


def test_lo_stemma_viene_dall_api_e_la_regola_dei_contenuti_lo_ammette():
    res = serve(PageStore({(CODE, payload.PUBLIC): con_candidatura()}), f"/c/{CODE}")
    assert f'<img class="crest" src="{BADGE}"' in res.body.decode()
    assert "img-src data: https://api-assets.clashofclans.com;" in \
        res.headers["Content-Security-Policy"]
    senza = serve(PageStore({(CODE, payload.PUBLIC): built()}), f"/c/{CODE}").body.decode()
    assert "<img" not in senza


def test_nessun_nome_ne_tag_di_membri_sulla_pagina_indicizzabile():
    body = built({"members": True, "stats": True})
    assert "members" not in body and "stats" not in body
    body["members"] = [{"name": "Mario", "tag": "#P1", "trophies": 5400, "donations": 1200}]
    body["stats"] = {"points": [{"name": "Luigi", "value": 90}]}
    text = serve(PageStore({(CODE, payload.PUBLIC): body}), f"/c/{CODE}").body.decode()
    for segreto in ("#P1", "Mario", "Luigi", L.t("web.page.trophies"), L.t("web.page.donations")):
        assert segreto not in text, segreto


def test_the_page_shows_the_public_facts_and_hides_the_rest():
    store = PageStore({(CODE, payload.PUBLIC): built()})
    res = serve(store, f"/c/{CODE}")
    assert res.status == 200 and res.kind == http.HTML
    text = res.body.decode()
    assert "Nostro Clan" in text and "Crystal League I" in text
    assert f"<h2>{esc(L.t('web.page.war'))}</h2>" in text
    assert esc(L.t("web.page.record", wins=L.n(0), wars=L.n(0))) in text
    assert "Mario" not in text and L.t("web.page.trophies") not in text
    assert res.headers["X-Robots-Tag"] == "index"
    assert "frame-ancestors 'none'" in res.headers["Content-Security-Policy"]
    assert res.headers["Cache-Control"] == web_app.PAGE_HEAD
    assert L.t("web.home.unofficial") in text
    assert "[web." not in text and "[agenda." not in text


def test_the_calendar_rows_are_named_and_dated_on_the_page():
    text = serve(PageStore({(CODE, payload.PUBLIC): built()}), f"/c/{CODE}").body.decode()
    assert esc(L.t("web.page.events")) in text
    assert L.t("agenda.item.cwl") in text and L.t("agenda.item.season") in text
    assert L.t("web.page.upcoming") in text


def test_la_pagina_del_clan_resta_in_inglese_come_il_resto_del_sito():
    body = dict(built(), lang="it")
    text = serve(PageStore({(CODE, payload.PUBLIC): body}), f"/c/{CODE}").body.decode()
    assert L.t("web.page.war") in text and 'lang="en"' in text
    assert IT.t("web.page.no_war") not in text and 'lang="it"' not in text


def corpo(body, code=CODE, store=None):
    place = store or PageStore({(code, payload.PUBLIC): body})
    return serve(place, f"/c/{code}").body.decode().split("<body>")[1]


def test_la_guerra_in_corso_non_sta_sulla_pagina_restano_solo_i_totali():
    con_guerra = con_candidatura()
    assert con_guerra["war"]["them"]["name"] == "Clan Nemico"
    text = corpo(con_guerra)
    testa = head_of(con_guerra)
    for segreto in ("Clan Nemico", "&#11088;", "\u2b50", L.t("web.page.no_war"),
                    L.t("web.page.war_end", when="")[:5]):
        assert segreto not in text, segreto
        assert segreto not in testa, segreto
    vinte = L.t("web.page.record", wins=L.n(5), wars=L.n(8))
    assert f'<span class="chip">{esc(vinte)}</span>' in text
    senza = corpo(dict(con_candidatura(), war=None))
    assert senza == text
    assert not hasattr(pages, "war_card")


TAG_RE = re.compile(r"#[0289PYLQGRJCUV]{3,}")


def test_l_attaccante_che_legge_la_pagina_non_trova_nomi_tag_rosa_ne_donazioni():
    body = con_candidatura()
    body["war"]["members"] = {"#P9LQ": {"name": "Peach", "pos": 1,
                                        "attacks": [{"stars": 3, "destr": 100.0}]}}
    body["rows"] = [{"pos": 1, "name": "Bowser", "assignee": "Toad", "assignee_tag": "#2YQ8"}]
    body["ours"] = [{"pos": 1, "name": "Yoshi", "tag": "#Y0GRJ", "stars": 3}]
    body["members"] = [{"name": "Mario", "tag": "#PL2Q9", "donations": 1234, "received": 987,
                        "trophies": 5432}]
    body["plan"] = {"note": "piano segreto"}
    text = corpo(body)
    for segreto in ("Peach", "Bowser", "Toad", "Yoshi", "Mario", "#P9LQ", "#2YQ8", "#Y0GRJ",
                    "#PL2Q9", "1234", "987", "5432", "piano segreto", body["clan"]["tag"],
                    L.t("web.page.donations"), L.t("web.page.trophies")):
        assert segreto not in text, segreto
    assert TAG_RE.search(text) is None, TAG_RE.search(text)
    assert body["clan"]["tag"] not in head_of(body)


def test_il_titolare_vede_nome_stemma_livello_lega_membri_posti_requisiti_e_candidati():
    text = corpo(con_candidatura())
    assert "<h1>Nostro Clan</h1>" in text and f'<img class="crest" src="{BADGE}"' in text
    for label in ("web.page.lvl", "web.page.members", "web.page.free"):
        assert esc(L.t(label)) in text, label
    assert "Crystal League I" in text and esc(L.t("recruit.req_th", th=15)) in text
    assert f'<span class="big">{L.n(6)}</span>' in text
    assert f'<a class="btn" href="{web_board.deep_link({"bot": CLAN_BOT}, CODE)}">' in text


def esempio(code=CODE, altre=()):
    store = PageStore({(code, payload.PUBLIC): con_candidatura()})
    for altra in altre:
        store.pages[(altra, payload.PUBLIC)] = con_candidatura()
    store.kv[conf().KEY] = {"example_code": code}
    return store


def test_il_clan_d_esempio_porta_il_segno_scritto_e_gli_altri_no():
    segno = f'<span class="chip mark">{esc(L.t("web.page.example"))}</span>'
    assert segno in corpo(None, store=esempio())
    assert segno not in corpo(con_candidatura())
    altro = esempio(altre=("zz99zz",))
    assert segno not in corpo(None, code="zz99zz", store=altro)
    assert segno in corpo(None, store=altro)


def test_names_are_escaped():
    body = built()
    body["clan"]["name"] = "<script>x</script>"
    text = serve(PageStore({(CODE, payload.PUBLIC): body}), f"/c/{CODE}").body.decode()
    assert "<script>x</script>" not in text and "&lt;script&gt;" in text


def head_of(body):
    text = serve(PageStore({(CODE, payload.PUBLIC): body}), f"/c/{CODE}").body.decode()
    return text.split("</head>")[0]


def test_the_link_preview_is_curated():
    head = head_of(built())
    assert '<meta property="og:title" content="Nostro Clan">' in head
    assert '<meta property="og:type" content="website">' in head
    assert '<meta name="twitter:card" content="summary">' in head
    assert "Crystal League I" in head and L.t("web.page.level", n=12) in head
    assert "Clan Nemico" not in head and "#CLAN1" not in head
    assert L.t("web.page.record", wins=L.n(0), wars=L.n(0)) in head


def test_the_preview_tells_the_truth_when_there_is_no_war():
    head = head_of(dict(built(), war=None))
    assert L.t("web.page.no_war") not in head and "Clan Nemico" not in head
    assert head == head_of(built())


def test_the_preview_speaks_english_like_the_rest_of_the_site():
    head = head_of(dict(built(), lang="it"))
    assert L.t("web.page.level", n=12) in head
    assert IT.t("web.page.level", n=12) not in head


def test_the_preview_escapes_the_clan_name():
    body = built()
    body["clan"]["name"] = 'Nostro "Clan" <b>'
    head = head_of(body)
    assert '<meta property="og:title" content="Nostro &quot;Clan&quot; &lt;b&gt;">' in head
    assert "<b>" not in head


def test_la_pagina_del_clan_porta_lo_stesso_vestito_della_home():
    same_dress(serve(dressed(), f"/c/{CODE}").body.decode())


def test_la_pagina_pubblica_non_porta_mai_la_chiave_dell_app():
    store = dressed(secrets={"site_base": BASE}, console=CONSOLE)
    text = serve(store, f"/c/{CODE}").body.decode()
    assert SLUG not in text and "startapp" not in text
    assert boards.open_url(CONSOLE, SLUG) not in text
    assert L.t("board.all.open") not in text
    assert SLUG not in serve(store, f"/c/{CODE}/widget").body.decode()


def test_il_bottone_della_bacheca_nasce_in_un_posto_solo():
    assert boards.open_url(CONSOLE, SLUG) == f"https://t.me/{CONSOLE}/ClanBoard?startapp={SLUG}"
    markup = boards.open_markup(L, CONSOLE, SLUG)
    assert markup.inline_keyboard[0][0].url == boards.open_url(CONSOLE, SLUG)
    assert boards.open_markup(L, "", SLUG) is None


def test_il_widget_firma_con_la_home_restando_compatto():
    text = serve(dressed(), f"/c/{CODE}/widget").body.decode()
    assert text.count("<style>") == 1 and style.CSS in text
    assert pages.WIDGET_BRAND in text and 'href="/"' in pages.WIDGET_BRAND
    assert pages.TOP_OPEN not in text and "<h1" not in text


def test_nessuno_script_fuori_dalla_mini_app():
    store = dressed(secrets={"site_base": BASE}, console=CONSOLE)
    for path in ("/", "/status", f"/c/{CODE}", f"/c/{CODE}/widget"):
        assert "<script" not in serve(store, path).body.decode(), path
    assert "<script" in miniapp.app_page(L, None, "")


def test_a_clan_page_never_says_it_is_on_the_board():
    body = built()
    assert "listing" not in body["extras"] and "named" not in body["extras"]
    body["extras"]["listing"] = True
    corpo = serve(PageStore({(CODE, payload.PUBLIC): body}),
                  f"/c/{CODE}").body.decode().split("</header>")[1]
    assert "listing" not in corpo and L.t("web.board.title") not in corpo


def test_static_files_are_served_with_a_long_cache_only_under_their_hash():
    found = static.manifest()
    res = serve(PageStore(), f"/static/{found['hash']}/vendor/htm-preact-standalone.module.js")
    assert res.status == 200 and res.kind == http.SCRIPT
    assert res.headers["Cache-Control"] == f"public, max-age={static.STATIC_MAX_AGE}, immutable"
    other = serve(PageStore(), "/static/000000000000/vendor/htm-preact-standalone.module.js")
    assert other.status == 200 and other.headers["Cache-Control"] == web_app.PAGE_HEAD
    assert serve(PageStore(), f"/static/{found['hash']}/vendor/nope.js").status == 404


def test_static_files_answer_inside_the_frame_of_the_mini_app():
    found = static.manifest()
    res = serve(PageStore(), f"/static/{found['hash']}/vendor/htm-preact-standalone.module.js")
    assert res.body == static.read("vendor/htm-preact-standalone.module.js")
    assert "frame-ancestors 'none'" not in res.headers["Content-Security-Policy"]
    assert res.headers["Content-Security-Policy"] == miniapp.CSP


def test_no_path_climbs_out_of_the_static_folder():
    found = static.manifest()
    for name in ("../app.py", "vendor/../../app.py", "vendor/VERSIONS", "package.json"):
        assert serve(PageStore(), f"/static/{found['hash']}/{name}").status == 404, name


def test_the_shell_loads_modules_deferred():
    text = pages.shell("t", "<div></div>", "it", modules=("/static/abc/app/main.js",))
    assert '<script type="module" src="/static/abc/app/main.js" defer></script>' in text
    assert pages.shell("t", "<div></div>", "it").count("<script") == 0
    assert "modulepreload" not in text


def test_the_shell_declares_the_preloaded_modules_before_the_scripts():
    text = pages.shell("t", "<div></div>", "it", scripts=("/x.js",),
                       preload=("/static/abc/app/ui.js",))
    assert '<link rel="modulepreload" href="/static/abc/app/ui.js">' in text
    assert text.index("modulepreload") < text.index("<script")
