from datetime import datetime, timezone

from . import family as family_mod, progress as progress_mod, tournaments
from .util import parse_coc_time, to_int

METRIC_COUNTER = {"stars": "war_stars", "donated": "donated", "capital_gold": "capital_gold",
                  "loot": "loot", "games": "games"}
ACTIVITY_METRICS = ("activity", "both")
WAR_METRICS = ("stars", "triples")
CWL_METRIC = "stars"


def _in_window(record, start, end):
    ended = parse_coc_time(record.get("endTime"))
    if not ended:
        return False
    when = ended.timestamp()
    return when >= start and (end is None or when <= end)


def clash_from_wars(records, opp_tag, start, end):
    for record in records or ():
        if not opp_tag or record.get("opp_tag") != opp_tag:
            continue
        if not _in_window(record, start, end):
            continue
        return {"stars_a": to_int(record.get("stars")), "destr_a": float(record.get("destr") or 0),
                "stars_b": to_int(record.get("opp_stars")), "destr_b": float(record.get("opp_destr") or 0)}
    return None


async def clan_value(store, clan, metric, since, period="week", until=None, start=None):
    if metric in WAR_METRICS:
        from_ts = since.timestamp()
        end = until.timestamp() if until is not None else None
        records = [r for r in await store.wars_since(clan.alias, since) if _in_window(r, from_ts, end)]
        if metric == "stars":
            return sum(to_int(r.get("stars")) for r in records), sum(float(r.get("destr") or 0) for r in records)
        triples = sum(1 for r in records for m in r.get("members", [])
                      for a in m.get("attacks", []) if to_int(a.get("stars")) == 3)
        return triples, 0.0
    if metric in ACTIVITY_METRICS:
        return int(round(await family_mod.clan_activity(store, clan, period, start)
                         * tournaments.TENTHS)), 0.0
    rows = progress_mod.window(await store.get_state(clan.alias, "progress") or {}, period, start)
    key = METRIC_COUNTER.get(metric, metric)
    return sum(to_int(row.get(key)) for row in rows), 0.0


async def member_value(store, clan_alias, tag, metric, period="week", start=None):
    if not clan_alias:
        return 0
    rows = progress_mod.window(await store.get_state(clan_alias, "progress") or {}, period, start)
    row = next((r for r in rows if r.get("tag") == tag), None)
    if not row:
        return 0
    if metric in ACTIVITY_METRICS:
        return to_int(row.get("score")) * tournaments.TENTHS
    return to_int(row.get(METRIC_COUNTER.get(metric, metric)))


async def _family_hides(store, doc, clan):
    if doc["scope"] != "family":
        return False
    return not await family_mod.shows_score(store, clan)


async def _entry_hides(store, doc, entry):
    if entry["type"] != "clan" or doc["scope"] != "family":
        return False
    clan = await store.clan_by_alias(entry["ref"])
    return not clan or await _family_hides(store, doc, clan)


async def _scores(store, doc, index, start, end, now):
    since = datetime.fromtimestamp(start, timezone.utc)
    until = datetime.fromtimestamp(end, timezone.utc)
    windowed, counted, ties = {}, {}, {}
    for entry in doc["entries"]:
        if entry["type"] == "clan":
            clan = await store.clan_by_alias(entry["ref"])
            if not clan:
                continue
            if await _family_hides(store, doc, clan):
                value, tie = 0, 0.0
            else:
                value, tie = await clan_value(store, clan, doc["metric"], since,
                                              until=until, start=start)
            target = windowed if doc["metric"] in WAR_METRICS else counted
        else:
            value = await member_value(store, doc.get("clan_alias"), entry["ref"], doc["metric"],
                                       start=start)
            tie = 0.0
            target = counted
        target[entry["id"]] = to_int(value)
        ties[entry["id"]] = int(round(float(tie) * tournaments.TENTHS))
    doc["scores"].update(windowed)
    if counted:
        doc = tournaments.scope_scores(doc, index, counted, now.timestamp() < end)
    doc["ties"].update(ties)
    return doc


async def _pair_result(store, doc, left, right, start, end):
    if left["type"] != "clan" or right["type"] != "clan":
        return None
    other = await store.clan_by_alias(right["ref"])
    if not other:
        return None
    if await _family_hides(store, doc, other):
        return None
    records = await store.wars_since(left["ref"], datetime.fromtimestamp(start, timezone.utc))
    return clash_from_wars(records, other.tag, start, end)


async def _bracket(store, doc, now, index, start, end):
    known = {entry["id"]: entry for entry in doc["entries"]}
    closed = False
    for position, match in enumerate(list(doc["rounds"][index])):
        if match["done"] or not match["b"]:
            continue
        left, right = known.get(match["a"]), known.get(match["b"])
        if not left or not right:
            continue
        hidden = await _entry_hides(store, doc, left)
        row = None if hidden else await _pair_result(store, doc, left, right, start, end)
        if row:
            doc = tournaments.record_result(doc, index, position, row["stars_a"], row["stars_b"],
                                            int(round(row["destr_a"] * tournaments.TENTHS)),
                                            int(round(row["destr_b"] * tournaments.TENTHS)))
            closed = True
        elif now.timestamp() >= end:
            doc = tournaments.record_result(doc, index, position,
                                            doc["scores"].get(match["a"], 0), doc["scores"].get(match["b"], 0),
                                            doc["ties"].get(match["a"], 0), doc["ties"].get(match["b"], 0))
            closed = True
    if not closed:
        return doc, []
    doc = tournaments.note(doc, "round", index=index)
    if all(match["done"] for match in doc["rounds"][index]):
        doc = tournaments.close_round(doc, index)
    return doc, [{"type": "result", "index": index}]


async def _groups(store, doc):
    if doc["metric"] != CWL_METRIC or not any(entry["type"] == "clan" for entry in doc["entries"]):
        return doc
    known = {entry["id"]: entry for entry in doc["entries"]}
    results, seen = [], set()
    for group in doc["groups"] or [[entry["id"] for entry in doc["entries"]]]:
        for left_id in group:
            left = known.get(left_id)
            if not left or left["type"] != "clan":
                continue
            if await _entry_hides(store, doc, left):
                continue
            for right_id in group:
                if right_id == left_id or (right_id, left_id) in seen:
                    continue
                right = known.get(right_id)
                if not right or right["type"] != "clan":
                    continue
                row = await _pair_result(store, doc, left, right, doc["starts"], doc["ends"])
                if row:
                    seen.add((left_id, right_id))
                    results.append({"a": left_id, "b": right_id, **row})
    return tournaments.apply_clash(doc, results) if results else doc


async def refresh(store, doc, now):
    doc = tournaments.ensure(doc)
    if not tournaments.started(doc):
        return doc, []
    if doc["format"] == "bracket":
        index = tournaments.next_round(doc)
        current = len(doc["rounds"]) - 1 if index is None else index
        start, end = tournaments.round_window(doc, current)
        doc = await _scores(store, doc, current, start, end, now)
        if index is None:
            return doc, []
        return await _bracket(store, doc, now, index, start, end)
    doc = await _scores(store, doc, 0, doc["starts"], doc["ends"], now)
    return await _groups(store, doc), []
