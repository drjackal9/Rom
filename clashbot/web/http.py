import asyncio
import hashlib
import ipaddress
import json
import logging
import time
from urllib.parse import parse_qs, unquote, urlsplit

log = logging.getLogger("clashbot.web")

MAX_LINE = 8192
MAX_HEADERS = 64
MAX_BODY = 65536
READ_TIMEOUT = 15
READ_RATE = 60
WRITE_RATE = 10
BUCKET_MAX = 512
IDLE_DROP = 120
ETAG_LEN = 8
ETAG_MAX = 8
CACHED = "public"
SAFE = ("GET", "HEAD")

HTML = "text/html; charset=utf-8"
JSON = "application/json; charset=utf-8"
TEXT = "text/plain; charset=utf-8"
CALENDAR = "text/calendar; charset=utf-8"
SHEET = "text/csv; charset=utf-8"
PHOTO = "image/png"
CSS = "text/css; charset=utf-8"
FONT = "font/woff2"
SCRIPT = "text/javascript; charset=utf-8"
EVENT_STREAM = "text/event-stream; charset=utf-8"

REASONS = {
    200: "OK", 204: "No Content", 302: "Found", 304: "Not Modified",
    400: "Bad Request", 401: "Unauthorized",
    403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
    413: "Payload Too Large", 429: "Too Many Requests", 500: "Internal Server Error",
    503: "Service Unavailable",
}

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}

DOCUMENTATION = tuple(ipaddress.ip_network(cidr) for cidr in (
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32"))


def private(ip):
    try:
        address = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    if any(address in network for network in DOCUMENTATION):
        return False
    return address.is_private or address.is_loopback


class Request:
    __slots__ = ("method", "path", "query", "headers", "body", "peer")

    def __init__(self, method, path, query, headers, body, peer):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.peer = peer

    def header(self, name, default=""):
        return self.headers.get(name.lower(), default)

    def one(self, name, default=""):
        values = self.query.get(name) or []
        return values[0] if values else default

    def cookie(self, name):
        for part in self.header("cookie").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return ""

    def kind(self):
        return self.header("content-type").split(";")[0].strip().lower()

    def form(self):
        if self.kind() != "application/x-www-form-urlencoded":
            return {}
        parsed = parse_qs(self.body.decode("utf-8", "replace"), keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items()}

    def payload(self):
        if self.kind() != "application/json":
            return {}
        try:
            body = json.loads(self.body.decode("utf-8", "replace"))
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    @property
    def ip(self):
        if not private(self.peer):
            return self.peer
        for name in ("cf-connecting-ip", "x-forwarded-for"):
            found = self.header(name)
            if found:
                return found.split(",")[0].strip()[:45]
        return self.peer


class Response:
    __slots__ = ("status", "body", "kind", "headers")

    def __init__(self, body=b"", status=200, kind=HTML, headers=None):
        self.status = status
        self.body = body.encode() if isinstance(body, str) else body
        self.kind = kind
        self.headers = dict(headers or {})


class StreamResponse:
    __slots__ = ("status", "events", "kind", "headers")

    def __init__(self, events, kind=EVENT_STREAM, headers=None, status=200):
        self.status = status
        self.events = events
        self.kind = kind
        self.headers = {
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            **(headers or {}),
        }


def text(body="", status=200, headers=None):
    return Response(body, status, TEXT, headers)


def etag(body):
    return '"' + hashlib.blake2b(body, digest_size=ETAG_LEN).hexdigest() + '"'


def asked(req):
    raw = req.header("if-none-match")
    return [one.strip() for one in raw.split(",")[:ETAG_MAX] if one.strip()]


def revalidate(req, res):
    if res.status != 200 or req.method not in SAFE:
        return res
    if not res.headers.get("Cache-Control", "").startswith(CACHED):
        return res
    mark = etag(res.body)
    res.headers["ETag"] = mark
    if mark in asked(req):
        return Response(b"", 304, res.kind, res.headers)
    return res


def data(obj, status=200, headers=None):
    return Response(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), status, JSON, headers)


class Bucket:
    def __init__(self, rate, clock=time.monotonic):
        self.rate = float(rate)
        self.clock = clock
        self.seen = {}

    def allow(self, ip):
        now = self.clock()
        tokens, stamp = self.seen.get(ip, (self.rate, now))
        tokens = min(self.rate, tokens + (now - stamp) * self.rate / 60.0)
        if tokens < 1.0:
            self.seen[ip] = (tokens, now)
            return False
        if len(self.seen) >= BUCKET_MAX:
            self.prune(now)
        self.seen[ip] = (tokens - 1.0, now)
        return True

    def prune(self, now):
        for ip, (_, stamp) in list(self.seen.items()):
            if now - stamp > IDLE_DROP:
                self.seen.pop(ip, None)


async def read_request(reader, peer):
    line = await asyncio.wait_for(reader.readline(), READ_TIMEOUT)
    if not line:
        return None
    if len(line) >= MAX_LINE:
        raise ValueError("riga troppo lunga")
    parts = line.decode("latin-1").rstrip("\r\n").split(" ")
    if len(parts) != 3 or not parts[1].startswith("/"):
        raise ValueError("richiesta malformata")
    headers = {}
    for _ in range(MAX_HEADERS):
        raw = await asyncio.wait_for(reader.readline(), READ_TIMEOUT)
        if not raw or raw in (b"\r\n", b"\n"):
            break
        if len(raw) >= MAX_LINE:
            raise ValueError("intestazione troppo lunga")
        name, sep, value = raw.decode("latin-1").partition(":")
        if not sep:
            raise ValueError("intestazione malformata")
        headers[name.strip().lower()] = value.strip()
    else:
        raise ValueError("troppe intestazioni")
    raw_length = headers.get("content-length") or "0"
    if not raw_length.isdigit():
        raise ValueError("lunghezza non valida")
    length = int(raw_length)
    if length > MAX_BODY:
        raise ValueError("corpo troppo grande")
    body = await asyncio.wait_for(reader.readexactly(length), READ_TIMEOUT) if length else b""
    split = urlsplit(parts[1])
    return Request(
        parts[0].upper(), unquote(split.path), parse_qs(split.query, keep_blank_values=True),
        headers, body, peer,
    )


def render_head(res, length=None):
    lines = [
        f"HTTP/1.1 {res.status} {REASONS.get(res.status, 'OK')}",
        f"Content-Type: {res.kind}",
    ]
    if length is not None:
        lines.append(f"Content-Length: {length}")
    lines.append("Connection: close")
    for name, value in {**BASE_HEADERS, **res.headers}.items():
        lines.append(f"{name}: {value}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def render_response(res, head_only=False):
    return render_head(res, len(res.body)) + (b"" if head_only else res.body)


async def stream(writer, res):
    writer.write(render_head(res))
    await writer.drain()
    try:
        async for event in res.events:
            writer.write(event.encode())
            await writer.drain()
    finally:
        shut = getattr(res.events, "aclose", None)
        if shut is not None:
            await shut()


async def handle(reader, writer, router):
    started = time.monotonic()
    peer = writer.get_extra_info("peername")
    req = res = stop = None
    try:
        req = await read_request(reader, peer[0] if peer else "?")
        if req is not None:
            res = await router(req)
    except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
        res = None
    except ValueError as e:
        log.info("richiesta rifiutata: %s", e)
        res = text("", 400)
    except Exception:
        log.exception("richiesta non servita")
        res = text("", 500)
    if res is not None:
        try:
            if isinstance(res, StreamResponse):
                await stream(writer, res)
            else:
                writer.write(render_response(res, req is not None and req.method == "HEAD"))
                await writer.drain()
        except (ConnectionError, RuntimeError):
            pass
        except asyncio.CancelledError as cancelled:
            stop = cancelled
        if req is not None:
            log.info("%s %s %s %sms", req.method, req.path[:120], res.status,
                     int((time.monotonic() - started) * 1000))
    try:
        writer.close()
    except RuntimeError:
        pass
    if stop is not None:
        raise stop


async def serve(router, host=None, port=8080):
    async def client(reader, writer):
        await handle(reader, writer, router)

    return await asyncio.start_server(client, host, port)
