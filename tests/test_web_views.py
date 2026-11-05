from clashbot import settings, views
from clashbot.web import miniapp, payload
from test_web_door import FULL, OUT, door_of, page_with, seat_of, vault
from test_web_miniapp import CLAN, INFO, MEMBERS, NOW, SEATS, SECTIONS, WAR

SEZIONI = miniapp.SECTION_KEYS
TUTTE = tuple(key for keys in SEZIONI.values() for key in keys)


def pagina(box, switches=None):
    found = page_with(box, **door_of(box, approved=[FULL, 777]))
    found["bases"] = {"clan": [], "library": {"videos": []}}
    found["attack_videos"] = {"#E1": []}
    found["cwl"] = {"day": 1}
    found["idle"] = [{"tag": "#P3", "days": 9}]
    found["growth"] = {"days": []}
    found["record"] = {"wars": 30}
    found["ours"] = [{"tag": "#P3"}]
    if switches is not None:
        found[views.KIND] = switches
    return found


def vista(page, box, uid):
    seat = seat_of(page, uid, box)
    return miniapp.view_for(page, seat, miniapp.level_of(page, seat))


def test_senza_interruttori_valgono_i_valori_di_partenza_della_spec(tmp_path):
    box = vault(tmp_path)
    seen = vista(pagina(box), box, FULL)
    assert "rows" in seen
    assert [key for key in ("bases", "cwl", "idle", "growth", "record")
            if key not in seen] == []


def test_l_interruttore_sui_gestori_toglie_la_sezione_all_approvato(tmp_path):
    box = vault(tmp_path)
    switches = views.set_one(views.state_of(None), views.LEAGUE, views.STAFF_ONLY)
    assert "cwl" not in vista(pagina(box, switches), box, FULL)


def test_l_interruttore_su_tutti_apre_i_piani_anche_fuori_dalla_formazione(tmp_path):
    box = vault(tmp_path)
    page = pagina(box)
    page["ours"] = [{"tag": "#P1"}]
    assert "rows" not in vista(page, box, FULL)
    page[views.KIND] = views.set_one(views.state_of(None), views.PLANS, views.EVERYONE)
    assert "rows" in vista(page, box, FULL)


def test_l_interruttore_sui_numeri_toglie_assenze_medie_e_primati(tmp_path):
    box = vault(tmp_path)
    switches = views.set_one(views.state_of(None), views.NUMBERS, views.STAFF_ONLY)
    seen = vista(pagina(box, switches), box, FULL)
    assert [key for key in SEZIONI[views.NUMBERS] if key in seen] == []


def test_gli_interruttori_non_tolgono_niente_al_gestore(tmp_path):
    box = vault(tmp_path)
    page = pagina(box, {name: views.STAFF_ONLY for name in views.SECTIONS})
    seen = miniapp.view_for(page, seat_of(page, 777, box), miniapp.BOSS)
    assert [key for key in TUTTE if key not in seen] == []


def test_gli_interruttori_non_escono_mai_dalla_risposta_di_chi_non_comanda(tmp_path):
    box = vault(tmp_path)
    page = pagina(box, views.state_of(None))
    for uid in (OUT, FULL):
        assert views.KIND not in miniapp.state_body(page, seat_of(page, uid, box), now=0)


def test_il_gestore_riceve_gli_interruttori_per_poterli_muovere(tmp_path):
    box = vault(tmp_path)
    page = pagina(box, views.state_of(None))
    body = miniapp.state_body(page, seat_of(page, 777, box), now=0)
    assert body[views.KIND][views.PLANS] == views.IN_WAR


def test_il_carico_dell_app_porta_gli_interruttori():
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome"})
    shut = views.set_one(views.state_of(None), views.BASES, views.STAFF_ONLY)
    found = payload.app_payload(CLAN, conf, INFO, MEMBERS, WAR, "war", None, {}, SEATS,
                                SECTIONS, {}, NOW, views=shut)
    assert found[views.KIND] == shut


def test_il_capo_muove_un_interruttore_e_resta_scritto(tmp_path):
    from test_intents_manager import CHIEF, applied, manager_store
    from test_web_publish import CLAN as CLAN_A
    import asyncio
    store = manager_store(tmp_path)
    assert applied(store, "view.set", {"section": views.LEAGUE, "value": views.STAFF_ONLY},
                   uid=CHIEF) is True
    stored = asyncio.run(store.get_state(CLAN_A.alias, views.KIND))
    assert views.state_of(stored)[views.LEAGUE] == views.STAFF_ONLY
    assert len(store.logs) == 1


def test_l_anziano_non_muove_gli_interruttori(tmp_path):
    from clashbot import reasons
    from test_intents_manager import ELDER, applied, manager_store
    store = manager_store(tmp_path)
    assert applied(store, "view.set", {"section": views.BASES, "value": views.STAFF_ONLY},
                   uid=ELDER) == reasons.NOT_MANAGER


def test_una_sezione_inventata_non_muove_niente(tmp_path):
    from clashbot import reasons
    from test_intents_manager import CHIEF, applied, manager_store
    store = manager_store(tmp_path)
    assert applied(store, "view.set", {"section": "piani", "value": views.EVERYONE},
                   uid=CHIEF) == reasons.BAD


def test_il_punteggio_alla_famiglia_parte_spento_e_il_capo_lo_accende(tmp_path):
    import asyncio
    from test_intents_manager import CHIEF, applied, manager_store
    from test_web_publish import CLAN as CLAN_A
    store = manager_store(tmp_path)
    assert views.state_of(None)[views.FAMILY] is False
    assert applied(store, "family.score.toggle", {}, uid=CHIEF) is True
    stored = asyncio.run(store.get_state(CLAN_A.alias, views.KIND))
    assert views.state_of(stored)[views.FAMILY] is True


def test_l_anziano_non_accende_il_punteggio_alla_famiglia(tmp_path):
    from clashbot import reasons
    from test_intents_manager import ELDER, applied, manager_store
    store = manager_store(tmp_path)
    assert applied(store, "family.score.toggle", {}, uid=ELDER) == reasons.NOT_MANAGER


def test_il_battito_pubblica_gli_interruttori_salvati(tmp_path):
    from test_intents_manager import CHIEF, applied, manager_store, page_of
    store = manager_store(tmp_path)
    assert applied(store, "view.set", {"section": views.NUMBERS, "value": views.STAFF_ONLY},
                   uid=CHIEF) is True
    assert page_of(store)[views.KIND][views.NUMBERS] == views.STAFF_ONLY
