from .cwl import standings
from .events import member_stats
from .util import parse_coc_time

SEASON_WARS = 20


def season_wars(records, season):
    rows = []
    for record in records or []:
        if record.get("kind") != "cwl":
            continue
        end = str(record.get("endTime") or "")
        if len(end) >= 6 and f"{end[:4]}-{end[4:6]}" == season:
            rows.append(record)
    return sorted(rows, key=lambda r: r.get("day") or 0)


def finished(cwl):
    if not cwl:
        return False
    if cwl.get("state") == "ended":
        return True
    rounds = cwl.get("rounds") or []
    our = cwl.get("our") or {}
    wars = cwl.get("wars") or {}
    if not rounds or len(our) < len(rounds):
        return False
    return all((wars.get(tag) or {}).get("state") == "warEnded" for tag in our.values())


def sides(war, our_tag):
    us, them = war.get("clan") or {}, war.get("opponent") or {}
    if us.get("tag") != our_tag:
        us, them = them, us
    return us, them


def result(us, them):
    ours = (us.get("stars") or 0, us.get("destr") or 0.0)
    theirs = (them.get("stars") or 0, them.get("destr") or 0.0)
    if ours > theirs:
        return "win"
    if ours < theirs:
        return "lose"
    return "tie"


def day_results(cwl, our_tag):
    rows = []
    our = (cwl or {}).get("our") or {}
    wars = (cwl or {}).get("wars") or {}
    names = (cwl or {}).get("clans") or {}
    for index in range(len((cwl or {}).get("rounds") or [])):
        war = wars.get(our.get(str(index)))
        if not war or war.get("state") != "warEnded":
            continue
        us, them = sides(war, our_tag)
        rows.append({
            "day": index + 1,
            "opponent": (names.get(them.get("tag")) or {}).get("name"),
            "result": result(us, them),
            "stars": us.get("stars") or 0,
            "destr": us.get("destr") or 0.0,
            "opp_stars": them.get("stars") or 0,
            "opp_destr": them.get("destr") or 0.0,
            "endTime": war.get("endTime"),
        })
    return rows


def member_rows(records, roster=None):
    bonus = set((roster or {}).get("bonus") or ())
    rows = [dict(stats, tag=tag, bonus=tag in bonus) for tag, stats in member_stats(records).items()]
    rows.sort(key=lambda r: (-r["stars"], -r["destr"], r["name"] or ""))
    return rows


def season_record(cwl, our_tag, records, roster=None):
    table = standings((cwl or {}).get("clans") or {}, (cwl or {}).get("wars") or {})
    ours = next((row for tag, row in table if tag == our_tag), {})
    days = day_results(cwl, our_tag)
    return {
        "season": (cwl or {}).get("season"),
        "league": (cwl or {}).get("league"),
        "rank": next((i + 1 for i, (tag, _) in enumerate(table) if tag == our_tag), None),
        "of": len(table),
        "stars": ours.get("stars", 0),
        "destr": ours.get("destr", 0.0),
        "wins": sum(1 for d in days if d["result"] == "win"),
        "losses": sum(1 for d in days if d["result"] == "lose"),
        "ties": sum(1 for d in days if d["result"] == "tie"),
        "days": days,
        "members": member_rows(records, roster),
        "move": None,
    }


def ended_at(record, now):
    for day in reversed(record.get("days") or []):
        end = parse_coc_time(day.get("endTime"))
        if end:
            return end
    return now
