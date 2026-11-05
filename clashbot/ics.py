from datetime import timedelta, timezone

from . import agenda
from .util import parse_coc_time

PRODID = "-//ClanBoard//Calendario//IT"
HORIZON_DAYS = 90
FOLD_AT = 73
CRLF = "\r\n"
WINDOWS = (("cwl", agenda.cwl_signup), ("games", agenda.clan_games), ("raid", agenda.raid_weekend))
WAR_STATES = ("preparation", "inWar")


def escape(text):
    out = str(text if text is not None else "")
    out = out.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return out.replace("\r\n", "\\n").replace("\n", "\\n")


def fold(line):
    data = line.encode()
    if len(data) <= FOLD_AT:
        return line
    parts, start = [], 0
    while start < len(data):
        end = min(start + (FOLD_AT if not parts else FOLD_AT - 1), len(data))
        while end < len(data) and data[end] & 0xC0 == 0x80:
            end -= 1
        parts.append(data[start:end].decode() if not parts else " " + data[start:end].decode())
        start = end
    return CRLF.join(parts)


def stamp(when):
    return when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def series(now, goldpass_end=None, horizon=HORIZON_DAYS):
    limit = now + timedelta(days=horizon)
    rows, seen = [], set()
    for key, window in WINDOWS:
        cursor = now
        for _ in range(horizon):
            start, end = window(cursor)
            if start >= limit:
                break
            if (key, start) not in seen:
                seen.add((key, start))
                rows.append((key, start, end))
            cursor = end + timedelta(seconds=1)
    end = agenda.season_end(now, goldpass_end)
    if end < limit:
        rows.append(("season", end, end + timedelta(hours=1)))
    return sorted(rows, key=lambda row: (row[1], row[0]))


def war_entry(war):
    if not isinstance(war, dict) or war.get("state") not in WAR_STATES:
        return None
    start, end = parse_coc_time(war.get("startTime")), parse_coc_time(war.get("endTime"))
    if not start or not end or end <= start:
        return None
    return ("war", start, end, (war.get("opponent") or {}).get("name"))


def summary(L, key, name=None):
    if key == "war":
        return L.t("ics.war", name=name or "?")
    return L.t(f"agenda.item.{key}")


def uid(slug, key, start):
    return f"{key}-{stamp(start)}-{slug}@clanboard"


def event_lines(slug, key, text, start, end, now):
    return ["BEGIN:VEVENT", f"UID:{uid(slug, key, start)}", f"DTSTAMP:{stamp(now)}",
            f"DTSTART:{stamp(start)}", f"DTEND:{stamp(end)}", f"SUMMARY:{escape(text)}", "END:VEVENT"]


def build(L, slug, clan_name, now, goldpass_end=None, war=None):
    rows = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
            f"X-WR-CALNAME:{escape(L.t('ics.name', clan=clan_name))}"]
    entry = war_entry(war)
    if entry:
        rows += event_lines(slug, "war", summary(L, "war", entry[3]), entry[1], entry[2], now)
    for key, start, end in series(now, goldpass_end):
        rows += event_lines(slug, key, summary(L, key), start, end, now)
    rows.append("END:VCALENDAR")
    return CRLF.join(fold(row) for row in rows) + CRLF
