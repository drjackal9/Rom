from .platform_guard import IDLE_TTL
from .retention import WAR_HISTORY_KEEP

KEY = "feed:{alias}:{uid}"
TTL = IDLE_TTL
KEEP = WAR_HISTORY_KEEP


def key_of(alias, uid):
    return KEY.format(alias=alias, uid=int(uid))


async def _doc(store, alias, uid):
    saved = await store.kv_get(key_of(alias, uid)) or {}
    return {"rows": list(saved.get("rows") or []), "read_at": int(saved.get("read_at") or 0)}


async def _save(store, alias, uid, doc):
    await store.kv_set(key_of(alias, uid), doc, ref=alias, ttl=TTL)


async def add(store, alias, uid, kind, text, now):
    doc = await _doc(store, alias, uid)
    entry = {"at": int(now.timestamp()), "kind": kind, "text": text}
    doc["rows"] = (doc["rows"] + [entry])[-KEEP:]
    await _save(store, alias, uid, doc)
    return len(doc["rows"])


async def rows(store, alias, uid):
    return (await _doc(store, alias, uid))["rows"]


async def unread(store, alias, uid):
    doc = await _doc(store, alias, uid)
    return sum(1 for row in doc["rows"] if row["at"] > doc["read_at"])


async def mark_read(store, alias, uid, now):
    doc = await _doc(store, alias, uid)
    if not doc["rows"]:
        return
    doc["read_at"] = int(now.timestamp())
    await _save(store, alias, uid, doc)


async def forget(store, alias, uid):
    gone = len((await _doc(store, alias, uid))["rows"])
    await store.kv_del(key_of(alias, uid))
    return gone
