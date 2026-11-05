import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clashbot import console, i18n, incidents, otp, platform, reports, site_days
from clashbot.crypto import Vault
from clashbot.db import INCIDENT_AAD, INCIDENT_KINDS, Store
from clashbot.leaders import NOTE_MAX
from test_console import (ConsoleApp, DELEGATE_ID, OWNER, con_codice, datas, delegate_store,
                          panel_store, pressed)

IT = i18n.locale("it")
NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
NOTE = "il tunnel e caduto"


def run(coro):
    return asyncio.run(coro)


def row(number=1, kind="outage", opened=None, closed=None, note=NOTE):
    return {"id": number, "kind": kind, "opened": opened or NOW - timedelta(hours=3),
            "closed": closed, "note": note}


class Pool:
    def __init__(self, rows=(), status="UPDATE 1", value=7):
        self.rows = list(rows)
        self.status = status
        self.value = value
        self.log = []

    async def execute(self, sql, *args):
        self.log.append((" ".join(sql.split()), args))
        return self.status

    async def fetchval(self, sql, *args):
        self.log.append((" ".join(sql.split()), args))
        return self.value

    async def fetch(self, sql, *args):
        self.log.append((" ".join(sql.split()), args))
        return list(self.rows)


def store_with(tmp_path, **kw):
    store = Store(Vault(tmp_path))
    store.pool = Pool(**kw)
    return store


def test_un_incidente_si_scrive_cifrato_e_senza_la_nota_in_chiaro(tmp_path):
    store = store_with(tmp_path)
    assert run(store.incident_add("outage", NOTE, NOW)) == 7
    sql, args = store.pool.log[0]
    assert sql.startswith("insert into incidents(opened, kind, key_id, data)")
    assert "returning id" in sql
    assert args[0] == NOW and args[1] == "outage"
    assert NOTE not in str(args)
    assert Vault(tmp_path).decrypt_json(args[3], INCIDENT_AAD)["note"] == NOTE


def test_un_incidente_si_chiude_una_volta_sola(tmp_path):
    store = store_with(tmp_path, status="UPDATE 1")
    assert run(store.incident_close(3, NOW)) is True
    sql, args = store.pool.log[0]
    assert sql == ("update incidents set closed=$2 where id=$1 and closed is null")
    assert args == (3, NOW)
    assert run(store_with(tmp_path, status="UPDATE 0").incident_close(3, NOW)) is False


def test_gli_incidenti_si_rileggono_e_una_riga_rotta_non_ferma_le_altre(tmp_path, caplog):
    vault = Vault(tmp_path)
    good = vault.encrypt_json({"kind": "bug", "note": NOTE}, INCIDENT_AAD)
    bad = bytes(good)[:-1] + bytes([bytes(good)[-1] ^ 0xFF])
    rows = [{"id": 2, "opened": NOW, "closed": None, "kind": "bug", "data": bad},
            {"id": 1, "opened": NOW, "closed": NOW, "kind": "bug", "data": good}]
    store = store_with(tmp_path, rows=rows)
    with caplog.at_level("WARNING", logger="clashbot.db"):
        found = run(store.incidents(20))
    assert [one["id"] for one in found] == [1]
    assert found[0]["note"] == NOTE
    assert "order by opened desc limit $1" in store.pool.log[0][0]


def test_la_tessera_dice_aperto_o_chiuso_con_la_durata():
    text, keyboard = incidents.page(IT, [row(), row(2, "bug", closed=NOW)], NOW)
    assert IT.t("panel.incidents.open", kind=IT.t("panel.incidents.kind_outage"),
                when=IT.ago(NOW - timedelta(hours=3), NOW)) in text
    assert IT.t("panel.incidents.closed", kind=IT.t("panel.incidents.kind_bug"), n="3") in text
    assert "panel:incclose:1" in datas(keyboard)
    assert "panel:incclose:2" not in datas(keyboard)


def test_senza_incidenti_la_tessera_lo_dice():
    text, keyboard = incidents.page(IT, [], NOW)
    assert IT.t("panel.incidents.empty") in text
    assert datas(keyboard) == ["panel:incopen", "panel:ops"]


def test_il_delegato_vede_e_non_ha_bottoni_che_scrivono():
    text, keyboard = incidents.page(IT, [row()], NOW, full=False)
    assert IT.t("panel.incidents.open", kind=IT.t("panel.incidents.kind_outage"),
                when=IT.ago(NOW - timedelta(hours=3), NOW)) in text
    assert datas(keyboard) == ["panel:ops"]
    for name in ("incopen", "incpick", "incclose"):
        assert name not in platform.OPEN, name
    assert "incidents" in platform.OPEN


def test_le_azioni_che_scrivono_passano_dall_otp():
    for name in ("incopen", "incpick", "incclose"):
        assert name in otp.GUARDED, name
    assert "incidents" not in otp.GUARDED


def test_il_modulo_degli_incidenti_e_l_unica_autorita_delle_sue_azioni():
    assert set(incidents.ACTIONS) == set(incidents.OPEN) | set(incidents.WRITES)
    assert set(incidents.OPEN) <= set(platform.OPEN)
    assert set(incidents.WRITES) <= set(otp.GUARDED)
    for module, names in ((platform, incidents.OPEN), (otp, incidents.WRITES)):
        text = Path(module.__file__).read_text(encoding="utf-8")
        for name in names:
            assert f'"{name}"' not in text, (module.__name__, name)


def test_la_nota_dell_incidente_si_rivede_nel_pannello():
    text, _ = incidents.page(IT, [row(), row(2, "bug", closed=NOW, note="altra nota")], NOW)
    assert NOTE in text
    assert "altra nota" in text


def test_la_nota_non_porta_marcatori_dentro_la_tessera():
    text, _ = incidents.page(IT, [row(note="<b>rotto</b> & <script>")], NOW)
    assert "&lt;b&gt;rotto&lt;/b&gt; &amp; &lt;script&gt;" in text
    assert "<b>rotto" not in text and "<script>" not in text


def test_una_nota_vuota_non_lascia_righe_a_meta():
    text, _ = incidents.page(IT, [row(note=None)], NOW)
    assert IT.t("panel.incidents.open", kind=IT.t("panel.incidents.kind_outage"),
                when=IT.ago(NOW - timedelta(hours=3), NOW)) in text
    assert "None" not in text


def test_la_nota_si_taglia_al_limite_dei_testi():
    class Keeper:
        def __init__(self):
            self.seen = None

        async def incident_add(self, kind, note, now):
            self.seen = (kind, note, now)
            return 1

    keeper = Keeper()
    assert run(incidents.add(keeper, "abuse", "x" * (NOTE_MAX + 50), NOW)) == 1
    assert len(keeper.seen[1]) == NOTE_MAX
    assert run(incidents.add(keeper, "sconosciuto", NOTE, NOW)) is None
    assert run(incidents.add(keeper, "abuse", "   ", NOW)) is None
    assert incidents.KINDS == INCIDENT_KINDS == ("outage", "bug", "abuse", "other")


class PanelStore:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.added = []
        self.closed = []

    async def incidents(self, limit=20):
        return list(self.rows)

    async def incident_add(self, kind, note, now):
        self.added.append((kind, note))
        return len(self.added)

    async def incident_close(self, number, now):
        self.closed.append(number)
        return True


def panel_with(rows=(), lang="it"):
    store = panel_store(lang)
    keeper = PanelStore(rows)
    for name in ("incidents", "incident_add", "incident_close"):
        setattr(store, name, getattr(keeper, name))
    store.keeper = keeper
    return store


def test_dal_quadro_ops_si_arriva_agli_incidenti():
    app = ConsoleApp(store=panel_with([row()]))
    con_codice(app.store, OWNER)
    update, query = pressed("panel:ops", user_id=OWNER)
    run(console.on_panel_callback(update, app.context))
    assert "panel:incidents" in datas(query.edits[-1][1])
    update, query = pressed("panel:incidents", user_id=OWNER)
    run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.incidents.title") in query.edits[-1][0]


def test_il_gestore_apre_un_incidente_scegliendo_il_tipo_e_scrivendo_la_nota():
    app = ConsoleApp(store=panel_with())
    con_codice(app.store, OWNER)
    update, query = pressed("panel:incopen", user_id=OWNER)
    run(console.on_panel_callback(update, app.context))
    assert datas(query.edits[-1][1])[:1] == ["panel:incpick:outage"]
    update, query = pressed("panel:incpick:abuse", user_id=OWNER)
    run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.incidents.ask", n=NOTE_MAX,
                kind=IT.t("panel.incidents.kind_abuse")) in query.edits[-1][0]
    assert app.context.user_data[incidents.FLOW] == "abuse"
    written, ctx = app.update_from(user_id=OWNER, text=NOTE)
    run(console.on_newbot_text(written, ctx))
    assert app.store.keeper.added == [("abuse", NOTE)]
    assert incidents.FLOW not in ctx.user_data
    assert IT.t("panel.incidents.title") in written.effective_message.sent[-1][0]


def test_il_gestore_chiude_un_incidente_dal_pannello():
    app = ConsoleApp(store=panel_with([row()]))
    con_codice(app.store, OWNER)
    update, query = pressed("panel:incclose:1", user_id=OWNER)
    run(console.on_panel_callback(update, app.context))
    assert app.store.keeper.closed == [1]


def test_un_tipo_inventato_non_lascia_il_flusso_appeso():
    app = ConsoleApp(store=panel_with())
    con_codice(app.store, OWNER)
    update, query = pressed("panel:incpick:tipo-inventato", user_id=OWNER)
    run(console.on_panel_callback(update, app.context))
    assert incidents.FLOW not in app.context.user_data
    assert IT.t("panel.incidents.title") in query.edits[-1][0]
    written, ctx = app.update_from(user_id=OWNER, text=NOTE)
    run(console.on_newbot_text(written, ctx))
    assert app.store.keeper.added == []
    assert incidents.FLOW not in ctx.user_data


def test_senza_otp_il_gestore_non_apre_niente():
    app = ConsoleApp(store=panel_with())
    con_codice(app.store, OWNER, aperta=False)
    update, query = pressed("panel:incpick:bug", user_id=OWNER)
    run(console.on_panel_callback(update, app.context))
    assert IT.t("panel.incidents.ask", n=NOTE_MAX,
                kind=IT.t("panel.incidents.kind_bug")) not in query.edits[-1][0]
    assert incidents.FLOW not in app.context.user_data


def test_il_delegato_legge_e_non_scrive():
    store = delegate_store()
    keeper = PanelStore([row()])
    for name in ("incidents", "incident_add", "incident_close"):
        setattr(store, name, getattr(keeper, name))
    app = ConsoleApp(store=store)
    update, query = pressed("panel:incidents", user_id=DELEGATE_ID)
    run(console.on_panel_callback(update, app.context))
    assert datas(query.edits[-1][1]) == ["panel:ops"]
    update, query = pressed("panel:incopen", user_id=DELEGATE_ID)
    run(console.on_panel_callback(update, app.context))
    assert query.edits == []
    assert query.answers[-1] == (IT.t("console.not_owner"), True)
    assert keeper.added == [] and keeper.closed == []


def test_un_estraneo_non_apre_ne_chiude_niente():
    store = panel_with([row()])
    app = ConsoleApp(store=store)
    for data in ("panel:incidents", "panel:incopen", "panel:incpick:bug", "panel:incclose:1"):
        update, query = pressed(data, user_id=4242)
        run(console.on_panel_callback(update, app.context))
        assert query.edits == [], data
        assert query.answers[-1] == (IT.t("console.owner_only"), True), data
    assert store.keeper.added == [] and store.keeper.closed == []


def test_la_decisione_del_gestore_su_una_segnalazione_finisce_nel_registro():
    class LogStore:
        def __init__(self):
            self.kv = {}

        async def kv_get(self, key):
            return self.kv.get(key)

        async def kv_set(self, key, obj, ref=None, ttl=None):
            self.kv[key] = obj

    store = LogStore()
    at = time.time()
    assert run(reports.note_decision(store, "AB1", at)) is True
    rows = store.kv["platform:actions"]["history"]
    assert rows[-1]["what"] == site_days.REPORT_MARK and rows[-1]["code"] == "AB1"
    assert json.dumps(rows).find("uid") == -1


@pytest.mark.parametrize("code", sorted(i18n.LANGUAGES))
def test_le_chiavi_degli_incidenti_esistono_in_ogni_catalogo(code):
    L = i18n.locale(code)
    keys = ["panel.incidents.title", "panel.incidents.btn", "panel.incidents.empty",
            "panel.incidents.open", "panel.incidents.closed", "panel.incidents.pick",
            "panel.incidents.ask", "panel.incidents.btn_open", "panel.incidents.btn_close"]
    keys += [f"panel.incidents.kind_{kind}" for kind in INCIDENT_KINDS]
    for key in keys:
        assert L.t(key) != f"[{key}]", (code, key)
