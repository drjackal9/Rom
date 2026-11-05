import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import badges, challenges, events_registry, handlers, i18n, render, scoring, settings as settings_mod

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
IT = i18n.locale("it")
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")


class FakeStore:
    def __init__(self, state=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def kv_get(self, key):
        return None


def test_ensure_ripara_e_non_cambia_due_volte():
    base = challenges.ensure(None)
    assert base["v"] == challenges.VERSION
    assert base["duels"] == {"open": [], "done": []} and base["badges"] == {}
    assert challenges.ensure(base) == base
    rotto = {"v": "x", "quiz": [], "duels": {"open": [{"id": "d1"}], "done": []}, "log": "no"}
    fixed = challenges.ensure(rotto)
    assert fixed["quiz"] == challenges.empty()["quiz"]
    assert fixed["duels"]["open"] == [{"id": "d1"}]
    assert fixed["log"] == []
    assert challenges.ensure(fixed) == fixed


def test_ensure_ripara_anche_i_campi_che_nascono_vuoti():
    corrotto = challenges.ensure({"quiz": {"open": "no", "used": "no", "last": 3},
                                  "awards": {"given": "no", "vote": 5},
                                  "duels": {"open": "no", "done": None}})
    assert corrotto["quiz"] == {"open": None, "used": [], "last": None}
    assert corrotto["awards"] == {"given": [], "vote": None}
    assert corrotto["duels"] == {"open": [], "done": []}
    assert challenges.ensure(corrotto) == corrotto


def test_ensure_ripara_anche_missione_e_bingo():
    base = challenges.empty()
    assert challenges.ensure({})["mission"] == base["mission"]
    assert challenges.ensure({})["bingo"] == base["bingo"]
    corrotto = challenges.ensure({"mission": {"week": 38, "goal": "mille", "sent": "no", "best": None},
                                  "bingo": {"cells": 9, "hit": "no", "behind": "forse",
                                            "message_id": "x", "done": 7}})
    assert corrotto["mission"] == base["mission"]
    assert corrotto["bingo"] == base["bingo"]
    vivo = challenges.ensure({"mission": {"week": "2026-W39", "metric": "donated", "best": {"donated": 10}},
                              "bingo": {"done": "w1"}})
    assert vivo["mission"]["week"] == "2026-W39" and vivo["mission"]["best"] == {"donated": 10}
    assert vivo["mission"]["goal"] == 0 and vivo["mission"]["sent"] == []
    assert vivo["bingo"]["done"] == "w1" and vivo["bingo"]["cells"] == []
    assert challenges.ensure(vivo) == vivo


def test_log_tiene_le_ultime_cento_voci_come_le_guerre():
    state = challenges.empty()
    for i in range(150):
        challenges.note(state, "quiz", n=i)
    assert len(state["log"]) == 100
    assert state["log"][0]["n"] == 50 and state["log"][-1] == {"kind": "quiz", "n": 149}


def test_i_badge_nascono_dai_traguardi_gia_rilevati_e_non_si_duplicano():
    state = challenges.empty()
    events = [{"type": "th", "name": "Mario", "level": 16}, {"type": "hero", "name": "Mario", "level": 90},
              {"type": "warstars", "name": "Mario", "value": 1000}]
    assert sorted(badges.from_player_events(state, "#P1", events, 100)) == ["hero", "th", "warstars"]
    assert badges.from_player_events(state, "#P1", events, 200) == []
    assert state["badges"]["#P1"]["th"]["n"] == 2
    assert badges.of(state, "#P1") == ["hero", "th", "warstars"]
    assert badges.line(IT, state, "#P2") == ""
    assert badges.CATALOG["th"] in badges.line(IT, state, "#P1")


def test_i_badge_delle_sfide_si_assegnano_una_volta_per_evento():
    state = challenges.empty()
    assert badges.grant(state, "7", "quiz", 10) is True
    assert badges.grant(state, "7", "quiz", 20) is False
    assert state["badges"]["7"]["quiz"] == {"n": 2, "ts": 20}
    assert badges.grant(state, "7", "inventato", 30) is False
    assert badges.grant_all(state, ["#P1", "#P2", "#P1"], "bingo", 40) == ["#P1", "#P2"]
    assert state["badges"]["#P1"]["bingo"]["n"] == 1
    assert set(badges.CATALOG) >= {"quiz", "veggente", "duello", "missione", "bingo", "ambasciatore"}


def test_le_medaglie_vinte_col_numero_telegram_restano_del_villaggio():
    state = challenges.empty()
    badges.grant(state, "#P1", "th", 10)
    badges.grant(state, 7, "quiz", 20)
    badges.grant(state, 7, "veggente", 30)
    badges.grant(state, 9, "ambasciatore", 40)
    found = badges.by_player(state, ["#P1", "#P2"], owners={"#P1": 7})
    assert [row["badge"] for row in found["#P1"]] == ["quiz", "th", "veggente"]
    assert "#P2" not in found
    assert badges.by_player(state, ["#P1"]) == {"#P1": [{"badge": "th", "ts": 10}]}


def test_una_medaglia_presa_due_volte_conta_la_piu_recente():
    state = challenges.empty()
    badges.grant(state, "#P1", "quiz", 10)
    badges.grant(state, 7, "quiz", 50)
    assert badges.by_player(state, ["#P1"], owners={"#P1": 7}) == {"#P1": [{"badge": "quiz",
                                                                           "ts": 50}]}


def test_settimana_locale_e_uguale_a_quella_del_report():
    assert challenges.week_id(NOW, "Europe/Rome") == NOW.astimezone(challenges.zone("Europe/Rome")).strftime("%G-W%V")
    assert challenges.week_id(NOW, "Fuso/Inventato") == NOW.strftime("%G-W%V")


def test_load_e_save_passano_dallo_stato_cifrato_del_clan():
    store = FakeStore()
    state = asyncio.run(challenges.load(store, CLAN.alias))
    state["quiz"]["used"] = ["w1"]
    asyncio.run(challenges.save(store, CLAN.alias, state))
    assert store.state[(CLAN.alias, challenges.KIND)]["quiz"]["used"] == ["w1"]
    assert asyncio.run(challenges.load(store, CLAN.alias))["v"] == challenges.VERSION


def test_i_punti_di_gioco_entrano_nella_stagione_esistente():
    season = scoring.empty_season("2026-09")
    scoring.apply_play(season, 7, "Alex", "quiz")
    scoring.apply_play(season, 7, "Alex", "duels")
    scoring.apply_play(season, 9, "Toad", "quiz")
    board = scoring.play_board(season)
    assert board[0][0] == "7" and board[0][1]["points"] == 2 * scoring.WEIGHTS["challenge"]
    assert board[0][1]["quiz"] == 1 and board[0][1]["duels"] == 1
    assert [row[1]["name"] for row in board] == ["Alex", "Toad"]
    titles = scoring.titles(season)
    assert titles["Sapiente"][0] == "Alex" and titles["Sfidante"] == ("Alex", 1)
    assert "MVP" not in titles


def test_gli_eventi_delle_sfide_sono_nel_registro_della_fase_sette():
    for name in ("challenges.quiz", "challenges.duel", "challenges.mission", "challenges.bingo",
                 "challenges.award", "challenges.vote", "challenges.badge", "challenges.ambassador"):
        event = events_registry.EVENTS[name]
        assert event["pack"] == "challenges"
        assert event["default"] in event["allowed"]
        assert set(event["allowed"]) <= set(events_registry.DESTINATIONS)
    conf = settings_mod.effective(None, None)
    conf["packs"]["challenges"] = False
    assert settings_mod.route(conf, "challenges.quiz")[0] == "off"


def test_hub_sfide_vuoto_e_con_classifica():
    assert render.play_board_section(IT, scoring.empty_season("2026-09")) is None
    assert "Ancora niente" in render.challenges_view(IT, [None, None])
    season = scoring.empty_season("2026-09")
    scoring.apply_play(season, 7, "Alex", "quiz")
    text = render.challenges_view(IT, [render.play_board_section(IT, season)])
    assert "SFIDE" in text and "Alex" in text and "3" in text


def test_il_comando_sfide_e_registrato_e_mostra_il_hub():
    assert ("challenges", ["sfide"]) in handlers.COMMANDS
    assert "challenges" in handlers.VIEWS
    assert any("challenges" in row for row in handlers.MENU_ROWS)
    store = FakeStore({(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"}})
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": CLAN.bot_alias})
    text, keyboard = asyncio.run(handlers.build_view("challenges", CLAN, context))
    assert "SFIDE" in text and keyboard is not None


def test_il_catalogo_delle_medaglie_dice_come_si_ottengono():
    rows = badges.catalog()
    assert [row["badge"] for row in rows] == list(badges.CATALOG)
    for row in rows:
        assert row["glyph"] == badges.CATALOG[row["badge"]]
        assert row["name"] == "badge.name." + row["badge"]
        assert row["how"] == "badge.how." + row["badge"]
        assert IT.t(row["name"]) and not IT.t(row["name"]).startswith("[")
        assert IT.t(row["how"]) and not IT.t(row["how"]).startswith("[")
