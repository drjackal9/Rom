from clashbot import growth, trend

WEEK = {"since": 1}
NOW = {"donated": 40, "war_stars": 5, "levels": 3}


def line(name, days):
    return {"name": name, "days": [{"d": day, "trophies": trophies, "th": th, "legend": 0}
                                   for day, trophies, th in days]}


def test_the_days_are_the_union_and_what_is_missing_stays_empty():
    state = {"#P1": line("Mario", [("2026-09-20", 5000, 16), ("2026-09-21", 5100, 16)]),
             "#P2": line("Luigi", [("2026-09-21", 4000, 15), ("2026-09-22", 4100, 15)])}
    found = growth.growth_of(state, {}, {"#P1": {}, "#P2": {}})
    assert found["days"] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    assert found["players"]["#P1"]["trophies"] == [5000, 5100, None]
    assert found["players"]["#P1"]["th"] == [16, 16, None]
    assert found["players"]["#P2"]["trophies"] == [None, 4000, 4100]
    assert found["clan"]["trophies"] == [5000, 9100, 4100]


def test_who_has_no_days_is_not_in_the_growth():
    state = {"#P1": line("Mario", [("2026-09-20", 5000, 16)])}
    found = growth.growth_of(state, {}, {"#P1": {}, "#P2": {}})
    assert "#P2" not in found["players"] and found["clan"]["trophies"] == [5000]


def test_who_stayed_out_of_the_kept_days_is_not_in_the_growth():
    days = [(f"2026-09-{day:02d}", 5000 + day, 16) for day in range(1, trend.DAYS + 2)]
    state = {"#P1": line("Mario", days), "#P2": line("Luigi", [("2026-09-01", 4000, 15)])}
    found = growth.growth_of(state, {}, {"#P1": {}, "#P2": {}})
    assert "2026-09-01" not in found["days"] and "#P2" not in found["players"]


def test_the_growth_stops_at_the_days_the_trend_keeps():
    days = [(f"2026-09-{day:02d}", 5000 + day, 16) for day in range(1, trend.DAYS + 2)]
    found = growth.growth_of({"#P1": line("Mario", days)}, {}, {"#P1": {}})
    assert len(found["days"]) == trend.DAYS and found["days"][0] == "2026-09-02"
    assert len(found["players"]["#P1"]["trophies"]) == trend.DAYS


def test_the_week_and_the_month_carry_only_the_members():
    state = {"#P1": {"name": "Mario", "week": WEEK, "month": WEEK, "now": NOW},
             "#P9": {"name": "Wario", "week": WEEK, "month": WEEK, "now": NOW}}
    found = growth.growth_of({}, state, {"#P1": {}})
    assert set(found["period"]) == {"week", "month"}
    assert found["period"]["week"] == {"#P1": {"donated": 40, "war_stars": 5, "levels": 3,
                                               "score": 9}}
    assert found["period"]["month"]["#P1"]["war_stars"] == 5


def test_without_anything_the_growth_is_still_a_shape():
    assert growth.growth_of(None, None, None) == {
        "days": [], "players": {}, "clan": {"trophies": []}, "period": {"week": {}, "month": {}}}
