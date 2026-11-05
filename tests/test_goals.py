import asyncio
from datetime import datetime, timedelta, timezone

from test_routing import CLAN, FUTURO, MEMBERS, MONDAY, TZ, FakeCoc, routed, setup

from clashbot import boards, feed, goals, hero_caps, i18n, progress, render, trend
from clashbot.achievements import player_snapshot
from clashbot.events_registry import EVENTS

IT = i18n.locale("it")


def snapshot(th=13, trophies=4820, warstars=880, heroes=None):
    return {"name": "Mario", "th": th, "trophies": trophies, "warStars": warstars,
            "heroes": heroes if heroes is not None else {"Barbarian King": 62, "Archer Queen": 71}}


def test_i_tipi_dipendono_da_cosa_ha_il_giocatore():
    assert goals.kinds_for(snapshot()) == ["trophies", "warstars", "th", "hero"]
    assert goals.kinds_for(snapshot(heroes={})) == ["trophies", "warstars", "th"]
    assert goals.kinds_for(None) == []


def test_chi_e_gia_al_municipio_massimo_non_riceve_il_traguardo_municipio():
    top = snapshot(th=hero_caps.TOP_TH, heroes={})
    assert goals.kinds_for(top) == ["trophies", "warstars"]
    assert goals.choices(top, "th") == []


def test_un_eroe_gia_al_tetto_non_fa_comparire_il_tipo_eroe():
    assert goals.kinds_for(snapshot(th=13, heroes={"Barbarian King": 75})) == [
        "trophies", "warstars", "th"
    ]


def test_i_traguardi_dei_trofei_sono_i_prossimi_scalini_da_cinquecento():
    assert [c["target"] for c in goals.choices(snapshot(trophies=4820), "trophies")] == [5000, 5500, 6000]


def test_i_traguardi_delle_stelle_di_guerra_partono_dal_valore_attuale():
    assert [c["target"] for c in goals.choices(snapshot(warstars=880), "warstars")] == [1000, 1500, 2000]


def test_il_traguardo_del_municipio_e_quello_successivo():
    assert goals.choices(snapshot(th=13), "th") == [{"target": 14, "hero": None}]


def test_i_traguardi_eroe_salgono_di_cinque_e_si_fermano_al_tetto_del_municipio():
    picked = goals.choices(snapshot(th=13, heroes={"Barbarian King": 62}), "hero")
    assert picked == [{"target": 65, "hero": "Barbarian King"},
                      {"target": 70, "hero": "Barbarian King"},
                      {"target": 75, "hero": "Barbarian King"}]


def test_un_eroe_gia_al_tetto_non_offre_traguardi():
    assert goals.choices(snapshot(th=13, heroes={"Barbarian King": 75}), "hero") == []


def test_raggiunto_confronta_il_valore_giusto():
    assert goals.reached({"kind": "trophies", "target": 5000}, snapshot(trophies=5000)) is True
    assert goals.reached({"kind": "trophies", "target": 5000}, snapshot(trophies=4999)) is False
    assert goals.reached({"kind": "hero", "hero": "Archer Queen", "target": 75},
                         snapshot(heroes={"Archer Queen": 75})) is True
    assert goals.reached({"kind": "th", "target": 14}, snapshot(th=14)) is True
    assert goals.reached(None, snapshot()) is False
    assert goals.reached({"kind": "boh", "target": 1}, snapshot()) is False


def test_current_legge_il_valore_attuale():
    assert goals.current(snapshot(trophies=4820), {"kind": "trophies"}) == 4820
    assert goals.current(snapshot(heroes={"Archer Queen": 71}), {"kind": "hero", "hero": "Archer Queen"}) == 71
    assert goals.current(None, {"kind": "trophies"}) == 0


def test_gli_eventi_nuovi_sono_nel_pacchetto_membri():
    for event, default in (("members.goal", "group"), ("members.progress", "member_dm")):
        meta = EVENTS[event]
        assert meta["pack"] == "members"
        assert meta["default"] == default
        assert set(meta["allowed"]) == {"group", "topic", "member_dm", "off"}
        assert meta["intensity"] is None


def test_la_carta_dell_obiettivo_dice_traguardo_e_valore_attuale():
    goal = {"kind": "hero", "hero": "Archer Queen", "target": 75}
    text = render.goal_card(IT, "Mario", goal, 71)
    assert IT.t("goal.title") in text and "Mario" in text
    assert IT.t("hero.name.aq") in text and "75" in text and IT.n(71) in text


def test_senza_obiettivo_la_carta_invita_a_sceglierne_uno():
    text = render.goal_card(IT, "Mario", None, 0)
    assert IT.t("goal.none") in text and IT.t("goal.choose_kind") in text


def test_la_carta_del_traguardo_raggiunto_nomina_chi_ce_l_ha_fatta():
    rows = [{"tag": "#P1", "name": "Mario", "goal": {"kind": "trophies", "target": 5000}}]
    text = render.goal_done_card(IT, rows)
    assert IT.t("goal.done.title") in text and IT.t("goal.done.tail") in text
    assert IT.t("goal.done.row", name="Mario", what=IT.t("goal.what.trophies", n=5000)) in text


def test_il_nome_dell_eroe_viene_dal_catalogo_e_ripiega_sull_inglese():
    assert render.hero_name(IT, "Royal Champion") == IT.t("hero.name.rc")
    assert render.hero_name(IT, "Sky Captain") == "Sky Captain"


def test_la_carta_della_settimana_racconta_solo_quello_che_e_successo():
    row = {"loot": 4_000_000, "wins": 12, "levels": 3, "th_up": 1, "games": 0}
    samples = [{"d": "2026-09-01", "trophies": 5000}, {"d": "2026-09-07", "trophies": 5200}]
    text = render.member_week_card(IT, row, samples)
    assert IT.t("week.title") in text and IT.t("week.tail") in text
    assert IT.t("week.farm", loot=render.millions(IT, 4_000_000)) in text
    assert IT.t("week.upgrade", levels=3, th=1) in text
    assert IT.t("week.wins", n=12) in text
    assert IT.t("week.games", n=IT.n(0), count=0) not in text
    assert IT.t("me.trend_up", n=200) in text


def test_una_settimana_senza_niente_da_dire_resta_gentile():
    text = render.member_week_card(IT, {"loot": 0, "wins": 0, "levels": 0, "th_up": 0}, None)
    assert IT.t("week.none") in text and IT.t("week.tail") in text


def sweep_player_json(name="Mario", th=14, trophies=4820, warstars=880, bk=62):
    return {"tag": "#P1", "name": name, "townHallLevel": th, "warStars": warstars,
            "trophies": trophies, "warPreference": "in",
            "achievements": [{"name": "Gold Grab", "value": 10}],
            "heroes": [{"name": "Barbarian King", "level": bk, "village": "home"}]}


def run_sweep(stored=FUTURO, goal=None, trophies=4820):
    coc = FakeCoc({"#P1": sweep_player_json(trophies=trophies)})
    state = {(CLAN.alias, "players"): {"tags": {"#P1": player_snapshot(sweep_player_json())},
                                       "cursor": 0, "out_since": {}}}
    if goal is not None:
        state[(CLAN.alias, "goals")] = {"#P1": goal, "#PX": {"kind": "th", "target": 99}}
    poller, store, bot, t = setup(stored, state=state, coc=coc)
    t.members = {"#P1": MEMBERS["#P1"]}
    asyncio.run(poller.sweep_players(t, per_tick=1))
    asyncio.run(poller.flush(t))
    return store, bot, t


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_il_traguardo_raggiunto_si_festeggia_sulla_bacheca_e_l_obiettivo_si_chiude():
    store, bot, t = run_sweep(goal={"kind": "trophies", "hero": None, "target": 5000}, trophies=5000)
    assert bot.sent == []
    righe = boards.lines_of(t.boards, "members")
    assert any("Mario" in riga for riga in righe)
    assert store.state[(CLAN.alias, "goals")] == {}


def test_l_obiettivo_non_ancora_raggiunto_resta_dov_e():
    goal = {"kind": "trophies", "hero": None, "target": 5000}
    store, bot, t = run_sweep(goal=goal, trophies=4900)
    assert bot.sent == [] and t.boards is None
    assert store.state[(CLAN.alias, "goals")] == {"#P1": goal}


def test_il_capo_puo_portare_il_traguardo_nel_feed_dell_interessato():
    store, bot, t = run_sweep(stored=routed(FUTURO, "members.goal", "member_dm"),
                              goal={"kind": "trophies", "hero": None, "target": 5000}, trophies=5000)
    assert bot.sent == []
    assert any(IT.t("goal.done.title") in text for text in feed_rows(store, 7))


def week_progress():
    previous = MONDAY - timedelta(days=7)
    state = progress.update({}, "#P1", "Mario", {"gold": 0}, previous, TZ)
    state = progress.update(state, "#P1", "Mario", {"gold": 4_000_000, "wins": 12, "levels": 3},
                            previous + timedelta(days=3), TZ)
    return progress.update(state, "#P1", "Mario", {"gold": 4_000_000, "wins": 12, "levels": 3},
                           MONDAY, TZ)


def run_member_report(stored=FUTURO, now=MONDAY, reports=None, state=None):
    base = {(CLAN.alias, "progress"): week_progress(),
            (CLAN.alias, "trend"): trend.record({}, "#P1", "Mario", "2026-09-06", 5000, 14)}
    if reports is not None:
        base[(CLAN.alias, "reports")] = reports
    poller, store, bot, t = setup(stored, state=state if state is not None else base, now=now)
    asyncio.run(poller.member_report(t))
    asyncio.run(poller.flush(t))
    return store, bot


def test_il_riepilogo_settimanale_arriva_nel_feed_di_chi_ha_qualcosa_da_leggere():
    store, bot = run_member_report()
    assert bot.sent == []
    testo = feed_rows(store, 7)[0]
    assert IT.t("week.title") in testo
    assert IT.t("week.farm", loot=render.millions(IT, 4_000_000)) in testo
    assert store.state[(CLAN.alias, "reports")]["member_week"] == "2026-W37"


def test_il_riepilogo_settimanale_non_si_ripete():
    store, bot = run_member_report(reports={"member_week": "2026-W37"})
    assert bot.sent == [] and feed_rows(store, 7) == []


def test_il_rapporto_dei_capi_non_cancella_il_marcatore_del_riepilogo_personale():
    poller, store, bot, t = setup(FUTURO, state={(CLAN.alias, "reports"): {"member_week": "2026-W37"}},
                                  now=MONDAY)
    asyncio.run(poller.leader_report(t))
    assert store.state[(CLAN.alias, "reports")] == {"member_week": "2026-W37", "week": "2026-W37"}


def test_prima_delle_nove_locali_il_riepilogo_non_parte():
    store, bot = run_member_report(now=datetime(2026, 9, 7, 5, tzinfo=timezone.utc))
    assert bot.sent == [] and "reports" not in store.writes


def test_chi_non_ha_fatto_niente_non_riceve_un_messaggio_vuoto():
    poller, store, bot, t = setup(FUTURO, state={}, now=MONDAY)
    asyncio.run(poller.member_report(t))
    asyncio.run(poller.flush(t))
    assert bot.sent == []


def test_l_anello_porta_il_traguardo_e_le_scelte():
    snap = snapshot()
    found = goals.view(snap, {"kind": "trophies", "hero": None, "target": 5000})
    assert found["kind"] == "trophies" and found["target"] == 5000
    assert found["value"] == goals.current(snap, {"kind": "trophies"})
    assert {"kind": "trophies", "hero": None, "target": 5000} in found["picks"]
    assert {"kind": "th", "hero": None, "target": 14} in found["picks"]
    senza = goals.view(snap, None)
    assert senza["kind"] is None and senza["target"] == 0 and senza["picks"] == found["picks"]
    assert goals.view(None, None) is None and goals.view({}, None) is None
