import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import cwl_bonus, cwl_cards, cwl_season, handlers, i18n
from clashbot.poller import Poller, Tick
from cwl_fixtures import SEASON, cwl_state, war_records

L = i18n.locale("it")
NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#C1", name="Futuro", bot_alias="bot-1")


class FakeStore:
    def __init__(self, state=None, wars=()):
        self.state = {k: copy.deepcopy(v) for k, v in (state or {}).items()}
        self.wars = list(wars)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def recent_wars(self, alias, limit=10):
        return copy.deepcopy(self.wars)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def links_by_user(self, user_id):
        return []

    async def bot_by_alias(self, alias):
        return None

    async def get_secret(self, kind):
        return None


class ContaLetture(FakeStore):
    def __init__(self, state=None, wars=()):
        super().__init__(state, wars)
        self.reads = []

    async def get_state(self, alias, kind):
        self.reads.append(kind)
        return await super().get_state(alias, kind)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []
        self.markups = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)
        self.markups.append(reply_markup)


def fake_supervisor():
    return SimpleNamespace(bot=lambda alias: None, running=lambda: ["bot-1"],
                           default_alias="bot-1", owner_bot=lambda: None)


def rows():
    return cwl_season.member_rows(cwl_season.season_wars(war_records(), SEASON))


def test_il_punteggio_usa_i_pesi_gia_in_uso():
    mario = next(r for r in rows() if r["tag"] == "#P1")
    assert cwl_bonus.value(mario) == 12
    luigi = next(r for r in rows() if r["tag"] == "#P2")
    assert cwl_bonus.value(luigi) == 5


def test_a_parita_sale_chi_ha_avuto_meno_bonus():
    history = [{"season": "2026-08", "members": [{"tag": "#P3", "bonus": True},
                                                 {"tag": "#P1", "bonus": False}]}]
    past = cwl_bonus.past_bonus(history)
    assert past == {"#P3": 1}
    base = [{"tag": "#A", "name": "A", "attacks": 2, "stars": 6, "triples": 2, "missed": 0, "wars": 2},
            {"tag": "#B", "name": "B", "attacks": 2, "stars": 6, "triples": 2, "missed": 0, "wars": 2}]
    ordered = cwl_bonus.proposal(base, {"#A": 2})
    assert [r["tag"] for r in ordered] == ["#B", "#A"]
    assert ordered[0]["value"] == ordered[1]["value"] and ordered[1]["past"] == 2


def test_il_segno_del_capo_si_accende_e_si_spegne():
    state = {"season": SEASON, "avail": {}, "bonus": [], "sent": {}}
    cwl_bonus.toggle(state, "#P1")
    assert state["bonus"] == ["#P1"]
    cwl_bonus.toggle(state, "#P1")
    assert state["bonus"] == []


def test_la_card_spiega_come_nasce_il_punteggio():
    text = cwl_cards.bonus_card(L, cwl_bonus.proposal(rows()))
    assert "MEDAGLIE BONUS" in text and "Mario" in text and "tripla +3" in text
    assert "Ancora nessuna" in cwl_cards.bonus_card(L, [])


def test_la_riga_mostra_i_quattro_conti_che_fanno_il_punteggio():
    proposta = cwl_bonus.proposal(rows())
    mario = next(r for r in proposta if r["name"] == "Mario")
    riga = next(line for line in cwl_cards.bonus_card(L, proposta).splitlines()
                if "Mario" in line)
    for pezzo in (f"{mario['value']} pt", f"{mario['stars']}⭐",
                  f"attacchi {mario['attacks']}", f"triple {mario['triples']}",
                  f"saltati {mario['missed']}"):
        assert pezzo in riga
    assert mario["triples"] and cwl_bonus.value(
        dict(mario, triples=0)) != mario["value"]


def test_la_riga_non_mette_due_segni_in_testa_e_non_sbaglia_il_plurale():
    proposta = cwl_bonus.proposal(rows())
    righe = [line for line in cwl_cards.bonus_card(L, proposta).splitlines() if " pt · " in line]
    assert righe and all("· 1." not in riga for riga in righe)
    primo = righe[0].replace("<blockquote>", "")
    assert primo.startswith(L.t("rank.n", n=1))
    for sbagliato in ("1 attacchi", "1 triple", "1 saltati"):
        assert all(sbagliato not in riga for riga in righe)
    segnata = cwl_cards.bonus_card(L, [dict(proposta[0], assigned=True)])
    assert "🎖 " + proposta[0]["name"] in segnata


def test_la_proposta_parte_una_volta_a_stagione(monkeypatch):
    sent = []

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        sent.append((event, render_text(t.L)))

    async def no_history(store, alias, limit=12):
        return []

    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    monkeypatch.setattr("clashbot.cwl_store.seasons", no_history)
    store = FakeStore(wars=war_records())
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    t.L = L
    cwl = cwl_state()
    assert asyncio.run(poller.cwl_bonus(t, cwl)) is True
    assert sent[0][0] == "cwl.bonus" and "MEDAGLIE BONUS" in sent[0][1]
    assert asyncio.run(poller.cwl_bonus(t, cwl)) is False
    assert len(sent) == 1
    aperto = cwl_state(state="inWar")
    aperto["wars"]["#W2"]["state"] = "inWar"
    fresco = Poller(fake_supervisor(), FakeStore(wars=war_records()), None)
    assert asyncio.run(fresco.cwl_bonus(t, aperto)) is False
    assert len(sent) == 1


def test_solo_chi_gestisce_puo_segnare(monkeypatch):
    async def no_history(store, alias, limit=12):
        return []

    monkeypatch.setattr("clashbot.cwl_store.seasons", no_history)
    store = FakeStore(state={(CLAN.alias, "cwl"): cwl_state()}, wars=war_records())
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"})
    update = SimpleNamespace(callback_query=FakeQuery("cw:b:#P1"),
                             effective_chat=SimpleNamespace(id=CLAN.chat_id),
                             effective_user=SimpleNamespace(id=7, language_code="it"))

    async def no_manage(update, context, clan):
        return False

    monkeypatch.setattr(handlers, "can_manage", no_manage)
    asyncio.run(handlers.on_cwl_callback(update, context))
    assert update.callback_query.answers[-1][1] is True
    assert (CLAN.alias, "cwl_roster") not in store.state

    async def manage(update, context, clan):
        return True

    monkeypatch.setattr(handlers, "can_manage", manage)
    ok = SimpleNamespace(callback_query=FakeQuery("cw:b:#P1"),
                         effective_chat=SimpleNamespace(id=CLAN.chat_id),
                         effective_user=SimpleNamespace(id=7, language_code="it"))
    asyncio.run(handlers.on_cwl_callback(ok, context))
    assert store.state[(CLAN.alias, "cwl_roster")]["bonus"] == ["#P1"]
    assert "🎖" in ok.callback_query.edits[-1]
    buttons = [b for row in ok.callback_query.markups[-1].inline_keyboard for b in row]
    segno = next(b for b in buttons if b.callback_data == "cw:b:#P1")
    assert segno.text.startswith("🎖") and "Mario" in segno.text
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons)


def test_a_stagione_chiusa_il_poller_non_legge_piu_niente():
    chiusa = cwl_state(closed=True, checked=NOW.timestamp())
    store = ContaLetture(state={(CLAN.alias, "cwl"): chiusa}, wars=war_records())
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    t.L = L
    asyncio.run(poller.track_cwl(t))
    assert store.reads == ["cwl"]
    assert (CLAN.alias, "cwl_scout") not in store.state
    assert (CLAN.alias, "cwl_roster") not in store.state
