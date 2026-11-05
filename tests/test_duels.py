import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import (agenda, badges, boards, challenges, duels, handlers, i18n, scoring,
                      settings as settings_mod)
from clashbot.poller import Poller, Tick

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))

CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
A = {"tag": "#P1", "name": "Mario", "user_id": 7}
B = {"tag": "#P2", "name": "Luigi", "user_id": 9}


def progress_state(gold_a, gold_b):
    return {
        "#P1": {"name": "Mario", "now": {"gold": gold_a, "elixir": 0, "war_stars": 10, "donated": 0,
                                         "capital_gold": 0, "levels": 0}},
        "#P2": {"name": "Luigi", "now": {"gold": gold_b, "elixir": 0, "war_stars": 12, "donated": 0,
                                         "capital_gold": 0, "levels": 0}},
    }


class FakeStore:
    def __init__(self, state=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def kv_get(self, key):
        return None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


class ChatStore(FakeStore):
    def __init__(self, state=None, links=()):
        super().__init__(state)
        self.links = list(links)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def links_for_players(self, tags):
        return {link.tag: link for link in self.links if link.tag in set(tags)}

    async def links_by_user(self, user_id):
        return [link for link in self.links if link.user_id == user_id]


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append((text, reply_markup))


def link_of(who):
    return SimpleNamespace(alias="link-1", user_id=who["user_id"], tag=who["tag"],
                           name=who["name"], dm=True, lang="it")


def chat_update(user_id, query=None):
    return SimpleNamespace(callback_query=query, effective_message=FakeMessage(),
                           effective_chat=SimpleNamespace(id=CLAN.chat_id, type="group"),
                           effective_user=SimpleNamespace(id=user_id, language_code="it"))


def buttons_of(markup):
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


def tick(store, bot, now):
    poller = Poller(SimpleNamespace(bot=lambda alias: bot, running=lambda: [CLAN.bot_alias],
                                    default_alias=CLAN.bot_alias, owner_bot=lambda: bot), store, None)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective({"lang": "it", "tz": "Europe/Rome"}, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.season = scoring.empty_season("2026-09")
    return poller, t


def test_proposta_accettazione_e_un_solo_duello_per_coppia_e_metrica():
    state = challenges.empty()
    duel = duels.propose(state, A, B, "loot", "week", NOW)
    assert duel["status"] == "proposed" and duel["metric"] == "loot"
    assert duels.propose(state, A, B, "loot", "week", NOW) is None
    assert duels.propose(state, A, B, "war_stars", "week", NOW) is not None
    assert duels.accept(state, duel["id"], A["user_id"], progress_state(100, 100), NOW) is None
    started = duels.accept(state, duel["id"], B["user_id"], progress_state(100, 200), NOW)
    assert started["status"] == "open"
    assert started["base"] == {"#P1": 100, "#P2": 200}
    assert started["ends"] == int(NOW.timestamp()) + duels.DURATIONS["week"]


def test_la_proposta_scade_dopo_un_giorno():
    state = challenges.empty()
    duel = duels.propose(state, A, B, "loot", "week", NOW)
    later = NOW + timedelta(seconds=duels.PROPOSAL_TTL + 1)
    assert duels.accept(state, duel["id"], B["user_id"], progress_state(1, 1), later) is None
    assert state["duels"]["open"] == []


def test_senza_contatori_il_duello_aspetta_il_primo_sweep():
    state = challenges.empty()
    duel = duels.propose(state, A, B, "loot", "raid", NOW)
    pending = duels.accept(state, duel["id"], B["user_id"], {"#P1": {"now": {"gold": 5}}}, NOW)
    assert pending["status"] == "pending"
    later = NOW + timedelta(hours=1)
    started = duels.start_pending(state, progress_state(50, 80), later)
    assert started and started[0]["status"] == "open"
    assert started[0]["base"] == {"#P1": 50, "#P2": 80}
    assert started[0]["ends"] == int(later.timestamp()) + duels.DURATIONS["raid"]


def test_il_duello_di_stagione_finisce_quando_finisce_la_stagione():
    state = challenges.empty()
    stagione = int(agenda.season_end(NOW).timestamp())
    duel = duels.propose(state, A, B, "loot", "season", NOW)
    started = duels.accept(state, duel["id"], B["user_id"], progress_state(100, 100), NOW)
    assert started["ends"] == stagione
    assert started["ends"] != int(NOW.timestamp()) + 30 * 86400
    later = NOW + timedelta(days=10)
    other = duels.propose(state, A, B, "war_stars", "season", later)
    pending = duels.accept(state, other["id"], B["user_id"], {"#P1": {"now": {"war_stars": 1}}}, later)
    assert pending["status"] == "pending"
    started_later = duels.start_pending(state, progress_state(1, 1), later + timedelta(hours=1))
    assert started_later[0]["ends"] == stagione


def test_il_verdetto_confronta_i_delta_e_il_pari_non_ha_vincitori():
    state = challenges.empty()
    duel = duels.propose(state, A, B, "loot", "raid", NOW)
    duels.accept(state, duel["id"], B["user_id"], progress_state(100, 100), NOW)
    end = NOW + timedelta(seconds=duels.DURATIONS["raid"] + 60)
    assert duels.due(state, NOW) == []
    assert len(duels.due(state, end)) == 1
    won = duels.verdict(state["duels"]["open"][0], progress_state(900, 300))
    assert won["winner"]["tag"] == "#P1" and won["scores"] == {"#P1": 800, "#P2": 200}
    tied = duels.verdict(state["duels"]["open"][0], progress_state(500, 500))
    assert tied["winner"] is None and tied["scores"] == {"#P1": 400, "#P2": 400}


def test_il_giro_chiude_il_duello_annuncia_e_da_i_punti():
    store, bot = FakeStore(), FakeBot()
    state = challenges.empty()
    duel = duels.propose(state, A, B, "loot", "raid", NOW)
    duels.accept(state, duel["id"], B["user_id"], progress_state(100, 100), NOW)
    asyncio.run(challenges.save(store, CLAN.alias, state))
    end = NOW + timedelta(seconds=duels.DURATIONS["raid"] + 60)
    store.state[(CLAN.alias, "progress")] = progress_state(900, 300)
    poller, t = tick(store, bot, end)
    asyncio.run(duels.run(poller, t))
    assert t.season["play"][str(A["user_id"])]["duels"] == 1
    assert t.season["play"][str(A["user_id"])]["points"] == scoring.WEIGHTS["challenge"]
    assert any("Mario" in line for line in boards.lines_of(t.boards, "challenges"))
    closed = asyncio.run(challenges.load(store, CLAN.alias))
    assert closed["duels"]["open"] == [] and len(closed["duels"]["done"]) == 1
    assert badges.of(closed, A["tag"]) == ["duello"] and badges.of(closed, B["tag"]) == []
    asyncio.run(duels.run(poller, t))
    assert t.season["play"][str(A["user_id"])]["duels"] == 1


def test_col_privato_il_verdetto_arriva_a_tutti_e_due_i_duellanti(monkeypatch):
    store, bot = FakeStore(), FakeBot()
    state = challenges.empty()
    duel = duels.propose(state, A, B, "loot", "raid", NOW)
    duels.accept(state, duel["id"], B["user_id"], progress_state(100, 100), NOW)
    asyncio.run(challenges.save(store, CLAN.alias, state))
    store.state[(CLAN.alias, "progress")] = progress_state(900, 300)
    poller, t = tick(store, bot, NOW + timedelta(seconds=duels.DURATIONS["raid"] + 60))
    monkeypatch.setattr(duels, "route", lambda conf, event: ("member_dm", None))
    sent = []

    async def fake_dispatch(tick_, event, text, member_tag=None):
        sent.append(member_tag)

    monkeypatch.setattr(poller, "dispatch", fake_dispatch)
    asyncio.run(duels.run(poller, t))
    assert sent == [A["tag"], B["tag"]]


def test_una_riga_rotta_nello_stato_non_ferma_i_duelli():
    store, bot = FakeStore(), FakeBot()
    state = challenges.ensure({"duels": {"open": [{"id": "d1"}], "done": []}})
    assert state["duels"]["open"] == [{"id": "d1"}]
    assert duels.section(i18n.locale("it"), state) is None
    assert duels.due(state, NOW) == []
    assert duels.start_pending(state, progress_state(1, 1), NOW) == []
    assert duels.accept(state, "d1", B["user_id"], progress_state(1, 1), NOW) is None
    assert duels.propose(state, A, B, "loot", "week", NOW) is not None
    asyncio.run(challenges.save(store, CLAN.alias, state))
    poller, t = tick(store, bot, NOW)
    asyncio.run(duels.run(poller, t))
    assert [duel["id"] for duel in asyncio.run(challenges.load(store, CLAN.alias))["duels"]["open"]] \
        == [state["duels"]["open"][-1]["id"]]


def test_senza_niente_da_fare_il_giro_non_riscrive_lo_stato():
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot, NOW)
    asyncio.run(duels.run(poller, t))
    assert (CLAN.alias, challenges.KIND) not in store.state


def test_il_riquadro_del_hub_elenca_i_duelli_aperti():
    IT = i18n.locale("it")
    state = challenges.empty()
    assert duels.section(IT, state) is None
    duel = duels.propose(state, A, B, "war_stars", "week", NOW)
    duels.accept(state, duel["id"], B["user_id"], progress_state(1, 1), NOW)
    text = duels.section(IT, state)
    assert "Mario" in text and "Luigi" in text


def test_il_comando_duello_e_i_bottoni_sono_registrati():
    assert ("duel", ["duello", "sfida"]) in handlers.COMMANDS
    assert handlers.HANDLERS["duel"] is duels.cmd_duel
    assert "cmd.duel" in EN
    for metric in duels.METRICS:
        assert i18n.locale("it").t(f"duel.metric.{metric}") != f"[duel.metric.{metric}]"
    for duration in duels.DURATION_KEYS:
        assert i18n.locale("it").t(f"duel.duration.{duration}") != f"[duel.duration.{duration}]"
    keyboard = duels.wizard_keyboard(i18n.locale("it"), {"step": "duration"}, [])
    assert [data for _, data in buttons_of(keyboard) if data.startswith("d:duration:")] \
        == [f"d:duration:{key}" for key in duels.DURATION_KEYS]


def duel_context(store):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": CLAN.bot_alias},
                           user_data={})


def wizard_store():
    return ChatStore({(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"},
                      (CLAN.alias, "members"): {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}},
                      (CLAN.alias, "progress"): progress_state(10, 20)},
                     links=[link_of(A), link_of(B)])


def test_il_comando_apre_la_scelta_del_rivale_e_non_offre_se_stessi():
    store = wizard_store()
    context = duel_context(store)
    update = chat_update(A["user_id"])
    asyncio.run(duels.cmd_duel(update, context))
    text, markup = update.effective_message.replies[-1]
    assert text == i18n.locale("it").t("duel.ask_who")
    assert ("Luigi", "d:who:#P2") in buttons_of(markup)
    assert not any(data == "d:who:#P1" for _, data in buttons_of(markup))
    assert context.user_data[duels.FLOW] == {"step": "who"}


def test_il_giro_dei_bottoni_propone_e_solo_lo_sfidato_accetta():
    store = wizard_store()
    context = duel_context(store)
    for data, ask in (("d:who:#P2", "metric"), ("d:metric:loot", "duration")):
        update = chat_update(A["user_id"], FakeQuery(data))
        asyncio.run(duels.on_duel_callback(update, context))
        assert update.callback_query.edits[-1][0] == i18n.locale("it").t(f"duel.ask_{ask}")
    update = chat_update(A["user_id"], FakeQuery("d:duration:week"))
    asyncio.run(duels.on_duel_callback(update, context))
    text, markup = update.callback_query.edits[-1]
    assert "Mario" in text and "Luigi" in text
    assert duels.FLOW not in context.user_data
    open_duels = asyncio.run(challenges.load(store, CLAN.alias))["duels"]["open"]
    assert len(open_duels) == 1 and open_duels[0]["status"] == "proposed"
    accept_data = buttons_of(markup)[0][1]
    assert accept_data == f"d:accept:{open_duels[0]['id']}"
    wrong = chat_update(A["user_id"], FakeQuery(accept_data))
    asyncio.run(duels.on_duel_callback(wrong, duel_context(store)))
    assert wrong.callback_query.answers[-1][1] is True and wrong.callback_query.edits == []
    right = chat_update(B["user_id"], FakeQuery(accept_data))
    asyncio.run(duels.on_duel_callback(right, duel_context(store)))
    assert "Mario" in right.callback_query.edits[-1][0]
    started = asyncio.run(challenges.load(store, CLAN.alias))["duels"]["open"][0]
    assert started["status"] == "open" and started["base"] == {"#P1": 10, "#P2": 20}


def test_il_hub_delle_sfide_mostra_i_duelli_aperti():
    store = FakeStore({(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"}})
    state = challenges.empty()
    duel = duels.propose(state, A, B, "loot", "week", NOW)
    duels.accept(state, duel["id"], B["user_id"], progress_state(1, 1), NOW)
    asyncio.run(challenges.save(store, CLAN.alias, state))
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": CLAN.bot_alias})
    text, _ = asyncio.run(handlers.build_view("challenges", CLAN, context))
    assert "Mario" in text and "Luigi" in text
