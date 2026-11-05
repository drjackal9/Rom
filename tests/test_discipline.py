import asyncio
import pathlib
from types import SimpleNamespace

from telegram.constants import ChatType
from telegram.error import Forbidden

from clashbot import discipline, feed, guard, render, render_live, settings as settings_mod
from clashbot.events_registry import EVENTS
from clashbot.poller import Poller
from test_flows import (CLAN, FakeBot, FakeMessage, FakeQuery, FakeStore, fake_context,
                        fake_supervisor, fake_update)
from test_war_live import TZ, L, snap, tick

MEMBERS = {
    "#P1": {"name": "Mario", "role": "leader"},
    "#P2": {"name": "Luigi", "role": "member"},
    "#P3": {"name": "Peach", "role": "member"},
}


def leader_link(tag, user_id, name, lang=None):
    return SimpleNamespace(tag=tag, user_id=user_id, name=name, dm=True, lang=lang)


def group_update(user_id=7):
    return SimpleNamespace(
        callback_query=None,
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.GROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it"),
        effective_message=FakeMessage(),
    )


def proposal_setup(stored=None, links=None):
    store, bot = FakeStore(), FakeBot()
    store.links = list(links or [leader_link("#P1", 7, "Mario"), leader_link("#P3", 9, "Peach")])
    store.state[(CLAN.alias, "members")] = dict(MEMBERS)
    poller = Poller(fake_supervisor(bot), store, None)
    t = tick(stored=stored, members=dict(MEMBERS))
    war = snap("warEnded", our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)],
                                        "#P2": [("#E3", 1, 30)]})
    return store, bot, poller, t, war


def propose_and_flush(poller, t, war):
    async def run():
        code = await discipline.propose(poller, t, war, "war", None)
        await poller.flush(t)
        return code

    return asyncio.run(run())


async def forbidden_send(chat_id, text, **kw):
    raise Forbidden("bot bloccato")


def context_with(store, bot):
    context = fake_context(store)
    context.bot = bot
    return context


def test_every_member_with_missed_attacks_becomes_a_proposal_sorted_by_how_many():
    war = snap("warEnded", our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)],
                                        "#P2": [("#E3", 1, 30)]})
    rows = discipline.proposals(war)
    assert rows == [{"tag": "#P3", "name": "Peach", "missed": 2},
                    {"tag": "#P2", "name": "Luigi", "missed": 1}]
    assert discipline.proposals(snap("warEnded", our_attacks={
        "#P1": [("#E1", 3, 100), ("#E2", 2, 60)],
        "#P2": [("#E3", 1, 30), ("#E1", 1, 30)],
        "#P3": [("#E2", 1, 30), ("#E3", 1, 30)]})) == []


def test_the_ledger_keeps_only_who_is_still_in_the_clan_and_stops_at_the_cap():
    ledger = [{"tag": "#P9", "name": "Wario", "missed": 1}]
    ledger = discipline.register(ledger, {"tag": "#P2", "name": "Luigi", "missed": 2},
                                 members={"#P1", "#P2"})
    assert [row["tag"] for row in ledger] == ["#P2"]
    assert discipline.counts(ledger) == {"#P2": 1}
    assert len(discipline.register(ledger * 120, {"tag": "#P1", "name": "Mario", "missed": 1})) == 100


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [(row["kind"], row["text"]) for row in saved.get("rows") or []]


def test_the_proposal_reaches_only_the_managers_with_short_callback_data():
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    assert bot.sent == []
    payload = store.kv[f"warn:{code}"]
    assert [row["tag"] for row in payload["rows"]] == ["#P3", "#P2"]
    assert [kind for kind, _ in feed_rows(store, 7)] == [discipline.EVENT]
    assert feed_rows(store, 9) == []
    for row in discipline.keyboard(L, code, payload["rows"], {}).inline_keyboard:
        for button in row:
            assert len(button.callback_data.encode()) <= 64


def test_the_proposal_speaks_the_language_of_every_manager():
    store, bot, poller, t, war = proposal_setup(links=[leader_link("#P1", 7, "Mario", lang="en")])
    propose_and_flush(poller, t, war)
    text = feed_rows(store, 7)[0][1]
    assert L.t("warn.title") not in text and "MISSED ATTACKS" in text


def test_no_proposal_where_the_clan_turned_the_warnings_off():
    stored = settings_mod.migrate({"lang": "it", "tz": TZ})
    stored["routes"]["war.warning"] = {"to": "off", "intensity": None}
    store, bot, poller, t, war = proposal_setup(stored=stored)
    propose_and_flush(poller, t, war)
    assert bot.sent == [] and store.kv == {}


def test_a_leader_who_blocked_the_bot_reads_the_proposal_all_the_same():
    store, bot, poller, t, war = proposal_setup()
    bot.send_message = forbidden_send
    code = propose_and_flush(poller, t, war)
    assert f"warn:{code}" in store.kv
    assert [kind for kind, _ in feed_rows(store, 7)] == [discipline.EVENT]
    assert [link.dm for link in store.links] == [True, True]


def test_the_night_does_not_queue_the_proposal_it_goes_to_the_feed():
    store, bot, poller, t, war = proposal_setup()
    t.quiet = True
    code = propose_and_flush(poller, t, war)
    assert bot.sent == []
    assert (CLAN.alias, "queue_dm") not in store.state
    assert store.kv[f"warn:{code}"]["messages"] == []
    assert [kind for kind, _ in feed_rows(store, 7)] == [discipline.EVENT]


def test_the_warning_stays_private_and_only_the_leaders_can_route_it():
    assert EVENTS["war.warning"]["default"] == "leaders_dm"
    assert set(EVENTS["war.warning"]["allowed"]) == {"leaders_dm", "off"}
    assert EVENTS["war.warning"]["pack"] == "wars"


def test_a_confirmed_warning_is_written_down_and_told_in_the_feed_only_once():
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    store.links.append(leader_link("#P2", 5, "Luigi"))
    context = context_with(store, bot)
    update = fake_update(FakeQuery(f"w:{code}:1:1"))
    asyncio.run(discipline.on_warning_callback(update, context))
    ledger = store.state[(CLAN.alias, discipline.STATE)]
    assert [row["tag"] for row in ledger] == ["#P2"]
    assert ledger[0]["by"] == "#P1" and "user_id" not in ledger[0]
    assert len(feed_rows(store, 5)) == 1 and bot.sent == []
    asyncio.run(discipline.on_warning_callback(update, context))
    assert len(store.state[(CLAN.alias, discipline.STATE)]) == 1
    assert len(feed_rows(store, 5)) == 1


def test_l_ammonizione_confermata_ha_un_codice_suo_e_finisce_nel_registro():
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    store.links.append(leader_link("#P2", 5, "Luigi"))
    context = context_with(store, bot)
    asyncio.run(discipline.on_warning_callback(fake_update(FakeQuery(f"w:{code}:1:1")), context))
    entry = store.state[(CLAN.alias, discipline.STATE)][0]
    assert entry["id"] and isinstance(entry["id"], str)
    riga = asyncio.run(store.recent_log(CLAN.alias))[0]
    assert {key: value for key, value in riga.items() if key != "at"} == {
        "kind": "warning", "ref": entry["id"], "by": 7, "by_name": "Mario"}


def test_l_ammonito_legge_chi_lo_ha_ammonito():
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    store.links.append(leader_link("#P2", 5, "Luigi"))
    asyncio.run(discipline.on_warning_callback(fake_update(FakeQuery(f"w:{code}:1:1")),
                                               context_with(store, bot)))
    avviso = feed_rows(store, 5)[0][1]
    assert "Luigi" in avviso and "Mario" in avviso


def test_letting_it_go_writes_nothing_and_says_nothing_to_the_member():
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    store.links.append(leader_link("#P2", 5, "Luigi"))
    context = context_with(store, bot)
    asyncio.run(discipline.on_warning_callback(update=fake_update(FakeQuery(f"w:{code}:1:0")),
                                               context=context))
    assert (CLAN.alias, discipline.STATE) not in store.state
    assert feed_rows(store, 5) == [] and bot.sent == []


def test_a_member_who_blocked_the_bot_reads_the_notice_in_the_feed():
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    store.links.append(leader_link("#P2", 5, "Luigi"))
    context = context_with(store, bot)
    bot.send_message = forbidden_send
    asyncio.run(discipline.on_warning_callback(fake_update(FakeQuery(f"w:{code}:1:1")), context))
    assert [link.dm for link in store.links if link.tag == "#P2"] == [True]
    assert len(feed_rows(store, 5)) == 1
    assert [row["tag"] for row in store.state[(CLAN.alias, discipline.STATE)]] == ["#P2"]


def test_a_touch_on_a_forgotten_proposal_answers_without_an_error():
    store, bot = FakeStore(), FakeBot()
    context = context_with(store, bot)
    query = FakeQuery("w:sparita:0:1")
    asyncio.run(discipline.on_warning_callback(fake_update(query), context))
    assert query.answers == [(None, False)]
    assert bot.sent == []


def test_the_command_shows_the_registry_to_who_can_manage():
    store, bot = FakeStore(), FakeBot()
    store.links = [leader_link("#P1", 7, "Mario")]
    store.state[(CLAN.alias, "members")] = dict(MEMBERS)
    store.state[(CLAN.alias, discipline.STATE)] = [
        {"tag": "#P2", "name": "Luigi", "missed": 2, "at": 1757700000}
    ]
    update = group_update()
    asyncio.run(discipline.cmd_warnings(update, context_with(store, bot)))
    assert "Luigi" in update.effective_message.sent[-1][0]


def test_the_cards_stay_inside_the_telegram_limit():
    rows = [{"tag": "#P2", "name": "Luigi", "missed": 2}]
    assert len(render_live.warning_proposal_card(L, rows, {"#P2": 1})) <= render.MAX_LEN
    assert "Luigi" in render_live.warning_notice_card(L, rows[0])
    assert len(render_live.warnings_view(L, [dict(rows[0], at=1757700000)], "Europe/Rome")) <= render.MAX_LEN
    assert L.t("warn.list_empty") in render_live.warnings_view(L, [], "Europe/Rome")
    full = [dict(rows[0], name="Luigi Mario Peach", at=1757700000) for _ in range(100)]
    assert len(render_live.warnings_view(L, full, "Europe/Rome")) <= render.MAX_LEN


def test_the_command_is_published_with_its_italian_name():
    from clashbot import handlers
    assert ("warnings", ["ammonizioni"]) in handlers.COMMANDS
    assert handlers.HANDLERS["warnings"] is discipline.cmd_warnings


def test_l_avviso_di_ammonizione_passa_dal_feed(monkeypatch):
    testo = pathlib.Path(discipline.__file__).read_text(encoding="utf-8")
    assert "send_message" not in testo and "delivery" not in testo
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    store.links.append(leader_link("#P2", 5, "Luigi"))
    visti = []

    async def finta(store_, alias, uid, kind, text, now):
        visti.append((uid, text))

    monkeypatch.setattr(feed, "add", finta)
    asyncio.run(discipline.on_warning_callback(fake_update(FakeQuery(f"w:{code}:1:1")),
                                               context_with(store, bot)))
    assert [uid for uid, _ in visti] == [5]
    assert "Luigi" in visti[0][1]
    assert 5 not in [chat_id for chat_id, _text in bot.sent]


def test_il_gestore_sospeso_non_conferma_le_ammonizioni():
    store, bot, poller, t, war = proposal_setup()
    code = propose_and_flush(poller, t, war)
    store.links.append(leader_link("#P2", 5, "Luigi"))
    store.kv[guard.suspended_key(CLAN.alias, 7)] = {"at": 0}
    query = FakeQuery(f"w:{code}:1:1")
    asyncio.run(discipline.on_warning_callback(fake_update(query), context_with(store, bot)))
    assert query.answers == [(L.t("h.suspended"), True)]
    assert (CLAN.alias, discipline.STATE) not in store.state
    assert feed_rows(store, 5) == []
