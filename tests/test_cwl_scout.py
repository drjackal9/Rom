import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import cwl_cards, cwl_scout, i18n, scouting
from clashbot.poller import Poller, Tick
from cwl_fixtures import SEASON, cwl_state

L = i18n.locale("it")
NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#C1", name="Futuro", bot_alias="bot-1")

PROFILES = {
    "#C1": {"clanLevel": 12, "warWinStreak": 4, "warWins": 120, "warLosses": 30,
            "isWarLogPublic": True, "warLeague": {"name": "Crystal League I"}},
    "#C2": {"clanLevel": 10, "warWinStreak": 0, "warWins": 80,
            "isWarLogPublic": False, "warLeague": {"name": "Crystal League I"}},
}


class FakeStore:
    def __init__(self, state=None):
        self.state = {k: copy.deepcopy(v) for k, v in (state or {}).items()}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)


class FakeCoc:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    async def clan(self, tag):
        self.calls.append(tag)
        if tag in self.fail:
            return None, "network"
        return copy.deepcopy(PROFILES.get(tag)), None


def fake_supervisor():
    return SimpleNamespace(bot=lambda alias: None, running=lambda: ["bot-1"],
                           default_alias="bot-1", owner_bot=lambda: None)


def test_distribuzione_e_media_dei_municipi_sono_quelle_del_blocco_guerre():
    members = [{"th": 15}, {"th": 15}, {"th": 13}, {"th": None}]
    assert cwl_scout.th_rows is scouting.th_rows
    assert cwl_scout.average_th is scouting.average_th
    assert cwl_scout.th_rows(members) == [[15, 2], [13, 1]]
    assert cwl_scout.th_rows({"#A": {"th": 15}, "#B": {"th": 13}}) == [[15, 1], [13, 1]]
    assert cwl_scout.average_th(members) == 14.33
    assert cwl_scout.average_th([]) == 0.0


def test_profilo_dal_clan_e_registro_privato():
    assert cwl_scout.clan_facts is scouting.clan_facts
    assert cwl_scout.clan_facts(PROFILES["#C1"])["streak"] == 4
    assert cwl_scout.clan_facts(PROFILES["#C2"])["losses"] is None
    assert cwl_scout.clan_facts(PROFILES["#C2"])["ties"] is None
    assert cwl_scout.clan_facts(PROFILES["#C2"])["public"] is False


def test_un_clan_per_giro_e_una_sola_card(monkeypatch):
    sent = []

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        sent.append((event, render_text(t.L)))

    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    store = FakeStore()
    coc = FakeCoc()
    poller = Poller(fake_supervisor(), store, coc)
    t = Tick(CLAN, NOW)
    t.L = L
    cwl = cwl_state(state="preparation", active=True)
    assert asyncio.run(poller.track_cwl_scout(t, cwl)) is False
    assert coc.calls == ["#C1"] and sent == []
    assert asyncio.run(poller.track_cwl_scout(t, cwl)) is False
    assert coc.calls == ["#C1", "#C2"]
    assert asyncio.run(poller.track_cwl_scout(t, cwl)) is True
    assert coc.calls == ["#C1", "#C2"] and sent[0][0] == "cwl.scout"
    assert asyncio.run(poller.track_cwl_scout(t, cwl)) is False
    assert len(sent) == 1


def test_la_card_ordina_per_municipio_e_segna_il_nostro():
    scout = cwl_scout.for_season(None, SEASON)
    cwl = cwl_state()
    assert cwl_scout.missing(cwl, scout) == ["#C1", "#C2"]
    assert cwl_scout.complete(cwl, scout) is False
    assert cwl_scout.complete({}, scout) is False
    for tag in ("#C1", "#C2"):
        cwl_scout.remember(scout, tag, cwl["clans"][tag], PROFILES[tag], NOW.timestamp())
    assert cwl_scout.missing(cwl, scout) == [] and cwl_scout.complete(cwl, scout) is True
    assert cwl_scout.for_season(scout, "2026-10")["clans"] == {}
    rows = cwl_scout.rows(scout, "#C1")
    assert [r["tag"] for r in rows] == ["#C1", "#C2"]
    assert rows[0]["us"] is True and rows[0]["rank"] == 1
    text = cwl_cards.scout_card(L, rows, SEASON)
    assert "IL GIRONE" in text and "Nostro Clan" in text and "🏰" in text
    assert "Nessun girone" in cwl_cards.scout_card(L, [])


def test_una_chiamata_fallita_non_consuma_il_clan_e_si_riprova(monkeypatch):
    sent = []

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        sent.append((event, render_text(t.L)))

    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    store = FakeStore()
    coc = FakeCoc(fail={"#C1"})
    poller = Poller(fake_supervisor(), store, coc)
    t = Tick(CLAN, NOW)
    t.L = L
    cwl = cwl_state(state="preparation", active=True)
    assert asyncio.run(poller.track_cwl_scout(t, cwl)) is False
    assert coc.calls == ["#C1"] and sent == []
    assert store.state.get(("clan-1", "cwl_scout")) is None
    coc.fail.clear()
    assert asyncio.run(poller.track_cwl_scout(t, cwl)) is False
    assert coc.calls == ["#C1", "#C1"]
    assert ((store.state[("clan-1", "cwl_scout")]).get("clans") or {}).get("#C1")


def test_il_profilo_mancante_si_dichiara_non_si_arrotonda():
    scout = cwl_scout.for_season(None, SEASON)
    cwl = cwl_state()
    cwl_scout.remember(scout, "#C1", cwl["clans"]["#C1"], None, NOW.timestamp())
    rows = cwl_scout.rows(scout, "#C1")
    assert rows[0]["streak"] is None and rows[0]["league"] is None
    assert "?" in cwl_cards.scout_card(L, rows, SEASON)
    assert "0 di fila" not in cwl_cards.scout_card(L, rows, SEASON)
