import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import coaching, i18n, leader_cards, leader_jobs, scoring
from clashbot import settings as settings_mod

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
ROME = {"lang": "it", "tz": "Europe/Rome"}
MEMBERS = {
    "#P1": {"name": "Mario", "role": "leader"},
    "#P2": {"name": "Luigi", "role": "member"},
    "#P3": {"name": "Peach", "role": "member"},
    "#P4": {"name": "Toad", "role": "member"},
}
STATS = {
    "#P2": {"name": "Luigi", "wars": 8, "attacks": 16, "stars": 40, "triples": 6, "missed": 0},
    "#P3": {"name": "Peach", "wars": 8, "attacks": 12, "stars": 20, "triples": 1, "missed": 4},
    "#P4": {"name": "Toad", "wars": 1, "attacks": 0, "stars": 0, "triples": 0, "missed": 2},
}
SEASON = {"members": {
    "#P2": {"name": "Luigi", "wars": 8, "attacks": 16, "stars": 40, "triples": 6, "missed": 0,
            "raid_attacks": 6, "loot": 400000, "donations": 1200},
    "#P3": {"name": "Peach", "wars": 8, "attacks": 12, "stars": 20, "triples": 1, "missed": 4,
            "raid_attacks": 0, "loot": 0, "donations": 100},
}}
ACTIVITY = [{"tag": "#P2", "name": "Luigi", "score": 42}, {"tag": "#P3", "name": "Peach", "score": 3}]


def old(days):
    return (NOW - timedelta(days=days)).timestamp()


def test_track_segna_gli_arrivi_e_dimentica_chi_esce():
    players = {"tags": {}, "joined": {"#P9": {"ts": old(30), "told": True}}}
    out = coaching.track(players, MEMBERS, [{"type": "join", "tag": "#P4", "name": "Toad"}], NOW)
    assert out["joined"]["#P4"] == {"ts": NOW.timestamp(), "told": False}
    assert "#P9" not in out["joined"]
    assert out["tags"] == {}


def test_chi_c_era_gia_non_ha_una_prova():
    assert coaching.trial_due({"joined": {}}, MEMBERS, NOW) == []


def test_la_prova_scatta_dopo_due_settimane_e_una_volta_sola():
    players = {"joined": {"#P4": {"ts": old(coaching.TRIAL_DAYS + 1), "told": False},
                          "#P3": {"ts": old(3), "told": False}}}
    due = coaching.trial_due(players, MEMBERS, NOW)
    assert [row["tag"] for row in due] == ["#P4"]
    told = coaching.mark_told(players, ["#P4"])
    assert coaching.trial_due(told, MEMBERS, NOW) == []


def test_le_promozioni_prendono_solo_chi_e_affidabile_e_al_massimo_tre():
    players = {"joined": {"#P2": {"ts": old(60), "told": True}, "#P4": {"ts": old(2), "told": False}}}
    rows = coaching.promotions(MEMBERS, STATS, SEASON, ACTIVITY, players, NOW)
    assert [row["name"] for row in rows] == ["Luigi"]
    row = rows[0]
    assert row["missed"] == 0 and row["attacks"] == 16 and row["points"] > 0 and row["rank"] == 1


def test_niente_promozioni_per_chi_comanda_gia():
    only_leaders = {"#P1": {"name": "Mario", "role": "leader"}, "#P2": {"name": "Luigi", "role": "coLeader"}}
    assert coaching.promotions(only_leaders, STATS, SEASON, ACTIVITY, {"joined": {}}, NOW) == []


def test_le_promozioni_si_fermano_ai_primi_tre():
    members = {tag: {"name": f"Membro{tag[-1]}", "role": "member"} for tag in
               ("#A1", "#A2", "#A3", "#A4")}
    stats = {tag: {"name": members[tag]["name"], "wars": 4, "attacks": 8, "stars": 20,
                   "triples": 2, "missed": 0} for tag in members}
    season = {"members": {tag: {"name": members[tag]["name"], "wars": 4, "attacks": 8,
                                "stars": 20 + i, "triples": 2, "missed": 0, "raid_attacks": 0,
                                "loot": 0, "donations": 0}
                          for i, tag in enumerate(members)}}
    rows = coaching.promotions(members, stats, season, [], {"joined": {}}, NOW)
    assert len(rows) == coaching.TOP
    assert [row["rank"] for row in rows] == [1, 2, 3]


def test_a_pari_punti_la_posizione_e_quella_della_classifica():
    members = {"#P2": {"name": "Luigi", "role": "member"}, "#P3": {"name": "Peach", "role": "member"}}
    stats = {"#P2": {"name": "Luigi", "wars": 2, "attacks": 2, "stars": 1, "triples": 0, "missed": 0},
             "#P3": {"name": "Peach", "wars": 2, "attacks": 3, "stars": 5, "triples": 0, "missed": 0}}
    season = {"members": {
        "#P2": {"name": "Luigi", "wars": 2, "attacks": 2, "stars": 1, "triples": 0, "missed": 0,
                "raid_attacks": 0, "loot": 0, "donations": 0},
        "#P3": {"name": "Peach", "wars": 2, "attacks": 0, "stars": 5, "triples": 0, "missed": 0,
                "raid_attacks": 0, "loot": 0, "donations": 0},
    }}
    board = {tag: place + 1 for place, (tag, _, _) in enumerate(scoring.leaderboard(season))}
    assert board == {"#P3": 1, "#P2": 2}
    rows = coaching.promotions(members, stats, season, [], {"joined": {}}, NOW)
    assert {row["tag"]: row["rank"] for row in rows} == board
    assert [row["rank"] for row in rows] == [1, 2]


def test_le_schede_dicono_i_numeri_che_le_hanno_prodotte():
    players = {"joined": {"#P2": {"ts": old(60), "told": True}}}
    rows = coaching.promotions(MEMBERS, STATS, SEASON, ACTIVITY, players, NOW)
    text = leader_cards.promotion_card(IT, rows)
    assert "Luigi" in text and "16" in text and IT.t("leaders.promo.tail") in text
    assert IT.t("leaders.promo.row", name="Luigi", rank=1) in text
    assert IT.t("leaders.promo.why", wars=8, attacks=16, stars=40, missed=0,
                donations=IT.n(1200), points=148) in text
    record = coaching.record_of("#P3", STATS, SEASON, ACTIVITY)
    trial = leader_cards.trial_card(IT, [{"name": "Peach", **record}])
    assert IT.t("leaders.trial.row", name="Peach", wars=8, attacks=12, stars=20, missed=4,
                donations=IT.n(100), score=3) in trial
    assert IT.t("leaders.trial.tail") in trial


def test_le_schede_vuote_non_esistono():
    assert leader_cards.promotion_card(IT, []) is None
    assert leader_cards.trial_card(IT, []) is None


class Store:
    def __init__(self, state=None, wars=()):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.wars = [copy.deepcopy(war) for war in wars]
        self.writes = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get(kind))

    async def set_state(self, alias, kind, obj):
        self.writes.append(kind)
        self.state[kind] = copy.deepcopy(obj)

    async def recent_wars(self, alias, limit=10):
        return copy.deepcopy(self.wars[:limit])


class Poller:
    def __init__(self, store, activity=()):
        self.store = store
        self.activity = list(activity)
        self.dispatched = []

    async def month_activity(self, t):
        return copy.deepcopy(self.activity)

    async def dispatch(self, t, event, render_text):
        self.dispatched.append((event, render_text(t.L)))


def tick(now=NOW, events=(), members=None):
    t = SimpleNamespace(clan=CLAN, now=now, chunks=[], dm=[], events=list(events),
                        settings=settings_mod.effective(ROME, None),
                        members=copy.deepcopy(MEMBERS if members is None else members))
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    return t


def war_record(tag, name, stars, missed=0):
    return {"members": [{"tag": tag, "name": name,
                         "attacks": [{"stars": stars, "destr": 100.0}], "missed": missed}],
            "attacksPerMember": 2}


def test_il_giro_dei_capi_racconta_la_prova_una_volta_sola():
    store = Store({"players": {"tags": {}, "joined": {"#P4": {"ts": old(coaching.TRIAL_DAYS), "told": False}}}})
    poller = Poller(store)
    asyncio.run(leader_jobs.run(poller, tick()))
    assert [event for event, _ in poller.dispatched] == ["leaders.trial"]
    assert "Toad" in poller.dispatched[0][1]
    assert store.state["players"]["joined"]["#P4"]["told"] is True
    assert store.state["players"]["tags"] == {}
    poller.dispatched.clear()
    asyncio.run(leader_jobs.run(poller, tick()))
    assert poller.dispatched == []


def test_chi_arriva_adesso_aspetta_il_suo_turno():
    store = Store()
    poller = Poller(store)
    asyncio.run(leader_jobs.newcomers(poller, tick(events=[{"type": "join", "tag": "#P4", "name": "Toad"}])))
    assert poller.dispatched == []
    assert store.state["players"]["joined"]["#P4"] == {"ts": NOW.timestamp(), "told": False}


def test_senza_novita_le_date_di_ingresso_non_si_riscrivono():
    store = Store()
    poller = Poller(store)
    asyncio.run(leader_jobs.newcomers(poller, tick(events=[{"type": "join", "tag": "#P4", "name": "Toad"}])))
    assert store.writes == ["players"]
    asyncio.run(leader_jobs.newcomers(poller, tick()))
    assert store.writes == ["players"]


def test_le_promozioni_arrivano_il_lunedi_e_non_si_ripetono():
    store = Store({"season": SEASON, "players": {"joined": {"#P2": {"ts": old(60), "told": True}}}},
                  wars=[war_record("#P2", "Luigi", 3), war_record("#P3", "Peach", 1, missed=2)])
    poller = Poller(store)
    asyncio.run(leader_jobs.promotions(poller, tick()))
    assert [event for event, _ in poller.dispatched] == ["leaders.promotion"]
    text = poller.dispatched[0][1]
    assert "Luigi" in text and "Peach" not in text
    poller.dispatched.clear()
    asyncio.run(leader_jobs.promotions(poller, tick()))
    assert poller.dispatched == []


def test_fuori_dal_lunedi_le_promozioni_tacciono():
    store = Store({"season": SEASON, "players": {"joined": {"#P2": {"ts": old(60), "told": True}}}},
                  wars=[war_record("#P2", "Luigi", 3)])
    poller = Poller(store)
    asyncio.run(leader_jobs.promotions(poller, tick(now=NOW + timedelta(days=1))))
    assert poller.dispatched == [] and "reports" not in store.state


def test_senza_stagione_l_archivio_delle_guerre_resta_chiuso():
    store = Store({"players": {"joined": {"#P2": {"ts": old(60), "told": True}}}})
    poller = Poller(store)
    asyncio.run(leader_jobs.promotions(poller, tick()))
    assert poller.dispatched == []


def test_le_chiavi_nuove_esistono():
    for key in ("leaders.promo.title", "leaders.promo.row", "leaders.promo.why", "leaders.promo.tail",
                "leaders.trial.title", "leaders.trial.row", "leaders.trial.tail"):
        assert key in EN, key


def test_le_chiavi_nuove_sono_scritte_in_italiano_e_in_inglese():
    italian = json.load(open(i18n.LOCALE_DIR / "it.json", encoding="utf-8"))
    for key in ("leaders.promo.title", "leaders.promo.why", "leaders.promo.tail",
                "leaders.trial.title", "leaders.trial.row", "leaders.trial.tail"):
        assert italian[key] and EN[key] and italian[key] != EN[key], key
