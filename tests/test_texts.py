import json

from clashbot import i18n, texts

BOT = "FuturoCoCBot"
SITE = "clanboard.cloud"
KEYS = ("texts.reject.link", "texts.reject.phone", "texts.reject.bot")
IT = i18n.locale("it")


def check(body):
    return texts.filter(body, BOT, SITE)


def test_il_testo_semplice_e_i_nostri_indirizzi_passano():
    assert check("Si attacca tutti alle 21, niente scuse") == (True, None)
    assert check("") == (True, None)
    assert check("scrivimi su t.me/FuturoCoCBot") == (True, None)
    assert check("https://t.me/futurococbot e basta") == (True, None)
    assert check("la bacheca sta su https://clanboard.cloud/c/abc") == (True, None)
    assert check("scrivi a @FuturoCoCBot") == (True, None)
    assert check("scrivi a @futurococbot") == (True, None)


def test_i_link_di_fuori_tornano_indietro():
    assert check("guarda https://evil.example") == (False, "link")
    assert check("guarda bit.ly/x") == (False, "link")
    assert check("guarda www.sito.it") == (False, "link")
    assert check("iscriviti t.me/AltroClanBot") == (False, "link")
    assert check("prima clanboard.cloud poi evil.example") == (False, "link")


def test_i_numeri_di_telefono_tornano_indietro():
    assert check("chiamami +39 333 123 4567") == (False, "phone")
    assert check("chiamami 3331234567") == (False, "phone")
    assert check("siamo 30 contro 30 e vinciamo 45-12") == (True, None)


def test_gli_altri_bot_tornano_indietro():
    assert check("scrivi a @AltroBot") == (False, "bot")
    assert check("scrivi a @altrobot per i soldi") == (False, "bot")


def test_senza_sito_nostro_passa_solo_il_bot_del_clan():
    assert texts.filter("https://clanboard.cloud/c/abc", BOT, None) == (False, "link")
    assert texts.filter("t.me/FuturoCoCBot", BOT, None) == (True, None)
    assert texts.filter("t.me/FuturoCoCBot", None, None) == (False, "link")


def test_il_motivo_ha_la_sua_riga_nel_catalogo():
    assert texts.reason(IT, "link") == IT.t("texts.reject.link")
    assert texts.reason(IT, "phone") == IT.t("texts.reject.phone")
    assert texts.reason(IT, "bot") == IT.t("texts.reject.bot")
    assert "texts.reject" not in texts.reason(IT, "link")


def test_le_chiavi_nuove_stanno_in_tutti_i_venti_cataloghi():
    for code in i18n.LANGUAGES:
        with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
            catalogo = json.load(handle)
        assert [key for key in KEYS if key not in catalogo] == [], code
