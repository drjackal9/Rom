from . import cwl_roster, cwl_season, cwl_table

ROUNDS = 7
DONE = "done"
LIVE = "live"
NEXT = "next"
OPEN = ("preparation", "inWar")
WAR_STATE = "cwl_war"


def day_rows(cwl, our_tag):
    ended = {row["day"]: row for row in cwl_season.day_results(cwl, our_tag)}
    names = cwl.get("clans") or {}
    our = cwl.get("our") or {}
    wars = cwl.get("wars") or {}
    rows = []
    for number in range(1, ROUNDS + 1):
        closed = ended.get(number)
        if closed:
            rows.append({"n": number, "them": closed["opponent"],
                         "us_stars": int(closed["stars"] or 0),
                         "them_stars": int(closed["opp_stars"] or 0),
                         "result": closed["result"], "state": DONE})
            continue
        war = wars.get(our.get(str(number - 1))) or {}
        us, them = cwl_season.sides(war, our_tag)
        rows.append({"n": number, "them": (names.get(them.get("tag")) or {}).get("name"),
                     "us_stars": int(us.get("stars") or 0),
                     "them_stars": int(them.get("stars") or 0),
                     "result": None,
                     "state": LIVE if war.get("state") in OPEN else NEXT})
    return rows


def table_rows(cwl, our_tag):
    return [{"name": row["name"], "stars": row["stars"],
             "destr": round(float(row["destr"] or 0), 2), "rank": row["rank"]}
            for row in cwl_table.table(cwl, our_tag)]


def attacked_in(war):
    return {tag for tag, member in ((war or {}).get("members") or {}).items()
            if member.get("attacks")}


async def lineup_rows(store, clan, cwl, players):
    state = cwl_roster.for_season(await store.get_state(clan.alias, cwl_roster.STATE),
                                  cwl.get("season"))
    war = await store.get_state(clan.alias, WAR_STATE) or {}
    records = cwl_season.season_wars(
        await store.recent_wars(clan.alias, cwl_season.SEASON_WARS), cwl.get("season"))
    rows = cwl_roster.rows(cwl_roster.registered(cwl, clan.tag), state,
                           cwl_roster.played_days(records, war), records, players)
    bonus = set(cwl_roster.marked(state, cwl_roster.BONUS))
    chosen = set(cwl_roster.picked(state))
    hit = attacked_in(war)
    return [{"tag": row["tag"], "name": row["name"], "th": row["th"],
             "in": row["state"] == cwl_roster.IN, "attacked": row["tag"] in hit,
             "picked": row["tag"] in chosen,
             "bonus": row["tag"] in bonus}
            for row in rows]


async def summary(store, clan, cwl, players):
    if not cwl or clan.tag not in (cwl.get("clans") or {}):
        return None
    days = day_rows(cwl, clan.tag)
    return {
        "season": cwl.get("season"),
        "day": next((row["n"] for row in days if row["state"] == LIVE), None),
        "days": days,
        "lineup": await lineup_rows(store, clan, cwl, players),
        "table": table_rows(cwl, clan.tag),
    }
