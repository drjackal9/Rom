from .. import leader_cards
from ..acts import STAFF
from ..boards import SECTION_ORDER
from ..leaders import TEXT_MAX, sanitize
from . import payload

PENDING = "pending"
APPROVED = "approved"
REPORTS = "reports"
APPLICATIONS = "applications"
WARNINGS = "warnings"
PROPOSALS = "proposals"
WARS = "wars"
RECRUITMENT = "recruitment"
LEADERS = "leaders"
SECTIONS = "sections"
RECRUIT = "recruit"
FAMILY = "family"
INTEGRATIONS = "integrations"
BLOCKED = "blocked"
MIN_TH = "min_th"
TH = "th"
CODE = "code"
DERBY = "derby"
TOURNEY = "tourney"
TWITCH = "twitch"
DISCORD = "discord"
ICS = "ics"
BASES = "bases"
PAGE_ON = "page_on"
UNDO = "undo"
TEXTS = "texts"
WELCOME = "welcome"
RULES = "rules"
CLAN = "clan"
NAME = "name"
CARDS = {WELCOME: lambda L, text, clan: leader_cards.welcome_card(L, text, None, clan),
         RULES: lambda L, text, clan: leader_cards.rules_card(L, text)}


def staff_of(page, seat):
    mine = ((page or {}).get(payload.MANAGE) or {}).get(str((seat or {}).get("uid"))) or {}
    return mine.get(STAFF) or {}


def rows_of(tools, pack, field):
    return ((tools or {}).get(pack) or {}).get(field) or ()


def pending_row(row):
    return {"who": row.get("who"), "name": row.get("name"), "tag": row.get("tag")}


def approved_row(row):
    return {"who": row.get("who"), "name": row.get("name"), "trusted": bool(row.get("trusted"))}


def application_row(row):
    return {"id": row.get("id"), "name": row.get("name"), "th": row.get("th"),
            "goals": list(row.get("goals") or ())}


def report_row(row):
    return {"code": row.get("code"), "reason": row.get("reason"), "at": row.get("at")}


def warning_row(row):
    return {"tag": row.get("tag"), "name": row.get("name"), "missed": row.get("missed")}


def base_row(row):
    return {"id": row.get("id"), "name": row.get("name"), "label": row.get("label"),
            "village": row.get("village"), "hall": row.get("hall"), "link": row.get("link")}


def inbox_for(page, seat, tools=None):
    staff = staff_of(page, seat)
    return {
        PENDING: [pending_row(row) for row in staff.get(PENDING) or ()],
        APPLICATIONS: [application_row(row)
                       for row in rows_of(tools, RECRUITMENT, APPLICATIONS)],
        REPORTS: [report_row(row) for row in staff.get(REPORTS) or ()],
        WARNINGS: [warning_row(row) for row in rows_of(tools, WARS, PROPOSALS)],
        BASES: [base_row(row) for row in rows_of(tools, LEADERS, BASES)],
    }


def blocked_row(row):
    return {"id": row.get("id"), NAME: row.get(NAME)}


def recruit_of(tools):
    found = (tools or {}).get(RECRUITMENT)
    if not found:
        return None
    return {TH: found.get(MIN_TH),
            BLOCKED: [blocked_row(row) for row in found.get(BLOCKED) or ()]}


def family_of(tools):
    found = (tools or {}).get(FAMILY)
    if not found:
        return None
    return {NAME: found.get(NAME), CODE: found.get(CODE),
            DERBY: found.get(DERBY), TOURNEY: found.get(TOURNEY)}


def integrations_of(tools):
    found = (tools or {}).get(INTEGRATIONS)
    if not found:
        return None
    return {TWITCH: found.get(TWITCH) or "", DISCORD: bool(found.get(DISCORD)),
            ICS: bool(found.get(ICS))}


def packs_of(page):
    live = (page or {}).get(SECTIONS) or {}
    return {pack: pack in live for pack in SECTION_ORDER}


def texts_of(tools):
    return dict(((tools or {}).get(LEADERS) or {}).get(TEXTS) or {})


def preview_of(L, page, kind, raw=None):
    card = CARDS.get(kind)
    if card is None:
        return None
    stored = texts_of((page or {}).get(payload.TOOLS))
    text = sanitize(stored.get(kind) if raw is None else raw, TEXT_MAX)
    return card(L, text, ((page or {}).get(CLAN) or {}).get(NAME))


def manage_view(page, seat, tools=None):
    staff = staff_of(page, seat)
    leaders = (tools or {}).get(LEADERS) or {}
    return {
        "paused": bool(staff.get("paused")),
        "chief": bool(staff.get(UNDO)),
        "delegates": list(staff.get("delegates") or ()),
        "people": list(staff.get("people") or ()),
        "suspended": list(staff.get("suspended") or ()),
        APPROVED: [approved_row(row) for row in staff.get(APPROVED) or ()],
        "log": list(staff.get("log") or ()),
        "packs": packs_of(page),
        "schedules": list(leaders.get("scheduled") or ()),
        TEXTS: texts_of(tools),
        "channels": list(leaders.get("channels") or ()),
        PAGE_ON: bool(((page or {}).get(RECRUIT) or {}).get(PAGE_ON)),
        RECRUIT: recruit_of(tools),
        FAMILY: family_of(tools),
        INTEGRATIONS: integrations_of(tools),
    }
