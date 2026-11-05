import asyncio
import logging
import secrets as pysecrets
from zoneinfo import available_timezones

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest
from telegram.ext import (CallbackQueryHandler, ChatMemberHandler, CommandHandler, ContextTypes,
                          MessageHandler, PollAnswerHandler, PollHandler, PreCheckoutQueryHandler,
                          filters)

from . import (agenda, ambassadors, awards, badges, bingo, brake, builder as builder_mod,
               capital as capital_mod, cards, challenges, compare, cwl_bonus, cwl_cards,
               cwl_roster, cwl_scout, cwl_season, cwl_store, cwl_table, derby, diagnostics,
               discipline, duels, family as family_mod, familyroom, games as games_mod,
               goals, guard, hub, i18n, integration_cards, integration_tools, leader_tools,
               leaderboards as boards, leaders,
               ledger, linking, manager_alerts, media, missions, news, one_group, polls, privacy,
               privacy_tools, quiz,
               reasons, recruit_tools, render,
               roles, roster as roster_mod, scoring, seats, settings as settings_mod, setup_ui,
               share,
               source as source_mod, stickers, suggest, support_cards, support_desk, survey, tips,
               topics, tourney_ui, tournaments, trend as trend_mod, undo, verify, warstats)
from .achievements import player_snapshot
from .coc import public_ip
from . import command_gate as gate_mod
from .command_gate import ACTION_BY_COMMAND, gate, gated
from .events import member_snapshot, member_stats, war_key, war_snapshot
from .retention import STAT_HISTORY_KEEP, WAR_HISTORY_KEEP
from .settings import clan_locale
from .setup_ui import ON
from .targets import assign, member_at, mirror_plan, plan_rows, targets_for
from .util import normalize_tag, now_utc
from .verify import LEADER_ROLES, userclan_key
from .web.app_war import ENDED as WAR_ENDED
from .web.payload import slug_for

log = logging.getLogger("clashbot.handlers")

COURTESY_KEY = gate_mod.COURTESY_KEY

COMMANDS_BY_AREA = {
    "group": [
        ("link", ["collega"]),
        ("unlink", ["scollega"]),
        ("settings", ["impostazioni"]),
        ("topics", ["argomenti"]),
        ("lang", ["lingua"]),
        ("tz", ["fuso"]),
        ("status", ["stato"]),
        ("check", ["controllo"]),
        ("newclan", ["nuovoclan"]),
        ("setclan", []),
        ("remove", ["rimuovi"]),
        ("cancel", ["annulla"]),
    ],
    "wars": [
        ("war", ["guerra"]),
        ("attacks", ["attacchi"]),
        ("targets", ["bersagli"]),
        ("mine", ["mio"]),
        ("ready", ["pronti"]),
        ("lazy", ["pigri"]),
        ("warnings", ["ammonizioni"]),
        ("foes", ["avversari"]),
        ("defense", ["difese"]),
        ("triples", ["triple"]),
        ("history", ["storico"]),
    ],
    "cwl": [
        ("cwl", []),
    ],
    "capital_games": [
        ("capital", ["capitale"]),
        ("games", ["giochi"]),
        ("builderbase", ["basecostruttore", "base2"]),
        ("agenda", []),
    ],
    "members": [
        ("boards", ["classifiche"]),
        ("points", ["punti"]),
        ("hall", ["albo"]),
        ("activity", ["attivita"]),
        ("top", []),
        ("donations", ["donazioni"]),
        ("stars", ["stelle"]),
        ("heroes", ["eroi"]),
        ("members", ["membri"]),
        ("former", ["ex"]),
        ("me", ["io"]),
        ("player", ["giocatore"]),
        ("vs", []),
        ("clanvs", ["clansfida"]),
        ("goal", ["obiettivo"]),
    ],
    "challenges": [
        ("challenges", ["sfide"]),
        ("duel", ["duello", "sfida"]),
    ],
    "bases": [
        ("base", []),
        ("bases", ["basi"]),
        ("stickers", ["adesivi"]),
    ],
    "family": [
        ("family", ["famiglia"]),
        ("tournament", ["torneo"]),
    ],
    "recruitment": [
        ("recruit", ["reclutamento"]),
        ("requirements", ["requisiti"]),
    ],
    "leaders": [],
    "data": [],
    "integrations": [],
    "support": [
        ("invite", ["invita", "condividi", "share"]),
        ("support", ["sostieni"]),
    ],
}

VIEWS = ("menu", "war", "attacks", "targets", "cwl", "games", "builderbase", "agenda", "boards",
         "ready", "heroes", "members", "former", "history", "me", "foes", "defense", "triples",
         "suggest", "challenges", "bases")

MENU_ROWS = [
    ["war", "attacks"],
    ["targets", "cwl"],
    ["boards", "agenda"],
    ["games", "builderbase"],
    ["members", "ready"],
    ["heroes", "history"],
    ["me"],
    ["former"],
    ["challenges"],
    ["bases"],
]

HELP_COLUMNS = max(len(row) for row in MENU_ROWS)

CLAN_LIMIT = 25

START_LINK = ("collega", "link")
START_NEWCLAN = ("nuovoclan", "newclan")
START_SUPPORT = ("sostieni", "support")
START_ACTION = ACTION_BY_COMMAND["newclan"]

GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)

ANONYMOUS_ADMIN_ID = 1087968824

_ZONES = {}


def known_zone(raw):
    if not _ZONES:
        for name in available_timezones():
            _ZONES[name.lower()] = name
    return _ZONES.get(str(raw).strip().lower())


def parse_lang(raw):
    text = str(raw or "").strip().replace("_", "-").lower()
    if not text:
        return None
    code = i18n.resolve(text)
    if code.lower() == text or code.lower().split("-")[0] == text.split("-")[0]:
        return code
    if i18n.ALIASES.get(text) == code:
        return code
    return None


def menu_keyboard(L):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(L.t(f"menu.{key}"), callback_data=f"v:{key}") for key in row] for row in MENU_ROWS]
    )


def back_keyboard(L, key, extra=None):
    rows = list(extra or [])
    rows.append([
        InlineKeyboardButton(L.t("menu.back"), callback_data="v:menu"),
        InlineKeyboardButton(L.t("menu.refresh"), callback_data=f"v:{key}"),
    ])
    return InlineKeyboardMarkup(rows)


METRIC_COLUMNS = 3
ME_ACCOUNTS = 3


def in_columns(buttons):
    return [buttons[i:i + METRIC_COLUMNS] for i in range(0, len(buttons), METRIC_COLUMNS)]


def challenges_keyboard(L, manage):
    if not manage:
        return back_keyboard(L, "challenges")
    metrics = [InlineKeyboardButton(L.t(f"mission.metric.{metric}"), callback_data=f"m:{metric}")
               for metric in missions.METRICS]
    prizes = [InlineKeyboardButton(L.t(f"award.category.{category}"), callback_data=f"aw:{category}")
              for category in awards.CATEGORIES]
    return back_keyboard(L, "challenges", in_columns(metrics) + in_columns(prizes))


CWL_TABS = ("cwl", "cwl:table", "cwl:roster", "cwl:scout", "cwl:bonus", "cwl:history")

TARGET_ACTIONS = ("set", "mirror", "clear")
LIVE_WAR = ("preparation", "inWar")
ENDED_WAR = (WAR_ENDED,)


def cwl_keyboard(L, key, extra=None):
    rows = list(extra or [])
    tabs = [
        InlineKeyboardButton((setup_ui.PICKED if tab == key else "") + L.t(f"menu.{tab.replace(':', '.')}"),
                             callback_data=f"v:{tab}")
        for tab in CWL_TABS
    ]
    rows += [tabs[i:i + 3] for i in range(0, len(tabs), 3)]
    return back_keyboard(L, key, rows)


def capital_tabs(L):
    return [
        [InlineKeyboardButton(L.t("menu.capital.raid"), callback_data="v:capital"),
         InlineKeyboardButton(L.t("menu.capital.eff"), callback_data="v:capital:eff"),
         InlineKeyboardButton(L.t("menu.capital.districts"), callback_data="v:capital:districts")],
        [InlineKeyboardButton(L.t("menu.capital.gold"), callback_data="v:capital:gold"),
         InlineKeyboardButton(L.t("menu.capital.hall"), callback_data="v:capital:hall")],
    ]


def capital_keyboard(L, tab):
    return back_keyboard(L, f"capital:{tab}" if tab else "capital", capital_tabs(L))


def board_extra(L, tab):
    if tab == "capital":
        return capital_tabs(L)
    if tab == "stars":
        return [[InlineKeyboardButton(L.t("menu.defense"), callback_data="v:defense"),
                 InlineKeyboardButton(L.t("menu.triples"), callback_data="v:triples")]]
    return None


def games_keyboard(L, tab):
    extra = [[InlineKeyboardButton(L.t("menu.games.now"), callback_data="v:games"),
              InlineKeyboardButton(L.t("menu.games.albo"), callback_data="v:games:albo")]]
    return back_keyboard(L, f"games:{tab}" if tab else "games", extra)


def targets_keyboard(L, manage, app_url=None):
    extra = []
    if app_url:
        extra.append([InlineKeyboardButton(L.t("web.app.open"), web_app=WebAppInfo(url=app_url))])
    if manage:
        extra.append([
            InlineKeyboardButton(L.t("h.btn_assign"), callback_data="t:pick"),
            InlineKeyboardButton(L.t("h.btn_mirror"), callback_data="t:mirror"),
            InlineKeyboardButton(L.t("h.btn_clear"), callback_data="t:clear"),
        ])
    extra.append([InlineKeyboardButton(L.t("menu.suggest"), callback_data="v:suggest")])
    return back_keyboard(L, "targets", extra)


async def app_url(store, clan):
    url = await media.site_base(store)
    if not url:
        return None
    return f"{url.rstrip('/')}/app/{slug_for(store.vault, clan.alias)}"


def services(context):
    return context.bot_data["store"], context.bot_data["coc"]


def bot_alias(context):
    return context.bot_data.get("bot_alias")


async def owner_id(context):
    store, _ = services(context)
    return await store.get_secret("owner_id")


async def is_platform_owner(update, context):
    owner = await owner_id(context)
    user = update.effective_user
    return bool(owner and user and str(user.id) == owner)


async def bot_owner_id(context):
    if "bot_owner" not in context.bot_data:
        store, _ = services(context)
        alias = bot_alias(context)
        bot = await store.bot_by_alias(alias) if alias else None
        context.bot_data["bot_owner"] = bot.owner_id if bot else 0
    return context.bot_data["bot_owner"]


async def is_owner(update, context):
    if await is_platform_owner(update, context):
        return True
    user = update.effective_user
    return bool(user and await bot_owner_id(context) == user.id)


async def user_roles(store, user_id, members):
    links = await store.links_by_user(user_id)
    return {(members or {}).get(l.tag, {}).get("role") for l in links} - {None}


async def can_manage(update, context, clan, action="settings"):
    if await is_owner(update, context):
        return True
    store, _ = services(context)
    user = update.effective_user
    if not user:
        return False
    members = await store.get_state(clan.alias, "members")
    conf = await clan_settings(store, clan)
    level = await roles.level(store, clan, conf, members or {}, user.id)
    return settings_mod.allowed(conf, action, level)


async def can_lead(update, context, clan):
    if await is_owner(update, context):
        return True
    store, _ = services(context)
    user = update.effective_user
    if not user:
        return False
    members = await store.get_state(clan.alias, "members")
    return leaders.can_lead(await user_roles(store, user.id, members))


async def clan_settings(store, clan):
    return settings_mod.effective(await store.get_state(clan.alias, "settings"), None)


def user_locale(update):
    user = getattr(update, "effective_user", None)
    return i18n.locale(getattr(user, "language_code", None))


def actor(update):
    message = getattr(update, "effective_message", None)
    if getattr(message, "sender_chat", None):
        return None
    user = getattr(update, "effective_user", None)
    if user is None or user.id == ANONYMOUS_ADMIN_ID:
        return None
    return user


def served_by(cached, alias):
    return isinstance(cached, dict) and "alias" in cached and cached.get("bot_alias") == alias


def private_chat(update):
    chat = getattr(update, "effective_chat", None)
    return getattr(chat, "type", None) == ChatType.PRIVATE


async def remember_language(store, update, links):
    user = getattr(update, "effective_user", None)
    if not links or not user or not private_chat(update):
        return
    lang = parse_lang(getattr(user, "language_code", None))
    if not lang or all(link.lang == lang for link in links):
        return
    await store.set_link_lang(user.id, lang)
    for link in links:
        link.lang = lang


async def clan_of_user(store, user_id, alias=None, links=None):
    links = await store.links_by_user(user_id) if links is None else links
    if not links:
        return None
    tags = {link.tag for link in links}
    key = userclan_key(store, user_id)
    cached = await store.kv_get(key)
    if served_by(cached, alias):
        if cached["alias"] is None:
            return None
        clan = await store.clan_by_alias(cached["alias"])
        if clan and clan.active:
            members = await store.get_state(clan.alias, "members") or {}
            if tags & members.keys():
                return clan
    for clan in await store.active_clans(alias):
        members = await store.get_state(clan.alias, "members") or {}
        if tags & members.keys():
            await store.kv_set(key, {"alias": clan.alias, "bot_alias": alias}, ttl=7 * 86400)
            return clan
    await store.kv_set(key, {"alias": None, "bot_alias": alias}, ttl=3600)
    return None


async def clan_for(update, context):
    store, _ = services(context)
    chat = update.effective_chat
    alias = bot_alias(context)
    clan = await store.clan_by_chat(chat.id, alias)
    if clan or chat.type != ChatType.PRIVATE or not update.effective_user:
        return clan
    links = await store.links_by_user(update.effective_user.id)
    await remember_language(store, update, links)
    return await clan_of_user(store, update.effective_user.id, alias, links)


async def actor_locale(store, update):
    user = actor(update)
    lang = parse_lang(getattr(user, "language_code", None)) if user else None
    if not lang and user:
        links = await store.links_by_user(user.id)
        lang = next((link.lang for link in links if link.lang), None)
    return i18n.locale(lang) if lang else user_locale(update)


async def spoken_locale(store, update, clan_L, tz):
    if not private_chat(update):
        return clan_L, tz
    return await actor_locale(store, update), tz


async def view_locale(update, context, clan):
    store, _ = services(context)
    place = await clan_locale(store, clan) if clan else (user_locale(update), "UTC")
    return await spoken_locale(store, update, *place)


async def chat_locale(update, context):
    store, _ = services(context)
    chat = update.effective_chat
    clan = await store.clan_by_chat(chat.id, bot_alias(context)) if chat else None
    L, tz = await view_locale(update, context, clan)
    return clan, L, tz


async def refuse_anonymous(update, context):
    if actor(update):
        return False
    _, L, _ = await chat_locale(update, context)
    await update.effective_message.reply_text(L.t("h.anonymous"))
    return True


async def family_locale(store, family, update=None):
    clans = await store.family_clans(family.alias)
    place = await clan_locale(store, clans[0]) if clans else (user_locale(update), "UTC")
    return await spoken_locale(store, update, *place)


async def save_settings(store, clan, changes, by=None, keep_prev=True):
    stored = settings_mod.merge(await store.get_state(clan.alias, "settings"), changes)
    if keep_prev:
        await undo.keep_prev(store, clan.alias, stored)
    await store.set_state(clan.alias, "settings", stored)
    if by:
        await ledger.record(store, clan.alias, "settings", by.id, by.first_name,
                            ",".join(sorted(changes)), now_utc())
    return stored


def thread_of(update):
    query = getattr(update, "callback_query", None)
    message = getattr(query, "message", None) or getattr(update, "effective_message", None)
    thread = getattr(message, "message_thread_id", None)
    return thread if isinstance(thread, int) and not isinstance(thread, bool) else None


def opened_step(context, alias):
    return ((getattr(context, "user_data", None) or {}).get("settings_step") or {}).get(alias)


def remembered_step(context, alias):
    return setup_ui.valid_step(opened_step(context, alias))


def remember_step(context, alias, step):
    data = getattr(context, "user_data", None)
    if data is not None:
        steps = dict(data.get("settings_step") or {})
        steps[alias] = step
        data["settings_step"] = steps


async def settings_state_at(store, clan, conf, user_id, step, thread=None):
    state = setup_ui.from_settings(conf, clan.alias, user_id, thread)
    state["step"] = step
    if step == "web":
        state["url"] = await media.site_base(store)
        state["slug"] = store.recruit_code(clan.alias) if state["url"] else None
    return await with_candidates(store, clan, state, step)


async def settings_state(update, context, store, clan, step):
    user = update.effective_user
    return await settings_state_at(store, clan, await clan_settings(store, clan),
                                   user.id if user else None, step, thread_of(update))


async def with_candidates(store, clan, state, step):
    if step == "delegates" and not state.get("candidates"):
        found = await roles.linked_members(store, await store.get_state(clan.alias, "members"))
        state["candidates"] = [[seats.seat_ref(store.vault, clan.alias, uid), name, int(uid)]
                               for uid, name in found]
    return state


async def save_settings_state(store, clan, state):
    before = settings_mod.migrate(await store.get_state(clan.alias, "settings"))
    doc = settings_mod.migrate(settings_mod.merge(before, setup_ui.updates(state)))
    if doc == before:
        return before, before, False
    await undo.keep_prev(store, clan.alias, doc)
    await store.set_state(clan.alias, "settings", doc)
    return before, doc, True


async def active_war(store, clan, states=LIVE_WAR):
    war = await store.get_state(clan.alias, "war")
    if war and war.get("state") in states:
        return war, "war", None
    cwl = await store.get_state(clan.alias, "cwl")
    cwl_war = await store.get_state(clan.alias, "cwl_war")
    if cwl and cwl.get("active") and cwl_war and cwl_war.get("state") in states:
        return cwl_war, "cwl", cwl_war.get("day")
    return None, None, None


async def current_plan(store, clan, war):
    plan = await store.get_state(clan.alias, "plan")
    if plan and war and plan.get("war") == war_key(war):
        return plan.get("targets") or {}
    return {}


async def linked_rows(store, user):
    return await store.links_by_user(user.id) if user else []


async def linked_tags(store, user):
    return [link.tag for link in await linked_rows(store, user)]


def board_hidden(tags, excluded):
    return bool(tags) and set(tags) <= set(excluded or ())


async def build_view(key, clan, context, update=None):
    store, coc = services(context)
    now = now_utc()
    L, tz = await view_locale(update, context, clan)
    user = update.effective_user if update else None
    if key == "menu":
        info = await store.get_state(clan.alias, "info")
        return render.menu_view(L, clan, info), menu_keyboard(L)
    if key in ("war", "attacks"):
        data, error = await coc.current_war(clan.tag)
        if error and error != "not_found":
            return render.api_error(L, error), back_keyboard(L, key)
        war = war_snapshot(data) if data else None
        view = render.war_view if key == "war" else render.attacks_view
        if not war or war.get("state") == "notInWar":
            tracked, kind, day = await active_war(store, clan)
            if tracked and kind == "cwl":
                return view(L, tz, tracked, "cwl", day, now), back_keyboard(L, key)
        return view(L, tz, war, "war", None, now), back_keyboard(L, key)
    if key == "targets":
        war, kind, day = await active_war(store, clan)
        if not war:
            return render.targets_view(L, [], None), back_keyboard(L, key)
        plan = await current_plan(store, clan, war)
        manage = update is not None and await can_manage(update, context, clan, "targets")
        return (render.targets_view(L, plan_rows(war, plan), war, kind, day),
                targets_keyboard(L, manage, await app_url(store, clan)))
    if key == "suggest":
        war, kind, day = await active_war(store, clan)
        players = (await store.get_state(clan.alias, "players") or {}).get("tags", {})
        plan = await current_plan(store, clan, war)
        records = await store.recent_wars(clan.alias, WAR_HISTORY_KEEP)
        rows = suggest.suggestions(war, players, plan, records)
        extra = [[InlineKeyboardButton(L.t("menu.targets"), callback_data="v:targets")]]
        return render.suggest_view(L, rows, war, kind, day), back_keyboard(L, key, extra)
    if key.split(":")[0] == "cwl":
        tab = key.split(":")[1] if ":" in key else ""
        if tab == "history":
            return (cwl_cards.history_card(L, await cwl_store.seasons(store, clan.alias)),
                    cwl_keyboard(L, key))
        if tab == "table":
            cwl = await store.get_state(clan.alias, "cwl") or {}
            cwl_war = await store.get_state(clan.alias, "cwl_war") or {}
            zones = await store.get_state(clan.alias, "cwl_zones") or {}
            rows = cwl_table.table(cwl, clan.tag)
            total = len(cwl.get("rounds") or [])
            ours = next((r for r in rows if r["us"]), None)
            rows = cwl_table.projection(rows, total, cwl_war.get("teamSize"))
            return (cwl_cards.table_card(L, rows, ours["played"] if ours else 0, total,
                                         (zones.get("leagues") or {}).get(cwl.get("league"))),
                    cwl_keyboard(L, key))
        if tab == "roster":
            cwl = await store.get_state(clan.alias, "cwl") or {}
            cwl_war = await store.get_state(clan.alias, "cwl_war") or {}
            state = cwl_roster.for_season(await store.get_state(clan.alias, "cwl_roster"),
                                          cwl.get("season"))
            records = cwl_season.season_wars(await store.recent_wars(clan.alias, 20), cwl.get("season"))
            players = (await store.get_state(clan.alias, "players") or {}).get("tags", {})
            rows = cwl_roster.rows(cwl_roster.registered(cwl, clan.tag), state,
                                   cwl_roster.played_days(records, cwl_war), records, players)
            size = cwl_war.get("teamSize")
            proposed, bench = cwl_roster.lineup(rows, size, cwl_roster.picked(state))
            buttons = [[InlineKeyboardButton(L.t("cwl.btn.in"), callback_data="cw:av:in"),
                        InlineKeyboardButton(L.t("cwl.btn.out"), callback_data="cw:av:out")]]
            return (cwl_cards.roster_card(L, rows, proposed, bench, size),
                    cwl_keyboard(L, key, buttons))
        if tab == "bonus":
            cwl = await store.get_state(clan.alias, "cwl") or {}
            state = cwl_roster.for_season(await store.get_state(clan.alias, "cwl_roster"),
                                          cwl.get("season"))
            records = cwl_season.season_wars(await store.recent_wars(clan.alias, 20), cwl.get("season"))
            rows = cwl_bonus.proposal(cwl_season.member_rows(records, state),
                                      cwl_bonus.past_bonus(await cwl_store.seasons(store, clan.alias, 12)),
                                      state.get("bonus"))
            manage = update is not None and await can_manage(update, context, clan)
            buttons = []
            if manage and rows:
                marks = [InlineKeyboardButton(("🎖 " if r.get("assigned") else "") + str(r.get("name")),
                                              callback_data=f"cw:b:{r['tag']}") for r in rows]
                buttons = [marks[i:i + 3] for i in range(0, len(marks), 3)]
            return cwl_cards.bonus_card(L, rows), cwl_keyboard(L, key, buttons)
        if tab == "scout":
            cwl = await store.get_state(clan.alias, "cwl") or {}
            scout = await store.get_state(clan.alias, "cwl_scout") or {}
            return (cwl_cards.scout_card(L, cwl_scout.rows(scout, clan.tag), cwl.get("season")),
                    cwl_keyboard(L, key))
        cwl = await store.get_state(clan.alias, "cwl")
        cwl_war = await store.get_state(clan.alias, "cwl_war")
        return render.cwl_view(L, tz, cwl, cwl_war, clan.tag, now), cwl_keyboard(L, key)
    if key.startswith("capital:"):
        tab = key.split(":")[1]
        if tab == "hall":
            cap = await store.get_state(clan.alias, "capital") or {}
            return capital_mod.hall_card(L, cap.get("hall")), capital_keyboard(L, tab)
        if tab == "gold":
            cap = await store.get_state(clan.alias, "capital") or {}
            state = await store.get_state(clan.alias, "progress") or {}
            return capital_mod.gold_card(L, capital_mod.gold_since(state, cap)), capital_keyboard(L, tab)
        data, error = await coc.capital_raids(clan.tag)
        if error:
            return render.api_error(L, error), capital_keyboard(L, tab)
        items = data.get("items") or []
        raid = items[0] if items else None
        if tab == "eff":
            return capital_mod.efficiency_card(L, raid), capital_keyboard(L, tab)
        if tab == "districts":
            return capital_mod.districts_card(L, raid), capital_keyboard(L, tab)
        members = await store.get_state(clan.alias, "members")
        return render.capital_view(L, tz, raid, members, now), capital_keyboard(L, tab)
    if key.split(":")[0] == "games":
        albo = key.split(":")[1:2] == ["albo"]
        edition = None if albo else await store.get_state(clan.alias, "games")
        if edition and not edition.get("closed"):
            return games_mod.board_text(L, tz, edition, now), games_keyboard(L, None)
        history = await store.recent_stats(clan.alias, "games", STAT_HISTORY_KEEP)
        if albo:
            return games_mod.albo_card(L, history), games_keyboard(L, "albo")
        start, _ = agenda.clan_games(now)
        return games_mod.waiting_card(L, tz, start, history, now), games_keyboard(L, None)
    if key == "builderbase":
        members = await store.get_state(clan.alias, "members") or {}
        state = await store.get_state(clan.alias, "builder") or {}
        players = (await store.get_state(clan.alias, "players") or {}).get("tags", {})
        rows = builder_mod.trophy_rows(members, state.get("base"), players)
        return builder_mod.board_card(L, rows), back_keyboard(L, "builderbase")
    if key == "agenda":
        season_end = await integration_tools.goldpass_end(store)
        return render.agenda_view(L, tz, agenda.upcoming(now, season_end), now), back_keyboard(L, key)
    if key.split(":")[0] in hub.COMMAND_TABS:
        tab, period = hub.COMMAND_TABS[key.split(":")[0]]
        data = await hub.sources(store, coc, clan, tab, period, now, tz,
                                 await integration_tools.goldpass_end(store))
        tags = await linked_tags(store, user)
        return (await hub.view(L, tz, tab, period, data, now),
                hub.keyboard(L, tab, period, board_hidden(tags, data["hidden"]),
                             board_extra(L, tab), bool(tags)))
    if key == "challenges":
        state = await challenges.load(store, clan.alias)
        season = await store.get_state(clan.alias, "season") or scoring.empty_season(scoring.season_id(now, tz))
        blocks = [missions.section(L, state), quiz.section(L, state), duels.section(L, state),
                  bingo.section(L, state), render.play_board_section(L, season),
                  awards.section(L, state), badges.section(L, state),
                  render.ambassadors_section(L, await ambassadors.board(store))]
        manage = update is not None and await can_manage(update, context, clan)
        return render.challenges_view(L, blocks), challenges_keyboard(L, manage)
    if key in ("ready", "heroes"):
        players = (await store.get_state(clan.alias, "players") or {}).get("tags", {})
        members = await store.get_state(clan.alias, "members") or {}
        view = render.ready_view if key == "ready" else render.heroes_view
        return view(L, players, members), back_keyboard(L, key)
    if key == "members":
        data, error = await coc.clan(clan.tag)
        if error:
            return render.api_error(L, error, clan.tag), back_keyboard(L, key)
        members = member_snapshot(data)
        return render.members_view(L, members, {"level": data.get("clanLevel")}), back_keyboard(L, key)
    if key == "history":
        data, error = await coc.war_log(clan.tag, 12)
        if error:
            return render.api_error(L, error), back_keyboard(L, key)
        extra = [[InlineKeyboardButton(L.t("menu.foes"), callback_data="v:foes")]]
        return render.history_view(L, tz, data.get("items") or [], now), back_keyboard(L, key, extra)
    if key in ("foes", "defense", "triples"):
        records = await store.recent_wars(clan.alias, WAR_HISTORY_KEEP)
        if key == "foes":
            return render.foes_view(L, warstats.opponents(records), now), back_keyboard(L, key)
        if key == "defense":
            rows = warstats.defense_rows(records)
            return render.defense_view(L, rows, warstats.wall(rows), len(records)), back_keyboard(L, key)
        return render.triples_view(L, warstats.th_rows(records), len(records)), back_keyboard(L, key)
    if key == "bases":
        return await _base_ui().hub_view(update, context, clan)
    if key == "former":
        records = await store.former_members(clan.alias, roster_mod.FORMER_SHOWN)
        return render.former_view(L, roster_mod.former_rows(records, int(now.timestamp()))), back_keyboard(L, key)
    if key == "me":
        links = await store.links_by_user(user.id) if user else []
        if not links:
            return render.not_linked_me(L, context.bot.username), back_keyboard(L, key)
        roster_state = await store.get_state(clan.alias, "roster") or {}
        trend_state = await store.get_state(clan.alias, "trend") or {}
        snapshots = {}
        for link in links[:ME_ACCOUNTS]:
            data, _ = await coc.player(link.tag)
            if data:
                snapshots[link.tag] = player_snapshot(data)
        trends = {link.tag: trend_mod.series(trend_state, link.tag) for link in links[:ME_ACCOUNTS]}
        state = await challenges.load(store, clan.alias)
        marks = badges_line(L, state, user.id, links)
        extra = await ambassador_row(store, L, user.id)
        return (render.me_view(L, links, snapshots, trends=trends, badges_line=marks),
                me_keyboard(L, links, roster_state, extra))
    return render.menu_view(L, clan), menu_keyboard(L)


def badges_line(L, state, user_id, links):
    owners = [user_id] + [link.tag for link in links[:ME_ACCOUNTS]]
    return " ".join(filter(None, (badges.line(L, state, who) for who in owners)))


async def ambassador_row(store, L, user_id):
    if not await ambassadors.brought(store, user_id):
        return None
    return [[InlineKeyboardButton(L.t("amb.btn_show"), callback_data="a:show"),
             InlineKeyboardButton(L.t("amb.btn_hide"), callback_data="a:hide")]]


async def show(update, context, key):
    allowed = await gate(update, context)
    if not allowed:
        return
    clan, _ = allowed
    store, _ = services(context)
    if not clan:
        if key == "me" and update.effective_chat.type == ChatType.PRIVATE:
            await cmd_me(update, context)
            return
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    text, keyboard = await build_view(key, clan, context, update)
    await media.reply(update.effective_message, store, text, reply_markup=keyboard)


def command(key):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await show(update, context, key)
    return handler


async def edit_or_log(query, text, keyboard, alias):
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.warning("%s: modifica messaggio fallita: %s", alias, e)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    allowed = await gate(update, context)
    if not allowed:
        return
    clan, _ = allowed
    key = query.data.split(":", 1)[1]
    if not clan:
        await edit_or_log(query, render.not_linked_view(user_locale(update)), None, "?")
        return
    text, keyboard = await build_view(key, clan, context, update)
    await edit_or_log(query, text, keyboard, clan.alias)


async def on_board_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    allowed = await gate(update, context)
    if not allowed:
        await query.answer()
        return
    clan, _ = allowed
    store, coc = services(context)
    if not clan:
        await query.answer()
        await edit_or_log(query, render.not_linked_view(user_locale(update)), None, "?")
        return
    L, tz = await view_locale(update, context, clan)
    now = now_utc()
    links = await linked_rows(store, update.effective_user)
    tags = [row.tag for row in links]
    if query.data in ("b:network:toggle", "b:network:name"):
        if not await can_manage(update, context, clan):
            await query.answer(L.t("h.admin_only"), show_alert=True)
            return
        row = await store.network_get(clan.alias)
        if query.data == "b:network:toggle" and row and row["visible"]:
            await store.network_forget(clan.alias)
            await query.answer(L.t("network.left"), show_alert=True)
        else:
            named = not bool(row and row["named"]) if query.data == "b:network:name" else False
            await store.network_set(clan.alias, True, named,
                                    await hub.network_payload_now(store, clan, now, tz))
            await query.answer(L.t("network.named_on") if named and query.data == "b:network:name"
                               else L.t("network.named_off") if query.data == "b:network:name"
                               else L.t("network.joined"), show_alert=True)
        tab, period = "network", "week"
    elif query.data == "b:me:hide":
        if not tags:
            await query.answer(L.t("boards.no_account"), show_alert=True)
            return
        hide = not board_hidden(tags, await privacy.excluded(store, clan.alias))
        for row in links:
            await privacy.set_excluded(store, clan.alias, row.tag, hide, row.name, now)
        await query.answer(L.t("boards.hidden") if hide else L.t("boards.shown"), show_alert=True)
        tab, period = hub.DEFAULT_TAB, boards.default_period(hub.DEFAULT_TAB)
    else:
        await query.answer()
        tab, period = hub.parse(query.data)
    data = await hub.sources(store, coc, clan, tab, period, now, tz,
                             await integration_tools.goldpass_end(store))
    hidden = board_hidden(tags, data["hidden"])
    text = await hub.view(L, tz, tab, period, data, now)
    extra = board_extra(L, tab)
    if tab == "network" and await can_manage(update, context, clan):
        row = data.get("network") or {}
        extra = hub.network_rows(L, bool(row.get("visible")), bool(row.get("named")))
    await edit_or_log(query, text, hub.keyboard(L, tab, period, hidden, extra, bool(tags)),
                      clan.alias)


async def on_mission_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, tz = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await query.answer(L.t("h.admin_only"), show_alert=True)
        return
    await query.answer()
    metric = query.data.split(":", 1)[1]
    state = await challenges.load(store, clan.alias)
    if missions.set_metric(state, metric,
                           await missions.current_total(store, clan.alias, metric, now_utc(), tz)):
        await challenges.save(store, clan.alias, state)
    text, keyboard = await build_view("challenges", clan, context, update)
    await edit_or_log(query, text, keyboard, clan.alias)


async def on_award_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, tz = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await query.answer(L.t("h.admin_only"), show_alert=True)
        return
    await query.answer()
    parts = query.data.split(":")
    members = await store.get_state(clan.alias, "members") or {}
    if len(parts) == 2:
        rows = [[InlineKeyboardButton(m["name"], callback_data=f"aw:{parts[1]}:{tag}")]
                for tag, m in sorted(members.items(), key=lambda kv: kv[1]["name"] or "")]
        rows.append([InlineKeyboardButton(L.t("menu.back"), callback_data="v:challenges")])
        await edit_or_log(query, L.t("award.ask_member", category=L.t(f"award.category.{parts[1]}")),
                          InlineKeyboardMarkup(rows), clan.alias)
        return
    member = members.get(parts[2])
    if not member:
        return
    state = await challenges.load(store, clan.alias)
    given = awards.give(state, scoring.season_id(now_utc(), tz), parts[1], parts[2], member["name"],
                        int(now_utc().timestamp()))
    if given:
        await challenges.save(store, clan.alias, state)
        await leaders.notify(store, context.bot, clan, await clan_settings(store, clan),
                             awards.EVENT_AWARD, awards.given_card(L, parts[1], member["name"]),
                             now=now_utc())
    text, keyboard = await build_view("challenges", clan, context, update)
    await edit_or_log(query, text, keyboard, clan.alias)


async def on_ambassador_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    store, _ = services(context)
    user = update.effective_user
    visible = query.data == "a:show"
    L = await actor_locale(store, update)
    if not await ambassadors.set_visible(store, user.id, user.first_name, visible):
        await query.message.reply_text(L.t("amb.unavailable"))
        return
    await query.message.reply_text(L.t("amb.visible" if visible else "amb.hidden"))


async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    L = (await view_locale(update, context, clan))[0] if clan else user_locale(update)
    username = share.console_of(context)
    if not clan or not username:
        await update.effective_message.reply_text(L.t("amb.unavailable"))
        return
    code = await ambassadors.invite(store, update.effective_user.id, clan.alias)
    await update.effective_message.reply_text(
        render.share_card(L, ambassadors.link(username, code)),
        reply_markup=share.keyboard(L, username, code))


async def on_targets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan, "targets"):
        await query.answer(L.t("h.admin_only"), show_alert=True)
        return
    war, kind, day = await active_war(store, clan)
    if not war:
        await query.answer(L.t("h.no_war"), show_alert=True)
        return
    parts = query.data.split(":")
    action = parts[1]
    plan = await current_plan(store, clan, war)
    if action == "pick":
        rows = plan_rows(war, plan)
        buttons = [InlineKeyboardButton(f"#{r['pos']}{' ' + ON if r['best'] == 3 else ''}", callback_data=f"t:pos:{r['pos']}") for r in rows]
        grid = [buttons[i:i + 5] for i in range(0, len(buttons), 5)]
        grid.append([InlineKeyboardButton(L.t("h.btn_targets"), callback_data="v:targets")])
        await query.answer()
        await edit_or_log(query, L.t("h.target_pick"), InlineKeyboardMarkup(grid), clan.alias)
        return
    if action == "pos":
        pos = parts[2]
        ours = sorted(war.get("members", {}).items(), key=lambda kv: kv[1].get("pos") or 99)
        buttons = [InlineKeyboardButton(f"#{m.get('pos')} {m['name'][:10]}", callback_data=f"t:set:{pos}:{m.get('pos')}") for tag, m in ours]
        grid = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
        grid.append([InlineKeyboardButton(L.t("h.btn_free"), callback_data=f"t:set:{pos}:0"),
                     InlineKeyboardButton(L.t("h.btn_targets"), callback_data="v:targets")])
        defender = next((d for d in war.get("defenders", {}).values() if str(d.get("pos")) == pos), {})
        await query.answer()
        await edit_or_log(query, L.t("h.target_who", pos=pos, name=render.esc(defender.get("name"))), InlineKeyboardMarkup(grid), clan.alias)
        return
    if action == "set":
        pos, ourpos = parts[2], parts[3]
        plan = assign(plan, pos, member_at(war, ourpos) if ourpos != "0" else None)
        await store.set_state(clan.alias, "plan", {"war": war_key(war), "targets": plan})
        await query.answer(L.t("h.target_set") if ourpos != "0" else L.t("h.target_free"))
    elif action == "mirror":
        plan = mirror_plan(war)
        await store.set_state(clan.alias, "plan", {"war": war_key(war), "targets": plan})
        await query.answer(L.t("h.target_mirror"))
    elif action == "clear":
        plan = {}
        await store.del_state(clan.alias, "plan")
        await query.answer(L.t("h.target_clear"))
    else:
        await query.answer()
    by = actor(update)
    if by and action in TARGET_ACTIONS:
        await ledger.acted(store, clan.alias, "target", parts[2] if action == "set" else action,
                           by.id, getattr(by, "first_name", None), now=now_utc())
    await edit_or_log(query, render.targets_view(L, plan_rows(war, plan), war, kind, day),
                      targets_keyboard(L, True, await app_url(store, clan)), clan.alias)


async def on_cwl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, _ = await view_locale(update, context, clan)
    parts = query.data.split(":")
    cwl = await store.get_state(clan.alias, "cwl") or {}
    state = cwl_roster.for_season(await store.get_state(clan.alias, "cwl_roster"), cwl.get("season"))
    if parts[1] == "av":
        user = update.effective_user
        reg = cwl_roster.registered(cwl, clan.tag)
        links = await store.links_by_user(user.id) if user else []
        tags = [link.tag for link in links if link.tag in reg]
        if not tags:
            await query.answer(L.t("cwl.roster.not_registered"), show_alert=True)
            return
        for tag in tags:
            cwl_roster.declare(state, tag, parts[2], user.id, now_utc().timestamp())
        await store.set_state(clan.alias, "cwl_roster", state)
        await query.answer(L.t("cwl.roster.declared"))
        text, keyboard = await build_view("cwl:roster", clan, context, update)
        await edit_or_log(query, text, keyboard, clan.alias)
        return
    if parts[1] == "b":
        if not await can_manage(update, context, clan):
            await query.answer(L.t("h.admin_only"), show_alert=True)
            return
        tag = ":".join(parts[2:])
        cwl_bonus.toggle(state, tag)
        await store.set_state(clan.alias, "cwl_roster", state)
        await cwl_bonus.sync_season(store, clan.alias, cwl.get("season"), state.get("bonus"))
        await query.answer(L.t("cwl.bonus.marked" if tag in state["bonus"] else "cwl.bonus.unmarked"))
        text, keyboard = await build_view("cwl:bonus", clan, context, update)
        await edit_or_log(query, text, keyboard, clan.alias)
        return
    await query.answer()


async def on_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        await edit_or_log(query, render.not_linked_view(user_locale(update)), None, "?")
        return
    L, _ = await view_locale(update, context, clan)
    by = actor(update)
    if not by:
        await query.answer(L.t("h.anonymous"), show_alert=True)
        return
    if await guard.suspended(store, clan.alias, by.id):
        await query.answer(L.t(guard.REFUSAL), show_alert=True)
        return
    if not await can_manage(update, context, clan):
        await query.answer(L.t("h.admin_only"), show_alert=True)
        return
    data = query.data or ""
    parts = data.split(":")
    mine = setup_ui.code_of(data) == clan.alias
    opening = "web" if mine and len(parts) > 2 and parts[2] == "web" else None
    state = await settings_state(update, context, store, clan,
                                 opening or remembered_step(context, clan.alias))
    step, alert, saved, braked = state["step"], None, False, False
    if mine:
        before = step
        state, step = setup_ui.handle(state, data)
        was, doc, saved = await save_settings_state(store, clan, state)
        if saved:
            kind, ref = ledger.pressed(data)
            await ledger.acted(store, clan.alias, kind, ref, by.id,
                               getattr(by, "first_name", None), now=now_utc())
            _, braked = await brake.wizard(store, clan.alias, by.id, context, was, doc, now_utc())
        if not private_chat(update):
            L = i18n.locale(settings_mod.effective(doc, None)["lang"])
        if step == "mentions" and before == "mentions" and state.get("mentions") not in settings_mod.MENTIONS:
            alert = L.t("setup.mentions.required")
    if braked:
        alert = L.t(guard.NOTICE)
    remember_step(context, clan.alias, step)
    await query.answer(alert or (L.t("settings.saved") if saved else None), show_alert=alert is not None)
    state = await with_candidates(store, clan, state, step)
    text, keyboard = setup_ui.screen(L, state, step)
    await edit_or_log(query, text, keyboard, clan.alias)


async def open_settings(update, context, store, clan, L, step):
    brake.reopen(context, clan.alias)
    remember_step(context, clan.alias, step)
    state = await with_candidates(store, clan, await settings_state(update, context, store, clan, step), step)
    text, keyboard = setup_ui.screen(L, state, step)
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def cmd_lazy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    records = await store.recent_wars(clan.alias, 10)
    await update.effective_message.reply_text(render.lazy_view(L, member_stats(records), len(records)))


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    await open_settings(update, context, store, clan, L, setup_ui.STEPS[0])


async def cmd_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    store, coc = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    await update.effective_message.reply_text(
        render.card("🎨", L.t("stickers.title"), L.t("stickers.making")))
    clan_json, _ = await coc.clan(clan.tag)
    made = await stickers.build(context.bot, store.vault, clan, clan_json,
                                update.effective_user.id, clan.name,
                                f"{clan.name} · {L.t('stickers.emoji.title')}")
    if not made:
        await update.effective_message.reply_text(
            render.card("🎨", L.t("stickers.title"), L.t("stickers.failed")))
        return
    await store.set_state(clan.alias, stickers.STATE, made)
    await store.set_state(clan.alias, stickers.QUEUE, {"set": made["set"]})
    done = (L.t("stickers.done", set=made["set"], emoji=made["emoji"]) if made["emoji"]
            else L.t("stickers.done_no_emoji", set=made["set"]))
    await update.effective_message.reply_text(
        render.card("🎨", L.t("stickers.title"), done + "\n" + L.t("stickers.owner")))


async def cmd_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    if not await topics.can_open(context.bot, clan.chat_id):
        await update.effective_message.reply_text(L.t("topics.not_forum"))
        return
    conf = await clan_settings(store, clan)
    await update.effective_message.reply_text(topics.card(L, conf),
                                              reply_markup=topics.keyboard(L, conf))


async def on_topics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, _ = await view_locale(update, context, clan)
    if not actor(update):
        await query.answer(L.t("h.anonymous"), show_alert=True)
        return
    if not await can_manage(update, context, clan):
        await query.answer(L.t("h.admin_only"), show_alert=True)
        return
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    conf = await clan_settings(store, clan)
    if action == "no":
        await query.answer(L.t("topics.later"))
        await edit_or_log(query, topics.card(L, conf), None, clan.alias)
        return
    wanted = topics.missing(conf) if action == "all" else tuple(
        pack for pack in parts[2:3] if pack in topics.missing(conf))
    opened = dict(topics.saved(conf))
    for pack in wanted:
        thread = await topics.open_topic(context.bot, clan.chat_id, L, pack)
        if thread:
            opened[pack] = thread
    if opened != topics.saved(conf):
        await save_settings(store, clan, {"topics": opened}, actor(update))
        conf = await clan_settings(store, clan)
        await query.answer(L.t("topics.done"))
    else:
        await query.answer(L.t("topics.failed"))
    await edit_or_log(query, topics.card(L, conf), topics.keyboard(L, conf), clan.alias)


async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    if not context.args:
        await open_settings(update, context, store, clan, L, "locale")
        return
    code = parse_lang(context.args[0])
    if not code:
        await update.effective_message.reply_text(L.t("lang.unknown"))
        return
    await save_settings(store, clan, {"lang": code}, actor(update))
    new = i18n.locale(code)
    await update.effective_message.reply_text(new.t("lang.set", lang=i18n.LANGUAGES[code]))


async def cmd_tz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    conf = await clan_settings(store, clan)
    if not context.args:
        await update.effective_message.reply_text(L.t("tz.usage", tz=render.esc(conf.get("tz"))))
        return
    zone = known_zone(context.args[0])
    if not zone:
        await update.effective_message.reply_text(L.t("tz.unknown"))
        return
    await save_settings(store, clan, {"tz": zone}, actor(update))
    await update.effective_message.reply_text(L.t("tz.set", tz=render.esc(zone)))


async def cmd_mine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    user = update.effective_user
    if not clan or not user:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    links = await store.links_by_user(user.id)
    if not links:
        await media.reply(update.effective_message, store, render.not_linked_me(L, context.bot.username))
        return
    war, kind, day = await active_war(store, clan)
    if not war:
        await update.effective_message.reply_text(render.targets_view(L, [], None))
        return
    plan = await current_plan(store, clan, war)
    rows = plan_rows(war, plan)
    positions = []
    for link in links:
        positions += targets_for(plan, link.tag)
    await update.effective_message.reply_text(render.my_targets_view(L, links[0].name, rows, positions))


async def served_elsewhere(update, context, tag):
    store, _ = services(context)
    alias = bot_alias(context)
    if not alias or await is_platform_owner(update, context):
        return False
    found = await store.bot_for_tag(tag)
    return bool(found) and found != alias


async def link_clan(update, context, chat, tag, user_id, setup=None, reply=None, note=None):
    store, coc = services(context)
    alias = bot_alias(context)
    reply = reply or update.effective_message.reply_text
    if await served_elsewhere(update, context, tag):
        await reply(user_locale(update).t("console.newbot_clan_taken"))
        return None
    platform = await is_platform_owner(update, context)
    if alias and not await store.clan_by_chat(chat.id, alias) and not platform:
        if await store.count_clans(alias) >= CLAN_LIMIT:
            await reply(user_locale(update).t("h.clan_limit", n=CLAN_LIMIT))
            return None
    data, error = await coc.clan(tag)
    if not data:
        await reply(render.api_error(user_locale(update), error, tag))
        return None
    if not platform and not await verify.linked_leader(store, user_id, verify.clan_roles(data)):
        await reply(user_locale(update).t("h.onboard_not_leader", clan=render.esc(data.get("name") or tag)))
        return None
    clan = await store.add_clan(chat.id, tag, data.get("name"), user_id, alias)
    await store.set_state(clan.alias, "members", member_snapshot(data))
    if alias and await store.count_clans(alias) == 1:
        row = await ambassadors.credit(store, user_id)
        if row:
            await ambassadors.reward(store, row)
    if setup:
        await save_settings(store, clan, setup_ui.to_settings(setup), keep_prev=False)
    conf = settings_mod.effective(await store.get_state(clan.alias, "settings"), data)
    if not setup and (data.get("location") or {}).get("countryCode"):
        await save_settings(store, clan, {"lang": conf["lang"], "tz": conf["tz"]},
                            keep_prev=False)
    L = i18n.locale(conf["lang"])
    log.info("%s: clan collegato", clan.alias)
    await ledger.record(store, clan.alias, "link", user_id, None, clan.name)
    if note:
        await reply(L.t(note))
    await reply(render.linked_view(L, clan, data), reply_markup=menu_keyboard(L))
    if not conf["setup_done"]:
        await reply(L.t("setup.needed"))
    elif setup:
        await reply(L.t("setup.applied"))
    owner = await owner_id(context)
    if owner and str(user_id) != owner:
        await manager_alerts.from_console(
            store, context.bot_data.get("supervisor"),
            L.t("h.new_clan_notice", name=render.esc(clan.name), alias=render.esc(clan.alias)))
    return clan


def help_keyboard(L, context, offered, picked=None):
    rows = [[InlineKeyboardButton(("✓ " if name == picked else "") + render.help_area_title(L, name),
                                  callback_data=f"h:{name}")
             for name in offered[start:start + HELP_COLUMNS]]
            for start in range(0, len(offered), HELP_COLUMNS)]
    rows.append([InlineKeyboardButton(L.t("h.btn_onboard"), callback_data="ob:start")])
    rows.append([InlineKeyboardButton(L.t("h.btn_link"), callback_data="ob:link")])
    return share.with_button(L, InlineKeyboardMarkup(rows), share.console_of(context))


async def send_help_private(update, context):
    user = update.effective_user
    L = user_locale(update)
    text, offered = render.help_view(L, COMMANDS_BY_AREA, user.id if user else None)
    await update.effective_message.reply_text(
        text, reply_markup=help_keyboard(L, context, offered))


async def on_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    area = query.data.split(":", 1)[1]
    user = update.effective_user
    L = user_locale(update)
    text, offered = render.help_view(L, COMMANDS_BY_AREA, user.id if user else None, area=area)
    await query.answer()
    await edit_or_log(query, text, help_keyboard(L, context, offered, area), "help")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        if await gate(update, context):
            await send_help_private(update, context)
        return
    await show(update, context, "menu")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    store, _ = services(context)
    if chat.type == ChatType.PRIVATE:
        arg = context.args[0] if context.args else ""
        if arg in START_LINK:
            await cmd_link(update, context)
            return
        if await gate(update, context, START_ACTION if arg in START_NEWCLAN else None) is None:
            return
        if arg in START_NEWCLAN:
            await cmd_newclan(update, context)
            return
        if arg in START_SUPPORT:
            await cmd_support(update, context)
            return
        if arg.split("_")[0] == recruit_tools.START_APPLY:
            await recruit_tools.cmd_apply(update, context, code=arg.partition("_")[2] or None)
            return
        clan = await clan_for(update, context)
        if clan:
            await show(update, context, "menu")
            return
        await send_help_private(update, context)
        return
    if context.args and chat.type in GROUPS:
        pending = await store.kv_get(f"ob:{context.args[0]}")
        if pending and pending.get("bot_alias", bot_alias(context)) == bot_alias(context):
            clan = await link_clan(update, context, chat, pending["tag"], pending.get("user_id"),
                                   pending.get("setup"))
            if clan:
                await store.kv_del(f"ob:{context.args[0]}")
            return
    await show(update, context, "menu")


async def cmd_setclan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    _, L, _ = await chat_locale(update, context)
    here = await one_group.elsewhere(store, bot_alias(context), update.effective_chat.id)
    await update.effective_message.reply_text(L.t(one_group.REFUSAL if here else "h.setclan_usage"))


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    alias = bot_alias(context)
    clan = await clan_for(update, context)
    if not clan and await is_owner(update, context):
        clan = await one_group.elsewhere(store, alias, update.effective_chat.id)
    if not clan:
        await update.effective_message.reply_text(user_locale(update).t("h.removed_none"))
        return
    L, _ = await view_locale(update, context, clan)
    if not await is_owner(update, context):
        user = update.effective_user
        members = await store.get_state(clan.alias, "members")
        if not user or not (await user_roles(store, user.id, members) & LEADER_ROLES):
            await update.effective_message.reply_text(L.t("h.owner_only"))
            return
    await store.remove_clan(clan.chat_id, alias)
    await update.effective_message.reply_text(L.t("h.unlinked"))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, coc = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, tz = await view_locale(update, context, clan)
    _, error = await coc.check()
    ip = await public_ip() if error == "invalid_ip" else None
    text = render.status_view(L, tz, clan, error is None, error, ip, now_utc())
    if await is_platform_owner(update, context):
        counts = await store.counts()
        text += "\n\n" + L.t("h.status_owner", active=counts["active"], total=counts["total"])
    await update.effective_message.reply_text(text)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    store, coc = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    war, error = await coc.current_war(clan.tag)
    private = True if error == "private" else (False if war else None)
    conf = await clan_settings(store, clan)
    results = await diagnostics.inspect(context.bot, clan.chat_id, conf, private)
    await update.effective_message.reply_text(render.check_view(L, results))


async def cmd_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    L = user_locale(update)
    if update.effective_chat.type != ChatType.PRIVATE:
        store, _ = services(context)
        _, L, _ = await chat_locale(update, context)
        await media.reply(update.effective_message, store, L.t("h.link_private", bot=context.bot.username))
        return
    await support_desk.open_flow(update, update.effective_message, context, "link")


async def cmd_newclan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    L = user_locale(update)
    if update.effective_chat.type != ChatType.PRIVATE:
        store, _ = services(context)
        _, L, _ = await chat_locale(update, context)
        await media.reply(update.effective_message, store, L.t("h.newclan_private", bot=context.bot.username))
        return
    await support_desk.open_flow(update, update.effective_message, context, "onboard")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    if context.user_data.pop("flow", None):
        await update.effective_message.reply_text(user_locale(update).t("h.cancelled"))


async def on_onboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "ob:link":
        await support_desk.open_flow(update, query.message, context, "link")
        return
    if query.data != "ob:start" or await gate(update, context, START_ACTION) is None:
        return
    await support_desk.open_flow(update, query.message, context, "onboard")


async def finish_onboard(update, context, flow):
    store, _ = services(context)
    user = update.effective_user
    L = user_locale(update)
    code = pysecrets.token_urlsafe(12)
    await store.kv_set(f"ob:{code}", {"tag": flow["clan_tag"], "name": flow["clan_name"], "user_id": user.id,
                                      "bot_alias": bot_alias(context)}, ttl=86400)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
        L.t("h.btn_add_group"), url=f"https://t.me/{context.bot.username}?startgroup={code}"
    )]])
    context.user_data.pop("flow", None)
    await update.effective_message.reply_text(render.onboard_ready(L, flow["clan_name"], flow["clan_tag"]), reply_markup=keyboard)


async def on_link_text(update, context, flow, text):
    store, coc = services(context)
    user = update.effective_user
    L = user_locale(update)
    reply = update.effective_message.reply_text
    if flow["step"] == "tag":
        tag = normalize_tag(text)
        if not tag:
            await reply(L.t("h.tag_invalid"))
            return
        data, error = await coc.player(tag)
        if not data:
            await reply(render.api_error(L, error, tag))
            return
        flow.update(step="token", tag=tag, name=data.get("name"))
        await reply(render.link_ask_token(L, flow["name"], tag))
        return
    who = linking.Who(user.id, parse_lang(user.language_code))
    _, error = await linking.link_player(store, coc, who, flow["tag"], flow["name"], text, now_utc())
    if error == reasons.TERMS:
        flow["step"] = verify.TERMS
        await support_desk.remind_terms(update, context)
        return
    if error:
        await reply(link_fault(L, error, flow))
        return
    context.user_data.pop("flow", None)
    await reply(render.link_done(L, flow["name"], flow["tag"]))


def link_fault(L, error, flow):
    if error == linking.BAD_TOKEN:
        return L.t("h.token_invalid")
    if error == linking.TAKEN:
        return L.t(linking.NOTES[error], name=render.esc(flow["name"]))
    if error == reasons.BANNED:
        return L.t("h.link_banned")
    return render.api_error(L, error, flow["tag"])


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    flow = context.user_data.get("flow")
    if not flow or "kind" not in flow:
        return
    if flow["kind"] == leader_tools.FLOW:
        await leader_tools.on_text(update, context, flow)
        return
    if flow["kind"] == "apply":
        await recruit_tools.on_text(update, context, flow)
        return
    if flow["kind"] == "discord":
        await integration_tools.on_token(update, context, flow)
        return
    if flow.get("step") == verify.TERMS:
        await support_desk.remind_terms(update, context)
        return
    text = (update.effective_message.text or "").strip()
    if flow["kind"] == "link":
        await on_link_text(update, context, flow, text)
        return
    if flow["kind"] == "feedback":
        await support_desk.on_text(update, context, flow)
        return
    if flow["kind"] == "famnotice":
        await on_family_notice_text(update, context, flow, text)
        return
    if flow["kind"] == "onboard":
        await on_onboard_text(update, context, flow, text)


async def on_family_notice_text(update, context, flow, text):
    store, _ = services(context)
    L = user_locale(update)
    reply = update.effective_message.reply_text
    family = await store.family_by_alias(flow["family"])
    if not family or not await family_allowed(update, context, family):
        context.user_data.pop("flow", None)
        await reply(L.t("h.family_owner_only"))
        return
    if not text:
        await reply(L.t("family.message.ask", n=familyroom.MESSAGE_MAX))
        return
    last = await store.kv_get(f"fam:{family.alias}:message") or {}
    if now_utc().timestamp() - float(last.get("ts") or 0) < familyroom.MESSAGE_EVERY:
        context.user_data.pop("flow", None)
        await reply(L.t("family.message.too_soon"))
        return
    flow["text"] = text[:familyroom.MESSAGE_MAX]
    clans = await store.family_clans(family.alias)
    await reply(familyroom.preview_card(L, family, flow["text"], len(clans)),
                reply_markup=familyroom.preview_keyboard(L))


async def on_onboard_text(update, context, flow, text):
    if await gate(update, context, START_ACTION) is None:
        context.user_data.pop("flow", None)
        return
    if flow["step"] == "clan":
        await onboard_clan_text(update, context, flow, text)
        return
    if flow["step"] == "player":
        await onboard_player_text(update, context, flow, text)
        return
    await onboard_token_text(update, context, flow, text)


async def onboard_clan_text(update, context, flow, text):
    store, coc = services(context)
    L = user_locale(update)
    reply = update.effective_message.reply_text
    tag = normalize_tag(text)
    if not tag:
        await reply(L.t("h.tag_invalid"))
        return
    data, error = await coc.clan(tag)
    if not data:
        await reply(render.api_error(L, error, tag))
        return
    if await served_elsewhere(update, context, tag):
        context.user_data.pop("flow", None)
        await reply(L.t("console.newbot_clan_taken"))
        return
    roles = verify.clan_roles(data)
    flow.update(clan_tag=tag, clan_name=data.get("name"), roles=roles)
    if await verify.linked_leader(store, update.effective_user.id, roles):
        await finish_onboard(update, context, flow)
        return
    flow["step"] = "player"
    await reply(render.onboard_ask_player(L, flow["clan_name"]))


async def onboard_player_text(update, context, flow, text):
    _, coc = services(context)
    L = user_locale(update)
    reply = update.effective_message.reply_text
    player, error = await verify.check_player(coc, flow["roles"], text)
    if error == "not_leader":
        await reply(L.t("h.onboard_not_leader", clan=render.esc(flow["clan_name"])))
        return
    if error:
        await reply(render.api_error(L, error, normalize_tag(text)))
        return
    flow.update(step="token", player=player["tag"], name=player["name"])
    await reply(render.onboard_ask_token(L, flow["name"]))


async def onboard_token_text(update, context, flow, text):
    store, coc = services(context)
    L = user_locale(update)
    user = update.effective_user
    reply = update.effective_message.reply_text
    error = await verify.check_token(coc, flow["player"], text)
    if error == "token_invalid":
        await reply(L.t("h.token_invalid"))
        return
    if error:
        await reply(render.api_error(L, error, flow["player"]))
        return
    refused = await verify.link_verified(store, user.id, flow["player"], flow["name"],
                                         parse_lang(user.language_code))
    if refused == reasons.TERMS:
        flow["step"] = verify.TERMS
        await support_desk.remind_terms(update, context)
        return
    if refused:
        await reply(L.t("h.link_banned"))
        return
    await finish_onboard(update, context, flow)


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    store, coc = services(context)
    _, L, _ = await chat_locale(update, context)
    user = actor(update)
    links = await store.links_by_user(user.id) if user else []
    if not links:
        await media.reply(update.effective_message, store, render.not_linked_me(L, context.bot.username))
        return
    await remember_language(store, update, links)
    snapshots = {}
    clans = {}
    badges_of = {}
    for link in links[:ME_ACCOUNTS]:
        data, _ = await coc.player(link.tag)
        if data:
            snapshots[link.tag] = player_snapshot(data)
            clan = data.get("clan") or {}
            clans[link.tag] = clan.get("name")
            badges_of[link.tag] = (clan.get("badgeUrls") or {}).get("medium")
    text = render.me_view(L, links, snapshots)
    first = links[0]
    if snapshots.get(first.tag):
        spec = cards.build_player(L, snapshots[first.tag], first.tag, clans.get(first.tag),
                                  await media.site_base(store))
        try:
            if await media.card_reply(update.effective_message, store, bot_alias(context), spec,
                                      badges_of.get(first.tag), text):
                return
        except Exception:
            log.exception("card del giocatore non disegnata")
    await update.effective_message.reply_text(text)


async def cmd_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, coc = services(context)
    _, L, _ = await chat_locale(update, context)
    tag = normalize_tag(" ".join(context.args)) if context.args else None
    if not tag:
        await update.effective_message.reply_text(L.t("player.usage"))
        return
    data, error = await coc.player(tag)
    if not data:
        await update.effective_message.reply_text(render.api_error(L, error, tag))
        return
    await update.effective_message.reply_text(render.player_card(L, player_snapshot(data), tag))


async def two_players(update, context, L):
    store, coc = services(context)
    tags = [normalize_tag(arg) for arg in (context.args or [])]
    tags = [tag for tag in tags if tag]
    if len(tags) == 1:
        user = actor(update)
        links = await store.links_by_user(user.id) if user else []
        if not links:
            await update.effective_message.reply_text(L.t("vs.not_linked", bot=context.bot.username))
            return None
        tags = [links[0].tag, tags[0]]
    if len(tags) != 2:
        await update.effective_message.reply_text(L.t("vs.usage"))
        return None
    snapshots = []
    for tag in tags:
        data, error = await coc.player(tag)
        if not data:
            await update.effective_message.reply_text(render.api_error(L, error, tag))
            return None
        snapshots.append(player_snapshot(data))
    return snapshots


async def cmd_vs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, L, _ = await chat_locale(update, context)
    pair = await two_players(update, context, L)
    if not pair:
        return
    left, right = pair
    rows = compare.compare(compare.PLAYER_FIELDS, compare.player_values(left),
                           compare.player_values(right))
    await update.effective_message.reply_text(
        render.vs_card(L, L.t("vs.title"), left.get("name"), right.get("name"), rows,
                       left.get("labels"), right.get("labels")))


async def cmd_clanvs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, coc = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await clan_locale(store, clan)
    tag = normalize_tag(" ".join(context.args)) if context.args else None
    if not tag:
        await update.effective_message.reply_text(L.t("clanvs.usage"))
        return
    pair = []
    for wanted in (clan.tag, tag):
        data, error = await coc.clan(wanted)
        if not data:
            await update.effective_message.reply_text(render.api_error(L, error, wanted))
            return
        pair.append(data)
    rows = compare.compare(compare.CLAN_FIELDS, compare.clan_values(pair[0]),
                           compare.clan_values(pair[1]))
    await update.effective_message.reply_text(
        render.vs_card(L, L.t("clanvs.title"), pair[0].get("name"), pair[1].get("name"), rows))


def me_keyboard(L, links, roster, extra=None):
    rows = [
        [InlineKeyboardButton(
            L.t("me.anniv_off" if roster_mod.optout(roster, link.tag) else "me.anniv_on", name=link.name),
            callback_data=f"m:a:{index}")]
        for index, link in enumerate(links[:ME_ACCOUNTS])
    ]
    rows.extend(extra or [])
    return back_keyboard(L, "me", rows)


async def on_me_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    user = actor(update)
    links = (await store.links_by_user(user.id))[:ME_ACCOUNTS] if user else []
    parts = (query.data or "").split(":")
    index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else -1
    if not clan or not 0 <= index < len(links):
        await query.answer()
        return
    L, _ = await view_locale(update, context, clan)
    state = await store.get_state(clan.alias, "roster") or {}
    tag = links[index].tag
    state = roster_mod.set_optout(state, tag, not roster_mod.optout(state, tag))
    await store.set_state(clan.alias, "roster", state)
    await query.answer(L.t("me.anniv_saved"))
    text, _ = await build_view("me", clan, context, update)
    await edit_or_log(query, text, me_keyboard(L, links, state), clan.alias)


def goal_accounts(links, members):
    known = members if isinstance(members, dict) else {}
    return [link for link in (links or []) if link.tag in known][:ME_ACCOUNTS]


def goal_account_keyboard(L, accounts):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(L.t("goal.account", name=link.name), callback_data=f"g:a:{slot}")]
        for slot, link in enumerate(accounts)
    ])


def goal_kind_keyboard(L, slot, kinds, has_goal, many):
    rows = [[InlineKeyboardButton(L.t(f"goal.kind.{kind}"), callback_data=f"g:k:{slot}:{index}")]
            for index, kind in enumerate(kinds)]
    if has_goal:
        rows.append([InlineKeyboardButton(L.t("goal.clear"), callback_data=f"g:x:{slot}")])
    if many:
        rows.append([InlineKeyboardButton(L.t("goal.other_account"), callback_data="g:a")])
    return InlineKeyboardMarkup(rows)


def goal_target_keyboard(L, slot, kind_index, picks):
    rows = [[InlineKeyboardButton(str(pick["target"]), callback_data=f"g:t:{slot}:{kind_index}:{index}")]
            for index, pick in enumerate(picks)]
    rows.append([InlineKeyboardButton(L.t("menu.back"), callback_data=f"g:b:{slot}")])
    return InlineKeyboardMarkup(rows)


async def goal_context(update, context, clan, slot=None):
    store, coc = services(context)
    user = actor(update)
    links = await store.links_by_user(user.id) if user else []
    members = await store.get_state(clan.alias, "members") or {}
    accounts = goal_accounts(links, members)
    if not accounts or slot is None or not 0 <= slot < len(accounts):
        return accounts, None, None
    data, _ = await coc.player(accounts[slot].tag)
    return accounts, accounts[slot], player_snapshot(data) if data else None


async def goal_slot_view(update, context, clan, L, slot):
    store, _ = services(context)
    accounts, link, snapshot = await goal_context(update, context, clan, slot)
    if not link or not snapshot:
        return None, None
    stored = (await store.get_state(clan.alias, "goals") or {}).get(link.tag)
    return (render.goal_card(L, link.name, stored, goals.current(snapshot, stored)),
            goal_kind_keyboard(L, slot, goals.kinds_for(snapshot), bool(stored), len(accounts) > 1))


async def cmd_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await clan_locale(store, clan)
    accounts, _, _ = await goal_context(update, context, clan)
    if not accounts:
        await update.effective_message.reply_text(render.goal_not_member(L))
        return
    if len(accounts) > 1:
        await update.effective_message.reply_text(
            render.card("🎯", L.t("goal.title"), L.t("goal.choose_account")),
            reply_markup=goal_account_keyboard(L, accounts))
        return
    text, keyboard = await goal_slot_view(update, context, clan, L, 0)
    if not text:
        await update.effective_message.reply_text(render.api_error(L, None, accounts[0].tag))
        return
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def on_goal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, _ = await clan_locale(store, clan)
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    slot = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    accounts, link, snapshot = await goal_context(update, context, clan, slot)
    if not accounts:
        await query.answer()
        await edit_or_log(query, render.goal_not_member(L), None, clan.alias)
        return
    if not link:
        await query.answer()
        await edit_or_log(query, render.card("🎯", L.t("goal.title"), L.t("goal.choose_account")),
                          goal_account_keyboard(L, accounts), clan.alias)
        return
    if not snapshot:
        await query.answer(render.api_error(L, None, link.tag), show_alert=True)
        return
    stored = await store.get_state(clan.alias, "goals") or {}
    kinds = goals.kinds_for(snapshot)
    many = len(accounts) > 1
    if action == "x":
        stored.pop(link.tag, None)
        await store.set_state(clan.alias, "goals", stored)
        await query.answer(L.t("goal.cleared"))
        await edit_or_log(query, render.goal_card(L, link.name, None, 0),
                          goal_kind_keyboard(L, slot, kinds, False, many), clan.alias)
        return
    if action in ("k", "t"):
        index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else -1
        if not 0 <= index < len(kinds):
            await query.answer()
            return
        picks = goals.choices(snapshot, kinds[index])
        if action == "k":
            await query.answer()
            await edit_or_log(query, render.card("🎯", L.t("goal.title"), L.t("goal.choose_target")),
                              goal_target_keyboard(L, slot, index, picks), clan.alias)
            return
        choice = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else -1
        if not 0 <= choice < len(picks):
            await query.answer()
            return
        goal = {"kind": kinds[index], "hero": picks[choice]["hero"], "target": picks[choice]["target"]}
        stored[link.tag] = goal
        await store.set_state(clan.alias, "goals", stored)
        await query.answer(L.t("goal.saved"))
        await edit_or_log(query, render.goal_card(L, link.name, goal, goals.current(snapshot, goal)),
                          goal_kind_keyboard(L, slot, kinds, True, many), clan.alias)
        return
    await query.answer()
    current_goal = stored.get(link.tag)
    await edit_or_log(query, render.goal_card(L, link.name, current_goal,
                                              goals.current(snapshot, current_goal)),
                      goal_kind_keyboard(L, slot, kinds, bool(current_goal), many), clan.alias)


def unlink_keyboard(links):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{link.name} · {link.tag}", callback_data=f"u:{link.tag}")] for link in links
    ])


def unlink_confirm_keyboard(L, tag):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("unlink.btn_confirm"), callback_data=f"u:{tag}:yes"),
        InlineKeyboardButton(L.t("console.btn_cancel"), callback_data=f"u:{tag}:no"),
    ]])


def unlink_done(L, link):
    return render.card("🔓", L.t("unlink.title"), L.t("unlink.done", name=render.esc(link.name), tag=render.esc(link.tag)))


async def drop_link(store, user_id, link):
    return await privacy.drop_link(store, user_id, link)


async def cmd_unlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await refuse_anonymous(update, context):
        return
    store, _ = services(context)
    _, L, _ = await chat_locale(update, context)
    user = actor(update)
    reply = update.effective_message.reply_text
    links = await store.links_by_user(user.id) if user else []
    if not links:
        await media.reply(update.effective_message, store, render.not_linked_me(L, context.bot.username))
        return
    await remember_language(store, update, links)
    if context.args:
        tag = normalize_tag(" ".join(context.args))
        link = next((l for l in links if l.tag == tag), None)
        if not link or not await drop_link(store, user.id, link):
            await reply(L.t("unlink.not_yours"))
            return
        await reply(unlink_done(L, link))
        return
    await reply(render.card("🔓", L.t("unlink.title"), L.t("unlink.choose")), reply_markup=unlink_keyboard(links))


async def on_unlink_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    _, L, _ = await chat_locale(update, context)
    user = actor(update)
    if not user:
        await query.answer(L.t("h.anonymous"), show_alert=True)
        return
    parts = (query.data or "").split(":")
    tag = parts[1] if len(parts) > 1 else ""
    action = parts[2] if len(parts) > 2 else ""
    links = await store.links_by_user(user.id)
    await remember_language(store, update, links)
    link = next((l for l in links if l.tag == tag), None)
    if not link:
        await query.answer(L.t("unlink.not_yours"), show_alert=True)
        return
    if action == "yes":
        if not await drop_link(store, user.id, link):
            await query.answer(L.t("unlink.not_yours"), show_alert=True)
            return
        await query.answer()
        await edit_or_log(query, unlink_done(L, link), None, "unlink")
        return
    await query.answer()
    if action == "no":
        await edit_or_log(query, L.t("h.cancelled"), None, "unlink")
        return
    body = L.t("unlink.confirm", name=render.esc(link.name), tag=render.esc(link.tag))
    await edit_or_log(query, render.card("🔓", L.t("unlink.title"), body), unlink_confirm_keyboard(L, link.tag), "unlink")


async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan, L, _ = await chat_locale(update, context)
    url = await store.get_secret("support_url")
    code = await store.get_secret("creator_code")
    twitch = await store.get_secret("twitch_url")
    where = await store.get_secret(source_mod.SECRET)
    channel = await store.get_secret("channel_url")
    if update.effective_chat.type == ChatType.PRIVATE:
        keyboard = support_cards.tip_keyboard(L, tips.AMOUNTS)
    else:
        keyboard = support_cards.tip_link_keyboard(L, context.bot.username)
    keyboard = share.with_button(L, keyboard, share.console_of(context))
    text = render.support_card(L, url, code, twitch, where, channel)
    if clan:
        text += integration_cards.support_extra(L, await clan_settings(store, clan))
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def cmd_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await view_locale(update, context, clan)
    stored = await store.get_state(clan.alias, "settings") or {}
    if not context.args:
        current = L.t("h.requirements_th", th=stored["min_th"]) if stored.get("min_th") else L.t("h.requirements_none")
        note = L.t("h.requirements_note", note=render.esc(stored["note"])) if stored.get("note") else ""
        await update.effective_message.reply_text(
            L.t("h.requirements_current", current=current) + note + "\n" + L.t("h.requirements_hint")
        )
        return
    if not await can_manage(update, context, clan):
        await update.effective_message.reply_text(L.t("h.admin_only"))
        return
    try:
        min_th = int(context.args[0].upper().replace("TH", ""))
    except ValueError:
        await update.effective_message.reply_text(L.t("h.requirements_usage"))
        return
    note = " ".join(context.args[1:])[:80]
    await save_settings(store, clan, {"min_th": min_th, "note": note}, actor(update))
    await update.effective_message.reply_text(
        L.t("h.requirements_set", th=min_th) + (L.t("h.requirements_note", note=render.esc(note)) if note else "")
    )


async def family_of_bot(store, context, alias):
    family = await store.family_by_alias(alias)
    if family and family.bot_alias != bot_alias(context):
        return None
    return family


async def family_allowed(update, context, family):
    if await is_owner(update, context):
        return True
    user = update.effective_user
    return bool(user and family and user.id == family.owner_id)


async def cmd_family(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    chat = update.effective_chat
    user = update.effective_user
    clan, L, _ = await chat_locale(update, context)
    if chat.type == ChatType.PRIVATE:
        clan = None
    args = context.args or []
    sub = args[0].lower() if args else ""
    reply = update.effective_message.reply_text
    if sub in ("crea", "create"):
        name = " ".join(args[1:]).strip()[:40]
        if chat.type != ChatType.PRIVATE or not user:
            await reply(L.t("h.family_create_private"))
            return
        if not name:
            await reply(L.t("h.family_create_name"))
            return
        alias = await store.create_family(name, user.id, bot_alias(context))
        await reply(L.t("h.family_created", name=render.esc(name), alias=alias))
        return
    if sub in ("canale", "channel") and len(args) > 1:
        family = await family_of_bot(store, context, args[1])
        if not family:
            await reply(L.t("h.family_not_found"))
            return
        if chat.type != ChatType.CHANNEL and not await family_allowed(update, context, family):
            await reply(L.t("h.family_owner_only"))
            return
        family.chat_id = chat.id
        await store.save_family(family)
        await reply(L.t("h.family_channel_set", name=render.esc(family.name)))
        return
    if sub in ("aggiungi", "add") and len(args) > 1:
        family = await family_of_bot(store, context, args[1])
        if not family or not clan:
            await reply(L.t("h.family_add_usage"))
            return
        if not await family_allowed(update, context, family) and not await can_manage(update, context, clan):
            await reply(L.t("h.family_add_denied"))
            return
        await store.add_family_clan(family.alias, clan.alias)
        await reply(L.t("h.family_added", clan=render.esc(clan.name), family=render.esc(family.name)))
        return
    if sub in ("esci", "leave"):
        if not clan or not await can_manage(update, context, clan):
            await reply(L.t("h.family_leave_denied"))
            return
        removed = await store.remove_family_clan(clan.alias)
        await reply(L.t("h.family_left") if removed else L.t("h.family_leave_none"))
        return
    if sub in ("annuncio", "message"):
        if chat.type != ChatType.PRIVATE or not user:
            await reply(L.t("h.family_notice_private"))
            return
        families = [f for f in await store.families(bot_alias(context)) if f.owner_id == user.id]
        if not families:
            await reply(L.t("h.family_none_mine"))
            return
        context.user_data["flow"] = {"kind": "famnotice", "family": families[0].alias}
        await reply(L.t("family.message.ask", n=familyroom.MESSAGE_MAX))
        return
    if chat.type == ChatType.PRIVATE:
        families = [f for f in await store.families(bot_alias(context))
                    if user and (f.owner_id == user.id or await is_owner(update, context))]
        if not families:
            await reply(L.t("h.family_none_mine"))
            return
        for family in families:
            FL, _ = await family_locale(store, family, update)
            await reply(render.family_view(FL, family, await family_mod.rows(store, family), activity=await family_mod.activity_rows(store, family, "month")))
        return
    family = await store.family_of_clan(clan.alias) if clan else await store.family_by_chat(chat.id, bot_alias(context))
    if not family:
        await reply(L.t("h.family_none_clan"))
        return
    FL, _ = await family_locale(store, family, update)
    await reply(render.family_view(FL, family, await family_mod.rows(store, family), activity=await family_mod.activity_rows(store, family, "month")))


async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    if not answer or not answer.user:
        return
    store, _ = services(context)
    await polls.record_answer(store, answer)


async def on_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.poll:
        return
    store, _ = services(context)
    await survey.save(store, update.poll)


def group_reply(context, chat_id):
    async def reply(text, reply_markup=None):
        return await context.bot.send_message(chat_id, text, reply_markup=reply_markup)
    return reply


async def led_clans(store, coc, user):
    if not user:
        return {}
    led = {}
    for link in await store.links_by_user(user.id):
        if not link.verified:
            continue
        data, _ = await coc.player(link.tag)
        clan = (data or {}).get("clan") or {}
        if clan.get("tag") and (data or {}).get("role") in LEADER_ROLES:
            led[clan["tag"]] = clan.get("name")
    return led


async def auto_link(update, context, chat, user):
    store, coc = services(context)
    tags = await led_clans(store, coc, user)
    alias = bot_alias(context)
    free = [tag for tag in tags if await store.bot_for_tag(tag) in (None, alias)]
    if len(free) != 1:
        return None
    return await link_clan(update, context, chat, free[0], user.id,
                           reply=group_reply(context, chat.id), note="h.auto_linked")


async def move_here(update, context, chat, alias):
    store, coc = services(context)
    user = actor(update)
    moved = await one_group.move(store, alias, chat.id, user.id if user else None, context.bot, coc)
    if not moved:
        await one_group.step_out(context.bot, chat.id)
        return None
    clan = await store.clan_by_chat(chat.id, alias)
    await ledger.record(store, clan.alias if clan else alias, "link", user.id,
                        getattr(user, "first_name", None),
                        getattr(clan, "name", None), now_utc())
    log.info("clan spostato nel gruppo nuovo dal capo del gioco")
    return clan


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    change = update.my_chat_member
    if not change:
        return
    new_status = change.new_chat_member.status
    old_status = change.old_chat_member.status
    chat = change.chat
    store, _ = services(context)
    alias = bot_alias(context)
    if new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        if await store.remove_clan(chat.id, alias):
            log.info("bot rimosso da una chat, clan scollegato")
        return
    joined = old_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) and new_status in (
        ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.RESTRICTED
    )
    if joined and chat.type in GROUPS and not await store.clan_by_chat(chat.id, alias):
        if await one_group.elsewhere(store, alias, chat.id):
            await move_here(update, context, chat, alias)
            return
        try:
            if await auto_link(update, context, chat, actor(update)):
                return
        except Exception as e:
            log.warning("collegamento automatico non riuscito: %s", e)
        try:
            await context.bot.send_message(chat.id, render.not_linked_view(user_locale(update)))
        except Exception as e:
            log.warning("benvenuto non inviato: %s", e)


async def on_migrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.migrate_to_chat_id:
        return
    store, _ = services(context)
    if await store.move_clan(message.chat.id, message.migrate_to_chat_id, bot_alias(context)):
        log.info("chat migrata a supergruppo, clan aggiornato")


TOURNEY_SETUP = ("scope", "metric", "format", "size", "window", "new", "go", "cancel")


async def clan_tournaments(store, clan):
    family = await store.family_of_clan(clan.alias)
    docs = await store.tournaments_for(clan_alias=clan.alias)
    if family:
        docs += await store.tournaments_for(family_alias=family.alias)
    if tournaments.network_ready(await store.network_get(clan.alias)):
        docs += await store.tournaments_for(scope="network", status="signup")
    seen, out = set(), []
    for doc in docs:
        alias = doc.get("alias")
        if alias in seen:
            continue
        seen.add(alias)
        out.append(doc)
    return out


async def tournament_entry(store, clan, doc, user):
    if doc.get("scope") != "clan":
        return "clan", clan.alias, clan.name
    links = await store.links_by_user(user.id) if user else []
    link = links[0] if links else None
    return "member", (link.tag if link else None), (link.name if link else None)


def entered(doc, entry):
    kind, ref, _ = entry
    if not ref:
        return False
    eid = tournaments.entry_id(kind, ref)
    return any(row["id"] == eid for row in tournaments.ensure(doc)["entries"])


async def cmd_tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await update.effective_message.reply_text(render.not_linked_view(user_locale(update)))
        return
    L, _ = await clan_locale(store, clan)
    docs = await clan_tournaments(store, clan)
    manage = await can_manage(update, context, clan)
    if not docs:
        await update.effective_message.reply_text(
            tourney_ui.list_view(L, docs), reply_markup=tourney_ui.keyboard(L, {}, False, manage))
        return
    doc = docs[0]
    entry = await tournament_entry(store, clan, doc, update.effective_user)
    await update.effective_message.reply_text(
        tourney_ui.view(L, doc, now_utc()),
        reply_markup=tourney_ui.keyboard(L, doc, entered(doc, entry), manage))


async def open_tournament(query, context, store, clan, L, state, manage):
    family = await store.family_of_clan(clan.alias)
    doc = tourney_ui.to_doc(state, now_utc())
    if doc["scope"] == "family" and not family:
        await query.answer(L.t("tournament.no_family"), show_alert=True)
        return
    if doc["scope"] == "network" and not tournaments.network_ready(
            await store.network_get(clan.alias)):
        await query.answer(L.t("tournament.no_network"), show_alert=True)
        return
    family_alias = family.alias if family and doc["scope"] != "clan" else None
    doc["origin"] = clan.alias
    alias = await store.create_tournament(
        doc, query.from_user.id,
        family_alias=family_alias,
        clan_alias=None if family_alias else clan.alias)
    context.user_data.pop("tourney", None)
    doc = await store.tournament(alias)
    await query.answer(L.t("tournament.opened"))
    await edit_or_log(query, tourney_ui.view(L, doc, now_utc()),
                      tourney_ui.keyboard(L, doc, False, manage), clan.alias)


async def setup_tournament(query, context, store, clan, L, action, manage):
    if not manage:
        await query.answer(L.t("tournament.denied"), show_alert=True)
        return
    if action == "cancel":
        context.user_data.pop("tourney", None)
        docs = await clan_tournaments(store, clan)
        await query.answer()
        await edit_or_log(query, tourney_ui.list_view(L, docs), None, clan.alias)
        return
    state = context.user_data.get("tourney") or tourney_ui.new_state("clan")
    if action == "new":
        state = tourney_ui.new_state("clan")
    elif action == "go":
        await open_tournament(query, context, store, clan, L, state, manage)
        return
    else:
        state = tourney_ui.handle(state, query.data)
    context.user_data["tourney"] = state
    await query.answer()
    await edit_or_log(query, tourney_ui.open_view(L, state),
                      tourney_ui.open_keyboard(L, state), clan.alias)


async def enter_tournament(query, store, L, doc, alias, action, entry):
    kind, ref, name = entry
    if not ref:
        await query.answer(L.t("tournament.denied"), show_alert=True)
        return doc
    if action == "join":
        doc, outcome = tournaments.join(doc, kind, ref, name, now=now_utc().timestamp())
    else:
        doc, removed = tournaments.leave(doc, tournaments.entry_id(kind, ref))
        outcome = "left" if removed else "closed"
    await store.save_tournament(alias, doc)
    await query.answer(L.t(f"tournament.{outcome}"))
    return doc


async def on_tournament_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    clan = await clan_for(update, context)
    if not clan:
        await query.answer()
        return
    L, _ = await clan_locale(store, clan)
    manage = await can_manage(update, context, clan)
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    alias = parts[2] if len(parts) > 2 else ""
    if action in TOURNEY_SETUP:
        await setup_tournament(query, context, store, clan, L, action, manage)
        return
    doc = await store.tournament(alias) if alias else None
    if not doc:
        await query.answer(L.t("tournament.none"), show_alert=True)
        return
    entry = await tournament_entry(store, clan, doc, query.from_user)
    if action in ("join", "leave"):
        doc = await enter_tournament(query, store, L, doc, alias, action, entry)
    else:
        await query.answer()
    await edit_or_log(query, tourney_ui.view(L, doc, now_utc()),
                      tourney_ui.keyboard(L, doc, entered(doc, entry), manage), clan.alias)


async def derby_family(update, context):
    store, _ = services(context)
    chat = update.effective_chat
    family = await store.family_by_chat(chat.id, bot_alias(context)) if chat else None
    if family:
        return family
    user = update.effective_user
    if chat and chat.type == ChatType.PRIVATE and user:
        mine = [row for row in await store.families(bot_alias(context)) if row.owner_id == user.id]
        if mine:
            return mine[0]
    clan = await clan_for(update, context)
    return await store.family_of_clan(clan.alias) if clan else None


async def on_derby_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    store, _ = services(context)
    family = await derby_family(update, context)
    if not family:
        await query.answer()
        return
    L, _ = await family_locale(store, family, update)
    if not await family_allowed(update, context, family):
        await query.answer(L.t("h.family_owner_only"), show_alert=True)
        return
    saved = await store.kv_get(derby.saved_key(family.alias)) or {}
    doc = await store.tournament(saved["alias"]) if saved.get("alias") else None
    if not doc:
        await query.answer(L.t("derby.none"), show_alert=True)
        return
    doc = derby.apply(doc, query.data)
    if derby.skipped(doc):
        await store.save_tournament(doc["alias"], doc, "done")
        await familyroom.drop_notice(store, family, familyroom.DERBY_KIND)
    else:
        await store.save_tournament(doc["alias"], doc)
    await query.answer(L.t("derby.saved"))
    await edit_or_log(query, derby.view(L, family, doc, True), derby.keyboard(L, doc), family.alias)


async def on_family_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from . import console
    query = update.callback_query
    store, _ = services(context)
    L = user_locale(update)
    flow = context.user_data.pop("flow", None) or {}
    await query.answer()
    family = (await store.family_by_alias(flow["family"])
              if flow.get("kind") == "famnotice" and flow.get("family") else None)
    if not family or not flow.get("text") or not query.data.endswith("send"):
        await edit_or_log(query, L.t("family.message.cancelled"), None, "fam")
        return
    if not await family_allowed(update, context, family):
        await edit_or_log(query, L.t("h.family_owner_only"), None, family.alias)
        return
    poller = getattr(context.bot_data.get("supervisor"), "poller", None)
    clans = await store.family_clans(family.alias) if poller else []
    for clan in clans:
        clan_L, _ = await clan_locale(store, clan)
        await poller.deliver(clan, familyroom.message_card(clan_L, family, flow["text"]),
                             "family.notice")
        await asyncio.sleep(console.BROADCAST_DELAY)
    if poller:
        FL, _ = await family_locale(store, family)
        await poller.family_deliver(family, "family.notice",
                                    familyroom.message_card(FL, family, flow["text"]))
    await familyroom.push_notice(store, family, "message", flow["text"], now_utc())
    await store.kv_set(f"fam:{family.alias}:message", {"ts": now_utc().timestamp()},
                       ttl=familyroom.NOTICE_TTL)
    await edit_or_log(query, L.t("family.message.sent", n=len(clans)), None, family.alias)


def _base_ui():
    from . import base_ui
    return base_ui


async def cmd_base(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _base_ui().cmd_base(update, context)


async def on_bases_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _base_ui().on_callback(update, context)


HANDLERS = {
    "warnings": discipline.cmd_warnings,
    "tournament": cmd_tournament,
    "base": cmd_base,
    "duel": duels.cmd_duel,
    "mine": cmd_mine,
    "player": cmd_player,
    "vs": cmd_vs,
    "clanvs": cmd_clanvs,
    "goal": cmd_goal,
    "invite": cmd_invite,
    "link": cmd_link,
    "unlink": cmd_unlink,
    "family": cmd_family,
    "requirements": cmd_requirements,
    "newclan": cmd_newclan,
    "setclan": cmd_setclan,
    "remove": cmd_remove,
    "status": cmd_status,
    "check": cmd_check,
    "settings": cmd_settings,
    "topics": cmd_topics,
    "stickers": cmd_stickers,
    "lang": cmd_lang,
    "tz": cmd_tz,
    "support": cmd_support,
    "cancel": cmd_cancel,
    "points": command("points"),
    "hall": command("hall"),
    "activity": command("activity"),
    "top": command("top"),
    "donations": command("donations"),
    "capital": command("capital"),
    "stars": command("stars"),
    "lazy": cmd_lazy,
}

for module in (leader_tools, recruit_tools, privacy_tools, support_desk, news, integration_tools):
    COMMANDS_BY_AREA[module.AREA].extend(module.COMMANDS)
    HANDLERS.update(module.HANDLERS)

COMMANDS = [entry for rows in COMMANDS_BY_AREA.values() for entry in rows]


def register(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    for name, aliases in COMMANDS:
        handler = (command(name) if name in VIEWS
                   else gated(ACTION_BY_COMMAND.get(name))(HANDLERS[name]))
        app.add_handler(CommandHandler([name] + aliases, handler))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^v:"))
    app.add_handler(CallbackQueryHandler(on_board_callback, pattern=r"^b:"))
    app.add_handler(CallbackQueryHandler(on_targets_callback, pattern=r"^t:"))
    app.add_handler(CallbackQueryHandler(on_cwl_callback, pattern=r"^cw:"))
    app.add_handler(CallbackQueryHandler(on_settings_callback, pattern=r"^(s|cfg):"))
    app.add_handler(CallbackQueryHandler(on_topics_callback, pattern=r"^tp:"))
    app.add_handler(CallbackQueryHandler(on_bases_callback, pattern=r"^bs:"))
    app.add_handler(CallbackQueryHandler(discipline.on_warning_callback, pattern=r"^w:"))
    app.add_handler(CallbackQueryHandler(duels.on_duel_callback, pattern=r"^d:"))
    app.add_handler(CallbackQueryHandler(on_award_callback, pattern=r"^aw:"))
    app.add_handler(CallbackQueryHandler(on_ambassador_callback, pattern=r"^a:"))
    app.add_handler(CallbackQueryHandler(on_help_callback, pattern=r"^h:"))
    app.add_handler(CallbackQueryHandler(on_onboard_callback, pattern=r"^ob:"))
    app.add_handler(CallbackQueryHandler(on_unlink_callback, pattern=r"^u:"))
    app.add_handler(CallbackQueryHandler(privacy_tools.on_privacy_callback, pattern=r"^p:"))
    app.add_handler(CallbackQueryHandler(support_desk.on_feedback_callback, pattern=r"^f:"))
    app.add_handler(CallbackQueryHandler(support_desk.on_terms_callback, pattern=r"^tos:"))
    app.add_handler(CallbackQueryHandler(news.on_news_callback, pattern=r"^n:"))
    app.add_handler(CallbackQueryHandler(tips.on_tip_callback, pattern=r"^tip:"))
    app.add_handler(PreCheckoutQueryHandler(tips.on_pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, tips.on_paid))
    app.add_handler(MessageHandler(filters.StatusUpdate.REFUNDED_PAYMENT, tips.on_refunded))
    app.add_handler(CallbackQueryHandler(on_me_callback, pattern=r"^m:a:"))
    app.add_handler(CallbackQueryHandler(on_mission_callback, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(on_goal_callback, pattern=r"^g:"))
    app.add_handler(CallbackQueryHandler(on_tournament_callback, pattern=r"^tr:"))
    app.add_handler(CallbackQueryHandler(on_derby_callback, pattern=r"^dy:"))
    app.add_handler(CallbackQueryHandler(on_family_callback, pattern=r"^fa:"))
    for handler in leader_tools.extra_handlers():
        app.add_handler(handler)
    for handler in recruit_tools.extra_handlers():
        app.add_handler(handler)
    for handler in integration_tools.extra_handlers():
        app.add_handler(handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_private_text))
    app.add_handler(PollAnswerHandler(on_poll_answer))
    app.add_handler(PollHandler(on_poll))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, on_migrate))
