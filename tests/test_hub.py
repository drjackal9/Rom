import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram import InlineKeyboardButton
from telegram.constants import ChatType

from clashbot import handlers, hub, i18n, leaderboards as boards, privacy, render
from test_flows import ALIAS, CLAN, FakeQuery, FakeStore, fake_update

L = i18n.locale("it")
EN = i18n.locale("en")
TZ = "Europe/Rome"
NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
LINK = SimpleNamespace(tag="#P1", user_id=7, name="Mario")
PROGRESS = {"#P1": {"name": "Mario", "now": {"gold": 9_000_000, "elixir": 3_300_000, "dark": 800_000},
                    "week": {"since": 0, "gold": 0, "elixir": 0, "dark": 0}}}
COUNTERS = {"#P1": {"name": "Mario",
                    "now": {"gold": 9_000_000, "elixir": 3_300_000, "dark": 800_000,
                            "wins": 37, "games": 1_200, "levels": 14, "th": 15},
                    "week": {"since": 0, "gold": 0, "elixir": 0, "dark": 0,
                             "wins": 0, "games": 0, "levels": 0, "th": 14}}}

FARM = [{"tag": "#P1", "name": "Mario", "value": 12_300_000, "delta": 12_300_000, "extra": 800_000},
        {"tag": "#P2", "name": "Luigi", "value": 2_000_000, "delta": 2_000_000, "extra": 0}]
TROPHIES = [{"tag": "#P1", "name": "Mario", "value": 5400, "delta": 300, "extra": 16},
            {"tag": "#P2", "name": "Luigi", "value": 5100, "delta": -50, "extra": 15}]
MVP = [{"tag": "#P1", "name": "Mario", "value": 207, "total": 207, "delta": 207, "extra": 6,
        "parts": {"attacks": 12, "stars": 15, "triples": 9, "missed": -3, "raid_attacks": 6,
                  "loot": 45, "donations": 12, "farm": 24, "wins": 37, "levels": 18,
                  "th_up": 25, "games": 7}}]


def test_keyboard_offers_to_hide_and_to_come_back():
    out = [b.text for row in hub.keyboard(L, "farm", "week").inline_keyboard for b in row]
    back = [b.text for row in hub.keyboard(L, "farm", "week", hidden=True).inline_keyboard for b in row]
    assert L.t("boards.btn_hide") in out and L.t("boards.btn_show") not in out
    assert L.t("boards.btn_show") in back


def test_without_a_linked_account_there_is_nothing_to_hide():
    markup = hub.keyboard(L, "farm", "week", linked=False)
    assert "b:me:hide" not in datas_of(markup)
    assert "b:farm:month" in datas_of(markup)


def test_keyboard_carries_the_extra_rows_of_a_tab():
    extra = [[InlineKeyboardButton("x", callback_data="b:network:toggle")]]
    markup = hub.keyboard(L, "network", "week", False, extra)
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "b:network:toggle" in data
    assert all(len(d.encode()) <= 64 for d in data)
    plain = [b.callback_data for row in hub.keyboard(L, "network", "week").inline_keyboard for b in row]
    assert "b:network:toggle" not in plain


def test_the_network_tab_has_its_own_branch_and_never_reads_deltas():
    data = {"state": {}, "hidden": set()}
    text = asyncio.run(hub.view(L, TZ, "network", "week", data, NOW))
    assert L.t("network.title") in text and L.t("network.off") in text


def test_parse_reads_tab_and_period():
    assert hub.parse("b:farm:week") == ("farm", "week")
    assert hub.parse("b:hall:") == ("hall", None)
    assert hub.parse("b:pinco:week") == (hub.DEFAULT_TAB, boards.default_period(hub.DEFAULT_TAB))
    assert hub.parse("b:farm:pinco") == ("farm", "week")
    assert hub.parse("b:mvp:week") == ("mvp", "month")


def test_keyboard_has_every_tab_and_only_the_allowed_periods():
    markup = hub.keyboard(L, "farm", "week")
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    for tab in boards.TABS:
        assert any(d.startswith(f"b:{tab}:") for d in data), tab
    assert all(len(d.encode()) <= 64 for d in data)
    periods = [d for d in data if d.startswith("b:farm:")]
    assert sorted(periods) == ["b:farm:month", "b:farm:season", "b:farm:week"]
    assert not [d for d in hub.keyboard(L, "points", "month").inline_keyboard[0]
                if d.callback_data == "b:points:week"]


def test_board_view_renders_farm_like_the_old_activity_card():
    text = render.board_view(L, "farm", "week", FARM)
    assert "🏹 <b>Farm</b>" in text and "questa settimana" in text
    assert "🥇 <b>Mario</b> · 12,3M 💰 · 0,8M ⚫" in text
    assert "🥈 <b>Luigi</b> · 2,0M 💰" in text and "🥈 <b>Luigi</b> · 2,0M 💰 ·" not in text
    assert "Fermi" not in text
    assert len(text) <= render.MAX_LEN


def test_board_view_shows_climbers_and_an_encouraging_close():
    text = render.board_view(L, "trophies", "week", TROPHIES, climb=boards.climbers(TROPHIES))
    assert "🏆 5.400" in text and "📈" in text and "Mario" in text
    assert "+300" in text and "-50" not in text
    assert L.t("boards.encourage.week") in text


def test_board_view_is_empty_without_rows():
    text = render.board_view(L, "farm", "week", [])
    assert L.t("boards.empty") in text and "🥇" not in text


def test_mvp_view_shows_the_total_and_every_part():
    text = render.mvp_view(L, "month", MVP)
    assert "<b>207 pt</b>" in text and "Mario" in text
    for part in boards.MVP_PARTS:
        assert L.t(f"boards.part.{part}") in text
    assert L.t("boards.mvp.how") in text
    assert len(text) <= render.MAX_LEN


def test_every_tab_renders_in_english_too():
    for tab in ("farm", "upgrade", "wins", "games", "donations", "trophies", "capital", "stars"):
        rows = TROPHIES if tab == "trophies" else FARM
        text = render.board_view(EN, tab, "month", rows)
        assert f"<b>{render.board_label(EN, tab)}</b>" in text and "[" not in text
        assert f"<b>{EN.t(f'boards.tab.{tab}')}</b>" not in text


def hub_store():
    return FakeStore(state={(CLAN.alias, "settings"): {"lang": "it", "tz": TZ},
                            (CLAN.alias, "progress"): PROGRESS},
                     links=[LINK], owner="7")


def pressed(store, data):
    query = FakeQuery(data)
    asyncio.run(handlers.on_board_callback(fake_update(query, chat_type=ChatType.PRIVATE),
                                           context_for(store)))
    return query


def context_for(store):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": ALIAS})


def datas_of(keyboard):
    return [b.callback_data for row in keyboard.inline_keyboard for b in row]


def test_the_old_activity_command_opens_the_farm_tab_of_the_hub():
    store = hub_store()
    update = fake_update(FakeQuery("v:activity"))
    text, keyboard = asyncio.run(handlers.build_view("activity", CLAN, context_for(store), update))
    assert "🏹 <b>Farm</b>" in text and "🥇 <b>Mario</b> · 12,3M 💰 · 0,8M ⚫" in text
    assert "b:farm:month" in datas_of(keyboard) and "b:me:hide" in datas_of(keyboard)


def test_who_has_no_account_gets_a_word_instead_of_a_silent_button():
    store = FakeStore(state={(CLAN.alias, "settings"): {"lang": "it", "tz": TZ},
                             (CLAN.alias, "progress"): PROGRESS}, owner="7")
    update = fake_update(FakeQuery("v:activity"))
    _, keyboard = asyncio.run(handlers.build_view("activity", CLAN, context_for(store), update))
    assert "b:me:hide" not in datas_of(keyboard)
    query = pressed(store, "b:me:hide")
    assert query.answers == [(L.t("boards.no_account"), True)]
    assert (CLAN.alias, boards.STATE_KIND) not in store.state
    assert query.edits == []


def test_every_metric_tab_gets_the_deltas_it_reads():
    store = FakeStore(state={(CLAN.alias, "settings"): {"lang": "it", "tz": TZ},
                             (CLAN.alias, "progress"): COUNTERS})
    for tab, row in (("wins", "<b>Mario</b> · 37 vittorie"),
                     ("games", "<b>Mario</b> · 1.200 punti"),
                     ("farm", "🥇 <b>Mario</b> · 12,3M 💰 · 0,8M ⚫"),
                     ("upgrade", "🥇 <b>Mario</b> · +14 livelli · 🏠 +1")):
        data = asyncio.run(hub.sources(store, None, CLAN, tab, "week", NOW, TZ))
        assert "deltas" in data, tab
        text = asyncio.run(hub.view(L, TZ, tab, "week", data, NOW))
        assert row in text, tab


def test_pressing_hide_takes_the_member_out_of_every_board():
    store = hub_store()
    query = pressed(store, "b:me:hide")
    assert asyncio.run(privacy.excluded(store, CLAN.alias)) == {"#P1"}
    assert query.answers == [(L.t("boards.hidden"), True)]
    farm = pressed(store, "b:farm:week")
    assert "Mario" not in farm.edits[0] and L.t("boards.empty") in farm.edits[0]
    _, keyboard = asyncio.run(handlers.build_view("activity", CLAN, context_for(store),
                                                 fake_update(FakeQuery("v:activity"))))
    assert L.t("boards.btn_show") in [b.text for row in keyboard.inline_keyboard for b in row]
    back = pressed(store, "b:me:hide")
    assert asyncio.run(privacy.excluded(store, CLAN.alias)) == set()
    assert back.answers == [(L.t("boards.shown"), True)]


def test_the_clan_games_row_keeps_its_plural_forms():
    ru = i18n.locale("ru")
    rows = [{"tag": "#P1", "name": "Mario", "value": 4000, "delta": 4000, "extra": 0}]
    assert ru.n(4000) + " очков" in render.board_view(ru, "games", "week", rows)
    pl = i18n.locale("pl")
    assert pl.n(4000) + " punktów" in render.board_view(pl, "games", "week", rows)
    wins = [{"tag": "#P1", "name": "Mario", "value": 1, "delta": 1, "extra": 0}]
    assert "1 vittoria" in render.board_view(L, "wins", "week", wins)
