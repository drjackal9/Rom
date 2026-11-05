from . import cwl_roster, cwl_season, cwl_store
from .scoring import WEIGHTS
from .util import now_utc


def value(row):
    return (int(row.get("attacks") or 0) * WEIGHTS["attack"]
            + int(row.get("stars") or 0) * WEIGHTS["star"]
            + int(row.get("triples") or 0) * WEIGHTS["triple"]
            + int(row.get("missed") or 0) * WEIGHTS["missed"])


def past_bonus(history):
    counts = {}
    for record in history or []:
        for m in record.get("members") or []:
            if m.get("bonus") and m.get("tag"):
                counts[m["tag"]] = counts.get(m["tag"], 0) + 1
    return counts


def proposal(rows, past=None, assigned=()):
    past = past or {}
    marked = set(assigned or ())
    out = [dict(r, value=value(r), past=past.get(r.get("tag"), 0), assigned=r.get("tag") in marked)
           for r in rows or [] if (r.get("attacks") or 0) or (r.get("wars") or 0)]
    out.sort(key=lambda r: (-r["value"], r["past"], -(r.get("stars") or 0), r.get("name") or ""))
    return out


def toggle(state, tag):
    return cwl_roster.mark(state, cwl_roster.BONUS, tag)


async def sync_season(store, alias, season, bonus):
    if not season:
        return False
    record = next((r for r in await cwl_store.seasons(store, alias, 3) if r.get("season") == season), None)
    if not record:
        return False
    marked = set(bonus or ())
    for m in record.get("members") or []:
        m["bonus"] = m.get("tag") in marked
    await cwl_store.save_season(store, alias, season, cwl_season.ended_at(record, now_utc()), record)
    return True
