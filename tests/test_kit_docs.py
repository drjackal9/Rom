import re
from pathlib import Path

import pytest

from clashbot import handlers, i18n, retention, source

REPO = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "README.it.md")
KIT_DOCS = DOCS + ("CONTRIBUTING.md", "SECURITY.md", "CLA.md")
HEADING = re.compile(r"^(#{1,3}) (.+)$", re.M)
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"```\n(.*?)```", re.S)
COMMAND = re.compile(r"`/([a-z][a-z0-9_]*)`")
CROSS = {"README.md", "README.it.md"}


def read(name):
    return (REPO / name).read_text(encoding="utf-8")


def known_commands():
    known = {name for name, _ in handlers.COMMANDS}
    known |= {alias for _, aliases in handlers.COMMANDS for alias in aliases}
    console = (REPO / "clashbot" / "console.py").read_text(encoding="utf-8")
    known |= set(re.findall(r'CommandHandler\("([a-z]+)"', console))
    return known


@pytest.mark.parametrize("name", DOCS)
def test_ogni_readme_dice_licenza_titolare_e_attribuzione(name):
    text = read(name)
    code = "en" if name == "README.md" else "it"
    assert source.NAME in text
    assert f"Copyright (C) {source.YEAR} {source.HOLDER}" in text
    assert source.LICENSE in text
    assert "LICENSE" in LINK.findall(text)
    assert i18n.locale(code).t("console.attribution") in text


@pytest.mark.parametrize("name", DOCS)
def test_ogni_readme_dice_i_numeri_veri(name):
    text = read(name)
    assert str(len(i18n.LANGUAGES)) in text
    assert str(retention.WAR_HISTORY_KEEP) in text
    assert str(retention.INACTIVE_CLAN_DAYS) in text


@pytest.mark.parametrize("name", DOCS)
def test_ogni_readme_dice_dell_app_dentro_telegram(name):
    text = read(name)
    assert "Mini App" in text
    assert "secret site_base" in text


@pytest.mark.parametrize("name", DOCS)
def test_ogni_readme_dice_i_segreti_che_si_danno_solo_dal_server(name):
    text = read(name)
    assert "secret otp_reset" in text
    assert "secret channel_url" in text


@pytest.mark.parametrize("name", KIT_DOCS)
def test_nessun_documento_del_kit_scrive_indirizzi_assoluti_o_comandi_finti(name):
    text = read(name)
    assert "github.com" not in text
    assert "http://" not in text
    assert set(COMMAND.findall(text)) <= known_commands()


@pytest.mark.parametrize("name", DOCS)
def test_ogni_readme_nomina_i_comandi_del_bot(name):
    assert COMMAND.findall(read(name))


def test_contributing_dice_i_comandi_veri_delle_prove():
    text = read("CONTRIBUTING.md")
    assert "python -m pyflakes clashbot tests" in text
    assert "node tests/js/run.js" in text
    assert "python -m pytest -q -p no:cacheprovider tests" in text
    assert "requirements-dev.txt" in text
    assert str(len(i18n.LANGUAGES)) in text


def test_security_non_chiede_mai_segreti_e_dice_dove_segnalare():
    text = read("SECURITY.md")
    assert "Report a vulnerability" in text
    for parola in ("token", "chiavi", "dump"):
        assert parola in text.lower()


def test_il_cla_dice_le_tre_concessioni_nelle_due_lingue():
    text = read("CLA.md")
    for titolo in ("Grant of rights", "Patent license", "Originality", "Notice",
                   "Concessione dei diritti", "Licenza sui brevetti", "Originalità", "Avvertenza",
                   "Entity", "Ente"):
        assert titolo in text, titolo
    assert source.HOLDER in text
    assert "legal" in text.lower() or "legale" in text.lower()


def test_il_workflow_del_cla_ferma_le_pull_request_non_firmate():
    text = (REPO / ".github" / "workflows" / "cla.yml").read_text(encoding="utf-8")
    assert "contributor-assistant/github-action" in text
    assert "pull_request_target" in text and "issue_comment" in text
    assert "cla-signatures" in text and "signatures/cla.json" in text
    assert "path-to-document" in text and "CLA.md" in text


def test_contributing_e_i_readme_portano_al_cla():
    for name in ("CONTRIBUTING.md",) + DOCS:
        assert "CLA.md" in read(name), name


def test_i_due_readme_hanno_la_stessa_struttura():
    en, it = read("README.md"), read("README.it.md")
    assert [level for level, _ in HEADING.findall(en)] == [level for level, _ in HEADING.findall(it)]
    assert FENCE.findall(en) == FENCE.findall(it)
    assert set(LINK.findall(en)) - CROSS == set(LINK.findall(it)) - CROSS
    assert set(COMMAND.findall(en)) == set(COMMAND.findall(it))
