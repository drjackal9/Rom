import csv
import io

from . import coaching
from .render import REPORT_MISSED
from .scoring import points as season_points
from .warstats import in_window

KINDS = ("wars", "members")
READY_KEY = "export:{alias}:{uid}"
WARS_HEADER = ("ended", "kind", "day", "opponent", "result", "stars", "destruction",
               "opponent_stars", "opponent_destruction", "team_size", "attacks_per_member")
MEMBERS_HEADER = ("tag", "name", "role", "town_hall", "trophies", "donations", "received",
                  "wars", "attacks", "stars", "triples", "missed", "season_points", "activity_score")
GROWN = 5
HEADER_ROWS = 2


def ready_key(alias, uid):
    return READY_KEY.format(alias=alias, uid=int(uid))


def filled(data):
    return data.count(b"\n" if isinstance(data, bytes) else "\n") >= HEADER_ROWS


def _csv(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def _pct(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0


def wars_csv(records):
    rows = [
        (r.get("endTime"), r.get("kind"), r.get("day"), r.get("opponent"), r.get("result"),
         r.get("stars"), _pct(r.get("destr")), r.get("opp_stars"), _pct(r.get("opp_destr")),
         r.get("teamSize"), r.get("attacksPerMember"))
        for r in records or ()
    ]
    return _csv(WARS_HEADER, rows)


def members_csv(members, stats, season, activity):
    scores = {row.get("tag"): row.get("score") or 0 for row in activity or ()}
    entries = (season or {}).get("members") or {}
    rows = []
    for tag, member in sorted((members or {}).items(),
                              key=lambda item: (item[1] or {}).get("name") or ""):
        war = (stats or {}).get(tag) or {}
        entry = entries.get(tag) or {}
        rows.append((tag, (member or {}).get("name"), (member or {}).get("role"),
                     (member or {}).get("th"), (member or {}).get("trophies"),
                     (member or {}).get("donations"), (member or {}).get("received"),
                     war.get("wars", 0), war.get("attacks", 0), war.get("stars", 0),
                     war.get("triples", 0), war.get("missed", 0),
                     season_points(entry) if entry else 0, scores.get(tag, 0)))
    return _csv(MEMBERS_HEADER, rows)


def month_data(records, members, activity, players, start, end):
    wars = in_window(records, start, end)
    missed = {}
    for record in wars:
        for member in record.get("members") or ():
            if member.get("missed"):
                missed[member["name"]] = missed.get(member["name"], 0) + member["missed"]
    since, until = start.timestamp(), end.timestamp()
    arrivals = sorted(
        ((members or {}).get(tag) or {}).get("name") or tag
        for tag, info in coaching.joined(players).items()
        if since <= (info.get("ts") or 0) < until and tag in (members or {})
    )
    return {
        "wars": len(wars),
        "wins": sum(1 for r in wars if r.get("result") == "win"),
        "losses": sum(1 for r in wars if r.get("result") == "lose"),
        "ties": sum(1 for r in wars if r.get("result") == "tie"),
        "stars": sum(r.get("stars") or 0 for r in wars),
        "missed": sorted(missed.items(), key=lambda item: (-item[1], item[0]))[:REPORT_MISSED],
        "arrivals": arrivals,
        "grown": [row for row in activity or () if (row.get("score") or 0) > 0][:GROWN],
    }
