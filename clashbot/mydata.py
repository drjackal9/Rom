from . import discipline, privacy

SURE = "yes"


def warnings_of(entries, members, tags):
    found = []
    for row in entries or ():
        if not isinstance(row, dict) or row.get("tag") not in tags:
            continue
        found.append({"at": row.get("at"), "war": row.get("war"), "missed": row.get("missed"),
                      "by": ((members or {}).get(row.get("by")) or {}).get("name")})
    return found


async def bundle(store, alias, uid, now):
    clan = await store.clan_by_alias(alias)
    if not clan:
        return None
    links = await store.links_by_user(uid)
    data = await privacy.bundle(store, clan)
    found = await privacy.collect(store, uid, privacy.scoped(data, links), now, [(clan, data)])
    found["warnings"] = warnings_of(await store.get_state(alias, discipline.STATE),
                                    data.get("members"), {row.tag for row in links})
    return found


async def forget(store, uid, now):
    return await privacy.erase(store, uid, await store.links_by_user(uid), now)


async def forget_act(act):
    if str(act.body.get("sure") or "") != SURE:
        return False
    await forget(act.store, act.uid, act.now)
    return True


HANDLERS = {"data.forget": forget_act}
