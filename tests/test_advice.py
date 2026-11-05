from clashbot import advice
from clashbot.leaderboards import PODIUM
from clashbot.retention import WAR_HISTORY_KEEP


def hit(stars, th, destr=100.0):
    return {"stars": stars, "destr": destr, "defender": "#E1", "d_pos": 1, "d_th": th}


WARS = [
    {"members": [{"name": "Mario", "attacks": [hit(3, 16), hit(2, 15)]},
                 {"name": "Luigi", "attacks": [hit(1, 16)]}]},
    {"members": [{"name": "Mario", "attacks": [hit(3, 16)]},
                 {"name": "Peach", "attacks": [hit(2, 16), hit(3, 15)]}]},
    {"members": [{"name": "Luigi", "attacks": [hit(0, 16)]},
                 {"name": "Toad", "attacks": [{"stars": 3, "destr": 100.0}]}]},
]


def test_il_consiglio_pesa_le_stelle_per_municipio():
    found = advice.by_th(WARS)
    assert set(found) == {"16", "15"}
    assert found["16"]["avg_stars"] == 1.8
    assert found["15"]["avg_stars"] == 2.5


def test_il_consiglio_nomina_i_tre_che_ci_riescono_meglio():
    found = advice.by_th(WARS)
    assert found["16"]["best"] == [{"name": "Mario", "stars": 3.0, "count": 2},
                                   {"name": "Peach", "stars": 2.0, "count": 1},
                                   {"name": "Luigi", "stars": 0.5, "count": 2}]
    assert found["15"]["best"] == [{"name": "Peach", "stars": 3.0, "count": 1},
                                   {"name": "Mario", "stars": 2.0, "count": 1}]


def test_i_migliori_non_sono_mai_piu_di_tre():
    wars = [{"members": [{"name": name, "attacks": [hit(stars, 14)]}
                         for name, stars in (("Mario", 3), ("Luigi", 2), ("Peach", 1),
                                             ("Toad", 0))]}]
    found = advice.by_th(wars)
    assert len(found["14"]["best"]) == advice.BEST == PODIUM
    assert [row["name"] for row in found["14"]["best"]] == ["Mario", "Luigi", "Peach"]


def test_senza_attacchi_non_c_e_consiglio():
    assert advice.by_th([]) == {} and advice.by_th(None) == {}
    assert advice.by_th([{"members": []}, {}]) == {}


def test_il_consiglio_guarda_le_guerre_che_teniamo():
    wars = [{"members": [{"name": "Mario", "attacks": [hit(3, 16)]}]}] * WAR_HISTORY_KEEP
    wars += [{"members": [{"name": "Bowser", "attacks": [hit(0, 16)]}]}]
    found = advice.by_th(wars)
    assert [row["name"] for row in found["16"]["best"]] == ["Mario"]
    assert found["16"]["avg_stars"] == 3.0
