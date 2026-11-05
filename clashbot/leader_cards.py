from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .leaders import SCHEDULE_MAX, fill
from .render import MAX_LEN, card, clip, compose, quote
from .util import esc

HOURS_PER_ROW = 4
DAYS_PER_ROW = 4
MINUTES = ("00", "30")
WEEK = range(7)
CUT = "…"
TARGET = "target"
TARGET_NOTES = {"mirror": "h.target_mirror", "clear": "h.target_clear"}


def rules_card(L, text):
    body = quote(esc(text)) if text else L.t("leaders.rules.none")
    return card("📜", L.t("leaders.rules.title"), body)


def welcome_preview(L, text):
    body = quote(esc(text)) if text else L.t("leaders.welcome.none")
    return card("👋", L.t("leaders.welcome.title"), body + "\n" + L.t("leaders.welcome.tokens"))


def welcome_card(L, text, names, clan_name):
    return card("👋", L.t("leaders.welcome.title"), fill(text, names, clan_name))


def day_labels(L, days):
    if not days:
        return L.t("leaders.schedule.every_day")
    return " ".join(L.t(f"weekday.{day}") for day in days)


def schedule_card(L, entries):
    if not entries:
        return card("⏰", L.t("leaders.schedule.title"), L.t("leaders.schedule.none"))
    rows = "\n".join(
        L.t("leaders.schedule.row", hhmm=entry["hhmm"], days=day_labels(L, entry["days"]),
            text=esc(entry["text"]))
        for entry in entries
    )
    return card("⏰", L.t("leaders.schedule.title"), quote(rows))


def schedule_keyboard(L, entries):
    rows = [[InlineKeyboardButton(f"{L.t('leaders.schedule.btn_del')} {entry['hhmm']}",
                                  callback_data=f"lt:sch:del:{entry['id']}")]
            for entry in entries]
    if len(entries) < SCHEDULE_MAX:
        rows.append([InlineKeyboardButton(L.t("leaders.schedule.btn_add"), callback_data="lt:sch:add")])
    return InlineKeyboardMarkup(rows)


def hours_keyboard(L):
    buttons = [InlineKeyboardButton(f"{hour:02d}", callback_data=f"lt:sch:h:{hour:02d}")
               for hour in range(24)]
    return InlineKeyboardMarkup([buttons[i:i + HOURS_PER_ROW]
                                 for i in range(0, len(buttons), HOURS_PER_ROW)])


def minutes_keyboard(L, hour):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{hour}:{minute}", callback_data=f"lt:sch:m:{hour}:{minute}")
        for minute in MINUTES
    ]])


def days_keyboard(L, picked):
    buttons = [InlineKeyboardButton(("✓ " if day in picked else "") + L.t(f"weekday.{day}"),
                                    callback_data=f"lt:sch:d:{day}")
               for day in WEEK]
    rows = [[InlineKeyboardButton(L.t("leaders.schedule.every_day"), callback_data="lt:sch:d:all")]]
    rows += [buttons[:DAYS_PER_ROW], buttons[DAYS_PER_ROW:]]
    rows.append([InlineKeyboardButton(L.t("leaders.schedule.btn_done"), callback_data="lt:sch:ok")])
    return InlineKeyboardMarkup(rows)


def scheduled_message(L, text, clan_name):
    return clip(fill(text, None, clan_name))


def gate_card(L, on):
    return card("🚪", L.t("leaders.gate.title"),
                L.t("leaders.gate.on") if on else L.t("leaders.gate.off"))


def gate_keyboard(L, on):
    key = "leaders.gate.btn_off" if on else "leaders.gate.btn_on"
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t(key), callback_data="gt:switch")]])


def gate_request_card(L, name, username):
    who = esc(name) + (f" · @{esc(username)}" if username else "")
    return card("🚪", L.t("leaders.gate.title"), L.t("leaders.gate.request", who=who))


def gate_request_keyboard(L, user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("leaders.gate.btn_ok"), callback_data=f"gt:ok:{user_id}"),
        InlineKeyboardButton(L.t("leaders.gate.btn_no"), callback_data=f"gt:no:{user_id}"),
    ]])


def gate_done(L, name, approved, by):
    key = "leaders.gate.approved" if approved else "leaders.gate.declined"
    return card("🚪", L.t("leaders.gate.title"), L.t(key, who=esc(name), by=esc(by)))


def gate_auto(L, name, player):
    return card("🚪", L.t("leaders.gate.title"),
                L.t("leaders.gate.auto", who=esc(name), player=esc(player)))


def gate_needs_admin(L):
    return card("🚪", L.t("leaders.gate.title"), L.t("leaders.gate.needs_admin"))


def gate_gone(L):
    return card("🚪", L.t("leaders.gate.title"), L.t("leaders.gate.gone"))


def exit_card(L, rows):
    body = "\n".join(
        L.t("leaders.exit.row", who=f'<a href="tg://user?id={row["user_id"]}">{esc(row["name"])}</a>')
        for row in rows
    )
    return card("👋", L.t("leaders.exit.title"), body + "\n\n" + L.t("leaders.exit.tail"))


def promotion_card(L, rows):
    if not rows:
        return None
    body = "\n".join(
        L.t("leaders.promo.row", name=esc(row["name"]), rank=row["rank"]) + "\n"
        + L.t("leaders.promo.why", wars=row["wars"], attacks=row["attacks"], stars=row["stars"],
              missed=row["missed"], donations=L.n(row["donations"]), points=row["points"])
        for row in rows
    )
    return card("⬆️", L.t("leaders.promo.title"), quote(body) + "\n\n" + L.t("leaders.promo.tail"))


def trial_card(L, rows):
    if not rows:
        return None
    body = "\n".join(
        L.t("leaders.trial.row", name=esc(row["name"]), wars=row["wars"], attacks=row["attacks"],
            stars=row["stars"], missed=row["missed"], donations=L.n(row["donations"]),
            score=row["score"])
        for row in rows
    )
    return card("🧪", L.t("leaders.trial.title"), quote(body) + "\n\n" + L.t("leaders.trial.tail"))


def from_ts(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def note_card(L, tz, tag, name, note):
    if not note:
        return card("🗒", L.t("leaders.note.title"), L.t("leaders.note.none"), esc(name or tag))
    body = quote(esc(note["text"])) + "\n" + L.t(
        "leaders.note.by", who=esc(note.get("by_name")), when=L.when(from_ts(note.get("ts")), tz))
    return card("🗒", L.t("leaders.note.title"), body, esc(note.get("name") or name or tag))


def whole_lines(lines, budget):
    kept, used = [], 0
    for i, line in enumerate(lines):
        step = len(line) + (1 if kept else 0)
        tail = 1 + len(CUT) if i < len(lines) - 1 else 0
        if used + step + tail > budget:
            break
        kept.append(line)
        used += step
    return kept if len(kept) == len(lines) else kept + [CUT]


def notes_card(L, rows):
    hint = "\n<code>" + L.t("leaders.note.usage") + "</code>"
    if not rows:
        return card("🗒", L.t("leaders.note.title"), L.t("leaders.note.none") + hint)
    lines = [L.t("leaders.note.row", name=esc(note.get("name") or tag), text=esc(note["text"]))
             for tag, note in rows]
    frame = len(compose("🗒", L.t("leaders.note.title"), quote("") + hint))
    body = "\n".join(whole_lines(lines, MAX_LEN - frame))
    return card("🗒", L.t("leaders.note.title"), quote(body) + hint)


def export_card(L):
    return card("📦", L.t("leaders.export.title"), L.t("leaders.export.caption"))


def export_keyboard(L):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("leaders.export.btn_wars"), callback_data="ex:wars"),
        InlineKeyboardButton(L.t("leaders.export.btn_members"), callback_data="ex:members"),
    ]])


def month_card(L, clan_name, data):
    blocks = [L.t("leaders.month.wars", wars=data["wars"], wins=data["wins"], losses=data["losses"],
                  ties=data["ties"], stars=data["stars"])]
    if data["missed"]:
        blocks.append(L.t("leaders.month.missed") + "\n" + quote("\n".join(
            L.t("report.missed_row", name=esc(name), n=value) for name, value in data["missed"])))
    if data["arrivals"]:
        blocks.append(L.t("leaders.month.arrivals", who=esc(", ".join(data["arrivals"]))))
    if data["grown"]:
        blocks.append(L.t("leaders.month.grown") + "\n" + quote("\n".join(
            L.t("leaders.month.grown_row", name=esc(row.get("name")), score=row.get("score") or 0)
            for row in data["grown"])))
    blocks.append(L.t("leaders.month.tail"))
    return card("📈", L.t("leaders.month.title"), "\n\n".join(blocks), esc(clan_name))


def log_detail(L, row):
    if row.get("of"):
        return L.t(f"leaders.log.action.{row['of']}")
    if row.get("kind") == TARGET and row.get("ref"):
        ref = str(row["ref"])
        return L.t(TARGET_NOTES[ref]) if ref in TARGET_NOTES else "#" + esc(ref)
    return esc(row["detail"]) if row.get("detail") else ""


def log_card(L, tz, rows):
    if not rows:
        return card("📒", L.t("leaders.log.title"), L.t("leaders.log.none"))
    body = "\n".join(
        L.t("leaders.log.row", when=L.when(row.get("at"), tz),
            action=L.t(f"leaders.log.action.{row.get('action') or row.get('kind')}"),
            who=esc(row.get("by_name")), detail=log_detail(L, row))
        for row in rows
    )
    return card("📒", L.t("leaders.log.title"), quote(body))
