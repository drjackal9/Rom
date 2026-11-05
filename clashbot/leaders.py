from datetime import timedelta

from . import delivery, feed, quiet, topics
from . import settings as settings_mod
from . import texts as free_text
from .util import esc, now_utc, zone

PACK = "leaders"
EVENTS = ("leaders.welcome", "leaders.rules", "leaders.scheduled", "leaders.gate",
          "leaders.exit", "leaders.promotion", "leaders.trial")
ROLES = frozenset({"leader", "coLeader"})
TEXT_MAX = 1000
SCHEDULE_TEXT_MAX = 500
SCHEDULE_MAX = 5
NOTE_MAX = 400
SENT_KEEP_DAYS = 7


def can_lead(roles):
    return bool(set(roles or ()) & ROLES)


def sanitize(raw, limit, bot_username=None, site_host=None):
    text = str(raw or "").replace("\r", "").strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    text = text[:limit]
    if bot_username is None:
        return text
    passed, why = free_text.filter(text, bot_username, site_host)
    if not passed:
        raise ValueError(why)
    return text


def fill(text, name=None, clan=None):
    out = esc(text)
    out = out.replace("{name}", esc(name) if name else "")
    return out.replace("{clan}", esc(clan) if clan else "")


def texts(conf):
    stored = (conf or {}).get("texts")
    stored = stored if isinstance(stored, dict) else {}
    return {key: sanitize(stored.get(key), TEXT_MAX) for key in ("welcome", "rules")}


def gate_on(conf):
    return bool((conf or {}).get("gate"))


def slot(raw):
    text = str(raw or "")
    if len(text) != 5 or text[2] != ":" or not (text[:2] + text[3:]).isdigit():
        return None
    hour, minute = int(text[:2]), int(text[3:])
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def days_of(raw):
    if not isinstance(raw, (list, tuple)):
        return []
    return sorted({d for d in raw if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6})


def schedule(conf):
    raw = (conf or {}).get("scheduled")
    out = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        hhmm = slot(entry.get("hhmm"))
        text = sanitize(entry.get("text"), SCHEDULE_TEXT_MAX)
        if not entry.get("id") or not hhmm or not text:
            continue
        out.append({"id": str(entry["id"])[:12], "hhmm": hhmm, "days": days_of(entry.get("days")),
                    "text": text, "by": entry.get("by")})
        if len(out) == SCHEDULE_MAX:
            break
    return out


def new_entry(entries, hhmm, days, text, by, bot_username=None, site_host=None):
    used = {str(e.get("id")) for e in entries or ()}
    free = [str(n) for n in range(1, SCHEDULE_MAX + 1) if str(n) not in used]
    clean = sanitize(text, SCHEDULE_TEXT_MAX, bot_username, site_host)
    if not free or not slot(hhmm) or not clean:
        return None
    return {"id": free[0], "hhmm": slot(hhmm), "days": days_of(days), "text": clean, "by": by}


def due(entries, now, tz, sent):
    local = now.astimezone(zone(tz))
    today = local.strftime("%Y-%m-%d")
    out = []
    for entry in entries or ():
        if entry["days"] and local.weekday() not in entry["days"]:
            continue
        hour, minute = (int(part) for part in entry["hhmm"].split(":"))
        if (local.hour, local.minute) < (hour, minute):
            continue
        key = f"{entry['id']}:{today}"
        if key in (sent or {}):
            continue
        out.append((key, entry))
    return out


def prune_sent(sent, now):
    cutoff = (now - timedelta(days=SENT_KEEP_DAYS)).timestamp()
    return {key: ts for key, ts in (sent or {}).items()
            if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > cutoff}


async def to_feed(store, clan, conf, event, text, now=None, to="leaders_dm"):
    from . import roles
    members = await store.get_state(clan.alias, "members") or {}
    sent = 0
    for uid in await roles.managers_for(store, clan, conf, members, to):
        await feed.add(store, clan.alias, uid, event, text, now or now_utc())
        sent += 1
    return sent


async def notify(store, bot, clan, conf, event, text, reply_markup=None, now=None, silent=False):
    where, _ = settings_mod.route(conf, event)
    if not text or where == "off":
        return 0
    if where not in topics.GROUP_DESTINATIONS:
        return await to_feed(store, clan, conf, event, text, now, where)
    if not bot:
        return 0
    if reply_markup is None and not silent and settings_mod.is_quiet(conf or {}, now or now_utc()):
        await quiet.enqueue(store, clan.alias, [text])
        return 1
    ok = await delivery.to_chat(store, bot, clan, text, thread_id=topics.thread_for(conf, event),
                                silent=silent, reply_markup=reply_markup)
    return 1 if ok else 0
