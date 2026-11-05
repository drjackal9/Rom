import asyncio
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from clashbot import ops, site_days
from clashbot import __main__ as cli
from clashbot.crypto import Vault
from clashbot.db import SCHEMA, SITE_DAY_FIELDS, Store
from clashbot.site_days import TOKEN_KIND, ZONE_KIND
from clashbot.supervisor import Supervisor
from clashbot.util import day_of

TOKEN = "cf-token-finto"
ZONE = "zona-finta"
DAY = date(2026, 9, 27)
NOW = datetime(2026, 9, 28, 1, 30, tzinfo=timezone.utc)
ROME = "Europe/Rome"


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status_code = status

    def json(self):
        return self.body


class FakeClient:
    def __init__(self, traffic=None, events=None, status=200, errors=None, zones=None):
        self.traffic = traffic
        self.events = list(events or [])
        self.status = status
        self.errors = errors
        self.zones = zones
        self.calls = []

    def answer(self, zone):
        if self.errors is not None:
            return FakeResponse({"data": None, "errors": list(self.errors)}, self.status)
        seen = [zone] if self.zones is None else list(self.zones)
        return FakeResponse({"data": {"viewer": {"zones": seen}}}, self.status)

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "query": json["query"], "vars": json["variables"],
                           "headers": dict(headers or {})})
        if "httpRequests1dGroups" in json["query"]:
            return self.answer({"httpRequests1dGroups": self.traffic or []})
        rows = self.events.pop(0) if self.events else []
        return self.answer({"firewallEventsAdaptive": rows})


def wrapped(zone):
    return {"data": {"viewer": {"zones": [zone]}}}


def traffic_row(requests=1000, pages=400, uniques=120):
    return [{"sum": {"requests": requests, "pageViews": pages,
                     "countryMap": [{"clientCountryName": "IT", "requests": 700},
                                    {"clientCountryName": "US", "requests": 300}]},
             "uniq": {"uniques": uniques}}]


AUTO = object()


def event(action="block", source="firewallCustom", at="2026-09-27T10:00:00Z", ray=AUTO):
    row = {"action": action, "source": source, "datetime": at}
    if ray is AUTO:
        row["rayName"] = f"ray-{at}-{action}-{source}"
    elif ray is not None:
        row["rayName"] = ray
    return row


class PagingClient(FakeClient):
    def __init__(self, rows, traffic=None):
        super().__init__(traffic=traffic if traffic is not None else traffic_row())
        self.rows = sorted(rows, key=lambda one: str(one.get("datetime") or ""))

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "query": json["query"], "vars": json["variables"],
                           "headers": dict(headers or {})})
        if "httpRequests1dGroups" in json["query"]:
            return self.answer({"httpRequests1dGroups": self.traffic or []})
        ask = json["variables"]
        got = [one for one in self.rows
               if ask["from"] <= str(one.get("datetime") or "") < ask["to"]]
        return self.answer({"firewallEventsAdaptive": got[:int(ask["limit"])]})


def hour_of(n):
    return f"2026-09-27T00:00:{n:02d}Z"


CLOUDFLARE = {TOKEN_KIND: TOKEN, ZONE_KIND: ZONE}


def quiet():
    return FakeClient(traffic=traffic_row(), events=[])


class FakeStore:
    def __init__(self, kv=None, secrets=None):
        self.kv = dict(kv or {})
        self.secrets = dict(secrets or {})
        self.put = []

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def site_day_put(self, day, body):
        self.put.append((day, dict(body)))

    async def site_days(self, limit=30):
        return []


def run(coro):
    return asyncio.run(coro)


def test_pull_legge_traffico_e_blocchi_e_tiene_il_gettone_solo_nell_intestazione():
    client = FakeClient(traffic=traffic_row(),
                        events=[[event(), event(source="firewallManaged"),
                                 event(source="botFight"), event(action="allow")]])
    found = run(site_days.pull(client, TOKEN, ZONE, DAY))
    assert found["requests"] == 1000 and found["pages"] == 400 and found["visitors"] == 120
    assert found["blocked_rule"] == 1 and found["blocked_waf"] == 1 and found["blocked_bot"] == 1
    assert found["blocked_total"] == 3
    assert found["countries"] == {"IT": 700, "US": 300}
    for call in client.calls:
        assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in call["query"] and TOKEN not in json.dumps(call["vars"])


def test_pull_senza_gettone_o_senza_zona_non_chiama_nessuno():
    client = FakeClient(traffic=traffic_row())
    assert run(site_days.pull(client, "", ZONE, DAY)) is None
    assert run(site_days.pull(client, TOKEN, "", DAY)) is None
    assert run(site_days.pull(None, TOKEN, ZONE, DAY)) is None
    assert client.calls == []


def test_pull_divide_il_giorno_in_ore_e_non_supera_il_limite_dichiarato():
    client = FakeClient(traffic=traffic_row(), events=[[event()] for _ in range(site_days.HOURS)])
    run(site_days.pull(client, TOKEN, ZONE, DAY))
    windows = [call["vars"] for call in client.calls if "firewallEventsAdaptive" in call["query"]]
    assert len(windows) == site_days.HOURS
    assert windows[0]["from"] == "2026-09-27T00:00:00Z"
    assert windows[0]["to"] == "2026-09-27T01:00:00Z"
    assert windows[-1]["to"] == "2026-09-28T00:00:00Z"
    assert all(row["limit"] == site_days.PAGE for row in windows)


def test_pull_con_gettone_revocato_non_spaccia_zero_per_una_misura():
    client = FakeClient(traffic=traffic_row(), errors=[{"message": "Authentication error"}])
    with pytest.raises(site_days.Refused):
        run(site_days.pull(client, TOKEN, ZONE, DAY))


def test_pull_rifiuta_una_risposta_che_non_e_duecento():
    client = FakeClient(traffic=traffic_row(), status=403)
    with pytest.raises(site_days.Refused):
        run(site_days.pull(client, TOKEN, ZONE, DAY))


def test_pull_rifiuta_se_la_zona_non_si_vede_piu():
    client = FakeClient(traffic=traffic_row(), zones=[])
    with pytest.raises(site_days.Refused):
        run(site_days.pull(client, TOKEN, ZONE, DAY))


def test_close_day_non_chiude_il_giorno_se_cloudflare_rifiuta():
    store = FakeStore(secrets={site_days.TOKEN_KIND: TOKEN, site_days.ZONE_KIND: ZONE},
                      kv={site_days.WEB_DAY + str(DAY): {"own_requests": 90}})
    client = FakeClient(traffic=traffic_row(), errors=[{"message": "Invalid API Token"}])
    assert run(site_days.close_day(store, NOW, ROME, client)) is None
    assert store.put == []
    assert site_days.CLOSED_KEY not in store.kv
    buono = FakeClient(traffic=traffic_row(), events=[[event()]])
    row = run(site_days.close_day(store, NOW, ROME, buono))
    assert row["requests"] == 1000 and row["own_requests"] == 90


def test_i_blocchi_continuano_dentro_l_ora_quando_la_pagina_e_piena():
    pieno = [[event(ray="a", at="2026-09-27T00:00:01Z"),
              event(ray="b", at="2026-09-27T00:00:02Z")],
             [event(ray="b", at="2026-09-27T00:00:02Z"),
              event(ray="c", at="2026-09-27T00:00:03Z")],
             [event(ray="d", at="2026-09-27T00:00:04Z")]]
    client = FakeClient(traffic=traffic_row(), events=pieno)
    found = run(site_days.pull(client, TOKEN, ZONE, DAY, 2))
    assert found["blocked_total"] == 4 and found["blocked_rule"] == 4
    windows = [call["vars"] for call in client.calls if "firewallEventsAdaptive" in call["query"]]
    assert windows[0]["from"] == "2026-09-27T00:00:00Z"
    assert windows[1]["from"] == "2026-09-27T00:00:02Z"
    assert windows[2]["from"] == "2026-09-27T00:00:03Z"
    assert windows[3]["from"] == "2026-09-27T01:00:00Z"


def test_una_finestra_che_non_avanza_si_ferma_invece_di_sottostimare():
    fermo = [event(ray="a", at="2026-09-27T00:00:01Z"),
             event(ray="b", at="2026-09-27T00:00:01Z")]
    client = FakeClient(traffic=traffic_row(), events=[list(fermo), list(fermo)])
    with pytest.raises(site_days.Refused):
        run(site_days.pull(client, TOKEN, ZONE, DAY, 2))


def test_la_domanda_dei_blocchi_chiede_istante_e_ordine():
    assert "datetime" in site_days.FIREWALL and "rayName" in site_days.FIREWALL
    assert "datetime_ASC" in site_days.FIREWALL


def test_i_blocchi_senza_ray_non_si_contano_due_volte_sul_confine_della_pagina():
    dodici = [event(at=hour_of(n), ray="") for n in range(1, 13)]
    client = PagingClient(dodici)
    found = run(site_days.pull(client, TOKEN, ZONE, DAY, 5))
    assert found["blocked_total"] == 12 and found["blocked_rule"] == 12


def test_i_blocchi_senza_il_campo_ray_non_si_contano_due_volte():
    dodici = [event(at=hour_of(n), ray=None) for n in range(1, 13)]
    assert all("rayName" not in row for row in dodici)
    found = run(site_days.pull(PagingClient(dodici), TOKEN, ZONE, DAY, 5))
    assert found["blocked_total"] == 12


def test_due_blocchi_gemelli_senza_ray_nello_stesso_istante_si_contano_tutti_e_due():
    gemelli = [event(at=hour_of(1), ray=""), event(at=hour_of(1), ray="")]
    found = run(site_days.pull(PagingClient(gemelli), TOKEN, ZONE, DAY, 5))
    assert found["blocked_total"] == 2


def test_close_day_somma_i_contatori_del_web_e_chiude_il_giorno_una_volta_sola():
    store = FakeStore(secrets=CLOUDFLARE,
                      kv={site_days.WEB_DAY + str(DAY): {"own_requests": 90, "limited": 4,
                                                         "probes": 6, "banned_h": 2,
                                                         "banned_d": 1, "banned_forever": 0}})
    row = run(site_days.close_day(store, NOW, ROME, quiet()))
    assert row["own_requests"] == 90 and row["limited"] == 4 and row["probes"] == 6
    assert row["banned_h"] == 2 and row["banned_d"] == 1 and row["banned_forever"] == 0
    assert store.put[0][0] == DAY
    assert store.kv[site_days.CLOSED_KEY] == {"day": str(DAY)}
    assert run(site_days.close_day(store, NOW, ROME, quiet())) is None
    assert len(store.put) == 1


def test_il_giorno_porta_anche_i_404_sconosciuti():
    assert "misses" in site_days.WEB_FIELDS and "misses" in SITE_DAY_FIELDS
    store = FakeStore(secrets=CLOUDFLARE,
                      kv={site_days.WEB_DAY + str(DAY): {"misses": 7, "own_requests": 9}})
    row = run(site_days.close_day(store, NOW, ROME, quiet()))
    assert row["misses"] == 7 and store.put[0][1]["misses"] == 7


def test_close_day_non_pubblica_un_giorno_senza_la_misura_di_cloudflare():
    store = FakeStore()
    assert run(site_days.close_day(store, NOW, ROME, quiet())) is None
    assert store.put == [] and site_days.CLOSED_KEY not in store.kv
    store.secrets.update(CLOUDFLARE)
    row = run(site_days.close_day(store, NOW, ROME, quiet()))
    assert row["requests"] == 1000 and store.put[0][0] == DAY


def test_close_day_col_gettone_mette_nella_riga_i_numeri_di_cloudflare():
    store = FakeStore(secrets=CLOUDFLARE)
    client = FakeClient(traffic=traffic_row(), events=[[event()]])
    row = run(site_days.close_day(store, NOW, ROME, client))
    assert row["requests"] == 1000 and row["blocked_rule"] == 1
    assert row["countries"] == {"IT": 700, "US": 300}
    assert set(SITE_DAY_FIELDS) <= set(row)


def test_close_day_chiude_il_giorno_finito_nel_fuso_del_gestore():
    store = FakeStore(secrets=CLOUDFLARE)
    mezzanotte = datetime(2026, 9, 28, 22, 10, tzinfo=timezone.utc)
    run(site_days.close_day(store, mezzanotte, ROME, quiet()))
    assert store.put[0][0] == date(2026, 9, 28)


def test_la_tabella_dei_giorni_ha_le_colonne_del_piano_ed_e_idempotente():
    assert "create table if not exists site_days (" in SCHEMA
    assert "day date primary key" in SCHEMA
    assert "countries jsonb" in SCHEMA
    for name in SITE_DAY_FIELDS:
        assert f"  {name} " in SCHEMA or f"add column if not exists {name} " in SCHEMA, name
    assert "create table if not exists incidents (" in SCHEMA


def test_le_colonne_arrivate_dopo_raggiungono_un_database_gia_creato():
    made = SCHEMA.split("create table if not exists site_days (")[1].split(");")[0]
    assert "  misses " not in made
    assert ("alter table site_days add column if not exists misses bigint not null default 0;"
            in SCHEMA)


def test_site_day_put_scrive_una_riga_sola_per_giorno(tmp_path):
    store = Store(Vault(tmp_path))
    seen = []

    class Pool:
        async def execute(self, sql, *args):
            seen.append((" ".join(sql.split()), args))

    store.pool = Pool()
    run(store.site_day_put(DAY, {"requests": 5, "countries": {"IT": 2}}))
    sql, args = seen[0]
    assert sql.startswith("insert into site_days(day,")
    assert "on conflict (day) do update" in sql
    assert args[0] == DAY and json.loads(args[-1]) == {"IT": 2}


def test_site_days_torna_le_righe_dalla_piu_vecchia(tmp_path):
    store = Store(Vault(tmp_path))
    rows = [{"day": date(2026, 9, 27), "requests": 2, "countries": '{"IT": 1}'},
            {"day": date(2026, 9, 26), "requests": 1, "countries": None}]

    class Pool:
        def __init__(self):
            self.seen = None

        async def fetch(self, sql, *args):
            self.seen = (" ".join(sql.split()), args)
            return rows

    store.pool = Pool()
    found = run(store.site_days(30))
    assert [row["day"] for row in found] == [date(2026, 9, 26), date(2026, 9, 27)]
    assert found[1]["countries"] == {"IT": 1} and found[0]["countries"] == {}
    assert "order by day desc limit $1" in store.pool.seen[0]
    assert store.pool.seen[1] == (30,)


def test_rows_chiede_al_deposito_i_giorni_del_piano_e_non_tocca_l_ordine():
    class DayStore(FakeStore):
        def __init__(self):
            super().__init__()
            self.asked = []

        async def site_days(self, limit=30):
            self.asked.append(limit)
            return [{"day": date(2026, 9, 26)}, {"day": DAY}]

    store = DayStore()
    found = run(site_days.rows(store))
    assert store.asked == [site_days.DAYS] and site_days.DAYS == 30
    assert [row["day"] for row in found] == [date(2026, 9, 26), DAY]
    run(site_days.rows(store, 7))
    assert store.asked[-1] == 7


def test_il_giorno_di_oggi_non_entra_mai_fra_le_righe():
    store = FakeStore(secrets=CLOUDFLARE)
    run(site_days.close_day(store, NOW, ROME, quiet()))
    assert store.put[0][0] < day_of(NOW, ROME)


def test_la_sonda_dice_se_la_risposta_passa_da_cloudflare():
    class Client:
        def __init__(self, server):
            self.server = server

        async def get(self, url):
            return type("R", (), {"status_code": 200, "headers": {"server": self.server}})()

    assert run(ops.probe("https://x.invalido", Client("cloudflare"), 10.0))["cdn"] is True
    assert run(ops.probe("https://x.invalido", Client("nginx"), 10.0))["cdn"] is False


def test_la_sonda_accumula_ok_totale_e_millisecondi_nel_giorno():
    store = FakeStore()
    run(ops.probe_day(store, {"ok": True, "ms": 40, "cdn": True}, DAY))
    run(ops.probe_day(store, {"ok": False, "ms": None, "cdn": False}, DAY))
    body = run(ops.probe_day(store, {"ok": True, "ms": 60, "cdn": False}, DAY))
    assert body == {"ok": 2, "total": 3, "ms": [40, 60], "cdn": True}
    assert store.kv[ops.PROBE_DAY + str(DAY)] == body


def test_la_sonda_non_tiene_piu_campioni_dei_giri_di_un_giorno():
    store = FakeStore()
    for _ in range(ops.SAMPLES_MAX + 5):
        run(ops.probe_day(store, {"ok": True, "ms": 10, "cdn": False}, DAY))
    assert len(store.kv[ops.PROBE_DAY + str(DAY)]["ms"]) == ops.SAMPLES_MAX
    assert ops.SAMPLES_MAX == 86400 // ops.PLATFORM_INTERVAL


def test_close_day_porta_la_mediana_e_il_massimo_della_sonda():
    store = FakeStore(secrets=CLOUDFLARE,
                      kv={ops.PROBE_DAY + str(DAY): {"ok": 140, "total": 144,
                                                     "ms": [10, 30, 50, 90], "cdn": True}})
    row = run(site_days.close_day(store, NOW, ROME, quiet()))
    assert row["probe_ok"] == 140 and row["probe_total"] == 144
    assert row["probe_ms_med"] == 40 and row["probe_ms_max"] == 90


def month_row(day, ok, total, med, top):
    return {"day": day, "probe_ok": ok, "probe_total": total,
            "probe_ms_med": med, "probe_ms_max": top}


def test_months_da_la_disponibilita_a_un_decimale_e_la_latenza():
    found = site_days.months([month_row(date(2026, 8, 31), 143, 144, 30, 80),
                              month_row(date(2026, 9, 1), 144, 144, 20, 60),
                              month_row(date(2026, 9, 2), 140, 144, 40, 500)])
    assert [row["month"] for row in found] == ["2026-08", "2026-09"]
    assert found[0]["uptime"] == 99.3 and found[0]["days"] == 1
    assert found[1]["uptime"] == 98.6 and found[1]["ms_med"] == 30 and found[1]["ms_max"] == 500
    assert found[1]["clean"] == 1
    assert site_days.months([]) == []


BACKUP = """[2026-09-27 03:00:01] db-ok 12M /opt/clashbot-backups/db/clashbot-20260927.dump
[2026-09-27 03:00:40] key-ok
[2026-09-27 03:01:10] prune-ok tenuti=3 tolti=1
[2026-09-27 03:01:11] done
"""

RESTORE = """[2026-09-26 04:00:00] restore-start
[2026-09-26 04:03:20] restore-ok clashbot-20260926.dump tabelle 21
"""


def logs(tmp_path, backup=BACKUP, restore=RESTORE):
    one = tmp_path / "backup.log"
    two = tmp_path / "restore.log"
    one.write_text(backup, encoding="utf-8")
    two.write_text(restore, encoding="utf-8")
    for path, text in ((one, backup), (two, restore)):
        last = ops.stamps(text)[-1][0]
        os.utime(path, (last, last))
    return str(one), str(two)


def test_backup_facts_legge_eta_dump_conservati_e_ultima_prova(tmp_path):
    backup, restore = logs(tmp_path)
    at = datetime(2026, 9, 27, 9, 0, 1, tzinfo=timezone.utc).timestamp()
    found = site_days.backup_facts(at, backup, restore)
    assert round(found["dump_age_h"]) == 6
    assert found["dumps"] == 3
    assert found["restore_ok"] is True
    assert found["restore_s"] == 200
    assert found["restore_at"] == datetime(2026, 9, 26, 4, 3, 20,
                                           tzinfo=timezone.utc).timestamp()
    assert found["rpo_h"] == site_days.BACKUP_EVERY_H == 24


def test_backup_facts_senza_riga_di_inizio_non_inventa_la_durata(tmp_path):
    backup, restore = logs(tmp_path, restore="[2026-09-26 04:03:20] restore-FAIL nessun dump\n")
    found = site_days.backup_facts(0.0, backup, restore)
    assert found["restore_ok"] is False and found["restore_s"] is None


def test_l_istante_del_ripristino_usa_lo_stesso_verso_del_backup(tmp_path):
    vero = datetime(2026, 9, 26, 2, 3, 20, tzinfo=timezone.utc).timestamp()
    one = tmp_path / "backup.log"
    two = tmp_path / "restore.log"
    one.write_text(BACKUP, encoding="utf-8")
    two.write_text(RESTORE, encoding="utf-8")
    os.utime(one, (vero, vero))
    os.utime(two, (vero, vero))
    found = site_days.backup_facts(vero, str(one), str(two))
    assert found["restore_at"] == vero
    assert found["restore_s"] == 200


def test_lo_script_del_ripristino_scrive_inizio_e_fine():
    text = (Path(__file__).resolve().parents[1] / "ops/vps/restore-test.sh").read_text("utf-8")
    assert f'log "{site_days.STARTED}"' in text
    for mark in site_days.ENDED:
        assert mark in text, mark


def test_backup_facts_senza_registri_non_inventa_niente(tmp_path):
    found = site_days.backup_facts(0.0, str(tmp_path / "manca.log"), str(tmp_path / "manca2.log"))
    assert found["dump_age_h"] is None and found["dumps"] is None
    assert found["restore_ok"] is None and found["restore_s"] is None


def test_le_aperture_dei_dati_privati_valgono_zero_finche_nessuno_le_scrive():
    store = FakeStore()
    assert run(site_days.opens(store, ["2026-08", "2026-09"])) == {"2026-08": 0, "2026-09": 0}
    store.kv[site_days.OPENS_KEY] = {"2026-09": 2}
    assert run(site_days.opens(store, ["2026-08", "2026-09"])) == {"2026-08": 0, "2026-09": 2}


def moment(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def test_le_segnalazioni_si_contano_per_mese_col_tempo_mediano_di_prima_risposta():
    rows = [{"code": "AB1", "at": moment("2026-09-01 10:00:00")},
            {"code": "AB1", "at": moment("2026-09-01 12:00:00")},
            {"code": "CD2", "at": moment("2026-09-03 10:00:00")},
            {"code": "EF3", "at": moment("2026-08-05 10:00:00")}]
    log = [{"what": "report", "code": "AB1", "at": moment("2026-09-01 11:00:00")},
           {"what": "report", "code": "CD2", "at": moment("2026-09-03 13:00:00")},
           {"what": "news", "at": moment("2026-09-04 10:00:00")}]
    found = site_days.report_facts(rows, log)
    assert [row["month"] for row in found] == ["2026-08", "2026-09"]
    assert found[0] == {"month": "2026-08", "n": 1, "answer_s": None}
    assert found[1]["n"] == 3 and found[1]["answer_s"] == 7200


def test_le_segnalazioni_non_portano_nomi_ne_utenti():
    rows = [{"code": "AB1", "at": moment("2026-09-01 10:00:00"), "by": 4242, "alias": "clan-1"}]
    found = site_days.report_facts(rows, [])
    assert json.dumps(found).find("4242") == -1
    assert json.dumps(found).find("clan-1") == -1


@pytest.mark.parametrize("name", ("pull", "close_day", "rows", "months", "backup_facts"))
def test_il_modulo_espone_le_funzioni_del_piano(name):
    assert callable(getattr(site_days, name))


def test_il_bot_chiude_il_giorno_col_fuso_del_gestore():
    store = FakeStore(secrets=dict(CLOUDFLARE, owner_tz=ROME))
    keeper = SimpleNamespace(store=store)
    row = run(Supervisor.close_site_day(keeper, quiet(), NOW))
    assert row is not None and store.put[0][0] == DAY
    assert run(Supervisor.close_site_day(keeper, quiet(), NOW)) is None


def test_il_compose_monta_il_registro_del_ripristino_in_sola_lettura():
    text = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/opt/clashbot-backups/restore.log:/backup/restore.log:ro" in text
    assert "/opt/clashbot-backups/backup.log:/backup/backup.log:ro" in text


def test_i_segreti_di_cloudflare_sono_dichiarati_nel_comando():
    assert site_days.TOKEN_KIND in cli.SECRET_KINDS
    assert site_days.ZONE_KIND in cli.SECRET_KINDS
    assert site_days.ZONE_KIND in cli.PLAIN_KINDS
    assert site_days.TOKEN_KIND not in cli.PLAIN_KINDS
