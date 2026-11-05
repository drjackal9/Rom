from . import badges, challenges, polls, render
from .agenda import cwl_signup
from .bingo import TRIPLE
from .retention import WAR_HISTORY_KEEP
from .warstats import month_start

EVENT_AWARD = "challenges.award"
EVENT_VOTE = "challenges.vote"
STATE_KEY = "challenges.vote"
CATEGORIES = ("mate", "attack", "defense", "generous", "steady", "welcome")
VOTE_OPTIONS = 4
SECTION_ROWS = 3


def candidates(records, limit=VOTE_OPTIONS):
    rows = []
    for record in records or ():
        for member in record.get("members") or ():
            for attack in member.get("attacks") or ():
                stars = attack.get("stars") or 0
                th, d_th = member.get("th"), attack.get("d_th")
                pos, d_pos = member.get("pos"), attack.get("d_pos")
                rows.append({"name": member.get("name"), "tag": member.get("tag"),
                             "stars": stars, "destr": attack.get("destr") or 0,
                             "th_up": bool(stars == TRIPLE and th and d_th and d_th > th),
                             "uphill": bool(pos and d_pos and d_pos < pos),
                             "opponent": record.get("opponent")})
    rows.sort(key=lambda row: (0 if row["th_up"] else 1 if row["uphill"] else 2,
                               -row["stars"], -row["destr"], row["name"] or ""))
    return rows[:limit]


def give(state, season, category, tag, name, ts):
    if category not in CATEGORIES:
        return None
    entry = {"season": season, "category": category, "tag": tag, "name": name, "ts": int(ts)}
    given = state.setdefault("awards", {}).setdefault("given", [])
    given.append(entry)
    state["awards"]["given"] = given[-WAR_HISTORY_KEEP:]
    badges.grant(state, tag, "premio", ts)
    return entry


def label(L, category):
    return L.t(f"award.category.{category}")


def given_card(L, category, name):
    return render.card("🏅", L.t("award.title"),
                       L.t("award.given", category=label(L, category), name=render.esc(name)))


def section(L, state, n=SECTION_ROWS):
    given = (state.get("awards") or {}).get("given") or []
    if not given:
        return None
    return L.t("award.section.head") + "\n" + render.quote("\n".join(
        L.t("award.section.row", category=label(L, row["category"]), name=render.esc(row["name"]))
        for row in given[-n:]))


def winner_card(L, row, votes):
    return render.card("🗳", L.t("vote.title"), L.t(
        "vote.winner", name=render.esc(row["name"]), stars=row["stars"],
        destr=L.pct(row["destr"], 0), votes=votes))


async def run(poller, t, closed_season):
    if poller.destination(t.settings, EVENT_VOTE)[0] == "off":
        return
    state = await challenges.load(poller.store, t.clan.alias)
    vote = (state.get("awards") or {}).get("vote")
    if closed_season and not vote:
        changed = await _open(poller, t, state, closed_season)
    elif vote:
        changed = await _close(poller, t, state)
    else:
        changed = False
    if changed:
        await challenges.save(poller.store, t.clan.alias, state)


async def _open(poller, t, state, season):
    rows = candidates(await poller.store.wars_since(t.clan.alias, month_start(season, t.tz)))
    if len(rows) < 2:
        return False
    options = [t.L.t("vote.option", name=row["name"], stars=row["stars"],
                     destr=t.L.pct(row["destr"], 0)) for row in rows]
    poll = await polls.open_poll(poller, t, STATE_KEY, EVENT_VOTE, t.L.t("vote.question"), options,
                                 extra={"season": season, "rows": rows,
                                        "ends": int(cwl_signup(t.now)[1].timestamp())})
    if not poll:
        return False
    state["awards"]["vote"] = poll
    return True


def _winner(vote):
    rows = vote.get("rows") or []
    tally = {}
    for choice in (vote.get("votes") or {}).values():
        index = (choice or {}).get("option")
        if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(rows):
            tally[index] = tally.get(index, 0) + 1
    if not tally:
        return None, 0
    index = max(tally, key=lambda key: (tally[key], -key))
    return rows[index], tally[index]


async def _close(poller, t, state):
    vote = state["awards"]["vote"]
    if t.now.timestamp() < (vote.get("ends") or 0):
        return False
    await polls.close_poll(poller, t, STATE_KEY)
    winner, votes = _winner(vote)
    if winner:
        badges.grant(state, winner["tag"], "attacco", int(t.now.timestamp()))
        await poller.dispatch(t, EVENT_VOTE, lambda L: winner_card(L, winner, votes))
    challenges.note(state, "vote", season=vote.get("season"), winner=(winner or {}).get("tag"),
                    ts=int(t.now.timestamp()))
    state["awards"]["vote"] = None
    return True


async def load_poll(store, alias):
    return ((await challenges.load(store, alias)).get("awards") or {}).get("vote")


async def save_poll(store, alias, poll):
    state = await challenges.load(store, alias)
    state["awards"]["vote"] = poll
    await challenges.save(store, alias, state)


polls.keeper(STATE_KEY, load_poll, save_poll)
