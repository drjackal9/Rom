import json
from datetime import datetime, timezone

from clashbot import progress, recap
from clashbot.web import app_recap

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
TZ = "Europe/Rome"
UNTIL = progress.period_start(NOW, TZ, recap.PERIOD)
OLD = progress.period_start(datetime(2026, 8, 11, 12, tzinfo=timezone.utc), TZ, recap.PERIOD)
MEMBERS = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}}
IN_SEASON = int(datetime(2026, 8, 15, tzinfo=timezone.utc).timestamp())
BEFORE = int(datetime(2026, 7, 15, tzinfo=timezone.utc).timestamp())
MEDALS = {"#P1": [{"badge": "th", "ts": IN_SEASON}, {"badge": "quiz", "ts": BEFORE}]}


def closed_row(until, score, wins, stars, donated, levels):
    return {"until": until, "since": 0, "score": score, "wins": wins, "war_stars": stars,
            "donated": donated, "levels": levels}


def walked():
    return {
        "#P1": {"name": "Mario",
                "last_month": closed_row(UNTIL, 120, 40, 30, 900, 6)},
        "#P2": {"name": "Luigi",
                "last_month": closed_row(UNTIL, 30, 10, 9, 200, 1)},
        "#P9": {"name": "Fuori", "last_month": closed_row(UNTIL, 999, 99, 99, 999, 9)},
    }


def test_il_riepilogo_prende_la_stagione_appena_chiusa():
    found = recap.build(walked(), MEDALS, MEMBERS, NOW, TZ)
    assert found["season"] == "2026-08"
    assert [row["name"] for row in found["players"]] == ["Mario", "Luigi"]
    assert found["players"][0] == {"tag": "#P1", "name": "Mario", "score": 120, "wins": 40,
                                   "war_stars": 30, "donated": 900, "levels": 6}


def test_le_medaglie_del_riepilogo_sono_solo_quelle_vinte_in_stagione():
    found = recap.build(walked(), MEDALS, MEMBERS, NOW, TZ)
    assert found["medals"] == {"#P1": ["th"]}


def test_finita_la_stagione_dopo_il_riepilogo_vecchio_sparisce():
    stale = {"#P1": {"name": "Mario", "last_month": closed_row(OLD, 120, 40, 30, 900, 6)}}
    assert recap.build(stale, MEDALS, MEMBERS, NOW, TZ) is None
    assert recap.build({}, MEDALS, MEMBERS, NOW, TZ) is None


def test_la_scheda_del_riepilogo_porta_il_mio_posto_e_i_numeri_del_clan():
    page = {"recap": recap.build(walked(), MEDALS, MEMBERS, NOW, TZ)}
    mine = app_recap.view_of(page, {"uid": 777, "tag": "#P1"})
    assert mine["season"] == "2026-08"
    assert mine["me"]["rank"] == 1 and mine["me"]["of"] == 2
    assert mine["me"]["score"] == 120 and mine["me"]["medals"] == ["th"]
    assert mine["clan"] == {"people": 2, "score": 150, "medals": 1,
                            "top": {"name": "Mario", "score": 120}}
    second = app_recap.view_of(page, {"uid": 888, "tag": "#P2"})
    assert second["me"]["rank"] == 2 and second["me"]["medals"] == []


def test_il_riepilogo_di_chi_non_ha_posto_non_porta_nessuno_altro():
    page = {"recap": recap.build(walked(), MEDALS, MEMBERS, NOW, TZ)}
    found = app_recap.view_of(page, {"uid": 999})
    assert found["me"] is None and found["clan"]["people"] == 2
    written = json.dumps(app_recap.view_of(page, {"uid": 777, "tag": "#P1"}), ensure_ascii=False)
    assert "777" not in written and "Luigi" not in written and "#P2" not in written
    assert app_recap.view_of({}, {"uid": 777, "tag": "#P1"}) is None
