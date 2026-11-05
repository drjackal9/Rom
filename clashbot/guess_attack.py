import hashlib

from .util import zone

STATE = "guess"
WARS = 1
MOST = 100
STARS = (0, 1, 2, 3)
SCORE = {"stars": 3, "percent": ((5, 3), (15, 2), (30, 1))}
STEP = 2 * SCORE["percent"][0][0]
CHOICES = tuple(range(0, MOST + 1, STEP))


def day_of(now, tz):
    return now.astimezone(zone(tz or "UTC")).strftime("%Y-%m-%d")


def attacks_of(record):
    found = []
    for member in (record or {}).get("members") or ():
        th = member.get("th")
        for hit in member.get("attacks") or ():
            if th and hit.get("d_th"):
                found.append({"th": int(th), "d_th": int(hit["d_th"]),
                              "stars": int(hit.get("stars") or 0),
                              "percent": int(hit.get("destr") or 0)})
    found.sort(key=lambda row: (row["th"], row["d_th"], row["stars"], row["percent"]))
    return found


def round_for(history, alias, day):
    for record in (history or ())[:WARS]:
        found = attacks_of(record)
        if not found:
            continue
        seed = int(hashlib.sha256(f"{alias}:{day}".encode()).hexdigest()[:8], 16)
        return dict(found[seed % len(found)], day=day)
    return None


def question(found):
    if not found:
        return None
    return {"day": found["day"], "th": found["th"], "d_th": found["d_th"]}


def fits(stars, percent):
    return stars in STARS and 0 <= percent <= MOST


def points(found, stars, percent):
    got = SCORE["stars"] if stars == found["stars"] else 0
    gap = abs(percent - found["percent"])
    for limit, value in SCORE["percent"]:
        if gap <= limit:
            return got + value
    return got


def answer(state, uid, found, stars, percent):
    if not found or not fits(stars, percent):
        return None
    if state.get("day") != found["day"]:
        state["day"], state["answers"] = found["day"], {}
    answers = state.setdefault("answers", {})
    if str(uid) in answers:
        return None
    got = points(found, stars, percent)
    answers[str(uid)] = got
    return got


def answered(state, day, tags):
    if (state or {}).get("day") != day:
        return []
    done = (state or {}).get("answers") or {}
    return sorted(tag for uid, tag in (tags or {}).items() if uid in done)


def seat_view(row, tag):
    if not row:
        return None
    return {"th": row.get("th"), "d_th": row.get("d_th"),
            "done": bool(tag) and tag in (row.get("answered") or ())}
