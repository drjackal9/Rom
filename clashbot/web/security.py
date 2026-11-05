from datetime import datetime, timedelta, timezone

from .. import manager_alerts, site_days
from ..db import INCIDENTS_KEEP, REPORTS_KEEP, SITE_DAYS_KEEP
from ..incidents import HOUR, hours_of, kind_label
from ..platform import LOG_KIND
from ..selfmetrics import BOT_KEY
from ..site_days import HOURS
from ..util import esc
from . import http
from .ban import STEPS
from .pages import ROW, SECURITY, SECURITY_TXT, bits, facts, foot, grid, link, shell, top_bar
from .public import empty_tile, share

PATH = SECURITY
WORD = "web.security."
TITLE = WORD + "title"
TLS = "1.2"
PORTS = 0
MEASURED = 4
SECTIONS = (WORD + "traffic", WORD + "uptime", WORD + "backup", WORD + "data",
            WORD + "edge", WORD + "decoy", WORD + "reports")
SUMS = (("requests", "requests"), ("pages", "pages"), ("visitors", "visitors"),
        ("blocked", "blocked_total"))
PARTS = (("waf", "blocked_waf"), ("bot", "blocked_bot"), ("rule", "blocked_rule"))
LEVELS = ("banned_h", "banned_d", "banned_forever")
REQUESTS = "requests"
PROBES = "probes"
KEEP = ("id", "tags", "game", "notes", "terms")


def word(L, name, **kw):
    return esc(L.t(WORD + name, **kw))


def unit(L, name):
    return esc(L.t("unit." + name))


def tile(big, name, tail=""):
    return (f'<div class="tile"><span class="big">{big}</span>'
            f"<span>{name}</span>{tail}</div>")


def muted(text):
    return f'<span class="muted">{text}</span>'


def nd(L):
    return word(L, "nd")


def number(L, value):
    return nd(L) if value is None else L.n(value)


def hours(L, value):
    if value is None:
        return nd(L)
    count = int(value)
    if count >= HOURS:
        return f"{L.n(count // HOURS)}{unit(L, 'd')}"
    return f"{L.n(count)}{unit(L, 'h')}"


def seconds(L, value):
    return nd(L) if value is None else f"{L.n(int(value))}{unit(L, 's')}"


def span(L, value):
    return word(L, "forever") if value is None else hours(L, int(value) // HOUR)


def outcome(L, value):
    if value is None:
        return nd(L)
    return word(L, "ok") if value else word(L, "failed")


def total(rows, name):
    return sum(int(row.get(name) or 0) for row in rows)


def stamp(value):
    if not value:
        return ""
    try:
        return str(datetime.fromtimestamp(float(value), timezone.utc).date())
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def opened_day(row):
    found = row.get("opened")
    return str(found.date()) if hasattr(found, "date") else ""


def bars(L, rows, name):
    top = max((int(row.get(name) or 0) for row in rows), default=0)
    cells = "".join(f'<span style="height:{share(int(row.get(name) or 0), top)}%"></span>'
                    for row in rows)
    label = word(L, "perday")
    return f'<div class="days" role="img" aria-label="{label}">{cells}</div>'


def countries(rows):
    found = {}
    for row in rows:
        for name, value in (row.get("countries") or {}).items():
            found[str(name)] = found.get(str(name), 0) + int(value or 0)
    return [name for name, _ in sorted(found.items(), key=lambda one: (-one[1], one[0]))]


def chips(names):
    if not names:
        return ""
    made = "".join(f'<span class="chip">{esc(name)}</span>' for name in names)
    return f'<p class="chips">{made}</p>'


def traffic_tiles(L, rows):
    made = []
    for name, field in SUMS:
        tail = ""
        if name == "blocked":
            tail = facts(tuple(f"{L.n(total(rows, key))} {word(L, short)}"
                               for short, key in PARTS), "muted")
        made.append(tile(L.n(total(rows, field)), word(L, name), tail))
    return made


def traffic_block(L, found):
    rows = found["days"]
    if not rows:
        return grid([empty_tile(L)], ROW)
    return grid(traffic_tiles(L, rows), ROW) + bars(L, rows, REQUESTS) + chips(countries(rows))


def month_tile(L, row):
    up = L.pct(row["uptime"]) if row.get("uptime") is not None else nd(L)
    tail = facts((f'{number(L, row.get("ms_med"))} {word(L, "ms")} {word(L, "mid")}',
                  f'{number(L, row.get("ms_max"))} {word(L, "ms")} {word(L, "peak")}',
                  f'{L.n(row.get("clean") or 0)}{unit(L, "d")} {word(L, "clean")}'), "muted")
    return tile(up, esc(str(row.get("month") or "")), tail)


def uptime_block(L, found):
    rows = found["months"]
    if not rows:
        return grid([empty_tile(L)], ROW)
    alive = found.get("uptime_s")
    made = [month_tile(L, row) for row in rows]
    made.append(tile(hours(L, None if alive is None else int(alive) // HOUR),
                     word(L, "restart")))
    return grid(made, ROW)


def backup_block(L, found):
    row = found["backup"]
    made = [tile(hours(L, row.get("dump_age_h")), word(L, "dump")),
            tile(number(L, row.get("dumps")), word(L, "dumps")),
            tile(outcome(L, row.get("restore_ok")), word(L, "restore"),
                 muted(esc(stamp(row.get("restore_at"))))),
            tile(hours(L, row.get("rpo_h")), word(L, "rpo")),
            tile(seconds(L, row.get("restore_s")), word(L, "rto"))]
    return grid(made, ROW)


def opened_now(found, now):
    return int(found["opens"].get(now.strftime("%Y-%m")) or 0)


def checked_line(L, audit):
    if not audit.get("version"):
        return ""
    return f'<p class="muted">{word(L, "checked", date=str(audit.get("day") or ""), build=str(audit["version"]))}</p>'


def data_block(L, found, now):
    kept = facts(tuple(word(L, "keep." + name) for name in KEEP), "muted")
    made = [tile(word(L, "collect"), word(L, "kept"), kept),
            tile(word(L, "never"), word(L, "nokeep")),
            tile(L.n(opened_now(found, now)), word(L, "opens"), muted(word(L, "promise")))]
    return grid(made, ROW) + checked_line(L, found["audit"])


def edge_block(L, found):
    audit = found["audit"]
    heads = found["heads"]
    made = [tile(L.n(PORTS), word(L, "ports"), muted(word(L, "tunnel"))),
            tile(esc(TLS), word(L, "tls")),
            tile(L.n(len(heads)), word(L, "heads"),
                 facts(tuple(esc(name) for name in heads), "muted")),
            tile(f"{L.n(http.READ_RATE)}/{L.n(http.WRITE_RATE)}", word(L, "rates"),
                 muted(word(L, "perminute"))),
            tile(L.n(len(STEPS)), word(L, "bans"),
                 facts(tuple(span(L, step) for step in STEPS), "muted")),
            tile(word(L, "otpon"), word(L, "otp")),
            tile(outcome(L, audit.get("ok")), word(L, "audit"),
                 muted(esc(str(audit.get("day") or ""))))]
    return grid(made, ROW)


def decoy_block(L, found):
    rows = found["days"]
    if not rows:
        return grid([empty_tile(L)], ROW)
    made = [tile(L.n(total(rows, PROBES)), word(L, "probes")),
            tile(L.n(sum(total(rows, name) for name in LEVELS)), word(L, "banned"))]
    return grid(made, 2) + bars(L, rows, PROBES)


def report_tile(L, row):
    answer = row.get("answer_s")
    return tile(L.n(row.get("n") or 0), esc(str(row.get("month") or "")),
                muted(f'{word(L, "answer")} '
                      f'{hours(L, None if answer is None else int(answer) // HOUR)}'))


def incident_tile(L, row):
    state = word(L, "open") if not row.get("closed") else hours(L, hours_of(row))
    return tile(state, esc(kind_label(L, row.get("kind"))), muted(esc(opened_day(row))))


def report_links(L, links):
    parts = [link(SECURITY_TXT, L.t(WORD + "report"))]
    for name in ("checklist", "thanks"):
        if links.get(name):
            parts.append(link(links[name], L.t(WORD + name)))
    return bits(parts)


def reports_block(L, found):
    made = [report_tile(L, row) for row in found["reports"]] or [empty_tile(L)]
    rows = [incident_tile(L, row) for row in found["incidents"]]
    if not rows:
        rows = [tile(word(L, "none"), word(L, "incidents"))]
    return grid(made, ROW) + grid(rows, ROW) + report_links(L, found["links"])


def blocks(L, found, now):
    return (traffic_block(L, found), uptime_block(L, found), backup_block(L, found),
            data_block(L, found, now), edge_block(L, found), decoy_block(L, found),
            reports_block(L, found))


def security_page(L, found, now):
    title = L.t(TITLE)
    yesterday = (now - timedelta(days=1)).date()
    body = [top_bar(PATH, found["links"]), f"<h1>{esc(title)}</h1>",
            f'<p class="lede">{word(L, "lede")}</p>',
            f'<p class="muted">{word(L, "asof", date=str(yesterday))}</p>']
    for key, made in zip(SECTIONS, blocks(L, found, now)):
        body.append(f"<h2>{esc(L.t(key))}</h2>{made}")
    body.append(f"<footer>{foot(L)}</footer>")
    return shell(title, "".join(body), L.code)


async def numbers(store, now, audit, heads, links=None):
    days = await site_days.rows(store, SITE_DAYS_KEEP)
    made = site_days.months(days)
    alive = await store.kv_get(BOT_KEY) or {}
    log = await manager_alerts.history(store, LOG_KIND, REPORTS_KEEP)
    return {"days": days, "months": made,
            "backup": site_days.backup_facts(now.timestamp()),
            "audit": dict(audit or {}),
            "reports": site_days.report_facts(await store.reports(REPORTS_KEEP), log),
            "incidents": await store.incidents(INCIDENTS_KEEP),
            "opens": await site_days.opens(store, [row["month"] for row in made]),
            "uptime_s": alive.get("uptime_s"), "heads": list(heads),
            "links": dict(links or {})}
