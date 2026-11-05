from collections import namedtuple

from .availability import OPTIONS as AVAIL
from .base_videos import ID_START, channel_of
from .bases import LABELS, parse_link
from .cwl_roster import IN, OUT
from .door import WAR_CHOICES
from .guess_attack import MOST as GUESS_MOST, STARS as GUESS_STARS
from .i18n import LANGUAGES
from .leaders import NOTE_MAX, TEXT_MAX, slot
from .recruit import DECIDED
from .reports import REASONS
from .settings import ACTIONS as SETTINGS_ACTIONS
from .views import SECTIONS, VALUES

TARGETS = "targets"
SETTINGS = "settings"
TOOLS = "tools"
WARNINGS = "warnings"
DELEGATES = "delegates"
PAUSE = "pause"
LINKS = "links"
STAFF = "staff"
VIEWS = "views"
MANAGE_PACKS = ("wars", "cwl", "leaders", "recruitment", "family", "integrations")
PRESS_HEAD = "cfg"
CALL_HEADS = ("dy", "tr")
SWITCH = ("on", "off")
ACCEPT = SWITCH[0]
WEEKDAYS = "0123456"
FIELD_MAX = 32
CHANNEL_TAIL = 22

Act = namedtuple("Act", "store clan conf kind body uid tag name level now coc bot members",
                 defaults=(None, None))


def _ident(value):
    return bool(value) and len(value) <= FIELD_MAX and value.isalnum()


def _num(value):
    return bool(value) and len(value) <= FIELD_MAX and value.isdigit()


def _word(value):
    return bool(value) and len(value) <= FIELD_MAX and value.replace("_", "").isalnum()


def _tag(value):
    return 1 < len(value) <= FIELD_MAX and value.startswith("#") and value[1:].isalnum()


def _name(value):
    return len(value) <= FIELD_MAX and all(ch.isalnum() or ch in " '-" for ch in value)


def _reason(value):
    return value in REASONS


def _choice(value):
    return value in AVAIL


def _part(value):
    return (bool(value) and len(value) <= FIELD_MAX
            and value.replace("_", "").replace("-", "").replace(".", "").isalnum())


def _press(value):
    parts = value.split(":")
    return len(parts) > 2 and parts[0] == PRESS_HEAD and all(_part(part) for part in parts[1:])


def _free(value):
    return bool(value.strip()) and len(value) <= TEXT_MAX


def _note(value):
    return len(value) <= NOTE_MAX


def _plan(value):
    return len(value) <= TEXT_MAX


def _call(value):
    parts = value.split(":")
    return len(parts) > 1 and parts[0] in CALL_HEADS and all(_part(part) for part in parts[1:])


def _switch(value):
    return value in SWITCH


def _side(value):
    return value in (IN, OUT)


def _verdict(value):
    return value in DECIDED


def _clock(value):
    return bool(slot(value))


def _days(value):
    return len(value) <= len(WEEKDAYS) and all(day in WEEKDAYS for day in value)


def _maybe_word(value):
    return not value or _word(value)


def _channel(value):
    return channel_of(value) == value and len(value) == len(ID_START) + CHANNEL_TAIL


def _lang(value):
    return value in LANGUAGES


def _link(value):
    return bool(parse_link(value))


def _label(value):
    return value in LABELS


def _section(value):
    return value in SECTIONS


def _seen_by(value):
    return value in VALUES


def _stars(value):
    return _num(value) and int(value) in GUESS_STARS


def _percent(value):
    return _num(value) and int(value) <= GUESS_MOST


def _war_from(value):
    return value in WAR_CHOICES


def _accept(value):
    return value in ("", ACCEPT)


MEMBER_KINDS = ("availability.set", "goal.set", "quiz.answer", "duel.challenge", "duel.accept",
                "award.vote", "prediction.set", "report.send", "guess.answer")
TARGET_OWN = ("target.set", "target.free", "target.mirror", "target.note", "target.swap")
TARGET_STAFF = ("target.clear",)
TARGET_KINDS = TARGET_OWN + TARGET_STAFF
LINK_KINDS = ("link.verify", "link.whisper", "link.drop")
DATA_KINDS = ("data.forget",)
SHARE_KINDS = ("share.week", "share.season", "share.war")
BASE_KINDS = ("base.propose",)
BASE_DECIDE = ("base.accept", "base.reject")
SHARE_MANAGER = ("share.clan",)
LANG_KINDS = ("lang.set",)
APP_KINDS = ("app.opened",)
SETUP_KINDS = ("settings.open", "settings.press")
TEXT_KINDS = ("welcome.set", "rules.set")
WARN_KINDS = ("warning.confirm", "warning.void")
CWL_KINDS = ("cwl.roster.set", "cwl.lineup.set", "cwl.bonus.toggle")
TOOL_KINDS = ("schedule.add", "schedule.delete", "gate.toggle", "note.set", "export.csv")
NET_KINDS = ("recruit.requirements.set", "application.decide", "sender.block", "sender.unblock")
FAMILY_KINDS = ("family.create", "family.invite", "family.derby", "family.tourney")
INTEGRATION_KINDS = ("integration.twitch", "integration.discord", "integration.ics")
PAGE_KINDS = ("page.toggle",)
CHANNEL_KINDS = ("channel.add", "channel.drop")
DELEGATE_KINDS = ("delegate.add", "delegate.remove", "delegates.clear")
PAUSE_KINDS = ("clan.pause", "clan.resume")
SEAT_KINDS = ("undo.apply", "suspension.lift")
VIEW_KINDS = ("view.set", "family.score.toggle")
PERSON_APPROVE = ("person.approve",)
PERSON_KINDS = PERSON_APPROVE + ("person.revoke", "person.trust")
NO_SEAT = ("link.verify",) + APP_KINDS
TOKEN_ONLY = ("link.claim", "link.approve", "link.reject")
CHIEF_KINDS = ("delegates.clear", "warning.void") + PAUSE_KINDS + SEAT_KINDS
SENSITIVE_KINDS = tuple(kind for kind in DELEGATE_KINDS + PAUSE_KINDS + SETUP_KINDS + TEXT_KINDS
                        if kind not in CHIEF_KINDS)
KINDS_MEMBER = (MEMBER_KINDS + TARGET_KINDS + LINK_KINDS + DATA_KINDS + SHARE_KINDS
                + LANG_KINDS + BASE_KINDS + APP_KINDS)
KINDS_MANAGER = (SETUP_KINDS + TEXT_KINDS + WARN_KINDS + CWL_KINDS + TOOL_KINDS + NET_KINDS
                 + FAMILY_KINDS + INTEGRATION_KINDS + PAGE_KINDS + CHANNEL_KINDS + DELEGATE_KINDS
                 + PAUSE_KINDS + SEAT_KINDS + SHARE_MANAGER + BASE_DECIDE
                 + VIEW_KINDS + PERSON_KINDS)
MANAGER_TOOLS = (TEXT_KINDS + CWL_KINDS + TOOL_KINDS + NET_KINDS + FAMILY_KINDS
                 + INTEGRATION_KINDS + PAGE_KINDS + CHANNEL_KINDS + SHARE_MANAGER + BASE_DECIDE
                 + ("warning.void", "undo.apply"))
ACTIONS = ({kind: None for kind in MEMBER_KINDS + LINK_KINDS + DATA_KINDS + SHARE_KINDS
                                   + LANG_KINDS + BASE_KINDS + APP_KINDS + TARGET_OWN}
           | {kind: TARGETS for kind in TARGET_STAFF}
           | {kind: SETTINGS for kind in SETUP_KINDS}
           | {kind: WARNINGS for kind in ("warning.confirm",)}
           | {kind: TOOLS for kind in MANAGER_TOOLS}
           | {kind: DELEGATES for kind in DELEGATE_KINDS + ("suspension.lift",)}
           | {kind: PAUSE for kind in PAUSE_KINDS}
           | {kind: LINKS for kind in PERSON_APPROVE}
           | {kind: VIEWS for kind in VIEW_KINDS + PERSON_KINDS[1:]})
LEVELS = {kind: SETTINGS_ACTIONS.get(action) for kind, action in ACTIONS.items()}
FIELDS = {
    "availability.set": {"choice": _choice},
    "goal.set": {"goal": _word, "target": _num, "hero": _name},
    "quiz.answer": {"option": _num},
    "guess.answer": {"stars": _stars, "percent": _percent},
    "duel.challenge": {"rival": _tag, "metric": _word, "duration": _word},
    "duel.accept": {"duel": _word},
    "award.vote": {"option": _num},
    "prediction.set": {"poll": _word, "option": _num},
    "report.send": {"reason": _reason},
    "target.set": {"pos": _num, "who": _num},
    "target.free": {"pos": _num},
    "target.mirror": {},
    "target.clear": {},
    "target.note": {"pos": _num, "text": _plan},
    "target.swap": {"pos": _num},
    "link.verify": {"village": _tag, "token": _ident, "terms": _accept},
    "link.whisper": {"village": _tag, "on": _word},
    "link.drop": {"village": _tag},
    "data.forget": {"sure": _word},
    "share.week": {},
    "share.season": {},
    "share.war": {},
    "share.clan": {},
    "lang.set": {"lang": _lang},
    "base.propose": {"link": _link, "label": _label},
    "base.accept": {"ref": _ident},
    "base.reject": {"ref": _ident},
    "app.opened": {},
    "settings.open": {},
    "settings.press": {"data": _press},
    "welcome.set": {"text": _free},
    "rules.set": {"text": _free},
    "warning.confirm": {"village": _tag},
    "warning.void": {"ref": _ident},
    "cwl.roster.set": {"village": _tag, "choice": _side},
    "cwl.lineup.set": {"village": _tag},
    "cwl.bonus.toggle": {"village": _tag},
    "schedule.add": {"hhmm": _clock, "days": _days, "text": _free},
    "schedule.delete": {"ref": _part},
    "gate.toggle": {"on": _switch},
    "note.set": {"village": _tag, "text": _note},
    "export.csv": {"sheet": _word},
    "recruit.requirements.set": {"th": _num},
    "application.decide": {"ref": _num, "choice": _verdict},
    "sender.block": {"ref": _num},
    "sender.unblock": {"ref": _num},
    "family.create": {"name": _name},
    "family.invite": {"ref": _part},
    "family.derby": {"data": _call},
    "family.tourney": {"data": _call},
    "integration.twitch": {"channel": _maybe_word},
    "integration.discord": {"on": _switch},
    "integration.ics": {"on": _switch},
    "page.toggle": {"on": _switch},
    "channel.add": {"channel": _channel},
    "channel.drop": {"channel": _channel},
    "delegate.add": {"who": _ident},
    "delegate.remove": {"who": _ident},
    "delegates.clear": {},
    "clan.pause": {},
    "clan.resume": {},
    "undo.apply": {"of": _word, "ref": _part},
    "suspension.lift": {"who": _ident},
    "view.set": {"section": _section, "value": _seen_by},
    "family.score.toggle": {},
    "person.approve": {"who": _ident, "war_from": _war_from},
    "person.revoke": {"who": _ident},
    "person.trust": {"who": _ident, "value": _switch},
}
NO_MARK = ("availability.set", "quiz.answer", "guess.answer", "award.vote", "report.send",
           "target.mirror", "target.clear", "data.forget", "share.week", "share.season",
           "share.war",
           "share.clan", "lang.set", "goal.set", "app.opened", "settings.open", "welcome.set",
           "rules.set", "gate.toggle", "recruit.requirements.set", "family.create",
           "integration.twitch", "integration.discord", "integration.ics", "page.toggle",
           "delegates.clear", "clan.pause", "clan.resume", "family.score.toggle")
ONE_MARK = {"duel.challenge": "rival", "duel.accept": "duel", "prediction.set": "poll",
            "target.set": "pos", "target.free": "pos", "target.note": "pos",
            "target.swap": "pos", "link.verify": "village",
            "link.whisper": "village", "link.drop": "village", "base.propose": "link",
            "base.accept": "ref", "base.reject": "ref", "settings.press": "data",
            "warning.confirm": "village", "warning.void": "ref", "cwl.roster.set": "village",
            "cwl.lineup.set": "village", "cwl.bonus.toggle": "village", "schedule.add": "hhmm",
            "schedule.delete": "ref", "note.set": "village", "export.csv": "sheet",
            "application.decide": "ref", "sender.block": "ref", "sender.unblock": "ref",
            "family.invite": "ref", "family.derby": "data", "family.tourney": "data",
            "channel.add": "channel", "channel.drop": "channel", "delegate.add": "who",
            "delegate.remove": "who", "suspension.lift": "who",
            "view.set": "section", "person.approve": "who", "person.revoke": "who",
            "person.trust": "who"}
MANY_MARKS = {"undo.apply": ("of", "ref")}
MARKS = ({kind: () for kind in NO_MARK} | {kind: (name,) for kind, name in ONE_MARK.items()}
         | dict(MANY_MARKS))


def checked(body, tag, uid):
    row = body if isinstance(body, dict) else {}
    kind = str(row.get("kind") or "")
    fields = FIELDS.get(kind)
    ident = str(row.get("id") or "")
    if fields is None or not _ident(ident):
        return None
    found = {"kind": kind, "by": uid, "tag": tag, "id": ident}
    for name, check in fields.items():
        value = str(row.get(name) or "")
        if not check(value):
            return None
        found[name] = value
    return found


def seat(links, members):
    for link in links or ():
        if link.tag in (members or {}):
            return link
    return None
