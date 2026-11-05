import html
import re
import string
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

TAG_CHARS = set("0289PYLQGRJCUV")
REPORT_HOUR = 9
CLAN_SLOTS = 50
API_LABELS = 3
TELEGRAM_LINK = "https://t.me/"
TELEGRAM_PATH = set(string.ascii_letters + string.digits + "_+-/")


def esc(value):
    return html.escape(str(value if value is not None else "?"))


def now_utc():
    return datetime.now(timezone.utc)


def parse_coc_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def normalize_tag(raw):
    if not raw:
        return None
    tag = re.sub(r"\s+", "", str(raw)).upper().replace("O", "0").lstrip("#")
    if not 3 <= len(tag) <= 15 or any(c not in TAG_CHARS for c in tag):
        return None
    return "#" + tag


def encode_tag(tag):
    return tag.replace("#", "%23")


def bar(pct, width=10):
    try:
        filled = max(0, min(width, round(float(pct) / 100 * width)))
    except (TypeError, ValueError):
        filled = 0
    return "▰" * filled + "▱" * (width - filled)


def zone(tz):
    try:
        return ZoneInfo(str(tz))
    except Exception:
        return timezone.utc


def day_of(now, tz=None):
    when = now if isinstance(now, datetime) else datetime.fromtimestamp(float(now), timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(zone(tz)).date()


def to_int(value):
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def valid_https(value):
    if not value or any(c.isspace() for c in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname)


def valid_telegram(value):
    if not isinstance(value, str) or not value.startswith(TELEGRAM_LINK):
        return False
    path = value[len(TELEGRAM_LINK):]
    return bool(path) and set(path) <= TELEGRAM_PATH
