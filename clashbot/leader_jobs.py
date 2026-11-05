import logging
from datetime import timedelta

from . import coaching, exports, leader_cards, leaders, ledger, scoring, warstats
from .events import member_stats
from .util import REPORT_HOUR, zone

log = logging.getLogger("clashbot.leader_jobs")
STATE = "scheduled"
MONDAY = 0
FIRST_DAY = 1


async def welcome(poller, t):
    text = leaders.texts(t.settings)["welcome"]
    names = [e.get("name") for e in (t.events or ()) if e.get("type") == "join" and e.get("name")]
    if not text or not names:
        return
    joined = ", ".join(names)
    await poller.dispatch(t, "leaders.welcome",
                          lambda L: leader_cards.welcome_card(L, text, joined, t.clan.name))


async def scheduled(poller, t):
    entries = leaders.schedule(t.settings)
    if not entries:
        return
    state = await poller.store.get_state(t.clan.alias, STATE) or {}
    sent = state.get("sent") or {}
    fired = leaders.due(entries, t.now, t.tz, sent)
    if not fired:
        return
    for key, entry in fired:
        await poller.dispatch(t, "leaders.scheduled",
                              lambda L, entry=entry: leader_cards.scheduled_message(
                                  L, entry["text"], t.clan.name))
        sent[key] = t.now.timestamp()
    await poller.store.set_state(t.clan.alias, STATE, {"sent": leaders.prune_sent(sent, t.now)})


async def leaving(poller, t):
    from . import gate
    if not gate.leave_rows(t.events):
        return
    rows = await gate.leavers_to_report(poller.bot_for(t.clan), poller.store, t.clan, t.events)
    if rows:
        await poller.dispatch(t, "leaders.exit", lambda L: leader_cards.exit_card(L, rows))


async def notes(poller, t):
    if t.members:
        await ledger.prune_notes(poller.store, t.clan.alias, t.members, t.now)


async def newcomers(poller, t):
    if not t.members:
        return
    stored = await poller.store.get_state(t.clan.alias, "players") or {}
    players = coaching.track(stored, t.members, t.events, t.now)
    due = coaching.trial_due(players, t.members, t.now)
    if due:
        stats = member_stats(await poller.store.recent_wars(t.clan.alias))
        season = await poller.store.get_state(t.clan.alias, "season") or {}
        activity = await poller.month_activity(t)
        rows = [{"name": row["name"], **coaching.record_of(row["tag"], stats, season, activity)}
                for row in due]
        await poller.dispatch(t, "leaders.trial", lambda L: leader_cards.trial_card(L, rows))
        players = coaching.mark_told(players, [row["tag"] for row in due])
    if players != stored:
        await poller.store.set_state(t.clan.alias, "players", players)


async def promotions(poller, t):
    if not t.members:
        return
    local = t.now.astimezone(zone(t.tz))
    if local.weekday() != MONDAY or local.hour < REPORT_HOUR:
        return
    season = await poller.store.get_state(t.clan.alias, "season") or {}
    if not (season.get("members") or {}):
        return
    week = local.strftime("%G-W%V")
    reports = await poller.store.get_state(t.clan.alias, "reports") or {}
    if reports.get("promo") == week:
        return
    stats = member_stats(await poller.store.recent_wars(t.clan.alias))
    players = await poller.store.get_state(t.clan.alias, "players") or {}
    rows = coaching.promotions(t.members, stats, season, await poller.month_activity(t), players,
                               t.now)
    if rows:
        await poller.dispatch(t, "leaders.promotion",
                              lambda L: leader_cards.promotion_card(L, rows))
    await poller.store.set_state(t.clan.alias, "reports", {**reports, "promo": week})


async def month_report(poller, t):
    if not t.members:
        return
    local = t.now.astimezone(zone(t.tz))
    if local.day != FIRST_DAY or local.hour < REPORT_HOUR:
        return
    month = local.strftime("%Y-%m")
    reports = await poller.store.get_state(t.clan.alias, "reports") or {}
    if reports.get("month") == month:
        return
    sid = scoring.season_id(t.now - timedelta(days=1), t.tz)
    start, end = warstats.month_start(sid, t.tz), warstats.month_end(sid, t.tz)
    records = await poller.store.wars_since(t.clan.alias, start)
    players = await poller.store.get_state(t.clan.alias, "players") or {}
    data = exports.month_data(records, t.members, await poller.closed_activity(t, "month"),
                              players, start, end)
    await poller.dispatch(t, "members.report",
                          lambda L: leader_cards.month_card(L, t.clan.name, data))
    await poller.store.set_state(t.clan.alias, "reports", {**reports, "month": month})


async def run(poller, t):
    for job in (welcome, scheduled, leaving, notes, newcomers, promotions, month_report):
        try:
            await job(poller, t)
        except Exception:
            log.exception("%s: %s fallito", t.clan.alias, job.__name__)
