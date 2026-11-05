from clashbot import cards, i18n, share_cards

IT = i18n.locale("it")
ME = {"tag": "#P1", "name": "Mario",
      "profile": {"name": "Mario", "tag": "#P1", "th": 16, "trophies": 5400},
      "period": {"donated": 300, "war_stars": 12, "levels": 2, "score": 40}}
PEOPLE = {"climb": {"week": [{"tag": "#P1", "name": "Mario", "score": 40},
                             {"tag": "#P2", "name": "Luigi", "score": 21}]}}
RECAP = {"season": "2026-08",
         "me": {"score": 120, "wins": 40, "war_stars": 30, "donated": 900, "levels": 6,
                "rank": 1, "of": 2, "medals": ["th"]},
         "clan": {"people": 2, "score": 150, "medals": 1,
                  "top": {"name": "Luigi", "score": 150}}}


def test_la_card_della_settimana_porta_i_miei_numeri():
    spec = share_cards.week_card(IT, ME)
    assert spec["kind"] == share_cards.WEEK and spec["title"] == "Mario"
    assert [chip["value"] for chip in spec["chips"]] == ["300", "12", "2", "5.400"]
    assert spec["subtitle"] == IT.t("web.app.growth.week")
    assert cards.draw(spec)[:4] == b"\x89PNG"


def test_la_card_della_stagione_porta_la_stagione_e_solo_i_miei_numeri():
    spec = share_cards.season_card(IT, RECAP, "Mario")
    assert spec["kind"] == share_cards.SEASON and spec["title"] == "Mario"
    assert spec["subtitle"] == IT.t("web.app.recap.title", season="2026-08")
    assert [chip["value"] for chip in spec["chips"]] == ["900", "30", "6", "120"]
    assert "Luigi" not in str(spec) and spec["rows"] == []
    assert cards.draw(spec)[:4] == b"\x89PNG"


def test_la_card_del_clan_porta_chi_cresce():
    spec = share_cards.clan_card(IT, PEOPLE)
    assert spec["kind"] == share_cards.CLAN_WEEK
    assert [row["name"] for row in spec["rows"]] == ["Mario", "Luigi"]
    assert spec["rows"][0]["rank"] == IT.t("rank.n", n=1)
    assert cards.draw(spec)[:4] == b"\x89PNG"


def test_le_tre_card_si_costruiscono_in_tutte_le_venti_lingue():
    for code in i18n.LANGUAGES:
        L = i18n.locale(code)
        for spec in (share_cards.week_card(L, ME), share_cards.clan_card(L, PEOPLE),
                     share_cards.season_card(L, RECAP, "Mario")):
            assert spec["kind"] in cards.KINDS
            for value in (spec["title"], spec["subtitle"], spec["footer"]):
                assert "[" not in str(value), (code, value)


def test_senza_settimana_la_card_del_clan_resta_vuota():
    assert share_cards.clan_card(IT, {})["rows"] == []
    assert share_cards.week_card(IT, {})["title"] == ""
    assert share_cards.season_card(IT, {}, "")["chips"][0]["value"] == IT.n(None)
