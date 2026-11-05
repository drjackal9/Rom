import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import i18n, ics, integration_cards, integration_tools, media, render
from clashbot.db import Store
from clashbot.web.payload import slug_for

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
WAR = {"state": "inWar", "startTime": "20260914T100000.000Z", "endTime": "20260915T100000.000Z",
       "opponent": {"name": "Clan, Nemico"}}


class FakeVault:
    def blind(self, label, value):
        return f"{label}{value}0123456789abcdef".replace("-", "")


class FakeStore:
    recruit_code = Store.recruit_code

    def __init__(self, state=None, secrets=None):
        self.vault = FakeVault()
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.secrets = dict(secrets or {})
        self.kv = {"goldpass": {"end": "20260928T050000.000Z", "fetched": 0}}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def kv_get(self, key):
        return self.kv.get(key)

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag="#P1", user_id=user_id, name="Mario", dm=True)]

    async def bot_by_alias(self, alias):
        return None


class FakeMessage:
    def __init__(self):
        self.texts = []
        self.documents = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.texts.append(text)

    async def reply_document(self, document=None, filename=None, caption=None, reply_markup=None, **kw):
        self.documents.append((document.getvalue().decode(), filename, caption, reply_markup))


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.captions = []
        self.message = FakeMessage()
        self.message.chat = SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP)
        self.from_user = SimpleNamespace(id=7, language_code="it", first_name="Mario")

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_caption(self, caption=None, reply_markup=None):
        self.captions.append((caption, reply_markup))


def group_update(user_id=7, query=None):
    return SimpleNamespace(
        callback_query=query, effective_message=FakeMessage(),
        effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"))


def context_for(store, args=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=list(args or []), user_data={},
                           bot=SimpleNamespace(id=99, username="ClanBoardFuturoBot"))


def clan_store(settings=None, war=None):
    return FakeStore({(CLAN.alias, "settings"): settings or {"lang": "it", "tz": "Europe/Rome"},
                      (CLAN.alias, "members"): {"#P1": {"name": "Mario", "role": "leader"}},
                      (CLAN.alias, "war"): war})


def lines(text):
    return text.split("\r\n")


SLUG = slug_for(FakeVault(), CLAN.alias)
CODE = Store.recruit_code(SimpleNamespace(vault=FakeVault()), CLAN.alias)


def test_il_testo_e_rfc5545_con_righe_crlf_e_un_evento_per_finestra():
    body = ics.build(IT, SLUG, "Futuro", NOW, "20260928T050000.000Z", WAR)
    rows = lines(body)
    assert rows[0] == "BEGIN:VCALENDAR" and rows[-2] == "END:VCALENDAR" and rows[-1] == ""
    assert "VERSION:2.0" in rows and f"PRODID:{ics.PRODID}" in rows
    assert rows.count("BEGIN:VEVENT") == rows.count("END:VEVENT") >= 8
    assert "SUMMARY:Guerra contro Clan\\, Nemico" in rows
    assert "DTSTART:20260914T100000Z" in rows and "DTEND:20260915T100000Z" in rows
    assert "SUMMARY:Giochi del Clan" in rows and "SUMMARY:Iscrizione CWL" in rows
    assert "SUMMARY:Weekend della Capitale" in rows and "SUMMARY:Fine stagione" in rows


def test_ogni_evento_ha_un_uid_stabile_e_diverso_per_occorrenza():
    first = ics.build(IT, SLUG, "Futuro", NOW)
    again = ics.build(IT, SLUG, "Futuro", NOW + timedelta(minutes=5))
    uids = [row for row in lines(first) if row.startswith("UID:")]
    assert len(uids) == len(set(uids))
    assert [row for row in lines(again) if row.startswith("UID:")] == uids
    assert all(row.endswith(f"{SLUG}@clanboard") for row in uids)
    assert CLAN.alias not in first


def test_due_clan_non_si_mescolano_nello_stesso_calendario():
    mine = [row for row in lines(ics.build(IT, SLUG, "Futuro", NOW)) if row.startswith("UID:")]
    theirs = [row for row in lines(ics.build(IT, "altroslug0123456", "Altro", NOW))
              if row.startswith("UID:")]
    assert mine and theirs and not set(mine) & set(theirs)


def test_le_finestre_coprono_l_orizzonte_e_restano_in_ordine():
    rows = ics.series(NOW, "20260928T050000.000Z")
    assert [key for key, _, _ in rows].count("games") >= 3
    assert rows == sorted(rows, key=lambda row: (row[1], row[0]))
    assert all(start < NOW + timedelta(days=ics.HORIZON_DAYS) for _, start, _ in rows)
    assert all(end > start for _, start, end in rows)
    assert len(ics.series(NOW, None, horizon=10)) < len(rows)


def test_la_guerra_entra_solo_quando_c_e_davvero():
    assert ics.war_entry(WAR)[1:3] == (datetime(2026, 9, 14, 10, tzinfo=timezone.utc),
                                       datetime(2026, 9, 15, 10, tzinfo=timezone.utc))
    assert ics.war_entry(None) is None
    assert ics.war_entry({"state": "warEnded", "startTime": "20260914T100000.000Z",
                          "endTime": "20260915T100000.000Z"}) is None
    assert ics.war_entry({"state": "inWar"}) is None


def test_escape_e_piegatura_non_rompono_gli_accenti():
    assert ics.escape("a;b,c\\d\ne") == "a\\;b\\,c\\\\d\\ne"
    folded = ics.fold("SUMMARY:" + "à" * 60)
    parts = folded.split("\r\n")
    assert len(parts) > 1 and all(len(part.encode()) <= 73 for part in parts)
    assert parts[1].startswith(" ")
    assert "".join([parts[0]] + [part[1:] for part in parts[1:]]) == "SUMMARY:" + "à" * 60
    assert ics.fold("SUMMARY:corta") == "SUMMARY:corta"


def test_il_comando_manda_il_file_con_la_didascalia_corta():
    store = clan_store(war=WAR)
    update = group_update()
    asyncio.run(integration_tools.cmd_calendar(update, context_for(store)))
    body, filename, caption, keyboard = update.effective_message.documents[0]
    assert filename == integration_tools.ICS_FILENAME and body.startswith("BEGIN:VCALENDAR")
    assert len(caption) <= 1024 and IT.t("ics.title") in caption
    assert keyboard is None
    assert IT.t("ics.public_off") in caption + (update.effective_message.texts or [""])[0]
    assert f"{CODE}@clanboard" in body and SLUG not in body


def test_il_link_pubblico_e_quello_del_sito_e_arriva_solo_con_l_interruttore_web():
    store = clan_store(settings={"lang": "it", "tz": "Europe/Rome",
                                 "web": {"page": True, "ics": True}})
    store.secrets["site_base"] = "https://clanboard.example/"
    update = group_update()
    asyncio.run(integration_tools.cmd_calendar(update, context_for(store)))
    caption = update.effective_message.documents[0][2]
    assert f"https://clanboard.example/c/{CODE}/calendar.ics" in caption
    assert SLUG not in caption
    assert "/ics/" not in caption


def test_senza_sito_la_card_rimanda_alle_impostazioni():
    store = clan_store(settings={"lang": "it", "tz": "Europe/Rome", "web": {"ics": True}})
    update = group_update()
    asyncio.run(integration_tools.cmd_calendar(update, context_for(store)))
    assert IT.t("ics.public_off") in update.effective_message.documents[0][2]


def test_non_resta_nessun_bottone_del_vecchio_feed():
    assert not hasattr(ics, "feed") and not hasattr(ics, "token")
    assert not hasattr(integration_cards, "calendar_keyboard")
    query = FakeQuery("int:ics:on")
    store = clan_store()
    asyncio.run(integration_tools.on_integration_callback(group_update(query=query),
                                                          context_for(store)))
    assert store.state[(CLAN.alias, "settings")].get("ics") is None
    assert query.captions == []


def carta_lunga():
    return render.card("📅", IT.t("ics.title"), "x" * (media.CAPTION_LIMIT * 2))


def test_una_traduzione_lunga_non_sfora_la_didascalia_del_file(monkeypatch):
    lunga = carta_lunga()
    monkeypatch.setattr(integration_cards, "calendar_card", lambda L, url=None: lunga)
    update = group_update()
    asyncio.run(integration_tools.cmd_calendar(update, context_for(clan_store(war=WAR))))
    caption = update.effective_message.documents[0][2]
    assert media.units(caption) <= media.CAPTION_LIMIT
    assert caption + "\n" + update.effective_message.texts[0] == lunga


def test_il_comando_del_calendario_e_registrato_con_le_sue_chiavi():
    assert ("calendar", ["calendario"]) in integration_tools.COMMANDS
    for key in ("cmd.calendar", "ics.title", "ics.body", "ics.name", "ics.war", "ics.link",
                "ics.public_off", "int.only"):
        assert key in EN, key
    for gone in ("ics.public_on", "ics.btn_on", "ics.btn_off", "web.ics.war"):
        assert gone not in EN, gone
