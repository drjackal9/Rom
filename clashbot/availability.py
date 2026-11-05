from . import polls, render_live
from .events import war_key

STATE = "poll_avail"
OPTIONS = ("in", "maybe", "out")
IN, MAYBE, OUT = 0, 1, 2


def options(L):
    return [L.t(f"avail.option.{name}") for name in OPTIONS]


def choice(said):
    option = (said or {}).get("option")
    if not isinstance(option, int) or isinstance(option, bool):
        return None
    return OPTIONS[option] if 0 <= option < len(OPTIONS) else None


async def open_for(poller, t, war):
    stored = await poller.store.get_state(t.clan.alias, STATE)
    if stored and stored.get("war") == war_key(war):
        return None
    return await polls.open_poll(
        poller, t, STATE, "war.availability",
        t.L.t("avail.question", opponent=war["opponent"]["name"]), options(t.L),
        extra={"war": war_key(war)},
    )


def roster_check(poll, war, links):
    votes = (poll or {}).get("votes") or {}
    by_user = {str(row.user_id): tag for tag, row in (links or {}).items()}
    said = {}
    for user_id, vote in votes.items():
        tag = by_user.get(str(user_id))
        if tag is not None:
            said[tag] = vote.get("option")
    roster = {tag: (m.get("name") or tag) for tag, m in (war.get("members") or {}).items()}
    return {
        "out_in_war": sorted(roster[tag] for tag in roster if said.get(tag) == OUT),
        "in_not_in_war": sorted(links[tag].name for tag, option in said.items()
                                if option == IN and tag not in roster),
        "silent": sorted(roster[tag] for tag in roster if tag in (links or {}) and tag not in said),
    }


async def settle(poller, t, war, kind, day):
    poll = await polls.close_poll(poller, t, STATE)
    if not poll or poll.get("war") != war_key(war):
        return
    links = await poller.store.links_for_players(sorted((t.members or {}).keys()))
    rows = roster_check(poll, war, links)
    if not any(rows.values()):
        return
    await poller.dispatch(t, "war.roster", lambda L: render_live.roster_card(L, rows, kind, day))
