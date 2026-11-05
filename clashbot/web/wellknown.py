from ..util import now_utc, valid_https
from . import http, pages

ADVISORY = "/security/advisories/new"
POLICY = "/blob/main/SECURITY.md"
THANKS = "/blob/main/docs/ringraziamenti.md"
CHECKLIST = "/blob/main/docs/sicurezza.md"
PREFERRED = "it, en"
STAMP = "%Y-%m-%dT%H:%M:%SZ"
CACHE = pages.PAGE_HEAD
ROBOTS = "\n".join((
    "User-agent: *",
    "Allow: /$",
    "Allow: /create",
    "Allow: /community",
    "Allow: /status",
    "Allow: /c/",
    "Allow: /bases",
    "Allow: /news",
    "Allow: /leaderboards",
    "Allow: /security",
    "Disallow: /app/",
    "Disallow: /r/",
    "Disallow: /board",
)) + "\n"


def expires(at):
    try:
        return at.replace(year=at.year + 1)
    except ValueError:
        return at.replace(year=at.year + 1, day=at.day - 1)


START = now_utc()
EXPIRES = expires(START)


def base_of(url):
    return str(url).rstrip("/") if valid_https(url) else ""


def thanks_url(url):
    base = base_of(url)
    return base + THANKS if base else ""


def checklist_url(url):
    base = base_of(url)
    return base + CHECKLIST if base else ""


def security_txt(url, until):
    base = base_of(url)
    if not base:
        return ""
    return "\n".join((
        f"Contact: {base}{ADVISORY}",
        f"Expires: {until.strftime(STAMP)}",
        f"Preferred-Languages: {PREFERRED}",
        f"Policy: {base}{POLICY}",
    )) + "\n"


async def security(site, req):
    body = security_txt(await site.source_url(), EXPIRES)
    if not body:
        return http.text("", 404)
    return http.text(body, headers=pages.headers(CACHE))


async def robots(site, req):
    return http.text(ROBOTS, headers=pages.headers(CACHE))
