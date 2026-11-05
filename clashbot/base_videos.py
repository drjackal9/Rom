import asyncio
import logging
import re
from datetime import datetime, time, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

from . import bases
from .media import TRAILING, URLS
from .retention import WAR_HISTORY_KEEP
from .web.http import READ_TIMEOUT

log = logging.getLogger("clashbot.base_videos")

API = "https://www.googleapis.com/youtube/v3"
CHANNELS_PATH = "channels"
ITEMS_PATH = "playlistItems"
CHANNEL_PART = "contentDetails"
ITEM_PART = "snippet"
TITLE_PART = "snippet"
KEY_PARAM = "key"
HANDLE_PARAM = "forHandle"
ID_START = "UC"
ID_EXTRA = "-_"
HANDLE_MARK = "@"
SCHEME = "https"
HOSTS = ("www.youtube.com", "youtube.com", "m.youtube.com")
SECRET = "youtube_key"
CHANNELS_KEY = "media_channels"
UPLOADS_KEY = "media_uploads:"
QUOTA_KEY = "media_quota_until"
STATE_KIND = "media"
STATE_FIELD = "channels"
OFFICIAL = "official"
PLATFORM = "platform"
FRESH = "fresh"
QUOTA = "quota"
DOWN = "down"
NOKEY = "nokey"
OK_STATUS = 200
FORBIDDEN = 403
QUOTA_REASON = "quotaExceeded"
PAGE_MAX = 50
PACIFIC = "America/Los_Angeles"
WATCH = "https://www.youtube.com/watch?v="
THUMB_HOST = "https://i.ytimg.com"
THUMB = THUMB_HOST + "/vi/"
THUMB_SIZE = "/mqdefault.jpg"
HALL_RE = re.compile(r"\bTH(\d{1,2})\b", re.IGNORECASE)


def masked(url):
    parts = urlsplit(str(url or ""))
    kept = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True)
            if name != KEY_PARAM]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def call_url(path, params, key):
    return f"{API}/{path}?{urlencode({**params, KEY_PARAM: key})}"


def links_in(text):
    found = []
    for raw in URLS.findall(str(text or "")):
        url = raw.rstrip(TRAILING)
        if bases.parse_link(url) and url not in found:
            found.append(url)
    return found


def marked(row, on):
    found = {"id": row["id"], "title": row.get("title") or ""}
    if on:
        found[OFFICIAL] = True
    return found


def official_in(rows):
    for row in rows or ():
        if row.get(OFFICIAL):
            return row["id"]
    return None


def clean(rows):
    kept, seen = [], set()
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        found = str(row.get("id") or "").strip()
        if not found or found in seen:
            continue
        seen.add(found)
        kept.append(marked({"id": found, "title": str(row.get("title") or "")},
                           bool(row.get(OFFICIAL))))
    return kept


def channel_of(raw):
    found = str(raw or "").strip()
    if not found.startswith(ID_START) or not found.isascii():
        return None
    return found if all(ch.isalnum() or ch in ID_EXTRA for ch in found) else None


def handle_of(raw):
    try:
        parts = urlsplit(str(raw or "").strip())
    except ValueError:
        return None
    if parts.scheme != SCHEME or (parts.hostname or "").lower() not in HOSTS:
        return None
    first = parts.path.strip("/").split("/")[0]
    return first if first.startswith(HANDLE_MARK) and first[1:] else None


def channel_in(body):
    for item in (body if isinstance(body, dict) else {}).get("items") or ():
        found = str((item or {}).get("id") or "").strip()
        if found:
            snippet = (item or {}).get(TITLE_PART) or {}
            return {"id": found, "title": str(snippet.get("title") or "")}
    return None


def per_channel(count):
    return max(1, min(WAR_HISTORY_KEEP // max(1, count), PAGE_MAX))


def next_reset(now):
    zone = ZoneInfo(PACIFIC)
    local = datetime.fromtimestamp(float(now), zone)
    return datetime.combine(local.date() + timedelta(days=1), time(), tzinfo=zone).timestamp()


def quota_hit(status, body):
    if status != FORBIDDEN:
        return False
    errors = ((body if isinstance(body, dict) else {}).get("error") or {}).get("errors") or ()
    return any(str((item or {}).get("reason")) == QUOTA_REASON for item in errors)


def playlist_of(body):
    for item in (body if isinstance(body, dict) else {}).get("items") or ():
        related = ((item or {}).get(CHANNEL_PART) or {}).get("relatedPlaylists") or {}
        found = str(related.get("uploads") or "").strip()
        if found:
            return found
    return None


def videos_of(body, channel, scopes):
    rows = []
    for item in (body if isinstance(body, dict) else {}).get("items") or ():
        snippet = (item or {}).get(ITEM_PART) or {}
        video = str((snippet.get("resourceId") or {}).get("videoId") or "").strip()
        if not video:
            continue
        found = {"channel": channel, "title": str(snippet.get("title") or ""),
                 "published": str(snippet.get("publishedAt") or ""),
                 "links": links_in(snippet.get("description"))}
        rows.extend({"id": video, "scope": scope, **found} for scope in scopes)
    return rows


def attack_videos(rows):
    found = {}
    for row in rows or ():
        for hall in dict.fromkeys(HALL_RE.findall(str(row.get("title") or ""))):
            found.setdefault(str(int(hall)), []).append(
                {"video_id": row.get("id"), "title": row.get("title"),
                 "channel": row.get("channel")})
    return found


async def api_key(store):
    try:
        return await store.get_secret(SECRET)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("chiave dei video non letta (%s)", type(e).__name__)
        return None


async def stored_channels(store, alias):
    state = await store.get_state(alias, STATE_KIND)
    if isinstance(state, dict):
        return state.get(STATE_FIELD)
    return state


async def platform_rows(store):
    return clean(await store.kv_get(CHANNELS_KEY))


async def add_channel(store, row):
    rows = await platform_rows(store)
    if any(found["id"] == row["id"] for found in rows):
        return False
    await store.kv_set(CHANNELS_KEY, rows + [row])
    return True


async def mark_official(store, channel):
    rows = await platform_rows(store)
    if not any(row["id"] == channel for row in rows):
        return False
    picked = channel if official_in(rows) != channel else None
    await store.kv_set(CHANNELS_KEY, [marked(row, row["id"] == picked) for row in rows])
    return True


async def stopped_by_quota(store, now):
    stopped = await store.kv_get(QUOTA_KEY) or {}
    return bool(stopped.get("until") and float(now) < float(stopped["until"]))


async def drop_channel(store, channel):
    rows = await platform_rows(store)
    kept = [row for row in rows if row["id"] != channel]
    if len(kept) == len(rows):
        return False
    await store.kv_set(CHANNELS_KEY, kept)
    return True


async def channels(store):
    clans = {}
    for clan in await store.active_clans():
        rows = clean(await stored_channels(store, clan.alias))
        if rows:
            clans[clan.alias] = rows
    return {"platform": await platform_rows(store), "clans": clans}


async def targets_of(store):
    found = await channels(store)
    targets = {}
    for row in found["platform"]:
        targets.setdefault(row["id"], []).append(PLATFORM)
    for alias, rows in found["clans"].items():
        for row in rows:
            targets.setdefault(row["id"], []).append(alias)
    return targets


async def ask(client, url):
    try:
        answer = await client.get(url, timeout=READ_TIMEOUT)
        status = int(answer.status_code)
        try:
            body = answer.json()
        except Exception:
            body = None
        return status, body
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("%s non letto (%s)", masked(url), type(e).__name__)
        return None


async def by_handle(client, key, handle):
    answer = await ask(client, call_url(CHANNELS_PATH,
                                        {"part": TITLE_PART, HANDLE_PARAM: handle}, key))
    if answer is None:
        return None
    status, body = answer
    if status != OK_STATUS:
        log.warning("canale del nome non letto (stato %s)", status)
        return None
    return channel_in(body)


async def found_channel(store, raw, client=None):
    picked = channel_of(raw)
    if picked:
        return {"id": picked, "title": ""}
    handle = handle_of(raw)
    if not handle:
        return None
    key = await api_key(store)
    if not key:
        return None
    owned = client is None
    client = client or httpx.AsyncClient(timeout=READ_TIMEOUT)
    try:
        return await by_handle(client, key, handle)
    finally:
        if owned:
            await client.aclose()


async def uploads_of(store, client, key, channel):
    stored = await store.kv_get(UPLOADS_KEY + channel) or {}
    if stored.get("playlist"):
        return stored["playlist"], None
    answer = await ask(client, call_url(CHANNELS_PATH, {"part": CHANNEL_PART, "id": channel}, key))
    if answer is None:
        return None, DOWN
    status, body = answer
    if quota_hit(status, body):
        return None, QUOTA
    playlist = playlist_of(body) if status == OK_STATUS else None
    if not playlist:
        log.warning("canale %s senza playlist dei caricamenti (stato %s)", channel, status)
        return None, DOWN
    await store.kv_set(UPLOADS_KEY + channel, {"playlist": playlist})
    return playlist, None


async def channel_rows(store, client, key, channel, scopes, cap):
    playlist, problem = await uploads_of(store, client, key, channel)
    if problem:
        return [], problem
    answer = await ask(client, call_url(
        ITEMS_PATH, {"part": ITEM_PART, "maxResults": cap, "playlistId": playlist}, key))
    if answer is None:
        return [], DOWN
    status, body = answer
    if quota_hit(status, body):
        return [], QUOTA
    if status != OK_STATUS:
        log.warning("caricamenti del canale %s non letti (stato %s)", channel, status)
        return [], DOWN
    return videos_of(body, channel, scopes), None


async def round_of(store, client, key, now):
    if not key:
        return {"status": NOKEY, "videos": 0}
    if await stopped_by_quota(store, now):
        return {"status": QUOTA, "videos": 0}
    targets = await targets_of(store)
    if not targets:
        return {"status": FRESH, "videos": 0}
    cap = per_channel(len(targets))
    rows, failed, over = [], 0, False
    for channel, scopes in targets.items():
        found, problem = await channel_rows(store, client, key, channel, scopes, cap)
        if problem == QUOTA:
            await store.kv_set(QUOTA_KEY, {"until": next_reset(now)})
            over = True
            break
        if problem:
            failed += 1
        rows.extend(found)
    saved = await store.videos_put(rows) if rows else 0
    if over:
        return {"status": QUOTA, "videos": saved}
    if failed and not rows:
        return {"status": DOWN, "videos": 0}
    return {"status": FRESH, "videos": saved}


async def refresh(store, client, key, now):
    try:
        return await round_of(store, client, key, now)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("video delle basi non aggiornati (%s)", type(e).__name__)
        return {"status": DOWN, "videos": 0}
