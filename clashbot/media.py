import asyncio
import hashlib
import logging
import re
import time
from urllib.parse import urlsplit

import httpx
from telegram import LinkPreviewOptions
from telegram.error import BadRequest, TelegramError

from . import cards
from .ttl import MANAGED_TTL

log = logging.getLogger("clashbot.media")

BADGE_HOST = "api-assets.clashofclans.com"
BADGE_LIMIT = 512 * 1024
BADGE_TIMEOUT = 10
BADGE_MEMO = 64
CAPTION_LIMIT = 1024
CARD_TTL = 30 * 86400
PREVIEW_HOSTS = ("t.me", "telegram.me")
SITE_TTL = MANAGED_TTL
URLS = re.compile(r"https://[^\s<>\"']+")
TRAILING = ".,;:!?)«»"

_BADGES = {}
_SITE = {"value": None, "at": None}


def forget():
    _BADGES.clear()
    _SITE.update({"value": None, "at": None})


def host(url):
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    if parts.scheme != "https":
        return None
    return (parts.hostname or "").lower() or None


async def badge(url, client=None):
    if not url or host(url) != BADGE_HOST:
        return None
    if url in _BADGES:
        return _BADGES[url]
    owned = client is None
    client = client or httpx.AsyncClient(timeout=BADGE_TIMEOUT)
    data = None
    try:
        response = await client.get(url)
        content = response.content
        if (response.status_code == 200 and len(content) <= BADGE_LIMIT
                and response.headers.get("content-type", "").startswith("image/")):
            data = content
    except httpx.HTTPError as error:
        log.warning("stemma non scaricato: %s", type(error).__name__)
    finally:
        if owned:
            await client.aclose()
    if len(_BADGES) >= BADGE_MEMO:
        _BADGES.clear()
    _BADGES[url] = data
    return data


def units(text):
    return len(str(text or "").encode("utf-16-le")) // 2


def caption(text):
    body = str(text or "")
    if units(body) <= CAPTION_LIMIT:
        return body, None
    head, _, rest = body.partition("\n")
    if units(head) <= CAPTION_LIMIT:
        return head, rest.strip("\n") or None
    while head and units(head) > CAPTION_LIMIT:
        head = head[:-1]
    return head, body


def _key(alias, png):
    return f"card:{alias}:{hashlib.sha256(png).hexdigest()[:32]}"


def _file_id(message):
    photos = getattr(message, "photo", None) or ()
    return photos[-1].file_id if photos else None


async def _deliver(send, store, key, png):
    cached = await store.kv_get(key) or {}
    for photo in ([cached["file_id"]] if cached.get("file_id") else []) + [png]:
        try:
            sent = await send(photo)
        except BadRequest as error:
            log.warning("card rifiutata: %s", error)
            await store.kv_del(key)
            continue
        except TelegramError as error:
            log.warning("card non inviata: %s", error)
            return False
        if photo is png:
            found = _file_id(sent)
            if found:
                await store.kv_set(key, {"file_id": found}, ttl=CARD_TTL)
        return True
    return False


async def send_card(bot, store, alias, chat_id, png, text, quiet=False, thread_id=None):
    extra = {"disable_notification": quiet}
    if thread_id:
        extra["message_thread_id"] = thread_id

    async def send(photo):
        return await bot.send_photo(chat_id, photo, caption=text or None, **extra)

    return await _deliver(send, store, _key(alias, png), png)


async def reply_card(message, store, alias, png, text):
    async def send(photo):
        return await message.reply_photo(photo, caption=text or None)

    return await _deliver(send, store, _key(alias, png), png)


async def render_card(spec, badge_url):
    return await asyncio.to_thread(cards.draw, spec, await badge(badge_url))


async def site_base(store):
    now = time.monotonic()
    if _SITE["at"] is not None and now - _SITE["at"] < SITE_TTL:
        return _SITE["value"]
    _SITE["value"] = await store.get_secret("site_base")
    _SITE["at"] = now
    return _SITE["value"]


def hosts(base=None):
    site = host(base)
    return PREVIEW_HOSTS + ((site,) if site else ())


def preview(text, base=None):
    allowed = hosts(base)
    for found in URLS.findall(str(text or "")):
        url = found.rstrip(TRAILING)
        if host(url) in allowed:
            return LinkPreviewOptions(is_disabled=False, url=url, prefer_large_media=True)
    return LinkPreviewOptions(is_disabled=True)


async def reply(message, store, text, **kw):
    return await message.reply_text(text, link_preview_options=preview(text, await site_base(store)), **kw)


async def card_reply(message, store, alias, spec, badge_url, text):
    png = await render_card(spec, badge_url)
    head, rest = caption(text)
    if not await reply_card(message, store, alias, png, head):
        return False
    if rest:
        await reply(message, store, rest)
    return True
