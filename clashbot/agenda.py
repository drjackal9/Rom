from datetime import timedelta

from .util import parse_coc_time


def next_month(dt):
    year, month = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
    return dt.replace(year=year, month=month, day=1)


def clan_games(now):
    start = now.replace(day=22, hour=8, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=6)
    if now >= end:
        start = next_month(start).replace(day=22)
        end = start + timedelta(days=6)
    return start, end


def cwl_signup(now):
    start = now.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=2)
    if now >= end:
        start = next_month(start)
        end = start + timedelta(days=2)
    return start, end


def raid_weekend(now):
    friday = (now - timedelta(days=(now.weekday() - 4) % 7)).replace(hour=7, minute=0, second=0, microsecond=0)
    if friday > now:
        friday -= timedelta(days=7)
    end = friday + timedelta(days=3)
    if now >= end:
        friday += timedelta(days=7)
        end = friday + timedelta(days=3)
    return friday, end


def last_monday(dt):
    first_next = next_month(dt.replace(day=1, hour=5, minute=0, second=0, microsecond=0))
    last_day = first_next - timedelta(days=1)
    return last_day - timedelta(days=last_day.weekday())


def season_end(now, goldpass_end=None):
    end = parse_coc_time(goldpass_end) if isinstance(goldpass_end, str) else goldpass_end
    if end and end > now:
        return end
    monday = last_monday(now)
    if monday <= now:
        monday = last_monday(next_month(now.replace(day=1)))
    return monday


def season_start(now):
    start = last_monday(now)
    if start > now:
        start = last_monday(now.replace(day=1, hour=5, minute=0, second=0, microsecond=0) - timedelta(days=1))
    return start


def season_window(now, goldpass_end=None):
    return season_start(now), season_end(now, goldpass_end)


def upcoming(now, goldpass_end=None):
    items = []
    start, end = cwl_signup(now)
    items.append({"key": "cwl", "icon": "🏅", "title": "Iscrizione CWL", "start": start, "end": end})
    start, end = clan_games(now)
    items.append({"key": "games", "icon": "🎮", "title": "Giochi del Clan", "start": start, "end": end})
    start, end = raid_weekend(now)
    items.append({"key": "raid", "icon": "🏛", "title": "Weekend della Capitale", "start": start, "end": end})
    end = season_end(now, goldpass_end)
    items.append({"key": "season", "icon": "🏁", "title": "Fine stagione", "start": end, "end": end})
    for item in items:
        item["state"] = "ongoing" if item["start"] <= now < item["end"] else "upcoming"
    return sorted(items, key=lambda i: (i["state"] != "ongoing", i["start"]))


def due_announcements(now, goldpass_end, sent):
    due = []
    for item in upcoming(now, goldpass_end):
        if item["key"] == "raid":
            continue
        occurrence = item["start"].strftime("%Y%m%d")
        key = f"{item['key']}:{occurrence}:tomorrow"
        if key not in sent and item["start"] - timedelta(hours=24) <= now < item["start"]:
            due.append((key, item, "tomorrow"))
        key = f"{item['key']}:{occurrence}:start"
        if item["key"] != "season" and key not in sent and item["start"] <= now < item["start"] + timedelta(hours=6):
            due.append((key, item, "start"))
        key = f"{item['key']}:{occurrence}:last"
        if item["key"] == "games" and key not in sent and item["end"] - timedelta(hours=24) <= now < item["end"]:
            due.append((key, item, "last"))
    return due
