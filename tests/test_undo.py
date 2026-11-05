import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import (discipline, handlers, i18n, leader_cards, ledger, render, seats,
                      undo)
from clashbot import settings as settings_mod
from clashbot.crypto import Vault
from clashbot.db import SETTINGS_PREV, Store

IT = i18n.locale("it")
EN = i18n.locale("en")
NOW = datetime(2026, 9, 17, 9, tzinfo=timezone.utc)
TZ = "Europe/Rome"
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
MEMBERS = {"#P1": {"name": "Mario", "role": "leader"},
           "#P2": {"name": "Luigi", "role": "coLeader"},
           "#P3": {"name": "Peach", "role": "member"}}
LINKS = {"#P1": SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None),
         "#P2": SimpleNamespace(tag="#P2", user_id=8, name="Luigi", dm=True, lang=None)}
WARNINGS = [{"id": "aa", "tag": "#P3", "name": "Peach", "missed": 2, "at": 1758000000, "by": "#P1"},
            {"id": "bb", "tag": "#P2", "name": "Luigi", "missed": 1, "at": 1758000100, "by": "#P1"}]


class Held:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return Conn(self.pool)

    async def __aexit__(self, *exc):
        return False


class Conn:
    def __init__(self, pool):
        self.pool = pool

    def transaction(self):
        return Held(self.pool)

    async def execute(self, sql, *args):
        if "insert into leader_log" in sql:
            self.pool.rows.append((args[1], args[3]))
        return "INSERT 0 1"


class MemoryPool:
    def __init__(self):
        self.states = {}
        self.rows = []

    async def fetchrow(self, sql, *args):
        if "from clan_state" not in sql:
            return None
        stored = self.states.get((args[0], args[1]))
        return {"data": stored} if stored is not None else None

    async def execute(self, sql, *args):
        if "insert into clan_state" in sql:
            self.states[(args[0], args[1])] = args[3]
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        return [{"at": at, "data": data} for at, data in reversed(self.rows)][:args[1]]

    def acquire(self):
        return Held(self)


class LinkedStore(Store):
    def __init__(self, vault, links=None):
        super().__init__(vault)
        self.pool = MemoryPool()
        self.links = dict(LINKS if links is None else links)

    async def links_for_players(self, tags):
        wanted = set(tags or ())
        return {tag: link for tag, link in self.links.items() if tag in wanted}


def store_for(tmp_path, links=None):
    return LinkedStore(Vault(tmp_path), links)


async def salva(store, doc):
    await undo.keep_prev(store, CLAN.alias, doc)
    await store.set_state(CLAN.alias, "settings", doc)


def conf_with(delegates=()):
    return settings_mod.effective({"lang": "it", "tz": TZ, "delegates": list(delegates)}, None)


def log_of(store):
    return asyncio.run(store.recent_log(CLAN.alias))


def bare(row):
    return {key: value for key, value in row.items() if key != "at"}


def test_le_specie_di_annullo_e_chi_le_puo_usare():
    assert undo.KINDS == ("warning", "delegate", "settings")
    assert undo.can(MEMBERS, LINKS, 7) is True
    assert undo.can(MEMBERS, LINKS, 8) is False
    assert undo.can(MEMBERS, LINKS, 99) is False
    assert undo.can(None, None, 7) is False


def test_l_annullo_toglie_l_ammonizione_e_lascia_la_riga_nel_registro(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await store.set_state(CLAN.alias, "members", MEMBERS)
        await store.set_state(CLAN.alias, discipline.STATE, WARNINGS)
        done = await undo.apply(store, CLAN, conf_with(), "warning", "bb", 7, NOW)
        di_nuovo = await undo.apply(store, CLAN, conf_with(), "warning", "bb", 7, NOW)
        return done, di_nuovo, await store.get_state(CLAN.alias, discipline.STATE)

    done, di_nuovo, rimaste = asyncio.run(run())
    assert done is True and di_nuovo is False
    assert [row["id"] for row in rimaste] == ["aa"]
    righe = log_of(store)
    assert len(righe) == 1
    assert bare(righe[0]) == {"kind": "undo", "of": "warning", "ref": "bb", "by": 7,
                              "by_name": "Mario"}


def test_il_co_capo_non_annulla_niente(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await store.set_state(CLAN.alias, "members", MEMBERS)
        await store.set_state(CLAN.alias, discipline.STATE, WARNINGS)
        done = await undo.apply(store, CLAN, conf_with(), "warning", "bb", 8, NOW)
        return done, await store.get_state(CLAN.alias, discipline.STATE)

    done, rimaste = asyncio.run(run())
    assert done is False
    assert [row["id"] for row in rimaste] == ["aa", "bb"]
    assert log_of(store) == []


def test_la_revoca_toglie_il_delegato_dalle_impostazioni(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await store.set_state(CLAN.alias, "members", MEMBERS)
        await store.set_state(CLAN.alias, "settings", {"lang": "it", "tz": TZ, "delegates": [8, 9]})
        conf = settings_mod.effective(await store.get_state(CLAN.alias, "settings"), None)
        ref = seats.seat_ref(store.vault, CLAN.alias, 8)
        done = await undo.apply(store, CLAN, conf, "delegate", ref, 7, NOW)
        estraneo = await undo.apply(store, CLAN, conf, "delegate",
                                    seats.seat_ref(store.vault, CLAN.alias, 42), 7, NOW)
        return done, estraneo, await store.get_state(CLAN.alias, "settings")

    done, estraneo, stored = asyncio.run(run())
    assert done is True and estraneo is False
    assert stored["delegates"] == [9]
    righe = log_of(store)
    assert len(righe) == 1
    assert bare(righe[0]) == {"kind": "undo", "of": "delegate",
                              "ref": seats.seat_ref(store.vault, CLAN.alias, 8), "by": 7,
                              "by_name": "Mario"}


def test_la_revoca_accetta_il_riferimento_vecchio_e_quello_nuovo(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await store.set_state(CLAN.alias, "members", MEMBERS)
        await store.set_state(CLAN.alias, "settings",
                              {"lang": "it", "tz": TZ, "delegates": [8, 9]})
        conf = settings_mod.effective(await store.get_state(CLAN.alias, "settings"), None)
        vecchio = await undo.apply(store, CLAN, conf, "delegate", "8", 7, NOW)
        stored = await store.get_state(CLAN.alias, "settings")
        conf = settings_mod.effective(stored, None)
        nuovo = await undo.apply(store, CLAN, conf, "delegate",
                                 seats.seat_ref(store.vault, CLAN.alias, 9), 7, NOW)
        estraneo = await undo.apply(store, CLAN,
                                    settings_mod.effective(
                                        await store.get_state(CLAN.alias, "settings"), None),
                                    "delegate", "42", 7, NOW)
        return vecchio, nuovo, estraneo, await store.get_state(CLAN.alias, "settings")

    vecchio, nuovo, estraneo, stored = asyncio.run(run())
    assert (vecchio, nuovo, estraneo) == (True, True, False)
    assert stored["delegates"] == []


def test_le_impostazioni_tornano_alla_penultima_versione(tmp_path):
    store = store_for(tmp_path)
    prima = {"lang": "it", "tz": TZ, "note": "prima"}
    poi = {"lang": "it", "tz": TZ, "note": "poi"}

    async def run():
        await store.set_state(CLAN.alias, "members", MEMBERS)
        await salva(store, prima)
        await salva(store, poi)
        penultima = await store.get_state(CLAN.alias, SETTINGS_PREV)
        done = await undo.apply(store, CLAN, conf_with(), "settings", "prev", 7, NOW)
        return penultima, done, await store.get_state(CLAN.alias, "settings")

    penultima, done, tornata = asyncio.run(run())
    assert penultima == prima
    assert done is True and tornata == prima
    assert bare(log_of(store)[0]) == {"kind": "undo", "of": "settings", "ref": "prev", "by": 7,
                                      "by_name": "Mario"}


def test_la_versione_precedente_sta_nel_database_cifrata(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await salva(store, {"lang": "it", "tz": TZ, "note": "prima"})
        await salva(store, {"lang": "it", "tz": TZ, "note": "poi"})

    asyncio.run(run())
    assert (CLAN.alias, SETTINGS_PREV) in store.pool.states
    for blob in store.pool.states.values():
        assert b"prima" not in bytes(blob) and b"Europe/Rome" not in bytes(blob)


def test_il_salvataggio_di_un_gestore_lascia_la_versione_precedente(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await handlers.save_settings(store, CLAN, {"lang": "it", "tz": TZ})
        await handlers.save_settings(store, CLAN, {"lang": "en"})
        return await store.get_state(CLAN.alias, SETTINGS_PREV)

    penultima = asyncio.run(run())
    assert penultima["lang"] == "it"


def test_il_collegamento_del_clan_non_lascia_una_versione_precedente(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await handlers.save_settings(store, CLAN, {"lang": "it", "tz": TZ}, keep_prev=False)
        await handlers.save_settings(store, CLAN, {"lang": "en"}, keep_prev=False)
        return await store.get_state(CLAN.alias, SETTINGS_PREV)

    assert asyncio.run(run()) is None


def test_un_salvataggio_automatico_non_diventa_la_versione_precedente(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await salva(store, {"lang": "it", "tz": TZ, "note": "scelta dal capo"})
        await store.set_state(CLAN.alias, "settings", {"lang": "en", "tz": TZ})
        return await store.get_state(CLAN.alias, SETTINGS_PREV)

    assert asyncio.run(run()) is None


def test_senza_versione_precedente_non_si_torna_indietro(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await store.set_state(CLAN.alias, "members", MEMBERS)
        await store.set_state(CLAN.alias, "settings", {"lang": "it", "tz": TZ})
        return await undo.apply(store, CLAN, conf_with(), "settings", "prev", 7, NOW)

    assert asyncio.run(run()) is False
    assert log_of(store) == []


def test_un_annullo_di_specie_sconosciuta_non_tocca_niente(tmp_path):
    store = store_for(tmp_path)

    async def run():
        await store.set_state(CLAN.alias, "members", MEMBERS)
        await store.set_state(CLAN.alias, discipline.STATE, WARNINGS)
        return await undo.apply(store, CLAN, conf_with(), "targets", "bb", 7, NOW)

    assert asyncio.run(run()) is False
    assert log_of(store) == []


def test_void_toglie_solo_la_riga_con_quel_codice():
    rimaste = discipline.void(WARNINGS, "aa")
    assert [row["id"] for row in rimaste] == ["bb"]
    assert discipline.void(WARNINGS, "zz") is None
    assert discipline.void(None, "aa") is None


def test_il_registro_mostra_il_nome_di_chi_ha_agito():
    righe = [{"kind": "undo", "of": "warning", "ref": "bb", "by": 7, "by_name": "Mario", "at": NOW},
             {"kind": "warning", "ref": "bb", "by": 7, "by_name": "Mario", "at": NOW},
             {"kind": "delegate", "ref": "zz9", "by": 7, "by_name": "Mario", "at": NOW},
             {"action": "export", "by": 7, "by_name": "Mario", "detail": "wars", "at": NOW}]
    text = leader_cards.log_card(IT, TZ, righe)
    assert text.count("Mario") == len(righe)
    assert IT.t("leaders.log.action.undo") in text
    assert IT.t("leaders.log.action.warning") in text
    assert IT.t("leaders.log.action.delegate") in text
    assert IT.t("leaders.log.action.export") in text
    assert "bb" not in text and "zz9" not in text
    assert len(text) <= render.MAX_LEN


def test_il_registro_dice_quale_bersaglio_e_stato_toccato():
    righe = [{"kind": "target", "ref": "7", "by": 7, "by_name": "Mario", "at": NOW},
             {"kind": "target", "ref": "mirror", "by": 7, "by_name": "Mario", "at": NOW},
             {"kind": "target", "ref": "clear", "by": 7, "by_name": "Mario", "at": NOW}]
    text = leader_cards.log_card(IT, TZ, righe)
    assert "#7" in text
    assert IT.t("h.target_mirror") in text and IT.t("h.target_clear") in text
    assert "mirror" not in text and "clear" not in text


def test_le_chiavi_nuove_esistono():
    for kind in ledger.KINDS:
        for L in (IT, EN):
            assert not L.t(f"leaders.log.action.{kind}").startswith("["), kind
    assert not EN.t("warn.notice_by", name="Mario").startswith("[")
