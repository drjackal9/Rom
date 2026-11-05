import json

from clashbot import cards, events, i18n, scoring
from fixtures import BASE_MEMBERS, clan_json, war_json

IT = i18n.locale("it")
EN = i18n.locale("en")
NUOVE = (
    "card.brand", "card.footer", "card.footer_site", "card.war.title", "card.war.subtitle",
    "card.war.subtitle_cwl", "card.title_row", "card.player.subtitle", "card.label.th",
    "card.label.league", "card.label.trophies", "card.label.best", "card.label.war_stars",
    "card.label.donations", "card.label.heroes", "card.label.war", "card.war_pref.in",
    "card.war_pref.out", "card.war_pref.unknown",
)
ATTACCHI = {"#P1": [("#E1", 3, 100), ("#E2", 3, 100)], "#P2": [("#E3", 2, 74)]}
SNAP = {"name": "Mario", "th": 16, "league": "Leggenda", "trophies": 5600, "best": 5800,
        "warStars": 1200, "heroes": {"Barbarian King": 95, "Archer Queen": 95, "Grand Warden": 70},
        "donations": 3000, "warPref": "in"}


def guerra_finita():
    return events.war_snapshot(war_json("warEnded", our_attacks=ATTACCHI))


def stagione():
    season = scoring.empty_season("2026-09")
    scoring.apply_war(season, events.war_record(guerra_finita()))
    scoring.apply_donations(season, events.member_snapshot(clan_json(BASE_MEMBERS)))
    return season


def test_la_card_di_fine_guerra_racconta_il_risultato():
    war = guerra_finita()
    spec = cards.build_war_end(IT, war, "win", tag="#CLAN1")
    assert spec["kind"] == "war_end" and spec["code"] == "it" and spec["result"] == "win"
    assert spec["title"] == "VITTORIA! 8 - 0"
    assert spec["subtitle"] == "Nostro Clan contro Clan Nemico"
    assert spec["score"]["left"] == {"name": "Nostro Clan", "stars": 8,
                                     "destr": IT.pct(war["clan"]["destr"])}
    assert spec["score"]["right"]["name"] == "Clan Nemico" and spec["score"]["right"]["stars"] == 0
    assert [(r["rank"], r["name"], r["value"], r["extra"]) for r in spec["rows"]] == [
        ("1.", "Mario", "6", "100%"), ("2.", "Luigi", "2", "74%")]
    assert len(spec["rows"]) <= cards.TOP_ROWS
    assert spec["footer"] == "ClanBoard · #CLAN1"


def test_la_card_di_fine_guerra_in_inglese_in_cwl_e_col_sito():
    war = guerra_finita()
    assert cards.build_war_end(EN, war, "lose")["title"] == "DEFEAT 8 - 0"
    assert cards.build_war_end(EN, war, "tie")["title"] == "DRAW 8 - 0"
    assert cards.build_war_end(EN, war, "win")["subtitle"] == "Nostro Clan vs Clan Nemico"
    cwl = cards.build_war_end(IT, war, "win", "cwl", 3, tag="#CLAN1", site="clanboard.it")
    assert "GIORNATA 3" in cwl["subtitle"] and "Nostro Clan contro Clan Nemico" in cwl["subtitle"]
    assert cwl["footer"] == "ClanBoard · clanboard.it"


def test_la_card_dei_titoli_usa_i_titoli_che_esistono_gia():
    titoli = scoring.titles(stagione())
    spec = cards.build_season(IT, "2026-09", titoli, tag="#CLAN1")
    assert spec["kind"] == "season" and spec["title"] == "TITOLI DEL MESE"
    assert spec["subtitle"] == "settembre 2026"
    assert spec["rows"][0]["name"] == "MVP · Mario"
    assert spec["rows"][0]["value"] == IT.n(titoli["MVP"][1])
    assert all(row["rank"] is None for row in spec["rows"])
    assert len(spec["rows"]) == len(titoli)
    assert cards.build_season(IT, "2026-09", {})["rows"] == []
    dallalbo = cards.build_season(EN, "2026-08", {"MVP": ["Mario", 80]})
    assert dallalbo["subtitle"] == "August 2026" and dallalbo["rows"][0]["value"] == "80"


def test_la_card_del_giocatore_mostra_le_otto_targhette():
    spec = cards.build_player(IT, SNAP, "#P1", "Futuro")
    assert spec["kind"] == "player" and spec["title"] == "Mario"
    assert spec["subtitle"] == "#P1 · Futuro"
    assert [(c["label"], c["value"]) for c in spec["chips"]] == [
        ("Municipio", "16"), ("Lega", "Leggenda"), ("Trofei", "5.600"), ("Record", "5.800"),
        ("Stelle di guerra", "1.200"), ("Donazioni", "3.000"), ("Eroi", "95/95/70"),
        ("Guerra", "Dentro")]
    assert len(spec["chips"]) == cards.CHIP_COLUMNS * 2
    assert spec["rows"] == [] and spec["footer"] == "ClanBoard"


def test_la_card_del_giocatore_regge_i_dati_che_mancano():
    vuota = cards.build_player(EN, None, "#P9")
    assert vuota["title"] == "#P9" and vuota["subtitle"] == "#P9"
    assert [c["value"] for c in vuota["chips"]] == ["?", "no league", "?", "?", "?", "?", "?", "?"]
    fuori = cards.build_player(EN, {"name": "Luigi", "warPref": "out"}, "#P2", "Futuro")
    assert fuori["chips"][-1]["value"] == "Out"


def test_le_tre_card_si_costruiscono_in_tutte_le_venti_lingue():
    war, titoli = guerra_finita(), scoring.titles(stagione())
    for code in i18n.LANGUAGES:
        L = i18n.locale(code)
        for spec in (cards.build_war_end(L, war, "win", tag="#CLAN1"),
                     cards.build_season(L, "2026-09", titoli, tag="#CLAN1"),
                     cards.build_player(L, SNAP, "#P1", "Futuro")):
            assert spec["kind"] in cards.KINDS
            for value in (spec["title"], spec["subtitle"], spec["footer"]):
                assert "[" not in str(value), (code, value)
            if code in ("it", "en", "ar", "ru", "zh-Hans"):
                assert cards.draw(spec)[:4] == b"\x89PNG"


def test_nelle_card_non_entrano_emoji():
    war, titoli = guerra_finita(), scoring.titles(stagione())
    for L in (IT, EN):
        for spec in (cards.build_war_end(L, war, "win", tag="#CLAN1"),
                     cards.build_season(L, "2026-09", titoli, tag="#CLAN1"),
                     cards.build_player(L, SNAP, "#P1", "Futuro")):
            testi = [spec["title"], spec["subtitle"], spec["footer"]]
            testi += [row["name"] for row in spec["rows"]] + [row["value"] for row in spec["rows"]]
            testi += [c["label"] for c in spec.get("chips") or []]
            testi += [c["value"] for c in spec.get("chips") or []]
            for testo in testi:
                assert all(ord(ch) < 0x2190 for ch in str(testo)), testo


def test_le_chiavi_nuove_stanno_in_tutti_i_venti_cataloghi():
    for code in i18n.LANGUAGES:
        with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
            catalogo = json.load(handle)
        mancanti = [key for key in NUOVE if key not in catalogo]
        assert mancanti == [], (code, mancanti)


DA_TRADURRE = ("card.war.subtitle", "card.war.subtitle_cwl", "card.label.th", "card.label.league",
               "card.label.trophies", "card.label.best", "card.label.war_stars",
               "card.label.donations", "card.label.heroes", "card.label.war",
               "card.war_pref.in", "card.war_pref.out")


def catalogo(code):
    with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def test_il_blocco_delle_card_e_scritto_in_italiano_e_inglese():
    inglese, italiano = catalogo("en"), catalogo("it")
    uguali = [key for key in DA_TRADURRE if italiano[key] == inglese[key]]
    assert uguali == []


def test_il_blocco_delle_card_aspetta_la_fase_delle_traduzioni():
    inglese = catalogo("en")
    for code in i18n.LANGUAGES:
        if code in ("en", "it"):
            continue
        mio = catalogo(code)
        diversi = [key for key in DA_TRADURRE if mio[key] != inglese[key]]
        assert diversi == [], (code, diversi)
