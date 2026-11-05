import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from clashbot import door, feed, intents, publish, reasons, recruit_block, views
from clashbot.crypto import Vault
from clashbot.events_registry import LINK_NEWS
from clashbot.settings import LIMITED, MANAGER
from clashbot.web import app as web_app, http, live, miniapp, payload
from test_web_miniapp import (AppStore, NOW, SEATS, SLUG, body, init, sample_page,
                              serve)
from test_web_status import request
from test_locales import CATALOGS
import test_intents_manager as casella

MINACCE = Path(__file__).resolve().parents[1] / "docs/minacce.json"
PORTA = "app"
STRIDE = ("spoofing", "tampering", "repudiation", "information_disclosure",
          "denial_of_service", "elevation_of_privilege")
ALTRO_TOKEN = "111:token-di-un-altro-bot"
BADGE = "https://api-assets.clashofclans.com/badges/200/uno.png"
RECLUTA = {"open": True, "free": 7, "requirement": 15, "page_on": True, "code": "ab12cd"}
OUT = 555
LOW = 999
FULL = 888
BOSS = 777
BANNED_UID = 666
ROUTES = ("/app/%s", "/app/%s/state", "/app/%s/live", "/app/%s/feed", "/app/%s/mydata.json",
          "/app/%s/export.csv", "/app/%s/preview", "/app/%s/act")
GESTO = {"kind": "availability.set", "choice": "in", "id": "gesto1"}
CASELLA_ORA = casella.NOW


def vault(tmp_path):
    return Vault(tmp_path)


def mark(box, uid):
    return payload.mark_for(box, SLUG, uid)


def door_marks(conia, known=(), approved=(), banned=(), war_from=0):
    state = door.state_of(None)
    for uid in known:
        state = door.saw(state, uid)
    for uid in approved:
        state = door.approve(state, uid, NOW.timestamp(), war_from)
    for uid in banned:
        state = door.ban(state, uid)
    return door.marks(state, conia)


def door_of(box, known=(), approved=(), banned=(), war_from=0):
    return door_marks(lambda uid: mark(box, uid), known, approved, banned, war_from)


def page_with(box, **kw):
    seats = {str(BOSS): dict(SEATS["777"]),
             str(FULL): {"tag": "#P3", "name": "Peach", "level": None, "verified": True},
             str(LOW): {"tag": "#P9", "name": "Fuori", "level": None, "verified": False},
             str(BANNED_UID): {"tag": "#P2", "name": "Luigi", "level": None, "verified": True}}
    found = body(seats=seats)
    found["recruit"] = dict(RECLUTA)
    found["clan"]["badge"] = BADGE
    found.update(kw)
    return found


def seat_with(page, uid, impronta):
    seat = (page.get("seats") or {}).get(str(uid))
    found = dict(seat or {}, uid=uid, who="Chi", mark=impronta)
    if not seat:
        found["level"] = None
    return found


def seat_of(page, uid, box):
    return seat_with(page, uid, mark(box, uid))


def levels(page, box, *uids):
    return [miniapp.level_of(page, seat_of(page, uid, box)) for uid in uids]


def test_i_quattro_livelli_di_vista_sono_quelli_della_spec(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, known=[LOW], approved=[BOSS, FULL]))
    assert levels(page, box, OUT, LOW, FULL, BOSS) == [miniapp.OUTSIDER, miniapp.REDUCED,
                                                       miniapp.FULL_VIEW, miniapp.BOSS]


def test_chi_e_nel_gruppo_senza_villaggio_provato_resta_ridotto(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, known=[OUT], approved=[]))
    assert levels(page, box, OUT) == [miniapp.REDUCED]


def test_il_villaggio_provato_senza_il_si_di_un_gestore_resta_ridotto(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    assert levels(page, box, FULL) == [miniapp.REDUCED]


def test_finche_il_bot_non_ha_pubblicato_la_porta_il_verificato_in_rosa_e_pieno(tmp_path):
    box = vault(tmp_path)
    page = page_with(box)
    assert miniapp.APPROVED not in page
    assert levels(page, box, FULL, LOW, OUT) == [miniapp.FULL_VIEW, miniapp.REDUCED,
                                                 miniapp.OUTSIDER]


def test_l_ex_membro_scende_a_ridotta_alla_lettura_della_rosa(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[FULL]))
    page["members"] = [row for row in page["members"] if row.get("tag") != "#P3"]
    assert levels(page, box, FULL) == [miniapp.REDUCED]


def test_il_membro_di_un_altro_clan_con_questo_slug_e_un_estraneo(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    altrove = {"uid": OUT, "who": "Chi", "level": None,
               "mark": payload.mark_for(box, "0123456789abcdef", OUT)}
    assert miniapp.level_of(page, altrove) == miniapp.OUTSIDER


def test_l_anziano_limitato_e_un_gestore(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box))
    page["seats"][str(FULL)]["level"] = LIMITED
    assert levels(page, box, FULL) == [miniapp.BOSS]
    assert page["seats"][str(BOSS)]["level"] == MANAGER


def test_l_estraneo_riceve_solo_nome_stemma_e_requisiti(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box))
    found = miniapp.state_body(page, seat_of(page, OUT, box), now=NOW.timestamp())
    assert found["level"] == miniapp.OUTSIDER
    assert found["clan"]["name"] and found["clan"]["badge"] == BADGE
    assert found["recruit"]["requirement"] == 15 and found["recruit"]["code"] == "ab12cd"
    for key in ("war", "rows", "ours", "members", "bases", "cwl", "agenda", "events", "seats"):
        assert key not in found, key
    assert found["war_view"] is None and found["people"]["rows"] == []


def test_le_chiavi_dei_livelli_escono_tutte_dal_payload():
    found = body(record={"wars": 30}, growth={"days": []})
    elenchi = [("OUT_KEYS", miniapp.OUT_KEYS), ("LOW_KEYS", miniapp.LOW_KEYS),
               ("WAR_KEYS", miniapp.WAR_KEYS)]
    elenchi += [(nome, miniapp.SECTION_KEYS[nome]) for nome in sorted(miniapp.SECTION_KEYS)]
    assert {nome for nome, _ in elenchi} >= set(miniapp.SECTION_KEYS)
    for nome, chiavi in elenchi:
        assert set(chiavi) <= set(found), (nome, sorted(set(chiavi) - set(found)))


def test_la_vista_ridotta_non_riceve_guerra_basi_lega_piani_ne_prenotazioni(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, known=[LOW]))
    found = miniapp.state_body(page, seat_of(page, LOW, box), now=NOW.timestamp())
    assert found["level"] == miniapp.REDUCED
    assert found["members"] and found["agenda"] is not None
    for key in ("war", "rows", "ours", "bases", "cwl", "record", "advice", "attack_videos"):
        assert key not in found, key
    assert found["war_view"] is None and found["next"] is None


def test_l_approvato_fuori_dalla_formazione_vede_il_punteggio_non_i_piani(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[FULL]))
    page["ours"] = [row for row in page["ours"] if row.get("tag") != "#P3"]
    found = miniapp.state_body(page, seat_of(page, FULL, box), now=NOW.timestamp())
    assert found["level"] == miniapp.FULL_VIEW
    assert found["war_view"]["us"]["stars"] >= 0 and found["war_view"]["phase"] == "inWar"
    assert found["war_view"]["enemy"] == [] and found["war_view"]["free"] == []
    assert "rows" not in found


def test_chi_e_in_formazione_riceve_i_piani(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[FULL]))
    found = miniapp.state_body(page, seat_of(page, FULL, box), now=NOW.timestamp())
    assert found["rows"] and found["war_view"]["enemy"]


def test_l_approvato_dalla_prossima_guerra_non_vede_quella_in_corso(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[FULL]))
    dopo = int(page["war"]["start"]) + 1
    page.update(door_of(box, approved=[FULL], war_from=dopo))
    found = miniapp.state_body(page, seat_of(page, FULL, box), now=NOW.timestamp())
    assert found["level"] == miniapp.FULL_VIEW
    assert found["war_view"] is None and "war" not in found and "ours" not in found
    assert found["members"]


def test_la_guerra_senza_inizio_resta_chiusa_a_chi_vale_dalla_prossima(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[FULL]))
    dopo = int(page["war"]["start"]) + 1
    page.update(door_of(box, approved=[FULL], war_from=dopo))
    guerra = {key: value for key, value in page["war"].items() if key != "start"}
    for senza in ({}, {"start": 0}, {"start": None}, {"start": "domani"}):
        page["war"] = dict(guerra, **senza)
        found = miniapp.state_body(page, seat_of(page, FULL, box), now=NOW.timestamp())
        assert found["war_view"] is None, senza
        assert "war" not in found and "ours" not in found and "rows" not in found, senza


def test_nessuna_risposta_porta_uid_tag_o_impronte_di_altri(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, known=[LOW], approved=[BOSS, FULL], banned=[BANNED_UID]))
    for uid in (OUT, LOW):
        found = miniapp.state_body(page, seat_of(page, uid, box), now=NOW.timestamp())
        testo = json.dumps(found, ensure_ascii=False)
        for leak in ("#P1", "#P2", "#P3", mark(box, BOSS), mark(box, uid), '"seats"'):
            assert leak not in testo, leak
        assert "mark" not in found["me"] and "uid" not in found["me"]


def test_l_impronta_del_visitatore_non_esce_mai_dal_server(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[FULL]))
    found = miniapp.state_body(page, seat_of(page, FULL, box), now=NOW.timestamp())
    testo = json.dumps(found, ensure_ascii=False)
    assert mark(box, FULL) not in testo
    assert miniapp.APPROVED not in found and miniapp.KNOWN not in found
    assert miniapp.BANNED not in found


def test_il_flusso_sei_tu_e_sparito_dallo_stato(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box))
    found = miniapp.state_body(page, seat_of(page, OUT, box), now=NOW.timestamp())
    assert "roster" not in found
    assert "candidates" not in found["me_view"]


def run(store, path, uid, method="GET", data=None):
    return serve(store, path, method=method, uid=uid, data=data)


def test_la_porta_apre_al_titolare_e_chiude_all_estraneo_su_ogni_rotta(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    assert run(store, f"/app/{SLUG}", BOSS).status == 200
    assert run(store, f"/app/{SLUG}/state", BOSS).status == 200
    assert run(store, f"/app/{SLUG}/feed", OUT).status == 401
    assert run(store, f"/app/{SLUG}/mydata.json", OUT).status == 401
    assert run(store, f"/app/{SLUG}/export.csv", FULL).status == 401
    assert run(store, f"/app/{SLUG}/preview?kind=welcome", FULL).status == 401


def test_lo_stato_dell_estraneo_non_porta_la_guerra(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    res = run(store, f"/app/{SLUG}/state", OUT)
    found = json.loads(res.body)
    assert res.status == 200 and found["level"] == miniapp.OUTSIDER
    assert "war" not in found and "members" not in found


def test_il_bandito_riceve_403_su_tutte_e_nove_le_rotte(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, BANNED_UID], banned=[BANNED_UID]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    visti = []
    for shape in ROUTES:
        path = shape % SLUG
        method = "POST" if path.endswith("/act") else "GET"
        data = GESTO if method == "POST" else None
        visti.append(run(store, path, BANNED_UID, method=method, data=data).status)
    aperto = run(store, "/app", BANNED_UID).status
    assert visti == [403] * len(ROUTES) and aperto == 403
    assert run(store, f"/app/{SLUG}/state", BOSS).status == 200


def test_il_bando_chiude_il_canale_gia_aperto(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    dopo = page_with(box, **door_of(box, approved=[BOSS, FULL], banned=[FULL]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    site = web_app.Site(store)
    firma = f"X-Init-Data: {init(FULL, code=SLUG)}\r\n".encode()
    req = request(f"/app/{SLUG}/live", headers=firma)

    async def go():
        res = await site.router(req)
        gen = res.events.__aiter__()
        primo = await gen.__anext__()
        store.pages[(SLUG, payload.APP)] = dopo
        site.pages.pop(SLUG, None)
        await site.refresh_page(SLUG)
        try:
            return primo, await asyncio.wait_for(gen.__anext__(), 1)
        except StopAsyncIteration:
            return primo, None

    primo, secondo = asyncio.run(go())
    assert json.loads(primo.split("data: ")[1])["level"] == miniapp.FULL_VIEW
    assert secondo is None, secondo
    assert site.live.get(SLUG) in (None, set())
    assert run(store, f"/app/{SLUG}/live", FULL).status == 403


def test_il_canale_non_si_apre_se_il_primo_evento_non_c_e(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    site = web_app.Site(store)

    async def niente():
        return None

    async def go():
        gen = live.stream(site, SLUG, str(BOSS), niente).__aiter__()
        eventi = []
        for _ in range(2):
            try:
                eventi.append(await asyncio.wait_for(gen.__anext__(), 1))
            except StopAsyncIteration:
                break
            except TimeoutError:
                eventi.append("fermo")
                break
        await gen.aclose()
        return eventi, site.live.get(SLUG)

    eventi, rimasti = asyncio.run(go())
    assert eventi == [] and rimasti in (None, set())


def test_l_interruttore_chiuso_toglie_le_chiavi_al_canale_gia_aperto(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    page["cwl"] = {"day": 1}
    dopo = dict(page, **{views.KIND: {views.LEAGUE: views.STAFF_ONLY}})
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    site = web_app.Site(store)
    firma = f"X-Init-Data: {init(FULL, code=SLUG)}\r\n".encode()
    req = request(f"/app/{SLUG}/live", headers=firma)

    async def go():
        res = await site.router(req)
        gen = res.events.__aiter__()
        primo = await gen.__anext__()
        store.pages[(SLUG, payload.APP)] = dopo
        site.pages.pop(SLUG, None)
        await site.refresh_page(SLUG)
        try:
            return primo, await asyncio.wait_for(gen.__anext__(), 1)
        except (StopAsyncIteration, TimeoutError):
            return primo, None

    primo, secondo = asyncio.run(go())
    prima_corpo = json.loads(primo.split("data: ")[1])
    assert set(miniapp.LEAGUE_KEYS) <= set(prima_corpo)
    assert secondo is not None, "il battito dopo l'interruttore non e' arrivato"
    dopo_corpo = json.loads(secondo.split("data: ")[1])
    assert dopo_corpo["level"] == miniapp.FULL_VIEW
    for chiave in miniapp.LEAGUE_KEYS:
        assert chiave not in dopo_corpo, chiave


def test_senza_la_firma_di_telegram_non_c_e_nessun_posto(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    falsa = f"X-Init-Data: {init(BOSS, code=SLUG, token=ALTRO_TOKEN)}\r\n".encode()
    for via, metodo in ((f"/app/{SLUG}/state", "GET"), (f"/app/{SLUG}/act", "POST")):
        req = request(via, metodo, headers=falsa)
        if metodo == "POST":
            req.body = json.dumps(GESTO).encode()
        assert asyncio.run(web_app.Site(store).router(req)).status == 401, via
    assert store.intents == []
    buono = run(store, f"/app/{SLUG}/act", BOSS, method="POST", data=GESTO)
    assert buono.status == 200 and store.intents[0][2]["by"] == BOSS


def test_il_martellamento_sulle_rotte_dell_app_prende_429(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    fermo = time.monotonic()
    site = web_app.Site(store, lambda: fermo)
    firma = f"X-Init-Data: {init(BOSS, code=SLUG)}\r\n".encode()
    visti = [asyncio.run(site.router(request(f"/app/{SLUG}/state", headers=firma))).status
             for _ in range(http.READ_RATE + 1)]
    assert visti[:http.READ_RATE] == [200] * http.READ_RATE
    assert visti[-1] == 429


def test_il_gesto_della_vista_ridotta_e_rifiutato_col_codice_giusto(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, known=[LOW], approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    res = run(store, f"/app/{SLUG}/act", LOW, method="POST", data=GESTO)
    assert res.status == 403 and json.loads(res.body)["error"] == reasons.NOT_APPROVED
    fuori = run(store, f"/app/{SLUG}/act", OUT, method="POST", data=GESTO)
    assert json.loads(fuori.body)["error"] == reasons.NOT_LINKED


def test_il_permesso_non_si_chiede_senza_la_pagina(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[FULL]))
    seat = seat_of(page, FULL, box)
    with pytest.raises(TypeError):
        miniapp.may("target.set", seat)
    assert miniapp.may("target.set", seat, page) is True


def test_la_pagina_dell_app_si_apre_anche_senza_firma_perche_la_firma_arriva_dopo(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS], banned=[BANNED_UID]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    res = asyncio.run(web_app.Site(store).router(request(f"/app/{SLUG}")))
    assert res.status == 200
    senza = asyncio.run(web_app.Site(store).router(request(f"/app/{SLUG}/state")))
    assert senza.status == 401
    firmato = run(store, f"/app/{SLUG}/state", OUT)
    assert firmato.status == 200 and json.loads(firmato.body)["level"] == miniapp.OUTSIDER


def test_senza_cassaforte_la_porta_si_chiude_invece_di_aprirsi(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS], banned=[BANNED_UID]))
    aperto = AppStore({(SLUG, payload.APP): page}, vault=box)
    assert run(aperto, f"/app/{SLUG}/state", BANNED_UID).status == 403
    cieco = AppStore({(SLUG, payload.APP): page}, vault=None)
    assert run(cieco, f"/app/{SLUG}/state", BANNED_UID).status == 403
    assert run(cieco, f"/app/{SLUG}/state", BOSS).status == 403


def test_la_vista_ridotta_tiene_i_gesti_sui_propri_dati(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, known=[LOW], approved=[BOSS]))
    seat = seat_of(page, LOW, box)
    assert miniapp.why(page, seat, "link.drop") is None
    assert miniapp.why(page, seat, "data.forget") is None
    assert miniapp.why(page, seat, "lang.set") is None
    assert miniapp.why(page, seat, "target.set") == reasons.NOT_APPROVED
    assert miniapp.why(page, seat, "settings.press") == reasons.NOT_MANAGER


def test_l_estraneo_puo_solo_aprire_e_provare_il_villaggio(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box))
    seat = seat_of(page, OUT, box)
    assert miniapp.why(page, seat, "app.opened") is None
    assert miniapp.why(page, seat, "link.verify") is None
    assert miniapp.why(page, seat, "availability.set") == reasons.NOT_LINKED


def test_la_pagina_html_dell_app_non_porta_dati_del_clan(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    testo = run(store, f"/app/{SLUG}", OUT).body.decode()
    for leak in ("#P1", "#P3", "Mario", "Peach", '"seats"'):
        assert leak not in testo, leak
    assert run(store, "/app/0000000000000000", BOSS).status == 404


def test_la_porta_del_clan_si_conta_a_impronte_cieche(tmp_path):
    box = vault(tmp_path)
    found = door_of(box, known=[LOW], approved=[FULL], banned=[BANNED_UID])
    testo = json.dumps(found)
    for uid in (LOW, FULL, BANNED_UID):
        assert re.search(rf"\b{uid}\b", testo) is None, uid
        assert mark(box, uid) in testo
    assert mark(box, LOW) != payload.mark_for(box, "0123456789abcdef", LOW)


def test_il_registro_della_porta_tiene_il_si_e_da_quando_vale():
    state = door.state_of(None)
    state = door.approve(state, FULL, NOW.timestamp(), 0)
    state = door.saw(state, LOW)
    state = door.ban(state, BANNED_UID)
    assert state[door.YES][str(FULL)][door.SINCE] == int(NOW.timestamp())
    assert state[door.SEEN] == [LOW] and state[door.BAN] == [BANNED_UID]
    assert door.state_of(json.loads(json.dumps(state))) == state


def test_la_porta_nasce_col_si_a_chi_aveva_gia_provato_il_villaggio():
    state = door.state_of(None)
    fresh = door.seed(state, [FULL, BOSS], NOW.timestamp())
    assert sorted(int(uid) for uid in fresh[door.YES]) == [BOSS, FULL]
    assert door.seed(fresh, [FULL, BOSS], NOW.timestamp()) is fresh


class DoorStore:
    def __init__(self, box, stati):
        self.vault = box
        self.stati = stati

    async def get_state(self, alias, kind):
        return self.stati.get(kind)

    async def set_state(self, alias, kind, value):
        self.stati[kind] = value

    async def kv_get(self, key):
        return None


def test_il_bando_si_toglie_come_si_mette():
    state = door.ban(door.state_of(None), BANNED_UID)
    assert state[door.BAN] == [BANNED_UID]
    fresh = door.unban(state, BANNED_UID)
    assert fresh[door.BAN] == [] and state[door.BAN] == [BANNED_UID]
    assert door.unban(fresh, BANNED_UID)[door.BAN] == []


def test_il_bando_cade_quando_il_gestore_annulla_il_blocco(tmp_path):
    box = vault(tmp_path)
    bloccati, riga = recruit_block.add(recruit_block.state_of(None), BANNED_UID, "Luigi", NOW)
    stati = {recruit_block.KIND: bloccati}
    battito = publish.Beat(DoorStore(box, stati), None, None, None)
    clan = SimpleNamespace(alias="clan-uno")
    prima = asyncio.run(battito.door_of(clan, SLUG, [], NOW))
    assert prima[door.BAN] == [mark(box, BANNED_UID)]
    stati[recruit_block.KIND] = recruit_block.drop(
        recruit_block.state_of(stati[recruit_block.KIND]), riga["id"])[0]
    dopo = asyncio.run(battito.door_of(clan, SLUG, [], NOW))
    assert dopo[door.BAN] == []
    assert door.state_of(stati[door.KIND])[door.BAN] == []


def test_le_sei_minacce_della_porta_hanno_ognuna_la_sua_prova():
    rows = json.loads(MINACCE.read_text(encoding="utf-8"))
    porta = rows[PORTA]
    assert len(porta) == 6
    assert sorted(row["stride"] for row in porta) == sorted(STRIDE)
    testo = Path(__file__).read_text(encoding="utf-8")
    for row in porta:
        assert row["minaccia"] and row["chiude"]
        assert ("def %s(" % row["prova"]) in testo, row["prova"]


@pytest.mark.parametrize("livello", (miniapp.OUTSIDER, miniapp.REDUCED, miniapp.FULL_VIEW,
                                     miniapp.BOSS))
def test_ogni_livello_ha_il_suo_stato_per_la_prova_dei_bottoni(livello, tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, known=[LOW], approved=[BOSS, FULL]))
    uid = {miniapp.OUTSIDER: OUT, miniapp.REDUCED: LOW,
           miniapp.FULL_VIEW: FULL, miniapp.BOSS: BOSS}[livello]
    found = miniapp.state_body(page, seat_of(page, uid, box), now=NOW.timestamp())
    assert found["level"] == livello


def test_il_viewer_conia_l_impronta_del_visitatore(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    req = request("/app", headers=f"X-Init-Data: {init(BOSS, code=SLUG)}\r\n".encode())
    _, seat = asyncio.run(web_app.Site(store).viewer(req, SLUG))
    assert seat["mark"] == mark(box, BOSS)


VISTE = {"estraneo": miniapp.OUTSIDER, "ridotta": miniapp.REDUCED,
         "piena": miniapp.FULL_VIEW, "gestore": miniapp.BOSS}
PAGINA = Path(__file__).parent / "js" / "page.json"
RIFAI = "CLANBOARD_RIFAI_PAGINA"


def sample_seats():
    return {str(BOSS): dict(SEATS["777"]),
            str(FULL): {"tag": "#P3", "name": "Peach", "level": None, "lang": "it",
                        "avail": "in", "verified": True},
            str(LOW): {"tag": "#P9", "name": "Fuori", "level": None, "lang": "it",
                       "verified": False}}


def finto_mark(uid):
    return hashlib.sha256(("%s:%d" % (SLUG, int(uid))).encode()).hexdigest()[:payload.SLUG_LEN]


def pagina_di_esempio():
    page = sample_page(sample_seats())
    page.update(door_marks(finto_mark, known=[LOW], approved=[BOSS, FULL]))
    page["recruit"] = dict(RECLUTA)
    page["clan"]["badge"] = BADGE
    posti = {"gestore": seat_with(page, BOSS, finto_mark(BOSS)),
             "piena": seat_with(page, FULL, finto_mark(FULL)),
             "ridotta": seat_with(page, LOW, finto_mark(LOW)),
             "estraneo": seat_with(page, OUT, finto_mark(OUT))}
    return page, posti


def test_la_pagina_di_esempio_dei_quattro_livelli_e_scritta_per_la_prova_dei_bottoni():
    page, posti = pagina_di_esempio()
    for nome, atteso in VISTE.items():
        assert miniapp.level_of(page, posti[nome]) == atteso, nome
    testo = json.dumps({"page": page, "seats": posti, "now": int(NOW.timestamp())},
                       ensure_ascii=False, indent=1) + "\n"
    if os.environ.get(RIFAI):
        PAGINA.write_text(testo, encoding="utf-8")
    assert PAGINA.read_text(encoding="utf-8") == testo, "rigenera con %s=1" % RIFAI
    misure = [len(json.dumps(miniapp.state_body(page, posti[nome], 0, NOW.timestamp())))
              for nome in ("estraneo", "ridotta", "piena", "gestore")]
    assert misure[0] < misure[1] < misure[2] < misure[3], misure


def test_il_si_di_prima_non_si_riscrive_e_il_villaggio_nuovo_aspetta_la_casella():
    state = door.seed(door.state_of(None), [BOSS], NOW.timestamp())
    dopo = door.seed(state, [BOSS, FULL], NOW.timestamp() + 60)
    assert dopo[door.YES][str(BOSS)][door.SINCE] == int(NOW.timestamp())
    assert str(FULL) not in dopo[door.YES]
    assert door.pending(dopo, [BOSS, FULL]) == [FULL]


def test_da_approvare_c_e_solo_chi_ha_provato_il_villaggio_senza_il_si():
    state = door.seed(door.state_of(None), [BOSS], NOW.timestamp())
    state = door.ban(state, BANNED_UID)
    assert door.pending(state, [BOSS, FULL, BANNED_UID, "storto"]) == [FULL]
    assert door.pending(door.approve(state, FULL, NOW.timestamp()), [BOSS, FULL]) == []


def test_la_revoca_toglie_solo_la_riga_del_si():
    state = door.seed(door.state_of(None), [BOSS, FULL], NOW.timestamp())
    fresh = door.revoke(state, FULL)
    assert sorted(fresh[door.YES]) == [str(BOSS)]
    assert fresh[door.YES][str(BOSS)] == state[door.YES][str(BOSS)]
    assert str(FULL) in state[door.YES]
    assert door.revoke(fresh, FULL) == fresh


def test_il_segno_va_e_viene_si_mette_e_si_toglie():
    state = door.seed(door.state_of(None), [FULL], NOW.timestamp())
    acceso = door.trust(state, FULL, True)
    assert acceso[door.TRUST] == [FULL] and door.trust(acceso, FULL, True) == acceso
    assert door.trust(acceso, FULL, False)[door.TRUST] == []
    assert door.state_of(json.loads(json.dumps(acceso))) == acceso
    assert door.state_of(None)[door.TRUST] == []


def test_chi_esce_senza_segno_perde_il_si_alla_lettura_della_rosa():
    state = door.seed(door.state_of(None), [BOSS, FULL], NOW.timestamp())
    assert door.gone(state, [BOSS]) == [FULL]
    fresh = door.left(state, [BOSS])
    assert sorted(fresh[door.YES]) == [str(BOSS)]
    assert door.left(fresh, [BOSS]) == fresh


def test_chi_esce_col_segno_tiene_il_si_e_rientra_pieno(tmp_path):
    box = vault(tmp_path)
    state = door.trust(door.seed(door.state_of(None), [BOSS, FULL], NOW.timestamp()), FULL, True)
    assert door.gone(state, [BOSS]) == [] and door.left(state, [BOSS]) == state
    page = page_with(box, **door.marks(door.left(state, [BOSS]), lambda uid: mark(box, uid)))
    assert levels(page, box, FULL) == [miniapp.FULL_VIEW]


def test_la_scelta_della_guerra_ha_solo_due_valori():
    assert door.WAR_CHOICES == ("now", "next")
    assert door.war_from("now", NOW.timestamp()) == 0
    assert door.war_from("next", NOW.timestamp()) == int(NOW.timestamp())
    for storto in ("", "dopo", "NOW", None):
        with pytest.raises(ValueError):
            door.war_from(storto, NOW.timestamp())


def seminata(store, *uids, trusted=(), banned=()):
    state = door.seed(door.state_of(None), list(uids), CASELLA_ORA.timestamp())
    for uid in trusted:
        state = door.trust(state, uid, True)
    for uid in banned:
        state = door.ban(state, uid)
    asyncio.run(store.set_state(casella.CLAN.alias, door.KIND, state))
    return store


def porta_di(store):
    return door.state_of(asyncio.run(store.get_state(casella.CLAN.alias, door.KIND)))


def posto(store, page, uid):
    return dict(page["seats"][str(uid)], uid=uid, mark=casella.mark_of(store, uid))


def gesto(store, kind, uid, ident, **body):
    return casella.applied(store, kind, body, uid=uid, ident=ident)


def pubblica(store, members):
    beat = casella.beat_for(store)
    asyncio.run(beat.app(casella.CLAN, casella.conf_of(store), members, casella.INFO,
                         CASELLA_ORA))
    return casella.page_of(store)


def test_l_anziano_approva_chi_ha_provato_il_villaggio_e_la_guerra_vale_subito(tmp_path):
    store = seminata(casella.manager_store(tmp_path, war=casella.WAR),
                     casella.CHIEF, casella.ELDER)
    assert gesto(store, "person.approve", casella.ELDER, "p1", person=casella.STRANGER,
                 war_from="now") is True
    assert porta_di(store)[door.YES][str(casella.STRANGER)][door.WAR_FROM] == 0
    page = casella.page_of(store)
    seat = posto(store, page, casella.STRANGER)
    assert page[door.YES][seat["mark"]][door.WAR_FROM] == 0
    found = miniapp.state_body(page, seat, now=CASELLA_ORA.timestamp())
    assert found["level"] == miniapp.FULL_VIEW and found["war_view"] is not None
    assert casella.staff_of(store)["pending"] == []


def test_il_capo_approva_dalla_prossima_guerra_e_quella_in_corso_resta_chiusa(tmp_path):
    store = seminata(casella.manager_store(tmp_path, war=casella.WAR),
                     casella.CHIEF, casella.ELDER)
    assert gesto(store, "person.approve", casella.CHIEF, "p2", person=casella.STRANGER,
                 war_from="next") is True
    ora = int(CASELLA_ORA.timestamp())
    assert porta_di(store)[door.YES][str(casella.STRANGER)][door.WAR_FROM] == ora
    page = casella.page_of(store)
    assert int(page["war"]["start"]) < ora
    found = miniapp.state_body(page, posto(store, page, casella.STRANGER), now=ora)
    assert found["level"] == miniapp.FULL_VIEW
    assert found["war_view"] is None and "war" not in found and "rows" not in found
    page["war"]["start"] = ora + 60
    dopo = miniapp.state_body(page, posto(store, page, casella.STRANGER), now=ora)
    assert dopo["war_view"] is not None


def test_il_membro_non_si_approva_da_solo(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER)
    assert gesto(store, "person.approve", casella.STRANGER, "p3", person=casella.STRANGER,
                 war_from="now") == reasons.NOT_MANAGER
    assert str(casella.STRANGER) not in porta_di(store)[door.YES]


def test_l_anziano_non_revoca_e_non_mette_il_segno(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER,
                     casella.STRANGER)
    prima = porta_di(store)
    assert gesto(store, "person.revoke", casella.ELDER, "p4",
                 person=casella.STRANGER) == reasons.NOT_MANAGER
    assert gesto(store, "person.trust", casella.ELDER, "p5", person=casella.STRANGER,
                 value="on") == reasons.NOT_MANAGER
    assert porta_di(store) == prima


def test_il_capo_mette_il_segno_e_revoca_senza_cancellare_il_collegamento(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER,
                     casella.STRANGER)
    assert gesto(store, "person.trust", casella.CHIEF, "p6", person=casella.STRANGER,
                 value="on") is True
    assert porta_di(store)[door.TRUST] == [casella.STRANGER]
    assert gesto(store, "person.revoke", casella.CHIEF, "p7", person=casella.STRANGER) is True
    assert str(casella.STRANGER) not in porta_di(store)[door.YES]
    assert [one.user_id for one in store.links if one.tag == "#P4"] == [casella.STRANGER]
    assert gesto(store, "person.revoke", casella.CHIEF, "p8",
                 person=casella.STRANGER) == reasons.GONE
    assert gesto(store, "person.trust", casella.CHIEF, "p9", person=casella.STRANGER,
                 value="off") is True
    assert porta_di(store)[door.TRUST] == []


def test_l_impronta_di_un_altro_clan_non_approva_nessuno(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER)
    altrove = payload.mark_for(store.vault, "0123456789abcdef", casella.STRANGER)
    fila = casella.row("person.approve", {"who": altrove, "war_from": "now"}, casella.CHIEF, "pa")
    esito = asyncio.run(intents.apply_one(store, casella.beat_for(store), fila, CASELLA_ORA))
    assert esito == reasons.NOT_LINKED
    assert str(casella.STRANGER) not in porta_di(store)[door.YES]


def test_il_gestore_di_un_altro_clan_con_lo_slug_di_questo_non_approva(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    corpo = {"kind": "person.approve", "who": mark(box, LOW), "war_from": "now", "id": "pb1"}
    res = run(store, f"/app/{SLUG}/act", 4242, method="POST", data=corpo)
    assert res.status == 403 and json.loads(res.body)["error"] == reasons.NOT_MANAGER
    assert store.intents == []
    buono = run(store, f"/app/{SLUG}/act", BOSS, method="POST", data=dict(corpo, id="pb2"))
    assert buono.status == 200 and store.intents[0][1] == "person.approve"


def test_il_bandito_non_si_approva(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER,
                     banned=[casella.STRANGER])
    assert gesto(store, "person.approve", casella.CHIEF, "pc", person=casella.STRANGER,
                 war_from="now") == reasons.BANNED
    assert str(casella.STRANGER) not in porta_di(store)[door.YES]


def test_chi_non_ha_provato_il_villaggio_non_si_approva(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER)
    store.links = ([one for one in store.links if one.tag != "#P4"]
                   + [casella.link("#P4", casella.STRANGER, "Toad", False)])
    assert gesto(store, "person.approve", casella.CHIEF, "pd", person=casella.STRANGER,
                 war_from="now") == reasons.NOT_LINKED
    assert str(casella.STRANGER) not in porta_di(store)[door.YES]


def test_la_guerra_fuori_elenco_non_passa_ne_alla_porta_ne_al_bot(tmp_path):
    corpo = {"kind": "person.approve", "who": "a" * payload.SLUG_LEN, "war_from": "dopo",
             "id": "pe1"}
    assert miniapp.intent(corpo, "#P1", BOSS) is None
    assert miniapp.intent(dict(corpo, war_from="next"), "#P1", BOSS)["war_from"] == "next"
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    web = AppStore({(SLUG, payload.APP): page}, vault=box)
    res = run(web, f"/app/{SLUG}/act", BOSS, method="POST", data=corpo)
    assert res.status == 400 and web.intents == []
    store = seminata(casella.manager_store(tmp_path / "bot"), casella.CHIEF, casella.ELDER)
    assert gesto(store, "person.approve", casella.CHIEF, "pe2", person=casella.STRANGER,
                 war_from="dopo") == reasons.BAD
    assert str(casella.STRANGER) not in porta_di(store)[door.YES]


def test_la_casella_nomina_le_persone_con_l_impronta_mai_con_l_uid(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER,
                     trusted=[casella.ELDER])
    assert gesto(store, "clan.pause", casella.CHIEF, "pf") is True
    staff = casella.staff_of(store)
    assert staff["pending"] == [{"who": casella.mark_of(store, casella.STRANGER),
                                 "name": "Toad", "tag": "#P4"}]
    assert staff["approved"] == [
        {"who": casella.mark_of(store, casella.CHIEF), "name": "Mario", "trusted": False},
        {"who": casella.mark_of(store, casella.ELDER), "name": "Peach", "trusted": True}]
    seat = {"uid": casella.CHIEF, "tag": "#P1", "level": MANAGER}
    found = miniapp.state_body(casella.page_of(store), seat)
    assert found["inbox"]["pending"] == staff["pending"] and "claims" not in found["inbox"]
    assert found["manage_view"]["approved"] == staff["approved"]
    for row in staff["pending"] + staff["approved"]:
        assert str(casella.STRANGER) != row["who"] and str(casella.ELDER) != row["who"]
        assert "uid" not in row and "user_id" not in row


def test_ogni_gesto_della_casella_lascia_la_riga_nel_registro(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER)
    assert gesto(store, "person.approve", casella.CHIEF, "pg1", person=casella.STRANGER,
                 war_from="now") is True
    assert gesto(store, "person.trust", casella.CHIEF, "pg2", person=casella.STRANGER,
                 value="on") is True
    assert gesto(store, "person.revoke", casella.CHIEF, "pg3", person=casella.STRANGER) is True
    assert [(entry["action"], entry["by"], entry["detail"]) for _, entry in store.logs] == [
        ("views", casella.CHIEF, "person.approve"), ("views", casella.CHIEF, "person.trust"),
        ("views", casella.CHIEF, "person.revoke")]


def test_chi_esce_senza_segno_perde_il_si_e_i_gestori_hanno_l_avviso(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER,
                     casella.STRANGER)
    fuori = {tag: row for tag, row in casella.MEMBERS.items() if tag != "#P4"}
    pubblica(store, fuori)
    assert str(casella.STRANGER) not in porta_di(store)[door.YES]
    avviso = (LINK_NEWS, casella.IT.t("feed.person.left", name="Toad"))
    for uid in (casella.CHIEF, casella.ELDER):
        righe = asyncio.run(feed.rows(store, casella.CLAN.alias, uid))
        assert [(one["kind"], one["text"]) for one in righe] == [avviso], uid
    assert asyncio.run(feed.rows(store, casella.CLAN.alias, casella.STRANGER)) == []
    assert [one.user_id for one in store.links if one.tag == "#P4"] == [casella.STRANGER]
    pubblica(store, fuori)
    righe = asyncio.run(feed.rows(store, casella.CLAN.alias, casella.CHIEF))
    assert len(righe) == 1
    page = pubblica(store, casella.MEMBERS)
    assert miniapp.level_of(page, posto(store, page, casella.STRANGER)) == miniapp.REDUCED
    assert casella.staff_of(store)["pending"][0]["name"] == "Toad"


def test_chi_esce_col_segno_rientra_approvato_da_solo(tmp_path):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER,
                     casella.STRANGER, trusted=[casella.STRANGER])
    fuori = {tag: row for tag, row in casella.MEMBERS.items() if tag != "#P4"}
    pubblica(store, fuori)
    assert str(casella.STRANGER) in porta_di(store)[door.YES]
    assert asyncio.run(feed.rows(store, casella.CLAN.alias, casella.CHIEF)) == []
    page = pubblica(store, casella.MEMBERS)
    assert miniapp.level_of(page, posto(store, page, casella.STRANGER)) == miniapp.FULL_VIEW


def test_la_rosa_vuota_non_toglie_il_si_a_nessuno(tmp_path):
    box = vault(tmp_path)
    stati = {door.KIND: door.seed(door.state_of(None), [BOSS, FULL], NOW.timestamp())}
    battito = publish.Beat(DoorStore(box, stati), None, None, None)
    clan = SimpleNamespace(alias="clan-uno")
    porta = asyncio.run(battito.door_of(clan, SLUG, [], NOW, {}))
    assert sorted(porta[door.YES]) == sorted([mark(box, BOSS), mark(box, FULL)])
    assert sorted(door.state_of(stati[door.KIND])[door.YES]) == sorted([str(BOSS), str(FULL)])


def senza_link(store, uid):
    store.links = [one for one in store.links if one.user_id != uid]


def non_provato(store, uid):
    store.links = [casella.link(one.tag, one.user_id, one.name, verified=False)
                   if one.user_id == uid else one for one in store.links]


@pytest.mark.parametrize("sgancia", [senza_link, non_provato])
def test_chi_resta_nel_clan_senza_villaggio_provato_non_e_uscito(tmp_path, sgancia):
    store = seminata(casella.manager_store(tmp_path), casella.CHIEF, casella.ELDER,
                     casella.STRANGER)
    sgancia(store, casella.STRANGER)
    pubblica(store, casella.MEMBERS)
    for uid in (casella.CHIEF, casella.ELDER):
        assert asyncio.run(feed.rows(store, casella.CLAN.alias, uid)) == [], uid


def test_gli_ex_membri_di_prima_della_porta_non_fanno_raffica_al_primo_battito(tmp_path):
    store = casella.manager_store(tmp_path)
    store.links.append(casella.link("#GONE", 4242, "Wario"))
    vecchio = {str(uid): {door.SINCE: int(CASELLA_ORA.timestamp()), door.WAR_FROM: 0}
               for uid in (casella.CHIEF, casella.ELDER, casella.STRANGER, 4242, 4343)}
    asyncio.run(store.set_state(casella.CLAN.alias, door.KIND,
                                {door.YES: vecchio, door.SEEDED: True}))
    pubblica(store, casella.MEMBERS)
    assert sorted(porta_di(store)[door.YES]) == sorted(
        str(uid) for uid in (casella.CHIEF, casella.ELDER, casella.STRANGER))
    for uid in (casella.CHIEF, casella.ELDER):
        assert asyncio.run(feed.rows(store, casella.CLAN.alias, uid)) == [], uid
    pubblica(store, {tag: row for tag, row in casella.MEMBERS.items() if tag != "#P4"})
    avviso = (LINK_NEWS, casella.IT.t("feed.person.left", name="Toad"))
    for uid in (casella.CHIEF, casella.ELDER):
        righe = asyncio.run(feed.rows(store, casella.CLAN.alias, uid))
        assert [(one["kind"], one["text"]) for one in righe] == [avviso], uid


def test_le_sei_minacce_della_porta_coprono_i_tre_gesti_di_casella():
    porta = json.loads(MINACCE.read_text(encoding="utf-8"))[PORTA]
    testo = Path(__file__).read_text(encoding="utf-8")
    assert sorted(row["stride"] for row in porta) == sorted(STRIDE)
    for row in porta:
        gesti = row.get("casella") or {}
        assert gesti.get("minaccia") and gesti.get("chiude"), row["stride"]
        assert ("def %s(" % gesti.get("prova")) in testo, gesti.get("prova")


PAROLE_CASELLA = ("web.app.manage.now", "web.app.manage.next", "web.app.manage.revoke",
                  "web.app.manage.trust", "web.app.manage.approved", "feed.person.left")


def test_la_voce_di_chi_aspetta_il_si_parla_di_persone_non_di_villaggi():
    assert CATALOGS["it"]["web.app.manage.claims"] == "Da approvare"
    for lingua, dati in CATALOGS.items():
        if lingua != "it":
            assert dati["web.app.manage.claims"] == "To approve", lingua


def test_le_parole_dei_tre_gesti_stanno_nei_venti_cataloghi():
    assert len(CATALOGS) == 20
    for lingua, dati in CATALOGS.items():
        assert all(dati.get(chiave) for chiave in PAROLE_CASELLA), lingua
    parole = miniapp.words(casella.IT)
    for nome in ("now", "next", "revoke", "trust", "approved"):
        assert not parole["manage_" + nome].startswith("["), nome
    assert miniapp.CONF["WAR_FROM"] == list(door.WAR_CHOICES)
