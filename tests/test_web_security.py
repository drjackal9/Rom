import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from urllib.robotparser import RobotFileParser

from clashbot import i18n, incidents as inc, selfmetrics, site_days, trend
from clashbot.db import SITE_DAY_FIELDS, SITE_DAYS_KEEP
from clashbot.util import esc
from clashbot.web import app as web_app, ban, http, pages, public, static
from clashbot.web import security as web_security
from test_web_insieme import TuttoStore
from test_web_status import ITALIAN, request, same_dress

AT = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc).timestamp()
DAY = date(2026, 9, 28)
ROME = "Europe/Rome"
IP = "203.0.113.9"


class CountStore(TuttoStore):
    def __init__(self, bans=()):
        super().__init__()
        self.secrets["owner_tz"] = ROME
        self.bans = list(bans)

    async def banned(self, limit=100):
        return list(self.bans)


def site(store=None):
    place = web_app.Site(store or CountStore(), lambda: 0.0)
    place.zone = ROME
    return place


def serve(place, path, peer="203.0.113.7", method="GET"):
    return asyncio.run(place.router(request(path, method, peer=peer, headers=ITALIAN)))


def run(coro):
    return asyncio.run(coro)


def test_il_web_conta_richieste_404_sconosciuti_429_e_sonde_sulle_esche():
    place = site()
    serve(place, "/")
    serve(place, "/non-esiste")
    serve(place, "/.env")
    assert place.counters["own_requests"] == 3
    assert place.counters["misses"] == 1
    assert place.counters["probes"] == 1
    assert place.counters["limited"] == 0


def test_il_web_conta_i_rifiuti_per_troppe_richieste():
    place = site()
    for _ in range(http.READ_RATE + 2):
        serve(place, "/", peer=IP)
    assert place.counters["limited"] == 2


def test_i_bandi_si_contano_per_livello_nel_giorno():
    rows = [{"ip": "a", "at": AT, "strikes": 1}, {"ip": "b", "at": AT, "strikes": 2},
            {"ip": "c", "at": AT, "strikes": 3}, {"ip": "d", "at": AT, "strikes": 9},
            {"ip": "e", "at": AT - 3 * 86400, "strikes": 1}, {"ip": "f", "at": None}]
    found = ban.levels(rows, DAY, ROME)
    assert found == {"banned_h": 1, "banned_d": 1, "banned_forever": 2}
    assert ban.levels([], DAY, ROME) == {"banned_h": 0, "banned_d": 0, "banned_forever": 0}


def test_il_battito_scarica_i_contatori_nel_giorno_e_riparte_da_zero():
    store = CountStore(bans=[{"ip": "a", "at": AT, "strikes": 1}])
    place = site(store)
    serve(place, "/")
    serve(place, "/non-esiste")
    body = run(place.flush(AT))
    key = selfmetrics.WEB_DAY + str(DAY)
    assert store.kv[key] == body
    assert body["own_requests"] == 2 and body["misses"] == 1 and body["banned_h"] == 1
    assert place.counters == dict.fromkeys(web_app.COUNTERS, 0)
    serve(place, "/")
    again = run(place.flush(AT))
    assert again["own_requests"] == 3 and again["misses"] == 1


def test_il_battito_tiene_il_massimo_dei_bandi_del_giorno():
    store = CountStore(bans=[{"ip": "a", "at": AT, "strikes": 1}])
    place = site(store)
    run(place.flush(AT))
    store.bans = []
    body = run(place.flush(AT))
    assert body["banned_h"] == 1


def page(body, headers=None):
    return http.Response(body, headers=dict(headers or {}))


def test_il_controllo_di_una_pagina_vede_cookie_script_e_domini_fuori():
    found = web_app.audit_page(page(
        '<link rel="stylesheet" href="https://cdn.invalido/x.css">'
        '<script src="https://cdn.invalido/x.js"></script>',
        {"Set-Cookie": "a=b", "Content-Security-Policy": "default-src 'none'"}))
    assert found["cookies"] == 1 and found["scripts"] == 1
    assert found["outside"] == ["https://cdn.invalido/x.js", "https://cdn.invalido/x.css"]


def test_il_controllo_lascia_passare_i_domini_ammessi():
    found = web_app.audit_page(page(
        f'<img src="{web_app.ALLOWED_HOSTS[0]}/vi/abc/mqdefault.jpg">'
        f'<img src="{web_app.ALLOWED_HOSTS[1]}/badge.png">'
        '<link rel="stylesheet" href="/static/abc/site.css">',
        {"Content-Security-Policy": "default-src 'none'"}))
    assert found["outside"] == [] and found["scripts"] == 0 and found["cookies"] == 0
    assert found["missing"] == []


def test_il_controllo_segnala_le_intestazioni_che_mancano():
    assert web_app.audit_page(page("<p>ciao</p>"))["missing"] == ["Content-Security-Policy"]


CSP = {"Content-Security-Policy": "default-src 'none'"}
FUORI = "https://cdn.invalido/x.js"


def test_il_controllo_non_si_fa_aggirare_dalle_virgolette_singole():
    found = web_app.audit_page(page(f"<script src='{FUORI}'></script>", CSP))
    assert found["scripts"] == 1 and found["outside"] == [FUORI]


def test_il_controllo_non_si_fa_aggirare_dalle_maiuscole():
    found = web_app.audit_page(page(f'<script SRC="{FUORI.upper()}"></script>', CSP))
    assert found["scripts"] == 1 and found["outside"] == [FUORI.upper()]


def test_il_controllo_non_si_fa_aggirare_dal_protocollo_relativo():
    found = web_app.audit_page(page('<script src="//cdn.invalido/x.js"></script>', CSP))
    assert found["scripts"] == 1 and found["outside"] == ["//cdn.invalido/x.js"]


def test_il_controllo_non_si_fa_aggirare_da_un_foglio_con_apici():
    found = web_app.audit_page(page(
        "<link rel='stylesheet' href='//cdn.invalido/x.css'>", CSP))
    assert found["outside"] == ["//cdn.invalido/x.css"]


def test_il_controllo_non_segnala_le_immagini_incorporate():
    found = web_app.audit_page(page('<img src="data:image/svg+xml,%3Csvg/%3E">', CSP))
    assert found["outside"] == [] and found["scripts"] == 0


def test_il_controllo_non_si_fa_aggirare_da_un_dominio_che_comincia_come_uno_ammesso():
    for host in web_app.ALLOWED_HOSTS:
        falso = f"{host}.male.invalido/pixel.gif"
        assert web_app.audit_page(page(f'<img src="{falso}">', CSP))["outside"] == [falso]


def test_il_controllo_non_si_fa_aggirare_dalla_chiocciola():
    falso = f"{web_app.ALLOWED_HOSTS[0]}@male.invalido/pixel.gif"
    assert web_app.audit_page(page(f'<img src="{falso}">', CSP))["outside"] == [falso]


def test_il_controllo_non_si_fa_aggirare_dalle_entita_html():
    found = web_app.audit_page(page('<script src="&#104;ttps://cdn.invalido/x.js"></script>', CSP))
    assert found["scripts"] == 1 and found["outside"] == [FUORI]


def test_il_controllo_guarda_anche_srcset_e_object():
    found = web_app.audit_page(page(
        '<img srcset="https://cdn.invalido/a.png 1x, https://cdn.invalido/b.png 2x">'
        '<object data="https://cdn.invalido/c.svg"></object>', CSP))
    assert found["outside"] == ["https://cdn.invalido/a.png", "https://cdn.invalido/b.png",
                                "https://cdn.invalido/c.svg"]


def test_il_controllo_lascia_passare_i_domini_ammessi_anche_in_maiuscolo():
    found = web_app.audit_page(page(
        f'<img src="{web_app.ALLOWED_HOSTS[0].upper()}/vi/abc/mqdefault.jpg">', CSP))
    assert found["outside"] == []


def test_una_pagina_che_non_risponde_non_diventa_un_intestazione(monkeypatch):
    monkeypatch.setattr(web_app, "AUDIT_PATHS", ("/", "/non-esiste"))
    store = CountStore()
    found = run(site(store).audit(AT))
    assert found["missing"] == []
    assert found["broken"] == ["/non-esiste"]
    assert found["pages"] == 1 and found["ok"] is False


def test_ogni_contatore_del_web_arriva_alla_riga_del_giorno():
    for name in web_app.COUNTERS:
        assert name in site_days.WEB_FIELDS, name
        assert name in SITE_DAY_FIELDS, name


def test_il_sito_vero_si_controlla_e_risulta_pulito():
    store = CountStore()
    found = run(site(store).audit(AT))
    assert found["ok"] is True
    assert found["pages"] == len(web_app.AUDIT_PATHS)
    assert found["cookies"] == 0 and found["scripts"] == 0 and found["outside"] == []
    assert found["version"] == static.manifest()["hash"]
    assert found["day"] == str(DAY)
    assert store.kv[web_app.AUDIT_KEY] == found


def test_il_controllo_non_si_ripete_se_la_versione_non_cambia():
    store = CountStore()
    place = site(store)
    assert run(place.audit_once(AT)) is not None
    assert run(place.audit_once(AT)) is None
    store.kv[web_app.AUDIT_KEY] = dict(store.kv[web_app.AUDIT_KEY], version="vecchia")
    assert run(place.audit_once(AT)) is not None


EN = i18n.locale("en")
NOW_DT = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
NOW = NOW_DT
YESTERDAY = date(2026, 9, 27)
BUILD = "abc123"
OPENED = datetime(2026, 9, 20, 11, 30, tzinfo=timezone.utc)
CLOSED = datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc)
SECRET_PATH = "/wp-login.php"
RULE_NAME = "regola-manuale-7"
PERSON = "Pino"


def day_row(day, **over):
    row = dict.fromkeys(SITE_DAY_FIELDS, 0)
    row.update({"day": day, "countries": {}})
    row.update(over)
    return row


def window(n=3):
    first = YESTERDAY - timedelta(days=n - 1)
    return [day_row(first + timedelta(days=step), requests=100 + step, pages=10 + step,
                    visitors=5 + step, blocked_total=9 + step, blocked_waf=4, blocked_bot=3,
                    blocked_rule=2 + step, probes=7 + step, banned_h=1, banned_d=1,
                    banned_forever=1, probe_ok=143, probe_total=144, probe_ms_med=120 + step,
                    probe_ms_max=400 + step, countries={"IT": 80, "DE": 20})
            for step in range(n)]


AUDIT = {"ok": True, "version": BUILD, "day": str(YESTERDAY), "pages": 8, "cookies": 0,
         "scripts": 0, "outside": [], "missing": [], "broken": [], "hsts": True}
BACKUP = {"dump_age_h": 6, "dumps": 3, "rpo_h": 24, "restore_ok": True,
          "restore_at": datetime(2026, 9, 26, 3, tzinfo=timezone.utc).timestamp(),
          "restore_s": 200}
NOTHING = {"dump_age_h": None, "dumps": None, "rpo_h": 24, "restore_ok": None,
           "restore_at": None, "restore_s": None}
HEADS = ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy",
         "Strict-Transport-Security")


class PageStore(CountStore):
    def __init__(self, days=None, incidents=(), reports=()):
        super().__init__()
        self.rows = window() if days is None else list(days)
        self.inc = list(incidents)
        self.rep = list(reports)
        self.letture = 0
        self.chiesto = None
        self.kv[web_app.AUDIT_KEY] = dict(AUDIT)

    async def site_days(self, limit=SITE_DAYS_KEEP):
        self.letture += 1
        self.chiesto = limit
        return list(self.rows)

    async def incidents(self, limit=20):
        return list(self.inc)

    async def reports(self, limit=20):
        return list(self.rep)


def facts(days=None, audit=None, backup=None, reports=(), incidents=(), opens=None,
          uptime_s=90000.0, links=None):
    rows = window() if days is None else list(days)
    return {"days": rows, "months": site_days.months(rows),
            "backup": dict(backup or BACKUP), "audit": dict(audit or AUDIT),
            "reports": list(reports), "incidents": list(incidents),
            "opens": dict(opens or {}), "uptime_s": uptime_s, "heads": list(HEADS),
            "links": dict(links or {})}


def rendered(found=None, L=EN):
    return web_security.security_page(L, found or facts(), NOW)


def heads_of(text):
    return re.findall(r"<h2>([^<]+)</h2>", text)


def hrs(n):
    return f"{EN.n(n)}{EN.t('unit.h')}"


def dys(n):
    return f"{EN.n(n)}{EN.t('unit.d')}"


def section(text, key):
    title = esc(EN.t(key))
    rest = text.split(f"<h2>{title}</h2>", 1)[1]
    return rest.split("<h2>", 1)[0]


def test_la_pagina_della_sicurezza_ha_le_sette_sezioni_in_ordine():
    text = rendered()
    same_dress(text)
    assert heads_of(text) == [esc(EN.t(key)) for key in web_security.SECTIONS]
    assert esc(EN.t("web.security.title")) in text
    assert "<ul" not in text and "<ol" not in text and "<table" not in text


def test_la_pagina_dice_che_i_numeri_arrivano_a_ieri():
    assert esc(EN.t("web.security.asof", date=str(YESTERDAY))) in rendered()


def test_il_traffico_porta_i_totali_la_ripartizione_le_barre_e_i_paesi():
    rows = window()
    part = section(rendered(facts(rows)), "web.security.traffic")
    assert EN.n(sum(row["requests"] for row in rows)) in part
    assert EN.n(sum(row["visitors"] for row in rows)) in part
    assert EN.n(sum(row["blocked_total"] for row in rows)) in part
    for name in ("waf", "bot", "rule"):
        assert esc(EN.t("web.security." + name)) in part, name
    assert part.count("<span") >= len(rows)
    assert part.count('class="days"') == 1
    for code in ("IT", "DE"):
        assert f'<span class="chip">{code}</span>' in part, code


def test_l_affidabilita_porta_disponibilita_latenza_giorni_puliti_e_ultimo_riavvio():
    found = facts()
    part = section(rendered(found), "web.security.uptime")
    month = found["months"][0]
    assert month["month"] in part
    assert EN.pct(month["uptime"]) in part
    assert EN.n(month["ms_med"]) in part and EN.n(month["ms_max"]) in part
    assert esc(EN.t("web.security.clean")) in part
    assert esc(EN.t("web.security.mid")) in part
    assert esc(EN.t("web.security.peak")) in part
    assert esc(EN.t("web.security.restart")) in part
    assert dys(1) in part


def test_il_backup_porta_eta_copie_prova_di_ripristino_rpo_e_rto():
    part = section(rendered(facts()), "web.security.backup")
    assert hrs(BACKUP["dump_age_h"]) in part
    assert EN.n(BACKUP["dumps"]) in part
    assert esc(EN.t("web.security.ok")) in part
    assert dys(site_days.BACKUP_EVERY_H // 24) in part
    assert "2026-09-26" in part
    assert EN.n(BACKUP["restore_s"]) in part


def test_i_dati_dicono_cosa_si_tiene_cosa_no_e_quando_e_stato_verificato():
    part = section(rendered(facts()), "web.security.data")
    assert esc(EN.t("web.security.collect")) in part
    assert esc(EN.t("web.security.never")) in part
    assert esc(EN.t("web.security.checked", date=str(YESTERDAY), build=BUILD)) in part


TENUTO = ("blind telegram id", "linked village tags", "public game data",
          "clan notes and settings", "day the terms were accepted", "encrypted")
MAI = ("no tracking", "nothing sold")


def tessera_del_tenuto(part):
    title = f'<span class="big">{esc(EN.t("web.security.collect"))}</span>'
    return part.split(title, 1)[1].split('<div class="tile">', 1)[0].lower()


def test_la_tessera_di_quello_che_teniamo_elenca_tutto_quello_che_dice_la_spec():
    tessera = tessera_del_tenuto(section(rendered(facts()), "web.security.data"))
    for voce in TENUTO:
        assert voce in tessera, voce
    assert tessera.count("<span>") >= len(TENUTO) - 1


def test_la_tessera_di_quello_che_non_teniamo_dice_niente_tracce_e_niente_venduto():
    part = section(rendered(facts()), "web.security.data").lower()
    for voce in MAI:
        assert voce in part, voce


def test_i_dati_portano_la_promessa_sulle_aperture_col_numero_del_mese():
    found = facts(opens={"2026-09": 2})
    part = section(rendered(found), "web.security.data")
    assert esc(EN.t("web.security.opens")) in part
    assert esc(EN.t("web.security.promise")) in part
    assert ">2<" in part
    senza = section(rendered(facts()), "web.security.data")
    assert esc(EN.t("web.security.opens")) in senza and ">0<" in senza


def test_il_perimetro_porta_porte_tls_intestazioni_limiti_scala_e_autocontrollo():
    part = section(rendered(facts()), "web.security.edge")
    assert esc(EN.t("web.security.ports")) in part and ">0<" in part
    assert web_security.TLS in part
    for name in HEADS:
        assert name in part, name
    assert f">{EN.n(http.READ_RATE)}/{EN.n(http.WRITE_RATE)}<" in part
    assert esc(EN.t("web.security.perminute")) in part
    assert hrs(1) in part and dys(1) in part
    assert esc(EN.t("web.security.forever")) in part
    assert esc(EN.t("web.security.otpon")) in part
    assert esc(EN.t("web.security.ok")) in part


def test_le_esche_portano_i_tocchi_gli_indirizzi_banditi_e_le_barre():
    rows = window()
    part = section(rendered(facts(rows)), "web.security.decoy")
    assert EN.n(sum(row["probes"] for row in rows)) in part
    assert EN.n(sum(row["banned_h"] + row["banned_d"] + row["banned_forever"]
                    for row in rows)) in part
    assert part.count('class="days"') == 1


def test_le_segnalazioni_e_gli_incidenti_hanno_mese_risposta_giorno_e_durata():
    reports = [{"month": "2026-09", "n": 4, "answer_s": 7200}]
    rows = [{"id": 1, "kind": "outage", "opened": OPENED, "closed": CLOSED, "note": "giu"},
            {"id": 2, "kind": "bug", "opened": OPENED, "closed": None, "note": ""}]
    part = section(rendered(facts(reports=reports, incidents=rows)), "web.security.reports")
    assert "2026-09" in part and ">4<" in part
    assert esc(EN.t("web.security.answer")) in part
    assert hrs(2) in part
    assert esc(inc.kind_label(EN, "outage")) in part
    assert esc(inc.kind_label(EN, "bug")) in part
    assert "2026-09-20" in part
    assert hrs(3) in part
    assert esc(EN.t("web.security.open")) in part


def test_senza_incidenti_la_pagina_lo_dice():
    part = section(rendered(facts(reports=[{"month": "2026-09", "n": 1, "answer_s": None}])),
                   "web.security.reports")
    assert esc(EN.t("web.security.none")) in part
    assert esc(EN.t("web.security.nd")) in part


def test_le_segnalazioni_portano_i_collegamenti_di_chi_vuole_avvisare():
    links = {"source": "https://example.org/cb", "checklist": "https://example.org/cb/c.md",
             "thanks": "https://example.org/cb/t.md"}
    part = section(rendered(facts(links=links)), "web.security.reports")
    assert f'href="{pages.SECURITY_TXT}"' in part
    assert f'href="{esc(links["checklist"])}"' in part
    assert f'href="{esc(links["thanks"])}"' in part
    senza = section(rendered(facts()), "web.security.reports")
    assert "checklist" not in senza and "thanks" not in senza


def test_senza_righe_ogni_sezione_misurata_mostra_la_tessera_vuota():
    text = rendered(facts(days=[], audit={}, backup=NOTHING, uptime_s=None))
    assert text.count(esc(EN.t(public.EMPTY))) == web_security.MEASURED
    assert text.count(esc(EN.t("web.security.nd"))) >= 1
    assert dys(site_days.BACKUP_EVERY_H // 24) in text


def test_la_pagina_non_porta_indirizzi_percorsi_ore_nomi_di_regola_ne_persone():
    rows = [{"id": 1, "kind": "abuse", "opened": OPENED, "closed": CLOSED,
             "note": f"{IP} {SECRET_PATH} {RULE_NAME} {PERSON}"}]
    found = facts(incidents=rows, audit=dict(AUDIT, outside=[f"https://{PERSON}.invalido/x.js"],
                                             broken=[SECRET_PATH]))
    text = rendered(found)
    for leak in (IP, SECRET_PATH, RULE_NAME, PERSON, "11:30", "14:30"):
        assert leak not in text, leak


def test_la_pagina_della_sicurezza_risponde_in_inglese_anche_a_un_browser_italiano():
    store = PageStore()
    place = site(store)
    res = serve(place, web_security.PATH)
    assert res.status == 200
    text = res.body.decode()
    assert esc(EN.t("web.security.title")) in text
    assert "[web." not in text
    assert res.headers["Cache-Control"] == pages.PAGE_HEAD
    assert res.headers["Content-Security-Policy"].startswith(pages.CSP_BASE)


def test_la_pagina_si_legge_una_volta_sola_dentro_la_cache():
    store = PageStore()
    place = site(store)
    serve(place, web_security.PATH)
    serve(place, web_security.PATH)
    assert store.letture == 1


def test_i_numeri_della_pagina_vengono_tutti_dal_database():
    store = PageStore()
    found = run(web_security.numbers(store, NOW_DT, AUDIT, HEADS))
    assert [str(row["day"]) for row in found["days"]] == [str(row["day"]) for row in store.rows]
    assert found["months"] == site_days.months(store.rows)
    assert found["audit"] == AUDIT and found["heads"] == list(HEADS)
    assert found["reports"] == site_days.report_facts(store.rep, [])
    assert found["incidents"] == store.inc
    assert found["opens"] == {"2026-09": 0}
    assert store.chiesto == SITE_DAYS_KEEP == trend.DAYS


def test_una_scrittura_sulla_pagina_della_sicurezza_non_esiste():
    assert serve(site(PageStore()), web_security.PATH, method="POST").status == 405


def test_i_motori_possono_leggere_la_pagina_della_sicurezza():
    regole = RobotFileParser()
    regole.parse(serve(site(PageStore()), "/robots.txt").body.decode().splitlines())
    assert regole.can_fetch("*", web_security.PATH)


def test_la_home_e_la_barra_portano_alla_pagina_della_sicurezza():
    assert (pages.SECURITY, web_security.PATH) == ("/security", "/security")
    assert web_security.PATH in [href for _, _, _, href in pages.SECTIONS]
    assert web_security.PATH in [href for _, href in pages.MENU]
    text = serve(site(PageStore()), "/").body.decode()
    assert f'<a class="tile go" href="{web_security.PATH}"' in text
