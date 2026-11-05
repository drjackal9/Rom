import asyncio
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("clashbot.selfmetrics")

PLATFORM_INTERVAL = 600
CGROUP = "/sys/fs/cgroup"
PROC = "/proc"
BOT_KEY = "ops:bot"
WEB_KEY = "ops:web"
POLL_KEY = "ops:poll"
PROBE_KEY = "ops:probe"
LAST_KEY = "ops:last"
PROBE_DAY = "ops:probe:"
WEB_DAY = "web:day:"
DAY = 86400
DAY_TTL = 2 * DAY
SAMPLES_MAX = DAY // PLATFORM_INTERVAL
USEC_PER_S = 1000000
NANO_PER_USEC = 1000
KB = 1024
START_FIELD = 19


def ticks():
    try:
        return os.sysconf("SC_CLK_TCK")
    except (AttributeError, ValueError, OSError):
        return None


TICKS = ticks()


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def read_int(path):
    raw = read_text(path)
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def first_float(path):
    parts = (read_text(path) or "").split()
    if not parts:
        return None
    try:
        return float(parts[0])
    except ValueError:
        return None


def field(raw, name, factor=1):
    for line in (raw or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name:
            try:
                return int(parts[1]) * factor
            except ValueError:
                return None
    return None


def mem_used(root):
    found = read_int(Path(root) / "memory.current")
    if found is None:
        found = read_int(Path(root) / "memory" / "memory.usage_in_bytes")
    return found


def mem_limit(root):
    found = read_int(Path(root) / "memory.max")
    if found is None:
        found = read_int(Path(root) / "memory" / "memory.limit_in_bytes")
    return found


def cpu_used(root):
    found = field(read_text(Path(root) / "cpu.stat"), "usage_usec")
    if found is not None:
        return found
    nanos = read_int(Path(root) / "cpuacct" / "cpuacct.usage")
    return nanos // NANO_PER_USEC if nanos is not None else None


def cores(previous, used, moment):
    if used is None or not isinstance(previous, dict):
        return None
    before = previous.get("cpu_usec")
    since = previous.get("ts")
    if before is None or since is None or used < before:
        return None
    elapsed = moment - float(since)
    if elapsed <= 0:
        return None
    return (used - before) / (elapsed * USEC_PER_S)


def host_available(proc):
    return field(read_text(Path(proc) / "meminfo"), "MemAvailable:", KB)


def age(proc):
    booted = first_float(Path(proc) / "uptime")
    started = start_seconds(Path(proc) / "self" / "stat")
    if booted is None or started is None:
        return None
    return booted - started if booted >= started else None


def start_seconds(path):
    raw = read_text(path)
    if raw is None or not TICKS:
        return None
    parts = raw.rpartition(")")[2].split()
    if len(parts) <= START_FIELD:
        return None
    try:
        return int(parts[START_FIELD]) / TICKS
    except ValueError:
        return None


def sample(root=CGROUP, proc=PROC, previous=None, now=None):
    moment = time.time() if now is None else float(now)
    used = cpu_used(root)
    alive = age(proc)
    return {
        "ts": moment,
        "mem_bytes": mem_used(root),
        "mem_limit": mem_limit(root),
        "cpu_usec": used,
        "cpu_cores": cores(previous, used, moment),
        "load1": first_float(Path(proc) / "loadavg"),
        "host_mem_available": host_available(proc),
        "uptime_s": alive,
        "pid_started": moment - alive if alive is not None else None,
    }


class Recorder:
    def __init__(self, store, key, interval=PLATFORM_INTERVAL, extra=None):
        self.store = store
        self.key = key
        self.interval = interval
        self.extra = extra
        self.previous = None
        self.due_at = 0.0

    async def tick(self, now=None):
        moment = time.monotonic() if now is None else float(now)
        if moment < self.due_at:
            return None
        self.due_at = moment + self.interval
        return await self.once()

    async def once(self):
        current = sample(previous=self.previous)
        self.previous = current
        if self.extra is not None:
            current = {**current, **self.extra()}
        try:
            await self.store.kv_set(self.key, current, ttl=2 * self.interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("%s: campione non salvato (%s)", self.key, type(e).__name__)
            return None
        return current
