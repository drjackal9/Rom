import logging

from . import i18n, integration_cards, integrations, twitch
from . import settings as settings_mod
from .settings import is_quiet

log = logging.getLogger("clashbot.twitch")

STATE = "twitch"


def channels(conf):
    stored = integrations.block(conf, "twitch")
    out = []
    channel = twitch.normalize_login(stored.get("channel"))
    if channel:
        out.append(channel)
    members = stored.get("members")
    for value in (members.values() if isinstance(members, dict) else ()):
        login = twitch.normalize_login(value)
        if login and login not in out:
            out.append(login)
    return out


async def api_for(poller):
    api = getattr(poller, "twitch", None)
    if api is not None and api.ready():
        return api
    if api is not None:
        await api.close()
    poller.twitch = twitch.TwitchApi(await poller.store.get_secret("twitch_client_id"),
                                     await poller.store.get_secret("twitch_client_secret"))
    return poller.twitch


async def targets(poller):
    rows = []
    for clan in await poller.store.active_clans():
        if not poller.served(clan):
            continue
        conf = settings_mod.effective(await poller.store.get_state(clan.alias, "settings"), None)
        if not settings_mod.pack_on(conf, integrations.PACK):
            continue
        logins = channels(conf)
        if logins:
            rows.append((clan, conf, logins))
    return rows


async def announce(poller, clan, conf, logins, live, now):
    state = await poller.store.get_state(clan.alias, STATE) or {}
    seen = state.get("live") if isinstance(state.get("live"), dict) else {}
    fresh, started = {}, []
    for login in logins:
        stream = live.get(login)
        if not stream:
            continue
        fresh[login] = stream["id"]
        if seen.get(login) != stream["id"]:
            started.append(stream)
    if fresh != seen:
        await poller.store.set_state(clan.alias, STATE, {"live": fresh})
    if not started:
        return 0
    L = i18n.locale(conf["lang"])
    bot = poller.bot_for(clan)
    silent = is_quiet(conf, now)
    sent = 0
    for stream in started:
        sent += await integrations.send_event(poller.store, bot, clan, conf, "integrations.twitch_live",
                                              integration_cards.live_card(L, stream), silent=silent)
    return sent


async def run(poller, now):
    api = await api_for(poller)
    if not api.ready():
        return 0
    rows = await targets(poller)
    if not rows:
        return 0
    every = sorted({login for _, _, logins in rows for login in logins})
    live, error = await api.streams(poller.store, every, now)
    if error:
        log.warning("Twitch: controllo saltato (%s)", error)
        return 0
    sent = 0
    for clan, conf, logins in rows:
        sent += await announce(poller, clan, conf, logins, live, now)
    return sent
