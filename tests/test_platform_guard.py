import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from clashbot import __main__ as cli
from clashbot import i18n, platform_guard
from clashbot import poller as poller_mod
from clashbot.platform_guard import FLOOD_LIMIT, FLOOD_WINDOW, GRACE_DAYS, IDLE_DAYS, PER_MINUTE, STATE_KEY, SUMMARY_HOUR
from clashbot.poller import Poller, Tick
from test_routing import ALIAS, CLAN, FakeBot, FakeStore

IT = i18n.locale("it")
MANAGER = 42
OWNER = 7
TZ = "Europe/Rome"
NOW = datetime(2026, 9, 13, 8, tzinfo=timezone.utc)
EARLY = datetime(2026, 9, 13, 4, tzinfo=timezone.utc)


def bot_row(alias=ALIAS, owner_id=OWNER, active=True, reason=None, kind="worker", username="ProvaBot"):
    return SimpleNamespace(alias=alias, owner_id=owner_id, username=username, bot_id=1000,
                           kind=kind, active=active, reason=reason, failures=0)


class GuardStore(FakeStore):
    def __init__(self, bots=(), clans=None, secrets=None, state=None):
        super().__init__(state=state)
        self.rows = {row.alias: row for row in bots}
        self.clans = dict(clans or {})
        self.secrets = {"owner_id": str(MANAGER), "owner_lang": "it", "owner_tz": TZ}
        self.secrets.update(secrets or {})
        self.removed = []
        self.ttl = {}

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        await super().kv_set(key, obj, ref=ref, ttl=ttl)
        self.ttl[key] = ttl

    async def kv_purge(self):
        return 0

    async def active_clans(self):
        return []

    async def live_tournaments(self):
        return []

    async def bots(self, active_only=False):
        return [row for row in self.rows.values() if row.active or not active_only]

    async def bot_by_alias(self, alias):
        return self.rows.get(alias)

    async def count_clans(self, bot_alias):
        return self.clans.get(bot_alias, 0)

    async def counts(self):
        return {"active": 2, "total": 3}

    async def set_bot_active(self, alias, active, reason=None):
        row = self.rows.get(alias)
        if row:
            row.active, row.reason = active, reason
        return row

    async def remove_bot(self, alias):
        self.removed.append(alias)
        return True


class FakeSupervisor:
    def __init__(self, store, bot):
        self.store = store
        self.console = bot
        self.stopped = []
        self.default_alias = ALIAS
        self.guard = None

    def bot(self, alias):
        return self.console if alias == ALIAS else None

    def running(self):
        return [ALIAS]

    def owner_bot(self):
        return self.console

    async def stop_bot(self, alias, reason=None):
        self.stopped.append((alias, reason))
        await self.store.set_bot_active(alias, False, reason)
        return True


class SecretStore:
    def __init__(self):
        self.saved = []

    async def set_secret(self, kind, value):
        self.saved.append((kind, value))
        return "sec-1"


def poller_for(store=None, clock=None, bot=None):
    store = store if store is not None else GuardStore(bots=[bot_row()])
    bot = bot if bot is not None else FakeBot()
    supervisor = FakeSupervisor(store, bot)
    poller = Poller(supervisor, store, None)
    supervisor.guard = poller.guard
    if clock is not None:
        poller.guard.clock = lambda: clock[0]
    return poller, store, bot, supervisor


def chats(bot):
    return [chat_id for chat_id, _, _ in bot.sent]


def texts(bot):
    return [text for _, text, _ in bot.sent]


def test_the_group_cap_is_fifteen_per_minute():
    assert PER_MINUTE == 15
    assert platform_guard.Buckets().per_minute == 15.0
    assert FLOOD_LIMIT == 5 and FLOOD_WINDOW == 3600


def test_the_bucket_stops_at_the_declared_cap_of_each_group():
    buckets = platform_guard.Buckets()
    assert [buckets.take(CLAN.chat_id, 0.0) for _ in range(PER_MINUTE)] == [True] * PER_MINUTE
    assert buckets.take(CLAN.chat_id, 0.0) is False
    assert buckets.take(999, 0.0) is True


def test_the_bucket_fills_up_again_while_the_minute_passes():
    buckets = platform_guard.Buckets()
    for _ in range(PER_MINUTE):
        buckets.take(CLAN.chat_id, 0.0)
    assert buckets.take(CLAN.chat_id, 30.0) is True
    assert buckets.take(CLAN.chat_id, 60.0) is True


def test_the_messages_over_the_cap_wait_for_the_next_round():
    clock = [0.0]
    poller, store, bot, _ = poller_for(clock=clock)
    for i in range(PER_MINUTE + 2):
        asyncio.run(poller.send(CLAN, f"m{i}"))
    assert len(bot.sent) == PER_MINUTE
    assert store.state[(CLAN.alias, "queue_hold")] == {"0": [f"m{PER_MINUTE}", f"m{PER_MINUTE + 1}"]}
    assert poller.guard.delayed == {CLAN.alias: 2}


def test_the_held_back_messages_leave_at_the_next_round_as_they_are():
    clock = [0.0]
    poller, store, bot, _ = poller_for(clock=clock)
    for i in range(PER_MINUTE + 1):
        asyncio.run(poller.send(CLAN, f"m{i}"))
    tick = Tick(CLAN, NOW)
    asyncio.run(poller.flush_queues(tick))
    assert len(bot.sent) == PER_MINUTE
    assert store.state[(CLAN.alias, "queue_hold")] == {"0": [f"m{PER_MINUTE}"]}
    clock[0] = 60.0
    asyncio.run(poller.flush_queues(tick))
    assert bot.sent[-1] == (CLAN.chat_id, f"m{PER_MINUTE}", None)
    assert IT.t("quiet.digest.title") not in texts(bot)[-1]
    assert (CLAN.alias, "queue_hold") not in store.state


def test_the_held_back_messages_of_a_topic_go_back_to_their_topic():
    clock = [0.0]
    poller, store, bot, _ = poller_for(clock=clock)
    for i in range(PER_MINUTE + 1):
        asyncio.run(poller.send(CLAN, f"m{i}", 77))
    assert store.state[(CLAN.alias, "queue_hold")] == {"77": [f"m{PER_MINUTE}"]}
    clock[0] = 60.0
    asyncio.run(poller.flush_queues(Tick(CLAN, NOW)))
    assert bot.sent[-1] == (CLAN.chat_id, f"m{PER_MINUTE}", 77)


def test_the_messages_lost_over_the_queue_cap_are_told_to_the_manager():
    poller, store, bot, _ = poller_for()
    long_text = "x" * 2000
    asyncio.run(poller.enqueue(CLAN.alias, [long_text, long_text, long_text]))
    assert poller.guard.dropped == {CLAN.alias: 2}
    report = asyncio.run(poller.guard.report())
    assert {"kind": "dropped", "name": CLAN.name, "n": 2} in report["actions"]


def test_a_bot_under_the_flood_threshold_keeps_running():
    poller, _, bot, supervisor = poller_for()
    for i in range(FLOOD_LIMIT - 1):
        assert asyncio.run(poller.guard.flood(ALIAS, NOW + timedelta(seconds=i))) is False
    assert supervisor.stopped == []
    assert bot.sent == []


def test_over_the_flood_threshold_the_bot_stops_and_the_manager_is_told():
    poller, store, bot, supervisor = poller_for()
    stopped = False
    for i in range(FLOOD_LIMIT):
        stopped = asyncio.run(poller.guard.flood(ALIAS, NOW + timedelta(seconds=i)))
    assert stopped is True
    assert supervisor.stopped == [(ALIAS, platform_guard.FLOOD_REASON)]
    assert store.rows[ALIAS].reason == "flood"
    assert chats(bot) == [MANAGER]
    assert IT.t("platform.stop.title") in texts(bot)[0]
    assert IT.t("console.reason.flood") in texts(bot)[0]


def test_the_flood_answers_older_than_an_hour_do_not_count():
    poller, _, _, supervisor = poller_for()
    for i in range(FLOOD_LIMIT - 1):
        asyncio.run(poller.guard.flood(ALIAS, NOW + timedelta(seconds=i)))
    late = NOW + timedelta(seconds=FLOOD_WINDOW + 10)
    assert asyncio.run(poller.guard.flood(ALIAS, late)) is False
    assert supervisor.stopped == []


def test_the_manager_gets_one_single_summary_a_day_at_the_fixed_hour():
    poller, _, bot, _ = poller_for()
    assert asyncio.run(poller.guard.daily(EARLY)) is False
    assert asyncio.run(poller.guard.daily(NOW)) is True
    assert asyncio.run(poller.guard.daily(NOW + timedelta(hours=2))) is False
    assert asyncio.run(poller.guard.daily(NOW + timedelta(days=1))) is True
    assert chats(bot) == [MANAGER, MANAGER]


def test_the_summary_follows_the_timezone_of_the_manager():
    poller, _, bot, _ = poller_for(GuardStore(bots=[bot_row()], secrets={"owner_tz": "UTC"}))
    assert NOW.astimezone(timezone.utc).hour < SUMMARY_HOUR
    assert asyncio.run(poller.guard.daily(NOW)) is False
    assert asyncio.run(poller.guard.daily(NOW + timedelta(hours=2))) is True
    assert chats(bot) == [MANAGER]


def test_the_summary_names_bots_clans_errors_and_what_to_do():
    store = GuardStore(bots=[bot_row(), bot_row(alias="bot-2", active=False, reason="flood", username="Altro")],
                       clans={ALIAS: 2})
    poller, _, bot, _ = poller_for(store)
    poller.guard.delay(CLAN.alias)
    assert asyncio.run(poller.guard.daily(NOW)) is True
    text = texts(bot)[0]
    assert IT.t("platform.title") in text
    assert IT.t("platform.bots", running=1, total=2) in text
    assert IT.t("platform.clans", n=2, total=3) in text
    assert IT.t("console.reason.flood") in text
    assert IT.t("platform.action.delayed", name=CLAN.name, n=1) in text


def test_a_bot_without_clans_is_only_noted_at_the_first_look():
    poller, store, bot, supervisor = poller_for()
    asyncio.run(poller.guard.idle_bots(NOW))
    assert bot.sent == [] and supervisor.stopped == []
    assert store.kv[f"idle:{ALIAS}"]["since"] == NOW.timestamp()


def test_after_ninety_days_without_clans_owner_and_manager_are_warned():
    poller, _, bot, supervisor = poller_for()
    asyncio.run(poller.guard.idle_bots(NOW))
    asyncio.run(poller.guard.idle_bots(NOW + timedelta(days=IDLE_DAYS)))
    assert chats(bot) == [OWNER, MANAGER]
    assert supervisor.stopped == []
    asyncio.run(poller.guard.idle_bots(NOW + timedelta(days=IDLE_DAYS + 1)))
    assert chats(bot) == [OWNER, MANAGER]


def test_after_thirty_more_days_the_bot_stops_as_abandoned_and_nothing_is_deleted():
    poller, store, bot, supervisor = poller_for()
    asyncio.run(poller.guard.idle_bots(NOW))
    asyncio.run(poller.guard.idle_bots(NOW + timedelta(days=IDLE_DAYS)))
    bot.sent.clear()
    asyncio.run(poller.guard.idle_bots(NOW + timedelta(days=IDLE_DAYS + GRACE_DAYS)))
    assert supervisor.stopped == [(ALIAS, platform_guard.IDLE_REASON)]
    assert store.rows[ALIAS].reason == "abandoned"
    assert store.removed == []
    assert chats(bot) == [OWNER, MANAGER]


def test_a_bot_that_finds_a_clan_forgets_the_countdown():
    poller, store, bot, supervisor = poller_for()
    asyncio.run(poller.guard.idle_bots(NOW))
    store.clans[ALIAS] = 1
    asyncio.run(poller.guard.idle_bots(NOW + timedelta(days=1)))
    assert f"idle:{ALIAS}" not in store.kv
    asyncio.run(poller.guard.idle_bots(NOW + timedelta(days=IDLE_DAYS + GRACE_DAYS)))
    assert supervisor.stopped == [] and bot.sent == []


def test_the_summary_counts_the_bots_waiting_to_be_stopped():
    poller, _, bot, _ = poller_for()
    asyncio.run(poller.guard.idle_bots(NOW))
    asyncio.run(poller.guard.idle_bots(NOW + timedelta(days=IDLE_DAYS)))
    bot.sent.clear()
    assert asyncio.run(poller.guard.daily(NOW + timedelta(days=IDLE_DAYS))) is True
    assert IT.t("platform.action.idle", name="ProvaBot", n=GRACE_DAYS) in texts(bot)[0]


def test_the_manager_timezone_is_a_secret_that_refuses_an_unknown_zone():
    assert "owner_tz" in cli.SECRET_KINDS and "owner_tz" in cli.PLAIN_KINDS
    store = SecretStore()
    with pytest.raises(SystemExit):
        asyncio.run(cli.store_secret(store, "owner_tz", "Europe/Nessunposto"))
    assert store.saved == []
    asyncio.run(cli.store_secret(store, "owner_tz", TZ))
    assert store.saved == [("owner_tz", TZ)]


def test_the_bucket_and_the_counters_of_the_summary_are_kept_in_kv_with_an_expiry():
    clock = [0.0]
    poller, store, _, _ = poller_for(clock=clock)
    for i in range(PER_MINUTE + 1):
        asyncio.run(poller.send(CLAN, f"m{i}"))
    poller.guard.drop(CLAN.alias, 2)
    assert asyncio.run(poller.guard.save()) is True
    saved = store.kv[STATE_KEY]
    assert saved["buckets"][str(CLAN.chat_id)][0] < 1.0
    assert saved["delayed"] == {CLAN.alias: 1} and saved["dropped"] == {CLAN.alias: 2}
    assert store.ttl[STATE_KEY] == platform_guard.STATE_TTL


def test_the_guard_counts_the_messages_that_went_out():
    poller, store, _, _ = poller_for()
    assert asyncio.run(poller.send(CLAN, "uno")) is True
    assert asyncio.run(poller.send(CLAN, "due")) is True
    assert poller.guard.sent == {CLAN.alias: 2}
    assert asyncio.run(poller.guard.save()) is True
    assert store.kv[STATE_KEY]["sent"] == {CLAN.alias: 2}
    again, _, _, _ = poller_for(store)
    asyncio.run(again.guard.load())
    assert again.guard.sent == {CLAN.alias: 2}
    asyncio.run(again.guard.report(NOW))
    assert again.guard.sent == {}


def test_the_guard_writes_in_kv_only_when_something_happened():
    poller, store, _, _ = poller_for()
    assert asyncio.run(poller.guard.save()) is False
    assert STATE_KEY not in store.kv


def test_after_a_restart_the_guard_takes_back_bucket_and_counters_from_kv():
    clock = [0.0]
    poller, store, _, _ = poller_for(clock=clock)
    for i in range(PER_MINUTE):
        asyncio.run(poller.send(CLAN, f"m{i}"))
    poller.guard.delay(CLAN.alias, 3)
    poller.guard.drop(CLAN.alias, 2)
    asyncio.run(poller.guard.save())
    again, _, _, _ = poller_for(store, clock=clock)
    asyncio.run(again.guard.load())
    assert again.guard.allow(CLAN.chat_id) is False
    assert again.guard.delayed == {CLAN.alias: 3} and again.guard.dropped == {CLAN.alias: 2}
    report = asyncio.run(again.guard.report(NOW))
    assert {"kind": "delayed", "name": CLAN.name, "n": 3} in report["actions"]


def test_the_bucket_fills_up_again_for_the_minutes_the_bot_was_down(monkeypatch):
    clock = [0.0]
    poller, store, _, _ = poller_for(clock=clock)
    for i in range(PER_MINUTE):
        asyncio.run(poller.send(CLAN, f"m{i}"))
    asyncio.run(poller.guard.save())
    monkeypatch.setattr(platform_guard, "now_utc", lambda: datetime.now(timezone.utc) + timedelta(minutes=5))
    again, _, _, _ = poller_for(store, clock=clock)
    asyncio.run(again.guard.load())
    assert again.guard.allow(CLAN.chat_id) is True


def test_the_summary_clears_the_counters_in_kv_too():
    poller, store, _, _ = poller_for()
    poller.guard.delay(CLAN.alias)
    assert asyncio.run(poller.guard.daily(NOW)) is True
    assert store.kv[STATE_KEY]["delayed"] == {}


def test_the_summary_calls_the_clan_by_name_not_by_its_internal_alias():
    poller, _, bot, _ = poller_for()
    poller.guard.delay(CLAN.alias)
    poller.guard.drop(CLAN.alias, 2)
    assert asyncio.run(poller.guard.daily(NOW)) is True
    text = texts(bot)[0]
    assert IT.t("platform.action.delayed", name=CLAN.name, n=1) in text
    assert IT.t("platform.action.dropped", name=CLAN.name, n=2) in text
    assert CLAN.alias not in text


def no_nap(monkeypatch):
    naps = []

    async def sleep(seconds):
        naps.append(seconds)

    monkeypatch.setattr(poller_mod, "asyncio", SimpleNamespace(sleep=sleep))
    return naps


def test_a_flood_answer_under_the_threshold_only_puts_off_the_message(monkeypatch):
    naps = no_nap(monkeypatch)
    bot = FakeBot(retries=1)
    poller, store, _, supervisor = poller_for(bot=bot)
    assert asyncio.run(poller.send(CLAN, "ciao")) is True
    assert naps == [1]
    assert bot.sent == [(CLAN.chat_id, "ciao", None)]
    assert len(store.kv[f"flood:{ALIAS}"]["hits"]) == 1
    assert supervisor.stopped == [] and (CLAN.alias, "queue_hold") not in store.state


def test_over_the_threshold_a_refused_send_stops_the_bot_and_keeps_the_message(monkeypatch):
    no_nap(monkeypatch)
    bot = FakeBot(retries=1)
    store = GuardStore(bots=[bot_row()])
    store.kv[f"flood:{ALIAS}"] = {"hits": [datetime.now(timezone.utc).timestamp()] * (FLOOD_LIMIT - 1)}
    poller, store, _, supervisor = poller_for(store, bot=bot)
    assert asyncio.run(poller.send(CLAN, "ciao")) is False
    assert supervisor.stopped == [(ALIAS, platform_guard.FLOOD_REASON)]
    assert store.state[(CLAN.alias, "queue_hold")] == {"0": ["ciao"]}
    assert chats(bot) == [MANAGER]
    assert IT.t("console.reason.flood") in texts(bot)[0]


def test_a_refused_group_message_counts_as_a_flood_answer():
    bot = FakeBot(retries=1)
    poller, store, _, supervisor = poller_for(bot=bot)
    assert asyncio.run(poller.send(CLAN, "ciao", hold=False)) is True
    assert len(store.kv[f"flood:{ALIAS}"]["hits"]) == 1
    assert supervisor.stopped == []


def test_the_flood_of_telegram_stops_the_bot_passing_by_the_poller(monkeypatch):
    naps = no_nap(monkeypatch)
    bot = FakeBot(retries=FLOOD_LIMIT * 2 - 1, retry_after=5)
    poller, store, _, supervisor = poller_for(bot=bot)
    for _ in range(FLOOD_LIMIT - 1):
        assert asyncio.run(poller.send(CLAN, "gruppo", hold=False)) is False
    assert asyncio.run(poller.send(CLAN, "gruppo")) is False
    assert naps == [6] * (FLOOD_LIMIT - 1)
    assert supervisor.stopped == [(ALIAS, platform_guard.FLOOD_REASON)]
    assert store.rows[ALIAS].reason == platform_guard.FLOOD_REASON
    assert chats(bot) == [MANAGER]
    assert IT.t("console.reason.flood") in texts(bot)[0]


def test_the_round_of_the_poller_takes_back_and_saves_the_state_of_the_guard(monkeypatch):
    store = GuardStore(bots=[bot_row()])
    store.kv[STATE_KEY] = {"at": NOW.timestamp(), "buckets": {}, "delayed": {CLAN.alias: 3}, "dropped": {}}
    poller, store, _, _ = poller_for(store)
    poller.coc = SimpleNamespace(keys_alive=lambda: 1, key_report=lambda: {"total": 1, "dead": {}},
                                 round_report=lambda: {"stall": None, "keys": 1, "calls": 0})

    async def family_jobs(now):
        poller.guard.delay(CLAN.alias)

    async def nothing(*args):
        return False

    def stop():
        raise asyncio.CancelledError

    monkeypatch.setattr(poller, "family_jobs", family_jobs)
    monkeypatch.setattr(poller, "owner_jobs", nothing)
    monkeypatch.setattr(poller.guard, "daily", nothing)
    monkeypatch.setattr(poller_mod, "HEARTBEAT", SimpleNamespace(touch=stop))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(poller.run())
    assert store.kv[STATE_KEY]["delayed"] == {CLAN.alias: 4}
