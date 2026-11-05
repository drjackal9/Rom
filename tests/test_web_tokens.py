import hashlib
import re
from pathlib import Path

from clashbot import i18n
from clashbot.base_videos import THUMB_HOST
from clashbot.media import BADGE_HOST
from clashbot.web import miniapp, pages, public, static, style

L = i18n.locale("it")
RADICE = static.ROOT
FONTI = RADICE / "fonts"
VERSIONI = RADICE / "vendor" / "VERSIONS"
BASE = "base.css"
SITO = "site.css"
APP = "app/app.css"
SCURO = "@media (prefers-color-scheme:dark)"
RADICE_RE = re.compile(r":root\s*\{([^}]*)\}")
VAR_RE = re.compile(r"^var\((--[a-z0-9-]+)\)$")
URL_RE = re.compile(r"url\(([^)]+)\)")
FACCIA_RE = re.compile(r"@font-face\s*\{([^}]*)\}")
SELETTORE_RE = re.compile(r"([^{}]+)\{")
REGOLA_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
BLOCCHI_MAX = 16
SALTI_MAX = 4
SQUADRA = ("--win", "--lose", "--live")
INCHIOSTRO = "--team-ink"
COSTANTI = {"--win": "#2FB344", "--lose": "#E5484D", "--live": "#FF8A1F", "--tie": "var(--hint)"}
TESTO = (("--text", "--bg"), ("--text", "--card"), ("--hint", "--bg"), ("--hint", "--card"),
         ("--link", "--bg"), ("--accent", "--bg"), ("--accent", "--card"),
         ("--tie", "--bg"), ("--tie", "--card"), ("--button-text", "--button"),
         (INCHIOSTRO, "--win"), (INCHIOSTRO, "--lose"), (INCHIOSTRO, "--live"))
SEGNI = ("--accent", "--hint")
FONDI = ("--bg", "--card")
MINIMO_TESTO = 4.5
MINIMO_SEGNO = 3.0
SCALA = {"--type-label": "13px", "--type-body": "16px", "--type-lead": "20px",
         "--type-head": "25px", "--type-title": "31px", "--type-score": "39px",
         "--type-hero": "49px"}
RAGGI = {"--radius-hero": "18px", "--radius-tile": "14px", "--radius-chip": "10px",
         "--radius-sheet": "22px"}
DURATE = {"--dur-tap": "120ms", "--dur-sheet": "200ms"}
PASSO = {"--space-1": "4px", "--space-2": "8px", "--space-3": "12px", "--space-4": "16px",
         "--space-5": "20px", "--space-6": "24px", "--gutter": "12px"}
PESI = {"500", "700", "800"}
FAMIGLIE = {"Barlow", "Barlow Semi Condensed"}
LICENZA = "OFL-1.1"
PUNTINO = "·"
MODULI = "app"
CALMA = "prefers-reduced-motion"
MOVIMENTO = ("transition", "transition-duration", "transition-delay",
             "animation", "animation-duration", "animation-delay")
ANIMA = "animation"
FERMO = "none"
CAMBIO = ".beat"
DURATA = "--dur-"
MOVIMENTO_MAX = 300
FUOCO = "outline"
VISIBILE = ":focus-visible"
SPENTO = ("none", "0", "0px")
TABULA = "tabindex"
SE = "'self'"
INLINE = "'unsafe-inline'"
NIENTE = "'none'"
DATI = "data:"
TG = "https://telegram.org"
TG_WEB = "https://web.telegram.org"
STEMMI = f"https://{BADGE_HOST}"
COMUNE = {"default-src": (NIENTE,), "style-src": (SE, INLINE), "font-src": (SE,),
          "base-uri": (NIENTE,)}
MODULO = {"form-action": (SE,)}
POLITICHE = {
    "pages.CSP_BASE": (pages.CSP_BASE, {**COMUNE, **MODULO, "img-src": (DATI,)}),
    "pages.CSP_CLAN": (pages.CSP_CLAN, {**COMUNE, **MODULO, "img-src": (DATI, STEMMI)}),
    "public.CSP_MEDIA": (public.CSP_MEDIA,
                         {**COMUNE, **MODULO, "img-src": (DATI, THUMB_HOST)}),
    "miniapp.CSP": (miniapp.CSP, {**COMUNE, "img-src": (DATI, THUMB_HOST, STEMMI),
                                  "script-src": (SE, TG), "connect-src": (SE,),
                                  "frame-ancestors": (TG_WEB, TG)}),
}


def foglio(nome):
    return (RADICE / nome).read_text(encoding="utf-8")


FOGLI_APP = (foglio(BASE), foglio(APP), style.CSS, miniapp.STYLE)
FOGLI_SITO = (foglio(BASE), foglio(SITO), style.CSS)
TUTTI = (foglio(BASE), foglio(APP), foglio(SITO))


def _blocco(testo, inizio):
    apertura = testo.index("{", inizio)
    livello = 0
    for indice in range(apertura, len(testo)):
        if testo[indice] == "{":
            livello += 1
        elif testo[indice] == "}":
            livello -= 1
            if livello == 0:
                return apertura, indice + 1
    return apertura, len(testo)


def _separa(testo):
    chiari = []
    scuri = []
    resto = testo
    for _ in range(BLOCCHI_MAX):
        inizio = resto.find("@media")
        if inizio < 0:
            break
        apertura, fine = _blocco(resto, inizio)
        chiari.append(resto[:inizio])
        if resto[inizio:apertura].replace(" ", "") in SCURO.replace(" ", ""):
            scuri.append(resto[apertura:fine])
        resto = resto[fine:]
    chiari.append(resto)
    return "".join(chiari), "".join(scuri)


def _token(testo):
    trovati = {}
    for blocco in RADICE_RE.findall(testo):
        for pezzo in blocco.split(";"):
            nome, _, valore = pezzo.partition(":")
            if nome.strip().startswith("--"):
                trovati[nome.strip()] = valore.strip()
    return trovati


def temi(fogli):
    chiaro_testo, scuro_testo = _separa("".join(fogli))
    chiaro = _token(chiaro_testo)
    scuro = dict(chiaro)
    scuro.update(_token(scuro_testo))
    return {"chiaro": chiaro, "scuro": scuro}


def valore(token, nome):
    trovato = token.get(nome, "")
    for _ in range(SALTI_MAX):
        salto = VAR_RE.match(trovato)
        if not salto:
            return trovato
        trovato = token.get(salto.group(1), "")
    return trovato


def _canale(numero):
    quota = numero / 255
    return quota / 12.92 if quota <= 0.04045 else ((quota + 0.055) / 1.055) ** 2.4


def luce(colore):
    grezzo = colore.strip().lstrip("#")
    assert len(grezzo) == 6, colore
    rosso, verde, blu = (int(grezzo[posto:posto + 2], 16) for posto in (0, 2, 4))
    return 0.2126 * _canale(rosso) + 0.7152 * _canale(verde) + 0.0722 * _canale(blu)


def contrasto(davanti, dietro):
    prima, dopo = luce(davanti), luce(dietro)
    alto, basso = max(prima, dopo), min(prima, dopo)
    return (alto + 0.05) / (basso + 0.05)


def versioni():
    righe = [riga.split("\t") for riga in VERSIONI.read_text(encoding="utf-8").splitlines()
             if riga]
    return {nome: (pacchetto, firma, licenza, origine)
            for nome, pacchetto, firma, licenza, origine in righe}


def test_ogni_coppia_di_colori_supera_la_soglia_del_testo_nei_due_temi():
    for dove, fogli in (("app", FOGLI_APP), ("sito", FOGLI_SITO)):
        for tema, token in temi(fogli).items():
            for davanti, dietro in TESTO:
                misura = contrasto(valore(token, davanti), valore(token, dietro))
                assert misura >= MINIMO_TESTO, (dove, tema, davanti, dietro, round(misura, 2))


def test_i_colori_dei_segni_restano_visibili_come_icone():
    for dove, fogli in (("app", FOGLI_APP), ("sito", FOGLI_SITO)):
        for tema, token in temi(fogli).items():
            for segno in SEGNI:
                for fondo in FONDI:
                    misura = contrasto(valore(token, segno), valore(token, fondo))
                    assert misura >= MINIMO_SEGNO, (dove, tema, segno, fondo, round(misura, 2))


def _dichiarazioni(corpo):
    fuori = []
    for pezzo in corpo.split(";"):
        nome, _, valore = pezzo.partition(":")
        if nome.strip():
            fuori.append((nome.strip(), valore.strip()))
    return fuori


def test_i_colori_di_squadra_sono_le_costanti_della_spec():
    for dove, fogli in (("app", FOGLI_APP), ("sito", FOGLI_SITO)):
        for tema, token in temi(fogli).items():
            for nome, atteso in COSTANTI.items():
                assert token.get(nome) == atteso, (dove, tema, nome, token.get(nome))


def test_i_colori_di_squadra_riempiono_e_non_scrivono():
    for nome in (APP, SITO):
        testo = foglio(nome)
        riempie = False
        for selettore, corpo in REGOLA_RE.findall(testo):
            for proprieta, valore in _dichiarazioni(corpo):
                if valore not in tuple(f"var({segno})" for segno in SQUADRA):
                    continue
                assert proprieta.startswith("background"), (nome, selettore, proprieta)
                riempie = True
        assert riempie and f"var({INCHIOSTRO})" in testo, nome


def test_la_scala_i_passi_i_raggi_e_le_durate_sono_quelli_della_spec():
    token = temi((foglio(BASE),))["chiaro"]
    for atteso in (SCALA, PASSO, RAGGI, DURATE):
        for nome, valore_atteso in atteso.items():
            assert token.get(nome) == valore_atteso, (nome, token.get(nome))


def test_nessun_maiuscolo_forzato_e_nessun_gradiente_nei_fogli():
    for testo in TUTTI + (style.CSS, miniapp.STYLE):
        assert "uppercase" not in testo
        assert "linear-gradient" not in testo and "radial-gradient" not in testo


def test_nessun_puntino_separa_le_parole_nell_app():
    moduli = sorted((RADICE / MODULI).glob("*.js"))
    assert moduli
    for percorso in moduli:
        assert PUNTINO not in percorso.read_text(encoding="utf-8"), percorso.name
    for testo in TUTTI + (style.CSS, miniapp.STYLE):
        assert PUNTINO not in testo


def test_il_movimento_si_spegne_e_il_fuoco_resta_visibile():
    testo = foglio(BASE)
    chiaro, ridotto = _separa(testo)
    assert CALMA in testo
    inizio = testo.find(CALMA)
    apertura, fine = _blocco(testo, inizio)
    spento = _token(testo[apertura:fine])
    for nome in DURATE:
        assert spento.get(nome) == "0s", (nome, spento.get(nome))
    assert ridotto or chiaro
    visto = False
    for selettore, corpo in REGOLA_RE.findall(testo):
        if VISIBILE not in selettore:
            continue
        assert dict(_dichiarazioni(corpo)).get(FUOCO, "").endswith("var(--accent)"), selettore
        visto = True
    assert visto
    for foglia in TUTTI + (style.CSS, miniapp.STYLE):
        for selettore, corpo in REGOLA_RE.findall(foglia):
            for proprieta, valore in _dichiarazioni(corpo):
                assert not (proprieta == FUOCO and valore in SPENTO), (selettore, valore)


def _fuori_calma(testo):
    vivi = []
    calmi = []
    resto = testo
    for _ in range(BLOCCHI_MAX):
        inizio = resto.find(CALMA)
        if inizio < 0:
            break
        apertura, fine = _blocco(resto, inizio)
        vivi.append(resto[:inizio])
        calmi.append(resto[apertura:fine])
        resto = resto[fine:]
    vivi.append(resto)
    return "".join(vivi), "".join(calmi)


def _mosse(testo):
    trovate = {}
    for selettore, corpo in REGOLA_RE.findall(testo):
        for proprieta, valore in _dichiarazioni(corpo):
            if proprieta not in MOVIMENTO:
                continue
            for pezzo in selettore.split(","):
                trovate.setdefault(pezzo.strip(), set()).add((proprieta, valore))
    return trovate


def _millisecondi(valore):
    testo = valore.strip()
    for coda, fattore in (("ms", 1), ("s", 1000)):
        if testo.endswith(coda):
            try:
                return float(testo[:-len(coda)]) * fattore
            except ValueError:
                return None
    return None


def test_ogni_animazione_si_spegne_col_movimento_ridotto():
    for nome in (APP, SITO):
        vivo, calmo = _fuori_calma(foglio(nome))
        animate = {selettore for selettore, mosse in _mosse(vivo).items()
                   if any(proprieta == ANIMA for proprieta, _ in mosse)}
        spente = {selettore for selettore, mosse in _mosse(calmo).items()
                  if (ANIMA, FERMO) in mosse}
        assert animate, nome
        resta = animate - {CAMBIO}
        assert resta <= spente, (nome, sorted(resta - spente))


def test_il_cambio_di_stato_resta_col_movimento_ridotto():
    vivo, calmo = _fuori_calma(foglio(APP))
    acceso = _mosse(vivo).get(CAMBIO, set())
    assert any(proprieta == ANIMA for proprieta, _ in acceso), CAMBIO
    spente = {selettore for selettore, mosse in _mosse(calmo).items()
              if (ANIMA, FERMO) in mosse}
    assert CAMBIO not in spente, sorted(spente)


def test_nessuna_durata_del_movimento_passa_i_trecento_millisecondi():
    token = temi((foglio(BASE),))["chiaro"]
    durate = {nome: valore for nome, valore in token.items() if nome.startswith(DURATA)}
    assert set(durate) == set(DURATE)
    for nome, valore in durate.items():
        misura = _millisecondi(valore)
        assert misura is not None and misura <= MOVIMENTO_MAX, (nome, valore)


def test_nessun_tabindex_forza_l_ordine_di_tabulazione():
    moduli = sorted((RADICE / MODULI).glob("*.js"))
    assert moduli
    for percorso in moduli:
        assert TABULA not in percorso.read_text(encoding="utf-8"), percorso.name


def test_solo_le_variabili_del_tema_restano_nel_foglio_dentro_la_pagina():
    for testo in (style.CSS, miniapp.STYLE):
        for selettore in SELETTORE_RE.findall(testo):
            pulito = selettore.strip()
            assert pulito.startswith(":root") or pulito.startswith("@media"), pulito


def test_i_font_del_foglio_esistono_e_combaciano_con_versions():
    registro = versioni()
    trovati = URL_RE.findall(foglio(BASE))
    assert trovati
    for grezzo in trovati:
        nome = grezzo.strip("\"'")
        percorso = RADICE / nome
        assert percorso.exists(), nome
        firma = hashlib.sha256(percorso.read_bytes()).hexdigest()
        assert nome in registro, nome
        assert registro[nome][1] == firma, nome


def test_versions_registra_ogni_font_con_licenza_aperta_e_origine():
    registro = versioni()
    nomi = sorted(percorso.name for percorso in FONTI.glob("*.woff2"))
    assert len(nomi) == len(set(nomi)) and nomi
    for nome in nomi:
        chiave = "fonts/" + nome
        assert chiave in registro, chiave
        pacchetto, firma, licenza, origine = registro[chiave]
        assert licenza == LICENZA and origine.startswith("https://"), chiave
        assert pacchetto.startswith("barlow"), chiave
        assert hashlib.sha256((FONTI / nome).read_bytes()).hexdigest() == firma, chiave
    assert "fonts/OFL.txt" in registro
    assert (FONTI / "OFL.txt").read_text(encoding="utf-8").startswith("Copyright")


def test_le_facce_coprono_le_due_larghezze_nei_tre_pesi():
    facce = FACCIA_RE.findall(foglio(BASE))
    assert facce
    visti = set()
    for faccia in facce:
        famiglia = re.search(r"font-family:\s*['\"]([^'\"]+)['\"]", faccia).group(1)
        peso = re.search(r"font-weight:\s*(\d+)", faccia).group(1)
        assert famiglia in FAMIGLIE and peso in PESI, faccia
        assert "font-display:swap" in faccia.replace(" ", "")
        assert "unicode-range" in faccia
        visti.add((famiglia, peso))
    assert visti == {(famiglia, peso) for famiglia in FAMIGLIE for peso in PESI}


def test_la_home_e_la_mini_app_caricano_i_fogli_con_l_hash_del_manifest():
    marchio = static.manifest()["hash"]
    casa = pages.home_page(L, {})
    app = miniapp.app_page(L, None, "abcdef0123456789")
    for corpo, proprio in ((casa, SITO), (app, APP)):
        for nome in (BASE, proprio):
            atteso = f'<link rel="stylesheet" href="/static/{marchio}/{nome}">'
            assert atteso in corpo, (nome, atteso)
    assert f"/static/{marchio}/{SITO}" not in app and f"/static/{marchio}/{APP}" not in casa


def _regole(politica):
    fuori = {}
    for pezzo in politica.split(";"):
        parti = pezzo.split()
        if parti:
            fuori[parti[0]] = tuple(parti[1:])
    return fuori


def test_le_politiche_lasciano_passare_i_fogli_e_i_font_nostri_e_nient_altro():
    for nome, (politica, atteso) in POLITICHE.items():
        assert _regole(politica) == atteso, (nome, politica)


def test_il_servizio_conosce_i_font_e_i_fogli():
    assert static.kind_of("fonts/barlow-500-latin.woff2") == "font/woff2"
    assert static.kind_of(BASE) == "text/css; charset=utf-8"
    assert static.read("fonts/OFL.txt") is None
    assert static.read(BASE) is not None and static.read(APP) is not None
    assert static.read("fonts/barlow-500-latin.woff2") == (
        Path(FONTI / "barlow-500-latin.woff2").read_bytes())
