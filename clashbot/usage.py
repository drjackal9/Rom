from datetime import timedelta

from . import render
from .settings import effective

DAYS = 30
VERSION = 1
PANEL_ICON = "📈"
PANEL_NUMBERS = ("bots", "clans_active", "families", "links", "members", "wars")


def _stamp(value):
    try:
        return int(value.timestamp())
    except AttributeError:
        return 0


def aggregate(bots, running, counts, families, links, langs, members, wars, now):
    return {
        "v": VERSION,
        "updated": int(now.timestamp()),
        "bots": len(bots),
        "bots_active": len([bot for bot in bots if bot.active]),
        "bots_running": len(running),
        "clans": int(counts["total"]),
        "clans_active": int(counts["active"]),
        "families": len(families),
        "links": int(links),
        "members": int(members),
        "wars": int(wars),
        "langs": dict(sorted(langs.items())),
    }


async def snapshot(store, supervisor, now, days=DAYS):
    langs, members, wars = {}, 0, 0
    since = now - timedelta(days=days)
    for clan in await store.active_clans():
        conf = effective(await store.get_state(clan.alias, "settings"), None)
        langs[conf["lang"]] = langs.get(conf["lang"], 0) + 1
        members += len(await store.get_state(clan.alias, "members") or {})
        wars += len(await store.wars_since(clan.alias, since))
    return aggregate(await store.bots(), supervisor.running(), await store.counts(),
                     await store.families(), await store.count_links(), langs, members, wars, now)


def snapshot_text(L, body):
    text = L.t("console.stats", bots=body["bots"], active=body["bots_active"],
               running=body["bots_running"], clans=body["clans"],
               clans_active=body["clans_active"], families=body["families"])
    return text + "\n" + L.t("console.stats_links", n=body["links"])


def panel_card(L, note):
    if not note:
        return render.card(PANEL_ICON, L.t("panel.usage.title"), L.t("panel.usage.empty"))
    lines = [L.t("panel.usage.row", label=L.t("panel.usage.n." + key), n=int(note.get(key) or 0))
             for key in PANEL_NUMBERS]
    langs = " · ".join(f"{render.esc(code)} {int(n)}"
                       for code, n in sorted((note.get("langs") or {}).items()))
    if langs:
        lines.append(L.t("panel.usage.langs", langs=langs))
    return render.card(PANEL_ICON, L.t("panel.usage.title"), render.quote("\n".join(lines)))


def report(now, bots, running, clans, errors, clan_counts=None):
    return {
        "v": VERSION,
        "updated": int(now.timestamp()),
        "bots": [
            {"alias": bot.alias, "username": bot.username, "running": bot.alias in running,
             "clans": (clan_counts or {}).get(bot.alias), "reason": bot.reason,
             "failures": bot.failures, "last_seen": _stamp(bot.last_seen)}
            for bot in bots
        ],
        "clans": [
            {"alias": clan.alias, "name": clan.name, "bot": clan.bot_alias,
             "failures": clan.failures, "last_seen": _stamp(clan.last_seen)}
            for clan in clans
        ],
        "errors": list(errors or []),
    }
