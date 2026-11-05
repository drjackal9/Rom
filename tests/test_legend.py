import asyncio
from datetime import datetime, timezone

from test_routing import CLAN, FUTURO, NOW, routed, setup

from clashbot import boards, feed, i18n, legend, render, trend
from clashbot.events_registry import EVENTS

IT = i18n.locale("it")
EARLY = datetime(2026, 9, 11, 5, tzinfo=timezone.utc)
TODAY = "2026-09-11"


def snapshot(name, league_id, trophies):
    return {"name": name, "league_id": league_id, "trophies": trophies, "th": 17,
            "league": legend.LEAGUE_NAME if league_id == legend.LEAGUE_ID else "Titan I",
            "legend": {"trophies": trophies, "rank": 42, "best_trophies": 6000,
                       "best_rank": 7, "best_season": "2026-03"}}


def test_solo_chi_e_in_leggenda_riceve_il_riepilogo():
    players = {"#P1": snapshot("Mario", legend.LEAGUE_ID, 5400),
               "#P2": snapshot("Luigi", 29000021, 4900)}
    members = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}}
    assert [r["tag"] for r in legend.rows(players, {}, members)] == ["#P1"]


def test_il_nome_della_lega_basta_se_manca_l_identificativo():
    assert legend.in_legend({"league": legend.LEAGUE_NAME}) is True
    assert legend.in_legend({"league_id": legend.LEAGUE_ID}) is True
    assert legend.in_legend({"league": "Titan I"}) is False
    assert legend.in_legend(None) is False


def test_la_differenza_viene_dal_campione_di_ieri():
    state = trend.record({}, "#P1", "Mario", "2026-09-12", 5300, 17, 5300)
    state = trend.record(state, "#P1", "Mario", "2026-09-13", 5400, 17, 5400)
    players = {"#P1": snapshot("Mario", legend.LEAGUE_ID, 5400)}
    row = legend.rows(players, state, {"#P1": {"name": "Mario"}})[0]
    assert row["trophies"] == 5400 and row["gained"] == 100
    assert row["rank"] == 42 and row["best_rank"] == 7 and row["best_season"] == "2026-03"


def test_senza_storico_la_differenza_e_zero():
    players = {"#P1": snapshot("Mario", legend.LEAGUE_ID, 5400)}
    assert legend.rows(players, {}, {"#P1": {"name": "Mario"}})[0]["gained"] == 0


def test_chi_ha_lasciato_il_clan_non_compare():
    players = {"#PX": snapshot("Ex", legend.LEAGUE_ID, 5400)}
    assert legend.rows(players, {}, {"#P1": {"name": "Mario"}}) == []


def test_le_righe_sono_ordinate_per_trofei():
    players = {"#P1": snapshot("Mario", legend.LEAGUE_ID, 5400),
               "#P2": snapshot("Luigi", legend.LEAGUE_ID, 5900)}
    members = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}}
    assert [r["name"] for r in legend.rows(players, {}, members)] == ["Luigi", "Mario"]
    assert legend.rows(None, None, None) == []


def test_levento_della_leggenda_e_nel_registro_con_le_destinazioni_dei_membri():
    meta = EVENTS["members.legend"]
    assert meta["pack"] == "members"
    assert meta["default"] == "member_dm"
    assert set(meta["allowed"]) == {"member_dm", "group", "topic", "off"}
    assert meta["intensity"] is None


def test_la_carta_della_leggenda_dice_trofei_posizione_e_record():
    row = {"tag": "#P1", "name": "Mario", "trophies": 5400, "gained": 100, "rank": 42,
           "best_trophies": 6000, "best_rank": 7, "best_season": "2026-03"}
    text = render.legend_card(IT, row)
    assert IT.t("legend.title") in text and "Mario" in text
    assert IT.t("legend.today", trophies=IT.n(5400), delta=IT.t("me.trend_up", n=100)) in text
    assert IT.t("legend.rank", rank=IT.n(42)) in text
    assert IT.t("legend.best", trophies=IT.n(6000), rank=IT.n(7), season="2026-03") in text
    assert IT.t("legend.tail") in text


def test_la_carta_tace_su_cio_che_l_api_non_espone():
    row = {"tag": "#P1", "name": "Mario", "trophies": 5400, "gained": -60, "rank": None,
           "best_trophies": None, "best_rank": None, "best_season": None}
    text = render.legend_card(IT, row)
    assert IT.t("me.trend_down", n=60) in text
    assert IT.t("legend.rank", rank=IT.n(42)) not in text
    assert "?" not in text


def legend_state(day=None):
    players = {"tags": {"#P1": snapshot("Mario", legend.LEAGUE_ID, 5400)}, "cursor": 0, "out_since": {}}
    state = {(CLAN.alias, "players"): players,
             (CLAN.alias, "trend"): trend.record({}, "#P1", "Mario", TODAY, 5400, 17, 5400)}
    if day:
        state[(CLAN.alias, "legend")] = {"day": day}
    return state


def run_legend(now=NOW, day=None, stored=FUTURO):
    poller, store, bot, t = setup(stored, state=legend_state(day), now=now)
    asyncio.run(poller.track_legend(t))
    asyncio.run(poller.flush(t))
    return store, bot, t


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_il_riepilogo_arriva_nel_feed_dell_interessato():
    store, bot, t = run_legend()
    assert bot.sent == []
    assert IT.t("legend.title") in feed_rows(store, 7)[0] and "Mario" in feed_rows(store, 7)[0]
    assert store.state[(CLAN.alias, "legend")] == {"day": TODAY}


def test_il_capo_puo_portare_il_riepilogo_sulla_bacheca():
    store, bot, t = run_legend(stored=routed(FUTURO, "members.legend", "group"))
    assert bot.sent == []
    righe = boards.lines_of(t.boards, "members")
    assert len(righe) == 1 and IT.n(5400) in righe[0]


def test_il_riepilogo_del_giorno_non_si_ripete():
    store, bot, t = run_legend(day=TODAY)
    assert bot.sent == [] and store.kv == {}
    assert "legend" not in store.writes


def test_prima_delle_nove_locali_non_si_manda_niente():
    store, bot, t = run_legend(now=EARLY)
    assert bot.sent == [] and t.boards is None
    assert "legend" not in store.writes
