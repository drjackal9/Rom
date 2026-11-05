import logging
import time
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from . import i18n, render
from .settings import valid_tz
from .util import now_utc

log = logging.getLogger("clashbot.platform")

PER_MINUTE = 15
MINUTE = 60.0
FLOOD_LIMIT = 5
FLOOD_WINDOW = 3600
SUMMARY_HOUR = 9
SUMMARY_KEY = "platform:summary"
SUMMARY_TTL = 2 * 86400
STATE_KEY = "platform:state"
STATE_TTL = SUMMARY_TTL
IDLE_DAYS = 90
GRACE_DAYS = 30
IDLE_TTL = (IDLE_DAYS + GRACE_DAYS + 16) * 86400
FLOOD_REASON = "flood"
IDLE_REASON = "abandoned"
DEFAULT_TZ = "UTC"


def zone(tz):
    return ZoneInfo(tz if valid_tz(tz) else DEFAULT_TZ)


async def owner_locale(store):
    return i18n.locale(await store.get_secret("owner_lang"))


async def notify(bot, chat_id, text, **extra):
    if not bot or not chat_id or not text:
        return False
    try:
        await bot.send_message(chat_id, text, **extra)
        return True
    except TelegramError as e:
        log.warning("avviso non consegnato: %s", type(e).__name__)
        return False


class Buckets:
    def __init__(self, per_minute=PER_MINUTE):
        self.per_minute = float(per_minute)
        self.tokens = {}
        self.stamp = {}

    def take(self, chat_id, now):
        key = str(chat_id)
        last = self.stamp.get(key)
        left = self.per_minute if last is None else min(
            self.per_minute, self.tokens.get(key, 0.0) + (float(now) - last) * self.per_minute / MINUTE
        )
        self.stamp[key] = float(now)
        if left < 1.0:
            self.tokens[key] = left
            return False
        self.tokens[key] = left - 1.0
        return True

    def dump(self, now):
        fresh = {}
        for key, last in self.stamp.items():
            age = float(now) - float(last)
            if age < MINUTE:
                fresh[key] = [self.tokens.get(key, 0.0), age]
        return fresh

    def load(self, data, now):
        for key, pair in (data or {}).items():
            tokens, age = pair
            self.tokens[key] = min(self.per_minute, max(0.0, float(tokens)))
            self.stamp[key] = float(now) - max(0.0, float(age))


def recent(hits, now, window=FLOOD_WINDOW):
    return [float(ts) for ts in hits or () if float(now) - float(ts) < window]


def flood_state(state, now, window=FLOOD_WINDOW):
    return {"hits": recent((state or {}).get("hits"), now, window) + [float(now)]}


def flooding(state, limit=FLOOD_LIMIT):
    return len((state or {}).get("hits") or []) >= limit


def summary_due(state, now, tz, hour=SUMMARY_HOUR):
    local = now.astimezone(zone(tz))
    if local.hour < hour:
        return None
    day = local.strftime("%Y-%m-%d")
    return None if (state or {}).get("day") == day else day


def idle_step(state, now, idle_days=IDLE_DAYS, grace_days=GRACE_DAYS):
    since = (state or {}).get("since")
    if not since:
        return "start", {"since": float(now)}
    warned = (state or {}).get("warned")
    if not warned:
        if float(now) - float(since) < idle_days * 86400:
            return "wait", None
        return "warn", {"since": float(since), "warned": float(now)}
    if float(now) - float(warned) < grace_days * 86400:
        return "wait", None
    return "stop", None


def days_left(state, now, grace_days=GRACE_DAYS):
    warned = (state or {}).get("warned")
    if not warned:
        return None
    return max(0, int((float(warned) + grace_days * 86400 - float(now)) // 86400))


class Guard:
    def __init__(self, store, supervisor, clock=time.monotonic):
        self.store = store
        self.supervisor = supervisor
        self.clock = clock
        self.buckets = Buckets()
        self.sent = {}
        self.delayed = {}
        self.dropped = {}
        self.dirty = False

    def allow(self, chat_id):
        self.dirty = True
        return self.buckets.take(chat_id, self.clock())

    def note_sent(self, alias, n=1):
        if alias and n > 0:
            self.sent[alias] = self.sent.get(alias, 0) + n
            self.dirty = True

    def delay(self, alias, n=1):
        if alias and n > 0:
            self.delayed[alias] = self.delayed.get(alias, 0) + n
            self.dirty = True

    def drop(self, alias, n=1):
        if alias and n > 0:
            self.dropped[alias] = self.dropped.get(alias, 0) + n
            self.dirty = True
            log.warning("%s: coda piena, %s messaggi scartati", alias, n)

    async def load(self):
        state = await self.store.kv_get(STATE_KEY) or {}
        at = float(state.get("at") or 0.0)
        down = max(0.0, now_utc().timestamp() - at) if at else 0.0
        self.buckets.load(state.get("buckets"), self.clock() - down)
        self.sent = {name: int(n) for name, n in (state.get("sent") or {}).items()}
        self.delayed = {name: int(n) for name, n in (state.get("delayed") or {}).items()}
        self.dropped = {name: int(n) for name, n in (state.get("dropped") or {}).items()}
        self.dirty = False

    async def save(self):
        if not self.dirty:
            return False
        state = {
            "at": now_utc().timestamp(),
            "buckets": self.buckets.dump(self.clock()),
            "sent": dict(self.sent),
            "delayed": dict(self.delayed),
            "dropped": dict(self.dropped),
        }
        await self.store.kv_set(STATE_KEY, state, ttl=STATE_TTL)
        self.dirty = False
        return True

    async def manager(self):
        owner = await self.store.get_secret("owner_id")
        try:
            return int(owner) if owner else None
        except (TypeError, ValueError):
            return None

    async def tell_manager(self, text):
        return await notify(self.supervisor.owner_bot(), await self.manager(), text)

    async def tell_owner(self, row, text):
        bot = self.supervisor.bot(row.alias) or self.supervisor.owner_bot()
        return await notify(bot, row.owner_id, text)

    async def flood(self, alias, now=None):
        if not alias:
            return False
        moment = (now or now_utc()).timestamp()
        key = f"flood:{alias}"
        state = flood_state(await self.store.kv_get(key), moment)
        await self.store.kv_set(key, state, ref=alias, ttl=FLOOD_WINDOW)
        if not flooding(state):
            return False
        await self.store.kv_del(key)
        row = await self.store.bot_by_alias(alias)
        await self.supervisor.stop_bot(alias, FLOOD_REASON)
        log.warning("%s: troppe risposte di flood in un'ora, fermato", alias)
        L = await owner_locale(self.store)
        await self.tell_manager(render.platform_stop(L, row.username if row else alias, FLOOD_REASON))
        return True

    async def idle_bots(self, now):
        moment = now.timestamp()
        for row in await self.store.bots(active_only=True):
            if row.kind == "console":
                continue
            key = f"idle:{row.alias}"
            if await self.store.count_clans(row.alias):
                await self.store.kv_del(key)
                continue
            step, state = idle_step(await self.store.kv_get(key), moment)
            if state is not None:
                await self.store.kv_set(key, state, ref=row.alias, ttl=IDLE_TTL)
            if step == "warn":
                await self.warn_idle(row)
            elif step == "stop":
                await self.stop_idle(row, key)

    async def warn_idle(self, row):
        L = await owner_locale(self.store)
        await self.tell_owner(row, render.platform_idle(L, IDLE_DAYS, GRACE_DAYS))
        await self.tell_manager(render.platform_idle_note(L, row.username, IDLE_DAYS))

    async def stop_idle(self, row, key):
        L = await owner_locale(self.store)
        days = IDLE_DAYS + GRACE_DAYS
        await self.tell_owner(row, render.platform_stopped(L, days))
        await self.store.kv_del(key)
        await self.supervisor.stop_bot(row.alias, IDLE_REASON)
        log.info("%s: senza clan da %s giorni, fermato", row.alias, days)
        await self.tell_manager(render.platform_stop(L, row.username, IDLE_REASON))

    async def clan_name(self, alias):
        row = await self.store.clan_by_alias(alias)
        return getattr(row, "name", None) or alias

    async def report(self, now=None):
        moment = (now or now_utc()).timestamp()
        bots = [row for row in await self.store.bots() if row.kind != "console"]
        running = set(self.supervisor.running())
        counts = await self.store.counts()
        actions = []
        for kind, counters in (("delayed", self.delayed), ("dropped", self.dropped)):
            for alias, n in sorted(counters.items()):
                actions.append({"kind": kind, "name": await self.clan_name(alias), "n": n})
        for row in bots:
            if not row.active or await self.store.count_clans(row.alias):
                continue
            left = days_left(await self.store.kv_get(f"idle:{row.alias}"), moment)
            if left is not None:
                actions.append({"kind": "idle", "name": row.username, "n": left})
        self.sent = {}
        self.delayed = {}
        self.dropped = {}
        self.dirty = True
        return {
            "bots": len(bots),
            "running": len([row for row in bots if row.alias in running]),
            "clans": int(counts["active"]),
            "clans_total": int(counts["total"]),
            "errors": [{"name": row.username, "reason": row.reason} for row in bots if not row.active],
            "actions": actions,
        }

    async def daily(self, now):
        day = summary_due(await self.store.kv_get(SUMMARY_KEY), now, await self.store.get_secret("owner_tz"))
        if not day:
            return False
        manager = await self.manager()
        if not manager:
            return False
        await self.store.kv_set(SUMMARY_KEY, {"day": day}, ttl=SUMMARY_TTL)
        L = await owner_locale(self.store)
        text = render.platform_summary(L, await self.report(now))
        sent = await notify(self.supervisor.owner_bot(), manager, text)
        await self.save()
        return sent
