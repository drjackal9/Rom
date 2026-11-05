SEASON = "2026-09"


def cwl_state(**kw):
    state = {
        "season": SEASON,
        "state": "ended",
        "active": False,
        "league": "Crystal League I",
        "clans": {
            "#C1": {"name": "Nostro Clan", "level": 12, "members": [
                {"tag": "#P1", "name": "Mario", "th": 15},
                {"tag": "#P2", "name": "Luigi", "th": 14},
                {"tag": "#P3", "name": "Peach", "th": 13},
            ]},
            "#C2": {"name": "Clan Due", "level": 10, "members": [
                {"tag": "#Q1", "name": "Bowser", "th": 14},
                {"tag": "#Q2", "name": "Wario", "th": 12},
            ]},
        },
        "rounds": [["#W1"], ["#W2"]],
        "our": {"0": "#W1", "1": "#W2"},
        "wars": {
            "#W1": {"state": "warEnded", "endTime": "20260902T100000.000Z",
                    "clan": {"tag": "#C1", "stars": 9, "destr": 90.0},
                    "opponent": {"tag": "#C2", "stars": 6, "destr": 70.0}},
            "#W2": {"state": "warEnded", "endTime": "20260903T100000.000Z",
                    "clan": {"tag": "#C2", "stars": 8, "destr": 85.0},
                    "opponent": {"tag": "#C1", "stars": 8, "destr": 80.0}},
        },
    }
    state.update(kw)
    return state


def war_records():
    return [
        {"kind": "cwl", "day": 1, "endTime": "20260902T100000.000Z", "opponent": "Clan Due",
         "result": "win", "stars": 9, "destr": 90.0, "opp_stars": 6, "opp_destr": 70.0,
         "teamSize": 3, "attacksPerMember": 1, "members": [
             {"tag": "#P1", "name": "Mario", "attacks": [{"stars": 3, "destr": 100.0}], "missed": 0},
             {"tag": "#P2", "name": "Luigi", "attacks": [{"stars": 3, "destr": 100.0}], "missed": 0},
             {"tag": "#P3", "name": "Peach", "attacks": [{"stars": 3, "destr": 100.0}], "missed": 0},
         ]},
        {"kind": "cwl", "day": 2, "endTime": "20260903T100000.000Z", "opponent": "Clan Due",
         "result": "lose", "stars": 8, "destr": 80.0, "opp_stars": 8, "opp_destr": 85.0,
         "teamSize": 3, "attacksPerMember": 1, "members": [
             {"tag": "#P1", "name": "Mario", "attacks": [{"stars": 2, "destr": 80.0}], "missed": 0},
             {"tag": "#P2", "name": "Luigi", "attacks": [], "missed": 1},
         ]},
        {"kind": "war", "day": None, "endTime": "20260905T100000.000Z", "opponent": "Altro",
         "result": "win", "stars": 30, "destr": 100.0, "opp_stars": 10, "opp_destr": 50.0,
         "teamSize": 3, "attacksPerMember": 2, "members": [
             {"tag": "#P1", "name": "Mario", "attacks": [{"stars": 3, "destr": 100.0}], "missed": 1},
         ]},
    ]
