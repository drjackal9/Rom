import pathlib
from datetime import datetime, timedelta, timezone

from clashbot import events_registry, i18n, recruit, render, retention, util
from clashbot import settings as settings_mod
from clashbot.web import board

NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
SNAP = {"name": "Toad", "th": 15, "trophies": 4100, "best": 4300, "warStars": 900,
        "heroes": {"Barbarian King": 80, "Archer Queen": 85}, "warPref": "in",
        "donations": 1200, "received": 900, "capital": 50000, "exp": 190, "clan": "#OLD"}


def fresh():
    return recruit.state_of(None)


def test_state_of_ricostruisce_un_documento_rotto():
    assert fresh() == {"next": 1, "items": {}, "reminded": None}
    broken = {"items": {"1": {"tag": "#P1", "state": "pending"}, "2": "rotto",
                        "3": {"state": "pending"}, "9": {"tag": "#P9", "state": "boh"}},
              "next": 0, "reminded": "2026-09-13"}
    state = recruit.state_of(broken)
    assert list(state["items"]) == ["1"]
    assert state["next"] == 2 and state["reminded"] == "2026-09-13"


def test_requirement_e_meets_leggono_le_impostazioni_di_oggi():
    conf = settings_mod.effective({"min_th": 14})
    assert recruit.requirement(conf) == 14
    assert recruit.requirement(settings_mod.effective({})) is None
    assert recruit.requirement({"min_th": True}) is None
    assert recruit.meets(conf, SNAP) is True
    assert recruit.meets(conf, {"th": 13}) is False
    assert recruit.meets(conf, {"th": None}) is True
    assert recruit.meets({}, {"th": 3}) is True


def test_goals_of_tiene_solo_quelli_previsti_e_nell_ordine():
    assert recruit.goals_of(["capital", "war", "inventato"]) == ["war", "capital"]
    assert recruit.goals_of(None) == []


def test_add_numera_e_mette_in_sospeso():
    state, app = recruit.add(fresh(), "#P9", SNAP, 7, True, ["war"], False, NOW)
    assert app["id"] == "1" and app["state"] == "pending" and app["verified"] is True
    assert app["goals"] == ["war"] and app["below"] is False and app["snap"]["th"] == 15
    state, second = recruit.add(state, "#P8", SNAP, 8, False, [], True, NOW)
    assert second["id"] == "2" and state["next"] == 3
    assert [a["id"] for a in recruit.pending(state)] == ["1", "2"]
    assert [a["id"] for a in recruit.pending(state, 8)] == ["2"]


def test_decide_vale_una_volta_sola():
    state, app = recruit.add(fresh(), "#P9", SNAP, 7, True, [], False, NOW)
    state, decided = recruit.decide(state, app["id"], "accepted", 5, "Mario", NOW)
    assert decided["state"] == "accepted" and decided["by"] == 5 and decided["by_name"] == "Mario"
    assert recruit.decide(state, app["id"], "rejected", 5, "Mario", NOW)[1] is None
    assert recruit.decide(state, "99", "accepted", 5, "Mario", NOW)[1] is None
    assert recruit.decide(fresh(), "1", "boh", 5, "Mario", NOW)[1] is None


def test_close_joined_chiude_chi_e_entrato_davvero():
    state, first = recruit.add(fresh(), "#P9", SNAP, 7, True, [], False, NOW)
    state, second = recruit.add(state, "#P8", SNAP, 8, True, [], False, NOW)
    state, _ = recruit.decide(state, first["id"], "accepted", 5, "Mario", NOW)
    state, arrived = recruit.close_joined(state, {"#P9": {"name": "Toad"}}, NOW)
    assert [a["id"] for a in arrived] == ["1"]
    assert recruit.find(state, "1")["state"] == "joined"
    assert recruit.find(state, second["id"])["state"] == "pending"


def test_stale_guarda_solo_chi_aspetta_da_piu_di_un_giorno():
    state, old = recruit.add(fresh(), "#P9", SNAP, 7, True, [], False, NOW - timedelta(hours=30))
    state, _ = recruit.add(state, "#P8", SNAP, 8, True, [], False, NOW)
    assert [a["id"] for a in recruit.stale(state, NOW)] == [old["id"]]


def test_prune_cancella_le_decise_vecchie_e_tiene_il_tetto():
    state = fresh()
    old = NOW - timedelta(days=recruit.DECIDED_DAYS + 1)
    state, gone = recruit.add(state, "#P1", SNAP, 1, True, [], False, old)
    state, _ = recruit.decide(state, gone["id"], "rejected", 5, "Mario", old)
    state, kept = recruit.add(state, "#P2", SNAP, 2, True, [], False, old)
    state = recruit.prune(state, NOW)
    assert recruit.find(state, gone["id"]) is None
    assert recruit.find(state, kept["id"])["state"] == "pending"
    for n in range(recruit.KEEP + 5):
        state, extra = recruit.add(state, f"#X{n}", SNAP, 100 + n, True, [], False, NOW)
        state, _ = recruit.decide(state, extra["id"], "rejected", 5, "Mario", NOW)
    assert len(state["items"]) == recruit.KEEP
    assert recruit.find(state, kept["id"])["state"] == "pending"


def test_prune_non_butta_mai_chi_aspetta_ancora_una_risposta():
    state = fresh()
    first = None
    for n in range(recruit.KEEP + 3):
        state, app = recruit.add(state, f"#W{n}", SNAP, 200 + n, True, [], False, NOW)
        if first is None:
            first = app
    assert recruit.find(state, first["id"])["state"] == "pending"
    assert len(state["items"]) == recruit.KEEP + 3
    assert recruit.counts(state)["pending"] == recruit.KEEP + 3
    state, _ = recruit.decide(state, first["id"], "rejected", 5, "Mario", NOW)
    state, _ = recruit.add(state, "#WLAST", SNAP, 999, True, [], False, NOW)
    assert recruit.find(state, first["id"]) is None
    assert len(state["items"]) == recruit.KEEP + 3
    assert recruit.counts(state)["pending"] == recruit.KEEP + 3


def test_counts_dice_quanti_aspettano_e_quanti_sono_sotto_requisito():
    state, _ = recruit.add(fresh(), "#P1", SNAP, 1, True, [], False, NOW)
    state, _ = recruit.add(state, "#P2", SNAP, 2, False, [], True, NOW)
    assert recruit.counts(state) == {"pending": 2, "below": 1, "unverified": 1}


def test_mark_via_scrive_la_provenienza_senza_toccare_il_resto():
    players = {"tags": {"#P9": {"th": 15}}, "joined": {"#P9": {"ts": 1.0, "told": True}}}
    out = recruit.mark_via(players, "#P9", NOW)
    assert out["joined"]["#P9"] == {"ts": 1.0, "told": True, "via": "apply"}
    assert out["tags"] == {"#P9": {"th": 15}}
    born = recruit.mark_via(None, "#P7", NOW)["joined"]["#P7"]
    assert born["via"] == "apply" and born["told"] is False


def test_board_row_solo_aggregati_e_nome_solo_se_nominato():
    info = {"level": 18, "members": 46, "league": "Cristallo I", "country": "IT",
            "type": "open", "war_frequency": "always", "labels": ["Clan Wars", "Farming", "x", "y"]}
    conf = settings_mod.effective({"min_th": 14, "lang": "it", "note": "niente pigri"})
    row = recruit.board_row(info, conf, False, "ab12cd", "Futuro", "#CLAN1")
    assert row["code"] == "ab12cd" and row["free"] == 4 and row["min_th"] == 14
    assert row["country"] == "IT" and row["lang"] == "it" and row["labels"] == ["Clan Wars", "Farming", "x"]
    assert row["name"] is None and row["tag"] is None
    assert "niente pigri" not in repr(row)
    named = recruit.board_row(info, conf, True, "ab12cd", "Futuro", "#CLAN1")
    assert named["name"] == "Futuro" and named["tag"] == "#CLAN1"
    assert recruit.board_row({**info, "members": 50}, conf, True, "ab12cd") is None
    assert recruit.board_row({**info, "type": "closed"}, conf, True, "ab12cd") is None
    assert recruit.board_row(None, conf, True, "ab12cd") is None
    sporco = recruit.board_row({**info, "labels": [{"id": 1, "name": "Clan Wars"}, "Farming"]},
                               conf, True, "ab12cd")
    assert sporco["labels"] == ["Farming"] and "iconUrls" not in repr(sporco)


def test_info_fields_pulisce_il_json_del_clan():
    clan_json = {"clanLevel": 18, "type": "open", "warFrequency": "always",
                 "location": {"countryCode": "IT", "name": "Italy"},
                 "labels": [{"id": 56000000, "name": "Clan Wars", "iconUrls": {"small": "x"}},
                            {"id": 56000001, "name": "Farming"}, "rotto", {}]}
    fields = recruit.info_fields(clan_json)
    assert fields == {"country": "IT", "type": "open", "war_frequency": "always",
                      "labels": ["Clan Wars", "Farming"]}
    assert "iconUrls" not in repr(fields) and "56000000" not in repr(fields)
    assert recruit.info_fields(None) == {"country": None, "type": None,
                                         "war_frequency": None, "labels": []}
    assert recruit.board_row({**info_base(), **fields}, settings_mod.effective({"lang": "it"}),
                             False, "ab12cd")["labels"] == ["Clan Wars", "Farming"]


def info_base():
    return {"level": 18, "members": 46, "league": "Cristallo I"}


def test_matches_filtra_per_nazione_lingua_e_municipio():
    row = {"country": "IT", "lang": "it", "min_th": 14}
    assert recruit.matches(row) is True
    assert recruit.matches(row, country="it") is True
    assert recruit.matches(row, country="ES") is False
    assert recruit.matches(row, lang="en") is False
    assert recruit.matches(row, min_th=15) is True
    assert recruit.matches(row, min_th=13) is False
    assert recruit.matches({"country": None, "lang": None, "min_th": None}, min_th=9) is True


def test_gli_eventi_del_blocco_sono_nel_registro_del_pacchetto_gia_esistente():
    assert recruit.PACK in events_registry.PACKS
    for event in recruit.EVENTS:
        entry = events_registry.EVENTS[event]
        assert entry["pack"] == recruit.PACK
        assert entry["default"] in entry["allowed"]
        assert set(entry["allowed"]) <= set(events_registry.DESTINATIONS)
    conf = settings_mod.effective({})
    assert settings_mod.route(conf, "recruit.application")[0] == "leaders_dm"
    assert settings_mod.route(conf, "recruit.reminder")[0] == "leaders_dm"


def test_i_tetti_sono_quelli_gia_in_casa():
    assert recruit.KEEP == retention.WAR_HISTORY_KEEP
    assert recruit.DECIDED_DAYS == retention.APPLICATION_DECIDED_DAYS == 30


def test_il_tetto_delle_etichette_e_uno_solo_e_viene_dall_api():
    assert util.API_LABELS == 3
    assert recruit.API_LABELS is util.API_LABELS
    assert render.API_LABELS is util.API_LABELS
    for modulo in (recruit, render):
        testo = pathlib.Path(modulo.__file__).read_text(encoding="utf-8")
        assert "LABELS_MAX" not in testo and "LABELS = 3" not in testo
    troppe = ["Clan Wars", "Farming", "Trophy Pushing", "Friendly Wars"]
    info = {"level": 18, "members": 46, "league": "Cristallo I", "country": "IT",
            "type": "open", "war_frequency": "always", "labels": troppe}
    conf = settings_mod.effective({"min_th": 14, "lang": "it"})
    riga = recruit.board_row(info, conf, False, "ab12cd")
    assert riga["labels"] == troppe[:util.API_LABELS]
    linea = render.labels_line(i18n.locale("it"), troppe)
    assert troppe[util.API_LABELS - 1] in linea and troppe[util.API_LABELS] not in linea
    tessera = board.tile(i18n.locale("it"), {"code": "ab12cd", "level": 18, "free": 4,
                                             "lang": "it", "labels": troppe}, "")
    assert not [una for una in troppe if una in tessera]
