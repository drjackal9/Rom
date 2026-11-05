from .render import card, quote, rank
from .util import esc

BOARD_TOP = 15


def trophy_rows(members, base=None, players=None):
    rows = []
    for tag, m in (members or {}).items():
        value = int((m or {}).get("bb") or 0)
        if value <= 0:
            continue
        was = int((base or {}).get(tag) or 0)
        rows.append({
            "tag": tag,
            "name": (m or {}).get("name") or tag,
            "value": value,
            "delta": value - was if was else 0,
            "extra": int(((players or {}).get(tag) or {}).get("bh") or 0),
        })
    rows.sort(key=lambda r: (-r["value"], r["name"] or ""))
    return rows


def climber(rows):
    gains = [r for r in rows or () if r["delta"] > 0]
    if not gains:
        return None
    return max(gains, key=lambda r: (r["delta"], r["value"]))


def baseline(members):
    return {tag: int((m or {}).get("bb") or 0)
            for tag, m in (members or {}).items() if int((m or {}).get("bb") or 0) > 0}


def milestones(old, new):
    if not old or not new:
        return []
    before, after = int(old.get("bh") or 0), int(new.get("bh") or 0)
    if before and after > before:
        return [{"type": "builder_hall", "name": new.get("name"), "level": after}]
    return []


def board_card(L, rows, n=BOARD_TOP):
    if not rows:
        return card("🔨", L.t("builder.board.title"), L.t("builder.board.empty"))
    body = quote("\n".join(
        L.t("builder.board.row", rank=rank(L, i), name=esc(r["name"]), trophies=L.n(r["value"]),
            bh=L.t("builder.board.bh", level=r["extra"]) if r["extra"] else "",
            delta=L.t("builder.board.delta", n=r["delta"]) if r["delta"] > 0 else "")
        for i, r in enumerate(rows[:n])))
    top = climber(rows)
    if top:
        body += "\n\n" + L.t("builder.board.climber", name=esc(top["name"]), n=top["delta"])
    return card("🔨", L.t("builder.board.title"), body)


def milestone_card(L, events):
    if not events:
        return None
    return card("🔨", L.t("builder.goal.title"), quote("\n".join(
        L.t("builder.goal.row", name=esc(e["name"]), level=e["level"]) for e in events)))
