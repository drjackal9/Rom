import json
import time

from ..acts import (ACTIONS, AVAIL, CHIEF_KINDS, DATA_KINDS, FIELD_MAX, LANG_KINDS, LEVELS,
                    LINK_KINDS, MANAGE_PACKS, MARKS, NO_SEAT, STAFF, SWITCH, TOKEN_ONLY, WEEKDAYS,
                    checked)
from ..badges import CATALOG as MEDALS, catalog as medal_catalog
from ..base_videos import THUMB, THUMB_HOST, THUMB_SIZE, WATCH
from ..bases import LABELS, VILLAGES
from ..boards import SECTION_ORDER
from ..cwl_roster import IN, OUT
from ..duels import DURATION_KEYS, METRICS
from ..events import EVENT_KINDS, ROLE_ORDER
from ..goals import KINDS as GOAL_KINDS
from ..guess_attack import CHOICES as GUESS_PERCENTS, STARS as GUESS_STARS
from ..i18n import LANGUAGES
from ..leaders import NOTE_MAX, TEXT_MAX
from ..media import BADGE_HOST
from ..mydata import SURE
from .. import door, reasons as denials, views
from ..recruit import DECIDED
from ..reports import REASONS
from ..privacy import DAY
from ..progress import IDLE_MIN_DAYS
from ..retention import INACTIVE_CLAN_DAYS
from ..settings import MANAGER, allowed
from ..util import esc
from . import app_manage, app_more, app_people, app_recap, app_war, http, live, payload, static
from .pages import shell

UNITS = ("d", "h", "m", "s")
DENIED = "denied"
CHIEF_ONLY = denials.CHIEF_ONLY
REFUSED = denials.REFUSED
UNDO = "undo"
FAMILY_PACK = "family"
DERBY = "derby"
OWNER = "owner"
TABS = ("war", "clan", "me", "more")
AGENDA = ("cwl", "games", "raid", "season")
TODO = ("duel", "quiz", "prediction", "link")
WAR_WORDS = ("vs", "prep", "left", "ended", "mine", "target", "change", "free", "missing",
             "enemy", "mirror", "last", "destr", "hits", "avg", "best", "book", "release",
             "clear", "swap", "plan", "watch", "shot", "top", "yours", "share")
STRIP_WORDS = ("link", "go", "whisper", "yes")
CWL_WORDS = ("day", "lineup", "pick", "bonus", "table")
RESULTS = ("win", "lose", "tie")
PRIVATE = ("seats", "profiles", "games", "events", "idle", app_recap.KEY, payload.DUELS,
           payload.MANAGE, payload.TOOLS, app_manage.SECTIONS)
OUTSIDER = "outsider"
REDUCED = "reduced"
FULL_VIEW = "full"
BOSS = MANAGER
VIEWS = (OUTSIDER, REDUCED, FULL_VIEW, BOSS)
KNOWN = door.SEEN
APPROVED = door.YES
BANNED = door.BAN
DOOR_KEYS = (KNOWN, APPROVED, BANNED)
OUT_KEYS = ("v", "updated", "lang", "tz", "clan", "recruit")
LOW_KEYS = OUT_KEYS + ("members", "events", "agenda", "games")
WAR_KEYS = ("war", "rows", "ours", "advice", "attack_videos", "wars", "last_war")
PLAN_KEYS = ("rows",)
BASE_KEYS = ("bases", "attack_videos")
LEAGUE_KEYS = ("cwl",)
NUMBER_KEYS = ("idle", "growth", "record")
SECTION_KEYS = {views.PLANS: PLAN_KEYS, views.BASES: BASE_KEYS,
                views.LEAGUE: LEAGUE_KEYS, views.NUMBERS: NUMBER_KEYS}
MEMBER_PRIVATE = ("tag", "linked", "verified", "avail")
SELF_KINDS = LINK_KINDS + DATA_KINDS + LANG_KINDS + ("report.send",)
LAST_ATTACKS = "last_attacks"
HIDDEN = ("uid", "who", payload.MARK)
LIMITED_PACKS = ("wars",)
AREAS = ("settings",) + MANAGE_PACKS + (STAFF,)
SHEET_KINDS = ("wars", "members")
HELP_LINKS = ("support", "creator", "community", "source")
LINK_WORDS = ("title", "yours", "mine", "verify", "steps", "token", "whisper", "drop", "terms")
DATA_WORDS = ("title", "forget", "sure", "gone", "device")
ME_WORDS = ("claimed", "verified", "medals", "tag", "share", "share_clan", "lang",
            "csv", "json")
CLAN_WORDS = ("record", "linked", "climb", "history", "chronicle", "absent",
              "ratio", "week", "month", "wars")
AGO = ("now", "hours", "yesterday", "days")
CLAN_SORTS = ("th", "trophies", "donations", "role")
GROWTH_WORDS = ("trophies", "week", "donated", "war_stars", "levels")
ROLES = tuple(ROLE_ORDER)
MORE_WORDS = ("games", "recruit", "family", "bases", "help", "duel", "rival", "quiz",
              "predict", "award", "free", "requirement", "apply", "support", "community",
              "creator", "source", "how", "report", "guess")
GUESS_WORDS = ("mine", "foe", "stars", "percent", "send", "wait", "done")
BASES_WORDS = ("videos", "open", "by", "hall", "kind", "copy", "propose")
BASES_TABS = ("clan", "library")
VIEW_WORDS = views.SECTIONS + ("title", "family")
CSP = ("default-src 'none'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "img-src data: " + THUMB_HOST + " https://" + BADGE_HOST + "; "
       "script-src 'self' https://telegram.org; connect-src 'self'; base-uri 'none'; "
       "frame-ancestors https://web.telegram.org https://telegram.org")
STYLE = ":root{--line:var(--bg)}"
SHEETS = ("base.css", "app/app.css")


MANAGE_WORDS = {
    "save": "web.app.manage.save",
    "on": "web.app.manage.on",
    "off": "web.app.manage.off",
    "restart": "web.app.manage.restart",
    "family_name": "web.app.manage.family_name",
    "family_code": "web.app.manage.family_code",
    "warn_title": "warn.title",
    "warn_yes": "warn.btn_yes",
    "warn_list": "warn.list_title",
    "undo": "web.app.manage.undo",
    "cwl_roster": "cwl.roster.title",
    "cwl_in": "cwl.btn.in",
    "cwl_out": "cwl.btn.out",
    "cwl_lineup": "cwl.roster.lineup",
    "cwl_bonus": "cwl.bonus.title",
    "rules_title": "leaders.rules.title",
    "welcome_title": "leaders.welcome.title",
    "sched_title": "leaders.schedule.title",
    "sched_add": "leaders.schedule.btn_add",
    "sched_del": "leaders.schedule.btn_del",
    "sched_hour": "leaders.schedule.pick_hour",
    "sched_days": "leaders.schedule.pick_days",
    "sched_text": "leaders.schedule.ask_text",
    "sched_every": "leaders.schedule.every_day",
    "gate_title": "leaders.gate.title",
    "gate_on": "leaders.gate.btn_on",
    "gate_off": "leaders.gate.btn_off",
    "note_title": "leaders.note.title",
    "export_title": "leaders.export.title",
    "export_wars": "leaders.export.btn_wars",
    "export_members": "leaders.export.btn_members",
    "req_hint": "h.requirements_th",
    "th_up": "web.app.manage.th_up",
    "th_down": "web.app.manage.th_down",
    "unblock": "web.app.manage.unblock",
    "app_yes": "recruit.btn_accept",
    "app_no": "recruit.btn_reject",
    "app_block": "recruit.btn_block",
    "block_title": "recruit.block.title",
    "twitch_title": "twitch.title",
    "ics_title": "web.set.ics",
    "discord_title": "discord.title",
    "integrations": "web.app.manage.integrations",
    "family_new": "web.app.manage.family_new",
    "family_invite": "web.app.manage.family_invite",
    "derby": "tournament.kind.derby",
    "tourney": "web.app.manage.tourney",
    "staff": "web.app.manage.staff",
    "paused": "board.all.paused",
    "pause": "web.app.manage.pause",
    "resume": "web.app.manage.resume",
    "delegates": "setup.delegates.label",
    "delegate_on": "web.app.manage.delegate_on",
    "delegate_off": "web.app.manage.delegate_off",
    "clear": "web.app.clear",
    "seats": "panel.seats.title",
    "lift": "web.app.manage.lift",
    "claims": "web.app.manage.claims",
    "now": "web.app.manage.now",
    "next": "web.app.manage.next",
    "revoke": "web.app.manage.revoke",
    "trust": "web.app.manage.trust",
    "approved": "web.app.manage.approved",
    "log": "leaders.log.title",
    "inbox": "web.app.manage.inbox",
    "applications": "web.app.manage.applications",
    "reports": "web.app.manage.reports",
    "warnings": "web.app.manage.warnings",
    "approve": "web.app.manage.approve",
    "reject": "web.app.manage.reject",
    "accept": "web.app.manage.accept",
    "void": "web.app.manage.void",
    "seen": "web.app.manage.seen",
    "packs": "web.app.manage.packs",
    "schedules": "web.app.manage.schedules",
    "suspended": "web.app.manage.suspended",
    "texts": "web.app.manage.texts",
    "welcome": "web.app.manage.welcome",
    "rules": "web.app.manage.rules",
    "channels": "web.app.manage.channels",
    "sure": "web.app.manage.sure",
    "settings": "web.app.manage.settings",
    "done": "web.app.manage.done",
    "undo_now": "web.app.manage.undo_now",
    "state_on": "web.app.manage.state_on",
    "state_off": "web.app.manage.state_off",
    "bases": "bases.title",
}
CONF = {"TOKEN_MAX": FIELD_MAX, "TEXT_MAX": TEXT_MAX, "NOTE_MAX": NOTE_MAX, "STAFF": STAFF,
        "BEAT": http.READ_TIMEOUT, "GRACE": live.LIVE_GRACE,
        "IDLE_MIN_DAYS": IDLE_MIN_DAYS, "KEEP": INACTIVE_CLAN_DAYS * DAY,
        "FULL": app_war.FULL, "WATCH": WATCH, "THUMB": THUMB, "THUMB_SIZE": THUMB_SIZE,
        "LABELS": list(LABELS),
        "AREAS": list(AREAS), "SHEETS": list(SHEET_KINDS), "SWITCH": list(SWITCH),
        "SECTIONS": list(views.SECTIONS), "SEEN_BY": list(views.VALUES),
        "DECIDED": list(DECIDED), "WAR_FROM": list(door.WAR_CHOICES), "SIDES": [IN, OUT],
        "MANAGE": list(MANAGE_PACKS),
        "MEDALS": dict(MEDALS), "AVAIL": list(AVAIL), "SURE": SURE,
        "REASONS": list(REASONS),
        "MARKS": {kind: list(names) for kind, names in MARKS.items() if names},
        "LANGS": [{"code": code, "name": name} for code, name in LANGUAGES.items()],
        "METRICS": list(METRICS), "DURATIONS": list(DURATION_KEYS),
        "GUESS_STARS": list(GUESS_STARS), "GUESS_PERCENTS": list(GUESS_PERCENTS),
        "WEEKDAYS": list(WEEKDAYS)}


def intent(body, tag, uid):
    return checked(body, tag, uid)


def token_only(body):
    return isinstance(body, dict) and str(body.get("kind") or "") in TOKEN_ONLY


def manager_only(kind):
    return bool(LEVELS.get(kind))


def under_level(kind, seat):
    return manager_only(kind) and not allowed(None, ACTIONS[kind], (seat or {}).get("level"))


def marked(page, field, seat):
    mark = str((seat or {}).get("mark") or "")
    return bool(mark) and mark in ((page or {}).get(field) or ())


def in_roster(page, seat):
    tag = str((seat or {}).get("tag") or "")
    return bool(tag) and any(row.get("tag") == tag for row in (page or {}).get("members") or ())


def proven(page, seat):
    return bool((seat or {}).get("verified", True)) and in_roster(page, seat)


def approval_of(page, seat):
    rows = (page or {}).get(APPROVED)
    mark = str((seat or {}).get(payload.MARK) or "")
    if rows is None or not mark:
        return {} if proven(page, seat) else None
    return rows.get(mark)


def level_of(page, seat):
    seat = seat or {}
    if seat.get("level"):
        return BOSS
    yes = approval_of(page, seat)
    if yes is not None and proven(page, seat):
        return FULL_VIEW
    if yes is not None or seat.get("tag") or marked(page, KNOWN, seat):
        return REDUCED
    return OUTSIDER


def sealed(page):
    return any(key in (page or {}) for key in DOOR_KEYS)


def shut(page, seat):
    if not seat or not sealed(page):
        return False
    return not seat.get(payload.MARK) or marked(page, BANNED, seat)


def needed(kind):
    if manager_only(kind):
        return BOSS
    if kind in NO_SEAT:
        return OUTSIDER
    return REDUCED if kind in SELF_KINDS else FULL_VIEW


def reads_feed(page, seat):
    return bool((seat or {}).get("tag")) and level_of(page, seat) in (FULL_VIEW, BOSS)


def may(kind, seat, page):
    if under_level(kind, seat):
        return False
    return VIEWS.index(level_of(page, seat)) >= VIEWS.index(needed(kind))


def chief_seat(page, seat):
    mine = ((page or {}).get(payload.MANAGE) or {}).get(str((seat or {}).get("uid"))) or {}
    return bool((mine.get(STAFF) or {}).get(UNDO))


def why(page, seat, kind):
    if under_level(kind, seat):
        return denials.NOT_MANAGER
    if not may(kind, seat, page):
        return denials.NOT_LINKED if not (seat or {}).get("tag") else denials.NOT_APPROVED
    if kind in CHIEF_KINDS and not chief_seat(page, seat):
        return CHIEF_ONLY
    return None


def own_derby(found, seat):
    family = found.get(FAMILY_PACK)
    if not family:
        return found
    kept = {key: value for key, value in family.items() if key != OWNER}
    if int(family.get(OWNER) or 0) != int((seat or {}).get("uid") or 0):
        kept[DERBY] = None
    return dict(found, **{FAMILY_PACK: kept})


def tools_for(page, seat):
    found = (page or {}).get(payload.TOOLS) or {}
    level = (seat or {}).get("level")
    if not level or not found:
        return None
    if level == MANAGER:
        return own_derby(found, seat)
    kept = {pack: rows for pack, rows in found.items() if pack in LIMITED_PACKS}
    return kept or None


def help_of(links):
    return {name: (links or {}).get(name) or "" for name in HELP_LINKS}


def in_lineup(page, seat):
    tag = str((seat or {}).get("tag") or "")
    return bool(tag) and any(row.get("tag") == tag for row in (page or {}).get("ours") or ())


def stamp_of(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def war_seen(page, seat):
    since = stamp_of((approval_of(page, seat) or {}).get(door.WAR_FROM))
    if not since:
        return True
    start = stamp_of(((page or {}).get("war") or {}).get("start"))
    return bool(start) and start >= since


def without(page, dropped):
    return {key: value for key, value in page.items() if key not in dropped}


def few_members(page):
    return [without(row, MEMBER_PRIVATE) for row in page.get("members") or ()]


def hidden_by(page, seat):
    state = views.state_of((page or {}).get(views.KIND))
    war = in_lineup(page, seat)
    dropped = (views.KIND,)
    for section in views.SECTIONS:
        if not views.sees(state, section, False, war):
            dropped += SECTION_KEYS[section]
    return dropped


def view_for(page, seat, level):
    page = page or {}
    if level == BOSS:
        return dict(page)
    if level == OUTSIDER:
        return {key: value for key, value in page.items() if key in OUT_KEYS}
    if level == REDUCED:
        found = {key: value for key, value in page.items() if key in LOW_KEYS}
        return dict(found, members=few_members(page)) if "members" in found else found
    dropped = hidden_by(page, seat)
    return without(page, dropped + WAR_KEYS if not war_seen(page, seat) else dropped)


def state_body(page, seat, unread=0, now=None, help=None, clans=()):
    clock = int(time.time() if now is None else now)
    level = level_of(page, seat)
    page = without(view_for(page, seat, level), DOOR_KEYS)
    body = {key: value for key, value in page.items() if key not in PRIVATE}
    body["level"] = level
    if level == BOSS:
        body[views.KIND] = views.state_of(page.get(views.KIND))
        body[app_manage.SECTIONS] = dict(page.get(app_manage.SECTIONS) or {})
    me = {key: value for key, value in seat.items() if key not in HIDDEN}
    profile = ((page or {}).get("profiles") or {}).get(str(seat.get("uid")))
    if profile:
        me["profile"] = profile
    manage = ((page or {}).get(payload.MANAGE) or {}).get(str(seat.get("uid")))
    if manage:
        me[payload.MANAGE] = manage
    tools = tools_for(page, seat)
    if tools:
        me[payload.TOOLS] = tools
        body["inbox"] = app_manage.inbox_for(page, seat, tools)
        body["manage_view"] = app_manage.manage_view(page, seat, tools)
    body["me"] = me
    body["people"] = app_people.members_view(page)
    body["me_view"] = app_people.me_view(page, seat)
    body["more_view"] = app_more.view_of(page, seat)
    body["help"] = help_of(help)
    body["unread"] = unread
    body["war_view"] = app_war.war_view(page, seat, clock)
    body["next"] = app_war.next_event(page, clock)
    body["todo"] = app_war.todo_for(page, seat)
    body[app_recap.KEY] = app_recap.view_of(page, seat)
    body["clans"] = [dict(row) for row in clans or ()]
    return body


async def clans_of(store, uid):
    found, seen = [], set()
    for link in await store.links_by_user(uid) or ():
        if link.alias in seen:
            continue
        seen.add(link.alias)
        clan = await store.clan_by_alias(link.alias)
        if not clan:
            continue
        found.append({"slug": payload.slug_for(store.vault, clan.alias), "name": clan.name})
    found.sort(key=lambda row: str(row["name"]))
    return found


SINGLE_WORDS = {"pos": "target.hint_pos", "th": "members.join.th",
                "target_th": "attack.target_th", "name_count": "common.name_count",
                "war_score": "card.war.title", "empty": "board.all.empty",
                "level": "web.page.level", "members": "web.page.members",
                "no_league": "me.no_league", "live_off": "web.app.live.off",
                "live_seen": "web.app.live.seen", "live_retry": "web.app.live.retry",
                "recap_title": "web.app.recap.title", "recap_share": "web.app.recap.share",
                "points": "web.page.points", "empty_screen": "web.app.empty.screen",
                "tab_manage": "web.app.tab.manage", "goal_title": "goal.title",
                "duel_accept": "duel.btn_accept", "req_none": "h.requirements_none",
                "page_state": "web.set.page", "more_privacy": "web.privacy.title",
                "more_terms": "web.terms.title",
                "more_donate": "web.home.donate", "more_stars": "web.home.stars"}


def denied_words(L):
    found = {key: L.t("web.app." + key) for key in (DENIED, "loading", "avail", "queued")}
    found[DENIED + "_" + CHIEF_ONLY] = L.t("web.app.denied_chief")
    found.update({DENIED + "_" + code: L.t("web.app.denied_" + code)
                  for code in denials.REASONS if code != CHIEF_ONLY})
    return found


def words(L):
    found = denied_words(L)
    found.update({name: L.t(key) for name, key in SINGLE_WORDS.items()})
    found.update({"tab_" + name: L.t("web.app.tab." + name) for name in TABS})
    found.update({"war_" + name: L.t("web.app.war." + name) for name in WAR_WORDS})
    found.update({"cwl_" + name: L.t("web.app.cwl." + name) for name in CWL_WORDS})
    found.update({"strip_" + name: L.t("web.app.strip." + name) for name in STRIP_WORDS})
    found.update({"war_" + name: L.t("foe.result." + name) for name in RESULTS})
    found.update({"next_" + key: L.t("agenda.item." + key) for key in AGENDA})
    found.update({"todo_" + name: L.t("web.app.todo." + name)
                  for name in TODO + ("title", "empty")})
    found.update({"pack_" + pack: L.t("board.title." + pack)
                  for pack in SECTION_ORDER + MANAGE_PACKS})
    found.update({"manage_" + name: L.t(key) for name, key in MANAGE_WORDS.items()})
    found.update({"avail_" + name: L.t("avail.option." + name) for name in AVAIL})
    found.update({"reason_" + name: L.t("report.reasons." + name) for name in REASONS})
    found.update({"unit_" + unit: L.t("unit." + unit) for unit in UNITS})
    found.update({"weekday_" + day: L.t("weekday." + day) for day in WEEKDAYS})
    found.update({"link_" + name: L.t("web.app.link." + name) for name in LINK_WORDS})
    found.update({"data_" + name: L.t("web.app.data." + name) for name in DATA_WORDS})
    found.update({"me_" + name: L.t("web.app.me." + name) for name in ME_WORDS})
    found.update({"badge_name_" + row["badge"]: L.t(row["name"]) for row in medal_catalog()})
    found.update({"badge_how_" + row["badge"]: L.t(row["how"]) for row in medal_catalog()})
    found.update({"goal_what_" + kind: L.t("goal.what." + kind) for kind in GOAL_KINDS})
    found.update({"clan_" + name: L.t("web.app.clan." + name) for name in CLAN_WORDS})
    found.update({"clan_sort_" + name: L.t("web.app.clan.sort." + name) for name in CLAN_SORTS})
    found.update({"ev_" + kind: L.t("web.app.clan.ev." + kind) for kind in EVENT_KINDS})
    found.update({"ago_" + name: L.t("ago." + name) for name in AGO})
    found.update({"growth_" + name: L.t("web.app.growth." + name) for name in GROWTH_WORDS})
    found.update({"role_" + name: L.t("role." + name, n=1) for name in ROLES})
    found.update({"more_" + name: L.t("web.app.more." + name) for name in MORE_WORDS})
    found.update({"guess_" + name: L.t("web.app.guess." + name) for name in GUESS_WORDS})
    found.update({"bases_" + name: L.t("web.app.bases." + name) for name in BASES_WORDS})
    found.update({"bases_" + name: L.t("bases.tab." + name) for name in BASES_TABS})
    found.update({"duel_metric_" + name: L.t("duel.metric." + name) for name in METRICS})
    found.update({"duel_duration_" + name: L.t("duel.duration." + name)
                  for name in DURATION_KEYS})
    found.update({"base_label_" + name: L.t("bases.label." + name) for name in LABELS})
    found.update({"base_village_" + name: L.t("bases.village." + name)
                  for name in VILLAGES.values()})
    found.update({"views_" + name: L.t("web.app.views." + name)
                  for name in VIEW_WORDS})
    found.update({"seen_" + name: L.t("web.app.seen." + name)
                  for name in views.VALUES})
    return found


def app_page(L, page, slug):
    payload_words = json.dumps(words(L), ensure_ascii=False, separators=(",", ":"))
    conf = json.dumps(CONF, ensure_ascii=False, separators=(",", ":"))
    body = (f'<div id="app" data-slug="{esc(slug)}" data-live="/app/{esc(slug)}/live" '
            f'data-words=\'{esc(payload_words)}\' data-conf=\'{esc(conf)}\'>'
            f'{esc(L.t("web.app.loading"))}</div>')
    title = f"{page['clan']['name']} · ClanBoard" if page else "ClanBoard"
    return shell(title, body, (page or {}).get("lang") or L.code, STYLE,
                 ("https://telegram.org/js/telegram-web-app.js",
                  static.url_for(static.BOOT)),
                 modules=(static.url_for("app/main.js"),),
                 preload=[static.url_for(name) for name in static.app_modules()],
                 styles=SHEETS)
