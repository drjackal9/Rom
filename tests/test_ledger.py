import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import ledger, retention

NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
ALIAS = "clan-1"


class FakeStore:
    def __init__(self, state=None, links=None):
        self.state = dict(state or {})
        self.log = []
        self.links = dict(links or {})

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def add_log(self, alias, entry, at=None):
        self.log.append((alias, entry, at))

    async def recent_log(self, alias, limit=20):
        return [entry for a, entry, _ in reversed(self.log) if a == alias][:limit]

    async def links_by_user(self, user_id):
        return list(self.links.get(user_id) or [])


def test_note_scritta_letta_e_cancellata():
    store = FakeStore()
    note = asyncio.run(ledger.note_set(store, ALIAS, "#P4", "Toad", "  dorme  ", 7, "Mario", NOW))
    assert note["text"] == "dorme" and note["by"] == 7 and note["by_name"] == "Mario"
    assert asyncio.run(ledger.note_get(store, ALIAS, "#P4"))["text"] == "dorme"
    assert asyncio.run(ledger.note_del(store, ALIAS, "#P4")) is True
    assert asyncio.run(ledger.note_del(store, ALIAS, "#P4")) is False


def test_note_vuota_non_si_salva_e_quella_lunga_si_taglia():
    store = FakeStore()
    assert asyncio.run(ledger.note_set(store, ALIAS, "#P4", "Toad", "   ", 7, "Mario", NOW)) is None
    long = asyncio.run(ledger.note_set(store, ALIAS, "#P4", "Toad", "x" * 2000, 7, "Mario", NOW))
    assert len(long["text"]) == 400


def test_prune_note_segna_chi_esce_e_cancella_dopo_novanta_giorni():
    old = NOW.timestamp() - (retention.INACTIVE_CLAN_DAYS + 1) * 86400
    store = FakeStore({(ALIAS, "notes"): {
        "#P1": {"text": "ok", "gone": None},
        "#P2": {"text": "uscito ora", "gone": None},
        "#P3": {"text": "uscito da un pezzo", "gone": old},
        "#P4": {"text": "rientrato", "gone": old},
    }})
    dropped = asyncio.run(ledger.prune_notes(store, ALIAS, {"#P1": {}, "#P4": {}}, NOW))
    notes = store.state[(ALIAS, "notes")]
    assert dropped == 1 and "#P3" not in notes
    assert notes["#P2"]["gone"] == NOW.timestamp()
    assert notes["#P1"]["gone"] is None and notes["#P4"]["gone"] is None


def test_registro_accetta_solo_azioni_note_e_non_scrive_altro():
    store = FakeStore()
    assert asyncio.run(ledger.record(store, ALIAS, "note", 7, "Mario", "Toad", NOW)) is True
    assert asyncio.run(ledger.record(store, ALIAS, "qualunque", 7)) is False
    assert store.log == [(ALIAS, {"action": "note", "by": 7, "by_name": "Mario", "detail": "Toad"}, NOW)]
    assert asyncio.run(ledger.history(store, ALIAS))[0]["action"] == "note"


def test_nel_registro_chi_ha_un_villaggio_collegato_si_vede_col_nome_del_gioco():
    store = FakeStore(links={7: [SimpleNamespace(tag="#P1", user_id=7, name="Mario")]})
    asyncio.run(ledger.record(store, ALIAS, "export", 7, "Mariuccio", "wars", NOW))
    asyncio.run(ledger.acted(store, ALIAS, "target", "7", 9, "Tizio", now=NOW))
    righe = asyncio.run(ledger.history(store, ALIAS))
    assert [row["by_name"] for row in righe] == ["Tizio", "Mario"]
