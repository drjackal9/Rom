import asyncio
import importlib
import re
from urllib.robotparser import RobotFileParser

from clashbot import base_videos, i18n, news_feed
from clashbot.platform_guard import FLOOD_LIMIT
from clashbot.util import esc, now_utc
from clashbot.web import (app as web_app, ban, board as web_board, pages, payload, public,
                          static, style, wellknown)
from test_locales import SHORT
from test_web_board import row as riga_bacheca
from test_web_page import CODE, SLUG, con_candidatura
from test_web_public import NOTIZIE, row as riga_base, video as clip
from test_web_status import ITALIAN, FakeStore, fresh_note, request, same_dress

L = i18n.locale("it")
EN = i18n.locale("en")
CONSOLE = "ClanBoardBot"
SOURCE = "https://example.org/clanboard"
BASI = "/bases"
NOTIZIE_PATH = "/news"
CLAN = f"/c/{CODE}"
CLASSIFICHE = "/leaderboards"
SICUREZZA = "/security"
CREA = "/create"
COMMUNITY = "/community"
PUBBLICHE = ("/", CREA, COMMUNITY, "/status", "/privacy", "/terms", "/board", BASI,
             NOTIZIE_PATH, CLAN, CLASSIFICHE, SICUREZZA)
SOTTO = ("/board", CLASSIFICHE, BASI, NOTIZIE_PATH)
MENU = ["Home", "Create your bot", "Community", "A clan live", "Security", "Status"]
VIVO = "A clan live"
GRUPPO = "https://t.me/clanboard_gruppo"
CANALE = "https://t.me/gruppo_di_un_clan"
ALTRO = "zz99zz"
VOCE = re.compile(r'<a href="([^"]+)"(?: aria-current="page")?>([^<]+)</a>')
VIVE = ("/status", "/board", CLASSIFICHE)
TEDESCO = b"Accept-Language: de\r\n"
IP = "203.0.113.9"
FAMIGLIE = ("web.home.", "web.bases.", "web.news.", "web.page.", "agenda.item.",
            "web.security.", "web.create.", "web.community.")
CHIUSA = "; frame-ancestors 'none'"


def conf():
    return importlib.import_module("clashbot.site_conf")


class TuttoStore(FakeStore):
    def __init__(self):
        super().__init__(secrets={"source_url": SOURCE})
        self.notes["services"] = fresh_note()
        self.notes["login"] = {"bot": CONSOLE, "url": None}
        self.kv[news_feed.ROWS_KEY] = NOTIZIE
        self.pagine = {(CODE, payload.PUBLIC): con_candidatura()}

    async def web_page(self, slug, kind):
        return self.pagine.get((slug, kind))

    async def recruit_board(self, limit=20, country=None, min_th=None, lang=None):
        return [riga_bacheca()]

    async def public_codes(self):
        return set()

    async def recruit_target(self, code):
        return None

    async def network_board(self, limit=20):
        return []

    async def library_rows(self, hall=None, village=None, kind=None, limit=None):
        return [riga_base()]

    async def videos_rows(self, scope=None, limit=None):
        return [clip()]

    async def site_days(self, limit=30):
        return []

    async def incidents(self, limit=20):
        return []

    async def reports(self, limit=20):
        return []


def sito(store=None):
    return web_app.Site(store or TuttoStore(), lambda: 0.0)


def risposta(place, path):
    res = asyncio.run(place.router(request(path, headers=ITALIAN)))
    assert res.status == 200, path
    return res


def pagina(place, path):
    return risposta(place, path).body.decode()


def fuori_dal_piede(text):
    return text.split("<body>")[1].split("<footer>")[0]


def test_nessuna_pagina_pubblica_ha_liste_fuori_dal_piede():
    place = sito()
    for path in PUBBLICHE:
        text = pagina(place, path)
        same_dress(text)
        for marchio in ("<ul", "<ol", "<li", "<table"):
            assert marchio not in fuori_dal_piede(text), (path, marchio)


def test_lo_stato_e_una_griglia_di_tessere_una_per_servizio():
    text = pagina(sito(), "/status")
    assert text.count('class="grid three"') == 1
    assert text.count('class="tile"') == len(payload.SERVICES)
    for name in payload.SERVICES:
        assert esc(EN.t("web.status." + name)) in text, name
    assert "svc" not in style.CSS


def test_le_anteprime_di_youtube_stanno_solo_nelle_basi_e_nelle_notizie():
    place = sito()
    for path in PUBBLICHE:
        csp = risposta(place, path).headers["Content-Security-Policy"]
        assert (base_videos.THUMB_HOST in csp) is (path in (BASI, NOTIZIE_PATH)), path
        assert csp.endswith(CHIUSA), path
    assert public.CSP_MEDIA.replace(" " + base_videos.THUMB_HOST, "") == pages.CSP_BASE
    for path in (BASI, NOTIZIE_PATH):
        assert risposta(place, path).headers["Content-Security-Policy"] == \
            public.CSP_MEDIA + CHIUSA, path
    for path in ("/", CREA, COMMUNITY, "/status", "/privacy", "/terms", "/board"):
        assert risposta(place, path).headers["Content-Security-Policy"] == \
            pages.CSP_BASE + CHIUSA, path
    assert risposta(place, CLAN).headers["Content-Security-Policy"] == pages.CSP_CLAN + CHIUSA


def test_ogni_riga_del_robots_parla_di_una_rotta_che_esiste():
    rotte = [path for _, path, _ in web_app.ROUTES]
    righe = [riga for riga in wellknown.ROBOTS.splitlines() if not riga.startswith("User-agent")]
    assert righe
    for riga in righe:
        percorso = riga.split(":", 1)[1].strip().rstrip("$")
        assert any(path.startswith(percorso) for path in rotte), riga


def test_i_motori_entrano_nelle_pagine_nuove_e_restano_fuori_dalle_altre():
    regole = RobotFileParser()
    regole.parse(risposta(sito(), "/robots.txt").body.decode().splitlines())
    for path in ("/", CREA, COMMUNITY, "/status", CLAN, BASI, NOTIZIE_PATH):
        assert regole.can_fetch("*", path), path
    for path in ("/app/" + SLUG, "/r/ab12cd", "/board"):
        assert not regole.can_fetch("*", path), path


def test_le_pagine_nuove_non_sono_sonde_e_chi_le_ripete_non_e_bandito():
    for _, path, _ in web_app.ROUTES:
        assert not path.lower().startswith(ban.PROBES), path
    store = TuttoStore()
    place = sito(store)
    for path in (BASI, NOTIZIE_PATH):
        for _ in range(FLOOD_LIMIT + 1):
            assert risposta(place, path).status == 200
    assert not [key for key in store.kv if key.startswith((ban.PREFIX, ban.MISS))]


def test_le_parole_delle_pagine_nuove_passano_dalla_regola_corta():
    for famiglia in FAMIGLIE:
        assert famiglia in SHORT, famiglia


def barra(text):
    return text.split("<body>")[1].split("</header>")[0]


def voci(text):
    return [(label, href) for href, label in VOCE.findall(barra(text).split("<nav>")[1])]


def con(store=None, **scelte):
    store = store or TuttoStore()
    store.kv[conf().KEY] = dict(scelte)
    return sito(store)


def test_ogni_pagina_pubblica_porta_il_menu_delle_sezioni_in_ordine():
    assert [label for label, _ in pages.MENU] == MENU
    assert [href for _, href in pages.MENU] == ["/", CREA, COMMUNITY, pages.LIVE, SICUREZZA,
                                                "/status"]
    place = sito()
    senza = [(label, href) for label, href in pages.MENU if label != VIVO]
    for path in PUBBLICHE:
        text = pagina(place, path)
        assert barra(text).count("<nav>") == 1, path
        assert voci(text) == senza, path


def test_ogni_sezione_risponde_e_sta_nel_menu():
    place = con(example_code=CODE)
    casa = pagina(place, "/")
    attese = [(label, CLAN if label == VIVO else href) for label, href in pages.MENU]
    assert voci(casa) == attese and len(attese) == 6
    for label, href in attese:
        assert risposta(place, href).status == 200, label
        assert voci(pagina(place, href)) == attese, label


def test_senza_example_code_la_sezione_un_clan_dal_vivo_non_esiste():
    place = sito()
    segno = 'class="chip mark"'
    for path in PUBBLICHE:
        text = pagina(place, path)
        assert VIVO not in text and segno not in text, path
    assert f'href="{CLAN}"' not in pagina(place, "/")
    vuoto = con(example_code="")
    assert VIVO not in pagina(vuoto, "/")


def test_con_example_code_il_menu_e_la_home_portano_al_clan_col_segno_example():
    place = con(example_code=CODE)
    for path in PUBBLICHE:
        assert (VIVO, CLAN) in voci(pagina(place, path)), path
    casa = pagina(place, "/")
    assert f'<a class="tile go" href="{CLAN}"' in casa
    assert esc(EN.t("web.home.live")) in casa and esc(EN.t("web.home.live_body")) in casa
    clan = pagina(place, CLAN)
    assert f'<span class="chip mark">{esc(EN.t("web.page.example"))}</span>' in clan
    assert f'<a href="{CLAN}" aria-current="page">{VIVO}</a>' in barra(clan)


def test_un_example_code_che_non_ha_una_pagina_non_apre_la_sezione():
    for brutto in (ALTRO, "../etc", "<b>", "a" * 40, 7, None, ["x"]):
        place = con(example_code=brutto)
        for path in ("/", COMMUNITY, CLAN):
            text = pagina(place, path)
            assert VIVO not in text and 'class="chip mark"' not in text, (brutto, path)


def test_il_clan_d_esempio_si_legge_dall_impostazione_e_mai_da_un_nome():
    radice = static.ROOT.parent
    for nome in ("pages.py", "public.py", "app.py", "board.py"):
        sorgente = (radice / nome).read_text(encoding="utf-8").casefold()
        assert "futuro" not in sorgente, nome
    assert "futuro" not in (static.ROOT / "site.css").read_text(encoding="utf-8").casefold()
    store = TuttoStore()
    store.pagine[(ALTRO, payload.PUBLIC)] = con_candidatura()
    place = con(store, example_code=ALTRO)
    assert (VIVO, f"/c/{ALTRO}") in voci(pagina(place, "/"))
    assert 'class="chip mark"' not in pagina(place, CLAN)
    assert 'class="chip mark"' in pagina(place, f"/c/{ALTRO}")


def test_senza_community_url_la_riga_del_gruppo_non_esiste():
    for place in (sito(), con(community_url="")):
        text = pagina(place, COMMUNITY)
        assert esc(EN.t("web.home.community")) not in text
        assert "t.me" not in text


def test_con_community_url_la_community_porta_al_gruppo():
    place = con(community_url=GRUPPO)
    text = pagina(place, COMMUNITY)
    assert f'<a class="tile go" href="{GRUPPO}" rel="noopener">' in text
    assert esc(EN.t("web.home.community")) in text
    for path in PUBBLICHE:
        if path != COMMUNITY:
            assert GRUPPO not in pagina(place, path), path


def test_un_community_url_che_non_e_di_telegram_non_arriva_in_pagina():
    for brutto in ("https://example.org/gruppo", "http://t.me/x", "javascript:alert(1)",
                   '"><script>x</script>', 7, None, ["https://t.me/x"]):
        text = pagina(con(community_url=brutto), COMMUNITY)
        assert esc(EN.t("web.home.community")) not in text, brutto
        assert "example.org/gruppo" not in text and "<script" not in text, brutto


def test_un_community_url_che_il_browser_legge_altrove_non_arriva_in_pagina():
    for brutto in ("https://evil.example\\@t.me/x", "https://user:pw@t.me/x",
                   "https://t.me:8443/x", "https://t.me/x‮", "https://t.me/"):
        text = pagina(con(community_url=brutto), COMMUNITY)
        assert esc(EN.t("web.home.community")) not in text, repr(brutto)
        assert "evil.example" not in text and "8443" not in text, repr(brutto)
    for buono in (GRUPPO, "https://t.me/+AbCdEf", "https://t.me/c/12/3"):
        assert f'href="{buono}"' in pagina(con(community_url=buono), COMMUNITY), buono


def test_channel_url_non_compare_in_nessuna_pagina_del_sito():
    store = TuttoStore()
    store.secrets["channel_url"] = CANALE
    place = con(store, example_code=CODE, community_url=GRUPPO)
    for path in PUBBLICHE:
        text = pagina(place, path)
        assert CANALE not in text and "gruppo_di_un_clan" not in text, path
    radice = static.ROOT.parent
    for nome in ("pages.py", "public.py", "board.py", "security.py"):
        assert "channel_url" not in (radice / nome).read_text(encoding="utf-8"), nome


def test_la_community_mette_insieme_bacheca_classifiche_basi_notizie_e_registro_d_onore():
    text = pagina(sito(), COMMUNITY)
    same_dress(text)
    assert f"<h1>{esc(EN.t('web.community.title'))}</h1>" in text
    for href in SOTTO:
        assert f'href="{href}"' in text, href
    assert esc(EN.t("web.board.title")) in text and public.RANK_TITLE in text
    assert esc(EN.t("web.board.filter_th")) in text and 'href="/board?th=17"' in text
    assert f'<a class="tile" href="/r/{CODE}">' in text
    for key in ("web.home.tile.bases", "web.home.tile.news", "web.community.fame",
                "web.home.thanks"):
        assert esc(EN.t(key)) in text, key
    assert f'<a class="tile go" href="{SOURCE}/blob/main/docs/ringraziamenti.md"' in text
    assert "[web." not in text


def test_la_community_mostra_i_primi_della_bacheca_e_della_classifica_e_porta_al_resto():
    store = TuttoStore()
    letti = []

    async def bacheca(limit=20, country=None, min_th=None, lang=None):
        letti.append((limit, country, min_th, lang))
        return [riga_bacheca(code=f"c{n}") for n in range(7)]

    store.recruit_board = bacheca
    text = pagina(sito(store), COMMUNITY + "?th=15&lang=it")
    assert text.count('<a class="tile" href="/r/') == pages.ROW
    assert letti == [(web_board.PAGE_SIZE, None, None, None)]
    assert text.count(esc(EN.t("web.community.more"))) == 2


def test_il_registro_d_onore_senza_sorgente_porta_alla_pagina_della_sicurezza():
    store = TuttoStore()
    store.secrets.pop("source_url")
    text = pagina(sito(store), COMMUNITY)
    assert "ringraziamenti" not in text
    assert f'<a class="tile go" href="{SICUREZZA}"' in text
    assert esc(EN.t("web.community.fame")) in text


def test_le_pagine_della_community_tengono_accesa_la_voce_community():
    place = sito()
    for path in (COMMUNITY,) + SOTTO:
        text = pagina(place, path)
        assert f'<a href="{COMMUNITY}" aria-current="page">Community</a>' in barra(text), path
        assert text.count('<nav class="sub"') == 1, path
        sotto = text.split('<nav class="sub"')[1].split("</nav>")[0]
        assert [href for href, _ in VOCE.findall(sotto)] == list(SOTTO), path
        assert (f'<a href="{path}" aria-current="page">' in sotto) is (path != COMMUNITY), path
    for path in ("/", CREA, "/status", SICUREZZA, CLAN, "/privacy"):
        assert '<nav class="sub"' not in pagina(place, path), path


def test_privacy_e_termini_stanno_nel_piede_di_ogni_pagina():
    place = sito()
    for path in PUBBLICHE:
        piede = pagina(place, path).split("<footer>")[1]
        assert piede.count('href="/privacy"') == 1 and piede.count('href="/terms"') == 1, path


def test_nessuno_stato_si_legge_dal_solo_colore():
    foglio = (static.ROOT / "site.css").read_text(encoding="utf-8")
    assert ".dot.degraded{border-radius:0;transform:rotate(45deg)}" in foglio
    assert ".dot.down{border-radius:0}" in foglio
    corrente = foglio.split("nav a[aria-current]{")[1].split("}")[0]
    assert "font-weight:var(--weight-strong)" in corrente and "border-bottom:" in corrente
    assert ".mark{" in foglio and "font-weight:var(--weight-strong)" in \
        foglio.split(".mark{")[1].split("}")[0]
    stato = pagina(sito(), "/status")
    assert stato.count('<span class="dot ') == len(payload.SERVICES)
    for pezzo in stato.split('<span class="dot ')[1:]:
        nome = pezzo.split('"')[0]
        assert f'<span class="muted">{esc(EN.t("web.status." + nome))}</span>' in \
            pezzo.split("</div>")[0], nome
    place = con(example_code=CODE)
    clan = pagina(place, CLAN)
    assert f'class="chip mark">{esc(EN.t("web.page.example"))}<' in clan
    accesa = foglio.split(".chip.on{")[1].split("}")[0]
    assert "font-weight:var(--weight-strong)" in accesa
    assert ".chip.on::before{content:'\\2713\\00a0'}" in foglio
    assert '<a class="chip on" href="/board?th=15">' in pagina(place, "/board?th=15")


def test_la_verifica_di_casa_guarda_anche_le_sezioni_nuove():
    for path in (CREA, COMMUNITY):
        assert path in web_app.AUDIT_PATHS, path
    assert "channel_url" not in pages.__dict__ and not hasattr(pages, "NAV")


def test_il_sito_resta_in_inglese_anche_per_un_browser_italiano():
    place = sito()
    for path in PUBBLICHE:
        if path in ("/privacy", "/terms"):
            continue
        text = pagina(place, path)
        assert '<html lang="en">' in text, path
    casa = pagina(place, "/")
    assert esc(EN.t("web.home.tagline")) in casa
    assert esc(L.t("web.home.tagline")) not in casa


def test_privacy_e_termini_restano_in_italiano_e_inglese():
    place = sito()
    for path in ("/privacy", "/terms"):
        nostro = pagina(place, path)
        assert '<html lang="it">' in nostro, path
        fuori = asyncio.run(place.router(request(path, headers=TEDESCO))).body.decode()
        assert '<html lang="en">' in fuori, path
        assert esc(EN.t("web.legal.fanpolicy")) in fuori, path


def test_solo_le_pagine_vive_si_ricaricano_da_sole():
    place = sito()
    marchio = f'<meta http-equiv="refresh" content="{pages.FRESH_EVERY}">'
    for path in PUBBLICHE:
        assert (marchio in pagina(place, path)) is (path in VIVE), path


def test_ogni_pagina_pubblica_risponde_con_etag_e_304():
    place = sito()
    for path in PUBBLICHE:
        res = risposta(place, path)
        marchio = res.headers["ETag"]
        assert marchio.startswith('"') and marchio.endswith('"'), path
        chiede = ITALIAN + f"If-None-Match: {marchio}\r\n".encode()
        ferma = asyncio.run(place.router(request(path, headers=chiede)))
        assert ferma.status == 304 and ferma.body == b"", path
        assert ferma.headers["ETag"] == marchio, path


def test_nessun_puntino_separa_le_parole_nel_corpo_del_sito():
    place = sito()
    corpi = [pagina(place, path) for path in PUBBLICHE]
    corpi.append(pages.widget_page(EN, con_candidatura(), now_utc()))
    corpi.append(pages.warning_page(EN, IP, 1))
    for text in corpi:
        corpo = text.split("<body>")[1]
        assert "\u00b7" not in corpo and "&middot;" not in corpo, corpo[:80]


def test_la_sonda_delle_sezioni_porta_il_gruppo_e_l_esempio():
    from tests.sonde import guarda_sezioni as sonda

    class Base:
        MISURE = ((390, 844), (1280, 800))

        @staticmethod
        def campione(radice):
            assert radice == sonda.RADICE
            return TuttoStore(), list(PUBBLICHE)

    store, pagine = sonda.campione(Base, CODE)
    assert pagine == list(PUBBLICHE) and sonda.FUORI.startswith("document.")
    place = sito(store)
    assert (VIVO, CLAN) in voci(pagina(place, "/"))
    assert f'href="{sonda.GRUPPO}"' in pagina(place, COMMUNITY)
