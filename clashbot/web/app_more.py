from .. import guess_attack
from ..more_lists import DUEL_FIELDS, DUEL_SIDES
from . import app_people, payload


def duel_row(duel, mine):
    row = {name: duel.get(name) for name in DUEL_FIELDS}
    sides = [(duel.get(side) or {}) for side in DUEL_SIDES]
    tags = [str(one.get("tag") or "") for one in sides]
    names = [one.get("name") for one in sides]
    if mine and mine in tags:
        row["rival"] = names[0] if tags[1] == mine else names[1]
        row["mate"] = None
    else:
        row["rival"] = names[1]
        row["mate"] = names[0]
    return row


def duel_rows(page, seat):
    mine = str((seat or {}).get("tag") or "")
    return [duel_row(duel, mine) for duel in (page or {}).get(payload.DUELS) or ()
            if isinstance(duel, dict)]


def rivals_of(page, seat):
    mine = str((seat or {}).get("uid") or "")
    rows = [{"tag": (one or {}).get("tag"), "name": (one or {}).get("name")}
            for uid, one in ((page or {}).get("seats") or {}).items()
            if str(uid) != mine and (one or {}).get("tag")]
    rows.sort(key=lambda row: str(row.get("name") or ""))
    return rows


def guess_of(page, seat):
    row = ((page or {}).get("games") or {}).get(guess_attack.STATE)
    return guess_attack.seat_view(row, str((seat or {}).get("tag") or ""))


def view_of(page, seat):
    return {"duels": duel_rows(page, seat), "rivals": rivals_of(page, seat),
            "rival": app_people.rival_for(page, seat), "guess": guess_of(page, seat)}
