import asyncio
import json
from datetime import datetime, timezone

import pytest

from clashbot import db
from clashbot.__main__ import SECRET_KINDS, parse_migrate_args
from clashbot.crypto import Vault
from clashbot.db import CLAN_BOUND_STATE, KEEP_STATE, SCHEMA, Bot, Clan, Family, Link, Store


def test_schema_crea_la_tabella_bots():
    assert "create table if not exists bots (" in SCHEMA
    for piece in (
        "alias text primary key",
        "owner_index text not null",
        "kind text not null default 'worker'",
        "bot_index text not null unique",
        "key_id text not null",
        "identity bytea not null",
        "active boolean not null default true",
        "reason text",
        "failures int not null default 0",
        "last_seen timestamptz",
    ):
        assert piece in SCHEMA


def test_schema_aggiunge_bot_alias_e_sostituisce_gli_indici_unici():
    assert "alter table clans add column if not exists bot_alias text references bots(alias) on delete cascade" in SCHEMA
    assert "alter table families add column if not exists bot_alias text references bots(alias) on delete cascade" in SCHEMA
    assert "alter table clans drop constraint if exists clans_chat_index_key" in SCHEMA
    assert "alter table families drop constraint if exists families_chat_index_key" in SCHEMA
    assert "create unique index if not exists clans_bot_chat_idx on clans (bot_alias, chat_index)" in SCHEMA
    assert "create unique index if not exists families_bot_chat_idx on families (bot_alias, chat_index)" in SCHEMA


def test_schema_resta_idempotente():
    statements = [s.strip() for s in SCHEMA.split(";") if s.strip()]
    for statement in statements:
        head = " ".join(statement.split())
        if head.startswith("create table"):
            assert head.startswith("create table if not exists"), head
        if head.startswith("create index") or head.startswith("create unique index"):
            assert "if not exists" in head, head
        if head.startswith("alter table") and " add column" in head:
            assert "add column if not exists" in head, head
        if head.startswith("alter table") and " drop constraint" in head:
            assert "drop constraint if exists" in head, head
    assert SCHEMA.index("create table if not exists bots") < SCHEMA.index("alter table clans add column if not exists bot_alias")


def test_bot_dataclass_con_default_e_senza_token():
    bot = Bot(alias="bot-abc123", owner_id=7, username="FuturoCoCBot", bot_id=42)
    assert (bot.kind, bot.active, bot.reason, bot.failures) == ("worker", True, None, 0)
    assert bot.created_at is None and bot.last_seen is None
    assert not hasattr(bot, "token")
    assert "token" not in repr(bot)
    pieno = Bot("bot-def456", 7, "ClanBoardBot", 43, "console", False, "token_invalid", 3, None, None)
    assert (pieno.kind, pieno.active, pieno.reason, pieno.failures) == ("console", False, "token_invalid", 3)


def test_clan_e_family_guadagnano_bot_alias_opzionale():
    clan = Clan("clan-1", -100, "#ABC", "Futuro", True, 0, None)
    assert clan.bot_alias is None
    assert Clan("clan-1", -100, "#ABC", "Futuro", True, 0, None, "bot-abc123").bot_alias == "bot-abc123"
    family = Family("fam-1", "Famiglia", 7, None)
    assert family.bot_alias is None
    assert Family("fam-1", "Famiglia", 7, None, "bot-abc123").bot_alias == "bot-abc123"


def test_bot_decoder_legge_identita_cifrata(tmp_path):
    vault = Vault(tmp_path)
    store = Store(vault)
    creato = datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc)
    row = {
        "alias": "bot-abc123",
        "kind": "worker",
        "active": False,
        "reason": "token_invalid",
        "failures": 2,
        "created_at": creato,
        "last_seen": None,
        "identity": vault.encrypt_json(
            {"token": "123:SEGRETO", "owner_id": 7, "username": "FuturoCoCBot", "bot_id": 42},
            "bot:bot-abc123",
        ),
    }
    bot = store._bot(row)
    assert bot == Bot("bot-abc123", 7, "FuturoCoCBot", 42, "worker", False, "token_invalid", 2, creato, None)
    assert "SEGRETO" not in repr(bot)


def test_clan_e_family_decoder_portano_il_bot(tmp_path):
    vault = Vault(tmp_path)
    store = Store(vault)
    clan_row = {
        "alias": "clan-1", "active": True, "failures": 0, "last_seen": None, "bot_alias": "bot-abc123",
        "identity": vault.encrypt_json({"chat_id": -100, "tag": "#ABC", "name": "Futuro"}, "clan:clan-1"),
    }
    assert store._clan(clan_row).bot_alias == "bot-abc123"
    family_row = {
        "alias": "fam-1", "bot_alias": "bot-abc123",
        "identity": vault.encrypt_json({"name": "Famiglia", "owner_id": 7, "chat_id": None}, "family:fam-1"),
    }
    family = store._family(family_row)
    assert family.bot_alias == "bot-abc123" and family.chat_id is None


def test_parse_migrate_args():
    assert parse_migrate_args([]) == (False, None)
    assert parse_migrate_args(["--yes"]) == (True, None)
    assert parse_migrate_args(["--database", "clashbot_test"]) == (False, "clashbot_test")
    assert parse_migrate_args(["--database=clashbot_test", "--yes"]) == (True, "clashbot_test")
    assert parse_migrate_args(["--yes", "--database", "copia"]) == (True, "copia")


def test_parse_migrate_args_rifiuta_argomenti_sbagliati():
    for argv in (["--database"], ["--database="], ["--forza"], ["copia"], ["--yes=1"]):
        with pytest.raises(SystemExit):
            parse_migrate_args(argv)


def test_console_token_fra_i_segreti_ammessi():
    assert "console_token" in SECRET_KINDS
    assert "telegram_token" in SECRET_KINDS


class Taken:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return self.pool

    async def __aexit__(self, kind, error, trace):
        return False


class FakePool:
    def __init__(self):
        self.rows = {}
        self.steps = []
        self.broken = False

    def acquire(self):
        return Taken(self)

    def transaction(self):
        return self

    async def __aenter__(self):
        self.steps.append("begin")
        self.before = {key: dict(row) for key, row in self.rows.items()}
        return self

    async def __aexit__(self, kind, error, trace):
        if kind:
            self.rows = self.before
        self.steps.append("rollback" if kind else "commit")
        return False

    async def fetchval(self, sql, *args):
        assert "born_index=$1" in sql and "bot_index<>$2" in sql
        return next((row["alias"] for key, row in self.rows.items()
                     if row["born_index"] == args[0] and key != args[1]), None)

    async def fetchrow(self, sql, *args):
        if "where bot_index" in sql:
            return self.rows.get(args[0])
        if "where alias" in sql:
            return next((row for row in self.rows.values() if row["alias"] == args[0]), None)
        return None

    async def execute(self, sql, *args):
        if "set born_index=null" in sql:
            self.steps.append("update")
            row = next(row for row in self.rows.values() if row["alias"] == args[0])
            row.update({"born_index": None, "key_id": args[1], "identity": args[2]})
            return "UPDATE 1"
        if self.broken:
            raise RuntimeError("database giù")
        self.steps.append("insert")
        alias, owner_index, kind, bot_index, key_id, identity, *born = args
        born_index = born[0] if born else None
        row = self.rows.get(bot_index)
        if row:
            row.update({"owner_index": owner_index, "kind": kind, "key_id": key_id, "born_index": born_index,
                        "identity": identity, "active": True, "reason": None, "failures": 0})
            return "UPDATE 1"
        self.rows[bot_index] = {
            "alias": alias, "owner_index": owner_index, "kind": kind, "bot_index": bot_index,
            "key_id": key_id, "identity": identity, "active": True, "reason": None,
            "failures": 0, "created_at": None, "last_seen": None, "born_index": born_index,
        }
        return "INSERT 0 1"


def store_with_pool(tmp_path):
    store = Store(Vault(tmp_path))
    store.pool = FakePool()
    return store


def test_add_bot_trusted_takes_over_owner(tmp_path):
    store = store_with_pool(tmp_path)
    primo = asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42))
    with pytest.raises(ValueError, match="owned_by_other"):
        asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 42))
    bot = asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 42, trusted=True))
    assert bot.alias == primo.alias and bot.owner_id == 2 and bot.username == "SecondoBot"
    row = store.pool.rows[store.vault.blind("bot", 42)]
    assert row["owner_index"] == store.vault.blind("user", 2)
    identita = store.vault.decrypt_json(row["identity"], f"bot:{bot.alias}")
    assert identita == {"token": "123:DUE", "owner_id": 2, "username": "SecondoBot", "bot_id": 42}
    assert len(store.pool.rows) == 1


def test_add_bot_trusted_still_refuses_disabled(tmp_path):
    store = store_with_pool(tmp_path)
    bot = asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42))
    store.pool.rows[store.vault.blind("bot", 42)]["reason"] = "disabled"
    with pytest.raises(ValueError, match="disabled"):
        asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 42, trusted=True))
    ripreso = asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 42, allow_disabled=True, trusted=True))
    assert ripreso.alias == bot.alias and ripreso.owner_id == 2 and ripreso.active


def test_il_bot_porta_il_clan_per_cui_e_nato_e_lo_tiene_al_rinnovo(tmp_path):
    store = store_with_pool(tmp_path)
    bot = asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    row = store.pool.rows[store.vault.blind("bot", 42)]
    assert store.vault.decrypt_json(row["identity"], f"bot:{bot.alias}")["clan_tag"] == "#2PP"
    asyncio.run(store.add_bot(1, "123:DUE", "PrimoBot", 42, trusted=True))
    rinnovata = store.vault.decrypt_json(row["identity"], f"bot:{bot.alias}")
    assert rinnovata["clan_tag"] == "#2PP" and rinnovata["token"] == "123:DUE"


def test_il_clan_di_nascita_ha_il_suo_indice_cieco_e_lo_tiene_al_rinnovo(tmp_path):
    store = store_with_pool(tmp_path)
    asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    row = store.pool.rows[store.vault.blind("bot", 42)]
    assert row["born_index"] == store.vault.blind("tag", "#2PP") and "2PP" not in row["born_index"]
    asyncio.run(store.add_bot(1, "123:DUE", "PrimoBot", 42, trusted=True))
    assert row["born_index"] == store.vault.blind("tag", "#2PP")
    asyncio.run(store.add_bot(1, "123:TRE", "AltroBot", 43))
    assert store.pool.rows[store.vault.blind("bot", 43)]["born_index"] is None


def test_il_bot_che_perde_il_clan_resta_registrato_senza_clan(tmp_path):
    store = store_with_pool(tmp_path)
    bot = asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    asyncio.run(store.drop_born(bot.alias))
    row = store.pool.rows[store.vault.blind("bot", 42)]
    rimasta = store.vault.decrypt_json(row["identity"], f"bot:{bot.alias}")
    assert rimasta == {"token": "123:UNO", "owner_id": 1, "username": "PrimoBot", "bot_id": 42}
    assert row["born_index"] is None and len(store.pool.rows) == 1
    asyncio.run(store.add_bot(1, "123:DUE", "PrimoBot", 42, trusted=True))
    assert row["born_index"] is None
    asyncio.run(store.drop_born("bot-che-non-esiste"))
    assert len(store.pool.rows) == 1


def nato(store, bot_id):
    row = store.pool.rows[store.vault.blind("bot", bot_id)]
    return row["born_index"], store.vault.decrypt_json(row["identity"], f"bot:{row['alias']}").get("clan_tag")


def test_schema_un_clan_di_nascita_ha_un_bot_solo():
    assert ("create unique index if not exists bots_born_one_idx on bots (born_index) "
            "where born_index is not null") in " ".join(SCHEMA.split())


def test_il_secondo_bot_nato_per_lo_stesso_clan_resta_senza_clan(tmp_path):
    store = store_with_pool(tmp_path)
    cieco = store.vault.blind("tag", "#2PP")
    asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    secondo = asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 43, clan_tag="#2PP"))
    assert secondo.bot_id == 43 and len(store.pool.rows) == 2
    assert nato(store, 42) == (cieco, "#2PP") and nato(store, 43) == (None, None)
    asyncio.run(store.add_bot(2, "123:TRE", "SecondoBot", 43, clan_tag="#2PP", trusted=True))
    assert nato(store, 42) == (cieco, "#2PP") and nato(store, 43) == (None, None)


def test_il_bot_nuovo_prende_il_clan_del_vecchio_in_un_passo_solo(tmp_path):
    store = store_with_pool(tmp_path)
    cieco = store.vault.blind("tag", "#2PP")
    vecchio = asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    store.pool.steps.clear()
    asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 43, clan_tag="#2PP", replaces=vecchio.alias))
    assert store.pool.steps == ["begin", "update", "insert", "commit"]
    assert nato(store, 42) == (None, None) and nato(store, 43) == (cieco, "#2PP")
    assert len(store.pool.rows) == 2


def test_la_nascita_rifiutata_lascia_il_clan_al_bot_vecchio(tmp_path):
    store = store_with_pool(tmp_path)
    cieco = store.vault.blind("tag", "#2PP")
    vecchio = asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 43))
    store.pool.rows[store.vault.blind("bot", 43)]["reason"] = "disabled"
    store.pool.steps.clear()
    with pytest.raises(ValueError, match="disabled"):
        asyncio.run(store.add_bot(2, "123:TRE", "SecondoBot", 43, clan_tag="#2PP", trusted=True,
                                  replaces=vecchio.alias))
    assert store.pool.steps == [] and nato(store, 42) == (cieco, "#2PP")


def test_la_nascita_che_si_rompe_a_meta_non_lascia_il_clan_senza_bot(tmp_path):
    store = store_with_pool(tmp_path)
    cieco = store.vault.blind("tag", "#2PP")
    vecchio = asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    store.pool.steps.clear()
    store.pool.broken = True
    with pytest.raises(RuntimeError):
        asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 43, clan_tag="#2PP", replaces=vecchio.alias))
    assert store.pool.steps == ["begin", "update", "rollback"]
    assert nato(store, 42) == (cieco, "#2PP") and len(store.pool.rows) == 1


def test_chi_nomina_un_bot_che_non_tiene_il_clan_non_scalza_chi_lo_tiene(tmp_path):
    store = store_with_pool(tmp_path)
    cieco = store.vault.blind("tag", "#2PP")
    asyncio.run(store.add_bot(1, "123:UNO", "PrimoBot", 42, clan_tag="#2pp"))
    terzo = asyncio.run(store.add_bot(3, "123:TRE", "TerzoBot", 44))
    asyncio.run(store.add_bot(2, "123:DUE", "SecondoBot", 43, clan_tag="#2PP", replaces=terzo.alias))
    assert nato(store, 42) == (cieco, "#2PP") and nato(store, 43) == (None, None)


class SecretsPool:
    def __init__(self, status):
        self.status = status
        self.log = []

    async def execute(self, sql, *args):
        self.log.append((" ".join(sql.split()), args))
        return self.status


def test_delete_secret_removes_only_that_kind(tmp_path):
    for status, expected in (("DELETE 1", True), ("DELETE 0", False)):
        store = Store(Vault(tmp_path))
        store.pool = SecretsPool(status)
        assert asyncio.run(store.delete_secret("support_url")) is expected
        assert store.pool.log == [("delete from secrets where kind=$1", ("support_url",))]


class LinksPool:
    def __init__(self):
        self.rows = []

    async def fetchrow(self, sql, *args):
        return next((row for row in self.rows if row["player_index"] == args[0]), None)

    async def fetch(self, sql, *args):
        return [row for row in self.rows if row["user_index"] == args[0]]

    async def execute(self, sql, *args):
        head = " ".join(sql.split())
        if head.startswith("update links set whisper"):
            for row in self.rows:
                if row["user_index"] == args[0] and row["player_index"] == args[1]:
                    row["whisper"] = args[2]
            return "UPDATE 1"
        if head.startswith("update links set verified"):
            for row in self.rows:
                if row["user_index"] == args[0] and row["player_index"] == args[1]:
                    row["verified"] = args[2]
            return "UPDATE 1"
        if head.startswith("update links"):
            for row in self.rows:
                if row["alias"] == args[0]:
                    row["identity"] = args[1]
            return "UPDATE 1"
        alias, user_index, player_index, key_id, identity = args
        claim = "verified) values($1,$2,$3,$4,$5,false)" in head
        for row in self.rows:
            if row["player_index"] == player_index:
                if claim:
                    return "INSERT 0 0"
                row.update({"user_index": user_index, "key_id": key_id, "identity": identity,
                            "verified": True})
                return "UPDATE 1"
        self.rows.append({"alias": alias, "user_index": user_index, "player_index": player_index,
                          "key_id": key_id, "identity": identity, "whisper": False,
                          "verified": not claim, "created_at": len(self.rows)})
        return "INSERT 0 1"


def links_store(tmp_path):
    store = Store(Vault(tmp_path))
    store.pool = LinksPool()
    return store


def test_link_carries_an_optional_language():
    assert Link("link-1", 7, "#ABC", "Alex", True).lang is None
    assert Link("link-1", 7, "#ABC", "Alex", True, "de").lang == "de"


def test_il_sussurro_nasce_spento_sul_collegamento():
    assert Link("link-1", 7, "#ABC", "Alex", True).whisper is False
    assert Link("link-1", 7, "#ABC", "Alex", True, "de", True).whisper is True
    assert "alter table links add column if not exists whisper boolean not null default false" in SCHEMA


def test_il_sussurro_si_accende_per_un_villaggio_alla_volta(tmp_path):
    store = links_store(tmp_path)
    asyncio.run(store.link_player(7, "#ABC", "Alex"))
    asyncio.run(store.link_player(7, "#DEF", "AlexMini"))
    assert [row.whisper for row in asyncio.run(store.links_by_user(7))] == [False, False]
    asyncio.run(store.set_link_whisper(7, "#ABC", True))
    assert [(row.tag, row.whisper) for row in asyncio.run(store.links_by_user(7))] == [
        ("#ABC", True), ("#DEF", False),
    ]
    asyncio.run(store.set_link_whisper(7, "#ABC", False))
    assert [row.whisper for row in asyncio.run(store.links_by_user(7))] == [False, False]


def test_the_language_of_a_link_lives_in_the_encrypted_document(tmp_path):
    store = links_store(tmp_path)
    asyncio.run(store.link_player(7, "#ABC", "Alex", dm=True, lang="de"))
    link = asyncio.run(store.links_by_user(7))[0]
    assert (link.lang, link.dm, link.tag, link.name) == ("de", True, "#ABC", "Alex")
    identity = store.pool.rows[0]["identity"]
    assert store.vault.decrypt_json(identity, f"link:{link.alias}")["lang"] == "de"


def test_a_fresh_link_has_no_language_and_relinking_keeps_the_one_it_had(tmp_path):
    store = links_store(tmp_path)
    asyncio.run(store.link_player(7, "#ABC", "Alex"))
    assert asyncio.run(store.links_by_user(7))[0].lang is None
    asyncio.run(store.set_link_lang(7, "fr"))
    asyncio.run(store.link_player(7, "#ABC", "Alex"))
    assert asyncio.run(store.links_by_user(7))[0].lang == "fr"


def test_a_village_that_changes_owner_does_not_inherit_the_language(tmp_path):
    store = links_store(tmp_path)
    asyncio.run(store.link_player(7, "#ABC", "Alex", lang="de"))
    asyncio.run(store.link_player(8, "#ABC", "Bea"))
    assert asyncio.run(store.links_by_user(7)) == []
    assert asyncio.run(store.links_by_user(8))[0].lang is None


def test_set_link_lang_moves_every_link_of_that_user_only(tmp_path):
    store = links_store(tmp_path)
    asyncio.run(store.link_player(7, "#ABC", "Alex"))
    asyncio.run(store.link_player(7, "#DEF", "Alex secondo"))
    asyncio.run(store.link_player(8, "#GHI", "Bea"))
    asyncio.run(store.set_link_lang(7, "es"))
    assert [link.lang for link in asyncio.run(store.links_by_user(7))] == ["es", "es"]
    assert asyncio.run(store.links_by_user(8))[0].lang is None


def test_saving_a_link_does_not_lose_the_language(tmp_path):
    store = links_store(tmp_path)
    asyncio.run(store.link_player(7, "#ABC", "Alex", lang="it"))
    link = asyncio.run(store.links_by_user(7))[0]
    link.dm = True
    asyncio.run(store.update_link(link))
    saved = asyncio.run(store.links_by_user(7))[0]
    assert (saved.lang, saved.dm) == ("it", True)


def test_il_cambio_tag_azzera_gli_stati_legati_al_clan_derivandoli_da_keep_state(tmp_path):
    from test_retention import store_with

    assert CLAN_BOUND_STATE == tuple(kind for kind in KEEP_STATE if kind != "settings")
    assert "settings" not in CLAN_BOUND_STATE
    store = store_with(tmp_path,
                       statuses=["UPDATE 1", "DELETE 4", "DELETE 9", "DELETE 2", "DELETE 3",
                                 "DELETE 6", "DELETE 1", "DELETE 5"])

    async def fetchrow(sql, *args):
        return {"alias": "clan-1", "tag_index": "altro"}

    async def clan_by_chat(chat_id, bot_alias=None):
        return "clan"

    store.pool.fetchrow = fetchrow
    store.clan_by_chat = clan_by_chat
    asyncio.run(store.add_clan(-100, "#AAA", "Clan", bot_alias="bot-1"))
    puliti = [entry for entry in store.pool.log
              if isinstance(entry, tuple)
              and entry[0] == "delete from clan_state where clan_alias=$1 and kind = any($2::text[])"]
    assert [entry[1][1] for entry in puliti] == [list(CLAN_BOUND_STATE)]
    tenuti = [entry for entry in store.pool.log
              if isinstance(entry, tuple)
              and entry[0] == "delete from clan_state where clan_alias=$1 and not (kind = any($2::text[]))"]
    assert [entry[1][1] for entry in tenuti] == [list(KEEP_STATE)]


class FakeVault:
    key_id = "k1"

    def encrypt_json(self, obj, aad):
        return json.dumps(obj).encode()


class PublishPool:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((" ".join(sql.split()), args))
        return "INSERT 0 1"


def test_publishing_a_page_notifies_its_slug():
    store = Store.__new__(Store)
    store.pool = PublishPool()
    store.vault = FakeVault()
    asyncio.run(store.web_publish("clan-1", "app", "abc123", {"x": 1}))
    sql, args = store.pool.calls[-1]
    assert sql == "select pg_notify($1, $2)" and args == (db.PAGE_CHANNEL, "abc123")
    assert "insert into web_pages" in store.pool.calls[0][0]


def test_listen_opens_a_dedicated_connection_and_registers_the_callback():
    class Conn:
        def __init__(self):
            self.listeners = []

        async def add_listener(self, channel, fn):
            self.listeners.append((channel, fn))

        def is_closed(self):
            return False

    made = []

    async def connect(**dsn):
        conn = Conn()
        made.append((dsn, conn))
        return conn

    heard = []
    store = Store.__new__(Store)
    store.dsn = {"host": "db"}
    conn = asyncio.run(store.listen("clanboard_page", heard.append, connect=connect))
    assert made[0][0] == {"host": "db"} and conn is made[0][1]
    channel, fn = conn.listeners[0]
    fn(conn, 1, channel, "abc123")
    assert heard == ["abc123"] and channel == "clanboard_page"
