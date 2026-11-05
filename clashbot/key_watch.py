from . import manager_alerts, platform, render
from .coc import public_ip
from .util import esc

PACK = "platform"
EVENTS = ("platform.key_down", "platform.key_back")
KIND = "keys"
API_KIND = "api"
OK = "ok:"
API_ICON = "🎮"


def alive(report):
    return report["total"] - len(report["dead"])


def signature(report):
    if not report["dead"]:
        return f"ok:{report['total']}"
    return ";".join(f"{i}:{why}" for i, why in sorted(report["dead"].items())) + f"/{report['total']}"


def short(why):
    return "invalid_ip" if why == "invalid_ip" else "rejected"


def was_broken(stored):
    sig = stored.get("sig")
    return bool(sig) and not str(sig).startswith(OK)


def settled(stored):
    return not was_broken(stored) and bool(stored.get("sent", True))


def card(L, report, ip):
    total = report["total"]
    dead = report["dead"]
    if not dead:
        return render.card("🔑", L.t("owner.key.back.title"),
                           L.t("owner.key.back.body", alive=alive(report), total=total))
    if alive(report) == 0:
        name = short(sorted(dead.items())[0][1])
        why = L.t(f"owner.key.{name}.why", ip=esc(str(ip)))
        return render.card("🚫", L.t(f"owner.key.{name}.title"),
                           L.t("owner.key.body", why=why, ip=esc(str(ip))))
    lines = "\n".join(
        L.t("owner.key.line", n=i + 1, total=total, why=L.t(f"owner.key.{short(why)}.short"))
        for i, why in sorted(dead.items())
    )
    return render.card("🔑", L.t("owner.key.partial.title"),
                       L.t("owner.key.partial.body", lines=lines, alive=alive(report), total=total))


def entry(report):
    return {"alive": alive(report), "total": report["total"], "dead": sorted(report["dead"])}


def api_signature(report):
    return report["stall"] or f"{OK}{report['keys']}"


def api_entry(report):
    return {"stall": report["stall"], "keys": report["keys"], "calls": report["calls"]}


def api_card(L, report, tz, since, span):
    kind = report["stall"]
    if not kind:
        return render.card(API_ICON, L.t("owner.api.back.title"),
                           L.t("owner.api.back.body", span=span))
    return render.card(API_ICON, L.t(f"owner.api.{kind}.title"),
                       L.t("owner.api.body", since=L.when(since, tz), keys=report["keys"],
                           what=L.t(f"owner.api.{kind}.what")))


async def watchers(store):
    owner = await manager_alerts.owner_id(store)
    found = [owner] if owner else []
    for row in await platform.delegates(store):
        uid = row.get("user_id")
        if uid is not None and int(uid) not in found:
            found.append(int(uid))
    return found


async def due_state(store, kind, sig, made, at):
    stored = await manager_alerts.state(store, kind)
    if not manager_alerts.due(stored, sig):
        return None
    if sig.startswith(OK) and settled(stored):
        await manager_alerts.record(store, kind, sig, made, at)
        return None
    return stored


async def keys_check(store, bot, coc, at):
    report = coc.key_report()
    if not report["total"]:
        return False
    sig = signature(report)
    if await due_state(store, KIND, sig, entry(report), at) is None:
        return False
    L = await manager_alerts.locale(store)
    ip = await public_ip() if report["dead"] else None
    return await manager_alerts.on_change(store, bot, KIND, sig, entry(report), card(L, report, ip), at)


async def api_check(store, bot, coc, at):
    report = coc.round_report()
    if not report["calls"]:
        return False
    sig = api_signature(report)
    stored = await due_state(store, API_KIND, sig, api_entry(report), at)
    if stored is None:
        return False
    L = await manager_alerts.locale(store)
    tz = await store.get_secret("owner_tz")
    started = manager_alerts.moment(stored.get("at") or at)
    text = api_card(L, report, tz, manager_alerts.moment(at),
                    L.delta(manager_alerts.moment(at), started))
    return await manager_alerts.on_change(store, bot, API_KIND, sig, api_entry(report), text, at,
                                          await watchers(store))


async def check(store, bot, coc, at):
    keys = await keys_check(store, bot, coc, at)
    stall = await api_check(store, bot, coc, at)
    return bool(keys or stall)
