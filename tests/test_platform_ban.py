import asyncio

from clashbot import door, platform_ban, recruit_block
from clashbot.crypto import Vault
from test_intents import ActStore

OSPITE = 4242
ALTRO = 99
TAG = "#P9"
ALIAS = "clan-a1"
ORA = 1789000000.0


def store_of(tmp_path):
    return ActStore(Vault(tmp_path))


def bandito(store, uid=OSPITE, tags=(TAG,)):
    return asyncio.run(platform_ban.ban(store, uid, tags, ORA))


def test_lo_stato_del_bando_nasce_vuoto_e_regge_i_valori_storti():
    fresh = platform_ban.state_of({"rows": {"7": {"tags": ["#p1", 5]}, "x": {}, "": None}})
    assert platform_ban.uids(fresh) == [7]
    assert platform_ban.tags(fresh) == ["#P1"]
    assert platform_ban.state_of(None) == {platform_ban.ROWS: {}}


def test_un_uid_storto_non_finisce_sotto_la_chiave_none():
    fresh = platform_ban.with_ban({}, "non-un-numero", [TAG], ORA)
    assert fresh == {platform_ban.ROWS: {}}
    assert platform_ban.shut(fresh, None, [TAG]) is False


def test_bandire_con_un_uid_storto_risponde_di_no(tmp_path):
    store = store_of(tmp_path)
    assert asyncio.run(platform_ban.ban(store, "non-un-numero", [TAG], ORA)) is False
    assert asyncio.run(platform_ban.load(store)) == {platform_ban.ROWS: {}}
    assert asyncio.run(platform_ban.refuses(store, OSPITE, [TAG])) is False


def test_il_bando_prende_il_telegram_e_i_villaggi_provati(tmp_path):
    store = store_of(tmp_path)
    assert bandito(store) is True
    state = asyncio.run(platform_ban.load(store))
    assert platform_ban.shut(state, OSPITE) is True
    assert platform_ban.shut(state, ALTRO) is False
    assert platform_ban.shut(state, ALTRO, [TAG]) is True
    assert platform_ban.shut(state, ALTRO, ["#P1"]) is False


def test_il_bando_di_uno_non_libera_i_villaggi_di_un_altro(tmp_path):
    store = store_of(tmp_path)
    bandito(store)
    bandito(store, ALTRO, ["#P1"])
    assert asyncio.run(platform_ban.lift(store, ALTRO)) is True
    state = asyncio.run(platform_ban.load(store))
    assert platform_ban.tags(state) == [TAG]


def test_il_bando_si_toglie_come_si_mette(tmp_path):
    store = store_of(tmp_path)
    bandito(store)
    assert asyncio.run(platform_ban.lift(store, OSPITE)) is True
    state = asyncio.run(platform_ban.load(store))
    assert platform_ban.shut(state, OSPITE) is False
    assert platform_ban.shut(state, ALTRO, [TAG]) is False


def test_bandire_due_volte_non_raddoppia_niente(tmp_path):
    store = store_of(tmp_path)
    bandito(store)
    bandito(store)
    state = asyncio.run(platform_ban.load(store))
    assert platform_ban.uids(state) == [OSPITE]
    assert platform_ban.tags(state) == [TAG]


def test_il_muro_della_piattaforma_non_e_l_insieme_del_clan():
    state = door.state_of(None)
    state = door.wall(state, OSPITE)
    state = door.bans(state, [])
    assert state[door.WALL] == [OSPITE]
    assert state[door.BAN] == []
    assert door.marks(state, lambda uid: str(uid))[door.BAN] == [str(OSPITE)]


def test_un_battito_non_libera_chi_ha_bandito_la_piattaforma():
    state = door.state_of(None)
    state = door.walls(door.ban(state, ALTRO), [OSPITE])
    state = door.bans(state, [ALTRO])
    attesi = sorted([str(ALTRO), str(OSPITE)])
    assert door.marks(state, lambda uid: str(uid))[door.BAN] == attesi
    state = door.walls(state, [OSPITE])
    assert door.marks(state, lambda uid: str(uid))[door.BAN] == attesi


def test_la_porta_chiude_anche_chi_tiene_un_villaggio_bandito(tmp_path):
    from types import SimpleNamespace
    from clashbot import publish
    from clashbot.web import payload
    from test_web_publish import CLAN, NOW
    from test_web_miniapp import SLUG
    box = Vault(tmp_path)
    store = ActStore(box)
    store.links = [SimpleNamespace(tag=TAG, user_id=ALTRO, name="Toad", dm=True, lang="it")]
    bandito(store, OSPITE, [TAG])
    beat = publish.Beat(store, None, None, None, clock=lambda: 0.0)
    porta = asyncio.run(beat.door_of(CLAN, SLUG, [ALTRO], NOW))
    assert payload.mark_for(box, SLUG, ALTRO) in porta[door.BAN]


def test_il_bandito_dalla_piattaforma_non_si_candida(tmp_path):
    store = store_of(tmp_path)
    assert asyncio.run(recruit_block.refuses(store, ALIAS, OSPITE)) is False
    bandito(store)
    assert asyncio.run(recruit_block.refuses(store, ALIAS, OSPITE)) is True
    assert asyncio.run(recruit_block.refuses(store, ALIAS, ALTRO)) is False


def test_dopo_un_battito_il_bandito_dalla_piattaforma_e_ancora_fuori(tmp_path):
    import json
    from clashbot import publish
    from clashbot.web import miniapp, payload
    from test_web_door import BOSS, door_of as porta_di, page_with, seat_of
    from test_web_miniapp import AppStore, SLUG, serve
    from test_web_publish import CLAN, NOW
    box = Vault(tmp_path)
    store = ActStore(box)
    bandito(store, OSPITE, [])
    beat = publish.Beat(store, None, None, None, clock=lambda: 0.0)
    prima = asyncio.run(beat.door_of(CLAN, SLUG, [BOSS, OSPITE], NOW))
    dopo = asyncio.run(beat.door_of(CLAN, SLUG, [BOSS, OSPITE], NOW))
    impronta = payload.mark_for(box, SLUG, OSPITE)
    assert impronta in prima[door.BAN] and impronta in dopo[door.BAN]
    page = page_with(box, **dict(porta_di(box, approved=[BOSS]), **{door.BAN: dopo[door.BAN]}))
    servito = AppStore({(SLUG, payload.APP): page}, vault=box)
    assert serve(servito, f"/app/{SLUG}/state", uid=OSPITE).status == 403
    aperto = serve(servito, f"/app/{SLUG}/state", uid=BOSS)
    assert aperto.status == 200 and json.loads(aperto.body)["level"] == miniapp.BOSS
    assert miniapp.shut(page, seat_of(page, OSPITE, box)) is True
