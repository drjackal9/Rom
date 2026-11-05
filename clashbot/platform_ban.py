KEY = "platform_bans"
ROWS = "rows"
TAGS = "tags"
AT = "at"


def _uid(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tags(rows):
    found = set()
    for tag in rows if isinstance(rows, (list, tuple, set)) else ():
        if not isinstance(tag, str):
            continue
        clean = "#" + tag.strip().lstrip("#").upper()
        if len(clean) > 1:
            found.add(clean)
    return sorted(found)


def state_of(stored):
    stored = stored if isinstance(stored, dict) else {}
    kept = stored.get(ROWS) if isinstance(stored.get(ROWS), dict) else {}
    rows = {}
    for key, row in kept.items():
        uid = _uid(key)
        row = row if isinstance(row, dict) else {}
        if uid is None:
            continue
        try:
            at = float(row.get(AT) or 0)
        except (TypeError, ValueError):
            at = 0.0
        rows[str(uid)] = {TAGS: _tags(row.get(TAGS)), AT: at}
    return {ROWS: rows}


def uids(state):
    return sorted(int(key) for key in state_of(state)[ROWS])


def tags(state):
    found = set()
    for row in state_of(state)[ROWS].values():
        found |= set(row[TAGS])
    return sorted(found)


def shut(state, uid, wanted=()):
    found = state_of(state)
    if uid is not None and str(_uid(uid)) in found[ROWS]:
        return True
    return bool(set(_tags(wanted)) & set(tags(found)))


def with_ban(state, uid, wanted, at):
    found = state_of(state)
    if _uid(uid) is None:
        return found
    key = str(_uid(uid))
    kept = found[ROWS].get(key) or {TAGS: [], AT: float(at)}
    rows = dict(found[ROWS])
    rows[key] = {TAGS: _tags(kept[TAGS] + list(wanted or ())), AT: kept[AT]}
    return {ROWS: rows}


def without_ban(state, uid):
    found = state_of(state)
    return {ROWS: {key: row for key, row in found[ROWS].items() if key != str(_uid(uid))}}


async def load(store):
    return state_of(await store.kv_get(KEY))


async def ban(store, uid, wanted, at):
    if _uid(uid) is None:
        return False
    await store.kv_set(KEY, with_ban(await load(store), uid, wanted, at))
    return True


async def lift(store, uid):
    found = await load(store)
    if str(_uid(uid)) not in found[ROWS]:
        return False
    await store.kv_set(KEY, without_ban(found, uid))
    return True


async def refuses(store, uid, wanted=()):
    return shut(await load(store), uid, wanted)
