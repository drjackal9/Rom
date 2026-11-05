import asyncio
import json

from . import http

PING = "event: ping\ndata: {}\n\n"
LIVE_GRACE = 2 * http.READ_TIMEOUT
CLOSE = object()


class Client(asyncio.Queue):
    def __init__(self, slug, seat_key):
        super().__init__()
        self.slug = slug
        self.seat_key = seat_key


def event(name, obj):
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {body}\n\n"


def attach(site, slug, seat_key):
    clients = site.live.setdefault(slug, set())
    for old in list(clients):
        if old.seat_key == seat_key:
            clients.discard(old)
            old.put_nowait(CLOSE)
    client = Client(slug, seat_key)
    clients.add(client)
    return client


def detach(site, client):
    clients = site.live.get(client.slug)
    if clients is None:
        return
    clients.discard(client)
    if not clients:
        site.live.pop(client.slug, None)


async def stream(site, slug, seat_key, first, ping=http.READ_TIMEOUT, shape=None):
    client = attach(site, slug, seat_key)
    try:
        opened = await first() if callable(first) else first
        if opened is None:
            return
        yield opened
        while True:
            try:
                page = await asyncio.wait_for(client.get(), ping)
            except TimeoutError:
                yield PING
                continue
            if page is CLOSE:
                return
            shaped = await shape(page) if shape else page
            if shaped is None:
                return
            yield event("state", shaped)
    finally:
        detach(site, client)
