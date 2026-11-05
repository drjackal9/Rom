import asyncio
import copy
import io
import json
import re
from types import SimpleNamespace

from PIL import Image
from telegram.error import TelegramError
from test_flows import ALIAS
from test_flows import FakeStore as ChatStore
from test_routing import ENDED, FUTURO, MEMBERS, NOW, STARTED
from test_routing import CLAN as WAR_CLAN
from test_routing import FakeBot as RoutingBot
from test_routing import FakeStore as RoutingStore
from test_routing import routed, supervisor_for
from test_settings_ui import USER, context, group_update

from clashbot import (boards, events as events_mod, handlers, i18n, media, scoring,
                      settings as settings_mod, stickers)
from clashbot.events_registry import EVENTS, GROUP_ONLY
from clashbot.poller import Poller, Tick

IT = i18n.locale("it")
CATALOGS = {code: json.load(open(i18n.LOCALE_DIR / f"{code}.json", encoding="utf-8"))
            for code in ("it", "en")}
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias=ALIAS)
KEYS = ("cmd.stickers", "stickers.title", "stickers.making", "stickers.done", "stickers.failed",
        "stickers.ready", "stickers.owner", "stickers.emoji.title", "setup.event.system.stickers",
        "stickers.done_no_emoji")
BADGE_URL = f"https://{media.BADGE_HOST}/badges/512/clan.png"


class FakeVault:
    def blind(self, label, value):
        return f"{abs(hash((label, value))) % (16 ** 12):012x}"


def badge_png():
    out = io.BytesIO()
    Image.new("RGBA", (512, 512), (20, 90, 180, 255)).save(out, format="PNG")
    return out.getvalue()


class FakeBot:
    def __init__(self, existing=()):
        self.username = "futuro_clan_bot"
        self.created = []
        self.existing = set(existing)

    async def get_sticker_set(self, name):
        if name not in self.existing:
            raise ValueError("not found")
        return SimpleNamespace(name=name,
                               stickers=[SimpleNamespace(file_id=f"f{i}") for i in range(5)])

    async def create_new_sticker_set(self, user_id, name, title, items, sticker_type=None):
        self.created.append((user_id, name, title, len(items), sticker_type))
        self.existing.add(name)
        return True


def test_set_names_follow_the_telegram_rule():
    vault = FakeVault()
    name = stickers.set_name(vault, CLAN.alias, "futuro_clan_bot")
    emoji = stickers.emoji_set_name(vault, CLAN.alias, "futuro_clan_bot")
    for value in (name, emoji):
        assert value.endswith("_by_futuro_clan_bot")
        assert len(value) <= 64
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value)
        assert stickers.valid_name(value) is True
    assert name != emoji


def test_a_name_that_telegram_would_refuse_is_not_valid():
    assert stickers.valid_name(None) is False
    assert stickers.valid_name("") is False
    assert stickers.valid_name("1cb_by_bot") is False
    assert stickers.valid_name("cb-by-bot") is False
    assert stickers.valid_name("c" * 65) is False


def test_the_set_name_never_carries_the_clan_tag():
    assert "CLAN1" not in stickers.set_name(FakeVault(), CLAN.alias, "futuro_clan_bot").upper()


def test_compose_returns_a_square_webp_inside_the_telegram_size():
    out = stickers.compose(badge_png(), (200, 40, 40))
    image = Image.open(io.BytesIO(out))
    assert image.size == (stickers.SIZE, stickers.SIZE)
    assert image.format == "WEBP"
    assert len(out) < 512 * 1024


def test_compose_makes_the_small_square_for_the_custom_emoji():
    out = stickers.compose(badge_png(), (200, 40, 40), stickers.EMOJI_SIZE, 6)
    assert Image.open(io.BytesIO(out)).size == (stickers.EMOJI_SIZE, stickers.EMOJI_SIZE)


def test_build_creates_the_two_sets_once_and_keeps_the_file_ids(monkeypatch):
    async def fake_badge(url, client=None):
        return badge_png()

    monkeypatch.setattr(stickers, "badge_of", fake_badge)
    bot = FakeBot()
    clan_json = {"badgeUrls": {"large": BADGE_URL}}
    made = asyncio.run(stickers.build(bot, FakeVault(), CLAN, clan_json, 7, "Futuro"))
    assert made["set"].endswith("_by_futuro_clan_bot")
    assert made["emoji"].endswith("_by_futuro_clan_bot")
    assert made["files"]["war"] == "f0"
    assert [entry[4] for entry in bot.created] == [None, "custom_emoji"]
    assert [entry[3] for entry in bot.created] == [len(stickers.MOMENTS), 1]
    again = asyncio.run(stickers.build(bot, FakeVault(), CLAN, clan_json, 7, "Futuro"))
    assert again["set"] == made["set"]
    assert len(bot.created) == 2


def test_build_gives_the_emoji_set_its_own_title(monkeypatch):
    async def fake_badge(url, client=None):
        return badge_png()

    monkeypatch.setattr(stickers, "badge_of", fake_badge)
    bot = FakeBot()
    clan_json = {"badgeUrls": {"small": BADGE_URL}}
    asyncio.run(stickers.build(bot, FakeVault(), CLAN, clan_json, 7, "Futuro", "Futuro · emoji"))
    assert [entry[2] for entry in bot.created] == ["Futuro", "Futuro · emoji"]


class NoEmojiBot(FakeBot):
    async def create_new_sticker_set(self, user_id, name, title, items, sticker_type=None):
        if sticker_type == "custom_emoji":
            raise TelegramError("emoji set refused")
        return await super().create_new_sticker_set(user_id, name, title, items, sticker_type)


def test_build_keeps_the_stickers_and_admits_the_emoji_set_is_missing(monkeypatch):
    async def fake_badge(url, client=None):
        return badge_png()

    monkeypatch.setattr(stickers, "badge_of", fake_badge)
    bot = NoEmojiBot()
    clan_json = {"badgeUrls": {"large": BADGE_URL}}
    made = asyncio.run(stickers.build(bot, FakeVault(), CLAN, clan_json, 7, "Futuro"))
    assert made["set"].endswith("_by_futuro_clan_bot")
    assert made["emoji"] is None
    assert made["files"]["war"] == "f0"


def test_build_says_no_without_a_badge():
    assert asyncio.run(stickers.build(FakeBot(), FakeVault(), CLAN, {}, 7, "Futuro")) is None


def test_build_says_no_when_the_badge_does_not_arrive(monkeypatch):
    async def no_badge(url, client=None):
        return None

    monkeypatch.setattr(stickers, "badge_of", no_badge)
    clan_json = {"badgeUrls": {"large": BADGE_URL}}
    assert asyncio.run(stickers.build(FakeBot(), FakeVault(), CLAN, clan_json, 7, "Futuro")) is None


class StickerStore(ChatStore):
    def __init__(self, role="coLeader"):
        super().__init__(state={(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"},
                                (CLAN.alias, "members"): {"#P1": {"role": role}}},
                         links=[SimpleNamespace(tag="#P1", user_id=USER, dm=True)])
        self.vault = FakeVault()


class FakeCoc:
    def __init__(self, data):
        self.data = data

    async def clan(self, tag):
        return self.data, None


def command_context(store, bot, data=None):
    ctx = context(store)
    ctx.bot_data["coc"] = FakeCoc(
        {"badgeUrls": {"large": BADGE_URL}} if data is None else data)
    ctx.bot = bot
    return ctx


def test_the_command_and_its_keys_are_in_place():
    assert ("stickers", ["adesivi"]) in handlers.COMMANDS
    assert handlers.HANDLERS["stickers"] is handlers.cmd_stickers
    for key in KEYS:
        assert key in CATALOGS["it"] and key in CATALOGS["en"], key
    assert CATALOGS["it"]["setup.event.system.stickers"] != CATALOGS["en"]["setup.event.system.stickers"]


def test_the_registry_carries_the_announcement_of_the_new_sets():
    meta = EVENTS["system.stickers"]
    assert meta["pack"] == "members" and meta["default"] == "group"
    assert meta["allowed"] == GROUP_ONLY and meta["intensity"] is None


def test_the_command_draws_the_sets_and_writes_them_down(monkeypatch):
    async def fake_badge(url, client=None):
        return badge_png()

    monkeypatch.setattr(stickers, "badge_of", fake_badge)
    store = StickerStore()
    bot = FakeBot()
    update = group_update()
    asyncio.run(handlers.cmd_stickers(update, command_context(store, bot)))
    texts = [text for text, _ in update.effective_message.sent]
    assert IT.t("stickers.making") in texts[0]
    made = store.state[(CLAN.alias, stickers.STATE)]
    assert made["files"]["war"] == "f0"
    assert IT.t("stickers.done", set=made["set"], emoji=made["emoji"]) in texts[1]
    assert IT.t("stickers.owner") in texts[1]
    assert store.state[(CLAN.alias, "stickers_new")] == {"set": made["set"]}
    assert [entry[2] for entry in bot.created] == [
        CLAN.name, f"{CLAN.name} · {IT.t('stickers.emoji.title')}"]


def test_the_command_does_not_hand_out_a_link_to_an_emoji_set_that_is_missing(monkeypatch):
    async def fake_badge(url, client=None):
        return badge_png()

    monkeypatch.setattr(stickers, "badge_of", fake_badge)
    store = StickerStore()
    update = group_update()
    asyncio.run(handlers.cmd_stickers(update, command_context(store, NoEmojiBot())))
    last = update.effective_message.sent[-1][0]
    made = store.state[(CLAN.alias, stickers.STATE)]
    assert made["emoji"] is None
    assert "addemoji" not in last
    assert IT.t("stickers.done_no_emoji", set=made["set"]) in last
    assert IT.t("stickers.owner") in last


def test_the_command_says_so_when_the_badge_is_missing():
    store = StickerStore()
    update = group_update()
    asyncio.run(handlers.cmd_stickers(update, command_context(store, FakeBot(), {})))
    assert IT.t("stickers.failed") in update.effective_message.sent[-1][0]
    assert (CLAN.alias, stickers.STATE) not in store.state


def test_the_command_is_for_who_can_change_the_settings():
    store = StickerStore(role="member")
    update = group_update()
    asyncio.run(handlers.cmd_stickers(update, command_context(store, FakeBot())))
    assert update.effective_message.sent == [(IT.t("h.admin_only"), None)]


class StickerBot(RoutingBot):
    def __init__(self):
        super().__init__()
        self.stickers = []

    async def send_sticker(self, chat_id, sticker, disable_notification=None,
                           message_thread_id=None):
        self.stickers.append((chat_id, sticker, message_thread_id))
        return SimpleNamespace(message_id=1)


PACK = {"set": "cbsetname_by_futuro_clan_bot", "emoji": "cesetname_by_futuro_clan_bot",
        "files": {"war": "f0", "win": "f1", "loss": "f2", "gift": "f3", "night": "f4"}}


def war_setup(stored=FUTURO, state=None):
    store = RoutingStore(state=state)
    bot = StickerBot()
    poller = Poller(supervisor_for(bot), store, None)
    t = Tick(WAR_CLAN, NOW)
    t.settings = settings_mod.effective(stored, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.members = copy.deepcopy(MEMBERS)
    t.season = scoring.empty_season("2026-09")
    return poller, store, bot, t


def play_end(poller, store, t, kind="war", day=None):
    asyncio.run(store.set_state(WAR_CLAN.alias, "war" if kind == "war" else "cwl_war", STARTED))
    asyncio.run(poller.track_war(t, copy.deepcopy(ENDED), kind, day))
    asyncio.run(poller.flush(t))


def test_the_end_of_the_war_sends_the_sticker_of_the_result():
    assert events_mod.war_result(ENDED) == "win"
    poller, store, bot, t = war_setup(state={(WAR_CLAN.alias, stickers.STATE): copy.deepcopy(PACK)})
    play_end(poller, store, t)
    assert t.sticker is None
    assert bot.stickers == [(WAR_CLAN.chat_id, "f1", None)]


def test_no_sticker_without_a_set_or_when_the_end_of_the_war_is_silent():
    poller, store, bot, t = war_setup()
    play_end(poller, store, t)
    assert bot.stickers == []
    poller, store, bot, t = war_setup(routed(FUTURO, "war.end", "off"),
                                      {(WAR_CLAN.alias, stickers.STATE): copy.deepcopy(PACK)})
    play_end(poller, store, t)
    assert bot.stickers == []


def test_the_sticker_follows_the_route_of_the_card_that_closed_the_war():
    poller, store, bot, t = war_setup(state={(WAR_CLAN.alias, stickers.STATE): copy.deepcopy(PACK)})
    play_end(poller, store, t, "cwl", 3)
    assert t.sticker_event == "cwl.day" and bot.stickers == [(WAR_CLAN.chat_id, "f1", None)]
    poller, store, bot, t = war_setup(routed(FUTURO, "cwl.day", "off"),
                                      {(WAR_CLAN.alias, stickers.STATE): copy.deepcopy(PACK)})
    play_end(poller, store, t, "cwl", 3)
    assert bot.stickers == []


def test_the_group_learns_about_the_new_sets_only_once():
    poller, store, _, t = war_setup(state={(WAR_CLAN.alias, "stickers_new"): {"set": PACK["set"]}})
    asyncio.run(poller.announce_stickers(t))
    assert t.L.t("stickers.ready", set=PACK["set"]) in boards.lines_of(t.boards, "members")[0]
    asyncio.run(poller.announce_stickers(t))
    assert len(boards.lines_of(t.boards, "members")) == 1
