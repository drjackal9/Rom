from datetime import datetime, timezone

from clashbot import trend


def test_day_key_usa_il_fuso_del_clan():
    now = datetime(2026, 9, 13, 23, 30, tzinfo=timezone.utc)
    assert trend.day_key(now, "UTC") == "2026-09-13"
    assert trend.day_key(now, "Asia/Tokyo") == "2026-09-14"
    assert trend.day_key(now, "Marte/Olimpo") == "2026-09-13"


def test_un_campione_al_giorno_l_ultimo_vince():
    state = trend.record({}, "#P1", "Mario", "2026-09-12", 5000, 16, 0)
    state = trend.record(state, "#P1", "Mario", "2026-09-13", 5100, 16, 5100)
    state = trend.record(state, "#P1", "Mario", "2026-09-13", 5150, 16, 5150)
    samples = trend.series(state, "#P1")
    assert [s["d"] for s in samples] == ["2026-09-12", "2026-09-13"]
    assert samples[-1] == {"d": "2026-09-13", "trophies": 5150, "th": 16, "legend": 5150}


def test_la_serie_si_ferma_a_trenta_giorni():
    state = {}
    for day in range(40):
        state = trend.record(state, "#P1", "Mario", f"2026-10-{day:02d}", 5000 + day, 16)
    samples = trend.series(state, "#P1")
    assert len(samples) == trend.DAYS
    assert samples[0]["d"] == "2026-10-10" and samples[-1]["d"] == "2026-10-39"


def test_le_barre_sono_normalizzate_tra_minimo_e_massimo():
    assert trend.bars([]) == ""
    assert trend.bars([5000, 5000, 5000]) == trend.BLOCKS[0] * 3
    drawn = trend.bars([100, 200, 300])
    assert len(drawn) == 3
    assert drawn[0] == trend.BLOCKS[0] and drawn[-1] == trend.BLOCKS[-1]
    assert all(ch in trend.BLOCKS for ch in trend.bars([1, 7, 3, 9, 2]))


def test_move_e_la_differenza_tra_primo_e_ultimo():
    samples = [{"trophies": 5000}, {"trophies": 4800}, {"trophies": 5200}]
    assert trend.move(samples) == 200
    assert trend.move([{"trophies": 5000}]) == 0
    assert trend.move(None) == 0


def test_prune_toglie_chi_non_e_piu_nel_clan():
    state = trend.record({}, "#P1", "Mario", "2026-09-13", 5000, 16)
    state = trend.record(state, "#P9", "Ex", "2026-09-13", 4000, 14)
    assert list(trend.prune(state, ["#P1"])) == ["#P1"]
    assert trend.prune("rotto", ["#P1"]) == {}
    assert trend.series("rotto", "#P1") == []
