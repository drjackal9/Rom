from ..events import war_result

FULL = 3
ENDED = "warEnded"
PROPOSED = "proposed"
ONGOING = "ongoing"
UPCOMING = "upcoming"


def phase_of(brief, now):
    state = brief.get("state")
    if state == "inWar" and brief.get("end") and brief["end"] <= now:
        return "warEnded"
    return state


def mine_of(ours, seat):
    tag, name = seat.get("tag"), seat.get("name")
    for row in ours:
        if tag and row.get("tag") == tag:
            return row
    for row in ours:
        if name and row.get("name") == name:
            return row
    return None


def last_attack_of(brief, tag):
    for row in brief.get("last_attacks") or ():
        if tag and row.get("tag") == tag:
            return row
    return None


def best_hit(rows):
    found, mark = None, None
    for row in rows:
        for hit in row.get("history") or ():
            score = (int(hit.get("stars") or 0), float(hit.get("destr") or 0))
            if mark is None or score > mark:
                found = {"pos": row.get("pos"), "name": hit.get("name"),
                         "stars": hit.get("stars"), "destr": hit.get("destr")}
                mark = score
    return found


def ended_of(brief, rows):
    us, them = brief.get("us") or {}, brief.get("them") or {}
    sides = {"clan": {"stars": int(us.get("stars") or 0), "destr": float(us.get("destr") or 0)},
             "opponent": {"stars": int(them.get("stars") or 0),
                          "destr": float(them.get("destr") or 0)}}
    return {"result": war_result(sides), "best": best_hit(rows)}


def target_of(rows, tag):
    for row in rows:
        if tag and row.get("assignee_tag") == tag:
            return {"pos": row["pos"], "th": row["th"], "best": row["best"]}
    return None


def war_view(page, seat, now):
    page, seat = page or {}, seat or {}
    brief = page.get("war")
    if not brief:
        return None
    rows = page.get("rows") or []
    ours = page.get("ours") or []
    per_member = int(brief.get("per_member") or 0)
    me = mine_of(ours, seat) if seat.get("tag") else None
    mine = None
    if me:
        left = int(me.get("left") or 0)
        mine = {"pos": me.get("pos"), "th": me.get("th"), "left": left,
                "used": max(0, per_member - left),
                "stars": int(me.get("stars") or 0),
                "destr": round(float(me.get("destr") or 0), 2),
                "target": target_of(rows, seat.get("tag")),
                "last_attack": last_attack_of(brief, seat.get("tag"))}
    phase = phase_of(brief, now)
    return {
        "phase": phase,
        "start": brief.get("start"),
        "end": brief.get("end"),
        "us": brief.get("us"),
        "them": brief.get("them"),
        "size": brief.get("size"),
        "per_member": per_member,
        "mine": mine,
        "ended": ended_of(brief, rows) if phase == ENDED else None,
        "free": [{"pos": row["pos"], "th": row["th"], "best": row["best"]} for row in rows
                 if not row.get("assignee") and int(row.get("best") or 0) < FULL],
        "missing": [{"name": row.get("name"), "left": int(row.get("left") or 0)} for row in ours
                    if int(row.get("left") or 0) > 0],
        "enemy": [{"pos": row["pos"], "th": row["th"], "best": row["best"],
                   "by": row.get("by") or [], "assignee": row.get("assignee"),
                   "history": row.get("history") or [], "note": row.get("note"),
                   "swap_pending": bool(row.get("swap"))} for row in rows],
    }


def next_event(page, now):
    rows = (page or {}).get("agenda") or []
    for row in rows:
        if row.get("state") == ONGOING and int(row.get("end") or 0) > now:
            return row
    for row in rows:
        if row.get("state") == UPCOMING and int(row.get("start") or 0) > now:
            return row
    return None


def duels_for(rows, tag):
    return [{"kind": "duel", "id": duel.get("id"), "rival": duel.get("challenger"),
             "metric": duel.get("metric")}
            for duel in rows or ()
            if duel.get("status") == PROPOSED and duel.get("rival") == tag]


def quiz_for(poll, tag):
    if not poll or not poll.get("open") or tag in (poll.get("answered") or ()):
        return []
    return [{"kind": "quiz", "question": poll.get("question"), "options": poll.get("options")}]


def predictions_for(rows, tag):
    return [{"kind": "prediction", "poll": poll.get("poll"), "options": poll.get("options")}
            for poll in rows or () if tag not in (poll.get("voted") or ())]


def todo_for(page, seat):
    page, seat = page or {}, seat or {}
    games = page.get("games") or {}
    tag = seat.get("tag")
    rows = []
    if tag:
        rows += duels_for(games.get("duels"), tag)
        rows += quiz_for(games.get("quiz"), tag)
        rows += predictions_for(games.get("predictions"), tag)
    if not tag or not seat.get("verified"):
        rows.append({"kind": "link"})
    return rows
