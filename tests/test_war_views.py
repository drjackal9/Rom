import json
from datetime import datetime, timezone

from clashbot import handlers, i18n, render, warstats

L = i18n.locale("it")
EN = i18n.locale("en")
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def rec(opponent="Clan Nemico", opp_tag="#ENEMY", result="win", end="20260912T100000.000Z",
        stars=6, opp_stars=2, destr=100.0, size=3, members=()):
    return {"kind": "war", "day": None, "endTime": end, "opponent": opponent, "opp_tag": opp_tag,
            "result": result, "stars": stars, "destr": destr, "opp_stars": opp_stars, "opp_destr": 26.0,
            "teamSize": size, "attacksPerMember": 2, "members": list(members)}


def mem(tag="#P1", name="Mario", th=15, attacks=(), conceded=(0, 0, 0)):
    return {"tag": tag, "name": name, "th": th, "missed": 0,
            "attacks": [{"stars": s, "destr": d, "d_th": t} for s, d, t in attacks],
            "def": {"stars": conceded[0], "destr": conceded[1], "hits": conceded[2]}}


def test_la_card_degli_avversari_mostra_bilancio_e_ultima_volta():
    rows = warstats.opponents([rec(), rec(end="20260905T100000.000Z", result="lose", stars=3, opp_stars=8)])
    text = render.foes_view(L, rows, NOW)
    assert "AVVERSARI AFFRONTATI" in text and "Clan Nemico" in text
    assert "1V" in text and "1P" in text and "9⭐" in text
    assert len(text) <= render.MAX_LEN
    assert "OPPONENTS FACED" in render.foes_view(EN, rows, NOW)
    assert L.t("foes.empty") in render.foes_view(L, [], NOW)


def test_la_card_delle_difese_apre_con_il_muro():
    rows = warstats.defense_rows([rec(members=[mem("#P1", "Mario", conceded=(0, 0, 1)),
                                               mem("#P2", "Luigi", conceded=(3, 100, 1))])])
    text = render.defense_view(L, rows, warstats.wall(rows), 1)
    assert "DIFESE" in text and "Muro" in text
    assert text.index("Mario") < text.index("Luigi")
    assert "ultime 1 guerra" in text
    assert L.t("defense.empty") in render.defense_view(L, [], None, 0)


def test_la_card_delle_triple_ha_sempre_le_cinque_righe():
    rows = warstats.th_rows([rec(members=[mem(attacks=[(3, 100, 15), (0, 10, 16), (3, 100, 13)])])])
    assert [r["delta"] for r in rows] == [-1, 0, 2]
    text = render.triples_view(L, rows, 1)
    assert "TRIPLE PER MUNICIPIO" in text
    labels = [L.t(f"triples.delta.{render.DELTA_KEYS[d]}") for d in (-2, -1, 0, 1, 2)]
    assert [label for label in labels if label in text] == labels
    assert text.index(labels[0]) < text.index(labels[2]) < text.index(labels[4])
    assert "100%" in text and "0%" in text
    assert L.t("triples.row", delta=labels[0], rate=L.pct(0, 0), attacks=0, avg=render.fixed(L, 0.0)) in text
    assert L.t("triples.empty") in render.triples_view(L, [], 0)


def test_lalbo_mostra_i_record_prima_delle_stagioni_e_regge_il_formato_vecchio():
    records = warstats.update_records(warstats.update_streak(None, 9),
                                      rec(stars=9, destr=100.0, size=3))
    hall = {"seasons": [{"season": "2026-08", "titles": {"MVP": ["Mario", 120]}}], "records": records}
    text = render.hall_view(L, hall)
    assert "Record del clan" in text
    assert text.index("Record del clan") < text.index("MVP")
    assert "Serie di vittorie" in text and "Guerre perfette" in text and "Clan Nemico" in text
    legacy = render.hall_view(L, [{"season": "2026-08", "titles": {"MVP": ["Mario", 120]}}])
    assert "MVP" in legacy and "Record del clan" not in legacy
    assert L.t("hall.empty") in render.hall_view(L, [])
    assert render.records_block(L, warstats.empty_records()) == ""


def test_i_comandi_nuovi_hanno_descrizione_bottone_e_vista():
    for name, alias in (("foes", "avversari"), ("defense", "difese"), ("triples", "triple")):
        assert (name, [alias]) in handlers.COMMANDS
        assert name in handlers.VIEWS
        for key in (f"cmd.{name}", f"menu.{name}"):
            assert EN.t(key) != f"[{key}]" and L.t(key) != f"[{key}]"
    assert "suggest" in handlers.VIEWS


BLOCK = ("foes.title", "foes.empty", "foes.row", "foes.legend", "defense.title", "defense.empty",
         "defense.row", "defense.wall", "defense.legend", "triples.title", "triples.empty",
         "triples.row", "triples.delta.up2", "triples.delta.up1", "triples.delta.same",
         "triples.delta.down1", "triples.delta.down2", "triples.legend",
         "records.title", "records.streak", "records.destr", "records.stars", "records.perfect",
         "suggest.title", "suggest.none", "suggest.done", "suggest.pick", "suggest.nobody",
         "suggest.more", "suggest.legend", "menu.foes", "menu.defense", "menu.triples", "menu.suggest",
         "cmd.foes", "cmd.defense", "cmd.triples", "title.Muro", "foe.title", "foe.body", "foe.last",
         "foe.result.win", "foe.result.lose", "foe.result.tie", "record.title", "record.tail",
         "war_end.defense", "war_end.defense_row", "war_end.held")


def catalog(code):
    with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def test_il_blocco_guerre_e_tradotto_in_tutte_le_lingue():
    english = catalog("en")
    for code in i18n.LANGUAGES:
        if code == "en":
            continue
        catalogue = catalog(code)
        same = [key for key in BLOCK if catalogue[key] == english[key]]
        assert same == [], (code, same)
