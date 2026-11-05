import logging
import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ops
from .db import SITE_DAY_FIELDS
from .manager_alerts import OPENS_KEY, REPORT_MARK
from .selfmetrics import PROBE_DAY, WEB_DAY
from .trend import DAYS
from .util import day_of

log = logging.getLogger("clashbot.site_days")

GRAPHQL = "https://api.cloudflare.com/client/v4/graphql"
TOKEN_KIND = "cloudflare_analytics"
ZONE_KIND = "cloudflare_zone"
RESTORE_LOG = "/backup/restore.log"
BACKUP_EVERY_H = 24
PAGE = 10000
HOURS = 24
CLOSED_KEY = "site:closed"
WEB_FIELDS = ("own_requests", "misses", "limited", "probes",
              "banned_h", "banned_d", "banned_forever")
KEPT = re.compile(r"prune-ok tenuti=(\d+)")
STARTED = "restore-start"
ENDED = {"restore-ok": True, "restore-FAIL": False}
BLOCKING = ("block", "drop", "challenge", "jschallenge", "managedchallenge", "connectionclose")
SOURCES = {"firewallcustom": "blocked_rule", "firewallmanaged": "blocked_waf",
           "waf": "blocked_waf", "botfight": "blocked_bot", "bic": "blocked_bot"}
BLOCKED_FIELDS = ("blocked_waf", "blocked_bot", "blocked_rule")

TRAFFIC = """query($zone: String!, $day: Date!) {
  viewer { zones(filter: {zoneTag: $zone}) {
    httpRequests1dGroups(limit: 1, filter: {date: $day}) {
      sum { requests pageViews countryMap { clientCountryName requests } }
      uniq { uniques }
    }
  } }
}"""

FIREWALL = """query($zone: String!, $from: Time!, $to: Time!, $limit: Int!) {
  viewer { zones(filter: {zoneTag: $zone}) {
    firewallEventsAdaptive(limit: $limit, filter: {datetime_geq: $from, datetime_lt: $to},
                           orderBy: [datetime_ASC]) {
      action source datetime rayName
    }
  } }
}"""


class Refused(Exception):
    pass


def stamp(day, hour=0):
    return f"{day}T{hour:02d}:00:00Z"


async def ask(client, token, query, variables):
    res = await client.post(GRAPHQL, json={"query": query, "variables": variables},
                            headers={"Authorization": f"Bearer {token}"})
    if int(res.status_code) != ops.OK_STATUS:
        raise Refused(f"stato {res.status_code}")
    body = res.json() or {}
    if body.get("errors"):
        raise Refused("risposta con errori")
    zones = ((body.get("data") or {}).get("viewer") or {}).get("zones") or []
    first = zones[0] if zones else None
    if not isinstance(first, dict):
        raise Refused("zona non visibile")
    return first


def countries_of(sums):
    found = {}
    for row in sums.get("countryMap") or ():
        name = row.get("clientCountryName")
        if name:
            found[str(name)] = int(row.get("requests") or 0)
    return found


def traffic_of(body):
    groups = body.get("httpRequests1dGroups") or []
    first = groups[0] if groups else {}
    sums = first.get("sum") or {}
    return {"requests": int(sums.get("requests") or 0),
            "pages": int(sums.get("pageViews") or 0),
            "visitors": int((first.get("uniq") or {}).get("uniques") or 0),
            "countries": countries_of(sums)}


def word(value):
    return str(value or "").replace("_", "").lower()


def counted(rows):
    found = dict.fromkeys(BLOCKED_FIELDS, 0)
    found["blocked_total"] = 0
    for row in rows:
        if word(row.get("action")) not in BLOCKING:
            continue
        found["blocked_total"] += 1
        field = SOURCES.get(word(row.get("source")))
        if field:
            found[field] += 1
    return found


def ident(row):
    return (str(row.get("rayName") or ""), str(row.get("datetime") or ""),
            word(row.get("action")), word(row.get("source")))


def unseen(rows, seen, since):
    made = []
    for row in rows:
        key = ident(row)
        if key[1] == since and seen.get(key):
            seen[key] -= 1
            continue
        made.append(row)
    return made


def border(rows, at):
    found = {}
    for row in rows:
        key = ident(row)
        if key[1] == at:
            found[key] = found.get(key, 0) + 1
    return found


async def window(client, token, zone, start, edge, limit):
    found, seen, since = [], {}, start
    for _ in range(PAGE):
        body = await ask(client, token, FIREWALL,
                         {"zone": zone, "from": since, "to": edge, "limit": limit})
        rows = body.get("firewallEventsAdaptive") or []
        fresh = unseen(rows, seen, since)
        found.extend(fresh)
        if len(rows) < limit:
            return found
        ahead = max((str(row.get("datetime") or "") for row in rows), default="")
        if ahead <= since:
            raise Refused(f"finestra che non avanza da {since}")
        seen, since = border(fresh, ahead), ahead
    raise Refused(f"finestra senza fine da {start}")


async def events(client, token, zone, day, limit=PAGE):
    found = []
    after = day + timedelta(days=1)
    for hour in range(HOURS):
        edge = stamp(day, hour + 1) if hour + 1 < HOURS else stamp(after)
        found.extend(await window(client, token, zone, stamp(day, hour), edge, limit))
    return found


async def pull(client, token, zone, day, limit=PAGE):
    if client is None or not token or not zone:
        return None
    found = traffic_of(await ask(client, token, TRAFFIC, {"zone": zone, "day": str(day)}))
    found.update(counted(await events(client, token, zone, day, limit)))
    return found


def whole(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def web_counts(stored):
    body = stored if isinstance(stored, dict) else {}
    return {name: int(body.get(name) or 0) for name in WEB_FIELDS}


def probe_counts(stored):
    body = stored if isinstance(stored, dict) else {}
    samples = [whole(one) for one in body.get("ms") or ()]
    samples = sorted(one for one in samples if one is not None)
    return {"probe_ok": int(body.get("ok") or 0), "probe_total": int(body.get("total") or 0),
            "probe_ms_med": int(statistics.median(samples)) if samples else 0,
            "probe_ms_max": max(samples) if samples else 0}


async def close_day(store, now, tz=None, client=None):
    day = day_of(now, tz) - timedelta(days=1)
    closed = await store.kv_get(CLOSED_KEY) or {}
    if str(closed.get("day") or "") >= str(day):
        return None
    row = dict.fromkeys(SITE_DAY_FIELDS, 0)
    row["countries"] = {}
    row.update(web_counts(await store.kv_get(WEB_DAY + str(day))))
    row.update(probe_counts(await store.kv_get(PROBE_DAY + str(day))))
    try:
        found = await pull(client, await store.get_secret(TOKEN_KIND),
                           await store.get_secret(ZONE_KIND), day)
    except Refused as e:
        log.warning("Cloudflare non risponde (%s): il giorno %s resta aperto", e, day)
        return None
    if not found:
        log.warning("Cloudflare non configurata: il giorno %s resta aperto", day)
        return None
    row.update(found)
    await store.site_day_put(day, row)
    await store.kv_set(CLOSED_KEY, {"day": str(day)})
    return row


async def rows(store, days=DAYS):
    return await store.site_days(int(days))


def month_of(at):
    return datetime.fromtimestamp(float(at or 0), timezone.utc).strftime("%Y-%m")


def uptime_of(ok, total):
    return round(100.0 * ok / total, 1) if total else None


def months(found):
    groups = {}
    for row in found or ():
        groups.setdefault(str(row.get("day"))[:7], []).append(row)
    made = []
    for key in sorted(groups):
        part = groups[key]
        ok = sum(int(row.get("probe_ok") or 0) for row in part)
        total = sum(int(row.get("probe_total") or 0) for row in part)
        meds = [whole(row.get("probe_ms_med")) for row in part if row.get("probe_ms_med")]
        tops = [whole(row.get("probe_ms_max")) for row in part if row.get("probe_ms_max")]
        clean = [row for row in part if int(row.get("probe_total") or 0)
                 and int(row.get("probe_ok") or 0) == int(row.get("probe_total") or 0)]
        made.append({"month": key, "days": len(part), "uptime": uptime_of(ok, total),
                     "ms_med": int(statistics.median(meds)) if meds else None,
                     "ms_max": max(tops) if tops else None, "clean": len(clean)})
    return made


def read_log(path):
    file = Path(path)
    try:
        return file.read_text(encoding="utf-8"), file.stat().st_mtime
    except (OSError, ValueError):
        return None, None


def shifted(path):
    text, written = read_log(path)
    if not text:
        return (), 0.0
    found = ops.stamps(text)
    return found, (written - found[-1][0]) if found else 0.0


def kept_dumps(path):
    text, _ = read_log(path)
    found = KEPT.findall(text or "")
    return int(found[-1]) if found else None


def restore_facts(path):
    found, shift = shifted(path)
    end = next(((when, mark) for when, mark in reversed(found) if mark in ENDED), None)
    if end is None:
        return {"restore_ok": None, "restore_at": None, "restore_s": None}
    started = [when for when, mark in found if mark == STARTED and when <= end[0]]
    return {"restore_ok": ENDED[end[1]], "restore_at": end[0] + shift,
            "restore_s": int(end[0] - started[-1]) if started else None}


def backup_facts(now, backup=ops.BACKUP_LOG, restore=RESTORE_LOG):
    found = {"dump_age_h": ops.dump_age_h(backup, now), "dumps": kept_dumps(backup),
             "rpo_h": BACKUP_EVERY_H}
    found.update(restore_facts(restore))
    return found


async def opens(store, keys):
    stored = await store.kv_get(OPENS_KEY) or {}
    return {str(key): int((stored or {}).get(str(key)) or 0) for key in keys}


def first_by_code(found, mark=None):
    seen = {}
    for row in found or ():
        code = row.get("code")
        if not code or (mark is not None and row.get("what") != mark):
            continue
        at = float(row.get("at") or 0)
        if code not in seen or at < seen[code]:
            seen[code] = at
    return seen


def report_facts(found, log):
    answered = first_by_code(log, REPORT_MARK)
    groups = {}
    for row in found or ():
        groups.setdefault(month_of(row.get("at")), {"n": 0, "waits": []})["n"] += 1
    for code, at in first_by_code(found).items():
        reply = answered.get(code)
        if reply is not None and reply >= at:
            groups.setdefault(month_of(at), {"n": 0, "waits": []})["waits"].append(reply - at)
    made = []
    for key in sorted(groups):
        waits = groups[key]["waits"]
        made.append({"month": key, "n": groups[key]["n"],
                     "answer_s": int(statistics.median(waits)) if waits else None})
    return made
