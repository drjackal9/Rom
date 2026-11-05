import asyncio

from clashbot import i18n, ics
from clashbot.web import app as web_app, http, payload
from test_web_page import PageStore, SLUG
from test_web_publish import built
from test_web_status import request

L = i18n.locale("it")


def serve(store, path):
    return asyncio.run(web_app.Site(store).router(request(path)))


def page_with_calendar():
    return {(SLUG, payload.PUBLIC): built({"ics": True, "page": True})}


def test_the_public_page_carries_the_file_the_bot_writes():
    page = built({"ics": True})
    assert page["ics"].startswith("BEGIN:VCALENDAR\r\n")
    assert page["ics"].endswith("END:VCALENDAR\r\n")
    assert f"PRODID:{ics.PRODID}" in page["ics"]
    for key in ("cwl", "games", "raid", "season"):
        assert ics.escape(L.t(f"agenda.item.{key}")) in page["ics"]
    assert "Clan Nemico" in page["ics"]
    assert built()["ics"] is None


def test_the_only_route_serves_that_very_text():
    pages = page_with_calendar()
    res = serve(PageStore(pages), f"/c/{SLUG}/calendar.ics")
    assert res.status == 200 and res.kind == http.CALENDAR
    assert res.headers["Cache-Control"] == "public, max-age=900"
    assert res.headers["X-Robots-Tag"] == "noindex"
    assert res.body.decode() == pages[(SLUG, payload.PUBLIC)]["ics"]


def test_the_calendar_answers_only_when_the_leader_wants_it():
    assert serve(PageStore({(SLUG, payload.PUBLIC): built()}),
                 f"/c/{SLUG}/calendar.ics").status == 404
    assert serve(PageStore(), f"/c/{SLUG}/calendar.ics").status == 404
    page = dict(built({"ics": True}), ics=None)
    assert serve(PageStore({(SLUG, payload.PUBLIC): page}),
                 f"/c/{SLUG}/calendar.ics").status == 404


def test_the_page_links_the_calendar_where_it_really_is():
    text = serve(PageStore(page_with_calendar()), f"/c/{SLUG}").body.decode()
    assert f'href="/c/{SLUG}/calendar.ics"' in text
    plain = serve(PageStore({(SLUG, payload.PUBLIC): built({"page": True})}),
                  f"/c/{SLUG}").body.decode()
    assert "calendar.ics" not in plain


def test_there_is_no_second_calendar_path():
    store = PageStore(page_with_calendar())
    assert serve(store, "/ics/qualunque.ics").status == 404
    assert [pattern for _, pattern, _ in web_app.ROUTES if "ics" in pattern] == \
        ["/c/<code>/calendar.ics"]


def test_the_widget_answers_only_when_the_leader_wants_it_and_can_be_embedded():
    assert serve(PageStore({(SLUG, payload.PUBLIC): built()}), f"/c/{SLUG}/widget").status == 404
    res = serve(PageStore({(SLUG, payload.PUBLIC): built({"widget": True})}), f"/c/{SLUG}/widget")
    assert res.status == 200
    text = res.body.decode()
    assert "Nostro Clan" in text
    assert "frame-ancestors" not in res.headers["Content-Security-Policy"]
    assert "Mario" not in text and "<script" not in text
    assert res.headers["Cache-Control"] == "public, max-age=60"
