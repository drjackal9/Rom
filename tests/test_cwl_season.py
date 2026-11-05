import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import cwl_cards, cwl_season, handlers, i18n, setup_ui
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


def fake_supervisor():
    return SimpleNamespace(bot=lambda alias: None, running=lambda: ["bot-1"],
                           default_alias="bot-1", owner_bot=lambda: None)


def test_season_wars_tiene_solo_le_giornate_cwl_della_stagione():
    rows = cwl_season.season_wars(war_records(), SEASON)
    assert [r["day"] for r in rows] == [1, 2]
    assert cwl_season.season_wars(war_records(), "2026-08") == []


def test_finished_solo_quando_tutte_le_giornate_sono_chiuse():
    assert cwl_season.finished(cwl_state()) is True
    aperto = cwl_state(state="inWar")
    aperto["wars"]["#W2"]["state"] = "inWar"
    assert cwl_season.finished(aperto) is False
    assert cwl_season.finished({"state": "ended"}) is True
    assert cwl_season.finished({}) is False


def test_season_record_riassume_posizione_giornate_e_membri():
    record = cwl_season.season_record(cwl_state(), "#C1", cwl_season.season_wars(war_records(), SEASON),
                                      {"bonus": ["#P2"]})
    assert record["season"] == SEASON and record["league"] == "Crystal League I"
    assert record["rank"] == 1 and record["of"] == 2 and record["stars"] == 27
    assert (record["wins"], record["losses"], record["ties"]) == (1, 1, 0)
    assert [d["result"] for d in record["days"]] == ["win", "lose"]
    assert record["days"][1]["opponent"] == "Clan Due" and record["days"][1]["stars"] == 8
    mario = next(m for m in record["members"] if m["tag"] == "#P1")
    assert mario["stars"] == 5 and mario["wars"] == 2 and mario["bonus"] is False
    assert next(m for m in record["members"] if m["tag"] == "#P2")["bonus"] is True
    assert record["move"] is None
    assert cwl_season.ended_at(record, NOW) == datetime(2026, 9, 3, 10, tzinfo=timezone.utc)


def test_le_card_di_stagione_e_storico_si_leggono():
    record = cwl_season.season_record(cwl_state(), "#C1", cwl_season.season_wars(war_records(), SEASON))
    text = cwl_cards.season_card(L, record)
    assert "CWL CHIUSA" in text and "Clan Due" in text and "Mario" in text and "✅" in text
    history = cwl_cards.history_card(L, [dict(record, move="up")])
    assert "settembre 2026" in history and "⬆️" in history and "Crystal League I" in history
    assert "Nessuna CWL chiusa" in cwl_cards.history_card(L, [])


def test_le_schede_di_cwl_segnano_quella_aperta():
    assert handlers.CWL_TABS[0] == "cwl" and "cwl:history" in handlers.CWL_TABS
    for key in handlers.CWL_TABS:
        rows = handlers.cwl_keyboard(L, key).inline_keyboard
        tabs = [b for row in rows[:-1] for b in row]
        assert rows[-1][-1].callback_data == f"v:{key}"
        assert [b.callback_data for b in tabs] == [f"v:{tab}" for tab in handlers.CWL_TABS]
        assert all(len(b.callback_data.encode()) <= 64 for b in tabs)
        assert "[menu." not in " ".join(b.text for b in tabs)
        picked = [b.text for b in tabs if b.text.startswith(setup_ui.PICKED)]
        assert len(picked) == 1 and picked[0].endswith(L.t(f"menu.{key.replace(':', '.')}"))


def test_la_chiusura_archivia_e_annuncia_una_volta_sola(monkeypatch):
    saved, sent = [], []

    async def fake_save(store, alias, season, ended_at, record):
        saved.append((alias, season, ended_at, record))
        return True

    async def fake_dispatch(self, t, event, render_text, member_tag=None, chunk=None):
        sent.append((event, render_text(t.L)))

    monkeypatch.setattr("clashbot.cwl_store.save_season", fake_save)
    monkeypatch.setattr(Poller, "dispatch", fake_dispatch)
    store = FakeStore(state={(CLAN.alias, "cwl"): cwl_state()}, wars=war_records())
    poller = Poller(fake_supervisor(), store, None)
    t = Tick(CLAN, NOW)
    t.L = L
    cwl = asyncio.run(store.get_state(CLAN.alias, "cwl"))
    assert asyncio.run(poller.close_cwl_season(t, cwl)) is True
    assert saved[0][0] == CLAN.alias and saved[0][1] == SEASON
    assert saved[0][2] == datetime(2026, 9, 3, 10, tzinfo=timezone.utc)
    assert sent[0][0] == "cwl.season" and "CWL CHIUSA" in sent[0][1]
    assert store.state[(CLAN.alias, "cwl")]["closed"] is True
    cwl = asyncio.run(store.get_state(CLAN.alias, "cwl"))
    assert asyncio.run(poller.close_cwl_season(t, cwl)) is False
    assert len(saved) == 1 and len(sent) == 1
