import logging
from collections import deque
from time import monotonic

import httpx

from .util import encode_tag

log = logging.getLogger("clashbot.coc")
BASE = "https://api.clashofclans.com/v1"
COOLDOWN = 30
DEAD_RETRY = 60
CALL_WINDOW = 60
REJECTED = ("invalid_ip", "invalid_key")
STALLS = ("rate", "maintenance")


def parse_keys(raw):
    if raw is None:
        return []
    items = [raw] if isinstance(raw, str) else list(raw)
    keys = []
    for item in items:
        if item is None:
            continue
        for part in str(item).replace("\r", "\n").replace("\n", ",").split(","):
            key = part.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def classify(response):
    status = response.status_code
    if status == 200:
        return None
    reason = message = ""
    try:
        body = response.json()
        reason = body.get("reason", "") or ""
        message = body.get("message", "") or ""
    except Exception:
        pass
    if status == 403 and "invalidIp" in reason:
        return "invalid_ip"
    if status == 403 and "authorization" in message.lower():
        return "invalid_key"
    if status == 403:
        return "private"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate"
    if status == 503:
        return "maintenance"
    log.warning("Clash API %s su %s: %s", status, response.request.url.path, reason or response.text[:200])
    return f"http_{status}"


class CocApi:
    def __init__(self, token=None, transport=None):
        self.client = httpx.AsyncClient(
            base_url=BASE, timeout=15, headers={"Accept": "application/json"}, transport=transport
        )
        self.calls = deque()
        self.set_token(token)

    def set_token(self, token):
        self.keys = parse_keys(token)
        self.dead = {}
        self.cooling = {}
        self.reasons = {}
        self.cursor = 0
        self.last_error = None
        self.stalls = dict.fromkeys(STALLS, 0)
        self.served = 0

    def keys_alive(self):
        return len(self.keys) - len(self.dead)

    def key_report(self):
        return {"total": len(self.keys), "dead": {i: self.reasons.get(i, "") for i in sorted(self.dead)}}

    def note_stall(self, kind):
        if kind in self.stalls:
            self.stalls[kind] += 1

    def stall_kind(self):
        if self.served or not sum(self.stalls.values()):
            return None
        return "maintenance" if self.stalls["maintenance"] else "rate"

    def round_report(self):
        report = {"stall": self.stall_kind(), "keys": len(self.keys),
                  "calls": self.served + sum(self.stalls.values())}
        self.stalls = dict.fromkeys(STALLS, 0)
        self.served = 0
        return report

    def prune_calls(self, now):
        edge = now - CALL_WINDOW
        while self.calls and self.calls[0] <= edge:
            self.calls.popleft()

    def note_call(self):
        now = monotonic()
        self.calls.append(now)
        self.prune_calls(now)

    def calls_per_minute(self):
        self.prune_calls(monotonic())
        return float(len(self.calls))

    async def close(self):
        await self.client.aclose()

    def pick(self):
        now = monotonic()
        total = len(self.keys)
        for step in range(total):
            index = (self.cursor + step) % total
            if self.dead.get(index, 0) <= now and self.cooling.get(index, 0) <= now:
                self.cursor = (index + 1) % total
                return index
        return None

    def exhausted(self):
        if len(self.dead) < len(self.keys):
            return "rate"
        return self.last_error or "invalid_key"

    async def send(self, method, path, **kwargs):
        total = len(self.keys)
        while True:
            index = self.pick()
            if index is None:
                stopped = self.exhausted()
                self.note_stall(stopped)
                return None, stopped
            try:
                self.note_call()
                response = await self.client.request(
                    method, path, headers={"Authorization": f"Bearer {self.keys[index]}"}, **kwargs
                )
                error = classify(response)
            except UnicodeEncodeError:
                error = "invalid_key"
            except httpx.HTTPError as e:
                log.warning("rete: %s", type(e).__name__)
                return None, "network"
            if error in REJECTED:
                if index not in self.dead:
                    log.error("chiave Clash %s di %s rifiutata (%s)", index + 1, total, error)
                self.dead[index] = monotonic() + DEAD_RETRY
                self.reasons[index] = error
                self.last_error = error
                continue
            if error == "rate":
                self.note_stall(error)
                self.cooling[index] = monotonic() + COOLDOWN
                log.warning("rate limit Clash API sulla chiave %s di %s, pausa %ss", index + 1, total, COOLDOWN)
                continue
            if error == "maintenance":
                self.note_stall(error)
            else:
                self.served += 1
            if self.dead.pop(index, None) is not None:
                self.reasons.pop(index, None)
                log.info("chiave Clash %s di %s di nuovo accettata", index + 1, total)
            return response, error

    async def get(self, path, **params):
        response, error = await self.send("GET", path, params=params or None)
        if error:
            return None, error
        return response.json(), None

    async def clan(self, tag):
        return await self.get(f"/clans/{encode_tag(tag)}")

    async def current_war(self, tag):
        return await self.get(f"/clans/{encode_tag(tag)}/currentwar")

    async def league_group(self, tag):
        return await self.get(f"/clans/{encode_tag(tag)}/currentwar/leaguegroup")

    async def league_war(self, war_tag):
        return await self.get(f"/clanwarleagues/wars/{encode_tag(war_tag)}")

    async def capital_raids(self, tag):
        return await self.get(f"/clans/{encode_tag(tag)}/capitalraidseasons", limit=1)

    async def war_log(self, tag, limit=10):
        return await self.get(f"/clans/{encode_tag(tag)}/warlog", limit=limit)

    async def war_leagues(self):
        return await self.get("/warleagues")

    async def player(self, tag):
        return await self.get(f"/players/{encode_tag(tag)}")

    async def location_clans(self, location_id, limit=200):
        return await self.get(f"/locations/{location_id}/rankings/clans", limit=limit)

    async def location_players(self, location_id, limit=200):
        return await self.get(f"/locations/{location_id}/rankings/players", limit=limit)

    async def check(self):
        return await self.get("/locations", limit=1)

    async def goldpass(self):
        return await self.get("/goldpass/seasons/current")

    async def verify_token(self, tag, token):
        response, error = await self.send("POST", f"/players/{encode_tag(tag)}/verifytoken", json={"token": token})
        if error:
            return None, error
        return response.json().get("status") == "ok", None


async def public_ip():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            return (await client.get("https://api.ipify.org")).text.strip()
    except Exception:
        return "sconosciuto"


async def telegram_me(token):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            data = (await client.get(f"https://api.telegram.org/bot{token}/getMe")).json()
    except Exception:
        return None
    return data.get("result") if data.get("ok") else None
