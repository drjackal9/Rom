import asyncio
import importlib.util
import sys
import tempfile
import threading
from pathlib import Path

from clashbot import site_conf

RADICE = Path(__file__).resolve().parents[2]
GRUPPO = "https://t.me/clanboard_gruppo"
FUORI = "document.documentElement.scrollWidth - window.innerWidth"
ATTESA = 20


def carica(percorso):
    spec = importlib.util.spec_from_file_location("guarda_sito_originale", str(percorso))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def campione(base, codice):
    store, pagine = base.campione(RADICE)
    store.kv[site_conf.KEY] = {site_conf.GROUP: GRUPPO, site_conf.EXAMPLE: codice}
    return store, pagine


def servi(store):
    from clashbot.web import app as web, http
    pronto = threading.Event()
    trovato = {}

    async def gira():
        server = await http.serve(web.Site(store, lambda: 0.0).router, "127.0.0.1", 0)
        trovato["porta"] = server.sockets[0].getsockname()[1]
        pronto.set()
        async with server:
            await server.serve_forever()

    threading.Thread(target=lambda: asyncio.run(gira()), daemon=True).start()
    if not pronto.wait(ATTESA):
        raise RuntimeError("il sito non parte")
    return f"http://127.0.0.1:{trovato['porta']}"


def fotografa(base, scatti, lavoro):
    processo, canale = base.apri(lavoro)
    try:
        esiti = []
        for scatto in scatti:
            fatto = base.scatta(canale.chiama, scatto)
            esiti.append((scatto["file"], fatto, base.valore(canale.chiama, FUORI)))
        return esiti
    finally:
        base.chiudi(processo, canale)


def guarda(originale, uscita, codice):
    base = carica(originale)
    store, pagine = campione(base, codice)
    indirizzo = servi(store)
    scatti = base.piano(indirizzo, pagine, list(base.MISURE), uscita)
    with tempfile.TemporaryDirectory() as lavoro:
        return fotografa(base, scatti, Path(lavoro))


def main(argomenti):
    if len(argomenti) != 3:
        sys.stderr.write("uso: python -m tests.sonde.guarda_sezioni <guarda_sito.py> <cartella> "
                         "<codice del clan d'esempio>\n")
        return 1
    esiti = guarda(Path(argomenti[0]).expanduser(), Path(argomenti[1]).expanduser(), argomenti[2])
    for file, fatto, fuori in esiti:
        sys.stdout.write(f"{'ok' if fatto else 'MANCA'} fuori={fuori} {file}\n")
    return 0 if all(fatto and fuori == 0 for _, fatto, fuori in esiti) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
