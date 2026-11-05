NOTE = "note"
SWAP = "swap"


def by_pos(members):
    return {m["pos"]: dict(m, tag=tag) for tag, m in (members or {}).items() if m.get("pos")}


def mirror_plan(war):
    return {
        str(pos): {"tag": m["tag"], "name": m["name"]}
        for pos, m in by_pos(war.get("members")).items()
    }


def hits_by_defender(members):
    hits = {}
    for m in (members or {}).values():
        for a in m.get("attacks", []):
            tag = a.get("defender")
            if not tag:
                continue
            entry = hits.setdefault(tag, {"best": 0, "by": [], "hits": []})
            entry["best"] = max(entry["best"], a.get("stars", 0))
            entry["by"].append(m["name"])
            entry["hits"].append({"name": m["name"], "stars": a.get("stars", 0),
                                  "destr": a.get("destr", 0)})
    return hits


def best_by_defender(members):
    return {tag: hit["best"] for tag, hit in hits_by_defender(members).items()}


def plan_rows(war, plan):
    plan = plan or {}
    hits = hits_by_defender(war.get("members"))
    rows = []
    for tag, d in sorted(war.get("defenders", {}).items(), key=lambda kv: kv[1].get("pos") or 99):
        hit = hits.get(tag, {"best": 0, "by": [], "hits": []})
        held = plan.get(str(d.get("pos"))) or {}
        rows.append({
            "pos": d.get("pos"), "name": d.get("name"), "th": d.get("th"),
            "assignee": held.get("name"), "assignee_tag": held.get("tag"),
            "best": hit["best"], "by": hit["by"], "history": hit["hits"],
            NOTE: held.get(NOTE), SWAP: bool(held.get(SWAP)),
        })
    return rows


def targets_for(plan, tag):
    return sorted(int(pos) for pos, a in (plan or {}).items() if a.get("tag") == tag)


def member_at(war, pos):
    for tag, member in (war.get("members") or {}).items():
        if str(member.get("pos")) == str(pos):
            return tag, member
    return None


def assign(plan, pos, member):
    updated = dict(plan or {})
    if not member:
        updated.pop(str(pos), None)
        return updated
    tag, found = member
    updated[str(pos)] = {"tag": tag, "name": found.get("name")}
    return updated


def noted(plan, pos, text):
    held = (plan or {}).get(str(pos))
    if not held:
        return None
    kept = {name: value for name, value in held.items() if name != NOTE}
    updated = dict(plan or {})
    updated[str(pos)] = dict(kept, **{NOTE: text}) if text else kept
    return updated


def swapped(plan, pos, tag):
    held = (plan or {}).get(str(pos))
    if not held or held.get("tag") == tag:
        return None
    updated = dict(plan or {})
    updated[str(pos)] = dict(held, **{SWAP: True})
    return updated


def attacks_left(war, tag):
    member = (war.get("members") or {}).get(tag)
    if not member:
        return 0
    return max(0, int(war.get("attacksPerMember") or 2) - len(member.get("attacks") or []))
