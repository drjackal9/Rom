import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from fixtures import war_json
from telegram.constants import MessageLimit
from telegram.error import BadRequest, Forbidden, RetryAfter

from clashbot import (boards, events as events_mod, feed, i18n, quiet, render, scoring,
                      settings as settings_mod, views, warstats, whisper)
from clashbot.achievements import player_snapshot
from clashbot.poller import Poller, Tick, link_names, member_locale

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
LATE = datetime(2026, 9, 12, 9, 30, tzinfo=timezone.utc)
END_OF_WAR = datetime(2026, 9, 12, 10, 5, tzinfo=timezone.utc)
MONDAY = datetime(2026, 9, 7, 9, 30, tzinfo=timezone.utc)
NIGHT = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)
FAMILY_MONDAY = datetime(2026, 9, 14, 9, 30, tzinfo=timezone.utc)
ALIAS = "bot-1"
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias=ALIAS)
FAMILY = SimpleNamespace(alias="fam-1", chat_id=202, name="Famiglia", bot_alias=ALIAS)
IT = i18n.locale("it")
DE = i18n.locale("de")
TZ = "Europe/Rome"

FUTURO = {
    "lang": "it",
    "tz": TZ,
    "defenses": True,
    "achievements": True,
    "agenda": True,
    "polls": True,
    "movements": True,
    "board": True,
    "reminders": [28800, 14400, 3600],
    "quiet": None,
    "min_th": None,
    "note": "",
}

MEMBERS = {
    "#P1": {"name": "Mario", "role": "leader"},
    "#P2": {"name": "Luigi", "role": "coLeader"},
    "#P3": {"name": "Peach", "role": "member"},
}

PREP = events_mod.war_snapshot(war_json("preparation"))
STARTED = events_mod.war_snapshot(war_json("inWar"))
ATTACKED = events_mod.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]},
                                            their_attacks={"#E2": [("#P3", 2, 78)]}))
ENDED = events_mod.war_snapshot(war_json("warEnded",
                                         our_attacks={"#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 60)]},
                                         their_attacks={"#E2": [("#P3", 2, 78)]}))


def link(tag, user_id, name, dm=True, lang=None, whisper=False):
    return SimpleNamespace(alias=CLAN.alias, tag=tag, user_id=user_id, name=name, dm=dm, lang=lang,
                           whisper=whisper)


LINKS = {"#P1": link("#P1", 7, "Mario"), "#P2": link("#P2", 8, "Luigi"), "#P3": link("#P3", 9, "Peach")}


class FakeBot:
    def __init__(self, retries=0, retry_after=0):
        self.sent = []
        self.silent = []
        self.photos = []
        self.polls = []
        self.pins = []
        self.edits = []
        self.markups = []
        self.deleted = []
        self.unpinned = []
        self.retries = retries
        self.retry_after = retry_after
        self.refused = 0
        self.fail_edit_with = None
        self.fail_delete_with = None

    async def send_message(self, chat_id, text, message_thread_id=None, disable_notification=None,
                           reply_markup=None, **kw):
        if self.refused < self.retries:
            self.refused += 1
            raise RetryAfter(self.retry_after)
        self.sent.append((chat_id, text, message_thread_id))
        self.silent.append(bool(disable_notification))
        self.markups.append(reply_markup)
        return SimpleNamespace(message_id=100 + len(self.sent))

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.photos.append((chat_id, caption, kw.get("message_thread_id")))
        return SimpleNamespace(photo=[SimpleNamespace(file_id=f"file-{len(self.photos)}")])

    async def send_poll(self, chat_id, question, options, **kw):
        self.polls.append((chat_id, kw.get("message_thread_id")))
        return SimpleNamespace(message_id=1, poll=SimpleNamespace(id="poll-1"))

    async def stop_poll(self, chat_id, message_id):
        return SimpleNamespace(id="poll-1")

    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None):
        if self.fail_edit_with:
            raise self.fail_edit_with
        self.edits.append((chat_id, text, message_id))
        self.markups.append(reply_markup)

    async def delete_message(self, chat_id, message_id):
        if self.fail_delete_with:
            raise self.fail_delete_with
        self.deleted.append(message_id)

    async def pin_chat_message(self, chat_id, message_id, disable_notification=None):
        self.pins.append(message_id)

    async def unpin_chat_message(self, chat_id, message_id):
        self.unpinned.append(message_id)
        self.pins = [pinned for pinned in self.pins if pinned != message_id]


class FakeStore:
    def __init__(self, state=None, links=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.links = dict(LINKS if links is None else links)
        self.kv = {}
        self.wars = []
        self.writes = []
        self.whispers = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.writes.append(kind)
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def bot_by_alias(self, alias):
        return None

    async def links_for_players(self, tags):
        return {tag: self.links[tag] for tag in tags if tag in self.links}

    async def links_by_user(self, user_id):
        return [row for row in self.links.values() if row.user_id == user_id]

    async def update_link(self, row):
        return row

    async def set_link_whisper(self, user_id, tag, value):
        self.whispers.append((user_id, tag, value))
        row = self.links.get(tag)
        if row is not None and row.user_id == user_id:
            row.whisper = value

    async def add_war(self, alias, key, ended, record):
        self.wars.append(record)
        return True

    async def wars_since(self, alias, since):
        return []

    async def mark_failure(self, alias):
        return {"failures": 1, "active": True}

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def kv_del(self, key):
        self.kv.pop(key, None)


class FakeCoc:
    def __init__(self, players=None):
        self.players = players or {}

    async def player(self, tag):
        return copy.deepcopy(self.players.get(tag)), None


def supervisor_for(bot):
    return SimpleNamespace(bot=lambda alias: bot if alias == ALIAS else None,
                           running=lambda: [ALIAS], default_alias=ALIAS, owner_bot=lambda: bot)


def setup(stored, state=None, links=None, now=NOW, coc=None, bot=None):
    store = FakeStore(state=state, links=links)
    bot = bot or FakeBot()
    poller = Poller(supervisor_for(bot), store, coc)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(stored, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.quiet = settings_mod.is_quiet(t.settings, now)
    t.members = copy.deepcopy(MEMBERS)
    t.season = scoring.empty_season("2026-09")
    return poller, store, bot, t


def routed(stored, event, to, intensity=None):
    doc = settings_mod.migrate(stored)
    doc["routes"][event] = {"to": to, "intensity": intensity}
    return doc


def board_lines(t, pack):
    return boards.lines_of(t.boards, pack)


async def play(poller, store, t, steps, kind="war", day=None):
    key = "war" if kind == "war" else "cwl_war"
    for old, new in zip(steps, steps[1:]):
        t.chunks, t.threads = [], {}
        t.named, t.nudges = [], []
        await store.set_state(CLAN.alias, key, old)
        await poller.track_war(t, copy.deepcopy(new), kind, day)
        await poller.flush(t)


def war_text(old, new, kind="war", day=None, now=NOW):
    visible = [e for e in events_mod.war_events(old, new) if e["type"] != "war_end"]
    return render.render_war_events(IT, TZ, visible, new, kind, day, now)


def end_text(new, kind="war", day=None):
    return render.render_war_end(IT, new, events_mod.war_result(new), kind, day,
                                 warstats.war_defense(new))


def group_sent(bot):
    return [row for row in bot.sent if row[0] == CLAN.chat_id]


def test_futuro_puts_the_war_on_the_board_and_keeps_only_the_end_in_chat():
    poller, store, bot, t = setup(FUTURO)
    asyncio.run(play(poller, store, t, [PREP, STARTED, ATTACKED, ENDED]))
    assert group_sent(bot) == []
    assert board_lines(t, "wars") == [
        "14:00 · " + render.board_body(war_text(PREP, STARTED)),
        "14:00 · " + render.board_body(war_text(STARTED, ATTACKED)),
    ]
    assert bot.photos == [(CLAN.chat_id, end_text(ENDED), None)]
    assert [kind for kind, _ in feed_rows(store, 7)] == ["war.warning"]
    assert [kind for kind, _ in feed_rows(store, 8)] == ["war.warning"]
    assert store.state[(CLAN.alias, "war")]["state"] == "warEnded" and store.wars


def test_the_war_clan_preset_keeps_every_fight_on_the_board():
    poller, store, bot, t = setup(settings_mod.apply_preset(FUTURO, "war_clan"))
    asyncio.run(play(poller, store, t, [STARTED, ATTACKED]))
    assert bot.sent == []
    assert board_lines(t, "wars") == ["14:00 · " + render.board_body(war_text(STARTED, ATTACKED))]


def test_the_casual_preset_drops_the_fights_and_keeps_start_and_end():
    poller, store, bot, t = setup(settings_mod.apply_preset(FUTURO, "casual_clan"))
    asyncio.run(play(poller, store, t, [PREP, STARTED, ATTACKED, ENDED]))
    assert group_sent(bot) == []
    assert board_lines(t, "wars") == ["14:00 · " + render.board_body(war_text(PREP, STARTED))]
    assert bot.photos == [(CLAN.chat_id, end_text(ENDED), None)]


def test_the_leaders_only_preset_writes_to_the_feed_of_the_managers():
    poller, store, bot, t = setup(settings_mod.apply_preset(FUTURO, "leaders_only"))
    asyncio.run(play(poller, store, t, [PREP, STARTED]))
    assert bot.sent == []
    assert [text for _, text in feed_rows(store, 7)] == [war_text(PREP, STARTED)]
    assert [text for _, text in feed_rows(store, 8)] == [war_text(PREP, STARTED)]


def test_a_topic_destination_sends_the_urgent_into_the_thread():
    stored = routed(FUTURO, "war.last_call", "topic")
    stored["topics"] = {"wars": 42}
    poller, store, bot, t = setup(stored)
    asyncio.run(poller.dispatch(t, "war.last_call", lambda L: "ultima chiamata"))
    asyncio.run(poller.flush(t))
    assert bot.sent == [(CLAN.chat_id, "ultima chiamata", 42)]


def test_a_topic_without_a_thread_falls_back_to_the_group():
    poller, store, bot, t = setup(routed(FUTURO, "war.last_call", "topic"))
    asyncio.run(poller.dispatch(t, "war.last_call", lambda L: "ultima chiamata"))
    asyncio.run(poller.flush(t))
    assert bot.sent == [(CLAN.chat_id, "ultima chiamata", None)]


def test_the_wars_pack_turned_off_says_nothing():
    stored = settings_mod.migrate(FUTURO)
    stored["packs"]["wars"] = False
    poller, store, bot, t = setup(stored)
    asyncio.run(play(poller, store, t, [PREP, STARTED, ATTACKED, ENDED]))
    assert bot.sent == []
    assert store.wars and store.state[(CLAN.alias, "war")]["state"] == "warEnded"


def test_an_event_routed_off_leaves_the_others_on_the_board():
    poller, store, bot, t = setup(routed(FUTURO, "war.attack", "off"))
    asyncio.run(play(poller, store, t, [STARTED, ATTACKED]))
    defenses = [e for e in events_mod.war_events(STARTED, ATTACKED) if e["type"] == "defense"]
    assert bot.sent == []
    assert board_lines(t, "wars") == ["14:00 · " + render.board_body(
        render.render_war_events(IT, TZ, defenses, ATTACKED, "war", None, NOW))]


def test_the_cwl_round_follows_the_cwl_pack():
    stored = settings_mod.migrate(FUTURO)
    stored["packs"]["cwl"] = False
    poller, store, bot, t = setup(stored)
    asyncio.run(play(poller, store, t, [STARTED, ATTACKED], kind="cwl", day=3))
    assert bot.sent == []
    stored["packs"]["cwl"] = True
    poller, store, bot, t = setup(stored)
    asyncio.run(play(poller, store, t, [STARTED, ATTACKED], kind="cwl", day=3))
    assert bot.sent == []
    assert board_lines(t, "cwl") == ["14:00 · " + render.board_body(war_text(STARTED, ATTACKED, "cwl", 3))]


SOON = events_mod.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]}))


def reminder_run(stored, links=None):
    poller, store, bot, t = setup(stored, links=links, now=LATE)
    asyncio.run(play(poller, store, t, [SOON, SOON]))
    return store, bot, t


def feed_chats(store, key):
    return [uid for uid in (7, 8, 9)
            if any(IT.t(key) in text for _, text in feed_rows(store, uid))]


def test_the_mentions_of_today_stay_in_the_group_and_the_personal_reminders_go_to_the_feed():
    store, bot, _ = reminder_run(FUTURO)
    group = [text for chat, text, _ in bot.sent if chat == CLAN.chat_id]
    assert len(group) == 1 and 'tg://user?id=7' in group[0] and 'tg://user?id=9' in group[0]
    assert feed_chats(store, "dm.title") == [7, 8, 9]
    assert IT.t("last_call.title") in group[0]


def test_the_old_private_only_mentions_become_mentions_in_the_group():
    stored = dict(settings_mod.migrate(FUTURO), mentions="dm")
    assert settings_mod.migrate(stored)["mentions"] == "group"
    store, bot, _ = reminder_run(stored)
    group = [text for chat, text, _ in bot.sent if chat == CLAN.chat_id]
    assert len(group) == 1 and 'tg://user?id=7' in group[0] and "Luigi" in group[0]
    assert feed_chats(store, "dm.title") == [7, 8, 9]


def test_mentions_never_sends_no_mention_and_no_personal_reminder():
    store, bot, _ = reminder_run(dict(settings_mod.migrate(FUTURO), mentions="never"))
    assert [chat for chat, _, _ in bot.sent if chat == CLAN.chat_id] == [CLAN.chat_id]
    assert "tg://user" not in bot.sent[0][1]
    assert feed_chats(store, "dm.title") == []
    assert IT.t("last_call.title") in bot.sent[0][1]


def test_a_person_with_two_villages_is_mentioned_once():
    members = [{"tag": "#A", "name": "Alex"}, {"tag": "#B", "name": "AlexMini"}]
    links = {"#A": link("#A", 7, "Alex", dm=False), "#B": link("#B", 7, "AlexMini", dm=False)}
    names = link_names(members, links)
    assert names["#A"] == '<a href="tg://user?id=7">Alex</a> (AlexMini)'
    assert names["#B"] == "AlexMini"


def test_the_villages_of_a_person_are_listed_in_clan_order_and_the_others_stay_alone():
    members = [{"tag": "#A", "name": "Alex"}, {"tag": "#P2", "name": "Luigi"},
               {"tag": "#B", "name": "AlexMini"}, {"tag": "#C", "name": "AlexNano"},
               {"tag": "#P9", "name": "Wario"}]
    links = dict(LINKS, **{"#A": link("#A", 7, "Alex"), "#B": link("#B", 7, "AlexMini"),
                           "#C": link("#C", 7, "AlexNano")})
    names = link_names(members, links)
    assert names["#A"] == '<a href="tg://user?id=7">Alex</a> (AlexMini, AlexNano)'
    assert names["#B"] == "AlexMini" and names["#C"] == "AlexNano"
    assert names["#P2"] == '<a href="tg://user?id=8">Luigi</a>'
    assert "#P9" not in names


def test_a_member_who_closed_the_private_messages_reads_it_in_the_feed_all_the_same():
    store, bot, _ = reminder_run(FUTURO, links=dict(LINKS, **{"#P2": link("#P2", 8, "Luigi", dm=False)}))
    assert [chat for chat, _, _ in bot.sent] == [CLAN.chat_id]
    assert feed_chats(store, "dm.title") == [7, 8, 9]


def test_the_reminder_routed_to_the_member_skips_the_group_card():
    store, bot, _ = reminder_run(routed(FUTURO, "war.reminder", "member_dm"))
    assert [chat for chat, text, _ in bot.sent
            if chat == CLAN.chat_id and IT.t("reminder.1h.title") in text] == []
    assert feed_chats(store, "dm.title") == [7, 8, 9]


def test_the_night_queue_and_the_digest_work_for_a_topic():
    hour = datetime.now(timezone.utc).hour
    stored = routed(dict(FUTURO, tz="UTC", quiet=[(hour - 1) % 24, (hour + 2) % 24], night="digest"),
                    "war.reminder", "topic")
    stored["topics"] = {"wars": 42}
    store = FakeStore(state={(CLAN.alias, "settings"): stored})
    poller = Poller(supervisor_for(FakeBot()), store, None)
    asyncio.run(poller.deliver(CLAN, "manca un'ora", "war.reminder"))
    assert store.state[(CLAN.alias, "queue_topics")]["42"] == ["manca un'ora"]
    poller, store, bot, t = setup(stored, state=store.state, now=NOW)
    t.quiet = False
    asyncio.run(poller.flush(t))
    chat, text, thread = next(row for row in bot.sent if row[2] == 42)
    assert (chat, thread) == (CLAN.chat_id, 42)
    assert IT.t("quiet.digest.title") in text and "manca un'ora" in text
    assert (CLAN.alias, "queue_topics") not in store.state


def test_an_urgent_reminder_reaches_the_thread_even_at_night():
    stored = routed(dict(FUTURO, quiet=[23, 7]), "war.reminder", "topic")
    stored["topics"] = {"wars": 42}
    stored["mentions"] = "never"
    soon = events_mod.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]},
                                            end="20260912T000000.000Z"))
    poller, store, bot, t = setup(stored, now=NIGHT)
    asyncio.run(play(poller, store, t, [soon, soon]))
    assert [(chat, thread) for chat, _, thread in bot.sent if chat == CLAN.chat_id] == [(CLAN.chat_id, 42)]
    urgent = next(text for _, text, thread in bot.sent if thread == 42)
    assert IT.t("last_call.title") in urgent
    assert urgent not in (store.state.get((CLAN.alias, "queue_topics")) or {}).get("42", [])


def test_load_settings_saves_the_migrated_document_once():
    store = FakeStore(state={(CLAN.alias, "settings"): FUTURO})
    poller = Poller(supervisor_for(FakeBot()), store, None)
    t = Tick(CLAN, NOW)
    asyncio.run(poller.load_settings(t, None))
    saved = store.state[(CLAN.alias, "settings")]
    assert saved["version"] == settings_mod.SCHEMA_VERSION
    assert saved["mentions"] == "group" and saved["setup_done"] is True
    assert "defenses" not in saved and store.writes == ["settings"]
    asyncio.run(poller.load_settings(t, None))
    assert store.writes == ["settings"]


def test_the_leader_report_reaches_the_feed_of_the_managers_and_can_be_turned_off():
    poller, store, bot, t = setup(FUTURO, now=MONDAY)
    asyncio.run(poller.leader_report(t))
    asyncio.run(poller.flush(t))
    assert bot.sent == []
    assert [kind for kind, _ in feed_rows(store, 7)] == ["members.report"]
    assert [kind for kind, _ in feed_rows(store, 8)] == ["members.report"]
    poller, store, bot, t = setup(routed(FUTURO, "members.report", "off"), now=MONDAY)
    asyncio.run(poller.leader_report(t))
    asyncio.run(poller.flush(t))
    assert bot.sent == [] and store.kv == {}


def test_the_board_follows_its_destination():
    stored = routed(FUTURO, "war.board", "topic")
    stored["topics"] = {"wars": 42}
    poller, store, bot, t = setup(stored, state={(CLAN.alias, "war"): ATTACKED})
    asyncio.run(poller.update_boards(t))
    assert [(chat, thread) for chat, _, thread in bot.sent] == [(CLAN.chat_id, None)]
    scheda = render.board_body(render.render_board(IT, TZ, ATTACKED, "war", None, NOW))
    assert scheda in boards.lines_of(stored_boards(store), "wars")[0]
    poller, store, bot, t = setup(routed(FUTURO, "war.board", "off"), state={(CLAN.alias, "war"): ATTACKED})
    asyncio.run(poller.update_boards(t))
    assert [(chat, thread) for chat, _, thread in bot.sent] == [(CLAN.chat_id, None)]
    assert boards.lines_of(stored_boards(store), "wars") == []


async def board_round(poller, t, events):
    for event, text in events:
        await poller.dispatch(t, event, lambda L, text=text: text)
    await poller.flush(t)
    await poller.update_boards(t)


def stored_boards(store):
    return store.state.get((CLAN.alias, "boards"))


def test_the_board_mode_edits_one_pinned_message_instead_of_sending():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO),
                                  state={(CLAN.alias, "boards"): {"message_id": 555,
                                                                  "members": {"lines": []}}})
    asyncio.run(board_round(poller, t, [("members.movement", "Alex è entrato nel clan"),
                                        ("members.movement", "Bruno ha lasciato il clan")]))
    assert bot.sent == []
    assert len(bot.edits) == 1
    chat, text, message_id = bot.edits[0]
    assert (chat, message_id) == (CLAN.chat_id, 555)
    assert "Alex" not in text and IT.t("board.title.members") not in text
    righe = boards.lines_of(stored_boards(store), "members")
    assert "Alex" in righe[0] and "Bruno" in righe[1]
    assert boards.dirty(stored_boards(store)) == []


def test_a_new_board_is_created_and_pinned():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    asyncio.run(board_round(poller, t, [("members.movement", "Alex è entrato nel clan")]))
    assert [(chat, thread) for chat, _, thread in bot.sent] == [(CLAN.chat_id, None)]
    assert bot.pins == [101] and bot.edits == []
    assert boards.message_id(stored_boards(store)) == 101


def test_a_deleted_board_is_recreated_and_pinned():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO),
                                  state={(CLAN.alias, "boards"): {"message_id": 999,
                                                                  "members": {"lines": []}}})
    bot.fail_edit_with = BadRequest("message to edit not found")
    asyncio.run(board_round(poller, t, [("members.movement", "Alex è entrato nel clan")]))
    assert len(bot.sent) == 1 and bot.pins == [101]
    assert boards.message_id(stored_boards(store)) == 101


def test_the_urgent_chunks_still_reach_the_chat_in_board_mode():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    asyncio.run(board_round(poller, t, [("war.reminder", "Manca un'ora, Mario deve attaccare"),
                                        ("war.start", "La guerra è iniziata")]))
    assert [text for _, text, _ in bot.sent][0] == "Manca un'ora, Mario deve attaccare"
    assert len(bot.sent) == 2 and "La guerra è iniziata" not in bot.sent[1][1]
    assert boards.lines_of(stored_boards(store), "wars") == ["14:00 · La guerra è iniziata"]


def test_the_war_board_and_its_history_share_the_wars_section():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO), state={(CLAN.alias, "war"): ATTACKED})
    asyncio.run(board_round(poller, t, [("war.start", "La guerra è iniziata")]))
    assert len(bot.sent) == 1 and bot.pins == [101]
    assert IT.t("board.title.wars") not in bot.sent[0][1]
    righe = boards.lines_of(stored_boards(store), "wars")
    assert "La guerra è iniziata" in righe[0]
    assert render.board_body(render.render_board(IT, TZ, ATTACKED, "war", None, NOW)) in righe[1]
    assert boards.dirty(stored_boards(store)) == []


def test_the_wars_section_stands_on_its_own_when_the_war_board_is_off():
    stored = settings_mod.migrate(routed(FUTURO, "war.board", "off"))
    poller, store, bot, t = setup(stored, state={(CLAN.alias, "war"): ATTACKED})
    asyncio.run(board_round(poller, t, [("war.start", "La guerra è iniziata")]))
    assert [(chat, thread) for chat, _, thread in bot.sent] == [(CLAN.chat_id, None)]
    righe = boards.lines_of(stored_boards(store), "wars")
    assert righe == ["14:00 · La guerra è iniziata"]
    assert render.board_body(render.render_board(IT, TZ, ATTACKED, "war", None, NOW)) not in righe[0]
    assert bot.pins == [101]
    assert boards.dirty(stored_boards(store)) == []
    assert boards.message_id(stored_boards(store)) == 101


def test_the_pinned_board_takes_over_the_standalone_wars_board():
    poller, store, bot, t = setup(
        settings_mod.migrate(FUTURO),
        state={(CLAN.alias, "war"): ATTACKED,
               (CLAN.alias, "boards"): {"wars": {"message_id": 555, "lines": ["12:00 · La guerra è iniziata"]}}})
    bot.pins.append(555)
    asyncio.run(board_round(poller, t, [("war.attack", "Mario ha fatto 3 stelle")]))
    assert bot.pins == [101] and bot.deleted == [555]
    assert [message_id for _, _, message_id in bot.edits] == []
    righe = boards.lines_of(stored_boards(store), "wars")
    assert render.board_body(render.render_board(IT, TZ, ATTACKED, "war", None, NOW)) in righe[-1]
    assert "La guerra è iniziata" in righe[0] and "Mario ha fatto 3 stelle" in righe[1]
    assert boards.message_of(stored_boards(store), "wars") is None
    assert boards.message_id(stored_boards(store)) == 101
    assert boards.dirty(stored_boards(store)) == []


def test_the_staff_feed_reaches_the_elders_and_above():
    poller, store, bot, t = setup(routed(FUTURO, "members.movement", "staff_dm"))
    t.members = {"#P1": {"name": "Mario", "role": "leader"},
                 "#P2": {"name": "Luigi", "role": "member"},
                 "#P3": {"name": "Peach", "role": "admin"}}
    asyncio.run(board_round(poller, t, [("members.movement", "Alex è entrato nel clan")]))
    assert [uid for uid in (7, 8, 9) if feed_rows(store, uid)] == [7, 9]


def test_a_movement_asked_in_private_to_the_member_reaches_the_board_instead_of_no_one():
    poller, store, bot, t = setup(routed(FUTURO, "members.movement", "member_dm"))
    asyncio.run(board_round(poller, t, [("members.movement", "Alex è entrato nel clan")]))
    assert boards.lines_of(stored_boards(store), "members") == ["14:00 · Alex è entrato nel clan"]


def test_the_leader_report_asked_in_private_to_the_member_still_reaches_the_managers():
    poller, store, bot, t = setup(routed(FUTURO, "members.report", "member_dm"), now=MONDAY)
    asyncio.run(poller.leader_report(t))
    asyncio.run(poller.flush(t))
    assert bot.sent == []
    assert [uid for uid in (7, 8, 9) if feed_rows(store, uid)] == [7, 8]


def test_the_board_lines_are_trimmed_to_the_telegram_limit():
    state = {}
    for i in range(400):
        state = boards.append(state, "members", [f"riga {i} " + "x" * 60], NOW, TZ)
    text = boards.render(IT, "members", state)
    assert len(text) <= MessageLimit.MAX_TEXT_LENGTH
    assert "riga 399" in text and "riga 0 " not in text


def test_a_board_row_drops_the_head_of_the_card_and_keeps_only_the_body():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    card = render.card("👥", "MOVIMENTI NEL CLAN", "Alex è entrato nel clan\nBruno ha lasciato il clan")
    asyncio.run(board_round(poller, t, [("members.movement", card)]))
    text = bot.sent[0][1]
    assert "MOVIMENTI NEL CLAN" not in text and IT.t("board.title.members") not in text
    assert boards.lines_of(stored_boards(store), "members") == [
        "14:00 · Alex è entrato nel clan\nBruno ha lasciato il clan"]


def test_the_board_keeps_more_history_now_that_the_head_is_gone():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    card = render.card("👥", "MOVIMENTI NEL CLAN", "Alex è entrato nel clan")
    asyncio.run(board_round(poller, t, [("members.movement", card)] * 3))
    righe = boards.lines_of(stored_boards(store), "members")
    assert righe == ["14:00 · Alex è entrato nel clan"] * 3


def test_the_body_of_a_card_survives_whole_even_when_it_is_quoted():
    body = render.quote("🏆 <b>MVP</b> · Mario\n🏹 <b>Cecchino</b> · Luigi")
    assert render.board_body(render.card("🏆", "FINE STAGIONE", body)) == body
    assert render.board_body(render.card("👥", "MOVIMENTI NEL CLAN")) == "👥 <b>MOVIMENTI NEL CLAN</b>"
    assert render.board_body("riga secca") == "riga secca"
    assert render.board_body("") == ""


def test_a_board_line_carries_the_local_hour_and_an_empty_board_says_so():
    state = boards.append({}, "members", ["Alex è entrato nel clan"], NOW, TZ)
    assert boards.render(IT, "members", state).endswith("14:00 · Alex è entrato nel clan")
    assert boards.dirty(state) == ["members"]
    assert IT.t("board.empty") in boards.render(IT, "members", {})
    done = boards.published(state, "members", 42)
    assert boards.dirty(done) == [] and boards.message_of(done, "members") == 42


def sweep_player_json(name, th=14):
    return {
        "tag": "#P1", "name": name, "townHallLevel": th, "warStars": 100, "trophies": 5000,
        "warPreference": "in",
        "achievements": [{"name": "Gold Grab", "value": 10}],
        "heroes": [{"name": "Barbarian King", "level": 50, "village": "home"}],
    }


def sweep_run(stored, links=None):
    players = {"tags": {"#P1": player_snapshot(sweep_player_json("Mario"))}, "cursor": 0, "out_since": {}}
    coc = FakeCoc({"#P1": sweep_player_json("Mario", th=15)})
    poller, store, bot, t = setup(stored, state={(CLAN.alias, "players"): players}, links=links, coc=coc)
    t.members = {"#P1": MEMBERS["#P1"]}
    asyncio.run(poller.sweep_players(t, per_tick=1))
    asyncio.run(poller.flush(t))
    return store, bot, t


def test_the_achievements_reach_the_feed_of_the_member_when_they_are_routed_to_the_person():
    store, bot, _ = sweep_run(routed(FUTURO, "members.achievement", "member_dm"))
    assert bot.sent == []
    assert feed_chats(store, "ach.title") == [7]
    assert feed_chats(store, "badge.title") == [7]


def test_the_achievements_stay_on_the_board_by_default():
    store, bot, t = sweep_run(FUTURO)
    assert bot.sent == []
    assert any("Mario" in line for line in board_lines(t, "members"))
    assert feed_chats(store, "badge.title") == [7]


def test_the_feed_of_the_night_keeps_the_language_of_the_member():
    stored = routed(dict(FUTURO, quiet=[23, 7]), "members.achievement", "member_dm")
    links = {"#P1": link("#P1", 7, "Mario", lang="de")}
    players = {"tags": {"#P1": player_snapshot(sweep_player_json("Mario"))}, "cursor": 0, "out_since": {}}
    coc = FakeCoc({"#P1": sweep_player_json("Mario", th=15)})
    poller, store, bot, t = setup(stored, state={(CLAN.alias, "players"): players}, links=links,
                                  coc=coc, now=NIGHT)
    t.members = {"#P1": MEMBERS["#P1"]}
    asyncio.run(poller.sweep_players(t, per_tick=1))
    asyncio.run(poller.flush(t))
    assert bot.sent == []
    text = next(text for _, text in feed_rows(store, 7) if DE.t("ach.title") in text)
    assert IT.t("ach.title") not in text


def test_the_language_of_the_member_wins_over_the_one_of_the_clan():
    store = FakeStore()
    conf = settings_mod.effective(FUTURO, None)
    assert asyncio.run(member_locale(store, link("#P2", 8, "Luigi", lang="de"), conf)).code == "de"
    assert asyncio.run(member_locale(store, link("#P2", 8, "Luigi"), conf)).code == "it"


def test_the_personal_reminder_in_the_feed_speaks_the_language_of_the_member():
    links = dict(LINKS, **{"#P2": link("#P2", 8, "Luigi", lang="de")})
    store, bot, _ = reminder_run(FUTURO, links=links)
    missing = {m["tag"]: m for m in events_mod.missing_attackers(SOON)}
    assert [text for _, text in feed_rows(store, 8)] == [
        render.dm_reminder(DE, TZ, SOON, missing["#P2"], "war", None, LATE, {})]
    assert [text for _, text in feed_rows(store, 9)] == [
        render.dm_reminder(IT, TZ, SOON, missing["#P3"], "war", None, LATE, {})]
    group = [text for chat, text, _ in bot.sent if chat == CLAN.chat_id]
    assert len(group) == 1 and DE.t("dm.title") not in group[0]


def test_the_achievements_in_the_feed_speak_the_language_of_the_member():
    links = dict(LINKS, **{"#P1": link("#P1", 7, "Mario", lang="de")})
    store, _bot, _t = sweep_run(routed(FUTURO, "members.achievement", "member_dm"), links=links)
    achievements = [text for _, text in feed_rows(store, 7) if DE.t("ach.title") in text]
    assert len(achievements) == 1 and IT.t("ach.title") not in achievements[0]


def test_the_leader_report_speaks_the_language_of_each_manager():
    links = dict(LINKS, **{"#P2": link("#P2", 8, "Luigi", lang="de")})
    poller, store, bot, t = setup(FUTURO, now=MONDAY, links=links)
    asyncio.run(poller.leader_report(t))
    asyncio.run(poller.flush(t))
    assert [text for _, text in feed_rows(store, 7)] == [render.leader_report(IT, CLAN, [], [], [], idle=[])]
    assert [text for _, text in feed_rows(store, 8)] == [render.leader_report(DE, CLAN, [], [], [], idle=[])]


def test_the_leaders_only_preset_leaves_no_board_and_no_poll_anywhere():
    stored = settings_mod.apply_preset(FUTURO, "leaders_only")
    poller, store, bot, t = setup(stored, state={(CLAN.alias, "war"): ATTACKED})
    asyncio.run(poller.update_boards(t))
    assert len(bot.sent) == 1
    assert boards.lines_of(stored_boards(store), "wars") == []
    poller, store, bot, t = setup(stored)
    asyncio.run(play(poller, store, t, [PREP, STARTED]))
    assert bot.polls == []
    assert settings_mod.route(t.settings, "war.board") == ("off", None)
    assert settings_mod.route(t.settings, "challenges.poll") == ("off", None)


def test_a_board_and_a_poll_set_in_private_go_back_to_the_group():
    stored = routed(FUTURO, "war.board", "leaders_dm")
    stored["routes"]["challenges.poll"] = {"to": "leaders_dm", "intensity": None}
    poller, store, bot, t = setup(stored, state={(CLAN.alias, "war"): ATTACKED})
    asyncio.run(poller.update_boards(t))
    assert [(chat, thread) for chat, _, thread in bot.sent] == [(CLAN.chat_id, None)]
    poller, store, bot, t = setup(stored)
    asyncio.run(play(poller, store, t, [PREP, STARTED]))
    assert bot.polls == [(CLAN.chat_id, None)]


def test_the_end_of_a_round_leaves_at_once_at_night_in_war_and_in_cwl():
    stored = dict(FUTURO, quiet=[23, 7])
    poller, store, bot, t = setup(stored, now=NIGHT)
    asyncio.run(play(poller, store, t, [ATTACKED, ENDED]))
    assert group_sent(bot) == []
    assert bot.photos == [(CLAN.chat_id, end_text(ENDED), None)]
    assert feed_chats(store, "warn.title") == [7, 8]
    poller, store, bot, t = setup(stored, now=NIGHT)
    asyncio.run(play(poller, store, t, [ATTACKED, ENDED], kind="cwl", day=3))
    assert bot.sent == []
    assert bot.photos == [(CLAN.chat_id, end_text(ENDED, "cwl", 3), None)]
    assert (CLAN.alias, "queue") not in store.state
    poller, store, bot, t = setup(stored, now=NIGHT)
    asyncio.run(play(poller, store, t, [STARTED, ATTACKED], kind="cwl", day=3))
    assert (CLAN.alias, "queue") not in store.state
    assert board_lines(t, "cwl") == ["01:30 · " + render.board_body(
        war_text(STARTED, ATTACKED, "cwl", 3, now=NIGHT))]
    assert [text for _, text in bot.sent] == [] or IT.t("midway.title") in bot.sent[0][1]


def family_setup(stored, kv=None, families=None):
    store = FakeStore(state={(CLAN.alias, "settings"): stored,
                             (CLAN.alias, views.KIND): {views.FAMILY: True}})
    store.kv.update(kv or {})

    async def family_clans(alias):
        return [CLAN]

    async def family_of_clan(alias):
        return FAMILY if alias == CLAN.alias else None

    store.family_clans = family_clans
    store.family_of_clan = family_of_clan
    bot = FakeBot()
    return Poller(supervisor_for(bot), store, None), store, bot


def packs_off(*names):
    stored = settings_mod.migrate(FUTURO)
    for name in names:
        stored["packs"][name] = False
    return stored


def test_the_weekly_family_digest_follows_the_family_pack():
    poller, store, bot = family_setup(FUTURO)
    asyncio.run(poller.family_digest(FAMILY, FAMILY_MONDAY))
    assert [chat for chat, _, _ in bot.sent] == [FAMILY.chat_id]
    poller, store, bot = family_setup(packs_off("family"))
    asyncio.run(poller.family_digest(FAMILY, FAMILY_MONDAY))
    assert bot.sent == []
    assert f"fam:{FAMILY.alias}:digest" not in store.kv


def test_the_recruiting_board_follows_the_recruitment_pack():
    poller, store, bot = family_setup(FUTURO)
    asyncio.run(poller.family_recruit(FAMILY, NOW))
    assert [chat for chat, _, _ in bot.sent] == [FAMILY.chat_id]
    assert bot.pins and store.kv[f"fam:{FAMILY.alias}:recruit"]["message_id"]
    poller, store, bot = family_setup(packs_off("recruitment"))
    asyncio.run(poller.family_recruit(FAMILY, NOW))
    assert bot.sent == [] and bot.pins == []
    assert f"fam:{FAMILY.alias}:recruit" not in store.kv


def moves_kv(now):
    return {f"fam:{FAMILY.alias}:moves": {
        "#P4": {"from": "clan-2", "from_name": "Altro", "name": "Toad", "ts": now.timestamp()},
    }}


def transfer_run(stored):
    poller, store, bot = family_setup(stored, kv=moves_kv(NOW))
    t = Tick(CLAN, NOW)
    t.settings = settings_mod.effective(stored, None)
    t.L = i18n.locale(t.settings["lang"])
    asyncio.run(poller.track_moves(t, [{"type": "join", "tag": "#P4", "name": "Toad"}]))
    return bot, t


OTHER = SimpleNamespace(alias="clan-2", chat_id=303, tag="#CLAN2", name="Altro", bot_alias=ALIAS)


def departure_run(other_stored):
    poller, store, bot = family_setup(settings_mod.migrate(FUTURO), kv=moves_kv(NOW))
    store.state[(OTHER.alias, "settings")] = copy.deepcopy(other_stored)

    async def clan_by_alias(alias):
        return {CLAN.alias: CLAN, OTHER.alias: OTHER}.get(alias)

    store.clan_by_alias = clan_by_alias
    t = Tick(CLAN, NOW)
    t.settings = settings_mod.effective(settings_mod.migrate(FUTURO), None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    asyncio.run(poller.track_moves(t, [{"type": "join", "tag": "#P4", "name": "Toad"}]))
    return store, bot


def test_the_clan_of_departure_gets_the_transfer_on_its_section():
    store, bot = departure_run(settings_mod.migrate(FUTURO))
    assert OTHER.chat_id not in [chat for chat, _, _ in bot.sent]
    righe = boards.lines_of(store.state[(OTHER.alias, "boards")], "family")
    assert len(righe) == 1 and "Toad" in righe[0]
    assert boards.dirty(store.state[(OTHER.alias, "boards")]) == ["family"]


def test_the_family_copy_of_a_transfer_follows_the_family_pack():
    bot, t = transfer_run(settings_mod.migrate(FUTURO))
    assert [chat for chat, _, _ in bot.sent] == [FAMILY.chat_id]
    assert render.transfer_card(IT, "Toad", "Altro", CLAN.name) == bot.sent[0][1]
    assert len(boards.lines_of(t.boards, "family")) == 1
    bot, t = transfer_run(packs_off("family"))
    assert bot.sent == [] and t.boards is None


def notice_run(stored, links=None):
    store = FakeStore(state={(CLAN.alias, "settings"): stored, (CLAN.alias, "members"): MEMBERS},
                      links=links)
    bot = FakeBot()
    poller = Poller(supervisor_for(bot), store, None)
    asyncio.run(poller.deliver(CLAN, "trasferimento", "family.transfer"))
    return store, bot


def leaders_dm_now(night_mode):
    hour = datetime.now(timezone.utc).hour
    stored = dict(FUTURO, tz="UTC", quiet=[(hour - 1) % 24, (hour + 2) % 24], night=night_mode)
    return routed(stored, "family.transfer", "leaders_dm")


def test_a_notice_for_the_leaders_reaches_the_feed_of_every_manager():
    store, bot = notice_run(routed(FUTURO, "family.transfer", "leaders_dm"))
    assert bot.sent == []
    assert feed_rows(store, 7) == [("family.transfer", "trasferimento")]
    assert feed_rows(store, 8) == [("family.transfer", "trasferimento")]
    assert feed_rows(store, 9) == []


def test_a_notice_for_the_leaders_at_night_reaches_the_feed_all_the_same():
    store, bot = notice_run(leaders_dm_now("digest"))
    assert bot.sent == []
    assert feed_rows(store, 7) == [("family.transfer", "trasferimento")]
    assert (CLAN.alias, "queue_dm") not in store.state


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [(row["kind"], row["text"]) for row in saved.get("rows") or []]


async def one_event(poller, t, event, **kw):
    await poller.dispatch(t, event, lambda L: "una riga", **kw)
    await poller.flush(t)


def test_an_event_of_a_member_reaches_the_feed_of_who_linked_the_village():
    poller, store, bot, t = setup(FUTURO)
    asyncio.run(one_event(poller, t, "members.progress", member_tag="#P1"))
    assert bot.sent == []
    assert feed_rows(store, 7) == [("members.progress", "una riga")]


def test_an_event_of_a_member_who_did_not_link_goes_nowhere():
    poller, store, bot, t = setup(FUTURO, links={})
    asyncio.run(one_event(poller, t, "members.progress", member_tag="#P1"))
    assert bot.sent == [] and store.kv == {}


def test_an_event_for_the_leaders_reaches_the_feed_of_every_manager():
    poller, store, bot, t = setup(routed(FUTURO, "members.movement", "leaders_dm"))
    asyncio.run(one_event(poller, t, "members.movement"))
    assert bot.sent == []
    assert feed_rows(store, 7) == [("members.movement", "una riga")]
    assert feed_rows(store, 8) == [("members.movement", "una riga")]
    assert feed_rows(store, 9) == []


def test_the_staff_feed_takes_in_the_elders_too():
    poller, store, bot, t = setup(routed(FUTURO, "members.movement", "staff_dm"))
    t.members = {"#P1": {"name": "Mario", "role": "leader"},
                 "#P3": {"name": "Peach", "role": "admin"}}
    asyncio.run(one_event(poller, t, "members.movement"))
    assert bot.sent == []
    assert feed_rows(store, 7) == [("members.movement", "una riga")]
    assert feed_rows(store, 9) == [("members.movement", "una riga")]


def test_an_event_that_is_not_urgent_writes_a_row_in_its_section_and_says_nothing_in_chat():
    poller, store, bot, t = setup(FUTURO)
    asyncio.run(one_event(poller, t, "members.movement"))
    assert bot.sent == []
    assert boards.lines_of(t.boards, "members") == ["14:00 · una riga"]


def test_the_poller_has_no_private_channel_left():
    assert not hasattr(Poller, "add_dm") and not hasattr(Poller, "flush_dm")
    assert not hasattr(Poller, "deliver_dm") and not hasattr(Poller, "send_dm")
    assert not hasattr(Tick(CLAN, NOW), "dm")
    assert not hasattr(quiet, "enqueue_dm")


def last_call_settings():
    stored = FUTURO
    for event in ("war.reminder", "war.risk", "war.midway"):
        stored = routed(stored, event, "off")
    return stored


def last_call_run(links):
    return reminder_run(last_call_settings(), links=links)


def test_the_last_call_names_in_chat_only_who_linked_the_village():
    _, bot, _ = last_call_run({"#P2": link("#P2", 8, "Luigi")})
    assert [chat for chat, _, _ in bot.sent] == [CLAN.chat_id]
    text = bot.sent[0][1]
    assert IT.t("last_call.title") in text
    assert 'tg://user?id=8' in text and "Peach" not in text


def test_without_anyone_linked_the_last_call_does_not_leave():
    _, bot, _ = last_call_run({})
    assert bot.sent == []


P2_DONE = events_mod.war_snapshot(war_json("inWar", our_attacks={
    "#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 60), ("#E3", 1, 30)]}))
ALL_DONE = events_mod.war_snapshot(war_json("inWar", our_attacks={
    "#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 60), ("#E3", 1, 30)],
    "#P3": [("#E3", 3, 100), ("#E1", 1, 20)]}))
OVER = events_mod.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100)]}))


def named_links(whispering=()):
    return {"#P2": link("#P2", 8, "Luigi", whisper="#P2" in whispering),
            "#P3": link("#P3", 9, "Peach", whisper="#P3" in whispering)}


def last_call_play(links, steps, bot=None, now=LATE):
    poller, store, bot, t = setup(last_call_settings(), links=links, now=now, bot=bot)
    asyncio.run(play(poller, store, t, steps))
    return poller, store, bot, t


def nudges_of(store):
    return store.state.get((CLAN.alias, whisper.STATE))


def group_nudge(message_id=101):
    return {"chat_id": CLAN.chat_id, "message_id": message_id, "war": events_mod.war_key(SOON)}


def test_the_last_call_remembers_under_every_tag_the_mention_it_left_in_the_group():
    _, store, bot, _ = last_call_play(named_links(), [SOON, SOON])
    text = bot.sent[0][1]
    assert [chat for chat, _, _ in bot.sent] == [CLAN.chat_id]
    assert 'tg://user?id=8' in text and 'tg://user?id=9' in text
    assert nudges_of(store) == {"#P2": [group_nudge()], "#P3": [group_nudge()]}
    assert bot.deleted == []


def test_a_last_call_without_mentions_leaves_nothing_to_delete():
    poller, store, bot, t = setup(dict(settings_mod.migrate(last_call_settings()), mentions="never"),
                                  links=named_links(), now=LATE)
    asyncio.run(play(poller, store, t, [SOON, SOON]))
    assert "tg://user" not in bot.sent[0][1]
    assert nudges_of(store) is None


def test_the_mention_stays_while_one_of_the_named_still_has_to_attack():
    _, store, bot, _ = last_call_play(named_links(), [SOON, SOON, P2_DONE])
    assert bot.deleted == []
    assert nudges_of(store) == {"#P3": [group_nudge()]}


def test_when_everyone_named_has_attacked_the_mention_goes_away():
    _, store, bot, _ = last_call_play(named_links(), [SOON, SOON, ALL_DONE])
    assert bot.deleted == [101]
    assert nudges_of(store) is None


def test_at_the_end_of_the_war_the_mentions_go_away_all_the_same():
    poller, store, bot, t = last_call_play(named_links(), [SOON, SOON])
    t.now = END_OF_WAR
    asyncio.run(play(poller, store, t, [SOON, OVER]))
    assert bot.deleted == [101]
    assert nudges_of(store) is None


def test_the_whisper_reaches_only_who_asked_for_it_and_goes_away_after_the_attack():
    _, store, bot, _ = last_call_play(named_links({"#P2"}), [SOON, SOON, P2_DONE])
    assert [chat for chat, _, _ in bot.sent] == [8, CLAN.chat_id]
    assert bot.silent == [True, False]
    assert IT.t("dm.title") in bot.sent[0][1]
    assert bot.deleted == [101]
    assert nudges_of(store) == {"#P3": [group_nudge(102)]}


class BlockedBot(FakeBot):
    async def send_message(self, chat_id, text, **kw):
        if chat_id != CLAN.chat_id:
            raise Forbidden("bot was blocked by the user")
        return await super().send_message(chat_id, text, **kw)


def test_who_blocked_the_bot_loses_the_whisper_and_the_round_goes_on():
    links = named_links({"#P2"})
    _, store, bot, _ = last_call_play(links, [SOON, SOON], bot=BlockedBot())
    assert links["#P2"].whisper is False and store.whispers == [(8, "#P2", False)]
    assert [chat for chat, _, _ in bot.sent] == [CLAN.chat_id]
    assert nudges_of(store) == {"#P2": [group_nudge()], "#P3": [group_nudge()]}


FOUR_HOURS = datetime(2026, 9, 12, 6, tzinfo=timezone.utc)
RISKY = events_mod.war_snapshot(war_json(
    "inWar", our_attacks={"#P1": [("#E1", 1, 30)]},
    their_attacks={"#E1": [("#P1", 3, 100)], "#E2": [("#P2", 3, 100)]}))
RISKY_DONE = events_mod.war_snapshot(war_json(
    "inWar",
    our_attacks={"#P1": [("#E1", 1, 30), ("#E2", 1, 30)],
                 "#P2": [("#E2", 2, 60), ("#E3", 1, 30)],
                 "#P3": [("#E3", 3, 100), ("#E1", 1, 20)]},
    their_attacks={"#E1": [("#P1", 3, 100)], "#E2": [("#P2", 3, 100)]}))


def risky_play(steps, links=None):
    poller, store, bot, t = setup(FUTURO, links=links if links is not None else named_links(),
                                  now=FOUR_HOURS)
    asyncio.run(play(poller, store, t, steps))
    return poller, store, bot, t


def test_the_risk_alarm_leaves_the_group_apart_from_the_mentions():
    _, store, bot, _ = risky_play([RISKY, RISKY])
    group = [text for chat, text, _ in bot.sent if chat == CLAN.chat_id]
    assert len(group) == 2
    assert IT.t("reminder.4h.title") in group[0] and 'tg://user?id=8' in group[0]
    assert IT.t("risk.title") not in group[0]
    assert IT.t("risk.title") in group[1] and "tg://user" not in group[1]
    assert nudges_of(store) == {"#P2": [group_nudge()], "#P3": [group_nudge()]}


def test_when_everyone_named_has_attacked_the_risk_alarm_stays_in_the_group():
    _, store, bot, _ = risky_play([RISKY, RISKY, RISKY_DONE])
    assert bot.deleted == [101]
    assert IT.t("risk.title") in bot.sent[1][1] and bot.sent[1][2] is None
    assert nudges_of(store) is None


class CountingCoc(FakeCoc):
    def __init__(self):
        super().__init__()
        self.asked = []

    async def clan(self, tag):
        self.asked.append(tag)
        return None, "private"


async def one_tick(poller, clan=CLAN):
    await poller.tick(clan, asyncio.Semaphore(1))


def paused_setup(pinned_id=55):
    state = {(CLAN.alias, "settings"): settings_mod.migrate(FUTURO),
             (CLAN.alias, "pause"): {"by": 7, "at": NOW.timestamp()}}
    if pinned_id:
        state[(CLAN.alias, "boards")] = {"message_id": pinned_id, "digest": "vecchio", "updated": 0.0}
    coc = CountingCoc()
    poller, store, bot, _ = setup(FUTURO, state=state, coc=coc)
    return poller, store, bot, coc


def paused_text():
    return IT.t("board.all.paused", clan=CLAN.name)


def test_the_pause_writes_the_paused_line_on_the_pinned_board_only_once():
    poller, store, bot, coc = paused_setup()
    asyncio.run(one_tick(poller))
    assert bot.edits == [(CLAN.chat_id, paused_text(), 55)]
    assert bot.sent == [] and bot.photos == [] and bot.pins == [] and coc.asked == []
    asyncio.run(one_tick(poller))
    assert bot.edits == [(CLAN.chat_id, paused_text(), 55)] and bot.sent == []
    assert store.state[(CLAN.alias, "boards")]["digest"] == boards.text_digest(paused_text())


def test_la_pausa_lascia_il_bottone_della_bacheca_sul_fissato():
    poller, store, bot, _ = paused_setup()
    poller.site = "https://clanboard.cloud"
    store.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
    asyncio.run(store.kv_set("console:username", "ClanBoardBot"))
    asyncio.run(one_tick(poller))
    assert bot.edits == [(CLAN.chat_id, paused_text(), 55)]
    button = bot.markups[0].inline_keyboard[0][0]
    assert button.text == IT.t("board.all.open")


def test_the_pause_never_opens_a_pinned_board_that_is_not_there():
    poller, _, bot, coc = paused_setup(pinned_id=None)
    asyncio.run(one_tick(poller))
    assert bot.sent == [] and bot.edits == [] and bot.pins == [] and coc.asked == []


def test_without_the_pause_the_round_goes_on_as_today():
    poller, _, _, coc = paused_setup()
    asyncio.run(poller.store.del_state(CLAN.alias, "pause"))
    asyncio.run(one_tick(poller))
    assert coc.asked == [CLAN.tag]


def test_i_movimenti_diventano_eventi_strutturati_per_la_cronaca():
    mossi = [{"type": "join", "tag": "#P9", "name": "Alex", "th": 14, "trophies": 3000},
             {"type": "leave", "tag": "#P8", "name": "Bruno"},
             {"type": "promote", "name": "Carla", "role": "admin"},
             {"type": "rename", "tag": "#P7", "old": "Dino", "name": "Dina"}]
    assert events_mod.member_facts(mossi) == [
        {"kind": "join", "who": "Alex", "n": 14},
        {"kind": "leave", "who": "Bruno", "n": None},
        {"kind": "promote", "who": "Carla", "n": None},
        {"kind": "rename", "who": "Dina", "n": None}]
    assert events_mod.member_facts([]) == [] and events_mod.member_facts(None) == []
    assert events_mod.EVENT_KINDS == events_mod.MOVEMENT_KINDS + (events_mod.WAR_END,)


def test_la_fine_della_guerra_diventa_un_evento_strutturato():
    finita = events_mod.war_snapshot(war_json("warEnded", {"#P1": [("#E1", 3, 100.0)]}))
    assert events_mod.war_end_fact(finita) == {"kind": "war_end", "who": "Clan Nemico", "n": 3}


def test_il_dispatch_scrive_la_riga_e_l_evento_strutturato_sul_tabellone():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))

    async def giro():
        await poller.dispatch(t, "members.movement", lambda L: "Alex è entrato nel clan",
                              facts=[{"kind": "join", "who": "Alex", "n": 14}])
        await poller.flush(t)
        await poller.update_boards(t)

    asyncio.run(giro())
    saved = stored_boards(store)
    assert boards.lines_of(saved, "members") == ["14:00 · Alex è entrato nel clan"]
    assert boards.events_of(saved) == [{"pack": "members", "kind": "join", "who": "Alex",
                                        "n": 14, "at": int(NOW.timestamp())}]
