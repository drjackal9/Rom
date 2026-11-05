from hashlib import sha256

from .cwl import standings as cwl_standings
from .retention import WAR_HISTORY_KEEP
from .ttl import ONBOARD_TTL
from .util import to_int

VERSION = 1
KINDS = ("derby", "internal", "clash")
SCOPES = ("family", "clan", "network")
FORMATS = ("table", "groups", "bracket")
SIZES = (4, 8, 16, 32)
METRICS = ("stars", "activity", "both", "triples", "donated", "capital_gold", "loot", "games")
STATUSES = ("signup", "running", "done")
WINDOWS = (3 * 86400, 7 * 86400)
SIGNUP_WINDOW = ONBOARD_TTL
MAX_ENTRIES = SIZES[-1]
GROUP_SIZE = SIZES[0]
TENTHS = 10
LOG_KEEP = WAR_HISTORY_KEEP
NAMES = ("signup", "round", "result", "final")


def _pick(value, allowed, fallback):
    return value if value in allowed else fallback


def _bracket_size(total):
    size = 2
    while size < total:
        size *= 2
    return size


def planned_rounds(fmt, size):
    if fmt != "bracket":
        return 1
    return max(1, _bracket_size(max(2, to_int(size))).bit_length() - 1)


def empty(kind, scope, metric, fmt, opens, starts, ends, size=None, week=None, rounds_total=None):
    fmt = _pick(fmt, FORMATS, "table")
    size = _pick(size, SIZES, MAX_ENTRIES)
    return {
        "v": VERSION,
        "alias": None,
        "status": None,
        "family_alias": None,
        "clan_alias": None,
        "origin": None,
        "kind": _pick(kind, KINDS, "internal"),
        "scope": _pick(scope, SCOPES, "clan"),
        "metric": _pick(metric, METRICS, "stars"),
        "format": fmt,
        "size": size,
        "rounds_total": to_int(rounds_total) if to_int(rounds_total) > 0 else planned_rounds(fmt, size),
        "opens": to_int(opens),
        "starts": to_int(starts),
        "ends": to_int(ends),
        "week": week if isinstance(week, str) else None,
        "entries": [],
        "groups": [],
        "rounds": [],
        "base": {},
        "scores": {},
        "ties": {},
        "mission": None,
        "sent": [],
        "log": [],
    }


def _close_bye(match):
    if match["a"] is None and match["b"] is not None:
        match["a"], match["b"] = match["b"], None
    if match["b"] is None and match["a"] is not None:
        match["winner"] = match["a"]
        match["done"] = True
    return match


def ensure(doc):
    src = doc if isinstance(doc, dict) else {}
    out = empty(src.get("kind"), src.get("scope"), src.get("metric"), src.get("format"),
                src.get("opens"), src.get("starts"), src.get("ends"),
                size=src.get("size"), week=src.get("week"), rounds_total=src.get("rounds_total"))
    for key in ("alias", "status", "family_alias", "clan_alias", "origin"):
        out[key] = src.get(key) if isinstance(src.get(key), str) else None
    seen, entries = set(), []
    for item in src.get("entries") or []:
        if not isinstance(item, dict) or len(entries) >= MAX_ENTRIES:
            continue
        eid = item.get("id")
        if not isinstance(eid, str) or eid in seen:
            continue
        seen.add(eid)
        entries.append({
            "id": eid,
            "type": "clan" if item.get("type") == "clan" else "member",
            "ref": str(item.get("ref") or ""),
            "name": str(item.get("name") or "?"),
            "seed": to_int(item.get("seed")),
        })
    out["entries"] = entries
    out["groups"] = [[eid for eid in group if eid in seen]
                     for group in src.get("groups") or [] if isinstance(group, list)]
    rounds = []
    for raw in src.get("rounds") or []:
        if not isinstance(raw, list):
            continue
        matches = []
        for match in raw:
            if not isinstance(match, dict) or match.get("a") not in seen:
                continue
            score = match.get("score")
            score = score if isinstance(score, list) and len(score) == 2 else [0, 0]
            matches.append(_close_bye({
                "a": match["a"],
                "b": match.get("b") if match.get("b") in seen else None,
                "score": [to_int(score[0]), to_int(score[1])],
                "winner": match.get("winner") if match.get("winner") in seen else None,
                "done": bool(match.get("done")),
            }))
        rounds.append(matches)
    out["rounds"] = rounds
    if rounds and to_int(src.get("rounds_total")) <= 0:
        out["rounds_total"] = max(1, (len(rounds[0]) * 2).bit_length() - 1)
    for key in ("scores", "ties"):
        values = src.get(key)
        if isinstance(values, dict):
            out[key] = {eid: to_int(value) for eid, value in values.items() if eid in seen}
    base = src.get("base")
    if isinstance(base, dict):
        out["base"] = {eid: {k: to_int(v) for k, v in values.items()}
                       for eid, values in base.items() if eid in seen and isinstance(values, dict)}
    mission = src.get("mission")
    if isinstance(mission, dict):
        out["mission"] = {
            "metric": _pick(mission.get("metric"), METRICS, out["metric"]),
            "goal": to_int(mission.get("goal")),
            "best": to_int(mission.get("best")),
            "value": to_int(mission.get("value")),
            "hit": bool(mission.get("hit")),
            "first": bool(mission.get("first")),
        }
    out["sent"] = [item for item in src.get("sent") or [] if isinstance(item, str)][-LOG_KEEP:]
    out["log"] = [item for item in src.get("log") or [] if isinstance(item, dict)][-LOG_KEEP:]
    return out


def entry_id(kind, ref):
    return f"{'c' if kind == 'clan' else 'm'}:{ref}"


def name_of(doc, eid):
    for entry in ensure(doc)["entries"]:
        if entry["id"] == eid:
            return entry["name"]
    return "?"


def started(doc):
    doc = ensure(doc)
    return bool(doc["rounds"] or doc["groups"])


def join(doc, kind, ref, name, now=None):
    doc = ensure(doc)
    if started(doc) or (now is not None and to_int(now) >= doc["starts"]):
        return doc, "closed"
    eid = entry_id(kind, ref)
    if any(entry["id"] == eid for entry in doc["entries"]):
        return doc, "dup"
    if len(doc["entries"]) >= min(doc["size"], MAX_ENTRIES):
        return doc, "full"
    doc["entries"].append({"id": eid, "type": "clan" if kind == "clan" else "member",
                           "ref": str(ref), "name": str(name or "?"), "seed": 0})
    return doc, "ok"


def leave(doc, eid):
    doc = ensure(doc)
    if started(doc):
        return doc, False
    keep = [entry for entry in doc["entries"] if entry["id"] != eid]
    removed = len(keep) != len(doc["entries"])
    doc["entries"] = keep
    return doc, removed


def eligible(doc, excluded):
    doc = ensure(doc)
    blocked = {str(ref) for ref in excluded or ()}
    doc["entries"] = [entry for entry in doc["entries"] if entry["ref"] not in blocked]
    return doc


def seed(doc):
    doc = ensure(doc)
    salt = doc.get("alias") or doc.get("week") or ""
    order = sorted(doc["entries"], key=lambda e: sha256(f"{salt}|{e['id']}".encode()).hexdigest())
    for position, entry in enumerate(order, start=1):
        entry["seed"] = position
    doc["entries"] = order
    return doc


def shrink(doc):
    doc = ensure(doc)
    total = len(doc["entries"])
    for size in sorted(SIZES, reverse=True):
        if total >= size:
            doc["size"] = size
            doc["entries"] = doc["entries"][:size]
            return doc
    return doc


def groups_for(doc):
    return max(1, len(ensure(doc)["entries"]) // GROUP_SIZE)


def make_groups(doc, n_groups):
    doc = seed(doc)
    count = max(1, to_int(n_groups))
    groups = [[] for _ in range(count)]
    for index, entry in enumerate(doc["entries"]):
        row, column = divmod(index, count)
        groups[column if row % 2 == 0 else count - 1 - column].append(entry["id"])
    doc["groups"] = [group for group in groups if group]
    doc["rounds_total"] = 1
    return doc


def make_bracket(doc):
    doc = seed(doc)
    ids = [entry["id"] for entry in doc["entries"]]
    if len(ids) < 2:
        doc["rounds"] = []
        return doc
    size = _bracket_size(len(ids))
    slots = ids + [None] * (size - len(ids))
    doc["rounds"] = [[_close_bye({"a": slots[i], "b": slots[size - 1 - i], "score": [0, 0],
                                  "winner": None, "done": False}) for i in range(size // 2)]]
    doc["rounds_total"] = max(1, size.bit_length() - 1)
    return doc


def next_round(doc):
    for index, matches in enumerate(ensure(doc)["rounds"]):
        if any(not match["done"] for match in matches):
            return index
    return None


def close_round(doc, index):
    doc = ensure(doc)
    if index >= len(doc["rounds"]) or any(not match["done"] for match in doc["rounds"][index]):
        return doc
    winners = [match["winner"] for match in doc["rounds"][index] if match["winner"]]
    if len(winners) < 2 or len(doc["rounds"]) > index + 1:
        return doc
    doc["rounds"].append([_close_bye({"a": winners[i], "b": winners[i + 1] if i + 1 < len(winners) else None,
                                      "score": [0, 0], "winner": None, "done": False})
                          for i in range(0, len(winners), 2)])
    return doc


def _seed_of(doc, eid):
    for entry in doc["entries"]:
        if entry["id"] == eid:
            return entry["seed"] or MAX_ENTRIES
    return MAX_ENTRIES


def record_result(doc, index, match, value_a, value_b, tie_a=0, tie_b=0):
    doc = ensure(doc)
    if index >= len(doc["rounds"]) or match >= len(doc["rounds"][index]):
        return doc
    entry = doc["rounds"][index][match]
    entry["score"] = [to_int(value_a), to_int(value_b)]
    left = (to_int(value_a), to_int(tie_a), -_seed_of(doc, entry["a"]))
    right = (to_int(value_b), to_int(tie_b), -_seed_of(doc, entry["b"]))
    entry["winner"] = entry["a"] if left >= right else entry["b"]
    entry["done"] = True
    return doc


def round_window(doc, index):
    doc = ensure(doc)
    total = max(1, to_int(doc["rounds_total"]), len(doc["rounds"]))
    span = max(1, (doc["ends"] - doc["starts"]) // total)
    start = doc["starts"] + span * max(0, to_int(index))
    return start, start + span


def scope_scores(doc, index, values, live):
    doc = ensure(doc)
    index = max(0, to_int(index))
    for eid, value in (values or {}).items():
        row = doc["base"].get(eid)
        if not isinstance(row, dict) or to_int(row.get("round")) != index:
            row = {"round": index, "value": to_int(value)} if live or index > 0 else None
            if row is not None:
                doc["base"][eid] = row
        doc["scores"][eid] = max(0, to_int(value) - to_int((row or {}).get("value")))
    return doc


def table(doc, group=None):
    doc = ensure(doc)
    if group is not None and group < len(doc["groups"]):
        ids = list(doc["groups"][group])
    else:
        ids = [entry["id"] for entry in doc["entries"]]
    known = {entry["id"]: entry for entry in doc["entries"]}
    rows = [{"id": eid, "name": known.get(eid, {}).get("name", "?"),
             "value": to_int(doc["scores"].get(eid)), "tie": to_int(doc["ties"].get(eid)),
             "seed": known.get(eid, {}).get("seed") or MAX_ENTRIES} for eid in ids]
    rows.sort(key=lambda row: (-row["value"], -row["tie"], row["seed"], row["name"] or ""))
    return rows


def winner(doc):
    doc = ensure(doc)
    if doc["rounds"]:
        last = doc["rounds"][-1]
        return last[0]["winner"] if len(last) == 1 else None
    rows = table(doc)
    return rows[0]["id"] if rows else None


def apply_clash(doc, results):
    doc = ensure(doc)
    tags = {entry["id"]: entry["ref"] for entry in doc["entries"] if entry["type"] == "clan"}
    clans = {ref: {"name": name_of(doc, eid), "level": 0} for eid, ref in tags.items()}
    wars = {}
    for index, row in enumerate(results or ()):
        left, right = row.get("a"), row.get("b")
        if left not in tags or right not in tags:
            continue
        wars[str(index)] = {
            "state": "warEnded",
            "clan": {"tag": tags[left], "stars": to_int(row.get("stars_a")),
                     "destr": float(row.get("destr_a") or 0)},
            "opponent": {"tag": tags[right], "stars": to_int(row.get("stars_b")),
                         "destr": float(row.get("destr_b") or 0)},
        }
    by_ref = {ref: eid for eid, ref in tags.items()}
    for ref, row in cwl_standings(clans, wars):
        eid = by_ref.get(ref)
        if eid:
            doc["scores"][eid] = to_int(row["stars"])
            doc["ties"][eid] = int(round(float(row["destr"]) * TENTHS))
    return doc


def note(doc, kind, **fields):
    doc = ensure(doc)
    row = {"kind": kind}
    row.update(fields)
    doc["log"] = (doc["log"] + [row])[-LOG_KEEP:]
    return doc


def event(name, scope):
    pack = "challenges" if scope == "clan" else "family"
    return f"{pack}.tournament.{_pick(name, NAMES, 'result')}"


def network_ready(row):
    return bool(isinstance(row, dict) and row.get("visible"))


def advance(doc, now):
    doc = ensure(doc)
    if doc["kind"] == "derby":
        return doc, []
    ts = to_int(now)
    fired = []
    if not started(doc):
        if ts < doc["starts"] and len(doc["entries"]) < doc["size"]:
            if ts >= doc["opens"] and "signup" not in doc["sent"]:
                doc["sent"].append("signup")
                fired.append({"type": "signup"})
            return doc, fired
        doc = shrink(doc)
        if len(doc["entries"]) < 2:
            if "empty" not in doc["sent"]:
                doc["sent"].append("empty")
                fired.append({"type": "empty"})
            return doc, fired
        span = max(1, (doc["ends"] - doc["starts"]) // max(1, to_int(doc["rounds_total"])))
        if doc["format"] == "bracket":
            doc = make_bracket(doc)
        else:
            doc = make_groups(doc, groups_for(doc) if doc["format"] == "groups" else 1)
        doc["ends"] = doc["starts"] + span * max(1, to_int(doc["rounds_total"]))
        doc["sent"].append("round:0")
        return doc, [{"type": "round", "index": 0}]
    if doc["format"] != "bracket":
        if ts >= doc["ends"] and "final" not in doc["sent"]:
            doc["sent"].append("final")
            fired.append({"type": "final", "winner": winner(doc)})
        return doc, fired
    index = next_round(doc)
    if index is None:
        if "final" not in doc["sent"]:
            doc["sent"].append("final")
            fired.append({"type": "final", "winner": winner(doc)})
        return doc, fired
    key = f"round:{index}"
    if key not in doc["sent"]:
        doc["sent"].append(key)
        fired.append({"type": "round", "index": index})
    return doc, fired
