import asyncio
import logging
import time

import httpx
from telegram.error import InvalidToken, TelegramError

from . import (base_library, base_videos, manager_alerts, news_feed, ops, publish, render,
               selfmetrics, site_days)
from .bot import ALLOWED_UPDATES, CONSOLE, SINGLE, build_console_app, build_worker_app
from .discord_link import Hub
from .platform_guard import owner_locale
from .poller import CONSOLE_NAME, HEARTBEAT, PLATFORM_INTERVAL, Poller
from .util import now_utc

log = logging.getLogger("clashbot.supervisor")

WATCH_EVERY = 30
BEAT_EVERY = 60
PROBE_EVERY = 300
PROBE_TIMEOUT = 20
BACKOFF_START = 30
BACKOFF_MAX = 600
DEATH_WINDOW = 600
POLLING_ATTR = "_Updater__polling_task"


def polling_task(app):
    updater = getattr(app, "updater", None)
    if updater is None:
        return None
    task = getattr(updater, POLLING_ATTR, None)
    if isinstance(task, asyncio.Task):
        return task
    for value in vars(updater).values():
        if isinstance(value, asyncio.Task):
            return value
    return None


class Supervisor:
    def __init__(self, store, coc, app_factory=None):
        self.store = store
        self.coc = coc
        self.app_factory = app_factory or self.default_factory
        self.apps = {}
        self.fixed = {}
        self.tasks = {}
        self.starting = set()
        self.healed = set()
        self.polling = {}
        self.deaths = {}
        self.retry = {}
        self.probed = {}
        self.default_alias = None
        self.poller = None
        self.web = None
        self.discord = Hub(self, store)
        self.guard = None
        self.stopping = False
        self.manager_checked = False

    def default_factory(self, token, kind, alias):
        if kind == "console":
            return build_console_app(token, self.store, self.coc, self)
        return build_worker_app(token, self.store, self.coc, self, alias)

    def bot(self, alias):
        app = self.apps.get(alias)
        return app.bot if app else None

    def running(self):
        return list(self.apps)

    def owner_changed(self, alias, owner_id):
        app = self.apps.get(alias)
        if app is not None:
            app.bot_data["bot_owner"] = owner_id

    def manager(self):
        return self.apps.get(CONSOLE)

    def owner_bot(self):
        app = self.apps.get(CONSOLE) or next(iter(self.apps.values()), None)
        return app.bot if app else None

    async def start(self):
        if getattr(self.store, "pool", None) is None:
            await self.store.open()
        console_token = await self.store.get_secret("console_token")
        registered = await self.store.bots()
        if console_token:
            self.fixed[CONSOLE] = (console_token, "console")
            await self.launch(console_token, "console", CONSOLE)
            await self.name_console()
            await self.check_manager()
        workers = [bot for bot in registered if bot.kind != "console" and bot.active]
        if not registered:
            await self.start_single()
        else:
            for bot in workers:
                await self.start_bot(bot.alias)
            if len(workers) == 1:
                self.default_alias = workers[0].alias
        publish.watch_errors()
        self.web = publish.Beat(self.store, self, self.coc, HEARTBEAT)
        self.poller = Poller(self, self.store, self.coc)
        self.guard = self.poller.guard
        self.spawn("poller", self.poller.run())
        self.spawn("watch", self.watch())
        self.spawn("beat", self.beat())
        self.spawn("web", self.web_loop())
        self.spawn("ops", self.measure())
        self.spawn("discord", self.discord.run())
        await self.announce()

    async def start_single(self):
        token = await self.store.get_secret("telegram_token")
        if not token:
            log.error("nessun bot configurato: docker compose run --rm bot setup")
            return False
        self.fixed[SINGLE] = (token, "worker")
        self.default_alias = SINGLE
        return await self.launch(token, "worker", SINGLE)

    async def stop(self):
        self.stopping = True
        for name in list(self.tasks):
            task = self.tasks.pop(name)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("%s: chiusura non pulita", name)
        for alias in list(self.apps):
            await self.dispose(self.apps.pop(alias))
        self.fixed.clear()
        self.starting.clear()
        self.healed.clear()
        self.polling.clear()
        self.deaths.clear()
        self.retry.clear()
        self.probed.clear()
        if self.poller is not None and getattr(self.poller, "twitch", None) is not None:
            await self.quietly(self.poller.twitch.close)
        await self.quietly(self.discord.stop)
        await self.quietly(self.coc.close)
        await self.quietly(self.store.close)

    def spawn(self, name, coro):
        self.tasks[name] = asyncio.create_task(coro)
        return self.tasks[name]

    def forget(self, alias):
        self.polling.pop(alias, None)
        self.deaths.pop(alias, None)
        self.retry.pop(alias, None)
        self.probed.pop(alias, None)

    async def launch(self, token, kind, alias):
        app = None
        try:
            app = self.app_factory(token, kind, alias)
            await app.initialize()
            if getattr(app, "post_init", None):
                await app.post_init(app)
            await app.start()
            await app.updater.start_polling(allowed_updates=ALLOWED_UPDATES, drop_pending_updates=True)
        except InvalidToken:
            log.warning("%s: token rifiutato da Telegram", alias)
            if app is not None:
                await self.dispose(app)
            await self.disable_invalid(alias)
            return False
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s: avvio fallito", alias)
            if app is not None:
                await self.dispose(app)
            return False
        self.apps[alias] = app
        self.polling[alias] = polling_task(app)
        self.probed[alias] = time.monotonic()
        self.retry.pop(alias, None)
        log.info("%s @%s avviato (%s)", alias, getattr(app.bot, "username", "?"), kind)
        return True

    async def start_bot(self, alias):
        if alias in self.apps or alias in self.starting:
            return False
        self.starting.add(alias)
        try:
            return await self.launch_bot(alias)
        finally:
            self.starting.discard(alias)

    async def launch_bot(self, alias):
        bot = await self.store.bot_by_alias(alias)
        if not bot or not bot.active:
            return False
        token = await self.store.bot_token(alias)
        if not token:
            log.warning("%s: token illeggibile", alias)
            return False
        if any(token == fixed_token for fixed_token, _ in self.fixed.values()):
            log.warning("%s: stesso token di un bot fisso, serve un riavvio", alias)
            return False
        if not await self.launch(token, bot.kind or "worker", alias):
            return False
        await self.store.touch_bot(alias)
        return True

    async def stop_bot(self, alias, reason=None):
        app = self.apps.pop(alias, None)
        self.forget(alias)
        if app is not None:
            await self.dispose(app)
            log.info("%s: fermato (%s)", alias, reason or "non più attivo")
        row = None
        if reason is not None:
            row = await self.store.set_bot_active(alias, False, reason)
        return bool(app is not None or row)

    async def restart_bot(self, alias):
        if alias in self.fixed:
            return await self.restart(alias)
        if alias in self.starting:
            return False
        self.starting.add(alias)
        try:
            await self.stop_bot(alias)
            return await self.launch_bot(alias)
        finally:
            self.starting.discard(alias)

    async def restart(self, alias):
        if alias in self.starting:
            return False
        self.starting.add(alias)
        try:
            app = self.apps.pop(alias, None)
            self.polling.pop(alias, None)
            if app is not None:
                await self.dispose(app)
            if alias in self.fixed:
                token, kind = self.fixed[alias]
                return await self.launch(token, kind, alias)
            return await self.launch_bot(alias)
        finally:
            self.starting.discard(alias)

    async def name_console(self):
        app = self.manager()
        username = getattr(app.bot, "username", None) if app else None
        if username:
            await self.store.kv_set(CONSOLE_NAME, username)

    async def check_manager(self):
        if self.manager_checked:
            return
        app = self.manager()
        if app is None:
            return
        try:
            me = await app.bot.get_me()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("permesso can_manage_bots non verificato (%s)", type(e).__name__)
            return
        self.manager_checked = True
        if getattr(me, "can_manage_bots", None):
            return
        log.warning("console senza can_manage_bots: accendi il permesso in BotFather")
        L = await manager_alerts.locale(self.store)
        await manager_alerts.send(self.store, app.bot, L.t("console.manager_off"))

    async def warn_manager(self, alias, reason):
        if self.guard is None:
            return False
        bot = await self.store.bot_by_alias(alias)
        L = await owner_locale(self.store)
        return await self.guard.tell_manager(render.platform_stop(L, bot.username if bot else alias, reason))

    async def disable_invalid(self, alias):
        if alias in self.fixed:
            return
        bot = await self.store.set_bot_active(alias, False, "token_invalid")
        if not bot:
            return
        console = self.apps.get(CONSOLE)
        if not console:
            return
        key = "console.bot_recovered" if await self.heal_bot(console, bot) else "console.bot_invalid"
        L = await owner_locale(self.store)
        try:
            await console.bot.send_message(bot.owner_id, L.t(key, alias=alias, username=bot.username))
        except TelegramError as e:
            log.warning("%s: avviso al proprietario non inviato: %s", alias, e)

    async def swap_token(self, manager, bot):
        token = await manager.replace_managed_bot_token(user_id=bot.bot_id)
        await self.store.add_bot(
            bot.owner_id, token, bot.username, bot.bot_id, kind=bot.kind or "worker", trusted=True
        )

    async def heal_bot(self, console, bot):
        if bot.alias in self.healed:
            return False
        self.healed.add(bot.alias)
        try:
            await self.swap_token(console.bot, bot)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.healed.discard(bot.alias)
            log.warning("%s: token non sostituibile (%s)", bot.alias, type(e).__name__)
            return False
        log.info("%s: token sostituito da Telegram, lo rimetto in moto", bot.alias)
        try:
            return await self.restart_bot(bot.alias) or bot.alias in self.starting
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("%s: riavvio dopo la cura fallito (%s)", bot.alias, type(e).__name__)
            return False

    async def watch(self):
        while not self.stopping:
            await asyncio.sleep(WATCH_EVERY)
            if self.stopping:
                return
            try:
                await self.watch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("controllo dei bot fallito")

    async def watch_once(self):
        wanted = {bot.alias for bot in await self.store.bots(active_only=True) if bot.kind != "console"}
        for alias in list(self.apps):
            if alias in self.fixed or alias in wanted:
                continue
            await self.stop_bot(alias)
        for alias in sorted(wanted):
            if alias in self.apps or alias in self.starting or not self.ready(alias):
                continue
            if not await self.start_bot(alias):
                self.hold(alias)
        for alias in sorted(self.fixed):
            if alias in self.apps or alias in self.starting or not self.ready(alias):
                continue
            if not await self.restart(alias):
                self.hold(alias)
        await self.check_updaters()
        await self.probe()
        await self.check_manager()

    def ready(self, alias):
        until, _ = self.retry.get(alias, (0.0, 0))
        return time.monotonic() >= until

    def hold(self, alias):
        _, delay = self.retry.get(alias, (0.0, 0))
        delay = min(delay * 2, BACKOFF_MAX) if delay else BACKOFF_START
        self.retry[alias] = (time.monotonic() + delay, delay)
        log.warning("%s: riprovo fra %s s", alias, delay)

    def dead(self, alias):
        app = self.apps.get(alias)
        if app is None:
            return False
        task = self.polling.get(alias)
        if task is not None and task.done():
            return True
        updater = getattr(app, "updater", None)
        return updater is not None and not getattr(updater, "running", True)

    async def check_updaters(self):
        for alias in list(self.apps):
            if not self.dead(alias):
                continue
            now = time.monotonic()
            last = self.deaths.get(alias)
            repeated = last is not None and now - last <= DEATH_WINDOW
            self.deaths[alias] = now
            if repeated and alias not in self.fixed:
                log.warning("%s: fermo di nuovo, lo tolgo dal giro", alias)
                await self.store.bump_bot_failure(alias)
                await self.stop_bot(alias, "too_many_failures")
                await self.warn_manager(alias, "too_many_failures")
                continue
            log.warning("%s: polling fermo, riavvio", alias)
            if not await self.restart(alias):
                self.hold(alias)

    async def probe(self):
        for alias in list(self.apps):
            now = time.monotonic()
            if now - self.probed.get(alias, 0.0) < PROBE_EVERY:
                continue
            self.probed[alias] = now
            app = self.apps.get(alias)
            if app is None:
                continue
            try:
                await asyncio.wait_for(app.bot.get_me(), PROBE_TIMEOUT)
            except InvalidToken:
                log.warning("%s: token rifiutato da Telegram", alias)
                await self.stop_bot(alias)
                await self.disable_invalid(alias)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("%s: controllo del token rimandato (%s)", alias, type(e).__name__)

    async def beat(self):
        while not self.stopping:
            try:
                HEARTBEAT.touch()
            except OSError:
                pass
            await asyncio.sleep(BEAT_EVERY)

    async def web_loop(self):
        while not self.stopping:
            try:
                await self.web.once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("giro web fallito")
            await asyncio.sleep(publish.BEAT_EVERY)

    async def close_site_day(self, client, now=None):
        return await site_days.close_day(self.store, now or now_utc(),
                                         await self.store.get_secret("owner_tz"), client)

    async def measure(self):
        recorder = selfmetrics.Recorder(self.store, selfmetrics.BOT_KEY)
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
            while not self.stopping:
                await recorder.once()
                await ops.check(self.store, self.owner_bot(), client)
                await ops.safe(self.close_site_day, client)
                await base_library.refresh(self.store, client, time.time())
                key = await base_videos.api_key(self.store)
                await base_videos.refresh(self.store, client, key, time.time())
                await news_feed.collect(self.store, client, key, self.coc, now_utc())
                await asyncio.sleep(PLATFORM_INTERVAL)

    async def announce(self):
        counts = await self.store.counts()
        log.info("avviati %s bot · %s clan attivi su %s", len(self.apps), counts["active"], counts["total"])
        L = await manager_alerts.locale(self.store)
        text = L.t("bot.started", n=counts["active"]) + "\n" + L.t("bot.started_bots", n=len(self.apps))
        await manager_alerts.send(self.store, self.owner_bot(), text)

    async def dispose(self, app):
        updater = getattr(app, "updater", None)
        if updater is not None and getattr(updater, "running", True):
            await self.quietly(updater.stop)
        if getattr(app, "running", True):
            await self.quietly(app.stop)
        await self.quietly(app.shutdown)
        if getattr(app, "post_shutdown", None):
            await self.quietly(lambda: app.post_shutdown(app))
        bot = getattr(app, "bot", None)
        if bot is not None and getattr(bot, "shutdown", None):
            await self.quietly(bot.shutdown)

    async def quietly(self, action):
        try:
            await action()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("chiusura parziale: %s", e)
