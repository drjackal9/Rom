import asyncio
import re
from pathlib import Path

from clashbot import __main__ as cli, i18n, render, source, util

REPO = Path(__file__).resolve().parents[1]
LICENSE = REPO / "LICENSE"
L = i18n.locale("it")
EN = i18n.locale("en")


def test_la_licenza_e_il_testo_verbatim_della_agpl_3():
    raw = LICENSE.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    text = raw.decode("utf-8")
    assert 30000 < len(text) < 40000
    lines = text.splitlines()
    assert lines[0].strip() == "GNU AFFERO GENERAL PUBLIC LICENSE"
    assert lines[1].strip() == "Version 3, 19 November 2007"
    assert "Free Software Foundation, Inc." in text and "fsf.org" in text
    for heading in ("  0. Definitions.",
                    "  13. Remote Network Interaction; Use with the GNU General Public License.",
                    "  17. Interpretation of Sections 15 and 16.",
                    "How to Apply These Terms to Your New Programs"):
        assert heading in text, heading
    assert re.search(r"\bAlex\b", text) is None


def test_valid_https_accetta_solo_indirizzi_veri():
    for good in ("https://example.org", "https://example.org/clanboard", "https://a.b/c?d=1"):
        assert util.valid_https(good), good
    for bad in (None, "", "  ", "http://example.org", "https://", "ftp://example.org",
                "https://exa mple.org", "example.org"):
        assert not util.valid_https(bad), bad


def test_il_titolo_dice_nome_titolare_anno_e_licenza():
    for locale in (L, EN):
        text = source.notice(locale)
        assert source.NAME in text
        assert source.HOLDER in text
        assert source.YEAR in text
        assert source.LICENSE in text
        assert "{" not in text


def test_l_offerta_mostra_l_indirizzo_quando_c_e():
    text = source.offer(L, "https://example.org/clanboard")
    assert "https://example.org/clanboard" in text
    assert text != source.offer(L, None)


def test_l_offerta_dice_che_manca_invece_di_tacere():
    for missing in (None, "", "http://example.org", "non un indirizzo"):
        text = source.offer(L, missing)
        assert text == L.t("source.unpublished")
        assert "http" not in text
        assert "{" not in text


def test_l_indirizzo_viene_scappato():
    assert "&amp;" in source.offer(L, "https://example.org/a?b=1&c=2")
    assert "<" not in source.offer(L, "https://example.org/<b>")


def test_le_due_righe_stanno_insieme_in_quest_ordine():
    text = source.lines(L, "https://example.org/clanboard")
    assert text == source.notice(L) + "\n" + source.offer(L, "https://example.org/clanboard")


def test_la_scheda_di_sostegno_porta_sempre_licenza_e_sorgente():
    with_url = render.support_card(L, "https://ko-fi.com/x", "CODE", source="https://example.org/clanboard")
    assert render.quote(L.t("console.attribution")) in with_url
    assert render.quote(source.lines(L, "https://example.org/clanboard")) in with_url
    assert with_url.index(L.t("console.attribution")) < with_url.index(source.notice(L))
    bare = render.support_card(L, None, None)
    assert render.quote(source.lines(L, None)) in bare
    assert "https://" not in bare
    assert render.support_card(L, None, None) == render.support_card(L, "", "", "")


def test_le_tre_chiavi_nuove_sono_in_tutti_i_cataloghi():
    for code in sorted(i18n.LANGUAGES):
        locale = i18n.locale(code)
        for key in ("source.notice", "source.offer", "source.unpublished"):
            assert not locale.t(key).startswith("["), (code, key)


def finta_installazione(monkeypatch, risposte):
    salvati = []
    corde = iter(risposte)
    monkeypatch.setattr(cli, "read_value", lambda prompt, secret=True: next(corde))

    async def salva(store, kind, value):
        salvati.append((kind, value))

    monkeypatch.setattr(cli, "store_secret", salva)
    asyncio.run(cli.setup(None))
    assert next(corde, None) is None
    return salvati


def test_setup_non_si_ferma_se_l_indirizzo_del_sorgente_non_c_e_ancora(monkeypatch):
    salvati = finta_installazione(monkeypatch, ["t1", "k1", "", ""])
    assert [kind for kind, _ in salvati] == ["telegram_token", "coc_api_key"]


def test_setup_salva_l_indirizzo_quando_chi_installa_ce_l_ha(monkeypatch):
    salvati = finta_installazione(monkeypatch, ["t1", "k1", "https://example.org/clanboard", "7"])
    assert salvati[2] == ("source_url", "https://example.org/clanboard")
    assert salvati[3][0] == "owner_id"
