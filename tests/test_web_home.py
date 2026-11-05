import asyncio
import re
from pathlib import Path

from clashbot import __main__ as cli
from clashbot import console, handlers, i18n, render
from clashbot.i18n import LANGUAGES
from clashbot.retention import INACTIVE_CLAN_DAYS, WAR_HISTORY_KEEP
from clashbot.util import esc
from clashbot.web import app as web_app, art, pages, static, style
from test_console import FakeStore as ConsoleStore, context as console_context, last, private
from test_handlers import AccountStore, chat_update, worker_context
from test_web_status import ITALIAN, FakeStore, serve

L = i18n.locale("en")
IT = i18n.locale("it")
CONSOLE = "ClanBoardBot"
SOURCE = "https://example.org/clanboard"
SUPPORT = "https://example.org/dona"
CHANNEL = "https://t.me/clanboard"
CREATOR = "cyfren"
CHECKLIST = f"{SOURCE}/blob/main/docs/sicurezza.md"
SECURITY = "/.well-known/security.txt"
SECURITY_PAGE = "/security"
BASES = "/bases"
NEWS = "/news"
ART_JS = Path(__file__).resolve().parents[1] / "clashbot" / "web" / "static" / "app" / "art.js"
VOCE = re.compile(r"\n  (\w+): \(\) => mark\(html`(.*?)`\),", re.S)
TRATTO = re.compile(r'd="([^"]+)"')
FORMA = re.compile(r"<(circle|rect|path)\b")


def segni(corpo):
    return (tuple(TRATTO.findall(corpo)), tuple(FORMA.findall(corpo)))


def disegni_js():
    blocco = ART_JS.read_text(encoding="utf-8").split("const ICON = {", 1)[1].split("\n};", 1)[0]
    return {nome: segni(corpo) for nome, corpo in VOCE.findall(blocco)}


def disegni_py():
    return {nome: segni(corpo) for nome, corpo in art.ICON.items()}


def site(console=CONSOLE, **secrets):
    store = FakeStore(secrets=secrets)
    if console:
        store.notes["login"] = {"bot": console, "url": None}
    return web_app.Site(store)


def page(path="/", place=None, lang=ITALIAN):
    res = serve(place or site(), path, headers=lang)
    assert res.status == 200, path
    return res.body.decode()


def test_la_home_crea_il_bot_del_clan_in_un_tocco():
    text = page()
    assert f'href="https://t.me/{CONSOLE}?start=newbot"' in text
    assert esc(L.t("web.home.newbot")) in text
    assert esc(L.t("web.home.tagline")) in text
    muta = page(place=site(console=None))
    assert "start=newbot" not in muta and "t.me" not in muta


def test_la_home_ha_una_tessera_per_sezione():
    text = page()
    assert [href for _, _, _, href in pages.SECTIONS] == [
        "/create", "/community", pages.LIVE, SECURITY_PAGE, "/status"]
    assert text.count('<div class="sections">') == 1
    griglia = text.split('<div class="sections">')[1].split("</div>")[0]
    senza_esempio = [row for row in pages.SECTIONS if row[3] != pages.LIVE]
    assert griglia.count('<a class="tile go') == len(senza_esempio) == 4
    assert griglia.count('class="ico"') == 4
    for _, name, line, href in senza_esempio:
        assert f'href="{href}"' in griglia, href
        assert esc(L.t(name)) in griglia, name
        assert esc(L.t(line)) in griglia, line
    assert griglia.count('<a class="tile go lead" href="/create"') == 1
    assert griglia.index('href="/create"') < griglia.index('href="/community"')
    assert 'class="tile"' not in text and 'class="grid three"' not in text


def test_la_home_non_ha_piu_liste_ne_il_fissato_di_esempio():
    text = page()
    assert "<ul" not in text and "<ol" not in text
    assert 'class="msg"' not in text and 'class="steps"' not in text
    assert 'class="cols"' not in text and 'class="checks"' not in text
    for sparito in ("board_html", "sample_board", "SAMPLE_CLAN", "STEPS", "COLUMNS", "SAFETY"):
        assert not hasattr(pages, sparito), sparito


def test_la_home_dice_cos_e_in_due_righe_e_come_si_parte():
    text = page()
    assert len(pages.WHAT) == 2 and text.count('<p class="pair">') == 2
    for name, line in pages.WHAT:
        assert f"<strong>{esc(L.t(name))}</strong>" in text, name
        assert esc(L.t(line)) in text, line
    assert esc(L.t("web.home.start")) in text
    assert not hasattr(pages, "TILES") and not hasattr(pages, "function_grid")
    assert not hasattr(pages, "NAV")


def test_crea_il_tuo_bot_mette_i_quattro_passi_in_fila_e_dice_chi_puo():
    text = page("/create")
    assert f"<h1>{esc(L.t('web.create.title'))}</h1>" in text
    assert esc(L.t("web.create.who")) in text
    assert len(pages.CREATE_STEPS) == 4 and text.count('<div class="tile step">') == 4
    posti = []
    for numero, (name, line) in enumerate(pages.CREATE_STEPS, start=1):
        assert f'<span class="big">{numero}</span><span>{esc(L.t(name))}</span>' in text, name
        assert esc(L.t(line)) in text, line
        posti.append(text.index(esc(L.t(name))))
    assert posti == sorted(posti)
    assert [name for name, _ in pages.CREATE_STEPS] == [
        "web.create.open", "web.create.clan", "web.create.village", "web.create.terms"]
    assert f'<a class="btn" href="https://t.me/{CONSOLE}?start=newbot">' in text
    assert 'href="/terms"' in text and "<ol" not in text and "<script" not in text


def test_crea_il_tuo_bot_senza_il_bot_clanboard_non_inventa_un_link():
    muta = page("/create", site(console=None))
    assert "t.me" not in muta and 'class="btn"' not in muta
    assert muta.count('<div class="tile step">') == 4


def test_le_icone_del_sito_sono_quelle_dell_app():
    dalla_app, dal_sito = disegni_js(), disegni_py()
    assert set(dalla_app) == set(dal_sito) == set(art.ICON)
    for nome, tratti in dalla_app.items():
        assert tratti == dal_sito[nome], nome
    for nome in ("wars", "members", "bases", "platform", "recruitment", "linked"):
        assert nome in art.ICON, nome
    assert art.icon("boh") == art.icon("empty")
    assert art.icon("wars").startswith('<svg class="ico"')


def test_il_piede_porta_alla_lista_di_controllo_e_ai_ringraziamenti():
    text = page(place=site(source_url=SOURCE))
    assert esc(L.t("web.home.security")) in text
    assert f'href="{SECURITY}"' in text
    assert f'href="{CHECKLIST}"' in text and esc(L.t("web.home.checklist")) in text
    assert f'href="{SOURCE}/blob/main/docs/ringraziamenti.md"' in text
    senza = page()
    assert "sicurezza.md" not in senza and "ringraziamenti" not in senza
    assert esc(L.t("web.home.security")) in senza


def test_la_home_porta_alla_rete_allo_stato_e_alle_pagine_legali():
    text = page()
    for path, key in (("/community", "web.community.title"), ("/status", "web.status.title"),
                      ("/privacy", "web.privacy.title"), ("/terms", "web.terms.title")):
        assert f'href="{path}"' in text and esc(L.t(key)) in text, path
    assert esc(L.t("web.home.network_body")) in text
    assert esc(L.t("web.home.languages", n=len(LANGUAGES))) in text
    assert esc(L.t("web.home.unofficial")) in text
    assert esc(L.t("web.legal.fanpolicy")) in text


def test_il_sostegno_mostra_solo_quello_che_il_gestore_ha_impostato():
    text = page(place=site(support_url=SUPPORT, creator_code=CREATOR))
    assert esc(L.t("web.home.support")) in text
    assert f'href="{SUPPORT}"' in text and esc(L.t("web.home.donate")) in text
    assert esc(L.t("web.home.creator", code=CREATOR)) in text
    assert esc(L.t("web.home.stars")) in text
    assert esc(L.t("web.home.credits", name=CREATOR)) in text
    nudo = page()
    assert esc(L.t("web.home.support")) in nudo and esc(L.t("web.home.stars")) in nudo
    assert esc(L.t("web.home.donate")) not in nudo
    assert CREATOR not in nudo and SUPPORT not in nudo


def test_la_community_ufficiale_e_un_segreto_telegram_in_chiaro():
    assert "channel_url" in cli.SECRET_KINDS and "channel_url" in cli.PLAIN_KINDS
    assert "channel_url" in cli.CLEARABLE_KINDS and "channel_url" not in cli.TOKEN_KINDS
    assert cli.valid_channel_url(CHANNEL) and cli.valid_channel_url("https://t.me/c/12/3")
    for brutto in ("https://example.org/canale", "http://t.me/x", "t.me/x", "", None):
        assert not cli.valid_channel_url(brutto), brutto
    for path in ("/", "/create", "/privacy", "/terms"):
        text = page(path, site(channel_url=CHANNEL))
        assert CHANNEL not in text and esc(L.t("web.home.community")) not in text, path


def test_il_support_dei_bot_nomina_la_community_solo_quando_c_e():
    riga = IT.t("support.community", url=CHANNEL)
    assert riga in render.support_card(IT, None, None, None, None, CHANNEL)
    assert riga not in render.support_card(IT, None, None)
    update = chat_update()
    asyncio.run(handlers.cmd_support(update, worker_context(AccountStore(
        secrets={"channel_url": CHANNEL}))))
    assert riga in update.effective_message.sent[-1][0]
    dal_console = private()
    asyncio.run(console.cmd_support(dal_console, console_context(ConsoleStore(
        secrets={"channel_url": CHANNEL}))))
    assert riga in last(dal_console)


def test_privacy_e_termini_dicono_le_cose_difficili_in_chiaro():
    place = site(source_url=SOURCE)
    for path in ("/privacy", "/terms"):
        res = serve(place, path, headers=ITALIAN)
        assert res.status == 200 and res.headers["Cache-Control"] == "public, max-age=300"
    riservatezza = page("/privacy", place)
    for title, body in pages.PRIVACY:
        assert esc(IT.t(title)) in riservatezza, title
        assert esc(IT.t(body, wars=IT.n(WAR_HISTORY_KEEP),
                        days=IT.n(INACTIVE_CLAN_DAYS))) in riservatezza, body
    assert IT.n(WAR_HISTORY_KEEP) in riservatezza and IT.n(INACTIVE_CLAN_DAYS) in riservatezza
    assert f'href="{SECURITY}"' in riservatezza
    assert esc(IT.t("web.privacy.license")) in riservatezza and f'href="{SOURCE}"' in riservatezza
    assert "AGPL-3.0" in riservatezza
    assert esc(IT.t("web.legal.updated", date=IT.t("web.legal.date"))) in riservatezza
    assert esc(IT.t("web.home.unofficial")) in riservatezza
    assert esc(IT.t("web.legal.fanpolicy")) in riservatezza
    termini = page("/terms", place)
    for title, body in pages.TERMS:
        assert esc(IT.t(title)) in termini, title
        assert esc(IT.t(body)) in termini, body
    assert esc(IT.t("web.terms.license")) in termini and esc(IT.t("web.terms.changes")) in termini
    assert esc(IT.t("web.legal.updated", date=IT.t("web.legal.date"))) in termini


def test_privacy_e_termini_rispondono_in_italiano_e_in_inglese_senza_chiavi_grezze():
    place = site(source_url=SOURCE)
    for code in LANGUAGES:
        parla = IT if code == "it" else L
        for path, key in (("/privacy", "web.privacy.title"), ("/terms", "web.terms.title")):
            testo = page(path, place, lang=f"Accept-Language: {code}\r\n".encode())
            dentro = testo.split("<body>")[1]
            assert esc(parla.t(key)) in dentro, (code, path)
            assert "[web." not in dentro and "{" not in dentro, (code, path)
    tedesco = page("/privacy", place, lang=b"Accept-Language: de\r\n")
    assert esc(L.t("web.privacy.collect.body")) in tedesco
    assert esc(IT.t("web.privacy.collect.body")) not in tedesco


def test_la_home_non_ha_script_e_nessun_indirizzo_di_fuori():
    text = page(place=site(source_url=SOURCE, support_url=SUPPORT, channel_url=CHANNEL,
                           creator_code=CREATOR))
    assert "<script" not in text and "javascript:" not in text and "src=" not in text
    for url in sorted(set(re.findall(r'href="([^"]+)"', text))):
        if url.startswith("/"):
            continue
        assert url.startswith("https://t.me/") or url.startswith(SOURCE) or url == SUPPORT, url


def test_la_home_si_presenta_da_sola_quando_qualcuno_la_condivide():
    text = page()
    assert f'<meta name="description" content="{esc(L.t("web.home.tagline"))}">' in text
    assert '<meta property="og:title" content="ClanBoard">' in text
    assert f'<meta property="og:description" content="{esc(L.t("web.home.tagline"))}">' in text
    assert '<html lang="en">' in text and "<title>ClanBoard</title>" in text


def test_il_foglio_di_stile_sta_in_un_posto_solo_e_dipinge_i_due_temi():
    text = page()
    marchio = static.manifest()["hash"]
    assert text.count("<style>") == 1 and text.count("<link") == len(pages.SHEETS)
    for foglio in pages.SHEETS:
        assert f'<link rel="stylesheet" href="/static/{marchio}/{foglio}">' in text, foglio
    assert style.CSS in text
    assert not hasattr(pages, "STYLE")
    for colore in ("#fbfbf9", "#1c1c1a", "#1f5fbf"):
        assert colore in style.CSS
    assert "prefers-color-scheme" in style.CSS and "system-ui" not in style.CSS
    for nome in ("--bg", "--text", "--hint", "--link", "--button", "--button-text", "--bg2",
                 "--card"):
        assert f"{nome}:" in style.CSS, nome
    for vecchio in ("--ink", "--dim", "--on-accent"):
        assert vecchio not in style.CSS, vecchio
    sito = (static.ROOT / "site.css").read_text(encoding="utf-8")
    base = (static.ROOT / "base.css").read_text(encoding="utf-8")
    assert "system-ui" in base and "--line:" in base
    assert "64rem" in sito and "var(--measure)" in sito and "700px" in sito
    for classe in (".tile{", ".grid{", ".big{", ".ico{", ".sections{", ".tile.go{",
                   ".tile.lead{", ".tile.step{", ".pair{", ".mark{", "nav.sub{"):
        assert classe in sito, classe
    for morta in (".pin{", ".msg{", ".steps{", ".cols{", ".checks{"):
        assert morta not in sito, morta


def test_la_home_apre_col_titolo_a_sinistra_e_la_card_del_match_a_destra():
    text = page()
    assert text.count('class="split"') == 1
    aperto = text.index('class="split"')
    titolo = text.index("<h1>ClanBoard</h1>")
    carta = text.index('class="card hero match stripe"')
    assert aperto < titolo < carta < text.index('class="sections"')


def test_la_card_del_match_e_viva_senza_javascript():
    text = page()
    assert 'class="chip live"' in text and text.count('class="clock"') == 1
    assert text.count('class="score"') == 2 and text.count('class="tick"') == 2
    assert text.count("<b>") == pages.TENS + pages.UNITS
    for label, score in pages.MATCH:
        assert label in text and f">{score}</span>" in text, label
    assert "<script" not in text and "src=" not in text


def test_il_foglio_del_sito_porta_l_eroe_la_barra_e_il_movimento_spento():
    foglio = (static.ROOT / "site.css").read_text(encoding="utf-8")
    for classe in (".split{", ".card.hero{", ".card.stripe::before{", ".clock{", ".tick{",
                   ".badge{", ".bar{", ".bar-fill{", ".facts{", ".chip.live{", ".score{"):
        assert classe in foglio, classe
    assert "@keyframes tens" in foglio and "@keyframes units" in foglio
    assert "prefers-reduced-motion" in foglio and "animation:none" in foglio
    assert f"--tick-minute:{pages.FRESH_EVERY}s" in foglio
