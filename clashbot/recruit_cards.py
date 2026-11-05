from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .recruit import GOALS, is_verified
from .render import HERO_ICONS, card, quote
from .util import encode_tag, esc

GOAL_ICONS = {"war": "⚔️", "cwl": "🏆", "capital": "🏕", "calm": "🌿"}
PREF_KEYS = {"in": "me.pref_in", "out": "me.pref_out"}
FILTERS = ("all", "country", "th")


def goal_label(L, goal):
    return f"{GOAL_ICONS[goal]} {L.t(f'recruit.apply.goal.{goal}')}"


def clan_link(L, tag):
    return (f"https://link.clashofclans.com/{L.t('link.lang')}"
            f"?action=OpenClanProfile&tag={encode_tag(tag)}")


def intro_card(L, clan_name, need):
    req = L.t("recruit.apply.req", th=need) if need else L.t("recruit.apply.req_any")
    return card("📨", L.t("recruit.apply.title"),
                L.t("recruit.apply.intro", clan=esc(clan_name)) + "\n" + req)


def clans_keyboard(names):
    return InlineKeyboardMarkup([[InlineKeyboardButton(name, callback_data=f"rc:clan:{i}")]
                                 for i, name in enumerate(names)])


def accounts_keyboard(L, links):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{link.name} · {link.tag}",
                                                       callback_data=f"rc:acc:{i}")]
                                 for i, link in enumerate(links)])


def goals_card(L, clan_name, picked):
    chosen = " ".join(goal_label(L, goal) for goal in picked)
    body = L.t("recruit.apply.goals", clan=esc(clan_name))
    return card("📨", L.t("recruit.apply.title"), body + ("\n" + quote(chosen) if chosen else ""))


def goals_keyboard(L, picked):
    rows = [[InlineKeyboardButton(("✓ " if goal in picked else "") + goal_label(L, goal),
                                  callback_data=f"rc:g:{goal}")] for goal in GOALS]
    rows.append([InlineKeyboardButton(L.t("recruit.apply.btn_send"), callback_data="rc:send")])
    return InlineKeyboardMarkup(rows)


def below_card(L, level, need):
    return card("📨", L.t("recruit.apply.title"), L.t("recruit.apply.below", th=need, yours=level))


def below_keyboard(L):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("recruit.apply.btn_anyway"), callback_data="rc:anyway"),
        InlineKeyboardButton(L.t("recruit.apply.btn_stop"), callback_data="rc:stop"),
    ]])


def sent_card(L, clan_name):
    return card("📨", L.t("recruit.apply.title"), L.t("recruit.apply.sent", clan=esc(clan_name)))


def applicant_card(L, app, clan_name, need):
    snap = app.get("snap") or {}
    heroes = " ".join(f"{HERO_ICONS.get(name, '•')}{level}"
                      for name, level in (snap.get("heroes") or {}).items())
    lines = [L.t("recruit.card.numbers", th=snap.get("th") or "?", trophies=L.n(snap.get("trophies")),
                 best=L.n(snap.get("best")), stars=L.n(snap.get("warStars")))]
    if heroes:
        lines.append(L.t("recruit.card.heroes", heroes=heroes))
    lines.append(L.t("recruit.card.donations", given=L.n(snap.get("donations")),
                     got=L.n(snap.get("received")), capital=L.n(snap.get("capital"))))
    lines.append(L.t("recruit.card.pref",
                     pref=L.t(PREF_KEYS.get(snap.get("warPref"), "me.pref_unknown"))))
    lines.append(L.t("recruit.card.clan", tag=esc(snap.get("clan")))
                 if snap.get("clan") else L.t("recruit.card.no_clan"))
    if app.get("goals"):
        lines.append(L.t("recruit.card.goals",
                         goals=" ".join(goal_label(L, goal) for goal in app["goals"])))
    head = L.t("recruit.card.verified") if app.get("verified") else L.t("recruit.card.unverified")
    if app.get("below") and need:
        head += " · " + L.t("recruit.card.below", th=need)
    return card("🙋", L.t("recruit.card.title", name=esc(snap.get("name")), tag=esc(app.get("tag"))),
                head + "\n" + quote("\n".join(lines)), esc(clan_name))


def applications_card(L, rows):
    if not rows:
        return card("🙋", L.t("recruit.list.title"), L.t("recruit.list.empty"))
    lines = []
    for app in rows:
        snap = app.get("snap") or {}
        marks = "" if app.get("verified") else " ❔"
        marks += " ⚠️" if app.get("below") else ""
        lines.append(L.t("recruit.list.row", name=esc(snap.get("name")), th=snap.get("th") or "?",
                         trophies=L.n(snap.get("trophies")), marks=marks))
    return card("🙋", L.t("recruit.list.title"), quote("\n".join(lines)))


def applications_keyboard(L, rows):
    if not rows:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton((app.get("snap") or {}).get("name") or "?",
                                                       callback_data=f"ap:o:{app['id']}")]
                                 for app in rows])


def answer_card(L, clan_name, tag, accepted):
    if not accepted:
        return card("📨", L.t("recruit.apply.title"), L.t("recruit.answer.rejected",
                                                          clan=esc(clan_name)))
    body = L.t("recruit.answer.accepted", clan=esc(clan_name))
    if tag:
        body += "\n" + L.t("recruit.answer.link", link=clan_link(L, tag))
    return card("🎉", L.t("recruit.apply.title"), body)


def stale_card(L, rows):
    lines = [L.t("recruit.stale.row", name=esc((app.get("snap") or {}).get("name")),
                 th=(app.get("snap") or {}).get("th") or "?") for app in rows]
    return card("⏳", L.t("recruit.stale.title", n=len(rows)), quote("\n".join(lines)))


def decision_keyboard(L, app_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("recruit.btn_accept"), callback_data=f"ap:y:{app_id}"),
        InlineKeyboardButton(L.t("recruit.btn_reject"), callback_data=f"ap:n:{app_id}"),
    ]])


def board_view(L, tz, rows, listed, now=None):
    if not rows:
        body = L.t("recruit.net.empty") if listed else L.t("recruit.net.off")
        return card("🧭", L.t("recruit.net.title"), body + "\n\n" + L.t("recruit.net.note"))
    lines = []
    for row in rows:
        req = L.t("recruit.req_th", th=row["min_th"]) if row.get("min_th") else L.t("recruit.req_any")
        if row.get("name") and row.get("tag"):
            name = f"<a href=\"{clan_link(L, row['tag'])}\">{esc(row['name'])}</a>"
        else:
            name = L.t("recruit.net.anon", code=row.get("code"))
        if is_verified(row):
            name += " " + L.t("recruit.verified")
        lines.append(L.t("recruit.net.row", name=name, level=row.get("level") or "?",
                         n=row.get("free") or 0, req=req,
                         country=esc(row.get("country") or "—")))
    body = quote("\n".join(lines)) + "\n" + L.t("recruit.net.note")
    if not listed:
        body += "\n" + L.t("recruit.net.off")
    return card("🧭", L.t("recruit.net.title"), body)


def board_keyboard(L, manage, listed, picked):
    rows = [[InlineKeyboardButton(("✓ " if name == picked else "") + L.t(f"recruit.net.filter.{name}"),
                                  callback_data=f"rb:f:{name}") for name in FILTERS]]
    if manage:
        rows.append([InlineKeyboardButton(L.t("recruit.net.btn_leave" if listed else "recruit.net.btn_join"),
                                          callback_data="rb:off" if listed else "rb:on")])
    return InlineKeyboardMarkup(rows)


def open_keyboard(L):
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t("recruit.net.btn_open"),
                                                       callback_data="rb:open")]])
