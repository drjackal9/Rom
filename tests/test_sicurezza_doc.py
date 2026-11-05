import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "sicurezza.md"
LETTURE = ("README.md", "README.it.md")
CAPITOLI = (
    "Identità e ruoli",
    "Gestori che abusano",
    "Contenuti e gruppo",
    "Rete fra clan e reclutamento",
    "Piattaforma e moderazione",
)
ARRIVO = "in arrivo con l'app"
ESTERNO = "configurazione esterna"
NODO = re.compile(r"`(tests/test_[a-z0-9_]+\.py::test_[a-z0-9_]+)`")
PENDING = ("Sonde automatiche e bot contro il sito",)


def contenuto():
    return DOC.read_text(encoding="utf-8")


def tabelle():
    esito = {}
    capitolo = None
    for riga in contenuto().splitlines():
        riga = riga.strip()
        if riga.startswith("## "):
            capitolo = riga[3:].strip()
            esito[capitolo] = []
            continue
        if not riga.startswith("|") or capitolo is None:
            continue
        celle = [cella.strip() for cella in riga.strip("|").split("|")]
        if len(celle) != 3 or celle[0] == "Minaccia" or set(celle[0]) <= set("-: "):
            continue
        esito[capitolo].append(celle)
    return esito


def righe():
    return [riga for righe_capitolo in tabelle().values() for riga in righe_capitolo]


def citati():
    return [nodo for _, _, prove in righe() for nodo in NODO.findall(prove)]


def raccolti():
    esito = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--collect-only", "tests"],
        cwd=REPO, capture_output=True, text=True)
    assert esito.returncode == 0, esito.stdout[-2000:]
    return {riga.strip() for riga in esito.stdout.splitlines()}


def test_la_lista_ha_una_tabella_per_ogni_capitolo_nell_ordine():
    piene = tuple(nome for nome, righe_capitolo in tabelle().items() if righe_capitolo)
    assert piene == CAPITOLI


def test_ogni_riga_dice_la_minaccia_il_controllo_e_la_prova():
    for minaccia, controllo, prove in righe():
        assert minaccia and controllo, minaccia
        assert NODO.findall(prove) or ARRIVO in prove or ESTERNO in prove, minaccia


def test_solo_le_righe_previste_restano_senza_prova():
    assert tuple(minaccia for minaccia, _, prove in righe() if not NODO.findall(prove)) == PENDING


def test_ogni_test_citato_esiste_davvero():
    nomi = citati()
    assert nomi
    raccolta = raccolti()
    assert raccolta
    assert [nome for nome in nomi if nome not in raccolta] == []


def test_i_due_leggimi_portano_alla_lista():
    for nome in LETTURE:
        assert "docs/sicurezza.md" in (REPO / nome).read_text(encoding="utf-8"), nome
