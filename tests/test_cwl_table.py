import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import cwl_cards, cwl_table, handlers, i18n
from clashbot.poller import Poller, Tick
from cwl_fixtures import SEASON, cwl_state, war_records

L = i18n.locale("it")
NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#C1", name="Futuro", bot_alias="bot-1")
ORDER = {"Gold League I": 11, "Crystal League I": 12, "Master League III": 13}
LAST = {"season": "2026-08", "league": "Crystal League I", "ranks": {"#C1": 1, "#C2": 8}}


class FakeStore:
    def __init__(self, state=None, kv=None, wars=()):
        self.state = {k: copy.deepcopy(v) for k, v in (state or {}).items()}
        self.kv = {k: copy.deepcopy(v) for k, v in (kv or {}).items()}
        self.wars = list(wars)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def recent_wars(self, alias, limit=10):
        return copy.deepcopy(self.wars)


class FakeCoc:
    def __init__(self, data=None, clans=None, fail=()):
        self.data = data
        self.clans = clans or {}
        self.fail = dict(fail)
        self.calls = 0
        self.asked = []

    async def war_leagues(self):
        self.calls += 1
        return copy.deepcopy(self.data), None

    async def clan(self, tag):
        self.asked.append(tag)
        if tag in self.fail:
            return None, self.fail[tag]
        return copy.deepcopy(self.clans.get(tag)), None


def fake_supervisor():
    return SimpleNamespace(bot=lambda alias: None, running=lambda: ["bot-1"],
                           default_alias="bot-1", owner_bot=lambda: None)


def test_la_classifica_porta_le_giornate_senza_rifare_la_somma():
    rows = cwl_table.table(cwl_state(), "#C1")
    assert [r["tag"] for r in rows] == ["#C1", "#C2"]
    assert rows[0]["rank"] == 1 and rows[0]["stars"] == 27 and rows[0]["us"] is True
    assert rows[0]["days"][1] == {"stars": 9, "destr": 90.0, "win": True}
    assert rows[0]["days"][2]["win"] is False
    assert rows[1]["days"][2]["win"] is True
    assert cwl_table.table(None, "#C1") == []


def test_la_proiezione_dice_posizione_migliore_e_peggiore():
    rows = cwl_table.projection(cwl_table.table(cwl_state(), "#C1"), 7, 3)
    ours = rows[0]
    assert ours["left"] == 5 and ours["best"] == 1 and ours["worst"] == 2
    finite = cwl_table.projection(cwl_table.table(cwl_state(), "#C1"), 2, 3)
    assert finite[0]["left"] == 0 and finite[0]["best"] == 1 and finite[0]["worst"] == 1


def test_le_fasce_si_osservano_non_si_inventano():
    leagues = {"#C1": "Master League III", "#C2": "Gold League I"}
    entry = cwl_table.observe(LAST, leagues, ORDER)
    assert entry == {"promote": 1, "demote": 8}
    assert cwl_table.zone(1, entry) == "up"
    assert cwl_table.zone(8, entry) == "down"
    assert cwl_table.zone(4, entry) == "safe"
    assert cwl_table.zone(4, None) is None
    solo_su = cwl_table.observe(LAST, {"#C1": "Master League III"}, ORDER)
    assert solo_su == {"promote": 1, "demote": 0}
    assert cwl_table.zone(1, solo_su) == "up"
    assert cwl_table.zone(4, solo_su) is None and cwl_table.zone(8, solo_su) is None
    assert cwl_table.observe(LAST, {"#C1": "Crystal League I", "#C2": "Crystal League I"}, ORDER) is None
    assert cwl_table.observe(None, leagues, ORDER) is None
    assert cwl_table.observe(LAST, leagues, {}) is None
    assert cwl_table.move_of("Crystal League I", "Master League III", ORDER) == "up"
    assert cwl_table.move_of("Crystal League I", "Gold League I", ORDER) == "down"
    assert cwl_table.move_of("Crystal League I", "Crystal League I", ORDER) == "same"
    assert cwl_table.move_of("Crystal League I", None, ORDER) is None


def test_ordine_ufficiale_delle_leghe_dalla_api():
    assert cwl_table.league_order({"items": [{"id": 11, "name": "Gold League I"},
                                             {"id": 12, "name": "Crystal League I"}]}) == {
        "Gold League I": 11, "Crystal League I": 12}
    assert cwl_table.league_order(None) == {}


def test_la_fotografia_del_girone_tiene_stagione_lega_e_posizioni():
    record = {"season": SEASON, "league": "Crystal League I"}
    assert cwl_table.snapshot(cwl_state(), record) == {
        "season": SEASON, "league": "Crystal League I", "ranks": {"#C1": 1, "#C2": 2}}


def test_la_card_mostra_proiezione_e_fasce_in_osservazione():
    rows = cwl_table.projection(cwl_table.table(cwl_state(), "#C1"), 7, 3)
    aperta = cwl_cards.table_card(L, rows, 2, 7)
    assert "CLASSIFICA · GIORNATA 2 di 7" in aperta and "in osservazione" in aperta
    assert "5 giornate" in aperta and "G1 ✅9⭐" in aperta
    con_fasce = cwl_cards.table_card(L, rows, 2, 7, {"promote": 2, "demote": 7})
    assert "⬆️" in con_fasce and "in osservazione" not in con_fasce
    assert "Nessuna Lega di Guerra" in cwl_cards.table_card(L, [], 0, 0)


def test_la_scheda_classifica_sta_tra_le_schede_della_cwl():
    assert "cwl:table" in handlers.CWL_TABS
    assert L.t("menu.cwl.table") != "[menu.cwl.table]"


def test_la_classifica_di_giornata_parte_una_volta_per_giornata(monkeypatch):
    sent = []

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        sent.append((event, render_text(t.L)))

    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    cwl = cwl_state()
    store = FakeStore(state={(CLAN.alias, "cwl_war"): {"teamSize": 3, "day": 2}})
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    t.L = L
    assert asyncio.run(poller.cwl_day_table(t, cwl)) is True
    assert sent[0][0] == "cwl.standings" and "CLASSIFICA" in sent[0][1]
    assert store.state[(CLAN.alias, "cwl")]["sent"]["table"] == 2
    assert asyncio.run(poller.cwl_day_table(t, cwl)) is False
    assert len(sent) == 1
    assert asyncio.run(poller.cwl_day_table(t, {})) is False


def test_l_elenco_delle_leghe_si_chiede_una_volta_al_giorno():
    coc = FakeCoc({"items": [{"id": 12, "name": "Crystal League I"}]})
    poller = Poller(fake_supervisor(), FakeStore(), coc)
    assert asyncio.run(poller.league_order(NOW)) == {"Crystal League I": 12}
    assert asyncio.run(poller.league_order(NOW)) == {"Crystal League I": 12}
    assert coc.calls == 1


def test_la_chiusura_lascia_la_fotografia_per_le_fasce(monkeypatch):
    async def fake_save(store, alias, season, ended_at, record):
        return True

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        render_text(t.L)

    monkeypatch.setattr("clashbot.cwl_store.save_season", fake_save)
    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    store = FakeStore(state={(CLAN.alias, "cwl"): cwl_state()}, wars=war_records())
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    t.L = L
    cwl = asyncio.run(store.get_state(CLAN.alias, "cwl"))
    assert asyncio.run(poller.close_cwl_season(t, cwl)) is True
    assert store.state[(CLAN.alias, "cwl_zones")]["last"] == {
        "season": SEASON, "league": "Crystal League I", "ranks": {"#C1": 1, "#C2": 2}}


def zones_setup(monkeypatch, coc, saved, last=None):
    async def fake_seasons(store, alias, limit=12):
        return [{"season": "2026-08", "league": "Crystal League I", "days": [], "move": None}]

    async def fake_save(store, alias, season, ended_at, record):
        saved.append(record)
        return True

    monkeypatch.setattr("clashbot.cwl_store.seasons", fake_seasons)
    monkeypatch.setattr("clashbot.cwl_store.save_season", fake_save)
    store = FakeStore(state={(CLAN.alias, "cwl_zones"): {"leagues": {},
                                                         "last": copy.deepcopy(last or LAST)}},
                      kv={"warleagues": {"order": ORDER, "fetched": NOW.timestamp()}})
    poller = Poller(fake_supervisor(), store, coc)
    t = Tick(CLAN, NOW)
    t.L = L
    return store, poller, t


def test_le_fasce_si_imparano_leggendo_gli_stessi_otto_clan_del_girone_finito(monkeypatch):
    saved = []
    coc = FakeCoc(clans={"#C1": {"warLeague": {"name": "Master League III"}},
                         "#C2": {"warLeague": {"name": "Gold League I"}}})
    store, poller, t = zones_setup(monkeypatch, coc, saved)
    nuovo = cwl_state(season=SEASON, league="Master League III",
                      clans={"#C1": {"name": "Nostro Clan"}, "#C9": {"name": "Clan Nuovo"}})
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is False
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is False
    assert coc.asked == ["#C1", "#C2"]
    assert store.state[(CLAN.alias, "cwl_zones")]["last"]["leagues"] == {
        "#C1": "Master League III", "#C2": "Gold League I"}
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is True
    zones = store.state[(CLAN.alias, "cwl_zones")]
    assert zones["leagues"]["Crystal League I"]["promote"] == 1
    assert zones["leagues"]["Crystal League I"]["demote"] == 8
    assert zones["leagues"]["Crystal League I"]["season"] == SEASON
    assert zones["last"] is None
    assert saved[0]["move"] == "up"
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is False
    assert coc.asked == ["#C1", "#C2"]


def test_una_lettura_andata_male_si_riprova_e_un_clan_sparito_non_blocca(monkeypatch):
    saved = []
    coc = FakeCoc(clans={"#C1": {"warLeague": {"name": "Master League III"}}},
                  fail={"#C1": "rate", "#C2": "not_found"})
    store, poller, t = zones_setup(monkeypatch, coc, saved)
    nuovo = cwl_state(season=SEASON, league="Master League III")
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is False
    assert store.state[(CLAN.alias, "cwl_zones")]["last"].get("leagues") in (None, {})
    coc.fail.pop("#C1")
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is False
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is False
    assert coc.asked == ["#C1", "#C1", "#C2"]
    assert asyncio.run(poller.learn_cwl_zones(t, nuovo)) is True
    entry = store.state[(CLAN.alias, "cwl_zones")]["leagues"]["Crystal League I"]
    assert entry == {"promote": 1, "demote": 0, "season": SEASON}
    assert cwl_table.zone(1, entry) == "up" and cwl_table.zone(4, entry) is None
