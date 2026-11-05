from .leaders import NOTE_MAX, sanitize
from .retention import INACTIVE_CLAN_DAYS

ACTIONS = ("settings", "rules", "welcome", "schedule", "note", "gate", "export", "link", "apply",
           "cwl", "family", "integration", "pause", "seat", "claim", "bases",
           "views", "platform")
KINDS = ("warning", "target", "settings", "delegate", "undo")
KIND = "notes"
GONE_DAYS = INACTIVE_CLAN_DAYS
DELEGATE_PRESS = "dlg"


def pressed(data):
    parts = str(data or "").split(":")
    action = parts[2] if len(parts) > 2 else ""
    return ("delegate" if action == DELEGATE_PRESS else "settings",
            parts[3] if len(parts) > 3 else action)


async def notes_all(store, alias):
    stored = await store.get_state(alias, KIND)
    return stored if isinstance(stored, dict) else {}


async def note_get(store, alias, tag):
    return (await notes_all(store, alias)).get(tag)


async def note_set(store, alias, tag, name, text, by, by_name, now):
    clean = sanitize(text, NOTE_MAX)
    if not clean:
        return None
    notes = await notes_all(store, alias)
    notes[tag] = {"name": name, "text": clean, "by": by, "by_name": by_name,
                  "ts": now.timestamp(), "gone": None}
    await store.set_state(alias, KIND, notes)
    return notes[tag]


async def note_del(store, alias, tag):
    notes = await notes_all(store, alias)
    if notes.pop(tag, None) is None:
        return False
    await store.set_state(alias, KIND, notes)
    return True


async def prune_notes(store, alias, members, now):
    notes = await notes_all(store, alias)
    if not notes:
        return 0
    cutoff = now.timestamp() - GONE_DAYS * 86400
    dropped, changed = 0, False
    for tag, note in list(notes.items()):
        if tag in (members or {}):
            if note.get("gone"):
                note["gone"] = None
                changed = True
            continue
        gone = note.get("gone")
        if not gone:
            note["gone"] = now.timestamp()
            changed = True
        elif gone < cutoff:
            del notes[tag]
            dropped += 1
            changed = True
    if changed:
        await store.set_state(alias, KIND, notes)
    return dropped


async def record(store, alias, action, by, by_name=None, detail=None, now=None):
    if action not in ACTIONS:
        return False
    await store.add_log(alias, {"action": action, "by": by, "by_name": by_name, "detail": detail},
                        at=now)
    return True


async def acted(store, alias, kind, ref, by, by_name=None, of=None, now=None):
    if kind not in KINDS:
        return False
    row = {"kind": kind, "ref": ref, "by": by, "by_name": by_name}
    if of:
        row["of"] = of
    await store.add_log(alias, row, at=now)
    return True


async def game_names(store, rows):
    found = {}
    for row in rows:
        uid = row.get("by")
        if uid is None or uid in found:
            continue
        links = await store.links_by_user(uid)
        found[uid] = links[0].name if links else None
    return found


async def history(store, alias, limit=20):
    rows = await store.recent_log(alias, limit)
    names = await game_names(store, rows)
    return [dict(row, by_name=names.get(row.get("by")) or row.get("by_name")) for row in rows]
