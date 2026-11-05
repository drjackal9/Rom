from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from . import ambassadors

CHOOSER = "https://t.me/share/url"
NEWBOT = "newbot"


def console_of(context):
    supervisor = context.bot_data.get("supervisor")
    bot = supervisor.owner_bot() if supervisor else None
    return getattr(bot, "username", None)


def console_link(console_username):
    return f"https://t.me/{console_username}"


def link(console_username, L, code=None):
    target = ambassadors.link(console_username, code) if code else console_link(console_username)
    text = L.t("share.text", console=console_username)
    return f"{CHOOSER}?url={quote(target, safe='')}&text={quote(text, safe='')}"


def newbot_link(console_username):
    return f"{console_link(console_username)}?start={NEWBOT}"


def button(L, console_username, code=None):
    return InlineKeyboardButton(L.t("share.btn_share"), url=link(console_username, L, code))


def keyboard(L, console_username, code=None):
    return InlineKeyboardMarkup([
        [button(L, console_username, code)],
        [InlineKeyboardButton(L.t("share.btn_newbot"), url=newbot_link(console_username))],
    ])


def with_button(L, markup, console_username):
    if not console_username:
        return markup
    return InlineKeyboardMarkup(list(markup.inline_keyboard) + [[button(L, console_username)]])
