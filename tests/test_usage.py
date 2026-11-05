import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import i18n, publish, usage
from tests.test_web_status import BeatCoc, BeatStore, BeatSupervisor, beat_bot

L = i18n.locale("it")
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)


class UsageStore:
    def __init__(self):
        self.clans = [SimpleNamespace(alias="clan-a", name="Uno", bot_alias="bot-1",
                                      failures=0, last_seen=NOW),
                      SimpleNamespace(alias="clan-b", name="Due", bot_alias="bot-1",
                                      failures=2, last_seen=None)]
        self.states = {("clan-a", "settings"): {"lang": "it"},
                       ("clan-a", "members"): {"#P1": {}, "#P2": {}},
                       ("clan-b", "settings"): {"lang": "en"},
                       ("clan-b", "members"): {"#P3": {}}}

    async def bots(self, active_only=False):
        rows = [SimpleNamespace(alias="bot-1", username="UnoBot", kind="worker", active=True,
                                reason=None, failures=0, last_seen=NOW),
                SimpleNamespace(alias="bot-2", username="DueBot", kind="worker", active=False,
                                reason="owner_stopped", failures=1, last_seen=None)]
        return [row for row in rows if row.active] if active_only else rows

    async def counts(self):
        return {"active": 2, "total": 3}

    async def families(self, bot_alias=None):
        return [SimpleNamespace(alias="fam-1")]

    async def count_links(self):
        return 7

    async def active_clans(self, bot_alias=None):
        return self.clans

    async def get_state(self, alias, kind):
        return self.states.get((alias, kind))

    async def wars_since(self, alias, since):
        assert since == NOW - timedelta(days=usage.DAYS)
        return [{}, {}] if alias == "clan-a" else []


def test_the_usage_snapshot_has_numbers_and_no_names():
    supervisor = SimpleNamespace(running=lambda: ["bot-1"])
    body = asyncio.run(usage.snapshot(UsageStore(), supervisor, NOW))
    assert body == {"v": 1, "updated": int(NOW.timestamp()), "bots": 2, "bots_active": 1,
                    "bots_running": 1, "clans": 3, "clans_active": 2, "families": 1,
                    "links": 7, "members": 3, "wars": 2, "langs": {"en": 1, "it": 1}}
    flat = str(body)
    assert "clan-a" not in flat and "UnoBot" not in flat and "#P1" not in flat


def test_the_report_is_for_the_manager_and_says_what_is_broken():
    store = UsageStore()
    bots = asyncio.run(store.bots())
    errors = [{"at": 1, "level": "ERROR", "who": "clashbot.poller", "text": "giro fallito"}]
    body = usage.report(NOW, bots, ["bot-1"], store.clans, errors)
    assert body["bots"][0] == {"alias": "bot-1", "username": "UnoBot", "running": True,
                               "clans": None, "reason": None, "failures": 0,
                               "last_seen": int(NOW.timestamp())}
    assert body["bots"][1]["running"] is False and body["bots"][1]["reason"] == "owner_stopped"
    assert body["clans"][1] == {"alias": "clan-b", "name": "Due", "bot": "bot-1",
                                "failures": 2, "last_seen": 0}
    assert body["errors"] == errors


def test_the_error_log_keeps_only_the_last_lines_and_no_secrets():
    recent = publish.Recent(keep=3)
    log = logging.getLogger("clashbot.test.recent")
    log.addHandler(recent)
    try:
        log.info("non mi interessa")
        for n in range(5):
            log.warning("guaio %s", n)
    finally:
        log.removeHandler(recent)
    assert [row["text"] for row in recent.rows] == ["guaio 2", "guaio 3", "guaio 4"]
    assert all(row["level"] == "WARNING" for row in recent.rows)
    assert all(len(row["text"]) <= 200 for row in recent.rows)


def test_the_same_numbers_feed_the_console_line():
    body = asyncio.run(usage.snapshot(UsageStore(), SimpleNamespace(running=lambda: []), NOW))
    text = usage.snapshot_text(L, body)
    assert L.t("console.stats", bots=2, active=1, running=0, clans=3, clans_active=2,
               families=1) in text
    assert L.t("console.stats_links", n=7) in text


def beat_clan(alias, bot_alias="b1"):
    return SimpleNamespace(alias=alias, name="Uno", bot_alias=bot_alias, failures=0, last_seen=NOW)


def test_the_beat_writes_the_notes_the_panel_reads(tmp_path):
    heartbeat = tmp_path / "beat"
    heartbeat.touch()
    clock = [0.0]
    store = BeatStore(bots=[beat_bot("b0", kind="console", username="ClanBoardBot"),
                            beat_bot("b1")],
                      clans=[beat_clan("clan-a")], secrets={"site_base": "https://esempio.test/"})
    pulse = publish.Beat(store, BeatSupervisor(running=["b1"]), BeatCoc(), heartbeat,
                         clock=lambda: clock[0])
    asyncio.run(pulse.once())
    assert store.notes["login"] == {"bot": "ClanBoardBot", "url": "https://esempio.test"}
    report = store.notes["report"]
    assert [row["alias"] for row in report["bots"]] == ["b0", "b1"]
    assert report["bots"][1]["running"] is True and report["bots"][1]["clans"] == 1
    assert report["clans"][0]["alias"] == "clan-a"
    assert store.notes["usage"]["clans"] == 1 and store.notes["usage"]["bots"] == 2

    store.notes["usage"] = None
    asyncio.run(pulse.once())
    assert store.notes["usage"] is None
    clock[0] = publish.NOTES_EVERY
    asyncio.run(pulse.once())
    assert store.notes["login"]["bot"] == "ClanBoardBot"
    assert store.notes["usage"]["bots"] == 2


def test_the_watchman_hangs_the_error_log_once_and_the_report_carries_it(tmp_path):
    root = logging.getLogger("clashbot")
    try:
        publish.watch_errors()
        publish.watch_errors()
        assert root.handlers.count(publish.RECENT) == 1
        publish.RECENT.rows.clear()
        logging.getLogger("clashbot.prova").error("giro fallito")
        store = BeatStore(bots=[beat_bot("b1")])
        pulse = publish.Beat(store, BeatSupervisor(), BeatCoc(), tmp_path / "beat")
        asyncio.run(pulse.platform())
        assert store.notes["report"]["errors"][-1]["text"] == "giro fallito"
    finally:
        root.removeHandler(publish.RECENT)
        publish.RECENT.rows.clear()
