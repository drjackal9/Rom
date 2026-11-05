EMPTY_TAG = "#0"
WIN_BONUS = 10


def group_summary(group_json):
    return {
        "state": group_json.get("state"),
        "season": group_json.get("season"),
        "clans": {
            c.get("tag"): {
                "name": c.get("name"),
                "level": c.get("clanLevel"),
                "members": [
                    {"tag": m.get("tag"), "name": m.get("name"), "th": m.get("townHallLevel")}
                    for m in c.get("members") or [] if m.get("tag")
                ],
            }
            for c in group_json.get("clans", [])
            if c.get("tag")
        },
        "rounds": [
            [t for t in r.get("warTags", []) if t and t != EMPTY_TAG]
            for r in group_json.get("rounds", [])
        ],
    }


def war_summary(war_json):
    clan = war_json.get("clan") or {}
    opp = war_json.get("opponent") or {}
    return {
        "state": war_json.get("state"),
        "endTime": war_json.get("endTime"),
        "clan": {"tag": clan.get("tag"), "stars": clan.get("stars", 0) or 0, "destr": clan.get("destructionPercentage", 0) or 0},
        "opponent": {"tag": opp.get("tag"), "stars": opp.get("stars", 0) or 0, "destr": opp.get("destructionPercentage", 0) or 0},
    }


def standings(clans, wars):
    table = {tag: {"name": info.get("name"), "stars": 0, "wins": 0, "destr": 0.0, "played": 0} for tag, info in clans.items()}
    for war in wars.values():
        if war.get("state") != "warEnded":
            continue
        a, b = war["clan"], war["opponent"]
        for side, other in ((a, b), (b, a)):
            row = table.get(side["tag"])
            if not row:
                continue
            row["played"] += 1
            row["stars"] += side["stars"]
            row["destr"] += side["destr"]
            if (side["stars"], side["destr"]) > (other["stars"], other["destr"]):
                row["wins"] += 1
                row["stars"] += WIN_BONUS
    return sorted(table.items(), key=lambda kv: (-kv[1]["stars"], -kv[1]["destr"], kv[1]["name"] or ""))


def current_round(rounds, our, wars):
    current = None
    for index in range(len(rounds)):
        tag = our.get(str(index))
        if not tag:
            continue
        state = (wars.get(tag) or {}).get("state")
        if state in ("preparation", "inWar"):
            return index
        if state == "warEnded":
            current = index
    return current
