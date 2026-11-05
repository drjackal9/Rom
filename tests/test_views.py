import pytest

from clashbot import views


def test_le_sezioni_e_i_valori_sono_quelli_della_spec():
    assert views.SECTIONS == ("plans", "bases", "league", "numbers")
    assert views.VALUES == ("approved", "in_war", "managers")


def test_i_valori_di_partenza_sono_quelli_della_spec():
    fresh = views.state_of(None)
    assert fresh[views.PLANS] == views.IN_WAR
    assert [fresh[name] for name in (views.BASES, views.LEAGUE, views.NUMBERS)] == [
        views.EVERYONE, views.EVERYONE, views.EVERYONE]
    assert fresh[views.FAMILY] is False


def test_un_valore_storto_torna_a_quello_di_partenza():
    fresh = views.state_of({"plans": "chiunque", "bases": None, "league": 7,
                            "numbers": "managers", "family_score": "si"})
    assert fresh[views.PLANS] == views.IN_WAR
    assert fresh[views.BASES] == views.EVERYONE
    assert fresh[views.LEAGUE] == views.EVERYONE
    assert fresh[views.NUMBERS] == views.STAFF_ONLY
    assert fresh[views.FAMILY] is True


def test_si_muove_un_interruttore_alla_volta():
    moved = views.set_one(views.state_of(None), views.BASES, views.STAFF_ONLY)
    assert moved[views.BASES] == views.STAFF_ONLY
    assert moved[views.PLANS] == views.IN_WAR
    assert moved[views.LEAGUE] == views.EVERYONE


def test_una_sezione_o_un_valore_che_non_esiste_non_si_muove():
    fresh = views.state_of(None)
    with pytest.raises(ValueError):
        views.set_one(fresh, "piani", views.EVERYONE)
    with pytest.raises(ValueError):
        views.set_one(fresh, views.BASES, "tutti")


def test_il_punteggio_alla_famiglia_si_accende_e_si_spegne():
    fresh = views.state_of(None)
    on = views.toggle_family(fresh)
    assert on[views.FAMILY] is True
    assert views.toggle_family(on)[views.FAMILY] is False


def test_i_gestori_vedono_ogni_sezione_comunque():
    shut = {name: views.STAFF_ONLY for name in views.SECTIONS}
    assert all(views.sees(shut, name, True, False) for name in views.SECTIONS)


def test_solo_chi_e_in_guerra_vede_i_piani_di_partenza():
    fresh = views.state_of(None)
    assert views.sees(fresh, views.PLANS, False, True) is True
    assert views.sees(fresh, views.PLANS, False, False) is False


def test_basi_lega_e_numeri_di_partenza_li_vedono_tutti_gli_approvati():
    fresh = views.state_of(None)
    assert [views.sees(fresh, name, False, False)
            for name in (views.BASES, views.LEAGUE, views.NUMBERS)] == [True, True, True]


def test_con_l_interruttore_sui_gestori_l_approvato_non_vede_piu():
    shut = views.set_one(views.state_of(None), views.LEAGUE, views.STAFF_ONLY)
    assert views.sees(shut, views.LEAGUE, False, True) is False
