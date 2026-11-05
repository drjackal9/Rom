import os
from pathlib import Path

from .crypto import KEY_DIR

TOKEN_FILE = "tunnel.token"


def path(key_dir=None):
    return Path(key_dir or KEY_DIR) / TOKEN_FILE


def valid(value):
    return bool(value) and value == value.strip() and not any(ch.isspace() for ch in value)


def write(value, key_dir=None):
    target = path(key_dir)
    tmp = target.with_name(TOKEN_FILE + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(target)
    return target


def remove(key_dir=None):
    target = path(key_dir)
    if not target.exists():
        return False
    target.unlink()
    return True
