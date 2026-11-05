def clan_json(members):
    return {
        "tag": "#CLAN1", "name": "Nostro Clan", "clanLevel": 12, "members": len(members),
        "warLeague": {"name": "Crystal League I"},
        "memberList": [
            {"tag": tag, "name": name, "role": role, "townHallLevel": th, "trophies": trophies,
             "donations": don, "donationsReceived": rec}
            for tag, name, role, th, trophies, don, rec in members
        ],
    }


BASE_MEMBERS = [
    ("#P1", "Mario", "leader", 16, 5400, 1200, 300),
    ("#P2", "Luigi", "coLeader", 15, 5100, 800, 900),
    ("#P3", "Peach", "admin", 14, 4700, 400, 100),
    ("#P4", "Toad", "member", 13, 4200, 50, 700),
]


def war_json(state, our_attacks=None, their_attacks=None, end="20260912T100000.000Z", start="20260911T100000.000Z", per_member=2, opp_tag="#ENEMY"):
    our_attacks = our_attacks or {}
    their_attacks = their_attacks or {}

    def side(tag, name, names, attacks, defenders_prefix):
        members = []
        for i, (mtag, mname) in enumerate(names, start=1):
            m = {"tag": mtag, "name": mname, "mapPosition": i, "townhallLevel": 14, "attacks": []}
            for order, (dtag, stars, destr) in enumerate(attacks.get(mtag, []), start=1):
                m["attacks"].append({"attackerTag": mtag, "defenderTag": dtag, "stars": stars,
                                     "destructionPercentage": destr, "order": order})
            members.append(m)
        stars = sum(a["stars"] for m in members for a in m["attacks"])
        count = sum(len(m["attacks"]) for m in members)
        destr = sum(a["destructionPercentage"] for m in members for a in m["attacks"]) / max(1, len(names) * 1)
        return {"tag": tag, "name": name, "stars": stars, "destructionPercentage": destr, "attacks": count, "members": members}

    ours = [("#P1", "Mario"), ("#P2", "Luigi"), ("#P3", "Peach")]
    theirs = [("#E1", "Bowser"), ("#E2", "Wario"), ("#E3", "Waluigi")]
    return {
        "state": state, "teamSize": 3, "attacksPerMember": per_member,
        "preparationStartTime": "20260910T100000.000Z", "startTime": start, "endTime": end,
        "clan": side("#CLAN1", "Nostro Clan", ours, our_attacks, "#E"),
        "opponent": side(opp_tag, "Clan Nemico", theirs, their_attacks, "#P"),
    }
