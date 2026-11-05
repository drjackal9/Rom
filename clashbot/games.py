from datetime import datetime, timezone

from . import agenda, progress as progress_mod
from .render import card, quote, rank, season_label
from .util import esc

REMIND_BEFORE = 2 * 86400
BOARD_TOP = 25
ZERO_SHOWN = 40


def window(now):
    start, end = agenda.clan_games(now)
    if start <= now < end:
        return start, end
    return None, None


def edition_id(start):
    return start.strftime("%Y-%m")


def ends_at(edition):
    end = (edition or {}).get("end")
    if not end:
        return None
    return datetime.fromtimestamp(float(end), timezone.utc)


def open_edition(progress, members, start, end, record=None):
    base = {tag: values["games"]
            for tag, values in progress_mod.snapshot(progress, members, ("games",)).items()}
    names = {tag: ((progress or {}).get(tag) or {}).get("name") or ((members or {}).get(tag) or {}).get("name")
             for tag in base}
    return {
        "id": edition_id(start), "start": start.timestamp(), "end": end.timestamp(),
        "base": base, "points": {tag: 0 for tag in base}, "names": names,
        "record": record, "reminded": False, "closed": False,
    }


def track(edition, swept):
    base = edition.setdefault("base", {})
    points = edition.setdefault("points", {})
    names = edition.setdefault("names", {})
    for tag, name, counters in swept or ():
        value = int((counters or {}).get("games") or 0)
        if tag not in base:
            base[tag] = value
        if name:
            names[tag] = name
        points[tag] = max(0, value - int(base[tag] or 0))
    return edition


def prune(edition, members):
    keep = set(members or ())
    for key in ("base", "points", "names"):
        stored = edition.get(key) or {}
        for tag in [t for t in stored if t not in keep]:
            del stored[tag]
    return edition


def rows(edition):
    names = (edition or {}).get("names") or {}
    out = [{"tag": tag, "name": names.get(tag) or tag, "points": int(value or 0)}
           for tag, value in ((edition or {}).get("points") or {}).items()]
    out.sort(key=lambda r: (-r["points"], r["name"] or ""))
    return out


def total(edition):
    return sum(int(v or 0) for v in ((edition or {}).get("points") or {}).values())


def digest(edition):
    return "|".join(f"{tag}:{int(value or 0)}"
                    for tag, value in sorted(((edition or {}).get("points") or {}).items()))


def behind(edition):
    return [r for r in rows(edition) if r["points"] <= 0]


def due_reminder(edition, now):
    if not edition or edition.get("reminded") or edition.get("closed"):
        return False
    end = ends_at(edition)
    if not end:
        return False
    return 0 < (end - now).total_seconds() <= REMIND_BEFORE


def best_ever(history):
    best = None
    for entry in history or ():
        top = (entry or {}).get("best") or {}
        points = int(top.get("points") or 0)
        if points and (not best or points > best["points"]):
            best = {"name": top.get("name"), "points": points, "id": entry.get("id")}
    return best


def board_text(L, tz, edition, now=None):
    board = rows(edition)
    scored = [r for r in board if r["points"] > 0]
    zero = [r for r in board if r["points"] <= 0]
    end = ends_at(edition)
    record = (edition or {}).get("record") or None
    limit = int((record or {}).get("points") or 0)
    body = L.t("games.board.total", points=L.n(total(edition)), n=len(scored))
    if end:
        body += "\n" + L.t("games.board.left", left=L.delta(end, now), when=L.when(end, tz))
    if scored:
        body += "\n\n" + quote("\n".join(
            L.t("games.board.row", rank=rank(L, i), name=esc(r["name"]), points=L.n(r["points"]),
                done=L.t("games.board.done") if limit and r["points"] >= limit else "").rstrip()
            for i, r in enumerate(scored[:BOARD_TOP])))
    if zero:
        body += "\n\n" + L.t("games.board.zero", n=len(zero)) + "\n" + quote(
            "   ".join(esc(r["name"]) for r in zero[:ZERO_SHOWN]))
    if record:
        body += "\n\n" + L.t("games.board.record", points=L.n(record["points"]), name=esc(record["name"]))
    return card("🎮", L.t("games.board.title"), body, L.t("games.board.sub"))


def reminder_dm(L, tz, edition, now=None):
    end = ends_at(edition)
    body = L.t("games.reminder.body", left=L.delta(end, now) if end else "?")
    if end:
        body += "\n" + L.t("games.reminder.when", when=L.when(end, tz))
    return card("🎮", L.t("games.reminder.title"), body + "\n\n" + L.t("games.reminder.tail"))


def waiting_card(L, tz, start, history, now=None):
    body = L.t("games.none.body", when=L.when(start, tz), left=L.delta(start, now))
    best = best_ever(history)
    if best:
        body += "\n\n" + L.t("games.board.record", points=L.n(best["points"]), name=esc(best["name"]))
    return card("🎮", L.t("games.none.title"), body)


def record(edition):
    board = [r for r in rows(edition) if r["points"] > 0]
    top = board[0] if board else None
    return {
        "id": edition.get("id"),
        "end": edition.get("end"),
        "total": total(edition),
        "scored": len(board),
        "best": {"name": top["name"], "points": top["points"]} if top else None,
        "members": [{"tag": r["tag"], "name": r["name"], "points": r["points"]} for r in board],
    }


def end_card(L, entry, previous=None, record_before=None):
    body = L.t("games.end.total", points=L.n(entry["total"]), n=entry["scored"])
    if previous:
        delta = int(entry["total"]) - int(previous.get("total") or 0)
        body += "\n" + L.t("games.end.previous", points=L.n(previous.get("total") or 0),
                           delta=("+" if delta >= 0 else "−") + L.n(abs(delta)))
    members = entry.get("members") or []
    if members:
        body += "\n\n" + L.t("games.end.podium") + "\n" + quote("\n".join(
            L.t("games.end.podium_row", rank=rank(L, i), name=esc(r["name"]), points=L.n(r["points"]))
            for i, r in enumerate(members[:3])))
    best = entry.get("best")
    if best and int(best["points"]) > int((record_before or {}).get("points") or 0):
        body += "\n\n" + L.t("games.end.record", name=esc(best["name"]), points=L.n(best["points"]))
    return card("🎮", L.t("games.end.title"), body + "\n\n" + L.t("games.end.tail"),
                season_label(L, entry["id"]))


def albo_card(L, history):
    if not history:
        return card("🎮", L.t("games.albo.title"), L.t("games.albo.empty"))
    lines = []
    for entry in history:
        best = entry.get("best") or {}
        lines.append(L.t("games.albo.row", season=season_label(L, entry.get("id")),
                         total=L.n(entry.get("total") or 0), name=esc(best.get("name") or "—"),
                         points=L.n(best.get("points") or 0)))
    return card("🎮", L.t("games.albo.title"), quote("\n".join(lines)))
