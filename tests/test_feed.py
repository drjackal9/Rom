import asyncio
import copy
from datetime import datetime, timedelta, timezone

from clashbot import feed, platform_guard, retention

ALIAS = "clan-1"
UID = 42
OTHER = 77
NOW = datetime(2026, 9, 17, 9, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self):
        self.kv, self.refs, self.ttl = {}, {}, {}

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)
        self.refs[key], self.ttl[key] = ref, ttl

    async def kv_del(self, key):
        self.kv.pop(key, None)
        self.refs.pop(key, None)
        self.ttl.pop(key, None)


def at(minutes):
    return NOW + timedelta(minutes=minutes)


def test_la_chiave_nomina_il_clan_e_la_persona():
    assert feed.key_of(ALIAS, UID) == f"feed:{ALIAS}:{UID}"
    assert feed.key_of(ALIAS, str(UID)) == feed.key_of(ALIAS, UID)


def test_i_tetti_del_feed_sono_quelli_gia_decisi():
    assert feed.KEEP == retention.WAR_HISTORY_KEEP
    assert feed.TTL == platform_guard.IDLE_TTL


def test_una_novita_finisce_nel_feed_con_ora_tipo_e_testo():
    store = FakeStore()
    count = asyncio.run(feed.add(store, ALIAS, UID, "goal.done", "Obiettivo raggiunto", NOW))
    assert count == 1
    assert asyncio.run(feed.rows(store, ALIAS, UID)) == [
        {"at": int(NOW.timestamp()), "kind": "goal.done", "text": "Obiettivo raggiunto"}
    ]


def test_il_feed_resta_appeso_al_clan_e_scade_da_solo():
    store = FakeStore()
    asyncio.run(feed.add(store, ALIAS, UID, "goal.done", "Obiettivo raggiunto", NOW))
    key = feed.key_of(ALIAS, UID)
    assert store.refs[key] == ALIAS
    assert store.ttl[key] == feed.TTL


def test_il_feed_tiene_le_ultime_cento_voci_come_lo_storico_delle_guerre():
    store = FakeStore()
    for number in range(1, 131):
        count = asyncio.run(feed.add(store, ALIAS, UID, "war.attack", f"voce {number}", at(number)))
    rows = asyncio.run(feed.rows(store, ALIAS, UID))
    assert count == retention.WAR_HISTORY_KEEP
    assert len(rows) == retention.WAR_HISTORY_KEEP
    assert rows[0]["text"] == "voce 31"
    assert rows[-1]["text"] == "voce 130"


def test_le_novita_non_lette_sono_quelle_arrivate_dopo_l_ultima_letta():
    store = FakeStore()
    for number in range(1, 4):
        asyncio.run(feed.add(store, ALIAS, UID, "war.attack", f"voce {number}", at(number)))
    assert asyncio.run(feed.unread(store, ALIAS, UID)) == 3
    asyncio.run(feed.mark_read(store, ALIAS, UID, at(2)))
    assert asyncio.run(feed.unread(store, ALIAS, UID)) == 1


def test_appena_letto_il_feed_non_ha_piu_novita_ma_tiene_le_voci():
    store = FakeStore()
    asyncio.run(feed.add(store, ALIAS, UID, "goal.done", "Obiettivo raggiunto", NOW))
    asyncio.run(feed.mark_read(store, ALIAS, UID, at(1)))
    assert asyncio.run(feed.unread(store, ALIAS, UID)) == 0
    assert len(asyncio.run(feed.rows(store, ALIAS, UID))) == 1
    key = feed.key_of(ALIAS, UID)
    assert store.refs[key] == ALIAS and store.ttl[key] == feed.TTL


def test_una_novita_dopo_la_lettura_torna_a_contare():
    store = FakeStore()
    asyncio.run(feed.add(store, ALIAS, UID, "goal.done", "Obiettivo raggiunto", NOW))
    asyncio.run(feed.mark_read(store, ALIAS, UID, at(1)))
    asyncio.run(feed.add(store, ALIAS, UID, "war.attack", "Tocca a te", at(2)))
    assert asyncio.run(feed.unread(store, ALIAS, UID)) == 1


def test_chi_chiede_di_essere_dimenticato_perde_il_suo_feed():
    store = FakeStore()
    asyncio.run(feed.add(store, ALIAS, UID, "goal.done", "Obiettivo raggiunto", NOW))
    asyncio.run(feed.forget(store, ALIAS, UID))
    assert feed.key_of(ALIAS, UID) not in store.kv
    assert asyncio.run(feed.rows(store, ALIAS, UID)) == []
    assert asyncio.run(feed.unread(store, ALIAS, UID)) == 0


def test_il_feed_di_una_persona_non_si_mescola_con_quello_di_un_altra():
    store = FakeStore()
    asyncio.run(feed.add(store, ALIAS, UID, "goal.done", "La tua", NOW))
    asyncio.run(feed.add(store, ALIAS, OTHER, "goal.done", "La sua", NOW))
    asyncio.run(feed.forget(store, ALIAS, UID))
    assert [row["text"] for row in asyncio.run(feed.rows(store, ALIAS, OTHER))] == ["La sua"]
    assert asyncio.run(feed.rows(store, ALIAS, UID)) == []


def test_un_feed_mai_scritto_e_vuoto_e_senza_novita():
    store = FakeStore()
    assert asyncio.run(feed.rows(store, ALIAS, UID)) == []
    assert asyncio.run(feed.unread(store, ALIAS, UID)) == 0
    assert store.kv == {}


def test_chi_apre_novita_che_non_ha_non_lascia_righe():
    store = FakeStore()
    asyncio.run(feed.mark_read(store, ALIAS, UID, NOW))
    assert store.kv == {}
    asyncio.run(feed.add(store, ALIAS, UID, "goal.done", "Obiettivo raggiunto", at(1)))
    assert asyncio.run(feed.unread(store, ALIAS, UID)) == 1
