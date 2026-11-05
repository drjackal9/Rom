import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import badges, boards, challenges, i18n, missions, progress, settings as settings_mod
from clashbot.poller import Poller, Tick

CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
TZ = "Europe/Rome"
MONDAY = datetime(2026, 9, 14, 10, tzinfo=timezone.utc)
SUNDAY = datetime(2026, 9, 20, 10, tzinfo=timezone.utc)
ROWS = [{"tag": "#P1", "name": "Mario", "donated": 600, "war_stars": 5, "loot": 1000, "capital_gold": 0,
         "games": 0, "levels": 2},
        {"tag": "#P2", "name": "Luigi", "donated": 400, "war_stars": 3, "loot": 500, "capital_gold": 0,
         "games": 0, "levels": 0}]


class FakeStore:
    def __init__(self, state=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)


def tick(store, bot, now):
    poller = Poller(SimpleNamespace(bot=lambda alias: bot, running=lambda: [CLAN.bot_alias],
                                    default_alias=CLAN.bot_alias, owner_bot=lambda: bot), store, None)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective({"lang": "it", "tz": TZ}, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    return poller, t


def swept(state, tag, name, donated, now):
    return progress.update(state, tag, name, {"donated": donated, "th": 14}, now, TZ)


def test_somma_e_contributi():
    assert missions.total(ROWS, "donated") == 1000
    assert [row["name"] for row in missions.contributors(ROWS, "donated")] == ["Mario", "Luigi"]
    assert missions.contributors(ROWS, "capital_gold") == []


def test_la_prima_settimana_registra_il_record_poi_l_obiettivo_e_batterlo():
    state = challenges.empty()
    first = missions.open_week(state, "2026-W38", "donated", 0)
    assert first["goal"] == 0 and first["measuring"] is True
    state["mission"]["best"] = {"donated": 1000}
    second = missions.open_week(state, "2026-W39", "donated", 0)
    assert second["goal"] == 1000 and second["measuring"] is False


def test_avanzamento_e_avvisi_una_volta_sola():
    mission = {"week": "2026-W39", "metric": "donated", "goal": 1000, "start": 0, "sent": [], "measuring": False}
    done, goal, pct = missions.standing(mission, 400)
    assert (done, goal, pct) == (400, 1000, 40)
    assert missions.due_notices(mission, 400, 1000) == []
    assert missions.due_notices(mission, 600, 1000) == ["half"]
    assert missions.due_notices(mission, 600, 1000) == []
    assert missions.due_notices(mission, 1200, 1000) == ["done"]
    assert missions.due_notices(mission, 1400, 1000) == []


def week_of_two(donated_p1=1000, donated_p2=600):
    before = datetime(2026, 9, 9, 10, tzinfo=timezone.utc)
    state = swept(swept({}, "#P1", "Mario", 0, before), "#P2", "Luigi", 0, before)
    state = swept(state, "#P1", "Mario", 0, MONDAY)
    state = swept(state, "#P2", "Luigi", 0, MONDAY)
    friday = datetime(2026, 9, 18, 10, tzinfo=timezone.utc)
    state = swept(state, "#P1", "Mario", donated_p1, friday)
    state = swept(state, "#P2", "Luigi", donated_p2, friday)
    after = SUNDAY + timedelta(days=1)
    state = swept(state, "#P1", "Mario", donated_p1, after)
    state = swept(state, "#P2", "Luigi", donated_p2, after)
    return state, after


def test_il_giro_apre_la_missione_e_la_chiude_a_fine_settimana():
    opening = swept(swept({}, "#P1", "Mario", 0, datetime(2026, 9, 9, 10, tzinfo=timezone.utc)),
                    "#P1", "Mario", 600, MONDAY)
    store, bot = FakeStore({(CLAN.alias, "progress"): opening}), FakeBot()
    poller, t = tick(store, bot, MONDAY)
    asyncio.run(missions.run(poller, t))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["mission"]["week"] == challenges.week_id(MONDAY, t.tz)
    assert state["mission"]["metric"] in missions.METRICS
    assert state["mission"]["start"] == 0
    assert len(boards.lines_of(t.boards, "challenges")) == 1
    closed_state, after = week_of_two()
    asyncio.run(store.set_state(CLAN.alias, "progress", closed_state))
    poller, t2 = tick(store, bot, after)
    asyncio.run(missions.run(poller, t2))
    closed = asyncio.run(challenges.load(store, CLAN.alias))
    assert closed["mission"]["week"] == challenges.week_id(t2.now, t2.tz)
    assert closed["mission"]["best"] == {"donated": 1600}
    assert challenges.recent(closed, "mission")


def test_la_missione_riuscita_da_il_badge_a_chi_ha_contribuito():
    progress_state, after = week_of_two()
    store, bot = FakeStore({(CLAN.alias, "progress"): progress_state}), FakeBot()
    state = challenges.empty()
    state["mission"]["best"] = {"donated": 500}
    missions.open_week(state, challenges.week_id(MONDAY, TZ), "donated", 0)
    asyncio.run(challenges.save(store, CLAN.alias, state))
    poller, t = tick(store, bot, after)
    asyncio.run(missions.run(poller, t))
    closed = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(closed, "#P1") == ["missione"] and badges.of(closed, "#P2") == ["missione"]
    assert challenges.recent(closed, "mission")[-1]["won"] is True


def test_al_primo_giro_della_settimana_contano_solo_le_righe_gia_azzerate():
    before = datetime(2026, 9, 9, 10, tzinfo=timezone.utc)
    saturday = datetime(2026, 9, 12, 10, tzinfo=timezone.utc)
    state = swept(swept({}, "#P1", "Mario", 0, before), "#P2", "Luigi", 0, before)
    state = swept(swept(state, "#P1", "Mario", 900, saturday), "#P2", "Luigi", 700, saturday)
    state = swept(state, "#P1", "Mario", 950, MONDAY)
    store, bot = FakeStore({(CLAN.alias, "progress"): state}), FakeBot()
    poller, t = tick(store, bot, MONDAY)
    asyncio.run(missions.run(poller, t))
    mission = asyncio.run(challenges.load(store, CLAN.alias))["mission"]
    assert mission["metric"] == "donated" and mission["start"] == 0
    later = MONDAY + timedelta(minutes=5)
    state = swept(state, "#P2", "Luigi", 760, later)
    asyncio.run(store.set_state(CLAN.alias, "progress", state))
    poller, t2 = tick(store, bot, later)
    asyncio.run(missions.run(poller, t2))
    mission = asyncio.run(challenges.load(store, CLAN.alias))["mission"]
    assert mission["now"] == 110
    assert missions.standing(mission, mission["now"])[0] == 110


CROWD = [(f"#P{i:02d}", f"Membro {i:02d}", i * 11) for i in range(1, 51)]
DAWN = datetime(2026, 9, 13, 22, 30, tzinfo=timezone.utc)
REPORT = datetime(2026, 9, 14, 7, 30, tzinfo=timezone.utc)


def crowd_progress():
    before = datetime(2026, 9, 9, 10, tzinfo=timezone.utc)
    saturday = datetime(2026, 9, 12, 10, tzinfo=timezone.utc)
    state = {}
    for tag, name, _ in CROWD:
        state = swept(state, tag, name, 0, before)
    for tag, name, donated in CROWD:
        state = swept(state, tag, name, donated, saturday)
    for tag, name, donated in CROWD[:2]:
        state = swept(state, tag, name, donated, DAWN)
    return state


def crowd_mission(store):
    state = challenges.empty()
    state["mission"]["best"] = {"donated": 100}
    missions.open_week(state, challenges.week_id(DAWN - timedelta(days=1), TZ), "donated", 0)
    asyncio.run(challenges.save(store, CLAN.alias, state))


def test_la_chiusura_aspetta_l_ora_dei_report_e_conta_tutti_i_membri():
    progress_state = crowd_progress()
    store, bot = FakeStore({(CLAN.alias, "progress"): progress_state}), FakeBot()
    crowd_mission(store)
    poller, t = tick(store, bot, DAWN)
    asyncio.run(missions.run(poller, t))
    aperta = asyncio.run(challenges.load(store, CLAN.alias))
    assert t.chunks == []
    assert challenges.recent(aperta, "mission") == []
    assert badges.of(aperta, CROWD[0][0]) == []
    assert aperta["mission"]["week"] == challenges.week_id(DAWN - timedelta(days=1), TZ)
    for tag, name, donated in CROWD[2:]:
        progress_state = swept(progress_state, tag, name, donated, REPORT)
    asyncio.run(store.set_state(CLAN.alias, "progress", progress_state))
    poller, t2 = tick(store, bot, REPORT)
    asyncio.run(missions.run(poller, t2))
    chiusa = asyncio.run(challenges.load(store, CLAN.alias))
    intero = sum(donated for _, _, donated in CROWD)
    nota = challenges.recent(chiusa, "mission")[-1]
    assert nota["done"] == intero and nota["won"] is True
    assert chiusa["mission"]["best"] == {"donated": intero}
    assert all(badges.of(chiusa, tag) == ["missione"] for tag, _, _ in CROWD)
    assert any("Missione" in line or "MISSIONE" in line
               for line in boards.lines_of(t2.boards, "challenges"))


def test_il_capo_cambia_metrica_e_la_missione_riparte():
    state = challenges.empty()
    missions.open_week(state, "2026-W39", "donated", 0)
    changed = missions.set_metric(state, "war_stars", 8)
    assert changed["metric"] == "war_stars" and changed["start"] == 8 and changed["sent"] == []
    assert missions.set_metric(state, "inventata", 8) is None
