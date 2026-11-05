import asyncio
import logging

import discord

from . import bridge, i18n, integrations
from . import settings as settings_mod
from .settings import is_quiet
from .util import now_utc

log = logging.getLogger("clashbot.discord")

RECONCILE_EVERY = 30
REASONS = ("token", "intent", "channel", "permission", "network")
RETRY_REASONS = ("network",)
BUTTON_LIMIT = 100


def ready(client):
    check = getattr(client, "is_ready", None)
    return check() if callable(check) else True


def make_intents():
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    return intents


class Client(discord.Client):
    def __init__(self, alias, hub):
        super().__init__(intents=make_intents(), max_messages=None, chunk_guilds_at_startup=False)
        self.alias = alias
        self.hub = hub

    async def on_message(self, message):
        await self.hub.from_discord(self.alias, message)


def default_factory(alias, hub):
    return Client(alias, hub)


async def probe(token):
    client = discord.Client(intents=discord.Intents.none())
    try:
        await client.login(token)
        rows = []
        async for guild in client.fetch_guilds(limit=BUTTON_LIMIT):
            channels = [c for c in await guild.fetch_channels() if isinstance(c, discord.TextChannel)]
            rows.append({"id": guild.id, "name": guild.name,
                         "channels": [{"id": c.id, "name": c.name}
                                      for c in channels[:BUTTON_LIMIT]]})
        return rows, None
    except discord.LoginFailure:
        return [], "token"
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("Discord: prova del token non riuscita (%s)", type(e).__name__)
        return [], "network"
    finally:
        await client.close()


class Hub:
    def __init__(self, supervisor, store, factory=default_factory, every=RECONCILE_EVERY):
        self.supervisor = supervisor
        self.store = store
        self.factory = factory
        self.every = every
        self.clients = {}
        self.tasks = {}
        self.marks = {}
        self.rows = {}
        self.broken = {}
        self.stopping = False

    def alive(self):
        return sorted(self.clients)

    def bot_for(self, clan):
        return self.supervisor.bot(getattr(clan, "bot_alias", None) or self.supervisor.default_alias)

    async def run(self):
        while not self.stopping:
            await asyncio.sleep(self.every)
            if self.stopping:
                return
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ponte Discord: giro fallito")

    async def wanted(self):
        out = {}
        for clan in await self.store.active_clans():
            alias = getattr(clan, "bot_alias", None) or self.supervisor.default_alias
            if alias not in self.supervisor.running():
                continue
            conf = settings_mod.effective(await self.store.get_state(clan.alias, "settings"), None)
            if not settings_mod.pack_on(conf, integrations.PACK):
                continue
            cfg = bridge.config(await self.store.get_state(clan.alias, "discord"))
            if cfg:
                out[clan.alias] = (clan, conf, cfg)
        return out

    async def reconcile(self):
        wanted = await self.wanted()
        for alias in sorted(set(self.clients) | set(self.broken)):
            entry = wanted.get(alias)
            mark = bridge.digest(entry[2]) if entry else ""
            if alias in self.broken and mark != self.marks.get(alias):
                self.broken.pop(alias, None)
            if entry is None or mark != self.marks.get(alias) or alias in self.broken:
                reason = self.broken.get(alias)
                await self.dispose(alias)
                if reason:
                    await self.warn(alias, reason)
                    if reason in RETRY_REASONS:
                        self.broken.pop(alias, None)
                    else:
                        self.broken[alias] = None
        for alias, (clan, conf, cfg) in sorted(wanted.items()):
            if alias in self.clients or alias in self.broken:
                self.rows[alias] = (clan, conf, cfg)
                continue
            await self.start_clan(clan, conf, cfg)

    async def start_clan(self, clan, conf, cfg):
        client = self.factory(clan.alias, self)
        self.clients[clan.alias] = client
        self.rows[clan.alias] = (clan, conf, cfg)
        self.marks[clan.alias] = bridge.digest(cfg)
        self.tasks[clan.alias] = asyncio.create_task(self.hold(clan.alias, client, cfg["token"]))

    async def hold(self, alias, client, token):
        try:
            await client.start(token)
            self.broken[alias] = "network"
        except asyncio.CancelledError:
            raise
        except discord.LoginFailure:
            self.broken[alias] = "token"
        except discord.PrivilegedIntentsRequired:
            self.broken[alias] = "intent"
        except Exception as e:
            self.broken[alias] = "network"
            log.warning("%s: ponte Discord interrotto (%s)", alias, type(e).__name__)

    async def dispose(self, alias):
        task = self.tasks.pop(alias, None)
        client = self.clients.pop(alias, None)
        if task is not None and not task.done():
            task.cancel()
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                log.warning("%s: chiusura del ponte parziale (%s)", alias, type(e).__name__)
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.warning("%s: ponte chiuso male (%s)", alias, type(e).__name__)

    async def to_discord(self, clan, name, text, label):
        client = self.clients.get(clan.alias)
        row = self.rows.get(clan.alias)
        content = bridge.to_discord(name, text, label)
        if not client or not row or not content:
            return False
        channel = client.get_channel(row[2]["channel_id"])
        if channel is None:
            if ready(client):
                self.broken[clan.alias] = "channel"
            return False
        try:
            await channel.send(content, allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.Forbidden:
            self.broken[clan.alias] = "permission"
        except discord.HTTPException as e:
            log.warning("%s: messaggio verso Discord non consegnato (%s)", clan.alias, type(e).__name__)
        return False

    async def from_discord(self, alias, message, now=None):
        client = self.clients.get(alias)
        row = self.rows.get(alias)
        if not client or not row:
            return 0
        clan, conf, cfg = row
        if not bridge.from_discord_ok(message, getattr(client, "user", None), cfg["channel_id"]):
            return 0
        L = i18n.locale(conf["lang"])
        text = bridge.to_telegram(getattr(message.author, "display_name", None),
                                  getattr(message, "content", ""),
                                  bridge.attachments_label(L, getattr(message, "attachments", None)))
        if not text:
            return 0
        moment = now or now_utc()
        return await integrations.send_event(self.store, self.bot_for(clan), clan, conf,
                                             integrations.BRIDGE_EVENT, text,
                                             silent=is_quiet(conf, moment), now=moment)

    async def warn(self, alias, reason):
        row = self.rows.get(alias)
        if not row or reason not in REASONS:
            return
        clan, conf, _ = row
        L = i18n.locale(conf["lang"])
        await integrations.notice(self.store, self.bot_for(clan), clan, conf, f"discord_{reason}",
                                  L.t(f"discord.error.{reason}"), now_utc())

    async def stop(self):
        self.stopping = True
        for alias in list(self.clients):
            await self.dispose(alias)
        self.rows.clear()
        self.marks.clear()
        self.broken.clear()
