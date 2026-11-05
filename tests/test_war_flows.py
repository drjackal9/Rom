import asyncio
import inspect
from datetime import datetime, timezone

import pytest

from clashbot import boards, events, i18n, render, scoring, warstats
from clashbot.events_registry import EVENTS
from clashbot.poller import Poller, Tick
from fixtures import war_json
from test_flows import CLAN, FakeStore, fake_supervisor
from test_scouting import FakeCoc

L = i18n.locale("it")
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


def tick(settings=None):
    t = Tick(CLAN, NOW)
    t.settings = {**t.settings, **(settings or {})}
    t.L = L
    t.season = scoring.empty_season("2026-09")
    return t


def dispatched(poller):
    sent = []

    async def dispatch(t, event, render_text, member_tag=None, chunk=None, card=None):
        sent.append((event, render_text(t.L)))

    poller.dispatch = dispatch
    return sent


def old_record(opponent="Clan Nemico", opp_tag="#ENEMY", result="win"):
    return {"kind": "war", "day": None, "endTime": "20260901T100000.000Z", "opponent": opponent,
            "opp_tag": opp_tag, "result": result, "stars": 6, "destr": 90.0, "opp_stars": 2,
            "opp_destr": 40.0, "teamSize": 3, "attacksPerMember": 2, "members": []}


def defended_record():
    return events.war_record(events.war_snapshot(war_json("warEnded",
                                                          our_attacks={"#P1": [("#E1", 3, 100)]},
                                                          their_attacks={"#E2": [("#P3", 2, 78)]})))


def test_i_due_eventi_nuovi_stanno_nel_registro_del_pacchetto_guerre():
    for name in ("war.opponent_history", "war.record"):
        assert EVENTS[name]["pack"] == "wars"
        assert EVENTS[name]["default"] == "group"
        assert "off" in EVENTS[name]["allowed"]
    assert "leaders_dm" in EVENTS["war.opponent_history"]["allowed"]
    assert set(EVENTS["war.record"]["allowed"]) == {"group", "topic", "off"}


def test_in_preparazione_arriva_la_card_dellavversario_gia_visto():
    store = FakeStore(wars=[old_record()])
    poller = Poller(fake_supervisor(), store, None)
    sent = dispatched(poller)
    war = events.war_snapshot(war_json("preparation"))
    asyncio.run(poller.opponent_history(tick(), war, "war", None))
    assert [event for event, _ in sent] == ["war.opponent_history"]
    assert "Clan Nemico" in sent[0][1] and "Vinte 1" in sent[0][1]


def test_contro_un_clan_mai_visto_non_arriva_niente():
    store = FakeStore(wars=[old_record(opponent="Altri", opp_tag="#OTHER")])
    poller = Poller(fake_supervisor(), store, None)
    sent = dispatched(poller)
    war = events.war_snapshot(war_json("preparation"))
    asyncio.run(poller.opponent_history(tick(), war, "war", None))
    assert sent == []


def test_la_guerra_che_entra_in_preparazione_porta_i_gia_visti():
    store = FakeStore(state={(CLAN.alias, "war"): {"state": "notInWar"}}, wars=[old_record()])
    poller = Poller(fake_supervisor(), store, FakeCoc())
    sent = dispatched(poller)
    war = events.war_snapshot(war_json("preparation"))
    asyncio.run(poller.track_war(tick(), war, "war", None))
    assert [event for event, _ in sent] == ["war.prep", "war.opponent_history"]


def test_il_primo_record_non_si_annuncia_ma_si_salva():
    store = FakeStore()
    poller = Poller(fake_supervisor(), store, None)
    sent = dispatched(poller)
    t = tick()
    asyncio.run(poller.bump_streak(t, 7))
    assert sent == []
    hall = warstats.hall_state(asyncio.run(store.get_state(CLAN.alias, "hall")))
    assert hall["records"]["streak"] == {"current": 7, "best": 7}
    asyncio.run(poller.bump_streak(t, 9))
    assert [event for event, _ in sent] == ["war.record"]
    assert "Serie di vittorie" in sent[0][1]


def test_la_serie_che_non_cambia_non_riscrive_lalbo():
    store = FakeStore()
    poller = Poller(fake_supervisor(), store, None)
    dispatched(poller)
    t = tick()
    asyncio.run(poller.bump_streak(t, 7))
    written = asyncio.run(store.get_state(CLAN.alias, "hall"))
    asyncio.run(poller.bump_streak(t, 7))
    asyncio.run(poller.bump_streak(t, None))
    assert asyncio.run(store.get_state(CLAN.alias, "hall")) == written


def test_la_guerra_perfetta_entra_nei_record_e_si_annuncia():
    store = FakeStore()
    poller = Poller(fake_supervisor(), store, None)
    sent = dispatched(poller)
    perfetta = events.war_record(events.war_snapshot(war_json("warEnded", our_attacks={
        "#P1": [("#E1", 3, 100)], "#P2": [("#E2", 3, 100)], "#P3": [("#E3", 3, 100)],
    })))
    asyncio.run(poller.bump_records(tick(), perfetta))
    assert [event for event, _ in sent] == ["war.record"]
    assert "Guerre perfette" in sent[0][1]
    hall = warstats.hall_state(asyncio.run(store.get_state(CLAN.alias, "hall")))
    assert hall["records"]["perfect"]["n"] == 1


def test_la_card_di_fine_guerra_senza_difese_e_identica_a_oggi():
    ended = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]},
                                         their_attacks={"#E2": [("#P3", 2, 78)]}))
    assert render.render_war_end(L, ended, "win") == render.render_war_end(L, ended, "win", "war", None, None)
    with_defense = render.render_war_end(L, ended, "win", "war", None, warstats.war_defense(ended))
    assert "Difese" in with_defense and "Peach · 2⭐" in with_defense
    assert L.t("war_end.held").split("{")[0] not in with_defense
    tenuta = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]},
                                          their_attacks={"#E2": [("#P3", 2, 78)], "#E1": [("#P1", 0, 45)]}))
    con_muro = render.render_war_end(L, tenuta, "win", "war", None, warstats.war_defense(tenuta))
    assert L.t("war_end.held").split("{")[0] in con_muro and "Mario" in con_muro


def test_il_muro_diventa_un_titolo_di_stagione():
    season = scoring.empty_season("2026-09")
    scoring.apply_war(season, old_record())
    wall = {"name": "Mario", "stars": 1, "attacked": 4}
    assert scoring.titles(season, wall=wall)["Muro"] == ("Mario", 1)
    assert "Muro" not in scoring.titles(season)
    assert "Muro" not in scoring.titles(season, wall={"name": "Mario", "stars": 0, "attacked": 0})
    assert scoring.TITLES["Muro"] == "🧱"


def test_il_muro_si_passa_solo_per_nome_cosi_il_posto_resta_libero():
    season = scoring.empty_season("2026-09")
    with pytest.raises(TypeError):
        scoring.titles(season, None, {"name": "Mario", "stars": 1, "attacked": 4})


def positional_names(fn):
    return [p.name for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]


def test_il_confine_col_blocco_classifiche_resta_scritto_nel_codice():
    params = inspect.signature(scoring.titles).parameters
    assert positional_names(scoring.titles) == ["season", "activity"]
    assert params["wall"].kind is params["wall"].KEYWORD_ONLY
    assert positional_names(render.record_card) == ["L", "names", "records"]
    assert "perfect" in warstats.RECORD_KEYS
    assert not hasattr(boards, "perfect_war")
    assert not hasattr(boards, "push_history")
    assert "perfect" not in getattr(boards, "RECORDS", ())


def test_a_fine_stagione_restano_il_muro_nei_titoli_e_la_fotografia_del_mese():
    record = defended_record()
    season = scoring.empty_season("2026-08")
    scoring.apply_war(season, record)
    store = FakeStore(state={(CLAN.alias, "season"): season}, wars=[record])
    poller = Poller(fake_supervisor(), store, None)
    sent = dispatched(poller)
    t = tick()
    asyncio.run(poller.season_for(t))
    assert [event for event, _ in sent] == ["boards.mvp"]
    assert "🧱" in sent[0][1] and "Peach" in sent[0][1]
    ended_at, snapshot = store.stats[(CLAN.alias, "war_month", "2026-08")]
    assert ended_at == warstats.month_end("2026-08", "UTC")
    assert snapshot["wars"] == 1 and snapshot["wall"]["name"] == "Peach"
    hall = asyncio.run(store.get_state(CLAN.alias, "hall"))
    assert hall["seasons"][0]["titles"]["Muro"] == ["Peach", 2]
    assert t.season["id"] == "2026-09" and t.season["members"] == {}


def test_la_fotografia_del_mese_si_scrive_una_volta_sola_anche_se_il_giro_si_rompe():
    record = defended_record()
    season = scoring.empty_season("2026-08")
    scoring.apply_war(season, record)
    store = FakeStore(state={(CLAN.alias, "season"): season}, wars=[record])
    poller = Poller(fake_supervisor(), store, None)
    sent = dispatched(poller)
    written = []
    stored_add_stat = store.add_stat

    async def add_stat(alias, kind, stat_key, ended_at, obj):
        written.append((kind, stat_key))
        return await stored_add_stat(alias, kind, stat_key, ended_at, obj)

    store.add_stat = add_stat
    asyncio.run(poller.season_for(tick()))
    assert asyncio.run(store.get_state(CLAN.alias, "season"))["id"] == "2026-09"
    asyncio.run(poller.season_for(tick()))
    assert written == [("war_month", "2026-08")]
    assert [event for event, _ in sent] == ["boards.mvp"]
    assert [s["season"] for s in asyncio.run(store.get_state(CLAN.alias, "hall"))["seasons"]] == ["2026-08"]
