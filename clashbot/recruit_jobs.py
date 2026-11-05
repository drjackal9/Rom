from . import recruit, recruit_cards, roles
from .util import zone


def report_line(L, state):
    numbers = recruit.counts(state)
    if not numbers["pending"]:
        return ""
    return "\n" + L.t("recruit.report.line", n=numbers["pending"], below=numbers["below"])


async def applications(poller, t):
    stored = await poller.store.get_state(t.clan.alias, recruit.KIND)
    if not stored:
        return
    state = recruit.state_of(stored)
    kept = len(state["items"])
    state, arrived = recruit.close_joined(state, t.members, t.now)
    if arrived:
        players = await poller.store.get_state(t.clan.alias, "players") or {}
        for item in arrived:
            players = recruit.mark_via(players, item["tag"], t.now)
        await poller.store.set_state(t.clan.alias, "players", players)
    waiting = recruit.stale(state, t.now)
    today = t.now.astimezone(zone(t.tz)).strftime("%Y-%m-%d")
    reminding = bool(waiting) and state.get("reminded") != today
    if reminding:
        state["reminded"] = today
        await poller.dispatch(t, "recruit.reminder",
                              lambda L: recruit_cards.stale_card(L, waiting))
    state = recruit.prune(state, t.now)
    if arrived or reminding or len(state["items"]) != kept:
        await poller.store.set_state(t.clan.alias, recruit.KIND, state)


async def card_for(store, clan, conf, named):
    info = await store.get_state(clan.alias, "info")
    return recruit.board_row(info, conf, named, store.recruit_code(clan.alias), clan.name, clan.tag)


async def publish_now(store, clan, conf):
    row = await store.network_get(clan.alias)
    named = bool((row or {}).get("named"))
    await store.recruit_publish(clan.alias, await card_for(store, clan, conf, named))


async def publish(poller, t):
    store = poller.store
    row = await store.recruit_row(t.clan.alias)
    if not row:
        return
    card = await card_for(store, t.clan, t.settings, row.get("named"))
    if card == row.get("card") and t.now.timestamp() - (row.get("ts") or 0) < 86400:
        return
    await store.recruit_publish(t.clan.alias, card)


async def stamp_verified(poller, t):
    await poller.store.set_network_verified(
        t.clan.alias, bool(await roles.chiefs(poller.store, t.members)))


async def run(poller, t):
    await applications(poller, t)
    await publish(poller, t)
    await stamp_verified(poller, t)
