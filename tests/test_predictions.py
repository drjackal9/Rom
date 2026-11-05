import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import (badges, boards, challenges, cwl_season, handlers, i18n, polls, predictions, scoring,
                      settings as settings_mod)
from clashbot.poller import Poller, Tick
from cwl_fixtures import SEASON, cwl_state, war_records
from test_capital_block import CAPITAL_JSON, FRIDAY, MONDAY, Coc
from test_capital_block import Store as CapitalStore
from test_capital_block import raid
from test_capital_block import tick as capital_tick
from test_flows import CLAN, FakeBot, FakeStore, fake_context, fake_supervisor

L = i18n.locale("it")
TZ = "Europe/Rome"
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
RAID = "20260911T070000.000Z"
CWL_CLAN = SimpleNamespace(alias=CLAN.alias, chat_id=CLAN.chat_id, tag="#C1", name="Nostro Clan",
                           bot_alias=CLAN.bot_alias)


class Store(FakeStore):
    def __init__(self, state=None, wars=(), history=()):
        super().__init__(state=state, wars=wars)
        self.history = [copy.deepcopy(row) for row in history]

    async def recent_stats(self, alias, kind, limit=10):
        rows = [obj for row_alias, row_kind, obj in self.history
                if row_alias == alias and row_kind == kind]
        return copy.deepcopy(rows[:limit])


def tick(stored=None, clan=CLAN):
    t = Tick(clan, NOW)
    t.settings = settings_mod.effective(stored or {"lang": "it", "tz": TZ}, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.season = scoring.empty_season("2026-09")
    return t


def vote(poll_id, user_id, name, option):
    return SimpleNamespace(poll_id=poll_id, option_ids=[option],
                           user=SimpleNamespace(id=user_id, first_name=name))


def open_cwl(poller, t, key=SEASON):
    return asyncio.run(predictions.start(poller, t, "cwl", key))


def test_la_domanda_e_le_opzioni_della_guerra_restano_quelle_di_oggi():
    store, bot = Store(), FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick()
    assert asyncio.run(predictions.start(poller, t, "war", "w1", opponent="Nemici")) is True
    chat_id, question, options, kw = bot.polls[0]
    assert chat_id == CLAN.chat_id and kw["is_anonymous"] is False
    assert question == L.t("poll.question", opponent="Nemici")
    assert options == [L.t(f"poll.option.{i}") for i in range(scoring.POLL_OPTIONS)]
    assert store.state[(CLAN.alias, "poll")] == {"war": "w1", "poll_id": "pid1", "message_id": 1,
                                                 "votes": {}}
    assert store.kv["poll:pid1"] == {"state": "poll"}
    assert asyncio.run(predictions.start(poller, t, "war", "w1", opponent="Nemici")) is False
    assert len(bot.polls) == 1


def test_i_tre_pronostici_convivono_ognuno_col_suo_stato():
    store, bot = Store(), FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick()
    asyncio.run(predictions.start(poller, t, "war", "w1", opponent="Nemici"))
    open_cwl(poller, t)
    asyncio.run(predictions.start(poller, t, "capital", RAID, reference=200000,
                                  record=L.n(200000)))
    assert [predictions.state_key(kind) for kind in ("war", "cwl", "capital")] == [
        "poll", "poll_cwl", "poll_capital"]
    assert {key[1] for key in store.state} == {"poll", "poll_cwl", "poll_capital"}
    assert len(bot.polls) == 3
    assert bot.polls[1][1] == L.t("poll.question.cwl")
    assert L.n(200000) in bot.polls[2][1]
    assert bot.polls[2][2] == bot.polls[0][2]
    assert store.state[(CLAN.alias, "poll_capital")]["reference"] == 200000
    assert "reference" not in store.state[(CLAN.alias, "poll")]


def test_il_voto_arriva_al_sondaggio_giusto_senza_un_percorso_nuovo():
    store, bot = Store(), FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick()
    asyncio.run(predictions.start(poller, t, "war", "w1", opponent="Nemici"))
    open_cwl(poller, t)
    asyncio.run(handlers.on_poll_answer(SimpleNamespace(poll_answer=vote("pid2", 7, "Alex", 3)),
                                        fake_context(store)))
    assert store.state[(CLAN.alias, "poll_cwl")]["votes"] == {"7": {"name": "Alex", "option": 3}}
    assert store.state[(CLAN.alias, "poll")]["votes"] == {}


def test_il_verdetto_paga_punti_badge_e_una_sola_classifica():
    store, bot = Store(), FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick()
    open_cwl(poller, t)
    asyncio.run(polls.record_answer(store, vote("pid1", 7, "Alex", 3)))
    asyncio.run(polls.record_answer(store, vote("pid1", 9, "Toad", 0)))
    assert asyncio.run(predictions.settle(poller, t, "cwl", SEASON, 63, 63)) is True
    assert t.season["predictions"]["7"] == {"name": "Alex", "correct": 1, "total": 1}
    assert t.season["predictions"]["9"] == {"name": "Toad", "correct": 0, "total": 1}
    righe = boards.lines_of(t.boards, "challenges")
    assert len(righe) == 1 and "Alex" in righe[0] and "Toad" not in righe[0]
    assert bot.stopped == [(CLAN.chat_id, 1)]
    assert (CLAN.alias, "poll_cwl") not in store.state and "poll:pid1" not in store.kv
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(state, 7) == ["veggente"] and badges.of(state, 9) == []
    assert asyncio.run(predictions.settle(poller, t, "cwl", SEASON, 63, 63)) is False


def test_il_pronostico_della_capitale_si_giudica_sul_record_scritto_nella_domanda():
    store, bot = Store(), FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick()
    asyncio.run(predictions.start(poller, t, "capital", RAID, reference=200000,
                                  record=L.n(200000)))
    asyncio.run(polls.record_answer(store, vote("pid1", 7, "Alex", 1)))
    asyncio.run(polls.record_answer(store, vote("pid1", 9, "Toad", 3)))
    assert asyncio.run(predictions.capital_settle(poller, t, dict(raid("ended"),
                                                                 startTime=RAID,
                                                                 capitalTotalLoot=120000))) is True
    assert t.season["predictions"]["7"] == {"name": "Alex", "correct": 1, "total": 1}
    assert t.season["predictions"]["9"] == {"name": "Toad", "correct": 0, "total": 1}


def test_il_record_della_capitale_esce_dallo_storico_gia_scritto():
    store = Store(history=[(CLAN.alias, "capital", {"loot": 180000}),
                           (CLAN.alias, "capital", {"loot": 120000}),
                           (CLAN.alias, "games", {"loot": 900000})])
    assert asyncio.run(predictions.capital_reference(store, CLAN.alias)) == 180000
    assert asyncio.run(predictions.capital_reference(Store(), CLAN.alias)) == 0


def test_senza_record_la_capitale_non_apre_nessun_sondaggio():
    store, bot = Store(), FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick()
    assert asyncio.run(predictions.capital_open(poller, t, raid("ongoing"))) is False
    assert bot.polls == [] and store.state == {}


def test_col_pacchetto_delle_sfide_spento_non_parte_niente():
    store, bot = Store(), FakeBot()
    poller = Poller(fake_supervisor(bot), store, None)
    t = tick({"lang": "it", "tz": TZ, "packs": {"challenges": False}})
    assert open_cwl(poller, t) is False
    assert asyncio.run(predictions.start(poller, t, "war", "w1", opponent="Nemici")) is False
    assert bot.polls == [] and store.state == {} and store.kv == {}


def test_la_cwl_apre_un_solo_pronostico_alla_prima_giornata():
    store, bot = Store(), FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick()
    cwl = cwl_state(state="inWar")
    assert asyncio.run(predictions.cwl_open(poller, t, cwl, {"day": 2, "state": "preparation"})) is False
    assert asyncio.run(predictions.cwl_open(poller, t, cwl, {"day": 1, "state": "warEnded"})) is False
    assert asyncio.run(predictions.cwl_open(poller, t, cwl, {"day": 1, "state": "preparation"})) is True
    assert asyncio.run(predictions.cwl_open(poller, t, cwl, {"day": 1, "state": "inWar"})) is False
    assert len(bot.polls) == 1 and store.state[(CLAN.alias, "poll_cwl")]["war"] == SEASON


def test_la_cwl_chiusa_giudica_sulle_stelle_di_guerra_e_non_sul_bonus(monkeypatch):
    saved = []

    async def fake_save(store, alias, season, ended_at, record):
        saved.append(season)
        return True

    monkeypatch.setattr("clashbot.cwl_store.save_season", fake_save)
    store = Store(state={(CWL_CLAN.alias, "cwl"): cwl_state()}, wars=war_records())
    bot = FakeBot()
    poller, t = Poller(fake_supervisor(bot), store, None), tick(clan=CWL_CLAN)
    open_cwl(poller, t)
    asyncio.run(polls.record_answer(store, vote("pid1", 7, "Alex", 2)))
    asyncio.run(polls.record_answer(store, vote("pid1", 9, "Toad", 3)))
    cwl = asyncio.run(store.get_state(CWL_CLAN.alias, "cwl"))
    record = cwl_season.season_record(cwl, CWL_CLAN.tag, war_records())
    assert record["stars"] == 27
    assert asyncio.run(poller.close_cwl_season(t, cwl)) is True
    assert saved == [SEASON]
    assert t.season["predictions"]["7"] == {"name": "Alex", "correct": 1, "total": 1}
    assert t.season["predictions"]["9"] == {"name": "Toad", "correct": 0, "total": 1}
    assert len(boards.lines_of(t.boards, "cwl")) == 1
    assert len(boards.lines_of(t.boards, "challenges")) == 1
    assert (CWL_CLAN.alias, "poll_cwl") not in store.state


def test_la_capitale_apre_sul_record_e_chiude_a_weekend_finito():
    store = CapitalStore()
    store.stats.append((CLAN.alias, "capital", "20260904T070000.000Z",
                        datetime(2026, 9, 7, 7, tzinfo=timezone.utc), {"loot": 200000}))
    bot, coc = FakeBot(), Coc([raid("ongoing")])
    poller = Poller(fake_supervisor(bot), store, coc)
    t = capital_tick(FRIDAY)
    asyncio.run(poller.track_capital(t, CAPITAL_JSON))
    assert len(bot.polls) == 1 and L.n(200000) in bot.polls[0][1]
    assert store.state[(CLAN.alias, "poll_capital")]["war"] == RAID
    asyncio.run(polls.record_answer(store, vote("pid1", 7, "Alex", 1)))
    coc.items = [raid("ended")]
    dopo = capital_tick(MONDAY)
    asyncio.run(poller.track_capital(dopo, CAPITAL_JSON))
    assert dopo.season["predictions"]["7"] == {"name": "Alex", "correct": 1, "total": 1}
    assert (CLAN.alias, "poll_capital") not in store.state
    assert len(boards.lines_of(dopo.boards, "challenges")) == 1
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(state, 7) == ["veggente"]
