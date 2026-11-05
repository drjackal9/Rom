import asyncio
import copy
import json
from datetime import timedelta
from types import SimpleNamespace

from telegram.constants import ChatMemberStatus, ChatType

from clashbot import boards, handlers, i18n, render, scoring
from clashbot import settings as settings_mod
from clashbot.poller import HANDOVER_DAYS, Poller, Tick
from test_routing import ATTACKED, CLAN, ENDED, FUTURO, MEMBERS, NOW, FakeBot, FakeStore, link, supervisor_for

IT = i18n.locale("it")
ALIAS = "bot-1"
USER = 7
EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
CLAN_JSON = {"tag": "#CLAN1", "name": "Futuro", "location": {"countryCode": "IT"},
             "memberList": [{"tag": "#P1", "name": "Mario", "role": "leader"}]}


class JoinBot:
    def __init__(self):
        self.username = "ClanBoardProvaBot"
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=1)


class JoinStore:
    def __init__(self, links=(), served=None):
        self.links = list(links)
        self.served = served or {}
        self.state = {}
        self.kv = {}
        self.added = []
        self.log = []

    async def add_log(self, alias, entry, at=None):
        self.log.append(entry)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

    async def active_clans(self, bot_alias=None):
        return []

    async def links_by_user(self, user_id):
        return [row for row in self.links if row.user_id == user_id]

    async def bot_for_tag(self, tag):
        return self.served.get(tag)

    async def count_clans(self, bot_alias):
        return 0

    async def add_clan(self, chat_id, tag, name, added_by=None, bot_alias=None):
        self.added.append((chat_id, tag, added_by, bot_alias))
        return SimpleNamespace(alias=CLAN.alias, chat_id=chat_id, tag=tag, name=name, bot_alias=bot_alias)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def get_secret(self, kind):
        return None

    async def bot_by_alias(self, alias):
        return None

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj


class JoinCoc:
    def __init__(self, players=None, clan=None):
        self.players = players or {}
        self.clan_json = clan if clan is not None else CLAN_JSON

    async def player(self, tag):
        return copy.deepcopy(self.players.get(tag)), None

    async def clan(self, tag):
        return copy.deepcopy(self.clan_json), None


def player(role, clan_tag="#CLAN1", name="Mario"):
    return {"tag": "#P1", "name": name, "role": role, "clan": {"tag": clan_tag, "name": "Futuro"}}


def join_update(user_id=USER, status=ChatMemberStatus.MEMBER, old=ChatMemberStatus.LEFT):
    chat = SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP)
    user = SimpleNamespace(id=user_id, language_code="it")
    return SimpleNamespace(
        my_chat_member=SimpleNamespace(chat=chat, from_user=user,
                                       new_chat_member=SimpleNamespace(status=status),
                                       old_chat_member=SimpleNamespace(status=old)),
        effective_chat=chat,
        effective_user=user,
        effective_message=None,
    )


def join(store, coc, bot=None):
    bot = bot or JoinBot()
    context = SimpleNamespace(bot=bot, bot_data={"store": store, "coc": coc, "bot_alias": ALIAS}, user_data={})
    asyncio.run(handlers.on_my_chat_member(join_update(), context))
    return bot


def linked(tag="#P1", user_id=USER, verified=True):
    return SimpleNamespace(tag=tag, user_id=user_id, name="Mario", dm=True, verified=verified)


def test_il_capo_solo_rivendicato_non_collega_il_clan_da_solo():
    store = JoinStore(links=[linked(verified=False)])
    bot = join(store, JoinCoc({"#P1": player("leader")}))
    assert store.added == []
    assert [text for _, text in bot.sent] == [render.not_linked_view(IT)]


def test_the_bot_links_by_itself_the_only_clan_of_the_leader_who_added_it():
    store = JoinStore(links=[linked()])
    bot = join(store, JoinCoc({"#P1": player("leader")}))
    assert store.added == [(CLAN.chat_id, "#CLAN1", USER, ALIAS)]
    texts = [text for _, text in bot.sent]
    assert IT.t("h.auto_linked") in texts
    assert IT.t("setup.needed") in texts


def test_a_member_who_is_not_a_leader_links_nothing():
    store = JoinStore(links=[linked()])
    bot = join(store, JoinCoc({"#P1": player("member")}))
    assert store.added == []
    assert [text for _, text in bot.sent] == [render.not_linked_view(IT)]


def test_a_leader_of_two_clans_links_nothing():
    store = JoinStore(links=[linked(), linked("#P2", USER)])
    coc = JoinCoc({"#P1": player("leader"), "#P2": player("coLeader", "#CLAN2")})
    bot = join(store, coc)
    assert store.added == []
    assert [text for _, text in bot.sent] == [render.not_linked_view(IT)]


def test_a_clan_already_served_is_not_linked_again():
    store = JoinStore(links=[linked()], served={"#CLAN1": "bot-2"})
    bot = join(store, JoinCoc({"#P1": player("leader")}))
    assert store.added == []
    assert [text for _, text in bot.sent] == [render.not_linked_view(IT)]


def test_il_bot_nato_per_il_clan_lo_collega_da_solo_nel_gruppo():
    store = JoinStore(links=[linked()], served={"#CLAN1": ALIAS})
    bot = join(store, JoinCoc({"#P1": player("leader")}))
    assert store.added == [(CLAN.chat_id, "#CLAN1", USER, ALIAS)]
    assert IT.t("h.auto_linked") in [text for _, text in bot.sent]


def test_a_stranger_who_adds_the_bot_links_nothing():
    store = JoinStore()
    bot = join(store, JoinCoc())
    assert store.added == []
    assert [text for _, text in bot.sent] == [render.not_linked_view(IT)]


def setup(stored=None, links=None, now=NOW, state=None):
    store = FakeStore(state=state, links=links)
    bot = FakeBot()
    bot.username = "ProvaBot"
    poller = Poller(supervisor_for(bot), store, None)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(stored if stored is not None else FUTURO, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.members = copy.deepcopy(MEMBERS)
    t.season = scoring.empty_season("2026-09")
    return poller, store, bot, t


async def end_a_war(poller, store, t):
    await store.set_state(CLAN.alias, "war", copy.deepcopy(ATTACKED))
    await poller.track_war(t, copy.deepcopy(ENDED), "war", None)
    await poller.flush(t)
    t.chunks, t.threads = [], {}


def nudge_text(linked_count, total):
    return render.link_nudge(IT, linked_count, total, "ProvaBot")


def said(t):
    return "\n\n".join(boards.lines_of(t.boards, "members"))


def test_after_a_war_a_clan_with_few_links_is_invited():
    poller, store, bot, t = setup(links={"#P1": link("#P1", 7, "Mario")})
    asyncio.run(end_a_war(poller, store, t))
    assert render.board_body(nudge_text(1, 3)) in said(t)
    assert store.kv.get(f"nudge:{CLAN.alias}")


def test_the_invitation_is_not_repeated_the_same_week():
    poller, store, bot, t = setup(links={"#P1": link("#P1", 7, "Mario")})
    asyncio.run(end_a_war(poller, store, t))
    righe = len(boards.lines_of(t.boards, "members"))
    asyncio.run(end_a_war(poller, store, t))
    assert len(boards.lines_of(t.boards, "members")) == righe


def test_a_clan_where_most_are_linked_is_not_invited():
    poller, store, bot, t = setup()
    asyncio.run(end_a_war(poller, store, t))
    assert IT.t("nudge.body", linked=1, total=3, pct=IT.pct(33.3)) not in said(t)
    assert store.kv.get(f"nudge:{CLAN.alias}") is None


def test_the_invitation_follows_the_members_pack():
    stored = settings_mod.migrate(FUTURO)
    stored["packs"]["members"] = False
    poller, store, bot, t = setup(stored, links={"#P1": link("#P1", 7, "Mario")})
    asyncio.run(end_a_war(poller, store, t))
    assert IT.t("nudge.body", linked=1, total=3, pct=IT.pct(33.3)) not in said(t)
    assert store.kv.get(f"nudge:{CLAN.alias}") is None


def test_the_invitation_carries_the_share_and_the_link():
    text = render.link_nudge(IT, 1, 3, "ProvaBot")
    assert IT.t("nudge.title") in text
    assert "ProvaBot" in text and IT.pct(100 / 3) in text


class OwnerStore(FakeStore):
    def __init__(self, bots=(), clans=(), members=None, links=None, owner_links=None):
        super().__init__(state={(alias, "members"): value for alias, value in (members or {}).items()},
                         links=links or {})
        self.bot_rows = list(bots)
        self.clan_rows = list(clans)
        self.owner_links = owner_links or {}
        self.owners = []

    async def bots(self, active_only=False):
        return [row for row in self.bot_rows if row.active or not active_only]

    async def active_clans(self, bot_alias=None):
        return [row for row in self.clan_rows if row.bot_alias == bot_alias]

    async def count_clans(self, bot_alias):
        return len([row for row in self.clan_rows if row.bot_alias == bot_alias])

    async def links_by_user(self, user_id):
        return list(self.owner_links.get(user_id, []))

    async def set_bot_owner(self, alias, owner_id):
        self.owners.append((alias, owner_id))
        for row in self.bot_rows:
            if row.alias == alias:
                row.owner_id = owner_id
        return None


def bot_row(owner_id=99, alias=ALIAS, kind="worker", active=True):
    return SimpleNamespace(alias=alias, owner_id=owner_id, kind=kind, active=active, username="ProvaBot")


def owner_setup(owner_id=99, role="leader", owner_role=None, leader_linked=True):
    members = {"#P1": {"name": "Mario", "role": role}, "#P9": {"name": "Capo", "role": owner_role or "member"}}
    store = OwnerStore(
        bots=[bot_row(owner_id)],
        clans=[SimpleNamespace(alias=CLAN.alias, chat_id=CLAN.chat_id, tag=CLAN.tag, name=CLAN.name,
                               bot_alias=ALIAS)],
        members={CLAN.alias: members},
        links={"#P1": link("#P1", USER, "Mario")} if leader_linked else {},
        owner_links={owner_id: [link("#P9", owner_id, "Capo")]},
    )
    store.state[(CLAN.alias, "settings")] = settings_mod.migrate(FUTURO)
    bot = FakeBot()
    supervisor = supervisor_for(bot)
    supervisor.owner_changed = lambda alias, user_id: store.kv.__setitem__("refreshed", (alias, user_id))
    return Poller(supervisor, store, None), store, bot


def test_an_owner_who_still_leads_keeps_the_bot():
    poller, store, bot = owner_setup(owner_role="coLeader")
    asyncio.run(poller.owner_jobs(NOW))
    assert store.kv.get(f"handover:{ALIAS}") is None
    assert store.owners == [] and bot.sent == []


def test_the_handover_starts_the_clock_and_waits():
    poller, store, bot = owner_setup()
    asyncio.run(poller.owner_jobs(NOW))
    assert store.kv[f"handover:{ALIAS}"]["since"] == NOW.timestamp()
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=HANDOVER_DAYS - 1)))
    assert store.owners == [] and bot.sent == []


def test_after_the_wait_the_bot_passes_to_the_linked_leader():
    poller, store, bot = owner_setup()
    asyncio.run(poller.owner_jobs(NOW))
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=HANDOVER_DAYS)))
    assert store.owners == [(ALIAS, USER)]
    assert [chat for chat, _, _ in bot.sent] == [USER, 99]
    for _, text, _ in bot.sent:
        assert IT.t("handover.telegram") in text
    assert store.kv.get(f"handover:{ALIAS}") is None
    assert store.kv.get("refreshed") == (ALIAS, USER)


def test_the_handover_speaks_to_each_one_in_his_own_language():
    poller, store, bot = owner_setup()
    store.links["#P1"] = link("#P1", USER, "Mario", lang="de")
    store.owner_links[99] = [link("#P9", 99, "Capo", lang="fr")]
    asyncio.run(poller.owner_jobs(NOW))
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=HANDOVER_DAYS)))
    assert store.owners == [(ALIAS, USER)]
    heir, old = bot.sent[0], bot.sent[1]
    assert heir[1] == render.handover_new(i18n.locale("de"), CLAN.name, HANDOVER_DAYS)
    assert old[1] == render.handover_old(i18n.locale("fr"), "Mario", HANDOVER_DAYS)


def test_whoever_has_no_recorded_language_hears_the_clan_one():
    poller, store, bot = owner_setup()
    store.owner_links[99] = []
    asyncio.run(poller.owner_jobs(NOW))
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=HANDOVER_DAYS)))
    assert bot.sent[0][1] == render.handover_new(IT, CLAN.name, HANDOVER_DAYS)
    assert bot.sent[1][1] == render.handover_old(IT, "Mario", HANDOVER_DAYS)


def test_without_a_linked_leader_nothing_moves():
    poller, store, bot = owner_setup(leader_linked=False)
    asyncio.run(poller.owner_jobs(NOW))
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=HANDOVER_DAYS)))
    assert store.owners == [] and bot.sent == []


def test_the_clock_stops_when_the_owner_leads_again():
    poller, store, bot = owner_setup()
    asyncio.run(poller.owner_jobs(NOW))
    store.state[(CLAN.alias, "members")]["#P9"]["role"] = "leader"
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=1)))
    assert store.kv.get(f"handover:{ALIAS}") is None
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=HANDOVER_DAYS + 2)))
    assert store.owners == []


def test_a_bot_that_is_not_running_is_left_alone():
    poller, store, bot = owner_setup()
    store.bot_rows = [bot_row(99, alias="bot-spento")]
    asyncio.run(poller.owner_jobs(NOW))
    asyncio.run(poller.owner_jobs(NOW + timedelta(days=HANDOVER_DAYS)))
    assert store.kv.get("handover:bot-spento") is None and store.owners == []


def test_the_console_bot_is_left_alone():
    poller, store, bot = owner_setup()
    store.bot_rows = [bot_row(99, alias="console", kind="console")]
    asyncio.run(poller.owner_jobs(NOW))
    assert store.kv.get("handover:console") is None and store.owners == []


def test_the_handover_keys_are_written_in_italian_and_in_english():
    catalogs = {code: json.load(open(i18n.LOCALE_DIR / f"{code}.json", encoding="utf-8"))
                for code in ("it", "en")}
    for key in ("handover.title", "handover.old", "handover.new", "handover.telegram",
                "nudge.title", "nudge.body", "h.auto_linked"):
        assert catalogs["it"][key] and catalogs["en"][key], key
        assert catalogs["it"][key] != catalogs["en"][key], key
