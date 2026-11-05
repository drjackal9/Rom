from clashbot import compare


def snapshot(**kw):
    base = {"name": "Mario", "th": 15, "trophies": 5000, "best": 5200, "warStars": 900,
            "heroes": {"Barbarian King": 85, "Archer Queen": 85}, "donations": 1200,
            "attackWins": 40, "capital": 90000, "exp": 220, "labels": ["Farming"]}
    base.update(kw)
    return base


def test_i_valori_del_giocatore_hanno_tutte_le_righe():
    values = compare.player_values(snapshot())
    assert list(values) == [key for key, _ in compare.PLAYER_FIELDS]
    assert values["th"] == 15 and values["heroes"] == 170
    assert values["warstars"] == 900 and values["capital"] == 90000
    assert 0 < values["ready"] < 100


def test_il_vincitore_di_riga_e_chi_ha_il_valore_piu_alto():
    left = compare.player_values(snapshot(trophies=5000))
    right = compare.player_values(snapshot(name="Luigi", trophies=4800))
    rows = compare.compare(compare.PLAYER_FIELDS, left, right)
    trophies = next(r for r in rows if r["key"] == "trophies")
    assert trophies["winner"] == "left" and trophies["left"] == 5000
    pari = next(r for r in rows if r["key"] == "th")
    assert pari["winner"] is None


def test_i_valori_mancanti_valgono_zero_e_non_fanno_esplodere_nulla():
    rows = compare.compare(compare.PLAYER_FIELDS, compare.player_values(None),
                           compare.player_values(snapshot()))
    assert all(r["left"] == 0 for r in rows)
    assert all(r["winner"] == "right" for r in rows if r["right"])


def test_i_valori_del_clan_usano_solo_campi_sempre_presenti():
    clan_json = {"name": "Nostro Clan", "clanLevel": 12, "members": 47, "clanPoints": 41000,
                 "warWinStreak": 5, "warWins": 300, "requiredTownhallLevel": 13,
                 "requiredTrophies": 2000, "warLeague": {"name": "Crystal I"},
                 "labels": [{"name": "Clan Wars"}]}
    values = compare.clan_values(clan_json)
    assert list(values) == [key for key, _ in compare.CLAN_FIELDS]
    assert values["level"] == 12 and values["members"] == 47 and values["streak"] == 5
    assert compare.clan_values(None)["level"] == 0


def test_ogni_riga_di_confronto_ha_una_etichetta_nel_catalogo():
    from clashbot import i18n
    L = i18n.locale("it")
    for key, mode in compare.PLAYER_FIELDS + compare.CLAN_FIELDS:
        assert mode in ("n", "pct", "plain")
        assert L.t(f"vs.field.{key}") != f"[vs.field.{key}]", key
