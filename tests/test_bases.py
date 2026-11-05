import asyncio
import json
from types import SimpleNamespace

from telegram.constants import ChatType
from test_flows import ALIAS, CLAN, FakeMessage, FakeQuery, FakeStore, fake_update
from test_retention import FakePool, flat
from test_routing import FUTURO, setup as tick_setup

from clashbot import base_ui, bases, boards, handlers, i18n, retention, settings as settings_mod
from clashbot.crypto import Vault
from clashbot.db import SCHEMA, Store
from clashbot.events_registry import EVENTS, PACKS

IT = i18n.locale("it")
CATALOGS = {code: json.load(open(i18n.LOCALE_DIR / f"{code}.json", encoding="utf-8"))
            for code in ("it", "en")}
GOOD = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16:HV:AAAA-BBBB_CC"
BUILDER = "https://link.clashofclans.com/en?action=OpenLayout&id=BH10:BB:ZZZZ1111"
SETTINGS = {(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"}}


def test_parse_link_reads_village_and_hall_from_the_link():
    assert bases.parse_link(GOOD) == {"village": "home", "hall": 16, "id": "TH16:HV:AAAA-BBBB_CC"}
    assert bases.parse_link(BUILDER) == {"village": "builder", "hall": 10, "id": "BH10:BB:ZZZZ1111"}
    assert bases.parse_link(f"  {GOOD}  ") == bases.parse_link(GOOD)


def test_parse_link_refuses_everything_that_is_not_an_official_layout():
    for bad in (
        None, "", "ciao",
        "https://example.invalid/?action=OpenLayout&id=TH16:HV:AAAA-BBBB",
        "https://link.clashofclans.com/it?action=OpenClanProfile&tag=%23CLAN1",
        "https://link.clashofclans.com/it?action=OpenLayout&id=TH16:HV",
        "https://link.clashofclans.com/it?action=OpenLayout&id=TH16:BB:AAAA-BBBB",
        "https://link.clashofclans.com/it?action=OpenLayout&id=BH10:HV:AAAA-BBBB",
        "https://link.clashofclans.com/it?action=OpenLayout&id=XX16:HV:AAAA-BBBB",
        "https://link.clashofclans.com/it?action=OpenLayout&id=TH16:HV:ab",
        "ftp://link.clashofclans.com/it?action=OpenLayout&id=TH16:HV:AAAA-BBBB",
    ):
        assert bases.parse_link(bad) is None, bad


def test_link_url_speaks_the_language_of_the_reader():
    assert bases.link_url(IT, "TH16:HV:AAAA") == (
        "https://link.clashofclans.com/it?action=OpenLayout&id=TH16%3AHV%3AAAAA")


def test_label_name_falls_back_without_inventing():
    assert bases.label_name(IT, "farm") == IT.t("bases.label.farm")
    assert bases.label_name(IT, None) == IT.t("bases.label.war")
    assert bases.label_name(IT, "boh") == IT.t("bases.label.war")


def test_halls_are_listed_once_from_the_highest_and_ignore_rows_without_a_hall():
    rows = [{"village": "home", "hall": 15}, {"village": "home", "hall": 16},
            {"village": "home", "hall": 15}, {"village": "builder", "hall": 10},
            {"village": "home", "label": "war"}]
    assert bases.halls(rows, "home") == [16, 15]
    assert bases.halls(rows, "builder") == [10]
    assert bases.halls([], "home") == []


def test_the_card_says_when_there_is_nothing_yet():
    assert IT.t("bases.empty") in bases.card(IT, [], "clan", "home", None)


def test_the_card_lists_the_rows_with_label_and_hall():
    rows = [{"alias": "base-1", "village": "home", "hall": 16, "label": "war",
             "name": "Mario", "id": "TH16:HV:AAAA", "shared": False, "published": False}]
    text = bases.card(IT, rows, "clan", "home", 16)
    assert "Mario" in text and IT.t("bases.label.war") in text and "16" in text


def test_a_shared_or_published_row_wears_its_mark():
    row = {"alias": "base-1", "village": "home", "hall": 16, "label": "war",
           "name": "Mario", "id": "TH16:HV:AAAA", "shared": True, "published": True}
    line = bases.row_line(IT, row, 0)
    assert "📚" in line and "📦" in line


def test_the_base_cap_is_the_one_of_the_wars():
    assert retention.BASE_KEEP == retention.WAR_HISTORY_KEEP
    assert "base_layouts" in retention.COUNT_SQL["basi_oltre_tetto"]
    assert retention.DELETE_SQL["basi_oltre_tetto"].strip().startswith("delete from base_layouts")
    assert "partition by clan_alias" in retention.COUNT_SQL["basi_oltre_tetto"]
    assert "base_layouts" in retention.PRUNE_CLAN_BASES_SQL


def test_the_schema_creates_the_table_only_if_it_is_missing():
    assert "create table if not exists base_layouts" in SCHEMA
    assert "on delete cascade" in SCHEMA.split("base_layouts")[1][:400]
    assert "create unique index if not exists base_layouts_link_idx" in SCHEMA


class Pool(FakePool):
    async def execute(self, sql, *args):
        self.log.append(("execute", flat(sql), args))
        return self.values.pop(0)


def store_with(tmp_path, **kw):
    store = Store(Vault(tmp_path))
    store.pool = Pool(**kw)
    return store


def test_add_base_writes_an_encrypted_row_and_prunes_the_clan(tmp_path):
    store = store_with(tmp_path, statuses=["base-1", "DELETE 0"])
    saved = asyncio.run(store.add_base("clan-1", bases.parse_link(GOOD), "war",
                                       {"name": "Mario", "by": 7}))
    assert saved == "base-1"
    log = store.pool.log
    assert log[0] == "begin" and log[-1] == "commit"
    insert, prune = log[1], log[2]
    assert insert[0].startswith("insert into base_layouts")
    assert insert[1][1] == "clan-1" and insert[1][3] == "home" and insert[1][4] == 16
    written = " ".join(str(value) for value in insert[1])
    assert "Mario" not in written and "AAAA-BBBB_CC" not in written
    assert prune == (flat(retention.PRUNE_CLAN_BASES_SQL), ("clan-1", retention.BASE_KEEP))


def test_a_base_already_there_is_not_saved_twice(tmp_path):
    store = store_with(tmp_path, statuses=[None])
    assert asyncio.run(store.add_base("clan-1", bases.parse_link(GOOD), "war", {"name": "Mario"})) is None
    assert [entry for entry in store.pool.log if isinstance(entry, tuple)][1:] == []


def row_of(store, alias="base-1", **kw):
    payload = {"name": "Mario", "by": 7, "id": "TH16:HV:AAAA-BBBB_CC"}
    return dict({"alias": alias, "clan_alias": "clan-1", "label": "war", "village": "home",
                 "hall": 16, "shared": False, "published": False, "created_at": None,
                 "data": store.vault.encrypt_json(payload, f"base:{alias}")}, **kw)


def test_the_rows_of_the_clan_come_back_readable(tmp_path):
    store = store_with(tmp_path)
    store.pool.values = [[row_of(store)]]
    rows = asyncio.run(store.clan_bases("clan-1", "home", 16, bases.PAGE))
    assert rows[0]["name"] == "Mario" and rows[0]["id"] == "TH16:HV:AAAA-BBBB_CC"
    assert rows[0]["hall"] == 16 and rows[0]["shared"] is False
    assert store.pool.log[0][2] == ("clan-1", "home", 16, bases.PAGE)


def test_the_library_asks_only_for_the_shared_ones(tmp_path):
    store = store_with(tmp_path)
    store.pool.values = [[row_of(store, shared=True)]]
    rows = asyncio.run(store.shared_bases(None, None, bases.PAGE))
    assert rows[0]["shared"] is True
    assert "where shared" in store.pool.log[0][1]


def test_an_unreadable_row_does_not_take_down_the_list(tmp_path):
    store = store_with(tmp_path)
    store.pool.values = [[row_of(store, alias="base-2", data=b"rotto"), row_of(store)]]
    rows = asyncio.run(store.clan_bases("clan-1"))
    assert [row["alias"] for row in rows] == ["base-1"]


def test_the_flags_and_the_removal_answer_how_many_rows_they_touched(tmp_path):
    store = store_with(tmp_path)
    store.pool.values = ["UPDATE 1", "DELETE 0"]
    assert asyncio.run(store.set_base_flags("base-1", shared=True)) is True
    assert asyncio.run(store.remove_base("base-1")) is False
    assert store.pool.log[0][2] == ("base-1", True, None)


def test_the_bases_pack_and_its_three_events_are_in_the_registry():
    assert "bases" in PACKS
    for name, default in (("bases.new", "group"), ("bases.poll", "group"), ("bases.pack", "leaders_dm")):
        assert EVENTS[name]["pack"] == "bases"
        assert EVENTS[name]["default"] == default
        assert EVENTS[name]["default"] in EVENTS[name]["allowed"]
    assert "leaders_dm" not in EVENTS["bases.new"]["allowed"]


def test_the_bases_pack_is_off_only_for_the_leaders_preset():
    for name in ("war_clan", "casual_clan", "family"):
        assert settings_mod.PRESETS[name]["packs"]["bases"] is True, name
    assert settings_mod.PRESETS["leaders_only"]["packs"]["bases"] is False


def test_the_commands_and_the_menu_know_the_bases():
    assert ("base", []) in handlers.COMMANDS
    assert ("bases", ["basi"]) in handlers.COMMANDS
    assert "bases" in handlers.VIEWS and ["bases"] in handlers.MENU_ROWS
    assert "base" in handlers.HANDLERS
    for key in ("cmd.base", "cmd.bases", "menu.bases"):
        assert key in CATALOGS["it"] and key in CATALOGS["en"], key


class BaseStore(FakeStore):
    def __init__(self, rows=(), **kw):
        super().__init__(**kw)
        self.rows = [dict(row) for row in rows]

    async def add_base(self, clan_alias, layout, label, payload, keep=retention.BASE_KEEP):
        if any(row["clan_alias"] == clan_alias and row["id"] == layout["id"] for row in self.rows):
            return None
        alias = f"base-{len(self.rows) + 1}"
        self.rows.append(dict({"alias": alias, "clan_alias": clan_alias, "label": label,
                               "village": layout["village"], "hall": layout["hall"],
                               "shared": False, "published": False, "id": layout["id"]}, **payload))
        return alias

    async def base_by_alias(self, alias):
        return next((row for row in self.rows if row["alias"] == alias), None)

    async def clan_bases(self, clan_alias, village=None, hall=None, limit=10):
        return [row for row in self.rows
                if row["clan_alias"] == clan_alias
                and village in (None, row["village"]) and hall in (None, row["hall"])][:limit]

    async def shared_bases(self, village=None, hall=None, limit=10):
        return [row for row in self.rows if row["shared"]
                and village in (None, row["village"]) and hall in (None, row["hall"])][:limit]

    async def set_base_flags(self, alias, shared=None, published=None):
        row = await self.base_by_alias(alias)
        if not row:
            return False
        if shared is not None:
            row["shared"] = shared
        if published is not None:
            row["published"] = published
        return True

    async def remove_base(self, alias):
        before = len(self.rows)
        self.rows = [row for row in self.rows if row["alias"] != alias]
        return len(self.rows) < before


SAVED = {"alias": "base-1", "clan_alias": CLAN.alias, "label": "war", "village": "home",
         "hall": 16, "shared": False, "published": False, "id": "TH16:HV:AAAA-BBBB_CC",
         "name": "Mario", "by": 7}


def context_for(store, args=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": ALIAS},
                           args=list(args or []))


def message_update(user_id=7):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.GROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"),
        effective_message=FakeMessage(),
    )


def datas_of(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row
            if button.callback_data]


def urls_of(markup):
    return [button.url for row in markup.inline_keyboard for button in row if button.url]


def run_command(store, args):
    update = message_update()
    asyncio.run(base_ui.cmd_base(update, context_for(store, args)))
    return update.effective_message.sent


def test_without_a_link_the_bot_says_how_to_copy_it():
    store = BaseStore(state=SETTINGS, owner="7")
    sent = run_command(store, ["ciao"])
    assert IT.t("bases.ask_link") in sent[0][0] and sent[0][1] is None
    assert store.kv == {}


def test_with_a_good_link_the_bot_asks_the_label_with_the_buttons():
    store = BaseStore(state=SETTINGS, owner="7")
    sent = run_command(store, [GOOD])
    assert IT.t("bases.village.home") in sent[0][0] and "TH16" in sent[0][0]
    datas = datas_of(sent[0][1])
    assert [data.split(":")[3] for data in datas] == list(bases.LABELS)
    assert all(len(data.encode()) <= 64 for data in datas)
    code = datas[0].split(":")[2]
    assert store.kv[f"basedraft:{code}"]["layout"] == bases.parse_link(GOOD)


def choose_label(store, code, label="war", user_id=7):
    query = FakeQuery(f"bs:l:{code}:{label}")
    update = fake_update(query, user_id)
    asyncio.run(base_ui.on_callback(update, context_for(store)))
    return query


def draft_code(store):
    return next(key.split(":")[1] for key in store.kv if key.startswith("basedraft:"))


def test_the_label_saves_the_base_and_queues_the_announcement():
    store = BaseStore(state=SETTINGS, owner="7")
    run_command(store, [GOOD])
    query = choose_label(store, draft_code(store))
    assert query.answers[0][0] == IT.t("bases.saved")
    assert [row["id"] for row in store.rows] == ["TH16:HV:AAAA-BBBB_CC"]
    assert store.state[(CLAN.alias, "bases_new")] == [
        {"name": "Mario", "village": "home", "hall": 16, "label": "war"}]
    assert store.kv == {}
    assert "Mario" in query.edits[0]


def test_the_same_base_twice_is_not_saved_again():
    store = BaseStore(rows=[SAVED], state=SETTINGS, owner="7")
    run_command(store, [GOOD])
    query = choose_label(store, draft_code(store))
    assert query.answers[0][0] == IT.t("bases.duplicate")
    assert len(store.rows) == 1
    assert (CLAN.alias, "bases_new") not in store.state


def test_a_draft_that_is_gone_does_not_invent_a_base():
    store = BaseStore(state=SETTINGS, owner="7")
    query = choose_label(store, "abcdef")
    assert query.answers[0][0] == IT.t("bases.expired")
    assert store.rows == []


def test_the_hub_shows_the_tabs_the_villages_and_the_link_of_every_base():
    store = BaseStore(rows=[SAVED], state=SETTINGS, owner="7")
    update = message_update()
    text, keyboard = asyncio.run(base_ui.hub_view(update, context_for(store), CLAN))
    assert IT.t("bases.tab.clan") in text and "Mario" in text
    assert "bs:s:library" in datas_of(keyboard) and "bs:v:clan:builder" in datas_of(keyboard)
    assert "bs:h:clan:home:16" in datas_of(keyboard)
    assert urls_of(keyboard) == [bases.link_url(IT, SAVED["id"])]
    assert datas_of(keyboard)[-1] == "v:menu"
    assert all(len(data.encode()) <= 64 for data in datas_of(keyboard))


def test_only_who_can_manage_sees_the_library_and_the_bin():
    update = message_update()
    leader = context_for(BaseStore(rows=[SAVED], state=SETTINGS, owner="7"))
    member = context_for(BaseStore(rows=[SAVED], state=SETTINGS))
    _, mine = asyncio.run(base_ui.hub_view(update, leader, CLAN))
    _, theirs = asyncio.run(base_ui.hub_view(update, member, CLAN))
    assert "bs:sh:base-1" in datas_of(mine) and "bs:rm:base-1" in datas_of(mine)
    assert "bs:sh:base-1" not in datas_of(theirs) and "bs:rm:base-1" not in datas_of(theirs)


def test_in_the_library_the_buttons_stay_on_the_bases_of_your_clan():
    rows = [dict(SAVED, shared=True),
            dict(SAVED, alias="base-9", clan_alias="clan-9", name="Luigi", shared=True)]
    store = BaseStore(rows=rows, state=SETTINGS, owner="7")
    update = message_update()
    text, keyboard = asyncio.run(base_ui.hub_view(update, context_for(store), CLAN, "library"))
    assert "Luigi" in text
    datas = datas_of(keyboard)
    assert "bs:sh:base-1" in datas and "bs:rm:base-1" in datas
    assert "bs:sh:base-9" not in datas and "bs:rm:base-9" not in datas


def callback(store, data, user_id=7):
    query = FakeQuery(data)
    asyncio.run(base_ui.on_callback(fake_update(query, user_id), context_for(store)))
    return query


def test_a_member_cannot_remove_or_share_the_bases_of_the_clan():
    store = BaseStore(rows=[SAVED], state=SETTINGS)
    query = callback(store, "bs:rm:base-1")
    assert query.answers[0] == (IT.t("h.admin_only"), True)
    assert len(store.rows) == 1
    assert callback(store, "bs:sh:base-1").answers[0][1] is True
    assert store.rows[0]["shared"] is False


def test_the_leader_shares_a_base_and_then_throws_it_away():
    store = BaseStore(rows=[SAVED], state=SETTINGS, owner="7")
    assert callback(store, "bs:sh:base-1").answers[0][0] == IT.t("bases.shared")
    assert store.rows[0]["shared"] is True
    assert callback(store, "bs:rm:base-1").answers[0][0] == IT.t("bases.removed")
    assert store.rows == []


def test_a_base_of_another_clan_is_not_touched():
    store = BaseStore(rows=[dict(SAVED, clan_alias="clan-9")], state=SETTINGS, owner="7")
    assert callback(store, "bs:rm:base-1").answers[0][0] == IT.t("bases.expired")
    assert len(store.rows) == 1


def test_the_chosen_hall_still_shows_the_way_back_to_the_others():
    rows = [SAVED, dict(SAVED, alias="base-2", hall=15, id="TH15:HV:BBBB-CCCC")]
    store = BaseStore(rows=rows, state=SETTINGS, owner="7")
    update = message_update()
    text, keyboard = asyncio.run(base_ui.hub_view(update, context_for(store), CLAN, hall=16))
    assert "TH15" not in text
    assert "bs:h:clan:home:15" in datas_of(keyboard)
    assert [button.text for row in keyboard.inline_keyboard for button in row
            if button.callback_data == "bs:h:clan:home:16"] == ["✓ TH16"]


def test_the_tabs_walk_between_clan_library_village_and_hall():
    store = BaseStore(rows=[dict(SAVED, shared=True)], state=SETTINGS, owner="7")
    assert IT.t("bases.tab.library") in callback(store, "bs:s:library").edits[0]
    assert IT.t("bases.village.builder") in callback(store, "bs:v:clan:builder").edits[0]
    assert "TH16" in callback(store, "bs:h:clan:home:16").edits[0]


def test_the_menu_button_opens_the_hub_in_place():
    store = BaseStore(rows=[SAVED], state=SETTINGS, owner="7")
    query = FakeQuery("v:bases")
    update = fake_update(query, chat_type=ChatType.PRIVATE)
    asyncio.run(handlers.on_callback(update, context_for(store)))
    assert IT.t("bases.tab.clan") in query.edits[0] and "Mario" in query.edits[0]


def test_the_new_bases_are_announced_once_and_then_forgotten():
    queued = [{"name": "Mario", "hall": 16, "label": "war"},
              {"name": "Luigi", "hall": 10, "label": "farm"}]
    poller, store, bot, t = tick_setup(FUTURO, state={(CLAN.alias, "bases_new"): queued})
    asyncio.run(poller.announce_bases(t))
    asyncio.run(poller.flush(t))
    assert bot.sent == []
    text = "\n".join(boards.lines_of(t.boards, "bases"))
    assert "Mario" in text and "Luigi" in text and IT.t("bases.label.farm") in text
    assert (CLAN.alias, "bases_new") not in store.state
    t.chunks, t.threads = [], {}
    asyncio.run(poller.announce_bases(t))
    asyncio.run(poller.flush(t))
    assert boards.lines_of(t.boards, "bases") == boards.lines_of(t.boards, "bases")[:2]


def test_with_the_bases_pack_off_nothing_is_announced():
    stored = settings_mod.migrate(FUTURO)
    stored["packs"]["bases"] = False
    poller, store, bot, t = tick_setup(stored, state={
        (CLAN.alias, "bases_new"): [{"name": "Mario", "hall": 16, "label": "war"}]})
    asyncio.run(poller.announce_bases(t))
    asyncio.run(poller.flush(t))
    assert bot.sent == []
    assert (CLAN.alias, "bases_new") not in store.state
