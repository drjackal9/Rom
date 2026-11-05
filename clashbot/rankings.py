TOP_N = 200


def place(position):
    try:
        value = int(position)
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= TOP_N else None


def _best(entry):
    row = entry if isinstance(entry, dict) else {}
    return place(row.get("best")) or place(row.get("rank"))


def _entry(item):
    rank = place(item.get("rank"))
    if rank is None:
        return None
    return {"tag": item.get("tag"), "name": item.get("name"), "rank": rank, "best": rank}


def clan_entry(payload, tag):
    for item in (payload or {}).get("items") or ():
        if isinstance(item, dict) and item.get("tag") == tag:
            return _entry(item)
    return None


def player_entries(payload, tags):
    wanted = set(tags or ())
    found = {}
    for item in (payload or {}).get("items") or ():
        if isinstance(item, dict) and item.get("tag") in wanted:
            entry = _entry(item)
            if entry:
                found[entry["tag"]] = entry
    return found


def _keep_best(before, after):
    previous = _best(before)
    if not after or previous is None:
        return after
    return dict(after, best=min(int(after["rank"]), previous))


def merge(previous, current):
    before = previous or {}
    now = dict(current or {})
    if "clan" in now:
        now["clan"] = _keep_best(before.get("clan"), now["clan"])
    if "players" in now:
        old = before.get("players") or {}
        now["players"] = {tag: _keep_best(old.get(tag), entry)
                          for tag, entry in (now["players"] or {}).items()}
    return now


def _improved(before, after):
    if not after:
        return False
    previous = _best(before)
    return previous is None or int(after["rank"]) < previous


def changes(previous, current):
    before = previous or {}
    now = current or {}
    moves = []
    if _improved(before.get("clan"), now.get("clan")):
        moves.append({"kind": "clan", **now["clan"]})
    old_players = before.get("players") or {}
    for tag, entry in (now.get("players") or {}).items():
        if _improved(old_players.get(tag), entry):
            moves.append({"kind": "player", **entry})
    return moves
