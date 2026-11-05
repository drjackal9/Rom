import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import agenda, badges, challenges, render, scoring, ttl
from .retention import WAR_HISTORY_KEEP
from .settings import route
from .util import now_utc

EVENT = "challenges.duel"
PROPOSAL_TTL = ttl.ONBOARD_TTL
METRICS = {
    "loot": ("gold", "elixir"),
    "war_stars": ("war_stars",),
    "donated": ("donated",),
    "capital_gold": ("capital_gold",),
    "levels": ("levels",),
}
DURATIONS = {"raid": 3 * 86400, "week": 7 * 86400}
SEASON = "season"
DURATION_KEYS = (*DURATIONS, SEASON)
RUNNING = ("open", "pending")
SECTION_ROWS = 5
FLOW = "duel"
DUEL_STEPS = ("who", "metric", "duration")
DONE = "done"
PICK_COLUMNS = 3


def value(counters, metric):
    row = counters if isinstance(counters, dict) else {}
    total = 0
    for key in METRICS.get(metric, ()):
        try:
            total += int(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _now_counters(progress, tag):
    entry = (progress or {}).get(tag)
    return (entry or {}).get("now") if isinstance(entry, dict) else None


def _pair(duel):
    return duel["a"]["tag"], duel["b"]["tag"]


def _sound(duel):
    return (isinstance(duel, dict) and duel.get("metric") in METRICS
            and duel.get("duration") in DURATION_KEYS
            and all(isinstance(duel.get(side), dict) and duel[side].get("tag") for side in ("a", "b")))


def _open(state):
    return [duel for duel in state["duels"]["open"] if _sound(duel)]


def running(state):
    return [duel for duel in _open(state) if duel.get("status") in RUNNING]


def propose(state, a, b, metric, duration, now):
    if metric not in METRICS or duration not in DURATION_KEYS:
        return None
    open_duels = state["duels"]["open"]
    for duel in _open(state):
        if duel["metric"] == metric and set(_pair(duel)) == {a["tag"], b["tag"]}:
            return None
    duel = {
        "id": secrets.token_hex(4),
        "status": "proposed",
        "metric": metric,
        "duration": duration,
        "a": dict(a),
        "b": dict(b),
        "proposed": int(now.timestamp()),
        "base": {},
        "ends": 0,
    }
    open_duels.append(duel)
    return duel


def _expired(duel, now):
    return (duel.get("status") == "proposed"
            and int(now.timestamp()) - int(duel.get("proposed") or 0) > PROPOSAL_TTL)


def _drop_expired(state, now):
    fresh = [duel for duel in _open(state) if not _expired(duel, now)]
    dropped = len(state["duels"]["open"]) - len(fresh)
    state["duels"]["open"] = fresh
    return dropped


def _ends_at(duration, now):
    if duration == SEASON:
        return int(agenda.season_end(now).timestamp())
    return int(now.timestamp()) + DURATIONS[duration]


def _begin(duel, progress, now):
    counters = {tag: _now_counters(progress, tag) for tag in _pair(duel)}
    if any(row is None for row in counters.values()):
        duel["status"] = "pending"
        return duel
    duel["status"] = "open"
    duel["base"] = {tag: value(row, duel["metric"]) for tag, row in counters.items()}
    duel["ends"] = _ends_at(duel["duration"], now)
    return duel


def accept(state, duel_id, user_id, progress, now):
    _drop_expired(state, now)
    for duel in _open(state):
        if duel.get("id") != duel_id or duel.get("status") != "proposed":
            continue
        if int(duel["b"].get("user_id") or 0) != int(user_id):
            return None
        return _begin(duel, progress, now)
    return None


def start_pending(state, progress, now):
    started = []
    for duel in _open(state):
        if duel.get("status") != "pending":
            continue
        if _begin(duel, progress, now)["status"] == "open":
            started.append(duel)
    return started


def due(state, now):
    return [duel for duel in _open(state)
            if duel.get("status") == "open" and int(duel.get("ends") or 0) <= int(now.timestamp())]


def verdict(duel, progress):
    scores = {}
    base = duel.get("base") or {}
    for tag in _pair(duel):
        current = value(_now_counters(progress, tag) or {}, duel["metric"])
        scores[tag] = max(0, current - int(base.get(tag) or 0))
    a_tag, b_tag = _pair(duel)
    if scores[a_tag] == scores[b_tag]:
        return {"winner": None, "scores": scores}
    winner = duel["a"] if scores[a_tag] > scores[b_tag] else duel["b"]
    return {"winner": winner, "scores": scores}


def section(L, state):
    rows = running(state)
    if not rows:
        return None
    return L.t("duel.section.head", n=len(rows)) + "\n" + render.quote("\n".join(
        L.t("duel.section.row", a=render.esc(duel["a"].get("name")), b=render.esc(duel["b"].get("name")),
            metric=L.t(f"duel.metric.{duel['metric']}")) for duel in rows[:SECTION_ROWS]))


def result_card(L, duel, outcome):
    metric = L.t(f"duel.metric.{duel['metric']}")
    a_tag, b_tag = _pair(duel)
    body = render.quote("\n".join([
        L.t("duel.result.row", name=render.esc(duel["a"]["name"]), value=L.n(outcome["scores"][a_tag])),
        L.t("duel.result.row", name=render.esc(duel["b"]["name"]), value=L.n(outcome["scores"][b_tag])),
    ]))
    if outcome["winner"]:
        body += "\n\n" + L.t("duel.result.win", name=render.esc(outcome["winner"]["name"]))
    else:
        body += "\n\n" + L.t("duel.result.tie")
    return render.card("🤺", L.t("duel.result.title", metric=metric), body)


def _verdict_text(duel, outcome):
    return lambda L: result_card(L, duel, outcome)


async def run(poller, t):
    dest = route(t.settings, EVENT)[0]
    if dest == "off":
        return
    state = await challenges.load(poller.store, t.clan.alias)
    progress = await poller.read_progress(t)
    changed = bool(_drop_expired(state, t.now))
    changed = bool(start_pending(state, progress, t.now)) or changed
    closed = []
    for duel in due(state, t.now):
        outcome = verdict(duel, progress)
        text = _verdict_text(duel, outcome)
        if dest == "member_dm":
            for side in (duel["a"], duel["b"]):
                await poller.dispatch(t, EVENT, text, member_tag=side["tag"])
        else:
            await poller.dispatch(t, EVENT, text)
        if outcome["winner"]:
            badges.grant(state, outcome["winner"]["tag"], "duello", int(t.now.timestamp()))
            if outcome["winner"].get("user_id"):
                scoring.apply_play(t.season, outcome["winner"]["user_id"], outcome["winner"]["name"], "duels")
        duel["status"] = "done"
        duel["winner"] = (outcome["winner"] or {}).get("tag")
        duel["scores"] = outcome["scores"]
        challenges.note(state, "duel", id=duel.get("id"), metric=duel["metric"],
                        winner=duel["winner"], ts=int(t.now.timestamp()))
        closed.append(duel)
    if closed:
        state["duels"]["open"] = [d for d in state["duels"]["open"] if d.get("status") != "done"]
        state["duels"]["done"] = (state["duels"]["done"] + closed)[-WAR_HISTORY_KEEP:]
    if changed or closed:
        await challenges.save(poller.store, t.clan.alias, state)


def next_step(flow):
    return next((step for step in DUEL_STEPS if not flow.get(step)), DONE)


def wizard_keyboard(L, flow, rivals):
    if flow["step"] == "who":
        buttons = [InlineKeyboardButton(link.name, callback_data=f"d:who:{link.tag}") for link in rivals]
        rows = [buttons[i:i + PICK_COLUMNS] for i in range(0, len(buttons), PICK_COLUMNS)]
    elif flow["step"] == "metric":
        rows = [[InlineKeyboardButton(L.t(f"duel.metric.{metric}"), callback_data=f"d:metric:{metric}")]
                for metric in METRICS]
    else:
        rows = [[InlineKeyboardButton(L.t(f"duel.duration.{key}"), callback_data=f"d:duration:{key}")]
                for key in DURATION_KEYS]
    rows.append([InlineKeyboardButton(L.t("menu.back"), callback_data="v:challenges")])
    return InlineKeyboardMarkup(rows)


async def rivals_of(store, clan, user_id):
    members = await store.get_state(clan.alias, "members") or {}
    links = await store.links_for_players(list(members))
    return links, [link for link in links.values() if link.user_id != user_id]


async def cmd_duel(update, context):
    from .handlers import clan_for, services, user_locale, view_locale
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    _, rivals = await rivals_of(store, clan, update.effective_user.id)
    if not rivals:
        await update.effective_message.reply_text(L.t("duel.nobody"))
        return
    flow = context.user_data[FLOW] = {"step": DUEL_STEPS[0]}
    await update.effective_message.reply_text(L.t("duel.ask_who"),
                                              reply_markup=wizard_keyboard(L, flow, rivals))


async def on_duel_callback(update, context):
    from .handlers import clan_for, edit_or_log, services, view_locale
    query = update.callback_query
    parts = query.data.split(":")
    store, _ = services(context)
    clan = await clan_for(update, context)
    if len(parts) < 3 or not clan:
        await query.answer()
        return
    L, _ = await view_locale(update, context, clan)
    user_id = update.effective_user.id
    if parts[1] == "accept":
        await _accepted(query, store, clan, L, parts[2], user_id)
        return
    if parts[1] not in DUEL_STEPS:
        await query.answer()
        return
    links, rivals = await rivals_of(store, clan, user_id)
    flow = context.user_data.get(FLOW) or {}
    flow[parts[1]] = parts[2]
    flow["step"] = next_step(flow)
    context.user_data[FLOW] = flow
    await query.answer()
    if flow["step"] != DONE:
        await edit_or_log(query, L.t(f"duel.ask_{flow['step']}"),
                          wizard_keyboard(L, flow, rivals), clan.alias)
        return
    context.user_data.pop(FLOW, None)
    await _proposed(query, store, clan, L, flow, links, user_id)


async def _accepted(query, store, clan, L, duel_id, user_id):
    from .handlers import edit_or_log
    state = await challenges.load(store, clan.alias)
    progress = await store.get_state(clan.alias, "progress") or {}
    duel = accept(state, duel_id, user_id, progress, now_utc())
    await challenges.save(store, clan.alias, state)
    if not duel:
        await query.answer(L.t("duel.not_yours"), show_alert=True)
        return
    await query.answer()
    await edit_or_log(query, L.t("duel.accepted", a=render.esc(duel["a"]["name"]),
                                 b=render.esc(duel["b"]["name"]),
                                 metric=L.t(f"duel.metric.{duel['metric']}")), None, clan.alias)


async def _proposed(query, store, clan, L, flow, links, user_id):
    from .handlers import edit_or_log
    mine = [link for link in await store.links_by_user(user_id) if link.tag in links]
    other = links.get(flow["who"])
    if not mine or not other or other.user_id == user_id:
        await edit_or_log(query, L.t("duel.nobody"), None, clan.alias)
        return
    state = await challenges.load(store, clan.alias)
    duel = propose(state, {"tag": mine[0].tag, "name": mine[0].name, "user_id": user_id},
                   {"tag": other.tag, "name": other.name, "user_id": other.user_id},
                   flow["metric"], flow["duration"], now_utc())
    await challenges.save(store, clan.alias, state)
    if not duel:
        await edit_or_log(query, L.t("duel.already"), None, clan.alias)
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(L.t("duel.btn_accept"),
                                                          callback_data=f"d:accept:{duel['id']}")]])
    await edit_or_log(query, L.t("duel.proposed", a=render.esc(duel["a"]["name"]),
                                 b=render.esc(duel["b"]["name"]),
                                 metric=L.t(f"duel.metric.{duel['metric']}"),
                                 duration=L.t(f"duel.duration.{duel['duration']}")), keyboard, clan.alias)
