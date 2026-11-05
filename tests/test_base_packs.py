import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram.constants import PollLimit
from test_bases import (BaseStore, SETTINGS, callback, context_for, datas_of, message_update,
                        row_of, store_with)
from test_flows import CLAN as FLOW_CLAN
from test_routing import FUTURO, feed_rows, setup as tick_setup

from clashbot import acts, base_packs, base_ui, bases, i18n, progress as progress_mod, reasons
from clashbot import settings as settings_mod

MONDAY = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
SUNDAY = datetime(2026, 9, 13, 9, tzinfo=timezone.utc)
IT = i18n.locale("it")
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")


def base_row(alias, hall, label="war", village="home", name="Mario", clan_alias=CLAN.alias):
    return {"alias": alias, "clan_alias": clan_alias, "label": label, "village": village,
            "hall": hall, "shared": False, "published": False, "name": name,
            "id": f"TH{hall}:HV:{alias.upper()}0000"}


class FakeStore:
    def __init__(self, state=None, rows=(), members=None, links=()):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.rows = list(rows)
        self.members = members or {}
        self.links = list(links)
        self.copied = []
        self.flags = []
        self.kv = {}
        self.ttls = []
        self.kv_deleted = []
        self.added = []
        self.logs = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)
        self.ttls.append(ttl)

    async def kv_del(self, key):
        self.kv_deleted.append(key)

    async def clan_bases(self, clan_alias, village=None, hall=None, limit=10):
        return [r for r in self.rows if r["clan_alias"] == clan_alias
                and (village is None or r["village"] == village)
                and (hall is None or r["hall"] == hall)][:limit]

    async def base_by_alias(self, alias):
        return next((r for r in self.rows if r["alias"] == alias), None)

    async def set_base_flags(self, alias, shared=None, published=None):
        self.flags.append((alias, shared, published))
        return True

    async def copy_bases(self, source_alias, target_alias, village, label, keep=100):
        self.copied.append((source_alias, target_alias, village, label))
        return 3

    async def links_by_user(self, user_id):
        return list(self.links)

    async def add_base(self, clan_alias, layout, label, payload, keep=100):
        self.added.append((clan_alias, label, layout["village"], layout["hall"],
                           payload.get("name")))
        return f"base-{len(self.added)}"

    async def add_log(self, alias, row, at=None):
        self.logs.append(dict(row))
        return True


class PollBot:
    def __init__(self):
        self.polls = []
        self.stopped = []

    async def send_poll(self, chat_id, question, options, **kw):
        self.polls.append((chat_id, question, options, kw.get("message_thread_id")))
        return SimpleNamespace(message_id=1, poll=SimpleNamespace(id="poll-1"))

    async def stop_poll(self, chat_id, message_id):
        self.stopped.append((chat_id, message_id))


class FakePoller:
    def __init__(self, store, bot=None, to="group"):
        self.store = store
        self.bot = bot if bot is not None else PollBot()
        self.to = to
        self.dispatched = []

    def bot_for(self, clan):
        return self.bot

    def destination(self, conf, event):
        return self.to, None, None

    async def dispatch(self, t, event, render_text, member_tag=None):
        self.dispatched.append((event, render_text(t.L)))


def tick(now=MONDAY):
    return SimpleNamespace(clan=CLAN, now=now, L=IT, tz="UTC", quiet=False,
                           settings={"lang": "it", "tz": "UTC"}, chunks=[], dm=[])


def test_period_start_is_public_and_still_lands_on_monday():
    assert progress_mod.period_start(MONDAY, "UTC", "week") == int(
        datetime(2026, 9, 14, tzinfo=timezone.utc).timestamp())
    assert progress_mod.period_start(SUNDAY, "UTC", "week") == int(
        datetime(2026, 9, 7, tzinfo=timezone.utc).timestamp())


def test_only_a_verified_leader_publishes():
    members = {"#P1": {"role": "leader"}, "#P2": {"role": "admin"}}
    leader = FakeStore(state={(CLAN.alias, "members"): members},
                       links=[SimpleNamespace(tag="#P1")])
    elder = FakeStore(state={(CLAN.alias, "members"): members},
                      links=[SimpleNamespace(tag="#P2")])
    assert asyncio.run(base_packs.is_verified(leader, 7, CLAN)) is True
    assert asyncio.run(base_packs.is_verified(elder, 7, CLAN)) is False


def test_the_verified_roles_are_the_ones_of_the_leaders():
    from clashbot.verify import LEADER_ROLES

    assert base_packs.VERIFIED is LEADER_ROLES


def test_publish_flips_every_base_of_that_village_and_label():
    store = FakeStore(rows=[base_row("base-1", 16), base_row("base-2", 15),
                            base_row("base-3", 14, label="farm")])
    assert asyncio.run(base_packs.publish(store, CLAN, "home", "war", True)) == 2
    assert store.flags == [("base-1", None, True), ("base-2", None, True)]


def test_import_copies_and_says_how_many():
    store = FakeStore()
    assert asyncio.run(base_packs.import_pack(store, CLAN, "clan-9", "home", "war")) == 3
    assert store.copied == [("clan-9", CLAN.alias, "home", "war")]
    assert store.state[(CLAN.alias, base_packs.PACK_QUEUE)] == [
        {"source": "clan-9", "village": "home", "label": "war", "n": 3}]


def test_poll_pick_takes_the_fullest_hall_and_stays_inside_telegram():
    rows = [base_row(f"base-{i}", 16) for i in range(14)] + [base_row("base-x", 15)]
    picked = base_packs.poll_pick(rows)
    assert len(picked) == PollLimit.MAX_OPTION_NUMBER
    assert {row["hall"] for row in picked} == {16}
    assert base_packs.poll_pick([base_row("base-1", 16)]) == []
    assert base_packs.poll_pick([]) == []


def test_poll_options_fit_the_telegram_length():
    rows = [base_row("base-1", 16, name="X" * 200), base_row("base-2", 15)]
    for option in base_packs.poll_options(IT, rows):
        assert 0 < len(option) <= PollLimit.MAX_OPTION_LENGTH


def test_the_weekly_poll_opens_once_a_week_through_the_shared_polls_module():
    rows = [base_row(f"base-{i}", 16) for i in range(3)]
    store = FakeStore(rows=rows)
    poller = FakePoller(store)
    assert asyncio.run(base_packs.weekly_poll(poller, tick())) is True
    assert asyncio.run(base_packs.weekly_poll(poller, tick())) is False
    assert len(poller.bot.polls) == 1
    assert poller.bot.polls[0][1] == IT.t("bases.poll.question")
    saved = store.state[(CLAN.alias, base_packs.POLL_STATE)]
    assert saved["poll_id"] == "poll-1" and saved["bases"] == [row["alias"] for row in rows]
    assert store.kv["poll:poll-1"] == {"state": base_packs.POLL_STATE}
    assert store.ttls == [7 * progress_mod.DAY]


def test_the_weekly_poll_stays_quiet_with_less_than_two_bases():
    poller = FakePoller(FakeStore(rows=[base_row("base-1", 16)]))
    assert asyncio.run(base_packs.weekly_poll(poller, tick())) is False
    assert poller.bot.polls == []


def test_the_weekly_poll_respects_a_clan_that_turned_the_event_off():
    rows = [base_row(f"base-{i}", 16) for i in range(3)]
    poller = FakePoller(FakeStore(rows=rows), to="off")
    assert asyncio.run(base_packs.weekly_poll(poller, tick())) is False
    assert poller.bot.polls == []


def test_settling_the_poll_marks_the_winner_without_pushing_it_into_the_library():
    rows = [base_row("base-1", 16, name="Mario"), base_row("base-2", 16, name="Luigi")]
    bot = PollBot()
    store = FakeStore(rows=rows, state={(CLAN.alias, base_packs.POLL_STATE): {
        "poll_id": "p1", "message_id": 5, "bases": ["base-1", "base-2"],
        "votes": {"7": {"name": "Peach", "option": 1}, "8": {"name": "Toad", "option": 1}}}})
    poller = FakePoller(store, bot)
    assert asyncio.run(base_packs.settle_poll(poller, tick())) is True
    assert bot.stopped == [(CLAN.chat_id, 5)]
    assert store.state[(CLAN.alias, base_packs.WEEK_STATE)]["winner"] == "base-2"
    assert store.flags == []
    assert store.kv_deleted == ["poll:p1"]
    assert poller.dispatched and poller.dispatched[0][0] == "bases.poll"
    assert "Luigi" in poller.dispatched[0][1]
    assert (CLAN.alias, base_packs.POLL_STATE) not in store.state
    assert asyncio.run(base_packs.settle_poll(poller, tick())) is False


def test_a_poll_nobody_voted_crowns_nobody():
    store = FakeStore(rows=[base_row("base-1", 16)], state={
        (CLAN.alias, base_packs.POLL_STATE): {"poll_id": "p1", "message_id": 5,
                                              "bases": ["base-1"], "votes": {}}})
    poller = FakePoller(store, PollBot())
    assert asyncio.run(base_packs.settle_poll(poller, tick())) is False
    assert store.flags == [] and poller.dispatched == []
    assert (CLAN.alias, base_packs.POLL_STATE) not in store.state
    assert (CLAN.alias, base_packs.WEEK_STATE) not in store.state


def test_the_winner_of_the_week_opens_the_list_of_the_clan_with_its_mark():
    rows = [base_row("base-1", 16, name="Mario"), base_row("base-2", 16, name="Luigi")]
    store = FakeStore(rows=rows, state={
        (CLAN.alias, base_packs.WEEK_STATE): {"week": 1, "winner": "base-2"}})
    ordered = asyncio.run(base_packs.winner_first(store, CLAN.alias, rows, "home", 16))
    assert [row["alias"] for row in ordered] == ["base-2", "base-1"]
    assert "🏆" in bases.row_line(IT, ordered[0], 0)
    assert "🏆" not in bases.row_line(IT, ordered[1], 1)
    assert rows[1].get("winner") is None


def test_without_a_winner_the_list_of_the_clan_stays_as_it_is():
    rows = [base_row("base-1", 16), base_row("base-2", 16)]
    store = FakeStore(rows=rows)
    assert asyncio.run(base_packs.winner_first(store, CLAN.alias, rows, "home", 16)) == rows


def test_the_winner_comes_back_even_from_outside_the_page():
    page = [base_row(f"base-{i}", 16) for i in range(bases.PAGE)]
    crowned = base_row("base-old", 16, name="Peach")
    store = FakeStore(rows=page + [crowned], state={
        (CLAN.alias, base_packs.WEEK_STATE): {"winner": "base-old"}})
    ordered = asyncio.run(base_packs.winner_first(store, CLAN.alias, page, "home", 16))
    assert ordered[0]["alias"] == "base-old" and len(ordered) == len(page)


def test_the_winner_does_not_jump_into_another_village_or_into_another_clan():
    builder = [base_row("base-1", 10, village="builder")]
    home = base_row("base-2", 16)
    store = FakeStore(rows=builder + [home], state={
        (CLAN.alias, base_packs.WEEK_STATE): {"winner": "base-2"}})
    assert asyncio.run(base_packs.winner_first(store, CLAN.alias, builder, "builder", 10)) == builder
    other = FakeStore(rows=[base_row("base-2", 16, clan_alias="clan-9")], state={
        (CLAN.alias, base_packs.WEEK_STATE): {"winner": "base-2"}})
    assert asyncio.run(base_packs.winner_first(other, CLAN.alias, [], "home", 16)) == []


def test_the_new_week_does_not_forget_who_won_the_last_one():
    rows = [base_row(f"base-{i}", 16) for i in range(3)]
    store = FakeStore(rows=rows, state={
        (CLAN.alias, base_packs.WEEK_STATE): {"week": 1, "winner": "base-1"}})
    poller = FakePoller(store)
    assert asyncio.run(base_packs.weekly_poll(poller, tick())) is True
    marker = store.state[(CLAN.alias, base_packs.WEEK_STATE)]
    assert marker["winner"] == "base-1" and marker["week"] > 1


def test_the_real_poller_routes_the_base_poll_like_any_other_event():
    rows = [base_row("base-1", 16), base_row("base-2", 16)]
    poller, store, bot, t = tick_setup(FUTURO)

    async def clan_bases(clan_alias, village=None, hall=None, limit=10):
        return list(rows)

    store.clan_bases = clan_bases
    assert asyncio.run(base_packs.weekly_poll(poller, t)) is True
    assert bot.polls == [(CLAN.chat_id, None)]
    assert store.state[(CLAN.alias, base_packs.POLL_STATE)]["bases"] == ["base-1", "base-2"]
    assert store.kv["poll:poll-1"] == {"state": base_packs.POLL_STATE}


def test_the_imported_packs_are_announced_once_and_then_forgotten():
    queued = [{"source": CLAN.alias, "village": "home", "label": "war", "n": 3}]
    poller, store, bot, t = tick_setup(FUTURO, state={(CLAN.alias, base_packs.PACK_QUEUE): queued})
    asyncio.run(poller.announce_bases(t))
    asyncio.run(poller.flush(t))
    text = "\n".join(row[1] for row in feed_rows(store, 7))
    assert bot.sent == []
    assert CLAN.name in text and IT.t("bases.tab.packs") in text
    assert (CLAN.alias, base_packs.PACK_QUEUE) not in store.state
    already = len(feed_rows(store, 7))
    t.chunks, t.threads = [], {}
    asyncio.run(poller.announce_bases(t))
    asyncio.run(poller.flush(t))
    assert len(feed_rows(store, 7)) == already


def test_a_pack_asks_only_for_the_published_bases(tmp_path):
    store = store_with(tmp_path)
    store.pool.values = [[row_of(store, published=True)]]
    rows = asyncio.run(store.published_bases("clan-1", "home", "war", bases.PAGE))
    assert rows[0]["published"] is True and rows[0]["name"] == "Mario"
    assert "where published" in store.pool.log[0][1]
    assert store.pool.log[0][2] == ("clan-1", "home", "war", bases.PAGE)


def test_the_catalogue_counts_the_packs_by_clan_village_and_label(tmp_path):
    store = store_with(tmp_path)
    store.pool.values = [[{"clan_alias": "clan-9", "village": "home", "label": "war",
                           "n": 4, "last": None}]]
    assert asyncio.run(store.base_packs(bases.PAGE)) == [
        {"clan_alias": "clan-9", "village": "home", "label": "war", "n": 4}]
    assert "group by clan_alias, village, label" in store.pool.log[0][1]
    assert store.pool.log[0][2] == (bases.PAGE,)


def test_copying_a_pack_lands_in_the_other_clan_without_leaking_the_payload(tmp_path):
    store = store_with(tmp_path, statuses=["base-9", "DELETE 0"])
    store.pool.values = [[row_of(store, published=True)]]
    assert asyncio.run(store.copy_bases("clan-9", "clan-1", "home", "war")) == 1
    log = store.pool.log
    assert log[1] == "begin" and log[-1] == "commit"
    insert = log[2]
    assert insert[0].startswith("insert into base_layouts")
    assert insert[1][1] == "clan-1" and insert[1][2] == "war"
    written = " ".join(str(value) for value in insert[1])
    assert "Mario" not in written and "clan-9" not in written


class PackStore(BaseStore):
    def __init__(self, packs=(), **kw):
        super().__init__(**kw)
        self.packs = [dict(pack) for pack in packs]
        self.copied = []

    async def base_packs(self, limit=10):
        return [dict(pack) for pack in self.packs[:limit]]

    async def copy_bases(self, source_alias, target_alias, village, label, keep=100):
        self.copied.append((source_alias, target_alias, village, label))
        return 2


PACK = {"clan_alias": FLOW_CLAN.alias, "village": "home", "label": "war", "n": 4}


def member_link(tag):
    return SimpleNamespace(alias=FLOW_CLAN.alias, tag=tag, user_id=7, name="Mario", dm=True,
                           lang=None)


def test_the_packs_tab_shows_the_catalogue_with_the_name_of_the_clan():
    store = PackStore(packs=[PACK], state=SETTINGS, owner="7")
    text, keyboard = asyncio.run(
        base_ui.hub_view(message_update(), context_for(store), FLOW_CLAN, "packs"))
    assert IT.t("bases.tab.packs") in text and FLOW_CLAN.name in text
    datas = datas_of(keyboard)
    assert f"bs:im:{FLOW_CLAN.alias}:home:war" in datas and datas[-1] == "v:menu"
    assert all(len(data.encode()) <= 64 for data in datas)


def test_an_empty_catalogue_says_so():
    store = PackStore(state=SETTINGS, owner="7")
    text, _ = asyncio.run(
        base_ui.hub_view(message_update(), context_for(store), FLOW_CLAN, "packs"))
    assert IT.t("bases.packs.empty") in text


def test_the_import_button_copies_the_pack_into_the_clan():
    store = PackStore(packs=[PACK], state=SETTINGS, owner="7")
    query = callback(store, f"bs:im:{FLOW_CLAN.alias}:home:war")
    assert query.answers[0][0] == IT.t("bases.imported", n=2)
    assert store.copied == [(FLOW_CLAN.alias, FLOW_CLAN.alias, "home", "war")]
    assert store.state[(FLOW_CLAN.alias, base_packs.PACK_QUEUE)][0]["n"] == 2


def test_a_member_cannot_pour_another_clan_pack_into_the_list():
    store = PackStore(packs=[PACK], state=SETTINGS)
    query = callback(store, f"bs:im:{FLOW_CLAN.alias}:home:war")
    assert query.answers[0] == (IT.t("h.admin_only"), True)
    assert store.copied == []
    assert (FLOW_CLAN.alias, base_packs.PACK_QUEUE) not in store.state


def test_only_the_verified_leader_publishes_from_the_hub():
    members = {"#P1": {"role": "leader"}, "#P2": {"role": "admin"}}
    rows = [{"alias": "base-1", "clan_alias": FLOW_CLAN.alias, "label": "war", "village": "home",
             "hall": 16, "shared": False, "published": False, "id": "TH16:HV:AAAA-BBBB_CC",
             "name": "Mario"}]
    state = {**SETTINGS, (FLOW_CLAN.alias, "members"): members}
    elder = PackStore(rows=rows, state=state, owner="7", links=[member_link("#P2")])
    query = callback(elder, "bs:pb:home:war")
    assert query.answers[0] == (IT.t("bases.only_verified"), True)
    assert elder.rows[0]["published"] is False
    leader = PackStore(rows=rows, state=state, owner="7", links=[member_link("#P1")])
    query = callback(leader, "bs:pb:home:war")
    assert query.answers[0][0] == IT.t("bases.published", n=1)
    assert leader.rows[0]["published"] is True


def test_the_publish_button_lives_next_to_the_bases_of_the_clan():
    rows = [{"alias": "base-1", "clan_alias": FLOW_CLAN.alias, "label": "war", "village": "home",
             "hall": 16, "shared": False, "published": False, "id": "TH16:HV:AAAA-BBBB_CC",
             "name": "Mario"}]
    store = PackStore(rows=rows, state=SETTINGS, owner="7")
    _, keyboard = asyncio.run(base_ui.hub_view(message_update(), context_for(store), FLOW_CLAN))
    assert "bs:pb:home:war" in datas_of(keyboard)
    assert "bs:s:packs" in datas_of(keyboard)


def test_the_clan_tab_opens_with_the_base_of_the_week_and_the_library_stays_untouched():
    rows = [{"alias": "base-1", "clan_alias": FLOW_CLAN.alias, "label": "war", "village": "home",
             "hall": 16, "shared": False, "published": False, "id": "TH16:HV:AAAA-BBBB_CC",
             "name": "Mario"},
            {"alias": "base-2", "clan_alias": FLOW_CLAN.alias, "label": "war", "village": "home",
             "hall": 16, "shared": False, "published": False, "id": "TH16:HV:CCCC-DDDD_EE",
             "name": "Luigi"}]
    store = PackStore(rows=rows, owner="7", state={
        **SETTINGS, (FLOW_CLAN.alias, base_packs.WEEK_STATE): {"winner": "base-2"}})
    text, keyboard = asyncio.run(
        base_ui.hub_view(message_update(), context_for(store), FLOW_CLAN))
    assert text.index("Luigi") < text.index("Mario") and "🏆" in text
    assert "bs:sh:base-2" in datas_of(keyboard)
    assert asyncio.run(store.shared_bases(None, None, bases.PAGE)) == []


LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16%3AHV%3AAaBbCcDd"
OTHER_LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH15%3AHV%3AEeFfGgHh"
PROPOSED = {"id": "ab12", "name": "Mario", "label": "war", "village": "home", "hall": 16,
            "link": LINK}


def act_for(store, kind, body, level=None, uid=7, name="Mario"):
    return acts.Act(store=store, clan=CLAN, conf={}, kind=kind, body=dict(body, kind=kind),
                    uid=uid, tag="#P1", name=name, level=level, now=MONDAY, coc=None)


def _niente_base(store):
    async def presa(clan_alias, layout, label, payload, keep=100):
        return None
    return presa


def proposed(store):
    return asyncio.run(base_packs.proposals(store, CLAN.alias))


def test_la_base_proposta_da_un_membro_aspetta_nella_casella():
    store = FakeStore()
    assert asyncio.run(base_packs.propose_act(
        act_for(store, "base.propose", {"link": LINK, "label": "war", "id": "ab12"}))) is True
    assert proposed(store) == [PROPOSED]
    assert store.added == [] and store.logs == []


def test_la_stessa_base_non_si_propone_due_volte():
    store = FakeStore(state={(CLAN.alias, base_packs.PROPOSED_STATE): [PROPOSED]})
    assert asyncio.run(base_packs.propose_act(
        act_for(store, "base.propose", {"link": LINK, "label": "farm", "id": "cd34"}))) == reasons.TAKEN
    assert proposed(store) == [PROPOSED]


def test_lo_stesso_villaggio_scritto_in_un_altro_modo_resta_un_doppione():
    store = FakeStore(state={(CLAN.alias, base_packs.PROPOSED_STATE): [PROPOSED]})
    stesso = LINK.replace("/it?", "/en?").replace("id=TH16", "id=th16")
    assert stesso != LINK and bases.parse_link(stesso)["id"] == bases.parse_link(LINK)["id"]
    assert asyncio.run(base_packs.propose_act(
        act_for(store, "base.propose", {"link": stesso, "label": "war", "id": "cd34"}))) == reasons.TAKEN
    assert proposed(store) == [PROPOSED]
    assert asyncio.run(base_packs.propose_act(
        act_for(store, "base.propose",
                {"link": OTHER_LINK, "label": "war", "id": "ef56"}))) is True
    assert len(proposed(store)) == 2


def test_una_proposta_senza_link_buono_o_senza_etichetta_non_entra():
    store = FakeStore()
    for body in ({"link": "https://esempio.test", "label": "war", "id": "ab12"},
                 {"link": LINK, "label": "pinco", "id": "ab12"},
                 {"link": LINK, "label": "war", "id": ""}):
        assert asyncio.run(base_packs.propose_act(
            act_for(store, "base.propose", body))) == reasons.BAD
    assert proposed(store) == []


def test_il_gestore_che_propone_mette_subito_la_base_del_clan():
    store = FakeStore()
    assert asyncio.run(base_packs.propose_act(
        act_for(store, "base.propose", {"link": LINK, "label": "war", "id": "ab12"},
                level=settings_mod.MANAGER))) is True
    assert store.added == [(CLAN.alias, "war", "home", 16, "Mario")]
    assert proposed(store) == []
    assert store.logs[0]["action"] == base_packs.LOG


def test_il_si_del_gestore_fa_la_base_del_clan_e_svuota_la_casella():
    store = FakeStore(state={(CLAN.alias, base_packs.PROPOSED_STATE): [PROPOSED]})
    boss = act_for(store, "base.accept", {"ref": "ab12"}, level=settings_mod.MANAGER,
                   uid=9, name="Peach")
    assert asyncio.run(base_packs.accept_act(boss)) is True
    assert store.added == [(CLAN.alias, "war", "home", 16, "Mario")]
    assert proposed(store) == []
    assert store.logs == [{"action": base_packs.LOG, "by": 9, "by_name": "Peach",
                           "detail": "war"}]
    assert asyncio.run(base_packs.accept_act(boss)) == reasons.GONE


def test_il_si_su_una_base_gia_presa_dice_gia_presa_non_non_ce_piu():
    store = FakeStore(state={(CLAN.alias, base_packs.PROPOSED_STATE): [PROPOSED]})
    store.add_base = _niente_base(store)
    boss = act_for(store, "base.accept", {"ref": "ab12"}, level=settings_mod.MANAGER)
    assert asyncio.run(base_packs.accept_act(boss)) == reasons.TAKEN
    assert proposed(store) == [PROPOSED] and store.logs == []


def test_il_si_su_una_proposta_sparita_dice_non_ce_piu():
    store = FakeStore()
    boss = act_for(store, "base.accept", {"ref": "ab12"}, level=settings_mod.MANAGER)
    assert asyncio.run(base_packs.accept_act(boss)) == reasons.GONE
    assert asyncio.run(base_packs.reject_act(boss)) == reasons.GONE


def test_il_no_del_gestore_toglie_la_proposta_senza_fare_la_base():
    store = FakeStore(state={(CLAN.alias, base_packs.PROPOSED_STATE): [PROPOSED]})
    boss = act_for(store, "base.reject", {"ref": "ab12"}, level=settings_mod.MANAGER)
    assert asyncio.run(base_packs.reject_act(boss)) is True
    assert proposed(store) == [] and store.added == []
    assert store.logs[0]["action"] == base_packs.LOG
    assert asyncio.run(base_packs.reject_act(boss)) == reasons.GONE


def test_la_casella_delle_proposte_ha_il_suo_tetto():
    rows = [dict(PROPOSED, id=f"id{index:04d}", link=f"{OTHER_LINK}{index:04d}")
            for index in range(base_packs.PROPOSED_KEEP)]
    store = FakeStore(state={(CLAN.alias, base_packs.PROPOSED_STATE): rows})
    assert asyncio.run(base_packs.propose_act(
        act_for(store, "base.propose", {"link": LINK, "label": "war", "id": "ab12"}))) == reasons.TAKEN
    assert len(proposed(store)) == base_packs.PROPOSED_KEEP
