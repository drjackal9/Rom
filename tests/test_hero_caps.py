from clashbot import hero_caps
from clashbot.achievements import HERO_IT


def test_la_tabella_copre_tutti_gli_eroi_conosciuti():
    assert set(hero_caps.HERO_MAX) == set(HERO_IT)
    assert set(hero_caps.ORDER) == set(HERO_IT)


def test_ogni_eroe_ha_la_sua_sigla_corta_e_unica():
    assert set(hero_caps.SLUGS) == set(HERO_IT)
    assert len(set(hero_caps.SLUGS.values())) == len(hero_caps.SLUGS)
    assert all(slug.isalpha() and slug.islower() and len(slug) <= 3
               for slug in hero_caps.SLUGS.values())


def test_il_municipio_piu_alto_conosciuto_viene_dalla_tabella():
    assert hero_caps.TOP_TH == max(max(table) for table in hero_caps.HERO_MAX.values())


def test_i_tetti_non_scendono_mai_salendo_di_municipio():
    for hero, table in hero_caps.HERO_MAX.items():
        levels = [table[th] for th in sorted(table)]
        assert levels == sorted(levels), hero
        assert all(value > 0 for value in levels), hero


def test_cap_usa_il_tetto_piu_alto_gia_sbloccato():
    assert hero_caps.cap("Royal Champion", 12) == 0
    assert hero_caps.cap("Royal Champion", 13) == 25
    assert hero_caps.cap("Barbarian King", 99) == max(hero_caps.HERO_MAX["Barbarian King"].values())
    assert hero_caps.cap("Sconosciuto", 15) == 0
    assert hero_caps.cap("Barbarian King", None) == 0


def test_prontezza_al_massimo_e_cento():
    th = 13
    heroes = {hero: hero_caps.cap(hero, th) for hero in hero_caps.ORDER if hero_caps.cap(hero, th)}
    ready = hero_caps.readiness(heroes, th)
    assert ready["pct"] == 100.0
    assert [r["hero"] for r in ready["rows"]] == [h for h in hero_caps.ORDER if hero_caps.cap(h, th)]


def test_prontezza_a_zero_e_senza_eroi():
    assert hero_caps.readiness({}, 13)["pct"] == 0.0
    assert hero_caps.readiness(None, 5) == {"rows": [], "pct": 0.0}


def test_un_eroe_oltre_il_tetto_non_supera_il_cento():
    assert hero_caps.readiness({"Barbarian King": 99}, 7)["pct"] == 100.0


def test_gli_eroi_sbloccati_ma_non_ancora_costruiti_pesano_a_zero():
    ready = hero_caps.readiness({"Barbarian King": 30}, 9)
    assert [r["hero"] for r in ready["rows"]] == ["Barbarian King", "Archer Queen", "Minion Prince"]
    assert [r["level"] for r in ready["rows"]] == [30, 0, 0]
    assert ready["pct"] == 37.5


def test_prontezza_media_del_clan_solo_sui_membri_noti():
    players = {"#P1": {"th": 13, "heroes": {"Barbarian King": 75, "Archer Queen": 75,
                                            "Minion Prince": 60, "Grand Warden": 50,
                                            "Royal Champion": 25}},
               "#PX": {"th": 13, "heroes": {}}}
    assert hero_caps.clan_readiness(players, {"#P1": {"name": "Mario"}}) == 100.0
    assert hero_caps.clan_readiness({}, {"#P1": {}}) == 0.0
