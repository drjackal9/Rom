import asyncio
import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from clashbot import ambassadors, brake, discipline, events_registry, feed, guard, i18n, poller
from clashbot import roles
from clashbot import settings as settings_mod
from clashbot.platform_guard import FLOOD_LIMIT, FLOOD_WINDOW

IT = i18n.locale("it")
EN = i18n.locale("en")
NOW = datetime(2026, 9, 17, 9, tzinfo=timezone.utc)
TZ = "Europe/Rome"
CHIEF = 7
DEPUTY = 8
MEMBER = 9
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro",
                       bot_alias="bot-1", linked_by=CHIEF)
MEMBERS = {"#P1": {"name": "Mario", "role": "leader"},
           "#P2": {"name": "Luigi", "role": "coLeader"},
           "#P3": {"name": "Peach", "role": "member"}}
LINKS = {"#P1": SimpleNamespace(tag="#P1", user_id=CHIEF, name="Mario", dm=True, lang=None),
         "#P2": SimpleNamespace(tag="#P2", user_id=DEPUTY, name="Luigi", dm=True, lang=None),
         "#P3": SimpleNamespace(tag="#P3", user_id=MEMBER, name="Peach", dm=True, lang=None)}
STORED = {"lang": "it", "tz": TZ}
CONF = settings_mod.effective(STORED, None)


class FakeStore:
    def __init__(self):
        self.kv, self.ttl, self.refs = {}, {}, {}
        self.state = {("clan-1", "settings"): copy.deepcopy(STORED),
                      ("clan-1", "members"): copy.deepcopy(MEMBERS)}
        self.links = dict(LINKS)

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)
        self.refs[key], self.ttl[key] = ref, ttl

    async def kv_del(self, key):
        self.kv.pop(key, None)
        self.refs.pop(key, None)
        self.ttl.pop(key, None)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def bot_by_alias(self, alias):
        return None

    async def links_for_players(self, tags):
        wanted = set(tags or ())
        return {tag: link for tag, link in self.links.items() if tag in wanted}

    async def links_by_user(self, user_id):
        return [link for link in self.links.values() if link.user_id == user_id]


async def press(store, uid, times, start=NOW, step=timedelta(minutes=1), kind="warning"):
    return [await guard.destructive(store, CLAN.alias, uid, kind, start + step * n)
            for n in range(times)]


def rows_of(store, uid):
    return asyncio.run(feed.rows(store, CLAN.alias, uid))


def managers_of(store):
    return asyncio.run(roles.managers(store, CLAN, CONF, MEMBERS))


COPERTE = ("warning", "settings", "delegate.remove", "text.delete", "schedule.delete", "undo")
CHIAMATA = re.compile(r"destructive\([^)]*?\"([a-z_.]+)\"")


def test_il_catalogo_delle_azioni_distruttive_e_quello_deciso():
    assert guard.DESTRUCTIVE == ("warning", "settings", "delegate.remove", "text.delete",
                                 "schedule.delete", "undo")


def test_le_azioni_frenate_oggi_sono_quelle_del_catalogo():
    assert set(COPERTE) == set(guard.DESTRUCTIVE)
    assert brake.SETTINGS in guard.DESTRUCTIVE and brake.DELEGATE in guard.DESTRUCTIVE


def test_ogni_chiamata_al_freno_nomina_un_tipo_del_catalogo():
    trovati = set()
    for path in sorted(Path(guard.__file__).parent.glob("*.py")):
        trovati.update(CHIAMATA.findall(path.read_text(encoding="utf-8")))
    assert trovati <= set(guard.DESTRUCTIVE)
    assert trovati | {brake.SETTINGS, brake.DELEGATE} == set(COPERTE)


def test_un_azione_fuori_dal_catalogo_non_conta_e_non_lascia_traccia():
    store = FakeStore()
    assert asyncio.run(guard.destructive(store, CLAN.alias, DEPUTY, "sfregio", NOW)) == (0, False)
    assert store.kv == {}
    assert not asyncio.run(guard.suspended(store, CLAN.alias, DEPUTY))


def test_le_voci_di_feed_non_sono_eventi_instradabili():
    assert guard.EVENT == events_registry.LEADERS_SUSPENDED
    assert poller.BOARD_LOST == events_registry.BOARD_LOST
    for name in events_registry.FEED_ONLY:
        assert not events_registry.routed(name), name


def test_le_voci_di_feed_scritte_dagli_handler_sono_quelle_dichiarate():
    assert events_registry.HANDLER_FEED == (discipline.EVENT, ambassadors.EVENT)
    for name in events_registry.HANDLER_FEED:
        assert events_registry.routed(name), name
        assert name not in events_registry.FEED_ONLY, name


def test_nel_feed_scrivono_solo_i_moduli_dichiarati():
    trovati = {path.name for path in sorted(Path(guard.__file__).parent.glob("*.py"))
               if "feed.add(" in path.read_text(encoding="utf-8")}
    assert trovati == {"guard.py", "leaders.py", "linking.py", "poller.py", "discipline.py",
                       "ambassadors.py"}


def test_le_soglie_sono_quelle_gia_decise_per_il_flood():
    assert FLOOD_LIMIT == 5 and FLOOD_WINDOW == 3600


def test_quattro_azioni_distruttive_in_un_ora_non_sospendono_nessuno():
    store = FakeStore()
    esiti = asyncio.run(press(store, DEPUTY, FLOOD_LIMIT - 1))
    assert esiti == [(1, False), (2, False), (3, False), (4, False)]
    assert not asyncio.run(guard.suspended(store, CLAN.alias, DEPUTY))
    assert rows_of(store, CHIEF) == [] and rows_of(store, DEPUTY) == []


def test_alla_quinta_azione_il_posto_e_sospeso_e_lo_staff_lo_legge_nel_feed():
    store = FakeStore()
    esiti = asyncio.run(press(store, DEPUTY, FLOOD_LIMIT))
    assert esiti[-1] == (FLOOD_LIMIT, True)
    assert asyncio.run(guard.suspended(store, CLAN.alias, DEPUTY))
    atteso = IT.t("feed.suspended", name="Luigi")
    assert [row["text"] for row in rows_of(store, CHIEF)] == [atteso]
    assert [row["text"] for row in rows_of(store, DEPUTY)] == [atteso]
    assert rows_of(store, MEMBER) == []


def test_passata_la_finestra_il_conteggio_riparte():
    store = FakeStore()
    asyncio.run(press(store, DEPUTY, FLOOD_LIMIT - 1))
    oltre = NOW + timedelta(seconds=FLOOD_WINDOW) + timedelta(minutes=FLOOD_LIMIT)
    dopo = asyncio.run(press(store, DEPUTY, 1, start=oltre))
    assert dopo == [(1, False)]
    assert not asyncio.run(guard.suspended(store, CLAN.alias, DEPUTY))


def test_il_capo_del_gioco_non_si_sospende_ma_lo_staff_riceve_l_avviso():
    store = FakeStore()
    esiti = asyncio.run(press(store, CHIEF, FLOOD_LIMIT))
    assert esiti[-1] == (FLOOD_LIMIT, False)
    assert not asyncio.run(guard.suspended(store, CLAN.alias, CHIEF))
    atteso = IT.t("feed.suspended", name="Mario")
    assert [row["text"] for row in rows_of(store, CHIEF)] == [atteso]
    assert [row["text"] for row in rows_of(store, DEPUTY)] == [atteso]
    assert managers_of(store) == {CHIEF: settings_mod.MANAGER, DEPUTY: settings_mod.MANAGER}


def senza_capi():
    return {tag: dict(row, role="member") for tag, row in MEMBERS.items()}


def gestori(store, members):
    return asyncio.run(roles.managers(store, CLAN, CONF, members))


def test_il_creatore_unico_gestore_non_si_sospende_ma_lo_staff_riceve_l_avviso():
    store = FakeStore()
    members = senza_capi()
    store.state[("clan-1", "members")] = copy.deepcopy(members)
    assert gestori(store, members) == {CHIEF: settings_mod.MANAGER}
    esiti = asyncio.run(press(store, CHIEF, FLOOD_LIMIT))
    assert esiti[-1] == (FLOOD_LIMIT, False)
    assert not asyncio.run(guard.suspended(store, CLAN.alias, CHIEF))
    assert [row["text"] for row in rows_of(store, CHIEF)] == [IT.t("feed.suspended", name="Mario")]
    assert gestori(store, members) == {CHIEF: settings_mod.MANAGER}


def test_il_creatore_si_sospende_quando_dal_gioco_comanda_qualcun_altro():
    store = FakeStore()
    store.state[("clan-1", "members")] = dict(MEMBERS, **{"#P1": {"name": "Mario",
                                                                  "role": "member"}})
    esiti = asyncio.run(press(store, CHIEF, FLOOD_LIMIT))
    assert esiti[-1] == (FLOOD_LIMIT, True)
    assert asyncio.run(guard.suspended(store, CLAN.alias, CHIEF))


def test_i_gestori_non_contano_chi_e_sospeso():
    store = FakeStore()
    assert managers_of(store) == {CHIEF: settings_mod.MANAGER, DEPUTY: settings_mod.MANAGER}
    asyncio.run(press(store, DEPUTY, FLOOD_LIMIT))
    assert managers_of(store) == {CHIEF: settings_mod.MANAGER}


def test_il_capo_riattiva_il_posto_sospeso():
    store = FakeStore()
    asyncio.run(press(store, DEPUTY, FLOOD_LIMIT))
    assert asyncio.run(guard.lift(store, CLAN.alias, DEPUTY))
    assert not asyncio.run(guard.suspended(store, CLAN.alias, DEPUTY))
    assert managers_of(store) == {CHIEF: settings_mod.MANAGER, DEPUTY: settings_mod.MANAGER}
    assert not asyncio.run(guard.lift(store, CLAN.alias, DEPUTY))


def test_il_freno_scade_con_la_finestra_la_sospensione_no():
    store = FakeStore()
    asyncio.run(press(store, DEPUTY, FLOOD_LIMIT - 1))
    chiave = guard.abuse_key(CLAN.alias, DEPUTY)
    assert chiave == f"abuse:{CLAN.alias}:{DEPUTY}"
    assert store.ttl[chiave] == FLOOD_WINDOW and store.refs[chiave] == CLAN.alias
    asyncio.run(press(store, DEPUTY, 1, start=NOW + timedelta(minutes=FLOOD_LIMIT)))
    sospeso = guard.suspended_key(CLAN.alias, DEPUTY)
    assert sospeso == f"suspended:{CLAN.alias}:{DEPUTY}"
    assert store.ttl[sospeso] is None and store.refs[sospeso] == CLAN.alias


def test_il_conteggio_e_separato_per_persona():
    store = FakeStore()
    asyncio.run(press(store, DEPUTY, FLOOD_LIMIT - 1))
    assert asyncio.run(press(store, CHIEF, 1)) == [(1, False)]


def test_la_pausa_del_capo_si_accende_e_si_spegne():
    store = FakeStore()
    assert asyncio.run(guard.paused(store, CLAN.alias)) is None
    asyncio.run(guard.pause(store, CLAN.alias, CHIEF, NOW))
    assert asyncio.run(guard.paused(store, CLAN.alias)) == {"by": CHIEF, "at": NOW.timestamp()}
    assert store.state[(CLAN.alias, guard.PAUSE)] == {"by": CHIEF, "at": NOW.timestamp()}
    asyncio.run(guard.resume(store, CLAN.alias))
    assert asyncio.run(guard.paused(store, CLAN.alias)) is None


def test_le_chiavi_nuove_sono_vere_in_italiano_e_in_inglese():
    for key in ("h.suspended", "h.suspend_notice", "feed.suspended", "board.all.paused"):
        assert IT.t(key, name="Luigi", clan="Futuro") != EN.t(key, name="Luigi", clan="Futuro")
        assert not IT.t(key, name="Luigi", clan="Futuro").startswith("[")
        assert not EN.t(key, name="Luigi", clan="Futuro").startswith("[")
