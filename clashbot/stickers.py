import io
import logging
import re

from PIL import Image, ImageDraw
from telegram import InputSticker
from telegram.error import TelegramError

from .media import badge as badge_of

log = logging.getLogger("clashbot.stickers")

SIZE = 512
EMOJI_SIZE = 100
RING = 28
STATE = "stickers"
QUEUE = "stickers_new"
EVENT = "system.stickers"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
NAME_LIMIT = 64
TITLE_LIMIT = 64
MOMENTS = (
    ("war", "⚔️", (214, 84, 61)),
    ("win", "🏆", (233, 183, 58)),
    ("loss", "💔", (108, 117, 133)),
    ("gift", "🎁", (86, 168, 96)),
    ("night", "🌙", (63, 81, 137)),
)
EMOJI_RING = 6
EMOJI_LIST = ("🛡",)


def valid_name(name):
    return bool(name) and len(name) <= NAME_LIMIT and bool(NAME_RE.fullmatch(name))


def _name(vault, prefix, label, clan_alias, username):
    return f"{prefix}{vault.blind(label, clan_alias)[:10]}_by_{username}"


def set_name(vault, clan_alias, username):
    return _name(vault, "cb", "sticker", clan_alias, username)


def emoji_set_name(vault, clan_alias, username):
    return _name(vault, "ce", "stickeremoji", clan_alias, username)


def compose(badge, color, size=SIZE, ring=RING):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((0, 0, size - 1, size - 1), fill=(*color, 255))
    draw.ellipse((ring, ring, size - 1 - ring, size - 1 - ring), fill=(0, 0, 0, 0))
    art = Image.open(io.BytesIO(badge)).convert("RGBA")
    box = max(1, size - 3 * ring)
    art = art.resize((box, box), Image.LANCZOS)
    canvas.alpha_composite(art, ((size - box) // 2, (size - box) // 2))
    out = io.BytesIO()
    canvas.save(out, format="WEBP", lossless=True, method=6)
    return out.getvalue()


async def _found(bot, name):
    try:
        return await bot.get_sticker_set(name)
    except Exception:
        return None


async def _ensure(bot, user_id, name, title, items, sticker_type=None):
    pack = await _found(bot, name)
    if pack:
        return pack
    try:
        await bot.create_new_sticker_set(user_id, name, title[:TITLE_LIMIT], items,
                                         sticker_type=sticker_type)
    except TelegramError as e:
        log.warning("set non creato: %s", e)
        return None
    return await _found(bot, name)


async def build(bot, vault, clan, clan_json, user_id, title, emoji_title=None):
    urls = (clan_json or {}).get("badgeUrls") or {}
    url = urls.get("large") or urls.get("medium") or urls.get("small")
    if not url:
        return None
    badge = await badge_of(url)
    if not badge:
        return None
    name = set_name(vault, clan.alias, bot.username)
    emoji_name = emoji_set_name(vault, clan.alias, bot.username)
    if not valid_name(name) or not valid_name(emoji_name):
        return None
    items = [InputSticker(compose(badge, color), [emoji], "static") for _, emoji, color in MOMENTS]
    pack = await _ensure(bot, user_id, name, title, items)
    if not pack:
        return None
    emoji_pack = await _ensure(bot, user_id, emoji_name, emoji_title or title,
                               [InputSticker(compose(badge, MOMENTS[0][2], EMOJI_SIZE, EMOJI_RING),
                                             list(EMOJI_LIST), "static")],
                               sticker_type="custom_emoji")
    files = {kind: sticker.file_id for (kind, _, _), sticker in zip(MOMENTS, pack.stickers)}
    return {"set": name, "emoji": emoji_name if emoji_pack else None, "files": files}
