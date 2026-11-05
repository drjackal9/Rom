from ..growth import FIELDS, LINES, PERIODS
from ..leaderboards import PODIUM
from ..util import to_int

WEEK = "week"


def _period(page, period):
    return (((page or {}).get("growth") or {}).get("period") or {}).get(period) or {}


def _week(page):
    return _period(page, WEEK)


def _names(page):
    return {row.get("tag"): row.get("name") for row in (page or {}).get("members") or ()}


def climb_rows(page, period=WEEK):
    names = _names(page)
    rows = []
    for tag, row in _period(page, period).items():
        if not names.get(tag):
            continue
        found = {"tag": tag, "name": names[tag]}
        found.update({field: to_int(row.get(field)) for field in FIELDS})
        rows.append(found)
    rows.sort(key=lambda row: (-row["score"], row["name"]))
    return rows[:PODIUM]


def absent_days(page):
    return {row.get("tag"): to_int(row.get("days")) for row in (page or {}).get("idle") or ()}


def ratio(row):
    got = to_int((row or {}).get("received"))
    if not got:
        return None
    return round(to_int((row or {}).get("donations")) / got, 2)


def member_tiles(page):
    away = absent_days(page)
    return [dict(row, absent_days=away.get(row.get("tag"), 0), ratio=ratio(row))
            for row in (page or {}).get("members") or ()]


def chronicle(page):
    rows = [dict(row) for row in (page or {}).get("events") or ()]
    rows.sort(key=lambda row: to_int(row.get("at")), reverse=True)
    return rows


def members_view(page):
    return {"rows": member_tiles(page),
            "climb": {period: climb_rows(page, period) for period in PERIODS},
            "chronicle": chronicle(page),
            "record": dict((page or {}).get("record") or {})}


def rival_for(page, seat):
    mine = str((seat or {}).get("tag") or "")
    rows = (page or {}).get("members") or []
    me = next((row for row in rows if row.get("tag") == mine), None) if mine else None
    if not me:
        return None
    others = [row for row in rows if row.get("linked") and row.get("tag") != mine]
    if not others:
        return None
    near = min(others, key=lambda row: (abs(to_int(row.get("trophies"))
                                            - to_int(me.get("trophies"))),
                                        str(row.get("name") or "")))
    return {"tag": near.get("tag"), "name": near.get("name"),
            "trophies": to_int(near.get("trophies"))}


def growth_of(page, tag):
    grown = (page or {}).get("growth") or {}
    lines = (grown.get("players") or {}).get(tag)
    if not lines:
        return None
    found = {"days": list(grown.get("days") or ())}
    found.update({key: list(lines.get(key) or ()) for key in LINES})
    return found


def villages_of(seat):
    known = (seat or {}).get("villages")
    if known is not None:
        return [{"tag": one.get("tag"), "name": one.get("name"),
                 "verified": bool(one.get("verified"))} for one in known]
    if not (seat or {}).get("tag"):
        return []
    return [{"tag": seat.get("tag"), "name": seat.get("name"),
             "verified": bool(seat.get("verified"))}]


def me_view(page, seat):
    seat = seat or {}
    tag = seat.get("tag")
    return {"tag": tag,
            "name": seat.get("name"),
            "verified": bool(seat.get("verified")),
            "whisper": bool(seat.get("whisper")),
            "avail": seat.get("avail"),
            "lang": seat.get("lang"),
            "goal": seat.get("goal"),
            "profile": ((page or {}).get("profiles") or {}).get(str(seat.get("uid"))),
            "villages": villages_of(seat),
            "growth": growth_of(page, tag),
            "medals": list(((page or {}).get("medals") or {}).get(tag) or ()),
            "period": _week(page).get(tag)}
