import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import (boards, derby, family as family_mod, i18n, progress as progress_mod,
                      tournaments, views)
from clashbot.poller import Poller

IT = i18n.locale("it")
MONDAY = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
A = SimpleNamespace(alias="clan-a", chat_id=1, tag="#A", name="Alfa", bot_alias="bot-1", active=True)
B = SimpleNamespace(alias="clan-b", chat_id=2, tag="#B", name="Beta", bot_alias="bot-1", active=True)
FAMILY = SimpleNamespace(alias="fam-1", name="Famiglia", owner_id=7, chat_id=99, bot_alias="bot-1")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))
        return SimpleNamespace(message_id=len(self.sent))


class FakeSupervisor:
    def __init__(self, bot):
        self._bot = bot
        self.default_alias = "bot-1"

    def bot(self, alias):
        return self._bot

    def running(self):
        return ["bot-1"]


class FakeStore:
    def __init__(self, state=None, wars=None, kv=None):
        self.state = dict(state or {})
        self.wars = dict(wars or {})
        self.kv = dict(kv or {})
        self.tournaments = {}
        self.saves = []

    async def family_clans(self, alias):
        return [A, B]

    async def links_by_user(self, user_id):
        return []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def wars_since(self, alias, since):
        return [copy.deepcopy(r) for r in self.wars.get(alias, [])]

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def create_tournament(self, doc, owner_id, family_alias=None, clan_alias=None):
        alias = f"trn-{len(self.tournaments) + 1:06d}"
        doc = copy.deepcopy(doc)
        doc.update({"alias": alias, "status": "signup", "family_alias": family_alias,
                    "clan_alias": clan_alias})
        self.tournaments[alias] = doc
        return alias

    async def save_tournament(self, alias, doc, status=None):
        self.saves.append(alias)
        stored = self.tournaments[alias]
        doc = copy.deepcopy(doc)
        doc.update({"alias": alias, "status": status or stored.get("status"),
                    "family_alias": stored.get("family_alias"),
                    "clan_alias": stored.get("clan_alias")})
        self.tournaments[alias] = doc

    async def tournament(self, alias):
        return copy.deepcopy(self.tournaments.get(alias))


def store_with_activity():
    return FakeStore(state={
        ("clan-a", "progress"): {"#P1": {"name": "M", "now": {"wins": 40}, "week": {"since": 0, "wins": 0}}},
        ("clan-a", "info"): {"members": 1},
        ("clan-a", views.KIND): {views.FAMILY: True},
        ("clan-b", "progress"): {"#P9": {"name": "L", "now": {"wins": 10}, "week": {"since": 0, "wins": 0}}},
        ("clan-b", "info"): {"members": 1},
        ("clan-b", views.KIND): {views.FAMILY: True},
    })


PREV_MONDAY = MONDAY - timedelta(days=7)
SUNDAY = MONDAY - timedelta(hours=21)


def wins_over_monday(before, after):
    stored = progress_mod.update({}, "#P1", "Mario", {"wins": 0}, PREV_MONDAY, "UTC")
    stored = progress_mod.update(stored, "#P1", "Mario", {"wins": before}, SUNDAY, "UTC")
    return progress_mod.update(stored, "#P1", "Mario", {"wins": before + after}, MONDAY, "UTC")


def test_l_attivita_della_settimana_non_si_azzera_al_lunedi():
    store = FakeStore(state={("clan-a", "progress"): wins_over_monday(40, 2),
                             ("clan-a", "info"): {"members": 1}})
    fresh = asyncio.run(family_mod.clan_activity(store, A))
    whole = asyncio.run(family_mod.clan_activity(store, A, start=int(PREV_MONDAY.timestamp())))
    assert fresh == 2.0
    assert whole == 42.0


def test_il_derby_chiude_sulla_settimana_e_non_sulle_ore_del_lunedi():
    store = FakeStore(state={("clan-a", "progress"): wins_over_monday(40, 2),
                             ("clan-a", "info"): {"members": 1},
                             ("clan-a", views.KIND): {views.FAMILY: True},
                             ("clan-b", "progress"): wins_over_monday(10, 1),
                             ("clan-b", "info"): {"members": 1},
                             ("clan-b", views.KIND): {views.FAMILY: True}})
    doc = asyncio.run(derby.build(store, FAMILY, PREV_MONDAY, "UTC"))
    doc = derby.apply(doc, "dy:metric:activity")
    assert doc["ends"] == int(MONDAY.timestamp())
    doc = asyncio.run(derby.scores(store, FAMILY, doc, MONDAY))
    assert [(row["name"], row["value"]) for row in tournaments.table(doc)] == [
        ("Alfa", 420), ("Beta", 110)]


def test_il_bot_propone_il_derby_con_tutti_i_clan_e_la_settimana_giusta():
    store = store_with_activity()
    doc = asyncio.run(derby.build(store, FAMILY, MONDAY, "Europe/Rome"))
    assert doc["kind"] == "derby" and doc["scope"] == "family" and doc["format"] == "table"
    assert [entry["ref"] for entry in doc["entries"]] == ["clan-a", "clan-b"]
    assert doc["metric"] == "both"
    assert doc["week"] == "2026-W38"
    assert doc["starts"] == int(MONDAY.timestamp()) + derby.AUTO_START
    assert doc["ends"] == derby.week_end(MONDAY, "Europe/Rome")


def test_il_capo_cambia_metrica_toglie_e_rimette_un_clan():
    store = store_with_activity()
    doc = asyncio.run(derby.build(store, FAMILY, MONDAY, "Europe/Rome"))
    doc = derby.apply(doc, "dy:metric:stars")
    assert doc["metric"] == "stars"
    doc = derby.apply(doc, "dy:metric:oro")
    assert doc["metric"] == "stars"
    doc = derby.apply(doc, f"dy:drop:{tournaments.entry_id('clan', 'clan-b')}")
    assert [entry["ref"] for entry in doc["entries"]] == ["clan-a"]
    doc = derby.apply(doc, "dy:go")
    assert doc["starts"] <= int(MONDAY.timestamp())


def test_le_posizioni_si_sommano_quando_la_metrica_e_entrambe():
    store = store_with_activity()
    store.wars = {"clan-a": [{"result": "win", "stars": 30, "destr": 95.0, "members": []}],
                  "clan-b": [{"result": "lose", "stars": 10, "destr": 60.0, "members": []}]}
    doc = asyncio.run(derby.build(store, FAMILY, MONDAY, "Europe/Rome"))
    doc = asyncio.run(derby.scores(store, FAMILY, doc, MONDAY))
    rows = tournaments.table(doc)
    assert [row["name"] for row in rows] == ["Alfa", "Beta"]
    assert rows[0]["value"] == 2 and rows[1]["value"] == 0
    only_stars = asyncio.run(derby.scores(store, FAMILY, derby.apply(doc, "dy:metric:stars"), MONDAY))
    assert tournaments.table(only_stars)[0]["value"] == 30


def test_la_missione_e_il_record_della_famiglia():
    first = derby.mission_of({}, "stars", 40)
    assert first["goal"] == 0 and first["best"] == 0 and first["value"] == 40 and first["hit"] is True
    later = derby.mission_of({"stars": 60}, "stars", 40)
    assert later["goal"] == 60 and later["hit"] is False
    beaten = derby.mission_of({"stars": 60}, "stars", 61)
    assert beaten["hit"] is True


def test_la_prima_settimana_senza_storia_dice_che_e_la_prima_misura():
    first = derby.mission_of({}, "stars", 40)
    assert first["first"] is True
    record_a_zero = derby.mission_of({"stars": 0}, "stars", 0)
    assert record_a_zero["first"] is False and record_a_zero["hit"] is True
    store = store_with_activity()
    doc = asyncio.run(derby.build(store, FAMILY, MONDAY, "Europe/Rome"))
    doc = asyncio.run(derby.scores(store, FAMILY, doc, MONDAY))
    doc["mission"] = first
    running = derby.view(IT, FAMILY, doc, False)
    ending = derby.end_card(IT, FAMILY, doc)
    assert IT.t("derby.mission.first", value=IT.n(40)) in running
    assert IT.t("derby.end.mission.first", value=IT.n(40)) in ending
    assert IT.t("derby.end.mission.hit", value=IT.n(40), goal=IT.n(0)) not in ending
    doc["mission"] = record_a_zero
    assert IT.t("derby.end.mission.first", value=IT.n(0)) not in derby.end_card(IT, FAMILY, doc)


def test_le_card_del_derby_parlano_italiano():
    store = store_with_activity()
    doc = asyncio.run(derby.build(store, FAMILY, MONDAY, "Europe/Rome"))
    doc = asyncio.run(derby.scores(store, FAMILY, doc, MONDAY))
    doc["mission"] = derby.mission_of({"both": 3}, doc["metric"], 2)
    proposal = derby.view(IT, FAMILY, doc, True)
    running = derby.view(IT, FAMILY, doc, False)
    ending = derby.end_card(IT, FAMILY, doc)
    for text in (proposal, running, ending):
        assert "[" not in text and len(text) <= 4000
    for row in derby.keyboard(IT, doc).inline_keyboard:
        for button in row:
            assert len(button.callback_data.encode()) <= 64


def test_a_meta_settimana_il_derby_resta_in_corso_e_non_si_riscrive_da_solo():
    store = store_with_activity()
    store.wars = {"clan-a": [{"result": "win", "stars": 30, "destr": 95.0, "members": []}],
                  "clan-b": [{"result": "lose", "stars": 10, "destr": 60.0, "members": []}]}
    poller = Poller(FakeSupervisor(FakeBot()), store, None)
    asyncio.run(poller.family_derby(FAMILY, MONDAY))
    alias = store.kv[f"fam:{FAMILY.alias}:derby"]["alias"]
    asyncio.run(poller.family_derby(FAMILY, MONDAY + timedelta(days=3)))
    asyncio.run(poller.family_derby(FAMILY, MONDAY + timedelta(days=4)))
    live = store.tournaments[alias]
    assert len(store.tournaments) == 1 and live["status"] == "running"
    assert tournaments.table(live)[0]["value"] == 2
    assert store.saves == [alias]
    assert f"fam:{FAMILY.alias}:records" not in store.kv


def test_ogni_lunedi_ha_il_suo_derby_senza_settimane_morte():
    store = store_with_activity()
    store.wars = {"clan-a": [{"result": "win", "stars": 30, "destr": 95.0, "members": []}],
                  "clan-b": [{"result": "lose", "stars": 10, "destr": 60.0, "members": []}]}
    poller = Poller(FakeSupervisor(FakeBot()), store, None)
    seen = []
    for week in range(3):
        asyncio.run(poller.family_derby(FAMILY, MONDAY + timedelta(days=7 * week)))
        saved = store.kv[f"fam:{FAMILY.alias}:derby"]
        live = store.tournaments[saved["alias"]]
        seen.append((saved["week"], live["week"], live["status"], len(store.tournaments)))
    assert seen == [("2026-W38", "2026-W38", "signup", 1),
                    ("2026-W39", "2026-W39", "signup", 2),
                    ("2026-W40", "2026-W40", "signup", 3)]
    assert sorted(doc["status"] for doc in store.tournaments.values()) == ["done", "done", "signup"]
    assert store.kv[f"fam:{FAMILY.alias}:records"]["both"] > 0


def sezione(store, clan):
    return boards.lines_of(store.state.get((clan.alias, "boards")), "family")


def test_la_proposta_arriva_nel_canale_di_famiglia_coi_bottoni():
    store = store_with_activity()
    bot = FakeBot()
    poller = Poller(FakeSupervisor(bot), store, None)
    asyncio.run(poller.family_derby(FAMILY, MONDAY))
    private = [sent for sent in bot.sent if sent[0] == FAMILY.owner_id]
    channel = [sent for sent in bot.sent if sent[0] == FAMILY.chat_id]
    assert private == [] and len(channel) == 1
    for chat_id, text, kw in channel:
        markup = kw.get("reply_markup")
        assert markup is not None
        data = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert "dy:go" in data and "dy:skip" in data
        assert any(item.startswith("dy:metric:") for item in data)
        assert any(item.startswith("dy:drop:") for item in data)


def test_ogni_clan_riceve_il_derby_nella_sua_lingua():
    store = store_with_activity()
    store.state[("clan-a", "settings")] = {"lang": "it"}
    store.state[("clan-b", "settings")] = {"lang": "en"}
    bot = FakeBot()
    poller = Poller(FakeSupervisor(bot), store, None)
    asyncio.run(poller.family_derby(FAMILY, MONDAY))
    assert [chat_id for chat_id, _, _ in bot.sent] == [FAMILY.chat_id]
    assert "Alfa" in "\n".join(sezione(store, A))
    assert "Beta" in "\n".join(sezione(store, B))
    asyncio.run(poller.family_derby(FAMILY, MONDAY + timedelta(days=7)))
    assert len(sezione(store, A)) == 3 and len(sezione(store, B)) == 3


def test_il_derby_non_pubblica_il_punteggio_del_clan_che_non_l_ha_acceso():
    store = FakeStore(state={("clan-a", "progress"): wins_over_monday(40, 2),
                             ("clan-a", "info"): {"members": 1},
                             ("clan-a", views.KIND): {views.FAMILY: True},
                             ("clan-b", "progress"): wins_over_monday(10, 1),
                             ("clan-b", "info"): {"members": 1}})
    doc = asyncio.run(derby.build(store, FAMILY, PREV_MONDAY, "UTC"))
    doc = derby.apply(doc, "dy:metric:activity")
    doc = asyncio.run(derby.scores(store, FAMILY, doc, MONDAY))
    assert [(row["name"], row["value"]) for row in tournaments.table(doc)] == [("Alfa", 420)]


def test_il_derby_di_partenza_non_mette_in_classifica_nessun_clan():
    store = FakeStore(state={
        ("clan-a", "progress"): {"#P1": {"name": "M", "now": {"wins": 40}, "week": {"since": 0, "wins": 0}}},
        ("clan-a", "info"): {"members": 1},
        ("clan-b", "progress"): {"#P9": {"name": "L", "now": {"wins": 10}, "week": {"since": 0, "wins": 0}}},
        ("clan-b", "info"): {"members": 1},
    })
    doc = asyncio.run(derby.build(store, FAMILY, MONDAY, "Europe/Rome"))
    doc = derby.apply(doc, "dy:metric:activity")
    doc = asyncio.run(derby.scores(store, FAMILY, doc, MONDAY))
    assert doc["entries"] == [] and doc["scores"] == {}


WARS_STELLE = {"clan-a": [{"result": "win", "stars": 42, "members": []}],
               "clan-b": [{"result": "lose", "stars": 7, "members": []}]}


def store_con_stelle(acceso=()):
    state = {(alias, views.KIND): {views.FAMILY: True} for alias in acceso}
    return FakeStore(state=state, wars=WARS_STELLE)


def test_il_derby_non_iscrive_il_clan_che_tiene_il_punteggio_nel_suo_clan():
    doc = asyncio.run(derby.build(store_con_stelle(["clan-a"]), FAMILY, PREV_MONDAY, "UTC"))
    assert [entry["ref"] for entry in doc["entries"]] == ["clan-a"]


def test_il_derby_a_stelle_non_pubblica_il_punteggio_di_chi_lo_tiene_nel_suo_clan():
    acceso = store_con_stelle(["clan-a", "clan-b"])
    doc = derby.apply(asyncio.run(derby.build(acceso, FAMILY, PREV_MONDAY, "UTC")),
                      "dy:metric:stars")
    vivo = asyncio.run(derby.scores(acceso, FAMILY, copy.deepcopy(doc), MONDAY))
    spento = asyncio.run(derby.scores(store_con_stelle(), FAMILY, copy.deepcopy(doc), MONDAY))
    assert sorted(vivo["scores"].values()) == [7, 42]
    assert sorted(spento["scores"].values()) == [0, 0]


def test_il_derby_di_partenza_non_pubblica_il_punteggio_di_chi_non_l_ha_acceso():
    acceso = store_con_stelle(["clan-a", "clan-b"])
    doc = asyncio.run(derby.build(acceso, FAMILY, PREV_MONDAY, "UTC"))
    assert doc["metric"] == "both"
    spento = asyncio.run(derby.scores(store_con_stelle(), FAMILY, doc, MONDAY))
    assert sorted(spento["scores"].values()) == [0, 0]


def test_le_stelle_tenute_nel_clan_non_spostano_la_posizione_degli_altri():
    wars = {"clan-a": [{"result": "lose", "stars": 7, "members": []}],
            "clan-b": [{"result": "win", "stars": 42, "members": []}]}
    acceso = FakeStore(wars=wars, state={(alias, views.KIND): {views.FAMILY: True}
                                         for alias in ("clan-a", "clan-b")})
    doc = asyncio.run(derby.build(acceso, FAMILY, PREV_MONDAY, "UTC"))
    solo_a = FakeStore(wars=wars, state={("clan-a", views.KIND): {views.FAMILY: True}})
    doc = asyncio.run(derby.scores(solo_a, FAMILY, doc, MONDAY))
    assert doc["scores"][tournaments.entry_id("clan", "clan-a")] == 2
    assert doc["scores"][tournaments.entry_id("clan", "clan-b")] == 0
