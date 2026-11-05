import asyncio
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import (guard, handlers, i18n, leader_cards, leader_jobs, leader_tools, leaders,
                      ledger, render, retention)
from clashbot.poller import Tick

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")


class FakeStore:
    def __init__(self, role="leader"):
        self.state = {(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"},
                      (CLAN.alias, "members"): {"#PY2": {"name": "Mario", "role": role},
                                                "#PY9": {"name": "Toad", "role": "member"}}}
        self.log = []
        self.kv = {}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag="#PY2", user_id=user_id, name="Mario", dm=True, lang=None)]

    async def links_for_players(self, tags):
        link = SimpleNamespace(tag="#PY2", user_id=7, name="Mario", dm=True, lang=None)
        return {link.tag: link} if link.tag in set(tags or ()) else {}

    async def add_log(self, alias, entry, at=None):
        self.log.append({**entry, "at": at or NOW})

    async def recent_log(self, alias, limit=20):
        return list(reversed(self.log))[:limit]

    async def bot_by_alias(self, alias):
        return None

    async def get_secret(self, kind):
        return None


class LinkStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.state = {}
        self.added = []

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

    async def count_clans(self, bot_alias):
        return 0

    async def bot_for_tag(self, tag):
        return None

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag="#PY2", user_id=user_id, name="Mario", dm=True, lang=None, verified=True)]

    async def add_clan(self, chat_id, tag, name, user_id, bot_alias):
        self.added.append((chat_id, tag, name, user_id, bot_alias))
        return CLAN


class LinkCoc:
    async def clan(self, tag):
        return {"tag": tag, "name": CLAN.name, "memberList": [{"tag": "#PY2", "name": "Mario", "role": "leader"}],
                "location": {"countryCode": "IT"}}, None


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)
        return SimpleNamespace(message_id=1)


def update_for(user_id=7):
    return SimpleNamespace(callback_query=None, effective_message=FakeMessage(),
                           effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
                           effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"))


def context_for(store, args=None, coc=None):
    return SimpleNamespace(bot_data={"store": store, "coc": coc, "bot_alias": "bot-1"},
                           args=list(args or []), user_data={},
                           bot=SimpleNamespace(username="ClanBoardFuturoBot"))


def test_nota_scritta_riletta_e_cancellata():
    store = FakeStore()
    update = update_for()
    asyncio.run(leader_tools.cmd_note(update, context_for(store, ["#PY9", "dorme", "sempre"])))
    assert asyncio.run(ledger.note_get(store, CLAN.alias, "#PY9"))["text"] == "dorme sempre"
    letta = update_for()
    asyncio.run(leader_tools.cmd_note(letta, context_for(store, ["#PY9"])))
    assert "dorme sempre" in letta.effective_message.sent[0]
    tolta = update_for()
    asyncio.run(leader_tools.cmd_note(tolta, context_for(store, ["#PY9", "-"])))
    assert asyncio.run(ledger.note_get(store, CLAN.alias, "#PY9")) is None


def test_senza_argomenti_arriva_l_elenco_delle_note():
    store = FakeStore()
    asyncio.run(leader_tools.cmd_note(update_for(), context_for(store, ["#PY9", "dorme"])))
    elenco = update_for()
    asyncio.run(leader_tools.cmd_note(elenco, context_for(store)))
    text = elenco.effective_message.sent[0]
    assert "Toad" in text and "dorme" in text and IT.t("leaders.note.usage") in text


def test_la_nota_a_un_estraneo_non_si_scrive():
    store = FakeStore()
    update = update_for()
    asyncio.run(leader_tools.cmd_note(update, context_for(store, ["#CU2V", "ciao"])))
    assert update.effective_message.sent[0] == IT.t("leaders.note.unknown")
    assert asyncio.run(ledger.notes_all(store, CLAN.alias)) == {}


def test_nel_registro_finisce_il_nome_del_membro_mai_il_testo_della_nota():
    store = FakeStore()
    asyncio.run(leader_tools.cmd_note(update_for(), context_for(store, ["#PY9", "segreto"])))
    assert store.log[-1]["action"] == "note" and store.log[-1]["detail"] == "Toad"
    assert all("segreto" not in str(value) for value in store.log[-1].values())


def test_un_anziano_non_vede_ne_scrive_le_note():
    store = FakeStore(role="admin")
    update = update_for()
    asyncio.run(leader_tools.cmd_note(update, context_for(store, ["#PY9", "niente"])))
    assert IT.t("leaders.only") in update.effective_message.sent[0]
    assert asyncio.run(ledger.notes_all(store, CLAN.alias)) == {}


def test_il_registro_mostra_le_ultime_azioni():
    store = FakeStore()
    asyncio.run(ledger.record(store, CLAN.alias, "export", 7, "Mario", "wars", NOW))
    update = update_for()
    asyncio.run(leader_tools.cmd_log(update, context_for(store)))
    text = update.effective_message.sent[0]
    assert IT.t("leaders.log.title") in text and IT.t("leaders.log.action.export") in text


def test_il_registro_vuoto_lo_dice():
    store = FakeStore()
    update = update_for()
    asyncio.run(leader_tools.cmd_log(update, context_for(store)))
    assert IT.t("leaders.log.none") in update.effective_message.sent[0]


def test_il_collegamento_del_clan_finisce_nel_registro():
    store = LinkStore()
    update = update_for()
    asyncio.run(handlers.link_clan(update, context_for(store, coc=LinkCoc()),
                                   update.effective_chat, CLAN.tag, 7))
    assert store.log[-1]["action"] == "link" and store.log[-1]["detail"] == CLAN.name


def test_le_note_degli_ex_membri_si_potano_da_sole():
    store = FakeStore()
    old = NOW.timestamp() - (retention.INACTIVE_CLAN_DAYS + 1) * 86400
    asyncio.run(store.set_state(CLAN.alias, "notes", {
        "#PY9": {"name": "Toad", "text": "resta", "gone": None},
        "#GQ8": {"name": "Via", "text": "andato", "gone": old},
    }))
    t = Tick(CLAN, NOW)
    t.members = asyncio.run(store.get_state(CLAN.alias, "members"))
    asyncio.run(leader_jobs.run(SimpleNamespace(store=store), t))
    notes = asyncio.run(ledger.notes_all(store, CLAN.alias))
    assert "#GQ8" not in notes and notes["#PY9"]["gone"] is None


def test_l_elenco_di_un_clan_pieno_resta_un_messaggio_valido():
    rows = [(f"#PY{i:02d}", {"name": f"Membro{i:02d}", "text": "x" * leaders.NOTE_MAX})
            for i in range(50)]
    text = leader_cards.notes_card(IT, rows)
    assert len(text) <= render.MAX_LEN
    assert text.count("<blockquote>") == text.count("</blockquote>") == 1
    assert text.endswith("</code>") and IT.t("leaders.note.usage") in text
    body = text.split("<blockquote>")[1].split("</blockquote>")[0]
    intere = [IT.t("leaders.note.row", name=note["name"], text=note["text"]) for _, note in rows]
    assert body.split("\n")[0] == intere[0]
    assert all(line in intere or line == leader_cards.CUT for line in body.split("\n"))


def test_l_elenco_che_ci_sta_tutto_non_perde_nessuna_nota():
    rows = [(f"#PY{i:02d}", {"name": f"Membro{i:02d}", "text": "dorme"}) for i in range(5)]
    text = leader_cards.notes_card(IT, rows)
    body = text.split("<blockquote>")[1].split("</blockquote>")[0]
    assert leader_cards.CUT not in body and len(body.split("\n")) == len(rows)


def test_le_chiavi_nuove_esistono():
    keys = ["leaders.note.title", "leaders.note.usage", "leaders.note.saved", "leaders.note.removed",
            "leaders.note.none", "leaders.note.row", "leaders.note.by", "leaders.note.unknown",
            "leaders.log.title", "leaders.log.none", "leaders.log.row", "cmd.note", "cmd.log"]
    keys += [f"leaders.log.action.{action}" for action in ledger.ACTIONS]
    for key in keys:
        assert key in EN, key


def test_il_gestore_sospeso_non_cancella_piu_le_note():
    store = FakeStore()
    asyncio.run(leader_tools.cmd_note(update_for(), context_for(store, ["#PY9", "dorme"])))
    store.kv[guard.suspended_key(CLAN.alias, 7)] = {"at": 0}
    fermo = update_for()
    asyncio.run(leader_tools.cmd_note(fermo, context_for(store, ["#PY9", "-"])))
    assert fermo.effective_message.sent == [IT.t("h.suspended")]
    assert asyncio.run(ledger.note_get(store, CLAN.alias, "#PY9"))["text"] == "dorme"


def test_alla_quinta_nota_cancellata_nell_ora_il_posto_si_sospende():
    store = FakeStore(role="coLeader")
    for numero in range(5):
        asyncio.run(leader_tools.cmd_note(update_for(), context_for(store, ["#PY9", f"nota {numero}"])))
        tolta = update_for()
        asyncio.run(leader_tools.cmd_note(tolta, context_for(store, ["#PY9", "-"])))
    assert tolta.effective_message.sent == [IT.t("h.suspend_notice")]
    assert asyncio.run(guard.suspended(store, CLAN.alias, 7))
