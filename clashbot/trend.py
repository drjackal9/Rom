from .util import to_int, zone

DAYS = 30
BLOCKS = "▁▂▃▄▅▆▇█"


def day_key(now, tz):
    return now.astimezone(zone(tz)).strftime("%Y-%m-%d")


def record(trend, tag, name, day, trophies, th, legend=0):
    state = trend if isinstance(trend, dict) else {}
    row = state.get(tag)
    if not isinstance(row, dict):
        row = {"name": name, "days": []}
        state[tag] = row
    if name:
        row["name"] = name
    days = row.setdefault("days", [])
    sample = {"d": day, "trophies": to_int(trophies), "th": to_int(th), "legend": to_int(legend)}
    if days and days[-1].get("d") == day:
        days[-1] = sample
    else:
        days.append(sample)
    del days[:-DAYS]
    return state


def series(trend, tag):
    row = (trend if isinstance(trend, dict) else {}).get(tag)
    if not isinstance(row, dict):
        return []
    return [s for s in (row.get("days") or []) if isinstance(s, dict)]


def bars(values):
    numbers = [to_int(v) for v in values or ()]
    if not numbers:
        return ""
    low, high = min(numbers), max(numbers)
    span = high - low
    if not span:
        return BLOCKS[0] * len(numbers)
    return "".join(BLOCKS[min(len(BLOCKS) - 1, (v - low) * len(BLOCKS) // span)] for v in numbers)


def move(samples):
    rows = [s for s in samples or () if isinstance(s, dict)]
    if len(rows) < 2:
        return 0
    return to_int(rows[-1].get("trophies")) - to_int(rows[0].get("trophies"))


def prune(trend, member_tags):
    state = trend if isinstance(trend, dict) else {}
    keep = set(member_tags or ())
    for tag in [t for t in state if t not in keep]:
        del state[tag]
    return state
