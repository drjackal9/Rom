from . import guard

KEY = "wizard_counted"
SETTINGS = "settings"
DELEGATE = "delegate.remove"


def delegates_of(doc):
    return {int(uid) for uid in ((doc or {}).get("delegates") or [])}


def dropped(before, after):
    return bool(delegates_of(before) - delegates_of(after))


def first_save(context, alias):
    data = getattr(context, "user_data", None)
    if data is None:
        return True
    done = set(data.get(KEY) or ())
    if alias in done:
        return False
    data[KEY] = sorted(done | {alias})
    return True


def reopen(context, alias):
    data = getattr(context, "user_data", None)
    if data is None:
        return
    data[KEY] = sorted(set(data.get(KEY) or ()) - {alias})


def kind_at(counted, before, after):
    if dropped(before, after):
        return DELEGATE
    return None if counted else SETTINGS


def kind_of(context, alias, before, after):
    if dropped(before, after):
        return DELEGATE
    return kind_at(not first_save(context, alias), before, after)


async def wizard(store, alias, uid, context, before, after, now=None):
    kind = kind_of(context, alias, before, after)
    if not kind:
        return 0, False
    return await guard.destructive(store, alias, uid, kind, now)
