from collections import Counter

from telegram.constants import PollLimit

from . import bases, ledger, polls, progress, reasons, render
from .handlers import user_roles
from .reasons import refuse
from .retention import BASE_KEEP
from .settings import MANAGER
from .verify import LEADER_ROLES

POLL_STATE = "poll_bases"
WEEK_STATE = "bases_week"
PACK_QUEUE = "bases_pack"
POLL_EVENT = "bases.poll"
PACK_EVENT = "bases.pack"
POLL_TTL = 7 * progress.DAY
VERIFIED = LEADER_ROLES
PROPOSED_STATE = "bases_proposed"
PROPOSED_KEEP = BASE_KEEP
LOG = "bases"


async def proposals(store, clan_alias):
    rows = await store.get_state(clan_alias, PROPOSED_STATE)
    return [row for row in rows or () if isinstance(row, dict)]


def proposal_row(ref, link, label, name):
    layout = bases.parse_link(link)
    if not ref or not layout or label not in bases.LABELS:
        return None
    return {"id": ref, "name": name, "label": label, "village": layout["village"],
            "hall": layout["hall"], "link": link}


def layout_of(link):
    found = bases.parse_link(link)
    return found["id"] if found else ""


async def keep_proposals(act, rows):
    await act.store.set_state(act.clan.alias, PROPOSED_STATE, rows)


async def made(act, row):
    layout = bases.parse_link(row.get("link"))
    if not layout or not await act.store.add_base(act.clan.alias, layout, row.get("label"),
                                                  {"name": row.get("name")}):
        return refuse(reasons.TAKEN)
    await ledger.record(act.store, act.clan.alias, LOG, act.uid, act.name,
                        row.get("label"), act.now)
    return True


async def propose_act(act):
    link = str(act.body.get("link") or "")
    row = proposal_row(str(act.body.get("id") or ""), link, str(act.body.get("label") or ""),
                       act.name)
    if not row:
        return refuse(reasons.BAD)
    if act.level == MANAGER:
        return await made(act, row)
    rows = await proposals(act.store, act.clan.alias)
    layout = layout_of(link)
    if len(rows) >= PROPOSED_KEEP or any(layout_of(one.get("link")) == layout for one in rows):
        return refuse(reasons.TAKEN)
    await keep_proposals(act, rows + [row])
    return True


async def decide(act, yes):
    ref = str(act.body.get("ref") or "")
    rows = await proposals(act.store, act.clan.alias)
    row = next((one for one in rows if one.get("id") == ref), None)
    if not row:
        return None, refuse(reasons.GONE)
    if yes:
        outcome = await made(act, row)
        if not reasons.done(outcome):
            return None, outcome
    await keep_proposals(act, [one for one in rows if one.get("id") != ref])
    return row, None


async def accept_act(act):
    row, code = await decide(act, True)
    return True if row else code


async def reject_act(act):
    row, code = await decide(act, False)
    if not row:
        return code
    await ledger.record(act.store, act.clan.alias, LOG, act.uid, act.name,
                        row.get("label"), act.now)
    return True


def pack_title(L, row):
    return L.t("bases.pack.name", label=bases.label_name(L, row.get("label")),
               village=L.t(f"bases.village.{row.get('village')}"))


def pack_card(L, rows, names):
    if not rows:
        return render.card("📦", L.t("bases.tab.packs"), L.t("bases.packs.empty"))
    lines = [L.t("bases.pack.row", clan=render.esc(names.get(row["clan_alias"]) or "?"),
                 name=pack_title(L, row), n=row["n"]) for row in rows]
    return render.card("📦", L.t("bases.tab.packs"), render.quote("\n".join(lines)))


def poll_pick(rows):
    usable = [row for row in rows or () if row.get("hall")]
    if len(usable) < 2:
        return []
    village, hall = Counter((row["village"], row["hall"]) for row in usable).most_common(1)[0][0]
    picked = [row for row in usable if row["village"] == village and row["hall"] == hall]
    if len(picked) < 2:
        return []
    return picked[:PollLimit.MAX_OPTION_NUMBER]


def poll_options(L, rows):
    return [L.t("bases.poll.option", label=bases.label_name(L, row.get("label")),
                hall=bases.hall_name(row.get("village"), row.get("hall")),
                name=row.get("name") or "?")[:PollLimit.MAX_OPTION_LENGTH] for row in rows]


def winner_card(L, row):
    return render.card("🏰", L.t("bases.title"), L.t(
        "bases.poll.winner", name=render.esc(row.get("name") or "?"),
        label=bases.label_name(L, row.get("label")),
        hall=bases.hall_name(row.get("village"), row.get("hall"))))


async def winner_first(store, clan_alias, rows, village=None, hall=None):
    marker = await store.get_state(clan_alias, WEEK_STATE) or {}
    alias = marker.get("winner")
    page = list(rows or ())
    if not alias:
        return page
    row = (next((one for one in page if one.get("alias") == alias), None)
           or await store.base_by_alias(alias))
    if not row or row.get("clan_alias") != clan_alias:
        return page
    if (village and row.get("village") != village) or (hall and row.get("hall") != hall):
        return page
    merged = [dict(row, winner=True)] + [one for one in page if one.get("alias") != alias]
    return merged[:len(page)] if page else merged


async def is_verified(store, user_id, clan):
    members = await store.get_state(clan.alias, "members")
    return bool(await user_roles(store, user_id, members) & VERIFIED)


async def publish(store, clan, village, label, on=True):
    rows = [row for row in await store.clan_bases(clan.alias, village, None, BASE_KEEP)
            if row["label"] == label]
    for row in rows:
        await store.set_base_flags(row["alias"], published=on)
    return len(rows)


async def import_pack(store, clan, source_alias, village, label):
    copied = await store.copy_bases(source_alias, clan.alias, village, label)
    if copied:
        queued = await store.get_state(clan.alias, PACK_QUEUE) or []
        queued.append({"source": source_alias, "village": village, "label": label, "n": copied})
        await store.set_state(clan.alias, PACK_QUEUE, queued)
    return copied


async def settle_poll(poller, t):
    poll = await polls.close_poll(poller, t, POLL_STATE)
    if not poll:
        return False
    counts = Counter(vote.get("option") for vote in (poll.get("votes") or {}).values())
    if not counts:
        return False
    index = counts.most_common(1)[0][0]
    aliases = poll.get("bases") or []
    if not isinstance(index, int) or not 0 <= index < len(aliases):
        return False
    row = await poller.store.base_by_alias(aliases[index])
    if not row:
        return False
    marker = await poller.store.get_state(t.clan.alias, WEEK_STATE) or {}
    await poller.store.set_state(t.clan.alias, WEEK_STATE, dict(marker, winner=row["alias"]))
    await poller.dispatch(t, POLL_EVENT, lambda L, row=row: winner_card(L, row))
    return True


async def weekly_poll(poller, t):
    week = progress.period_start(t.now, t.tz, "week")
    marker = await poller.store.get_state(t.clan.alias, WEEK_STATE)
    if marker and int(marker.get("week") or 0) >= week:
        return False
    rows = poll_pick(await poller.store.clan_bases(t.clan.alias, None, None, bases.PAGE))
    if not rows:
        return False
    await settle_poll(poller, t)
    marker = await poller.store.get_state(t.clan.alias, WEEK_STATE) or {}
    await poller.store.set_state(t.clan.alias, WEEK_STATE, dict(marker, week=week))
    return bool(await polls.open_poll(poller, t, POLL_STATE, POLL_EVENT,
                                      t.L.t("bases.poll.question"), poll_options(t.L, rows),
                                      {"bases": [row["alias"] for row in rows]}, POLL_TTL))


HANDLERS = {"base.propose": propose_act, "base.accept": accept_act,
            "base.reject": reject_act}
