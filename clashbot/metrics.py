import json
from pathlib import Path

SAMPLES = "/metrics/samples.jsonl"
HOURS = 24
FIELDS = ("mem_mb", "cpu")


def read_samples(path=SAMPLES):
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def latest(samples):
    for row in reversed(samples or []):
        if "containers" in row:
            return row
    return None


def recent(samples, now, hours=HOURS):
    edge = number(now) - hours * 3600
    return [row for row in samples or [] if number(row.get("ts")) >= edge]


def peaks(samples, now, hours=HOURS):
    top = {}
    for row in recent(samples, now, hours):
        for name, stats in (row.get("containers") or {}).items():
            if not isinstance(stats, dict):
                continue
            peak = top.setdefault(name, {field: 0 for field in FIELDS})
            for field in FIELDS:
                if number(stats.get(field)) > number(peak[field]):
                    peak[field] = stats.get(field)
    return top


def alerts(samples, now, hours=HOURS):
    return [str(row["alert"]) for row in recent(samples, now, hours) if row.get("alert")]
