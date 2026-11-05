from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import tournaments
from .render import card, clip, esc, quote, rank

PAGE = 8
CLAN_METRICS = ("stars", "activity", "both")


def new_state(scope):
    return {
        "scope": scope,
        "kind": "internal" if scope == "clan" else "clash",
        "metric": "loot" if scope == "clan" else "stars",
        "format": "bracket",
        "size": 8,
        "window": tournaments.WINDOWS[1],
    }


def handle(state, data):
    state = dict(state or {})
    parts = (data or "").split(":")
    field = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""
    if field == "scope" and value in tournaments.SCOPES:
        state["scope"] = value
        state["kind"] = "internal" if value == "clan" else "clash"
        if value != "clan" and state.get("metric") not in CLAN_METRICS:
            state["metric"] = "stars"
    elif field == "metric" and value in tournaments.METRICS:
        state["metric"] = value
    elif field == "format" and value in tournaments.FORMATS:
        state["format"] = value
    elif field == "size" and value.isdigit() and int(value) in tournaments.SIZES:
        state["size"] = int(value)
    elif field == "window" and value.isdigit() and int(value) in tournaments.WINDOWS:
        state["window"] = int(value)
    return state


def to_doc(state, now):
    state = dict(new_state((state or {}).get("scope") or "clan"), **(state or {}))
    opens = int(now.timestamp())
    starts = opens + tournaments.SIGNUP_WINDOW
    rounds = tournaments.planned_rounds(state["format"], state["size"])
    return tournaments.empty(state["kind"], state["scope"], state["metric"], state["format"],
                             opens, starts, starts + int(state["window"]) * rounds,
                             size=state["size"], rounds_total=rounds)


def metric_label(L, metric):
    return L.t(f"tournament.metric.{metric}")


def value_label(L, doc, value):
    if doc.get("metric") in ("activity", "both"):
        return L.t("tournament.value.activity",
                   value=L.pct(value / tournaments.TENTHS, 1).rstrip("%"))
    return L.n(value)


def open_view(L, state):
    body = "\n".join((
        L.t("tournament.open.scope", value=L.t(f"tournament.scope.{state['scope']}")),
        L.t("tournament.open.metric", value=metric_label(L, state["metric"])),
        L.t("tournament.open.format", value=L.t(f"tournament.format.{state['format']}")),
        L.t("tournament.open.size", n=state["size"]),
        L.t("tournament.open.window", n=state["window"] // 86400),
    ))
    return card("🏆", L.t("tournament.open.title"), quote(body))


def open_keyboard(L, state):
    rows = [
        [InlineKeyboardButton(L.t(f"tournament.scope.{s}"), callback_data=f"tr:scope:{s}")
         for s in tournaments.SCOPES],
        [InlineKeyboardButton(metric_label(L, m), callback_data=f"tr:metric:{m}")
         for m in tournaments.METRICS[:4]],
        [InlineKeyboardButton(metric_label(L, m), callback_data=f"tr:metric:{m}")
         for m in tournaments.METRICS[4:]],
        [InlineKeyboardButton(L.t(f"tournament.format.{f}"), callback_data=f"tr:format:{f}")
         for f in tournaments.FORMATS],
        [InlineKeyboardButton(str(s), callback_data=f"tr:size:{s}") for s in tournaments.SIZES],
        [InlineKeyboardButton(L.t("tournament.btn.window", n=w // 86400), callback_data=f"tr:window:{w}")
         for w in tournaments.WINDOWS],
        [InlineKeyboardButton(L.t("tournament.btn.go"), callback_data="tr:go"),
         InlineKeyboardButton(L.t("tournament.btn.cancel"), callback_data="tr:cancel")],
    ]
    return InlineKeyboardMarkup(rows)


def _match_line(L, doc, match):
    left = esc(tournaments.name_of(doc, match["a"]))
    if not match["b"]:
        return L.t("tournament.bye", name=left)
    right = esc(tournaments.name_of(doc, match["b"]))
    if not match["done"]:
        return L.t("tournament.match", a=left, b=right)
    return L.t("tournament.match.done", a=left, b=right,
               sa=match["score"][0], sb=match["score"][1],
               winner=esc(tournaments.name_of(doc, match["winner"])))


def _table_block(L, doc, group=None):
    rows = tournaments.table(doc, group)[:PAGE]
    return "\n".join(L.t("tournament.row", rank=rank(L, i), name=esc(row["name"]),
                         value=value_label(L, doc, row["value"]))
                     for i, row in enumerate(rows))


def view(L, doc, now=None):
    doc = tournaments.ensure(doc)
    head = L.t("tournament.entries", n=len(doc["entries"]), size=doc["size"]) + "\n"
    head += L.t("tournament.metric.line", value=metric_label(L, doc["metric"]))
    body = quote(head)
    if doc["rounds"]:
        index = tournaments.next_round(doc)
        index = len(doc["rounds"]) - 1 if index is None else index
        body += "\n\n" + L.t("tournament.round", n=index + 1) + "\n" + quote(
            "\n".join(_match_line(L, doc, match) for match in doc["rounds"][index]))
    elif doc["groups"]:
        for number, _ in enumerate(doc["groups"]):
            body += "\n\n" + L.t("tournament.group", n=number + 1) + "\n" + quote(
                _table_block(L, doc, number))
    elif doc["entries"]:
        body += "\n\n" + quote("\n".join(
            L.t("tournament.entry", name=esc(entry["name"])) for entry in doc["entries"][:PAGE * 2]))
    mission = doc.get("mission")
    if mission:
        body += "\n\n" + L.t("tournament.mission", goal=L.n(mission["goal"]), value=L.n(mission["value"]))
    return clip(card("🏆", L.t(f"tournament.kind.{doc['kind']}").upper(), body))


def keyboard(L, doc, joined, manage):
    alias = doc.get("alias") or ""
    rows = []
    if alias and not tournaments.started(doc):
        action = "leave" if joined else "join"
        rows.append([InlineKeyboardButton(L.t(f"tournament.btn.{action}"),
                                          callback_data=f"tr:{action}:{alias}")])
    if alias:
        rows.append([InlineKeyboardButton(L.t("tournament.btn.refresh"),
                                          callback_data=f"tr:show:{alias}")])
    if manage:
        rows.append([InlineKeyboardButton(L.t("tournament.btn.open"), callback_data="tr:new")])
    return InlineKeyboardMarkup(rows) if rows else None


def list_view(L, docs):
    if not docs:
        return card("🏆", L.t("tournament.list.title"), L.t("tournament.none"))
    lines = [L.t("tournament.list.row", name=L.t(f"tournament.kind.{doc['kind']}"),
                 state=L.t(f"tournament.state.{doc.get('status') or 'signup'}"),
                 n=len(tournaments.ensure(doc)["entries"]))
             for doc in docs[:PAGE]]
    return card("🏆", L.t("tournament.list.title"), quote("\n".join(lines)))


def notice(L, doc, event):
    doc = tournaments.ensure(doc)
    kind = L.t(f"tournament.kind.{doc['kind']}")
    if event.get("type") == "final":
        name = tournaments.name_of(doc, event.get("winner")) if event.get("winner") else "?"
        return L.t("tournament.notice.final", kind=kind, name=name)
    return L.t("tournament.notice.signup", kind=kind, n=doc["size"])


def announcement(L, doc, event):
    doc = tournaments.ensure(doc)
    kind = L.t(f"tournament.kind.{doc['kind']}")
    if event.get("type") == "signup":
        return card("🏆", L.t("tournament.signup.title"),
                    L.t("tournament.signup.body", kind=kind, n=doc["size"],
                        metric=metric_label(L, doc["metric"])))
    if event.get("type") == "round":
        index = int(event.get("index") or 0)
        matches = doc["rounds"][index] if index < len(doc["rounds"]) else []
        body = quote("\n".join(_match_line(L, doc, match) for match in matches)) if matches else _table_block(L, doc)
        return clip(card("🥊", L.t("tournament.round.title", n=index + 1), body))
    if event.get("type") == "result":
        return clip(card("📊", L.t("tournament.result.title"), quote(_table_block(L, doc))))
    if event.get("type") == "final":
        name = tournaments.name_of(doc, event.get("winner")) if event.get("winner") else None
        if not name or name == "?":
            return card("🏁", L.t("tournament.final.title"), L.t("tournament.final.none", kind=kind))
        return card("🏁", L.t("tournament.final.title"),
                    L.t("tournament.final.body", kind=kind, name=esc(name)))
    if event.get("type") == "empty":
        return card("🏆", L.t("tournament.signup.title"), L.t("tournament.empty.body", kind=kind))
    return None
