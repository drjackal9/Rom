import re

from clashbot.web import art, static

RADICE = static.ROOT
MODULI = RADICE / "app"
FOGLI = ("base.css", "app/app.css")
TUTTI = FOGLI + ("site.css",)
APP = "app/app.css"
DISEGNI = "app/art.js"
SITO = "site.css"
FISSA = re.compile(r'class="([^"$]+)"')
LETTERALE = re.compile(r'"([^"\\\n]*)"')
CONFRONTO = re.compile(r"[=!]=$")
REGOLA_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
CLASSE_RE = re.compile(r"\.([a-zA-Z0-9_-]+)")
RAGGIO_RE = re.compile(r"border-radius\s*:\s*([^;{}]+)")
OMBRA_RE = re.compile(r"box-shadow\s*:\s*([^;{}]+)")
TRATTO_RE = re.compile(r"stroke-width\s*:\s*([^;{}]+)")
MOVIMENTO_RE = re.compile(r"(?:transition|animation)\s*:\s*([^;{}]+)")
TEMPO_RE = re.compile(r"[\d.]+m?s\b")
TOKEN_RE = re.compile(r"^var\(--[a-z0-9-]+\)$")
USO_RE = re.compile(r"var\(--[a-z0-9-]+\)")
BLOCCHI_MAX = 64
SPENTO = ("0", "none")
RAGGI = {".card": "--radius-tile", ".card.hero": "--radius-hero", ".tile": "--radius-tile",
         ".chip": "--radius-chip", ".sheet": "--radius-sheet"}
OMBRE = {".card": "--shadow-tile", ".card.hero": "--shadow-hero", ".tile": "--shadow-tile",
         ".sheet": "--shadow-hero"}
BATTITO = "beat"
TONI = ("mine", "mate", "free", "done")
TRATTI = ("--stroke-art", "--stroke-ico", "--stroke-star", "--stroke-ring", "--stroke-line")


def foglio(nome):
    return (RADICE / nome).read_text(encoding="utf-8")


def _fine(testo, apertura):
    livello = 0
    for indice in range(apertura, len(testo)):
        if testo[indice] == "{":
            livello += 1
        elif testo[indice] == "}":
            livello -= 1
            if livello == 0:
                return indice + 1
    return len(testo)


def _senza_at(testo):
    fuori = []
    resto = testo
    for _ in range(BLOCCHI_MAX):
        inizio = resto.find("@")
        if inizio < 0:
            break
        apertura = resto.find("{", inizio)
        if apertura < 0:
            break
        fuori.append(resto[:inizio])
        resto = resto[_fine(resto, apertura):]
    fuori.append(resto)
    return "".join(fuori)


def _corpo(testo, inizio):
    livello = 0
    for indice in range(inizio, len(testo)):
        if testo[indice] == "{":
            livello += 1
        elif testo[indice] == "}":
            livello -= 1
            if livello == 0:
                return testo[inizio + 1:indice]
    return ""


def _letterali(espressione):
    fuori = []
    for pezzo in LETTERALE.finditer(espressione):
        if CONFRONTO.search(espressione[:pezzo.start()].rstrip()):
            continue
        fuori.append(pezzo.group(1))
    return fuori


def classi_dei_moduli():
    trovate = {}
    for percorso in sorted(MODULI.glob("*.js")):
        testo = percorso.read_text(encoding="utf-8")
        scritte = [pezzo.group(1) for pezzo in FISSA.finditer(testo)]
        for segno in re.finditer(r"class=\$", testo):
            scritte.extend(_letterali(_corpo(testo, segno.end())))
        for scritta in scritte:
            for nome in scritta.split():
                trovate.setdefault(nome, set()).add(percorso.name)
    return trovate


def regole():
    fuori = []
    for nome in FOGLI:
        for selettore, corpo in REGOLA_RE.findall(_senza_at(foglio(nome))):
            fuori.append(([pezzo.strip() for pezzo in selettore.split(",")], corpo))
    return fuori


def classi_con_regola():
    scritte = set()
    for selettori, _ in regole():
        for selettore in selettori:
            scritte.update(CLASSE_RE.findall(selettore))
    return scritte


def _valori(chiave, selettore):
    fuori = []
    for selettori, corpo in regole():
        if selettore in selettori:
            fuori.extend(chiave.findall(corpo))
    return fuori


def test_ogni_classe_dei_moduli_ha_una_regola_nei_fogli():
    usate = classi_dei_moduli()
    assert usate
    scritte = classi_con_regola()
    assert not sorted(nome for nome in usate if nome not in scritte)


def test_la_gerarchia_dei_raggi_segue_le_superfici():
    for selettore, token in RAGGI.items():
        valori = _valori(RAGGIO_RE, selettore)
        assert valori, selettore
        assert all(f"var({token})" in valore for valore in valori), (selettore, valori)


def test_la_gerarchia_delle_ombre_mette_l_eroe_sopra_le_tessere():
    for selettore, token in OMBRE.items():
        valori = _valori(OMBRA_RE, selettore)
        assert valori, selettore
        assert all(f"var({token})" in valore for valore in valori), (selettore, valori)
    assert not _valori(OMBRA_RE, ".chip") and not _valori(OMBRA_RE, ".row")


def test_ogni_raggio_e_ogni_ombra_vengono_dai_token():
    for nome in TUTTI:
        testo = _senza_at(foglio(nome))
        for chiave in (RAGGIO_RE, OMBRA_RE, TRATTO_RE):
            for valore in chiave.findall(testo):
                for pezzo in valore.split():
                    assert TOKEN_RE.match(pezzo) or pezzo in SPENTO, (nome, valore)


def test_ogni_durata_del_movimento_viene_dai_token():
    for nome in (APP, SITO):
        valori = MOVIMENTO_RE.findall(foglio(nome))
        assert valori, nome
        for valore in valori:
            assert not TEMPO_RE.search(USO_RE.sub(" ", valore)), (nome, valore)
    for valore in MOVIMENTO_RE.findall(foglio(APP)):
        assert "var(--dur-" in valore or valore.strip() in SPENTO, valore


def test_l_impulso_ha_la_sua_animazione_e_il_suo_tratto():
    testo = foglio(APP)
    assert f"@keyframes {BATTITO}" in testo
    assert f".{BATTITO}" in testo
    tratti = foglio("base.css")
    for token in TRATTI:
        assert token in tratti, token
    assert "stroke-width=" not in foglio(DISEGNI)
    assert "stroke-width" not in art.icon("wars")
    assert "stroke-width:var(--stroke-ico)" in foglio(SITO)


def test_ogni_tono_della_griglia_nemica_porta_il_suo_bordo():
    scritte = classi_con_regola()
    assert not [tono for tono in TONI if tono not in scritte]
