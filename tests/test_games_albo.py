import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import agenda, boards, games, handlers, i18n, settings as settings_mod
from clashbot.events_registry import EVENTS
from test_games_live import (OUTSIDE, SETTINGS, Store, counters, next_tick, run_games, setup,
                             stored_edition)
from test_routing import CLAN, FUTURO

L = i18n.locale("it")
TZ = "Europe/Rome"
INSIDE = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)
AFTER = datetime(2026, 9, 29, 10, tzinfo=timezone.utc)
NEXT = datetime(2026, 10, 23, 10, tzinfo=timezone.utc)


def closed_edition():
    start, end = games.window(INSIDE)
    e = games.open_edition({"#P1": {"name": "Mario", "now": {"games": 1000}},
                            "#P2": {"name": "Luigi", "now": {"games": 500}}},
                           {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}}, start, end)
    games.track(e, [("#P1", "Mario", {"games": 5000}), ("#P2", "Luigi", {"games": 1500})])
    return e


def test_record_dell_edizione():
    entry = games.record(closed_edition())
    assert entry["id"] == "2026-09" and entry["total"] == 5000 and entry["scored"] == 2
    assert entry["best"] == {"name": "Mario", "points": 4000}
    assert [m["name"] for m in entry["members"]] == ["Mario", "Luigi"]


def test_card_di_chiusura_confronta_e_festeggia_il_record():
    entry = games.record(closed_edition())
    text = games.end_card(L, entry, {"total": 3000}, {"name": "Peach", "points": 3500})
    assert "Mario" in text and "5.000" in text
    assert L.t("games.end.record").split("{")[0] in text
    senza = games.end_card(L, entry, None, {"name": "Peach", "points": 9000})
    assert L.t("games.end.record").split("{")[0] not in senza
    assert L.t("games.end.previous").split("{")[0] not in senza


def test_albo_elenca_le_edizioni():
    history = [games.record(closed_edition()), {"id": "2026-08", "total": 3000,
                                                "best": {"name": "Peach", "points": 3500}}]
    text = games.albo_card(L, history)
    assert "Mario" in text and "Peach" in text
    assert L.t("games.albo.empty") in games.albo_card(L, [])


def test_fuori_dalla_finestra_si_vede_quando_riaprono():
    assert games.window(AFTER) == (None, None)
    start, _ = agenda.clan_games(AFTER)
    text = games.waiting_card(L, TZ, start, [games.record(closed_edition())], AFTER)
    assert L.t("games.none.title") in text and "Mario" in text


def test_best_ever_sceglie_il_massimo_registrato():
    history = [{"id": "2026-09", "best": {"name": "Mario", "points": 4000}},
               {"id": "2026-08", "best": {"name": "Peach", "points": 4500}}]
    assert games.best_ever(history) == {"name": "Peach", "points": 4500, "id": "2026-08"}
    assert games.best_ever([]) is None


def test_la_chiusura_e_un_evento_del_pacchetto_della_capitale():
    assert EVENTS["games.end"]["pack"] == "capital_games"
    assert "member_dm" not in EVENTS["games.end"]["allowed"]
    conf = settings_mod.effective(FUTURO, None)
    assert settings_mod.route(conf, "games.end") == ("group", None)


def test_la_finestra_finita_chiude_l_edizione_una_volta_sola():
    poller, store, bot, t = setup()
    run_games(poller, t, [("#P1", "Mario", counters(16000))])
    assert bot.pins == [101]
    dopo = next_tick(t, OUTSIDE)
    run_games(poller, dopo)
    assert stored_edition(store) is None and bot.pins == [101]
    assert [(kind, key) for _, kind, key, _, _ in store.stats] == [("games", "2026-09")]
    entry = store.stats[0][4]
    assert entry["total"] == 4000 and entry["best"] == {"name": "Mario", "points": 4000}
    assert store.stats[0][3] == games.window(INSIDE)[1]
    testi = [line for line in boards.lines_of(dopo.boards, "capital_games")
             if L.t("games.end.total", points=L.n(4000), n=1) in line]
    assert len(testi) == 1 and "Mario" in testi[0]
    ancora = next_tick(t, OUTSIDE + timedelta(hours=1))
    run_games(poller, ancora)
    assert len([line for line in boards.lines_of(ancora.boards, "capital_games")
                if L.t("games.end.total", points=L.n(4000), n=1) in line]) == 1
    assert len(store.stats) == 1


def test_un_edizione_senza_punti_resta_nello_storico_senza_annuncio():
    poller, store, bot, t = setup()
    run_games(poller, t)
    dopo = next_tick(t, OUTSIDE)
    run_games(poller, dopo)
    assert dopo.chunks == []
    assert [key for _, _, key, _, _ in store.stats] == ["2026-09"]
    assert store.stats[0][4]["total"] == 0 and store.stats[0][4]["members"] == []
    assert stored_edition(store) is None


def test_una_nuova_edizione_chiude_quella_rimasta_aperta():
    poller, store, bot, t = setup()
    run_games(poller, t, [("#P1", "Mario", counters(16000))])
    ottobre = next_tick(t, NEXT)
    run_games(poller, ottobre, [("#P1", "Mario", counters(16000))])
    assert [key for _, _, key, _, _ in store.stats] == ["2026-09"]
    assert stored_edition(store)["id"] == "2026-10"
    assert stored_edition(store)["record"] == {"name": "Mario", "points": 4000, "id": "2026-09"}
    assert len([line for line in boards.lines_of(ottobre.boards, "capital_games")
                if L.t("games.end.total", points=L.n(4000), n=1) in line]) == 1


def view(monkeypatch, key, state, now, history=()):
    monkeypatch.setattr(handlers, "now_utc", lambda: now)
    context = SimpleNamespace(bot_data={"store": Store(state=state, history=history),
                                        "coc": None, "bot_alias": "bot-1"})
    return asyncio.run(handlers.build_view(key, CLAN, context))


def datas_of(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_la_vista_dei_giochi_ha_le_schede_e_l_albo(monkeypatch):
    history = [games.record(closed_edition())]
    text, keyboard = view(monkeypatch, "games:albo", dict(SETTINGS), OUTSIDE, history)
    assert L.t("games.albo.title") in text and "Mario" in text
    datas = datas_of(keyboard)
    assert datas[:2] == ["v:games", "v:games:albo"] and datas[-1] == "v:games:albo"
    assert all(len(d.encode()) <= 64 for d in datas)
    attesa, tastiera = view(monkeypatch, "games", dict(SETTINGS), OUTSIDE, history)
    assert L.t("games.none.title") in attesa and "Mario" in attesa
    assert datas_of(tastiera)[-1] == "v:games"


def test_l_albo_si_apre_anche_con_l_edizione_in_corso(monkeypatch):
    aperta = games.open_edition({"#P1": {"name": "Mario", "now": {"games": 1000}}},
                                {"#P1": {"name": "Mario"}}, *games.window(INSIDE))
    state = dict(SETTINGS) | {(CLAN.alias, "games"): aperta}
    text, _ = view(monkeypatch, "games:albo", state, INSIDE, [games.record(closed_edition())])
    assert L.t("games.albo.title") in text and L.t("games.board.title") not in text
    diretta, _ = view(monkeypatch, "games", state, INSIDE, [games.record(closed_edition())])
    assert L.t("games.board.title") in diretta
