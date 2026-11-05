import asyncio
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telegram.constants import ChatType

from clashbot import handlers, i18n, leader_cards, leader_jobs, leader_tools, leaders, render, verify
from clashbot import settings as settings_mod
from clashbot.poller import Tick

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 8, 5, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1",
                       active=True)
LEADER = 7
MEMBER = 9
MEMBERS = {"#P1": {"name": "Mario", "role": "leader"}, "#P9": {"name": "Toad", "role": "member"}}
ROME = {"lang": "it", "tz": "Europe/Rome"}


class FakeStore:
    def __init__(self, settings=None):
        self.state = {(CLAN.alias, "settings"): copy.deepcopy(settings or ROME),
                      (CLAN.alias, "members"): copy.deepcopy(MEMBERS)}
        self.links = [SimpleNamespace(tag="#P1", user_id=LEADER, name="Mario", dm=True, lang="it"),
                      SimpleNamespace(tag="#P9", user_id=MEMBER, name="Toad", dm=True, lang="it")]
        self.kv = {}
        self.secrets = {}
        self.log = []
        self.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def active_clans(self, bot_alias=None):
        return [CLAN]

    async def links_by_user(self, user_id):
        return [link for link in self.links if link.user_id == user_id]

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def bot_by_alias(self, alias):
        return None

    async def add_log(self, alias, entry, at=None):
        self.log.append(entry)

    def saved(self):
        return self.state[(CLAN.alias, "settings")]


class FakeMessage:
    def __init__(self, text=None):
        self.text = text
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


def group_update(user_id=LEADER):
    return SimpleNamespace(callback_query=None, effective_message=FakeMessage(),
                           effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
                           effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                          first_name="Mario"))


def private_update(user_id=LEADER, text=None):
    return SimpleNamespace(callback_query=None, effective_message=FakeMessage(text),
                           effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
                           effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                          first_name="Mario"))


def press(context, data, user_id=LEADER):
    query = FakeQuery(data)
    update = SimpleNamespace(callback_query=query, effective_message=query.message,
                             effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
                             effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                            first_name="Mario"))
    asyncio.run(leader_tools.on_leader_callback(update, context))
    return query


def context_for(store, args=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=list(args or []), user_data={},
                           bot=SimpleNamespace(username="ClanBoardFuturoBot"))


def datas_of(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def labels_of(keyboard):
    return [button.text for row in keyboard.inline_keyboard for button in row]


def test_rules_le_scrive_solo_chi_comanda_e_le_legge_chiunque():
    store = FakeStore()
    update = group_update()
    asyncio.run(leader_tools.cmd_rules(update, context_for(store, ["niente", "spam"])))
    assert leaders.texts(store.saved())["rules"] == "niente spam"
    assert store.log[-1] == {"action": "rules", "by": LEADER, "by_name": "Mario", "detail": None}
    reader = group_update(MEMBER)
    asyncio.run(leader_tools.cmd_rules(reader, context_for(store)))
    assert "niente spam" in reader.effective_message.sent[0][0]


def test_un_membro_semplice_non_cambia_le_regole():
    store = FakeStore()
    update = group_update(MEMBER)
    asyncio.run(leader_tools.cmd_rules(update, context_for(store, ["mie", "regole"])))
    assert leaders.texts(store.saved())["rules"] == ""
    assert update.effective_message.sent[0][0] == IT.t("leaders.only")
    assert store.log == []


def test_senza_clan_il_comando_dice_come_collegarsi():
    store = FakeStore()
    update = private_update(user_id=42)
    asyncio.run(leader_tools.cmd_welcome(update, context_for(store)))
    assert update.effective_message.sent[0][0] == render.not_linked_view(IT)


def test_benvenuto_sostituisce_i_segnaposti_e_scappa_il_testo():
    text = leader_cards.welcome_card(IT, "Ciao {name}, benvenuto in {clan} <3", "Mar<io>", "Fu&turo")
    assert "Mar&lt;io&gt;" in text and "Fu&amp;turo" in text and "&lt;3" in text
    assert len(text) <= render.MAX_LEN
    preview = leader_cards.welcome_preview(IT, "")
    assert IT.t("leaders.welcome.none") in preview and "{name}" in preview


def test_il_benvenuto_scritto_dal_capo_si_salva_e_le_regole_restano():
    store = FakeStore({"lang": "it", "tz": "Europe/Rome", "texts": {"rules": "niente spam"}})
    update = group_update()
    asyncio.run(leader_tools.cmd_welcome(update, context_for(store, ["Ciao", "{name}!"])))
    assert leaders.texts(store.saved()) == {"rules": "niente spam", "welcome": "Ciao {name}!"}
    assert update.effective_message.sent[0][0] == IT.t("leaders.welcome.saved")


def test_sanitize_rifiuta_col_motivo_solo_quando_sa_chi_siamo():
    assert leaders.sanitize("ciao", leaders.TEXT_MAX, "ClanBoardFuturoBot", "clanboard.cloud") == "ciao"
    with pytest.raises(ValueError) as rejected:
        leaders.sanitize("scrivi a @AltroBot", leaders.TEXT_MAX, "ClanBoardFuturoBot", None)
    assert str(rejected.value) == "bot"
    with pytest.raises(ValueError) as linked:
        leaders.sanitize("vai su https://evil.example", leaders.TEXT_MAX, "ClanBoardFuturoBot", None)
    assert str(linked.value) == "link"
    assert leaders.sanitize("scrivi a @AltroBot", leaders.TEXT_MAX) == "scrivi a @AltroBot"


def test_il_benvenuto_con_un_link_di_fuori_torna_al_capo_e_non_si_salva():
    store = FakeStore()
    update = group_update()
    asyncio.run(leader_tools.cmd_welcome(update, context_for(store, ["Ciao", "https://evil.example"])))
    assert leaders.texts(store.saved())["welcome"] == ""
    assert update.effective_message.sent[0][0] == IT.t("texts.reject.link")
    assert store.log == []


def test_le_regole_col_numero_di_telefono_tornano_al_capo():
    store = FakeStore()
    update = group_update()
    asyncio.run(leader_tools.cmd_rules(update, context_for(store, ["chiamami", "333", "123", "4567"])))
    assert leaders.texts(store.saved())["rules"] == ""
    assert update.effective_message.sent[0][0] == IT.t("texts.reject.phone")
    assert store.log == []


def test_il_programmato_con_un_altro_bot_torna_al_capo_che_puo_riscriverlo():
    store = FakeStore()
    context = context_for(store)
    press(context, "lt:sch:add")
    press(context, "lt:sch:h:08")
    press(context, "lt:sch:m:08:30")
    press(context, "lt:sch:ok")
    typed = private_update(text="scrivi a @AltroBot")
    asyncio.run(handlers.on_private_text(typed, context))
    assert leaders.schedule(store.saved()) == []
    assert typed.effective_message.sent[0][0] == IT.t("texts.reject.bot")
    assert context.user_data.get("flow") is not None
    again = private_update(text="Buongiorno")
    asyncio.run(handlers.on_private_text(again, context))
    assert [entry["text"] for entry in leaders.schedule(store.saved())] == ["Buongiorno"]


def test_il_nostro_bot_e_il_nostro_sito_restano_scrivibili():
    store = FakeStore()
    store.secrets = {"site_base": "https://clanboard.cloud/"}
    update = group_update()
    asyncio.run(leader_tools.cmd_rules(update, context_for(store, ["tutto", "su",
                                                                  "https://clanboard.cloud/c/abc",
                                                                  "e", "@ClanBoardFuturoBot"])))
    assert leaders.texts(store.saved())["rules"] == ("tutto su https://clanboard.cloud/c/abc "
                                                     "e @ClanBoardFuturoBot")
    assert update.effective_message.sent[0][0] == IT.t("leaders.rules.saved")


def test_programmazione_aggiunta_letta_e_tolta():
    store = FakeStore()
    conf = settings_mod.effective(store.saved())
    entry = leaders.new_entry(leaders.schedule(conf), "08:30", [0, 2], "Buongiorno", LEADER)
    assert entry == {"id": "1", "hhmm": "08:30", "days": [0, 2], "text": "Buongiorno", "by": LEADER}
    card = leader_cards.schedule_card(IT, [entry])
    assert "08:30" in card and "Buongiorno" in card
    assert IT.t("leaders.schedule.none") in leader_cards.schedule_card(IT, [])
    assert datas_of(leader_cards.schedule_keyboard(IT, [entry])) == ["lt:sch:del:1", "lt:sch:add"]
    full = [dict(entry, id=str(n)) for n in range(1, leaders.SCHEDULE_MAX + 1)]
    assert "lt:sch:add" not in datas_of(leader_cards.schedule_keyboard(IT, full))


def test_ore_minuti_e_giorni_sono_a_bottoni():
    hours = datas_of(leader_cards.hours_keyboard(IT))
    assert hours[:2] == ["lt:sch:h:00", "lt:sch:h:01"] and len(hours) == 24
    assert datas_of(leader_cards.minutes_keyboard(IT, "08")) == ["lt:sch:m:08:00", "lt:sch:m:08:30"]
    days = datas_of(leader_cards.days_keyboard(IT, [1]))
    assert days[0] == "lt:sch:d:all" and days[-1] == "lt:sch:ok"
    assert len(days) == 9


def test_il_capo_programma_un_messaggio_a_bottoni_e_poi_lo_toglie():
    store = FakeStore()
    context = context_for(store)
    assert press(context, "lt:sch:add").edits[0][0] == IT.t("leaders.schedule.pick_hour")
    assert press(context, "lt:sch:h:08").edits[0][0] == IT.t("leaders.schedule.pick_minute")
    assert press(context, "lt:sch:m:08:30").edits[0][0] == IT.t("leaders.schedule.pick_days")
    picked = press(context, "lt:sch:d:2").edits[0][1]
    assert datas_of(picked)[3] == "lt:sch:d:2" and labels_of(picked)[3].startswith("✓")
    assert press(context, "lt:sch:ok").edits[0][0] == IT.t("leaders.schedule.ask_text")
    typed = private_update(text="Buongiorno")
    asyncio.run(handlers.on_private_text(typed, context))
    assert leaders.schedule(store.saved()) == [{"id": "1", "hhmm": "08:30", "days": [2],
                                                "text": "Buongiorno", "by": LEADER}]
    assert store.log[-1]["action"] == "schedule" and store.log[-1]["detail"] == "08:30"
    assert context.user_data.get("flow") is None
    press(context, "lt:sch:del:1")
    assert leaders.schedule(store.saved()) == []


def test_il_bottone_vecchio_dopo_annulla_riporta_al_programma():
    store = FakeStore()
    context = context_for(store)
    press(context, "lt:sch:add")
    press(context, "lt:sch:h:08")
    asyncio.run(handlers.cmd_cancel(private_update(), context))
    query = press(context, "lt:sch:m:08:30")
    assert context.user_data.get("flow") is None
    assert query.edits[0][0] == leader_cards.schedule_card(IT, [])
    assert datas_of(query.edits[0][1]) == ["lt:sch:add"]
    typed = private_update(text="Buongiorno")
    asyncio.run(handlers.on_private_text(typed, context))
    assert leaders.schedule(store.saved()) == []
    assert typed.effective_message.sent == []


def test_i_giorni_di_un_programma_annullato_non_si_accumulano():
    store = FakeStore()
    context = context_for(store)
    press(context, "lt:sch:add")
    press(context, "lt:sch:m:08:30")
    asyncio.run(handlers.cmd_cancel(private_update(), context))
    query = press(context, "lt:sch:d:2")
    assert context.user_data.get("flow") is None
    assert query.edits[0][0] == leader_cards.schedule_card(IT, [])
    assert press(context, "lt:sch:ok").edits[0][0] == leader_cards.schedule_card(IT, [])


def test_il_membro_semplice_non_tocca_i_bottoni_del_capo():
    store = FakeStore()
    query = press(context_for(store), "lt:sch:add", user_id=MEMBER)
    assert query.answers == [(IT.t("leaders.only"), True)]
    assert query.edits == []


def test_il_programma_pieno_non_ne_accetta_altri():
    entries = [{"id": str(n), "hhmm": "08:00", "days": [], "text": "x", "by": LEADER}
               for n in range(1, leaders.SCHEDULE_MAX + 1)]
    store = FakeStore(dict(ROME, scheduled=entries))
    query = press(context_for(store), "lt:sch:add")
    assert query.answers == [(IT.t("leaders.schedule.full", n=leaders.SCHEDULE_MAX), True)]


def test_dal_gruppo_i_bottoni_mandano_in_privato():
    store = FakeStore()
    context = context_for(store)
    query = FakeQuery("lt:sch:add")
    update = SimpleNamespace(callback_query=query, effective_message=query.message,
                             effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
                             effective_user=SimpleNamespace(id=LEADER, language_code="it",
                                                            first_name="Mario"))
    asyncio.run(leader_tools.on_leader_callback(update, context))
    assert query.edits[0][0] == IT.t("leaders.private_only", bot="ClanBoardFuturoBot")
    assert context.user_data.get("flow") is None


class FakePoller:
    def __init__(self, store):
        self.store = store
        self.dispatched = []

    async def dispatch(self, t, event, render_text, member_tag=None):
        self.dispatched.append((event, render_text(t.L), member_tag))


def tick_for(settings, events=()):
    t = SimpleNamespace(clan=CLAN, now=NOW, chunks=[], dm=[], events=list(events),
                        settings=settings_mod.effective(settings), members=copy.deepcopy(MEMBERS))
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    return t


def test_il_messaggio_programmato_parte_una_volta_al_giorno():
    settings = dict(ROME, scheduled=[{"id": "1", "hhmm": "10:00", "days": [], "text": "Buongiorno",
                                      "by": LEADER}])
    store = FakeStore(settings)
    poller = FakePoller(store)
    asyncio.run(leader_jobs.run(poller, tick_for(settings)))
    assert [event for event, _, _ in poller.dispatched] == ["leaders.scheduled"]
    assert "Buongiorno" in poller.dispatched[0][1]
    assert store.state[(CLAN.alias, "scheduled")]["sent"] == {"1:2026-09-14": NOW.timestamp()}
    poller.dispatched.clear()
    asyncio.run(leader_jobs.run(poller, tick_for(settings)))
    assert poller.dispatched == []


def test_il_messaggio_programmato_aspetta_il_suo_giorno():
    settings = dict(ROME, scheduled=[{"id": "1", "hhmm": "10:00", "days": [1], "text": "Buongiorno",
                                      "by": LEADER}])
    poller = FakePoller(FakeStore(settings))
    asyncio.run(leader_jobs.run(poller, tick_for(settings)))
    assert poller.dispatched == []


def test_il_benvenuto_parte_sui_nuovi_arrivati_e_tace_senza_testo():
    settings = dict(ROME, texts={"welcome": "Ciao {name}!"})
    store = FakeStore(settings)
    poller = FakePoller(store)
    events = [{"type": "join", "tag": "#P9", "name": "Toad"}, {"type": "leave", "tag": "#P8", "name": "Peach"}]
    asyncio.run(leader_jobs.run(poller, tick_for(settings, events)))
    assert [event for event, _, _ in poller.dispatched] == ["leaders.welcome"]
    assert "Toad" in poller.dispatched[0][1] and "Peach" not in poller.dispatched[0][1]
    muto = FakePoller(store)
    asyncio.run(leader_jobs.run(muto, tick_for(ROME, events)))
    assert muto.dispatched == []


def test_un_lavoro_che_esplode_non_ferma_gli_altri():
    settings = dict(ROME, texts={"welcome": "Ciao {name}!"},
                    scheduled=[{"id": "1", "hhmm": "10:00", "days": [], "text": "Buongiorno", "by": LEADER}])
    poller = FakePoller(FakeStore(settings))
    asyncio.run(leader_jobs.run(poller, tick_for(settings, [None])))
    assert [event for event, _, _ in poller.dispatched] == ["leaders.scheduled"]


def test_il_giro_di_controllo_porta_con_se_i_movimenti():
    assert Tick(CLAN, NOW).events == []


def test_i_comandi_del_capo_sono_registrati():
    for name, alias in (("rules", "regole"), ("welcome", "benvenuto"), ("schedule", "programma")):
        assert (name, [alias]) in handlers.COMMANDS
        assert handlers.HANDLERS[name] is leader_tools.HANDLERS[name]


def test_il_cambio_di_impostazioni_finisce_nel_registro():
    store = FakeStore()
    asyncio.run(handlers.save_settings(store, CLAN, {"tz": "Europe/Rome"}))
    assert store.log == []
    asyncio.run(handlers.save_settings(store, CLAN, {"lang": "en", "tz": "UTC"},
                                       SimpleNamespace(id=LEADER, first_name="Mario")))
    assert store.log[-1] == {"action": "settings", "by": LEADER, "by_name": "Mario",
                             "detail": "lang,tz"}


def test_i_ruoli_di_comando_sono_un_insieme_solo():
    assert handlers.LEADER_ROLES is leaders.ROLES
    assert verify.LEADER_ROLES is leaders.ROLES


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("leaders.only", "leaders.rules.title", "leaders.rules.none", "leaders.rules.saved",
                "leaders.welcome.title", "leaders.welcome.none", "leaders.welcome.saved",
                "leaders.welcome.tokens", "leaders.schedule.title", "leaders.schedule.none",
                "leaders.schedule.row", "leaders.schedule.added", "leaders.schedule.removed",
                "leaders.schedule.full", "leaders.schedule.ask_text", "leaders.schedule.pick_hour",
                "leaders.schedule.pick_minute", "leaders.schedule.pick_days", "leaders.schedule.every_day",
                "leaders.schedule.btn_add", "leaders.schedule.btn_del", "leaders.schedule.btn_done",
                "leaders.private_only", "cmd.rules", "cmd.welcome", "cmd.schedule",
                "texts.reject.link", "texts.reject.phone", "texts.reject.bot"):
        assert key in EN, key
