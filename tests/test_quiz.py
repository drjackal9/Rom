import asyncio
import copy
import inspect
import json
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import (badges, boards, challenges, handlers, i18n, polls, quiz, quizbank, scoring,
                      settings as settings_mod)
from clashbot.poller import Poller, Tick

CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
FRIDAY = datetime(2026, 9, 11, 9, tzinfo=timezone.utc)
TUESDAY = datetime(2026, 9, 15, 9, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self):
        self.state = {}
        self.kv = {}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = {"value": copy.deepcopy(obj), "ref": ref}

    async def kv_get(self, key):
        return copy.deepcopy((self.kv.get(key) or {}).get("value"))

    async def kv_ref(self, key):
        return (self.kv.get(key) or {}).get("ref")

    async def kv_del(self, key):
        self.kv.pop(key, None)


class FakeBot:
    def __init__(self):
        self.polls = []
        self.stopped = []

    async def send_poll(self, chat_id, question, options, **kw):
        self.polls.append({"question": question, "options": options, "kw": kw})
        return SimpleNamespace(poll=SimpleNamespace(id=f"q{len(self.polls)}"), message_id=len(self.polls))

    async def stop_poll(self, chat_id, message_id):
        self.stopped.append(message_id)


def tick(store, bot, now):
    poller = Poller(SimpleNamespace(bot=lambda alias: bot, running=lambda: [CLAN.bot_alias],
                                    default_alias=CLAN.bot_alias, owner_bot=lambda: bot), store, None)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(
        {"lang": "it", "tz": "Europe/Rome",
         "routes": {quiz.EVENT: {"to": "group", "intensity": None}}}, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.season = scoring.empty_season("2026-09")
    return poller, t


def test_la_banca_ha_ventiquattro_domande_bilanciate_e_risposte_valide():
    assert len(quizbank.QUESTIONS) == 24
    topics = {}
    for q in quizbank.QUESTIONS:
        topics[q["topic"]] = topics.get(q["topic"], 0) + 1
        assert 0 <= q["answer"] < quizbank.OPTIONS
        assert quizbank.by_id(q["id"]) is q
    assert topics == {"war": 6, "capital": 6, "army": 6, "clan": 6}
    assert len({q["id"] for q in quizbank.QUESTIONS}) == 24


def test_ogni_domanda_esiste_in_tutte_e_venti_le_lingue_e_sta_nei_limiti_di_telegram():
    for code in i18n.LANGUAGES:
        with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
            catalog = json.load(handle)
        for q in quizbank.QUESTIONS:
            assert len(catalog[f"quiz.q.{q['id']}"]) <= 300, (code, q["id"])
            assert len(catalog[f"quiz.q.{q['id']}.why"]) <= 200, (code, q["id"])
            for i in range(quizbank.OPTIONS):
                assert 0 < len(catalog[f"quiz.q.{q['id']}.{i}"]) <= 100, (code, q["id"], i)


def test_la_scelta_e_deterministica_evita_le_usate_e_riparte_a_banca_finita():
    first = quiz.pick(CLAN.alias, "20260911", [])
    assert quiz.pick(CLAN.alias, "20260911", []) is first
    assert quiz.pick(CLAN.alias, "20260918", []) is not None
    used = [q["id"] for q in quizbank.QUESTIONS if q["id"] != first["id"]]
    assert quiz.pick(CLAN.alias, "20260911", used)["id"] == first["id"]
    assert quiz.pick(CLAN.alias, "20260911", [q["id"] for q in quizbank.QUESTIONS]) is not None


def test_il_quiz_parte_col_weekend_dei_raid_e_lo_chiude_il_bot():
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot, FRIDAY)
    asyncio.run(quiz.run(poller, t))
    assert len(bot.polls) == 1
    assert bot.polls[0]["kw"]["type"] == "quiz"
    assert bot.polls[0]["kw"]["is_anonymous"] is False
    assert isinstance(bot.polls[0]["kw"]["correct_option_id"], int)
    assert "open_period" not in bot.polls[0]["kw"] and "close_date" not in bot.polls[0]["kw"]
    asyncio.run(quiz.run(poller, t))
    assert len(bot.polls) == 1
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["quiz"]["open"]["poll_id"] == "q1" and state["quiz"]["used"]
    poller, t = tick(store, bot, TUESDAY)
    asyncio.run(quiz.run(poller, t))
    assert bot.stopped == [1]
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["quiz"]["open"] is None and state["quiz"]["last"] == "20260911"


def answer(option, user_id, name):
    return SimpleNamespace(poll_id="q1", option_ids=[option],
                           user=SimpleNamespace(id=user_id, first_name=name))


def test_i_punti_vanno_a_chi_ha_risposto_giusto_e_il_verdetto_esce_una_volta_sola():
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot, FRIDAY)
    asyncio.run(quiz.run(poller, t))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    right = quizbank.by_id(state["quiz"]["open"]["id"])["answer"]
    asyncio.run(polls.record_answer(store, answer(right, 7, "Alex")))
    asyncio.run(polls.record_answer(store, answer((right + 1) % quizbank.OPTIONS, 9, "Toad")))
    poller, closing = tick(store, bot, TUESDAY)
    asyncio.run(quiz.run(poller, closing))
    assert bot.stopped == [1]
    assert closing.season["play"]["7"] == {"name": "Alex", "quiz": 1, "duels": 0,
                                           "points": scoring.WEIGHTS["challenge"]}
    assert "9" not in closing.season["play"]
    assert any("Alex" in line for line in boards.lines_of(closing.boards, "challenges"))
    closed = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(closed, 7) == ["quiz"] and badges.of(closed, 9) == []
    poller, again = tick(store, bot, TUESDAY)
    asyncio.run(quiz.run(poller, again))
    assert again.season["play"] == {} and again.chunks == []


def test_il_voto_al_quiz_arriva_dal_percorso_dei_sondaggi_gia_esistente():
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot, FRIDAY)
    asyncio.run(quiz.run(poller, t))
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": CLAN.bot_alias})
    asyncio.run(handlers.on_poll_answer(SimpleNamespace(poll_answer=answer(2, 7, "Alex")), context))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["quiz"]["open"]["votes"] == {"7": {"name": "Alex", "option": 2}}


def test_senza_pacchetto_acceso_il_quiz_non_parte():
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot, FRIDAY)
    t.settings["packs"]["challenges"] = False
    asyncio.run(quiz.run(poller, t))
    assert bot.polls == []


def test_il_quiz_apre_dalla_strada_dei_sondaggi_e_scrive_l_unica_riga_kv():
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot, FRIDAY)
    asyncio.run(quiz.run(poller, t))
    assert store.kv["poll:q1"] == {"value": {"state": quiz.STATE_KEY}, "ref": CLAN.alias}
    assert polls.KEEPERS[quiz.STATE_KEY] == (quiz.load_poll, quiz.save_poll)
    testo = pathlib.Path(quiz.__file__).read_text(encoding="utf-8")
    assert "send_poll" not in testo and "stop_poll" not in testo and "kv_set" not in testo
    ramo = inspect.getsource(handlers.on_poll_answer)
    assert "polls.record_answer" in ramo
    assert "quiz" not in ramo and "awards" not in ramo and "kind" not in ramo
    poller, chiusura = tick(store, bot, TUESDAY)
    asyncio.run(quiz.run(poller, chiusura))
    assert bot.stopped == [1] and "poll:q1" not in store.kv
