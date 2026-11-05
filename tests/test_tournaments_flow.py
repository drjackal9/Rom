import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import boards, events_registry, handlers, i18n, tourney_ui, tournaments
from clashbot.poller import Poller

NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
TS = int(NOW.timestamp())
IT = i18n.locale("it")
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro",
                       bot_alias="bot-1", active=True)
SISTER = SimpleNamespace(alias="clan-2", chat_id=202, tag="#CLAN2", name="Sorella",
                         bot_alias="bot-1", active=True)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))


class FakeSupervisor:
    def __init__(self, bot):
        self._bot = bot
        self.default_alias = "bot-1"

    def bot(self, alias):
        return self._bot

    def running(self):
        return ["bot-1"]


class FakeQuery:
    def __init__(self):
        self.from_user = SimpleNamespace(id=7)
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)


class FakeStore:
    def __init__(self, docs=(), state=None, family=None, network=None, clans=(CLAN,)):
        self.docs = {doc["alias"]: copy.deepcopy(doc) for doc in docs}
        self.state = dict(state or {})
        self.saved = []
        self.family = family
        self.network = network
        self.clans = list(clans)

    async def family_of_clan(self, clan_alias):
        return self.family

    async def family_clans(self, family_alias):
        return list(self.clans)

    async def network_get(self, clan_alias):
        return copy.deepcopy(self.network)

    async def links_by_user(self, user_id):
        return []

    async def create_tournament(self, doc, owner_id, family_alias=None, clan_alias=None):
        alias = f"trn-{len(self.docs):06d}"
        doc = copy.deepcopy(doc)
        doc.update({"alias": alias, "status": "signup",
                    "family_alias": family_alias, "clan_alias": clan_alias})
        self.docs[alias] = doc
        return alias

    async def tournament(self, alias):
        return copy.deepcopy(self.docs.get(alias))

    async def tournaments_for(self, family_alias=None, clan_alias=None, status=None, scope=None):
        return [copy.deepcopy(doc) for doc in self.docs.values()
                if doc.get("kind") != "derby"
                and (family_alias is None or doc.get("family_alias") == family_alias)
                and (clan_alias is None or doc.get("clan_alias") == clan_alias)
                and (status is None or doc.get("status") == status)
                and (scope is None or doc.get("scope") == scope)]

    async def live_tournaments(self):
        return [copy.deepcopy(doc) for doc in self.docs.values()
                if doc.get("status") != "done" and doc.get("kind") != "derby"]

    async def save_tournament(self, alias, doc, status=None):
        doc = copy.deepcopy(doc)
        doc["status"] = status or self.docs[alias].get("status")
        doc["alias"] = alias
        doc["family_alias"] = self.docs[alias].get("family_alias")
        doc["clan_alias"] = self.docs[alias].get("clan_alias")
        self.docs[alias] = doc
        self.saved.append((alias, doc["status"]))

    async def clan_by_alias(self, alias):
        return next((clan for clan in self.clans if clan.alias == alias), None)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def links_for_players(self, tags):
        return {}

    async def wars_since(self, alias, since):
        return []


def poller_with(store, bot):
    return Poller(FakeSupervisor(bot), store, None)


def test_il_registro_dichiara_i_dodici_eventi_nuovi():
    for name in ("family.derby.open", "family.derby.end", "family.notice", "family.suggest"):
        assert events_registry.EVENTS[name]["pack"] == "family"
    assert events_registry.EVENTS["family.suggest"]["default"] == "leaders_dm"
    for name in tournaments.NAMES:
        assert events_registry.EVENTS[f"family.tournament.{name}"]["pack"] == "family"
        assert events_registry.EVENTS[f"challenges.tournament.{name}"]["pack"] == "challenges"
        assert events_registry.EVENTS[f"family.tournament.{name}"]["default"] == "group"


def test_lo_scopo_decide_il_tipo_e_il_pacchetto():
    state = tourney_ui.handle(tourney_ui.new_state("clan"), "tr:scope:family")
    assert (state["scope"], state["kind"]) == ("family", "clash")
    state = tourney_ui.handle(state, "tr:metric:loot")
    assert state["metric"] == "loot"
    state = tourney_ui.handle(state, "tr:scope:network")
    assert (state["scope"], state["kind"], state["metric"]) == ("network", "clash", "stars")
    assert tourney_ui.handle(state, "tr:scope:galassia")["scope"] == "network"
    back = tourney_ui.handle(state, "tr:scope:clan")
    assert (back["scope"], back["kind"]) == ("clan", "internal")
    assert "[" not in tourney_ui.open_view(IT, back)


def test_la_creazione_a_bottoni_non_accetta_valori_fuori_elenco():
    state = tourney_ui.new_state("clan")
    assert state["kind"] == "internal"
    state = tourney_ui.handle(state, "tr:metric:loot")
    state = tourney_ui.handle(state, "tr:size:8")
    state = tourney_ui.handle(state, "tr:format:groups")
    state = tourney_ui.handle(state, "tr:window:604800")
    assert (state["metric"], state["size"], state["format"], state["window"]) == ("loot", 8, "groups", 604800)
    same = tourney_ui.handle(dict(state), "tr:metric:oro-vero")
    assert same["metric"] == "loot"
    assert tourney_ui.handle(dict(state), "tr:size:7")["size"] == 8
    doc = tourney_ui.to_doc(state, NOW)
    assert doc["starts"] == TS + tournaments.SIGNUP_WINDOW
    assert doc["ends"] == doc["starts"] + 604800
    assert doc["scope"] == "clan" and doc["metric"] == "loot"


def test_le_card_restano_sotto_il_limite_di_telegram():
    doc = tournaments.empty("clash", "family", "stars", "bracket", TS, TS + 10, TS + 20, size=32)
    for i in range(32):
        doc, _ = tournaments.join(doc, "clan", f"clan-{i}", f"Clan numero {i} con un nome lungo")
    doc["alias"] = "trn-aaaaaa"
    doc = tournaments.make_bracket(doc)
    text = tourney_ui.view(IT, doc, NOW)
    assert len(text) <= 4000
    assert "[" not in text
    keyboard = tourney_ui.keyboard(IT, doc, joined=False, manage=True)
    for row in keyboard.inline_keyboard:
        for button in row:
            assert len(button.callback_data.encode()) <= 64


def test_gli_annunci_esistono_per_ogni_evento():
    doc = tournaments.make_bracket({**tournaments.empty("clash", "family", "stars", "bracket", TS, TS, TS + 20),
                                    "alias": "trn-bbbbbb",
                                    "entries": [{"id": "c:a", "type": "clan", "ref": "clan-1", "name": "Futuro"},
                                                {"id": "c:b", "type": "clan", "ref": "clan-2", "name": "Altri"}]})
    for event in ({"type": "signup"}, {"type": "round", "index": 0},
                  {"type": "final", "winner": "c:a"}, {"type": "empty"}):
        text = tourney_ui.announcement(IT, doc, event)
        assert text and "[" not in text


def test_il_poller_fa_avanzare_annuncia_una_volta_sola_e_salva():
    doc = tournaments.empty("clash", "family", "stars", "bracket", TS - 10, TS - 5, TS + 86400)
    doc["alias"] = "trn-cccccc"
    doc["status"] = "signup"
    doc["family_alias"] = "fam-1"
    doc["clan_alias"] = None
    for ref, name in (("clan-1", "Futuro"), ("clan-9", "Altri")):
        doc, _ = tournaments.join(doc, "clan", ref, name)
    store = FakeStore([doc], state={(CLAN.alias, "settings"): {"version": 2}})
    bot = FakeBot()
    poller = poller_with(store, bot)
    asyncio.run(poller.tournament_jobs(NOW))
    assert bot.sent == [] and len(section(store, CLAN, "family")) == 1
    assert store.saved[-1][1] == "running"
    asyncio.run(poller.tournament_jobs(NOW))
    assert len(section(store, CLAN, "family")) == 1
    settled = len(store.saved)
    asyncio.run(poller.tournament_jobs(NOW))
    assert len(section(store, CLAN, "family")) == 1
    assert len(store.saved) == settled
    assert {status for _, status in store.saved} == {"running"}


def test_il_giro_dei_tornei_lascia_stare_il_derby():
    doc = tournaments.empty("derby", "family", "both", "table", TS - 10, TS - 5, TS + 86400)
    doc["alias"] = "trn-dddddd"
    doc["status"] = "signup"
    doc["family_alias"] = "fam-1"
    doc["clan_alias"] = None
    for ref, name in (("clan-1", "Futuro"), ("clan-9", "Altri"), ("clan-7", "Terzi")):
        doc, _ = tournaments.join(doc, "clan", ref, name)
    store = FakeStore([doc])
    bot = FakeBot()
    poller = poller_with(store, bot)
    asyncio.run(poller.tournament_jobs(NOW))
    assert bot.sent == []
    assert store.saved == []
    assert len(store.docs["trn-dddddd"]["entries"]) == 3


def section(store, clan, pack):
    return boards.lines_of(store.state.get((clan.alias, "boards")), pack)


def test_deliver_rispetta_la_destinazione_spenta():
    store = FakeStore(state={(CLAN.alias, "settings"): {"packs": {"family": False}}})
    bot = FakeBot()
    poller = poller_with(store, bot)
    asyncio.run(poller.deliver(CLAN, "ciao", "family.tournament.round"))
    assert section(store, CLAN, "family") == []
    asyncio.run(poller.deliver(CLAN, "ciao", "challenges.tournament.round"))
    assert [text[-4:] for text in section(store, CLAN, "challenges")] == ["ciao"]
    assert bot.sent == []


def test_deliver_non_consegna_fuori_dal_registro():
    store = FakeStore(state={(CLAN.alias, "settings"): {"version": 2}})
    bot = FakeBot()
    poller = poller_with(store, bot)
    asyncio.run(poller.deliver(CLAN, "ciao", "famiglia.inventata"))
    asyncio.run(poller.deliver(CLAN, "ciao", None))
    assert bot.sent == [] and section(store, CLAN, "family") == []
    asyncio.run(poller.deliver(CLAN, "ciao", "family.tournament.round"))
    assert [text[-4:] for text in section(store, CLAN, "family")] == ["ciao"]


def test_un_clan_solo_apre_la_sfida_di_rete_e_la_ritrova():
    store = FakeStore(network={"visible": True, "named": True})
    query = FakeQuery()
    context = SimpleNamespace(user_data={"tourney": tourney_ui.new_state("network")})
    asyncio.run(handlers.open_tournament(query, context, store, CLAN, IT,
                                         tourney_ui.new_state("network"), True))
    assert query.answers == [IT.t("tournament.opened")]
    doc = list(store.docs.values())[0]
    assert (doc["scope"], doc["family_alias"], doc["clan_alias"]) == ("network", None, CLAN.alias)
    assert [row["alias"] for row in asyncio.run(handlers.clan_tournaments(store, CLAN))] == [doc["alias"]]
    assert asyncio.run(handlers.tournament_entry(store, CLAN, doc, query.from_user)) == (
        "clan", CLAN.alias, CLAN.name)
    poller = poller_with(store, FakeBot())
    assert [clan.alias for clan in asyncio.run(poller.tournament_clans(doc))] == [CLAN.alias]


def test_senza_famiglia_cade_solo_l_ambito_famiglia():
    store = FakeStore()
    query = FakeQuery()
    context = SimpleNamespace(user_data={})
    asyncio.run(handlers.open_tournament(query, context, store, CLAN, IT,
                                         tourney_ui.new_state("family"), True))
    assert query.answers == [IT.t("tournament.no_family")]
    asyncio.run(handlers.open_tournament(query, context, store, CLAN, IT,
                                         tourney_ui.new_state("network"), True))
    assert query.answers[-1] == IT.t("tournament.no_network")
    assert store.docs == {}


def test_con_la_famiglia_il_torneo_resta_appeso_alla_famiglia():
    store = FakeStore(family=SimpleNamespace(alias="fam-1"), network={"visible": True})
    query = FakeQuery()
    context = SimpleNamespace(user_data={})
    for scope in ("family", "network"):
        asyncio.run(handlers.open_tournament(query, context, store, CLAN, IT,
                                             tourney_ui.new_state(scope), True))
    anchors = {(doc["scope"], doc["family_alias"], doc["clan_alias"]) for doc in store.docs.values()}
    assert anchors == {("family", "fam-1", None), ("network", "fam-1", None)}
    assert len(asyncio.run(handlers.clan_tournaments(store, CLAN))) == 2


def test_il_torneo_fra_membri_iscrive_il_membro():
    store = FakeStore()
    query = FakeQuery()
    context = SimpleNamespace(user_data={})
    asyncio.run(handlers.open_tournament(query, context, store, CLAN, IT,
                                         tourney_ui.new_state("clan"), True))
    doc = list(store.docs.values())[0]
    assert (doc["scope"], doc["family_alias"], doc["clan_alias"]) == ("clan", None, CLAN.alias)
    assert asyncio.run(handlers.tournament_entry(store, CLAN, doc, query.from_user)) == (
        "member", None, None)


def test_le_iscrizioni_di_famiglia_bussano_a_tutti_i_clan_della_famiglia():
    doc = tournaments.empty("clash", "family", "stars", "bracket", TS - 10, TS + 3600, TS + 86400)
    doc.update({"alias": "trn-eeeeee", "status": "signup", "family_alias": "fam-1",
                "clan_alias": None, "origin": CLAN.alias})
    store = FakeStore([doc], state={(CLAN.alias, "settings"): {"version": 2},
                                    (SISTER.alias, "settings"): {"version": 2}},
                      clans=[CLAN, SISTER])
    bot = FakeBot()
    poller = poller_with(store, bot)
    assert doc["entries"] == []
    asyncio.run(poller.tournament_jobs(NOW))
    assert bot.sent == []
    assert len(section(store, CLAN, "family")) == 1 and len(section(store, SISTER, "family")) == 1


def test_il_clan_che_apre_resta_fra_i_destinatari():
    doc = tournaments.empty("clash", "family", "stars", "bracket", TS - 10, TS + 3600, TS + 86400)
    doc.update({"alias": "trn-gggggg", "status": "signup", "family_alias": "fam-1",
                "clan_alias": None, "origin": CLAN.alias})
    store = FakeStore([doc], clans=[CLAN, SISTER])

    async def only_sister(family_alias):
        return [SISTER]

    store.family_clans = only_sister
    poller = poller_with(store, FakeBot())
    assert [clan.alias for clan in asyncio.run(poller.tournament_clans(doc))] == [
        CLAN.alias, SISTER.alias]


def test_chi_apre_un_torneo_resta_scritto_nel_documento():
    store = FakeStore(network={"visible": True})
    query = FakeQuery()
    context = SimpleNamespace(user_data={})
    asyncio.run(handlers.open_tournament(query, context, store, CLAN, IT,
                                         tourney_ui.new_state("network"), True))
    doc = list(store.docs.values())[0]
    assert doc["origin"] == CLAN.alias
    assert tournaments.ensure(doc)["origin"] == CLAN.alias


def test_un_torneo_di_rete_si_trova_anche_dagli_altri_clan():
    doc = tournaments.empty("clash", "network", "stars", "bracket", TS - 10, TS + 3600, TS + 86400)
    doc.update({"alias": "trn-ffffff", "status": "signup", "family_alias": "fam-9",
                "clan_alias": None, "origin": "clan-9"})
    store = FakeStore([doc], network={"visible": True})
    assert [row["alias"] for row in asyncio.run(handlers.clan_tournaments(store, CLAN))] == [
        "trn-ffffff"]
    store.network = {"visible": False}
    assert asyncio.run(handlers.clan_tournaments(store, CLAN)) == []
    store.network = {"visible": True}
    store.docs["trn-ffffff"]["status"] = "done"
    assert asyncio.run(handlers.clan_tournaments(store, CLAN)) == []


def test_il_comando_torneo_e_i_callback_sono_registrati():
    assert ("tournament", ["torneo"]) in handlers.COMMANDS
    assert handlers.HANDLERS["tournament"] is handlers.cmd_tournament
    app = SimpleNamespace(handlers=[], add_handler=lambda h: app.handlers.append(h))
    handlers.register(app)
    patterns = [getattr(h, "pattern", None) and h.pattern.pattern for h in app.handlers]
    assert "^tr:" in patterns
