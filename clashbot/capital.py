from . import progress as progress_mod
from .events import raid_attack_limit
from .leaderboards import TOP as BOARD_TOP
from .render import card, quote, rank
from .util import esc

TOP = BOARD_TOP
END_TOP = 3
GOLD_KEYS = ("capital_gold", "raid_loot")


def efficiency_rows(raid):
    rows = []
    for m in (raid or {}).get("members") or []:
        attacks = int(m.get("attacks") or 0)
        loot = int(m.get("capitalResourcesLooted") or 0)
        if not attacks and not loot:
            continue
        rows.append({
            "tag": m.get("tag"),
            "name": m.get("name"),
            "attacks": attacks,
            "loot": loot,
            "per_attack": loot // attacks if attacks else 0,
            "left": max(0, raid_attack_limit(m) - attacks),
        })
    rows.sort(key=lambda r: (-r["per_attack"], -r["loot"], r["name"] or ""))
    return rows


def district_rows(raid):
    seen = {}
    for entry in (raid or {}).get("attackLog") or []:
        for d in entry.get("districts") or []:
            name = d.get("name")
            if not name:
                continue
            row = seen.setdefault(name, {"name": name, "level": 0, "attacks": 0, "loot": 0, "done": 0, "raided": 0})
            row["level"] = max(row["level"], int(d.get("districtHallLevel") or 0))
            row["attacks"] += int(d.get("attackCount") or 0)
            row["loot"] += int(d.get("totalLooted") or 0)
            row["raided"] += 1
            if float(d.get("destructionPercent") or 0) >= 100:
                row["done"] += 1
    rows = list(seen.values())
    rows.sort(key=lambda r: (-r["done"], -r["attacks"], r["name"]))
    return rows


def skipped_rows(raid, members):
    joined = {m.get("tag"): m for m in (raid or {}).get("members") or []}
    rows = []
    for tag, member in (members or {}).items():
        entry = joined.get(tag) or {}
        left = raid_attack_limit(entry) - int(entry.get("attacks") or 0)
        if left <= 0:
            continue
        rows.append({
            "tag": tag,
            "name": entry.get("name") or (member or {}).get("name") or tag,
            "left": left,
            "done": int(entry.get("attacks") or 0),
        })
    rows.sort(key=lambda r: (-r["left"], r["name"] or ""))
    return rows


def free_attacks(raid, members):
    return sum(row["left"] for row in skipped_rows(raid, members))


def track_gold(cap, progress, members):
    base = cap.setdefault("gold_base", {})
    for tag, values in progress_mod.snapshot(progress, members, GOLD_KEYS).items():
        base.setdefault(tag, values)
    keep = set(members or ())
    for tag in [t for t in base if t not in keep]:
        del base[tag]
    return cap


def gold_since(progress, cap):
    return progress_mod.since(progress, (cap or {}).get("gold_base"), GOLD_KEYS)


def gold_rows(rows):
    out = [
        {"tag": r.get("tag"), "name": r.get("name"), "gold": int(r.get("capital_gold") or 0),
         "loot": int(r.get("raid_loot") or 0)}
        for r in (rows or []) if int(r.get("capital_gold") or 0) > 0
    ]
    out.sort(key=lambda r: (-r["gold"], -r["loot"], r["name"] or ""))
    return out


def hall_snapshot(clan_json):
    payload = (clan_json or {}).get("clanCapital") or {}
    level = int(payload.get("capitalHallLevel") or 0)
    if not level:
        return None
    districts = [
        {"name": d.get("name"), "level": int(d.get("districtHallLevel") or 0)}
        for d in payload.get("districts") or [] if d.get("name")
    ]
    districts.sort(key=lambda d: (-d["level"], d["name"]))
    return {"level": level, "districts": districts}


def hall_events(old, new):
    if not old or not new:
        return []
    events = []
    if int(new.get("level") or 0) > int(old.get("level") or 0):
        events.append({"type": "capital_hall", "level": int(new["level"])})
    before = {d["name"]: d["level"] for d in old.get("districts") or []}
    for d in new.get("districts") or []:
        was = before.get(d["name"])
        if was is not None and d["level"] > was:
            events.append({"type": "district", "name": d["name"], "level": d["level"]})
    return events


def next_goals(hall):
    level = int((hall or {}).get("level") or 0)
    return [d for d in (hall or {}).get("districts") or [] if 0 < d["level"] < level]


def _eff_lines(L, rows):
    return "\n".join(
        L.t("capital.eff.row", rank=rank(L, i), name=esc(r["name"]), per=L.n(r["per_attack"]),
            attacks=r["attacks"], loot=L.n(r["loot"]))
        for i, r in enumerate(rows)
    )


def _district_lines(L, rows):
    return "\n".join(
        L.t("capital.districts.row", name=esc(r["name"]), level=r["level"], done=r["done"],
            attacks=r["attacks"], loot=L.n(r["loot"]))
        for r in rows
    )


def efficiency_card(L, raid, n=TOP):
    rows = efficiency_rows(raid)[:n]
    if not rows:
        return card("⛏️", L.t("capital.eff.title"), L.t("capital.eff.empty"))
    return card("⛏️", L.t("capital.eff.title"), quote(_eff_lines(L, rows)) + "\n" + L.t("capital.eff.legend"))


def districts_card(L, raid, n=TOP):
    rows = district_rows(raid)[:n]
    if not rows:
        return card("🏚", L.t("capital.districts.title"), L.t("capital.districts.empty"))
    return card("🏚", L.t("capital.districts.title"), quote(_district_lines(L, rows)))


def gold_card(L, source, n=TOP):
    rows = gold_rows(source)[:n]
    if not rows:
        return card("🪙", L.t("capital.gold.title"), L.t("capital.gold.empty"))
    body = quote("\n".join(
        L.t("capital.gold.row", rank=rank(L, i), name=esc(r["name"]), gold=L.n(r["gold"]), loot=L.n(r["loot"]))
        for i, r in enumerate(rows)))
    return card("🪙", L.t("capital.gold.title"), body + "\n\n" + L.t("capital.gold.tail"))


def hall_card(L, hall):
    if not hall:
        return card("🏛", L.t("capital.hall.title"), L.t("capital.hall.none"))
    body = L.t("capital.hall.level", level=hall["level"])
    districts = hall.get("districts") or []
    if districts:
        body += "\n\n" + quote("\n".join(
            L.t("capital.hall.district_row", name=esc(d["name"]), level=d["level"]) for d in districts))
    goals = next_goals(hall)
    if goals:
        body += "\n\n" + L.t("capital.hall.goals") + "\n" + quote("   ".join(
            L.t("capital.hall.goal_row", name=esc(d["name"]), level=d["level"]) for d in goals))
    else:
        body += "\n\n" + L.t("capital.hall.goals_none")
    return card("🏛", L.t("capital.hall.title"), body)


def level_cards(L, events):
    cards = []
    for e in events or ():
        if e["type"] == "capital_hall":
            cards.append(card("🏛", L.t("capital.level.hall.title"), L.t("capital.level.hall.body", level=e["level"])))
        else:
            cards.append(card("🏗", L.t("capital.level.district.title"),
                              L.t("capital.level.district.body", name=esc(e["name"]), level=e["level"])))
    return cards


def end_extra(L, raid):
    parts = []
    eff = efficiency_rows(raid)[:END_TOP]
    if eff:
        parts.append(L.t("capital.eff.section") + "\n" + quote(_eff_lines(L, eff)))
    districts = district_rows(raid)[:END_TOP]
    if districts:
        parts.append(L.t("capital.districts.section") + "\n" + quote(_district_lines(L, districts)))
    return "\n\n".join(parts)


def skipped_dm(L, tz, row, next_start=None):
    body = L.t("capital.skipped.body", done=row["done"], n=row["left"])
    if next_start:
        body += "\n" + L.t("capital.skipped.next", when=L.when(next_start, tz))
    return card("⛏️", L.t("capital.skipped.title"), body + "\n\n" + L.t("capital.skipped.tail"))


def raid_record(raid):
    return {
        "season": raid.get("startTime"),
        "end": raid.get("endTime"),
        "loot": int(raid.get("capitalTotalLoot") or 0),
        "attacks": int(raid.get("totalAttacks") or 0),
        "districts": int(raid.get("enemyDistrictsDestroyed") or 0),
        "raids": int(raid.get("raidsCompleted") or 0),
        "members": [
            {"tag": r["tag"], "name": r["name"], "attacks": r["attacks"], "loot": r["loot"],
             "per_attack": r["per_attack"]}
            for r in efficiency_rows(raid)
        ],
        "districts_log": district_rows(raid),
    }
