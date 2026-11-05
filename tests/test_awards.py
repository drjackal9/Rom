import asyncio
import copy
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram.constants import ChatType, PollLimit

from clashbot import (awards, badges, boards, challenges, events, handlers, i18n, polls, render, scoring,
                      settings as settings_mod)
from clashbot.achievements import player_snapshot
from clashbot.poller import Poller, Tick
from fixtures import war_json

CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
FIRST = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 4, 10, tzinfo=timezone.utc)
IT = i18n.locale("it")
OWNER = 7
COC_NAME = 15


class FakeStore:
    def __init__(self, wars=()):
        self.state = {}
        self.kv = {}
        self.wars = list(wars)
        self.links = {}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def recent_wars(self, alias, limit=10):
        return copy.deepcopy(self.wars[:limit])

    async def wars_since(self, alias, since):
        return copy.deepcopy(self.wars)

    async def links_for_players(self, tags):
        return {tag: self.links[tag] for tag in tags if tag in self.links}

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = {"value": copy.deepcopy(obj), "ref": ref}

    async def kv_get(self, key):
        return copy.deepcopy((self.kv.get(key) or {}).get("value"))

    async def kv_ref(self, key):
        return (self.kv.get(key) or {}).get("ref")

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def get_secret(self, name):
        return str(OWNER) if name == "owner_id" else None

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None


class FakeBot:
    def __init__(self):
        self.polls = []
        self.stopped = []
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=1)

    async def send_poll(self, chat_id, question, options, **kw):
        self.polls.append({"question": question, "options": options})
        return SimpleNamespace(poll=SimpleNamespace(id="a1"), message_id=1)

    async def stop_poll(self, chat_id, message_id):
        self.stopped.append(message_id)


class FakeCoc:
    def __init__(self, players=None):
        self.players = players or {}

    async def player(self, tag):
        return copy.deepcopy(self.players.get(tag)), None


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []
        self.message = FakeMessage()

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


def war_record_with_triples():
    war = events.war_snapshot(war_json("warEnded", our_attacks={
        "#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 80)], "#P3": [("#E3", 3, 100)]}))
    return events.war_record(war)


def record_with_targets():
    return {"opponent": "Clan Nemico", "members": [
        {"tag": "#P1", "name": "Mario", "pos": 3, "th": 15, "missed": 1,
         "attacks": [{"stars": 3, "destr": 100, "defender": "#E1", "d_pos": 1, "d_th": 16}]},
        {"tag": "#P2", "name": "Luigi", "pos": 1, "th": 16, "missed": 1,
         "attacks": [{"stars": 2, "destr": 95, "defender": "#E2", "d_pos": 4, "d_th": 15}]},
        {"tag": "#P3", "name": "Peach", "pos": 4, "th": 15, "missed": 1,
         "attacks": [{"stars": 2, "destr": 88, "defender": "#E3", "d_pos": 2, "d_th": 15}]},
        {"tag": "#P4", "name": "Toad", "pos": 5, "th": 15, "missed": 1,
         "attacks": [{"stars": 3, "destr": 100, "defender": "#E5", "d_pos": 7, "d_th": 13}]},
    ]}


def routed(event, to):
    doc = settings_mod.migrate({"lang": "it", "tz": "Europe/Rome"})
    doc["routes"][event] = {"to": to, "intensity": None}
    return settings_mod.effective(doc, None)


CONF = settings_mod.effective(settings_mod.migrate({"lang": "it", "tz": "Europe/Rome"}), None)


def tick(store, bot, now, coc=None, conf=None):
    poller = Poller(SimpleNamespace(bot=lambda alias: bot, running=lambda: [CLAN.bot_alias],
                                    default_alias=CLAN.bot_alias, owner_bot=lambda: bot), store, coc)
    t = Tick(CLAN, now)
    t.settings = conf or CONF
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.season = scoring.empty_season("2026-10")
    return poller, t


def player_json(name, th=14, stars=100):
    return {"tag": "#P1", "name": name, "townHallLevel": th, "warStars": stars, "trophies": 5000,
            "warPreference": "in", "achievements": [{"name": "Gold Grab", "value": 10}],
            "heroes": [{"name": "Barbarian King", "level": 50, "village": "home"}]}


def context(store, coc=None, bot=None, args=None):
    return SimpleNamespace(
        bot_data={"store": store, "coc": coc, "bot_alias": CLAN.bot_alias,
                  "supervisor": SimpleNamespace(bot=lambda alias: bot, owner_bot=lambda: bot)},
        args=args if args is not None else [],
        bot=bot,
    )


def group_update(query=None):
    return SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.GROUP),
        effective_user=SimpleNamespace(id=OWNER, first_name="Alex", language_code="it"),
        effective_message=FakeMessage(),
    )


def rows_of(keyboard):
    return [[button.callback_data for button in row] for row in keyboard.inline_keyboard]


def keyboard_of(query):
    return query.edits[-1][1]


def test_i_candidati_all_attacco_del_mese_escono_dai_dati():
    rows = awards.candidates([war_record_with_triples()])
    assert rows and len(rows) <= awards.VOTE_OPTIONS
    assert all(row["stars"] >= rows[-1]["stars"] for row in rows)
    assert {"name", "stars", "destr"} <= set(rows[0])
    assert awards.candidates([]) == []


def test_lo_storico_della_guerra_porta_municipio_e_posizione():
    record = war_record_with_triples()
    mario = next(m for m in record["members"] if m["tag"] == "#P1")
    assert mario["pos"] == 1 and mario["th"] == 14
    assert mario["attacks"][0]["defender"] == "#E1"
    assert mario["attacks"][0]["d_pos"] == 1 and mario["attacks"][0]["d_th"] == 14
    assert mario["def"] == {"stars": 0, "destr": 0, "hits": 0}
    assert events.member_stats([record])["#P1"]["stars"] == 3
    assert {m["name"]: m["missed"] for m in record["members"]} == {"Mario": 1, "Luigi": 1, "Peach": 1}


def test_i_candidati_mettono_davanti_la_tripla_sul_municipio_piu_alto():
    rows = awards.candidates([record_with_targets()])
    assert [row["name"] for row in rows] == ["Mario", "Peach", "Toad", "Luigi"]
    assert rows[0]["th_up"] is True and rows[1]["uphill"] is True
    vecchio = {"opponent": "Clan Nemico", "members": [
        {"tag": "#P1", "name": "Mario", "missed": 1, "attacks": [{"stars": 3, "destr": 100}]},
        {"tag": "#P2", "name": "Luigi", "missed": 1, "attacks": [{"stars": 2, "destr": 60}]}]}
    assert [row["name"] for row in awards.candidates([vecchio])] == ["Mario", "Luigi"]


def test_il_premio_del_capo_finisce_nello_stato_e_nel_riquadro():
    state = challenges.empty()
    given = awards.give(state, "2026-09", "generous", "#P2", "Luigi", 100)
    assert given["category"] == "generous"
    assert state["awards"]["given"][-1]["name"] == "Luigi"
    assert awards.give(state, "2026-09", "inventata", "#P2", "Luigi", 100) is None
    assert "Luigi" in awards.section(IT, state)
    assert badges.of(state, "#P2") == ["premio"]
    assert awards.section(IT, challenges.empty()) is None


def test_il_voto_apre_a_inizio_stagione_e_si_chiude_con_la_finestra_cwl():
    store, bot = FakeStore([war_record_with_triples()]), FakeBot()
    poller, t = tick(store, bot, FIRST)
    asyncio.run(awards.run(poller, t, "2026-09"))
    assert len(bot.polls) == 1
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["awards"]["vote"]["season"] == "2026-09"
    asyncio.run(awards.run(poller, t, None))
    assert len(bot.polls) == 1
    poller, t2 = tick(store, bot, LATER)
    asyncio.run(awards.run(poller, t2, None))
    assert bot.stopped == [1]
    closed = asyncio.run(challenges.load(store, CLAN.alias))
    assert closed["awards"]["vote"] is None
    assert challenges.recent(closed, "vote")


def test_il_voto_spento_non_apre_nulla():
    store, bot = FakeStore([war_record_with_triples()]), FakeBot()
    poller, t = tick(store, bot, FIRST, conf=routed(awards.EVENT_VOTE, "off"))
    asyncio.run(awards.run(poller, t, "2026-09"))
    assert bot.polls == [] and store.state == {}


def vote_answer(poll_id, option, user_id, name):
    return SimpleNamespace(poll_id=poll_id, option_ids=[option],
                           user=SimpleNamespace(id=user_id, first_name=name))


def test_il_voto_annuncia_il_piu_votato_e_gli_da_il_badge():
    store, bot = FakeStore([record_with_targets()]), FakeBot()
    poller, t = tick(store, bot, FIRST)
    asyncio.run(awards.run(poller, t, "2026-09"))
    asyncio.run(polls.record_answer(store, vote_answer("a1", 1, 7, "Alex")))
    asyncio.run(polls.record_answer(store, vote_answer("a1", 1, 8, "Luigi")))
    asyncio.run(polls.record_answer(store, vote_answer("altro", 0, 9, "Toad")))
    poller, t2 = tick(store, bot, LATER)
    asyncio.run(awards.run(poller, t2, None))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(state, "#P3") == ["attacco"]
    assert any("Peach" in riga for riga in boards.lines_of(t2.boards, "challenges"))
    assert challenges.recent(state, "vote")[-1]["winner"] == "#P3"
    assert "poll:a1" not in store.kv


def test_i_badge_dei_traguardi_partono_dal_giro_del_poller():
    store = FakeStore()
    store.state[(CLAN.alias, "players")] = {"tags": {"#P1": player_snapshot(player_json("Mario"))},
                                            "cursor": 0, "out_since": {}}
    coc = FakeCoc({"#P1": player_json("Mario", th=15, stars=500)})
    poller, t = tick(store, FakeBot(), FIRST, coc=coc,
                     conf=routed("challenges.badge", "group"))
    t.members = {"#P1": {"name": "Mario", "role": "member"}}
    asyncio.run(poller.sweep_players(t, per_tick=1))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(state, "#P1") == ["th", "warstars"]
    assert len(boards.lines_of(t.boards, "challenges")) == 1
    asyncio.run(poller.sweep_players(t, per_tick=1))
    assert len(boards.lines_of(t.boards, "challenges")) == 1


def test_col_badge_spento_i_traguardi_restano_nello_stato():
    store = FakeStore()
    store.state[(CLAN.alias, "players")] = {"tags": {"#P1": player_snapshot(player_json("Mario"))},
                                            "cursor": 0, "out_since": {}}
    coc = FakeCoc({"#P1": player_json("Mario", th=15)})
    poller, t = tick(store, FakeBot(), FIRST, coc=coc, conf=routed("challenges.badge", "off"))
    t.members = {"#P1": {"name": "Mario", "role": "member"}}
    asyncio.run(poller.sweep_players(t, per_tick=1))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(state, "#P1") == ["th"]
    assert boards.lines_of(t.boards, "challenges") == []


def test_il_hub_mostra_i_premi_e_il_capo_ha_i_bottoni_di_ogni_categoria():
    store = FakeStore()
    store.state[(CLAN.alias, "settings")] = {"lang": "it", "tz": "Europe/Rome"}
    state = challenges.empty()
    awards.give(state, "2026-09", "generous", "#P2", "Luigi", 100)
    store.state[(CLAN.alias, challenges.KIND)] = state
    text, keyboard = asyncio.run(handlers.build_view("challenges", CLAN, context(store),
                                                     group_update()))
    assert "Luigi" in text
    data = [button for row in rows_of(keyboard) for button in row]
    assert [f"aw:{category}" for category in awards.CATEGORIES] == [d for d in data
                                                                   if d.startswith("aw:")]


def test_il_premio_si_da_in_due_tocchi_e_annuncia():
    store, bot = FakeStore(), FakeBot()
    store.state[(CLAN.alias, "settings")] = {"lang": "it", "tz": "Europe/Rome"}
    store.state[(CLAN.alias, "members")] = {"#P2": {"name": "Luigi", "role": "member"}}
    query = FakeQuery("aw:generous")
    asyncio.run(handlers.on_award_callback(group_update(query), context(store, bot=bot)))
    assert rows_of(keyboard_of(query))[0] == ["aw:generous:#P2"]
    query = FakeQuery("aw:generous:#P2")
    asyncio.run(handlers.on_award_callback(group_update(query), context(store, bot=bot)))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["awards"]["given"][-1]["tag"] == "#P2"
    assert badges.of(state, "#P2") == ["premio"]
    assert bot.sent and bot.sent[0][0] == CLAN.chat_id and "Luigi" in bot.sent[0][1]
    assert query.message.sent == []


def test_il_premio_dato_in_privato_va_dove_dicono_le_destinazioni(monkeypatch):
    monkeypatch.setattr(handlers, "now_utc", lambda: FIRST)
    store, bot = FakeStore(), FakeBot()
    store.state[(CLAN.alias, "settings")] = settings_mod.migrate({"lang": "it", "tz": "Europe/Rome",
                                                                  "quiet": [0, 23]})
    store.state[(CLAN.alias, "members")] = {"#P2": {"name": "Luigi", "role": "member"}}
    query = FakeQuery("aw:generous:#P2")
    asyncio.run(handlers.on_award_callback(group_update(query), context(store, bot=bot)))
    assert bot.sent == [] and query.message.sent == []
    assert "Luigi" in (asyncio.run(store.get_state(CLAN.alias, "queue")) or [""])[0]


def test_col_premio_spento_resta_nell_albo_senza_annuncio():
    store, bot = FakeStore(), FakeBot()
    store.state[(CLAN.alias, "settings")] = settings_mod.migrate({"lang": "it", "tz": "Europe/Rome"})
    store.state[(CLAN.alias, "settings")]["routes"][awards.EVENT_AWARD] = {"to": "off",
                                                                          "intensity": None}
    store.state[(CLAN.alias, "members")] = {"#P2": {"name": "Luigi", "role": "member"}}
    query = FakeQuery("aw:generous:#P2")
    asyncio.run(handlers.on_award_callback(group_update(query), context(store, bot=bot)))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["awards"]["given"][-1]["tag"] == "#P2"
    assert query.message.sent == [] and bot.sent == []


def test_il_voto_sta_nei_limiti_di_telegram_in_tutte_e_venti_le_lingue():
    assert awards.VOTE_OPTIONS <= PollLimit.MAX_OPTION_NUMBER
    for code in i18n.LANGUAGES:
        L = i18n.locale(code)
        question = L.t("vote.question")
        option = L.t("vote.option", name="M" * COC_NAME, stars=3, destr=L.pct(100, 0))
        assert PollLimit.MIN_QUESTION_LENGTH <= len(question) <= PollLimit.MAX_QUESTION_LENGTH, code
        assert 0 < len(option) <= PollLimit.MAX_OPTION_LENGTH, code


def test_i_badge_arrivano_in_me_con_le_due_chiavi():
    state = challenges.empty()
    badges.grant(state, OWNER, "quiz", 100)
    badges.grant(state, "#P1", "premio", 100)
    marks = " ".join(filter(None, (badges.line(IT, state, who) for who in (OWNER, "#P1"))))
    link = SimpleNamespace(tag="#P1", name="Mario", dm=True)
    text = render.me_view(IT, [link], {}, badges_line=marks)
    assert badges.CATALOG["quiz"] in text and badges.CATALOG["premio"] in text
    assert badges.CATALOG["quiz"] not in render.me_view(IT, [link], {})


def test_il_voto_apre_dalla_strada_dei_sondaggi_e_scrive_l_unica_riga_kv():
    store, bot = FakeStore([record_with_targets()]), FakeBot()
    poller, t = tick(store, bot, FIRST)
    asyncio.run(awards.run(poller, t, "2026-09"))
    assert store.kv["poll:a1"] == {"value": {"state": awards.STATE_KEY}, "ref": CLAN.alias}
    assert polls.KEEPERS[awards.STATE_KEY] == (awards.load_poll, awards.save_poll)
    testo = pathlib.Path(awards.__file__).read_text(encoding="utf-8")
    assert "send_poll" not in testo and "stop_poll" not in testo and "kv_set" not in testo
    aperto = asyncio.run(challenges.load(store, CLAN.alias))["awards"]["vote"]
    assert aperto["season"] == "2026-09" and aperto["votes"] == {} and aperto["rows"]
    asyncio.run(polls.record_answer(store, vote_answer("a1", 1, 7, "Alex")))
    votato = asyncio.run(challenges.load(store, CLAN.alias))["awards"]["vote"]
    assert votato["votes"] == {"7": {"name": "Alex", "option": 1}}
    poller, t2 = tick(store, bot, LATER)
    asyncio.run(awards.run(poller, t2, None))
    assert bot.stopped == [1] and "poll:a1" not in store.kv
