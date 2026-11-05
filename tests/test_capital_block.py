import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import (boards, capital, feed, handlers, i18n, progress, scoring,
                      settings as settings_mod)
from clashbot.events import member_snapshot
from clashbot.events_registry import EVENTS
from clashbot.poller import Poller, Tick
from fixtures import BASE_MEMBERS, clan_json
from test_flows import ALIAS, CLAN, FakeStore, fake_supervisor

L = i18n.locale("it")
EN = i18n.locale("en")
TZ = "Europe/Rome"
NOW = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


def raid(state="ended"):
    return {
        "state": state,
        "startTime": "20260911T070000.000Z",
        "endTime": "20260914T070000.000Z",
        "capitalTotalLoot": 123456,
        "totalAttacks": 9,
        "raidsCompleted": 2,
        "enemyDistrictsDestroyed": 3,
        "members": [
            {"tag": "#P1", "name": "Mario", "attacks": 6, "attackLimit": 5, "bonusAttackLimit": 1,
             "capitalResourcesLooted": 60000},
            {"tag": "#P2", "name": "Luigi", "attacks": 2, "attackLimit": 5, "bonusAttackLimit": 0,
             "capitalResourcesLooted": 30000},
        ],
        "attackLog": [
            {"defender": {"name": "Nemici"}, "districts": [
                {"name": "Picco del Capitale", "districtHallLevel": 8, "destructionPercent": 100,
                 "attackCount": 4, "totalLooted": 40000},
                {"name": "Radura Barbara", "districtHallLevel": 4, "destructionPercent": 60,
                 "attackCount": 3, "totalLooted": 12000},
            ]},
            {"defender": {"name": "Altri"}, "districts": [
                {"name": "Picco del Capitale", "districtHallLevel": 8, "destructionPercent": 100,
                 "attackCount": 2, "totalLooted": 30000},
            ]},
        ],
    }


def test_efficienza_ordina_per_bottino_per_attacco():
    rows = capital.efficiency_rows(raid())
    assert [r["name"] for r in rows] == ["Luigi", "Mario"]
    assert rows[0]["per_attack"] == 15000 and rows[1]["per_attack"] == 10000
    assert rows[0]["left"] == 3 and rows[1]["left"] == 0
    assert capital.efficiency_rows({"members": []}) == []


def test_distretti_sommano_attacchi_e_abbattimenti():
    rows = capital.district_rows(raid())
    picco = next(r for r in rows if r["name"] == "Picco del Capitale")
    assert picco["attacks"] == 6 and picco["done"] == 2 and picco["loot"] == 70000 and picco["level"] == 8
    radura = next(r for r in rows if r["name"] == "Radura Barbara")
    assert radura["done"] == 0 and radura["attacks"] == 3
    assert rows[0]["name"] == "Picco del Capitale"


def test_chi_non_ha_fatto_i_raid_conta_anche_chi_non_ha_partecipato():
    members = member_snapshot(clan_json(BASE_MEMBERS))
    rows = capital.skipped_rows(raid(), members)
    by_name = {r["name"]: r for r in rows}
    assert "Mario" not in by_name
    assert by_name["Luigi"]["left"] == 3 and by_name["Luigi"]["done"] == 2
    assert by_name["Peach"]["left"] == 5 and by_name["Toad"]["left"] == 5
    assert [r["name"] for r in rows][:2] == ["Peach", "Toad"]


def test_gli_attacchi_liberi_sono_quelli_che_restano_a_tutto_il_clan():
    members = member_snapshot(clan_json(BASE_MEMBERS))
    assert capital.free_attacks(raid("ongoing"), members) == 13
    assert capital.free_attacks(raid("ongoing"), {"#P1": {"name": "Mario"}}) == 0
    assert capital.free_attacks(None, {"#P2": {"name": "Luigi"}}) == 5


def test_oro_versato_usa_i_contatori_gia_raccolti():
    activity = [
        {"tag": "#P1", "name": "Mario", "capital_gold": 50000, "raid_loot": 120000},
        {"tag": "#P2", "name": "Luigi", "capital_gold": 90000, "raid_loot": 0},
        {"tag": "#P3", "name": "Peach", "capital_gold": 0, "raid_loot": 4000},
    ]
    rows = capital.gold_rows(activity)
    assert [r["name"] for r in rows] == ["Luigi", "Mario"]
    assert rows[0]["gold"] == 90000
    assert "Peach" not in capital.gold_card(L, activity)
    assert "Luigi" in capital.gold_card(L, activity)


def progress_state(mario_gold, luigi_gold):
    return {
        "#P1": {"name": "Mario", "now": {k: 0 for k in progress.COUNTERS} | {"capital_gold": mario_gold,
                                                                             "raid_loot": 3000}},
        "#P2": {"name": "Luigi", "now": {k: 0 for k in progress.COUNTERS} | {"capital_gold": luigi_gold,
                                                                             "raid_loot": 0}},
    }


def test_base_dell_oro_si_ancora_all_apertura_del_weekend():
    members = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}, "#P3": {"name": "Peach"}}
    cap = capital.track_gold({}, progress_state(1_000_000, 2_000_000), members)
    assert cap["gold_base"]["#P1"] == {"capital_gold": 1_000_000, "raid_loot": 3000}
    assert "#P3" not in cap["gold_base"]
    capital.track_gold(cap, progress_state(1_090_000, 2_000_000), members)
    assert cap["gold_base"]["#P1"]["capital_gold"] == 1_000_000
    rows = capital.gold_since(progress_state(1_090_000, 2_000_000), cap)
    assert capital.gold_rows(rows) == [{"tag": "#P1", "name": "Mario", "gold": 90000, "loot": 0}]


def test_oro_del_weekend_non_dipende_dal_delta_settimanale():
    members = {"#P1": {"name": "Mario"}}
    venerdi = datetime(2026, 9, 11, 7, tzinfo=timezone.utc)
    state = progress.update({}, "#P1", "Mario", {"capital_gold": 1_000_000}, venerdi, TZ)
    cap = capital.track_gold({}, state, members)
    sabato = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
    state = progress.update(state, "#P1", "Mario", {"capital_gold": 1_090_000}, sabato, TZ)
    lunedi = datetime(2026, 9, 14, 6, tzinfo=timezone.utc)
    state = progress.update(state, "#P1", "Mario", {"capital_gold": 1_090_000}, lunedi, TZ)
    assert progress.deltas(state, "week")[0]["capital_gold"] == 0
    assert capital.gold_rows(capital.gold_since(state, cap))[0]["gold"] == 90000


def test_chi_esce_dal_clan_esce_dalla_base():
    members = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}}
    cap = capital.track_gold({}, progress_state(10, 20), members)
    capital.track_gold(cap, progress_state(10, 20), {"#P1": {"name": "Mario"}})
    assert list(cap["gold_base"]) == ["#P1"]
    assert capital.gold_since({}, {}) == []


def test_livello_capitale_e_prossimi_obiettivi():
    payload = {"clanCapital": {"capitalHallLevel": 8, "districts": [
        {"name": "Picco del Capitale", "districtHallLevel": 8},
        {"name": "Radura Barbara", "districtHallLevel": 5},
        {"name": "Valle dell'Arciere", "districtHallLevel": 0},
    ]}}
    hall = capital.hall_snapshot(payload)
    assert hall["level"] == 8 and hall["districts"][0]["name"] == "Picco del Capitale"
    assert [d["name"] for d in capital.next_goals(hall)] == ["Radura Barbara"]
    assert capital.hall_snapshot({}) is None
    assert capital.hall_events(None, hall) == []
    salito = {"level": 9, "districts": [{"name": "Radura Barbara", "level": 6},
                                        {"name": "Picco del Capitale", "level": 8}]}
    kinds = [e["type"] for e in capital.hall_events(hall, salito)]
    assert kinds == ["capital_hall", "district"]
    assert "9" in capital.level_cards(L, capital.hall_events(hall, salito))[0]


def test_card_di_fine_weekend_guadagna_efficienza_e_distretti():
    extra = capital.end_extra(L, raid())
    assert "Luigi" in extra and "Picco del Capitale" in extra
    assert len(extra) < 2000


def test_privato_a_chi_ha_saltato_i_raid_non_fa_la_predica():
    row = {"tag": "#P2", "name": "Luigi", "left": 3, "done": 2}
    text = capital.skipped_dm(L, TZ, row, datetime(2026, 9, 18, 7, tzinfo=timezone.utc))
    assert "3" in text and "ven" in text
    assert "Luigi" not in text
    assert capital.skipped_dm(EN, TZ, row) != text


def test_record_del_weekend_per_lo_storico():
    record = capital.raid_record(raid())
    assert record["season"] == "20260911T070000.000Z" and record["loot"] == 123456
    assert record["members"][0]["name"] == "Luigi"
    assert any(d["name"] == "Picco del Capitale" for d in record["districts_log"])


FRIDAY = datetime(2026, 9, 11, 7, 5, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
MONDAY = datetime(2026, 9, 14, 7, 5, tzinfo=timezone.utc)
STORED = {"lang": "it", "tz": TZ, "quiet": None, "reminders": [3600]}
MEMBERS = member_snapshot(clan_json(BASE_MEMBERS))
CAPITAL_JSON = {"clanCapital": {"capitalHallLevel": 8, "districts": [
    {"name": "Picco del Capitale", "districtHallLevel": 8},
    {"name": "Radura Barbara", "districtHallLevel": 5},
]}}


def link(tag, user_id, name, lang=None):
    return SimpleNamespace(alias=CLAN.alias, tag=tag, user_id=user_id, name=name, dm=True, lang=lang)


LINKS = [link("#P1", 71, "Mario"), link("#P2", 72, "Luigi"),
         link("#P3", 73, "Peach", lang="en"), link("#P4", 74, "Toad")]


class Store(FakeStore):
    def __init__(self, state=None):
        super().__init__(state=state, links=LINKS)
        self.stats = []

    async def links_for_players(self, tags):
        wanted = set(tags)
        return {row.tag: row for row in self.links if row.tag in wanted}

    async def add_stat(self, alias, kind, stat_key, ended_at, obj):
        self.stats.append((alias, kind, stat_key, ended_at, copy.deepcopy(obj)))
        return True

    async def recent_stats(self, alias, kind, limit=10):
        rows = [row for row in self.stats if row[0] == alias and row[1] == kind]
        rows.sort(key=lambda row: str(row[3]), reverse=True)
        return [copy.deepcopy(row[4]) for row in rows[:limit]]


class Coc:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    async def capital_raids(self, tag):
        self.calls += 1
        return {"items": copy.deepcopy(self.items)}, None


def tick(now, stored=STORED):
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(stored, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.members = copy.deepcopy(MEMBERS)
    t.season = scoring.empty_season("2026-09")
    return t


def counters_at(state, when, rows):
    for tag, name, values in rows:
        state = progress.update(state, tag, name, values, when, TZ)
    return state


def opened_weekend():
    state = counters_at({}, datetime(2026, 9, 11, 6, 50, tzinfo=timezone.utc), [
        ("#P1", "Mario", {"capital_gold": 1_000_000, "raid_loot": 500_000}),
        ("#P2", "Luigi", {"capital_gold": 2_000_000, "raid_loot": 100_000}),
    ])
    store = Store(state={(CLAN.alias, "progress"): state})
    coc = Coc([raid("ongoing")])
    poller = Poller(fake_supervisor(), store, coc)
    t = tick(FRIDAY)
    asyncio.run(poller.track_capital(t, CAPITAL_JSON))
    return poller, store, coc, t


def closed_weekend(stored=STORED):
    poller, store, coc, t = opened_weekend()
    state = counters_at(copy.deepcopy(store.state[(CLAN.alias, "progress")]), SATURDAY, [
        ("#P1", "Mario", {"capital_gold": 1_090_000, "raid_loot": 560_000}),
        ("#P2", "Luigi", {"capital_gold": 2_000_000, "raid_loot": 100_000}),
    ])
    state = counters_at(state, datetime(2026, 9, 14, 6, tzinfo=timezone.utc), [
        ("#P1", "Mario", {"capital_gold": 1_090_000, "raid_loot": 560_000}),
        ("#P2", "Luigi", {"capital_gold": 2_000_000, "raid_loot": 100_000}),
    ])
    store.state[(CLAN.alias, "progress")] = state
    coc.items = [raid("ended")]
    t = tick(MONDAY, stored)
    asyncio.run(poller.track_capital(t, CAPITAL_JSON))
    return poller, store, coc, t


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_la_chiusura_del_weekend_racconta_efficienza_distretti_e_oro():
    poller, store, coc, t = closed_weekend()
    testi = boards.lines_of(t.boards, "capital_games")
    fine = [text for text in testi if "Picco del Capitale" in text]
    assert len(fine) == 1 and "Luigi" in fine[0]
    oro = [text for text in testi if L.n(90000) in text]
    assert len(oro) == 1 and "Mario" in oro[0] and "Luigi" not in oro[0]


def test_la_classifica_dell_oro_ignora_la_settimana_solare_gia_ripartita():
    poller, store, coc, t = closed_weekend()
    state = store.state[(CLAN.alias, "progress")]
    assert {r["tag"]: r["capital_gold"] for r in progress.deltas(state, "week")}["#P1"] == 0
    cap = store.state[(CLAN.alias, "capital")]
    assert capital.gold_rows(capital.gold_since(state, cap)) == [
        {"tag": "#P1", "name": "Mario", "gold": 90000, "loot": 60000}]


def test_a_chi_e_rimasto_un_attacco_arriva_una_riga_nel_feed_nella_sua_lingua():
    poller, store, coc, t = closed_weekend()
    assert [uid for uid in (71, 72, 73, 74) if feed_rows(store, uid)] == [72, 73, 74]
    assert EN.t("capital.skipped.title") in feed_rows(store, 73)[0]
    assert L.t("capital.skipped.title") in feed_rows(store, 72)[0]
    assert all("Toad" not in text and "Peach" not in text
               for uid in (72, 73, 74) for text in feed_rows(store, uid))


def test_con_la_rotta_ai_capi_le_righe_saltate_vanno_ai_capi_e_non_ai_membri():
    stored = settings_mod.migrate(STORED)
    stored["routes"]["capital.skipped"] = {"to": "leaders_dm", "intensity": None}
    poller, store, coc, t = closed_weekend(stored)
    conteggio = {uid: len(feed_rows(store, uid)) for uid in (71, 72, 73, 74) if feed_rows(store, uid)}
    assert conteggio == {71: 3, 72: 3}
    assert not [text for uid in (71, 72) for text in feed_rows(store, uid)
                if L.t("capital.gold.title") in text]


def test_il_weekend_chiuso_finisce_nello_storico_una_volta_sola():
    poller, store, coc, t = closed_weekend()
    assert [(kind, key) for _, kind, key, _, _ in store.stats] == [("capital", "20260911T070000.000Z")]
    assert store.stats[0][4]["members"][0]["name"] == "Luigi"
    later = tick(MONDAY + timedelta(minutes=20))
    asyncio.run(poller.track_capital(later, CAPITAL_JSON))
    assert later.chunks == [] and later.boards is None and len(store.stats) == 1
    assert coc.calls == 3


def test_il_livello_della_capitale_si_annuncia_una_volta_sola():
    poller, store, coc, t = opened_weekend()
    assert not [text for text in boards.lines_of(t.boards, "capital_games")
                if L.t("capital.level.hall.body", level=L.n(9)) in text]
    salito = {"clanCapital": {"capitalHallLevel": 9, "districts": [
        {"name": "Picco del Capitale", "districtHallLevel": 9},
        {"name": "Radura Barbara", "districtHallLevel": 5},
    ]}}
    secondo = tick(FRIDAY + timedelta(minutes=20))
    asyncio.run(poller.track_capital(secondo, salito))
    saliti = [text for text in boards.lines_of(secondo.boards, "capital_games")
              if L.t("capital.level.hall.body", level=L.n(9)) in text]
    assert len(saliti) == 1 and L.n(9) in saliti[0]
    terzo = tick(FRIDAY + timedelta(minutes=40))
    asyncio.run(poller.track_capital(terzo, salito))
    assert not [text for text in boards.lines_of(terzo.boards, "capital_games")
                if L.t("capital.level.hall.body", level=L.n(9)) in text]


def test_un_weekend_nuovo_riparte_dalla_base_del_momento():
    poller, store, coc, t = closed_weekend()
    nuovo = raid("ongoing")
    nuovo["startTime"] = "20260918T070000.000Z"
    nuovo["endTime"] = "20260921T070000.000Z"
    coc.items = [nuovo]
    venerdi = datetime(2026, 9, 18, 7, 5, tzinfo=timezone.utc)
    dopo = tick(venerdi)
    asyncio.run(poller.track_capital(dopo, CAPITAL_JSON))
    cap = store.state[(CLAN.alias, "capital")]
    assert cap["season"] == "20260918T070000.000Z"
    assert cap["gold_base"]["#P1"]["capital_gold"] == 1_090_000
    assert capital.gold_rows(capital.gold_since(store.state[(CLAN.alias, "progress")], cap)) == []
    assert cap["hall"]["level"] == 8


def test_i_tre_eventi_nuovi_vivono_nel_pacchetto_della_capitale():
    for name in ("capital.gold", "capital.skipped", "capital.level"):
        assert EVENTS[name]["pack"] == "capital_games"
    conf = settings_mod.effective(STORED, None)
    assert settings_mod.route(conf, "capital.gold") == ("group", None)
    assert settings_mod.route(conf, "capital.skipped") == ("member_dm", None)
    assert settings_mod.route(conf, "capital.level") == ("group", None)
    assert "group" not in EVENTS["capital.skipped"]["allowed"]
    assert "member_dm" not in EVENTS["capital.level"]["allowed"]


def context_for(store, coc):
    return SimpleNamespace(bot_data={"store": store, "coc": coc, "bot_alias": ALIAS})


def view(key, store=None, coc=None):
    store = store or Store(state={(CLAN.alias, "settings"): copy.deepcopy(STORED)})
    coc = coc if coc is not None else Coc([raid()])
    return asyncio.run(handlers.build_view(key, CLAN, context_for(store, coc)))


def datas_of(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_capitale_apre_sulle_sue_schede_senza_cambiare_la_prima():
    text, keyboard = view("capital")
    assert L.t("capital.view.last") in text and L.n(123456) in text
    datas = datas_of(keyboard)
    for data in ("v:capital", "v:capital:eff", "v:capital:districts", "v:capital:gold", "v:capital:hall"):
        assert data in datas
    assert all(len(data.encode()) <= 64 for data in datas)


def test_le_schede_della_capitale_mostrano_quello_che_calcolano():
    assert L.t("capital.eff.title") in view("capital:eff")[0]
    assert "Picco del Capitale" in view("capital:districts")[0]
    store = Store(state={
        (CLAN.alias, "settings"): copy.deepcopy(STORED),
        (CLAN.alias, "capital"): {"hall": capital.hall_snapshot(CAPITAL_JSON),
                                  "gold_base": {"#P1": {"capital_gold": 1_000_000, "raid_loot": 0}}},
        (CLAN.alias, "progress"): progress_state(1_090_000, 0),
    })
    text, keyboard = view("capital:gold", store=store)
    assert L.n(90000) in text and "Mario" in text
    assert "v:capital:gold" in datas_of(keyboard)
    assert L.t("capital.hall.title") in view("capital:hall", store=store)[0]
    assert "Radura Barbara" in view("capital:hall", store=store)[0]


def test_la_scheda_dell_oro_non_chiama_l_api_delle_incursioni():
    coc = Coc([raid()])
    view("capital:gold", coc=coc)
    view("capital:hall", coc=coc)
    assert coc.calls == 0
