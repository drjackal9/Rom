import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import handlers, i18n, recruit, recruit_cards, recruit_jobs, recruit_tools

from test_recruit_apply import (CLAN, EN, SNAP, FakeBot, FakeQuery, FakeStore, context_for, link,
                                private_update)

IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)


def linked(tag, user_id):
    row = link(tag=tag, user_id=user_id)
    row.lang = "it"
    return row


def fake_store():
    store = FakeStore(links=[linked("#P1", 5)],
                      members={"#P1": {"name": "Mario", "role": "leader"}})
    store.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
    return store


def store_with_application(below=False, user_id=9):
    store = fake_store()
    state, app = recruit.add(recruit.state_of(None), "#P9", SNAP, user_id, True, ["war"], below, NOW)
    store.state[(CLAN.alias, recruit.KIND)] = state
    return store, app


def leader_update(query=None):
    return private_update(user_id=5, query=query)


class FakePoller:
    def __init__(self, store, bot=None):
        self.store = store
        self.bot = bot or FakeBot()
        self.dispatched = []

    def bot_for(self, clan):
        return self.bot

    async def dispatch(self, t, event, render_text, member_tag=None):
        self.dispatched.append((event, render_text(t.L), member_tag))


def tick_for(store, settings=None, members=None):
    from clashbot import settings as settings_mod
    conf = settings_mod.effective(settings or {"lang": "it", "tz": "Europe/Rome"})
    t = SimpleNamespace(clan=CLAN, now=NOW, chunks=[], dm=[], settings=conf,
                        members=members if members is not None else {"#P1": {"name": "Mario"}})
    t.L = i18n.locale(conf["lang"])
    t.tz = conf["tz"]
    return t


def test_accettare_risponde_al_candidato_e_registra_l_azione():
    store, app = store_with_application()
    context = context_for(store)
    query = FakeQuery(f"ap:y:{app['id']}")
    asyncio.run(recruit_tools.on_decision_callback(leader_update(query), context))
    state = recruit.state_of(store.state[(CLAN.alias, recruit.KIND)])
    assert recruit.find(state, app["id"])["state"] == "accepted"
    assert recruit.find(state, app["id"])["by"] == 5
    chat_id, text, _ = context.bot.sent[-1]
    assert chat_id == 9 and "Futuro" in text and "OpenClanProfile" in text
    assert query.edits and IT.t("recruit.decided.accepted") in query.edits[-1][0]


def test_rifiutare_e_cortese_e_non_dice_chi_ha_deciso():
    store, app = store_with_application()
    context = context_for(store)
    asyncio.run(recruit_tools.on_decision_callback(leader_update(FakeQuery(f"ap:n:{app['id']}")),
                                                   context))
    text = context.bot.sent[-1][1]
    assert "Mario" not in text and "OpenClanProfile" not in text
    assert IT.t("recruit.answer.rejected", clan="Futuro") in text


def test_un_membro_semplice_non_decide():
    store, app = store_with_application()
    store.links = [linked("#P9", 9)]
    store.state[(CLAN.alias, "members")] = {"#P9": {"name": "Toad", "role": "member"}}
    context = context_for(store)
    query = FakeQuery(f"ap:y:{app['id']}")
    asyncio.run(recruit_tools.on_decision_callback(private_update(user_id=9, query=query), context))
    assert recruit.find(recruit.state_of(store.state[(CLAN.alias, recruit.KIND)]),
                        app["id"])["state"] == "pending"
    assert query.answers[-1][1] is True


def test_la_stessa_candidatura_non_si_decide_due_volte():
    store, app = store_with_application()
    context = context_for(store)
    asyncio.run(recruit_tools.on_decision_callback(leader_update(FakeQuery(f"ap:y:{app['id']}")),
                                                   context))
    sent = len(context.bot.sent)
    query = FakeQuery(f"ap:n:{app['id']}")
    asyncio.run(recruit_tools.on_decision_callback(leader_update(query), context))
    assert len(context.bot.sent) == sent
    assert IT.t("recruit.gone") in (query.answers[-1][0] or "")


def test_il_bottone_apre_la_scheda_del_candidato():
    store, app = store_with_application()
    query = FakeQuery(f"ap:o:{app['id']}")
    asyncio.run(recruit_tools.on_decision_callback(leader_update(query), context_for(store)))
    text, keyboard = query.edits[-1]
    assert "Toad" in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [
        f"ap:y:{app['id']}", f"ap:n:{app['id']}"]


def test_l_elenco_mostra_chi_aspetta_con_i_bottoni():
    store, app = store_with_application(below=True)
    update = leader_update()
    asyncio.run(recruit_tools.cmd_applications(update, context_for(store)))
    text, keyboard = update.effective_message.sent[-1]
    assert "Toad" in text
    assert [b.callback_data for row in keyboard.inline_keyboard for b in row] == [f"ap:o:{app['id']}"]


def test_l_elenco_vuoto_non_porta_bottoni():
    store = fake_store()
    update = leader_update()
    asyncio.run(recruit_tools.cmd_applications(update, context_for(store)))
    text, keyboard = update.effective_message.sent[-1]
    assert IT.t("recruit.list.empty") in text and keyboard is None


def test_un_membro_semplice_non_vede_l_elenco():
    store, _ = store_with_application()
    store.links = [linked("#P9", 9)]
    store.state[(CLAN.alias, "members")] = {"#P9": {"name": "Toad", "role": "member"}}
    update = private_update(user_id=9)
    asyncio.run(recruit_tools.cmd_applications(update, context_for(store)))
    assert update.effective_message.sent[-1][0] == IT.t("recruit.only_leaders")


def test_chi_entra_in_clan_chiude_la_candidatura_e_lascia_la_provenienza():
    store, app = store_with_application()
    poller = FakePoller(store)
    t = tick_for(store, members={"#P1": {"name": "Mario"}, "#P9": {"name": "Toad"}})
    asyncio.run(recruit_jobs.run(poller, t))
    state = recruit.state_of(store.state[(CLAN.alias, recruit.KIND)])
    assert recruit.find(state, app["id"])["state"] == "joined"
    assert store.state[(CLAN.alias, "players")]["joined"]["#P9"]["via"] == "apply"


def test_il_promemoria_parte_una_volta_al_giorno_e_solo_dopo_un_giorno_di_attesa():
    store, app = store_with_application()
    state = recruit.state_of(store.state[(CLAN.alias, recruit.KIND)])
    state["items"][app["id"]]["ts"] = (NOW - timedelta(hours=30)).timestamp()
    store.state[(CLAN.alias, recruit.KIND)] = state
    poller = FakePoller(store)
    asyncio.run(recruit_jobs.run(poller, tick_for(store)))
    assert [event for event, _, _ in poller.dispatched] == ["recruit.reminder"]
    assert "Toad" in poller.dispatched[0][1]
    poller.dispatched.clear()
    asyncio.run(recruit_jobs.run(poller, tick_for(store)))
    assert poller.dispatched == []


def test_niente_promemoria_per_chi_ha_appena_scritto():
    store, _ = store_with_application()
    poller = FakePoller(store)
    asyncio.run(recruit_jobs.run(poller, tick_for(store)))
    assert poller.dispatched == []


def test_il_giro_non_riscrive_le_candidature_se_non_cambia_niente():
    store, _ = store_with_application()
    written = []
    saved = store.set_state

    async def counted(alias, kind, obj):
        written.append(kind)
        await saved(alias, kind, obj)

    store.set_state = counted
    asyncio.run(recruit_jobs.run(FakePoller(store), tick_for(store)))
    assert written == []


def test_un_clan_senza_candidature_non_scrive_niente():
    store = fake_store()
    poller = FakePoller(store)
    asyncio.run(recruit_jobs.run(poller, tick_for(store)))
    assert (CLAN.alias, recruit.KIND) not in store.state
    assert poller.dispatched == []


def test_la_riga_del_report_conta_solo_chi_aspetta():
    store, _ = store_with_application(below=True)
    state = recruit.state_of(store.state[(CLAN.alias, recruit.KIND)])
    assert IT.t("recruit.report.line", n=1, below=1) in recruit_jobs.report_line(IT, state)
    assert recruit_jobs.report_line(IT, recruit.state_of(None)) == ""


def test_il_comando_delle_candidature_e_agganciato():
    assert ("applications", ["candidature"]) in handlers.COMMANDS
    assert handlers.HANDLERS["applications"] is recruit_tools.cmd_applications


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("recruit.list.title", "recruit.list.empty", "recruit.list.row", "recruit.gone",
                "recruit.decided.accepted", "recruit.decided.rejected", "recruit.answer.accepted",
                "recruit.answer.rejected", "recruit.answer.link", "recruit.stale.title",
                "recruit.stale.row", "recruit.report.line", "recruit.only_leaders"):
        assert key in EN, key


def test_le_schede_restano_dentro_il_limite_di_telegram():
    rows = [{"id": str(n), "tag": "#P9", "verified": False, "below": True, "snap": SNAP,
             "state": "pending", "ts": NOW.timestamp()} for n in range(recruit.KEEP)]
    assert len(recruit_cards.applications_card(IT, rows)) <= 4096
    assert len(recruit_cards.stale_card(IT, rows)) <= 4096


def test_un_clan_senza_capo_collegato_non_riceve_candidature():
    store = FakeStore(members={"#P1": {"name": "Mario", "role": "coLeader"}},
                      links=[link()])
    update = private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context_for(store)))
    assert update.effective_message.sent[-1][0] == IT.t("recruit.unverified")
    assert (CLAN.alias, recruit.KIND) not in store.state


def test_col_capo_del_gioco_collegato_la_candidatura_parte():
    store = fake_store()
    update = private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context_for(store)))
    assert IT.t("recruit.unverified") not in [text for text, _ in update.effective_message.sent]
