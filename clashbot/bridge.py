import hashlib

from .render import MAX_LEN
from .util import esc

ICON = "💬"
NAME_MAX = 32
DISCORD_LIMIT = 2000
MEDIA_KINDS = ("photo", "video", "animation", "document", "audio", "voice", "sticker")
MEDIA_MARK = "[{label}]"
MARKDOWN = ("\\", "*", "_", "`", "~", "|", ">", "#")


def clean(text, limit):
    out = str(text or "").replace("\r", "").strip()
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out[:limit]


def person(name):
    return clean(name, NAME_MAX) or "?"


def mask(text):
    out = str(text)
    for char in MARKDOWN:
        out = out.replace(char, "\\" + char)
    return out


def config(state):
    if not isinstance(state, dict):
        return None
    token = state.get("token")
    if not isinstance(token, str) or not token.strip():
        return None
    try:
        channel_id = int(state.get("channel_id"))
        guild_id = int(state.get("guild_id") or 0)
    except (TypeError, ValueError):
        return None
    if channel_id <= 0:
        return None
    return {"token": token.strip(), "channel_id": channel_id, "guild_id": guild_id,
            "guild_name": clean(state.get("guild_name"), NAME_MAX),
            "channel_name": clean(state.get("channel_name"), NAME_MAX)}


def digest(cfg):
    if not cfg:
        return ""
    mark = hashlib.sha256(cfg["token"].encode()).hexdigest()[:12]
    return f"{cfg['guild_id']}:{cfg['channel_id']}:{mark}"


def kinds_of(message):
    return [kind for kind in MEDIA_KINDS if getattr(message, kind, None)]


def media_label(L, kinds):
    if not kinds:
        return None
    return " ".join(MEDIA_MARK.format(label=L.t(f"bridge.media.{kind}")) for kind in kinds)


def attachments_label(L, attachments):
    count = len(attachments or ())
    return MEDIA_MARK.format(label=L.t("bridge.media.file", n=count)) if count else None


def to_discord(name, text, label=None):
    head = f"**{mask(person(name))}**: "
    room = DISCORD_LIMIT - len(head) - (len(label) + 1 if label else 0)
    body = " ".join(part for part in (clean(text, max(0, room)), label) if part)
    if not body:
        return None
    return head + body


def to_telegram(name, text, label=None):
    body = " ".join(part for part in (esc(clean(text, MAX_LEN)) if text else "",
                                      esc(label) if label else "") if part)
    if not body:
        return None
    return f"{ICON} <b>{esc(person(name))}</b>: {body}"


def in_scope(thread_id, thread):
    return thread is None or thread_id == thread


def from_telegram_ok(message, bot_id):
    user = getattr(message, "from_user", None)
    if user is None or getattr(user, "is_bot", False) or getattr(user, "id", None) == bot_id:
        return False
    text = getattr(message, "text", None) or getattr(message, "caption", None)
    return bool(text) or bool(kinds_of(message))


def from_discord_ok(message, me, channel_id):
    author = getattr(message, "author", None)
    if author is None or getattr(author, "bot", False):
        return False
    if me is not None and getattr(author, "id", None) == getattr(me, "id", None):
        return False
    if getattr(message, "webhook_id", None):
        return False
    if getattr(getattr(message, "channel", None), "id", None) != channel_id:
        return False
    return bool(getattr(message, "content", "") or getattr(message, "attachments", None))
