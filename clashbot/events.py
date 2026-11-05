from .util import now_utc, parse_coc_time
from .warstats import war_defense

ROLE_ORDER = {"leader": 0, "coLeader": 1, "admin": 2, "member": 3}
ROLE_ICONS = {"leader": "👑", "coLeader": "🛡", "admin": "⚔️", "member": "👤"}
REMINDER_CHECKPOINTS = [28800, 14400, 3600]
JOIN = "join"
WAR_END = "war_end"
MOVEMENT_KINDS = (JOIN, "leave", "promote", "demote", "rename")
EVENT_KINDS = MOVEMENT_KINDS + (WAR_END,)


def member_snapshot(clan_json):
    members = {}
    for m in clan_json.get("memberList", []):
        tag = m.get("tag")
        if not tag:
            continue
        members[tag] = {
            "name": m.get("name"),
            "role": m.get("role"),
            "th": m.get("townHallLevel"),
            "trophies": m.get("trophies"),
            "bb": m.get("builderBaseTrophies"),
            "donations": m.get("donations"),
            "received": m.get("donationsReceived"),
        }
    return members


def member_events(old, new):
    events = []
    for tag in sorted(new.keys() - old.keys()):
        m = new[tag]
        events.append({"type": "join", "tag": tag, "name": m["name"], "th": m.get("th"), "trophies": m.get("trophies")})
    for tag in sorted(old.keys() - new.keys()):
        events.append({"type": "leave", "tag": tag, "name": old[tag]["name"]})
    for tag in sorted(new.keys() & old.keys()):
        old_name, new_name = old[tag].get("name"), new[tag].get("name")
        if old_name and new_name and old_name != new_name:
            events.append({"type": "rename", "tag": tag, "old": old_name, "name": new_name})
        old_role, new_role = old[tag].get("role"), new[tag].get("role")
        if old_role and new_role and old_role != new_role:
            up = ROLE_ORDER.get(new_role, 9) < ROLE_ORDER.get(old_role, 9)
            events.append({
                "type": "promote" if up else "demote",
                "name": new[tag]["name"],
                "role": new_role,
            })
    return events


def member_facts(events):
    return [{"kind": row.get("type"), "who": row.get("name"),
             "n": row.get("th") if row.get("type") == JOIN else None}
            for row in events or () if row.get("type") in MOVEMENT_KINDS]


def war_end_fact(war):
    return {"kind": WAR_END, "who": ((war or {}).get("opponent") or {}).get("name"),
            "n": ((war or {}).get("clan") or {}).get("stars")}


def orient_war(war_json, our_tag):
    if not war_json or not our_tag:
        return war_json
    clan_tag = (war_json.get("clan") or {}).get("tag")
    opp_tag = (war_json.get("opponent") or {}).get("tag")
    if opp_tag == our_tag and clan_tag != our_tag:
        swapped = dict(war_json)
        swapped["clan"], swapped["opponent"] = war_json["opponent"], war_json["clan"]
        return swapped
    return war_json


def _side_members(side):
    members = {}
    for m in side.get("members", []):
        tag = m.get("tag")
        if not tag:
            continue
        members[tag] = {
            "name": m.get("name"),
            "pos": m.get("mapPosition"),
            "th": m.get("townhallLevel"),
            "attacks": [
                {
                    "stars": a.get("stars", 0),
                    "destr": a.get("destructionPercentage", 0),
                    "defender": a.get("defenderTag"),
                    "order": a.get("order", 0),
                }
                for a in m.get("attacks", [])
            ],
        }
    return members


def _side_summary(side):
    return {
        "tag": side.get("tag"),
        "name": side.get("name"),
        "stars": side.get("stars", 0) or 0,
        "destr": side.get("destructionPercentage", 0) or 0,
        "attacks": side.get("attacks", 0) or 0,
    }


def war_snapshot(war_json):
    if not war_json:
        return None
    state = war_json.get("state")
    if state == "notInWar":
        return {"state": "notInWar"}
    clan = war_json.get("clan") or {}
    opponent = war_json.get("opponent") or {}
    return {
        "state": state,
        "teamSize": war_json.get("teamSize"),
        "attacksPerMember": war_json.get("attacksPerMember", 2) or 2,
        "startTime": war_json.get("startTime"),
        "endTime": war_json.get("endTime"),
        "warTag": war_json.get("warTag"),
        "clan": _side_summary(clan),
        "opponent": _side_summary(opponent),
        "members": _side_members(clan),
        "defenders": _side_members(opponent),
    }


def war_key(war):
    return f"{war.get('endTime')}|{(war.get('opponent') or {}).get('tag')}"


def war_result(war):
    c, o = war["clan"], war["opponent"]
    ours, theirs = (c["stars"], c["destr"]), (o["stars"], o["destr"])
    if ours > theirs:
        return "win"
    if ours < theirs:
        return "lose"
    return "tie"


def _new_attacks(old_side, new_side):
    found = []
    for tag, m in new_side.items():
        seen = len((old_side.get(tag) or {}).get("attacks", []))
        for n, attack in enumerate(m.get("attacks", [])[seen:], start=seen + 1):
            found.append((m, attack, n))
    return found


new_attacks = _new_attacks


def war_events(old, new):
    events = []
    if old is None or new is None:
        return events
    old_state, new_state = old.get("state"), new.get("state")
    same_war = bool(old.get("endTime")) and old.get("endTime") == new.get("endTime")
    if new_state == "preparation" and (old_state != "preparation" or not same_war):
        events.append({"type": "war_prep", "war": new})
    if new_state == "inWar" and (old_state != "inWar" or not same_war):
        events.append({"type": "war_start", "war": new})
    if same_war and old_state in ("preparation", "inWar") and new_state in ("preparation", "inWar"):
        for m, a, n in _new_attacks(old.get("members", {}), new.get("members", {})):
            d = new["defenders"].get(a.get("defender")) or {}
            events.append({
                "type": "attack", "name": m["name"], "stars": a["stars"], "destr": a["destr"],
                "defender": d.get("name"), "defender_pos": d.get("pos"), "defender_th": d.get("th"),
                "n": n, "order": a.get("order", 0),
            })
        for m, a, n in _new_attacks(old.get("defenders", {}), new.get("defenders", {})):
            d = new["members"].get(a.get("defender")) or {}
            events.append({
                "type": "defense", "name": m["name"], "stars": a["stars"], "destr": a["destr"],
                "defender": d.get("name"), "defender_pos": d.get("pos"), "order": a.get("order", 0),
            })
    if same_war and old_state == "inWar" and new_state == "warEnded":
        events.append({"type": "war_end", "war": new, "result": war_result(new)})
    return events


def performances(war):
    per_member = war.get("attacksPerMember", 2)
    rows = []
    for m in war.get("members", {}).values():
        attacks = m.get("attacks", [])
        rows.append({
            "name": m["name"],
            "pos": m.get("pos"),
            "stars": sum(a["stars"] for a in attacks),
            "destr": sum(a["destr"] for a in attacks),
            "attacks": len(attacks),
            "missed": max(0, per_member - len(attacks)),
            "triples": sum(1 for a in attacks if a["stars"] == 3),
        })
    rows.sort(key=lambda r: (-r["stars"], -r["destr"], r["name"] or ""))
    return rows


def missing_attackers(war):
    per_member = war.get("attacksPerMember", 2)
    missing = []
    for tag, m in sorted(war.get("members", {}).items(), key=lambda kv: kv[1].get("pos") or 99):
        left = per_member - len(m.get("attacks", []))
        if left > 0:
            missing.append({"tag": tag, "name": m["name"], "left": left, "pos": m.get("pos")})
    return missing


def _record_member(war, tag, m, per_member, defense):
    d = defense.get(tag) or {"stars": 0, "destr": 0, "hits": 0}
    defenders = war.get("defenders") or {}
    return {
        "tag": tag,
        "name": m["name"],
        "pos": m.get("pos"),
        "th": m.get("th"),
        "attacks": [
            {"stars": a["stars"], "destr": a["destr"],
             "defender": a.get("defender"),
             "d_pos": (defenders.get(a.get("defender")) or {}).get("pos"),
             "d_th": (defenders.get(a.get("defender")) or {}).get("th")}
            for a in m.get("attacks", [])
        ],
        "missed": max(0, per_member - len(m.get("attacks", []))),
        "def": {"stars": d["stars"], "destr": d["destr"], "hits": d["hits"]},
    }


def war_record(war, kind="war", day=None):
    per_member = war.get("attacksPerMember", 2)
    defense = {r["tag"]: r for r in war_defense(war)}
    return {
        "kind": kind,
        "day": day,
        "endTime": war.get("endTime"),
        "opponent": war["opponent"]["name"],
        "opp_tag": war["opponent"].get("tag"),
        "result": war_result(war),
        "stars": war["clan"]["stars"],
        "destr": war["clan"]["destr"],
        "opp_stars": war["opponent"]["stars"],
        "opp_destr": war["opponent"]["destr"],
        "teamSize": war.get("teamSize"),
        "attacksPerMember": per_member,
        "members": [
            _record_member(war, tag, m, per_member, defense)
            for tag, m in war.get("members", {}).items()
        ],
    }


def member_stats(records):
    stats = {}
    for record in records:
        for m in record.get("members", []):
            s = stats.setdefault(m["tag"], {
                "name": m["name"], "wars": 0, "attacks": 0, "stars": 0,
                "destr": 0.0, "triples": 0, "missed": 0, "expected": 0,
            })
            s["name"] = m["name"]
            s["wars"] += 1
            s["attacks"] += len(m["attacks"])
            s["stars"] += sum(a["stars"] for a in m["attacks"])
            s["destr"] += sum(a["destr"] for a in m["attacks"])
            s["triples"] += sum(1 for a in m["attacks"] if a["stars"] == 3)
            s["missed"] += m.get("missed", 0)
            s["expected"] += record.get("attacksPerMember", 2)
    return stats


def due_reminders(war, sent, now=None, checkpoints=None):
    end = parse_coc_time(war.get("endTime"))
    if not end:
        return []
    left = (end - (now or now_utc())).total_seconds()
    return [cp for cp in (checkpoints or REMINDER_CHECKPOINTS) if 0 < left <= cp and cp not in sent]


def raid_attack_limit(member):
    return (member.get("attackLimit") or 5) + (member.get("bonusAttackLimit") or 0)


def capital_events(cap, raid, members, now=None):
    now = now or now_utc()
    cap = dict(cap or {})
    events = []
    season = raid.get("startTime")
    raid_state = raid.get("state")
    if season != cap.get("season"):
        cap = {"season": season, "state": raid_state}
        if raid_state == "ongoing":
            events.append({"type": "capital_start", "end": raid.get("endTime")})
    if raid_state == "ongoing" and not cap.get("reminder_sent"):
        end = parse_coc_time(raid.get("endTime"))
        if end and 0 < (end - now).total_seconds() <= 12 * 3600:
            participants = {m.get("tag"): m for m in raid.get("members", [])}
            lazy = []
            for tag, member in (members or {}).items():
                rm = participants.get(tag)
                left = raid_attack_limit(rm or {}) - ((rm or {}).get("attacks") or 0)
                if left > 0:
                    lazy.append({"name": (rm or member).get("name"), "left": left})
            if lazy:
                events.append({"type": "capital_reminder", "end": raid.get("endTime"), "lazy": lazy})
            cap["reminder_sent"] = True
    if cap.get("state") == "ongoing" and raid_state == "ended" and not cap.get("summary_sent"):
        looters = sorted(
            raid.get("members", []), key=lambda m: -(m.get("capitalResourcesLooted") or 0)
        )[:3]
        events.append({
            "type": "capital_end",
            "loot": raid.get("capitalTotalLoot"),
            "attacks": raid.get("totalAttacks"),
            "districts": raid.get("enemyDistrictsDestroyed"),
            "podium": [(m.get("name"), m.get("capitalResourcesLooted")) for m in looters],
        })
        cap["summary_sent"] = True
    cap["state"] = raid_state
    return cap, events
