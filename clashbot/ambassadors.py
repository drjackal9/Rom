import secrets

from . import badges, challenges, feed, i18n, render, ttl
from .settings import effective, route
from .util import now_utc

INVITE_TTL = ttl.GONE_TTL
CODE_BYTES = 9
BOARD = "amb:board"
PAYLOAD = "amb"
EVENT = "challenges.ambassador"


def link(username, code):
    return f"https://t.me/{username}?start={PAYLOAD}{code}"


def code_of(payload):
    text = str(payload or "")
    return text[len(PAYLOAD):] if text.startswith(PAYLOAD) else ""


def _who(store, user_id):
    return store.vault.blind("user", user_id)


def _row(board, who):
    return board.setdefault(who, {"n": 0, "name": None, "visible": False})


async def invite(store, user_id, clan_alias):
    code = secrets.token_urlsafe(CODE_BYTES)
    await store.kv_set(f"amb:{code}",
                       {"by": _who(store, user_id), "uid": int(user_id), "clan": clan_alias},
                       ref=clan_alias, ttl=INVITE_TTL)
    return code


async def remember(store, user_id, code):
    pending = await store.kv_get(f"amb:{code}")
    if not pending:
        return False
    await store.kv_set(f"ambpend:{_who(store, user_id)}", pending, ttl=INVITE_TTL)
    return True


async def credit(store, user_id):
    key = f"ambpend:{_who(store, user_id)}"
    pending = await store.kv_get(key)
    if not pending:
        return None
    await store.kv_del(key)
    board = await store.kv_get(BOARD) or {}
    row = _row(board, pending["by"])
    row["n"] += 1
    await store.kv_set(BOARD, board)
    return dict(row, uid=pending.get("uid"), clan=pending.get("clan"))


async def reward(store, row):
    uid = int((row or {}).get("uid") or 0)
    alias = (row or {}).get("clan")
    clan = await store.clan_by_alias(alias) if uid and alias else None
    if not clan:
        return False
    now = now_utc()
    state = await challenges.load(store, clan.alias)
    badges.grant(state, uid, "ambasciatore", int(now.timestamp()))
    await challenges.save(store, clan.alias, state)
    conf = effective(await store.get_state(clan.alias, "settings"))
    if route(conf, EVENT)[0] == "off":
        return False
    L = i18n.locale(conf["lang"])
    await feed.add(store, clan.alias, uid, EVENT,
                   render.card("🤝", L.t("amb.title"), L.t("amb.credited", n=row["n"])), now)
    return True


async def board(store):
    rows = [{"who": who, "n": int(row.get("n") or 0),
             "name": row.get("name") if row.get("visible") else None}
            for who, row in (await store.kv_get(BOARD) or {}).items()]
    rows.sort(key=lambda row: (-row["n"], row["who"]))
    return rows


async def brought(store, user_id):
    who = _who(store, user_id)
    return int(((await store.kv_get(BOARD) or {}).get(who) or {}).get("n") or 0)


async def set_visible(store, user_id, name, visible):
    stored = await store.kv_get(BOARD) or {}
    row = stored.get(_who(store, user_id))
    if not row:
        return False
    row["name"] = name
    row["visible"] = bool(visible)
    await store.kv_set(BOARD, stored)
    return True
