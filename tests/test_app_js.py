import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "js" / "run.js"
APP = ROOT / "clashbot" / "web" / "static" / "app"
TETTO = 60
DICHIARA = re.compile(r"^(?:export )?(?:default )?(?:async )?(?:function|const|let|var|class)"
                      r" (\w+)")
APERTURA = re.compile(r"^(?:export )?(?:default )?(?:async )?function (\w+)")
CORPO = re.compile(r"=>|\bfunction\b")
CONFINE = re.compile(r"^\S")
CHIUSURE = ("}", ")", "]", "`")


def confini(righe):
    return [numero for numero, riga in enumerate(righe)
            if CONFINE.match(riga) and not riga.startswith(CHIUSURE)]


def coda(righe, fine, inizio):
    while fine > inizio + 1 and not righe[fine - 1].strip():
        fine -= 1
    return fine


def fine_di(righe, muri, inizio):
    dopo = next((muro for muro in muri if muro > inizio), len(righe))
    return coda(righe, dopo, inizio)


def funzioni(testo):
    righe = testo.splitlines()
    muri = confini(righe)
    trovate = []
    for inizio in muri:
        trovata = DICHIARA.match(righe[inizio])
        if trovata and (APERTURA.match(righe[inizio]) or CORPO.search(righe[inizio])):
            trovate.append((trovata.group(1), fine_di(righe, muri, inizio) - inizio))
    return trovate


def test_the_app_scripts_pass_in_node():
    node = shutil.which("node")
    assert node, "node non trovato: installalo sul Mac, i test JS non si saltano"
    done = subprocess.run([node, str(RUNNER)], capture_output=True, text=True, cwd=ROOT,
                          timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr


def test_il_rilevatore_vede_anche_i_componenti_scritti_come_arrow():
    testo = ("export const Corta = ({ a }) => html`\n"
             "  <div>${a}</div>`;\n"
             "\n"
             "const NOMI = [\"uno\", \"due\"];\n"
             "\n"
             "export function lunga(a) {\n"
             "  return a;\n"
             "}\n")
    assert funzioni(testo) == [("Corta", 2), ("lunga", 3)]


def test_una_funzione_lunga_scritta_come_arrow_non_sfugge_al_tetto():
    testo = ("export const Lunga = () => html`\n"
             + "  <div></div>\n" * TETTO
             + "  <b></b>`;\n"
             "\n"
             "export const Corta = () => 1;\n")
    assert funzioni(testo) == [("Lunga", TETTO + 2), ("Corta", 1)]


def test_nessuna_funzione_dell_app_supera_il_tetto_di_righe():
    lunghe = []
    for path in sorted(APP.glob("*.js")):
        for nome, righe in funzioni(path.read_text(encoding="utf-8")):
            if righe > TETTO:
                lunghe.append("%s:%s %d" % (path.name, nome, righe))
    assert lunghe == [], lunghe
