import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from ..ttl import MANAGED_TTL

MINIAPP_MAX_AGE = 86400
SKEW = MANAGED_TTL


def check_string(pairs):
    return "\n".join(f"{key}={value}" for key, value in sorted(pairs))


def _fresh(got, now, max_age):
    raw = got.get("auth_date") or ""
    if not str(raw).isdigit():
        return None
    stamp = int(raw)
    if now - stamp > max_age or stamp - now > SKEW:
        return None
    if "user" in got:
        try:
            got["user"] = json.loads(got["user"])
        except ValueError:
            return None
    return got


def init_data(raw, token, now, max_age=MINIAPP_MAX_AGE):
    if not raw or not token:
        return None
    got = dict(parse_qsl(raw, keep_blank_values=True))
    signature = got.pop("hash", "")
    if not signature or not got:
        return None
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    wanted = hmac.new(secret, check_string(got.items()).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(wanted, signature):
        return None
    return _fresh(got, now, max_age)


def user_id(checked):
    user = (checked or {}).get("user") if isinstance(checked, dict) else None
    if not isinstance(user, dict):
        return 0
    try:
        return int(user.get("id"))
    except (TypeError, ValueError):
        return 0


def user_name(checked):
    user = (checked or {}).get("user") if isinstance(checked, dict) else None
    if not isinstance(user, dict):
        return ""
    return str(user.get("first_name") or "")


def start_param(checked):
    raw = (checked or {}).get("start_param") if isinstance(checked, dict) else None
    if not isinstance(raw, str) or not raw.isalnum():
        return ""
    return raw
