import logging
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus, ForumIconColor, ForumTopicLimit
from telegram.error import TelegramError

from . import render
from .events_registry import EVENTS, PACKS as EVENT_PACKS
from .settings import route

log = logging.getLogger("clashbot.topics")

WANTED = ("wars", "cwl", "capital_games", "members", "challenges", "bases")

PACKS = tuple(pack for pack in WANTED if pack in EVENT_PACKS)

ICON_COLORS = tuple(int(color) for color in ForumIconColor)

COLORS = {
    "wars": int(ForumIconColor.RED),
    "cwl": int(ForumIconColor.YELLOW),
    "capital_games": int(ForumIconColor.BLUE),
    "members": int(ForumIconColor.GREEN),
    "challenges": int(ForumIconColor.PURPLE),
    "bases": int(ForumIconColor.PINK),
}

NAME_LIMIT = int(ForumTopicLimit.MAX_NAME_LENGTH)

GROUP_DESTINATIONS = ("group", "topic")

MISSING_MARKS = ("thread not found", "topic_deleted", "topic not found")

KEY = "topics:{alias}"


def name(L, pack):
    return L.t(f"topics.name.{pack}")[:NAME_LIMIT]


def saved(conf):
    return (conf or {}).get("topics") or {}


def missing(conf):
    have = saved(conf)
    return tuple(pack for pack in PACKS if not have.get(pack))


def thread_for(conf, event):
    meta = EVENTS.get(event) or {}
    pack = meta.get("pack")
    if not pack or "topic" not in (meta.get("allowed") or ()):
        return None
    to, _ = route(conf or {}, event)
    if to not in GROUP_DESTINATIONS:
        return None
    return saved(conf).get(pack)


def forget(conf, thread):
    return {pack: found for pack, found in saved(conf).items() if found != thread}


def is_missing_thread(error):
    reason = str(error).lower()
    return any(mark in reason for mark in MISSING_MARKS)


def card(L, conf):
    have = saved(conf)
    rows = [L.t("topics.row", name=name(L, pack),
                state=L.t("topics.have") if have.get(pack) else L.t("topics.none"))
            for pack in PACKS]
    return render.card("🗂", L.t("topics.title"),
                       render.quote("\n".join(rows)) + "\n" + L.t("topics.body"))


def keyboard(L, conf):
    left = missing(conf)
    if not left:
        return None
    rows = [[InlineKeyboardButton(L.t("topics.btn_all"), callback_data="tp:all")]]
    rows += [[InlineKeyboardButton(name(L, pack), callback_data=f"tp:p:{pack}")] for pack in left]
    rows.append([InlineKeyboardButton(L.t("topics.btn_no"), callback_data="tp:no")])
    return InlineKeyboardMarkup(rows)


async def can_open(bot, chat_id):
    if not bot:
        return False
    try:
        chat = await bot.get_chat(chat_id)
        if not getattr(chat, "is_forum", False):
            return False
        member = await bot.get_chat_member(chat_id, bot.id)
    except (TelegramError, RuntimeError, AttributeError):
        return False
    return (getattr(member, "status", None) == ChatMemberStatus.ADMINISTRATOR
            and bool(getattr(member, "can_manage_topics", False)))


async def open_topic(bot, chat_id, L, pack):
    try:
        topic = await bot.create_forum_topic(chat_id, name(L, pack), icon_color=COLORS[pack])
    except TelegramError as e:
        log.warning("argomento %s non creato: %s", pack, e)
        return None
    return topic.message_thread_id


async def propose(poller, t):
    if not missing(t.settings):
        return False
    key = KEY.format(alias=t.clan.alias)
    state = await poller.store.kv_get(key) or {}
    if state.get("asked"):
        return False
    today = t.now.astimezone(ZoneInfo(t.tz)).strftime("%Y-%m-%d")
    if state.get("day") == today:
        return False
    state["day"] = today
    await poller.store.kv_set(key, state, ref=t.clan.alias)
    if not await can_open(poller.bot_for(t.clan), t.clan.chat_id):
        return False
    sent = await poller.send(t.clan, card(t.L, t.settings), quiet=t.quiet, hold=False,
                             markup=keyboard(t.L, t.settings))
    if not sent:
        return False
    state["asked"] = int(t.now.timestamp())
    await poller.store.kv_set(key, state, ref=t.clan.alias)
    return True
