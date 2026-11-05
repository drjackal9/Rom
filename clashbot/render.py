from . import hero_caps, rankings, trend as trend_mod
from .diagnostics import CHECKS
from .events import ROLE_ICONS, ROLE_ORDER, missing_attackers, performances
from .events_registry import PACKS
from .i18n import SEPARATORS
from .leaderboards import MVP_PARTS as BOARD_MVP_PARTS, PODIUM, network_position
from .roster import FORMER_SHOWN
from .scoring import TITLES, play_board
from .source import lines as source_lines
from .util import API_LABELS, CLAN_SLOTS, bar, esc, parse_coc_time
from .warstats import VALUE_RECORDS as RECORD_VALUES

LINE = "━━━━━━━━━━━━━━━━━━━━"
MEDALS = ["🥇", "🥈", "🥉"]
MAX_LEN = 4000
REPORT_MISSED = 15
OPS_LEVELS = {"ok": "🟢", "unknown": "🟡", "bad": "🔴"}


def compose(icon, title, body="", subtitle=None):
    head = f"{icon} <b>{title}</b>"
    if subtitle:
        head += f" · {subtitle}"
    text = head + "\n" + LINE
    if body:
        text += "\n" + body
    return text


def card(icon, title, body="", subtitle=None):
    return clip(compose(icon, title, body, subtitle))


def quote(text):
    return f"<blockquote>{text}</blockquote>"


def clip(text):
    if len(text) <= MAX_LEN:
        return text
    return text[: MAX_LEN - 2] + "…"


def rank(L, i):
    return MEDALS[i] if i < 3 else L.t("rank.n", n=i + 1)


def fixed(L, value, digits=2):
    point = SEPARATORS.get(L.code, (",", "."))[1]
    try:
        return f"{float(value):.{digits}f}".replace(".", point)
    except (TypeError, ValueError):
        return "?"


def millions(L, value):
    return L.t("activity.millions", value=fixed(L, (value or 0) / 1_000_000, 1))


def title_icon(key):
    return TITLES.get(key, "🏅")


def season_label(L, sid):
    year, month = str(sid).split("-")
    return L.t("season.label", month=L.t(f"month.{int(month)}"), year=year)


def war_title(L, kind, day):
    if kind == "cwl":
        return L.t("war.title.cwl_day", day=day) if day else L.t("war.title.cwl")
    return L.t("war.title.war")


def versus(L, war):
    return L.t("versus", clan=esc(war["clan"]["name"]), opponent=esc(war["opponent"]["name"]))


def score_block(L, tz, war, now=None, with_time=True):
    c, o = war["clan"], war["opponent"]
    lines = [
        L.t("score.us", stars=c["stars"], destr=L.pct(c["destr"]), bar=bar(c["destr"])),
        L.t("score.them", stars=o["stars"], destr=L.pct(o["destr"]), bar=bar(o["destr"])),
    ]
    diff = c["stars"] - o["stars"]
    if diff > 0:
        lines.append(L.t("score.ahead", n=diff))
    elif diff < 0:
        lines.append(L.t("score.behind", n=-diff))
    elif c["destr"] != o["destr"]:
        lines.append(L.t("score.tie_ahead" if c["destr"] > o["destr"] else "score.tie_behind"))
    else:
        lines.append(L.t("score.draw"))
    if with_time and war.get("state") == "inWar":
        end = parse_coc_time(war.get("endTime"))
        lines.append(L.t("score.time_left", left=L.delta(end, now), when=L.when(end, tz)))
    return "\n".join(lines)


def attack_line(L, e):
    if e.get("defender"):
        target = L.t("attack.target", pos=e["defender_pos"], name=esc(e["defender"]))
    else:
        target = L.t("attack.target_unknown")
    if e.get("defender_th"):
        target = L.t("attack.target_th", target=target, th=e["defender_th"])
    return L.t("attack.line", name=esc(e["name"]), target=target,
               stars=L.stars(e["stars"]), destr=L.pct(e["destr"], 0), n=e["n"])


def defense_line(L, e):
    if e.get("defender"):
        target = L.t("attack.target", pos=e["defender_pos"], name=esc(e["defender"]))
    else:
        target = L.t("defense.target_unknown")
    return L.t("defense.line", name=esc(e["name"]), target=target,
               stars=L.stars(e["stars"]), destr=L.pct(e["destr"], 0))


def render_war_events(L, tz, events, war, kind="war", day=None, now=None):
    parts = []
    for e in events:
        if e["type"] == "war_prep":
            w = e["war"]
            start = parse_coc_time(w.get("startTime"))
            per = w.get("attacksPerMember", 2)
            body = (
                quote(versus(L, w))
                + "\n" + L.t("war.size", size=w.get("teamSize"), n=per)
                + "\n" + L.t("war_prep.start", when=L.when(start, tz), left=L.delta(start, now))
                + "\n\n" + L.t("war_prep.tip")
            )
            title = L.t("war_prep.title") if kind == "war" else L.t("war.title.prep", title=war_title(L, kind, day))
            parts.append(card("📣", title, body))
        elif e["type"] == "war_start":
            w = e["war"]
            end = parse_coc_time(w.get("endTime"))
            per = w.get("attacksPerMember", 2)
            body = (
                quote(versus(L, w))
                + "\n" + L.t("war.size", size=w.get("teamSize"), n=per)
                + "\n" + L.t("war_start.end", when=L.when(end, tz), left=L.delta(end, now))
                + "\n\n" + L.t("war_start.tip")
            )
            parts.append(card("⚔️", L.t("war_start.title", title=war_title(L, kind, day)), body))
    fights = sorted((e for e in events if e["type"] in ("attack", "defense")), key=lambda e: e.get("order") or 0)
    if fights:
        lines = [attack_line(L, e) if e["type"] == "attack" else defense_line(L, e) for e in fights]
        kinds = {e["type"] for e in fights}
        if kinds == {"attack"}:
            title = L.t("war_events.attacks")
        elif kinds == {"defense"}:
            title = L.t("war_events.defenses")
        else:
            title = L.t("war_events.both")
        body = "\n".join(lines) + "\n\n" + quote(score_block(L, tz, war, now))
        parts.append(card("💥", title, body, war_title(L, kind, day) if kind == "cwl" else None))
    return "\n\n".join(parts) if parts else None


def render_war_end(L, war, result, kind="war", day=None, defense=None):
    c, o = war["clan"], war["opponent"]
    if result == "win":
        icon, title, tail = "🏆", L.t("war_end.win.title"), L.t("war_end.win.tail")
    elif result == "lose":
        icon, title, tail = "😔", L.t("war_end.lose.title"), L.t("war_end.lose.tail")
    else:
        icon, title, tail = "🤝", L.t("war_end.tie.title"), L.t("war_end.tie.tail")
    perf = performances(war)
    top = [p for p in perf if p["attacks"]][:3]
    body = quote(
        L.t("war_end.us", name=esc(c["name"]), stars=c["stars"], destr=L.pct(c["destr"]))
        + "\n"
        + L.t("war_end.them", name=esc(o["name"]), stars=o["stars"], destr=L.pct(o["destr"]))
    )
    if top:
        body += "\n\n" + L.t("war_end.top") + "\n" + "\n".join(
            L.t("war_end.top_row", rank=MEDALS[i], name=esc(p["name"]), stars=p["stars"],
                destr=L.pct(p["destr"] / p["attacks"], 0))
            for i, p in enumerate(top)
        )
    triples = sum(p["triples"] for p in perf)
    if triples:
        body += "\n" + L.t("war_end.triples", n=triples)
    lazy = [L.t("war_end.missed_item", name=esc(p["name"]), n=p["missed"]) for p in perf if p["missed"] > 0]
    if lazy:
        body += "\n\n" + L.t("war_end.missed", names=", ".join(lazy))
    hit = [r for r in (defense or []) if r.get("hits")]
    if hit:
        worst = sorted(hit, key=lambda r: (-r["stars"], r["pos"] or 99))[:3]
        body += "\n\n" + L.t("war_end.defense") + "\n" + "\n".join(
            L.t("war_end.defense_row", name=esc(r["name"]), stars=r["stars"]) for r in worst)
        held = [r["name"] for r in hit if not r["stars"]]
        if held:
            body += "\n" + L.t("war_end.held", names=", ".join(esc(name) for name in held[:5]))
    body += "\n\n" + tail
    return card(icon, L.t("war_end.title", result=title, stars=c["stars"], opp_stars=o["stars"]), body,
                war_title(L, kind, day) if kind == "cwl" else None)


def who(L, m, names=None):
    html = (names or {}).get(m.get("tag"))
    return html or L.t("name.plain", name=esc(m["name"]))


def target_hint(L, plan, tag, war):
    if not plan:
        return ""
    positions = [pos for pos, a in plan.items() if a.get("tag") == tag]
    if not positions:
        return ""
    defenders = {str(d.get("pos")): d for d in war.get("defenders", {}).values()}
    bits = []
    for pos in sorted(positions, key=int):
        d = defenders.get(pos) or {}
        if d.get("name"):
            bits.append(L.t("target.hint_item", pos=pos, name=esc(d.get("name"))))
        else:
            bits.append(L.t("target.hint_pos", pos=pos))
    return L.t("target.hint", targets=", ".join(bits))


def render_reminder(L, tz, war, checkpoint, kind="war", day=None, now=None, names=None, plan=None):
    missing = missing_attackers(war)
    end = parse_coc_time(war.get("endTime"))
    if not missing:
        if checkpoint == 3600:
            return card("👏", L.t("war.all_done.title"), L.t("reminder.done.body", left=L.delta(end, now)),
                        war_title(L, kind, day))
        return None
    if checkpoint == 3600:
        icon, title, tail = "🚨", L.t("reminder.1h.title"), L.t("reminder.1h.tail")
    elif checkpoint == 14400:
        icon, title, tail = "⚠️", L.t("reminder.4h.title"), L.t("reminder.4h.tail")
    else:
        icon, title, tail = "⏰", L.t("reminder.8h.title"), L.t("reminder.8h.tail")
    total = sum(m["left"] for m in missing)
    lines = "\n".join(
        L.t("reminder.row", who=who(L, m, names), n=m["left"], hint=target_hint(L, plan, m["tag"], war))
        for m in missing
    )
    body = (
        L.t("war_start.end", when=L.when(end, tz), left=L.delta(end, now)) + "\n\n"
        + L.t("war.todo", n=total) + "\n" + quote(lines) + "\n\n" + tail
    )
    return card(icon, title, body, war_title(L, kind, day))


def dm_reminder(L, tz, war, m, kind="war", day=None, now=None, plan=None):
    end = parse_coc_time(war.get("endTime"))
    body = (
        versus(L, war) + "\n"
        + L.t("dm.left", n=m["left"], hint=target_hint(L, plan, m["tag"], war)) + "\n"
        + L.t("dm.end", left=L.delta(end, now), when=L.when(end, tz))
    )
    return card("⏰", L.t("dm.title"), body, war_title(L, kind, day))


def todo_block(L, missing):
    total = sum(m["left"] for m in missing)
    names = "   ".join(L.t("common.name_count", name=esc(m["name"]), n=m["left"]) for m in missing)
    return L.t("war.todo", n=total) + "\n" + quote(names)


def board_digest(war):
    c, o = war["clan"], war["opponent"]
    missing = tuple((m["name"], m["left"]) for m in missing_attackers(war))
    return repr((war.get("state"), c["stars"], c["destr"], o["stars"], o["destr"], missing))


def render_board(L, tz, war, kind="war", day=None, now=None):
    state = war.get("state")
    body = versus(L, war) + "\n" + score_block(L, tz, war, now)
    if state == "inWar":
        missing = missing_attackers(war)
        if missing:
            body += "\n\n" + todo_block(L, missing)
        else:
            body += "\n\n" + L.t("board.all_done")
    elif state == "warEnded":
        c, o = war["clan"], war["opponent"]
        ours, theirs = (c["stars"], c["destr"]), (o["stars"], o["destr"])
        verdict = L.t("board.win") if ours > theirs else L.t("board.lose") if ours < theirs else L.t("board.tie")
        body += "\n\n" + L.t("board.finished", verdict=verdict)
    body += "\n" + L.t("board.updated", time=L.clock(now, tz))
    return card("📌", L.t("board.title", title=war_title(L, kind, day)), body)


def board_card(L, pack, body):
    return compose("📋", L.t(f"board.title.{pack}"), body or L.t("board.empty"))


def board_body(text):
    parts = (text or "").split(LINE, 1)
    body = parts[1].strip("\n") if len(parts) == 2 else ""
    return body or parts[0].strip("\n")


def render_member_events(L, events):
    if not events:
        return None
    lines = []
    for e in events:
        if e["type"] == "join":
            bits = []
            if e.get("th"):
                bits.append(L.t("members.join.th", th=e["th"]))
            if e.get("trophies") is not None:
                bits.append(L.t("members.join.trophies", trophies=L.n(e["trophies"])))
            extra = L.t("members.join.extra", extra=" · ".join(bits)) if bits else ""
            lines.append(L.t("members.join", name=esc(e["name"]), extra=extra))
        elif e["type"] == "leave":
            lines.append(L.t("members.leave", name=esc(e["name"])))
        elif e["type"] == "rename":
            lines.append(L.t("members.rename", old=esc(e["old"]), name=esc(e["name"])))
        elif e["type"] in ("promote", "demote"):
            role = L.t(f"role.{e['role']}", n=1)
            lines.append(L.t(f"members.{e['type']}", name=esc(e["name"]), role=role))
    return card("👥", L.t("members.events.title"), "\n".join(lines))


def render_capital_events(L, tz, events):
    parts = []
    for e in events:
        if e["type"] == "capital_start":
            end = parse_coc_time(e.get("end"))
            parts.append(card("🏛", L.t("capital.start.title"), L.t("capital.start.body", when=L.when(end, tz))))
        elif e["type"] == "capital_reminder":
            end = parse_coc_time(e.get("end"))
            lines = "\n".join(
                L.t("capital.reminder.row", name=esc(m["name"]), n=m["left"]) for m in e["lazy"][:25]
            )
            extra = L.t("capital.reminder.more", n=len(e["lazy"]) - 25) if len(e["lazy"]) > 25 else ""
            parts.append(card("⛏️", L.t("capital.reminder.title"),
                              L.t("capital.reminder.left", left=L.delta(end)) + "\n\n"
                              + L.t("capital.reminder.todo") + "\n" + quote(lines + extra) + "\n\n"
                              + L.t("capital.reminder.tail")))
        elif e["type"] == "capital_end":
            podium = "\n".join(
                L.t("capital.podium_row", rank=MEDALS[i], name=esc(n), loot=L.n(v))
                for i, (n, v) in enumerate(e["podium"])
            )
            body = quote(L.t("capital.stats", loot=L.n(e["loot"]), attacks=L.n(e["attacks"]),
                             districts=L.n(e["districts"])))
            if podium:
                body += "\n\n" + L.t("capital.podium") + "\n" + podium
            parts.append(card("🏛", L.t("capital.end.title"), body))
    return "\n\n".join(parts) if parts else None


def war_view(L, tz, war, kind="war", day=None, now=None):
    if not war or war.get("state") == "notInWar":
        return card("😴", L.t("war_view.none.title"), L.t("war_view.none.body"))
    state = war.get("state")
    per = war.get("attacksPerMember", 2)
    if state == "preparation":
        start = parse_coc_time(war.get("startTime"))
        body = (quote(versus(L, war))
                + "\n" + L.t("war.size", size=war.get("teamSize"), n=per)
                + "\n" + L.t("war_prep.start", when=L.when(start, tz), left=L.delta(start, now)))
        return card("🛡", L.t("war.title.prep", title=war_title(L, kind, day)), body)
    used = sum(len(m.get("attacks", [])) for m in war.get("members", {}).values())
    total = (int(war.get("teamSize") or 0)) * per
    body = versus(L, war) + "\n" + quote(score_block(L, tz, war, now))
    if total:
        body += "\n" + L.t("war_view.used", used=used, total=total)
    title = war_title(L, kind, day)
    if state == "inWar":
        return card("⚔️", L.t("war_view.ongoing", title=title), body)
    return card("🏁", L.t("war_view.ended", title=title), body)


def attacks_view(L, tz, war, kind="war", day=None, now=None):
    if not war or war.get("state") not in ("inWar", "preparation"):
        return card("😴", L.t("attacks.none.title"), L.t("attacks.none.body"))
    if war.get("state") == "preparation":
        return card("🛡", L.t("attacks.prep.title"), L.t("attacks.prep.body"))
    missing = missing_attackers(war)
    end = parse_coc_time(war.get("endTime"))
    if not missing:
        return card("✅", L.t("war.all_done.title"), L.t("attacks.done.body", left=L.delta(end, now)),
                    war_title(L, kind, day))
    total = sum(m["left"] for m in missing)
    lines = "\n".join(
        L.t("attacks.row", pos=m["pos"], name=esc(m["name"]), n=m["left"]) for m in missing
    )
    body = quote(lines) + "\n" + L.t("score.time_left", left=L.delta(end, now), when=L.when(end, tz))
    return card("🗡", L.t("attacks.title", n=total), body, war_title(L, kind, day))


def members_view(L, members, info=None):
    groups = {}
    for m in members.values():
        groups.setdefault(m.get("role") or "member", []).append(m)
    sections = []
    for role in sorted(groups, key=lambda r: ROLE_ORDER.get(r, 9)):
        rows = sorted(groups[role], key=lambda m: -(m.get("trophies") or 0))
        lines = "\n".join(
            L.t("members.row", name=esc(m["name"]), th=m.get("th") or "?", trophies=L.n(m.get("trophies")))
            for m in rows
        )
        header = L.t("members.section", icon=ROLE_ICONS.get(role, "👤"),
                     label=L.t(f"role.{role}", n=len(rows)), n=len(rows))
        sections.append(header + "\n" + quote(lines))
    subtitle = L.t("common.level", n=info["level"]) if info and info.get("level") else None
    return card("👥", L.t("members.title", n=len(members)), "\n".join(sections), subtitle)


def capital_view(L, tz, raid, members=None, now=None):
    if not raid:
        return card("🏛", L.t("capital.view.title"), L.t("capital.view.none"))
    state = raid.get("state")
    end = parse_coc_time(raid.get("endTime"))
    body = quote(L.t("capital.stats", loot=L.n(raid.get("capitalTotalLoot")),
                     attacks=L.n(raid.get("totalAttacks")),
                     districts=L.n(raid.get("enemyDistrictsDestroyed"))))
    if state == "ongoing":
        body += "\n" + L.t("capital.view.closes", when=L.when(end, tz), left=L.delta(end, now))
        participants = {m.get("tag"): m for m in raid.get("members", [])}
        lazy = []
        for tag, member in (members or {}).items():
            rm = participants.get(tag)
            left = ((rm or {}).get("attackLimit") or 5) + ((rm or {}).get("bonusAttackLimit") or 0) - ((rm or {}).get("attacks") or 0)
            if left > 0:
                lazy.append(L.t("common.name_count", name=esc((rm or member).get("name")), n=left))
        if lazy:
            body += "\n\n" + L.t("capital.view.todo", n=len(lazy)) + "\n" + quote("   ".join(lazy[:40]))
        else:
            body += "\n\n" + L.t("capital.view.all_done")
        return card("🏛", L.t("capital.view.ongoing"), body)
    looters = sorted(raid.get("members", []), key=lambda m: -(m.get("capitalResourcesLooted") or 0))[:3]
    if looters:
        body += "\n\n" + L.t("capital.podium") + "\n" + "\n".join(
            L.t("capital.podium_row", rank=MEDALS[i], name=esc(m.get("name")),
                loot=L.n(m.get("capitalResourcesLooted")))
            for i, m in enumerate(looters)
        )
    body += "\n\n" + L.t("capital.view.last_closed", ago=L.ago(end, now))
    return card("🏛", L.t("capital.view.last"), body)


def cwl_view(L, tz, cwl, our_war, our_tag, now=None):
    if not cwl or not cwl.get("active"):
        return card("🏅", L.t("cwl.none.title"), L.t("cwl.none.body"))
    from .cwl import standings
    rounds = [r for r in cwl.get("rounds", []) if r]
    total_days = len(cwl.get("rounds", [])) or 7
    body = ""
    day = None
    if our_war and our_war.get("state") != "notInWar":
        day = our_war.get("day")
        state = our_war.get("state")
        if state == "preparation":
            start = parse_coc_time(our_war.get("startTime"))
            body += L.t("cwl.today", versus=versus(L, our_war)) + "\n" + L.t("cwl.prep", when=L.when(start, tz))
        else:
            body += L.t("cwl.today", versus=versus(L, our_war)) + "\n" + quote(score_block(L, tz, our_war, now))
            if state == "inWar":
                missing = missing_attackers(our_war)
                if missing:
                    body += "\n" + L.t("cwl.missing", n=len(missing)) + "\n" + quote(
                        ", ".join(esc(m["name"]) for m in missing))
                else:
                    body += "\n" + L.t("cwl.all_attacked")
    table = standings(cwl.get("clans", {}), cwl.get("wars", {}))
    if table:
        lines = []
        for i, (tag, row) in enumerate(table):
            mark = "🏰 " if tag == our_tag else ""
            name = L.t("name.plain", name=esc(row["name"])) if tag == our_tag else esc(row["name"])
            lines.append(L.t("cwl.row", rank=L.t("rank.n", n=i + 1), mark=mark, name=name, stars=row["stars"],
                             wins=row["wins"], destr=L.pct(row["destr"], 0)))
        body += ("\n\n" if body else "") + L.t("cwl.standings") + "\n" + quote("\n".join(lines))
    title = L.t("cwl.title", day=day or len(rounds), total=total_days)
    return card("🏅", title, body or L.t("cwl.waiting"), esc(cwl.get("league")) if cwl.get("league") else None)


def history_view(L, tz, items, now=None):
    rows = []
    for w in items or []:
        opp = w.get("opponent") or {}
        if not opp.get("name"):
            continue
        result = w.get("result")
        icon = "✅" if result == "win" else "❌" if result == "lose" else "🤝"
        c = w.get("clan") or {}
        rows.append(L.t(
            "history.row", icon=icon, opponent=esc(opp.get("name")), stars=c.get("stars", 0),
            destr=L.pct(c.get("destructionPercentage", 0), 0), opp_stars=opp.get("stars", 0),
            opp_destr=L.pct(opp.get("destructionPercentage", 0), 0),
            ago=L.ago(parse_coc_time(w.get("endTime")), now),
        ))
    if not rows:
        return card("📜", L.t("history.title"), L.t("history.none"))
    wins = sum(1 for w in items if w.get("result") == "win" and (w.get("opponent") or {}).get("name"))
    return card("📜", L.t("history.title_wins", wins=wins, total=len(rows)), quote("\n".join(rows)))


def no_history(L):
    return L.t("history.empty")


def stars_view(L, stats, n_wars):
    rows = sorted(
        (s for s in stats.values() if s["attacks"] >= 2),
        key=lambda s: (-(s["stars"] / s["attacks"]), -s["triples"], s["name"] or ""),
    )[:20]
    if not rows:
        return card("⭐", L.t("stars.title"), no_history(L))
    lines = "\n".join(
        L.t("stars.row", rank=rank(L, i), name=esc(s["name"]), avg=fixed(L, s["stars"] / s["attacks"]),
            attacks=s["attacks"], triples=s["triples"])
        for i, s in enumerate(rows)
    )
    return card("⭐", L.t("stars.title"), quote(lines), L.t("common.last_wars", n=n_wars))


def lazy_view(L, stats, n_wars):
    rows = sorted((s for s in stats.values() if s["missed"] > 0), key=lambda s: (-s["missed"], s["name"] or ""))[:20]
    if not stats:
        return card("😴", L.t("lazy.title"), no_history(L))
    if not rows:
        return card("👏", L.t("lazy.title_zero"), L.t("lazy.none"), L.t("common.last_wars", n=n_wars))
    lines = "\n".join(
        L.t("lazy.row", name=esc(s["name"]), missed=s["missed"], expected=s["expected"]) for s in rows
    )
    return card("😴", L.t("lazy.title"), quote(lines), L.t("common.last_wars", n=n_wars))


DELTA_KEYS = {-2: "up2", -1: "up1", 0: "same", 1: "down1", 2: "down2"}


def foes_view(L, rows, now=None, n=20):
    if not rows:
        return card("🤝", L.t("foes.title"), L.t("foes.empty"))
    lines = []
    for r in rows[:n]:
        icon = "✅" if r["wins"] > r["losses"] else "❌" if r["wins"] < r["losses"] else "🤝"
        lines.append(L.t("foes.row", icon=icon, name=esc(r["name"]), wins=r["wins"], losses=r["losses"],
                         ties=r["ties"], stars=r["stars"], opp_stars=r["opp_stars"],
                         ago=L.ago(r["last"], now)))
    return card("🤝", L.t("foes.title"), quote("\n".join(lines)) + "\n" + L.t("foes.legend"),
                L.t("common.last_wars", n=sum(r["wars"] for r in rows)))


def defense_view(L, rows, best, n_wars, n=20):
    picked = [r for r in rows or [] if r.get("attacked")]
    if not picked:
        return card("🛡", L.t("defense.title"), L.t("defense.empty"))
    lines = [
        L.t("defense.row", rank=rank(L, i), name=esc(r["name"]), avg=fixed(L, r["avg"]),
            wars=r["attacked"], stars=r["stars"])
        for i, r in enumerate(picked[:n])
    ]
    body = ""
    if best:
        body += L.t("defense.wall", name=esc(best["name"]),
                    avg=fixed(L, best["stars"] / best["attacked"])) + "\n"
    body += quote("\n".join(lines)) + "\n" + L.t("defense.legend")
    return card("🛡", L.t("defense.title"), body, L.t("common.last_wars", n=n_wars))


def triples_view(L, rows, n_wars):
    if not rows:
        return card("✨", L.t("triples.title"), L.t("triples.empty"))
    seen = {r["delta"]: r for r in rows}
    lines = []
    for delta in sorted(DELTA_KEYS):
        r = seen.get(delta) or {"attacks": 0, "rate": 0.0, "avg": 0.0}
        lines.append(L.t("triples.row", delta=L.t(f"triples.delta.{DELTA_KEYS[delta]}"),
                         rate=L.pct(r["rate"] * 100, 0), attacks=r["attacks"], avg=fixed(L, r["avg"])))
    return card("✨", L.t("triples.title"), quote("\n".join(lines)) + "\n" + L.t("triples.legend"),
                L.t("common.last_wars", n=n_wars))


def record_lines(L, records):
    r = records if isinstance(records, dict) else {}
    lines = []
    streak = r.get("streak") or {}
    if streak.get("best"):
        lines.append(("streak", L.t("records.streak", best=streak["best"], current=streak.get("current") or 0)))
    if r.get("destr"):
        lines.append(("destr", L.t("records.destr", destr=L.pct(r["destr"]["destr"]),
                                   opponent=esc(r["destr"]["opponent"]))))
    if r.get("stars"):
        lines.append(("stars", L.t("records.stars", stars=r["stars"]["stars"], total=r["stars"]["total"],
                                   opponent=esc(r["stars"]["opponent"]))))
    perfect = r.get("perfect") or {}
    if perfect.get("n"):
        last = perfect.get("last") or {}
        lines.append(("perfect", L.t("records.perfect", n=perfect["n"], opponent=esc(last.get("opponent")))))
    for key in RECORD_VALUES:
        row = r.get(key)
        if row:
            lines.append((key, L.t(f"records.{key}", name=esc(row.get("name")),
                                   value=L.n(row.get("value")))))
    return lines


def records_block(L, records):
    lines = record_lines(L, records)
    if not lines:
        return ""
    return L.t("records.title") + "\n" + quote("\n".join(line for _, line in lines))


def foe_card(L, row, kind="war", day=None, now=None):
    lines = [L.t("foe.body", wins=row["wins"], losses=row["losses"], ties=row["ties"], wars=row["wars"])]
    if row.get("last") and row.get("last_result"):
        lines.append(L.t("foe.last", ago=L.ago(row["last"], now),
                         result=L.t(f"foe.result.{row['last_result']}"),
                         stars=row["last_stars"], opp_stars=row["last_opp_stars"]))
    return card("🔎", L.t("foe.title", name=esc(row["name"])), quote("\n".join(lines)),
                war_title(L, kind, day) if kind == "cwl" else None)


def record_card(L, names, records):
    wanted = set(names or ())
    lines = [line for key, line in record_lines(L, records) if key in wanted]
    if not lines:
        return None
    return card("🏅", L.t("record.title"), quote("\n".join(lines)) + "\n\n" + L.t("record.tail"))


def menu_view(L, clan, info=None):
    lines = [L.t("clan.line", name=esc(clan.name), tag=esc(clan.tag))]
    if info:
        bits = []
        if info.get("level"):
            bits.append(L.t("common.level", n=info["level"]))
        if info.get("members") is not None:
            bits.append(L.t("menu_view.members", n=info["members"]))
        if info.get("league"):
            bits.append(esc(info["league"]))
        if info.get("streak"):
            bits.append(L.t("menu_view.streak", n=info["streak"]))
        if bits:
            lines.append(" · ".join(bits))
        line = labels_line(L, info.get("labels"))
        if line:
            lines.append(line)
    lines.append("\n" + L.t("menu_view.hint"))
    return card("📋", L.t("menu_view.title"), "\n".join(lines))


def linked_view(L, clan, clan_json):
    body = (
        L.t("clan.line", name=esc(clan.name), tag=esc(clan.tag)) + "\n"
        + L.t("linked.info", level=clan_json.get("clanLevel", "?"), members=clan_json.get("members", "?")) + "\n\n"
        + L.t("linked.body")
    )
    return card("✅", L.t("linked.title"), body)


def not_linked_view(L):
    return card("🔗", L.t("not_linked.title"), L.t("not_linked.body"))


def help_area_title(L, area):
    return L.t(f"setup.pack.{area}" if area in PACKS else f"help.area.{area}")


def help_block(L, area, rows):
    lines = "\n".join(L.t("help.cmd", name=name, text=L.t(f"cmd.{name}"))
                      for name, _aliases in rows)
    return f"<b>{help_area_title(L, area)}</b>\n" + lines


def help_intro(L, user_id=None):
    body = L.t("help.body")
    return body + "\n\n" + L.t("help.your_id", id=user_id) if user_id else body


def help_card(L, areas, intro):
    return card("🤖", L.t("help.title"), "\n\n".join(
        [intro] + [help_block(L, area, rows) for area, rows in areas]))


def help_view(L, areas, user_id=None, area=None, limit=MAX_LEN):
    intro = help_intro(L, user_id)
    filled = [(name, rows) for name, rows in areas.items() if rows]
    whole = help_card(L, filled, intro)
    if area is None and len(whole) <= limit:
        return whole, []
    names = [name for name, _rows in filled]
    picked = area if area in names else names[0]
    return help_card(L, [row for row in filled if row[0] == picked], intro), names


def support_card(L, url=None, code=None, twitch=None, source=None, channel=None):
    ways = []
    if url:
        ways.append(L.t("support.donate", url=esc(url)))
    if code:
        ways.append(L.t("support.creator", code=esc(code)))
    if twitch:
        ways.append(L.t("support.twitch", url=esc(twitch)))
    body = L.t("support.intro") + "\n\n" + "\n".join(ways) if ways else L.t("support.none")
    if channel:
        body += "\n\n" + L.t("support.community", url=esc(channel))
    legal = quote(L.t("console.attribution")) + "\n" + quote(source_lines(L, source))
    return card("💛", L.t("support.title"), body + "\n\n" + legal)


def share_card(L, personal=None):
    body = L.t("share.body")
    if personal:
        body += "\n\n" + L.t("amb.invite", link=esc(personal))
    return card("🤝", L.t("share.title"), body)


def status_view(L, tz, clan, api_ok, api_error, ip=None, now=None):
    api = L.t("status.api_ok") if api_ok else L.t("status.api_error", error=api_error)
    if api_error == "invalid_ip" and ip:
        api += "\n" + L.t("status.ip", ip=esc(ip))
    state = L.t("status.active") if clan.active else L.t("status.inactive")
    seen = L.ago(clan.last_seen, now) if clan.last_seen else L.t("status.never")
    return card("🔧", L.t("status.title"), (
        L.t("status.alias", alias=esc(clan.alias)) + "\n"
        + L.t("clan.line", name=esc(clan.name), tag=esc(clan.tag)) + "\n"
        + L.t("status.state", state=state, failures=clan.failures) + "\n"
        + L.t("status.last_seen", ago=seen) + "\n"
        + api
    ))


def api_error(L, error, tag=None):
    if error == "not_found":
        return L.t("api.not_found", tag=esc(tag)) if tag else L.t("api.not_found_plain")
    if error in ("network", "maintenance", "rate", "private", "invalid_ip", "invalid_key"):
        return L.t(f"api.{error}")
    return L.t("api.unknown")


CHECK_FIX = {"admin": "check.fix.admin", "pin": "check.fix.pin", "war_log": "war_log.body"}

CHECK_ICONS = {True: "✅", False: "❌"}


def check_line(L, name, ok):
    line = CHECK_ICONS.get(ok, "❔") + " " + L.t(f"check.label.{name}")
    if ok is False:
        line += "\n" + quote(L.t(CHECK_FIX[name]))
    return line


def check_view(L, results):
    found = results or {}
    body = "\n\n".join(check_line(L, name, found[name]) for name in CHECKS if name in found)
    if "admin" not in found:
        body += ("\n\n" if body else "") + L.t("check.unknown")
    elif not any(found[name] is False for name in CHECKS if name in found):
        body += "\n\n" + L.t("check.ok")
    return card("🩺", L.t("check.title"), body)


def diagnostic_card(L, names):
    return card("⚠️", L.t("diagnostic.title"), "\n\n".join(check_line(L, name, False) for name in names))


def link_nudge(L, linked, total, bot_username=None):
    body = L.t("nudge.body", linked=linked, total=total, pct=L.pct(100 * linked / total if total else 0))
    if bot_username:
        body += "\n\n" + L.t("h.link_private", bot=esc(bot_username))
    return card("🔗", L.t("nudge.title"), body)


def handover_card(L, body):
    return card("🔑", L.t("handover.title"), body + "\n\n" + quote(L.t("handover.telegram")))


def handover_old(L, name, days):
    return handover_card(L, L.t("handover.old", name=esc(name), days=days))


def handover_new(L, clan_name, days):
    return handover_card(L, L.t("handover.new", clan=esc(clan_name), days=days))


REASONS = ("token_invalid", "disabled", "owner_stopped", "too_many_failures", "flood", "abandoned",
           "reported")


def reason_label(L, reason):
    if not reason:
        return ""
    if reason in REASONS:
        return L.t(f"console.reason.{reason}")
    return esc(reason)


def platform_summary(L, report):
    body = [L.t("platform.bots", running=report.get("running") or 0, total=report.get("bots") or 0),
            L.t("platform.clans", n=report.get("clans") or 0, total=report.get("clans_total") or 0)]
    errors = report.get("errors") or []
    if errors:
        body.append(L.t("platform.errors") + "\n" + quote("\n".join(
            L.t("platform.error_line", name=esc(row.get("name")), reason=reason_label(L, row.get("reason")))
            for row in errors)))
    actions = report.get("actions") or []
    if actions:
        body.append(L.t("platform.actions") + "\n" + quote("\n".join(
            L.t(f"platform.action.{row['kind']}", name=esc(row.get("name")), n=row.get("n") or 0)
            for row in actions)))
    else:
        body.append(L.t("platform.nothing"))
    return card("📋", L.t("platform.title"), "\n\n".join(body))


def panel_container(L, row):
    key = "panel.container_peak" if row.get("peak_mem_mb") is not None else "panel.container"
    return L.t(key, name=esc(row.get("name")), mem=L.n(row.get("mem_mb")), cpu=fixed(L, row.get("cpu")),
               peak_mem=L.n(row.get("peak_mem_mb")), peak_cpu=fixed(L, row.get("peak_cpu")))


def panel_survey(L, data):
    counts = (data or {}).get("totals") or {}
    return L.t("panel.survey", great=L.n(counts.get("great") or 0), good=L.n(counts.get("good") or 0),
               meh=L.n(counts.get("meh") or 0), no=L.n(counts.get("no") or 0),
               n=(data or {}).get("clans") or 0)


def panel_card(L, data, resources=True):
    bots = data.get("bots") or {}
    clans = data.get("clans") or {}
    keys = data.get("keys") or {}
    sends = data.get("sends") or {}
    body = [L.t("platform.bots", running=bots.get("running") or 0, total=bots.get("total") or 0)]
    stopped = bots.get("stopped") or []
    if stopped:
        body.append(quote("\n".join(
            L.t("platform.error_line", name=esc(row.get("name")), reason=reason_label(L, row.get("reason")))
            for row in stopped)))
    body.append(L.t("platform.clans", n=clans.get("active") or 0, total=clans.get("total") or 0))
    body.append(L.t("panel.keys", alive=keys.get("alive") or 0, dead=keys.get("dead") or 0))
    body.append(L.t("panel.api", calls=L.n(data.get("api_per_minute") or 0)))
    body.append(L.t("panel.sends", sent=L.n(sends.get("sent") or 0), delayed=L.n(sends.get("delayed") or 0),
                    dropped=L.n(sends.get("dropped") or 0)))
    body.append(panel_survey(L, data.get("survey")))
    if resources:
        containers = data.get("containers") or []
        if containers:
            body.extend(panel_container(L, row) for row in containers)
        else:
            body.append(L.t("panel.no_samples"))
        hours = data.get("backup_age_h")
        body.append(L.t("panel.backup", n=hours) if hours is not None
                    else L.t("panel.backup_unknown"))
        retention = data.get("retention")
        if retention in ("ok", "fail"):
            body.append(L.t(f"panel.retention.{retention}"))
        alerts = data.get("alerts") or []
        if alerts:
            body.append(L.t("panel.alerts") + "\n"
                        + quote("\n".join(esc(text) for text in reversed(alerts))))
        else:
            body.append(L.t("panel.quiet"))
    return card("🛠", L.t("panel.title"), "\n".join(body))


def ops_value(L, value):
    if value is None:
        return "?"
    return fixed(L, value) if isinstance(value, float) else L.n(value)


def ops_line(L, row):
    args = {name: ops_value(L, value) for name, value in (row.get("args") or {}).items()}
    return OPS_LEVELS.get(row.get("level"), "") + " " + L.t(f"ops.{row['key']}", **args)


def ops_alert(L, row):
    return L.t("ops.alert_line", when=L.ago(row.get("when")), keys=esc(row.get("keys") or ""))


def ops_card(L, board):
    body = [ops_line(L, row) for row in board.get("rows") or ()]
    alerts = board.get("alerts") or []
    if alerts:
        body.append(L.t("ops.alerts") + "\n" + quote("\n".join(ops_alert(L, row) for row in alerts)))
    else:
        body.append(L.t("ops.quiet"))
    return card("🩺", L.t("ops.title"), "\n".join(body))


def platform_stop(L, name, reason):
    return card("🚦", L.t("platform.stop.title"),
                L.t("platform.stop.body", name=esc(name), reason=reason_label(L, reason)))


def platform_idle(L, days, grace):
    return card("💤", L.t("platform.idle.title"), L.t("platform.idle.owner", days=days, grace=grace))


def platform_idle_note(L, name, days):
    return card("💤", L.t("platform.idle.title"), L.t("platform.idle.manager", name=esc(name), days=days))


def platform_stopped(L, days):
    return card("⏹", L.t("platform.stopped.title"), L.t("platform.stopped.owner", days=days))


HERO_ICONS = {"Barbarian King": "👑", "Archer Queen": "🏹", "Grand Warden": "🧙", "Royal Champion": "🛡", "Minion Prince": "👾"}


def hero_levels(heroes):
    return " ".join(f"{HERO_ICONS.get(h, '•')}{lvl}" for h, lvl in (heroes or {}).items())


def hero_slots(L, rows):
    return " ".join(
        L.t("hero.slot", icon=HERO_ICONS.get(r["hero"], "•"), level=r["level"], max=r["max"])
        for r in rows
    )


VS_MARKS = {"left": "◀", "right": "▶", None: "="}


def labels_line(L, names):
    picked = [esc(n) for n in (names or []) if n]
    return L.t("labels.line", labels=" · ".join(picked[:API_LABELS])) if picked else ""


def achievements_card(L, events):
    if not events:
        return None
    lines = []
    for e in events:
        if e["type"] == "th":
            lines.append(L.t("ach.th", name=esc(e["name"]), level=e["level"]))
        elif e["type"] == "hero":
            lines.append(L.t("ach.hero", name=esc(e["name"]), hero=esc(e["hero"]), level=e["level"]))
        elif e["type"] == "league":
            lines.append(L.t("ach.league", name=esc(e["name"]), league=esc(e["league"])))
        elif e["type"] == "warstars":
            lines.append(L.t("ach.warstars", name=esc(e["name"]), n=L.n(e["value"]), count=e["value"]))
        elif e["type"] == "record":
            lines.append(L.t("ach.record", name=esc(e["name"]), n=L.n(e["value"]), count=e["value"]))
        elif e["type"] == "stars":
            lines.append(L.t("ach.stars", name=esc(e["name"]), goal=esc(e["goal"]), n=e["gained"]))
    return card("🏅", L.t("ach.title"), "\n".join(lines) + "\n\n" + L.t("ach.tail"))


def agenda_view(L, tz, items, now=None):
    lines = []
    for it in items:
        title = L.t(f"agenda.item.{it['key']}")
        if it["state"] == "ongoing":
            lines.append(L.t("agenda.ongoing", icon=it["icon"], title=title,
                             left=L.delta(it["end"], now), when=L.when(it["end"], tz)))
        else:
            lines.append(L.t("agenda.next", icon=it["icon"], title=title,
                             left=L.delta(it["start"], now), when=L.when(it["start"], tz)))
    return card("📅", L.t("agenda.title"), "\n".join(lines) + "\n\n" + L.t("agenda.note"))


def agenda_announcement(L, tz, item, phase, now=None):
    key, start, end = item["key"], item["start"], item["end"]
    if key == "cwl":
        if phase == "tomorrow":
            return card("📣", L.t("agenda.cwl.tomorrow.title"),
                        L.t("agenda.cwl.tomorrow.body", when=L.when(start, tz)))
        return card("🏅", L.t("agenda.cwl.open.title"),
                    L.t("agenda.cwl.open.body", when=L.when(end, tz), left=L.delta(end, now)))
    if key == "games":
        if phase == "tomorrow":
            return card("🎮", L.t("agenda.games.tomorrow.title"),
                        L.t("agenda.games.tomorrow.body", when=L.when(start, tz)))
        if phase == "start":
            return card("🎮", L.t("agenda.games.start.title"),
                        L.t("agenda.games.start.body", when=L.when(end, tz)))
        return card("⏳", L.t("agenda.games.last.title"),
                    L.t("agenda.games.last.body", when=L.when(end, tz), left=L.delta(end, now)))
    if key == "season":
        return card("🏁", L.t("agenda.season.title"), L.t("agenda.season.body", when=L.when(start, tz)))
    return None


def activity_family_section(L, activity):
    lines = [
        L.t("activity.family_row", rank=rank(L, i), name=esc(r.get("name")), avg=fixed(L, r.get("avg") or 0, 0))
        for i, r in enumerate(list(activity)[:10])
    ]
    return L.t("activity.family.section") + "\n" + quote("\n".join(lines))


BOARD_ICONS = {"mvp": "🏆", "points": "🔮", "farm": "🏹", "upgrade": "🏗", "wins": "⚔️",
               "games": "🎮", "donations": "🎁", "trophies": "🏆", "capital": "🏛", "stars": "⭐",
               "hall": "🥇", "network": "🌍"}


def board_row(L, tab, i, r):
    if tab == "wins":
        return L.t("activity.attacks_row", name=esc(r["name"]), n=r["value"])
    if tab == "games":
        return L.t("activity.games_row", name=esc(r["name"]), n=L.n(r["value"]), count=r["value"])
    if tab == "farm":
        dark = L.t("activity.farm_dark", dark=millions(L, r["extra"])) if r["extra"] > 0 else ""
        return L.t("activity.farm_row", rank=rank(L, i), name=esc(r["name"]),
                   loot=millions(L, r["value"]), dark=dark)
    if tab == "upgrade":
        th = L.t("activity.th_up", n=r["extra"]) if r["extra"] > 0 else ""
        return L.t("activity.upgrade_row", rank=rank(L, i), name=esc(r["name"]),
                   levels=L.t("activity.levels", n=r["value"]), th=th)
    if tab == "trophies":
        delta = L.t("boards.row.trophies_delta", n=L.n(r["delta"])) if r["delta"] > 0 else ""
        return L.t("boards.row.trophies", rank=rank(L, i), name=esc(r["name"]),
                   value=L.n(r["value"]), extra=r["extra"] or "?", delta=delta)
    if tab == "donations":
        return L.t("boards.row.donations", rank=rank(L, i), name=esc(r["name"]),
                   value=L.n(r["value"]), extra=L.n(r["extra"]))
    if tab == "capital":
        return L.t("boards.row.capital", rank=rank(L, i), name=esc(r["name"]), value=L.n(r["value"]))
    return L.t("boards.row.stars", rank=rank(L, i), name=esc(r["name"]), value=r["value"],
               extra=r["extra"], delta=r["delta"])


def board_label(L, tab):
    label = L.t(f"boards.tab.{tab}")
    icon = BOARD_ICONS.get(tab, "")
    return label[len(icon):].strip() if icon and label.startswith(icon) else label


def climb_block(L, rows, title="boards.climbers", row="boards.climber_row"):
    return L.t(title) + "\n" + quote("\n".join(
        L.t(row, rank=rank(L, i), name=esc(r["name"]), delta=L.n(r["delta"]))
        for i, r in enumerate(rows)))


def board_view(L, tab, period, rows, climb=None, footer=None, subtitle=None):
    icon = BOARD_ICONS.get(tab, "🏆")
    head = subtitle or (L.t(f"boards.period.{period}") if period else None)
    if not rows:
        return card(icon, board_label(L, tab), L.t("boards.empty"), head)
    body = quote("\n".join(board_row(L, tab, i, r) for i, r in enumerate(rows)))
    if climb:
        body += "\n\n" + climb_block(L, climb)
    tail = footer if footer is not None else (L.t(f"boards.encourage.{period}") if period else "")
    if tail:
        body += "\n\n" + tail
    return card(icon, board_label(L, tab), body, head)


def mvp_detail_block(L, name, parts):
    rows = parts if isinstance(parts, dict) else {}
    lines = [L.t("boards.mvp.part_row", label=L.t(f"boards.part.{key}"), value=rows[key])
             for key in BOARD_MVP_PARTS if key in rows]
    if not lines:
        return ""
    return L.t("boards.mvp.detail", name=esc(name)) + "\n" + quote("\n".join(lines))


def mvp_view(L, period, rows, subtitle=None):
    head = subtitle or (L.t(f"boards.period.{period}") if period else None)
    if not rows:
        return card("🏆", L.t("boards.mvp.title"), L.t("boards.empty"), head)
    body = quote("\n".join(
        L.t("boards.mvp.row", rank=rank(L, i), name=esc(r["name"]), total=r["total"])
        for i, r in enumerate(rows)))
    best = rows[0]
    body += "\n\n" + mvp_detail_block(L, best["name"], best["parts"])
    body += "\n\n" + L.t("boards.mvp.how")
    if period != "month":
        body += "\n" + L.t("boards.mvp.no_raid_attacks")
    return card("🏆", L.t("boards.mvp.title"), body, head)


def network_view(L, board, mine, joined):
    if not joined:
        return card("🌍", L.t("network.title"), L.t("network.off") + "\n\n" + L.t("network.note"))
    if not board:
        return card("🌍", L.t("network.title"), L.t("network.empty") + "\n\n" + L.t("network.note"))
    lines = []
    for i, r in enumerate(board):
        name = esc(r["name"]) if r.get("name") else L.t("network.anon", code=r.get("code"))
        lines.append(L.t("network.row", rank=rank(L, i), name=name,
                         avg=fixed(L, r["metrics"].get("avg") or 0, 1),
                         stars=r["metrics"].get("stars") or 0))
    body = quote("\n".join(lines))
    place = network_position(board, mine["alias"]) if mine else None
    if place:
        body += "\n\n" + L.t("network.you", n=place)
    return card("🌍", L.t("network.title"), body + "\n\n" + L.t("network.note"))


def points_view(L, season, board, streaks, n=15, activity=None):
    if not board:
        return card("🔮", L.t("points.title"), L.t("points.empty"), season_label(L, season["id"]))
    lines = []
    for i, (tag, e, pts) in enumerate(board[:n]):
        fire = L.t("points.streak", n=streaks[tag]["streak"]) if tag in streaks and streaks[tag]["streak"] >= 3 else ""
        lines.append(L.t("points.row", rank=rank(L, i), name=esc(e["name"]), points=pts, attacks=e["attacks"],
                         stars=e["stars"], triples=e["triples"], fire=fire))
    body = quote("\n".join(lines))
    seers = sorted(season.get("predictions", {}).values(), key=lambda p: (-p["correct"], p["total"]))[:5]
    if seers:
        body += "\n\n" + L.t("points.seers") + "\n" + quote("\n".join(
            L.t("points.seer_row", name=esc(p["name"]), correct=p["correct"], total=p["total"]) for p in seers))
    if activity:
        body += "\n\n" + L.t("activity.points.section") + "\n" + quote("\n".join(
            L.t("activity.points_row", name=esc(r.get("name")), points=r.get("score") or 0)
            for r in sorted(activity, key=lambda r: -(r.get("score") or 0))[:5]))
    body += "\n\n" + L.t("points.legend")
    return card("🔮", L.t("points.title"), body, season_label(L, season["id"]))


def season_end_card(L, sid, titles, board, mvp_parts=None):
    if not titles:
        return None
    lines = [
        L.t("season_end.row", icon=title_icon(t), title=L.t(f"title.{t}"), name=esc(name), value=L.n(value))
        for t, (name, value) in titles.items()
    ]
    body = quote("\n".join(lines))
    detail = mvp_detail_block(L, (titles.get("MVP") or ("",))[0], mvp_parts)
    if detail:
        body += "\n\n" + detail
    podium = [L.t("season_end.podium_row", rank=MEDALS[i], name=esc(e["name"]), points=pts)
              for i, (tag, e, pts) in enumerate(board[:3])]
    if podium:
        body += "\n\n" + L.t("season_end.podium") + "\n" + "\n".join(podium)
    body += "\n\n" + L.t("season_end.tail")
    return card("🏆", L.t("season_end.title"), body, season_label(L, sid))


def hall_view(L, hall):
    state = hall if isinstance(hall, dict) else {"seasons": list(hall or []), "records": {}}
    blocks = []
    head = records_block(L, state.get("records"))
    if head:
        blocks.append(head)
    for entry in list(reversed(state.get("seasons") or []))[:12]:
        lines = [L.t("hall.row", icon=title_icon(t), title=L.t(f"title.{t}"), name=esc(name))
                 for t, (name, value) in entry["titles"].items()]
        blocks.append(L.t("hall.season", season=season_label(L, entry["season"])) + "\n" + quote("\n".join(lines)))
    if not blocks:
        return card("🏛", L.t("hall.title"), L.t("hall.empty"))
    return card("🏛", L.t("hall.title"), "\n".join(blocks))


def week_summary(L, period_label, blocks, climb, points=None):
    sections = []
    for tab, rows in blocks:
        if not rows:
            continue
        sections.append(L.t("boards.week.block", icon=BOARD_ICONS.get(tab, "🏆"),
                            label=board_label(L, tab)) + "\n" + quote("\n".join(
            board_row(L, tab, i, r) for i, r in enumerate(rows))))
    if climb:
        sections.append(climb_block(L, climb))
    if points:
        sections.append(climb_block(L, points, "boards.climbers.points", "boards.climber_row.points"))
    if not sections:
        return card("📅", L.t("boards.week.title"), L.t("boards.empty"), period_label)
    body = "\n\n".join(sections) + "\n\n" + L.t("boards.encourage.week")
    return card("📅", L.t("boards.week.title"), body, period_label)


def season_summary(L, sid, mvp, leagues):
    body = ""
    if mvp:
        best = mvp[0]
        body += L.t("boards.week.block", icon=BOARD_ICONS["mvp"],
                    label=L.t("boards.mvp.title")) + "\n" + quote("\n".join(
            L.t("boards.mvp.row", rank=rank(L, i), name=esc(r["name"]), total=r["total"])
            for i, r in enumerate(mvp[:PODIUM])))
        body += "\n\n" + mvp_detail_block(L, best["name"], best["parts"])
    if leagues:
        body += ("\n\n" if body else "") + L.t("boards.season.leagues") + "\n" + quote("\n".join(
            L.t("boards.season.league_row", name=esc(r["name"]), league=esc(r["league"]),
                trophies=L.n(r["trophies"])) for r in leagues))
    body += ("\n\n" if body else "") + L.t("boards.encourage.season")
    return card("🏁", L.t("boards.season.title"), body, season_label(L, sid))


def rank_card(L, moves):
    rows = list(moves or ())
    if not rows:
        return None
    lines = [
        L.t("rank.clan_row" if m["kind"] == "clan" else "rank.player_row", name=esc(m.get("name")),
            band=L.t(f"rank.band.{rankings.TOP_N}"), rank=m.get("rank"))
        for m in rows
    ]
    return card("🌍", L.t("rank.title"), quote("\n".join(lines)) + "\n\n" + L.t("rank.tail"))


def ready_view(L, players, members):
    inside, outside, unknown = [], [], []
    for tag, m in members.items():
        p = (players or {}).get(tag)
        if not p:
            unknown.append(m["name"])
        elif p.get("warPref") == "out":
            outside.append(m["name"])
        else:
            inside.append(m["name"])
    nobody = L.t("ready.nobody")
    body = L.t("ready.in", n=len(inside)) + "\n" + quote(", ".join(esc(n) for n in sorted(inside)) or nobody)
    body += "\n" + L.t("ready.out", n=len(outside)) + "\n" + quote(", ".join(esc(n) for n in sorted(outside)) or nobody)
    if unknown:
        body += "\n" + L.t("ready.unknown", n=len(unknown))
    if inside or outside:
        body += "\n" + L.t("ready.readiness", pct=L.pct(hero_caps.clan_readiness(players, members), 0))
    body += "\n" + L.t("ready.note")
    return card("🧑‍🤝‍🧑", L.t("ready.title", n=len(inside)), body)


def heroes_view(L, players, members):
    rows = []
    for tag, m in members.items():
        p = (players or {}).get(tag)
        if not p:
            continue
        heroes = p.get("heroes") or {}
        ready = hero_caps.readiness(heroes, p.get("th"))
        icons = hero_slots(L, ready["rows"])
        rows.append((p.get("th") or 0, sum(heroes.values()),
                     L.t("heroes.row_ready", name=esc(m["name"]), th=p.get("th") or "?",
                         heroes=icons or "—", pct=L.pct(ready["pct"], 0))))
    if not rows:
        return card("🦸", L.t("heroes.title"), L.t("heroes.empty"))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    lines = [r[2] for r in rows]
    while len(lines) > 1 and len(compose("🦸", L.t("heroes.title"), quote("\n".join(lines)),
                                         L.t("heroes.legend"))) > MAX_LEN:
        lines.pop()
    return card("🦸", L.t("heroes.title"), quote("\n".join(lines)), L.t("heroes.legend"))


def targets_view(L, rows, war, kind="war", day=None):
    lines = []
    for r in rows:
        done = "✅" if r["best"] == 3 else ""
        hit = L.t("targets.hit", stars=L.stars(r["best"])) if r["by"] else ""
        by = L.t("targets.by", names=", ".join(esc(n) for n in r["by"][:2])) if r["by"] and not r["assignee"] else ""
        assignee = L.t("targets.assignee", name=esc(r["assignee"])) if r["assignee"] else L.t("targets.free")
        th = L.t("targets.th", th=r["th"]) if r.get("th") else ""
        lines.append(L.t("targets.row", pos=r["pos"], name=esc(r["name"]), th=th, assignee=assignee,
                         hit=hit, by=by, done=done).rstrip())
    assigned = sum(1 for r in rows if r["assignee"])
    return card("🎯", L.t("targets.title", assigned=assigned, total=len(rows)),
                quote("\n".join(lines)) if lines else L.t("targets.none"), war_title(L, kind, day))


def my_targets_view(L, name, rows, positions):
    mine = [r for r in rows if r["pos"] in positions]
    if not mine:
        return card("🎯", L.t("mine.title"), L.t("mine.none", name=esc(name)))
    lines = [
        L.t("mine.row", pos=r["pos"], name=esc(r["name"]),
            th=L.t("mine.th", th=r["th"]) if r.get("th") else "",
            stars=L.stars(r["best"]), done=L.t("mine.done") if r["best"] == 3 else "")
        for r in mine
    ]
    return card("🎯", L.t("mine.title"), L.t("mine.header", name=esc(name)) + "\n" + quote("\n".join(lines)))


def suggest_view(L, rows, war, kind="war", day=None, n=10):
    if not war:
        return card("💡", L.t("suggest.title"), L.t("suggest.none"))
    if not rows:
        return card("💡", L.t("suggest.title"), L.t("suggest.done"), war_title(L, kind, day))
    blocks = []
    for r in rows[:n]:
        th = L.t("targets.th", th=r["th"]) if r.get("th") else ""
        assignee = L.t("suggest.assignee", name=esc(r["assignee"])) if r.get("assignee") else ""
        head = L.t("suggest.target", pos=r["pos"], name=esc(r["name"]), th=th, assignee=assignee)
        if r["picks"]:
            picks = "\n".join(
                L.t("suggest.pick", mark=rank(L, i), name=esc(p["name"]), th=p["th"] or "?",
                    rate=L.pct(p["rate"] * 100, 0), power=p["power"])
                for i, p in enumerate(r["picks"])
            )
        else:
            picks = L.t("suggest.nobody")
        blocks.append(head + "\n" + picks)
    body = quote("\n".join(blocks))
    if len(rows) > n:
        body += "\n" + L.t("suggest.more", n=len(rows) - n)
    return card("💡", L.t("suggest.title"), body + "\n" + L.t("suggest.legend"), war_title(L, kind, day))


def me_facts(tag, snapshot):
    p = snapshot or {}
    return {"name": p.get("name"), "tag": tag, "th": p.get("th"), "league": p.get("league"),
            "trophies": p.get("trophies"), "best": p.get("best"), "stars": p.get("warStars"),
            "heroes": hero_levels(p.get("heroes")), "donations": p.get("donations"),
            "pref": p.get("warPref")}


def me_view(L, links, snapshots, trends=None, badges_line=""):
    blocks = []
    for link in links:
        p = snapshots.get(link.tag)
        if not p:
            blocks.append(L.t("me.unreachable", name=esc(link.name), tag=esc(link.tag)))
            continue
        facts = me_facts(link.tag, p)
        if facts["pref"] == "in":
            pref = L.t("me.pref_in")
        elif facts["pref"] == "out":
            pref = L.t("me.pref_out")
        else:
            pref = L.t("me.pref_unknown")
        blocks.append(quote(L.t(
            "me.block", name=esc(facts["name"]), tag=esc(facts["tag"]), th=facts["th"],
            league=esc(facts["league"] or L.t("me.no_league")), trophies=L.n(facts["trophies"]),
            best=L.n(facts["best"]), stars=L.n(facts["stars"]), heroes=facts["heroes"] or "",
            donations=L.n(facts["donations"]), pref=pref,
        )))
        ready = hero_caps.readiness(p.get("heroes"), p.get("th"))
        if ready["rows"]:
            blocks.append(L.t("me.ready", pct=L.pct(ready["pct"], 0),
                              heroes=hero_slots(L, ready["rows"])))
        line = labels_line(L, p.get("labels"))
        if line:
            blocks.append(line)
        samples = (trends or {}).get(link.tag) or []
        if len(samples) >= 2:
            change = trend_mod.move(samples)
            blocks.append(L.t("me.trend", days=L.t("activity.days", n=len(samples)),
                              bars=trend_mod.bars([s.get("trophies") for s in samples]),
                              delta=L.t("me.trend_up" if change >= 0 else "me.trend_down", n=abs(change))))
    if badges_line:
        blocks.append(badges_line)
    return card("🙋", L.t("me.title"), "\n".join(blocks))


def player_card(L, snapshot, tag):
    p = snapshot or {}
    ready = hero_caps.readiness(p.get("heroes"), p.get("th"))
    if p.get("warPref") == "in":
        pref = L.t("me.pref_in")
    elif p.get("warPref") == "out":
        pref = L.t("me.pref_out")
    else:
        pref = L.t("me.pref_unknown")
    body = quote(L.t("me.block", name=esc(p.get("name")), tag=esc(tag), th=p.get("th"),
                     league=esc(p.get("league") or L.t("me.no_league")), trophies=L.n(p.get("trophies")),
                     best=L.n(p.get("best")), stars=L.n(p.get("warStars")),
                     heroes=hero_levels(p.get("heroes")),
                     donations=L.n(p.get("donations")), pref=pref))
    if ready["rows"]:
        body += "\n" + L.t("me.ready", pct=L.pct(ready["pct"], 0), heroes=hero_slots(L, ready["rows"]))
    line = labels_line(L, p.get("labels"))
    if line:
        body += "\n" + line
    return card("🙋", L.t("player.title"), body)


def vs_value(L, row, side):
    value = row[side]
    if row["mode"] == "n":
        return L.n(value)
    if row["mode"] == "pct":
        return L.pct(value, 0)
    return str(value)


def vs_card(L, title, left_name, right_name, rows, left_labels=None, right_labels=None):
    lines = "\n".join(
        L.t("vs.row", mark=VS_MARKS[row["winner"]], label=L.t(f"vs.field.{row['key']}"),
            a=vs_value(L, row, "left"), b=vs_value(L, row, "right"))
        for row in rows
    )
    body = L.t("vs.header", a=esc(left_name), b=esc(right_name)) + "\n" + quote(lines)
    for name, names in ((left_name, left_labels), (right_name, right_labels)):
        line = labels_line(L, names)
        if line:
            body += "\n" + esc(name) + " " + line
    return card("⚖️", title, body)


def not_linked_me(L, bot_username):
    return card("🙋", L.t("me.title"), L.t("me.not_linked", bot=bot_username))


def link_ask_tag(L):
    return card("🔗", L.t("link.title"), L.t("link.ask_tag"))


def link_ask_token(L, name, tag):
    return card("🔗", L.t("link.title"),
                L.t("link.found", name=esc(name), tag=esc(tag)) + "\n\n" + L.t("link.ask_token"))


def link_done(L, name, tag):
    return card("✅", L.t("link.done.title"),
                L.t("player.line", name=esc(name), tag=esc(tag)) + "\n\n" + L.t("link.done.body"))


def onboard_ask_clan(L):
    return card("🚀", L.t("onboard.title"), L.t("onboard.ask_clan"))


def onboard_ask_player(L, clan_name):
    return card("🚀", L.t("onboard.title"), L.t("onboard.ask_player", clan=esc(clan_name)))


def onboard_ask_token(L, name):
    return card("🚀", L.t("onboard.title"), L.t("onboard.ask_token", name=esc(name)))


def onboard_ready(L, clan_name, tag):
    return card("✅", L.t("onboard.ready.title"), L.t("onboard.ready.body", clan=esc(clan_name), tag=esc(tag)))


def family_view(L, family, rows, activity=None):
    lines = []
    for r in rows:
        free = 50 - (r.get("members") or 0)
        lines.append(L.t(
            "family.row", name=esc(r["name"]), level=r.get("level") or "?", members=r.get("members") or "?",
            free=L.t("family.free", n=free) if free > 0 else L.t("family.full"),
            league=L.t("family.league", league=esc(r["league"])) if r.get("league") else "",
        ))
    body = quote("\n".join(lines)) if lines else L.t("family.none")
    if any((r.get("avg") or 0) for r in activity or ()):
        body += "\n\n" + activity_family_section(L, activity)
    body += "\n" + L.t("family.alias", alias=esc(family.alias))
    body += L.t("family.channel") if family.chat_id else L.t("family.no_channel")
    return card("👨‍👩‍👧‍👦", L.t("family.title", name=esc(family.name).upper()), body)


def recruit_board(L, tz, family, rows, now=None, notices=None):
    lines = []
    for r in rows:
        free = CLAN_SLOTS - (r.get("members") or 0)
        if free <= 0:
            continue
        req = L.t("recruit.req_th", th=r["min_th"]) if r.get("min_th") else L.t("recruit.req_any")
        note = L.t("recruit.note", note=esc(r["note"])) if r.get("note") else ""
        labels = labels_line(L, r.get("labels"))
        if labels:
            note += L.t("recruit.note", note=labels)
        link = f"https://link.clashofclans.com/{L.t('link.lang')}?action=OpenClanProfile&tag={r['tag'].replace('#', '%23')}"
        lines.append(L.t("recruit.row", link=link, name=esc(r["name"]), level=r.get("level") or "?",
                         n=free, req=req, note=note))
    body = quote("\n".join(lines)) if lines else L.t("recruit.full")
    if notices:
        body = quote("\n".join(notices)) + "\n\n" + body
    body += "\n" + L.t("recruit.updated", time=L.clock(now, tz))
    return clip(card("📣", L.t("recruit.title", name=esc(family.name).upper()), body))


def served_card(L, rows):
    lines = []
    for r in rows:
        name = r["name"] if r.get("name") else L.t("web.board.anon", code=str(r.get("code") or ""))
        lines.append(L.t("console.clans.row", name=esc(name), level=r.get("level") or "?",
                         members=int(r.get("members") or 0), free=int(r.get("free") or 0)))
    body = quote("\n".join(lines)) if lines else L.t("web.board.empty")
    return clip(card("📋", L.t("console.clans.title"), body))


def digest_card(L, family, clan_rows, top_stars, top_donors, top_loot, activity=None):
    lines = []
    for r in clan_rows:
        record = L.t("digest.record", wins=r["wins"], losses=r["losses"], ties=r["ties"]) if r["wars"] else L.t("digest.no_wars")
        lines.append(L.t("digest.row", name=esc(r["name"]), record=record,
                         stars=L.t("digest.stars", n=r["stars"]) if r["wars"] else ""))
    body = L.t("digest.week") + "\n" + quote("\n".join(lines))
    if top_stars:
        body += "\n\n" + L.t("digest.top_stars") + "\n" + quote("\n".join(
            L.t("digest.stars_row", rank=rank(L, i), name=esc(n), n=v, clan=esc(c))
            for i, (n, v, c) in enumerate(top_stars)))
    if top_donors:
        body += "\n\n" + L.t("digest.top_donors") + "\n" + quote("\n".join(
            L.t("digest.donors_row", rank=rank(L, i), name=esc(n), n=L.n(v), count=v, clan=esc(c))
            for i, (n, v, c) in enumerate(top_donors)))
    if top_loot:
        body += "\n\n" + L.t("digest.top_loot") + "\n" + quote("\n".join(
            L.t("digest.loot_row", rank=rank(L, i), name=esc(n), n=L.n(v), count=v, clan=esc(c))
            for i, (n, v, c) in enumerate(top_loot)))
    if any((r.get("avg") or 0) for r in activity or ()):
        body += "\n\n" + activity_family_section(L, activity)
    return card("📰", L.t("digest.title", name=esc(family.name).upper()), body)


def transfer_card(L, name, from_name, to_name):
    return card("🔁", L.t("transfer.title"),
                L.t("transfer.body", name=esc(name), from_clan=esc(from_name), to_clan=esc(to_name)))


def rejoin_card(L, rows):
    lines = "\n".join(
        L.t("rejoin.row", name=esc(r["name"]), away=L.t("activity.days", n=r["away"]),
            days=L.t("activity.days", n=r["days"]))
        for r in rows
    )
    return card("🔁", L.t("rejoin.title"), lines + "\n\n" + L.t("rejoin.tail"))


def anniversary_card(L, rows):
    lines = "\n".join(
        L.t("anniv.row", name=esc(r["name"]), n=r["years"], days=L.t("activity.days", n=r["days"]))
        for r in rows
    )
    return card("🎂", L.t("anniv.title"), lines + "\n\n" + L.t("anniv.tail"))


def legend_card(L, row):
    change = row.get("gained") or 0
    body = L.t("legend.today", trophies=L.n(row.get("trophies")),
               delta=L.t("me.trend_up" if change >= 0 else "me.trend_down", n=abs(change)))
    if row.get("rank"):
        body += "\n" + L.t("legend.rank", rank=L.n(row["rank"]))
    if row.get("best_trophies"):
        body += "\n" + L.t("legend.best", trophies=L.n(row["best_trophies"]),
                           rank=L.n(row.get("best_rank")), season=esc(row.get("best_season")))
    return card("👑", L.t("legend.title"), body + "\n\n" + L.t("legend.tail"), esc(row.get("name")))


def former_view(L, rows):
    if not rows:
        return card("🚪", L.t("former.title"), L.t("former.none"))
    lines = "\n".join(
        L.t("former.row", name=esc(r["name"]), away=L.t("activity.days", n=r["away"]),
            days=L.t("activity.days", n=r["days"]), stints=L.t("former.stints", n=r["stints"]))
        for r in rows[:FORMER_SHOWN]
    )
    return card("🚪", L.t("former.title"), quote(lines) + "\n" + L.t("former.note"),
                L.t("former.count", n=len(rows)))


def leader_report(L, clan, missed, inactive, out, idle=None, debt=None):
    body = ""
    if missed:
        body += L.t("report.missed") + "\n" + quote("\n".join(
            L.t("report.missed_row", name=esc(n), n=v) for n, v in missed[:REPORT_MISSED]))
    if inactive:
        body += ("\n\n" if body else "") + L.t("report.inactive") + "\n" + quote(
            ", ".join(esc(n) for n in inactive[:20]))
    if out:
        body += ("\n\n" if body else "") + L.t("report.out") + "\n" + quote(
            ", ".join(esc(n) for n in out[:20]))
    if idle:
        body += ("\n\n" if body else "") + L.t("activity.report.idle") + "\n" + quote("\n".join(
            L.t("activity.report.idle_row", name=esc(r.get("name")), days=L.t("activity.days", n=r.get("days") or 0))
            for r in idle[:20]))
    if debt:
        body += ("\n\n" if body else "") + L.t("report.debt") + "\n" + quote("\n".join(
            L.t("report.debt_row", name=esc(r.get("name")), given=L.n(r.get("value")),
                received=L.n(r.get("extra")))
            for r in list(debt)[:20]))
    if not body:
        body = L.t("report.ok")
    return card("📋", L.t("report.title"), body, esc(clan.name))


def prediction_result(L, bucket, options, winners):
    label = options[bucket] if bucket is not None else "?"
    if winners:
        return L.t("poll.result.win", label=esc(label),
                   winners=", ".join(L.t("name.plain", name=esc(w)) for w in winners))
    return L.t("poll.result.none", label=esc(label))


def hero_name(L, hero):
    slug = hero_caps.SLUGS.get(hero)
    return L.t(f"hero.name.{slug}") if slug else str(hero or "")


def goal_what(L, goal):
    if goal.get("kind") == "hero":
        return L.t("goal.what.hero", hero=esc(hero_name(L, goal.get("hero"))), n=goal.get("target"))
    return L.t(f"goal.what.{goal.get('kind')}", n=goal.get("target"))


def goal_card(L, name, goal, current_value):
    if not goal:
        return card("🎯", L.t("goal.title"), L.t("goal.none") + "\n\n" + L.t("goal.choose_kind"))
    body = L.t("goal.set", name=esc(name), what=goal_what(L, goal), current=L.n(current_value))
    return card("🎯", L.t("goal.title"), body)


def goal_not_member(L):
    return card("🎯", L.t("goal.title"), L.t("goal.not_member"))


def goal_done_card(L, rows):
    lines = "\n".join(
        L.t("goal.done.row", name=esc(r["name"]), what=goal_what(L, r["goal"])) for r in rows
    )
    return card("🎯", L.t("goal.done.title"), lines + "\n\n" + L.t("goal.done.tail"))


def member_week_card(L, row, samples=None):
    parts = []
    if (row.get("loot") or 0) > 0:
        parts.append(L.t("week.farm", loot=millions(L, row.get("loot"))))
    if (row.get("levels") or 0) > 0 or (row.get("th_up") or 0) > 0:
        parts.append(L.t("week.upgrade", levels=row.get("levels") or 0, th=row.get("th_up") or 0))
    if (row.get("wins") or 0) > 0:
        parts.append(L.t("week.wins", n=row.get("wins") or 0))
    if (row.get("games") or 0) > 0:
        parts.append(L.t("week.games", n=L.n(row.get("games") or 0), count=row.get("games") or 0))
    if samples and len(samples) >= 2:
        change = trend_mod.move(samples)
        parts.append(L.t("week.trophies", bars=trend_mod.bars([s.get("trophies") for s in samples]),
                         delta=L.t("me.trend_up" if change >= 0 else "me.trend_down", n=abs(change))))
    body = quote("\n".join(parts)) if parts else L.t("week.none")
    return card("📈", L.t("week.title"), body + "\n\n" + L.t("week.tail"))


def play_board_section(L, season, n=5):
    rows = [entry for _, entry in play_board(season)][:n]
    if not rows:
        return None
    return L.t("ch.board.head") + "\n" + quote("\n".join(
        L.t("ch.board.row", rank=rank(L, i), name=esc(p["name"]), points=p["points"])
        for i, p in enumerate(rows)))


def badge_card(L, name, icons):
    body = L.t("badge.new.who", who=esc(name), badges=icons) if name else L.t("badge.new", badges=icons)
    return card("🏅", L.t("badge.title"), body)


def ambassadors_section(L, rows, n=5):
    if not rows:
        return None
    return L.t("amb.section.head") + "\n" + quote("\n".join(
        L.t("amb.section.row", rank=rank(L, i), name=esc(row["name"] or L.t("amb.anonymous")),
            n=row["n"])
        for i, row in enumerate(rows[:n])))


def challenges_view(L, blocks):
    body = "\n\n".join(block for block in blocks if block)
    return card("🎲", L.t("ch.title"), body or L.t("ch.empty"))
