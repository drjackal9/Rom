import hashlib
import json

from ..events import ROLE_ORDER
from ..leaderboards import TOP, climbers, closed_trophy_rows
from ..media import BADGE_HOST, host
from ..recruit import requirement
from ..scoring import leaderboard
from ..targets import attacks_left, plan_rows
from ..util import CLAN_SLOTS, parse_coc_time
from ..warstats import hall_state

VERSION = 1
PUBLIC = "public"
APP = "app"
MANAGE = "manage"
TOOLS = "tools"
DUELS = "duels"
SERVICES = ("bot", "poller", "db", "clash", "web")
LATE_ROUNDS = 2
SLUG_LEN = 16
STATES = ("up", "degraded", "down")
REFRESH = 600
EXTRAS = ("widget", "ics")
VOLATILE = ("updated", "ics")
MARK = "mark"
VIEWS = "views"


def slug_for(vault, clan_alias):
    return vault.blind("slug", clan_alias)[:SLUG_LEN]


def mark_for(vault, slug, uid):
    return vault.blind(MARK, f"{slug}:{int(uid)}")[:SLUG_LEN]


def digest(payload):
    body = {key: value for key, value in (payload or {}).items() if key not in VOLATILE}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:32]


def _three(good, some):
    if good:
        return "up"
    return "degraded" if some else "down"


def services_note(now, beat_age, interval, db_ok, keys_alive, keys_total, running, wanted):
    interval = max(1, int(interval or 1))
    return {
        "v": VERSION,
        "updated": int(now.timestamp()),
        "interval": interval,
        "services": [
            {"name": "bot", "state": _three(running >= wanted, running)},
            {"name": "poller", "state": _three(beat_age <= interval * LATE_ROUNDS,
                                                beat_age <= interval * (LATE_ROUNDS + 1))},
            {"name": "db", "state": _three(bool(db_ok), False)},
            {"name": "clash", "state": _three(keys_total and keys_alive >= keys_total, keys_alive)},
        ],
    }


def status_body(note, now):
    services = []
    checked = 0
    if isinstance(note, dict) and isinstance(note.get("services"), list):
        checked = int(note.get("updated") or 0)
        interval = max(1, int(note.get("interval") or 60))
        stale = int(now.timestamp()) - checked > interval * (LATE_ROUNDS + 1)
        for service in note["services"]:
            state = service.get("state")
            services.append({
                "name": service.get("name"),
                "state": "down" if stale or state not in STATES else state,
            })
    if not services:
        services = [{"name": name, "state": "down"} for name in SERVICES if name != "web"]
    services.append({"name": "web", "state": "up"})
    worst = "up"
    for service in services:
        if service["state"] == "down":
            worst = "down"
            break
        if service["state"] == "degraded":
            worst = "degraded"
    return {"state": worst, "checked": checked, "services": services}


def stamp(value):
    when = parse_coc_time(value) if isinstance(value, str) else value
    try:
        return int(when.timestamp())
    except AttributeError:
        return 0


def _side(side):
    return {
        "name": (side or {}).get("name"),
        "stars": int((side or {}).get("stars") or 0),
        "destr": round(float((side or {}).get("destr") or 0), 2),
        "attacks": int((side or {}).get("attacks") or 0),
    }


def war_brief(war, kind, day):
    if not war or war.get("state") in (None, "notInWar"):
        return None
    return {
        "kind": kind,
        "day": day,
        "state": war.get("state"),
        "size": war.get("teamSize"),
        "per_member": int(war.get("attacksPerMember") or 2),
        "start": stamp(war.get("startTime")),
        "end": stamp(war.get("endTime")),
        "us": _side(war.get("clan")),
        "them": _side(war.get("opponent")),
    }


def attack_score(member):
    attacks = (member or {}).get("attacks") or ()
    if not attacks:
        return 0, 0.0
    stars = sum(int(one.get("stars") or 0) for one in attacks)
    destr = sum(float(one.get("destr") or 0) for one in attacks) / len(attacks)
    return stars, round(destr, 2)


def last_attacks(war):
    rows = []
    for tag, member in ((war or {}).get("members") or {}).items():
        attacks = member.get("attacks") or ()
        if not attacks:
            continue
        last = max(attacks, key=lambda one: int(one.get("order") or 0))
        rows.append({"tag": tag, "stars": int(last.get("stars") or 0),
                     "destr": round(float(last.get("destr") or 0), 2),
                     "at": int(last.get("order") or 0)})
    rows.sort(key=lambda row: -row["at"])
    return rows


def member_rows(members, links=None, avail=None):
    rows = []
    for tag, member in (members or {}).items():
        row = {
            "name": member.get("name"),
            "role": member.get("role"),
            "th": int(member.get("th") or 0),
            "trophies": int(member.get("trophies") or 0),
            "donations": int(member.get("donations") or 0),
            "received": int(member.get("received") or 0),
        }
        if links is not None or avail is not None:
            known = (links or {}).get(tag)
            row["tag"] = tag
            row["linked"] = known is not None
            row["verified"] = bool((known or {}).get("verified"))
            row["avail"] = (avail or {}).get(tag)
        rows.append(row)
    rows.sort(key=lambda row: (ROLE_ORDER.get(row["role"], 9), -row["trophies"], row["name"] or ""))
    return rows


def event_rows(items):
    return [
        {"key": item.get("key"), "state": item.get("state"),
         "start": stamp(item.get("start")), "end": stamp(item.get("end"))}
        for item in items or ()
    ]


def points_rows(season):
    if not isinstance((season or {}).get("members"), dict):
        return []
    rows = [{"name": entry.get("name"), "value": value}
            for _, entry, value in leaderboard(season) if value > 0 and entry.get("name")]
    return rows[:TOP]


def climb_rows(boards_state, members, hidden):
    rows = [row for row in closed_trophy_rows(boards_state, members)
            if row.get("tag") not in (hidden or ())]
    found = []
    for row in climbers(rows):
        name = ((members or {}).get(row.get("tag")) or {}).get("name")
        if name:
            found.append({"name": name, "value": int(row.get("delta") or 0)})
    return found


def stat_rows(season, hall, boards_state=None, members=None, hidden=None):
    seasons = hall_state(hall).get("seasons") or []
    titles = (seasons[-1].get("titles") or {}) if seasons else {}
    return {
        "points": points_rows(season),
        "hall": [{"kind": kind, "name": name, "value": value}
                 for kind, (name, value) in list(titles.items())[:TOP]],
        "climb": climb_rows(boards_state, members, hidden),
    }


def badge_of(url):
    return str(url) if url and host(url) == BADGE_HOST else None


def free_seats(info):
    try:
        taken = int((info or {}).get("members") or 0)
    except (TypeError, ValueError):
        taken = 0
    return max(0, CLAN_SLOTS - taken)


def war_record(hall):
    records = hall_state(hall).get("records") or {}
    return {"wars": int(records.get("wars") or 0), "wins": int(records.get("wins") or 0)}


def public_payload(clan, conf, info, war, kind, day, hall, items, now,
                   ics_text=None, bot=None, code=None):
    web = dict(conf.get("web") or {})
    info = info or {}
    return {
        "v": VERSION,
        "updated": int(now.timestamp()),
        "lang": conf.get("lang") or "en",
        "tz": conf.get("tz") or "UTC",
        "clan": {
            "name": clan.name,
            "tag": clan.tag,
            "level": info.get("level"),
            "league": info.get("league"),
            "points": info.get("points"),
            "wins": info.get("wins"),
            "streak": info.get("streak"),
            "members": info.get("members"),
            "badge": badge_of(info.get("badge")),
        },
        "free": free_seats(info),
        "min_th": requirement(conf),
        "record": war_record(hall),
        "bot": str(bot) if bot else None,
        "code": str(code) if code else None,
        "war": war_brief(war, kind, day),
        "events": event_rows(items),
        "extras": {field: bool(web.get(field)) for field in EXTRAS},
        "ics": ics_text if web.get("ics") else None,
    }


def manager_payload(screens):
    return {str(uid): dict(found) for uid, found in (screens or {}).items() if found}


def screen_of(text, markup):
    lines = [] if markup is None else [
        [{"label": button.text, "data": button.callback_data}
         for button in line if button.callback_data]
        for line in markup.inline_keyboard
    ]
    return {"text": text, "buttons": [line for line in lines if line]}


def plan_and_ours(war, plan, brief):
    rows, ours = [], []
    if not brief:
        return rows, ours
    brief["last_attacks"] = last_attacks(war)
    for row in plan_rows(war, plan):
        rows.append({"pos": row["pos"], "name": row["name"], "th": row["th"],
                     "best": row["best"], "by": row["by"][:3], "assignee": row["assignee"],
                     "assignee_tag": row["assignee_tag"], "history": row["history"],
                     "note": row["note"], "swap": row["swap"]})
    for tag, member in sorted((war.get("members") or {}).items(),
                              key=lambda pair: pair[1].get("pos") or 99):
        stars, destr = attack_score(member)
        ours.append({"pos": member.get("pos"), "name": member.get("name"), "tag": tag,
                     "th": member.get("th"), "left": attacks_left(war, tag),
                     "stars": stars, "destr": destr})
    return rows, ours


def app_payload(clan, conf, info, members, war, kind, day, plan, seats, sections, profiles, now,
                manage=None, tools=None, agenda=(), wars=(), last_war=None, games=None,
                cwl=None, links=None, avail=None, record=None, growth=None, medals=None,
                bases=None, recruit=None, family=None, award=None, duels=None, accent=None,
                advice=None, attack_videos=None, events=None, idle=None, recap=None,
                door=None, badge=None, views=None):
    brief = war_brief(war, kind, day)
    rows, ours = plan_and_ours(war, plan, brief)
    info = info or {}
    found = {
        "v": VERSION,
        "updated": int(now.timestamp()),
        "lang": conf.get("lang") or "en",
        "tz": conf.get("tz") or "UTC",
        "clan": {"name": clan.name, "level": info.get("level"), "league": info.get("league"),
                 "members": info.get("members"), "accent": accent, "badge": badge_of(badge)},
        "war": brief,
        "rows": rows,
        "ours": ours,
        "members": member_rows(members, links or {}, avail or {}),
        "record": dict(record or {}),
        "growth": dict(growth or {}),
        "medals": {tag: list(marks) for tag, marks in (medals or {}).items()},
        "sections": {pack: list(lines) for pack, lines in (sections or {}).items()},
        "events": [dict(row) for row in events or ()],
        "idle": [dict(row) for row in idle or ()],
        "recap": dict(recap) if recap else None,
        "seats": dict(seats or {}),
        "profiles": dict(profiles or {}),
        "agenda": [dict(row) for row in agenda or ()],
        "wars": [dict(row) for row in wars or ()],
        "last_war": last_war,
        "games": games,
        "cwl": cwl,
        "advice": dict(advice or {}),
        "attack_videos": dict(attack_videos or {}),
        "bases": dict(bases or {}),
        "recruit": dict(recruit or {}),
        "family": dict(family) if family else None,
        "award": dict(award) if award else None,
        DUELS: [dict(row) for row in duels or ()],
        MANAGE: manager_payload(manage),
        TOOLS: dict(tools or {}),
        VIEWS: dict(views or {}),
    }
    if door is not None:
        found.update({key: value for key, value in door.items()})
    return found
