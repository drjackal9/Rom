from datetime import datetime, timezone

from .render import (MAX_LEN, card, compose, fixed, quote, score_block, target_hint, todo_block,
                     versus, war_title, who)
from .util import esc, parse_coc_time


def cleanup_card(L, rows, kind="war", day=None):
    if not rows:
        return None
    lines = []
    for r in rows:
        lines.append(L.t(
            "cleanup.row_done" if r["finished"] else "cleanup.row",
            name=esc(r["name"]), pos=r["pos"], target=esc(r["defender"]),
            stars=L.stars(r["stars"]), was=r["was"],
            left_by=esc(r["left_by"]) if r["left_by"] else L.t("cleanup.someone"),
        ))
    return card("🧹", L.t("cleanup.title", n=len(rows)), quote("\n".join(lines)),
                war_title(L, kind, day) if kind == "cwl" else None)


def last_call_card(L, war, rows, kind="war", day=None, now=None, plan=None, names=None):
    end = parse_coc_time(war.get("endTime"))
    lines = "\n".join(L.t("reminder.row", who=who(L, m, names), n=m["left"],
                          hint=target_hint(L, plan, m["tag"], war)) for m in rows)
    body = versus(L, war) + "\n\n" + quote(lines) + "\n\n" + L.t("last_call.end", left=L.delta(end, now))
    return card("⏳", L.t("last_call.title"), body, war_title(L, kind, day))


def midway_card(L, tz, war, info, cleaned=0, kind="war", day=None, now=None):
    end = parse_coc_time(war.get("endTime"))
    body = quote(score_block(L, tz, war, now, with_time=False))
    body += "\n\n" + (L.t("midway.need", n=info["need"]) if info["need"] else L.t("midway.ahead"))
    body += "\n" + L.t("midway.reachable", n=info["reachable"])
    if cleaned:
        body += "\n" + L.t("midway.cleaned", n=cleaned)
    if info["missing"]:
        body += "\n\n" + todo_block(L, info["missing"])
    body += "\n\n" + L.t("midway.tail", left=L.delta(end, now))
    return card("⏱", L.t("midway.title"), body, war_title(L, kind, day))


def roster_card(L, rows, kind="war", day=None):
    parts = []
    for key in ("out_in_war", "in_not_in_war", "silent"):
        names = rows.get(key) or []
        if names:
            parts.append(L.t(f"roster.{key}", n=len(names)) + "\n"
                         + quote(", ".join(esc(name) for name in names)))
    if not parts:
        return None
    return card("🧾", L.t("roster.title"), "\n\n".join(parts), war_title(L, kind, day))


def _th_line(L, rows):
    return "  ".join(L.t("scout.th_item", th=th, n=n) for th, n in rows) or "—"


def _mirror_lines(L, rows):
    return [
        L.t("scout.mirror", pos=r["pos"], name=esc(r["name"]), th=r["th"], target=esc(r["target"]),
            target_th=r["target_th"],
            delta=L.t("scout.delta_up" if r["delta"] > 0 else "scout.delta_down", n=abs(r["delta"])))
        for r in rows
    ]


def _within(L, lines, budget, more="scout.more"):
    kept, used = [], 0
    for i, line in enumerate(lines):
        left = len(lines) - i - 1
        step = len(line) + (1 if kept else 0)
        tail = 1 + len(L.t(more, n=left)) if left else 0
        if used + step + tail > budget:
            break
        kept.append(line)
        used += step
    if len(kept) == len(lines):
        return kept
    return kept + [L.t(more, n=len(lines) - len(kept))]


def scout_card(L, report, kind="war", day=None):
    clan, log = report["clan"] or {}, report["log"] or {}
    body = quote(
        L.t("scout.ours", ths=_th_line(L, report["ours"]), avg=fixed(L, report["our_avg"], 1)) + "\n"
        + L.t("scout.theirs", ths=_th_line(L, report["theirs"]), avg=fixed(L, report["their_avg"], 1))
    )
    if report["their_heroes"]:
        body += "\n" + L.t("scout.heroes", ours=fixed(L, report["our_heroes"], 0),
                           theirs=fixed(L, report["their_heroes"], 0))
        if report["partial"]:
            body += " " + L.t("scout.partial")
    elif report["partial"]:
        body += "\n" + L.t("scout.partial")
    if clan.get("streak"):
        body += "\n" + L.t("scout.streak", n=clan["streak"])
    if log.get("played"):
        body += "\n" + L.t("scout.record", wins=log["wins"], losses=log["losses"], ties=log["ties"])
    elif log.get("error") == "private":
        body += "\n" + L.t("scout.log_private")
    if report["harder"]:
        body += "\n\n" + L.t("scout.harder", n=report["gap"])
    elif report["easier"]:
        body += "\n\n" + L.t("scout.easier", n=report["gap"])
    if report["mirrors"]:
        head = "\n\n" + L.t("scout.mirrors") + "\n"
        frame = len(compose("🔍", L.t("scout.title"), body + head + quote(""), war_title(L, kind, day)))
        lines = _within(L, _mirror_lines(L, report["mirrors"]), MAX_LEN - frame)
        body += head + quote("\n".join(lines))
    return card("🔍", L.t("scout.title"), body, war_title(L, kind, day))


def forecast_card(L, row, kind="war", day=None):
    lines = [L.t(f"forecast.term.{name}", value=f"{value:+d}") for name, value in row["terms"] if value]
    body = L.t("forecast.chance", n=row["probability"])
    body += "\n" + L.t("forecast.stars", us=row["stars_us"], them=row["stars_them"])
    body += "\n\n" + L.t("forecast.how") + "\n" + quote(
        "\n".join([L.t("forecast.base", n=row["base"])] + lines)
    )
    if row["partial"]:
        body += "\n" + L.t("forecast.partial")
    body += "\n\n" + L.t("forecast.honest")
    return card("🔮", L.t("forecast.title", opponent=esc(row["opponent"])), body, war_title(L, kind, day))


def forecast_result_card(L, row, acc, kind="war", day=None):
    body = quote(
        L.t("forecast.said", n=row["probability"], us=row["guess_us"], them=row["guess_them"]) + "\n"
        + L.t("forecast.real", us=row["stars_us"], them=row["stars_them"])
    )
    body += "\n\n" + L.t("forecast.hit" if row["hit"] else "forecast.miss")
    if acc["total"]:
        body += "\n" + L.t("forecast.accuracy", hits=acc["hits"], total=acc["total"], pct=acc["pct"])
    return card("🔮", L.t("forecast.result_title"), body, war_title(L, kind, day))


def warning_proposal_card(L, rows, seen, kind="war", day=None):
    lines = [
        L.t("warn.row", name=esc(row["name"]), n=row["missed"],
            seen=L.t("warn.seen", n=seen.get(row["tag"], 0)) if seen.get(row["tag"]) else "")
        for row in rows
    ]
    body = L.t("warn.intro", n=len(rows)) + "\n" + quote("\n".join(lines)) + "\n\n" + L.t("warn.tail")
    return card("📋", L.t("warn.title"), body, war_title(L, kind, day))


def warning_notice_card(L, row, by=None):
    body = L.t("warn.notice_body", name=esc(row["name"]), n=row["missed"])
    if by:
        body += "\n" + L.t("warn.notice_by", name=esc(by))
    return card("📌", L.t("warn.notice_title"), body + "\n\n" + L.t("warn.notice_tail"))


def warnings_view(L, ledger, tz):
    rows = [row for row in (ledger or []) if isinstance(row, dict)]
    if not rows:
        return card("📋", L.t("warn.list_title"), L.t("warn.list_empty"))
    lines = [
        L.t("warn.list_row", name=esc(row.get("name")), n=row.get("missed") or 0,
            when=L.when(datetime.fromtimestamp(row.get("at") or 0, timezone.utc), tz))
        for row in reversed(rows)
    ]
    frame = len(compose("📋", L.t("warn.list_title"), quote("")))
    return card("📋", L.t("warn.list_title"),
                quote("\n".join(_within(L, lines, MAX_LEN - frame, "warn.list_more"))))


def risk_card(L, tz, war, info, kind="war", day=None, now=None):
    end = parse_coc_time(war.get("endTime"))
    body = quote(score_block(L, tz, war, now, with_time=False))
    body += "\n\n" + L.t("risk.need", n=info["need"]) + "\n" + L.t("risk.reachable", n=info["reachable"])
    body += "\n\n" + todo_block(L, info["missing"])
    body += "\n\n" + L.t("risk.tail", left=L.delta(end, now))
    return card("🆘", L.t("risk.title"), body, war_title(L, kind, day))
