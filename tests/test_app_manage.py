from clashbot import acts, boards, settings
from clashbot.web import app_manage, payload

REFS = {7: "7a1b2c3d4e5f60718293a4b5c6d7e8f9", 8: "8f1c2d3e4a5b6c7d8e9f0a1b2c3d4e5f",
        9: "9b0c1d2e3f405162738495a6b7c8d9e0"}
MARKS = {9: "9a0b1c2d3e4f5061", 7: "7a0b1c2d3e4f5061"}
PENDING = {"who": MARKS[9], "name": "Toad", "tag": "#P9"}
APPROVED = {"who": MARKS[7], "name": "Mario", "trusted": False}
REPORT = {"code": "abc123", "reason": "scam", "at": 1789000000.0}
CHANNEL = {"id": "UCaaaaaaaaaaaaaaaaaaaaaa", "title": "Canale"}
MANAGE_STAFF = {"paused": False, "undo": True, "pending": [PENDING], "approved": [APPROVED],
                "reports": [REPORT],
                "delegates": [{"who": REFS[8], "name": "Luigi"}],
                "people": [{"who": REFS[7], "name": "Mario"}],
                "suspended": [{"who": REFS[9], "name": "Peach"}],
                "log": [{"what": "pausa", "who": "Mario", "at": 1, "of": None, "ref": None}]}
BLOCKED = {"id": "3", "name": "Spam"}
DERBY_SCREEN = {"text": "DERBY", "buttons": [[{"label": "Stelle", "data": "dy:metric:stars"}]]}
TOURNEY_SCREEN = {"text": "TORNEO", "buttons": [[{"label": "Apri", "data": "tr:go"}]]}
MANAGE_TOOLS = {
    "wars": {"proposals": [{"tag": "#P2", "name": "Luigi", "missed": 2}],
             "warnings": [{"id": "w1", "name": "Peach", "missed": 1, "at": 1}]},
    "recruitment": {"min_th": 14,
                    "applications": [{"id": "1", "name": "Nuovo", "th": 15, "goals": ["war"]}],
                    "blocked": [BLOCKED]},
    "leaders": {"gate": True, "texts": {"welcome": "Ciao", "rules": "Regole"},
                "scheduled": [{"id": "1", "hhmm": "20:30", "days": [], "text": "Ci siamo"}],
                "notes": [{"tag": "#P1", "name": "Mario", "text": "segreto"}],
                "channels": [CHANNEL]},
    "family": {"name": "Famiglia", "code": "fam1", "owner": 777,
               "derby": DERBY_SCREEN, "tourney": TOURNEY_SCREEN},
    "integrations": {"twitch": "canale", "discord": True, "ics": False},
}
PAGE = {payload.MANAGE: {"777": {"settings": None, acts.STAFF: MANAGE_STAFF}},
        "sections": {"wars": [], "members": []},
        "recruit": {"open": True, "free": 4, "requirement": 14, "page_on": True, "code": "abc123"}}
SEAT = {"uid": 777, "tag": "#P1", "level": settings.MANAGER}
NOBODY = {"uid": 5, "tag": "#P8", "level": None}


def test_la_casella_porta_solo_quello_che_aspetta_una_decisione():
    found = app_manage.inbox_for(PAGE, SEAT, MANAGE_TOOLS)
    assert found["pending"] == [PENDING] and "claims" not in found
    assert [row["id"] for row in found["applications"]] == ["1"]
    assert found["applications"][0]["th"] == 15 and found["applications"][0]["goals"] == ["war"]
    assert found["reports"] == [REPORT]
    assert found["warnings"] == [{"tag": "#P2", "name": "Luigi", "missed": 2}]


def test_la_casella_resta_vuota_per_chi_non_gestisce():
    assert app_manage.inbox_for(PAGE, NOBODY) == {"pending": [], "applications": [],
                                                  "reports": [], "warnings": [], "bases": []}


def test_la_casella_non_porta_le_note_ne_chi_ha_segnalato():
    found = app_manage.inbox_for(PAGE, SEAT, MANAGE_TOOLS)
    assert "segreto" not in str(found)
    assert all("by" not in row for row in found["reports"])
    assert all("user_id" not in row and "tag" not in row for row in found["applications"])


def test_lo_stato_del_gestore_riunisce_pacchetti_orari_testi_e_canali():
    found = app_manage.manage_view(PAGE, SEAT, MANAGE_TOOLS)
    assert found["packs"] == {pack: pack in PAGE["sections"] for pack in boards.SECTION_ORDER}
    assert set(found["packs"]) == set(boards.SECTION_ORDER)
    assert found["schedules"] == MANAGE_TOOLS["leaders"]["scheduled"]
    assert found["texts"] == {"welcome": "Ciao", "rules": "Regole"}
    assert found["channels"] == [CHANNEL]
    assert found["page_on"] is True and found["paused"] is False and found["chief"] is True
    assert found["delegates"] == MANAGE_STAFF["delegates"]
    assert found["people"] == MANAGE_STAFF["people"]
    assert found["suspended"] == MANAGE_STAFF["suspended"]
    assert found["log"] == MANAGE_STAFF["log"]
    assert found["approved"] == [APPROVED]
    assert "segreto" not in str(found)


def test_lo_stato_del_gestore_resta_spento_per_chi_non_gestisce():
    found = app_manage.manage_view(PAGE, NOBODY)
    assert found["chief"] is False and found["paused"] is False
    assert found["delegates"] == [] and found["people"] == [] and found["suspended"] == []
    assert found["approved"] == []
    assert found["log"] == [] and found["schedules"] == [] and found["channels"] == []
    assert found["texts"] == {}


BASE_LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16%3AHV%3AAaBbCcDd"
BASE_PROPOSAL = {"id": "ab12", "name": "Mario", "label": "war", "village": "home", "hall": 16,
                 "link": BASE_LINK}


def test_la_casella_porta_le_basi_proposte_col_loro_link():
    tools = dict(MANAGE_TOOLS,
                 leaders=dict(MANAGE_TOOLS["leaders"], bases=[dict(BASE_PROPOSAL, by=777)]))
    found = app_manage.inbox_for(PAGE, SEAT, tools)
    assert found["bases"] == [BASE_PROPOSAL]
    assert "777" not in str(found["bases"])


def test_lo_stato_del_gestore_porta_recluta_famiglia_e_integrazioni():
    found = app_manage.manage_view(PAGE, SEAT, MANAGE_TOOLS)
    assert found["recruit"] == {"th": 14, "blocked": [BLOCKED]}
    assert found["family"] == {"name": "Famiglia", "code": "fam1",
                               "derby": DERBY_SCREEN, "tourney": TOURNEY_SCREEN}
    assert found["integrations"] == {"twitch": "canale", "discord": True, "ics": False}
    assert "owner" not in found["family"] and "777" not in str(found["family"])


def test_recluta_famiglia_e_integrazioni_restano_spente_per_chi_non_gestisce():
    found = app_manage.manage_view(PAGE, NOBODY)
    assert found["recruit"] is None
    assert found["family"] is None
    assert found["integrations"] is None


def test_la_famiglia_senza_codice_arriva_lo_stesso_col_suo_posto():
    tools = dict(MANAGE_TOOLS, family={"name": None, "code": None, "derby": None,
                                       "tourney": TOURNEY_SCREEN})
    found = app_manage.manage_view(PAGE, SEAT, tools)["family"]
    assert found["code"] is None and found["derby"] is None
    assert found["tourney"] == TOURNEY_SCREEN
