from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .render import card, quote
from .util import esc

FILENAME = "clanboard-dati.json"


def account_lines(L, account):
    wars = account.get("wars") or {}
    clan = account.get("clan") or {}
    lines = [L.t("privacy.account", name=esc(account.get("name")), tag=esc(account.get("tag")))]
    if clan.get("name"):
        lines.append(L.t("privacy.in_clan", clan=esc(clan["name"])))
    lines += [
        L.t("privacy.alerts_on") if account.get("private_alerts") else L.t("privacy.alerts_off"),
        L.t("privacy.hidden_on") if account.get("hidden_from_boards") else L.t("privacy.hidden_off"),
        L.t("privacy.counts", wars=L.n(wars.get("wars") or 0), stars=L.n(wars.get("stars") or 0),
            points=L.n(account.get("season_points") or 0)),
    ]
    if account.get("titles"):
        lines.append(L.t("privacy.titles", n=len(account["titles"])))
    if account.get("leader_note"):
        lines.append(L.t("privacy.note_yes"))
    return "\n".join(lines)


def data_card(L, payload):
    blocks = [account_lines(L, account) for account in payload.get("accounts") or ()]
    body = L.t("privacy.intro")
    if blocks:
        body += "\n\n" + quote("\n\n".join(blocks))
    return card("🗂", L.t("privacy.title"), body + "\n\n" + L.t("privacy.file"))


def data_keyboard(L, hidden):
    label = "privacy.btn_show" if hidden else "privacy.btn_hide"
    action = "p:show" if hidden else "p:hide"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(L.t(label), callback_data=action)],
        [InlineKeyboardButton(L.t("privacy.btn_forget"), callback_data="p:forget")],
    ])


def hidden_card(L, on):
    return card("🙈" if on else "👀", L.t("privacy.title"),
                L.t("privacy.hidden_done") if on else L.t("privacy.shown_done"))


def forget_card(L):
    return card("🧹", L.t("privacy.forget.title"),
                L.t("privacy.forget.body") + "\n\n" + L.t("privacy.forget.log"))


def forget_keyboard(L):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(L.t("privacy.forget.btn_yes"), callback_data="p:forget:yes"),
        InlineKeyboardButton(L.t("console.btn_cancel"), callback_data="p:forget:no"),
    ]])


def forget_done(L, counts):
    body = L.t("privacy.forget.done", links=counts.get("links", 0), activity=counts.get("activity", 0),
               season=counts.get("season", 0), titles=counts.get("titles", 0), notes=counts.get("notes", 0))
    return card("🧹", L.t("privacy.forget.title"), body + "\n\n" + L.t("privacy.forget.stays"))
