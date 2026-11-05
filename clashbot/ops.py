import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import key_watch, manager_alerts, media, publish, render
from .platform_guard import FLOOD_LIMIT, FLOOD_WINDOW
from .selfmetrics import (BOT_KEY, DAY_TTL, LAST_KEY, PLATFORM_INTERVAL, POLL_KEY, PROBE_DAY,
                          PROBE_KEY, SAMPLES_MAX, WEB_KEY)
from .util import day_of
from .web import ban

log = logging.getLogger("clashbot.ops")

PACK = "platform"
EVENTS = ("platform.ops",)
KIND = "ops"
BACKUP_LOG = "/backup/backup.log"
DUMP_MARK = "db-ok"
STATUS_PATH = "/status.json"
OK_STATUS = 200
MB = 1024 * 1024
GB = 1024 * MB
MEM_LIMIT = 2 * GB
CPU_LIMIT = 2
HOUR = 3600
ERRORS_WINDOW = FLOOD_WINDOW
OWN_ALERT = ("keys_dead",)
FLOATS = ("bot_cpu",)
CONTAINERS = (("bot", "clashbot"), ("web", "clashbot-web"))
OK = "ok"
UNKNOWN = "unknown"
BAD = "bad"
STAMP = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (\S+)")
CDN = "cloudflare"


async def safe(call, *args):
    try:
        return await call(*args)
    except asyncio.CancelledError:
        raise
    except Exception:
        return None


def moment_of(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def stamps(text):
    rows = []
    for line in (text or "").splitlines():
        found = STAMP.match(line)
        when = moment_of(found.group(1)) if found else None
        if when is not None:
            rows.append((when, found.group(2)))
    return rows


def dump_age_h(path, now):
    file = Path(path)
    try:
        rows = stamps(file.read_text(encoding="utf-8"))
        written = file.stat().st_mtime
    except (OSError, ValueError):
        return None
    if not rows:
        return None
    shift = written - rows[-1][0]
    for when, mark in reversed(rows):
        if mark == DUMP_MARK:
            return max(0.0, (float(now) - (when + shift)) / HOUR)
    return None


def errors(now, window=ERRORS_WINDOW):
    rows = publish.RECENT.errors_in(window, now)
    return {"n": len(rows), "window": window, "last": rows[-1] if rows else None}


async def probe(site_base, client, now=None):
    at = time.time() if now is None else float(now)
    url = (site_base or "").rstrip("/") + STATUS_PATH
    started = time.monotonic()
    try:
        res = await client.get(url)
        status = int(res.status_code)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("sonda pubblica caduta (%s)", type(e).__name__)
        return {"ok": False, "ms": None, "status": None, "at": at, "cdn": False}
    return {"ok": status == OK_STATUS, "ms": int((time.monotonic() - started) * 1000),
            "status": status, "at": at,
            "cdn": CDN in str(dict(res.headers).get("server") or "").lower()}


async def probe_day(store, found, day):
    key = PROBE_DAY + str(day)
    stored = await store.kv_get(key) or {}
    samples = [whole(one) for one in stored.get("ms") or ()]
    samples = [one for one in samples if one is not None]
    if found.get("ms") is not None:
        samples = (samples + [int(found["ms"])])[-SAMPLES_MAX:]
    body = {"ok": int(stored.get("ok") or 0) + (1 if found.get("ok") else 0),
            "total": int(stored.get("total") or 0) + 1, "ms": samples,
            "cdn": bool(stored.get("cdn")) or bool(found.get("cdn"))}
    await store.kv_set(key, body, ttl=DAY_TTL)
    return body


async def alerts_of(store):
    rows = await safe(manager_alerts.history, store, KIND, manager_alerts.KEEP) or []
    return [row for row in rows if row.get("keys")]


async def snapshot(store, now):
    when = float(now)
    return {
        "bot": await safe(store.kv_get, BOT_KEY),
        "web": await safe(store.kv_get, WEB_KEY),
        "db_bytes": await safe(store.db_size_bytes),
        "dump_age_h": dump_age_h(BACKUP_LOG, when),
        "poll": await safe(store.kv_get, POLL_KEY),
        "intents_age_s": await safe(store.intent_oldest_age, when),
        "errors": errors(when),
        "probe": await safe(store.kv_get, PROBE_KEY),
        "keys": await safe(manager_alerts.last, store, key_watch.KIND),
        "banned": await safe(ban.summary, store, when),
        "alerts": await alerts_of(store),
    }


def note(key, value=None, limit=None, who=None):
    return {"key": key, "value": value, "limit": limit, "who": who}


def level_of(value):
    try:
        return int(float(value) // GB)
    except (TypeError, ValueError):
        return 0


def down_twice(now, before):
    if not isinstance(now, dict) or not isinstance(before, dict):
        return False
    if now.get("ok") or before.get("ok"):
        return False
    return now.get("at") != before.get("at")


def restarted(now, before):
    if not isinstance(now, dict) or not isinstance(before, dict):
        return False
    alive, was = now.get("uptime_s"), before.get("uptime_s")
    return alive is not None and was is not None and alive < was


def strange(current, previous):
    was = previous if isinstance(previous, dict) else {}
    found = []
    bot = current.get("bot") or {}
    mem = bot.get("mem_bytes")
    if mem is not None and mem > MEM_LIMIT:
        found.append(note("bot_mem", mem // MB, MEM_LIMIT // MB))
    cores = bot.get("cpu_cores")
    if cores is not None and cores > CPU_LIMIT:
        found.append(note("bot_cpu", cores, CPU_LIMIT))
    level = level_of(current.get("db_bytes"))
    if level and level > level_of(was.get("db_bytes")):
        found.append(note("db_gb", level))
    poll = current.get("poll") or {}
    took, interval = poll.get("took"), poll.get("interval")
    if took is not None and interval is not None and took > interval:
        found.append(note("poll_slow", int(took), int(interval)))
    age = current.get("intents_age_s")
    if age is not None and age > PLATFORM_INTERVAL:
        found.append(note("intents_stuck", int(age), PLATFORM_INTERVAL))
    if down_twice(current.get("probe"), was.get("probe")):
        found.append(note("probe_down"))
    for name in ("bot", "web"):
        if restarted(current.get(name), was.get(name)):
            found.append(note("restarted", who=name))
    keys = current.get("keys") or {}
    dead = int(keys.get("total") or 0) - int(keys.get("alive") or 0)
    if dead > 0:
        found.append(note("keys_dead", dead, keys.get("total")))
    burst = current.get("errors") or {}
    if int(burst.get("n") or 0) >= publish.KEEP_ERRORS:
        found.append(note("errors_burst", burst.get("n")))
    probes = whole((current.get("banned") or {}).get("hour"))
    if probes is not None and probes > FLOOD_LIMIT:
        found.append(note("probes_burst", probes, FLOOD_LIMIT))
    return found


def tag(row):
    return f"{row['key']}:{row['who']}" if row.get("who") else row["key"]


def signature(found):
    return ",".join(sorted(tag(row) for row in found)) or "ok"


def entry(found):
    return {"keys": sorted(tag(row) for row in found)}


def active_of(stored):
    sig = (stored or {}).get("sig") or ""
    if not (stored or {}).get("sent", True):
        return set()
    return set() if sig in ("", "ok") else set(sig.split(","))


def shown(L, key, value):
    if value is None:
        return ""
    return render.fixed(L, value) if key in FLOATS else L.n(value)


def line(L, row):
    return L.t(f"owner.ops.{row['key']}", n=shown(L, row["key"], row.get("value")),
               limit=shown(L, row["key"], row.get("limit")), who=row.get("who") or "")


def card(L, rows):
    return render.card("🩺", L.t("owner.ops.title"), "\n".join(line(L, row) for row in rows))


def mb_of(value):
    try:
        return int(float(value) // MB)
    except (TypeError, ValueError):
        return None


def whole(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def state_of(value, limit=None):
    if value is None:
        return UNKNOWN
    return BAD if limit is not None and value > limit else OK


def worst(*levels):
    for name in (BAD, UNKNOWN):
        if name in levels:
            return name
    return OK


def slot(key, level, **args):
    return {"key": key, "level": level, "args": args}


def bot_slot(current):
    bot = current.get("bot") or {}
    mem, cores, limit = mb_of(bot.get("mem_bytes")), bot.get("cpu_cores"), MEM_LIMIT // MB
    return slot("bot", worst(state_of(mem, limit), state_of(cores, CPU_LIMIT)),
                mem=mem, limit=limit, cpu=cores, cpu_limit=CPU_LIMIT)


def web_slot(current):
    web = current.get("web") or {}
    mem, limit = mb_of(web.get("mem_bytes")), mb_of(web.get("mem_limit"))
    cores = web.get("cpu_cores")
    return slot("web", worst(state_of(mem, limit), state_of(cores)),
                mem=mem, limit=limit, cpu=cores)


def count_slot(current, name):
    found = whole((current.get("web") or {}).get(name))
    return slot(f"web.{name}", state_of(found), n=found)


def live_slot(current):
    return count_slot(current, "live")


def pages_slot(current):
    return count_slot(current, "pages")


def notified_slot(current):
    return count_slot(current, "notified")


def host_slot(current):
    bot = current.get("bot") or {}
    load, free = bot.get("load1"), mb_of(bot.get("host_mem_available"))
    return slot("host", worst(state_of(load), state_of(free)), load=load, mem=free)


def db_slot(current):
    size = mb_of(current.get("db_bytes"))
    return slot("db", state_of(size), mem=size)


def dump_slot(current):
    hours = whole(current.get("dump_age_h"))
    return slot("dump", state_of(hours), n=hours)


def poll_slot(current):
    poll = current.get("poll") or {}
    took, interval = whole(poll.get("took")), whole(poll.get("interval"))
    return slot("poll", state_of(took, interval), n=took, limit=interval, clans=poll.get("clans"))


def intents_slot(current):
    age = whole(current.get("intents_age_s"))
    if age is None:
        return slot("intents_empty", OK)
    return slot("intents", state_of(age, PLATFORM_INTERVAL), n=age, limit=PLATFORM_INTERVAL)


def errors_slot(current):
    burst = current.get("errors") or {}
    seen = int(burst.get("n") or 0)
    return slot("errors", BAD if seen >= publish.KEEP_ERRORS else OK,
                n=seen, limit=publish.KEEP_ERRORS, window=burst.get("window"))


def probe_slot(current):
    probe = current.get("probe")
    if not isinstance(probe, dict):
        return slot("probe", UNKNOWN, n=None)
    if not probe.get("ok"):
        return slot("probe_down", BAD)
    return slot("probe", OK, n=probe.get("ms"))


def keys_slot(current):
    keys = current.get("keys")
    if not isinstance(keys, dict):
        return slot("keys", UNKNOWN, n=None, limit=None)
    alive, total = int(keys.get("alive") or 0), int(keys.get("total") or 0)
    return slot("keys", BAD if total - alive > 0 else OK, n=alive, limit=total)


def banned_slot(current):
    body = current.get("banned")
    if not isinstance(body, dict):
        return slot("banned", UNKNOWN, n=None, hour=None)
    hour = whole(body.get("hour"))
    return slot("banned", BAD if hour is not None and hour > FLOOD_LIMIT else OK,
                n=whole(body.get("n")), hour=hour)


SLOTS = (bot_slot, web_slot, live_slot, pages_slot, notified_slot, host_slot, db_slot, dump_slot,
         poll_slot, intents_slot, errors_slot, probe_slot, keys_slot, banned_slot)


def seen_of(row):
    return {"when": manager_alerts.moment(row.get("at")),
            "keys": " · ".join(str(key) for key in row.get("keys") or ())}


def board(current):
    return {"rows": [make(current) for make in SLOTS],
            "alerts": [seen_of(row) for row in current.get("alerts") or ()]}


def today(current):
    rows = {}
    for field, name in CONTAINERS:
        body = current.get(field)
        if not isinstance(body, dict):
            continue
        mem, cores = mb_of(body.get("mem_bytes")), body.get("cpu_cores")
        if mem is None and cores is None:
            continue
        rows[name] = {"mem_mb": mem, "cpu": cores}
    return rows


async def containers(store):
    return today({"bot": await safe(store.kv_get, BOT_KEY), "web": await safe(store.kv_get, WEB_KEY)})


async def watch(store, bot, current, previous, at):
    found = strange(current, previous)
    stored = await manager_alerts.state(store, KIND)
    sig = signature(found)
    if not manager_alerts.due(stored, sig):
        return False
    known = active_of(stored)
    fresh = [row for row in found if tag(row) not in known and row["key"] not in OWN_ALERT]
    if not fresh:
        await manager_alerts.record(store, KIND, sig, entry(found), at)
        return False
    L = await manager_alerts.locale(store)
    return await manager_alerts.on_change(store, bot, KIND, sig, entry(found), card(L, fresh), at)


async def round_of(store, bot, client, now):
    at = time.time() if now is None else float(now)
    site = await media.site_base(store)
    if site and client is not None:
        found = await probe(site, client, at)
        await store.kv_set(PROBE_KEY, found, ttl=2 * PLATFORM_INTERVAL)
        await safe(probe_day, store, found, day_of(at, await store.get_secret("owner_tz")))
    current = await snapshot(store, at)
    sent = await watch(store, bot, current, await safe(store.kv_get, LAST_KEY), at)
    await store.kv_set(LAST_KEY, {name: body for name, body in current.items() if name != "alerts"})
    return sent


async def check(store, bot, client=None, now=None):
    try:
        return await round_of(store, bot, client, now)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("quadro ops non aggiornato (%s)", type(e).__name__)
        return False
