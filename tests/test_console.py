import asyncio
import importlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ChatType
from telegram.error import TelegramError, TimedOut
from telegram.ext import ManagedBotUpdatedHandler, MessageHandler, filters

from clashbot import (base_library, base_videos, console, feed, guard, i18n, key_watch, manager_alerts,
                      metrics, ops, otp, platform, platform_ban, platform_guard, publish, render,
                      reports, seats, selfmetrics, survey)
from clashbot import __main__ as cli
from clashbot.web import ban

IT = i18n.locale("it")
EN = i18n.locale("en")
MANAGED_TOKEN = "555000111:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
NEW_ID = 555000111
NEW_NAME = "FuturoGuerrieriBot"
TAG = "#2YRLQPC0"
CLAN = "Futuro Guerrieri"
USER = 7
OWNER = 99
CONSOLE_NAME = "ClanBoardBot"
MINI_APP = "https://t.me/Botfather?startapp"
LEADER_TAG = "#PL2Q9"
MEMBER_TAG = "#Y0GRJ"
PLAYERS = {LEADER_TAG: "Mario", MEMBER_TAG: "Toad"}
CLAN_ROLES = ((LEADER_TAG, "leader"), (MEMBER_TAG, "member"))


def conf():
    return importlib.import_module("clashbot.site_conf")


def make_bot(alias, owner_id=USER, username="MioBot", bot_id=123456789, active=True, reason=None, kind="worker"):
    return SimpleNamespace(
        alias=alias, owner_id=owner_id, username=username, bot_id=bot_id,
        kind=kind, active=active, reason=reason, failures=0,
    )


def account(user_id=USER, tag=LEADER_TAG, verified=True):
    return SimpleNamespace(alias="link-1", user_id=user_id, tag=tag, name=PLAYERS.get(tag, "Tizio"),
                           dm=False, lang=None, verified=verified)


def make_clan(alias, chat_id, bot_alias):
    return SimpleNamespace(alias=alias, chat_id=chat_id, tag="#C1", name="Clan", active=True, bot_alias=bot_alias)


class FakeStore:
    def __init__(self, rows=(), owner=None, clans=(), secrets=None, links=0, tokens=None,
                 add_error=None, kv_error=(), accounts=(), taken=None):
        self.rows = list(rows)
        self.add_error = add_error
        self.kv_error = tuple(kv_error)
        self.owner = owner
        self.clans = list(clans)
        self.secrets = dict(secrets or {})
        self.links = links
        self.tokens = dict(tokens or {})
        self.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
        self.accounts = list(accounts)
        self.taken = taken
        self.linked = []
        self.link_langs = []
        self.added = []
        self.removed = []
        self.born = {}
        self.dropped = []
        self.replaced = []
        self.activated = []
        self.state = {}
        self.kv = {}
        self.ttls = {}
        self.db_bytes = None
        self.intent_age = None
        self.notes = {}
        self.logs = []
        self.accepted = {f"terms:user:{USER}": {"day": "2026-09-01"}}

    async def web_note(self, name):
        return self.notes.get(name)

    async def get_secret(self, kind):
        if kind == "owner_id":
            return self.owner
        return self.secrets.get(kind)

    async def set_secret(self, kind, value):
        self.secrets[kind] = value
        return f"sec-{kind}"

    async def delete_secret(self, kind):
        return self.secrets.pop(kind, None) is not None

    async def bots(self, active_only=False):
        return [b for b in self.rows if b.active or not active_only]

    async def bots_by_owner(self, owner_id):
        return [b for b in self.rows if b.owner_id == owner_id]

    async def bot_by_alias(self, alias):
        return next((b for b in self.rows if b.alias == alias), None)

    async def bot_token(self, alias):
        return self.tokens.get(alias)

    async def add_bot(self, owner_id, token, username, bot_id, kind="worker", allow_disabled=False, trusted=False,
                      clan_tag=None, replaces=None):
        if self.add_error:
            raise self.add_error
        existing = next((b for b in self.rows if b.bot_id == bot_id), None)
        if existing and existing.reason == "disabled" and not allow_disabled:
            raise ValueError("disabled")
        if existing and existing.owner_id != owner_id and not trusted:
            raise ValueError("owned_by_other")
        self.added.append((owner_id, token, username, bot_id, kind, trusted))
        if replaces:
            self.replaced.append(replaces)
        mine = existing.alias if existing else f"bot-{bot_id}"
        holder = next((a for a, born_for in self.born.items() if clan_tag and born_for == clan_tag and a != mine),
                      None)
        if holder and holder == replaces:
            self.dropped.append(holder)
            del self.born[holder]
        elif holder:
            clan_tag = None
        if existing:
            existing.active, existing.reason = True, None
            existing.owner_id, existing.username = owner_id, username
            self.tokens[existing.alias] = token
            return existing
        created = make_bot(f"bot-{bot_id}", owner_id, username, bot_id)
        self.rows.append(created)
        if clan_tag:
            self.born[created.alias] = clan_tag
        self.tokens[created.alias] = token
        return created

    async def set_bot_active(self, alias, active, reason=None):
        self.activated.append((alias, active, reason))
        bot = await self.bot_by_alias(alias)
        if bot:
            bot.active, bot.reason = active, reason
        return bot

    async def remove_bot(self, alias):
        self.removed.append(alias)
        self.rows = [b for b in self.rows if b.alias != alias]
        self.born.pop(alias, None)
        return True

    async def drop_born(self, alias):
        raise AssertionError("il clan passa di mano solo dentro add_bot")

    async def count_clans(self, bot_alias):
        return len([c for c in self.clans if c.bot_alias == bot_alias])

    async def count_links(self):
        return self.links

    async def links_by_user(self, user_id):
        return [a for a in self.accounts if a.user_id == user_id]

    async def link_player(self, user_id, tag, name, dm=False, lang=None):
        self.linked.append((user_id, tag, name))
        self.link_langs.append(lang)
        self.accounts.append(account(user_id, tag))

    async def bot_for_tag(self, tag):
        if isinstance(self.taken, dict):
            return self.taken.get(tag)
        if self.taken:
            return self.taken
        waiting = [body.get("bot_alias") for key, body in self.kv.items()
                   if key.startswith("ob:") and body.get("tag") == tag]
        idle = [alias for alias, born_for in self.born.items()
                if born_for == tag and not await self.count_clans(alias)]
        return next(iter(idle + waiting), None)

    async def active_clans(self, bot_alias=None):
        return [c for c in self.clans if bot_alias is None or c.bot_alias == bot_alias]

    async def clan_by_alias(self, alias):
        return next((c for c in self.clans if c.alias == alias), None)

    async def links_for_players(self, tags):
        return {a.tag: a for a in self.accounts if a.tag in set(tags or ())}

    def recruit_code(self, clan_alias):
        return self.vault.blind("network", clan_alias)[:6]

    async def counts(self):
        return {"active": 2, "total": 3}

    async def families(self, bot_alias=None):
        return [SimpleNamespace(alias="fam-1")]

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def set_state(self, alias, kind, value):
        self.state[(alias, kind)] = value

    async def add_log(self, alias, entry, at=None):
        self.logs.append((alias, dict(entry), at))

    async def wars_since(self, alias, since):
        return []

    async def kv_set(self, key, obj, ref=None, ttl=None):
        if self.kv_error and key.startswith(self.kv_error):
            raise RuntimeError("kv non raggiungibile")
        self.kv[key] = obj
        self.ttls[key] = ttl

    async def kv_get(self, key):
        return self.kv.get(key, self.accepted.get(key))

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def banned(self, limit=100):
        found = [{"ip": key[len(ban.PREFIX):], "at": body.get("at"), "until": body.get("until"),
                  "strikes": body.get("strikes")}
                 for key, body in self.kv.items() if key.startswith(ban.PREFIX)]
        found.sort(key=lambda row: -(row.get("at") or 0))
        return found[:limit]

    async def db_size_bytes(self):
        return self.db_bytes

    async def intent_oldest_age(self, now):
        return self.intent_age


class FakeCoc:
    def __init__(self, name=CLAN, error=None, roles=CLAN_ROLES, player_error=None,
                 token_ok=True, token_error=None):
        self.name = name
        self.error = error
        self.roles = list(roles)
        self.player_error = player_error
        self.token_ok = token_ok
        self.token_error = token_error
        self.asked = []
        self.players = []
        self.verified = []

    def key_report(self):
        return {"total": 1, "dead": {}}

    async def clan(self, tag):
        self.asked.append(tag)
        if self.error:
            return None, self.error
        members = [{"tag": t, "name": PLAYERS.get(t, "Tizio"), "role": role} for t, role in self.roles]
        return {"tag": tag, "name": self.name, "memberList": members}, None

    async def player(self, tag):
        self.players.append(tag)
        if self.player_error:
            return None, self.player_error
        return {"tag": tag, "name": PLAYERS.get(tag, "Tizio")}, None

    async def verify_token(self, tag, token):
        self.verified.append(tag)
        if self.token_error:
            return None, self.token_error
        return self.token_ok, None


class FakeTelegramBot:
    def __init__(self, fail=False, token=MANAGED_TOKEN, token_error=False, can_manage_bots=True,
                 me_error=None, no_edit=False, keeps=False):
        self.sent = []
        self.edited = []
        self.gone = []
        self.fail = fail
        self.no_edit = no_edit
        self.keeps = keeps
        self.token = token
        self.token_error = token_error
        self.token_calls = []
        self.can_manage_bots = can_manage_bots
        self.me_error = me_error
        self.me_calls = 0
        self.username = CONSOLE_NAME

    async def get_me(self):
        self.me_calls += 1
        if self.me_error:
            raise self.me_error
        return SimpleNamespace(can_manage_bots=self.can_manage_bots)

    async def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise TelegramError("rifiutato")
        self.sent.append((chat_id, text))

    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None):
        if self.fail or self.no_edit:
            raise TelegramError("rifiutato")
        self.edited.append((chat_id, message_id, text, reply_markup))

    async def delete_message(self, chat_id=None, message_id=None):
        if self.keeps:
            raise TelegramError("rifiutato")
        self.gone.append((chat_id, message_id))

    async def get_managed_bot_token(self, user_id):
        self.token_calls.append(user_id)
        if self.token_error:
            raise TelegramError("niente token")
        return self.token


class FakeSupervisor:
    def __init__(self, running=(), bots=None, starts=True):
        self._running = list(running)
        self.bots = dict(bots or {})
        self.starts = starts
        self.started = []
        self.stopped = []
        self.restarted = []
        self.swapped = []

    async def swap_token(self, manager, bot):
        self.swapped.append((bot.alias, manager))

    async def start_bot(self, alias):
        self.started.append(alias)
        if not self.starts:
            return False
        if alias not in self._running:
            self._running.append(alias)
        return True

    async def restart_bot(self, alias):
        self.restarted.append(alias)
        if alias not in self._running:
            self._running.append(alias)
        return self.starts

    async def stop_bot(self, alias, reason=None):
        self.stopped.append((alias, reason))
        if alias in self._running:
            self._running.remove(alias)
        return True

    def running(self):
        return list(self._running)

    def bot(self, alias):
        return self.bots.get(alias)


class FakeMessage:
    def __init__(self, text="", refuse_keyboard=False, refuse_link=False):
        self.text = text
        self.sent = []
        self.deleted = False
        self.managed_bot_created = None
        self.refuse_keyboard = refuse_keyboard
        self.refuse_link = refuse_link

    async def reply_text(self, text, reply_markup=None, **kw):
        if self.refuse_keyboard and isinstance(reply_markup, ReplyKeyboardMarkup):
            raise TelegramError("tastiera rifiutata")
        if self.refuse_link and isinstance(reply_markup, InlineKeyboardMarkup):
            raise TelegramError("link rifiutato")
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)

    async def delete(self):
        self.deleted = True


class FakeQuery:
    def __init__(self, data, chat_id=USER, message_id=77):
        self.data = data
        self.answers = []
        self.edits = []
        self.message = SimpleNamespace(chat_id=chat_id, message_id=message_id)

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


def context(store, supervisor=None, args=None, user_data=None, bot=None, coc=None):
    return SimpleNamespace(
        bot_data={"store": store, "coc": coc, "supervisor": supervisor or FakeSupervisor(), "bot_alias": "console"},
        user_data=user_data if user_data is not None else {},
        args=args if args is not None else [],
        bot=bot or FakeTelegramBot(),
    )


def private(user_id=USER, text="", refuse_keyboard=False, refuse_link=False):
    return SimpleNamespace(
        callback_query=None,
        managed_bot=None,
        effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=FakeMessage(text, refuse_keyboard, refuse_link),
    )


def group(user_id=USER):
    return SimpleNamespace(
        callback_query=None,
        managed_bot=None,
        effective_chat=SimpleNamespace(id=-100, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=FakeMessage(),
    )


def born(user_id=USER, bot_id=NEW_ID, username=NEW_NAME):
    update = private(user_id)
    update.effective_message.managed_bot_created = SimpleNamespace(
        bot=SimpleNamespace(id=bot_id, username=username)
    )
    return update


def managed(user_id=USER, bot_id=NEW_ID, username=NEW_NAME):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=None,
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=None,
        managed_bot=SimpleNamespace(
            user=SimpleNamespace(id=user_id, language_code="it"),
            bot=SimpleNamespace(id=bot_id, username=username),
        ),
    )


def pressed(data, user_id=USER):
    query = FakeQuery(data, chat_id=user_id)
    update = SimpleNamespace(
        callback_query=query,
        managed_bot=None,
        effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=FakeMessage(),
    )
    return update, query


def last(update):
    return update.effective_message.sent[-1][0]


def request_of(update):
    markup = next(m for _, m in update.effective_message.sent if isinstance(m, ReplyKeyboardMarkup))
    return markup.keyboard[0][0]


def link_of(update):
    markup = next(m for _, m in update.effective_message.sent if isinstance(m, InlineKeyboardMarkup))
    return markup.inline_keyboard[0][0]


def test_start_explains_the_native_flow_and_credits_supercell():
    update = private()
    asyncio.run(console.cmd_start(update, context(FakeStore())))
    text = last(update)
    assert "/newbot" in text and "/setclan" in text
    assert "@BotFather" not in text
    assert IT.t("console.attribution") in text


def test_lo_start_col_bottone_della_home_apre_il_flusso_di_creazione():
    ctx = context(FakeStore(), args=["newbot"], coc=FakeCoc())
    update = private()
    asyncio.run(console.cmd_start(update, ctx))
    assert ctx.user_data["newbot"] == {"step": "tag"}
    assert last(update) == render.onboard_ask_clan(IT)
    assert IT.t("console.start") not in last(update)
    assert ctx.args == []


def test_outside_private_the_console_says_where_to_write():
    update = group()
    asyncio.run(console.cmd_start(update, context(FakeStore())))
    assert last(update) == IT.t("console.private_only")


def test_newbot_with_a_clan_tag_offers_the_native_button_with_suggestions():
    coc = FakeCoc()
    ctx = context(FakeStore(accounts=[account()]), coc=coc, args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert coc.asked == [TAG]
    text = update.effective_message.sent[0][0]
    assert IT.t("console.newbot_ask_native") in text
    button = request_of(update)
    assert button.text == IT.t("console.btn_create")
    assert button.request_managed_bot.suggested_name == CLAN
    assert button.request_managed_bot.suggested_username == "FuturoGuerrieriBot"
    flow = ctx.user_data["newbot"]
    assert flow["tag"] == TAG and flow["clan"] == CLAN
    assert flow["request_id"] == button.request_managed_bot.request_id


def test_newbot_with_a_tag_the_api_does_not_know_says_so():
    coc = FakeCoc(error="not_found")
    ctx = context(FakeStore(), coc=coc, args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("console.newbot_bad_tag")
    assert isinstance(markup, ReplyKeyboardRemove)
    assert "newbot" not in ctx.user_data


def test_newbot_with_something_that_is_not_a_tag_never_asks_the_api():
    coc = FakeCoc()
    ctx = context(FakeStore(), coc=coc, args=["pippo"])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert coc.asked == []
    assert last(update) == IT.t("console.newbot_bad_tag")


def test_a_clan_name_without_latin_letters_still_gets_a_valid_username():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(name="部落"), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    request = request_of(update).request_managed_bot
    assert request.suggested_name == "部落"
    assert request.suggested_username.startswith("ClanBoard")
    assert request.suggested_username.endswith("Bot")
    assert 5 <= len(request.suggested_username) <= 32


def test_a_very_long_clan_name_is_trimmed_for_telegram():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(name="Guerrieri " * 12), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    request = request_of(update).request_managed_bot
    assert len(request.suggested_name) <= 64
    assert len(request.suggested_username) <= 32
    assert request.suggested_username.endswith("Bot")
    assert request.suggested_username[0].isalpha()


def test_the_fourth_bot_of_a_user_who_leads_no_clan_never_gets_the_button():
    rows = [make_bot(f"bot-{i}", bot_id=i) for i in range(3)]
    store = FakeStore(rows=rows, owner=str(OWNER), accounts=[account(tag=MEMBER_TAG)])
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert last(update) == render.onboard_ask_player(IT, CLAN)
    assert not any(isinstance(m, ReplyKeyboardMarkup) for _, m in update.effective_message.sent)
    assert ctx.user_data["newbot"]["step"] == "player"


def test_the_platform_owner_has_no_limit():
    rows = [make_bot(f"bot-{i}", owner_id=OWNER, bot_id=i) for i in range(3)]
    store = FakeStore(rows=rows, owner=str(OWNER))
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_newbot(update, ctx))
    assert update.effective_message.sent[-1][1] is not None
    assert ctx.user_data["newbot"]["request_id"]


def banco_di_un_altro():
    store = FakeStore(rows=[make_bot("bot-x", owner_id=USER)], owner=str(OWNER),
                      clans=[make_clan("clan-x", 101, "bot-x")],
                      accounts=[account(USER, LEADER_TAG)])
    store.state[("clan-x", "members")] = {LEADER_TAG: {"name": "Mario", "role": "leader"}}
    return store, FakeSupervisor(running=["bot-x"])


def casella(store, uid):
    return asyncio.run(feed.rows(store, "clan-x", uid))


def test_la_piattaforma_non_ferma_il_bot_di_un_altro_senza_motivo():
    store, supervisor = banco_di_un_altro()
    ctx = context(store, supervisor, user_data={})
    update, query = pressed("b:stop:bot-x", user_id=OWNER)
    asyncio.run(console.on_bot_callback(update, ctx))
    assert supervisor.stopped == [] and store.logs == [] and casella(store, USER) == []
    assert datas(query.edits[-1][1]) == [f"b:open:bot-x:{r}" for r in platform.OPEN_REASONS] + ["b:back"]


def test_la_piattaforma_che_apre_col_motivo_lascia_la_riga_e_l_avviso():
    store, supervisor = banco_di_un_altro()
    ctx = context(store, supervisor, user_data={})
    update, query = pressed(f"b:open:bot-x:{platform.OPEN_REASONS[0]}", user_id=OWNER)
    asyncio.run(console.on_bot_callback(update, ctx))
    alias, entry, _ = store.logs[0]
    assert alias == "clan-x" and entry["action"] == platform.OPEN_LOG
    assert entry["by"] == OWNER and entry["detail"] == platform.OPEN_REASONS[0]
    righe = casella(store, USER)
    assert len(righe) == 1 and righe[0]["kind"] == platform.OPENED
    fermo, _ = pressed("b:stop:bot-x", user_id=OWNER)
    asyncio.run(console.on_bot_callback(fermo, ctx))
    assert supervisor.stopped == [("bot-x", "owner_stopped")]


def test_un_motivo_inventato_non_apre_niente():
    store, supervisor = banco_di_un_altro()
    ctx = context(store, supervisor, user_data={})
    update, query = pressed("b:open:bot-x:perche_si", user_id=OWNER)
    asyncio.run(console.on_bot_callback(update, ctx))
    assert store.logs == [] and casella(store, USER) == []
    assert datas(query.edits[-1][1])[-1] == "b:back"
    fermo, risposta = pressed("b:stop:bot-x", user_id=OWNER)
    asyncio.run(console.on_bot_callback(fermo, ctx))
    assert supervisor.stopped == []


def test_un_estraneo_non_apre_i_dati_di_un_clan():
    store, supervisor = banco_di_un_altro()
    update, query = pressed(f"b:open:bot-x:{platform.OPEN_REASONS[0]}", user_id=4242)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor, user_data={})))
    assert store.logs == [] and casella(store, USER) == []
    assert query.answers == [(IT.t("console.owner_only"), True)]


def test_il_motivo_di_un_bot_non_vale_per_un_altro():
    store, supervisor = banco_di_un_altro()
    store.rows.append(make_bot("bot-y", owner_id=USER, bot_id=222))
    ctx = context(store, supervisor, user_data={})
    update, _ = pressed(f"b:open:bot-x:{platform.OPEN_REASONS[0]}", user_id=OWNER)
    asyncio.run(console.on_bot_callback(update, ctx))
    altro, query = pressed("b:remove2:bot-y", user_id=OWNER)
    asyncio.run(console.on_bot_callback(altro, ctx))
    assert store.removed == []
    assert datas(query.edits[-1][1])[-1] == "b:back"


def test_un_motivo_vale_un_gesto_solo_e_ogni_gesto_lascia_la_sua_riga():
    store, supervisor = banco_di_un_altro()
    ctx = context(store, supervisor, user_data={})
    for _ in range(2):
        apre, _ = pressed(f"b:open:bot-x:{platform.OPEN_REASONS[0]}", user_id=OWNER)
        asyncio.run(console.on_bot_callback(apre, ctx))
        ferma, _ = pressed("b:stop:bot-x", user_id=OWNER)
        asyncio.run(console.on_bot_callback(ferma, ctx))
    ancora, query = pressed("b:stop:bot-x", user_id=OWNER)
    asyncio.run(console.on_bot_callback(ancora, ctx))
    assert len(supervisor.stopped) == 2 and len(store.logs) == 2
    assert datas(query.edits[-1][1]) == [f"b:open:bot-x:{r}" for r in platform.OPEN_REASONS] + ["b:back"]


def test_senza_un_clan_da_aprire_la_piattaforma_non_prende_il_motivo():
    store = FakeStore(rows=[make_bot("bot-z", owner_id=USER)], owner=str(OWNER))
    supervisor = FakeSupervisor(running=["bot-z"])
    ctx = context(store, supervisor, user_data={})
    apre, _ = pressed(f"b:open:bot-z:{platform.OPEN_REASONS[0]}", user_id=OWNER)
    asyncio.run(console.on_bot_callback(apre, ctx))
    assert store.logs == [] and ctx.user_data.get(platform.OPEN_HELD) is None
    ferma, query = pressed("b:stop:bot-z", user_id=OWNER)
    asyncio.run(console.on_bot_callback(ferma, ctx))
    assert supervisor.stopped == []
    assert datas(query.edits[-1][1]) == [f"b:open:bot-z:{r}" for r in platform.OPEN_REASONS] + ["b:back"]


def test_il_bandito_dalla_piattaforma_non_crea_un_bot():
    store, supervisor = FakeStore(), FakeSupervisor()
    asyncio.run(platform_ban.ban(store, USER, [], time.time()))
    tg = FakeTelegramBot()
    ctx = context(store, supervisor, bot=tg,
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    assert store.added == [] and supervisor.started == [] and tg.token_calls == []
    assert last(update) == IT.t("console.newbot_banned")


def test_chi_non_e_bandito_crea_il_bot_lo_stesso():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor()
    asyncio.run(platform_ban.ban(store, OWNER, [], time.time()))
    ctx = context(store, supervisor, bot=FakeTelegramBot(), coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    asyncio.run(console.on_managed_created(born(), ctx))
    assert supervisor.started == [f"bot-{NEW_ID}"]


def test_the_creation_fetches_the_token_registers_it_and_starts_the_bot():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor()
    tg = FakeTelegramBot()
    ctx = context(store, supervisor, bot=tg, coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    assert tg.token_calls == [NEW_ID]
    assert store.added == [(USER, MANAGED_TOKEN, NEW_NAME, NEW_ID, "worker", True)]
    assert supervisor.started == [f"bot-{NEW_ID}"]
    done, remove = update.effective_message.sent[0]
    assert NEW_NAME in done and MANAGED_TOKEN not in done
    assert isinstance(remove, ReplyKeyboardRemove)
    invite, keyboard = update.effective_message.sent[1]
    assert MANAGED_TOKEN not in invite
    url = keyboard.inline_keyboard[0][0].url
    code = url.rsplit("=", 1)[1]
    assert url == f"https://t.me/{NEW_NAME}?startgroup={code}" and len(code) > 8
    pending = dict(store.kv[f"ob:{code}"])
    assert pending.pop("setup")["code"] == code
    assert pending == {"tag": TAG, "name": CLAN, "user_id": USER, "bot_alias": f"bot-{NEW_ID}"}
    assert "newbot" not in ctx.user_data


def test_without_a_clan_tag_the_button_only_opens_the_group_list():
    store = FakeStore(owner=str(OWNER))
    ctx = context(store, FakeSupervisor(), bot=FakeTelegramBot(), user_data={"newbot": {"request_id": 7}})
    update = born(user_id=OWNER)
    asyncio.run(console.on_managed_created(update, ctx))
    keyboard = update.effective_message.sent[-1][1]
    assert keyboard.inline_keyboard[0][0].url == f"https://t.me/{NEW_NAME}?startgroup=true"
    assert [k for k in store.kv if k.startswith("ob:")] == []


def test_the_same_creation_arriving_twice_answers_once():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor()
    tg = FakeTelegramBot()
    ctx = context(store, supervisor, bot=tg, coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    first = born()
    asyncio.run(console.on_managed_created(first, ctx))
    asyncio.run(console.on_managed_updated(managed(), ctx))
    assert tg.token_calls == [NEW_ID]
    assert len(store.added) == 1 and supervisor.started == [f"bot-{NEW_ID}"]
    assert len(first.effective_message.sent) == 3 and tg.sent == []


def test_the_update_alone_registers_the_bot_and_writes_to_the_owner():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor()
    tg = FakeTelegramBot()
    ctx = context(store, supervisor, bot=tg, coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    asyncio.run(console.on_managed_updated(managed(), ctx))
    assert len(store.added) == 1 and supervisor.started == [f"bot-{NEW_ID}"]
    assert [chat for chat, _ in tg.sent] == [USER, USER, USER]
    assert all(MANAGED_TOKEN not in text for _, text in tg.sent)


def test_a_new_token_updates_the_bot_restarts_it_and_warns_the_owner():
    row = make_bot("bot-a", bot_id=NEW_ID, username=NEW_NAME)
    store = FakeStore(rows=[row], tokens={"bot-a": "vecchio"})
    supervisor = FakeSupervisor(running=["bot-a"])
    tg = FakeTelegramBot()
    asyncio.run(console.on_managed_updated(managed(), context(store, supervisor, bot=tg, user_data={})))
    assert store.added == [(USER, MANAGED_TOKEN, NEW_NAME, NEW_ID, "worker", True)]
    assert supervisor.restarted == ["bot-a"] and supervisor.started == []
    assert [chat for chat, _ in tg.sent] == [USER]
    assert IT.t("console.bot_token_changed", username=NEW_NAME, alias="bot-a") in tg.sent[0][1]
    assert MANAGED_TOKEN not in tg.sent[0][1]


def test_an_update_with_the_same_token_leaves_everything_alone():
    row = make_bot("bot-a", bot_id=NEW_ID, username=NEW_NAME)
    store = FakeStore(rows=[row], tokens={"bot-a": MANAGED_TOKEN})
    supervisor = FakeSupervisor(running=["bot-a"])
    tg = FakeTelegramBot()
    asyncio.run(console.on_managed_updated(managed(), context(store, supervisor, bot=tg, user_data={})))
    assert store.added == [] and supervisor.restarted == [] and tg.sent == []


def test_a_change_of_owner_moves_the_bot_and_warns_both():
    row = make_bot("bot-a", owner_id=42, bot_id=NEW_ID, username=NEW_NAME)
    store = FakeStore(rows=[row], tokens={"bot-a": "vecchio"})
    supervisor = FakeSupervisor(running=["bot-a"])
    tg = FakeTelegramBot()
    asyncio.run(console.on_managed_updated(managed(), context(store, supervisor, bot=tg, user_data={})))
    assert store.added[0][0] == USER and store.added[0][5] is True
    assert supervisor.restarted == ["bot-a"]
    assert [chat for chat, _ in tg.sent] == [USER, 42]


def test_a_bot_disabled_by_the_manager_is_not_woken_up_by_an_update():
    row = make_bot("bot-a", bot_id=NEW_ID, username=NEW_NAME, active=False, reason="disabled")
    store = FakeStore(rows=[row], owner=str(OWNER), tokens={"bot-a": "vecchio"})
    supervisor = FakeSupervisor()
    tg = FakeTelegramBot()
    asyncio.run(console.on_managed_updated(managed(), context(store, supervisor, bot=tg, user_data={})))
    assert store.added == [] and supervisor.restarted == [] and tg.sent == []


def test_a_bot_disabled_by_the_manager_is_not_registered_again():
    row = make_bot("bot-a", bot_id=NEW_ID, username=NEW_NAME, active=False, reason="disabled")
    row.owner_id = 42
    store = FakeStore(rows=[row], owner=str(OWNER), tokens={"bot-a": "vecchio"})
    supervisor = FakeSupervisor()
    update = born()
    asyncio.run(console.on_managed_created(update, context(store, supervisor, bot=FakeTelegramBot(), user_data={})))
    assert store.added == [] and supervisor.started == []


def test_a_bot_created_over_the_limit_is_refused_politely():
    rows = [make_bot(f"bot-{i}", bot_id=i) for i in range(3)]
    store = FakeStore(rows=rows, owner=str(OWNER))
    supervisor = FakeSupervisor()
    update = born()
    asyncio.run(console.on_managed_created(update, context(store, supervisor, bot=FakeTelegramBot(), user_data={})))
    assert store.added == [] and supervisor.started == []
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("console.newbot_limit")
    assert isinstance(markup, ReplyKeyboardRemove)


def test_the_bot_that_does_not_start_is_reported():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor(starts=False)
    ctx = context(store, supervisor, bot=FakeTelegramBot(), coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("console.newbot_not_started", username=NEW_NAME, alias=f"bot-{NEW_ID}")
    assert isinstance(markup, ReplyKeyboardRemove)


def test_a_token_telegram_refuses_to_hand_over_offers_a_retry():
    store, supervisor = FakeStore(), FakeSupervisor()
    tg = FakeTelegramBot(token_error=True)
    update = born()
    asyncio.run(console.on_managed_created(update, context(store, supervisor, bot=tg, user_data={})))
    assert store.added == [] and supervisor.started == []
    card, remove = update.effective_message.sent[0]
    assert IT.t("console.newbot_failed", username=NEW_NAME) in card
    assert isinstance(remove, ReplyKeyboardRemove)
    text, keyboard = update.effective_message.sent[1]
    assert text == IT.t("console.newbot_retry")
    button = keyboard.inline_keyboard[0][0]
    assert button.text == IT.t("console.btn_retry") and button.callback_data == f"b:retry:{NEW_ID}"
    assert store.kv[f"retry:{NEW_ID}"] == {"user_id": USER, "username": NEW_NAME}
    assert store.ttls[f"retry:{NEW_ID}"] == console.RETRY_TTL
    assert all(MANAGED_TOKEN not in text for text, _ in update.effective_message.sent)


def test_the_retry_button_finishes_the_registration():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor()
    tg = FakeTelegramBot(token_error=True)
    ctx = context(store, supervisor, bot=tg, coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    asyncio.run(console.on_managed_created(born(), ctx))
    tg.token_error = False
    update, query = pressed(f"b:retry:{NEW_ID}")
    asyncio.run(console.on_bot_callback(update, ctx))
    assert store.added == [(USER, MANAGED_TOKEN, NEW_NAME, NEW_ID, "worker", True)]
    assert supervisor.started == [f"bot-{NEW_ID}"]
    assert [chat for chat, _ in tg.sent] == [USER, USER, USER]
    assert all(MANAGED_TOKEN not in text for _, text in tg.sent)
    assert f"retry:{NEW_ID}" not in store.kv and query.answers == [(None, False)]
    code = [k for k in store.kv if k.startswith("ob:")][0].split(":", 1)[1]
    assert store.kv[f"ob:{code}"]["tag"] == TAG


def test_the_retry_button_of_somebody_else_does_nothing():
    store, supervisor = FakeStore(), FakeSupervisor()
    store.kv[f"retry:{NEW_ID}"] = {"user_id": USER, "username": NEW_NAME}
    tg = FakeTelegramBot()
    update, query = pressed(f"b:retry:{NEW_ID}", user_id=42)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor, bot=tg, user_data={})))
    assert tg.token_calls == [] and store.added == [] and supervisor.started == []
    assert query.answers == [(IT.t("console.owner_only"), True)]
    assert store.kv[f"retry:{NEW_ID}"] == {"user_id": USER, "username": NEW_NAME}


def test_a_retry_for_a_bot_nobody_asked_about_is_refused():
    store = FakeStore()
    update, query = pressed(f"b:retry:{NEW_ID}")
    asyncio.run(console.on_bot_callback(update, context(store, FakeSupervisor())))
    assert query.answers == [(IT.t("console.retry_expired"), True)]


def test_a_creation_over_the_limit_is_refused_only_once():
    rows = [make_bot(f"bot-{i}", bot_id=i) for i in range(3)]
    store = FakeStore(rows=rows, owner=str(OWNER))
    supervisor = FakeSupervisor()
    tg = FakeTelegramBot()
    ctx = context(store, supervisor, bot=tg, user_data={})
    first = born()
    asyncio.run(console.on_managed_created(first, ctx))
    asyncio.run(console.on_managed_updated(managed(), ctx))
    assert tg.token_calls == [NEW_ID] and tg.sent == []
    assert [text for text, _ in first.effective_message.sent] == [
        IT.t("console.newbot_limit")
    ]


def test_a_bot_the_owner_stopped_gets_the_new_token_but_stays_off():
    row = make_bot("bot-a", bot_id=NEW_ID, username=NEW_NAME, active=False, reason="owner_stopped")
    store = FakeStore(rows=[row], tokens={"bot-a": "vecchio"})
    supervisor = FakeSupervisor()
    tg = FakeTelegramBot()
    asyncio.run(console.on_managed_updated(managed(), context(store, supervisor, bot=tg, user_data={})))
    assert store.tokens["bot-a"] == MANAGED_TOKEN
    assert store.activated[-1] == ("bot-a", False, "owner_stopped")
    assert supervisor.restarted == [] and supervisor.started == [] and tg.sent == []


def test_a_bot_removed_from_clanboard_does_not_come_back_by_itself():
    row = make_bot("bot-a", bot_id=NEW_ID, username=NEW_NAME)
    store = FakeStore(rows=[row])
    supervisor = FakeSupervisor(running=["bot-a"])
    update, query = pressed("b:remove2:bot-a")
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert store.removed == ["bot-a"] and store.kv[f"gone:{NEW_ID}"] == {"user_id": USER}
    assert store.ttls[f"gone:{NEW_ID}"] == console.GONE_TTL
    tg = FakeTelegramBot()
    asyncio.run(console.on_managed_updated(managed(), context(store, supervisor, bot=tg, user_data={})))
    assert tg.token_calls == [] and store.added == [] and supervisor.started == [] and tg.sent == []


def test_a_deliberate_newbot_lets_a_removed_bot_be_registered_again():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor()
    store.kv[f"gone:{NEW_ID}"] = {"user_id": USER}
    tg = FakeTelegramBot()
    ctx = context(store, supervisor, bot=tg, coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    assert len(store.added) == 1 and supervisor.started == [f"bot-{NEW_ID}"]
    assert f"gone:{NEW_ID}" not in store.kv


def test_cancel_clears_the_pending_creation():
    ctx = context(FakeStore(), user_data={"newbot": {"request_id": 7}})
    update = private()
    asyncio.run(console.cmd_cancel(update, ctx))
    assert "newbot" not in ctx.user_data and last(update) == IT.t("console.cancelled")


def test_mybots_shows_state_clans_and_one_row_of_buttons_per_bot():
    rows = [make_bot("bot-a", username="Uno"), make_bot("bot-b", username="Due", bot_id=2, active=False, reason="owner_stopped")]
    store = FakeStore(rows=rows, clans=[make_clan("clan-1", 101, "bot-a")])
    supervisor = FakeSupervisor(running=["bot-a"])
    update = private()
    asyncio.run(console.cmd_mybots(update, context(store, supervisor)))
    text, keyboard = update.effective_message.sent[-1]
    assert "🟢" in text and "🔴" in text
    assert IT.t("console.reason.owner_stopped") in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data == ["b:stop:bot-a", "b:remove:bot-a", "b:start:bot-b", "b:remove:bot-b"]


def test_mybots_without_bots_invites_to_create_one():
    update = private()
    asyncio.run(console.cmd_mybots(update, context(FakeStore())))
    text, keyboard = update.effective_message.sent[-1]
    assert IT.t("console.mybots_empty") in text and keyboard is None


def test_stop_button_stops_the_bot_with_the_owner_reason():
    store = FakeStore(rows=[make_bot("bot-a")])
    supervisor = FakeSupervisor(running=["bot-a"])
    update, query = pressed("b:stop:bot-a")
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert supervisor.stopped == [("bot-a", "owner_stopped")]
    assert query.answers[-1][0] == IT.t("console.stopped", username="MioBot")
    assert "🔴" in query.edits[-1][0]


def test_start_button_reactivates_and_starts():
    store = FakeStore(rows=[make_bot("bot-a", active=False, reason="owner_stopped")])
    supervisor = FakeSupervisor()
    update, query = pressed("b:start:bot-a")
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert store.activated == [("bot-a", True, None)]
    assert supervisor.started == ["bot-a"] and "🟢" in query.edits[-1][0]


def in_clan_store(rows, role="leader", uid=USER):
    store = FakeStore(rows=rows, clans=[make_clan("clan-1", 101, "bot-a")],
                      accounts=[account(uid, LEADER_TAG)])
    store.state[("clan-1", "members")] = {LEADER_TAG: {"name": "Tizio", "role": role}}
    return store


def test_remove_asks_first_and_then_removes():
    store = in_clan_store([make_bot("bot-a")])
    supervisor = FakeSupervisor(running=["bot-a"])
    ctx = context(store, supervisor)
    update, query = pressed("b:remove:bot-a")
    asyncio.run(console.on_bot_callback(update, ctx))
    text, keyboard = query.edits[-1]
    assert IT.t("console.remove_confirm", username="MioBot", n=1) in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data == ["b:remove2:bot-a", "b:back"]
    assert store.removed == []

    update2, query2 = pressed("b:remove2:bot-a")
    asyncio.run(console.on_bot_callback(update2, ctx))
    assert supervisor.stopped == [("bot-a", None)] and store.removed == ["bot-a"]
    assert IT.t("console.removed", username="MioBot") in query2.edits[-1][0]


def test_nobody_touches_the_bot_of_another_user():
    store = FakeStore(rows=[make_bot("bot-a", owner_id=42)], owner=str(OWNER))
    supervisor = FakeSupervisor(running=["bot-a"])
    update, query = pressed("b:stop:bot-a", user_id=USER)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert supervisor.stopped == [] and query.edits == []
    assert query.answers == [(IT.t("console.owner_only"), True)]


def test_the_platform_owner_can_touch_any_bot_once_it_gave_a_reason():
    store = FakeStore(rows=[make_bot("bot-a", owner_id=42)], owner=str(OWNER),
                      clans=[make_clan("clan-a", 101, "bot-a")])
    supervisor = FakeSupervisor(running=["bot-a"])
    ctx = context(store, supervisor, user_data={})
    apre, _ = pressed(f"b:open:bot-a:{platform.OPEN_REASONS[0]}", user_id=OWNER)
    asyncio.run(console.on_bot_callback(apre, ctx))
    update, query = pressed("b:stop:bot-a", user_id=OWNER)
    asyncio.run(console.on_bot_callback(update, ctx))
    assert supervisor.stopped == [("bot-a", "owner_stopped")]


def test_a_button_of_a_bot_that_is_gone_says_so():
    update, query = pressed("b:stop:bot-zz")
    asyncio.run(console.on_bot_callback(update, context(FakeStore())))
    assert query.answers == [(IT.t("console.not_found", alias="bot-zz"), True)]


def test_support_shows_the_same_card_as_the_clan_bots():
    store = FakeStore(secrets={"support_url": "https://ko-fi.com/clanboard", "creator_code": "CLANBOARD"})
    update = private()
    asyncio.run(console.cmd_support(update, context(store)))
    assert last(update) == render.support_card(IT, "https://ko-fi.com/clanboard", "CLANBOARD")
    assert IT.t("console.attribution") in last(update)
    only_code = private()
    asyncio.run(console.cmd_support(only_code, context(FakeStore(secrets={"creator_code": "CLANBOARD"}))))
    assert last(only_code) == render.support_card(IT, None, "CLANBOARD")
    plain = private()
    asyncio.run(console.cmd_support(plain, context(FakeStore())))
    assert last(plain) == render.support_card(IT, None, None)
    outside = group()
    asyncio.run(console.cmd_support(outside, context(store)))
    assert last(outside) == IT.t("console.private_only")


def test_the_manager_commands_are_closed_to_everybody_else():
    store = FakeStore(rows=[make_bot("bot-a")], owner=str(OWNER))
    for handler in (console.cmd_bots, console.cmd_stats, console.cmd_broadcast):
        update = private(user_id=USER)
        asyncio.run(handler(update, context(store, args=["ciao"])))
        assert last(update) == IT.t("console.owner_only")
    update = private(user_id=USER)
    asyncio.run(console.cmd_disable(update, context(store, args=["bot-a"])))
    assert last(update) == IT.t("console.owner_only")


def test_bots_lists_a_page_with_owner_and_clans():
    rows = [make_bot(f"bot-{i}", owner_id=1000 + i, bot_id=i) for i in range(25)]
    store = FakeStore(rows=rows, owner=str(OWNER), clans=[make_clan("clan-1", 101, "bot-0")])
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_bots(update, context(store, FakeSupervisor(running=["bot-0"]), args=["2"])))
    text = last(update)
    assert "2/2" in text and "bot-24" in text and "bot-0<" not in text
    assert "<code>1024</code>" in text


def test_il_gestore_della_piattaforma_bandisce_col_comando():
    store = FakeStore(owner=str(OWNER), accounts=[account(4242, MEMBER_TAG)])
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_ban(update, context(store, args=["4242", "#abc"])))
    assert asyncio.run(platform_ban.refuses(store, 4242)) is True
    assert asyncio.run(platform_ban.refuses(store, 1, ["#ABC"])) is True
    assert asyncio.run(platform_ban.refuses(store, 1, [MEMBER_TAG])) is True
    assert "4242" in last(update)


def test_un_estraneo_non_bandisce_nessuno():
    store = FakeStore(owner=str(OWNER))
    update = private(user_id=USER)
    asyncio.run(console.cmd_ban(update, context(store, args=["4242"])))
    assert last(update) == IT.t("console.owner_only")
    assert asyncio.run(platform_ban.refuses(store, 4242)) is False


def test_il_bando_si_toglie_col_comando_e_un_bando_che_non_c_e_lo_dice():
    store = FakeStore(owner=str(OWNER))
    asyncio.run(platform_ban.ban(store, 4242, [], time.time()))
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_unban(update, context(store, args=["4242"])))
    assert asyncio.run(platform_ban.refuses(store, 4242)) is False
    assert "4242" in last(update)
    ancora = private(user_id=OWNER)
    asyncio.run(console.cmd_unban(ancora, context(store, args=["4242"])))
    assert last(ancora) == IT.t("console.ban_none", uid=4242)


def test_un_bando_senza_numero_dice_come_si_usa():
    store = FakeStore(owner=str(OWNER))
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_ban(update, context(store, args=["pincopallo"])))
    assert last(update) == IT.t("console.usage", usage="/ban 123456789 #TAG")
    assert asyncio.run(platform_ban.load(store))[platform_ban.ROWS] == {}


def test_disable_stops_the_bot_and_warns_the_owner():
    store = FakeStore(rows=[make_bot("bot-a", owner_id=42)], owner=str(OWNER))
    supervisor = FakeSupervisor(running=["bot-a"])
    bot = FakeTelegramBot()
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_disable(update, context(store, supervisor, args=["bot-a", "spam"], bot=bot)))
    assert store.activated == [("bot-a", False, "disabled")]
    assert supervisor.stopped == [("bot-a", None)]
    assert bot.sent and bot.sent[0][0] == 42 and "spam" in bot.sent[0][1]
    assert "bot-a" in last(update)


def test_disable_survives_an_owner_who_blocked_the_console():
    store = FakeStore(rows=[make_bot("bot-a", owner_id=42)], owner=str(OWNER))
    update = private(user_id=OWNER)
    ctx = context(store, FakeSupervisor(), args=["bot-a"], bot=FakeTelegramBot(fail=True))
    asyncio.run(console.cmd_disable(update, ctx))
    assert store.activated == [("bot-a", False, "disabled")]
    assert "bot-a" in last(update)


def test_the_disabled_notice_names_who_turns_it_back_on_and_never_points_to_the_donation_card():
    secrets = {"support_url": "https://ko-fi.com/clanboard", "creator_code": "CLANBOARD"}
    store = FakeStore(rows=[make_bot("bot-a", owner_id=42)], owner=str(OWNER), secrets=secrets)
    bot = FakeTelegramBot()
    update = private(user_id=OWNER)
    ctx = context(store, FakeSupervisor(running=["bot-a"]), args=["bot-a", "spam"], bot=bot)
    asyncio.run(console.cmd_disable(update, ctx))
    notice = bot.sent[0][1]
    body = IT.t("console.disabled_notice", username="MioBot", reason="spam")
    assert notice == render.card("⛔", console.BRAND, body)
    assert notice.endswith("\nPuò riaccenderlo solo il gestore.")
    assert "/support" not in notice and "/sostieni" not in notice
    for key in ("support.title", "support.intro", "support.donate", "support.creator", "support.none"):
        assert IT.t(key, url="https://ko-fi.com/clanboard", code="CLANBOARD") not in notice


def test_a_disabled_bot_refused_at_creation_names_who_turns_it_back_on():
    store = FakeStore(owner=str(OWNER), add_error=ValueError("disabled"), accounts=[account()])
    supervisor = FakeSupervisor()
    update = born()
    asyncio.run(console.on_managed_created(update, context(store, supervisor, bot=FakeTelegramBot(),
                                                           coc=FakeCoc(), user_data={"newbot": dict(PRONTO)})))
    assert store.added == [] and supervisor.started == []
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("console.newbot_disabled")
    assert "solo il gestore" in text and "/support" not in text
    assert isinstance(markup, ReplyKeyboardRemove)


def test_no_message_in_any_language_sends_people_in_trouble_to_support():
    for code in sorted(i18n.LANGUAGES):
        catalog = json.loads((i18n.LOCALE_DIR / f"{code}.json").read_text(encoding="utf-8"))
        for key, value in catalog.items():
            for text in (value.values() if isinstance(value, dict) else [value]):
                assert "/support" not in text and "/sostieni" not in text, (code, key)


def test_enable_puts_the_bot_back_on():
    store = FakeStore(rows=[make_bot("bot-a", active=False, reason="disabled")], owner=str(OWNER))
    supervisor = FakeSupervisor()
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_enable(update, context(store, supervisor, args=["bot-a"])))
    assert store.activated == [("bot-a", True, None)] and supervisor.started == ["bot-a"]


def test_an_unknown_alias_is_reported():
    store = FakeStore(owner=str(OWNER))
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_enable(update, context(store, args=["bot-zz"])))
    assert last(update) == IT.t("console.not_found", alias="bot-zz")


def test_stats_counts_bots_clans_families_and_linked_accounts():
    rows = [make_bot("bot-a"), make_bot("bot-b", bot_id=2, active=False)]
    store = FakeStore(rows=rows, owner=str(OWNER), links=12)
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(update, context(store, FakeSupervisor(running=["bot-a"]), coc=FakeCoc())))
    assert IT.t("console.stats", bots=2, active=1, running=1, clans=3, clans_active=2, families=1) in last(update)
    assert IT.t("console.stats_links", n=12) in last(update)
    assert IT.t("console.stats_keys", alive=1, total=1) in last(update)


def stats_of(store):
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(update, context(store, coc=FakeCoc())))
    return last(update)


def test_stats_says_the_restore_test_never_ran():
    text = stats_of(FakeStore(owner=str(OWNER)))
    assert IT.t("console.stats_restore_never") in text
    assert IT.t("console.stats_restore_ok", when="") not in text


def test_stats_says_when_the_restore_test_passed():
    store = FakeStore(owner=str(OWNER))
    at = time.time() - 2 * 86400
    store.kv[manager_alerts.key_of("restore")] = {"history": [{"ok": False, "at": at - 86400},
                                                              {"ok": True, "at": at}]}
    assert IT.t("console.stats_restore_ok", when=IT.ago(manager_alerts.moment(at))) in stats_of(store)


def test_stats_says_when_the_restore_test_failed():
    store = FakeStore(owner=str(OWNER))
    at = time.time() - 3600
    store.kv[manager_alerts.key_of("restore")] = {"history": [{"ok": False, "at": at}]}
    text = stats_of(store)
    assert IT.t("console.stats_restore_ko", when=IT.ago(manager_alerts.moment(at))) in text
    assert IT.t("console.stats_restore_never") not in text


def test_broadcast_previews_only_the_clans_of_running_bots():
    clans = [make_clan("clan-1", 101, "bot-a"), make_clan("clan-2", 202, "bot-b")]
    store = FakeStore(owner=str(OWNER), clans=clans)
    store.state[("clan-1", "settings")] = {"news": True}
    store.state[("clan-2", "settings")] = {"news": True}
    ctx = context(store, FakeSupervisor(running=["bot-a"]), args=["Domani", "si", "parte"])
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_broadcast(update, ctx))
    text, keyboard = update.effective_message.sent[-1]
    assert ctx.user_data["broadcast"] == "Domani si parte"
    assert IT.t("console.broadcast_preview", n=1) in text and "Domani si parte" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data == ["bc:send", "bc:cancel"]


def test_broadcast_usage_when_the_text_is_missing():
    store = FakeStore(owner=str(OWNER))
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_broadcast(update, context(store, args=[])))
    assert last(update) == IT.t("console.broadcast_usage")


def test_broadcast_sends_in_the_language_of_each_clan_and_skips_stopped_bots(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    clans = [make_clan("clan-1", 101, "bot-a"), make_clan("clan-2", 202, "bot-b"), make_clan("clan-3", 303, "bot-a")]
    store = FakeStore(owner=str(OWNER), clans=clans)
    store.state[("clan-1", "settings")] = {"lang": "en", "news": True}
    store.state[("clan-2", "settings")] = {"news": True}
    store.state[("clan-3", "settings")] = {"lang": "it", "news": True}
    worker = FakeTelegramBot()
    supervisor = FakeSupervisor(running=["bot-a"], bots={"bot-a": worker})
    ctx = context(store, supervisor, user_data={"broadcast": "Manutenzione alle 3"})
    update, query = pressed("bc:send", user_id=OWNER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert [chat for chat, _ in worker.sent] == [101, 303]
    assert EN.t("console.broadcast_title") in worker.sent[0][1]
    assert IT.t("console.broadcast_title") in worker.sent[1][1]
    assert "Manutenzione alle 3" in worker.sent[0][1]
    assert IT.t("console.broadcast_sent", sent=2, failed=0) in query.edits[-1][0]
    assert "broadcast" not in ctx.user_data


def test_broadcast_counts_the_clans_that_refuse_the_message(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    store = FakeStore(owner=str(OWNER), clans=[make_clan("clan-1", 101, "bot-a")])
    store.state[("clan-1", "settings")] = {"news": True}
    supervisor = FakeSupervisor(running=["bot-a"], bots={"bot-a": FakeTelegramBot(fail=True)})
    ctx = context(store, supervisor, user_data={"broadcast": "Ciao"})
    update, query = pressed("bc:send", user_id=OWNER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert IT.t("console.broadcast_sent", sent=0, failed=1) in query.edits[-1][0]


def test_broadcast_skips_the_groups_that_never_asked_for_news(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    store = FakeStore(owner=str(OWNER), clans=[make_clan("clan-1", 101, "bot-a")])
    worker = FakeTelegramBot()
    supervisor = FakeSupervisor(running=["bot-a"], bots={"bot-a": worker})
    ctx = context(store, supervisor, user_data={"broadcast": "Novità"})
    update, query = pressed("bc:send", user_id=OWNER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert worker.sent == []
    assert IT.t("console.broadcast_sent", sent=0, failed=0) in query.edits[-1][0]


def test_broadcast_cancel_drops_the_text():
    store = FakeStore(owner=str(OWNER))
    ctx = context(store, user_data={"broadcast": "Ciao"})
    update, query = pressed("bc:cancel", user_id=OWNER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert "broadcast" not in ctx.user_data
    assert IT.t("console.cancelled") in query.edits[-1][0]


def test_only_the_manager_can_press_send():
    store = FakeStore(owner=str(OWNER), clans=[make_clan("clan-1", 101, "bot-a")])
    worker = FakeTelegramBot()
    supervisor = FakeSupervisor(running=["bot-a"], bots={"bot-a": worker})
    ctx = context(store, supervisor, user_data={"broadcast": "Ciao"})
    update, query = pressed("bc:send", user_id=USER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert worker.sent == [] and query.answers == [(IT.t("console.owner_only"), True)]
    assert ctx.user_data["broadcast"] == "Ciao"


def test_a_bot_disabled_by_the_manager_has_no_start_button():
    rows = [make_bot("bot-a", active=False, reason="disabled")]
    store = FakeStore(rows=rows)
    update = private()
    asyncio.run(console.cmd_mybots(update, context(store, FakeSupervisor())))
    text, keyboard = update.effective_message.sent[-1]
    assert IT.t("console.reason.disabled") in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data == ["b:remove:bot-a"]


def test_the_owner_cannot_restart_a_bot_disabled_by_the_manager():
    store = FakeStore(rows=[make_bot("bot-a", active=False, reason="disabled")], owner=str(OWNER))
    supervisor = FakeSupervisor()
    update, query = pressed("b:start:bot-a")
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert store.activated == [] and supervisor.started == []
    assert query.answers == [(IT.t("console.reason.disabled"), True)]


def test_the_manager_can_restart_a_bot_he_disabled():
    store = FakeStore(rows=[make_bot("bot-a", owner_id=OWNER, active=False, reason="disabled")], owner=str(OWNER))
    supervisor = FakeSupervisor()
    update, query = pressed("b:start:bot-a", user_id=OWNER)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert store.activated == [("bot-a", True, None)] and supervisor.started == ["bot-a"]


def test_back_redraws_the_card_of_whoever_pressed_it():
    store = FakeStore(rows=[make_bot("bot-a"), make_bot("bot-z", owner_id=42, bot_id=9)])
    update, query = pressed("b:back")
    asyncio.run(console.on_bot_callback(update, context(store, FakeSupervisor(running=["bot-a"]))))
    text, keyboard = query.edits[-1]
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data == ["b:stop:bot-a", "b:remove:bot-a"]
    assert query.answers == [(None, False)]


def test_the_paste_the_token_road_is_gone():
    assert not hasattr(console, "NEWBOT_TOKEN_RE")
    assert not hasattr(console, "on_private_text")


def test_register_wires_every_command_and_the_managed_bot_updates():
    class FakeApp:
        def __init__(self):
            self.handlers = []

        def add_handler(self, handler):
            self.handlers.append(handler)

    app = FakeApp()
    console.register(app)
    commands = set()
    patterns = set()
    for handler in app.handlers:
        commands |= set(getattr(handler, "commands", []) or [])
        pattern = getattr(handler, "pattern", None)
        if pattern is not None:
            patterns.add(pattern.pattern)
    assert {"start", "help", "newbot", "mybots", "support", "cancel", "annulla", "bots", "disable",
            "enable", "ban", "unban", "stats", "broadcast", "pannello", "panel"} <= commands
    assert patterns == {"^b:", "^bc:", "^cfg:", "^home:", "^panel:", "^tos:"}
    assert any(isinstance(h, ManagedBotUpdatedHandler) for h in app.handlers)
    messages = [h for h in app.handlers if isinstance(h, MessageHandler)]
    assert len(messages) == 2
    assert messages[0].filters == filters.StatusUpdate.MANAGED_BOT_CREATED
    assert messages[0].callback is console.on_managed_created
    assert messages[1].callback is console.on_newbot_text
    assert str(messages[1].filters) == str(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE)


def test_a_failed_token_fetch_offers_one_retry_even_if_the_twin_event_arrives():
    store = FakeStore()
    supervisor = FakeSupervisor()
    tg = FakeTelegramBot()
    tg.token_error = True
    ctx = context(store, supervisor, bot=tg, user_data={})
    asyncio.run(console.on_managed_created(born(), ctx))
    asyncio.run(console.on_managed_updated(managed(), ctx))
    assert len(tg.token_calls) == 1
    assert store.kv.get(f"managed:{NEW_ID}")
    assert store.kv.get(f"retry:{NEW_ID}")


def test_newbot_without_the_permission_to_create_says_come_back_later():
    tg, coc = FakeTelegramBot(can_manage_bots=False), FakeCoc()
    ctx = context(FakeStore(), coc=coc, bot=tg, args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert tg.me_calls == 1 and coc.asked == []
    text, markup = update.effective_message.sent[-1]
    assert len(update.effective_message.sent) == 1
    assert text == IT.t("console.newbot_unavailable")
    assert isinstance(markup, ReplyKeyboardRemove)
    assert "BotFather" not in text and "can_manage_bots" not in text
    assert "newbot" not in ctx.user_data


def test_a_keyboard_telegram_refuses_still_answers_the_user():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(), bot=FakeTelegramBot(), args=[TAG])
    update = private(refuse_keyboard=True)
    asyncio.run(console.cmd_newbot(update, ctx))
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("console.newbot_unavailable")
    assert isinstance(markup, ReplyKeyboardRemove)
    assert "newbot" not in ctx.user_data


def test_the_permission_is_asked_once_and_looked_at_again_later():
    tg = FakeTelegramBot()
    ctx = context(FakeStore(), coc=FakeCoc(), bot=tg)
    asyncio.run(console.cmd_newbot(private(), ctx))
    asyncio.run(console.cmd_newbot(private(), ctx))
    assert tg.me_calls == 1
    when, allowed = ctx.bot_data["can_manage"]
    ctx.bot_data["can_manage"] = (when - console.MANAGER_TTL, allowed)
    tg.can_manage_bots = False
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert tg.me_calls == 2
    assert last(update) == IT.t("console.newbot_unavailable")


def test_a_console_that_cannot_ask_telegram_still_offers_the_button():
    tg = FakeTelegramBot(me_error=TelegramError("rete"))
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(), bot=tg, args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert request_of(update).request_managed_bot.request_id == ctx.user_data["newbot"]["request_id"]


def test_a_registration_that_breaks_halfway_offers_a_retry_and_no_orphan():
    store = FakeStore(add_error=RuntimeError("database giù"), accounts=[account()])
    supervisor = FakeSupervisor()
    tg = FakeTelegramBot()
    ctx = context(store, supervisor, bot=tg, coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    assert supervisor.started == [] and f"managed:{NEW_ID}" not in store.kv
    assert store.kv[f"retry:{NEW_ID}"] == {"user_id": USER, "username": NEW_NAME}
    card, remove = update.effective_message.sent[0]
    assert IT.t("console.newbot_failed", username=NEW_NAME) in card
    assert isinstance(remove, ReplyKeyboardRemove)
    text, keyboard = update.effective_message.sent[1]
    assert text == IT.t("console.newbot_retry")
    assert keyboard.inline_keyboard[0][0].callback_data == f"b:retry:{NEW_ID}"
    assert all(MANAGED_TOKEN not in text for text, _ in update.effective_message.sent)
    store.add_error = None
    retried, query = pressed(f"b:retry:{NEW_ID}")
    asyncio.run(console.on_bot_callback(retried, ctx))
    assert store.added == [(USER, MANAGED_TOKEN, NEW_NAME, NEW_ID, "worker", True)]
    assert supervisor.started == [f"bot-{NEW_ID}"] and query.answers == [(None, False)]


def test_without_a_saved_reminder_there_is_no_retry_button():
    store = FakeStore(kv_error=("",))
    tg = FakeTelegramBot(token_error=True)
    update = born()
    asyncio.run(console.on_managed_created(update, context(store, FakeSupervisor(), bot=tg, user_data={})))
    assert store.kv == {}
    assert len(update.effective_message.sent) == 1
    card, remove = update.effective_message.sent[0]
    assert IT.t("console.newbot_failed", username=NEW_NAME) in card
    assert isinstance(remove, ReplyKeyboardRemove)


def test_a_group_code_that_cannot_be_saved_leaves_a_plain_invite():
    store = FakeStore(kv_error=("ob:",), accounts=[account()])
    supervisor = FakeSupervisor()
    ctx = context(store, supervisor, bot=FakeTelegramBot(), coc=FakeCoc(),
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN}})
    update = born()
    asyncio.run(console.on_managed_created(update, ctx))
    assert len(store.added) == 1 and supervisor.started == [f"bot-{NEW_ID}"]
    keyboard = update.effective_message.sent[-1][1]
    assert keyboard.inline_keyboard[0][0].url == f"https://t.me/{NEW_NAME}?startgroup=true"
    assert [k for k in store.kv if k.startswith("ob:")] == []


def test_a_retry_on_an_already_registered_bot_answers_and_starts_it():
    row = make_bot("bot-nuovo", bot_id=NEW_ID, username=NEW_NAME)
    store = FakeStore(rows=[row])
    store.kv[f"retry:{NEW_ID}"] = {"user_id": USER, "username": NEW_NAME}
    store.tokens[row.alias] = MANAGED_TOKEN
    supervisor = FakeSupervisor()
    tg = FakeTelegramBot()
    update, query = pressed(f"b:retry:{NEW_ID}")
    asyncio.run(console.on_bot_callback(update, context(store, supervisor, bot=tg, user_data={})))
    assert supervisor.started == ["bot-nuovo"]
    assert any(NEW_NAME in text for _, text in tg.sent)


def test_the_manager_off_notice_walks_through_the_botfather_mini_app():
    for code in i18n.LANGUAGES:
        text = i18n.locale(code).t("console.manager_off")
        assert MINI_APP in text, code
        assert "Bot Management Mode" in text, code
        assert "/stats" in text, code
        assert "getMe" not in text and "token" not in text.lower(), code
        assert "Bot Settings" not in text and "/mybots" not in text, code


def test_newbot_follows_the_button_with_a_link_for_iphone():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    sent = update.effective_message.sent
    assert len(sent) == 2
    (ask, keyboard), (hint, inline) = sent
    assert IT.t("console.newbot_ask_native") in ask and isinstance(keyboard, ReplyKeyboardMarkup)
    assert hint == IT.t("console.newbot_link_hint", button=IT.t("console.btn_create"))
    assert isinstance(inline, InlineKeyboardMarkup)
    button = inline.inline_keyboard[0][0]
    assert button.text == IT.t("console.btn_create_link")
    assert button.url == f"https://t.me/newbot/{CONSOLE_NAME}/FuturoGuerrieriBot?name=Futuro%20Guerrieri"
    assert request_of(update).request_managed_bot.suggested_username == "FuturoGuerrieriBot"


def test_the_link_encodes_every_odd_character_of_the_clan_name():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(name="Città & Guerrieri?"), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    expected = f"https://t.me/newbot/{CONSOLE_NAME}/CittGuerrieriBot?name=Citt%C3%A0%20%26%20Guerrieri%3F"
    assert link_of(update).url == expected


def test_a_clan_without_latin_letters_still_gives_the_link_a_valid_username():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(name="部落"), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    url = link_of(update).url
    prefix = f"https://t.me/newbot/{CONSOLE_NAME}/"
    assert url.startswith(prefix)
    username = url[len(prefix):].split("?")[0]
    assert re.fullmatch(r"ClanBoard\d{4}Bot", username)
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]*Bot", username) and 5 <= len(username) <= 32
    assert request_of(update).request_managed_bot.suggested_username == username


def test_the_generic_username_is_always_valid_for_telegram():
    for _ in range(200):
        username = console.generic_username()
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]*Bot", username)
        assert 5 <= len(username) <= 32


def test_the_pending_creation_is_ready_before_the_button_and_the_link_arrive():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(), args=[TAG])
    update = private()
    seen = []
    original = update.effective_message.reply_text

    async def spy(text, reply_markup=None, **kw):
        seen.append(dict(ctx.user_data.get("newbot") or {}))
        return await original(text, reply_markup=reply_markup, **kw)

    update.effective_message.reply_text = spy
    asyncio.run(console.cmd_newbot(update, ctx))
    assert len(seen) == 2
    assert all(flow.get("tag") == TAG and flow.get("request_id") for flow in seen)


def test_a_bot_born_from_the_link_is_registered_and_pre_linked_like_the_button():
    store, supervisor = FakeStore(accounts=[account()]), FakeSupervisor()
    ctx = context(store, supervisor, coc=FakeCoc(), args=[TAG])
    asyncio.run(console.cmd_newbot(private(), ctx))
    asyncio.run(console.on_managed_updated(managed(), ctx))
    assert store.added == [(USER, MANAGED_TOKEN, NEW_NAME, NEW_ID, "worker", True)]
    assert supervisor.started == [f"bot-{NEW_ID}"]
    codes = [dict(value) for key, value in store.kv.items() if key.startswith("ob:")]
    assert [code.pop("setup")["step"] for code in codes] == ["preset"]
    assert codes == [{"tag": TAG, "name": CLAN, "user_id": USER, "bot_alias": f"bot-{NEW_ID}"}]
    assert all(MANAGED_TOKEN not in text for _, text in ctx.bot.sent)


class UninitializedTelegramBot(FakeTelegramBot):
    @property
    def username(self):
        raise RuntimeError("bot non inizializzato")

    @username.setter
    def username(self, value):
        pass


def test_a_console_that_does_not_know_its_username_still_leaves_the_button_working(caplog):
    tg = UninitializedTelegramBot()
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(), args=[TAG], bot=tg)
    update = private()
    with caplog.at_level(logging.WARNING, logger="clashbot.console"):
        asyncio.run(console.cmd_newbot(update, ctx))
    sent = update.effective_message.sent
    assert len(sent) == 1 and isinstance(sent[0][1], ReplyKeyboardMarkup)
    assert ctx.user_data["newbot"]["tag"] == TAG
    assert "link" in caplog.text and "RuntimeError" in caplog.text
    assert "non inizializzato" not in caplog.text


def test_a_link_telegram_refuses_leaves_the_button_working(caplog):
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc(), args=[TAG])
    update = private(refuse_link=True)
    with caplog.at_level(logging.WARNING, logger="clashbot.console"):
        asyncio.run(console.cmd_newbot(update, ctx))
    sent = update.effective_message.sent
    assert len(sent) == 1 and isinstance(sent[0][1], ReplyKeyboardMarkup)
    assert ctx.user_data["newbot"]["tag"] == TAG
    assert "link" in caplog.text


def test_stats_says_bot_creation_is_active():
    store = FakeStore(owner=str(OWNER))
    tg = FakeTelegramBot()
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(update, context(store, bot=tg)))
    assert IT.t("console.stats_creation_on") in last(update)
    assert IT.t("console.stats_creation_off") not in last(update)
    assert tg.me_calls == 1


def test_stats_says_bot_creation_is_off_and_names_the_switch():
    store = FakeStore(owner=str(OWNER))
    tg = FakeTelegramBot(can_manage_bots=False)
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(update, context(store, bot=tg)))
    assert IT.t("console.stats_creation_off") in last(update)
    assert IT.t("console.stats_creation_on") not in last(update)
    assert IT.t("console.stats_creation_unknown") not in last(update)
    for code in i18n.LANGUAGES:
        text = i18n.locale(code).t("console.stats_creation_off")
        assert "Bot Management Mode" in text and MINI_APP in text, code


def test_stats_asks_telegram_again_and_refreshes_what_newbot_remembers():
    store = FakeStore(owner=str(OWNER))
    tg = FakeTelegramBot(can_manage_bots=False)
    ctx = context(store, coc=FakeCoc(), bot=tg)
    ctx.bot_data["can_manage"] = (time.monotonic(), True)
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(update, ctx))
    assert tg.me_calls == 1
    assert IT.t("console.stats_creation_off") in last(update)
    assert ctx.bot_data["can_manage"][1] is False
    later = private(user_id=OWNER)
    asyncio.run(console.cmd_newbot(later, ctx))
    assert tg.me_calls == 1 and last(later) == IT.t("console.manager_off")
    tg.can_manage_bots = True
    again = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(again, ctx))
    assert tg.me_calls == 2 and ctx.bot_data["can_manage"][1] is True
    assert IT.t("console.stats_creation_on") in last(again)


def test_stats_of_somebody_else_never_asks_telegram():
    tg = FakeTelegramBot()
    update = private()
    asyncio.run(console.cmd_stats(update, context(FakeStore(owner=str(OWNER)), bot=tg)))
    assert tg.me_calls == 0 and last(update) == IT.t("console.owner_only")


def test_a_fresh_check_that_fails_answers_unknown_while_newbot_stays_optimistic():
    tg = FakeTelegramBot(can_manage_bots=False, me_error=TimedOut("x"))
    ctx = context(FakeStore(), bot=tg)
    assert asyncio.run(console.can_manage(ctx, fresh=True)) is None
    assert "can_manage" not in ctx.bot_data
    assert asyncio.run(console.can_manage(ctx)) is True
    assert "can_manage" not in ctx.bot_data
    remembered = (time.monotonic() - console.MANAGER_TTL - 1, False)
    ctx.bot_data["can_manage"] = remembered
    assert asyncio.run(console.can_manage(ctx, fresh=True)) is None
    assert asyncio.run(console.can_manage(ctx)) is False
    assert ctx.bot_data["can_manage"] == remembered
    assert tg.me_calls == 4


def test_stats_does_not_guess_when_telegram_does_not_answer():
    store = FakeStore(owner=str(OWNER))
    tg = FakeTelegramBot(can_manage_bots=False, me_error=TimedOut("x"))
    ctx = context(store, bot=tg)
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(update, ctx))
    text = last(update)
    assert IT.t("console.stats_creation_unknown") in text
    assert IT.t("console.stats_creation_on") not in text
    assert IT.t("console.stats_creation_off") not in text
    assert "can_manage" not in ctx.bot_data
    assert tg.me_calls == 1


def test_stats_without_an_answer_keeps_what_newbot_remembers():
    store = FakeStore(owner=str(OWNER))
    tg = FakeTelegramBot(can_manage_bots=False, me_error=TimedOut("x"))
    ctx = context(store, bot=tg)
    remembered = (time.monotonic(), True)
    ctx.bot_data["can_manage"] = remembered
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_stats(update, ctx))
    assert IT.t("console.stats_creation_unknown") in last(update)
    assert IT.t("console.stats_creation_on") not in last(update)
    assert ctx.bot_data["can_manage"] is remembered


def test_the_unknown_creation_line_tells_the_owner_to_ask_again():
    for code in i18n.LANGUAGES:
        text = i18n.locale(code).t("console.stats_creation_unknown")
        assert "/stats" in text, code
        assert text not in (i18n.locale(code).t("console.stats_creation_on"), i18n.locale(code).t("console.stats_creation_off"))


def test_newbot_without_the_permission_tells_the_platform_owner_how_to_turn_it_on():
    tg, coc = FakeTelegramBot(can_manage_bots=False), FakeCoc()
    ctx = context(FakeStore(owner=str(OWNER)), coc=coc, bot=tg, args=[TAG])
    update = private(OWNER)
    asyncio.run(console.cmd_newbot(update, ctx))
    assert len(update.effective_message.sent) == 1
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("console.manager_off")
    assert MINI_APP in text and "Bot Management Mode" in text
    assert isinstance(markup, ReplyKeyboardRemove)
    assert "newbot" not in ctx.user_data


SAMPLE_ROWS = (
    {"ts": 1000, "containers": {"clashbot": {"mem_mb": 100, "cpu": 0.1}}},
    {"ts": 2000, "containers": {"clashbot": {"mem_mb": 900, "cpu": 2.4}}},
    {"ts": 3000, "containers": {"clashbot": {"mem_mb": 300, "cpu": 0.2}},
     "backup_age_h": 5, "retention": "ok"},
    {"ts": 3100, "alert": "bot oltre 2 core"},
)


def write_samples(tmp_path, rows=SAMPLE_ROWS):
    path = tmp_path / "samples.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def fresh_samples(tmp_path, now):
    rows = (
        {"ts": now - 7200, "containers": {"clashbot": {"mem_mb": 900, "cpu": 2.4},
                                          "clashbot-db": {"mem_mb": 40, "cpu": 0.05}}},
        {"ts": now - 600, "containers": {"clashbot": {"mem_mb": 300, "cpu": 0.2},
                                         "clashbot-db": {"mem_mb": 44, "cpu": 0.01}},
         "backup_age_h": 5, "retention": "ok"},
        {"ts": now - 300, "alert": "clashbot: 2100 MB, oltre 2 GB"},
    )
    return write_samples(tmp_path, rows)


class ConsoleApp:
    def __init__(self, store=None, supervisor=None, coc=None):
        self.owner_id = OWNER
        self.store = store if store is not None else panel_store()
        self.context = context(self.store, supervisor, coc=coc)
        self.updates = []

    def update_from(self, user_id, text=""):
        update = private(user_id=user_id, text=text)
        self.updates.append(update)
        return update, self.context

    @property
    def replies(self):
        return [text for update in self.updates for text, _ in update.effective_message.sent]


def panel_store(lang="it"):
    rows = [make_bot("bot-a", owner_id=OWNER, username="Uno"),
            make_bot("bot-b", owner_id=OWNER, username="Due", bot_id=2, active=False, reason="flood")]
    store = FakeStore(rows=rows, owner=str(OWNER), secrets={"owner_lang": lang},
                      clans=[make_clan("clan-1", 101, "bot-a")])
    store.kv[platform_guard.STATE_KEY] = {"sent": {"clan-1": 10, "clan-2": 2},
                                          "delayed": {"clan-1": 3}, "dropped": {"clan-1": 1}}
    return store


def key_pool(alive=2, dead=1, per_minute=7):
    return SimpleNamespace(keys=["k"] * (alive + dead), keys_alive=lambda: alive,
                           calls_per_minute=lambda: per_minute)


def test_metrics_reads_the_last_sample_the_peaks_and_the_alerts(tmp_path):
    samples = metrics.read_samples(write_samples(tmp_path))
    assert metrics.latest(samples)["containers"]["clashbot"]["mem_mb"] == 300
    assert metrics.peaks(samples, now=3200)["clashbot"] == {"mem_mb": 900, "cpu": 2.4}
    assert metrics.alerts(samples, now=3200) == ["bot oltre 2 core"]
    assert metrics.read_samples(tmp_path / "manca.jsonl") == []
    assert metrics.latest([]) is None


def test_metrics_looks_only_at_the_last_twenty_four_hours(tmp_path):
    samples = metrics.read_samples(write_samples(tmp_path))
    assert metrics.peaks(samples, now=3000 + 24 * 3600)["clashbot"] == {"mem_mb": 300, "cpu": 0.2}
    assert metrics.alerts(samples, now=3100 + 24 * 3600) == ["bot oltre 2 core"]
    assert metrics.peaks(samples, now=3100 + 24 * 3600 + 1) == {}
    assert metrics.alerts(samples, now=3100 + 24 * 3600 + 1) == []


def test_metrics_steps_over_the_broken_lines(tmp_path):
    path = tmp_path / "samples.jsonl"
    path.write_text('{"ts": 1000, "containers": {}}\nmezza riga\n\n{"ts": 2000, "alert": "giù"}\n',
                    encoding="utf-8")
    samples = metrics.read_samples(path)
    assert len(samples) == 2
    assert metrics.latest(samples)["ts"] == 1000
    assert metrics.alerts(samples, now=2000) == ["giù"]


def test_the_panel_is_only_for_the_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(write_samples(tmp_path)))
    app = ConsoleApp(coc=key_pool())
    update, ctx = app.update_from(user_id=42, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert "solo" in app.replies[-1].lower()
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert "PANNELLO" in app.replies[-1]


def test_the_panel_shows_bots_keys_messages_containers_and_alarms(monkeypatch, tmp_path):
    now = int(time.time())
    monkeypatch.setattr(metrics, "SAMPLES", str(fresh_samples(tmp_path, now)))
    app = ConsoleApp(supervisor=FakeSupervisor(running=["bot-a"]), coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    text, keyboard = update.effective_message.sent[-1]
    assert IT.t("panel.title") in text
    assert IT.t("platform.bots", running=1, total=2) in text
    assert IT.t("platform.error_line", name="Due", reason=IT.t("console.reason.flood")) in text
    assert IT.t("platform.clans", n=2, total=3) in text
    assert IT.t("panel.keys", alive=2, dead=1) in text and IT.t("panel.api", calls="7") in text
    assert IT.t("panel.sends", sent="12", delayed="3", dropped="1") in text
    assert IT.t("panel.container_peak", name="clashbot", mem="300", cpu="0,20",
                peak_mem="900", peak_cpu="2,40") in text
    assert IT.t("panel.container_peak", name="clashbot-db", mem="44", cpu="0,01",
                peak_mem="44", peak_cpu="0,05") in text
    assert IT.t("panel.backup", n=5) in text and IT.t("panel.retention.ok") in text
    assert IT.t("panel.alerts") in text and "clashbot: 2100 MB, oltre 2 GB" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data == ["panel:refresh", "panel:bots", "panel:reports", "panel:seats", "panel:ops",
                    "panel:delegates", "panel:usage", "panel:otp", "panel:media", "panel:site"]


def test_the_panel_without_samples_still_counts_what_the_bot_knows(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(supervisor=FakeSupervisor(running=["bot-a"]), coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    text = last(update)
    assert IT.t("panel.no_samples") in text
    assert IT.t("panel.backup_unknown") in text
    assert IT.t("panel.quiet") in text
    assert IT.t("panel.sends", sent="12", delayed="3", dropped="1") in text


def test_the_panel_speaks_the_language_of_the_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(store=panel_store(lang="en"), coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert EN.t("panel.title") in last(update)
    assert IT.t("panel.title") not in last(update)


def test_the_panel_without_clash_keys_does_not_break(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp()
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert IT.t("panel.keys", alive=0, dead=0) in last(update)
    assert IT.t("panel.api", calls="0") in last(update)


def test_the_panel_sums_the_survey_of_every_clan(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    store.clans.append(make_clan("clan-2", 202, "bot-a"))
    store.state[("clan-1", survey.STATE)] = {"sent": 1000,
                                             "counts": {"great": 3, "good": 1, "meh": 0, "no": 1}}
    store.state[("clan-2", survey.STATE)] = {"sent": 1000,
                                             "counts": {"great": 2, "good": 2, "meh": 1, "no": 0}}
    app = ConsoleApp(store=store, coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert IT.t("panel.survey", great="5", good="3", meh="1", no="1", n=2) in last(update)


def test_the_panel_says_zero_while_nobody_answered_the_survey(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert IT.t("panel.survey", great="0", good="0", meh="0", no="0", n=0) in last(update)


def test_the_panel_buttons_redraw_it_and_open_the_list_of_bots(monkeypatch, tmp_path):
    now = int(time.time())
    monkeypatch.setattr(metrics, "SAMPLES", str(fresh_samples(tmp_path, now)))
    app = ConsoleApp(supervisor=FakeSupervisor(running=["bot-a"]), coc=key_pool())
    update, query = pressed("panel:refresh", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.title") in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        "panel:refresh", "panel:bots", "panel:reports", "panel:seats", "panel:ops",
        "panel:delegates", "panel:usage", "panel:otp", "panel:media", "panel:site"]
    update, query = pressed("panel:bots", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("console.bots_title", n=2) in text and "bot-a" in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == ["panel:refresh"]


MEGA = 1024 * 1024
GIGA = 1024 * MEGA


def ops_store(now, lang="it"):
    store = panel_store(lang)
    store.db_bytes = 3 * GIGA
    store.intent_age = 12.0
    store.kv[selfmetrics.BOT_KEY] = {"ts": now, "mem_bytes": 2600 * MEGA, "mem_limit": 3 * GIGA,
                                     "cpu_cores": 0.25, "load1": 1.5,
                                     "host_mem_available": 900 * MEGA, "uptime_s": 5000.0}
    store.kv[selfmetrics.WEB_KEY] = {"ts": now, "mem_bytes": 120 * MEGA, "mem_limit": 256 * MEGA,
                                     "cpu_cores": 0.02, "uptime_s": 4000.0}
    store.kv[selfmetrics.POLL_KEY] = {"took": 45.0, "interval": 60, "clans": 3, "at": now}
    store.kv[selfmetrics.PROBE_KEY] = {"ok": True, "ms": 120, "status": 200, "at": now}
    store.kv[manager_alerts.key_of(key_watch.KIND)] = {
        "sig": "ok:3", "sent": True,
        "history": [{"alive": 3, "total": 3, "dead": [], "at": now - 3600}]}
    store.kv[manager_alerts.key_of(ops.KIND)] = {
        "sig": "poll_slow", "sent": True, "history": [{"keys": ["poll_slow"], "at": now - 7200}]}
    return store


def test_il_quadro_ops_non_esiste_per_chi_non_e_il_gestore(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(coc=key_pool())
    update, ctx = app.update_from(user_id=42, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    testo = app.replies[-1]
    assert IT.t("ops.btn") not in testo and IT.t("ops.title") not in testo
    update, query = pressed("panel:ops", user_id=42)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert query.edits == []
    assert query.answers[-1] == (IT.t("console.owner_only"), True)


def test_il_quadro_ops_mostra_al_gestore_i_numeri_del_quadro(monkeypatch, tmp_path):
    now = time.time()
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    monkeypatch.setattr(publish.RECENT, "rows", [])
    app = ConsoleApp(store=ops_store(now), coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    bottoni = [b for row in update.effective_message.sent[-1][1].inline_keyboard for b in row]
    assert ("panel:ops", IT.t("ops.btn")) in [(b.callback_data, b.text) for b in bottoni]
    update, query = pressed("panel:ops", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("ops.title") in text
    assert "🔴 " + IT.t("ops.bot", mem="2.600", limit="2.048", cpu="0,25", cpu_limit="2") in text
    assert "🟢 " + IT.t("ops.web", mem="120", limit="256", cpu="0,02") in text
    assert "🟢 " + IT.t("ops.host", load="1,50", mem="900") in text
    assert "🟢 " + IT.t("ops.db", mem="3.072") in text
    assert "🟡 " + IT.t("ops.dump", n="?") in text
    assert "🟢 " + IT.t("ops.poll", n="45", limit="60", clans="3") in text
    assert "🟢 " + IT.t("ops.intents", n="12", limit="600") in text
    assert "🟢 " + IT.t("ops.errors", n="0", limit="100", window="3.600") in text
    assert "🟢 " + IT.t("ops.probe", n="120") in text
    assert "🟢 " + IT.t("ops.keys", n="3", limit="3") in text
    assert IT.t("ops.alerts") in text and "poll_slow" in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        "panel:banned", "panel:incidents", "panel:refresh"]


def test_il_quadro_ops_dice_giallo_dove_la_misura_manca(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    monkeypatch.setattr(publish.RECENT, "rows", [])
    app = ConsoleApp(coc=key_pool())
    update, query = pressed("panel:ops", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text = query.edits[-1][0]
    assert "🟡 " + IT.t("ops.bot", mem="?", limit="2.048", cpu="?", cpu_limit="2") in text
    assert "🟡 " + IT.t("ops.db", mem="?") in text
    assert "🟡 " + IT.t("ops.probe", n="?") in text
    assert "🟢 " + IT.t("ops.intents_empty") in text
    assert IT.t("ops.quiet") in text and IT.t("ops.alerts") not in text


def test_il_quadro_ops_parla_la_lingua_del_gestore(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    monkeypatch.setattr(publish.RECENT, "rows", [])
    app = ConsoleApp(store=ops_store(time.time(), lang="en"), coc=key_pool())
    update, query = pressed("panel:ops", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text = query.edits[-1][0]
    assert EN.t("ops.title") in text and IT.t("ops.title") not in text


BANDITO = "203.0.113.9"


def ban_store(now, lang="it"):
    store = ops_store(now, lang)
    store.kv[ban.PREFIX + BANDITO] = {"at": now - 60, "until": now + 3540, "strikes": 1}
    store.kv[ban.PREFIX + "198.51.100.7"] = {"at": now - 7200, "until": None, "strikes": 3}
    return store


def test_dal_quadro_ops_si_arriva_ai_banditi(monkeypatch, tmp_path):
    now = time.time()
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    monkeypatch.setattr(publish.RECENT, "rows", [])
    app = ConsoleApp(store=ban_store(now), coc=key_pool())
    update, query = pressed("panel:ops", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("ops.banned", n="2", hour="1") in text
    assert ("panel:banned", IT.t("ban.btn")) in [
        (b.callback_data, b.text) for row in keyboard.inline_keyboard for b in row]


def test_i_banditi_si_vedono_uno_per_uno_col_bottone_per_sbandirli():
    now = time.time()
    app = ConsoleApp(store=ban_store(now), coc=key_pool())
    update, query = pressed("panel:banned", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("ban.title") in text and BANDITO in text and "198.51.100.7" in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        f"panel:unban:{BANDITO}", "panel:unban:198.51.100.7", "panel:ops"]
    assert IT.t("ban.lift_btn", ip=BANDITO) in [
        b.text for row in keyboard.inline_keyboard for b in row]


def test_sbandire_toglie_l_indirizzo_e_la_sua_storia():
    now = time.time()
    store = ban_store(now)
    store.kv[ban.HIST + BANDITO] = {"strikes": 1, "at": now - 60}
    store.kv[ban.MISS + BANDITO] = {"hits": [now - 60]}
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed(f"panel:unban:{BANDITO}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text = query.edits[-1][0]
    assert BANDITO not in text and "198.51.100.7" in text
    assert ban.PREFIX + BANDITO not in store.kv
    assert ban.HIST + BANDITO not in store.kv and ban.MISS + BANDITO not in store.kv


def test_senza_banditi_la_pagina_lo_dice_e_basta():
    app = ConsoleApp(coc=key_pool())
    update, query = pressed("panel:banned", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("ban.empty") in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == ["panel:ops"]


def test_i_banditi_non_si_vedono_se_non_sei_il_gestore():
    app = ConsoleApp(store=ban_store(time.time()), coc=key_pool())
    update, query = pressed("panel:banned", user_id=42)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert query.edits == []
    assert query.answers[-1] == (IT.t("console.owner_only"), True)


def test_le_risorse_di_oggi_vengono_dal_quadro_e_i_picchi_dai_campioni(monkeypatch, tmp_path):
    now = int(time.time())
    monkeypatch.setattr(metrics, "SAMPLES", str(fresh_samples(tmp_path, now)))
    monkeypatch.setattr(publish.RECENT, "rows", [])
    app = ConsoleApp(store=ops_store(now), supervisor=FakeSupervisor(running=["bot-a"]),
                     coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    text = last(update)
    assert IT.t("panel.container_peak", name="clashbot", mem="2.600", cpu="0,25",
                peak_mem="900", peak_cpu="2,40") in text
    assert IT.t("panel.container", name="clashbot-web", mem="120", cpu="0,02") in text
    assert IT.t("panel.container_peak", name="clashbot-db", mem="44", cpu="0,01",
                peak_mem="44", peak_cpu="0,05") in text


def test_le_risorse_restano_i_campioni_del_guardiano_finche_il_quadro_e_vuoto(monkeypatch, tmp_path):
    now = int(time.time())
    monkeypatch.setattr(metrics, "SAMPLES", str(fresh_samples(tmp_path, now)))
    monkeypatch.setattr(publish.RECENT, "rows", [])
    app = ConsoleApp(supervisor=FakeSupervisor(running=["bot-a"]), coc=key_pool())
    update, ctx = app.update_from(user_id=app.owner_id, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    text = last(update)
    assert IT.t("panel.container_peak", name="clashbot", mem="300", cpu="0,20",
                peak_mem="900", peak_cpu="2,40") in text
    assert "clashbot-web" not in text


def test_il_gestore_della_piattaforma_riattiva_i_posti_sospesi(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp()
    store = app.store
    store.state[("clan-1", "members")] = {LEADER_TAG: {"name": "Mario", "role": "coLeader"}}
    store.accounts.append(account(USER, LEADER_TAG))
    store.kv[guard.suspended_key("clan-1", USER)] = {"at": 0}
    code = store.recruit_code("clan-1")
    update, query = pressed("panel:seats", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.seats.row", code=code, n=1) in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        f"panel:seat:{code}", "panel:refresh"]
    update, query = pressed(f"panel:seat:{code}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.seats.lifted", code=code, n=1) in query.edits[-1][0]
    assert not asyncio.run(guard.suspended(store, "clan-1", USER))
    update, query = pressed("panel:seats", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.seats.empty") in query.edits[-1][0]


def seats_store():
    rows = [make_bot("bot-a", owner_id=OWNER, username="Uno")]
    store = CodeStore(rows=rows, owner=str(OWNER), secrets={"owner_lang": "it"},
                      clans=[make_clan("clan-1", 101, "bot-a"), make_clan("clan-2", 102, "bot-a")])
    store.accounts.append(account(USER, LEADER_TAG))
    for alias in ("clan-1", "clan-2"):
        store.state[(alias, "members")] = {LEADER_TAG: {"name": "Mario", "role": "coLeader"}}
        store.kv[guard.suspended_key(alias, USER)] = {"at": 0}
    return store


def test_i_posti_sospesi_oltre_la_prima_pagina_si_riattivano_lo_stesso():
    store = seats_store()
    code = store.recruit_code("clan-2")
    text, _ = asyncio.run(seats.act(store, IT, "seats", "", 1))
    assert code not in text and store.recruit_code("clan-1") in text
    text, _ = asyncio.run(seats.act(store, IT, "seat", code, 1))
    assert IT.t("panel.seats.lifted", code=code, n=1) in text
    assert not asyncio.run(guard.suspended(store, "clan-2", USER))
    assert asyncio.run(guard.suspended(store, "clan-1", USER))


def test_un_codice_che_non_e_di_nessun_clan_non_riattiva_niente():
    store = seats_store()
    text, _ = asyncio.run(seats.act(store, IT, "seat", "codzz", 1))
    assert IT.t("panel.seats.empty") in text
    assert asyncio.run(guard.suspended(store, "clan-1", USER))


def test_the_panel_buttons_are_closed_to_everybody_else(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp()
    for data in ("panel:refresh", "panel:bots", "panel:reports", "panel:seats"):
        update, query = pressed(data, user_id=USER)
        asyncio.run(console.on_panel_callback(update, app.context))
        assert query.edits == [] and query.answers == [(IT.t("console.owner_only"), True)]


REPORT_NOW = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
REPORT_CODE = "cod1"


class CodeStore(FakeStore):
    def recruit_code(self, clan_alias):
        return "cod" + str(clan_alias).rsplit("-", 1)[-1]


class ReportStore(CodeStore):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.reported = []

    async def report_add(self, clan_alias, user_id, reason, now):
        self.reported.append((clan_alias, user_id, reason, now.timestamp()))
        return len(self.reported)

    async def reports(self, limit=20):
        rows = [{"alias": alias, "code": self.recruit_code(alias), "reason": reason, "at": at}
                for alias, _, reason, at in self.reported]
        return list(reversed(rows))[:limit]


def report_store(clans=None):
    rows = [make_bot("bot-a", owner_id=OWNER, username="Uno")]
    store = ReportStore(rows=rows, owner=str(OWNER), secrets={"owner_lang": "it"},
                        clans=clans or [make_clan("clan-1", 101, "bot-a")])
    return store


def test_a_report_takes_a_reason_from_the_closed_list_only():
    store = report_store()
    assert asyncio.run(reports.add(store, "clan-1", USER, "spam", REPORT_NOW)) is True
    assert store.reported[-1][:3] == ("clan-1", USER, "spam")
    for reason in ("pinco", "", None, "libero"):
        with pytest.raises(ValueError):
            asyncio.run(reports.add(store, "clan-1", USER, reason, REPORT_NOW))
    assert len(store.reported) == 1


def test_the_sixth_report_of_the_same_person_in_the_window_is_refused():
    store = report_store()
    for step in range(platform_guard.FLOOD_LIMIT):
        moment = REPORT_NOW + timedelta(seconds=step)
        assert asyncio.run(reports.add(store, "clan-1", USER, "spam", moment)) is True
    late = REPORT_NOW + timedelta(seconds=platform_guard.FLOOD_LIMIT)
    assert asyncio.run(reports.add(store, "clan-1", USER, "scam", late)) is False
    assert len(store.reported) == platform_guard.FLOOD_LIMIT
    assert asyncio.run(reports.add(store, "clan-1", USER + 1, "scam", late)) is True
    after = REPORT_NOW + timedelta(seconds=platform_guard.FLOOD_WINDOW + 1)
    assert asyncio.run(reports.add(store, "clan-1", USER, "scam", after)) is True


def test_a_report_never_carries_free_text():
    assert reports.REASONS == ("spam", "scam", "harassment", "impersonation", "other_no_text")
    for reason in reports.REASONS:
        assert EN.t(f"report.reasons.{reason}")


def test_the_panel_lists_the_reports_with_the_blind_code(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = report_store()
    monkeypatch.setattr(console, "now_utc", lambda: REPORT_NOW + timedelta(minutes=5))
    asyncio.run(reports.add(store, "clan-1", USER, "harassment", REPORT_NOW))
    app = ConsoleApp(store=store, supervisor=FakeSupervisor(running=["bot-a"]))
    update, query = pressed("panel:refresh", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert "panel:reports" in [b.callback_data for row in query.edits[-1][1].inline_keyboard
                               for b in row]
    update, query = pressed("panel:reports", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.reports.title") in text
    assert REPORT_CODE in text and IT.t("report.reasons.harassment") in text
    assert "clan-1" not in text and str(USER) not in text
    assert f"panel:rep:{REPORT_CODE}" in [b.callback_data for row in keyboard.inline_keyboard
                                          for b in row]


def test_the_panel_says_when_there_is_nothing_to_look_at(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(store=report_store(), supervisor=FakeSupervisor())
    update, query = pressed("panel:reports", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.reports.empty") in query.edits[-1][0]


def test_the_manager_suspends_the_reported_bot_with_its_reason(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = report_store()
    monkeypatch.setattr(console, "now_utc", lambda: REPORT_NOW + timedelta(minutes=5))
    asyncio.run(reports.add(store, "clan-1", USER, "scam", REPORT_NOW))
    supervisor = FakeSupervisor(running=["bot-a"])
    app = ConsoleApp(store=store, supervisor=supervisor)
    update, query = pressed(f"panel:rep:{REPORT_CODE}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    datas = [b.callback_data for row in query.edits[-1][1].inline_keyboard for b in row]
    assert datas == [f"panel:stop:{REPORT_CODE}", f"panel:token:{REPORT_CODE}", "panel:refresh"]
    update, query = pressed(f"panel:stop:{REPORT_CODE}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert store.activated[-1] == ("bot-a", False, "reported")
    assert supervisor.stopped[-1][0] == "bot-a"
    assert IT.t("panel.reports.suspended", code=REPORT_CODE) in query.edits[-1][0]
    assert "reported" in render.REASONS
    assert IT.t("console.reason.reported") == render.reason_label(IT, "reported")


def test_the_manager_swaps_the_token_of_the_reported_bot(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = report_store()
    monkeypatch.setattr(console, "now_utc", lambda: REPORT_NOW + timedelta(minutes=5))
    asyncio.run(reports.add(store, "clan-1", USER, "spam", REPORT_NOW))
    supervisor = FakeSupervisor(running=["bot-a"])
    app = ConsoleApp(store=store, supervisor=supervisor)
    update, query = pressed(f"panel:token:{REPORT_CODE}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert supervisor.swapped == [("bot-a", app.context.bot)]
    assert IT.t("panel.reports.token_ok", code=REPORT_CODE) in query.edits[-1][0]


def test_una_segnalazione_fuori_dalla_prima_pagina_si_ferma_lo_stesso():
    store = report_store(clans=[make_clan("clan-1", 101, "bot-a"),
                                make_clan("clan-2", 102, "bot-b")])
    store.rows.append(make_bot("bot-b", owner_id=OWNER, username="Due", bot_id=2))
    asyncio.run(reports.add(store, "clan-2", USER, "spam", REPORT_NOW))
    asyncio.run(reports.add(store, "clan-1", USER + 1, "spam", REPORT_NOW))
    pagina = asyncio.run(store.reports(1))
    assert [row["alias"] for row in pagina] == ["clan-1"]
    code = store.recruit_code("clan-2")
    supervisor = FakeSupervisor(running=["bot-a", "bot-b"])
    text, _ = asyncio.run(
        reports.act(store, supervisor, None, IT, "stop", code, pagina, REPORT_NOW))
    assert IT.t("panel.reports.suspended", code=code) in text
    assert store.activated == [("bot-b", False, reports.STOP_REASON)]
    assert supervisor.stopped[-1][0] == "bot-b"


def test_a_report_without_a_bot_to_stop_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = report_store()
    monkeypatch.setattr(console, "now_utc", lambda: REPORT_NOW + timedelta(minutes=5))
    asyncio.run(reports.add(store, "clan-1", USER, "spam", REPORT_NOW))
    app = ConsoleApp(store=store, supervisor=FakeSupervisor())
    update, query = pressed("panel:stop:zzzzzz", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.reports.gone") in query.edits[-1][0]
    assert store.activated == []


USAGE_NOTE = {"v": 1, "updated": 1789000000, "bots": 2, "bots_active": 1, "bots_running": 1,
              "clans": 3, "clans_active": 2, "families": 1, "links": 7, "members": 30, "wars": 4,
              "langs": {"it": 2, "en": 1}}


def test_the_panel_shows_the_anonymous_numbers_of_the_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    store.notes["usage"] = USAGE_NOTE
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:usage", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.usage.title") in text
    for key, value in (("links", 7), ("wars", 4), ("clans_active", 2), ("members", 30)):
        assert IT.t("panel.usage.row", label=IT.t("panel.usage.n." + key), n=value) in text
    assert IT.t("panel.usage.langs", langs="en 1 · it 2") in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == ["panel:refresh"]


def test_the_numbers_of_the_platform_say_so_while_they_are_not_there(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(coc=key_pool())
    update, query = pressed("panel:usage", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.usage.empty") in query.edits[-1][0]


def test_la_sezione_dei_fidati_non_esiste_piu_da_nessuna_parte(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    app = ConsoleApp(store=store, coc=key_pool())
    for data in ("panel:trusted", "panel:trustadd", "panel:trust:it:123"):
        update, query = pressed(data, user_id=OWNER)
        asyncio.run(console.on_panel_callback(update, app.context))
        assert IT.t("panel.title") in query.edits[-1][0], data
        assert "panel:trusted" not in datas(query.edits[-1][1]), data
    assert "web:trusted" not in store.kv
    assert app.context.user_data == {}
    assert not hasattr(console, "on_trusted_text")
    assert not hasattr(platform, "TRANSLATIONS")
    for name in ("trust", "trustadd"):
        assert name not in otp.GUARDED and name not in platform.OPEN, name
    for code in i18n.LANGUAGES:
        for key in ("panel.trusted.btn", "panel.trusted.title", "panel.trusted.row",
                    "panel.trusted.added", "panel.trusted.ask"):
            assert i18n.locale(code).t(key) == f"[{key}]", (code, key)
    assert "fidat" not in i18n.locale("it").t("console.delegate.welcome")


DELEGATE_ID = 4242
DELEGATE_NAME = "cyfren1"


def waiting_row(username=DELEGATE_NAME, since=1789000000):
    return {"username": username, "user_id": None, "since": since}


def bound_row(user_id=DELEGATE_ID, username=DELEGATE_NAME, since=1789000000, bound=1789000500):
    return {"username": username, "user_id": user_id, "since": since, "bound": bound}


def delegate_store(lang="it", rows=None):
    store = panel_store(lang)
    store.kv[platform.KEY] = [bound_row()] if rows is None else list(rows)
    return store


def datas(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def con_codice(store, uid, aperta=True):
    chiave = otp.secret()
    store.secrets[otp.seed_of(uid)] = chiave
    if aperta:
        store.kv[otp.window_of(uid)] = {"at": time.time(), "step": 0}
    return chiave


def test_il_pannello_del_delegato_porta_solo_le_sue_sezioni(monkeypatch, tmp_path):
    now = int(time.time())
    monkeypatch.setattr(metrics, "SAMPLES", str(fresh_samples(tmp_path, now)))
    app = ConsoleApp(store=delegate_store(), supervisor=FakeSupervisor(running=["bot-a"]),
                     coc=key_pool())
    update, ctx = app.update_from(user_id=DELEGATE_ID, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    text, keyboard = update.effective_message.sent[-1]
    assert IT.t("panel.title") in text
    assert IT.t("platform.bots", running=1, total=2) in text
    assert IT.t("platform.clans", n=2, total=3) in text
    assert datas(keyboard) == ["panel:refresh", "panel:reports", "panel:usage", "panel:otp",
                               "panel:media"]
    assert IT.t("panel.backup", n=5) not in text and IT.t("panel.alerts") not in text
    assert IT.t("panel.no_samples") not in text and "clashbot" not in text
    update, query = pressed("panel:refresh", user_id=DELEGATE_ID)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert query.edits[-1][0] == text
    assert datas(query.edits[-1][1]) == datas(keyboard)


def test_il_pannello_del_delegato_parla_la_sua_lingua(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(store=delegate_store(lang="en"), coc=key_pool())
    update, ctx = app.update_from(user_id=DELEGATE_ID, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert IT.t("panel.title") in app.replies[-1]
    assert EN.t("panel.title") not in app.replies[-1]


def test_il_pannello_del_gestore_tiene_anche_le_deleghe(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(store=delegate_store(), coc=key_pool())
    update, ctx = app.update_from(user_id=OWNER, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    text, keyboard = update.effective_message.sent[-1]
    assert datas(keyboard) == ["panel:refresh", "panel:bots", "panel:reports", "panel:seats",
                               "panel:ops", "panel:delegates", "panel:usage", "panel:otp",
                               "panel:media", "panel:site"]
    assert IT.t("panel.no_samples") in text


def test_al_delegato_i_bottoni_del_gestore_dicono_che_non_sono_suoi(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = delegate_store()
    app = ConsoleApp(store=store, coc=key_pool())
    riservati = ("panel:ops", "panel:bots", "panel:banned", f"panel:unban:{BANDITO}",
                 "panel:seats", "panel:seat:cod1", "panel:delegates", "panel:deladd",
                 f"panel:deldrop:{DELEGATE_NAME}", "panel:stop:cod1", "panel:token:cod1")
    for data in riservati:
        update, query = pressed(data, user_id=DELEGATE_ID)
        asyncio.run(console.on_panel_callback(update, app.context))
        assert query.edits == [], data
        assert query.answers == [(IT.t("console.not_owner"), True)], data
    assert store.activated == [] and store.kv[platform.KEY] == [bound_row()]
    assert app.context.user_data == {}


def test_il_delegato_legge_le_segnalazioni_senza_poterle_punire(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = report_store()
    monkeypatch.setattr(console, "now_utc", lambda: REPORT_NOW + timedelta(minutes=5))
    store.kv[platform.KEY] = [bound_row()]
    asyncio.run(reports.add(store, "clan-1", USER, "harassment", REPORT_NOW))
    app = ConsoleApp(store=store, supervisor=FakeSupervisor(running=["bot-a"]))
    update, query = pressed("panel:reports", user_id=DELEGATE_ID)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.reports.title") in text and REPORT_CODE in text
    assert "clan-1" not in text and str(USER) not in text
    update, query = pressed(f"panel:rep:{REPORT_CODE}", user_id=DELEGATE_ID)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.reports.clan", code=REPORT_CODE, n=1) in text
    assert datas(keyboard) == ["panel:refresh"]
    assert store.activated == []


def test_il_gestore_aggiunge_un_delegato_che_resta_in_attesa(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(store=delegate_store(rows=[]), coc=key_pool())
    update, query = pressed("panel:delegates", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.delegates.title") in text and IT.t("panel.delegates.empty") in text
    assert datas(keyboard) == ["panel:deladd", "panel:refresh"]
    update, query = pressed("panel:deladd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.delegates.ask") in query.edits[-1][0]
    assert datas(query.edits[-1][1]) == ["panel:delegates"]
    assert app.context.user_data["delegates"] is True
    written, ctx = app.update_from(user_id=OWNER, text=f"@{DELEGATE_NAME}")
    asyncio.run(console.on_newbot_text(written, ctx))
    text, keyboard = written.effective_message.sent[-1]
    assert IT.t("panel.delegates.added", username=DELEGATE_NAME) in text
    assert IT.t("panel.delegates.row", mark=platform.WAITING, username=DELEGATE_NAME) in text
    assert datas(keyboard) == [f"panel:deldrop:{DELEGATE_NAME}", "panel:deladd", "panel:refresh"]
    assert "delegates" not in ctx.user_data
    riga = app.store.kv[platform.KEY][-1]
    assert riga["username"] == DELEGATE_NAME and riga["user_id"] is None and riga["since"] > 0
    assert asyncio.run(platform.level(app.store, DELEGATE_ID)) is None


def test_la_riga_del_delegato_legato_porta_l_id_e_la_data_del_legame(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    legato = bound_row()
    store = delegate_store(rows=[legato, waiting_row(username="altropassante")])
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:delegates", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text = query.edits[-1][0]
    assert IT.t("panel.delegates.bound", mark=platform.BOUND, username=DELEGATE_NAME,
                uid=DELEGATE_ID, when=IT.ago(manager_alerts.moment(legato["bound"]))) in text
    assert IT.t("panel.delegates.row", mark=platform.WAITING, username="altropassante") in text
    assert str(DELEGATE_ID) in text


def test_un_delegato_legato_prima_di_questa_riga_dice_che_la_data_non_si_sa(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    vecchio = {"username": DELEGATE_NAME, "user_id": DELEGATE_ID, "since": 1789000000}
    app = ConsoleApp(store=delegate_store(rows=[vecchio]), coc=key_pool())
    update, query = pressed("panel:delegates", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.delegates.bound", mark=platform.BOUND, username=DELEGATE_NAME,
                uid=DELEGATE_ID, when=IT.ago(None)) in query.edits[-1][0]


def test_uno_username_che_non_torna_fa_richiedere_il_nome(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = ConsoleApp(store=delegate_store(rows=[]), coc=key_pool())
    update, query = pressed("panel:deladd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    written, ctx = app.update_from(user_id=OWNER, text="chi va là?")
    asyncio.run(console.on_newbot_text(written, ctx))
    assert IT.t("panel.delegates.bad") in written.effective_message.sent[-1][0]
    assert ctx.user_data["delegates"] is True
    assert app.store.kv[platform.KEY] == []
    buono, ctx = app.update_from(user_id=OWNER, text=DELEGATE_NAME)
    asyncio.run(console.on_newbot_text(buono, ctx))
    assert [row["username"] for row in app.store.kv[platform.KEY]] == [DELEGATE_NAME]


def test_solo_il_gestore_scrive_nella_lista_dei_delegati(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = delegate_store(rows=[])
    ctx = context(store, user_data={"delegates": True})
    update = private(user_id=USER, text="@intruso")
    asyncio.run(console.on_newbot_text(update, ctx))
    assert update.effective_message.sent == []
    assert store.kv[platform.KEY] == [] and "delegates" not in ctx.user_data


def test_il_gestore_toglie_il_delegato_e_la_lista_resta_pulita(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = delegate_store()
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed(f"panel:deldrop:{DELEGATE_NAME}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.delegates.dropped", username=DELEGATE_NAME) in text
    assert IT.t("panel.delegates.empty") in text
    assert datas(keyboard) == ["panel:deladd", "panel:refresh"]
    assert store.kv[platform.KEY] == []
    assert asyncio.run(platform.level(store, DELEGATE_ID)) is None


CANALE = "UCabc"
CANALE_NOME = "Builder"


def media_store(lang="it", channels=(), last=None, quota=None):
    store = delegate_store(lang)
    store.kv[base_videos.CHANNELS_KEY] = list(channels)
    if last is not None:
        store.kv[base_library.LAST_KEY] = last
    if quota is not None:
        store.kv[base_videos.QUOTA_KEY] = quota
    return store


def test_il_pannello_porta_le_basi_e_le_notizie_anche_al_delegato(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    now = time.time()
    store = media_store(channels=[{"id": CANALE, "title": CANALE_NOME}],
                        last={"status": "fresh", "count": 5, "at": now - 7200},
                        quota={"until": now + 7200})
    app = ConsoleApp(store=store, coc=key_pool())
    update, ctx = app.update_from(user_id=DELEGATE_ID, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert "panel:media" in datas(update.effective_message.sent[-1][1])
    update, query = pressed("panel:media", user_id=DELEGATE_ID)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("panel.media.title") in text
    assert IT.t("panel.media.channels", title=CANALE_NOME, id=CANALE) in text
    assert IT.t("panel.media.library", n=5,
                when=IT.ago(manager_alerts.moment(now - 7200))) in text
    assert IT.t("panel.media.quota", when=IT.when(manager_alerts.moment(now + 7200))) in text
    assert datas(keyboard) == [f"panel:mediaofficial:{CANALE}", f"panel:mediadrop:{CANALE}",
                               "panel:mediaadd", "panel:refresh"]
    assert IT.t("otp.ask") not in text


def test_chi_non_e_di_piattaforma_non_vede_i_canali(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = media_store(channels=[{"id": CANALE, "title": CANALE_NOME}])
    app = ConsoleApp(store=store, coc=key_pool())
    for data in ("panel:media", "panel:mediaadd", f"panel:mediadrop:{CANALE}",
                 f"panel:mediaofficial:{CANALE}"):
        update, query = pressed(data, user_id=USER)
        asyncio.run(console.on_panel_callback(update, app.context))
        assert query.edits == [], data
        assert query.answers == [(IT.t("console.owner_only"), True)], data
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": CANALE_NOME}]


def test_il_gestore_aggiunge_il_canale_con_l_id_e_poi_lo_toglie(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = media_store()
    con_codice(store, OWNER)
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:mediaadd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.media.ask") in query.edits[-1][0]
    assert datas(query.edits[-1][1]) == ["panel:media"]
    assert app.context.user_data["media"] is True
    written, ctx = app.update_from(user_id=OWNER, text=CANALE)
    asyncio.run(console.on_newbot_text(written, ctx))
    text, keyboard = written.effective_message.sent[-1]
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": ""}]
    assert IT.t("panel.media.channels", title=CANALE, id=CANALE) in text
    assert datas(keyboard) == [f"panel:mediaofficial:{CANALE}", f"panel:mediadrop:{CANALE}",
                               "panel:mediaadd", "panel:refresh"]
    assert "media" not in ctx.user_data
    update, query = pressed(f"panel:mediadrop:{CANALE}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert store.kv[base_videos.CHANNELS_KEY] == []
    assert IT.t("panel.media.empty") in query.edits[-1][0]


def test_il_canale_ufficiale_si_segna_dal_pannello_e_si_vede_nella_riga(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = media_store(channels=[{"id": CANALE, "title": CANALE_NOME}])
    con_codice(store, OWNER)
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed(f"panel:mediaofficial:{CANALE}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert store.kv[base_videos.CHANNELS_KEY] == [
        {"id": CANALE, "title": CANALE_NOME, base_videos.OFFICIAL: True}]
    text, keyboard = query.edits[-1]
    assert IT.t("panel.media.channels", title=f"{console.OFFICIAL_MARK} {CANALE_NOME}",
                id=CANALE) in text
    assert datas(keyboard) == [f"panel:mediaofficial:{CANALE}", f"panel:mediadrop:{CANALE}",
                               "panel:mediaadd", "panel:refresh"]
    update, query = pressed(f"panel:mediaofficial:{CANALE}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": CANALE_NOME}]
    assert IT.t("panel.media.channels", title=CANALE_NOME, id=CANALE) in query.edits[-1][0]


def test_un_canale_che_non_si_capisce_fa_richiedere_l_id(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = media_store()
    con_codice(store, OWNER)
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:mediaadd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    written, ctx = app.update_from(user_id=OWNER, text="chi va là?")
    asyncio.run(console.on_newbot_text(written, ctx))
    text, keyboard = written.effective_message.sent[-1]
    assert IT.t("panel.media.bad") in text and IT.t("panel.media.ask") in text
    assert datas(keyboard) == ["panel:media"]
    assert ctx.user_data["media"] is True
    assert store.kv[base_videos.CHANNELS_KEY] == []


def test_anche_il_delegato_tiene_i_canali_della_piattaforma(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = media_store(channels=[{"id": CANALE, "title": CANALE_NOME}])
    con_codice(store, DELEGATE_ID)
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed(f"panel:mediadrop:{CANALE}", user_id=DELEGATE_ID)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert store.kv[base_videos.CHANNELS_KEY] == []
    assert IT.t("panel.media.empty") in query.edits[-1][0]
    update, query = pressed("panel:mediaadd", user_id=DELEGATE_ID)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.media.ask") in query.edits[-1][0]
    written, ctx = app.update_from(user_id=DELEGATE_ID, text=CANALE)
    asyncio.run(console.on_newbot_text(written, ctx))
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": ""}]


def test_le_due_domande_del_pannello_non_si_scambiano_la_risposta(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = media_store()
    con_codice(store, OWNER)
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:deladd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    update, query = pressed("panel:mediaadd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert "delegates" not in app.context.user_data
    written, ctx = app.update_from(user_id=OWNER, text=CANALE)
    asyncio.run(console.on_newbot_text(written, ctx))
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": ""}]
    assert store.kv[platform.KEY] == [bound_row()]
    update, query = pressed("panel:mediaadd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    update, query = pressed("panel:deladd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert "media" not in app.context.user_data
    written, ctx = app.update_from(user_id=OWNER, text=f"@{DELEGATE_NAME}")
    asyncio.run(console.on_newbot_text(written, ctx))
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": ""}]
    assert [row["username"] for row in store.kv[platform.KEY]] == [DELEGATE_NAME]


def test_con_la_finestra_chiusa_il_canale_chiede_il_codice(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = media_store(channels=[{"id": CANALE, "title": CANALE_NOME}])
    con_codice(store, OWNER, aperta=False)
    app = ConsoleApp(store=store, coc=key_pool())
    for data in ("panel:mediaadd", f"panel:mediadrop:{CANALE}"):
        update, query = pressed(data, user_id=OWNER)
        asyncio.run(console.on_panel_callback(update, app.context))
        assert IT.t("otp.ask") in query.edits[-1][0], data
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": CANALE_NOME}]
    assert "media" not in app.context.user_data
    update, query = pressed("panel:media", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.media.title") in query.edits[-1][0]


def test_il_delegato_manda_le_novita_e_il_registro_lo_annota(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    store = delegate_store()
    store.state[("clan-1", "settings")] = {"news": True}
    con_codice(store, DELEGATE_ID)
    worker = FakeTelegramBot()
    supervisor = FakeSupervisor(running=["bot-a"], bots={"bot-a": worker})
    ctx = context(store, supervisor, args=["Domani", "si", "parte"])
    chiesto = private(user_id=DELEGATE_ID)
    asyncio.run(console.cmd_broadcast(chiesto, ctx))
    assert IT.t("console.broadcast_preview", n=1) in chiesto.effective_message.sent[-1][0]
    update, query = pressed("bc:send", user_id=DELEGATE_ID)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert [chat for chat, _ in worker.sent] == [101]
    assert IT.t("console.broadcast_sent", sent=1, failed=0) in query.edits[-1][0]
    registro = store.kv[manager_alerts.key_of(platform.LOG_KIND)]
    assert [(row["what"], row["who"]) for row in registro["history"]] == [
        (platform.NEWS, DELEGATE_ID)]


def test_chi_non_e_delegato_non_manda_le_novita():
    store = delegate_store()
    worker = FakeTelegramBot()
    supervisor = FakeSupervisor(running=["bot-a"], bots={"bot-a": worker})
    ctx = context(store, supervisor, user_data={"broadcast": "Ciao"})
    update, query = pressed("bc:send", user_id=USER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert worker.sent == [] and query.answers == [(IT.t("console.owner_only"), True)]
    assert manager_alerts.key_of(platform.LOG_KIND) not in store.kv


def altro_codice(giusto):
    return "000000" if giusto != "000000" else "111111"


def test_l_azione_che_scrive_chiede_il_codice_e_poi_tace_per_dieci_minuti(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = delegate_store()
    chiave = con_codice(store, OWNER, aperta=False)
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed(f"panel:deldrop:{DELEGATE_NAME}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("otp.ask") in query.edits[-1][0]
    assert store.kv[platform.KEY] == [bound_row()]
    assert app.context.user_data["otp"] is True
    scritto, ctx = app.update_from(user_id=OWNER, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(scritto, ctx))
    assert IT.t("otp.ok", n=otp.MINUTES) in scritto.effective_message.sent[-1][0]
    assert "otp" not in ctx.user_data
    assert store.ttls[otp.window_of(OWNER)] == selfmetrics.PLATFORM_INTERVAL
    update, query = pressed(f"panel:deldrop:{DELEGATE_NAME}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.delegates.dropped", username=DELEGATE_NAME) in query.edits[-1][0]
    assert store.kv[platform.KEY] == []
    store.kv[otp.window_of(OWNER)]["at"] -= selfmetrics.PLATFORM_INTERVAL
    update, query = pressed("panel:deladd", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("otp.ask") in query.edits[-1][0]
    assert "delegates" not in app.context.user_data


def test_il_codice_gia_speso_non_riapre_la_finestra(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = delegate_store()
    chiave = con_codice(store, OWNER, aperta=False)
    app = ConsoleApp(store=store, coc=key_pool())
    codice = otp.code(chiave, time.time())
    scritto, ctx = app.update_from(user_id=OWNER, text=codice)
    ctx.user_data["otp"] = True
    asyncio.run(console.on_newbot_text(scritto, ctx))
    assert IT.t("otp.ok", n=otp.MINUTES) in scritto.effective_message.sent[-1][0]
    store.kv[otp.window_of(OWNER)]["at"] -= selfmetrics.PLATFORM_INTERVAL
    ancora, ctx = app.update_from(user_id=OWNER, text=codice)
    ctx.user_data["otp"] = True
    asyncio.run(console.on_newbot_text(ancora, ctx))
    assert IT.t("otp.bad") in ancora.effective_message.sent[-1][0]
    assert ctx.user_data["otp"] is True
    update, query = pressed(f"panel:deldrop:{DELEGATE_NAME}", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("otp.ask") in query.edits[-1][0]
    assert store.kv[platform.KEY] == [bound_row()]


def novita_pronte(store):
    store.state[("clan-1", "settings")] = {"news": True}
    worker = FakeTelegramBot()
    return worker, FakeSupervisor(running=["bot-a"], bots={"bot-a": worker})


def test_senza_codice_attivo_scrive_solo_il_gestore(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    store = delegate_store()
    worker, supervisor = novita_pronte(store)
    app = ConsoleApp(store=store, supervisor=supervisor, coc=key_pool())
    app.context.user_data["broadcast"] = "Domani si parte"
    update, query = pressed("bc:send", user_id=DELEGATE_ID)
    asyncio.run(console.on_broadcast_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("otp.needed") in text and datas(keyboard) == ["panel:otpnew", "panel:refresh"]
    assert worker.sent == [] and "otp" not in app.context.user_data
    update, query = pressed("bc:send", user_id=OWNER)
    asyncio.run(console.on_broadcast_callback(update, app.context))
    assert IT.t("console.broadcast_sent", sent=1, failed=0) in query.edits[-1][0]
    assert [chat for chat, _ in worker.sent] == [101]


def test_il_delegato_ha_il_suo_codice_e_la_sua_finestra(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    store = delegate_store()
    worker, supervisor = novita_pronte(store)
    chiave = con_codice(store, DELEGATE_ID, aperta=False)
    app = ConsoleApp(store=store, supervisor=supervisor, coc=key_pool())
    app.context.user_data["broadcast"] = "Domani si parte"
    update, query = pressed("bc:send", user_id=DELEGATE_ID)
    asyncio.run(console.on_broadcast_callback(update, app.context))
    assert IT.t("otp.ask") in query.edits[-1][0] and worker.sent == []
    scritto, ctx = app.update_from(user_id=DELEGATE_ID, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(scritto, ctx))
    assert IT.t("otp.ok", n=otp.MINUTES) in scritto.effective_message.sent[-1][0]
    assert otp.window_of(OWNER) not in store.kv
    update, query = pressed("bc:send", user_id=DELEGATE_ID)
    asyncio.run(console.on_broadcast_callback(update, app.context))
    assert IT.t("console.broadcast_sent", sent=1, failed=0) in query.edits[-1][0]
    assert [chat for chat, _ in worker.sent] == [101]


def test_ogni_azione_che_scrive_chiede_il_codice_e_la_lettura_resta_libera(monkeypatch, tmp_path):
    now = time.time()
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    monkeypatch.setattr(publish.RECENT, "rows", [])
    store = ban_store(now)
    store.kv[platform.KEY] = [bound_row()]
    store.kv[base_videos.CHANNELS_KEY] = [{"id": CANALE, "title": CANALE_NOME}]
    con_codice(store, OWNER, aperta=False)
    app = ConsoleApp(store=store, coc=key_pool())
    for data in ("panel:deladd", f"panel:deldrop:{DELEGATE_NAME}", "panel:seat:cod1",
                 f"panel:unban:{BANDITO}", "panel:stop:cod1", "panel:token:cod1",
                 "panel:mediaadd", f"panel:mediadrop:{CANALE}"):
        update, query = pressed(data, user_id=OWNER)
        asyncio.run(console.on_panel_callback(update, app.context))
        assert IT.t("otp.ask") in query.edits[-1][0], data
    assert store.kv[platform.KEY] == [bound_row()]
    assert store.kv[base_videos.CHANNELS_KEY] == [{"id": CANALE, "title": CANALE_NOME}]
    assert ban.PREFIX + BANDITO in store.kv
    assert store.activated == []
    assert "delegates" not in app.context.user_data
    assert "media" not in app.context.user_data
    for data in ("panel:refresh", "panel:ops", "panel:banned", "panel:usage",
                 "panel:delegates", "panel:seats", "panel:media"):
        update, query = pressed(data, user_id=OWNER)
        asyncio.run(console.on_panel_callback(update, app.context))
        assert IT.t("otp.ask") not in query.edits[-1][0], data


def test_il_gestore_attiva_il_codice_con_una_prova(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:otp", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    text, keyboard = query.edits[-1]
    assert IT.t("otp.off") in text and datas(keyboard) == ["panel:otpnew", "panel:refresh"]
    update, query = pressed("panel:otpnew", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    chiave = store.kv[otp.pending_of(OWNER)]["key"]
    assert chiave in query.edits[-1][0]
    assert app.context.user_data["otp"] is True
    giusto = otp.code(chiave, time.time())
    storto, ctx = app.update_from(user_id=OWNER, text=altro_codice(giusto))
    asyncio.run(console.on_newbot_text(storto, ctx))
    assert IT.t("otp.bad") in storto.effective_message.sent[-1][0]
    assert otp.seed_of(OWNER) not in store.secrets
    assert ctx.user_data["otp"] is True
    buono, ctx = app.update_from(user_id=OWNER, text=giusto)
    asyncio.run(console.on_newbot_text(buono, ctx))
    assert IT.t("otp.ready", n=otp.MINUTES) in buono.effective_message.sent[-1][0]
    assert store.secrets[otp.seed_of(OWNER)] == chiave
    assert otp.pending_of(OWNER) not in store.kv
    update, query = pressed("panel:otp", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert IT.t("otp.on", n=otp.MINUTES) in query.edits[-1][0]
    assert datas(query.edits[-1][1]) == ["panel:refresh"]


def test_la_chiave_dell_authenticator_sparisce_dalla_chat_dopo_la_prova(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:otpnew", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    chiave = store.kv[otp.pending_of(OWNER)]["key"]
    assert chiave in query.edits[-1][0]
    assert app.context.user_data[console.OTP_SEED] == (OWNER, query.message.message_id)
    buono, ctx = app.update_from(user_id=OWNER, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(buono, ctx))
    assert IT.t("otp.ready", n=otp.MINUTES) in buono.effective_message.sent[-1][0]
    chat, numero, coperto, tastiera = ctx.bot.edited[-1]
    assert (chat, numero) == (OWNER, query.message.message_id)
    assert IT.t("otp.on", n=otp.MINUTES) in coperto and chiave not in coperto
    assert datas(tastiera) == ["panel:refresh"]
    assert console.OTP_SEED not in ctx.user_data
    assert all(chiave not in testo for testo in app.replies)
    assert store.secrets[otp.seed_of(OWNER)] == chiave
    assert otp.pending_of(OWNER) not in store.kv


def test_annulla_copre_la_chiave_dell_authenticator(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    app = ConsoleApp(store=store, coc=key_pool())
    update, query = pressed("panel:otpnew", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    chiave = store.kv[otp.pending_of(OWNER)]["key"]
    assert chiave in query.edits[-1][0]
    fermo, ctx = app.update_from(user_id=OWNER, text="/annulla")
    asyncio.run(console.cmd_cancel(fermo, ctx))
    _, numero, coperto, _ = ctx.bot.edited[-1]
    assert numero == query.message.message_id
    assert chiave not in coperto and IT.t("otp.off") in coperto
    assert console.OTP_SEED not in ctx.user_data and "otp" not in ctx.user_data


def chiave_scoperta(store, ctx):
    update, query = pressed("panel:otpnew", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, ctx))
    return store.kv[otp.pending_of(OWNER)]["key"], query.message.message_id


def test_se_l_edit_non_copre_la_chiave_il_bot_toglie_il_messaggio(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    bot = FakeTelegramBot(no_edit=True)
    ctx = context(store, bot=bot, coc=key_pool())
    chiave, numero = chiave_scoperta(store, ctx)
    buono = private(user_id=OWNER, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(buono, ctx))
    assert bot.gone == [(OWNER, numero)] and bot.edited == []
    assert IT.t("otp.ready", n=otp.MINUTES) in last(buono)
    assert IT.t("otp.seed_left") not in last(buono)
    assert console.OTP_SEED not in ctx.user_data


def test_se_la_chiave_resta_in_chat_il_bot_dice_di_cancellarla(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    bot = FakeTelegramBot(no_edit=True, keeps=True)
    ctx = context(store, bot=bot, coc=key_pool())
    chiave, _ = chiave_scoperta(store, ctx)
    buono = private(user_id=OWNER, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(buono, ctx))
    assert bot.gone == [] and bot.edited == []
    assert IT.t("otp.ready", n=otp.MINUTES) in last(buono)
    assert IT.t("otp.seed_left") in last(buono)
    assert chiave not in last(buono)
    assert console.OTP_SEED not in ctx.user_data


def test_annulla_dice_di_cancellare_la_chiave_se_non_riesce_a_toglierla(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    bot = FakeTelegramBot(no_edit=True, keeps=True)
    ctx = context(store, bot=bot, coc=key_pool())
    chiave, _ = chiave_scoperta(store, ctx)
    fermo = private(user_id=OWNER, text="/annulla")
    asyncio.run(console.cmd_cancel(fermo, ctx))
    assert IT.t("console.cancelled") in last(fermo)
    assert IT.t("otp.seed_left") in last(fermo) and chiave not in last(fermo)
    assert console.OTP_SEED not in ctx.user_data


def test_sospendere_o_riaccendere_un_bot_col_comando_chiede_il_codice(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    chiave = con_codice(store, OWNER, aperta=False)
    supervisor = FakeSupervisor(running=["bot-a"])
    app = ConsoleApp(store=store, supervisor=supervisor, coc=key_pool())
    update, ctx = app.update_from(user_id=OWNER)
    ctx.args = ["bot-a"]
    asyncio.run(console.cmd_disable(update, ctx))
    assert IT.t("otp.ask") in last(update)
    assert store.activated == [] and supervisor.stopped == []
    scritto, ctx = app.update_from(user_id=OWNER, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(scritto, ctx))
    ancora, ctx = app.update_from(user_id=OWNER)
    ctx.args = ["bot-a"]
    asyncio.run(console.cmd_disable(ancora, ctx))
    assert store.activated == [("bot-a", False, "disabled")]
    store.kv[otp.window_of(OWNER)]["at"] -= selfmetrics.PLATFORM_INTERVAL
    chiuso, ctx = app.update_from(user_id=OWNER)
    ctx.args = ["bot-a"]
    asyncio.run(console.cmd_enable(chiuso, ctx))
    assert IT.t("otp.ask") in last(chiuso)
    assert store.activated == [("bot-a", False, "disabled")]


def test_i_bottoni_che_fermano_tolgono_o_riaccendono_un_bot_chiedono_il_codice(monkeypatch,
                                                                              tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    chiave = con_codice(store, OWNER, aperta=False)
    supervisor = FakeSupervisor(running=["bot-a"])
    app = ConsoleApp(store=store, supervisor=supervisor, coc=key_pool())
    for data in ("b:stop:bot-a", "b:start:bot-b", "b:remove2:bot-a"):
        update, query = pressed(data, user_id=OWNER)
        asyncio.run(console.on_bot_callback(update, app.context))
        assert IT.t("otp.ask") in query.edits[-1][0], data
    assert store.activated == [] and store.removed == []
    assert supervisor.stopped == [] and supervisor.started == []
    scritto, ctx = app.update_from(user_id=OWNER, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(scritto, ctx))
    update, query = pressed("b:stop:bot-a", user_id=OWNER)
    asyncio.run(console.on_bot_callback(update, app.context))
    assert supervisor.stopped == [("bot-a", "owner_stopped")]


def test_chi_ha_solo_il_suo_bot_non_deve_nessun_codice():
    store = FakeStore(rows=[make_bot("bot-c", owner_id=USER)], owner=str(OWNER))
    supervisor = FakeSupervisor(running=["bot-c"])
    update, query = pressed("b:stop:bot-c", user_id=USER)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert supervisor.stopped == [("bot-c", "owner_stopped")]
    assert IT.t("otp.ask") not in query.edits[-1][0]


def test_il_pannello_ricorda_di_attivare_il_codice_a_ogni_apertura(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    store = panel_store()
    app = ConsoleApp(store=store, coc=key_pool())
    update, ctx = app.update_from(user_id=OWNER, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert IT.t("otp.hint") in last(update)
    con_codice(store, OWNER)
    update, ctx = app.update_from(user_id=OWNER, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    quadro = last(update)
    assert IT.t("otp.hint") not in quadro
    update, query = pressed("panel:refresh", user_id=OWNER)
    asyncio.run(console.on_panel_callback(update, app.context))
    assert query.edits[-1][0] == quadro


def test_le_novita_partono_solo_col_codice(monkeypatch):
    monkeypatch.setattr(console, "BROADCAST_DELAY", 0)
    store = panel_store()
    store.state[("clan-1", "settings")] = {"news": True}
    chiave = con_codice(store, OWNER, aperta=False)
    worker = FakeTelegramBot()
    supervisor = FakeSupervisor(running=["bot-a"], bots={"bot-a": worker})
    ctx = context(store, supervisor, args=["Domani", "si", "parte"])
    chiesto = private(user_id=OWNER)
    asyncio.run(console.cmd_broadcast(chiesto, ctx))
    update, query = pressed("bc:send", user_id=OWNER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert worker.sent == [] and IT.t("otp.ask") in query.edits[-1][0]
    assert ctx.user_data["broadcast"] == "Domani si parte"
    scritto = private(user_id=OWNER, text=otp.code(chiave, time.time()))
    asyncio.run(console.on_newbot_text(scritto, ctx))
    update, query = pressed("bc:send", user_id=OWNER)
    asyncio.run(console.on_broadcast_callback(update, ctx))
    assert [chat for chat, _ in worker.sent] == [101]
    assert IT.t("console.broadcast_sent", sent=1, failed=0) in query.edits[-1][0]


def test_annulla_toglie_anche_l_attesa_del_codice():
    ctx = context(FakeStore(), user_data={"otp": True})
    asyncio.run(console.cmd_cancel(private(), ctx))
    assert "otp" not in ctx.user_data


def test_il_co_capo_non_toglie_il_bot():
    store = in_clan_store([make_bot("bot-a", owner_id=42)], role="coLeader")
    supervisor = FakeSupervisor(running=["bot-a"])
    update, query = pressed("b:remove2:bot-a", user_id=USER)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert store.removed == [] and supervisor.stopped == []
    assert query.answers == [(IT.t("console.owner_only"), True)]


def test_chi_ha_creato_il_bot_e_uscito_dal_clan_non_lo_ferma_piu():
    store = FakeStore(rows=[make_bot("bot-a")], clans=[make_clan("clan-1", 101, "bot-a")])
    store.state[("clan-1", "members")] = {LEADER_TAG: {"name": "Tizio", "role": "leader"}}
    supervisor = FakeSupervisor(running=["bot-a"])
    update, query = pressed("b:stop:bot-a", user_id=USER)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert supervisor.stopped == []
    assert query.answers == [(IT.t("console.owner_only"), True)]


def test_il_capo_del_momento_ferma_il_bot_che_non_ha_creato():
    store = in_clan_store([make_bot("bot-a", owner_id=42)])
    supervisor = FakeSupervisor(running=["bot-a"])
    update, query = pressed("b:stop:bot-a", user_id=USER)
    asyncio.run(console.on_bot_callback(update, context(store, supervisor)))
    assert supervisor.stopped == [("bot-a", "owner_stopped")]


STRANIERO_TAG = "#QQ8L2P"
PRONTO = {"request_id": 7, "tag": TAG, "clan": CLAN}


def nasce(store, flow=None, user_id=USER, coc=None):
    supervisor = FakeSupervisor()
    ctx = context(store, supervisor, bot=FakeTelegramBot(), coc=coc or FakeCoc(),
                  user_data={} if flow is None else {"newbot": dict(flow)})
    update = born(user_id)
    asyncio.run(console.on_managed_created(update, ctx))
    return update, supervisor, ctx


def bottone(update):
    return any(isinstance(m, ReplyKeyboardMarkup) for _, m in update.effective_message.sent)


def test_il_capo_verificato_crea_il_bot_del_suo_clan():
    store = FakeStore(accounts=[account()])
    _, supervisor, ctx = nasce(store, PRONTO)
    assert len(store.added) == 1 and supervisor.started == [f"bot-{NEW_ID}"]
    assert "newbot" not in ctx.user_data


def test_il_membro_semplice_non_crea_nemmeno_col_flusso():
    store = FakeStore(accounts=[account(tag=MEMBER_TAG)])
    update, supervisor, ctx = nasce(store, PRONTO)
    assert store.added == [] and supervisor.started == []
    assert last(update) == IT.t("h.onboard_not_leader", clan=CLAN)
    assert "newbot" not in ctx.user_data


def test_il_capo_solo_rivendicato_non_passa_il_cancello():
    store = FakeStore(accounts=[account(verified=False)])
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert last(update) == render.onboard_ask_player(IT, CLAN) and not bottone(update)
    assert ctx.user_data["newbot"]["step"] == "player"


def test_il_capo_solo_rivendicato_non_crea():
    store = FakeStore(accounts=[account(verified=False)])
    update, supervisor, _ = nasce(store, PRONTO)
    assert store.added == [] and supervisor.started == []
    assert last(update) == IT.t("h.onboard_not_leader", clan=CLAN)


def test_il_clan_gia_servito_non_prende_un_secondo_bot_alla_nascita():
    store = FakeStore(accounts=[account()], taken="bot-a")
    update, supervisor, _ = nasce(store, PRONTO)
    assert store.added == [] and supervisor.started == []
    assert last(update) == IT.t("console.newbot_clan_taken")


def test_il_villaggio_di_un_altro_clan_non_apre_la_creazione():
    store = FakeStore(accounts=[account(tag=STRANIERO_TAG)])
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    asked = private()
    asyncio.run(console.cmd_newbot(asked, ctx))
    assert last(asked) == render.onboard_ask_player(IT, CLAN) and not bottone(asked)
    typed = private(text=STRANIERO_TAG)
    asyncio.run(console.on_newbot_text(typed, ctx))
    assert last(typed) == IT.t("h.onboard_not_leader", clan=CLAN) and not bottone(typed)
    update, supervisor, _ = nasce(store, PRONTO)
    assert store.added == [] and supervisor.started == []


def test_il_bandito_non_vede_nemmeno_il_bottone():
    store = FakeStore(accounts=[account()])
    asyncio.run(platform_ban.ban(store, USER, [], time.time()))
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert last(update) == IT.t("console.newbot_banned") and not bottone(update)
    assert "newbot" not in ctx.user_data


def test_nessun_tetto_di_tre_bot():
    assert not hasattr(console, "MAX_BOTS")
    rows = [make_bot(f"bot-{i}", bot_id=i) for i in range(3)]
    store = FakeStore(rows=rows, accounts=[account()])
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert bottone(update) and ctx.user_data["newbot"]["tag"] == TAG
    _, supervisor, _ = nasce(store, PRONTO)
    assert len(store.added) == 1 and supervisor.started == [f"bot-{NEW_ID}"]


def test_il_bot_nato_dal_link_senza_flusso_non_si_registra():
    store = FakeStore(accounts=[account()])
    update, supervisor, _ = nasce(store)
    assert store.added == [] and supervisor.started == []
    assert last(update) == IT.t("console.newbot_limit")


def test_il_flusso_a_meta_non_crea_il_bot():
    store = FakeStore()
    supervisor = FakeSupervisor()
    ctx = context(store, supervisor, coc=FakeCoc(), args=[TAG])
    asyncio.run(console.cmd_newbot(private(), ctx))
    assert ctx.user_data["newbot"]["step"] == "player"
    asyncio.run(console.on_managed_updated(managed(), ctx))
    assert store.added == [] and supervisor.started == []


def test_senza_la_rosa_ufficiale_la_nascita_aspetta():
    store, coc = FakeStore(accounts=[account()]), FakeCoc(error="maintenance")
    update, supervisor, ctx = nasce(store, PRONTO, coc=coc)
    assert store.added == [] and supervisor.started == []
    assert last(update) == IT.t("console.newbot_retry")
    assert ctx.user_data["newbot"]["tag"] == TAG and f"managed:{NEW_ID}" not in store.kv
    assert store.kv[f"retry:{NEW_ID}"] == {"user_id": USER, "username": NEW_NAME}
    coc.error = None
    retried, _ = pressed(f"b:retry:{NEW_ID}")
    asyncio.run(console.on_bot_callback(retried, ctx))
    assert [row[3] for row in store.added] == [NEW_ID] and supervisor.started == [f"bot-{NEW_ID}"]


def test_la_rosa_non_letta_non_parla_del_token():
    store, coc = FakeStore(accounts=[account()]), FakeCoc(error="maintenance")
    update, _, _ = nasce(store, PRONTO, coc=coc)
    detti = update.effective_message.sent
    assert [text for text, _ in detti] == [IT.t("api.maintenance"), IT.t("console.newbot_retry")]
    assert isinstance(detti[0][1], ReplyKeyboardRemove)


def test_il_membro_di_un_clan_servito_crea_il_bot_del_clan_che_guida():
    store = FakeStore(accounts=[account(tag=STRANIERO_TAG), account()])
    _, supervisor, _ = nasce(store, PRONTO)
    assert len(store.added) == 1 and supervisor.started == [f"bot-{NEW_ID}"]


def test_la_piattaforma_crea_anche_senza_flusso():
    store = FakeStore(owner=str(OWNER))
    _, supervisor, _ = nasce(store, user_id=OWNER)
    assert supervisor.started == [f"bot-{NEW_ID}"]


def test_la_regola_di_creazione_si_legge_in_ogni_lingua():
    for code in i18n.LANGUAGES:
        text = i18n.locale(code).t("console.newbot_limit")
        assert "/newbot" in text and "{n}" not in text and not text.startswith("["), code
    assert IT.t("console.newbot_limit") != EN.t("console.newbot_limit")


GIRI = 5


def nasce_ancora(store, giro, supervisor=None):
    ctx = context(store, supervisor or FakeSupervisor(), bot=FakeTelegramBot(), coc=FakeCoc(),
                  user_data={"newbot": dict(PRONTO)})
    update = born(bot_id=900 + giro, username=f"Clan{giro}Bot")
    asyncio.run(console.on_managed_created(update, ctx))
    return update


def scade(store):
    for key in [k for k in store.kv if k.startswith("ob:")]:
        del store.kv[key]


def test_il_bot_che_non_parte_tiene_il_clan_e_non_ne_nasce_un_secondo():
    store = FakeStore(accounts=[account()])
    visti = [nasce_ancora(store, giro, FakeSupervisor(starts=False)) for giro in range(GIRI)]
    assert [k for k in store.kv if k.startswith("ob:")] == []
    assert [row[3] for row in store.added] == [900]
    assert last(visti[-1]) == IT.t("console.newbot_clan_taken")


def test_scaduta_la_prenotazione_il_bot_senza_gruppo_tiene_ancora_il_clan():
    store = FakeStore(accounts=[account()])
    visti = []
    for giro in range(GIRI):
        visti.append(nasce_ancora(store, giro))
        scade(store)
    assert [row[3] for row in store.added] == [900]
    assert last(visti[-1]) == IT.t("console.newbot_clan_taken")


def test_il_cancello_rifiuta_il_clan_di_un_bot_nato_e_mai_portato_nel_gruppo():
    store = FakeStore(accounts=[account()])
    nasce(store, PRONTO)
    scade(store)
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert last(update) == IT.t("console.newbot_clan_taken") and not bottone(update)
    assert "newbot" not in ctx.user_data


def test_tolto_il_bot_senza_gruppo_il_clan_torna_libero():
    store = FakeStore(accounts=[account()])
    _, _, ctx = nasce(store, PRONTO)
    scade(store)
    tolto, _ = pressed(f"b:remove2:bot-{NEW_ID}")
    asyncio.run(console.on_bot_callback(tolto, ctx))
    assert store.removed == [f"bot-{NEW_ID}"] and asyncio.run(store.bot_for_tag(TAG)) is None
    nasce_ancora(store, 0)
    assert [row[3] for row in store.added] == [NEW_ID, 900]


VECCHIO = 41


def clan_tenuto(ruolo="member", accounts=None):
    mine = [account()] if accounts is None else list(accounts)
    store = FakeStore(rows=[make_bot("bot-vecchio", owner_id=VECCHIO, bot_id=800)],
                      accounts=mine + [account(VECCHIO, MEMBER_TAG)])
    store.born["bot-vecchio"] = TAG
    store.kv["ob:vecchio"] = {"tag": TAG, "name": CLAN, "user_id": VECCHIO, "bot_alias": "bot-vecchio"}
    return store, FakeCoc(roles=((LEADER_TAG, "leader"), (MEMBER_TAG, ruolo)))


def test_il_capo_di_adesso_passa_il_cancello_se_chi_tiene_il_bot_non_guida_piu():
    store, coc = clan_tenuto()
    ctx = context(store, coc=coc, args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert request_of(update).request_managed_bot.suggested_name == CLAN
    assert store.dropped == [] and store.born == {"bot-vecchio": TAG}


def test_il_capo_di_adesso_crea_il_suo_bot_e_quello_vecchio_resta_senza_clan():
    store, coc = clan_tenuto()
    _, supervisor, _ = nasce(store, PRONTO, coc=coc)
    nuovo = f"bot-{NEW_ID}"
    assert [row[3] for row in store.added] == [NEW_ID] and supervisor.started == [nuovo]
    assert [b.alias for b in store.rows] == ["bot-vecchio", nuovo] and store.removed == []
    assert store.dropped == ["bot-vecchio"] and store.born == {nuovo: TAG}
    assert asyncio.run(store.bot_for_tag(TAG)) == nuovo


def test_chi_tiene_il_bot_ed_e_ancora_co_capo_non_viene_scalzato():
    store, coc = clan_tenuto("coLeader")
    ctx = context(store, coc=coc, args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert last(update) == IT.t("console.newbot_clan_taken") and not bottone(update)
    nato, supervisor, _ = nasce(store, PRONTO, coc=coc)
    assert last(nato) == IT.t("console.newbot_clan_taken")
    assert store.added == [] and supervisor.started == []
    assert store.dropped == [] and store.born == {"bot-vecchio": TAG}


def test_il_membro_semplice_non_scalza_il_bot_di_chi_non_guida_piu():
    store, coc = clan_tenuto(accounts=[account(tag=STRANIERO_TAG)])
    update, supervisor, _ = nasce(store, PRONTO, coc=coc)
    assert last(update) == IT.t("h.onboard_not_leader", clan=CLAN)
    assert store.added == [] and supervisor.started == []
    assert store.dropped == [] and store.born == {"bot-vecchio": TAG}


def test_il_capo_solo_rivendicato_non_scalza_il_bot_di_chi_non_guida_piu():
    store, coc = clan_tenuto(accounts=[account(verified=False)])
    ctx = context(store, coc=coc, args=[TAG])
    asked = private()
    asyncio.run(console.cmd_newbot(asked, ctx))
    assert last(asked) == render.onboard_ask_player(IT, CLAN) and not bottone(asked)
    update, supervisor, _ = nasce(store, PRONTO, coc=coc)
    assert last(update) == IT.t("h.onboard_not_leader", clan=CLAN)
    assert store.added == [] and supervisor.started == []
    assert store.dropped == [] and store.born == {"bot-vecchio": TAG}


def test_il_bot_che_serve_gia_un_gruppo_non_si_scalza_mai():
    store, coc = clan_tenuto()
    store.clans = [make_clan("clan-1", -100, "bot-vecchio")]
    update, supervisor, _ = nasce(store, PRONTO, coc=coc)
    assert last(update) == IT.t("console.newbot_clan_taken")
    assert store.added == [] and store.dropped == []


def test_la_nascita_rifiutata_dal_deposito_lascia_il_clan_al_bot_vecchio():
    store, coc = clan_tenuto()
    store.add_error = ValueError("disabled")
    update, supervisor, _ = nasce(store, PRONTO, coc=coc)
    assert last(update) == IT.t("console.newbot_disabled")
    assert store.added == [] and supervisor.started == []
    assert store.dropped == [] and store.born == {"bot-vecchio": TAG}


def test_il_clan_passa_di_mano_dentro_la_nascita_del_bot_nuovo():
    store, coc = clan_tenuto()
    nasce(store, PRONTO, coc=coc)
    assert store.replaced == ["bot-vecchio"] and store.dropped == ["bot-vecchio"]
    assert store.born == {f"bot-{NEW_ID}": TAG}


def test_due_bot_del_gestore_per_lo_stesso_clan_il_secondo_nasce_senza_clan():
    store = FakeStore(owner=str(USER), accounts=[])
    for giro in range(2):
        nasce_ancora(store, giro)
    assert [row[3] for row in store.added] == [900, 901]
    assert store.born == {"bot-900": TAG} and store.replaced == [] and store.dropped == []


SERVITI = [
    {"code": "ab12cd", "name": "Clan <Uno>", "tag": "#2PP0", "level": 14, "members": 41, "free": 9,
     "league": "Crystal League I", "min_th": 13, "country": "IT", "lang": "it", "verified": True},
    {"code": "ef34gh", "name": None, "tag": None, "level": None, "members": 48, "free": 2,
     "verified": False},
]


class ServedStore(FakeStore):
    def __init__(self, served=SERVITI, **kw):
        super().__init__(**kw)
        self.served = list(served)
        self.asked = []

    async def recruit_board(self, limit=20, country=None, min_th=None, lang=None):
        self.asked.append((limit, country, min_th, lang))
        return self.served[:limit]


def porta(user_id, store):
    update = private(user_id)
    asyncio.run(console.cmd_start(update, context(store)))
    return update.effective_message.sent[0]


def tocca(data, store, user_id=USER, coc=None, where=None):
    update, query = pressed(data, user_id=user_id)
    if where:
        update.effective_chat = SimpleNamespace(id=-100, type=where)
    ctx = context(store, coc=coc)
    asyncio.run(console.on_home_callback(update, ctx))
    return update, query, ctx


def test_l_estraneo_che_apre_il_bot_clanboard_vede_solo_crea_ed_elenco():
    store = ServedStore(owner=str(OWNER))
    text, keyboard = porta(42, store)
    assert [(b.callback_data, b.text) for row in keyboard.inline_keyboard for b in row] == [
        ("home:new", IT.t("console.btn_create")), ("home:clans", IT.t("console.btn_clans"))]
    assert IT.t("console.attribution") in text
    assert store.asked == []
    for row in SERVITI:
        assert str(row["name"]) not in text and row["code"] not in text


def test_il_fondatore_vede_anche_la_board_ops():
    _, keyboard = porta(OWNER, ServedStore(owner=str(OWNER)))
    assert [(b.callback_data, b.text) for row in keyboard.inline_keyboard for b in row] == [
        ("home:new", IT.t("console.btn_create")), ("home:clans", IT.t("console.btn_clans")),
        ("panel:ops", IT.t("ops.btn"))]


def test_il_delegato_non_vede_la_board_ops():
    store = delegate_store()
    _, keyboard = porta(DELEGATE_ID, store)
    assert datas(keyboard) == ["home:new", "home:clans"]


def test_senza_gestore_scritto_nessuno_vede_la_board_ops():
    _, keyboard = porta(USER, ServedStore())
    assert datas(keyboard) == ["home:new", "home:clans"]


def test_il_bottone_crea_apre_il_flusso_di_creazione():
    update, query, ctx = tocca("home:new", ServedStore(), coc=FakeCoc())
    assert ctx.user_data["newbot"] == {"step": "tag"}
    assert last(update) == render.onboard_ask_clan(IT)
    assert query.answers == [(None, False)] and query.edits == []


def test_il_bandito_che_tocca_crea_resta_fuori():
    store = ServedStore()
    asyncio.run(platform_ban.ban(store, USER, [], time.time()))
    update, _, ctx = tocca("home:new", store, coc=FakeCoc())
    assert last(update) == IT.t("console.newbot_banned")
    assert "newbot" not in ctx.user_data


def test_l_elenco_dei_clan_serviti_legge_la_bacheca_e_mostra_nome_livello_membri_posti():
    store = ServedStore()
    _, query, _ = tocca("home:clans", store, user_id=42)
    assert store.asked == [(console.PAGE_SIZE, None, None, None)]
    text, keyboard = query.edits[-1]
    assert text == render.served_card(IT, SERVITI)
    assert IT.t("console.clans.title") in text
    assert IT.t("console.clans.row", name="Clan &lt;Uno&gt;", level=14, members=41, free=9) in text
    assert IT.t("console.clans.row", name=IT.t("web.board.anon", code="ef34gh"),
                level="?", members=48, free=2) in text
    assert datas(keyboard) == ["home:back"]


def test_nell_elenco_non_c_e_nessun_uid_ne_tag_ne_altro_della_scheda():
    store = ServedStore(owner=str(OWNER), rows=[make_bot("bot-a", owner_id=OWNER)],
                        clans=[make_clan("clan-1", 101, "bot-a")])
    _, query, _ = tocca("home:clans", store, user_id=42)
    text = query.edits[-1][0]
    assert "#" not in text and "2PP0" not in text
    assert "<Uno>" not in text
    for nascosto in ("Crystal", "TH13", "bot-a", "clan-1", str(OWNER), "101", IT.t("recruit.verified")):
        assert nascosto not in text, nascosto


def test_l_elenco_vuoto_lo_dice_con_la_frase_della_bacheca():
    _, query, _ = tocca("home:clans", ServedStore(served=[]))
    text, keyboard = query.edits[-1]
    assert IT.t("web.board.empty") in text and datas(keyboard) == ["home:back"]


def test_dall_elenco_si_torna_alla_porta_con_i_bottoni_di_chi_guarda():
    store = ServedStore(owner=str(OWNER))
    _, query, _ = tocca("home:back", store, user_id=42)
    text, keyboard = query.edits[-1]
    assert IT.t("console.start") in text and datas(keyboard) == ["home:new", "home:clans"]
    _, mio, _ = tocca("home:back", store, user_id=OWNER)
    assert datas(mio.edits[-1][1]) == ["home:new", "home:clans", "panel:ops"]


def test_l_estraneo_che_forza_il_bottone_ops_dalla_porta_resta_fuori():
    store = ServedStore(owner=str(OWNER))
    update, query = pressed("panel:ops", user_id=42)
    asyncio.run(console.on_panel_callback(update, context(store)))
    assert query.edits == [] and query.answers[-1] == (IT.t("console.owner_only"), True)


@pytest.mark.parametrize("data", ["home:new", "home:clans", "home:back"])
def test_fuori_dalla_chat_privata_i_bottoni_della_porta_non_fanno_niente(data):
    store = ServedStore()
    update, query, ctx = tocca(data, store, coc=FakeCoc(), where=ChatType.SUPERGROUP)
    assert query.edits == [] and update.effective_message.sent == []
    assert store.asked == [] and ctx.user_data == {}
    assert len(query.answers) == 1


@pytest.mark.parametrize("data", ["home:", "home:ops", "home:clans:#2PP0", "home:scheda:clan-1"])
def test_un_gesto_della_porta_che_non_esiste_non_apre_niente(data):
    store = ServedStore(owner=str(OWNER))
    update, query, ctx = tocca(data, store, user_id=42)
    assert query.edits == [] and update.effective_message.sent == []
    assert store.asked == [] and len(query.answers) == 1


def test_la_porta_e_registrata_fra_i_gesti_del_bot_clanboard():
    app = SimpleNamespace(handlers=[], add_handler=lambda handler: app.handlers.append(handler))
    console.register(app)
    assert console.on_home_callback in [h.callback for h in app.handlers]


def test_nessun_nome_di_clan_e_scritto_nel_codice_della_porta():
    radice =Path(console.__file__).parent
    for nome in ("console.py", "render.py", "web/app.py"):
        assert "futuro" not in (radice / nome).read_text(encoding="utf-8").casefold(), nome
    assert "futuro" not in render.served_card(IT, SERVITI).casefold()


GRUPPO_SITO = "https://t.me/clanboard_gruppo"
CODICE_SITO = "ab12cd"
SITO_SCRIVE = ("panel:siteset:community_url", "panel:siteset:example_code",
               "panel:siteclear:community_url", "panel:siteclear:example_code")


def site_store(codici=(CODICE_SITO,), scelte=None):
    store = delegate_store()
    store.chieste = []

    async def web_page(slug, kind):
        store.chieste.append((slug, kind))
        return {"clan": {"name": "Uno"}} if slug in codici and kind == "public" else None

    store.web_page = web_page
    if scelte is not None:
        store.kv[conf().KEY] = dict(scelte)
    return store


def site_app(store=None, aperta=True):
    store = store or site_store()
    con_codice(store, OWNER, aperta=aperta)
    con_codice(store, DELEGATE_ID, aperta=aperta)
    return ConsoleApp(store=store, coc=key_pool())


def tocca_sito(app, data, user_id=OWNER):
    update, query = pressed(data, user_id=user_id)
    asyncio.run(console.on_panel_callback(update, app.context))
    return query


def scrive_sito(app, text, user_id=OWNER):
    written, ctx = app.update_from(user_id=user_id, text=text)
    asyncio.run(console.on_newbot_text(written, ctx))
    return written


def test_le_impostazioni_del_sito_nascono_vuote_e_sono_solo_due():
    store = site_store()
    assert conf().FIELDS == ("community_url", "example_code")
    assert asyncio.run(conf().read(store)) == {"community_url": "", "example_code": ""}
    assert conf().KEY not in store.kv
    for storta in ("testo", ["x"], {"community_url": 7, "example_code": ["a"]},
                   {"community_url": "https://example.org/x", "example_code": "../x"},
                   {"altro": "valore"}):
        store.kv[conf().KEY] = storta
        assert asyncio.run(conf().read(store)) == {"community_url": "", "example_code": ""}
    assert asyncio.run(conf().write(store, "channel_url", GRUPPO_SITO)) is False
    assert asyncio.run(conf().write(store, "owner_id", "1")) is False


def test_il_link_del_gruppo_e_di_telegram_come_quello_della_riga_di_comando():
    for buono in (GRUPPO_SITO, "https://t.me/+AbCdEf", "https://t.me/c/12/3"):
        assert conf().clean("community_url", buono) == buono
        assert cli.valid_channel_url(buono)
    for brutto in ("https://example.org/canale", "http://t.me/x", "t.me/x", "", None, 7,
                   "https://t.me/x y", "javascript:alert(1)"):
        assert conf().clean("community_url", brutto) == "", brutto
    for buono in (CODICE_SITO, "ABCDEF0123456789"):
        assert conf().clean("example_code", buono) == buono
    for brutto in ("", None, "ab 12", "../x", "a" * 17, "<b>", "ab12cd/widget", 12):
        assert conf().clean("example_code", brutto) == "", brutto
    assert conf().clean("altro", "x") == ""


INGANNI_TELEGRAM = ("https://evil.example\\@t.me/x", "https://user:pw@t.me/x",
                    "https://t.me@evil.example/x", "https://t.me:8443/x", "https://t.me/x\x00",
                    "https://t.me/x‮", "https://t.me/", "https://t.me\\@evil.example/x")


def test_un_link_che_il_browser_legge_altrove_non_passa_per_telegram():
    for brutto in INGANNI_TELEGRAM:
        assert conf().clean("community_url", brutto) == "", repr(brutto)
        assert not cli.valid_channel_url(brutto), repr(brutto)
    for buono in ("https://t.me/joinchat/Ab-c_1", "https://t.me/+AbCdEf", GRUPPO_SITO):
        assert conf().clean("community_url", buono) == buono
        assert cli.valid_channel_url(buono)


def test_dal_pannello_un_link_che_il_browser_legge_altrove_non_si_salva():
    for brutto in INGANNI_TELEGRAM:
        app = site_app()
        tocca_sito(app, "panel:siteset:community_url")
        written = scrive_sito(app, brutto)
        assert IT.t("panel.site.bad") in written.effective_message.sent[-1][0], repr(brutto)
        assert conf().KEY not in app.store.kv, repr(brutto)


def test_il_fondatore_trova_il_sito_nel_pannello_e_il_delegato_no(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "SAMPLES", str(tmp_path / "manca.jsonl"))
    app = site_app()
    update, ctx = app.update_from(user_id=OWNER, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    bottoni = [(b.callback_data, b.text) for row in
               update.effective_message.sent[-1][1].inline_keyboard for b in row]
    assert ("panel:site", IT.t("panel.site.btn")) in bottoni
    update, ctx = app.update_from(user_id=DELEGATE_ID, text="/pannello")
    asyncio.run(console.cmd_panel(update, ctx))
    assert "panel:site" not in datas(update.effective_message.sent[-1][1])


def test_la_scheda_del_sito_mostra_le_due_impostazioni_vuote(monkeypatch, tmp_path):
    app = site_app()
    query = tocca_sito(app, "panel:site")
    text, keyboard = query.edits[-1]
    assert IT.t("panel.site.title") in text
    assert IT.t("panel.site.group", value=IT.t("panel.site.none")) in text
    assert IT.t("panel.site.example", value=IT.t("panel.site.none")) in text
    assert datas(keyboard) == ["panel:siteset:community_url", "panel:siteset:example_code",
                               "panel:refresh"]
    assert conf().KEY not in app.store.kv


def test_il_fondatore_mette_il_gruppo_dal_pannello_e_poi_lo_toglie():
    app = site_app()
    query = tocca_sito(app, "panel:siteset:community_url")
    assert IT.t("panel.site.ask_group") in query.edits[-1][0]
    assert datas(query.edits[-1][1]) == ["panel:site"]
    assert app.context.user_data["site"] == "community_url"
    written = scrive_sito(app, f"  {GRUPPO_SITO}  ")
    text, keyboard = written.effective_message.sent[-1]
    assert app.store.kv[conf().KEY] == {"community_url": GRUPPO_SITO, "example_code": ""}
    assert IT.t("panel.site.group", value=GRUPPO_SITO) in text
    assert datas(keyboard) == ["panel:siteset:community_url", "panel:siteclear:community_url",
                               "panel:siteset:example_code", "panel:refresh"]
    assert "site" not in app.context.user_data
    query = tocca_sito(app, "panel:siteclear:community_url")
    assert app.store.kv[conf().KEY] == {"community_url": "", "example_code": ""}
    assert IT.t("panel.site.group", value=IT.t("panel.site.none")) in query.edits[-1][0]
    assert "panel:siteclear:community_url" not in datas(query.edits[-1][1])


def test_il_fondatore_sceglie_il_clan_d_esempio_fra_le_pagine_che_esistono():
    app = site_app(site_store(scelte={"community_url": GRUPPO_SITO}))
    query = tocca_sito(app, "panel:siteset:example_code")
    assert IT.t("panel.site.ask_example") in query.edits[-1][0]
    assert app.context.user_data["site"] == "example_code"
    written = scrive_sito(app, CODICE_SITO)
    text, keyboard = written.effective_message.sent[-1]
    assert app.store.kv[conf().KEY] == {"community_url": GRUPPO_SITO,
                                           "example_code": CODICE_SITO}
    assert app.store.chieste == [(CODICE_SITO, "public")]
    assert IT.t("panel.site.example", value=CODICE_SITO) in text
    assert datas(keyboard) == ["panel:siteset:community_url", "panel:siteclear:community_url",
                               "panel:siteset:example_code", "panel:siteclear:example_code",
                               "panel:refresh"]
    query = tocca_sito(app, "panel:siteclear:example_code")
    assert app.store.kv[conf().KEY] == {"community_url": GRUPPO_SITO, "example_code": ""}


@pytest.mark.parametrize("campo,storto", [
    ("community_url", "https://example.org/gruppo"), ("community_url", "http://t.me/x"),
    ("community_url", "ciao"), ("example_code", "zz99zz"), ("example_code", "../ab12cd"),
    ("example_code", "ab12cd/widget"), ("example_code", "a" * 40)])
def test_un_valore_storto_non_si_salva_e_il_pannello_richiede(campo, storto):
    app = site_app()
    tocca_sito(app, f"panel:siteset:{campo}")
    written = scrive_sito(app, storto)
    text, keyboard = written.effective_message.sent[-1]
    assert IT.t("panel.site.bad") in text
    assert datas(keyboard) == ["panel:site"]
    assert app.context.user_data["site"] == campo
    assert conf().KEY not in app.store.kv


def test_chi_non_e_il_fondatore_non_apre_e_non_scrive_le_impostazioni_del_sito():
    for uid, motivo in ((USER, "console.owner_only"), (DELEGATE_ID, "console.not_owner")):
        app = site_app(site_store(scelte={"community_url": GRUPPO_SITO,
                                          "example_code": CODICE_SITO}))
        for data in ("panel:site",) + SITO_SCRIVE + ("panel:siteset:owner_id",):
            query = tocca_sito(app, data, user_id=uid)
            assert query.edits == [], (uid, data)
            assert query.answers == [(IT.t(motivo), True)], (uid, data)
        assert "site" not in app.context.user_data
        assert app.store.kv[conf().KEY] == {"community_url": GRUPPO_SITO,
                                               "example_code": CODICE_SITO}


def test_chi_non_e_il_fondatore_non_scrive_nemmeno_con_la_domanda_gia_aperta():
    for uid in (USER, DELEGATE_ID):
        app = site_app()
        app.context.user_data["site"] = "community_url"
        written = scrive_sito(app, GRUPPO_SITO, user_id=uid)
        assert conf().KEY not in app.store.kv, uid
        assert "site" not in app.context.user_data, uid
        assert all(GRUPPO_SITO not in text for text, _ in written.effective_message.sent), uid


def test_un_campo_che_non_esiste_non_apre_nessuna_domanda():
    app = site_app()
    for data in ("panel:siteset:channel_url", "panel:siteset:", "panel:siteset",
                 "panel:siteclear:owner_id", "panel:siteclear"):
        query = tocca_sito(app, data)
        assert IT.t("panel.site.title") in query.edits[-1][0], data
        assert "site" not in app.context.user_data, data
    assert conf().KEY not in app.store.kv
    app.context.user_data["site"] = "channel_url"
    scrive_sito(app, GRUPPO_SITO)
    assert conf().KEY not in app.store.kv


def test_con_la_finestra_chiusa_le_impostazioni_del_sito_chiedono_il_codice():
    store = site_store(scelte={"community_url": GRUPPO_SITO, "example_code": CODICE_SITO})
    app = site_app(store, aperta=False)
    for data in SITO_SCRIVE:
        query = tocca_sito(app, data)
        assert IT.t("otp.ask") in query.edits[-1][0], data
    assert "site" not in app.context.user_data
    assert store.kv[conf().KEY] == {"community_url": GRUPPO_SITO, "example_code": CODICE_SITO}
    assert IT.t("panel.site.title") in tocca_sito(app, "panel:site").edits[-1][0]
    app.context.user_data.pop("otp", None)
    app.context.user_data["site"] = "community_url"
    written = scrive_sito(app, "https://t.me/altro")
    assert store.kv[conf().KEY]["community_url"] == GRUPPO_SITO
    assert IT.t("otp.ask") in written.effective_message.sent[-1][0]


def test_la_domanda_del_sito_non_si_scambia_con_le_altre_del_pannello():
    app = site_app()
    tocca_sito(app, "panel:siteset:community_url")
    tocca_sito(app, "panel:mediaadd")
    assert "site" not in app.context.user_data and app.context.user_data["media"] is True
    tocca_sito(app, "panel:siteset:example_code")
    assert "media" not in app.context.user_data
    assert app.context.user_data["site"] == "example_code"
    tocca_sito(app, "panel:site")
    assert "site" not in app.context.user_data


def test_togliere_un_impostazione_del_sito_non_cancella_nessuna_riga():
    store = site_store(scelte={"community_url": GRUPPO_SITO, "example_code": CODICE_SITO})
    cancellate = []

    async def kv_del(key):
        cancellate.append(key)

    async def delete_secret(kind):
        cancellate.append(kind)

    store.kv_del = kv_del
    store.delete_secret = delete_secret
    app = site_app(store)
    tocca_sito(app, "panel:siteclear:community_url")
    tocca_sito(app, "panel:siteclear:example_code")
    assert cancellate == []
    assert store.kv[conf().KEY] == {"community_url": "", "example_code": ""}
