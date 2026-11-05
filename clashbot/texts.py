import re
from urllib.parse import urlsplit

LINK = re.compile(r"(?i)\b(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:[a-z]{2,})(?:/\S*)?")
PHONE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){8,}\d(?!\d)")
BOT = re.compile(r"(?i)@\w*bot\b")
TELEGRAM = "t.me"


def handle(raw):
    return str(raw or "").lstrip("@").lower()


def split(found):
    try:
        parts = urlsplit(found if "//" in found else "//" + found)
    except ValueError:
        return "", ""
    return (parts.hostname or "").lower(), parts.path


def ours(found, bot_username, site_host):
    host, path = split(found)
    if not host:
        return False
    if site_host and host == str(site_host).lower():
        return True
    if host != TELEGRAM or not bot_username:
        return False
    return handle(path.strip("/").split("/")[0]) == handle(bot_username)


def filter(text, bot_username, site_host):
    body = str(text or "")
    for found in LINK.finditer(body):
        if not ours(found.group(0), bot_username, site_host):
            return False, "link"
    if PHONE.search(body):
        return False, "phone"
    for found in BOT.finditer(body):
        if handle(found.group(0)) != handle(bot_username):
            return False, "bot"
    return True, None


def reason(L, why):
    return L.t(f"texts.reject.{why}")
