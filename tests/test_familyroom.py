import asyncio
import copy
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import console, familyroom, handlers, i18n, render, tournaments, tourney_ui, views
from clashbot import family as family_mod
from clashbot import poller as poller_mod
from clashbot.platform_guard import Buckets
from clashbot.poller import Poller
from test_derby import FakeBot, FakeStore as DerbyStore, FakeSupervisor

IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
TS = int(NOW.timestamp())
FAMILY = SimpleNamespace(alias="fam-1", name="Famiglia", owner_id=7, chat_id=99, bot_alias="bot-1")

ROWS = [
    {"alias": "clan-a", "name": "Alfa", "members": 50, "min_th": 15, "note": "", "level": 12,
     "tag": "#A", "league": None, "chat_id": 1},
    {"alias": "clan-b", "name": "Beta", "members": 30, "min_th": 10, "note": "", "level": 8,
     "tag": "#B", "league": None, "chat_id": 2},
    {"alias": "clan-c", "name": "Gamma", "members": 20, "min_th": 16, "note": "", "level": 20,
     "tag": "#C", "league": None, "chat_id": 3},
]
MEMBERS = {
    "clan-a": {"#P1": {"name": "Piccolo", "th": 11, "role": "member"},
               "#P2": {"name": "Grande", "th": 16, "role": "member"}},
    "clan-b": {"#P3": {"name": "Cresciuto", "th": 16, "role": "member"}},
    "clan-c": {"#P4": {"name": "Giusto", "th": 16, "role": "member"}},
}


FULL = {"alias": "clan-d", "name": "Delta", "members": 50, "min_th": 10, "note": "", "level": 5,
        "tag": "#D", "league": None, "chat_id": 4}
CLANS = [SimpleNamespace(alias=row["alias"], chat_id=row["chat_id"], tag=row["tag"],
                         name=row["name"], bot_alias="bot-1", active=True) for row in ROWS + [FULL]]
STATE = {}
for _row in ROWS + [FULL]:
    STATE[(_row["alias"], "info")] = {"members": _row["members"], "level": _row["level"]}
    STATE[(_row["alias"], "settings")] = {"min_th": _row["min_th"]}
    STATE[(_row["alias"], "members")] = MEMBERS.get(_row["alias"], {})
    STATE[(_row["alias"], views.KIND)] = {views.FAMILY: True}


class FakeStore:
    def __init__(self, kv=None):
        self.kv = dict(kv or {})

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)


class FamilyStore(DerbyStore):
    async def family_clans(self, alias):
        return list(CLANS)

    async def clan_by_alias(self, alias):
        return next((clan for clan in CLANS if clan.alias == alias), None)

    async def live_tournaments(self):
        return [copy.deepcopy(doc) for doc in self.tournaments.values()
                if doc.get("status") != "done" and doc.get("kind") != "derby"]

    async def links_for_players(self, tags):
        return {}

    async def families(self, bot_alias=None):
        return [FAMILY]

    async def family_by_alias(self, alias):
        return FAMILY if alias == FAMILY.alias else None

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

    async def family_by_chat(self, chat_id, bot_alias=None):
        return None

    async def get_secret(self, kind):
        return None

    async def bot_by_alias(self, alias):
        return None


class BoardBot(FakeBot):
    def __init__(self):
        super().__init__()
        self.pinned = []

    async def pin_chat_message(self, chat_id, message_id, **kw):
        self.pinned.append((chat_id, message_id))


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw.get("reply_markup")))


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edited = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edited.append((text, reply_markup))


class RecordingPoller:
    def __init__(self):
        self.sent = []
        self.channel = []

    async def deliver(self, clan, text, event=None, member_tag=None):
        self.sent.append((clan.alias, text, event))

    async def family_deliver(self, family, event, text, conf=None, markup=None):
        self.channel.append((family.alias, text, event))


def private_update(text="", user_id=FAMILY.owner_id, query=None):
    user = SimpleNamespace(id=user_id, language_code="it", first_name="Capo")
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
        effective_user=user,
        effective_message=FakeMessage(text),
        callback_query=query,
    )


def private_context(store, bot=None, poller=None, args=None, user_data=None):
    return SimpleNamespace(
        bot_data={"store": store, "coc": None, "bot_alias": "bot-1",
                  "supervisor": SimpleNamespace(poller=poller)},
        args=args if args is not None else [],
        user_data=user_data if user_data is not None else {},
        bot=bot or BoardBot(),
    )


def sent_to(bot, chat_id):
    return [text for chat, text, _ in bot.sent if chat == chat_id]


def test_gli_annunci_restano_cinque_e_i_piu_recenti_in_testa():
    store = FakeStore()
    for i in range(7):
        asyncio.run(familyroom.push_notice(store, FAMILY, "derby", f"riga {i}", NOW))
    notices = asyncio.run(familyroom.notices_of(store, FAMILY))
    assert len(notices) == familyroom.NOTICE_KEEP
    assert notices[0]["text"] == "riga 6"
    lines = familyroom.notice_lines(IT, notices)
    assert len(lines) == familyroom.NOTICE_KEEP and all("[" not in line for line in lines)


def test_la_bacheca_unica_mette_gli_annunci_sopra_il_reclutamento():
    plain = render.recruit_board(IT, "Europe/Rome", FAMILY, ROWS, NOW)
    withnotices = render.recruit_board(IT, "Europe/Rome", FAMILY, ROWS, NOW, notices=["📣 ciao"])
    assert "📣 ciao" in withnotices and "📣 ciao" not in plain
    assert withnotices.index("📣 ciao") < withnotices.index("Beta")
    assert family_mod.recruit_digest(ROWS) != family_mod.recruit_digest(ROWS, ["📣 ciao"])


def test_gli_spostamenti_suggeriti_usano_solo_i_requisiti_dichiarati():
    rows = familyroom.suggestions(ROWS, MEMBERS)
    by_name = {row["name"]: row for row in rows}
    assert by_name["Piccolo"]["to"] == "Beta" and by_name["Piccolo"]["why"] == "below"
    assert by_name["Cresciuto"]["to"] == "Gamma" and by_name["Cresciuto"]["why"] == "up"
    assert by_name["Grande"]["to"] == "Gamma" and by_name["Grande"]["why"] == "up"
    assert "Giusto" not in by_name
    assert [row["name"] for row in rows] == ["Cresciuto", "Grande", "Piccolo"]
    assert familyroom.suggest_digest(rows) == familyroom.suggest_digest(familyroom.suggestions(ROWS, MEMBERS))
    full = [dict(row, members=50) for row in ROWS]
    assert familyroom.suggestions(full, MEMBERS) == []
    card = familyroom.suggest_card(IT, FAMILY, rows)
    assert "[" not in card and len(card) <= 4000


def test_il_messaggio_del_capo_ha_anteprima_limite_e_card():
    long_text = "a" * (familyroom.MESSAGE_MAX + 50)
    preview = familyroom.preview_card(IT, FAMILY, long_text[:familyroom.MESSAGE_MAX], 3)
    assert "[" not in preview and len(preview) <= 4000
    body = familyroom.message_card(IT, FAMILY, "<b>ciao</b>")
    assert "&lt;b&gt;ciao&lt;/b&gt;" in body
    for row in familyroom.preview_keyboard(IT).inline_keyboard:
        for button in row:
            assert len(button.callback_data.encode()) <= 64


def test_gli_spostamenti_partono_il_lunedi_una_volta_e_solo_ai_clan_toccati():
    store = FamilyStore(state=STATE)
    poller = Poller(FakeSupervisor(BoardBot()), store, None)
    seen = []

    async def deliver(clan, text, event=None, member_tag=None):
        seen.append((clan.alias, text, event))

    poller.deliver = deliver
    asyncio.run(poller.family_suggest(FAMILY, NOW - timedelta(days=1)))
    assert seen == [] and f"fam:{FAMILY.alias}:suggest" not in store.kv
    asyncio.run(poller.family_suggest(FAMILY, NOW))
    assert [row[0] for row in seen] == ["clan-a", "clan-b", "clan-c"]
    assert all(row[2] == "family.suggest" for row in seen)
    assert "Piccolo" in seen[0][1] and "[" not in seen[0][1]
    cards = {row[0]: row[1] for row in seen}
    assert "Grande" in cards["clan-a"] and "Cresciuto" not in cards["clan-a"]
    assert "Cresciuto" in cards["clan-b"] and "Grande" not in cards["clan-b"]
    assert "Cresciuto" in cards["clan-c"] and "Grande" in cards["clan-c"]
    assert "Piccolo" not in cards["clan-c"]
    asyncio.run(poller.family_suggest(FAMILY, NOW))
    assert len(seen) == 3
    asyncio.run(poller.family_suggest(FAMILY, NOW + timedelta(days=7)))
    assert len(seen) == 3
    assert store.kv[f"fam:{FAMILY.alias}:suggest"]["week"] == "2026-W39"


def test_il_derby_finisce_in_bacheca_sopra_il_reclutamento():
    store = FamilyStore(state=STATE)
    bot = BoardBot()
    poller = Poller(FakeSupervisor(bot), store, None)
    asyncio.run(poller.family_derby(FAMILY, NOW))
    notices = store.kv[f"fam:{FAMILY.alias}:notices"]
    assert [row["kind"] for row in notices] == ["derby"]
    bot.sent.clear()
    asyncio.run(poller.family_recruit(FAMILY, NOW))
    board = sent_to(bot, FAMILY.chat_id)[-1]
    assert "🚩" in board and board.index("🚩") < board.index("Beta")
    assert bot.pinned and "[" not in board


def test_la_bacheca_disegna_la_classifica_viva_del_derby():
    store = FamilyStore(state=STATE)
    bot = BoardBot()
    poller = Poller(FakeSupervisor(bot), store, None)
    asyncio.run(poller.family_derby(FAMILY, NOW))
    asyncio.run(poller.family_derby(FAMILY, NOW + timedelta(days=2)))
    alias = store.kv[f"fam:{FAMILY.alias}:derby"]["alias"]
    live = store.tournaments[alias]
    assert live["status"] == "running"
    bot.sent.clear()
    asyncio.run(poller.family_recruit(FAMILY, NOW + timedelta(days=2)))
    board = sent_to(bot, FAMILY.chat_id)[-1]
    assert "🚩" in board and len(board) <= render.MAX_LEN
    for row in tournaments.table(live):
        assert row["name"] in board
    assert board.index("🚩") < board.index("Beta")


def test_il_derby_saltato_non_chiude_e_non_scrive_il_record():
    store = FamilyStore(state=STATE)
    bot = BoardBot()
    poller = Poller(FakeSupervisor(bot), store, None)
    asyncio.run(poller.family_derby(FAMILY, NOW))
    alias = store.kv[f"fam:{FAMILY.alias}:derby"]["alias"]
    assert [row["kind"] for row in store.kv[f"fam:{FAMILY.alias}:notices"]] == ["derby"]
    query = FakeQuery("dy:skip")
    asyncio.run(handlers.on_derby_callback(private_update(query=query),
                                           private_context(store, bot=bot)))
    assert store.tournaments[alias]["status"] == "done"
    assert store.kv[f"fam:{FAMILY.alias}:notices"] == []
    bot.sent.clear()
    asyncio.run(poller.family_derby(FAMILY, NOW + timedelta(days=7)))
    closing = [text for _, text, _ in bot.sent if "DERBY FINITO" in text]
    assert closing == []
    assert f"fam:{FAMILY.alias}:records" not in store.kv


def test_il_capo_non_collegato_comanda_il_derby_dal_privato():
    store = FamilyStore(state=STATE)
    update = private_update(query=FakeQuery("dy:metric:stars"))
    context = private_context(store)
    assert asyncio.run(handlers.derby_family(update, context)) is FAMILY
    stranger = private_update(user_id=FAMILY.owner_id + 1, query=FakeQuery("dy:metric:stars"))
    assert asyncio.run(handlers.derby_family(stranger, context)) is None


def test_il_derby_in_corso_si_punteggia_col_ritmo_della_bacheca():
    store = FamilyStore(state=STATE)
    poller = Poller(FakeSupervisor(BoardBot()), store, None)
    asyncio.run(poller.family_derby(FAMILY, NOW))
    alias = store.kv[f"fam:{FAMILY.alias}:derby"]["alias"]
    asyncio.run(poller.family_derby(FAMILY, NOW + timedelta(days=1)))
    checked = store.kv[f"fam:{FAMILY.alias}:derby"]["checked"]
    saves = len(store.saves)
    asyncio.run(poller.family_derby(FAMILY, NOW + timedelta(days=1, seconds=60)))
    assert store.kv[f"fam:{FAMILY.alias}:derby"]["checked"] == checked
    asyncio.run(poller.family_derby(FAMILY,
                                    NOW + timedelta(days=1, seconds=familyroom.CHECK_EVERY + 1)))
    assert store.kv[f"fam:{FAMILY.alias}:derby"]["checked"] > checked
    assert store.tournaments[alias]["status"] == "running"
    assert len(store.saves) == saves


def test_il_torneo_di_famiglia_scrive_le_iscrizioni_in_bacheca():
    doc = tournaments.empty("clash", "family", "stars", "bracket",
                            TS - 10, TS + 3600, TS + 86400)
    doc.update({"alias": "trn-aaaaaa", "status": "signup", "family_alias": FAMILY.alias})
    for clan in CLANS[:2]:
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    store = FamilyStore(state=STATE)
    store.tournaments[doc["alias"]] = doc
    poller = Poller(FakeSupervisor(BoardBot()), store, None)
    asyncio.run(poller.tournament_jobs(NOW))
    notices = store.kv[f"fam:{FAMILY.alias}:notices"]
    assert [row["kind"] for row in notices] == ["tournament"]
    assert "[" not in notices[0]["text"] and notices[0]["text"]
    asyncio.run(poller.tournament_jobs(NOW))
    assert len(store.kv[f"fam:{FAMILY.alias}:notices"]) == 1


def test_il_vincitore_in_bacheca_tiene_la_e_commerciale_del_suo_nome():
    doc = tournaments.empty("clash", "family", "stars", "bracket",
                            TS - 10, TS + 3600, TS + 86400)
    doc, _ = tournaments.join(doc, "clan", "clan-a", "Fire & Ice")
    winner = doc["entries"][0]["id"]
    store = FakeStore()
    text = tourney_ui.notice(IT, doc, {"type": "final", "winner": winner})
    notices = asyncio.run(familyroom.push_notice(store, FAMILY, "tournament", text, NOW))
    line = familyroom.notice_lines(IT, notices)[0]
    assert "Fire &amp; Ice" in line and "&amp;amp;" not in line


def test_l_annuncio_del_capo_passa_dall_anteprima_e_arriva_a_tutti_i_clan(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    store = FamilyStore(state=STATE)
    store.state[("clan-a", "settings")] = {"min_th": 15, "lang": "it"}
    store.state[("clan-b", "settings")] = {"min_th": 10, "lang": "en"}
    poller = RecordingPoller()
    bot = BoardBot()
    context = private_context(store, bot=bot, poller=poller, args=["annuncio"])
    ask = private_update()
    asyncio.run(handlers.cmd_family(ask, context))
    assert context.user_data["flow"]["kind"] == "famnotice"
    assert str(familyroom.MESSAGE_MAX) in ask.effective_message.sent[-1][0]
    written = private_update("Ci vediamo in guerra")
    asyncio.run(handlers.on_private_text(written, context))
    preview, markup = written.effective_message.sent[-1]
    assert "Ci vediamo in guerra" in preview and "[" not in preview
    assert [button.callback_data for row in markup.inline_keyboard for button in row] == \
        ["fa:send", "fa:cancel"]
    query = FakeQuery("fa:send")
    asyncio.run(handlers.on_family_callback(private_update(query=query), context))
    assert [row[0] for row in poller.sent] == [clan.alias for clan in CLANS]
    assert all(row[2] == "family.notice" for row in poller.sent)
    assert all("Ci vediamo in guerra" in row[1] for row in poller.sent)
    assert "ANNUNCIO" in poller.sent[0][1] and "ANNOUNCEMENT" in poller.sent[1][1]
    assert [row[2] for row in poller.channel] == ["family.notice"]
    assert "ANNUNCIO" in poller.channel[0][1]
    assert [row["kind"] for row in store.kv[f"fam:{FAMILY.alias}:notices"]] == ["message"]
    assert "flow" not in context.user_data
    again = private_update("Secondo annuncio")
    context.user_data["flow"] = {"kind": "famnotice", "family": FAMILY.alias}
    asyncio.run(handlers.on_private_text(again, context))
    assert again.effective_message.sent[-1][0] == IT.t("family.message.too_soon")


class EditBot(BoardBot):
    def __init__(self):
        super().__init__()
        self.edits = []

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append((message_id, text))


def test_la_bacheca_di_famiglia_si_fissa_una_volta_e_poi_si_modifica_sul_posto():
    testo = pathlib.Path(poller_mod.__file__).read_text(encoding="utf-8")
    assert "edit_message_text" not in testo and "pin_chat_message" not in testo
    store = FamilyStore(state=copy.deepcopy(STATE))
    bot = EditBot()
    poller = Poller(FakeSupervisor(bot), store, None)
    asyncio.run(poller.family_recruit(FAMILY, NOW))
    salvata = store.kv[f"fam:{FAMILY.alias}:recruit"]
    assert bot.pinned == [(FAMILY.chat_id, salvata["message_id"])]
    assert len(bot.sent) == 1 and bot.edits == []
    dopo = NOW + timedelta(seconds=familyroom.CHECK_EVERY + 1)
    store.state[("clan-b", "info")] = {"members": 31, "level": 8}
    asyncio.run(poller.family_recruit(FAMILY, dopo))
    assert len(bot.sent) == 1 and len(bot.pinned) == 1
    assert [message_id for message_id, _ in bot.edits] == [salvata["message_id"]]
    aggiornata = store.kv[f"fam:{FAMILY.alias}:recruit"]
    assert aggiornata["message_id"] == salvata["message_id"]
    assert aggiornata["digest"] != salvata["digest"]
    assert aggiornata["checked"] == dopo.timestamp()


def test_la_bacheca_di_famiglia_rispetta_il_tetto_di_messaggi_per_gruppo():
    store = FamilyStore(state=copy.deepcopy(STATE))
    bot = EditBot()
    poller = Poller(FakeSupervisor(bot), store, None)
    while poller.guard.allow(FAMILY.chat_id):
        pass
    asyncio.run(poller.family_recruit(FAMILY, NOW))
    assert bot.sent == [] and bot.pinned == []
    assert store.kv[f"fam:{FAMILY.alias}:recruit"].get("message_id") is None
    poller.guard.buckets = Buckets()
    asyncio.run(poller.family_recruit(FAMILY, NOW + timedelta(seconds=familyroom.CHECK_EVERY + 1)))
    assert len(bot.sent) == 1 and len(bot.pinned) == 1
