from . import cwl_table
from .render import card, esc, fixed, quote, rank, season_label

MOVE = {"up": "⬆️", "down": "⬇️", "same": "➡️"}
ZONE = {"up": "⬆️", "down": "⬇️", "safe": "➡️"}
RESULT = {"win": "✅", "lose": "❌", "tie": "🤝"}
STATE_ICON = {"in": "✅", "out": "🚫", "unknown": "❔"}


def season_card(L, record):
    body = quote(
        L.t("cwl.season.rank", rank=record.get("rank") or "?", of=record.get("of") or "?",
            stars=record.get("stars") or 0)
        + "\n"
        + L.t("cwl.season.record", wins=record.get("wins") or 0, losses=record.get("losses") or 0,
              ties=record.get("ties") or 0)
    )
    days = record.get("days") or []
    if days:
        body += "\n\n" + L.t("cwl.season.days") + "\n" + quote("\n".join(
            L.t("cwl.season.day_row", icon=RESULT.get(d.get("result"), "•"), day=d.get("day"),
                opponent=esc(d.get("opponent")), stars=d.get("stars") or 0,
                opp_stars=d.get("opp_stars") or 0)
            for d in days))
    top = [m for m in (record.get("members") or []) if m.get("attacks")][:3]
    if top:
        body += "\n\n" + L.t("cwl.season.top") + "\n" + quote("\n".join(
            L.t("cwl.season.top_row", rank=rank(L, i), name=esc(m.get("name")),
                stars=m.get("stars") or 0, days=m.get("wars") or 0)
            for i, m in enumerate(top)))
    return card("🏅", L.t("cwl.season.title", league=esc(record.get("league") or "CWL")), body)


def history_card(L, records):
    if not records:
        return card("📜", L.t("cwl.history.title"), L.t("cwl.history.none"))
    lines = [
        L.t("cwl.history.row", move=MOVE.get(r.get("move"), "·"),
            season=season_label(L, r["season"]) if r.get("season") else "?",
            league=esc(r.get("league")), rank=r.get("rank") or "?", of=r.get("of") or "?",
            wins=r.get("wins") or 0, losses=r.get("losses") or 0)
        for r in records
    ]
    return card("📜", L.t("cwl.history.title"), quote("\n".join(lines)))


def roster_lines(L, rows):
    return "\n".join(
        L.t("cwl.roster.row", icon=STATE_ICON.get(r.get("state"), "❔"), name=esc(r.get("name")),
            th=r.get("th") or "?", days=r.get("days") or 0, stars=r.get("stars") or 0)
        for r in rows)


def roster_card(L, rows, proposed, bench, size=None):
    if not rows:
        return card("👥", L.t("cwl.roster.title"), L.t("cwl.roster.none"))
    body = L.t("cwl.roster.lineup") + "\n" + quote(roster_lines(L, proposed))
    if bench:
        body += "\n\n" + L.t("cwl.roster.bench") + "\n" + quote(roster_lines(L, bench))
    body += "\n\n" + L.t("cwl.roster.declare")
    return card("👥", L.t("cwl.roster.title"), body,
                L.t("cwl.roster.size", size=size) if size else None)


def lineup_card(L, proposed, bench, day):
    body = L.t("cwl.lineup.body") + "\n" + quote(roster_lines(L, proposed))
    if bench:
        body += "\n\n" + L.t("cwl.roster.bench") + "\n" + quote(roster_lines(L, bench))
    return card("📝", L.t("cwl.lineup.title", day=day), body)


def table_card(L, rows, day, total, zones=None):
    if not rows:
        return card("📊", L.t("cwl.none.title"), L.t("cwl.none.body"))
    lines = [
        L.t("cwl.table.row", rank=L.t("rank.n", n=r.get("rank")),
            zone=ZONE.get(cwl_table.zone(r.get("rank"), zones), "·"),
            mark="🏰 " if r.get("us") else "", name=esc(r.get("name")),
            stars=r.get("stars") or 0, wins=r.get("wins") or 0,
            destr=L.pct(r.get("destr") or 0, 0))
        for r in rows
    ]
    body = quote("\n".join(lines))
    ours = next((r for r in rows if r.get("us")), None)
    if ours and ours.get("left"):
        body += "\n\n" + L.t("cwl.table.projection", best=L.t("rank.n", n=ours.get("best")),
                             worst=L.t("rank.n", n=ours.get("worst")), left=ours.get("left"))
    if ours and not cwl_table.zone(ours.get("rank"), zones):
        body += "\n" + L.t("cwl.table.zones_learning")
    if ours and ours.get("days"):
        cells = sorted((int(k), v) for k, v in ours["days"].items())
        body += "\n\n" + L.t("cwl.table.days") + "\n" + quote(" · ".join(
            L.t("cwl.table.day_cell", day=d, stars=v.get("stars") or 0,
                icon="✅" if v.get("win") else "❌")
            for d, v in cells))
    return card("📊", L.t("cwl.table.title", day=day, total=total), body)


def bonus_card(L, rows):
    if not rows:
        return card("🎖", L.t("cwl.bonus.title"), L.t("cwl.bonus.none"))
    lines = [
        L.t("cwl.bonus.row", rank=L.t("rank.n", n=i + 1), mark="🎖 " if r.get("assigned") else "",
            name=esc(r.get("name")), value=r.get("value") or 0, stars=r.get("stars") or 0,
            attacks=r.get("attacks") or 0, triples=r.get("triples") or 0,
            missed=r.get("missed") or 0)
        for i, r in enumerate(rows)
    ]
    body = L.t("cwl.bonus.intro") + "\n" + quote("\n".join(lines)) + "\n\n" + L.t("cwl.bonus.how")
    return card("🎖", L.t("cwl.bonus.title"), body)


def scout_card(L, rows, season=None):
    if not rows:
        return card("🔭", L.t("cwl.scout.title"), L.t("cwl.scout.none"))
    lines = [
        L.t("cwl.scout.row", rank=L.t("rank.n", n=r.get("rank")), mark="🏰 " if r.get("us") else "",
            name=esc(r.get("name")), avg=fixed(L, r.get("avg_th") or 0, 1),
            level=r.get("level") or "?", members=r.get("members") or 0,
            streak="?" if r.get("streak") is None else r.get("streak"))
        for r in rows
    ]
    body = quote("\n".join(lines))
    ours = next((r for r in rows if r.get("us")), None)
    if ours:
        body += "\n\n" + L.t("cwl.scout.us", rank=L.t("rank.n", n=ours.get("rank")), total=len(rows))
        spread = ours.get("th") or []
        if spread:
            body += "\n" + L.t("cwl.scout.spread", spread=" · ".join(
                L.t("cwl.scout.th_cell", th=th, n=n) for th, n in spread))
    return card("🔭", L.t("cwl.scout.title"), body, esc(season) if season else None)
