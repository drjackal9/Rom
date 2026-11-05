from .retention import WAR_HISTORY_KEEP
from .util import zone

KIND = "challenges"
VERSION = 1
NONE = type(None)
FIELDS = {
    "quiz": {"open": (dict, NONE), "used": (list,), "last": (str, NONE)},
    "duels": {"open": (list,), "done": (list,)},
    "mission": {"week": (str, NONE), "metric": (str, NONE), "goal": (int,), "start": (int,),
                "now": (int, NONE), "measuring": (bool,), "best": (dict,), "sent": (list,)},
    "bingo": {"war": (str, NONE), "cells": (list,), "hit": (list,), "behind": (bool,),
              "bingo": (bool,), "done": (str, NONE), "message_id": (int, NONE),
              "digest": (str, NONE)},
    "awards": {"given": (list,), "vote": (dict, NONE)},
}


def empty():
    return {
        "v": VERSION,
        "quiz": {"open": None, "used": [], "last": None},
        "duels": {"open": [], "done": []},
        "mission": {"week": None, "metric": None, "goal": 0, "start": 0, "now": None,
                    "measuring": False, "best": {}, "sent": []},
        "bingo": {"war": None, "cells": [], "hit": [], "behind": False, "bingo": False,
                  "done": None, "message_id": None, "digest": None},
        "awards": {"given": [], "vote": None},
        "badges": {},
        "log": [],
    }


def ensure(state):
    base = empty()
    if not isinstance(state, dict):
        return base
    out = {"v": VERSION}
    for key, value in base.items():
        if key == "v":
            continue
        found = state.get(key)
        out[key] = found if type(found) is type(value) else value
    for group, fields in FIELDS.items():
        block = out[group] = dict(out[group])
        for field, kinds in fields.items():
            if field not in block or not isinstance(block[field], kinds):
                block[field] = base[group][field]
    out["duels"]["done"] = out["duels"]["done"][-WAR_HISTORY_KEEP:]
    out["awards"]["given"] = out["awards"]["given"][-WAR_HISTORY_KEEP:]
    out["log"] = [row for row in out["log"] if isinstance(row, dict)][-WAR_HISTORY_KEEP:]
    return out


def note(state, kind, **fields):
    entry = {"kind": kind}
    entry.update(fields)
    log = [row for row in (state.get("log") or []) if isinstance(row, dict)]
    state["log"] = (log + [entry])[-WAR_HISTORY_KEEP:]
    return entry


def recent(state, kind, limit=WAR_HISTORY_KEEP):
    rows = [row for row in (state.get("log") or []) if row.get("kind") == kind]
    return rows[-limit:]


def week_id(now, tz):
    return now.astimezone(zone(tz)).strftime("%G-W%V")


async def load(store, alias):
    return ensure(await store.get_state(alias, KIND))


async def save(store, alias, state):
    await store.set_state(alias, KIND, ensure(state))
