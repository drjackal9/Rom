from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import family as family_mod, tournaments, tourney_ui
from .render import card, esc, quote, rank
from .util import REPORT_HOUR, bar, zone

AUTO_START = tournaments.SIGNUP_WINDOW
METRICS = tourney_ui.CLAN_METRICS
DROPS_PER_ROW = 4
NAME_CHARS = 12
SKIPPED = "skipped"
SAVED_KEY = "fam:{alias}:derby"


def saved_key(alias):
    return SAVED_KEY.format(alias=alias)


def week_id(now, tz):
    return now.astimezone(zone(tz)).strftime("%G-W%V")


def week_end(now, tz):
    local = now.astimezone(zone(tz))
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=REPORT_HOUR, minute=0, second=0, microsecond=0)
    return int((monday + timedelta(days=7)).timestamp())


async def build(store, family, now, tz):
    records = await store.kv_get(f"fam:{family.alias}:records") or {}
    metric = records.get("metric") if records.get("metric") in METRICS else "both"
    opens = int(now.timestamp())
    doc = tournaments.empty("derby", "family", metric, "table",
                            opens, opens + AUTO_START, week_end(now, tz),
                            size=tournaments.MAX_ENTRIES, week=week_id(now, tz))
    for clan in await store.family_clans(family.alias):
        if not await family_mod.shows_score(store, clan):
            continue
        doc, _ = tournaments.join(doc, "clan", clan.alias, clan.name)
    return doc


def apply(doc, data):
    doc = tournaments.ensure(doc)
    parts = (data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    value = ":".join(parts[2:])
    if action == "metric" and value in METRICS:
        doc["metric"] = value
    elif action == "drop" and value:
        doc, _ = tournaments.leave(doc, value)
    elif action == "go":
        doc["starts"] = min(doc["starts"], doc["opens"])
    elif action == "skip":
        doc["entries"] = []
        doc = tournaments.note(doc, SKIPPED)
    return doc


def skipped(doc):
    return any(row.get("kind") == SKIPPED for row in tournaments.ensure(doc)["log"])


def _positions(rows):
    order = sorted(rows, key=lambda row: -row[1])
    return {row[0]: index + 1 for index, row in enumerate(order)}


async def scores(store, family, doc, now):
    doc = tournaments.ensure(doc)
    clan_rows, _, _, _ = await family_mod.digest_data(store, family, now)
    shown, activity = set(), {}
    for clan in await store.family_clans(family.alias):
        if not await family_mod.shows_score(store, clan):
            continue
        shown.add(clan.alias)
        activity[clan.alias] = int(round(
            await family_mod.clan_activity(store, clan, start=doc["starts"]) * tournaments.TENTHS))
    stars = {row["alias"]: int(row["stars"]) for row in clan_rows if row["alias"] in shown}
    metric = doc["metric"]
    star_of = {entry["id"]: stars.get(entry["ref"], 0) for entry in doc["entries"]}
    act_of = {entry["id"]: activity.get(entry["ref"], 0) for entry in doc["entries"]}
    if metric == "stars":
        values, ties = star_of, act_of
    elif metric == "activity":
        values, ties = act_of, star_of
    else:
        total = len(doc["entries"])
        star_pos = _positions(list(star_of.items()))
        act_pos = _positions(list(act_of.items()))
        values = {eid: total * 2 - (star_pos[eid] + act_pos[eid]) for eid in star_of}
        ties = star_of
    kept = {entry["id"] for entry in doc["entries"] if entry["ref"] in shown}
    doc["scores"] = {eid: value if eid in kept else 0 for eid, value in values.items()}
    doc["ties"] = {eid: value if eid in kept else 0 for eid, value in ties.items()}
    return doc


def mission_of(records, metric, value):
    records = records or {}
    best = int(records.get(metric) or 0)
    return {"metric": metric, "goal": best, "best": best, "value": int(value),
            "hit": int(value) >= best, "first": metric not in records}


def _rows(L, doc):
    rows = tournaments.table(doc)
    return "\n".join(L.t("derby.row", rank=rank(L, i), name=esc(row["name"]), value=L.n(row["value"]))
                     for i, row in enumerate(rows)) or L.t("derby.empty")


def view(L, family, doc, proposal):
    doc = tournaments.ensure(doc)
    body = quote(_rows(L, doc))
    body += "\n" + L.t("derby.metric", value=tourney_ui.metric_label(L, doc["metric"]))
    mission = doc.get("mission")
    if mission and mission.get("first"):
        body += "\n" + L.t("derby.mission.first", value=L.n(mission["value"]))
    elif mission:
        pct = 100 if not mission["goal"] else min(100, mission["value"] * 100 // mission["goal"])
        body += "\n" + L.t("derby.mission", bar=bar(pct), value=L.n(mission["value"]),
                           goal=L.n(mission["goal"]))
    title = L.t("derby.proposed" if proposal else "derby.title", name=esc(family.name).upper())
    return card("🚩", title, body)


def notice(L, doc):
    doc = tournaments.ensure(doc)
    return L.t("derby.notice", metric=tourney_ui.metric_label(L, doc["metric"]),
               n=len(doc["entries"]))


def board_lines(L, doc):
    doc = tournaments.ensure(doc)
    lines = [L.t("family.notice.row", icon=L.t("family.notice.icon.derby"), text=notice(L, doc))]
    lines += [L.t("derby.row", rank=rank(L, i), name=esc(row["name"]), value=L.n(row["value"]))
              for i, row in enumerate(tournaments.table(doc))]
    mission = doc.get("mission")
    if mission and mission.get("hit") and not mission.get("first"):
        lines.append(L.t("derby.end.mission.hit", value=L.n(mission["value"]),
                         goal=L.n(mission["goal"])))
    elif mission and mission.get("first"):
        lines.append(L.t("derby.mission.first", value=L.n(mission["value"])))
    return lines


def keyboard(L, doc):
    doc = tournaments.ensure(doc)
    rows = [[InlineKeyboardButton(tourney_ui.metric_label(L, m), callback_data=f"dy:metric:{m}")
             for m in METRICS]]
    drops = [InlineKeyboardButton(entry["name"][:NAME_CHARS], callback_data=f"dy:drop:{entry['id']}")
             for entry in doc["entries"]]
    rows += [drops[i:i + DROPS_PER_ROW] for i in range(0, len(drops), DROPS_PER_ROW)]
    rows.append([InlineKeyboardButton(L.t("derby.btn.go"), callback_data="dy:go"),
                 InlineKeyboardButton(L.t("derby.btn.skip"), callback_data="dy:skip")])
    return InlineKeyboardMarkup(rows)


def end_card(L, family, doc):
    doc = tournaments.ensure(doc)
    eid = tournaments.winner(doc)
    body = quote(_rows(L, doc))
    if eid:
        body = L.t("derby.end.winner", name=esc(tournaments.name_of(doc, eid))) + "\n" + body
    mission = doc.get("mission")
    if mission and mission.get("first"):
        body += "\n" + L.t("derby.end.mission.first", value=L.n(mission["value"]))
    elif mission:
        body += "\n" + L.t("derby.end.mission.hit" if mission["hit"] else "derby.end.mission.miss",
                           value=L.n(mission["value"]), goal=L.n(mission["goal"]))
    return card("🏁", L.t("derby.end.title", name=esc(family.name).upper()), body)
