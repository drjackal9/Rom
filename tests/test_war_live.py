import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import events, i18n, render, render_live, settings as settings_mod, war_live
from clashbot.poller import Poller, Tick
from fixtures import war_json
from test_flows import CLAN, FakeStore

L = i18n.locale("it")
TZ = "Europe/Rome"
END = datetime(2026, 9, 12, 10, tzinfo=timezone.utc)
START = datetime(2026, 9, 11, 10, tzinfo=timezone.utc)


def snap(state="inWar", **kw):
    return events.war_snapshot(war_json(state, **kw))


class FakePoller:
    destination = Poller.destination
    fill_links = Poller.fill_links
    names_map = Poller.names_map
    whisper_war = Poller.whisper_war

    def __init__(self, store, bot=None, coc=None):
        self.store = store
        self.bot = bot
        self.coc = coc
        self.sent = []
        self.nudged = []

    def bot_for(self, clan):
        return self.bot

    async def dispatch(self, t, event, render_text, member_tag=None, chunk=None, card=None,
                       nudged=None):
        if member_tag is not None:
            link = (await self.store.links_for_players([member_tag])).get(member_tag)
            if not link:
                return
        self.sent.append((event, member_tag, render_text(t.L)))
        if nudged:
            self.nudged.append((event, nudged))

    async def plan_for(self, t, war):
        return {}


def tick(now=None, stored=None, members=None):
    t = Tick(CLAN, now or END - timedelta(hours=6))
    t.settings = settings_mod.effective(stored or {"lang": "it", "tz": TZ}, None)
    t.L = L
    t.tz = TZ
    t.members = members or {}
    return t


def run_live(poller, t, old, new, kind="war", day=None, evs=None):
    asyncio.run(war_live.run(poller, t, old, new, kind, day, evs or []))


def test_an_attack_that_improves_a_base_left_under_three_stars_is_a_cleanup():
    old = snap(our_attacks={"#P1": [("#E1", 2, 74)]})
    new = snap(our_attacks={"#P1": [("#E1", 2, 74)], "#P2": [("#E1", 3, 100)]})
    rows = war_live.cleanups(old, new)
    assert len(rows) == 1
    row = rows[0]
    assert (row["name"], row["left_by"], row["defender"]) == ("Luigi", "Mario", "Bowser")
    assert (row["was"], row["stars"], row["finished"], row["pos"]) == (2, 3, True, 1)


def test_a_first_attack_or_an_already_finished_base_is_not_a_cleanup():
    old = snap(our_attacks={"#P1": [("#E1", 3, 100)]})
    new = snap(our_attacks={"#P1": [("#E1", 3, 100)], "#P2": [("#E2", 1, 40), ("#E1", 3, 100)]})
    assert war_live.cleanups(old, new) == []


def test_an_attack_that_does_not_improve_the_base_is_not_a_cleanup():
    old = snap(our_attacks={"#P1": [("#E1", 2, 74)]})
    new = snap(our_attacks={"#P1": [("#E1", 2, 74)], "#P2": [("#E1", 1, 55)]})
    assert war_live.cleanups(old, new) == []


def test_two_clanmates_on_the_same_base_in_one_round_are_read_in_attack_order():
    old = snap(our_attacks={"#P1": [("#E1", 1, 30)]})
    new = snap(our_attacks={"#P1": [("#E1", 1, 30)], "#P2": [("#E1", 3, 100)], "#P3": [("#E1", 2, 60)]})
    new["members"]["#P2"]["attacks"][0]["order"] = 5
    new["members"]["#P3"]["attacks"][0]["order"] = 4
    rows = war_live.cleanups(old, new)
    assert [(r["name"], r["was"], r["stars"], r["left_by"]) for r in rows] == [
        ("Peach", 1, 2, "Mario"), ("Luigi", 2, 3, "Peach")
    ]


def test_the_live_state_starts_again_when_the_war_changes():
    first = snap()
    other = events.war_snapshot(war_json("inWar", end="20260915T100000.000Z", opp_tag="#ALTRO"))
    state = war_live.state_for(None, first)
    state["last_call"].append("#P2")
    state["cleaned"] = 3
    assert war_live.state_for(state, first)["cleaned"] == 3
    fresh = war_live.state_for(state, other)
    assert fresh["cleaned"] == 0 and fresh["last_call"] == [] and fresh["war"] == events.war_key(other)


def test_the_last_call_leaves_at_thirty_minutes_and_only_once_per_member():
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    late = END - timedelta(minutes=29)
    assert [m["tag"] for m in war_live.last_call(war, [], late)] == ["#P2", "#P3"]
    assert war_live.last_call(war, ["#P2", "#P3"], late) == []
    assert war_live.last_call(war, [], END - timedelta(hours=2)) == []
    assert war_live.last_call(snap("preparation"), [], late) == []


def test_the_cleanup_card_names_who_cleaned_and_who_had_left_it():
    old = snap(our_attacks={"#P1": [("#E1", 2, 74)]})
    new = snap(our_attacks={"#P1": [("#E1", 2, 74)], "#P2": [("#E1", 3, 100)]})
    text = render_live.cleanup_card(L, war_live.cleanups(old, new))
    assert "Luigi" in text and "Mario" in text and "Bowser" in text and "⭐⭐⭐" in text
    assert len(text) <= render.MAX_LEN
    assert render_live.cleanup_card(L, []) is None


def test_the_last_call_message_says_who_is_missing_and_how_many_attacks_are_left():
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    rows = war_live.last_call(war, [], END - timedelta(minutes=25))
    text = render_live.last_call_card(L, war, rows[:1], now=END - timedelta(minutes=25))
    assert "Clan Nemico" in text and "Luigi" in text and "Peach" not in text


def test_the_cleanup_goes_out_once_and_is_counted_in_the_state():
    store = FakeStore()
    poller = FakePoller(store)
    t = tick()
    old = snap(our_attacks={"#P1": [("#E1", 2, 74)]})
    new = snap(our_attacks={"#P1": [("#E1", 2, 74)], "#P2": [("#E1", 3, 100)]})
    run_live(poller, t, old, new)
    assert [event for event, _tag, _text in poller.sent] == ["war.cleanup", "war.midway"]
    assert store.state[(CLAN.alias, "war_live")]["cleaned"] == 1
    run_live(poller, t, new, new)
    assert len(poller.sent) == 2


def test_with_the_summary_only_intensity_the_cleanup_is_counted_but_not_announced(monkeypatch):
    store = FakeStore()
    poller = FakePoller(store)
    monkeypatch.setattr(war_live, "route",
                        lambda conf, event: ("group", "summary") if event == "war.attack" else ("group", None))
    t = tick()
    old = snap(our_attacks={"#P1": [("#E1", 2, 74)]})
    new = snap(our_attacks={"#P1": [("#E1", 2, 74)], "#P2": [("#E1", 3, 100)]})
    run_live(poller, t, old, new)
    assert [event for event, _tag, _text in poller.sent] == ["war.midway"]
    assert L.t("midway.cleaned", n=1) in poller.sent[0][2]
    assert store.state[(CLAN.alias, "war_live")]["cleaned"] == 1


def linked_luigi():
    return [SimpleNamespace(tag="#P2", user_id=5, name="Luigi", dm=True, lang=None)]


def test_the_last_call_names_in_the_chat_only_who_linked_the_village():
    store = FakeStore(links=linked_luigi())
    poller = FakePoller(store)
    t = tick(now=END - timedelta(minutes=20))
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    run_live(poller, t, war, war)
    assert [(event, tag) for event, tag, _text in poller.sent] == [
        ("war.midway", None), ("war.last_call", None)
    ]
    assert "Luigi" in poller.sent[1][2] and "Peach" not in poller.sent[1][2]
    assert store.state[(CLAN.alias, "war_live")]["last_call"] == ["#P2"]
    run_live(poller, t, war, war)
    assert len(poller.sent) == 2


def test_without_anyone_linked_the_last_call_does_not_leave():
    store = FakeStore()
    poller = FakePoller(store)
    t = tick(now=END - timedelta(minutes=20))
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    run_live(poller, t, war, war)
    assert [event for event, _tag, _text in poller.sent] == ["war.midway"]
    assert store.state[(CLAN.alias, "war_live")]["last_call"] == []


def test_the_classic_war_round_does_not_erase_the_live_state_of_the_league_war():
    store = FakeStore(links=linked_luigi())
    poller = FakePoller(store)
    t = tick(now=END - timedelta(minutes=20))
    idle = snap("notInWar")
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    run_live(poller, t, idle, idle)
    run_live(poller, t, war, war, kind="cwl", day=3)
    assert [(event, tag) for event, tag, _text in poller.sent] == [
        ("war.midway", None), ("war.last_call", None)
    ]
    run_live(poller, t, idle, idle)
    run_live(poller, t, war, war, kind="cwl", day=3)
    assert len(poller.sent) == 2
    assert store.state[(CLAN.alias, "cwl_war_live")]["last_call"] == ["#P2"]
    assert store.state[(CLAN.alias, "war_live")]["last_call"] == []


def test_the_cleanups_of_the_league_war_keep_their_own_counter():
    store = FakeStore()
    poller = FakePoller(store)
    t = tick()
    idle = snap("notInWar")
    old = snap(our_attacks={"#P1": [("#E1", 2, 74)]})
    new = snap(our_attacks={"#P1": [("#E1", 2, 74)], "#P2": [("#E1", 3, 100)]})
    run_live(poller, t, idle, idle)
    run_live(poller, t, old, new, kind="cwl", day=3)
    run_live(poller, t, idle, idle)
    run_live(poller, t, new, new, kind="cwl", day=3)
    assert [event for event, _tag, _text in poller.sent] == ["war.cleanup", "war.midway"]
    assert store.state[(CLAN.alias, "cwl_war_live")]["cleaned"] == 1
    assert store.state[(CLAN.alias, "war_live")]["cleaned"] == 0


def test_the_midway_summary_arrives_at_the_halfway_point_and_only_once():
    war = snap(our_attacks={"#P1": [("#E1", 3, 100)]})
    assert war_live.midway_at(war) == START + timedelta(hours=12)
    assert war_live.midway(war, START + timedelta(hours=11)) is None
    info = war_live.midway(war, START + timedelta(hours=13))
    assert info["need"] == 0 and info["reachable"] == 6
    assert [m["tag"] for m in info["missing"]] == ["#P1", "#P2", "#P3"]
    assert war_live.midway(snap("preparation"), START + timedelta(hours=13)) is None


def test_the_risk_alarm_speaks_only_when_we_are_not_ahead_and_attacks_remain():
    behind = snap(our_attacks={"#P1": [("#E1", 1, 30)]}, their_attacks={"#E1": [("#P1", 3, 100)]})
    late = END - timedelta(minutes=50)
    info = war_live.risk(behind, late)
    assert info["need"] == 3 and [m["tag"] for m in info["missing"]] == ["#P1", "#P2", "#P3"]
    assert war_live.risk(behind, END - timedelta(hours=6)) is None
    assert war_live.risk(snap(our_attacks={"#P1": [("#E1", 3, 100)]}), late) is None


def test_the_risk_and_the_last_call_go_through_the_quiet_hours():
    from clashbot import quiet
    assert "war.risk" in quiet.URGENT and "war.last_call" in quiet.URGENT
    urgent, deferrable = quiet.split_urgent([("war.risk", "a"), ("war.midway", "b")])
    assert [kind for kind, _text in urgent] == ["war.risk"]
    assert [kind for kind, _text in deferrable] == ["war.midway"]


def test_the_midway_card_says_what_is_missing_and_what_is_still_reachable():
    war = snap(our_attacks={"#P1": [("#E1", 1, 30)]}, their_attacks={"#E1": [("#P1", 3, 100)]})
    now = START + timedelta(hours=13)
    text = render_live.midway_card(L, TZ, war, war_live.midway(war, now), cleaned=2, now=now)
    assert "3" in text and "Mario" in text and len(text) <= render.MAX_LEN


def test_the_risk_card_lists_who_still_has_attacks():
    war = snap(our_attacks={"#P1": [("#E1", 1, 30)]}, their_attacks={"#E1": [("#P1", 3, 100)]})
    now = END - timedelta(minutes=50)
    text = render_live.risk_card(L, TZ, war, war_live.risk(war, now), now=now)
    assert "Luigi" in text and "Peach" in text and len(text) <= render.MAX_LEN


class WhisperBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("disable_notification")))
        return SimpleNamespace(message_id=900 + len(self.sent))


def test_l_ultima_chiamata_passa_i_tag_di_chi_ha_nominato():
    store = FakeStore(links=linked_luigi())
    poller = FakePoller(store)
    t = tick(now=END - timedelta(minutes=20))
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    run_live(poller, t, war, war)
    assert poller.nudged == [("war.last_call", {"war": events.war_key(war), "tags": ["#P2"]})]


def test_il_sussurro_arriva_solo_a_chi_lo_ha_acceso_e_senza_suono():
    luigi = SimpleNamespace(tag="#P2", user_id=5, name="Luigi", dm=True, lang=None, whisper=True)
    store = FakeStore(links=[luigi])
    bot = WhisperBot()
    poller = FakePoller(store, bot=bot)
    t = tick(now=END - timedelta(minutes=20))
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    run_live(poller, t, war, war)
    assert [(chat, silent) for chat, _text, silent in bot.sent] == [(5, True)]
    assert L.t("dm.title") in bot.sent[0][1]
    assert t.nudges == [{"chat_id": 5, "message_id": 901, "tag": "#P2",
                         "war": events.war_key(war)}]


def test_senza_il_sussurro_acceso_l_ultima_chiamata_resta_nel_gruppo():
    store = FakeStore(links=linked_luigi())
    bot = WhisperBot()
    poller = FakePoller(store, bot=bot)
    t = tick(now=END - timedelta(minutes=20))
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    run_live(poller, t, war, war)
    assert bot.sent == [] and t.nudges == []


def test_con_l_ultima_chiamata_spenta_non_si_sussurra_niente():
    luigi = SimpleNamespace(tag="#P2", user_id=5, name="Luigi", dm=True, lang=None, whisper=True)
    store = FakeStore(links=[luigi])
    bot = WhisperBot()
    poller = FakePoller(store, bot=bot)
    stored = settings_mod.migrate({"lang": "it", "tz": TZ})
    stored["routes"]["war.last_call"] = {"to": "off", "intensity": None}
    t = tick(now=END - timedelta(minutes=20), stored=stored)
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)]})
    run_live(poller, t, war, war)
    assert bot.sent == [] and t.nudges == []


def test_the_midway_and_the_risk_go_out_once_per_war():
    store = FakeStore()
    poller = FakePoller(store)
    war = snap(our_attacks={"#P1": [("#E1", 1, 30)]}, their_attacks={"#E1": [("#P1", 3, 100)]})
    run_live(poller, tick(now=START + timedelta(hours=13)), war, war)
    run_live(poller, tick(now=END - timedelta(minutes=50)), war, war)
    run_live(poller, tick(now=END - timedelta(minutes=45)), war, war)
    assert [event for event, _tag, _text in poller.sent] == ["war.midway", "war.risk"]
    state = store.state[(CLAN.alias, "war_live")]
    assert state["midway"] is True and state["risk"] is True
