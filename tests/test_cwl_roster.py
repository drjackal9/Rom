import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import cwl_cards, cwl_roster, handlers, i18n
from clashbot.cwl import group_summary
from clashbot.poller import Poller, Tick
from cwl_fixtures import SEASON, cwl_state, war_records

L = i18n.locale("it")
NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#C1", name="Futuro", bot_alias="bot-1")
PLAYERS = {"tags": {"#P3": {"name": "Peach", "th": 13, "warPref": "out"}}}


class FakeStore:
    def __init__(self, state=None, wars=(), links=()):
        self.state = {k: copy.deepcopy(v) for k, v in (state or {}).items()}
        self.wars = list(wars)
        self.links = list(links)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def recent_wars(self, alias, limit=10):
        return copy.deepcopy(self.wars)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def links_by_user(self, user_id):
        return list(self.links)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)


def fake_supervisor():
    return SimpleNamespace(bot=lambda alias: None, running=lambda: ["bot-1"],
                           default_alias="bot-1", owner_bot=lambda: None)


def test_il_riassunto_del_girone_porta_la_rosa_iscritta():
    summary = group_summary({
        "state": "preparation", "season": SEASON,
        "clans": [{"tag": "#C1", "name": "Nostro Clan", "clanLevel": 12,
                   "members": [{"tag": "#P1", "name": "Mario", "townHallLevel": 15}]}],
        "rounds": [{"warTags": ["#W1", "#0"]}],
    })
    assert summary["clans"]["#C1"]["members"] == [{"tag": "#P1", "name": "Mario", "th": 15}]
    assert summary["rounds"] == [["#W1"]]


def test_registrati_disponibilita_e_rotazione():
    cwl = cwl_state()
    reg = cwl_roster.registered(cwl, "#C1")
    assert sorted(reg) == ["#P1", "#P2", "#P3"]
    state = cwl_roster.for_season(None, SEASON)
    cwl_roster.declare(state, "#P2", cwl_roster.IN, 7, NOW.timestamp())
    played = cwl_roster.played_days(war_records()[:2])
    assert played["#P1"] == [1, 2] and played["#P3"] == [1]
    rows = cwl_roster.rows(reg, state, played, war_records()[:2], {})
    assert [r["tag"] for r in rows] == ["#P2", "#P3", "#P1"]
    assert rows[0]["state"] == cwl_roster.IN and rows[0]["declared"] is True
    assert rows[1]["state"] == cwl_roster.UNKNOWN and rows[1]["days"] == 1
    assert rows[2]["state"] == cwl_roster.UNKNOWN and rows[2]["days"] == 2
    fuori = cwl_roster.rows(reg, cwl_roster.for_season(None, SEASON), played, war_records()[:2],
                            {"#P3": {"warPref": "out"}})
    assert next(r for r in fuori if r["tag"] == "#P3")["state"] == cwl_roster.OUT


def test_la_formazione_si_taglia_alla_dimensione_della_guerra():
    cwl = cwl_state()
    state = cwl_roster.for_season(None, SEASON)
    rows = cwl_roster.rows(cwl_roster.registered(cwl, "#C1"), state, {}, [], {})
    proposed, bench = cwl_roster.lineup(rows, 2)
    assert len(proposed) == 2 and len(bench) == 1
    proposed, bench = cwl_roster.lineup(rows, None)
    assert len(proposed) == 3 and bench == []


WIDE = {"#P1": {"name": "Mario", "th": 16}, "#P2": {"name": "Luigi", "th": 15},
        "#P3": {"name": "Peach", "th": 14}, "#P4": {"name": "Toad", "th": 13}}


def wide_rows(chosen=()):
    state = cwl_roster.for_season(None, SEASON)
    for tag in sorted(WIDE):
        cwl_roster.declare(state, tag, cwl_roster.IN, 7, NOW.timestamp())
    for tag in chosen:
        cwl_roster.choose(state, tag)
    return cwl_roster.rows(WIDE, state, {}, [], {}), state


def test_the_pinned_players_keep_their_seat_and_the_rest_of_the_line_up_is_filled():
    rows, state = wide_rows(["#P4"])
    assert [row["tag"] for row in rows] == ["#P1", "#P2", "#P3", "#P4"]
    proposed, bench = cwl_roster.lineup(rows, 3, cwl_roster.picked(state))
    assert [row["tag"] for row in proposed] == ["#P1", "#P2", "#P4"]
    assert [row["tag"] for row in bench] == ["#P3"]


def test_the_pinned_players_never_go_over_the_size_of_the_war():
    rows, state = wide_rows(["#P3", "#P4"])
    proposed, bench = cwl_roster.lineup(rows, 1, cwl_roster.picked(state))
    assert [row["tag"] for row in proposed] == ["#P3"]
    assert [row["tag"] for row in bench] == ["#P1", "#P2", "#P4"]
    rows, state = wide_rows(["#P4"])
    proposed, bench = cwl_roster.lineup(rows, 4, cwl_roster.picked(state))
    assert len(proposed) == 4 and bench == []


def picked_store():
    state = cwl_roster.for_season(None, SEASON)
    cwl_roster.choose(state, "#P3")
    return FakeStore(state={(CLAN.alias, "cwl"): cwl_state(),
                            (CLAN.alias, "players"): PLAYERS,
                            (CLAN.alias, "cwl_war"): {"teamSize": 1, "day": 3},
                            (CLAN.alias, "cwl_roster"): state,
                            (CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"}},
                     wars=war_records())


def test_la_formazione_fissata_nell_app_e_quella_che_esce_nel_gruppo(monkeypatch):
    sent = []

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        sent.append(render_text(t.L))

    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    store = picked_store()
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    t.L = L
    war = {"state": "preparation", "day": 3, "teamSize": 1}
    assert asyncio.run(poller.cwl_lineup(t, cwl_state(), war)) is True
    schierati = sent[0].split(L.t("cwl.roster.bench"))[0]
    assert "Peach" in schierati and "Mario" not in schierati


def test_la_scheda_della_rosa_mostra_i_titolari_fissati_dall_app():
    store = picked_store()
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"})
    text, _ = asyncio.run(handlers.build_view("cwl:roster", CLAN, context))
    schierati = text.split(L.t("cwl.roster.bench"))[0]
    assert "Peach" in schierati and "Mario" not in schierati


def test_le_card_della_rosa_si_leggono():
    cwl = cwl_state()
    state = cwl_roster.for_season(None, SEASON)
    cwl_roster.declare(state, "#P2", cwl_roster.IN, 7, NOW.timestamp())
    rows = cwl_roster.rows(cwl_roster.registered(cwl, "#C1"), state, {}, [], {})
    proposed, bench = cwl_roster.lineup(rows, 2)
    text = cwl_cards.roster_card(L, rows, proposed, bench, 2)
    assert "ROSA CWL" in text and "Luigi" in text and "Chi riposa" in text
    assert "FORMAZIONE · GIORNATA 3" in cwl_cards.lineup_card(L, proposed, bench, 3)


def test_il_bottone_vale_solo_per_il_proprio_giocatore():
    store = FakeStore(state={(CLAN.alias, "cwl"): cwl_state()},
                      links=[SimpleNamespace(alias="link-1", user_id=7, tag="#P2", name="Luigi", dm=True)])
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"})
    update = SimpleNamespace(callback_query=FakeQuery("cw:av:in"),
                             effective_chat=SimpleNamespace(id=CLAN.chat_id),
                             effective_user=SimpleNamespace(id=7, language_code="it"))
    asyncio.run(handlers.on_cwl_callback(update, context))
    assert store.state[(CLAN.alias, "cwl_roster")]["avail"]["#P2"]["state"] == "in"
    assert update.callback_query.edits and "✅ Luigi" in update.callback_query.edits[-1]
    estraneo = SimpleNamespace(callback_query=FakeQuery("cw:av:out"),
                               effective_chat=SimpleNamespace(id=CLAN.chat_id),
                               effective_user=SimpleNamespace(id=9, language_code="it"))
    store.links = []
    asyncio.run(handlers.on_cwl_callback(estraneo, context))
    assert estraneo.callback_query.answers[-1][1] is True
    assert "#P2" in store.state[(CLAN.alias, "cwl_roster")]["avail"]


def test_la_formazione_parte_una_volta_per_giornata(monkeypatch):
    sent = []

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        sent.append((event, render_text(t.L)))

    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    store = FakeStore(state={(CLAN.alias, "cwl"): cwl_state(), (CLAN.alias, "players"): PLAYERS},
                      wars=war_records())
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    t.L = L
    war = {"state": "preparation", "day": 3, "teamSize": 2}
    cwl = cwl_state()
    assert asyncio.run(poller.cwl_lineup(t, cwl, war)) is True
    assert sent[0][0] == "cwl.roster" and "FORMAZIONE" in sent[0][1]
    assert asyncio.run(poller.cwl_lineup(t, cwl, war)) is False
    assert len(sent) == 1
    assert asyncio.run(poller.cwl_lineup(t, cwl, {"state": "inWar", "day": 3})) is False
