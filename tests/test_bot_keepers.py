import asyncio
from types import SimpleNamespace

from clashbot import roles
from test_roles import CLAN, MEMBERS, FakeCoc, FakeStore

CAPO = 1
COCAPO = 2
ANZIANO = 3
CREATORE = 555
LINKS = {"#L": CAPO, "#C": COCAPO, "#E": ANZIANO}
FUORI = {"#L": CAPO, "#C": COCAPO, "#E": ANZIANO, "#M": CREATORE}
BOT = SimpleNamespace(alias="bot-1", owner_id=CREATORE, username="unBot")


class ClanStore(FakeStore):
    def __init__(self, links, owner=CREATORE, members=None, clans=(CLAN,)):
        super().__init__(links, owner)
        self.members = MEMBERS if members is None else members
        self.clans = list(clans)

    async def get_state(self, alias, kind):
        return dict(self.members) if kind == "members" else None

    async def active_clans(self, bot_alias=None):
        return list(self.clans)


def keeps(store, uid, coc=None, bot=BOT):
    return asyncio.run(roles.keeps_bot(store, coc, bot, uid))


def test_il_capo_del_momento_tiene_il_bot_anche_se_non_l_ha_creato():
    assert keeps(ClanStore(LINKS), CAPO) is True


def test_il_co_capo_non_ferma_e_non_toglie_il_bot():
    assert keeps(ClanStore(LINKS), COCAPO) is False


def test_l_anziano_non_ferma_e_non_toglie_il_bot():
    assert keeps(ClanStore(LINKS), ANZIANO) is False


def test_chi_l_ha_creato_lo_tiene_finche_e_nel_clan():
    assert keeps(ClanStore(FUORI), CREATORE) is True


def test_il_creatore_uscito_dal_clan_non_tocca_piu_il_bot():
    assert keeps(ClanStore(LINKS), CREATORE) is False


def test_senza_clan_il_bot_resta_di_chi_l_ha_creato():
    store = ClanStore({}, clans=())
    assert keeps(store, CREATORE) is True
    assert keeps(store, COCAPO) is False


def test_il_capo_si_legge_dalla_rosa_viva_quando_il_gioco_risponde():
    coc = FakeCoc({"#C": {"role": "leader", "clan": {"tag": CLAN.tag}}})
    assert keeps(ClanStore(LINKS), COCAPO, coc=coc) is True


def test_il_passaggio_del_capo_vale_subito_anche_al_vecchio_capo():
    coc = FakeCoc({"#L": {"role": "coLeader", "clan": {"tag": CLAN.tag}}})
    assert keeps(ClanStore(LINKS), CAPO, coc=coc) is False
