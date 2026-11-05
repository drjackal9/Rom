import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import (events, family as family_mod, i18n, leaderboards,
                      progress as progress_mod, scoring, tourney_results, tourney_ui, tournaments,
                      views)
from clashbot.poller import Poller
from clashbot.util import now_utc
from fixtures import war_json

NOW = datetime(2026, 9, 21, 9, tzinfo=timezone.utc)
TS = int(NOW.timestamp())
A = SimpleNamespace(alias="clan-a", chat_id=1, tag="#A", name="Alfa", bot_alias="bot-1", active=True)
B = SimpleNamespace(alias="clan-b", chat_id=2, tag="#B", name="Beta", bot_alias="bot-1", active=True)


class FakeStore:
    def __init__(self, wars=None, state=None):
        self.wars = wars or {}
        self.state = state or {}

    async def clan_by_alias(self, alias):
        return {"clan-a": A, "clan-b": B}.get(alias)

    async def family_clans(self, alias):
        return [A, B]

    async def wars_since(self, alias, since):
        return [copy.deepcopy(r) for r in self.wars.get(alias, [])]

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)


class FakeSupervisor:
    default_alias = "bot-1"

    def bot(self, alias):
        return None

    def running(self):
        return ["bot-1"]


def bracket(metric="stars"):
    doc = tournaments.empty("clash", "family", metric, "bracket", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-dddddd"
    for clan in (A, B):
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    return tournaments.make_bracket(doc)


def war_record_between(opp_tag, ended, stars, opp_stars, destr=90.0, opp_destr=40.0):
    record = events.war_record(events.war_snapshot(war_json("warEnded", end=ended, opp_tag=opp_tag)))
    record["stars"], record["opp_stars"] = stars, opp_stars
    record["destr"], record["opp_destr"] = destr, opp_destr
    return record


INSIDE = "20260921T083000.000Z"
OUTSIDE = "20260901T083000.000Z"


def both_sides(ended, stars_a, stars_b):
    return {"clan-a": [war_record_between("#B", ended, stars_a, stars_b, 90.0, 40.0)],
            "clan-b": [war_record_between("#A", ended, stars_b, stars_a, 40.0, 90.0)]}


def acceso_su(*aliases):
    return {(alias, views.KIND): {views.FAMILY: True} for alias in aliases}


def test_la_guerra_vera_decide_la_sfida():
    doc = bracket()
    store = FakeStore(wars=both_sides(INSIDE, 9, 5), state=acceso_su("clan-a", "clan-b"))
    doc, evs = asyncio.run(tourney_results.refresh(store, doc, NOW))
    match = doc["rounds"][0][0]
    assert match["done"] and sorted(match["score"]) == [5, 9]
    assert match["winner"] == tournaments.entry_id("clan", "clan-a")
    assert [e["type"] for e in evs] == ["result"]


def test_la_guerra_fuori_finestra_non_conta():
    doc = bracket()
    store = FakeStore(wars=both_sides(OUTSIDE, 9, 5))
    doc, evs = asyncio.run(tourney_results.refresh(store, doc, NOW - timedelta(hours=2)))
    assert doc["rounds"][0][0]["done"] is False and evs == []


def test_senza_guerra_alla_scadenza_decide_la_metrica():
    doc = bracket()
    store = FakeStore(wars={"clan-a": [war_record_between("#Z", INSIDE, 3, 1)],
                            "clan-b": [war_record_between("#Y", INSIDE, 12, 1)]})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW + timedelta(hours=2)))
    match = doc["rounds"][0][0]
    assert match["done"] and match["winner"] == tournaments.entry_id("clan", "clan-b")


def test_gli_esclusi_dalle_classifiche_non_entrano_nei_punteggi():
    doc = bracket()
    doc = tournaments.eligible(doc, ["clan-b"])
    assert [entry["ref"] for entry in doc["entries"]] == ["clan-a"]
    store = FakeStore(wars=both_sides(INSIDE, 9, 5))
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW))
    assert set(doc["scores"]) == {tournaments.entry_id("clan", "clan-a")}


def test_l_esclusione_arriva_dalle_classifiche():
    store = FakeStore(state={("clan-a", leaderboards.STATE_KIND): {"excluded": ["#P1"]}})
    poller = Poller(FakeSupervisor(), store, None)
    assert asyncio.run(poller.tournament_excluded({"clan_alias": "clan-a"})) == ["#P1"]
    assert asyncio.run(poller.tournament_excluded({"clan_alias": "clan-z"})) == []
    assert asyncio.run(poller.tournament_excluded({"clan_alias": None})) == []


def test_i_membri_si_confrontano_con_i_contatori():
    doc = tournaments.empty("internal", "clan", "loot", "bracket", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-eeeeee"
    doc["clan_alias"] = "clan-a"
    for tag, name in (("#P1", "Mario"), ("#P2", "Luigi")):
        doc, _ = tournaments.join(doc, "member", tag, name)
    doc = tournaments.make_bracket(doc)
    progress = {
        "#P1": {"name": "Mario", "now": {"gold": 3_000_000, "elixir": 0}, "week": {"since": TS - 86400, "gold": 1_000_000, "elixir": 0}},
        "#P2": {"name": "Luigi", "now": {"gold": 9_000_000, "elixir": 0}, "week": {"since": TS - 86400, "gold": 1_000_000, "elixir": 0}},
    }
    store = FakeStore(state={("clan-a", "progress"): progress})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW + timedelta(hours=2)))
    assert doc["scores"][tournaments.entry_id("member", "#P2")] == 8_000_000
    assert doc["rounds"][0][0]["winner"] == tournaments.entry_id("member", "#P2")


def test_l_attivita_dei_membri_sta_in_decimi_come_quella_dei_clan():
    progress = {"#P1": {"name": "Mario", "now": {"wins": 40}, "week": {"since": TS - 86400, "wins": 0}}}
    store = FakeStore(state={("clan-a", "progress"): progress, ("clan-a", "info"): {"members": 2}})
    clan_points, _ = asyncio.run(tourney_results.clan_value(store, A, "activity", NOW))
    member_points = asyncio.run(tourney_results.member_value(store, "clan-a", "#P1", "activity"))
    assert clan_points == 200 and member_points == 400


def torneo_attivita(scope):
    doc = tournaments.empty("clash", scope, "activity", "table", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-777777"
    doc, _ = tournaments.join(doc, "clan", A.alias, A.name)
    return tournaments.make_groups(doc, 1)


def punteggio_attivita(store, scope):
    doc, _ = asyncio.run(tourney_results.refresh(store, torneo_attivita(scope),
                                                 NOW + timedelta(hours=2)))
    return doc["scores"][tournaments.entry_id("clan", "clan-a")]


def store_attivita(acceso=False):
    progress = {"#P1": {"name": "Mario", "now": {"wins": 40}, "week": {"since": TS - 86400, "wins": 0}}}
    state = {("clan-a", "progress"): progress, ("clan-a", "info"): {"members": 2}}
    if acceso:
        state[("clan-a", views.KIND)] = {views.FAMILY: True}
    return FakeStore(state=state)


def test_il_torneo_di_famiglia_non_conta_l_attivita_di_chi_non_l_ha_accesa():
    assert punteggio_attivita(store_attivita(), "family") == 0
    assert punteggio_attivita(store_attivita(acceso=True), "family") == 200


def test_il_torneo_di_rete_conta_l_attivita_del_clan_che_ci_si_e_iscritto():
    assert punteggio_attivita(store_attivita(), "network") == 200
    assert punteggio_attivita(store_attivita(), "clan") == 200


def test_il_valore_in_decimi_si_legge_anche_con_stelle_e_attivita():
    L = i18n.locale("it")
    assert tourney_ui.value_label(L, {"metric": "both"}, 200) == tourney_ui.value_label(
        L, {"metric": "activity"}, 200)
    assert "200" not in tourney_ui.value_label(L, {"metric": "both"}, 200)


def test_activity_ha_una_formula_sola():
    progress = {"#P1": {"name": "Mario", "now": {"wins": 40}, "week": {"since": TS - 86400, "wins": 0}}}
    store = FakeStore(state={("clan-a", "progress"): progress, ("clan-a", "info"): {"members": 2},
                             ("clan-a", views.KIND): {views.FAMILY: True}})
    value = asyncio.run(family_mod.clan_activity(store, A))
    rows = asyncio.run(family_mod.activity_rows(store, SimpleNamespace(alias="fam-1")))
    assert value == 20.0
    assert [row["avg"] for row in rows if row["name"] == "Alfa"] == [value]


def test_il_vincitore_entra_nell_albo_senza_perdere_i_record():
    doc = bracket()
    store = FakeStore(wars=both_sides(INSIDE, 9, 5),
                      state={**acceso_su("clan-a", "clan-b"),
                             ("clan-a", "hall"): {"seasons": [], "records": {"wars": 7, "wins": 4}}})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW))
    poller = Poller(FakeSupervisor(), store, None)
    asyncio.run(poller.crown(doc, [A]))
    hall = store.state[("clan-a", "hall")]
    assert hall["records"]["wars"] == 7 and hall["records"]["wins"] == 4
    assert hall["seasons"][-1] == {"season": scoring.season_id(now_utc(), "UTC"),
                                  "titles": {"Torneo": ["Alfa", 2]}}


FOUR = {name: SimpleNamespace(alias=f"clan-{name.lower()}", chat_id=ord(name), tag=f"#{name}",
                              name=name, bot_alias="bot-1", active=True) for name in "ABCD"}
LONG_STARTS = TS - 12 * 3600
LONG_ENDS = TS + 12 * 3600
SEMI = "20260921T030000.000Z"


class FourStore(FakeStore):
    async def clan_by_alias(self, alias):
        return {clan.alias: clan for clan in FOUR.values()}.get(alias)


def four_bracket(metric, kind="clash", scope="family"):
    doc = tournaments.empty(kind, scope, metric, "bracket", LONG_STARTS - 86400, LONG_STARTS, LONG_ENDS)
    doc["alias"] = "trn-444444"
    for clan in FOUR.values():
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    return tournaments.make_bracket(doc)


def semifinal_wars(doc):
    known = {entry["id"]: entry for entry in doc["entries"]}
    tags = {entry["id"]: entry["ref"] for entry in doc["entries"]}
    wars, stars = {}, 9
    for match in doc["rounds"][0]:
        left, right = known[match["a"]], known[match["b"]]
        wars.setdefault(tags[left["id"]], []).append(
            war_record_between(f"#{right['name']}", SEMI, stars, stars - 4, 90.0, 30.0))
        wars.setdefault(tags[right["id"]], []).append(
            war_record_between(f"#{left['name']}", SEMI, stars - 4, stars, 30.0, 90.0))
        stars -= 1
    return wars


def test_la_finale_non_eredita_le_stelle_della_semifinale():
    doc = four_bracket("stars")
    store = FourStore(wars=semifinal_wars(doc))
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW))
    assert [match["done"] for match in doc["rounds"][0]] == [True, True]
    assert len(doc["rounds"]) == 2
    finalists = [doc["rounds"][1][0]["a"], doc["rounds"][1][0]["b"]]
    end = datetime.fromtimestamp(LONG_ENDS, timezone.utc)
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, end + timedelta(hours=1)))
    assert doc["rounds"][1][0]["done"] and doc["rounds"][1][0]["score"] == [0, 0]
    assert [doc["scores"][eid] for eid in finalists] == [0, 0]


TAGS = ("#P1", "#P2", "#P3", "#P4")


def four_members(metric):
    doc = tournaments.empty("internal", "clan", metric, "bracket", LONG_STARTS - 86400, LONG_STARTS, LONG_ENDS)
    doc["alias"] = "trn-777777"
    doc["clan_alias"] = "clan-a"
    for tag in TAGS:
        doc, _ = tournaments.join(doc, "member", tag, tag)
    return tournaments.make_bracket(doc)


def member_progress(golds):
    return {tag: {"name": tag, "now": {"gold": gold, "elixir": 0},
                  "week": {"since": LONG_STARTS - 86400, "gold": 0, "elixir": 0}}
            for tag, gold in zip(TAGS, golds)}


def test_il_turno_nuovo_non_eredita_i_contatori_del_turno_precedente():
    doc = four_members("loot")
    store = FakeStore(state={("clan-a", "progress"):
                             member_progress((4_000_000, 3_000_000, 2_000_000, 1_000_000))})
    end = datetime.fromtimestamp(LONG_ENDS, timezone.utc)
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, end + timedelta(hours=1)))
    assert [match["done"] for match in doc["rounds"][0]] == [True, True]
    assert max(doc["scores"].values()) == 4_000_000
    finalists = [doc["rounds"][1][0]["a"], doc["rounds"][1][0]["b"]]
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, end + timedelta(hours=2)))
    assert doc["rounds"][1][0]["done"] and doc["rounds"][1][0]["score"] == [0, 0]
    assert [doc["scores"][eid] for eid in finalists] == [0, 0]


def member_war_stars(values):
    return {tag: {"name": tag, "now": {"war_stars": value},
                  "week": {"since": LONG_STARTS - 86400, "war_stars": 0}}
            for tag, value in zip(TAGS, values)}


def test_il_turno_nuovo_non_eredita_le_stelle_dei_membri():
    doc = four_members("stars")
    store = FakeStore(state={("clan-a", "progress"): member_war_stars((40, 30, 20, 10))})
    end = datetime.fromtimestamp(LONG_ENDS, timezone.utc)
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, end + timedelta(hours=1)))
    assert [match["done"] for match in doc["rounds"][0]] == [True, True]
    assert max(doc["scores"].values()) == 40
    finalists = [doc["rounds"][1][0]["a"], doc["rounds"][1][0]["b"]]
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, end + timedelta(hours=2)))
    assert doc["rounds"][1][0]["done"] and doc["rounds"][1][0]["score"] == [0, 0]
    assert [doc["scores"][eid] for eid in finalists] == [0, 0]


INSIDE_ROUND = NOW - timedelta(hours=6)


def test_le_stelle_dei_membri_crescono_dentro_la_finestra():
    doc = four_members("stars")
    store = FakeStore(state={("clan-a", "progress"): member_war_stars((5, 5, 5, 5))})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, INSIDE_ROUND))
    assert set(doc["scores"].values()) == {0}
    store.state[("clan-a", "progress")] = member_war_stars((11, 5, 5, 5))
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, INSIDE_ROUND + timedelta(hours=1)))
    assert doc["scores"][tournaments.entry_id("member", "#P1")] == 6
    assert set(doc["scores"].values()) == {0, 6}


def test_la_metrica_del_turno_cresce_dentro_la_finestra():
    doc = four_members("loot")
    store = FakeStore(state={("clan-a", "progress"): member_progress([1_000_000] * 4)})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, INSIDE_ROUND))
    assert set(doc["scores"].values()) == {0}
    store.state[("clan-a", "progress")] = member_progress((3_000_000, 1_000_000, 1_000_000, 1_000_000))
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, INSIDE_ROUND + timedelta(hours=1)))
    assert doc["scores"][tournaments.entry_id("member", "#P1")] == 2_000_000
    assert set(doc["scores"].values()) == {0, 2_000_000}


def test_il_turno_scaduto_lascia_al_prossimo_una_finestra_ancora_viva():
    doc = four_members("loot")
    assert doc["rounds_total"] == 2
    store = FakeStore(state={("clan-a", "progress"):
                             member_progress((4_000_000, 3_000_000, 2_000_000, 1_000_000))})
    first = tournaments.round_window(doc, 0)
    assert first[1] < LONG_ENDS
    closing = datetime.fromtimestamp(first[1] + 60, timezone.utc)
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, closing))
    assert [match["done"] for match in doc["rounds"][0]] == [True, True]
    second = tournaments.round_window(doc, 1)
    assert second == (first[1], LONG_ENDS) and second[1] > closing.timestamp()
    finalists = [doc["rounds"][1][0]["a"], doc["rounds"][1][0]["b"]]
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, closing + timedelta(minutes=1)))
    assert [doc["scores"][eid] for eid in finalists] == [0, 0]
    store.state[("clan-a", "progress")][finalists[1].split(":", 1)[1]]["now"]["gold"] += 5_000_000
    doc, _ = asyncio.run(tourney_results.refresh(
        store, doc, datetime.fromtimestamp(second[1] + 60, timezone.utc)))
    assert doc["rounds"][1][0]["score"] == [0, 5_000_000]
    assert doc["rounds"][1][0]["winner"] == finalists[1]


WED = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
SUN = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
TUE = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)


def gold_over_monday(first, second, third):
    stored = {}
    for tag in ("#P1", "#P2"):
        stored = progress_mod.update(stored, tag, tag, {"gold": first}, WED, "UTC")
    stored = progress_mod.update(stored, "#P1", "#P1", {"gold": second}, SUN, "UTC")
    stored = progress_mod.update(stored, "#P2", "#P2", {"gold": first}, SUN, "UTC")
    sunday = copy.deepcopy(stored)
    stored = progress_mod.update(stored, "#P1", "#P1", {"gold": third}, TUE, "UTC")
    return sunday, progress_mod.update(stored, "#P2", "#P2", {"gold": first}, TUE, "UTC")


def two_members(metric, starts, ends):
    doc = tournaments.empty("internal", "clan", metric, "bracket",
                            starts - 86400, starts, ends, size=4)
    doc["alias"] = "trn-888888"
    doc["clan_alias"] = "clan-a"
    for tag in ("#P1", "#P2"):
        doc, _ = tournaments.join(doc, "member", tag, tag)
    return tournaments.make_bracket(doc)


def test_il_turno_che_attraversa_il_lunedi_non_azzera_i_contatori():
    starts, ends = int(WED.timestamp()), int(TUE.timestamp()) + 86400
    doc = two_members("loot", starts, ends)
    assert tournaments.round_window(doc, 0) == (starts, ends)
    sunday, tuesday = gold_over_monday(1_000_000, 3_000_000, 5_000_000)
    store = FakeStore(state={("clan-a", "progress"): sunday})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, SUN))
    assert set(doc["scores"].values()) == {0}
    store.state[("clan-a", "progress")] = tuesday
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, TUE))
    assert {row["tag"]: row["loot"] for row in progress_mod.deltas(tuesday, "week")} == {
        "#P1": 2_000_000, "#P2": 0}
    assert doc["scores"][tournaments.entry_id("member", "#P1")] == 2_000_000
    assert doc["scores"][tournaments.entry_id("member", "#P2")] == 0
    doc, _ = asyncio.run(tourney_results.refresh(
        store, doc, datetime.fromtimestamp(ends + 60, timezone.utc)))
    assert doc["rounds"][0][0]["winner"] == tournaments.entry_id("member", "#P1")


def test_la_finestra_somma_il_periodo_chiuso_solo_se_cade_dentro():
    _, tuesday = gold_over_monday(1_000_000, 3_000_000, 5_000_000)
    inside = progress_mod.window(tuesday, "week", int(WED.timestamp()))
    after = progress_mod.window(tuesday, "week", int(TUE.timestamp()))
    plain = progress_mod.window(tuesday, "week")
    assert {row["tag"]: row["loot"] for row in inside} == {"#P1": 4_000_000, "#P2": 0}
    assert {row["tag"]: row["loot"] for row in after} == {"#P1": 2_000_000, "#P2": 0}
    assert {row["tag"]: row["loot"] for row in plain} == {"#P1": 2_000_000, "#P2": 0}


def test_il_vincitore_si_aggiunge_ai_titoli_della_stessa_stagione():
    doc = bracket()
    store = FakeStore(wars=both_sides(INSIDE, 9, 5),
                      state={**acceso_su("clan-a", "clan-b"),
                             ("clan-a", "hall"): {"seasons": []}})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW))
    poller = Poller(FakeSupervisor(), store, None)
    asyncio.run(poller.crown(doc, [A]))
    derby_doc = tournaments.empty("derby", "family", "both", "table", TS - 10, TS - 5, TS + 10)
    derby_doc, _ = tournaments.join(derby_doc, "clan", A.alias, A.name)
    asyncio.run(poller.crown(derby_doc, [A]))
    seasons = store.state[("clan-a", "hall")]["seasons"]
    assert len(seasons) == 1
    assert seasons[0]["titles"] == {"Torneo": ["Alfa", 2], "Derby": ["Alfa", 1]}


def test_la_guerra_vera_non_riscrive_i_punteggi_di_un_altra_metrica():
    doc = tournaments.empty("clash", "family", "loot", "table", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-555555"
    doc["clan_alias"] = "clan-a"
    for clan in (FOUR["A"], FOUR["B"], FOUR["C"]):
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    doc = tournaments.make_groups(doc, 1)
    loot = {"clan-a": 1_000_000, "clan-b": 2_000_000, "clan-c": 5_000_000}
    store = FourStore(
        wars={"clan-a": [war_record_between("#B", INSIDE, 9, 5, 90.0, 40.0)],
              "clan-b": [war_record_between("#A", INSIDE, 5, 9, 40.0, 90.0)]},
        state={**acceso_su(*loot),
               **{(alias, "progress"): {"#P1": {"name": "Mario", "now": {"gold": gold, "elixir": 0},
                                                "week": {"since": TS - 86400, "gold": 0, "elixir": 0}}}
                  for alias, gold in loot.items()}})
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW + timedelta(hours=2)))
    assert [(row["name"], row["value"]) for row in tournaments.table(doc)] == [
        ("C", 5_000_000), ("B", 2_000_000), ("A", 1_000_000)]
    assert tournaments.winner(doc) == tournaments.entry_id("clan", "clan-c")


def test_la_classifica_a_stelle_resta_quella_della_cwl():
    doc = tournaments.empty("clash", "family", "stars", "table", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-666666"
    for clan in (FOUR["A"], FOUR["B"], FOUR["C"]):
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    doc = tournaments.make_groups(doc, 1)
    store = FourStore(wars={"clan-a": [war_record_between("#B", INSIDE, 9, 5, 90.0, 40.0)],
                            "clan-b": [war_record_between("#A", INSIDE, 5, 9, 40.0, 90.0)]},
                      state=acceso_su("clan-a", "clan-b", "clan-c"))
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW))
    assert doc["scores"][tournaments.entry_id("clan", "clan-a")] == 19
    assert doc["scores"][tournaments.entry_id("clan", "clan-b")] == 5


def test_i_titoli_del_blocco_esistono():
    assert scoring.TITLES["Derby"] and scoring.TITLES["Torneo"]


def torneo_di_clan(scope, metric):
    doc = tournaments.empty("clash", scope, metric, "table", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-888888"
    doc, _ = tournaments.join(doc, "clan", A.alias, A.name)
    return tournaments.make_groups(doc, 1)


def punteggio_di_clan(store, scope, metric):
    doc, _ = asyncio.run(tourney_results.refresh(store, torneo_di_clan(scope, metric),
                                                 NOW + timedelta(hours=2)))
    return doc["scores"][tournaments.entry_id("clan", "clan-a")]


def store_di_clan(acceso=False):
    progress = {"#P1": {"name": "Mario",
                        "now": {"wins": 40, "gold": 3_000_000, "elixir": 0},
                        "week": {"since": TS - 86400, "wins": 0, "gold": 1_000_000, "elixir": 0}}}
    state = {("clan-a", "progress"): progress, ("clan-a", "info"): {"members": 2}}
    if acceso:
        state[("clan-a", views.KIND)] = {views.FAMILY: True}
    return FakeStore(wars={"clan-a": [war_record_between("#Z", INSIDE, 42, 1)]}, state=state)


def test_il_torneo_di_famiglia_non_conta_le_stelle_di_chi_tiene_il_punteggio_nel_suo_clan():
    assert punteggio_di_clan(store_di_clan(), "family", "stars") == 0
    assert punteggio_di_clan(store_di_clan(acceso=True), "family", "stars") == 42


def test_il_torneo_di_famiglia_si_chiude_su_ogni_metrica_non_solo_sull_attivita():
    for metric in tourney_ui.CLAN_METRICS + ("loot",):
        assert punteggio_di_clan(store_di_clan(), "family", metric) == 0, metric
        assert punteggio_di_clan(store_di_clan(acceso=True), "family", metric) > 0, metric


def test_il_torneo_di_rete_conta_le_stelle_del_clan_che_ci_si_e_iscritto():
    assert punteggio_di_clan(store_di_clan(), "network", "stars") == 42
    assert punteggio_di_clan(store_di_clan(), "clan", "stars") == 42


def torneo_di_famiglia_a_stelle(*acceso):
    doc = tournaments.empty("clash", "family", "stars", "table", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-999999"
    for clan in (A, B):
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    doc = tournaments.make_groups(doc, 1)
    store = FakeStore(wars=both_sides(INSIDE, 9, 5), state=acceso_su(*acceso))
    doc, _ = asyncio.run(tourney_results.refresh(store, doc, NOW))
    return [doc["scores"][tournaments.entry_id("clan", alias)] for alias in ("clan-a", "clan-b")]


def test_la_guerra_fra_due_clan_di_famiglia_non_pubblica_il_punteggio_di_chi_lo_tiene_nel_clan():
    assert torneo_di_famiglia_a_stelle() == [0, 0]
    assert torneo_di_famiglia_a_stelle("clan-a", "clan-b") == [19, 5]


def test_la_guerra_di_famiglia_non_esce_se_uno_dei_due_tiene_il_punteggio_nel_suo_clan():
    assert torneo_di_famiglia_a_stelle("clan-a") == [9, 0]


def sfida_di_famiglia(*acceso):
    store = FakeStore(wars=both_sides(INSIDE, 9, 5), state=acceso_su(*acceso))
    doc, _ = asyncio.run(tourney_results.refresh(store, bracket(), NOW))
    return doc["rounds"][0][0]


def test_la_sfida_di_famiglia_non_si_decide_col_punteggio_di_chi_lo_tiene_nel_suo_clan():
    assert sfida_di_famiglia()["done"] is False
    assert sfida_di_famiglia("clan-a", "clan-b")["done"] is True


def test_la_sfida_di_famiglia_non_si_gioca_se_uno_dei_due_tiene_il_punteggio_nel_suo_clan():
    assert sfida_di_famiglia("clan-a")["done"] is False


class StoreCheConta(FakeStore):
    def __init__(self, clans, **kwargs):
        super().__init__(**kwargs)
        self.clans = {clan.alias: clan for clan in clans}
        self.conti = {"clan_by_alias": 0, "views": 0}

    async def clan_by_alias(self, alias):
        self.conti["clan_by_alias"] += 1
        return self.clans.get(alias)

    async def get_state(self, alias, kind):
        if kind == views.KIND:
            self.conti["views"] += 1
        return await super().get_state(alias, kind)


def costo_di_un_girone(scope, *acceso):
    doc = tournaments.empty("clash", scope, "stars", "table", TS - 86400, TS - 3600, TS + 3600)
    doc["alias"] = "trn-555555"
    for clan in FOUR.values():
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    doc = tournaments.make_groups(doc, 1)
    store = StoreCheConta(FOUR.values(), state=acceso_su(*acceso))
    asyncio.run(tourney_results.refresh(store, doc, NOW))
    return store.conti


def test_il_torneo_di_rete_non_risolve_il_clan_di_chi_sfida_per_un_cancello_che_non_puo_scattare():
    assert costo_di_un_girone("network") == {"clan_by_alias": 16, "views": 0}
    assert costo_di_un_girone("clan") == {"clan_by_alias": 16, "views": 0}


def test_il_torneo_di_famiglia_risolve_il_cancello_di_chi_sfida_una_volta_per_giro():
    acceso = [clan.alias for clan in FOUR.values()]
    assert costo_di_un_girone("family", *acceso) == {"clan_by_alias": 20, "views": 20}
