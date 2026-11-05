import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import leaderboards as boards, privacy, progress as progress_mod, render, scoring
from .events import member_stats

log = logging.getLogger("clashbot.hub")

DEFAULT_TAB = "mvp"
TAB_ROWS = [["mvp", "points"], ["farm", "upgrade"], ["wins", "games"], ["donations", "trophies"],
            ["capital", "stars"], ["hall", "network"]]
COMMAND_TABS = {
    "boards": ("mvp", "month"),
    "points": ("points", "month"),
    "activity": ("farm", "week"),
    "top": ("trophies", "week"),
    "donations": ("donations", "month"),
    "capital": ("capital", "week"),
    "stars": ("stars", "month"),
    "hall": ("hall", None),
    "network": ("network", "week"),
}
DELTA_TABS = ("mvp", "points", "donations", "capital", "farm", "upgrade", "stars", "trophies",
              "wins", "games")
WAR_TABS = ("mvp", "points", "stars")


def parse(data):
    parts = (data or "").split(":")
    tab = parts[1] if len(parts) > 1 else ""
    period = parts[2] if len(parts) > 2 else ""
    if tab not in boards.TABS:
        tab = DEFAULT_TAB
        period = ""
    allowed = boards.TAB_PERIODS.get(tab) or ()
    if period not in allowed:
        period = allowed[0] if allowed else None
    return tab, period


def keyboard(L, tab, period, hidden=False, extra_rows=None, linked=True):
    rows = []
    periods = boards.TAB_PERIODS.get(tab) or ()
    picked = len(periods) > 1
    if picked:
        rows.append([
            InlineKeyboardButton(("✓ " if p == period else "") + L.t(f"boards.btn.{p}"),
                                 callback_data=f"b:{tab}:{p}")
            for p in periods
        ])
    rows.extend([list(line) for line in (extra_rows or ())])
    for line in TAB_ROWS:
        buttons = [
            InlineKeyboardButton(("✓ " if key == tab else "") + L.t(f"boards.tab.{key}"),
                                 callback_data=f"b:{key}:{boards.default_period(key) or ''}")
            for key in line if not (key == tab and picked)
        ]
        if buttons:
            rows.append(buttons)
    if linked:
        rows.append([InlineKeyboardButton(L.t("boards.btn_show" if hidden else "boards.btn_hide"),
                                          callback_data="b:me:hide")])
    rows.append([InlineKeyboardButton(L.t("menu.back"), callback_data="v:menu")])
    return InlineKeyboardMarkup(rows)


def period_deltas(stored, period, alias):
    try:
        return progress_mod.deltas(stored, period)
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        log.warning("%s: attività non calcolabile: %s", alias, e)
        return []


async def sources(store, coc, clan, tab, period, now, tz, goldpass_end=None):
    state = await store.get_state(clan.alias, boards.STATE_KIND) or {}
    data = {"state": state, "hidden": privacy.hidden_in(state)}
    if tab in DELTA_TABS:
        data["members"] = await store.get_state(clan.alias, "members") or {}
        data["season"] = await store.get_state(clan.alias, "season") or scoring.empty_season(
            scoring.season_id(now, tz))
        stored = await store.get_state(clan.alias, "progress") or {}
        data["deltas"] = period_deltas(stored, period or "month", clan.alias)
    if tab in WAR_TABS:
        start, _ = boards.window(now, tz, period or "month", goldpass_end)
        records = await store.wars_since(clan.alias, start)
        data["stats"] = member_stats(records)
        data["wars"] = len(records)
        data["streaks"] = scoring.streaks(await store.recent_wars(clan.alias, 20))
    if tab == "capital":
        raids, _ = await coc.capital_raids(clan.tag)
        items = (raids or {}).get("items") or []
        data["raid"] = items[0] if items else None
    if tab == "hall":
        data["hall"] = await store.get_state(clan.alias, "hall") or {}
    if tab == "network":
        data["network"] = await store.network_get(clan.alias)
        data["board"] = await store.network_board() if (data["network"] or {}).get("visible") else []
    return data


async def view(L, tz, tab, period, data, now):
    excluded = data.get("hidden")
    if tab == "mvp":
        rows = boards.mvp_rows(period, data["season"], data["stats"], data["deltas"], excluded)
        return render.mvp_view(L, period, rows)
    if tab == "points":
        season = data["season"]
        activity = [r for r in data["deltas"] if r["score"] > 0]
        return render.points_view(L, season, scoring.leaderboard(season), data["streaks"],
                                  activity=activity)
    if tab == "hall":
        return render.hall_view(L, data["hall"])
    if tab == "trophies":
        rows = boards.trophy_rows(data["state"], data["members"], period)
        rows = privacy.keep_visible(rows, excluded)[:boards.TOP]
        return render.board_view(L, tab, period, rows, climb=boards.climbers(rows))
    if tab == "donations":
        rows = boards.donation_rows(period, data["deltas"], data["season"], data["members"], excluded)
        return render.board_view(L, tab, period, rows)
    if tab == "stars":
        rows = boards.star_rows(data["stats"], excluded)
        return render.board_view(L, tab, period, rows)
    if tab == "capital":
        rows = boards.metric_rows("capital", data["deltas"], excluded)
        head = render.capital_view(L, tz, data.get("raid"), data.get("members"), now)
        return render.clip(head + "\n\n" + render.board_view(L, tab, period, rows))
    if tab == "network":
        row = data.get("network") or {}
        return render.network_view(L, data.get("board") or [], row, bool(row.get("visible")))
    rows = boards.metric_rows(tab, data["deltas"], excluded)
    return render.board_view(L, tab, period, rows)


def network_rows(L, joined, named):
    rows = [[InlineKeyboardButton(L.t("network.btn_leave" if joined else "network.btn_join"),
                                  callback_data="b:network:toggle")]]
    if joined:
        rows.append([InlineKeyboardButton(L.t("network.btn_anon" if named else "network.btn_named"),
                                          callback_data="b:network:name")])
    return rows


async def network_payload_now(store, clan, now, tz):
    start, _ = boards.window(now, tz, "week")
    stats = member_stats(await store.wars_since(clan.alias, start))
    stored = await store.get_state(clan.alias, "progress") or {}
    members = await store.get_state(clan.alias, "members") or {}
    return boards.network_payload(clan.name, clan.tag, boards.period_id(now, tz, "week"),
                                  progress_mod.deltas(stored, "week"), stats, members)
