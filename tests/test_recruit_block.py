import asyncio
import json
from datetime import timedelta

import test_intents_manager as mgr
import test_recruit_apply as porta
from clashbot import acts, i18n, reasons, recruit, recruit_block, recruit_tools, retention
from clashbot.web import miniapp

IT = i18n.locale("it")
NUOVE = ("recruit.btn_block", "recruit.block.title", "recruit.apply.blocked")


def candidatura(store):
    state, app = recruit.add(recruit.state_of(None), "#N1", {"name": "Nuovo", "th": 15},
                             mgr.STRANGER, True, ["war"], False, mgr.NOW)
    asyncio.run(store.set_state(mgr.CLAN.alias, recruit.KIND, state))
    return app


def bloccati(store):
    return recruit_block.rows(recruit_block.state_of(
        asyncio.run(store.get_state(mgr.CLAN.alias, recruit_block.KIND))))


def flusso_bloccato(store, user_id=9):
    state, _ = recruit_block.add(recruit_block.state_of(None), user_id, "Toad", porta.NOW)
    asyncio.run(store.set_state(porta.CLAN.alias, recruit_block.KIND, state))


def test_il_clan_blocca_un_mittente_e_la_candidatura_si_chiude(tmp_path):
    store = mgr.manager_store(tmp_path)
    app = candidatura(store)
    assert mgr.applied(store, "sender.block", {"ref": app["id"]}) is True
    assert [(row["who"], row["name"]) for row in bloccati(store)] == [(mgr.STRANGER, "Nuovo")]
    decise = recruit.state_of(asyncio.run(store.get_state(mgr.CLAN.alias, recruit.KIND)))
    assert recruit.find(decise, app["id"])["state"] == "rejected"
    assert [entry["action"] for _, entry in store.logs] == ["apply"]
    assert mgr.applied(store, "sender.block", {"ref": app["id"]}, ident="b2") == reasons.REFUSED
    assert len(bloccati(store)) == 1


def test_solo_chi_gestisce_blocca_un_mittente(tmp_path):
    store = mgr.manager_store(tmp_path)
    app = candidatura(store)
    assert mgr.applied(store, "sender.block", {"ref": app["id"]}, uid=mgr.ELDER,
                       ident="e1") == reasons.NOT_MANAGER
    assert bloccati(store) == []
    assert mgr.applied(store, "sender.block", {"ref": "77"}, ident="b3") == reasons.REFUSED


def test_il_gestore_toglie_il_blocco_dall_app(tmp_path):
    store = mgr.manager_store(tmp_path)
    app = candidatura(store)
    assert mgr.applied(store, "sender.block", {"ref": app["id"]}) is True
    ref = bloccati(store)[0]["id"]
    assert mgr.applied(store, "sender.unblock", {"ref": ref}, ident="u1") is True
    assert bloccati(store) == []
    assert mgr.applied(store, "sender.unblock", {"ref": ref}, ident="u2") == reasons.REFUSED


def test_la_lista_dei_bloccati_arriva_nella_pagina_dei_gestori(tmp_path):
    store = mgr.manager_store(tmp_path)
    app = candidatura(store)
    assert mgr.applied(store, "sender.block", {"ref": app["id"]}) is True
    found = mgr.tools_of(store, "recruitment")
    assert [row["name"] for row in found["blocked"]] == ["Nuovo"]
    assert all(set(row) == {"id", "name"} for row in found["blocked"])
    assert str(mgr.STRANGER) not in json.dumps(found["blocked"])


def test_un_mittente_bloccato_non_apre_e_non_manda_un_altra_candidatura():
    store = porta.FakeStore(links=[porta.link()])
    flusso_bloccato(store)
    context = porta.context_for(store)
    update = porta.private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context))
    assert update.effective_message.sent[-1][0] == IT.t("recruit.apply.blocked")
    assert "flow" not in context.user_data
    assert (porta.CLAN.alias, recruit.KIND) not in store.state


def test_il_blocco_arrivato_a_meta_strada_ferma_l_invio():
    store = porta.FakeStore(links=[porta.link()])
    context = porta.context_for(store)
    asyncio.run(recruit_tools.cmd_apply(porta.private_update(), context))
    asyncio.run(recruit_tools.on_apply_callback(
        porta.private_update(query=porta.FakeQuery("rc:acc:0")), context))
    assert context.user_data["flow"]["step"] == "goals"
    flusso_bloccato(store)
    update = porta.private_update(query=porta.FakeQuery("rc:send"))
    asyncio.run(recruit_tools.on_apply_callback(update, context))
    assert update.effective_message.sent[-1][0] == IT.t("recruit.apply.blocked")
    assert "flow" not in context.user_data
    assert (porta.CLAN.alias, recruit.KIND) not in store.state


def test_i_mittenti_bloccati_stanno_nel_tetto_gia_deciso():
    assert recruit_block.KEEP == retention.WAR_HISTORY_KEEP
    state = recruit_block.state_of(None)
    for passo in range(recruit_block.KEEP + 1):
        state, row = recruit_block.add(state, 1000 + passo, f"Tale {passo}",
                                       mgr.NOW + timedelta(seconds=passo))
        assert row
    kept = recruit_block.rows(state)
    assert len(kept) == recruit_block.KEEP
    assert kept[0]["who"] == 1001 and kept[-1]["who"] == 1000 + recruit_block.KEEP
    assert recruit_block.blocked(state, 1000) is False


def test_lo_stato_storto_non_blocca_nessuno():
    assert recruit_block.rows(recruit_block.state_of("niente")) == []
    assert recruit_block.rows(recruit_block.state_of({"rows": {"1": {"who": 0}}})) == []
    assert recruit_block.blocked(recruit_block.state_of(None), None) is False
    state, row = recruit_block.add(recruit_block.state_of(None), 0, "Nessuno", mgr.NOW)
    assert row is None and recruit_block.rows(state) == []


def test_le_chiavi_nuove_esistono_in_inglese():
    english = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
    for key in NUOVE:
        assert key in english, key
    assert miniapp.MANAGE_WORDS["app_block"] == "recruit.btn_block"
    assert miniapp.MANAGE_WORDS["block_title"] == "recruit.block.title"
    for code in ("it", "en"):
        L = i18n.locale(code)
        assert all(not L.t(key).startswith("[") for key in NUOVE), code


def test_l_app_dei_gestori_manda_i_due_gesti_del_blocco():
    assert {"sender.block", "sender.unblock"} <= set(acts.KINDS_MANAGER)
    words = miniapp.words(IT)
    assert words["manage_app_block"] and not words["manage_app_block"].startswith("[")
    assert words["manage_block_title"] and not words["manage_block_title"].startswith("[")
