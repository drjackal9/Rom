import logging
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("clashbot.twitch")

ID_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix"
LOGINS_PER_CALL = 100
TOKEN_KEY = "twitch:token"
LOGIN_MIN = 4
LOGIN_MAX = 25
LOGIN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
HOSTS = ("twitch.tv", "www.twitch.tv", "m.twitch.tv")


def normalize_login(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    if "/" in text:
        parts = urlsplit(text if "//" in text else "//" + text)
        if parts.hostname not in HOSTS:
            return None
        text = parts.path.strip("/").split("/")[0]
    text = text.lstrip("@").lower()
    if not LOGIN_MIN <= len(text) <= LOGIN_MAX or any(c not in LOGIN_CHARS for c in text):
        return None
    return text


class TwitchApi:
    def __init__(self, client_id=None, client_secret=None, transport=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = httpx.AsyncClient(timeout=15, headers={"Accept": "application/json"},
                                        transport=transport)
        self.token = None
        self.expires = 0.0

    def ready(self):
        return bool(self.client_id and self.client_secret)

    async def close(self):
        await self.client.aclose()

    def headers(self, token):
        return {"Client-Id": self.client_id, "Authorization": f"Bearer {token}"}

    async def app_token(self, store, now):
        if not self.ready():
            return None
        ts = now.timestamp()
        if self.token and self.expires > ts:
            return self.token
        cached = await store.kv_get(TOKEN_KEY)
        if isinstance(cached, dict) and cached.get("token"):
            expires = cached.get("expires") or 0
            if isinstance(expires, (int, float)) and expires > ts:
                self.token, self.expires = cached["token"], float(expires)
                return self.token
        try:
            response = await self.client.post(ID_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "grant_type": "client_credentials"})
        except httpx.HTTPError as e:
            log.warning("Twitch: rete non disponibile (%s)", type(e).__name__)
            return None
        if response.status_code != 200:
            log.warning("Twitch: credenziali rifiutate (%s)", response.status_code)
            return None
        body = response.json()
        token = body.get("access_token")
        seconds = int(body.get("expires_in") or 0)
        if not token or seconds <= 0:
            log.warning("Twitch: risposta senza token o senza scadenza")
            return None
        self.token, self.expires = token, ts + seconds
        await store.kv_set(TOKEN_KEY, {"token": token, "expires": self.expires}, ttl=seconds)
        return token

    async def forget(self, store):
        self.token, self.expires = None, 0.0
        await store.kv_del(TOKEN_KEY)

    async def streams(self, store, logins, now, retry=True):
        token = await self.app_token(store, now)
        if not token:
            return {}, "no_token"
        live = {}
        ordered = list(logins)
        for start in range(0, len(ordered), LOGINS_PER_CALL):
            batch = ordered[start:start + LOGINS_PER_CALL]
            try:
                response = await self.client.get(
                    f"{HELIX}/streams", params=[("user_login", login) for login in batch],
                    headers=self.headers(token))
            except httpx.HTTPError as e:
                log.warning("Twitch: rete non disponibile (%s)", type(e).__name__)
                return {}, "network"
            if response.status_code == 401:
                await self.forget(store)
                if retry:
                    return await self.streams(store, logins, now, retry=False)
                return {}, "unauthorized"
            if response.status_code == 429:
                return {}, "rate"
            if response.status_code != 200:
                return {}, f"http_{response.status_code}"
            for row in response.json().get("data") or ():
                login = str(row.get("user_login") or "").lower()
                if login:
                    live[login] = {"id": str(row.get("id")), "login": login,
                                   "name": row.get("user_name") or login,
                                   "title": row.get("title") or "", "game": row.get("game_name") or ""}
        return live, None

    async def channel_exists(self, store, login, now):
        token = await self.app_token(store, now)
        if not token:
            return None
        try:
            response = await self.client.get(f"{HELIX}/users", params={"login": login},
                                             headers=self.headers(token))
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        return bool(response.json().get("data"))
