import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import asyncpg

from .platform_guard import IDLE_TTL
from .recruit import matches as recruit_matches, ordered as recruit_ordered
from .roster import FORMER_SHOWN
from .retention import (BASE_KEEP, COUNT_SQL, DELETE_SQL, LEADER_LOG_KEEP, MEMBER_HISTORY_KEEP,
                        PRUNE_CLAN_BASES_SQL, PRUNE_CLAN_LOG_SQL, PRUNE_CLAN_MEMBERS_SQL,
                        PRUNE_CLAN_STATS_SQL, PRUNE_CLAN_WARS_SQL, STAT_HISTORY_KEEP,
                        WAR_HISTORY_KEEP, deleted_rows)
from .util import normalize_tag

log = logging.getLogger("clashbot.db")

DATABASE = "clashbot"

SCHEMA = """
create table if not exists secrets (
  alias text primary key,
  kind text not null unique,
  key_id text not null,
  data bytea not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists clans (
  alias text primary key,
  chat_index text not null unique,
  tag_index text not null,
  key_id text not null,
  identity bytea not null,
  active boolean not null default true,
  failures int not null default 0,
  created_at timestamptz not null default now(),
  last_seen timestamptz
);
create table if not exists clan_state (
  clan_alias text not null references clans(alias) on delete cascade,
  kind text not null,
  key_id text not null,
  data bytea not null,
  updated_at timestamptz not null default now(),
  primary key (clan_alias, kind)
);
create table if not exists war_history (
  id bigserial primary key,
  clan_alias text not null references clans(alias) on delete cascade,
  war_index text not null,
  ended_at timestamptz not null,
  key_id text not null,
  data bytea not null,
  unique (clan_alias, war_index)
);
create index if not exists war_history_clan_idx on war_history (clan_alias, ended_at desc);
create table if not exists cwl_seasons (
  id bigserial primary key,
  clan_alias text not null references clans(alias) on delete cascade,
  season_index text not null,
  ended_at timestamptz not null,
  key_id text not null,
  data bytea not null,
  unique (clan_alias, season_index)
);
create index if not exists cwl_seasons_clan_idx on cwl_seasons (clan_alias, ended_at desc);
create table if not exists links (
  alias text primary key,
  user_index text not null,
  player_index text not null unique,
  key_id text not null,
  identity bytea not null,
  created_at timestamptz not null default now()
);
create index if not exists links_user_idx on links (user_index);
alter table links add column if not exists whisper boolean not null default false;
alter table links add column if not exists verified boolean not null default true;
create table if not exists families (
  alias text primary key,
  chat_index text unique,
  key_id text not null,
  identity bytea not null,
  created_at timestamptz not null default now()
);
create table if not exists family_clans (
  family_alias text not null references families(alias) on delete cascade,
  clan_alias text not null references clans(alias) on delete cascade,
  primary key (family_alias, clan_alias)
);
create table if not exists kv (
  k text primary key,
  ref text,
  key_id text not null,
  data bytea not null,
  expires_at timestamptz,
  updated_at timestamptz not null default now()
);
create table if not exists bots (
  alias text primary key,
  owner_index text not null,
  kind text not null default 'worker',
  bot_index text not null unique,
  key_id text not null,
  identity bytea not null,
  active boolean not null default true,
  reason text,
  failures int not null default 0,
  created_at timestamptz not null default now(),
  last_seen timestamptz
);
create index if not exists bots_owner_idx on bots (owner_index);
alter table bots add column if not exists born_index text;
create index if not exists bots_born_idx on bots (born_index);
create unique index if not exists bots_born_one_idx on bots (born_index) where born_index is not null;
alter table clans add column if not exists bot_alias text references bots(alias) on delete cascade;
alter table families add column if not exists bot_alias text references bots(alias) on delete cascade;
alter table clans drop constraint if exists clans_chat_index_key;
alter table families drop constraint if exists families_chat_index_key;
create unique index if not exists clans_bot_chat_idx on clans (bot_alias, chat_index);
create unique index if not exists families_bot_chat_idx on families (bot_alias, chat_index);
create index if not exists clans_bot_idx on clans (bot_alias);
create table if not exists stat_history (
  id bigserial primary key,
  clan_alias text not null references clans(alias) on delete cascade,
  kind text not null,
  stat_index text not null,
  ended_at timestamptz not null,
  key_id text not null,
  data bytea not null,
  unique (clan_alias, kind, stat_index)
);
create index if not exists stat_history_clan_idx on stat_history (clan_alias, kind, ended_at desc);
create table if not exists member_history (
  id bigserial primary key,
  clan_alias text not null references clans(alias) on delete cascade,
  member_index text not null,
  left_at timestamptz not null,
  key_id text not null,
  data bytea not null,
  unique (clan_alias, member_index)
);
create index if not exists member_history_clan_idx on member_history (clan_alias, left_at desc);
create table if not exists network_clans (
  clan_alias text primary key references clans(alias) on delete cascade,
  visible boolean not null default false,
  named boolean not null default false,
  key_id text not null,
  data bytea not null,
  updated_at timestamptz not null default now()
);
create index if not exists network_clans_updated_idx on network_clans (updated_at desc);
create table if not exists leader_log (
  id bigserial primary key,
  clan_alias text not null references clans(alias) on delete cascade,
  at timestamptz not null default now(),
  key_id text not null,
  data bytea not null
);
create index if not exists leader_log_clan_idx on leader_log (clan_alias, at desc);
create table if not exists tournaments (
  alias text primary key,
  owner_index text not null,
  scope text not null,
  kind text not null,
  status text not null default 'signup',
  family_alias text references families(alias) on delete cascade,
  clan_alias text references clans(alias) on delete cascade,
  key_id text not null,
  data bytea not null,
  created_at timestamptz not null default now(),
  ends_at timestamptz,
  updated_at timestamptz not null default now()
);
create index if not exists tournaments_family_idx on tournaments (family_alias, status);
create index if not exists tournaments_clan_idx on tournaments (clan_alias, status);
alter table network_clans add column if not exists recruiting boolean not null default false;
alter table network_clans add column if not exists recruit_data bytea;
alter table network_clans add column if not exists verified boolean not null default false;
create index if not exists network_clans_recruiting_idx on network_clans (recruiting);
create table if not exists base_layouts (
  alias text primary key,
  clan_alias text not null references clans(alias) on delete cascade,
  label text not null,
  village text not null,
  hall int not null,
  link_index text not null,
  shared boolean not null default false,
  published boolean not null default false,
  key_id text not null,
  data bytea not null,
  created_at timestamptz not null default now()
);
create unique index if not exists base_layouts_link_idx on base_layouts (clan_alias, link_index);
create index if not exists base_layouts_clan_idx on base_layouts (clan_alias, village, hall, created_at desc);
create index if not exists base_layouts_shared_idx on base_layouts (shared, village, hall, created_at desc);
create index if not exists base_layouts_pack_idx on base_layouts (published, village, label, created_at desc);
create table if not exists web_notes (
  name text primary key,
  key_id text not null,
  data bytea not null,
  updated_at timestamptz not null default now()
);
create table if not exists web_pages (
  clan_alias text not null references clans(alias) on delete cascade,
  kind text not null,
  slug text not null,
  key_id text not null,
  data bytea not null,
  updated_at timestamptz not null default now(),
  primary key (clan_alias, kind)
);
create unique index if not exists web_pages_slug_idx on web_pages (slug, kind);
create table if not exists web_intents (
  id bigserial primary key,
  clan_alias text not null references clans(alias) on delete cascade,
  kind text not null,
  key_id text not null,
  data bytea not null,
  created_at timestamptz not null default now()
);
create index if not exists web_intents_queue_idx on web_intents (created_at);
alter table web_intents add column if not exists taken_at timestamptz;
drop table if exists web_strings;
create table if not exists base_library (
  id text primary key,
  hall int not null,
  village text not null,
  kind text not null,
  link text not null,
  builder text not null default '',
  tags text[] not null default '{}',
  name text not null default '',
  added text not null default '',
  seen_at timestamptz not null default now()
);
create index if not exists base_library_pick_idx on base_library (village, hall, kind);
create table if not exists base_videos (
  video_id text not null,
  scope text not null,
  channel_id text not null,
  title text not null default '',
  published_at text not null default '',
  links text[] not null default '{}',
  seen_at timestamptz not null default now(),
  primary key (video_id, scope)
);
create index if not exists base_videos_pick_idx on base_videos (scope, published_at desc);
create table if not exists site_days (
  day date primary key,
  requests bigint not null default 0,
  visitors bigint not null default 0,
  pages bigint not null default 0,
  blocked_waf bigint not null default 0,
  blocked_bot bigint not null default 0,
  blocked_rule bigint not null default 0,
  blocked_total bigint not null default 0,
  banned_h int not null default 0,
  banned_d int not null default 0,
  banned_forever int not null default 0,
  limited bigint not null default 0,
  probes bigint not null default 0,
  own_requests bigint not null default 0,
  probe_ok int not null default 0,
  probe_total int not null default 0,
  probe_ms_med int not null default 0,
  probe_ms_max int not null default 0,
  countries jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
alter table site_days add column if not exists misses bigint not null default 0;
create table if not exists incidents (
  id bigserial primary key,
  opened timestamptz not null default now(),
  closed timestamptz,
  kind text not null,
  key_id text not null,
  data bytea not null
);
create index if not exists incidents_open_idx on incidents (opened desc);
"""

KEEP_STATE = ("settings", "notes", "roster", "discord")
CLAN_BOUND_STATE = tuple(kind for kind in KEEP_STATE if kind != "settings")

SETTINGS_STATE = "settings"
SETTINGS_PREV = "settings_prev"

REPORTS_KEY = "reports:"
REPORTS_KEEP = WAR_HISTORY_KEEP
REPORTS_TTL = IDLE_TTL

CLAIMS_KEY = "claims:"
CLAIMS_KEEP = WAR_HISTORY_KEEP
CLAIMS_TTL = IDLE_TTL

BAN_KEY = "ban:"
PENDING_KEY = "ob:"
BAN_KEEP = WAR_HISTORY_KEEP

WEB_APP = "app"
WEB_PUBLIC = "public"

PAGE_CHANNEL = "clanboard_page"

SITE_DAY_FIELDS = ("requests", "visitors", "pages", "blocked_waf", "blocked_bot", "blocked_rule",
                   "blocked_total", "banned_h", "banned_d", "banned_forever", "limited", "probes",
                   "own_requests", "probe_ok", "probe_total", "probe_ms_med", "probe_ms_max",
                   "misses")
SITE_DAYS_KEEP = 30
INCIDENT_AAD = "incident"
INCIDENT_KINDS = ("outage", "bug", "abuse", "other")
INCIDENTS_KEEP = 20


def site_day_row(row):
    found = dict(row)
    raw = found.get("countries")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    found["countries"] = raw if isinstance(raw, dict) else {}
    return found


@dataclass
class Link:
    alias: str
    user_id: int
    tag: str
    name: str
    dm: bool
    lang: str | None = None
    whisper: bool = False
    verified: bool = True


@dataclass
class Family:
    alias: str
    name: str
    owner_id: int
    chat_id: int | None
    bot_alias: str | None = None


@dataclass
class Clan:
    alias: str
    chat_id: int
    tag: str
    name: str
    active: bool
    failures: int
    last_seen: datetime | None
    bot_alias: str | None = None
    linked_by: int | None = None


@dataclass
class Bot:
    alias: str
    owner_id: int
    username: str
    bot_id: int
    kind: str = "worker"
    active: bool = True
    reason: str | None = None
    failures: int = 0
    created_at: datetime | None = None
    last_seen: datetime | None = None


class Store:
    def __init__(self, vault, host="db", database=DATABASE, user="postgres"):
        self.vault = vault
        self.dsn = {"host": host, "database": database, "user": user}
        self.pool = None

    async def open(self, schema=True):
        self.pool = await asyncpg.create_pool(**self.dsn, min_size=1, max_size=5)
        if not schema:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def listen(self, channel, callback, connect=None):
        conn = await (connect or asyncpg.connect)(**self.dsn)

        def heard(_conn, _pid, _channel, payload):
            callback(payload)

        await conn.add_listener(channel, heard)
        return conn

    async def get_secret(self, kind):
        row = await self.pool.fetchrow("select alias, data from secrets where kind=$1", kind)
        if not row:
            return None
        return self.vault.decrypt(row["data"], f"secret:{row['alias']}").decode()

    async def set_secret(self, kind, value):
        row = await self.pool.fetchrow("select alias from secrets where kind=$1", kind)
        alias = row["alias"] if row else self.vault.alias("sec")
        data = self.vault.encrypt(value, f"secret:{alias}")
        await self.pool.execute(
            """insert into secrets(alias, kind, key_id, data) values($1,$2,$3,$4)
               on conflict (kind) do update
               set data=excluded.data, key_id=excluded.key_id, updated_at=now()""",
            alias, kind, self.vault.key_id, data,
        )
        return alias

    async def delete_secret(self, kind):
        return deleted_rows(await self.pool.execute("delete from secrets where kind=$1", kind)) > 0

    async def list_secrets(self):
        return await self.pool.fetch("select alias, kind, key_id, updated_at from secrets order by kind")

    def _bot(self, row):
        ident = self.vault.decrypt_json(row["identity"], f"bot:{row['alias']}")
        return Bot(
            alias=row["alias"],
            owner_id=int(ident["owner_id"]),
            username=ident.get("username") or "?",
            bot_id=int(ident["bot_id"]),
            kind=row["kind"],
            active=row["active"],
            reason=row["reason"],
            failures=row["failures"],
            created_at=row["created_at"],
            last_seen=row["last_seen"],
        )

    def _bots(self, rows):
        bots = []
        for row in rows:
            try:
                bots.append(self._bot(row))
            except Exception:
                log.exception("%s: identità illeggibile", row["alias"])
        return bots

    def _born_tag(self, row):
        if not row:
            return None
        try:
            ident = self.vault.decrypt_json(row["identity"], f"bot:{row['alias']}")
        except Exception:
            log.warning("%s: identità illeggibile", row["alias"])
            return None
        return normalize_tag(ident.get("clan_tag"))

    async def _born_holder(self, born_index, bot_index):
        return await self.pool.fetchval(
            "select alias from bots where born_index=$1 and bot_index<>$2 limit 1", born_index, bot_index
        )

    async def add_bot(self, owner_id, token, username, bot_id, kind="worker", allow_disabled=False, trusted=False,
                      clan_tag=None, replaces=None):
        bot_index = self.vault.blind("bot", bot_id)
        owner_index = self.vault.blind("user", owner_id)
        existing = await self.pool.fetchrow(
            "select alias, owner_index, reason, identity from bots where bot_index=$1", bot_index
        )
        if existing and not trusted and existing["owner_index"] != owner_index:
            raise ValueError("owned_by_other")
        if existing and existing["reason"] == "disabled" and not allow_disabled:
            raise ValueError("disabled")
        alias = existing["alias"] if existing else self.vault.alias("bot")
        ident = {"token": token, "owner_id": owner_id, "username": username, "bot_id": bot_id}
        born = normalize_tag(clan_tag) or self._born_tag(existing)
        born_index = self.vault.blind("tag", born) if born else None
        holder = await self._born_holder(born_index, bot_index) if born else None
        if holder and holder != replaces:
            born = born_index = holder = None
        if born:
            ident["clan_tag"] = born
        identity = self.vault.encrypt_json(ident, f"bot:{alias}")
        async with self.pool.acquire() as conn, conn.transaction():
            if holder:
                await self.drop_born(holder, conn)
            await conn.execute(
                """insert into bots(alias, owner_index, kind, bot_index, key_id, identity, born_index)
                   values($1,$2,$3,$4,$5,$6,$7)
                   on conflict (bot_index) do update
                   set owner_index=excluded.owner_index, kind=excluded.kind, key_id=excluded.key_id,
                       identity=excluded.identity, born_index=excluded.born_index,
                       active=true, reason=null, failures=0""",
                alias, owner_index, kind, bot_index, self.vault.key_id, identity, born_index,
            )
        return await self.bot_by_alias(alias)

    async def drop_born(self, alias, conn=None):
        conn = conn or self.pool
        row = await conn.fetchrow("select alias, identity from bots where alias=$1", alias)
        if not row:
            return
        identity = self.vault.decrypt_json(row["identity"], f"bot:{alias}")
        identity.pop("clan_tag", None)
        await conn.execute(
            "update bots set born_index=null, key_id=$2, identity=$3 where alias=$1",
            alias, self.vault.key_id, self.vault.encrypt_json(identity, f"bot:{alias}"),
        )

    async def bot_token(self, alias):
        row = await self.pool.fetchrow("select alias, identity from bots where alias=$1", alias)
        if not row:
            return None
        return self.vault.decrypt_json(row["identity"], f"bot:{row['alias']}").get("token")

    async def bot_by_alias(self, alias):
        row = await self.pool.fetchrow("select * from bots where alias=$1", alias)
        return self._bot(row) if row else None

    async def bots(self, active_only=False):
        where = " where active" if active_only else ""
        return self._bots(await self.pool.fetch(f"select * from bots{where} order by created_at"))

    async def bots_by_owner(self, owner_id):
        rows = await self.pool.fetch(
            "select * from bots where owner_index=$1 order by created_at", self.vault.blind("user", owner_id)
        )
        return self._bots(rows)

    async def set_bot_active(self, alias, active, reason=None):
        row = await self.pool.fetchrow(
            """update bots set active=$2, reason=$3, failures=case when $2 then 0 else failures end
               where alias=$1 returning *""",
            alias, active, reason,
        )
        return self._bot(row) if row else None

    async def bump_bot_failure(self, alias, limit=5):
        row = await self.pool.fetchrow(
            """update bots set failures=failures+1, active=(active and failures+1 < $2),
               reason=case when failures+1 < $2 then reason else 'too_many_failures' end
               where alias=$1 returning *""",
            alias, limit,
        )
        return self._bot(row) if row else None

    async def set_bot_owner(self, alias, owner_id):
        row = await self.pool.fetchrow("select alias, identity from bots where alias=$1", alias)
        if not row:
            return None
        identity = self.vault.decrypt_json(row["identity"], f"bot:{alias}")
        if int(identity.get("owner_id") or 0) == int(owner_id):
            return await self.bot_by_alias(alias)
        identity["owner_id"] = int(owner_id)
        await self.pool.execute(
            "update bots set owner_index=$2, key_id=$3, identity=$4 where alias=$1",
            alias, self.vault.blind("user", owner_id), self.vault.key_id,
            self.vault.encrypt_json(identity, f"bot:{alias}"),
        )
        return await self.bot_by_alias(alias)

    async def touch_bot(self, alias):
        await self.pool.execute("update bots set last_seen=now(), failures=0 where alias=$1", alias)

    async def remove_bot(self, alias):
        result = await self.pool.execute("delete from bots where alias=$1", alias)
        return result.endswith("1")

    async def count_clans(self, bot_alias):
        return await self.pool.fetchval("select count(*) from clans where bot_alias=$1", bot_alias) or 0

    async def count_links(self):
        return await self.pool.fetchval("select count(*) from links") or 0

    async def bot_for_tag(self, tag):
        tag = normalize_tag(tag)
        if not tag:
            return None
        alias = await self.pool.fetchval(
            """select bot_alias from clans where tag_index=$1 and bot_alias is not null
               order by created_at limit 1""",
            self.vault.blind("tag", tag),
        )
        return alias or await self._idle_bot(tag) or await self._pending_bot(tag)

    async def _pending_bot(self, tag):
        row = await self.pool.fetchrow(
            f"""select k, data from kv where k like '{PENDING_KEY}%' and ref=$1
                and (expires_at is null or expires_at > now()) order by updated_at limit 1""",
            self.vault.blind("tag", tag),
        )
        if not row:
            return None
        try:
            return self.vault.decrypt_json(row["data"], f"kv:{row['k']}").get("bot_alias")
        except Exception:
            log.warning("creazione in sospeso illeggibile, la salto")
            return None

    def _pending_ref(self, key, obj):
        if not key.startswith(PENDING_KEY) or not isinstance(obj, dict) or not obj.get("bot_alias"):
            return None
        tag = normalize_tag(obj.get("tag"))
        return self.vault.blind("tag", tag) if tag else None

    async def _idle_bot(self, tag):
        return await self.pool.fetchval(
            """select alias from bots b where born_index=$1
               and not exists (select 1 from clans c where c.bot_alias = b.alias)
               order by created_at limit 1""",
            self.vault.blind("tag", tag),
        )

    async def pending_migration(self):
        return await self.pool.fetchrow(
            """select (select count(*) from clans where bot_alias is null) as clans,
                      (select count(*) from families where bot_alias is null) as families"""
        )

    async def migrate_multibot(self, token, owner_id, username, bot_id):
        bot = await self.add_bot(owner_id, token, username, bot_id, kind="worker", allow_disabled=True)
        clans = await self.pool.execute("update clans set bot_alias=$1 where bot_alias is null", bot.alias)
        families = await self.pool.execute("update families set bot_alias=$1 where bot_alias is null", bot.alias)
        bot.migrated_clans = int(clans.split()[-1])
        bot.migrated_families = int(families.split()[-1])
        return bot

    def _clan(self, row):
        ident = self.vault.decrypt_json(row["identity"], f"clan:{row['alias']}")
        return Clan(
            alias=row["alias"],
            chat_id=int(ident["chat_id"]),
            tag=ident["tag"],
            name=ident.get("name") or "?",
            active=row["active"],
            failures=row["failures"],
            last_seen=row["last_seen"],
            bot_alias=row["bot_alias"],
            linked_by=ident.get("added_by"),
        )

    async def clan_by_alias(self, alias):
        row = await self.pool.fetchrow("select * from clans where alias=$1", alias)
        return self._clan(row) if row else None

    async def clan_by_chat(self, chat_id, bot_alias=None):
        chat_index = self.vault.blind("chat", chat_id)
        if bot_alias is None:
            row = await self.pool.fetchrow("select * from clans where chat_index=$1", chat_index)
        else:
            row = await self.pool.fetchrow(
                "select * from clans where chat_index=$1 and bot_alias=$2", chat_index, bot_alias
            )
        return self._clan(row) if row else None

    async def add_clan(self, chat_id, tag, name, added_by=None, bot_alias=None):
        chat_index = self.vault.blind("chat", chat_id)
        tag_index = self.vault.blind("tag", tag)
        if bot_alias is None:
            existing = await self.pool.fetchrow(
                "select alias, tag_index from clans where chat_index=$1", chat_index
            )
        else:
            existing = await self.pool.fetchrow(
                "select alias, tag_index from clans where chat_index=$1 and bot_alias=$2",
                chat_index, bot_alias,
            )
        alias = existing["alias"] if existing else self.vault.alias("clan")
        identity = self.vault.encrypt_json(
            {"chat_id": chat_id, "tag": tag, "name": name, "added_by": added_by}, f"clan:{alias}"
        )
        async with self.pool.acquire() as conn, conn.transaction():
            if existing:
                await conn.execute(
                    """update clans set tag_index=$2, key_id=$3, identity=$4, active=true,
                       failures=0, bot_alias=coalesce($5, bot_alias) where alias=$1""",
                    alias, tag_index, self.vault.key_id, identity, bot_alias,
                )
            else:
                await conn.execute(
                    """insert into clans(alias, chat_index, tag_index, key_id, identity, bot_alias)
                       values($1,$2,$3,$4,$5,$6)
                       on conflict (bot_alias, chat_index) do update
                       set tag_index=excluded.tag_index, key_id=excluded.key_id,
                           identity=excluded.identity, active=true, failures=0""",
                    alias, chat_index, tag_index, self.vault.key_id, identity, bot_alias,
                )
            await conn.execute(
                "delete from clan_state where clan_alias=$1 and not (kind = any($2::text[]))",
                alias, list(KEEP_STATE),
            )
            if existing and existing["tag_index"] != tag_index:
                await conn.execute("delete from war_history where clan_alias=$1", alias)
                await conn.execute("delete from cwl_seasons where clan_alias=$1", alias)
                await conn.execute("delete from stat_history where clan_alias=$1", alias)
                await conn.execute("delete from member_history where clan_alias=$1", alias)
                await conn.execute(
                    "delete from clan_state where clan_alias=$1 and kind = any($2::text[])",
                    alias, list(CLAN_BOUND_STATE))
                await conn.execute("delete from leader_log where clan_alias=$1", alias)
        return await self.clan_by_chat(chat_id, bot_alias)

    async def rename_clan(self, clan, name):
        if name == clan.name:
            return
        identity = self.vault.encrypt_json(
            {"chat_id": clan.chat_id, "tag": clan.tag, "name": name, "added_by": clan.linked_by},
            f"clan:{clan.alias}",
        )
        await self.pool.execute("update clans set identity=$2 where alias=$1", clan.alias, identity)
        clan.name = name

    async def move_clan(self, old_chat_id, new_chat_id, bot_alias=None):
        clan = await self.clan_by_chat(old_chat_id, bot_alias)
        if not clan:
            return False
        identity = self.vault.encrypt_json(
            {"chat_id": new_chat_id, "tag": clan.tag, "name": clan.name, "added_by": clan.linked_by},
            f"clan:{clan.alias}",
        )
        await self.pool.execute(
            "update clans set chat_index=$2, identity=$3 where alias=$1",
            clan.alias, self.vault.blind("chat", new_chat_id), identity,
        )
        return True

    async def remove_clan(self, chat_id, bot_alias=None):
        chat_index = self.vault.blind("chat", chat_id)
        if bot_alias is None:
            result = await self.pool.execute("delete from clans where chat_index=$1", chat_index)
        else:
            result = await self.pool.execute(
                "delete from clans where chat_index=$1 and bot_alias=$2", chat_index, bot_alias
            )
        return result.endswith("1")

    async def active_clans(self, bot_alias=None):
        if bot_alias is None:
            rows = await self.pool.fetch("select * from clans where active order by created_at")
        else:
            rows = await self.pool.fetch(
                "select * from clans where active and bot_alias=$1 order by created_at", bot_alias
            )
        clans = []
        for row in rows:
            try:
                clans.append(self._clan(row))
            except Exception:
                log.exception("%s: identità illeggibile", row["alias"])
        return clans

    async def mark_ok(self, alias):
        await self.pool.execute(
            "update clans set failures=0, last_seen=now() where alias=$1", alias
        )

    async def mark_failure(self, alias, limit=3):
        return await self.pool.fetchrow(
            """update clans set failures=failures+1, active=(failures+1 < $2)
               where alias=$1 returning failures, active""",
            alias, limit,
        )

    async def counts(self):
        return await self.pool.fetchrow(
            "select count(*) filter (where active) as active, count(*) as total from clans"
        )

    async def get_state(self, alias, kind):
        row = await self.pool.fetchrow(
            "select data from clan_state where clan_alias=$1 and kind=$2", alias, kind
        )
        if not row:
            return None
        return self.vault.decrypt_json(row["data"], f"state:{alias}:{kind}")

    async def set_state(self, alias, kind, obj):
        data = self.vault.encrypt_json(obj, f"state:{alias}:{kind}")
        await self.pool.execute(
            """insert into clan_state(clan_alias, kind, key_id, data) values($1,$2,$3,$4)
               on conflict (clan_alias, kind) do update
               set data=excluded.data, key_id=excluded.key_id, updated_at=now()""",
            alias, kind, self.vault.key_id, data,
        )

    async def del_state(self, alias, kind):
        await self.pool.execute(
            "delete from clan_state where clan_alias=$1 and kind=$2", alias, kind
        )

    async def add_war(self, alias, war_key, ended_at, obj):
        war_index = self.vault.blind("war", f"{alias}:{war_key}")
        data = self.vault.encrypt_json(obj, f"war:{alias}:{war_index}")
        async with self.pool.acquire() as conn, conn.transaction():
            war_id = await conn.fetchval(
                """insert into war_history(clan_alias, war_index, ended_at, key_id, data)
                   values($1,$2,$3,$4,$5) on conflict do nothing returning id""",
                alias, war_index, ended_at, self.vault.key_id, data,
            )
            if war_id is None:
                return False
            pruned = await conn.fetch(PRUNE_CLAN_WARS_SQL, alias, WAR_HISTORY_KEEP)
        return all(row["id"] != war_id for row in pruned)

    async def recent_wars(self, alias, limit=10):
        rows = await self.pool.fetch(
            """select war_index, data from war_history where clan_alias=$1
               order by ended_at desc limit $2""",
            alias, limit,
        )
        return [
            self.vault.decrypt_json(r["data"], f"war:{alias}:{r['war_index']}") for r in rows
        ]

    async def wars_since(self, alias, since):
        rows = await self.pool.fetch(
            """select war_index, data from war_history where clan_alias=$1 and ended_at >= $2
               order by ended_at desc""",
            alias, since,
        )
        return [
            self.vault.decrypt_json(r["data"], f"war:{alias}:{r['war_index']}") for r in rows
        ]

    def _base_row(self, row):
        data = self.vault.decrypt_json(row["data"], f"base:{row['alias']}")
        return {
            "alias": row["alias"], "clan_alias": row["clan_alias"], "label": row["label"],
            "village": row["village"], "hall": row["hall"], "shared": row["shared"],
            "published": row["published"], "created_at": row["created_at"], **data,
        }

    def _base_rows(self, rows):
        out = []
        for row in rows:
            try:
                out.append(self._base_row(row))
            except Exception:
                log.exception("%s: base illeggibile", row["alias"])
        return out

    async def add_base(self, clan_alias, layout, label, payload, keep=BASE_KEEP):
        alias = self.vault.alias("base")
        link_index = self.vault.blind("base", layout["id"])
        data = self.vault.encrypt_json(dict(payload, id=layout["id"]), f"base:{alias}")
        async with self.pool.acquire() as conn, conn.transaction():
            saved = await conn.fetchval(
                """insert into base_layouts(alias, clan_alias, label, village, hall, link_index,
                                            key_id, data)
                   values($1,$2,$3,$4,$5,$6,$7,$8)
                   on conflict (clan_alias, link_index) do nothing returning alias""",
                alias, clan_alias, label, layout["village"], layout["hall"], link_index,
                self.vault.key_id, data,
            )
            if saved is None:
                return None
            await conn.execute(PRUNE_CLAN_BASES_SQL, clan_alias, keep)
        return saved

    async def base_by_alias(self, alias):
        row = await self.pool.fetchrow(
            """select alias, clan_alias, label, village, hall, shared, published, data, created_at
               from base_layouts where alias=$1""", alias)
        return self._base_row(row) if row else None

    async def clan_bases(self, clan_alias, village=None, hall=None, limit=10):
        rows = await self.pool.fetch(
            """select alias, clan_alias, label, village, hall, shared, published, data, created_at
               from base_layouts
               where clan_alias=$1 and ($2::text is null or village=$2)
                 and ($3::int is null or hall=$3)
               order by created_at desc limit $4""",
            clan_alias, village, hall, limit)
        return self._base_rows(rows)

    async def shared_bases(self, village=None, hall=None, limit=10):
        rows = await self.pool.fetch(
            """select alias, clan_alias, label, village, hall, shared, published, data, created_at
               from base_layouts
               where shared and ($1::text is null or village=$1)
                 and ($2::int is null or hall=$2)
               order by created_at desc limit $3""",
            village, hall, limit)
        return self._base_rows(rows)

    async def set_base_flags(self, alias, shared=None, published=None):
        status = await self.pool.execute(
            """update base_layouts set shared = coalesce($2, shared),
                                       published = coalesce($3, published)
               where alias=$1""", alias, shared, published)
        return deleted_rows(status) > 0

    async def remove_base(self, alias):
        return deleted_rows(await self.pool.execute(
            "delete from base_layouts where alias=$1", alias)) > 0

    async def published_bases(self, clan_alias, village, label, limit=10):
        rows = await self.pool.fetch(
            """select alias, clan_alias, label, village, hall, shared, published, data, created_at
               from base_layouts
               where published and clan_alias=$1 and village=$2 and label=$3
               order by created_at desc limit $4""",
            clan_alias, village, label, limit)
        return self._base_rows(rows)

    async def base_packs(self, limit=10):
        rows = await self.pool.fetch(
            """select clan_alias, village, label, count(*) as n, max(created_at) as last
               from base_layouts where published
               group by clan_alias, village, label
               order by last desc limit $1""", limit)
        return [{"clan_alias": row["clan_alias"], "village": row["village"],
                 "label": row["label"], "n": int(row["n"])} for row in rows]

    async def copy_bases(self, source_alias, target_alias, village, label, keep=BASE_KEEP):
        copied = 0
        for row in await self.published_bases(source_alias, village, label, keep):
            layout = {"village": row["village"], "hall": row["hall"], "id": row["id"]}
            payload = {"name": row.get("name"), "from": source_alias}
            if await self.add_base(target_alias, layout, row["label"], payload, keep):
                copied += 1
        return copied

    async def library_put(self, rows):
        if not rows:
            return 0
        ids = [row["id"] for row in rows]
        values = [(row["id"], int(row["hall"]), row["village"], row["kind"], row["link"],
                   row.get("builder") or "", list(row.get("tags") or ()), row.get("name") or "",
                   row.get("added") or "") for row in rows]
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                """insert into base_library(id, hall, village, kind, link, builder, tags,
                                            name, added, seen_at)
                   values($1,$2,$3,$4,$5,$6,$7,$8,$9,now())
                   on conflict (id) do update
                   set hall=excluded.hall, village=excluded.village, kind=excluded.kind,
                       link=excluded.link, builder=excluded.builder, tags=excluded.tags,
                       name=excluded.name, added=excluded.added, seen_at=now()""", values)
            await conn.execute(
                "delete from base_library where not (id = any($1::text[]))", ids)
        return len(ids)

    async def library_rows(self, hall=None, village=None, kind=None, limit=WAR_HISTORY_KEEP):
        rows = await self.pool.fetch(
            """select id, hall, village, kind, link, builder, tags, name, added
               from base_library
               where ($1::int is null or hall=$1) and ($2::text is null or village=$2)
                 and ($3::text is null or kind=$3)
               order by added desc, id limit $4""",
            hall, village, kind, limit)
        return [{"id": row["id"], "name": row["name"], "hall": int(row["hall"]),
                 "village": row["village"], "kind": row["kind"], "link": row["link"],
                 "builder": row["builder"], "tags": list(row["tags"] or ()),
                 "added": row["added"]} for row in rows]

    async def videos_put(self, rows, keep=WAR_HISTORY_KEEP):
        if not rows:
            return 0
        values = [(row["id"], row["scope"], row["channel"], row.get("title") or "",
                   row.get("published") or "", list(row.get("links") or ())) for row in rows]
        feeds = sorted({(row["channel"], row["scope"]) for row in rows})
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.executemany(
                """insert into base_videos(video_id, scope, channel_id, title, published_at,
                                           links, seen_at)
                   values($1,$2,$3,$4,$5,$6,now())
                   on conflict (video_id, scope) do update
                   set channel_id=excluded.channel_id, title=excluded.title,
                       published_at=excluded.published_at, links=excluded.links,
                       seen_at=now()""", values)
            for channel, scope in feeds:
                await conn.execute(
                    """delete from base_videos where channel_id=$1 and scope=$2
                       and video_id in (select video_id from base_videos
                                        where channel_id=$1 and scope=$2
                                        order by published_at desc, video_id desc offset $3)""",
                    channel, scope, keep)
        return len(values)

    async def videos_rows(self, scope=None, limit=WAR_HISTORY_KEEP):
        rows = await self.pool.fetch(
            """select video_id, channel_id, title, published_at, links
               from base_videos where ($1::text is null or scope=$1)
               order by published_at desc, video_id limit $2""",
            scope, limit)
        return [{"id": row["video_id"], "channel": row["channel_id"], "title": row["title"],
                 "published": row["published_at"], "links": list(row["links"] or ())}
                for row in rows]

    async def archive_member(self, alias, tag, obj, left_at):
        member_index = self.vault.blind("player", tag)
        data = self.vault.encrypt_json(obj, f"member:{alias}:{member_index}")
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """insert into member_history(clan_alias, member_index, left_at, key_id, data)
                   values($1,$2,$3,$4,$5)
                   on conflict (clan_alias, member_index) do update
                   set left_at=excluded.left_at, key_id=excluded.key_id, data=excluded.data""",
                alias, member_index, left_at, self.vault.key_id, data,
            )
            await conn.execute(PRUNE_CLAN_MEMBERS_SQL, alias, MEMBER_HISTORY_KEEP)

    async def former_member(self, alias, tag):
        member_index = self.vault.blind("player", tag)
        row = await self.pool.fetchrow(
            "select data from member_history where clan_alias=$1 and member_index=$2", alias, member_index
        )
        if not row:
            return None
        return self.vault.decrypt_json(row["data"], f"member:{alias}:{member_index}")

    async def drop_former(self, alias, tag):
        member_index = self.vault.blind("player", tag)
        result = await self.pool.execute(
            "delete from member_history where clan_alias=$1 and member_index=$2", alias, member_index
        )
        return result.endswith("1")

    async def former_members(self, alias, limit=FORMER_SHOWN):
        rows = await self.pool.fetch(
            """select member_index, data from member_history where clan_alias=$1
               order by left_at desc limit $2""",
            alias, limit,
        )
        return [
            self.vault.decrypt_json(r["data"], f"member:{alias}:{r['member_index']}") for r in rows
        ]

    async def add_log(self, alias, entry, at=None):
        data = self.vault.encrypt_json(entry, f"log:{alias}")
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """insert into leader_log(clan_alias, at, key_id, data)
                   values($1, coalesce($2, now()), $3, $4)""",
                alias, at, self.vault.key_id, data,
            )
            await conn.execute(PRUNE_CLAN_LOG_SQL, alias, LEADER_LOG_KEEP)

    async def recent_log(self, alias, limit=20):
        rows = await self.pool.fetch(
            """select at, data from leader_log where clan_alias=$1
               order by at desc, id desc limit $2""",
            alias, limit,
        )
        return [
            {**self.vault.decrypt_json(r["data"], f"log:{alias}"), "at": r["at"]} for r in rows
        ]

    async def add_stat(self, alias, kind, stat_key, ended_at, obj):
        stat_index = self.vault.blind("stat", f"{alias}:{kind}:{stat_key}")
        data = self.vault.encrypt_json(obj, f"stat:{alias}:{stat_index}")
        async with self.pool.acquire() as conn, conn.transaction():
            stat_id = await conn.fetchval(
                """insert into stat_history(clan_alias, kind, stat_index, ended_at, key_id, data)
                   values($1,$2,$3,$4,$5,$6) on conflict do nothing returning id""",
                alias, kind, stat_index, ended_at, self.vault.key_id, data,
            )
            if stat_id is None:
                return False
            pruned = await conn.fetch(PRUNE_CLAN_STATS_SQL, alias, kind, STAT_HISTORY_KEEP)
        return all(row["id"] != stat_id for row in pruned)

    async def recent_stats(self, alias, kind, limit=10):
        rows = await self.pool.fetch(
            """select stat_index, data from stat_history where clan_alias=$1 and kind=$2
               order by ended_at desc limit $3""",
            alias, kind, limit,
        )
        return [
            self.vault.decrypt_json(r["data"], f"stat:{alias}:{r['stat_index']}") for r in rows
        ]

    def _link(self, row):
        ident = self.vault.decrypt_json(row["identity"], f"link:{row['alias']}")
        return Link(row["alias"], int(ident["user_id"]), ident["tag"], ident.get("name") or "?",
                    bool(ident.get("dm")), ident.get("lang"), bool(row["whisper"]),
                    bool(row["verified"]))

    async def link_player(self, user_id, tag, name, dm=False, lang=None):
        player_index = self.vault.blind("player", tag)
        existing = await self.pool.fetchrow("select alias, identity from links where player_index=$1", player_index)
        alias = existing["alias"] if existing else self.vault.alias("link")
        if lang is None and existing:
            previous = self.vault.decrypt_json(existing["identity"], f"link:{alias}")
            if int(previous["user_id"]) == int(user_id):
                lang = previous.get("lang")
        identity = self.vault.encrypt_json(
            {"user_id": user_id, "tag": tag, "name": name, "dm": dm, "lang": lang}, f"link:{alias}"
        )
        await self.pool.execute(
            """insert into links(alias, user_index, player_index, key_id, identity) values($1,$2,$3,$4,$5)
               on conflict (player_index) do update
               set user_index=excluded.user_index, key_id=excluded.key_id,
                   identity=excluded.identity, verified=true""",
            alias, self.vault.blind("user", user_id), player_index, self.vault.key_id, identity,
        )
        return alias

    async def add_claim(self, user_id, tag, name):
        player_index = self.vault.blind("player", tag)
        if await self.pool.fetchrow("select alias from links where player_index=$1", player_index):
            return None
        alias = self.vault.alias("link")
        identity = self.vault.encrypt_json(
            {"user_id": user_id, "tag": tag, "name": name, "dm": False, "lang": None},
            f"link:{alias}",
        )
        result = await self.pool.execute(
            """insert into links(alias, user_index, player_index, key_id, identity, verified)
               values($1,$2,$3,$4,$5,false) on conflict (player_index) do nothing""",
            alias, self.vault.blind("user", user_id), player_index, self.vault.key_id, identity,
        )
        return alias if result.endswith("1") else None

    async def set_link_verified(self, user_id, tag, value):
        await self.pool.execute(
            "update links set verified=$3 where user_index=$1 and player_index=$2",
            self.vault.blind("user", user_id), self.vault.blind("player", tag), bool(value),
        )

    async def claim_add(self, clan_alias, user_id, tag, name, now):
        key = f"{CLAIMS_KEY}{clan_alias}"
        stored = await self.kv_get(key) or {}
        rows = [row for row in (stored.get("rows") or [])
                if not (row["tag"] == tag and int(row["by"]) == int(user_id))]
        rows = (rows + [{"at": now.timestamp(), "by": int(user_id), "tag": tag,
                         "name": name}])[-CLAIMS_KEEP:]
        await self.kv_set(key, {"rows": rows}, ref=clan_alias, ttl=CLAIMS_TTL)
        return len(rows)

    async def claims_pending(self, clan_alias):
        stored = await self.kv_get(f"{CLAIMS_KEY}{clan_alias}") or {}
        return list(stored.get("rows") or [])

    async def claim_drop(self, clan_alias, user_id, tag):
        key = f"{CLAIMS_KEY}{clan_alias}"
        stored = await self.kv_get(key) or {}
        before = stored.get("rows") or []
        rows = [row for row in before
                if not (row["tag"] == tag and int(row["by"]) == int(user_id))]
        if len(rows) == len(before):
            return False
        await self.kv_set(key, {"rows": rows}, ref=clan_alias, ttl=CLAIMS_TTL)
        return True

    async def update_link(self, link):
        identity = self.vault.encrypt_json(
            {"user_id": link.user_id, "tag": link.tag, "name": link.name, "dm": link.dm, "lang": link.lang},
            f"link:{link.alias}",
        )
        await self.pool.execute("update links set identity=$2 where alias=$1", link.alias, identity)

    async def set_link_lang(self, user_id, lang):
        for link in await self.links_by_user(user_id):
            if link.lang != lang:
                link.lang = lang
                await self.update_link(link)

    async def set_link_whisper(self, user_id, tag, value):
        await self.pool.execute(
            "update links set whisper=$3 where user_index=$1 and player_index=$2",
            self.vault.blind("user", user_id), self.vault.blind("player", tag), bool(value),
        )

    async def links_by_user(self, user_id):
        rows = await self.pool.fetch(
            "select * from links where user_index=$1 order by created_at", self.vault.blind("user", user_id)
        )
        return [self._link(r) for r in rows]

    async def links_for_players(self, tags):
        if not tags:
            return {}
        indexes = {self.vault.blind("player", t): t for t in tags}
        rows = await self.pool.fetch("select * from links where player_index = any($1::text[])", list(indexes))
        return {indexes[r["player_index"]]: self._link(r) for r in rows}

    async def unlink(self, user_id, tag):
        result = await self.pool.execute(
            "delete from links where user_index=$1 and player_index=$2",
            self.vault.blind("user", user_id), self.vault.blind("player", tag),
        )
        return result.endswith("1")

    def _family(self, row):
        ident = self.vault.decrypt_json(row["identity"], f"family:{row['alias']}")
        chat = ident.get("chat_id")
        return Family(
            row["alias"], ident.get("name") or "?", int(ident["owner_id"]),
            int(chat) if chat else None, row["bot_alias"],
        )

    async def create_family(self, name, owner_id, bot_alias=None):
        alias = self.vault.alias("fam")
        identity = self.vault.encrypt_json({"name": name, "owner_id": owner_id, "chat_id": None}, f"family:{alias}")
        await self.pool.execute(
            "insert into families(alias, key_id, identity, bot_alias) values($1,$2,$3,$4)",
            alias, self.vault.key_id, identity, bot_alias,
        )
        return alias

    async def save_family(self, family):
        identity = self.vault.encrypt_json(
            {"name": family.name, "owner_id": family.owner_id, "chat_id": family.chat_id}, f"family:{family.alias}"
        )
        chat_index = self.vault.blind("chat", family.chat_id) if family.chat_id else None
        await self.pool.execute(
            "update families set identity=$2, chat_index=$3 where alias=$1", family.alias, identity, chat_index
        )

    async def family_by_alias(self, alias):
        row = await self.pool.fetchrow("select * from families where alias=$1", alias)
        return self._family(row) if row else None

    async def family_by_chat(self, chat_id, bot_alias=None):
        chat_index = self.vault.blind("chat", chat_id)
        if bot_alias is None:
            row = await self.pool.fetchrow("select * from families where chat_index=$1", chat_index)
        else:
            row = await self.pool.fetchrow(
                "select * from families where chat_index=$1 and bot_alias=$2", chat_index, bot_alias
            )
        return self._family(row) if row else None

    async def family_of_clan(self, clan_alias):
        row = await self.pool.fetchrow(
            "select f.* from families f join family_clans fc on fc.family_alias=f.alias where fc.clan_alias=$1",
            clan_alias,
        )
        return self._family(row) if row else None

    async def families(self, bot_alias=None):
        if bot_alias is None:
            rows = await self.pool.fetch("select * from families order by created_at")
        else:
            rows = await self.pool.fetch(
                "select * from families where bot_alias=$1 order by created_at", bot_alias
            )
        return [self._family(r) for r in rows]

    async def add_family_clan(self, family_alias, clan_alias):
        await self.pool.execute("delete from family_clans where clan_alias=$1", clan_alias)
        await self.pool.execute(
            "insert into family_clans(family_alias, clan_alias) values($1,$2) on conflict do nothing",
            family_alias, clan_alias,
        )

    async def remove_family_clan(self, clan_alias):
        result = await self.pool.execute("delete from family_clans where clan_alias=$1", clan_alias)
        return result.endswith("1")

    async def family_clans(self, family_alias):
        rows = await self.pool.fetch(
            """select c.* from clans c join family_clans fc on fc.clan_alias=c.alias
               where fc.family_alias=$1 and c.active order by c.created_at""",
            family_alias,
        )
        return [self._clan(r) for r in rows]

    async def delete_family(self, alias):
        result = await self.pool.execute("delete from families where alias=$1", alias)
        return result.endswith("1")

    async def kv_set(self, key, obj, ref=None, ttl=None):
        ref = ref or self._pending_ref(key, obj)
        data = self.vault.encrypt_json(obj, f"kv:{key}")
        expires = f"now() + interval '{int(ttl)} seconds'" if ttl else "null"
        await self.pool.execute(
            f"""insert into kv(k, ref, key_id, data, expires_at) values($1,$2,$3,$4,{expires})
                on conflict (k) do update set ref=excluded.ref, key_id=excluded.key_id,
                data=excluded.data, expires_at=excluded.expires_at, updated_at=now()""",
            key, ref, self.vault.key_id, data,
        )

    async def kv_get(self, key):
        row = await self.pool.fetchrow(
            "select data from kv where k=$1 and (expires_at is null or expires_at > now())", key
        )
        return self.vault.decrypt_json(row["data"], f"kv:{key}") if row else None

    async def kv_ref(self, key):
        return await self.pool.fetchval(
            "select ref from kv where k=$1 and (expires_at is null or expires_at > now())", key
        )

    async def kv_del(self, key):
        await self.pool.execute("delete from kv where k=$1", key)

    async def kv_purge(self):
        await self.pool.execute("delete from kv where expires_at is not null and expires_at <= now()")

    async def banned(self, limit=BAN_KEEP):
        rows = await self.pool.fetch(
            f"""select k, data from kv where k like '{BAN_KEY}%'
                and (expires_at is null or expires_at > now())
                order by updated_at desc limit $1""",
            int(limit),
        )
        found = []
        for row in rows:
            try:
                stored = self.vault.decrypt_json(row["data"], f"kv:{row['k']}")
            except Exception:
                log.warning("un bando non si legge, lo salto")
                continue
            found.append({"ip": row["k"][len(BAN_KEY):], "at": stored.get("at"),
                          "until": stored.get("until"), "strikes": stored.get("strikes")})
        return found

    async def web_note_set(self, name, payload):
        data = self.vault.encrypt_json(payload, f"web:{name}")
        await self.pool.execute(
            """insert into web_notes(name, key_id, data) values($1,$2,$3)
               on conflict (name) do update
               set key_id=excluded.key_id, data=excluded.data, updated_at=now()""",
            name, self.vault.key_id, data,
        )

    async def web_note(self, name):
        row = await self.pool.fetchrow("select data from web_notes where name=$1", name)
        return self.vault.decrypt_json(row["data"], f"web:{name}") if row else None

    async def web_publish(self, clan_alias, kind, slug, payload):
        data = self.vault.encrypt_json(payload, f"page:{clan_alias}:{kind}")
        await self.pool.execute(
            """insert into web_pages(clan_alias, kind, slug, key_id, data) values($1,$2,$3,$4,$5)
               on conflict (clan_alias, kind) do update
               set slug=excluded.slug, key_id=excluded.key_id, data=excluded.data, updated_at=now()""",
            clan_alias, kind, slug, self.vault.key_id, data,
        )
        await self.pool.execute("select pg_notify($1, $2)", PAGE_CHANNEL, slug)

    async def web_page(self, slug, kind):
        row = await self.pool.fetchrow(
            "select clan_alias, data from web_pages where slug=$1 and kind=$2", slug, kind
        )
        if not row:
            return None
        return self.vault.decrypt_json(row["data"], f"page:{row['clan_alias']}:{kind}")

    async def web_drop_page(self, clan_alias, kind):
        await self.pool.execute(
            "delete from web_pages where clan_alias=$1 and kind=$2", clan_alias, kind
        )

    async def web_app_alias(self, slug):
        return await self.pool.fetchval(
            "select clan_alias from web_pages where slug=$1 and kind=$2", slug, WEB_APP
        )

    async def web_intent_for(self, slug, kind, body):
        alias = await self.web_app_alias(slug)
        if not alias:
            return 0
        data = self.vault.encrypt_json(body, f"web:intent:{alias}")
        return await self.pool.fetchval(
            """insert into web_intents(clan_alias, kind, key_id, data) values($1,$2,$3,$4)
               returning id""",
            alias, kind, self.vault.key_id, data,
        )

    async def web_intent_pending(self, intent_id):
        return bool(await self.pool.fetchval("select 1 from web_intents where id=$1", intent_id))

    async def web_intents_take(self, limit=50):
        rows = await self.pool.fetch(
            """update web_intents set taken_at = now() where id in (
                 select id from web_intents where taken_at is null order by id limit $1
               ) returning id, clan_alias, kind, data""",
            limit,
        )
        return [
            {"id": row["id"], "clan": row["clan_alias"], "kind": row["kind"],
             "body": self.vault.decrypt_json(row["data"], f"web:intent:{row['clan_alias']}")}
            for row in rows
        ]

    async def web_intent_done(self, intent_id):
        await self.pool.execute("delete from web_intents where id=$1", intent_id)

    async def intent_oldest_age(self, now):
        oldest = await self.pool.fetchval("select min(created_at) from web_intents")
        return max(0.0, float(now) - oldest.timestamp()) if oldest else None

    async def db_size_bytes(self):
        return int(await self.pool.fetchval("select pg_database_size(current_database())") or 0)

    def recruit_code(self, clan_alias):
        return self.vault.blind("network", clan_alias)[:6]

    def _network(self, row):
        payload = self.vault.decrypt_json(row["data"], f"network:{row['clan_alias']}")
        metrics = payload.get("metrics")
        return {
            "alias": row["clan_alias"],
            "visible": row["visible"],
            "named": row["named"],
            "code": self.recruit_code(row["clan_alias"]),
            "name": payload.get("name") if row["named"] else None,
            "week": payload.get("week"),
            "metrics": metrics if isinstance(metrics, dict) else {},
            "verified": bool(row["verified"]),
            "updated_at": row["updated_at"],
        }

    async def set_network_verified(self, clan_alias, value):
        return deleted_rows(await self.pool.execute(
            """update network_clans set verified=$2
               where clan_alias=$1 and verified is distinct from $2""",
            clan_alias, bool(value))) > 0

    async def network_set(self, clan_alias, visible, named, payload):
        data = self.vault.encrypt_json(payload, f"network:{clan_alias}")
        await self.pool.execute(
            """insert into network_clans(clan_alias, visible, named, key_id, data) values($1,$2,$3,$4,$5)
               on conflict (clan_alias) do update
               set visible=excluded.visible, named=excluded.named, key_id=excluded.key_id,
                   data=excluded.data, updated_at=now()""",
            clan_alias, visible, named, self.vault.key_id, data,
        )

    async def network_get(self, clan_alias):
        row = await self.pool.fetchrow("select * from network_clans where clan_alias=$1", clan_alias)
        return self._network(row) if row else None

    async def network_board(self, limit=20):
        rows = await self.pool.fetch(
            "select * from network_clans where visible order by updated_at desc limit 500")
        board = []
        for row in rows:
            try:
                board.append(self._network(row))
            except Exception:
                log.exception("%s: riga di rete illeggibile", row["clan_alias"])
        board.sort(key=lambda r: (-(r["metrics"].get("avg") or 0), r["code"]))
        return board[:limit]

    async def network_forget(self, clan_alias):
        return deleted_rows(await self.pool.execute(
            "delete from network_clans where clan_alias=$1", clan_alias)) > 0

    def _tournament(self, row):
        doc = self.vault.decrypt_json(row["data"], f"tour:{row['alias']}")
        doc["alias"] = row["alias"]
        doc["status"] = row["status"]
        doc["family_alias"] = row["family_alias"]
        doc["clan_alias"] = row["clan_alias"]
        return doc

    def _tournaments(self, rows):
        out = []
        for row in rows:
            try:
                out.append(self._tournament(row))
            except Exception:
                log.exception("%s: torneo illeggibile", row["alias"])
        return out

    def _ends_at(self, doc):
        ends = int(doc.get("ends") or 0)
        return datetime.fromtimestamp(ends, timezone.utc) if ends else None

    async def create_tournament(self, doc, owner_id, family_alias=None, clan_alias=None):
        alias = self.vault.alias("trn")
        doc = dict(doc)
        doc["alias"] = alias
        doc["status"] = "signup"
        doc["family_alias"] = family_alias
        doc["clan_alias"] = clan_alias
        await self.pool.execute(
            """insert into tournaments(alias, owner_index, scope, kind, status, family_alias,
                                       clan_alias, key_id, data, ends_at)
               values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            alias, self.vault.blind("user", owner_id), doc.get("scope"), doc.get("kind"), "signup",
            family_alias, clan_alias, self.vault.key_id,
            self.vault.encrypt_json(doc, f"tour:{alias}"), self._ends_at(doc),
        )
        return alias

    async def save_tournament(self, alias, doc, status=None):
        doc = dict(doc)
        doc["alias"] = alias
        await self.pool.execute(
            """update tournaments set data=$2, key_id=$3, status=coalesce($4, status),
               ends_at=$5, updated_at=now() where alias=$1""",
            alias, self.vault.encrypt_json(doc, f"tour:{alias}"), self.vault.key_id,
            status, self._ends_at(doc),
        )

    async def tournament(self, alias):
        row = await self.pool.fetchrow("select * from tournaments where alias=$1", alias)
        return self._tournament(row) if row else None

    async def tournaments_for(self, family_alias=None, clan_alias=None, status=None, scope=None):
        rows = await self.pool.fetch(
            """select * from tournaments
               where kind <> 'derby'
                 and ($1::text is null or family_alias=$1)
                 and ($2::text is null or clan_alias=$2)
                 and ($3::text is null or status=$3)
                 and ($4::text is null or scope=$4)
               order by created_at desc limit 50""",
            family_alias, clan_alias, status, scope,
        )
        return self._tournaments(rows)

    async def live_tournaments(self):
        return self._tournaments(await self.pool.fetch(
            "select * from tournaments where status <> 'done' and kind <> 'derby' order by created_at"
        ))

    async def delete_tournament(self, alias):
        return deleted_rows(await self.pool.execute(
            "delete from tournaments where alias=$1", alias)) > 0

    async def recruit_publish(self, clan_alias, card):
        data = self.vault.encrypt_json(card, f"recruit:{clan_alias}") if card else None
        await self.pool.execute(
            """insert into network_clans(clan_alias, key_id, data, recruiting, recruit_data)
               values($1,$2,$3,true,$4)
               on conflict (clan_alias) do update
               set recruiting=true, recruit_data=excluded.recruit_data, updated_at=now()""",
            clan_alias, self.vault.key_id, self.vault.encrypt_json({}, f"network:{clan_alias}"), data,
        )

    async def recruit_stop(self, clan_alias):
        gone = deleted_rows(await self.pool.execute(
            "delete from network_clans where clan_alias=$1 and not visible", clan_alias))
        if gone:
            return True
        return deleted_rows(await self.pool.execute(
            """update network_clans set recruiting=false, recruit_data=null, updated_at=now()
               where clan_alias=$1 and recruiting""", clan_alias)) > 0

    def _recruit(self, row):
        card = self.vault.decrypt_json(row["recruit_data"], f"recruit:{row['clan_alias']}")
        if not row["named"]:
            card["name"] = None
            card["tag"] = None
        card["code"] = self.recruit_code(row["clan_alias"])
        card["verified"] = bool(row["verified"])
        return card

    async def recruit_row(self, clan_alias):
        row = await self.pool.fetchrow(
            """select clan_alias, named, recruiting, recruit_data, verified, updated_at
               from network_clans where clan_alias=$1 and recruiting""", clan_alias)
        if not row:
            return None
        card = self._recruit(row) if row["recruit_data"] else None
        return {"recruiting": True, "named": row["named"], "card": card,
                "ts": row["updated_at"].timestamp()}

    async def recruit_board(self, limit=20, country=None, min_th=None, lang=None):
        rows = await self.pool.fetch(
            """select clan_alias, named, recruit_data, verified from network_clans
               where recruiting and recruit_data is not null
               order by updated_at desc limit 500""")
        board = []
        for row in rows:
            try:
                card = self._recruit(row)
            except Exception:
                log.exception("%s: riga di bacheca illeggibile", row["clan_alias"])
                continue
            if recruit_matches(card, country, min_th, lang):
                board.append(card)
        return recruit_ordered(board)[:limit]

    async def public_codes(self):
        rows = await self.pool.fetch("select slug from web_pages where kind=$1", WEB_PUBLIC)
        return {row["slug"] for row in rows}

    async def recruit_target(self, code):
        rows = await self.pool.fetch(
            """select clan_alias, verified from network_clans
               where recruiting and recruit_data is not null""")
        for row in rows:
            if self.recruit_code(row["clan_alias"]) != code:
                continue
            clan = await self.clan_by_alias(row["clan_alias"])
            if not clan:
                continue
            bot = await self.bot_by_alias(clan.bot_alias) if clan.bot_alias else None
            return {"alias": clan.alias, "tag": clan.tag, "bot": bot.username if bot else None,
                    "verified": bool(row["verified"])}
        return None

    async def report_add(self, clan_alias, user_id, reason, now):
        key = f"{REPORTS_KEY}{clan_alias}"
        stored = await self.kv_get(key) or {}
        rows = list(stored.get("rows") or [])
        rows = (rows + [{"at": now.timestamp(), "by": int(user_id), "reason": reason}])[-REPORTS_KEEP:]
        await self.kv_set(key, {"rows": rows}, ref=clan_alias, ttl=REPORTS_TTL)
        return len(rows)

    async def report_forget(self, clan_alias, user_id):
        key = f"{REPORTS_KEY}{clan_alias}"
        rows = list((await self.kv_get(key) or {}).get("rows") or [])
        kept = [row for row in rows if int(row.get("by") or 0) != int(user_id)]
        if len(kept) == len(rows):
            return 0
        await self.kv_set(key, {"rows": kept}, ref=clan_alias, ttl=REPORTS_TTL)
        return len(rows) - len(kept)

    async def reports_for(self, clan_alias):
        stored = await self.kv_get(f"{REPORTS_KEY}{clan_alias}") or {}
        code = self.recruit_code(clan_alias)
        found = [{"code": code, "reason": entry.get("reason"), "at": entry.get("at")}
                 for entry in stored.get("rows") or () if isinstance(entry, dict)]
        found.sort(key=lambda entry: -(entry.get("at") or 0))
        return found

    async def reports(self, limit=20):
        rows = await self.pool.fetch(
            f"""select k, ref, data from kv where k like '{REPORTS_KEY}%'
                and (expires_at is null or expires_at > now())
                order by updated_at desc limit 500""")
        found = []
        for row in rows:
            try:
                stored = self.vault.decrypt_json(row["data"], f"kv:{row['k']}")
            except Exception:
                log.exception("%s: segnalazioni illeggibili", row["k"])
                continue
            for entry in stored.get("rows") or ():
                found.append({"alias": row["ref"], "code": self.recruit_code(row["ref"]),
                              "reason": entry.get("reason"), "at": entry.get("at")})
        found.sort(key=lambda entry: -(entry.get("at") or 0))
        return found[:limit]

    async def retention_counts(self):
        return {name: int(await self.pool.fetchval(sql)) for name, sql in COUNT_SQL.items()}

    async def run_retention(self):
        deleted = {}
        async with self.pool.acquire() as conn, conn.transaction():
            for name, sql in DELETE_SQL.items():
                deleted[name] = deleted_rows(await conn.execute(sql))
        return deleted

    async def site_day_put(self, day, body):
        columns = ", ".join(SITE_DAY_FIELDS)
        slots = ", ".join(f"${n}" for n in range(2, len(SITE_DAY_FIELDS) + 2))
        fresh = ", ".join(f"{name}=excluded.{name}" for name in SITE_DAY_FIELDS)
        last = len(SITE_DAY_FIELDS) + 2
        await self.pool.execute(
            f"""insert into site_days(day, {columns}, countries)
                values($1, {slots}, ${last}::jsonb)
                on conflict (day) do update set {fresh},
                countries=excluded.countries, updated_at=now()""",
            day, *[int(body.get(name) or 0) for name in SITE_DAY_FIELDS],
            json.dumps(body.get("countries") or {}),
        )

    async def site_days(self, limit=SITE_DAYS_KEEP):
        rows = await self.pool.fetch(
            "select * from site_days order by day desc limit $1", int(limit))
        return [site_day_row(row) for row in reversed(rows)]

    async def incident_add(self, kind, note, now):
        data = self.vault.encrypt_json({"kind": kind, "note": note}, INCIDENT_AAD)
        return int(await self.pool.fetchval(
            """insert into incidents(opened, kind, key_id, data) values($1,$2,$3,$4)
               returning id""",
            now, kind, self.vault.key_id, data,
        ))

    async def incident_close(self, incident_id, now):
        done = await self.pool.execute(
            "update incidents set closed=$2 where id=$1 and closed is null",
            int(incident_id), now)
        return deleted_rows(done) > 0

    async def incidents(self, limit=INCIDENTS_KEEP):
        rows = await self.pool.fetch(
            """select id, opened, closed, kind, data from incidents
               order by opened desc limit $1""", int(limit))
        found = []
        for row in rows:
            try:
                stored = self.vault.decrypt_json(row["data"], INCIDENT_AAD)
            except Exception:
                log.warning("un incidente non si legge, lo salto")
                continue
            found.append({"id": int(row["id"]), "kind": row["kind"], "opened": row["opened"],
                          "closed": row["closed"], "note": stored.get("note")})
        return found
