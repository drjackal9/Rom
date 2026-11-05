import json
import re
from string import Formatter

import pytest

from clashbot import i18n

TAGS = ("b", "i", "code", "blockquote")

SOURCES = ("en", "it")

NUMBERS = range(0, 201)

SHORT = ("agenda.item.", "web.app.", "web.bases.", "web.board.", "web.community.",
         "web.create.", "web.home.", "web.news.", "web.page.", "web.security.")

SHORT_MAX = 60

LONG_OK = {
    "web.home.unofficial":
        "riga Supercell obbligatoria alla lettera, in fondo anche a privacy e termini",
}

DIDACTIC = {
    "it": ("ti permette", "questa sezione", "questa schermata", "in questa pagina",
           "qui trovi", "puoi"),
    "en": ("lets you", "this section", "this screen", "on this page",
           "here you find", "you can"),
}

BLOCK = (
    "capital.eff.title", "capital.eff.section", "capital.eff.row", "capital.eff.legend",
    "capital.eff.empty", "capital.districts.title", "capital.districts.section",
    "capital.districts.row", "capital.districts.empty", "capital.gold.title", "capital.gold.row",
    "capital.gold.tail", "capital.gold.empty", "capital.hall.title", "capital.hall.level",
    "capital.hall.district_row", "capital.hall.goals", "capital.hall.goal_row",
    "capital.hall.goals_none", "capital.hall.none", "capital.level.hall.title",
    "capital.level.hall.body", "capital.level.district.title", "capital.level.district.body",
    "capital.skipped.title", "capital.skipped.body", "capital.skipped.next", "capital.skipped.tail",
    "menu.capital.raid", "menu.capital.eff", "menu.capital.districts", "menu.capital.gold",
    "menu.capital.hall", "setup.event.capital.gold", "setup.event.capital.skipped",
    "setup.event.capital.level", "cmd.games", "menu.games", "games.board.title", "games.board.sub",
    "games.board.total", "games.board.left", "games.board.row", "games.board.done",
    "games.board.zero", "games.board.record", "games.reminder.title", "games.reminder.body",
    "games.reminder.when", "games.reminder.tail", "games.none.title", "games.none.body",
    "setup.event.games.board", "setup.event.games.reminder", "games.end.title", "games.end.total",
    "games.end.previous", "games.end.podium", "games.end.podium_row", "games.end.record",
    "games.end.tail", "games.albo.title", "games.albo.row", "games.albo.empty", "menu.games.now",
    "menu.games.albo", "setup.event.games.end", "cmd.builderbase", "menu.builderbase",
    "builder.board.title", "builder.board.row", "builder.board.bh", "builder.board.delta",
    "builder.board.climber", "builder.board.empty", "builder.goal.title", "builder.goal.row",
    "setup.event.members.builder_board", "setup.event.members.builder_goal",
    "privacy.title", "privacy.intro", "privacy.account", "privacy.in_clan", "privacy.alerts_on",
    "privacy.alerts_off", "privacy.hidden_on", "privacy.hidden_off", "privacy.counts",
    "privacy.titles", "privacy.note_yes", "privacy.file", "privacy.file_failed",
    "privacy.btn_hide", "privacy.btn_show", "privacy.btn_forget", "privacy.hidden_done",
    "privacy.shown_done", "privacy.private_only", "privacy.throttle", "privacy.no_clan",
    "privacy.forget.title", "privacy.forget.body", "privacy.forget.stays",
    "privacy.forget.btn_yes", "privacy.forget.done", "privacy.forget.nothing", "cmd.mydata",
    "cmd.forgetme", "guide.title", "guide.body", "guide.btn_link", "feedback.title",
    "feedback.intro", "feedback.cat.idea", "feedback.cat.bug", "feedback.cat.translation",
    "feedback.cat.other", "feedback.ask", "feedback.sent", "feedback.failed",
    "feedback.too_soon", "feedback.private_only", "feedback.owner.title", "feedback.owner.row",
    "cmd.guide", "cmd.feedback", "news.title", "news.body", "news.on", "news.off",
    "news.btn_on", "news.btn_off", "news.only_leaders", "setup.event.system.news", "cmd.news",
    "support.twitch", "tip.title", "tip.body", "tip.label", "tip.btn", "tip.btn_private",
    "tip.where", "tip.thanks.title", "tip.thanks.body", "tip.btn_refund", "tip.refunded",
    "tip.refund_failed", "tip.failed", "tip.private_only", "survey.question", "survey.opt.great",
    "survey.opt.good", "survey.opt.meh", "survey.opt.no", "panel.survey",
    "setup.event.system.survey", "share.title", "share.body", "share.text", "share.btn_share",
    "share.btn_newbot",
    "owner.key.partial.title", "owner.key.partial.body", "owner.key.line",
    "owner.key.invalid_ip.short", "owner.key.rejected.short", "owner.key.back.title",
    "owner.key.back.body", "console.stats_keys", "console.stats_restore_ok",
    "console.stats_restore_ko", "console.stats_restore_never",
)


def load(code):
    path = i18n.LOCALE_DIR / f"{code}.json"
    assert path.exists(), f"manca il catalogo {code}.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


CATALOGS = {code: load(code) for code in i18n.LANGUAGES}


def forms(value):
    if isinstance(value, dict):
        return value
    return {"other": value}


def placeholders(text):
    return {(name, spec or "", conv or "") for _, name, spec, conv in Formatter().parse(text) if name}


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_catalog_parses_and_is_flat(code):
    catalog = CATALOGS[code]
    assert isinstance(catalog, dict) and catalog
    for key, value in catalog.items():
        assert isinstance(key, str) and key
        if isinstance(value, dict):
            assert value, key
            for form, text in value.items():
                assert form in ("zero", "one", "two", "few", "many", "other"), (code, key, form)
                assert isinstance(text, str), (code, key, form)
        else:
            assert isinstance(value, str), (code, key)


@pytest.mark.parametrize("code", sorted(set(i18n.LANGUAGES) - {"en"}))
def test_same_keys_as_english(code):
    assert set(CATALOGS[code]) == set(CATALOGS["en"]), code


@pytest.mark.parametrize("code", sorted(set(i18n.LANGUAGES) - {"en"}))
def test_same_placeholders_as_english(code):
    english = CATALOGS["en"]
    for key, value in CATALOGS[code].items():
        expected = placeholders(forms(english[key])["other"])
        for form, text in forms(value).items():
            assert placeholders(text) == expected, (code, key, form)


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_html_tags_are_balanced(code):
    for key, value in CATALOGS[code].items():
        for form, text in forms(value).items():
            for tag in TAGS:
                assert text.count(f"<{tag}>") == text.count(f"</{tag}>"), (code, key, form, tag)


def test_italian_and_english_are_complete_catalogs():
    assert len(CATALOGS["it"]) > 400
    assert CATALOGS["it"]["war.title.war"] == "GUERRA"
    assert CATALOGS["en"]["war.title.war"] == "WAR"


def test_le_chiavi_doppie_del_blocco_web_sono_state_unite():
    english = CATALOGS["en"]
    coppie = (("web.home.status", "web.status.title"), ("web.home.board", "web.board.title"),
              ("web.board.level", "web.page.level"),
              ("web.app.nowar", "web.page.no_war"), ("web.ics.war", "ics.war"))
    for gone, kept in coppie:
        assert gone not in english, gone
        assert kept in english, kept
    for code in sorted(i18n.LANGUAGES):
        for gone, _ in coppie:
            assert gone not in CATALOGS[code], (code, gone)
        assert "web.home.translate" not in CATALOGS[code], code


PER_NOME = ("feed.link.claimed", "feed.link.refused", "feed.link.waiting")


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_le_chiavi_dei_collegamenti_per_nome_escono_coi_loro_gesti(code):
    for key in PER_NOME:
        assert key not in CATALOGS[code], (code, key)
    assert "feed.link.lost" in CATALOGS[code], code


def wording(text):
    return re.sub(r"</?[a-z]+>", "", re.sub(r"\{[^{}]*\}", "", text))


def translatable(value):
    return any(any(ch.isalpha() for ch in wording(text)) for text in forms(value).values())


@pytest.mark.parametrize("code", sorted(set(i18n.LANGUAGES) - set(SOURCES)))
def test_block_keys_are_not_left_in_english(code):
    english = CATALOGS["en"]
    for key in BLOCK:
        if not translatable(english[key]):
            continue
        shared = set(forms(CATALOGS[code][key]).values()) & set(forms(english[key]).values())
        assert not shared, (code, key, sorted(shared))


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_plural_keys_carry_every_form_the_language_needs(code):
    needed = {i18n.plural_form(code, number) for number in NUMBERS}
    for key, value in CATALOGS[code].items():
        if isinstance(value, dict):
            assert needed <= set(value), (code, key, sorted(needed - set(value)))


def test_every_key_renders_without_placeholders_left_over():
    for code in sorted(i18n.LANGUAGES):
        L = i18n.locale(code)
        for key in CATALOGS[code]:
            text = L.t(key, n=2)
            assert isinstance(text, str) and not text.startswith("[")


SHAPES = (
    re.compile(r'^  "[A-Za-z0-9_.]+": (?:".*"|\{),?$'),
    re.compile(r'^  "[A-Za-z0-9_.]+": \{"(?:zero|one|two|few|many|other)": ".*\},?$'),
    re.compile(r'^    "(?:zero|one|two|few|many|other)": ".*",?$'),
    re.compile(r"^  \},?$"),
)


def difetto(raw):
    if raw.startswith(b"\xef\xbb\xbf"):
        return "segno d'ordine in testa"
    if b"\r" in raw or not raw.endswith(b"\n"):
        return "fine riga"
    lines = raw.decode("utf-8").splitlines()
    if lines[0] != "{" or lines[-1] != "}":
        return "involucro"
    for number, line in enumerate(lines[1:-1], start=2):
        if not any(shape.match(line) for shape in SHAPES):
            return f"riga {number}: {line[:40]}"
    return None


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_il_file_ha_la_forma_che_le_modifiche_riga_per_riga_richiedono(code):
    raw = (i18n.LOCALE_DIR / f"{code}.json").read_bytes()
    assert difetto(raw) is None, (code, difetto(raw))


@pytest.mark.parametrize("code", sorted(set(i18n.LANGUAGES) - {"en"}))
def test_le_chiavi_stanno_nello_stesso_ordine_dell_inglese(code):
    assert list(CATALOGS[code]) == list(CATALOGS["en"]), code


def riscritture():
    a_due = json.dumps(CATALOGS["en"], ensure_ascii=False, indent=2)
    return {
        "una riga sola": json.dumps(CATALOGS["en"], ensure_ascii=False) + "\n",
        "indentazione a quattro": json.dumps(CATALOGS["en"], ensure_ascii=False, indent=4) + "\n",
        "senza newline in fondo": a_due,
        "fine riga di windows": a_due.replace("\n", "\r\n") + "\r\n",
        "segno d'ordine in testa": "\ufeff" + a_due + "\n",
    }


def test_un_catalogo_riscritto_con_uno_strumento_perde_la_forma():
    for modo, dump in riscritture().items():
        assert difetto(dump.encode("utf-8")) is not None, modo


def chiavi_corte(code):
    return [key for key in CATALOGS[code] if key.startswith(SHORT)]


@pytest.mark.parametrize("code", sorted(SOURCES))
def test_le_parole_dell_app_e_della_home_stanno_in_una_riga_corta(code):
    for key in chiavi_corte(code):
        if key in LONG_OK:
            continue
        for form, text in forms(CATALOGS[code][key]).items():
            assert len(text) <= SHORT_MAX, (code, key, form, len(text), text)


def test_le_eccezioni_lunghe_sono_dichiarate_una_per_una():
    assert set(LONG_OK) <= set(chiavi_corte("it"))
    for key, motivo in LONG_OK.items():
        assert motivo
        lunghezza = max(len(text) for code in SOURCES
                        for text in forms(CATALOGS[code][key]).values())
        assert lunghezza > SHORT_MAX, key


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_le_parole_dell_app_e_della_home_non_spiegano(code):
    vietate = DIDACTIC["it"] if code == "it" else DIDACTIC["en"]
    for key in chiavi_corte(code):
        for form, text in forms(CATALOGS[code][key]).items():
            basso = text.lower()
            for frase in vietate:
                assert frase not in basso, (code, key, form, frase)
