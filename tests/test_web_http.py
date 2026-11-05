import asyncio

from clashbot.web import http


class FakeWriter:
    def __init__(self, fail_after=None):
        self.chunks = []
        self.closed = False
        self.fail_after = fail_after

    def get_extra_info(self, name):
        return ("127.0.0.9", 1234)

    def write(self, data):
        if self.fail_after is not None and len(self.chunks) >= self.fail_after:
            raise ConnectionError("via")
        self.chunks.append(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True


def parse(raw, peer="127.0.0.5"):
    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(raw)
        reader.feed_eof()
        return await http.read_request(reader, peer)
    return asyncio.run(go())


def test_reads_method_path_query_and_headers():
    req = parse(b"GET /c/abc?tab=members&tab=stats HTTP/1.1\r\nHost: x\r\nAccept-Language: it-IT,it;q=0.9\r\n\r\n")
    assert req.method == "GET" and req.path == "/c/abc"
    assert req.query["tab"] == ["members", "stats"]
    assert req.one("tab") == "members" and req.one("pinco", "-") == "-"
    assert req.header("accept-language").startswith("it-IT")
    assert req.body == b""


def test_decodes_the_path_and_keeps_the_query_apart():
    req = parse(b"GET /translate/zh-Hans?k=war.title%20x HTTP/1.1\r\n\r\n")
    assert req.path == "/translate/zh-Hans" and req.one("k") == "war.title x"


def test_reads_the_body_by_content_length():
    req = parse(b"POST /translate/it HTTP/1.1\r\nContent-Type: application/x-www-form-urlencoded\r\n"
                b"Content-Length: 21\r\n\r\nname=war.title&t=ciao")
    assert req.form() == {"name": "war.title", "t": "ciao"}
    assert req.payload() == {}


def test_reads_a_json_body_only_with_its_own_type():
    req = parse(b"POST /app/abc/target HTTP/1.1\r\nContent-Type: application/json\r\n"
                b"Content-Length: 29\r\n\r\n{\"kind\":\"target.set\",\"pos\":3}")
    assert req.payload() == {"kind": "target.set", "pos": 3}
    assert req.form() == {}


def test_refuses_what_is_too_big_or_malformed():
    for raw in (b"GET /" + b"a" * http.MAX_LINE + b" HTTP/1.1\r\n\r\n",
                b"PINCO\r\n\r\n",
                b"POST / HTTP/1.1\r\nContent-Length: 999999\r\n\r\n",
                b"POST / HTTP/1.1\r\nContent-Length: pinco\r\n\r\n",
                b"GET / HTTP/1.1\r\n" + b"".join(b"X-%d: 1\r\n" % n for n in range(http.MAX_HEADERS + 2)) + b"\r\n"):
        try:
            parse(raw)
        except ValueError:
            continue
        raise AssertionError(raw[:40])


def test_no_request_at_all_is_not_an_error():
    assert parse(b"") is None


def test_cookies_are_read_one_by_one():
    req = parse(b"GET /panel HTTP/1.1\r\nCookie: other=1; sid=abc123; x=2\r\n\r\n")
    assert req.cookie("sid") == "abc123" and req.cookie("pinco") == ""


def test_the_forwarded_address_counts_only_from_the_inside():
    inside = parse(b"GET / HTTP/1.1\r\nX-Forwarded-For: 203.0.113.9, 127.0.0.2\r\n\r\n", peer="127.0.0.2")
    assert inside.ip == "203.0.113.9"
    outside = parse(b"GET / HTTP/1.1\r\nX-Forwarded-For: 203.0.113.9\r\n\r\n", peer="198.51.100.7")
    assert outside.ip == "198.51.100.7"
    assert http.private("127.0.0.1")
    assert not http.private("192.0.2.1") and not http.private("198.51.100.7")
    assert not http.private("203.0.113.9") and not http.private("pinco")


def test_the_response_carries_length_and_the_fixed_headers():
    raw = http.render_response(http.Response("ciao", headers={"Cache-Control": "public, max-age=60"}))
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    assert lines[0] == "HTTP/1.1 200 OK"
    assert "Content-Length: 4" in lines and "Connection: close" in lines
    assert "X-Content-Type-Options: nosniff" in lines and "Referrer-Policy: no-referrer" in lines
    assert "Cache-Control: public, max-age=60" in lines
    assert body == b"ciao"


def test_head_answers_without_a_body_but_with_the_length():
    raw = http.render_response(http.Response("ciao"), head_only=True)
    assert b"Content-Length: 4" in raw and raw.endswith(b"\r\n\r\n")


def test_data_responses_are_json():
    res = http.data({"state": "up"})
    assert res.kind == http.JSON and res.body == b'{"state":"up"}'


def test_a_stream_response_writes_the_head_then_each_event():
    async def events():
        yield "event: state\ndata: {}\n\n"
        yield ": ping\n\n"

    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(b"GET /x HTTP/1.1\r\n\r\n")
        reader.feed_eof()
        writer = FakeWriter()

        async def router(req):
            return http.StreamResponse(events())
        await http.handle(reader, writer, router)
        return writer

    writer = asyncio.run(go())
    raw = b"".join(writer.chunks)
    head, body = raw.split(b"\r\n\r\n", 1)
    assert b"HTTP/1.1 200 OK" in head and b"Content-Type: text/event-stream" in head
    assert b"Content-Length" not in head and b"Cache-Control: no-store" in head
    assert b"X-Accel-Buffering: no" in head
    assert body == b"event: state\ndata: {}\n\n: ping\n\n"
    assert writer.closed


def test_a_stream_stops_quietly_when_the_client_goes_away():
    seen = []

    async def events():
        seen.append(1)
        yield "a\n\n"
        seen.append(2)
        yield "b\n\n"

    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(b"GET /x HTTP/1.1\r\n\r\n")
        reader.feed_eof()
        writer = FakeWriter(fail_after=2)

        async def router(req):
            return http.StreamResponse(events())
        await http.handle(reader, writer, router)
        return writer

    writer = asyncio.run(go())
    assert seen == [1, 2] and writer.closed


def test_l_annullamento_chiude_il_cliente_e_risale():
    class Stopped(FakeWriter):
        def write(self, data):
            raise asyncio.CancelledError()

    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(b"GET /x HTTP/1.1\r\n\r\n")
        reader.feed_eof()
        writer = Stopped()

        async def router(req):
            return http.text("ciao")
        risen = False
        try:
            await http.handle(reader, writer, router)
        except asyncio.CancelledError:
            risen = True
        return risen, writer.closed

    assert asyncio.run(go()) == (True, True)


def test_the_ordinary_responses_keep_their_shape_next_to_the_stream():
    async def go():
        reader = asyncio.StreamReader()
        reader.feed_data(b"GET /x HTTP/1.1\r\n\r\n")
        reader.feed_eof()
        writer = FakeWriter()

        async def router(req):
            return http.text("ciao")
        await http.handle(reader, writer, router)
        return writer

    writer = asyncio.run(go())
    raw = b"".join(writer.chunks)
    assert b"Content-Length: 4" in raw and raw.endswith(b"ciao")
    assert writer.closed


def test_the_bucket_stops_the_flood_and_then_refills():
    clock = [0.0]
    bucket = http.Bucket(2, lambda: clock[0])
    assert bucket.allow("192.0.2.1") and bucket.allow("192.0.2.1")
    assert not bucket.allow("192.0.2.1")
    assert bucket.allow("192.0.2.2")
    clock[0] = 60.0
    assert bucket.allow("192.0.2.1")


def crowd(total):
    ranges = ("192.0.2.", "198.51.100.", "203.0.113.")
    return [f"{ranges[n // 256]}{n % 256}" for n in range(total)]


def test_the_bucket_does_not_grow_for_ever():
    clock = [0.0]
    bucket = http.Bucket(60, lambda: clock[0])
    for ip in crowd(http.BUCKET_MAX + 20):
        bucket.allow(ip)
    clock[0] = 600.0
    bucket.allow("203.0.113.200")
    assert len(bucket.seen) <= http.BUCKET_MAX


def test_l_etag_segue_il_corpo_e_il_304_non_rimanda_niente():
    assert http.REASONS[304] == "Not Modified"
    vivo = http.Response("pinco", headers={"Cache-Control": "public, max-age=60"})
    marchio = http.etag(vivo.body)
    assert marchio == http.etag(b"pinco") != http.etag(b"pinca")
    assert marchio.startswith('"') and marchio.endswith('"')
    req = parse(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert http.revalidate(req, vivo) is vivo and vivo.headers["ETag"] == marchio
    chiede = parse(b'GET / HTTP/1.1\r\nHost: x\r\nIf-None-Match: W/"altro", '
                   + marchio.encode() + b"\r\n\r\n")
    ferma = http.revalidate(chiede, http.Response(
        "pinco", headers={"Cache-Control": "public, max-age=60"}))
    assert ferma.status == 304 and ferma.body == b"" and ferma.headers["ETag"] == marchio
    assert http.render_response(ferma).startswith(b"HTTP/1.1 304 Not Modified")
    privato = http.Response("pinco", headers={"Cache-Control": "no-store"})
    assert "ETag" not in http.revalidate(chiede, privato).headers
    scritto = parse(b"POST / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert "ETag" not in http.revalidate(scritto, http.Response(
        "pinco", headers={"Cache-Control": "public, max-age=60"})).headers
