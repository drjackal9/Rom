import asyncio
import copy
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import badges, bingo, boards, challenges, events, i18n, settings as settings_mod
from clashbot.platform_guard import Buckets
from clashbot.poller import Poller, Tick
from fixtures import war_json

IT = i18n.locale("it")
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
ENDED = war_json("warEnded",
                 our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)], "#P2": [("#E3", 3, 100), ("#E1", 1, 30)],
                              "#P3": [("#E2", 1, 40), ("#E3", 2, 70)]},
                 their_attacks={"#E1": [("#P2", 1, 45)]})


class FakeStore:
    def __init__(self):
        self.state = {}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.pins = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return SimpleNamespace(message_id=70 + len(self.sent))

    async def edit_message_text(self, text, chat_id=None, message_id=None):
        self.edits.append((message_id, text))

    async def pin_chat_message(self, chat_id, message_id, **kw):
        self.pins.append(message_id)


def tick(store, bot, now=NOW):
    poller = Poller(SimpleNamespace(bot=lambda alias: bot, running=lambda: [CLAN.bot_alias],
                                    default_alias=CLAN.bot_alias, owner_bot=lambda: bot), store, None)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective({"lang": "it", "tz": "Europe/Rome"}, None)
    t.L = IT
    t.tz = t.settings["tz"]
    return poller, t


def test_la_cartella_e_deterministica_e_di_nove_caselle():
    first = bingo.card_for("20260912T100000.000Z|#ENEMY")
    assert len(first) == bingo.SIZE * bingo.SIZE
    assert len(set(first)) == len(first)
    assert set(first) <= set(bingo.CELLS)
    assert bingo.card_for("20260912T100000.000Z|#ENEMY") == first
    assert bingo.card_for("20260913T100000.000Z|#ALTRO") != first


def test_le_caselle_si_segnano_solo_con_quello_che_l_api_dice():
    war = events.war_snapshot(war_json(
        "warEnded",
        our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)], "#P2": [("#E3", 3, 100), ("#E1", 1, 30)],
                     "#P3": [("#E2", 1, 40), ("#E3", 2, 70)]},
        their_attacks={"#E1": [("#P2", 1, 45)]}))
    assert bingo.marks(war, behind=True) == {
        "opening", "no_missed", "all_scored", "total", "wall", "no_triple_against", "double", "comeback"}
    assert bingo.marks(war, behind=False) == {
        "opening", "no_missed", "all_scored", "total", "wall", "no_triple_against", "double"}
    assert bingo.marks(events.war_snapshot(war_json("inWar")), behind=False) == set()


def test_il_bingo_trova_righe_colonne_e_diagonali():
    cells = list(bingo.CELLS[:9])
    assert bingo.bingo_lines(cells, set(cells[:3])) == [cells[:3]]
    assert bingo.bingo_lines(cells, {cells[0], cells[3], cells[6]}) == [[cells[0], cells[3], cells[6]]]
    assert bingo.bingo_lines(cells, {cells[0], cells[4], cells[8]}) == [[cells[0], cells[4], cells[8]]]
    assert bingo.bingo_lines(cells, set()) == []


def test_il_riquadro_del_hub_mostra_le_caselle_segnate():
    state = {"bingo": {"war": "w1", "cells": list(bingo.CELLS[:9]), "hit": [bingo.CELLS[0]]}}
    text = bingo.section(IT, state)
    assert "1/9" in text
    assert bingo.section(IT, challenges.empty()) is None
    assert bingo.section(IT, {"bingo": {"done": "w1"}}) is None


def test_la_cartella_e_un_solo_messaggio_che_cambia_sul_posto(monkeypatch):
    monkeypatch.setattr(bingo, "card_for", lambda key: list(bingo.CELLS[:9]))
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot)
    aperta = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]}))
    asyncio.run(bingo.run(poller, t, aperta))
    assert len(bot.sent) == 1 and bot.edits == [] and bot.pins == []
    aperto = asyncio.run(challenges.load(store, CLAN.alias))
    message_id = aperto["bingo"]["message_id"]
    assert message_id and aperto["bingo"]["digest"]
    asyncio.run(bingo.run(poller, t, aperta))
    assert len(bot.sent) == 1 and bot.edits == []
    piena = events.war_snapshot(war_json("inWar", our_attacks={
        "#P1": [("#E1", 3, 100), ("#E2", 3, 100)], "#P2": [("#E3", 3, 100), ("#E1", 1, 30)],
        "#P3": [("#E2", 1, 40), ("#E3", 2, 70)]}))
    asyncio.run(bingo.run(poller, t, piena))
    assert len(bot.sent) == 1 and [mid for mid, _ in bot.edits] == [message_id]
    asyncio.run(bingo.run(poller, t, events.war_snapshot(ENDED)))
    assert len(bot.sent) == 1 and [mid for mid, _ in bot.edits] == [message_id, message_id]
    assert bot.pins == []
    chiuso = asyncio.run(challenges.load(store, CLAN.alias))
    assert chiuso["bingo"]["done"] == events.war_key(events.war_snapshot(ENDED))
    assert chiuso["bingo"]["message_id"] is None


def test_una_guerra_gia_chiusa_non_riparte_neanche_se_lo_stato_resta_fermo():
    store, bot = FakeStore(), FakeBot()
    war = events.war_snapshot(ENDED)
    poller, t = tick(store, bot)
    asyncio.run(bingo.run(poller, t, war))
    assert len(bot.sent) == 1 and not bot.pins
    chunks = len(t.chunks)
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert state["bingo"]["done"] == events.war_key(war) and state["bingo"]["cells"] == []
    for _ in range(3):
        asyncio.run(bingo.run(poller, t, war))
    assert len(bot.sent) == 1 and not bot.edits and len(t.chunks) == chunks
    assert len(challenges.recent(asyncio.run(challenges.load(store, CLAN.alias)), "bingo")) <= 1


def test_una_casella_segnata_resta_segnata_anche_se_il_nemico_rimonta(monkeypatch):
    cells = ["wall", "streak3", "opening", "th_up", "uphill", "no_missed",
             "all_scored", "comeback", "perfect"]
    monkeypatch.setattr(bingo, "card_for", lambda key: cells)
    prima = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]}))
    poi = events.war_snapshot(war_json(
        "inWar",
        our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)], "#P2": [("#E3", 3, 100)]},
        their_attacks={"#E1": [("#P1", 1, 30)], "#E2": [("#P2", 1, 30)], "#E3": [("#P3", 1, 30)]}))
    assert "wall" in bingo.marks(prima, behind=False)
    assert "wall" not in bingo.marks(poi, behind=False)
    assert "streak3" in bingo.marks(poi, behind=False)
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot)
    asyncio.run(bingo.run(poller, t, prima))
    aperto = asyncio.run(challenges.load(store, CLAN.alias))
    assert set(aperto["bingo"]["hit"]) == {"wall", "opening"}
    assert not aperto["bingo"]["bingo"]
    asyncio.run(bingo.run(poller, t, poi))
    dopo = asyncio.run(challenges.load(store, CLAN.alias))
    assert set(dopo["bingo"]["hit"]) == {"wall", "opening", "streak3", "perfect"}
    assert dopo["bingo"]["bingo"] is True
    assert badges.of(dopo, "#P1") == ["bingo"]
    assert [text for text in boards.lines_of(t.boards, "challenges") if "BINGO!" in text]


def test_la_riga_di_bingo_da_il_badge_a_chi_ha_attaccato(monkeypatch):
    store, bot = FakeStore(), FakeBot()
    war = events.war_snapshot(ENDED)
    riga = sorted(bingo.marks(war, behind=False))[:3]
    cells = riga + [cell for cell in bingo.CELLS if cell not in riga][:6]
    assert len(cells) == bingo.SIZE * bingo.SIZE
    monkeypatch.setattr(bingo, "card_for", lambda key: cells)
    poller, t = tick(store, bot)
    asyncio.run(bingo.run(poller, t, war))
    state = asyncio.run(challenges.load(store, CLAN.alias))
    assert badges.of(state, "#P1") == ["bingo"] and badges.of(state, "#P3") == ["bingo"]
    assert challenges.recent(state, "bingo")
    assert len(bot.sent) == 1 and not bot.pins
    assert [text for text in boards.lines_of(t.boards, "challenges") if "BINGO!" in text]


def test_la_cartella_passa_dall_involucro_comune_e_dal_tetto_per_gruppo(monkeypatch):
    testo = pathlib.Path(bingo.__file__).read_text(encoding="utf-8")
    assert "send_message" not in testo and "edit_message_text" not in testo
    monkeypatch.setattr(bingo, "card_for", lambda key: list(bingo.CELLS[:9]))
    store, bot = FakeStore(), FakeBot()
    poller, t = tick(store, bot)
    aperta = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]}))
    while poller.guard.allow(CLAN.chat_id):
        pass
    asyncio.run(bingo.run(poller, t, aperta))
    assert bot.sent == [] and bot.pins == []
    assert asyncio.run(challenges.load(store, CLAN.alias))["bingo"]["message_id"] is None
    poller.guard.buckets = Buckets()
    asyncio.run(bingo.run(poller, t, aperta))
    assert len(bot.sent) == 1 and bot.pins == []
    assert asyncio.run(challenges.load(store, CLAN.alias))["bingo"]["message_id"]
