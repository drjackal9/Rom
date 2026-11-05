from datetime import datetime, timezone

from .platform_guard import notify, owner_locale
from .retention import WAR_HISTORY_KEEP

ACTIONS = "actions"
KINDS = ("keys", "restore", "ops", ACTIONS, "api")
KEEP = WAR_HISTORY_KEEP
REPORT_MARK = "report"
OPENS_KEY = "site:opens"

locale = owner_locale


def key_of(kind):
    return f"platform:{kind}"


def moment(at):
    try:
        return datetime.fromtimestamp(float(at), timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def rows_of(stored):
    return [row for row in (stored or {}).get("history") or () if isinstance(row, dict)]


def grown(rows, entry, at):
    return rows[-(KEEP - 1):] + [{**entry, "at": at}]


def due(stored, signature):
    return (stored or {}).get("sig") != signature or not (stored or {}).get("sent")


async def owner_id(store):
    try:
        return int(await store.get_secret("owner_id"))
    except (TypeError, ValueError):
        return None


async def send(store, bot, text, ids=None):
    if ids is None:
        return await notify(bot, await owner_id(store), text)
    done = False
    for chat in ids:
        if await notify(bot, chat, text):
            done = True
    return done


async def from_console(store, supervisor, text):
    return await send(store, supervisor.owner_bot() if supervisor else None, text)


async def opened(store, at):
    when = at if isinstance(at, datetime) else moment(at)
    if when is None:
        return 0
    stored = await store.kv_get(OPENS_KEY) or {}
    counts = {str(key): int(value or 0) for key, value in dict(stored).items()}
    month = when.strftime("%Y-%m")
    counts[month] = counts.get(month, 0) + 1
    kept = {key: counts[key] for key in sorted(counts)[-KEEP:]}
    await store.kv_set(OPENS_KEY, kept)
    return kept.get(month, 0)


async def state(store, kind):
    stored = await store.kv_get(key_of(kind))
    return stored if isinstance(stored, dict) else {}


async def write(store, kind, signature, at, sent, rows):
    await store.kv_set(key_of(kind), {"sig": signature, "at": at, "sent": bool(sent), "history": rows})


async def pending(store, kind, signature):
    return due(await state(store, kind), signature)


async def record(store, kind, signature, entry, at):
    if kind not in KINDS:
        return False
    await write(store, kind, signature, at, True, grown(rows_of(await state(store, kind)), entry, at))
    return True


async def on_change(store, bot, kind, signature, entry, text, at, ids=None):
    if kind not in KINDS:
        return False
    stored = await state(store, kind)
    if not due(stored, signature):
        return False
    rows = rows_of(stored)
    if stored.get("sig") != signature:
        rows = grown(rows, entry, at)
    sent = await send(store, bot, text, ids)
    await write(store, kind, signature, at, sent, rows)
    return sent


async def last(store, kind):
    rows = rows_of(await state(store, kind))
    return rows[-1] if rows else None


async def history(store, kind, limit=10):
    return list(reversed(rows_of(await state(store, kind))))[:limit]
