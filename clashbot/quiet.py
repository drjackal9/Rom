SEPARATOR = "\n\n"
LIMIT = 3800

URGENT = ("reminder", "war_end", "war.risk", "war.last_call")


def split_urgent(chunks):
    urgent = []
    deferrable = []
    for kind, text in chunks or ():
        if not text:
            continue
        (urgent if kind in URGENT else deferrable).append((kind, text))
    return urgent, deferrable


def total_length(texts):
    if not texts:
        return 0
    return sum(len(t) for t in texts) + len(SEPARATOR) * (len(texts) - 1)


def merge_queue(queue, texts, limit=LIMIT):
    merged = [t for t in list(queue or []) + list(texts or []) if t]
    while len(merged) > 1 and total_length(merged) > limit:
        merged.pop(0)
    return merged


async def enqueue(store, alias, texts, merge=merge_queue):
    queued = await store.get_state(alias, "queue") or []
    await store.set_state(alias, "queue", merge(queued, texts))


async def enqueue_map(store, alias, key, pending, merge=merge_queue):
    stored = await store.get_state(alias, key) or {}
    for target, texts in (pending or {}).items():
        stored[target] = merge(stored.get(target) or [], texts)
    await store.set_state(alias, key, stored)


def digest(L, queue):
    entries = [t for t in (queue or []) if t]
    if not entries:
        return None
    return L.t("quiet.digest.intro") + SEPARATOR + SEPARATOR.join(entries)
