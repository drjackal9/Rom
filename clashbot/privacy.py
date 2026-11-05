import json

from . import discipline, feed, leaderboards, reports, scoring, warstats
from . import settings as settings_mod
from .events import member_stats
from .retention import WAR_HISTORY_KEEP
from .util import now_utc

KIND = leaderboards.STATE_KIND
KEY = "excluded"
FORGET_KEEP_DAYS = 365
EXPORT_WARS = WAR_HISTORY_KEEP
DAY = 86400
USER_PREFIXES = ("fb", "md", "tip", "terms")
BUNDLE_KINDS = ("members", "progress", "season", "hall", "notes", "queue_dm", "settings", KIND)


def _ts(value):
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dict(value):
    return value if isinstance(value, dict) else {}


def user_key(store, prefix, user_id):
    return f"{prefix}:{store.vault.blind('user', user_id)}"


def userclan_key(store, user_id):
    return user_key(store, "userclan", user_id)


def user_keys(store, user_id):
    return (userclan_key(store, user_id),) + tuple(user_key(store, p, user_id) for p in USER_PREFIXES)


def normalize(stored):
    if isinstance(stored, dict):
        items = list(stored.items())
    elif isinstance(stored, (list, tuple)):
        items = [(tag, {}) for tag in stored]
    else:
        items = []
    rows = {}
    for tag, row in items:
        if not isinstance(tag, str) or not tag.startswith("#"):
            continue
        row = _dict(row)
        rows[tag] = {"since": _ts(row.get("since")), "name": row.get("name") or None,
                     "gone": _ts(row.get("gone"))}
    return rows


def hidden_in(boards_state):
    return set(normalize(_dict(boards_state).get(KEY)))


def keep_visible(rows, hidden):
    if not hidden:
        return list(rows or ())
    return [row for row in rows or () if _dict(row).get("tag") not in hidden]


def member_tags(data, tags):
    members = _dict(_dict(data).get("members"))
    return {tag for tag in tags or () if tag in members}


async def drop_link(store, user_id, link):
    if not await store.unlink(user_id, link.tag):
        return False
    await store.kv_del(userclan_key(store, user_id))
    return True


async def _state(store, alias):
    return _dict(await store.get_state(alias, KIND))


async def _save(store, alias, state, rows):
    state[KEY] = rows
    await store.set_state(alias, KIND, state)


async def excluded(store, alias):
    return hidden_in(await _state(store, alias))


async def set_excluded(store, alias, tag, on, name=None, now=None):
    state = await _state(store, alias)
    rows = normalize(state.get(KEY))
    if bool(on) == (tag in rows):
        return False
    if on:
        rows[tag] = {"since": int((now or now_utc()).timestamp()), "name": name, "gone": 0}
    else:
        del rows[tag]
    await _save(store, alias, state, rows)
    return True


async def prune_excluded(store, alias, members, now):
    state = await _state(store, alias)
    rows = normalize(state.get(KEY))
    if not rows:
        return 0
    stamp = int(now.timestamp())
    cutoff = stamp - FORGET_KEEP_DAYS * DAY
    dropped, changed = 0, False
    for tag, row in list(rows.items()):
        if tag in (members or {}):
            if row["gone"]:
                row["gone"] = 0
                changed = True
            continue
        if not row["gone"]:
            row["gone"] = stamp
            changed = True
        elif row["gone"] < cutoff:
            del rows[tag]
            dropped += 1
            changed = True
    if changed:
        await _save(store, alias, state, rows)
    return dropped


def _points(entry):
    try:
        return scoring.points(entry)
    except (KeyError, TypeError):
        return 0


def _seasons(hall):
    return warstats.hall_state(hall)["seasons"]


def _titles_of(hall, name):
    out = []
    for entry in _seasons(hall):
        for title, row in _dict(entry.get("titles")).items():
            who = row[0] if isinstance(row, (list, tuple)) and row else None
            if who and who == name:
                out.append({"season": entry.get("season"), "title": title})
    return out


async def bundle(store, clan):
    return {kind: await store.get_state(clan.alias, kind) for kind in BUNDLE_KINDS}


def twitch_members(data):
    return _dict(_dict(_dict(data.get("settings")).get("twitch")).get("members"))


def _tags_touch(data, tags):
    tags = set(tags or ())
    season = _dict(data.get("season"))
    if tags & set(_dict(data.get("members"))) or tags & set(_dict(data.get("progress"))):
        return True
    if tags & set(_dict(season.get("members"))) or tags & set(_dict(data.get("notes"))):
        return True
    if tags & set(twitch_members(data)):
        return True
    return bool(tags & hidden_in(data.get(KIND)))


def scoped(data, links):
    return [row for row in links or () if _tags_touch(data, {row.tag})]


def local_names(data, links):
    return {row.name for row in scoped(data, links) if row.name}


def touches(data, user_id, tags):
    if _tags_touch(data, tags):
        return True
    who = str(user_id)
    return who in _dict(_dict(data.get("season")).get("predictions")) or who in _dict(data.get("queue_dm"))


async def places(store, user_id, links):
    tags = {row.tag for row in links or ()}
    found = []
    for clan in await store.active_clans():
        data = await bundle(store, clan)
        if touches(data, user_id, tags):
            found.append((clan, data))
    return found


def _account(link, clan, data, wars):
    entry = _dict(_dict(data.get("season")).get("members")).get(link.tag)
    return {
        "tag": link.tag,
        "name": link.name,
        "private_alerts": bool(link.dm),
        "clan": {"name": clan.name, "tag": clan.tag} if clan else None,
        "hidden_from_boards": link.tag in hidden_in(data.get(KIND)),
        "clan_row": _dict(data.get("members")).get(link.tag),
        "activity": _dict(data.get("progress")).get(link.tag),
        "season": entry,
        "season_points": _points(entry) if entry else 0,
        "wars": _dict(wars).get(link.tag),
        "twitch": twitch_members(data).get(link.tag),
        "titles": _titles_of(data.get("hall"), link.name),
        "leader_note": bool(_dict(data.get("notes")).get(link.tag)),
    }


async def collect(store, user_id, links, now, spots=None):
    who = str(user_id)
    clans, found = [], {}
    for clan, data in (await places(store, user_id, links) if spots is None else spots):
        wars = member_stats(await store.recent_wars(clan.alias, EXPORT_WARS))
        clans.append({
            "name": clan.name,
            "tag": clan.tag,
            "predictions": _dict(_dict(data.get("season")).get("predictions")).get(who),
            "queued": len(_dict(data.get("queue_dm")).get(who) or ()),
        })
        for row in links or ():
            if row.tag not in found and _tags_touch(data, {row.tag}):
                found[row.tag] = _account(row, clan, data, wars)
    return {
        "generated": now.isoformat(timespec="seconds"),
        "clans": clans,
        "accounts": [found.get(row.tag) or _account(row, None, {}, {}) for row in links or ()],
    }


def export_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode()


async def drop_warnings(store, alias, tags):
    entries = list(await store.get_state(alias, discipline.STATE) or ())
    kept = [row for row in entries if not (isinstance(row, dict) and row.get("tag") in tags)]
    if len(kept) == len(entries):
        return 0
    await store.set_state(alias, discipline.STATE, kept)
    return len(entries) - len(kept)


async def _erase_clan(store, clan, data, user_id, links, counts, now):
    alias = clan.alias
    who = str(user_id)
    tags = {row.tag for row in links}
    names = local_names(data, links)
    progress = data.get("progress")
    if isinstance(progress, dict) and tags & progress.keys():
        for tag in tags & progress.keys():
            del progress[tag]
            counts["activity"] += 1
        await store.set_state(alias, "progress", progress)
    season = data.get("season")
    if isinstance(season, dict):
        members = _dict(season.get("members"))
        gone = tags & members.keys()
        for tag in gone:
            del members[tag]
            counts["season"] += 1
        predictions = _dict(season.get("predictions"))
        guessed = who in predictions
        if guessed:
            del predictions[who]
        if gone or guessed:
            await store.set_state(alias, "season", season)
    hall = warstats.hall_state(data.get("hall"))
    scrubbed = False
    for entry in hall["seasons"]:
        titles = _dict(entry.get("titles"))
        for title in [name for name, row in titles.items()
                      if isinstance(row, (list, tuple)) and row and row[0] in names]:
            del titles[title]
            counts["titles"] += 1
            scrubbed = True
    if scrubbed:
        await store.set_state(alias, "hall", hall)
    notes = data.get("notes")
    if isinstance(notes, dict) and tags & notes.keys():
        for tag in tags & notes.keys():
            del notes[tag]
            counts["notes"] += 1
        await store.set_state(alias, "notes", notes)
    queued = data.get("queue_dm")
    if isinstance(queued, dict) and who in queued:
        del queued[who]
        counts["queued"] += 1
        await store.set_state(alias, "queue_dm", queued)
    channels = twitch_members(data)
    if tags & channels.keys():
        block = dict(_dict(_dict(data.get("settings")).get("twitch")))
        for tag in tags & channels.keys():
            del channels[tag]
            counts["twitch"] += 1
        block["members"] = channels
        await store.set_state(alias, "settings", settings_mod.merge(
            _dict(data.get("settings")), {"twitch": block}))
    for row in links:
        if await store.drop_former(alias, row.tag):
            counts["former"] += 1
    here = member_tags(data, tags)
    for row in links:
        if row.tag in here and await set_excluded(store, alias, row.tag, True, row.name, now):
            counts["hidden"] += 1
    counts["feed"] += await feed.forget(store, alias, user_id)
    counts["warnings"] += await drop_warnings(store, alias, tags)
    counts["reports"] += await reports.forget(store, alias, user_id)


async def erase(store, user_id, links, now):
    counts = {"links": 0, "keys": 0, "activity": 0, "season": 0, "titles": 0,
              "notes": 0, "queued": 0, "twitch": 0, "former": 0, "hidden": 0,
              "feed": 0, "warnings": 0, "reports": 0}
    spots = await places(store, user_id, links)
    for row in links or ():
        if await drop_link(store, user_id, row):
            counts["links"] += 1
    for key in user_keys(store, user_id):
        await store.kv_del(key)
        counts["keys"] += 1
    for clan, data in spots:
        await _erase_clan(store, clan, data, user_id, links or (), counts, now)
    return counts
