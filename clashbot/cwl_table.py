from .cwl import WIN_BONUS, standings
from .cwl_season import sides


def day_map(cwl):
    out = {}
    wars = (cwl or {}).get("wars") or {}
    for index, tags in enumerate((cwl or {}).get("rounds") or []):
        for war_tag in tags or []:
            war = wars.get(war_tag)
            if not war or war.get("state") != "warEnded":
                continue
            for side in ("clan", "opponent"):
                tag = (war.get(side) or {}).get("tag")
                if not tag:
                    continue
                us, them = sides(war, tag)
                out.setdefault(tag, {})[index + 1] = {
                    "stars": us.get("stars") or 0,
                    "destr": us.get("destr") or 0.0,
                    "win": (us.get("stars") or 0, us.get("destr") or 0.0)
                    > (them.get("stars") or 0, them.get("destr") or 0.0),
                }
    return out


def table(cwl, our_tag):
    days = day_map(cwl)
    rows = []
    for i, (tag, row) in enumerate(standings((cwl or {}).get("clans") or {},
                                             (cwl or {}).get("wars") or {})):
        rows.append({
            "rank": i + 1, "tag": tag, "name": row["name"], "stars": row["stars"],
            "wins": row["wins"], "destr": row["destr"], "played": row["played"],
            "days": days.get(tag, {}), "us": tag == our_tag,
        })
    return rows


def projection(rows, total_rounds, team_size):
    total = total_rounds or 0
    step = (team_size or 0) * 3 + WIN_BONUS
    ceiling = {r["tag"]: r["stars"] + max(0, total - r["played"]) * step for r in rows}
    out = []
    for row in rows:
        mine = ceiling[row["tag"]]
        best = 1 + sum(1 for o in rows if o["tag"] != row["tag"] and o["stars"] > mine)
        worst = 1 + sum(1 for o in rows
                        if o["tag"] != row["tag"] and ceiling[o["tag"]] >= row["stars"])
        out.append({**row, "left": max(0, total - row["played"]), "best": best, "worst": worst})
    return out


def league_order(data):
    order = {}
    for item in (data or {}).get("items") or []:
        name, league_id = item.get("name"), item.get("id")
        if name and isinstance(league_id, int):
            order[name] = league_id
    return order


def snapshot(cwl, record):
    return {
        "season": record.get("season"),
        "league": record.get("league"),
        "ranks": {tag: i + 1 for i, (tag, _) in enumerate(
            standings((cwl or {}).get("clans") or {}, (cwl or {}).get("wars") or {}))},
    }


def observe(last, leagues, order):
    ranks = (last or {}).get("ranks") or {}
    before = (order or {}).get((last or {}).get("league"))
    if before is None or not ranks:
        return None
    up, down = [], []
    for tag, rank in ranks.items():
        after = (order or {}).get((leagues or {}).get(tag))
        if after is None or not rank:
            continue
        if after > before:
            up.append(rank)
        elif after < before:
            down.append(rank)
    if not up and not down:
        return None
    return {"promote": max(up) if up else 0, "demote": min(down) if down else 0}


def move_of(before, after, order):
    a, b = (order or {}).get(before), (order or {}).get(after)
    if a is None or b is None:
        return None
    return "up" if b > a else "down" if b < a else "same"


def zone(rank, entry):
    if not entry or not rank:
        return None
    promote, demote = entry.get("promote") or 0, entry.get("demote") or 0
    if promote and rank <= promote:
        return "up"
    if demote and rank >= demote:
        return "down"
    return "safe" if promote and demote else None
