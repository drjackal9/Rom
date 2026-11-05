from ..recap import FIELDS
from ..util import to_int

KEY = "recap"


def place_of(rows, tag):
    for seat, row in enumerate(rows, start=1):
        if row.get("tag") == tag:
            return seat
    return 0


def clan_of(found, rows):
    top = rows[0] if rows else None
    return {"people": len(rows),
            "score": sum(to_int(row.get("score")) for row in rows),
            "medals": sum(len(marks or ()) for marks in (found.get("medals") or {}).values()),
            "top": {"name": top.get("name"), "score": to_int(top.get("score"))} if top else None}


def me_of(found, rows, tag):
    mine = next((row for row in rows if row.get("tag") == tag), None)
    if not mine:
        return None
    me = {name: to_int(mine.get(name)) for name in FIELDS}
    me["rank"] = place_of(rows, tag)
    me["of"] = len(rows)
    me["medals"] = list((found.get("medals") or {}).get(tag) or ())
    return me


def view_of(page, seat):
    found = (page or {}).get(KEY)
    if not found:
        return None
    rows = list(found.get("players") or ())
    return {"season": found.get("season"),
            "me": me_of(found, rows, str((seat or {}).get("tag") or "")),
            "clan": clan_of(found, rows)}
