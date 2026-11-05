import functools
from pathlib import Path

import pytest

from clashbot import acts, i18n
from clashbot.web import miniapp
from tests.e2e import prova_app

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (320, 360, 390, 430)
TG_VERSIONS = ("7.0", "9.0")
LARGA = 390
CORRENTE = "9.0"
VIVO = "vivo"
CADE = "cade"
GESTORE = "gestore"
VISTE = ("estraneo", "ridotta", "piena", "gestore")
LIVELLO_DI = {"estraneo": miniapp.OUTSIDER, "ridotta": miniapp.REDUCED,
              "piena": miniapp.FULL_VIEW, "gestore": miniapp.BOSS}

MUTI_PER_DISEGNO = {
    "campo": "campo di testo: il tocco porta il fuoco, non cambia il disegno",
    "collegamento": "collegamento: porta il file o la pagina fuori dall'app",
    "chip": "chip gia attivo: il tocco ripete la scelta in corso",
}

PIU_TOCCHI = "serve piu di un tocco dalla scheda: il giro riparte pulito prima di ogni tocco"
MODULO = "serve un testo scritto prima dell'invio"
ESEMPIO = "lo stato di esempio non ha la voce che la accende"
PRINCIPALE = "sta sul bottone principale di Telegram, fuori dal DOM della pagina"
AVVIO = "parte all'apertura dell'app, non da un tocco"
BOT = "azione del bot: nell'app il dato esce da un collegamento firmato"

NON_DA_BOTTONE = {
    "app.opened": AVVIO,
    "award.vote": PIU_TOCCHI,
    "base.accept": ESEMPIO,
    "base.propose": MODULO,
    "base.reject": ESEMPIO,
    "clan.pause": PIU_TOCCHI,
    "clan.resume": ESEMPIO,
    "cwl.bonus.toggle": PIU_TOCCHI,
    "cwl.lineup.set": PIU_TOCCHI,
    "cwl.roster.set": PIU_TOCCHI,
    "data.forget": PIU_TOCCHI,
    "delegates.clear": PIU_TOCCHI,
    "duel.accept": ESEMPIO,
    "duel.challenge": PRINCIPALE,
    "export.csv": BOT,
    "family.create": MODULO,
    "family.derby": PIU_TOCCHI,
    "family.invite": MODULO,
    "family.tourney": PIU_TOCCHI,
    "goal.set": PIU_TOCCHI,
    "guess.answer": PIU_TOCCHI,
    "link.verify": MODULO,
    "note.set": MODULO,
    "prediction.set": PIU_TOCCHI,
    "quiz.answer": PIU_TOCCHI,
    "report.send": PIU_TOCCHI,
    "rules.set": MODULO,
    "schedule.add": MODULO,
    "settings.press": PIU_TOCCHI,
    "share.season": ESEMPIO,
    "share.war": ESEMPIO,
    "target.free": PIU_TOCCHI,
    "target.mirror": PRINCIPALE,
    "target.note": MODULO,
    "target.swap": PIU_TOCCHI,
    "undo.apply": ESEMPIO,
    "welcome.set": MODULO,
}


@functools.lru_cache(maxsize=None)
def _giro(larghezza, versione, canale, livello):
    return prova_app.esegui(ROOT, larghezza, versione, canale, livello)


def _prova(larghezza=LARGA, versione=CORRENTE, canale=VIVO, livello=GESTORE):
    esito = _giro(larghezza, versione, canale, livello)
    if esito["saltata"]:
        pytest.skip(esito["saltata"])
    return esito


def _per_disegno(tocco):
    classi = tocco["cls"].split()
    if tocco["tag"] in ("input", "textarea", "select"):
        return "campo"
    if tocco["tag"] == "a" and tocco["href"]:
        return "collegamento"
    if "chip" in classi and "on" in classi:
        return "chip"
    return None


def test_a_ogni_larghezza_niente_esce_dallo_schermo():
    fuori = {}
    fogli = {}
    for larghezza in WIDTHS:
        esito = _prova(larghezza=larghezza)
        fuori[larghezza] = esito["fuori"]
        fogli[larghezza] = esito["fogli"]
    assert fuori == {larghezza: [] for larghezza in WIDTHS}
    assert all(fogli[larghezza] for larghezza in WIDTHS), fogli


def test_ogni_versione_di_telegram_apre_l_app_senza_errori():
    errori = {versione: _prova(versione=versione)["errori"] for versione in TG_VERSIONS}
    assert errori == {versione: [] for versione in TG_VERSIONS}


def test_nessun_tocco_viola_la_politica_della_pagina():
    violazioni = {versione: _prova(versione=versione)["csp"] for versione in TG_VERSIONS}
    assert violazioni == {versione: [] for versione in TG_VERSIONS}


def test_col_canale_vivo_ogni_controllo_vero_fa_qualcosa():
    esito = _prova()
    assert esito["controlli"] == esito["bersagli"] and esito["controlli"] > 0
    senza_motivo = [tocco for tocco in esito["muti"]
                    if _per_disegno(tocco) not in MUTI_PER_DISEGNO]
    assert senza_motivo == [], [
        (tocco["scheda"], tocco["tag"], tocco["cls"], tocco["etichetta"])
        for tocco in senza_motivo
    ]


def test_ogni_azione_e_raggiunta_da_un_tocco_o_ha_il_suo_motivo():
    esito = _prova()
    mancanti = sorted(set(acts.FIELDS) - set(esito["azioni"]))
    assert [kind for kind in mancanti if kind not in NON_DA_BOTTONE] == []
    assert sorted(NON_DA_BOTTONE) == mancanti
    assert all(NON_DA_BOTTONE.values())


def test_col_canale_caduto_nessun_tocco_parte_e_nessuno_si_rompe():
    esito = _prova(canale=CADE)
    assert esito["azioni"] == []
    assert esito["errori"] == [] and esito["csp"] == [] and esito["fuori"] == []
    assert esito["controlli"] > 0


def _dove(tocco):
    return (tocco["scheda"], tocco["i"])


def test_col_canale_tornato_la_coda_parte_da_sola():
    ripreso = _prova(canale=CADE)["ripristino"]
    assert ripreso["coda"] is True and ripreso["tasto"] is True, ripreso
    assert ripreso["inviati"] and ripreso["errori"] == [], ripreso
    assert ripreso["coda_dopo"] is False, ripreso


def test_col_canale_caduto_ogni_tocco_che_parlava_al_bot_finisce_in_coda():
    vivo = _prova()
    caduto = _prova(canale=CADE)
    partiti = {_dove(tocco) for tocco in vivo["tocchi"] if tocco["inviati"]}
    accodati = {_dove(tocco) for tocco in caduto["tocchi"] if tocco["coda"]}
    assert partiti, vivo["azioni"]
    assert sorted(partiti - accodati) == []
    assert caduto["coda"] == len(accodati) >= len(partiti)


def test_ai_quattro_livelli_nessun_gesto_esce_dal_suo_livello():
    esiti = {vista: _prova(livello=vista) for vista in VISTE}
    for vista, esito in esiti.items():
        mio = miniapp.VIEWS.index(LIVELLO_DI[vista])
        troppo = [kind for kind in esito["azioni"]
                  if miniapp.VIEWS.index(miniapp.needed(kind)) > mio]
        assert troppo == [], (vista, troppo)
        assert esito["errori"] == [], (vista, esito["errori"])
        assert esito["csp"] == [] and esito["fuori"] == [], vista
    conti = [esiti[vista]["controlli"] for vista in VISTE]
    assert conti[0] < conti[1] < conti[2] <= conti[3], conti


def test_il_tasto_dei_termini_sta_al_primo_collegamento():
    parole = miniapp.words(i18n.locale(prova_app.LINGUA))
    for larghezza in (LARGA, WIDTHS[0]):
        esito = _prova(larghezza=larghezza, livello="estraneo")
        tasti = [tocco for tocco in esito["tocchi"] if tocco["etichetta"] == parole["link_terms"]]
        assert tasti and all(tocco["tag"] == "button" and tocco["cambi"] for tocco in tasti)
        vie = {tocco["href"] for tocco in esito["tocchi"] if tocco["tag"] == "a"}
        assert {"/terms", "/privacy"} <= vie, vie
        assert esito["fuori"] == [] and esito["errori"] == [], larghezza


def test_il_cancello_esce_non_zero_quando_la_prova_si_salta(monkeypatch, capsys):
    monkeypatch.setattr(prova_app, "CHROME", "/mai/esistito/Chrome")
    codice = prova_app.principale([])
    detto = capsys.readouterr().out
    assert codice != 0, detto
    assert detto.startswith("SALTATA: Chrome non trovato"), detto
