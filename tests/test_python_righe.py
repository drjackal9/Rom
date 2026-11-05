import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACCHETTO = ROOT / "clashbot"
TETTO = 60
OLTRE_IL_TETTO = {
    "console.py:on_panel_callback": 80,
    "handlers.py:build_view": 193,
    "handlers.py:cmd_family": 78,
    "handlers.py:on_goal_callback": 61,
    "poller.py:_tick": 71,
    "poller.py:sweep_players": 84,
    "poller.py:track_cwl": 64,
    "poller.py:track_war": 65,
    "privacy.py:_erase_clan": 65,
    "tournaments.py:ensure": 67,
}


def funzioni(sorgente):
    trovate = []
    for nodo in ast.walk(ast.parse(sorgente)):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        ultima = max(getattr(figlio, "end_lineno", None) or nodo.lineno
                     for figlio in ast.walk(nodo))
        trovate.append((nodo.lineno, nodo.name, ultima - nodo.lineno + 1))
    return [(nome, righe) for _, nome, righe in sorted(trovate)]


def oltre_il_tetto():
    fuori = []
    for path in sorted(PACCHETTO.rglob("*.py")):
        for nome, righe in funzioni(path.read_text(encoding="utf-8")):
            if righe > TETTO:
                fuori.append(("%s:%s" % (path.relative_to(PACCHETTO).as_posix(), nome), righe))
    return fuori


def test_il_contatore_misura_dalla_def_all_ultima_riga_del_corpo():
    sorgente = "def corta():\n    return 1\n\n\ndef lunga():\n" + "    x = 1\n" * 3
    assert funzioni(sorgente) == [("corta", 2), ("lunga", 4)]


def test_il_contatore_vede_anche_i_metodi_e_le_funzioni_async():
    sorgente = "class C:\n    async def dentro(self):\n        return 1\n"
    assert funzioni(sorgente) == [("dentro", 2)]


def test_nessuna_funzione_python_nuova_supera_il_tetto_di_righe():
    nuove = [nome for nome, _ in oltre_il_tetto() if nome not in OLTRE_IL_TETTO]
    assert nuove == [], nuove


def test_nessuna_funzione_gia_lunga_cresce_ancora():
    misurate = dict(oltre_il_tetto())
    cresciute = [(nome, misurate.get(nome), righe) for nome, righe in OLTRE_IL_TETTO.items()
                 if misurate.get(nome, 0) > righe]
    assert cresciute == [], cresciute
