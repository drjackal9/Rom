import logging
import pathlib
import re
from datetime import datetime, timezone

from clashbot import (bridge, capital, db, familyroom, i18n, leaderboards, media, publish, render,
                      roster, twitch, util)
from clashbot.retention import WAR_HISTORY_KEEP
from clashbot.ttl import MANAGED_TTL
from clashbot.web import auth as web_auth, board as web_board, pages as web_pages, payload


def sorgente(modulo):
    return pathlib.Path(modulo.__file__).read_text(encoding="utf-8")


def test_il_ponte_discord_taglia_sul_limite_vero_della_piattaforma():
    assert bridge.DISCORD_LIMIT == 2000
    assert not hasattr(bridge, "DISCORD_MAX")
    lungo = bridge.to_discord("Mario", "x" * 5000, "[foto]")
    assert len(lungo) == bridge.DISCORD_LIMIT
    assert lungo.startswith("**Mario**: ") and lungo.endswith(" [foto]")
    assert bridge.to_discord("Mario", "ciao") == "**Mario**: ciao"


def test_il_token_twitch_non_ha_margini_scritti_a_mano():
    assert not hasattr(twitch, "TOKEN_MARGIN") and not hasattr(twitch, "TOKEN_FALLBACK")
    assert "3600" not in sorgente(twitch)


def test_le_misure_del_servizio_web_vengono_da_casa():
    assert web_board.CODE_MAX is payload.SLUG_LEN
    assert web_auth.SKEW is MANAGED_TTL
    assert media.SITE_TTL is MANAGED_TTL
    assert publish.KEEP_ERRORS is WAR_HISTORY_KEEP
    assert publish.TEXT_MAX is render.MAX_LEN
    assert "600" not in sorgente(publish)
    assert not hasattr(publish, "USAGE_EVERY")
    assert not hasattr(payload, "STALE")


def test_il_testo_di_un_errore_recente_si_taglia_sulla_misura_del_messaggio():
    recente = publish.Recent()
    riga = logging.LogRecord("clashbot.prova", logging.WARNING, "", 1,
                             "x" * (render.MAX_LEN + 10), (), None)
    recente.emit(riga)
    assert len(recente.rows[-1]["text"]) == render.MAX_LEN


def test_il_ritardo_del_battito_ha_un_numero_solo():
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    puntuale = payload.services_note(now, 60 * payload.LATE_ROUNDS, 60, True, 1, 1, 1, 1)
    tardi = payload.services_note(now, 60 * (payload.LATE_ROUNDS + 1) + 1, 60, True, 1, 1, 1, 1)
    assert {row["name"]: row["state"] for row in puntuale["services"]}["poller"] == "up"
    assert {row["name"]: row["state"] for row in tardi["services"]}["poller"] == "down"
    testo = sorgente(payload)
    assert "interval * 2" not in testo and "interval * 3" not in testo


def test_le_prime_dieci_sono_una_misura_sola():
    assert capital.TOP is leaderboards.TOP
    assert familyroom.SUGGEST_KEEP is leaderboards.TOP


def test_gli_ex_membri_si_contano_in_un_posto_solo():
    assert roster.FORMER_SHOWN == 40
    assert "limit=FORMER_SHOWN" in sorgente(db)
    assert "rows[:FORMER_SHOWN]" in sorgente(render)


def test_la_data_delle_pagine_legali_segue_il_testo_nel_catalogo():
    assert not hasattr(web_pages, "UPDATED")
    assert re.search(r"\b20\d\d-\d\d-\d\d\b", sorgente(web_pages)) is None
    for code in i18n.LANGUAGES:
        datetime.strptime(i18n.locale(code).t("web.legal.date"), "%Y-%m-%d")


def test_il_tetto_delle_etichette_viene_dall_api():
    assert util.API_LABELS == 3
    assert "LABELS_MAX" not in sorgente(render)
