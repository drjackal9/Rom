import re

from clashbot import acts, i18n
from clashbot.web import miniapp, static
from test_locales import CATALOGS, SHORT_MAX, forms

QUOTED = re.compile(r'"([^"\\\n]*)"')
KIND_SHAPE = re.compile(r"^[a-z]+(?:\.[a-z_]+)+$")
PLAIN_WORD = re.compile(r"words\.([A-Za-z_][A-Za-z0-9_]*)")
BOXED_WORD = re.compile(r'words\["([^"+]+)"\]')
HEAD_WORD = re.compile(r'words\["([a-z_]*)"\s*\+')
APP_KEYS = "web.app."
LOOSE = ("export.csv",)


def app_sources():
    found = static.manifest()["files"]
    return {name: body.decode() for name, body in found.items()
            if name.startswith("app/") and name.endswith(".js")}


def named(sources):
    seen = set()
    for text in sources.values():
        written = set(QUOTED.findall(text))
        seen |= written | {one + other for one in written for other in written}
    return seen


def orphans(kinds, sources):
    reached = named(sources)
    return sorted(kind for kind in kinds if kind not in reached)


def invented(sources):
    return sorted({lit for text in sources.values() for lit in QUOTED.findall(text)
                   if KIND_SHAPE.match(lit) and lit not in acts.ACTIONS})


def test_ogni_gesto_del_bot_ha_il_suo_bottone_nell_app():
    assert orphans(acts.ACTIONS, app_sources()) == sorted(LOOSE)


def test_il_controllo_si_accorge_di_un_gesto_senza_bottone():
    sources = app_sources()
    assert orphans(("finto.gesto", "target.set"), sources) == ["finto.gesto"]
    assert orphans(("welcome.set", "share.week", "settings.press"), sources) == []


def test_i_gesti_rimasti_scollegati_sono_dichiarati_uno_per_uno():
    for kind in LOOSE:
        assert kind in acts.ACTIONS, kind
    assert "export.csv" in acts.FIELDS
    assert any("export.csv" in text for text in app_sources().values())


def test_l_app_non_manda_piu_i_gesti_per_nome():
    for name, text in app_sources().items():
        for kind in ("link.claim", "link.approve", "link.reject"):
            assert kind not in text, (name, kind)


def test_nel_javascript_non_ci_sono_nomi_di_gesti_che_il_bot_non_conosce():
    assert invented(app_sources()) == []


def test_nessuna_parola_dell_app_nasce_nel_javascript():
    given = set(miniapp.words(i18n.locale("it")))
    read = set()
    heads = set()
    for text in app_sources().values():
        read |= set(PLAIN_WORD.findall(text)) | set(BOXED_WORD.findall(text))
        heads |= {head for head in HEAD_WORD.findall(text) if head}
    assert sorted(read - given) == []
    for head in sorted(heads):
        assert any(key.startswith(head) for key in given), head


def test_nel_javascript_dell_app_non_ci_sono_parole_scritte_a_mano():
    for name, text in app_sources().items():
        assert [ch for ch in text if ord(ch) > 127 and ch.isalpha()] == [], name


def test_le_parole_dell_app_stanno_corte_in_tutti_i_venti_cataloghi():
    assert len(CATALOGS) == len(i18n.LANGUAGES)
    for code in sorted(i18n.LANGUAGES):
        for key, value in CATALOGS[code].items():
            if not key.startswith(APP_KEYS):
                continue
            for form, text in forms(value).items():
                assert len(text) <= SHORT_MAX, (code, key, form, len(text))
