KIND = "door"
SEEN = "known"
YES = "approved"
BAN = "banned"
WALL = "walled"
SINCE = "since"
WAR_FROM = "war_from"
SEEDED = "seeded"
TRUST = "trusted"
HERE = "here"
WAR_CHOICES = ("now", "next")
FIELDS = (SEEN, YES, BAN)


def _uids(rows):
    found = set()
    for uid in rows if isinstance(rows, (list, tuple, set)) else ():
        try:
            found.add(int(uid))
        except (TypeError, ValueError):
            continue
    return sorted(found)


def _row(row):
    row = row if isinstance(row, dict) else {}
    try:
        since = int(row.get(SINCE) or 0)
    except (TypeError, ValueError):
        since = 0
    try:
        war_from = int(row.get(WAR_FROM) or 0)
    except (TypeError, ValueError):
        war_from = 0
    return {SINCE: since, WAR_FROM: war_from}


def state_of(stored):
    stored = stored if isinstance(stored, dict) else {}
    kept = stored.get(YES) if isinstance(stored.get(YES), dict) else {}
    rows = {}
    for uid, row in kept.items():
        try:
            rows[str(int(uid))] = _row(row)
        except (TypeError, ValueError):
            continue
    return {SEEN: _uids(stored.get(SEEN)), YES: rows, BAN: _uids(stored.get(BAN)),
            WALL: _uids(stored.get(WALL)), TRUST: _uids(stored.get(TRUST)),
            HERE: _uids(stored.get(HERE)), SEEDED: bool(stored.get(SEEDED))}


def saw(state, uid):
    return dict(state, **{SEEN: _uids(list(state[SEEN]) + [uid])})


def approve(state, uid, now, war_from=0):
    rows = dict(state[YES])
    rows[str(int(uid))] = _row({SINCE: int(now), WAR_FROM: war_from})
    return dict(state, **{YES: rows})


def ban(state, uid):
    return dict(state, **{BAN: _uids(list(state[BAN]) + [uid])})


def unban(state, uid):
    gone = _uids([uid])
    return dict(state, **{BAN: [one for one in state[BAN] if one not in gone]})


def bans(state, uids):
    wanted = _uids(uids)
    fresh = state
    for uid in wanted:
        fresh = ban(fresh, uid)
    for uid in list(fresh[BAN]):
        if uid not in wanted:
            fresh = unban(fresh, uid)
    return fresh


def wall(state, uid):
    return dict(state, **{WALL: _uids(list(state[WALL]) + [uid])})


def walls(state, uids):
    return dict(state, **{WALL: _uids(uids)})


def shut_out(state):
    return _uids(list(state[BAN]) + list(state[WALL]))


def seed(state, uids, now):
    if state[SEEDED]:
        return state
    fresh = dict(state, **{SEEDED: True, HERE: _uids(uids)})
    for uid in _uids(uids):
        if str(uid) not in fresh[YES]:
            fresh = approve(fresh, uid, now)
    return fresh


def war_from(choice, now):
    if choice not in WAR_CHOICES:
        raise ValueError(choice)
    return 0 if choice == WAR_CHOICES[0] else int(now)


def revoke(state, uid):
    gone = str(int(uid))
    return dict(state, **{YES: {key: row for key, row in state[YES].items() if key != gone}})


def trust(state, uid, on):
    kept = [one for one in state[TRUST] if one != int(uid)]
    return dict(state, **{TRUST: _uids(kept + ([uid] if on else []))})


def pending(state, uids):
    shut = set(shut_out(state))
    return [uid for uid in _uids(uids) if str(uid) not in state[YES] and uid not in shut]


def gone(state, roster_uids):
    here = set(_uids(roster_uids)) | set(state[TRUST])
    return sorted(int(uid) for uid in state[YES] if int(uid) not in here)


def told(state, roster_uids):
    seen = set(state[HERE])
    return [uid for uid in gone(state, roster_uids) if uid in seen]


def present(state, roster_uids):
    return dict(state, **{HERE: _uids(roster_uids)})


def left(state, roster_uids):
    fresh = state
    for uid in gone(state, roster_uids):
        fresh = revoke(fresh, uid)
    return fresh


async def note_seen(store, alias, uid):
    state = state_of(await store.get_state(alias, KIND))
    fresh = saw(state, uid)
    if fresh != state:
        await store.set_state(alias, KIND, fresh)
    return fresh


def marks(state, mark):
    return {SEEN: sorted(mark(uid) for uid in state[SEEN]),
            YES: {mark(int(uid)): dict(row) for uid, row in state[YES].items()},
            BAN: sorted(mark(uid) for uid in shut_out(state))}
