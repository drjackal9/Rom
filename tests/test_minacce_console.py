import json
from pathlib import Path

PORTA = "console"
MINACCE = Path(__file__).resolve().parents[1] / "docs/minacce.json"
STRIDE = ("spoofing", "tampering", "repudiation", "information_disclosure",
          "denial_of_service", "elevation_of_privilege")


def sorgenti():
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(Path(__file__).parent.glob("test_*.py"))}


def test_le_sei_minacce_della_porta_del_console_hanno_ognuna_la_sua_prova():
    porta = json.loads(MINACCE.read_text(encoding="utf-8"))[PORTA]
    assert len(porta) == 6
    assert sorted(row["stride"] for row in porta) == sorted(STRIDE)
    testi = sorgenti()
    for row in porta:
        assert row["minaccia"] and row["chiude"]
        assert any(("def %s(" % row["prova"]) in text for text in testi.values()), row["prova"]


def test_le_due_porte_non_si_scambiano_le_prove():
    rows = json.loads(MINACCE.read_text(encoding="utf-8"))
    nomi = {porta: {row["prova"] for row in righe} for porta, righe in rows.items()}
    assert set(rows) == {"app", PORTA}
    assert nomi["app"] & nomi[PORTA] == set()


def test_ogni_minaccia_del_console_copre_anche_segnala_e_termini():
    porta = json.loads(MINACCE.read_text(encoding="utf-8"))[PORTA]
    testi = sorgenti()
    viste = set()
    for row in porta:
        voce = row["segnala"]
        assert voce["minaccia"] and voce["chiude"], row["stride"]
        assert any(("def %s(" % voce["prova"]) in text for text in testi.values()), voce["prova"]
        viste.add(voce["prova"])
    assert len(viste) == len(STRIDE)


def test_ogni_minaccia_del_console_copre_anche_la_creazione():
    porta = json.loads(MINACCE.read_text(encoding="utf-8"))[PORTA]
    testi = sorgenti()
    viste = set()
    for row in porta:
        voce = row["crea"]
        assert voce["minaccia"] and voce["chiude"], row["stride"]
        assert any(("def %s(" % voce["prova"]) in text for text in testi.values()), voce["prova"]
        viste.add(voce["prova"])
    assert len(viste) == len(STRIDE)


def test_ogni_minaccia_del_console_copre_anche_la_porta_del_bot_clanboard():
    porta = json.loads(MINACCE.read_text(encoding="utf-8"))[PORTA]
    testi = sorgenti()
    viste = set()
    for row in porta:
        voce = row["porta"]
        assert voce["minaccia"] and voce["chiude"], row["stride"]
        assert any(("def %s(" % voce["prova"]) in text for text in testi.values()), voce["prova"]
        viste.add(voce["prova"])
    assert len(viste) == len(STRIDE)


def test_la_divulgazione_alla_creazione_nomina_la_prova_che_guarda_i_log():
    porta = json.loads(MINACCE.read_text(encoding="utf-8"))[PORTA]
    voce = next(row["crea"] for row in porta if row["stride"] == "information_disclosure")
    testa = "def %s(" % voce["prova"]
    testo = next(text for text in sorgenti().values() if testa in text)
    corpo = testo.split(testa)[1].split("\ndef ")[0]
    assert "caplog.text" in corpo, voce["prova"]


def test_la_creazione_nomina_il_codice_del_gruppo_di_chi_non_guida_piu():
    porta = json.loads(MINACCE.read_text(encoding="utf-8"))[PORTA]
    voce = next(row["crea"] for row in porta if row["stride"] == "denial_of_service")
    assert "link_clan" in voce["chiude"] and "codice" in voce["minaccia"]
    testa = "def %s(" % voce["prova"]
    testo = next(text for text in sorgenti().values() if testa in text)
    assert "run_code(" in testo.split(testa)[1].split("\ndef ")[0], voce["prova"]
