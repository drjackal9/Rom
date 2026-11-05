from telegram.error import TelegramError

from .settings import route

CHECKS = ("admin", "pin", "war_log")

PERIOD = 86400

ADMIN = "administrator"


def board_wanted(conf):
    return route(conf, "war.board")[0] != "off"


def due(state, now, period=PERIOD):
    checked = (state or {}).get("checked")
    return not checked or float(now) - float(checked) >= period


def broken(results):
    return [name for name in CHECKS if (results or {}).get(name) is False]


def fresh(state, results):
    known = (state or {}).get("checks") or {}
    return [name for name in broken(results) if known.get(name) is not False]


def merged(state, results, now):
    checks = dict((state or {}).get("checks") or {})
    checks.update(results or {})
    return {"checked": float(now), "checks": checks}


async def membership(bot, chat_id):
    if not bot:
        return None
    try:
        return await bot.get_chat_member(chat_id, bot.id)
    except (TelegramError, RuntimeError, AttributeError):
        return None


async def inspect(bot, chat_id, conf, war_private=None):
    results = {}
    if war_private is not None:
        results["war_log"] = not war_private
    member = await membership(bot, chat_id)
    if member is None:
        return results
    admin = getattr(member, "status", None) == ADMIN
    results["admin"] = admin
    if board_wanted(conf):
        pinning = getattr(member, "can_pin_messages", None)
        if not admin:
            results["pin"] = False
        elif pinning is not None:
            results["pin"] = bool(pinning)
    return results
