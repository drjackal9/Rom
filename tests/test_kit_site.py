import re
from pathlib import Path

import pytest

from clashbot import handlers, i18n, retention, source
from clashbot.web import app as web_app

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs" / "site"
PAGINE = ("index.html", "self-host.html", "privacy.html")
LINGUE = ("en", "it")
SEGNO = "__SOURCE__"
USCITE = ("https://t.me/ClanBoardBot", SEGNO)
SEZIONE = re.compile(r'<section id="([a-z0-9-]+)"')
ESTERNO = re.compile(r'(?:href|src)="(https?://[^"]*|__SOURCE__)"')
COMANDO = re.compile(r"<code>/([a-z][a-z0-9_]*)</code>")
BOTFATHER = ("newapp",)


def pagina(nome, lingua="en"):
    percorso = SITE / nome if lingua == "en" else SITE / lingua / nome
    return percorso.read_text(encoding="utf-8")


def known_commands():
    known = {name for name, _ in handlers.COMMANDS}
    known |= {alias for _, aliases in handlers.COMMANDS for alias in aliases}
    console = (REPO / "clashbot" / "console.py").read_text(encoding="utf-8")
    known |= set(re.findall(r'CommandHandler\("([a-z]+)"', console))
    return known | set(BOTFATHER)


CASI = [(nome, lingua) for nome in PAGINE for lingua in LINGUE]
IDS = [f"{lingua}/{nome}" for nome in PAGINE for lingua in LINGUE]


def test_il_sito_ha_sei_pagine_e_un_foglio_di_stile():
    assert (SITE / "style.css").is_file()
    for nome, lingua in CASI:
        percorso = SITE / nome if lingua == "en" else SITE / lingua / nome
        assert percorso.is_file(), percorso.name
    assert not list(SITE.rglob("*.png")) and not list(SITE.rglob("*.jpg"))
    assert sorted(p.suffix for p in SITE.rglob("*") if p.is_file()) == [".css"] + [".html"] * 6


@pytest.mark.parametrize("nome, lingua", CASI, ids=IDS)
def test_nessun_programma_e_nessuna_risorsa_esterna(nome, lingua):
    text = pagina(nome, lingua)
    for vietato in ("<script", "<iframe", "http://", "fonts.googleapis", "<img", "@import"):
        assert vietato not in text.lower(), (nome, lingua, vietato)
    for uscita in ESTERNO.findall(text):
        assert uscita.startswith(USCITE), (nome, lingua, uscita)
    atteso = "style.css" if lingua == "en" else "../style.css"
    assert f'href="{atteso}"' in text


@pytest.mark.parametrize("nome, lingua", CASI, ids=IDS)
def test_ogni_pagina_porta_licenza_e_attribuzione(nome, lingua):
    text = pagina(nome, lingua)
    assert f"Copyright (C) {source.YEAR} {source.HOLDER}" in text
    assert source.LICENSE in text
    assert i18n.locale(lingua).t("console.attribution") in text


@pytest.mark.parametrize("nome, lingua", CASI, ids=IDS)
def test_il_segno_del_sorgente_sta_solo_dentro_un_link(nome, lingua):
    text = pagina(nome, lingua)
    assert text.count(SEGNO) == text.count(f'href="{SEGNO}"') == 1


@pytest.mark.parametrize("nome, lingua", CASI, ids=IDS)
def test_le_pagine_nominano_solo_comandi_che_esistono(nome, lingua):
    assert set(COMANDO.findall(pagina(nome, lingua))) <= known_commands()


@pytest.mark.parametrize("nome", PAGINE)
def test_le_due_lingue_hanno_le_stesse_sezioni(nome):
    assert SEZIONE.findall(pagina(nome, "en")) == SEZIONE.findall(pagina(nome, "it"))
    assert SEZIONE.findall(pagina(nome, "en"))


@pytest.mark.parametrize("lingua", LINGUE)
def test_la_privacy_dice_i_numeri_della_ritenzione(lingua):
    text = pagina("privacy.html", lingua)
    assert str(retention.WAR_HISTORY_KEEP) in text
    assert str(retention.INACTIVE_CLAN_DAYS) in text
    assert "/unlink" in text or "/scollega" in text


@pytest.mark.parametrize("lingua", LINGUE)
def test_la_pagina_di_chi_ospita_spiega_come_si_accende_la_mini_app(lingua):
    text = pagina("self-host.html", lingua)
    assert '<section id="miniapp">' in text
    assert "<code>secret site_base</code>" in text
    assert "BotFather" in text and "<code>/newapp</code>" in text
    assert "<code>app</code>" in text and "&lt;site_base&gt;/app" in text
    assert any(percorso == "/app" for _, percorso, _ in web_app.ROUTES)


@pytest.mark.parametrize("lingua", LINGUE)
def test_la_pagina_di_chi_ospita_dice_i_segreti_che_si_danno_solo_dal_server(lingua):
    text = pagina("self-host.html", lingua)
    assert '<section id="gestione">' in text
    assert "<code>secret otp_reset</code>" in text
    assert "<code>secret channel_url</code>" in text


@pytest.mark.parametrize("lingua", LINGUE)
def test_la_pagina_di_chi_ospita_dice_dove_si_guarda_la_salute_della_copia(lingua):
    text = pagina("self-host.html", lingua)
    assert '<section id="ops">' in text
    assert "<code>secret owner_id</code>" in text
    assert "cgroup" in text and "status.json" in text
    assert not any(percorso.startswith("/ops") for _, percorso, _ in web_app.ROUTES)


@pytest.mark.parametrize("lingua", LINGUE)
def test_la_casa_dice_quante_lingue_e_dove_si_installa(lingua):
    text = pagina("index.html", lingua)
    assert str(len(i18n.LANGUAGES)) in text
    assert "self-host.html" in text and "privacy.html" in text


def test_la_pubblicazione_riempie_il_segno_e_non_lascia_tracce():
    workflow = (REPO / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "docs/site" in workflow
    assert "SORGENTE: ${{ github.server_url }}/${{ github.repository }}" in workflow
    assert f's|{SEGNO}|$SORGENTE|g' in workflow
    for nome, lingua in CASI:
        pubblicata = pagina(nome, lingua).replace(SEGNO, "https://esempio.invalid/alex/clanboard")
        assert SEGNO not in pubblicata
        assert 'href="https://esempio.invalid/alex/clanboard"' in pubblicata
