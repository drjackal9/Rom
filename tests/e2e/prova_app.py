import http.server
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from clashbot import i18n
from clashbot.acts import SHARE_KINDS, SHARE_MANAGER
from clashbot.web import live, miniapp, static

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TELEGRAM = "https://telegram.org/js/telegram-web-app.js"
VIA_TELEGRAM = "/telegram-web-app.js"
VIA_CANALE = "/__canale"
RADICE = pathlib.Path(__file__).resolve().parents[2]
ESEMPIO = "tests/js/page.json"
SLUG = "prova"
PAGINA = "/app/" + SLUG
LARGHEZZA = 390
ALTEZZA = 844
VERSIONE = "9.0"
LINGUA = "it"
CANALI = ("vivo", "cade")
LIVELLI = ("gestore", "piena", "ridotta", "estraneo")
CONDIVISIONI = SHARE_KINDS + SHARE_MANAGER
PREPARATO = "prepared"
PER_SCHEDA = 60
TIENI = "public, max-age=%d, immutable" % static.STATIC_MAX_AGE
ATTESA = 900
RETE = 20
BATTITO = 3
BATTITI = 8
FINESTRA = "560,1000"
MOSTRA = 400
CACHE = "prova-app-telegram-web-app.js"
PROFILO = "prova-app-chrome"

STRUMENTI = """
window.__errs = [];
window.__csp = [];
window.__risorse = [];
window.addEventListener('error', function (e) {
  var chi = e.target && e.target.tagName ? e.target : null;
  if (chi) { window.__risorse.push(chi.tagName + ' ' + (chi.src || chi.href || '')); }
  else { window.__errs.push('errore: ' + (e.message || e)); }
}, true);
window.addEventListener('unhandledrejection', function (e) {
  window.__errs.push('rifiuto: ' + ((e.reason && (e.reason.stack || e.reason.message)) || e.reason));
});
(function () {
  var vecchio = console.error;
  console.error = function () {
    window.__errs.push('console: ' + Array.prototype.join.call(arguments, ' '));
    vecchio.apply(console, arguments);
  };
})();
document.addEventListener('securitypolicyviolation', function (e) {
  window.__csp.push(e.violatedDirective + ' ' + e.blockedURI);
});
"""


def _politica():
    return miniapp.CSP.split("frame-ancestors")[0] + "frame-ancestors 'self'"


def _stato(radice, livello):
    dati = json.loads((pathlib.Path(radice) / ESEMPIO).read_text(encoding="utf-8"))
    return miniapp.state_body(dati["page"], dati["seats"][livello], 0, dati["now"])


def _telegram():
    cache = pathlib.Path(tempfile.gettempdir()) / CACHE
    if cache.exists() and cache.stat().st_size:
        return cache.read_bytes(), None
    try:
        with urllib.request.urlopen(TELEGRAM, timeout=RETE) as risposta:
            dati = risposta.read()
    except (OSError, ValueError) as errore:
        return None, "telegram-web-app.js non raggiungibile: %s" % errore
    cache.write_bytes(dati)
    return dati, None


class Banco:
    def __init__(self, radice, larghezza, versione, canale, livello, telegram):
        self.stato = _stato(radice, livello)
        self.canale = canale
        self.telegram = telegram
        self.ospite = (pathlib.Path(__file__).parent / "ospite_telegram.js").read_bytes()
        self.conf = {"pagina": PAGINA, "larghezza": larghezza, "altezza": ALTEZZA,
                     "versione": versione, "lingua": LINGUA, "perScheda": PER_SCHEDA,
                     "canale": canale, "riapri": VIA_CANALE}
        self.log = []
        self.esito = {}
        self.fatto = threading.Event()

    def pagina(self):
        dentro = {"clan": self.stato.get("clan") or {"name": SLUG}, "lang": LINGUA}
        testo = miniapp.app_page(i18n.locale(LINGUA), dentro, SLUG)
        testo = testo.replace(TELEGRAM, VIA_TELEGRAM, 1)
        return testo.replace("<head>", '<head><script src="/strumenti.js"></script>', 1)

    def prova(self):
        return ('<!doctype html><meta charset="utf-8"><title>prova</title>'
                '<iframe id="f" style="width:%dpx;height:%dpx;border:0"></iframe>'
                '<pre id="out">in corso</pre>'
                "<script>window.PROVA=%s;</script>"
                '<script src="/ospite.js"></script>'
                % (self.conf["larghezza"], self.conf["altezza"], json.dumps(self.conf)))

    def rispondi(self, corpo):
        kind = str(corpo.get("kind") or "")
        risposta = dict(self.stato)
        if kind in CONDIVISIONI:
            risposta[PREPARATO] = corpo.get("id") or SLUG
        self.log.append({"tipo": "azione", "kind": kind})
        return risposta


class Servo(http.server.BaseHTTPRequestHandler):
    banco = None
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def manda(self, corpo, genere="application/json", codice=200, politica=False,
              tieni=False):
        grezzo = corpo if isinstance(corpo, bytes) else str(corpo).encode()
        self.send_response(codice)
        self.send_header("Content-Type", genere)
        self.send_header("Content-Length", str(len(grezzo)))
        self.send_header("Cache-Control", TIENI if tieni else "no-store")
        if politica:
            self.send_header("Content-Security-Policy", _politica())
        self.end_headers()
        self.wfile.write(grezzo)

    def vivo(self):
        if self.banco.canale == CANALI[1]:
            self.banco.log.append({"tipo": "vivo", "kind": ""})
            return self.manda("", "text/plain", 503)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.banco.log.append({"tipo": "vivo", "kind": ""})
        self.wfile.write(b"retry: 60000\n\n")
        self.wfile.flush()
        corpo = json.dumps(self.banco.stato)
        self.wfile.write(("event: state\ndata: " + corpo + "\n\n").encode())
        self.wfile.flush()
        for _ in range(BATTITI):
            time.sleep(BATTITO)
            self.wfile.write(live.PING.encode())
            self.wfile.flush()

    def statico(self, via):
        parti = via.split("/", 3)
        corpo = static.read(parti[3]) if len(parti) > 3 else None
        if corpo is None:
            return self.manda("", "text/plain", 404)
        return self.manda(corpo, static.kind_of(parti[3]), tieni=True)

    def do_GET(self):
        via = self.path.split("?")[0]
        if via == "/prova":
            return self.manda(self.banco.prova(), "text/html; charset=utf-8")
        if via == "/ospite.js":
            return self.manda(self.banco.ospite, "text/javascript")
        if via == "/strumenti.js":
            return self.manda(STRUMENTI, "text/javascript")
        if via == VIA_TELEGRAM:
            return self.manda(self.banco.telegram, "text/javascript", tieni=True)
        if via == "/__log":
            return self.manda(json.dumps(self.banco.log))
        if via == VIA_CANALE:
            self.banco.canale = CANALI[0]
            return self.manda(json.dumps({"canale": self.banco.canale}))
        if via == PAGINA:
            return self.manda(self.banco.pagina(), "text/html; charset=utf-8", politica=True)
        if via == PAGINA + "/state":
            self.banco.log.append({"tipo": "stato", "kind": ""})
            return self.manda(json.dumps(self.banco.stato))
        if via == PAGINA + "/live":
            try:
                return self.vivo()
            except OSError:
                return None
        if via.startswith("/static/"):
            return self.statico(via)
        if via.startswith(PAGINA + "/"):
            return self.manda(json.dumps({"text": ""}))
        return self.manda("", "text/plain", 404)

    def do_POST(self):
        quanto = int(self.headers.get("Content-Length") or 0)
        grezzo = self.rfile.read(quanto) if quanto else b""
        try:
            corpo = json.loads(grezzo.decode() or "{}")
        except ValueError:
            corpo = {}
        if self.path == "/__esito":
            self.banco.esito = corpo
            self.banco.fatto.set()
            return self.manda("{}")
        if self.path.startswith(PAGINA + "/act"):
            return self.manda(json.dumps(self.banco.rispondi(corpo)))
        return self.manda("{}")


def _servo(banco):
    return type("ServoLegato", (Servo,), {"banco": banco})


class Palco(http.server.ThreadingHTTPServer):
    daemon_threads = True


def _chrome(porta, profilo):
    return subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
         "--no-default-browser-check", "--disable-extensions", "--mute-audio",
         "--user-data-dir=%s" % profilo, "--window-size=%s" % FINESTRA,
         "--remote-debugging-port=0", "http://127.0.0.1:%d/prova" % porta],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _saltata(motivo, larghezza, versione, canale, livello):
    return {"saltata": motivo, "larghezza": larghezza, "versione": versione, "canale": canale,
            "livello": livello, "schede": [], "controlli": 0, "bersagli": 0, "fogli": 0,
            "errori": [], "csp": [], "risorse": [], "fuori": [], "muti": [], "azioni": [],
            "coda": 0, "tocchi": [], "prima": {}, "ripristino": {}}


def _riga_fuori(dove, misura):
    return "%s: %d fuori su %d px %s" % (dove, misura["quanti"], misura["largo"],
                                         ", ".join(misura["esempi"]))


def _effetto(tocco):
    return bool(tocco["cambi"] or tocco["inviati"] or tocco["richieste"] or tocco["foglio"]
                or tocco["detti"] or tocco["scorre"])


def _fuori(grezzo, tocchi):
    trovati = []
    if grezzo["prima"]["fuori"]["quanti"]:
        trovati.append(_riga_fuori("prima vista", grezzo["prima"]["fuori"]))
    for scheda in grezzo["schede"]:
        if scheda["fuori"]["quanti"]:
            trovati.append(_riga_fuori(scheda["scheda"], scheda["fuori"]))
    for tocco in tocchi:
        if tocco["fuori"]["quanti"]:
            trovati.append(_riga_fuori("%s / %s" % (tocco["scheda"], tocco["etichetta"]),
                                       tocco["fuori"]))
    return trovati


def _raccogli(grezzo, larghezza, versione, canale, livello):
    tocchi = [tocco for scheda in grezzo["schede"] for tocco in scheda["tocchi"]]
    errori = list(grezzo["prima"]["errori"])
    csp = list(grezzo["prima"]["csp"])
    risorse = list(grezzo["prima"]["risorse"])
    azioni = set()
    for scheda in grezzo["schede"]:
        errori.extend(scheda["errori"])
        csp.extend(scheda["csp"])
    for tocco in tocchi:
        errori.extend(tocco["errori"])
        csp.extend(tocco["csp"])
        risorse.extend(tocco["risorse"])
        azioni.update(tocco["inviati"])
    return {"saltata": None, "larghezza": larghezza, "versione": versione, "canale": canale,
            "livello": livello, "schede": [scheda["scheda"] for scheda in grezzo["schede"]],
            "controlli": len(tocchi),
            "bersagli": sum(scheda["bersagli"] for scheda in grezzo["schede"]),
            "fogli": len([tocco for tocco in tocchi if tocco["foglio"]]),
            "errori": errori, "csp": csp, "risorse": risorse, "fuori": _fuori(grezzo, tocchi),
            "muti": [tocco for tocco in tocchi if not _effetto(tocco)],
            "azioni": sorted(azioni), "coda": len([one for one in tocchi if one["coda"]]),
            "tocchi": tocchi, "prima": grezzo["prima"],
            "ripristino": grezzo.get("ripristino") or {}}


def _gira(banco, larghezza, versione, canale, livello):
    palco = Palco(("127.0.0.1", 0), _servo(banco))
    porta = palco.server_address[1]
    threading.Thread(target=palco.serve_forever, daemon=True).start()
    profilo = pathlib.Path(tempfile.gettempdir()) / PROFILO
    chrome = _chrome(porta, profilo)
    finito = banco.fatto.wait(timeout=ATTESA)
    chrome.terminate()
    try:
        chrome.wait(timeout=RETE)
    except subprocess.TimeoutExpired:
        chrome.kill()
    palco.shutdown()
    palco.server_close()
    if not finito:
        return _saltata("tempo scaduto dopo %d s" % ATTESA, larghezza, versione, canale, livello)
    if banco.esito.get("crollo"):
        return _saltata("imbragatura caduta: %s" % banco.esito["crollo"][:MOSTRA],
                        larghezza, versione, canale, livello)
    return _raccogli(banco.esito, larghezza, versione, canale, livello)


def esegui(radice, larghezza=LARGHEZZA, versione=VERSIONE, canale=CANALI[0], livello=LIVELLI[0]):
    if canale not in CANALI:
        raise ValueError("canale sconosciuto: %s" % canale)
    if livello not in LIVELLI:
        raise ValueError("livello ancora senza porta: %s" % livello)
    if not pathlib.Path(CHROME).exists():
        return _saltata("Chrome non trovato in %s" % CHROME, larghezza, versione, canale, livello)
    telegram, manca = _telegram()
    if manca:
        return _saltata(manca, larghezza, versione, canale, livello)
    banco = Banco(radice, larghezza, versione, canale, livello, telegram)
    return _gira(banco, larghezza, versione, canale, livello)


def riassunto(esito):
    if esito["saltata"]:
        return "SALTATA: %s" % esito["saltata"]
    righe = ["%d px | Telegram %s | canale %s | livello %s"
             % (esito["larghezza"], esito["versione"], esito["canale"], esito["livello"]),
             "schede: %s" % ", ".join(esito["schede"]),
             "controlli toccati: %d su %d bersagli | fogli aperti: %d"
             % (esito["controlli"], esito["bersagli"], esito["fogli"]),
             "errori JS: %d | violazioni CSP: %d | risorse mancate: %d | fuori schermo: %d"
             % (len(esito["errori"]), len(esito["csp"]), len(esito["risorse"]),
                len(esito["fuori"])),
             "azioni raggiunte: %d | tocchi in coda: %d"
             % (len(esito["azioni"]), esito["coda"])]
    ripreso = esito["ripristino"]
    if ripreso.get("coda"):
        righe.append("canale tornato: partite %s | coda svuotata: %s"
                     % (", ".join(ripreso["inviati"]) or "niente",
                        "si" if not ripreso["coda_dopo"] else "no"))
    for riga in esito["fuori"]:
        righe.append("  FUORI %s" % riga)
    for riga in esito["errori"]:
        righe.append("  ERRORE %s" % riga[:MOSTRA])
    for riga in esito["csp"]:
        righe.append("  CSP %s" % riga)
    for tocco in esito["muti"]:
        righe.append("  MUTO %s %s | %s" % (tocco["scheda"], tocco["tag"], tocco["etichetta"]))
    return "\n".join(righe)


def _argomenti(dati):
    larghezza = int(dati[0]) if dati else LARGHEZZA
    versione = dati[1] if len(dati) > 1 else VERSIONE
    canale = dati[2] if len(dati) > 2 else CANALI[0]
    livello = dati[3] if len(dati) > 3 else LIVELLI[0]
    return larghezza, versione, canale, livello


def principale(dati):
    esito = esegui(RADICE, *_argomenti(dati))
    print(riassunto(esito))
    return 1 if esito["saltata"] else 0


if __name__ == "__main__":
    sys.exit(principale(sys.argv[1:]))
