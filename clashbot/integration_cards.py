from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .bridge import NAME_MAX
from .render import card, quote
from .util import esc


def calendar_card(L, url=None):
    body = L.t("ics.body")
    tail = L.t("ics.link", url=esc(url)) if url else L.t("ics.public_off")
    return card("📅", L.t("ics.title"), body + "\n\n" + tail)


TWITCH_URL = "https://twitch.tv/{login}"


def twitch_url(login):
    return TWITCH_URL.format(login=login)


def live_card(L, stream):
    body = L.t("twitch.live.body", name=esc(stream.get("name") or stream["login"]),
               title=esc(stream.get("title") or "?"), game=esc(stream.get("game") or "?"))
    return card("🔴", L.t("twitch.live.title"), body + "\n" + esc(twitch_url(stream["login"])))


def twitch_card(L, conf, names=None, live=None, ready=True):
    from . import integrations
    stored = integrations.block(conf, "twitch")
    channel = stored.get("channel")
    members = stored.get("members") if isinstance(stored.get("members"), dict) else {}
    parts = [L.t("twitch.clan", url=esc(twitch_url(channel))) if channel else L.t("twitch.clan_none")]
    if members:
        rows = "\n".join(
            L.t("twitch.member_row", name=esc((names or {}).get(tag, {}).get("name") or tag),
                url=esc(twitch_url(login)))
            for tag, login in sorted(members.items())
        )
        parts.append(L.t("twitch.members") + "\n" + quote(rows))
    if live:
        parts.append(L.t("twitch.live_now", names=esc(", ".join(sorted(live)))))
    if not ready:
        parts.append(L.t("twitch.not_ready"))
    parts.append(L.t("twitch.help"))
    return card("🟣", L.t("twitch.title"), "\n\n".join(parts))


def discord_card(L, cfg, privacy_ok=True):
    parts = [L.t("discord.on", guild=esc(cfg["guild_name"] or cfg["guild_id"]),
                 channel=esc(cfg["channel_name"] or cfg["channel_id"])) if cfg else L.t("discord.off")]
    if cfg and not privacy_ok:
        parts.append(L.t("discord.privacy"))
    parts.append(L.t("discord.help"))
    return card("🔗", L.t("discord.title"), "\n\n".join(parts))


def discord_keyboard(L, linked):
    key = "discord.btn_unlink" if linked else "discord.btn_link"
    data = "int:dc:off" if linked else "int:dc:link"
    return InlineKeyboardMarkup([[InlineKeyboardButton(L.t(key), callback_data=data)]])


def guilds_keyboard(guilds):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(guild["name"][:NAME_MAX], callback_data=f"int:dc:g:{guild['id']}")]
        for guild in guilds
    ])


def channels_keyboard(channels):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("#" + channel["name"][:NAME_MAX], callback_data=f"int:dc:c:{channel['id']}")]
        for channel in channels
    ])


def support_extra(L, conf):
    from . import integrations
    channel = integrations.block(conf, "twitch").get("channel")
    if not channel:
        return ""
    return "\n\n" + L.t("twitch.support", url=esc(twitch_url(channel)))
