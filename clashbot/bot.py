import asyncio
import hashlib
import json
import logging

from telegram import (BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
                      LinkPreviewOptions, Update)
from telegram.constants import ParseMode
from telegram.error import NetworkError, RetryAfter
from telegram.ext import Application, Defaults

from . import i18n
from .handlers import COMMANDS, register

log = logging.getLogger("clashbot")

TELEGRAM_CODES = {"pt-BR": "pt", "zh-Hans": "zh"}
PROFILE_GAP = 0.5
RETRY_PAUSE = 2.0
CONSOLE = "console"
SINGLE = "single"


def telegram_code(code):
    if code in TELEGRAM_CODES:
        return TELEGRAM_CODES[code]
    return code if len(code) == 2 else None


WORKER_SCOPES = (BotCommandScopeAllPrivateChats(), BotCommandScopeAllGroupChats())
CONSOLE_SCOPES = (None,)

WORKER_PROFILE = ([name for name, _ in COMMANDS], "cmd", "bot.short", "bot.description",
                  WORKER_SCOPES)
CONSOLE_PROFILE = (["start", "newbot", "mybots", "support", "help", "cancel"], "console.cmd", "console.short", "console.description", CONSOLE_SCOPES)


def profile_payload(L, profile=WORKER_PROFILE):
    names, prefix, short, description, scopes = profile
    payload = {
        "commands": [[name, L.t(f"{prefix}.{name}")] for name in names],
        "short": L.t(short),
        "description": L.t(description),
    }
    scoped = [scope.type for scope in scopes if scope]
    if scoped:
        payload["scope"] = scoped
    return payload


def profile_digest(L, profile=WORKER_PROFILE):
    payload = profile_payload(L, profile)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def with_retry(action):
    try:
        return await action()
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
    except NetworkError:
        await asyncio.sleep(RETRY_PAUSE)
    return await action()


async def publish_commands(bot, commands, scopes, language):
    await with_retry(lambda: bot.set_my_commands(commands, scope=scopes[0], language_code=language))
    for scope in scopes[1:]:
        await with_retry(lambda: bot.set_my_commands([], scope=scope, language_code=language))


async def publish_profile(bot, store, profile=WORKER_PROFILE):
    names, prefix, short, description, scopes = profile
    for code in [None] + [c for c in i18n.LANGUAGES if c != "en"]:
        language = telegram_code(code) if code else None
        if code and not language:
            continue
        L = i18n.locale(code)
        key = f"profile:{bot.id}:{language or 'default'}"
        digest = profile_digest(L, profile)
        try:
            if await store.kv_get(key) == digest:
                continue
            commands = [BotCommand(name, L.t(f"{prefix}.{name}")) for name in names]
            await publish_commands(bot, commands, scopes, language)
            await with_retry(lambda: bot.set_my_short_description(L.t(short), language_code=language))
            await with_retry(lambda: bot.set_my_description(L.t(description), language_code=language))
            await store.kv_set(key, digest)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("profilo bot non aggiornato per %s: %s", language or "default", e)
        await asyncio.sleep(PROFILE_GAP)


def defaults():
    return Defaults(parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True))


def scope(alias):
    return None if alias == SINGLE else alias


def build_worker_app(token, store, coc, supervisor, alias):
    async def post_init(app):
        app.bot_data["profile_task"] = asyncio.create_task(publish_profile(app.bot, store))

    async def post_shutdown(app):
        task = app.bot_data.get("profile_task")
        if task:
            task.cancel()

    app = (
        Application.builder()
        .token(token)
        .defaults(defaults())
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.bot_data.update({"store": store, "coc": coc, "supervisor": supervisor, "bot_alias": scope(alias)})
    register(app)
    return app


def build_console_app(token, store, coc, supervisor):
    from . import console

    async def post_init(app):
        app.bot_data["profile_task"] = asyncio.create_task(publish_profile(app.bot, store, CONSOLE_PROFILE))

    async def post_shutdown(app):
        task = app.bot_data.get("profile_task")
        if task:
            task.cancel()

    app = (
        Application.builder()
        .token(token)
        .defaults(defaults())
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.bot_data.update({"store": store, "coc": coc, "supervisor": supervisor, "bot_alias": CONSOLE})
    console.register(app)
    return app


ALLOWED_UPDATES = [
    Update.MESSAGE,
    Update.CHANNEL_POST,
    Update.CALLBACK_QUERY,
    Update.PRE_CHECKOUT_QUERY,
    Update.INLINE_QUERY,
    Update.MY_CHAT_MEMBER,
    Update.POLL,
    Update.POLL_ANSWER,
    Update.MANAGED_BOT,
    Update.CHAT_JOIN_REQUEST,
]
