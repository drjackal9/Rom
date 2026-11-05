import asyncio
import copy
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import handlers, hub, i18n, leaderboards as boards, render
from clashbot.crypto import Vault
from clashbot.db import Store
from test_flows import ALIAS, CLAN, FakeQuery, FakeStore, fake_update

L = i18n.locale("it")
STATE = {
    (CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"},
    (CLAN.alias, "members"): {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}},
    (CLAN.alias, "progress"): {"#P1": {"name": "Mario", "now": {"gold": 12_300_000, "donated": 900},
                                       "week": {"since": 0, "gold": 0, "donated": 0}}},
}

DELTAS = [{"tag": "#P1", "name": "Mario", "loot": 12_300_000, "dark": 0, "levels": 6, "th_up": 0,
           "wins": 37, "games": 4000, "raid_loot": 120_000, "capital_gold": 0, "donated": 900},
          {"tag": "#P2", "name": "Luigi", "loot": 2_000_000, "dark": 0, "levels": 14, "th_up": 1,
           "wins": 3, "games": 0, "raid_loot": 0, "capital_gold": 0, "donated": 200}]
STATS = {"#P1": {"name": "Mario", "wars": 2, "attacks": 4, "stars": 11, "triples": 2, "missed": 0}}
MEMBERS = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}, "#P3": {"name": "Peach"}}


def test_network_payload_is_only_aggregates():
    payload = boards.network_payload("Futuro", "#CLAN1", "2026-W37", DELTAS, STATS, MEMBERS)
    assert payload["name"] == "Futuro" and payload["tag"] == "#CLAN1" and payload["week"] == "2026-W37"
    assert payload["metrics"] == {"members": 3, "avg": 64.7, "stars": 11, "donations": 1100}
    assert "#P1" not in repr(payload["metrics"])


def test_network_position_is_one_based_or_none():
    board = [{"alias": "clan-a"}, {"alias": "clan-b"}]
    assert boards.network_position(board, "clan-b") == 2
    assert boards.network_position(board, "clan-z") is None


def test_network_view_hides_the_name_when_anonymous():
    board = [{"alias": "clan-a", "code": "ab12cd", "name": None, "metrics": {"avg": 60.0, "stars": 40}},
             {"alias": "clan-b", "code": "ef34gh", "name": "Futuro", "metrics": {"avg": 40.7, "stars": 11}}]
    text = render.network_view(L, board, board[1], True)
    assert "Futuro" in text and "ab12cd" in text
    assert L.t("network.anon", code="ab12cd") in text
    assert L.t("network.you", n=2) in text


def test_network_view_invites_who_is_out():
    text = render.network_view(L, [], None, False)
    assert L.t("network.off") in text and "🥇" not in text


class NetworkPool:
    def __init__(self):
        self.rows = {}

    async def execute(self, sql, *args):
        if "delete from" in sql:
            return "DELETE 1" if self.rows.pop(args[0], None) else "DELETE 0"
        alias, visible, named, key_id, data = args
        self.rows[alias] = {"clan_alias": alias, "visible": visible, "named": named,
                            "key_id": key_id, "data": data, "verified": False,
                            "updated_at": None}
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return self.rows.get(args[0])

    async def fetch(self, sql, *args):
        return [row for row in self.rows.values() if row["visible"]]


def store_with_pool(tmp_path):
    store = Store(Vault(tmp_path))
    store.pool = NetworkPool()
    return store


def test_store_round_trip_and_forget(tmp_path):
    store = store_with_pool(tmp_path)
    payload = {"name": "Futuro", "tag": "#CLAN1", "week": "2026-W37", "metrics": {"avg": 40.7}}
    asyncio.run(store.network_set("clan-a841cc", True, False, payload))
    row = asyncio.run(store.network_get("clan-a841cc"))
    assert row["visible"] is True and row["named"] is False and row["name"] is None
    assert row["metrics"]["avg"] == 40.7 and len(row["code"]) == 6
    asyncio.run(store.network_set("clan-a841cc", True, True, payload))
    assert asyncio.run(store.network_get("clan-a841cc"))["name"] == "Futuro"
    board = asyncio.run(store.network_board())
    assert [r["alias"] for r in board] == ["clan-a841cc"]
    assert asyncio.run(store.network_forget("clan-a841cc")) is True
    assert asyncio.run(store.network_get("clan-a841cc")) is None


def test_network_rows_join_then_name_and_ride_the_hub_keyboard():
    assert [b.callback_data for row in hub.network_rows(L, False, False) for b in row] == [
        "b:network:toggle"]
    rows = hub.network_rows(L, True, False)
    assert [b.callback_data for row in rows for b in row] == ["b:network:toggle", "b:network:name"]
    texts = [b.text for row in rows for b in row]
    assert L.t("network.btn_leave") in texts and L.t("network.btn_named") in texts
    assert L.t("network.btn_anon") in [b.text for row in hub.network_rows(L, True, True) for b in row]
    markup = hub.keyboard(L, "network", "week", False, rows)
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "b:network:toggle" in data and "b:network:name" in data
    assert "b:mvp:month" in data and "v:menu" in data
    assert all(len(d.encode()) <= 64 for d in data)


def test_retention_covers_the_network_table():
    from clashbot import retention
    assert "rete_vecchia" in retention.COUNT_SQL and "rete_vecchia" in retention.DELETE_SQL
    assert "network_clans" in retention.DELETE_SQL["rete_vecchia"]
    assert str(retention.INACTIVE_CLAN_DAYS) in retention.DELETE_SQL["rete_vecchia"]


class NetworkQuery(FakeQuery):
    def __init__(self, data):
        super().__init__(data)
        self.markups = []

    async def edit_message_text(self, text, reply_markup=None):
        await super().edit_message_text(text, reply_markup)
        self.markups.append(reply_markup)


def context_for(store):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": ALIAS})


def press(store, data, user_id=7):
    query = NetworkQuery(data)
    update = fake_update(query, user_id, ChatType.PRIVATE)
    asyncio.run(handlers.on_board_callback(update, context_for(store)))
    return query


def datas_of(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_the_leader_joins_anonymously_and_keeps_the_other_tabs_under_the_hand():
    store = FakeStore(state=copy.deepcopy(STATE), owner="7")
    query = press(store, "b:network:toggle")
    row = store.network[CLAN.alias]
    assert row["visible"] is True and row["named"] is False and row["name"] is None
    assert row["metrics"] == {"members": 2, "avg": 12.0, "stars": 0, "donations": 900}
    assert query.answers == [(L.t("network.joined"), True)]
    assert L.t("network.anon", code=CLAN.alias[-6:]) in query.edits[0]
    assert L.t("network.you", n=1) in query.edits[0] and CLAN.name not in query.edits[0]
    data = datas_of(query.markups[0])
    assert "b:network:toggle" in data and "b:network:name" in data
    assert "b:mvp:month" in data and "v:menu" in data


def test_the_name_can_go_on_and_off_and_the_exit_forgets_everything():
    store = FakeStore(state=copy.deepcopy(STATE), owner="7")
    press(store, "b:network:toggle")
    named = press(store, "b:network:name")
    assert store.network[CLAN.alias]["named"] is True
    assert store.network[CLAN.alias]["name"] == CLAN.name
    assert named.answers == [(L.t("network.named_on"), True)] and CLAN.name in named.edits[0]
    back = press(store, "b:network:name")
    assert store.network[CLAN.alias]["named"] is False
    assert back.answers == [(L.t("network.named_off"), True)]
    out = press(store, "b:network:toggle")
    assert store.network == {} and out.answers == [(L.t("network.left"), True)]
    assert L.t("network.off") in out.edits[0]
    data = datas_of(out.markups[0])
    assert "b:network:toggle" in data and "b:network:name" not in data


def test_who_does_not_manage_the_clan_gets_no_answer_and_no_board():
    store = FakeStore(state=copy.deepcopy(STATE), owner="7")
    denied = press(store, "b:network:toggle", user_id=99)
    assert store.network == {} and denied.edits == []
    assert denied.answers == [(None, False)]
    press(store, "b:network:toggle")
    shut = press(store, "b:network:week", user_id=99)
    assert shut.edits == [] and shut.markups == []
