from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .render import card, quote
from .util import esc


def guide_card(L, username):
    return card("📖", L.t("guide.title"), L.t("guide.body", bot=esc(username)))


def guide_keyboard(L, username):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("guide.btn_link"), url=f"https://t.me/{username}?start=collega")
    ]])


def feedback_card(L):
    return card("💬", L.t("feedback.title"), L.t("feedback.intro"))


def feedback_keyboard(L, categories):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(L.t(f"feedback.cat.{name}"), callback_data=f"f:{name}")]
        for name in categories
    ])


def feedback_ask(L, limit):
    return card("💬", L.t("feedback.title"), L.t("feedback.ask", n=limit))


def report_card(L):
    return card("🛟", L.t("feedback.report"), L.t("feedback.pick"))


def terms_card(L):
    return card("📜", L.t("terms.title"), L.t("terms.body"))


def terms_keyboard(L, data, site):
    rows = [[InlineKeyboardButton(L.t("terms.btn"), callback_data=data)]]
    if site:
        base = site.rstrip("/")
        rows.append([InlineKeyboardButton(L.t("terms.read"), url=base + "/terms"),
                     InlineKeyboardButton(L.t("terms.privacy"), url=base + "/privacy")])
    return InlineKeyboardMarkup(rows)


def news_card(L, on):
    return card("📣", L.t("news.title"), L.t("news.body") + "\n\n" + L.t("news.on" if on else "news.off"))


def news_keyboard(L, on):
    label, action = ("news.btn_off", "n:off") if on else ("news.btn_on", "n:on")
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t(label), callback_data=action)]])


def owner_feedback_card(L, category, text, user_id, bot_alias, clan_alias):
    head = L.t("feedback.owner.row", category=L.t(f"feedback.cat.{category}"), id=user_id,
               bot=esc(bot_alias), clan=esc(clan_alias or "-"))
    if not text:
        return card("💬", L.t("feedback.owner.title"), head)
    return card("💬", L.t("feedback.owner.title"), head + "\n" + quote(esc(text)))


def tip_keyboard(L, amounts):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("tip.btn", n=stars), callback_data=f"tip:{stars}") for stars in amounts
    ]])


def tip_link_keyboard(L, username):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("tip.btn_private"), url=f"https://t.me/{username}?start=sostieni")
    ]])


def thanks_card(L, stars):
    return card("💛", L.t("tip.thanks.title"), L.t("tip.thanks.body", n=stars) + "\n\n" + L.t("tip.where"))


def refund_keyboard(L, ref):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("tip.btn_refund"), callback_data=f"tip:r:{ref}")
    ]])
