import asyncio
import json
from datetime import datetime, timezone

from clashbot import acts, app_actions, events_registry, guess_attack, i18n, reasons, scoring
from clashbot.db import Clan
from clashbot.web import app_more, app_page, miniapp

NOW = datetime.fromtimestamp(1789000000, timezone.utc)
CLAN = Clan(alias="clan-a1", chat_id=-100, tag="#CLAN1", name="Nostro Clan", active=True,
            failures=0, last_seen=None, bot_alias="bot-1")
CONF = {"lang": "it", "tz": "Europe/Rome"}
RECORD = {
    "kind": "war", "endTime": "20260911T100000.000Z", "opponent": "Clan Nemico",
    "opp_tag": "#ENEMY", "result": "win", "stars": 6, "destr": 90.0,
    "opp_stars": 3, "opp_destr": 40.0, "teamSize": 3, "attacksPerMember": 2,
    "members": [
        {"tag": "#P1", "name": "Mario", "th": 16, "pos": 1, "missed": 0,
         "def": {"stars": 0, "destr": 0, "hits": 0},
         "attacks": [{"stars": 3, "destr": 100, "defender": "#E1", "d_pos": 1, "d_th": 15}]},
        {"tag": "#P2", "name": "Luigi", "th": 14, "pos": 2, "missed": 1,
         "def": {"stars": 2, "destr": 78, "hits": 1},
         "attacks": [{"stars": 1, "destr": 42, "defender": "#E2", "d_pos": 2, "d_th": 14}]},
    ],
}
EMPTY_WAR = dict(RECORD, members=[{"tag": "#P1", "name": "Mario", "th": 16, "pos": 1,
                                   "missed": 2, "def": {"stars": 0, "destr": 0, "hits": 0},
                                   "attacks": []}])
SEATS = {"777": {"tag": "#P1", "name": "Mario", "level": None},
         "888": {"tag": "#P2", "name": "Luigi", "level": None}}


class GuessStore:
    def __init__(self, history=(), state=None, season=None):
        self.history = list(history)
        self.state = {}
        if state is not None:
            self.state[guess_attack.STATE] = state
        if season is not None:
            self.state["season"] = season

    async def recent_wars(self, alias, limit=10):
        return [dict(row) for row in self.history[:limit]]

    async def get_state(self, alias, kind):
        return json.loads(json.dumps(self.state[kind])) if kind in self.state else None

    async def set_state(self, alias, kind, obj):
        self.state[kind] = json.loads(json.dumps(obj))


def act_of(store, body, uid=777, name="Mario", tag="#P1"):
    return acts.Act(store=store, clan=CLAN, conf=CONF, kind="guess.answer", body=body, uid=uid,
                    tag=tag, name=name, level=None, now=NOW, coc=None)


def run(coro):
    return asyncio.run(coro)


def test_la_manche_del_giorno_e_la_stessa_per_tutti_e_cambia_col_giorno():
    day = guess_attack.day_of(NOW, CONF["tz"])
    first = guess_attack.round_for([RECORD], CLAN.alias, day)
    assert first == guess_attack.round_for([RECORD], CLAN.alias, day)
    assert first["day"] == day
    picked = set()
    for other in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"):
        found = guess_attack.round_for([RECORD], CLAN.alias, other)
        picked.add((found["th"], found["d_th"], found["stars"], found["percent"]))
    assert len(picked) > 1


def test_la_manche_non_porta_nomi_ne_tag():
    day = guess_attack.day_of(NOW, CONF["tz"])
    asked = guess_attack.question(guess_attack.round_for([RECORD], CLAN.alias, day))
    raw = json.dumps(asked)
    for secret in ("#P1", "#P2", "#E1", "#E2", "Mario", "Luigi", "#ENEMY", "Clan Nemico"):
        assert secret not in raw
    assert set(asked) == {"day", "th", "d_th"}


def test_senza_guerre_chiuse_non_ce_manche():
    day = guess_attack.day_of(NOW, CONF["tz"])
    assert guess_attack.round_for([], CLAN.alias, day) is None
    assert guess_attack.round_for(None, CLAN.alias, day) is None
    assert guess_attack.round_for([EMPTY_WAR], CLAN.alias, day) is None


def test_i_punti_vengono_dalle_stelle_e_dalla_distanza():
    found = {"day": "2026-09-28", "th": 16, "d_th": 15, "stars": 3, "percent": 100}
    top = guess_attack.SCORE["stars"] + guess_attack.SCORE["percent"][0][1]
    assert guess_attack.points(found, 3, 100) == top
    assert guess_attack.points(found, 3, 0) == guess_attack.SCORE["stars"]
    assert guess_attack.points(found, 0, 100) == guess_attack.SCORE["percent"][0][1]
    assert guess_attack.points(found, 0, 0) == 0
    near, close = guess_attack.SCORE["percent"][0], guess_attack.SCORE["percent"][1]
    assert guess_attack.points(found, 1, 100 - near[0]) == near[1]
    assert guess_attack.points(found, 1, 100 - close[0]) == close[1]


def test_le_risposte_fuori_misura_sono_rifiutate():
    found = {"day": "2026-09-28", "th": 16, "d_th": 15, "stars": 3, "percent": 100}
    state = {}
    assert guess_attack.answer(state, 777, found, 4, 50) is None
    assert guess_attack.answer(state, 777, found, -1, 50) is None
    assert guess_attack.answer(state, 777, found, 2, 101) is None
    assert guess_attack.answer(state, 777, found, 2, -1) is None
    assert state == {}


def test_una_manche_al_giorno_per_persona():
    found = {"day": "2026-09-28", "th": 16, "d_th": 15, "stars": 3, "percent": 100}
    state = {}
    assert guess_attack.answer(state, 777, found, 3, 100) == (guess_attack.SCORE["stars"]
                                                              + guess_attack.SCORE["percent"][0][1])
    assert guess_attack.answer(state, 777, found, 3, 100) is None
    assert guess_attack.answer(state, 888, found, 0, 0) == 0
    later = dict(found, day="2026-09-29")
    assert guess_attack.answer(state, 777, later, 3, 100) is not None
    assert state["day"] == "2026-09-29"


def test_chi_ha_risposto_esce_per_tag_e_solo_del_giorno():
    state = {}
    found = {"day": "2026-09-28", "th": 16, "d_th": 15, "stars": 3, "percent": 100}
    guess_attack.answer(state, 777, found, 3, 100)
    tags = {"777": "#P1", "888": "#P2"}
    assert guess_attack.answered(state, "2026-09-28", tags) == ["#P1"]
    assert guess_attack.answered(state, "2026-09-29", tags) == []


def test_il_titolare_risponde_una_volta_sola_e_prende_i_punti():
    store = GuessStore([RECORD])
    day = guess_attack.day_of(NOW, CONF["tz"])
    real = guess_attack.round_for([RECORD], CLAN.alias, day)
    body = {"stars": str(real["stars"]), "percent": str(real["percent"])}
    assert run(app_actions.guess_answer(act_of(store, body))) is True
    board = scoring.play_board(store.state["season"])
    top = guess_attack.SCORE["stars"] + guess_attack.SCORE["percent"][0][1]
    assert board[0][0] == "777" and board[0][1]["points"] == top
    assert store.state[guess_attack.STATE] == {"day": day, "answers": {"777": top}}
    assert run(app_actions.guess_answer(act_of(store, body))) == reasons.TAKEN
    assert scoring.play_board(store.state["season"])[0][1]["points"] == top


def test_l_attaccante_non_passa_dalla_porta_della_manche():
    store = GuessStore([RECORD])
    bad = {"stars": "9", "percent": "50"}
    assert run(app_actions.guess_answer(act_of(store, bad))) == reasons.BAD
    assert run(app_actions.guess_answer(act_of(store, {"stars": "1",
                                                      "percent": "900"}))) == reasons.BAD
    assert run(app_actions.guess_answer(act_of(store, {"stars": "x",
                                                      "percent": "50"}))) == reasons.BAD
    assert run(app_actions.guess_answer(act_of(store, {}))) == reasons.BAD
    assert guess_attack.STATE not in store.state and "season" not in store.state
    assert run(app_actions.guess_answer(act_of(GuessStore([]), {"stars": "1",
                                                               "percent": "50"}))) == reasons.CLOSED


def test_ogni_rifiuto_della_manche_porta_un_motivo_che_l_app_sa_dire():
    store = GuessStore([RECORD])
    parole = miniapp.denied_words(i18n.locale("en"))
    for body in ({"stars": "9", "percent": "50"}, {}):
        code = run(app_actions.guess_answer(act_of(store, body)))
        assert code in reasons.REASONS and code != reasons.REFUSED
        assert parole["denied_" + code]
    vuoto = run(app_actions.guess_answer(act_of(GuessStore([]), {"stars": "1", "percent": "50"})))
    assert vuoto in reasons.REASONS and vuoto != reasons.REFUSED
    assert parole["denied_" + vuoto]


def test_la_manche_sta_in_coda_una_volta_sola_senza_bersaglio():
    assert acts.MARKS["guess.answer"] == ()
    assert "guess.answer" in acts.NO_MARK


def test_la_porta_accetta_solo_cifre_nella_misura_del_gioco():
    assert "guess.answer" in acts.FIELDS and "guess.answer" in acts.MEMBER_KINDS
    assert set(acts.FIELDS["guess.answer"]) == {"stars", "percent"}
    body = {"kind": "guess.answer", "id": "abc1", "stars": "3", "percent": "40"}
    passed = acts.checked(body, "#P1", 777)
    assert passed["stars"] == "3" and passed["percent"] == "40"
    assert acts.checked(dict(body, stars="9"), "#P1", 777) is None
    assert acts.checked(dict(body, percent="900"), "#P1", 777) is None
    assert acts.checked({"kind": "guess.answer", "id": "abc1", "stars": "3"}, "#P1", 777) is None


def test_la_manche_arriva_all_app_senza_chi_ha_risposto():
    day = guess_attack.day_of(NOW, CONF["tz"])
    store = GuessStore([RECORD])
    run(app_actions.guess_answer(act_of(store, {"stars": "3", "percent": "100"})))
    row = run(app_page.guess_row(store, CLAN, CONF, NOW, {"777": "#P1", "888": "#P2"},
                                 [RECORD]))
    assert row["day"] == day and row["answered"] == ["#P1"]
    page = {"clan": {"name": CLAN.name}, "seats": SEATS, "games": {"guess": row}}
    mine = app_more.view_of(page, {"uid": 777, "tag": "#P1"})["guess"]
    other = app_more.view_of(page, {"uid": 888, "tag": "#P2"})["guess"]
    assert mine == {"th": row["th"], "d_th": row["d_th"], "done": True}
    assert other["done"] is False
    body = miniapp.state_body(page, {"uid": 888, "tag": "#P2", "name": "Luigi"})
    assert "games" not in body
    assert "answered" not in json.dumps(body["more_view"]["guess"])


def test_senza_manche_la_vista_resta_vuota():
    store = GuessStore([])
    assert run(app_page.guess_row(store, CLAN, CONF, NOW, {}, [])) is None
    page = {"clan": {"name": CLAN.name}, "seats": SEATS, "games": {"guess": None}}
    assert app_more.view_of(page, {"uid": 777, "tag": "#P1"})["guess"] is None


def test_la_manche_si_vede_anche_alla_vista_ridotta():
    day = guess_attack.day_of(NOW, CONF["tz"])
    row = dict(guess_attack.question(guess_attack.round_for([RECORD], CLAN.alias, day)),
               answered=[])
    page = {"clan": {"name": CLAN.name}, "seats": SEATS, "games": {"guess": row}}
    seen = app_more.view_of(page, {"uid": 888, "tag": "#P2", "verified": False})["guess"]
    assert seen == {"th": row["th"], "d_th": row["d_th"], "done": False}


def test_il_quiz_resta_nel_repo_ma_parte_spento():
    assert events_registry.EVENTS["challenges.quiz"]["default"] == "off"
    assert "challenges.quiz" in events_registry.EVENTS


def test_le_parole_della_manche_stanno_nei_venti_cataloghi():
    keys = ["web.app.more.guess"] + [f"web.app.guess.{name}" for name in miniapp.GUESS_WORDS]
    for code in i18n.LANGUAGES:
        L = i18n.locale(code)
        for key in keys:
            text = L.t(key)
            assert text and not text.startswith("["), (code, key)
    found = miniapp.words(i18n.locale("it"))
    assert found["more_guess"] and all(found["guess_" + name] for name in miniapp.GUESS_WORDS)
