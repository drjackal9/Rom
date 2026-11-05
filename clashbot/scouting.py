from . import render_live, targets
from .achievements import player_snapshot
from .events import war_key
from .settings import route

STATE = "scout"
LOG_LIMIT = 20
TH_GAP = 2
RETRY = ("network", "rate", "maintenance")


def clan_facts(data):
    info = data or {}
    public = bool(info.get("isWarLogPublic"))
    return {
        "level": info.get("clanLevel"),
        "streak": info.get("warWinStreak"),
        "wins": info.get("warWins"),
        "losses": info.get("warLosses") if public else None,
        "ties": info.get("warTies") if public else None,
        "public": public,
        "league": (info.get("warLeague") or {}).get("name"),
    }


def log_facts(data):
    wins = losses = ties = stars = attacks = 0
    for item in (data or {}).get("items") or []:
        result = item.get("result")
        if result not in ("win", "lose", "tie"):
            continue
        wins += 1 if result == "win" else 0
        losses += 1 if result == "lose" else 0
        ties += 1 if result == "tie" else 0
        side = item.get("clan") or {}
        stars += side.get("stars") or 0
        attacks += side.get("attacks") or 0
    return {"wins": wins, "losses": losses, "ties": ties, "played": wins + losses + ties,
            "stars_per_attack": round(stars / attacks, 2) if attacks else None}


def opponent_snapshot(data):
    snapshot = player_snapshot(data)
    return {"th": snapshot["th"], "heroes": snapshot["heroes"], "stars": snapshot["warStars"]}


def members_of(members):
    if isinstance(members, dict):
        return list(members.values())
    return list(members or [])


def th_rows(members):
    rows = {}
    for m in members_of(members):
        th = m.get("th")
        if th:
            rows[th] = rows.get(th, 0) + 1
    return [[th, rows[th]] for th in sorted(rows, reverse=True)]


def average_th(members):
    values = [m.get("th") for m in members_of(members) if m.get("th")]
    return round(sum(values) / len(values), 2) if values else 0.0


def average_heroes(snapshots):
    totals = [sum((s.get("heroes") or {}).values()) for s in (snapshots or {}).values()]
    totals = [value for value in totals if value]
    return round(sum(totals) / len(totals), 1) if totals else 0.0


def mirrors(war):
    theirs = targets.by_pos(war.get("defenders"))
    rows = []
    for pos, m in sorted(targets.by_pos(war.get("members")).items()):
        other = theirs.get(pos) or {}
        rows.append({"pos": pos, "name": m.get("name"), "th": m.get("th"),
                     "target": other.get("name"), "target_th": other.get("th"),
                     "delta": (other.get("th") or 0) - (m.get("th") or 0)})
    return rows


def report(scout, war, our_players):
    ours, theirs = war.get("members") or {}, war.get("defenders") or {}
    players = (scout or {}).get("players") or {}
    our_avg, their_avg = average_th(ours), average_th(theirs)
    return {
        "size": len(ours), "gap": TH_GAP,
        "ours": th_rows(ours), "theirs": th_rows(theirs),
        "our_avg": our_avg, "their_avg": their_avg,
        "our_heroes": average_heroes({tag: p for tag, p in (our_players or {}).items() if tag in ours}),
        "their_heroes": average_heroes(players),
        "partial": len(players) < len(theirs),
        "clan": (scout or {}).get("clan") or {},
        "log": (scout or {}).get("log") or {},
        "mirrors": [row for row in mirrors(war) if row["delta"]],
        "harder": their_avg - our_avg >= TH_GAP,
        "easier": our_avg - their_avg >= TH_GAP,
    }


async def collect(poller, t, war, stored=None):
    alias = t.clan.alias
    key = war_key(war)
    scout = stored
    if not isinstance(scout, dict) or scout.get("war") != key:
        scout = {"war": key, "clan": None, "log": None, "players": {}, "cursor": 0, "sent": False}
    tag = (war.get("opponent") or {}).get("tag")
    if not tag:
        return scout
    if scout["clan"] is None or (scout["clan"] or {}).get("error") in RETRY:
        data, error = await poller.coc.clan(tag)
        scout["clan"] = clan_facts(data) if data else {"error": error}
    if scout["log"] is None or (scout["log"] or {}).get("error") in RETRY:
        data, error = await poller.coc.war_log(tag, LOG_LIMIT)
        scout["log"] = log_facts(data) if data else {"error": error}
    tags = sorted(war.get("defenders") or {})
    if scout["cursor"] < len(tags):
        data, _error = await poller.coc.player(tags[scout["cursor"]])
        if data:
            scout["players"][tags[scout["cursor"]]] = opponent_snapshot(data)
        scout["cursor"] += 1
    await poller.store.set_state(alias, STATE, scout)
    return scout


async def send(poller, t, war, scout, kind, day):
    scout["sent"] = True
    await poller.store.set_state(t.clan.alias, STATE, scout)
    if route(t.settings, "war.scout")[0] != "off":
        players = (await poller.store.get_state(t.clan.alias, "players") or {}).get("tags") or {}
        data = report(scout, war, players)
        await poller.dispatch(t, "war.scout",
                              lambda L: render_live.scout_card(L, data, kind, day))
    return scout


async def tick(poller, t, war, kind, day):
    if kind != "war" or war.get("state") != "preparation":
        return None
    if route(t.settings, "war.scout")[0] == "off" and route(t.settings, "war.forecast")[0] == "off":
        return None
    stored = await poller.store.get_state(t.clan.alias, STATE)
    if isinstance(stored, dict) and stored.get("war") == war_key(war) and stored.get("sent"):
        return stored
    scout = await collect(poller, t, war, stored)
    if scout["cursor"] < len(war.get("defenders") or {}):
        return scout
    return await send(poller, t, war, scout, kind, day)


async def at_start(poller, t, war, kind, day):
    if kind != "war":
        return None
    scout = await poller.store.get_state(t.clan.alias, STATE)
    if not isinstance(scout, dict) or scout.get("war") != war_key(war) or scout.get("sent"):
        return None
    return await send(poller, t, war, scout, kind, day)


async def forget(poller, t):
    await poller.store.del_state(t.clan.alias, STATE)
