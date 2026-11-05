import asyncio
import logging

from . import bases
from .web.http import READ_TIMEOUT

log = logging.getLogger("clashbot.base_library")

URL = "https://nschmeller.github.io/clash-bases/bases.json"
ROOT = "bases"
ETAG_KEY = "base_library:etag"
LAST_KEY = "base_library:last"
FRESH = "fresh"
SAME = "same"
DOWN = "down"
OK_STATUS = 200
NOT_MODIFIED = 304


def entries(body):
    if isinstance(body, dict):
        return body.get(ROOT) or ()
    return body if isinstance(body, list) else ()


def one(row):
    if not isinstance(row, dict):
        return None
    layout = bases.parse_link(row.get("link"))
    row_id = str(row.get("id") or "").strip()
    if not layout or not row_id:
        return None
    return {"id": row_id, "name": str(row.get("name") or ""), "hall": layout["hall"],
            "village": layout["village"],
            "kind": str(row.get("type") or "").strip().lower(),
            "link": str(row.get("link")).strip(), "builder": str(row.get("builder") or ""),
            "tags": [str(tag) for tag in (row.get("tags") or ()) if str(tag)],
            "added": str(row.get("added") or "")}


def parse(rows):
    kept = []
    for row in rows or ():
        entry = one(row)
        if entry:
            kept.append(entry)
    return kept


def tag_of(headers):
    value = headers.get("ETag") or headers.get("etag")
    return str(value).strip() if value else None


async def download(client, etag):
    headers = {"If-None-Match": etag} if etag else {}
    try:
        answer = await client.get(URL, headers=headers, timeout=READ_TIMEOUT)
        status = int(answer.status_code)
        body = answer.json() if status == OK_STATUS else None
        return status, body, tag_of(answer.headers)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("libreria delle basi non scaricata (%s)", type(e).__name__)
        return None


async def kept_count(store):
    last = await store.kv_get(LAST_KEY) or {}
    return int(last.get("count") or 0)


async def mark(store, status, count, now):
    await store.kv_set(LAST_KEY, {"status": status, "count": count, "at": float(now)})
    return {"status": status, "count": count}


async def round_of(store, client, now):
    stored = await store.kv_get(ETAG_KEY) or {}
    answer = await download(client, stored.get("etag"))
    if answer is None:
        return await mark(store, DOWN, await kept_count(store), now)
    status, body, etag = answer
    if status == NOT_MODIFIED:
        return await mark(store, SAME, await kept_count(store), now)
    rows = parse(entries(body))
    if status != OK_STATUS or not rows:
        log.warning("libreria delle basi senza righe valide (stato %s)", status)
        return await mark(store, DOWN, await kept_count(store), now)
    await store.library_put(rows)
    if etag:
        await store.kv_set(ETAG_KEY, {"etag": etag})
    return await mark(store, FRESH, len(rows), now)


async def refresh(store, client, now):
    try:
        return await round_of(store, client, now)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("libreria delle basi non aggiornata (%s)", type(e).__name__)
        return {"status": DOWN, "count": 0}
