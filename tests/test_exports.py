import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import (exports, i18n, leader_cards, leader_jobs, leader_tools, ledger, render,
                      retention, warstats)
from clashbot import settings as settings_mod

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
MONTH = (warstats.month_start("2026-09", "Europe/Rome"), warstats.month_end("2026-09", "Europe/Rome"))
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
ROME = {"lang": "it", "tz": "Europe/Rome"}
RECORDS = [
    {"kind": "war", "day": None, "endTime": "20260928T100000.000Z", "opponent": "Clan Nemico",
     "result": "win", "stars": 28, "destr": 91.5, "opp_stars": 20, "opp_destr": 80.0,
     "teamSize": 15, "attacksPerMember": 2,
     "members": [{"tag": "#P2", "name": "Luigi", "attacks": [{"stars": 3, "destr": 100}], "missed": 1}]},
    {"kind": "cwl", "day": 3, "endTime": "20260920T100000.000Z", "opponent": "Altro Clan",
     "result": "lose", "stars": 10, "destr": 50.0, "opp_stars": 12, "opp_destr": 60.0,
     "teamSize": 15, "attacksPerMember": 1, "members": []},
]
MEMBERS = {"#P2": {"name": "Luigi", "role": "member", "th": 15, "trophies": 5100,
                   "donations": 800, "received": 900}}
STATS = {"#P2": {"name": "Luigi", "wars": 2, "attacks": 3, "stars": 7, "triples": 1, "missed": 1}}
SEASON = {"members": {"#P2": {"name": "Luigi", "wars": 2, "attacks": 3, "stars": 7, "triples": 1,
                              "missed": 1, "raid_attacks": 6, "loot": 100000, "donations": 800}}}
ACTIVITY = [{"tag": "#P2", "name": "Luigi", "score": 21}]
PROGRESS = {"#P2": {"name": "Luigi", "now": {"wins": 21}, "month": {"since": 0}}}


def rows_of(payload):
    return [line.split(",") for line in payload.decode("utf-8-sig").strip().split("\n")]


def test_csv_guerre_una_riga_per_guerra_con_intestazione():
    rows = rows_of(exports.wars_csv(RECORDS))
    assert tuple(rows[0]) == exports.WARS_HEADER
    assert len(rows) == 3 and rows[1][3] == "Clan Nemico" and rows[1][4] == "win"


def test_csv_membri_unisce_anagrafica_guerre_punti_e_attivita():
    rows = rows_of(exports.members_csv(MEMBERS, STATS, SEASON, ACTIVITY))
    assert tuple(rows[0]) == exports.MEMBERS_HEADER
    assert rows[1][0] == "#P2" and rows[1][7] == "2" and rows[1][11] == "1"
    assert rows[1][13] == "21"


def test_il_csv_non_contiene_identificativi_telegram():
    payload = exports.members_csv(MEMBERS, STATS, SEASON, ACTIVITY).decode("utf-8-sig")
    assert "user_id" not in payload and "telegram" not in payload.lower()


def test_il_csv_vuoto_ha_solo_l_intestazione():
    assert exports.wars_csv([]).count(b"\n") == 1
    assert exports.members_csv({}, {}, {}, []).count(b"\n") == 1


def test_month_data_conta_guerre_saltati_e_arrivi_del_mese():
    players = {"joined": {"#P2": {"ts": (NOW - timedelta(days=20)).timestamp(), "told": True}}}
    data = exports.month_data(RECORDS, MEMBERS, ACTIVITY, players, *MONTH)
    assert data["wars"] == 2 and data["wins"] == 1 and data["losses"] == 1
    assert data["missed"] == [("Luigi", 1)] and data["arrivals"] == ["Luigi"]


def test_fuori_dal_mese_chiuso_non_contano_ne_guerre_ne_arrivi():
    players = {"joined": {"#P2": {"ts": (NOW - timedelta(hours=6)).timestamp(), "told": True}}}
    data = exports.month_data(RECORDS, MEMBERS, ACTIVITY, players, *MONTH)
    assert data["arrivals"] == []
    august = (warstats.month_start("2026-08", "Europe/Rome"),
              warstats.month_end("2026-08", "Europe/Rome"))
    old = exports.month_data(RECORDS, MEMBERS, ACTIVITY, {"joined": {}}, *august)
    assert old["wars"] == 0 and old["stars"] == 0 and old["missed"] == []


def test_la_scheda_mensile_non_ripete_titoli_e_classifica():
    data = exports.month_data(RECORDS, MEMBERS, ACTIVITY, {"joined": {}}, *MONTH)
    text = leader_cards.month_card(IT, "Futuro", data)
    assert IT.t("leaders.month.title") in text and IT.t("leaders.month.tail") in text
    assert IT.t("season_end.title") not in text and IT.t("season_end.podium") not in text


def test_la_scheda_mensile_dice_i_numeri_del_mese():
    data = exports.month_data(RECORDS, MEMBERS, ACTIVITY, {"joined": {}}, *MONTH)
    text = leader_cards.month_card(IT, "Futuro", data)
    assert IT.t("leaders.month.wars", wars=2, wins=1, losses=1, ties=0, stars=38) in text
    assert IT.t("report.missed_row", name="Luigi", n=1) in text
    assert IT.t("leaders.month.grown_row", name="Luigi", score=21) in text


def test_i_saltati_del_mese_hanno_lo_stesso_tetto_del_settimanale():
    missed = [(f"Giocatore {i:02d}", 2) for i in range(render.REPORT_MISSED + 4)]
    record = {"kind": "war", "result": "win", "stars": 0, "endTime": "20260928T100000.000Z",
              "members": [{"tag": f"#Q{i}", "name": name, "missed": n}
                          for i, (name, n) in enumerate(missed)]}
    data = exports.month_data([record], MEMBERS, [], {"joined": {}}, *MONTH)
    month = leader_cards.month_card(IT, CLAN.name, data)
    week = render.leader_report(IT, CLAN, missed, [], [])
    assert len(data["missed"]) == render.REPORT_MISSED
    assert sum(name in month for name, _ in missed) == sum(name in week for name, _ in missed)


class FakeMessage:
    def __init__(self):
        self.chat_id = CLAN.chat_id
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


class FakeBot:
    def __init__(self):
        self.username = "ClanBoardFuturoBot"
        self.documents = []

    async def send_document(self, chat_id, document, filename=None, caption=None, **kw):
        self.documents.append({"chat_id": chat_id, "document": document, "filename": filename,
                               "caption": caption})


class FakeStore:
    def __init__(self, role="leader", wars=RECORDS):
        self.state = {(CLAN.alias, "settings"): dict(ROME),
                      (CLAN.alias, "members"): copy.deepcopy(MEMBERS) | {
                          "#PY2": {"name": "Mario", "role": role}},
                      (CLAN.alias, "season"): copy.deepcopy(SEASON),
                      (CLAN.alias, "progress"): copy.deepcopy(PROGRESS)}
        self.wars = copy.deepcopy(list(wars))
        self.asked = []
        self.log = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag="#PY2", user_id=user_id, name="Mario", dm=True)]

    async def recent_wars(self, alias, limit=10):
        self.asked.append(limit)
        return copy.deepcopy(self.wars[:limit])

    async def wars_since(self, alias, since):
        self.asked.append(since)
        return copy.deepcopy(self.wars)

    async def add_log(self, alias, entry, at=None):
        self.log.append({**entry, "at": at or NOW})

    async def recent_log(self, alias, limit=20):
        return list(reversed(self.log))[:limit]

    async def bot_by_alias(self, alias):
        return None

    async def kv_get(self, key):
        return None

    async def get_secret(self, kind):
        return None


def update_for(query=None, user_id=7):
    message = query.message if query else FakeMessage()
    return SimpleNamespace(callback_query=query, effective_message=message,
                           effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
                           effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                          first_name="Mario"))


def context_for(store, bot=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=[], user_data={}, bot=bot or FakeBot())


def buttons(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_export_offre_guerre_e_membri_a_bottoni():
    store = FakeStore()
    update = update_for()
    asyncio.run(leader_tools.cmd_export(update, context_for(store)))
    text, markup = update.effective_message.sent[0]
    assert IT.t("leaders.export.title") in text
    assert buttons(markup) == ["ex:wars", "ex:members"]


def test_un_anziano_non_esporta():
    store = FakeStore(role="admin")
    update = update_for()
    asyncio.run(leader_tools.cmd_export(update, context_for(store)))
    assert IT.t("leaders.only") in update.effective_message.sent[0][0]


def test_il_file_delle_guerre_arriva_come_documento_e_finisce_nel_registro():
    store = FakeStore()
    bot = FakeBot()
    query = FakeQuery("ex:wars")
    asyncio.run(leader_tools.on_export_callback(update_for(query), context_for(store, bot)))
    sent = bot.documents[0]
    assert sent["chat_id"] == CLAN.chat_id and sent["filename"].startswith("wars-")
    assert sent["filename"].endswith(".csv") and sent["caption"] == IT.t("leaders.export.caption")
    assert rows_of(sent["document"])[0] == list(exports.WARS_HEADER)
    assert store.asked[0] == retention.WAR_HISTORY_KEEP
    assert store.log[-1]["action"] == "export" and store.log[-1]["detail"] == "wars"


def test_il_file_dei_membri_porta_i_tag_di_gioco_mai_quelli_di_telegram():
    store = FakeStore()
    bot = FakeBot()
    query = FakeQuery("ex:members")
    asyncio.run(leader_tools.on_export_callback(update_for(query), context_for(store, bot)))
    payload = bot.documents[0]["document"].decode("utf-8-sig")
    cells = {cell for row in rows_of(bot.documents[0]["document"]) for cell in row}
    assert "#P2" in payload and "Luigi" in payload
    assert "7" not in cells and "user_id" not in payload


def test_senza_archivio_l_export_lo_dice_e_non_manda_file():
    store = FakeStore(wars=[])
    bot = FakeBot()
    query = FakeQuery("ex:wars")
    asyncio.run(leader_tools.on_export_callback(update_for(query), context_for(store, bot)))
    assert bot.documents == []
    assert query.message.sent[0][0] == IT.t("leaders.export.empty")
    assert store.log == []


class Poller:
    def __init__(self, store, activity=ACTIVITY):
        self.store = store
        self.activity = list(activity)
        self.dispatched = []
        self.closed = []

    async def month_activity(self, t):
        return copy.deepcopy(self.activity)

    async def closed_activity(self, t, period):
        self.closed.append(period)
        return copy.deepcopy(self.activity)

    async def dispatch(self, t, event, render_text):
        self.dispatched.append((event, render_text(t.L)))


def tick(now=NOW, members=None):
    t = SimpleNamespace(clan=CLAN, now=now, chunks=[], dm=[], events=[],
                        settings=settings_mod.effective(ROME, None),
                        members=copy.deepcopy(MEMBERS if members is None else members))
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    return t


def test_il_report_mensile_parte_il_primo_del_mese_e_una_volta_sola():
    store = FakeStore()
    poller = Poller(store)
    asyncio.run(leader_jobs.month_report(poller, tick()))
    assert [event for event, _ in poller.dispatched] == ["members.report"]
    assert IT.t("leaders.month.title") in poller.dispatched[0][1]
    poller.dispatched.clear()
    asyncio.run(leader_jobs.month_report(poller, tick()))
    assert poller.dispatched == []


def test_il_report_mensile_guarda_il_mese_appena_chiuso():
    store = FakeStore()
    poller = Poller(store)
    asyncio.run(leader_jobs.month_report(poller, tick()))
    assert store.asked[0] == MONTH[0] and poller.closed == ["month"]
    text = poller.dispatched[0][1]
    assert IT.t("leaders.month.wars", wars=2, wins=1, losses=1, ties=0, stars=38) in text
    assert IT.t("leaders.month.grown_row", name="Luigi", score=21) in text


def test_fuori_dal_primo_del_mese_il_report_tace():
    store = FakeStore()
    poller = Poller(store)
    asyncio.run(leader_jobs.month_report(poller, tick(now=NOW + timedelta(days=1))))
    assert poller.dispatched == [] and (CLAN.alias, "reports") not in store.state


def test_il_report_mensile_gira_nel_giro_dei_capi():
    store = FakeStore()
    poller = Poller(store)
    asyncio.run(leader_jobs.run(poller, tick()))
    assert "members.report" in [event for event, _ in poller.dispatched]


def test_le_chiavi_nuove_esistono():
    for key in ("leaders.export.title", "leaders.export.btn_wars", "leaders.export.btn_members",
                "leaders.export.caption", "leaders.export.empty", "leaders.month.title",
                "leaders.month.wars", "leaders.month.missed", "leaders.month.arrivals",
                "leaders.month.grown", "leaders.month.grown_row", "leaders.month.tail", "cmd.export"):
        assert key in EN, key


def test_le_chiavi_nuove_sono_scritte_in_italiano_e_in_inglese():
    italian = json.load(open(i18n.LOCALE_DIR / "it.json", encoding="utf-8"))
    for key in ("leaders.export.title", "leaders.export.btn_wars", "leaders.export.btn_members",
                "leaders.export.caption", "leaders.export.empty", "leaders.month.title",
                "leaders.month.wars", "leaders.month.missed", "leaders.month.arrivals",
                "leaders.month.grown", "leaders.month.tail", "cmd.export"):
        assert italian[key] and EN[key] and italian[key] != EN[key], key


def test_l_export_riusa_l_azione_gia_prevista_dal_registro():
    assert "export" in ledger.ACTIONS
    assert "leaders.log.action.export" in EN
