import asyncio
import logging

from . import agenda, base_videos
from .more_lists import newest
from .retention import WAR_HISTORY_KEEP
from .util import parse_coc_time

log = logging.getLogger("clashbot.news_feed")

ROWS_KEY = "news:rows"
SEASON_KEY = "goldpass"
SEASON_TTL = 86400
VIDEO = "video"
GOLDPASS = "goldpass"
EVENT = "event"
KINDS = (VIDEO, GOLDPASS, EVENT)
ONE_CHANNEL = 1


def stamp(moment):
    return int(moment.timestamp()) if moment else None


async def ask_season(store, coc, now):
    data, _ = await coc.goldpass()
    found = {"start": (data or {}).get("startTime"), "end": (data or {}).get("endTime"),
             "fetched": now.timestamp()}
    if not found["end"]:
        return None
    await store.kv_set(SEASON_KEY, found)
    return found


async def season(store, coc, now):
    cached = await store.kv_get(SEASON_KEY)
    cached = cached if isinstance(cached, dict) else {}
    if cached.get("start") and now.timestamp() - float(cached.get("fetched") or 0) < SEASON_TTL:
        return cached
    if coc is None:
        return cached
    try:
        return await ask_season(store, coc, now) or cached
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("stagione del pass non letta (%s)", type(e).__name__)
        return cached


def season_rows(found, now):
    end = parse_coc_time((found or {}).get("end"))
    if not end or end <= now:
        return []
    return [{"kind": GOLDPASS, "start": stamp(parse_coc_time(found.get("start"))),
             "end": stamp(end)}]


def event_rows(now, end):
    return [{"kind": EVENT, "key": item["key"], "state": item["state"],
             "start": stamp(item["start"]), "end": stamp(item["end"])}
            for item in agenda.upcoming(now, end)]


def video_rows(rows):
    return [{"kind": VIDEO, "id": row["id"], "title": row.get("title") or "",
             "published": row.get("published") or ""}
            for row in newest(rows or (), "published", WAR_HISTORY_KEEP) if row.get("id")]


async def clips(store, client, key, now):
    channel = base_videos.official_in(await base_videos.platform_rows(store))
    if not channel:
        return []
    rows = [row for row in await store.videos_rows(base_videos.PLATFORM)
            if row.get("channel") == channel]
    if rows or not key or await base_videos.stopped_by_quota(store, now.timestamp()):
        return rows
    found, problem = await base_videos.channel_rows(
        store, client, key, channel, (base_videos.PLATFORM,),
        base_videos.per_channel(ONE_CHANNEL))
    if problem or not found:
        return []
    await store.videos_put(found)
    return found


async def gather(store, client, key, coc, now):
    found = await season(store, coc, now)
    return (season_rows(found, now) + event_rows(now, (found or {}).get("end"))
            + video_rows(await clips(store, client, key, now)))


async def collect(store, client, key, coc, now):
    try:
        rows = await gather(store, client, key, coc, now)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("notizie non raccolte (%s)", type(e).__name__)
        return []
    await store.kv_set(ROWS_KEY, rows)
    return rows
