import asyncio
from types import SimpleNamespace

from clashbot import roles
from clashbot.crypto import Vault
from clashbot.db import Store

CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#C1", name="Futuro", bot_alias="bot-1", linked_by=555)
MEMBERS = {"#L": {"name": "Capo", "role": "leader"}, "#C": {"name": "Co", "role": "coLeader"},
           "#E": {"name": "Anz", "role": "admin"}, "#M": {"name": "Mem", "role": "member"}}


class FakeStore:
    def __init__(self, links, owner=555):
        self.links, self.owner = links, owner

    async def bot_by_alias(self, alias):
        return SimpleNamespace(alias=alias, owner_id=self.owner)

    async def kv_get(self, key):
        return None

    async def links_for_players(self, tags):
        return {tag: SimpleNamespace(user_id=uid, name=tag, tag=tag) for tag, uid in self.links.items() if tag in tags}

    async def links_by_user(self, user_id):
        return [SimpleNamespace(user_id=uid, name=tag, tag=tag) for tag, uid in self.links.items() if uid == user_id]


class FakeCoc:
    def __init__(self, players=None, error=None):
        self.players, self.error = players or {}, error
        self.asked = []

    async def player(self, tag):
        self.asked.append(tag)
        if self.error:
            return None, self.error
        return self.players.get(tag), None


class ClanPool:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, sql, *args):
        return self.row

    async def execute(self, sql, *args):
        if "chat_index=$2, identity=$3" in sql:
            self.row = dict(self.row, chat_index=args[1], identity=args[2])
        else:
            self.row = dict(self.row, identity=args[1])
        return "UPDATE 1"


def clan_store(tmp_path, linked_by):
    vault = Vault(tmp_path)
    store = Store(vault)
    store.pool = ClanPool({
        "alias": "clan-1", "active": True, "failures": 0, "last_seen": None, "bot_alias": "bot-1",
        "chat_index": vault.blind("chat", -100),
        "identity": vault.encrypt_json(
            {"chat_id": -100, "tag": "#ABC", "name": "Futuro", "added_by": linked_by}, "clan:clan-1"),
    })
    return store


def test_finche_nessun_capo_e_collegato_gestisce_chi_ha_creato_il_bot():
    store = FakeStore({"#M": 7})
    found = asyncio.run(roles.managers(store, CLAN, {"delegates": []}, MEMBERS))
    assert found == {555: roles.MANAGER}


def test_appena_capo_o_co_capi_si_collegano_gestiscono_loro_e_il_creatore_esce():
    store = FakeStore({"#C": 9, "#M": 7})
    found = asyncio.run(roles.managers(store, CLAN, {"delegates": []}, MEMBERS))
    assert found == {9: roles.MANAGER}
    store = FakeStore({"#L": 8, "#C": 9, "#E": 10})
    found = asyncio.run(roles.managers(store, CLAN, {"delegates": [555]}, MEMBERS))
    assert found == {8: roles.MANAGER, 9: roles.MANAGER, 10: roles.LIMITED, 555: roles.MANAGER}


def test_un_delegato_deve_avere_un_villaggio_nel_clan_o_essere_il_creatore():
    store = FakeStore({"#L": 8, "#M": 7})
    found = asyncio.run(roles.managers(store, CLAN, {"delegates": [7, 42]}, MEMBERS))
    assert found == {8: roles.MANAGER, 7: roles.MANAGER}


def test_il_livello_di_una_persona_e_none_se_non_gestisce():
    store = FakeStore({"#L": 8, "#E": 10})
    assert asyncio.run(roles.level(store, CLAN, {}, MEMBERS, 10)) == roles.LIMITED
    assert asyncio.run(roles.level(store, CLAN, {}, MEMBERS, 12345)) is None


def test_con_due_villaggi_vince_il_grado_piu_alto():
    store = FakeStore({"#E": 8, "#C": 8})
    assert asyncio.run(roles.managers(store, CLAN, {}, MEMBERS)) == {8: roles.MANAGER}


def test_senza_chi_ha_collegato_il_clan_gestisce_chi_possiede_il_bot():
    clan = SimpleNamespace(alias="clan-2", tag="#C1", bot_alias="bot-1", linked_by=None)
    store = FakeStore({"#M": 7}, owner=77)
    assert asyncio.run(roles.creator_id(store, clan)) == 77
    assert asyncio.run(roles.managers(store, clan, {}, MEMBERS)) == {77: roles.MANAGER}


def test_dal_vivo_un_capo_retrocesso_nel_gioco_non_gestisce_piu():
    store = FakeStore({"#L": 8})
    coc = FakeCoc({"#L": {"role": "member", "clan": {"tag": "#C1"}}})
    assert asyncio.run(roles.level(store, CLAN, {}, MEMBERS, 8)) == roles.MANAGER
    assert asyncio.run(roles.live_level(coc, store, CLAN, {}, MEMBERS, 8)) == (None, True)
    assert coc.asked == ["#L"]


def test_dal_vivo_chi_ha_lasciato_il_clan_non_gestisce_piu():
    store = FakeStore({"#L": 8})
    coc = FakeCoc({"#L": {"role": "leader", "clan": {"tag": "#ALTRO"}}})
    assert asyncio.run(roles.live_level(coc, store, CLAN, {}, MEMBERS, 8)) == (None, True)


def test_un_villaggio_fuori_dal_roster_non_da_il_comando():
    store = FakeStore({"#X": 7})
    coc = FakeCoc({"#X": {"role": "leader", "clan": {"tag": "#ALTRO"}}})
    assert asyncio.run(roles.live_level(coc, store, CLAN, {}, MEMBERS, 7)) == (None, True)
    assert coc.asked == []


def test_se_il_gioco_non_risponde_vale_il_livello_del_roster():
    store = FakeStore({"#L": 8})
    coc = FakeCoc(error="network")
    assert asyncio.run(roles.live_level(coc, store, CLAN, {}, MEMBERS, 8)) == (roles.MANAGER, False)


def test_il_capo_del_gioco_si_riconferma_dal_vivo_prima_delle_azioni_delicate():
    store = FakeStore({"#L": 8, "#C": 9})
    assert asyncio.run(roles.live_chief(None, store, CLAN, MEMBERS, 8)) is True
    assert asyncio.run(roles.live_chief(None, store, CLAN, MEMBERS, 9)) is False
    vivo = FakeCoc({"#L": {"role": "leader", "clan": {"tag": "#C1"}}})
    assert asyncio.run(roles.live_chief(vivo, store, CLAN, MEMBERS, 8)) is True
    assert vivo.asked == ["#L"]
    retrocesso = FakeCoc({"#L": {"role": "coLeader", "clan": {"tag": "#C1"}}})
    assert asyncio.run(roles.live_chief(retrocesso, store, CLAN, MEMBERS, 8)) is False
    assert asyncio.run(roles.live_chief(FakeCoc(error="network"), store, CLAN,
                                        MEMBERS, 8)) is False


def test_il_clan_dice_chi_lo_ha_collegato(tmp_path):
    store = clan_store(tmp_path, 555)
    assert asyncio.run(store.clan_by_alias("clan-1")).linked_by == 555
    assert asyncio.run(clan_store(tmp_path, None).clan_by_alias("clan-1")).linked_by is None


def test_chi_ha_collegato_il_clan_resta_dopo_nome_nuovo_o_gruppo_nuovo(tmp_path):
    store = clan_store(tmp_path, 555)
    clan = asyncio.run(store.clan_by_alias("clan-1"))
    asyncio.run(store.rename_clan(clan, "Futuro 2"))
    rinominato = asyncio.run(store.clan_by_alias("clan-1"))
    assert (rinominato.name, rinominato.linked_by) == ("Futuro 2", 555)
    assert asyncio.run(store.move_clan(-100, -200)) is True
    spostato = asyncio.run(store.clan_by_alias("clan-1"))
    assert (spostato.chat_id, spostato.linked_by) == (-200, 555)


def test_i_candidati_a_delegato_sono_chi_ha_collegato_un_villaggio_nel_clan():
    store = FakeStore({"#L": 1, "#C": 2, "#E": 2, "#X": 9})
    assert asyncio.run(roles.linked_members(store, MEMBERS)) == [(1, "#L"), (2, "#C")]
    assert asyncio.run(roles.linked_members(store, {})) == []
    assert asyncio.run(roles.linked_members(store, None)) == []


def test_i_due_livelli_hanno_un_nome_solo_in_tutto_il_codice():
    from clashbot import settings as settings_mod
    assert (roles.MANAGER, roles.LIMITED) == (settings_mod.MANAGER, settings_mod.LIMITED)
