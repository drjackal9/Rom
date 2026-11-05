import asyncio

from clashbot import i18n, quiet, render

L = i18n.locale("it")
EN = i18n.locale("en")


def test_split_urgent_keeps_order_and_drops_empty():
    chunks = [("members", "a"), ("reminder", "b"), ("war_end", "c"), ("capital", ""), ("agenda", "d")]
    urgent, deferrable = quiet.split_urgent(chunks)
    assert urgent == [("reminder", "b"), ("war_end", "c")]
    assert deferrable == [("members", "a"), ("agenda", "d")]
    assert quiet.split_urgent([]) == ([], [])
    assert quiet.split_urgent(None) == ([], [])


def test_urgent_kinds_are_known():
    assert set(quiet.URGENT) == {"reminder", "war_end", "war.risk", "war.last_call"}


def test_merge_queue_appends_in_order():
    assert quiet.merge_queue([], ["a", "b"]) == ["a", "b"]
    assert quiet.merge_queue(["a"], ["b"]) == ["a", "b"]
    assert quiet.merge_queue(None, None) == []
    assert quiet.merge_queue(["a"], ["", None]) == ["a"]


def test_merge_queue_drops_the_oldest_over_the_limit():
    merged = quiet.merge_queue(["1" * 40, "2" * 40], ["3" * 40], limit=100)
    assert merged == ["2" * 40, "3" * 40]
    assert quiet.total_length(merged) <= 100
    assert quiet.merge_queue(["a" * 10], ["b" * 500], limit=100) == ["b" * 500]


def test_digest_is_empty_without_queue():
    assert quiet.digest(L, []) is None
    assert quiet.digest(L, None) is None


def test_digest_card_keeps_order_and_fits_telegram():
    queue = quiet.merge_queue([], [f"{i}" * 1000 for i in range(6)])
    assert quiet.total_length(queue) <= quiet.LIMIT
    body = quiet.digest(L, queue)
    assert body.startswith(L.t("quiet.digest.intro"))
    assert body.index(queue[0]) < body.index(queue[-1])
    card = render.card("🌙", L.t("quiet.digest.title"), body)
    assert "MENTRE DORMIVI" in card and len(card) <= render.MAX_LEN
    assert "WHILE YOU SLEPT" in render.card("🌙", EN.t("quiet.digest.title"), quiet.digest(EN, queue))


class State:
    def __init__(self):
        self.state = {}

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = obj


def test_enqueue_appends_to_the_clan_queue():
    store = State()
    asyncio.run(quiet.enqueue(store, "clan-1", ["a"]))
    asyncio.run(quiet.enqueue(store, "clan-1", ["b"]))
    assert store.state[("clan-1", "queue")] == ["a", "b"]


def test_the_private_queue_does_not_exist_any_more():
    assert not hasattr(quiet, "enqueue_dm")


def test_enqueue_map_uses_the_merge_it_is_given():
    store = State()
    seen = []

    def merge(queued, texts):
        seen.append((list(queued), list(texts)))
        return quiet.merge_queue(queued, texts)

    asyncio.run(quiet.enqueue_map(store, "clan-1", "queue_topics", {"5": ["a"]}, merge))
    assert seen == [([], ["a"])]
    assert store.state[("clan-1", "queue_topics")] == {"5": ["a"]}
