import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError

from clashbot import (ambassadors, console, duels, familyroom, feed, gate, handlers, i18n,
                      leader_cards, leader_jobs, leader_tools, leaders, media,
                      poller as poller_mod, recruit, stickers, tournaments, ttl, util)
from clashbot import settings as settings_mod
from clashbot.bot import ALLOWED_UPDATES

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 8, 5, tzinfo=timezone.utc)
NIGHT = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1",
                       active=True)
LEADER = 7
MEMBER = 9
STRANGER = 99
PLATFORM = 4242
MEMBERS ={"#P1": {"name": "Mario", "role": "leader"}, "#P9": {"name": "Toad", "role": "member"}}
ROME = {"lang": "it", "tz": "Europe/Rome", "gate": True}
NIGHT_ROME = dict(ROME, quiet=[23, 7])


def link(tag, user_id, name):
    return SimpleNamespace(tag=tag, user_id=user_id, name=name, dm=True, lang="it")


LINKS = [link("#P1", LEADER, "Mario"), link("#P9", MEMBER, "Toad")]


class RosterStore:
    def __init__(self, members, links, family=None, family_members=None):
        self.members = members
        self.links = links
        self.family = family
        self.family_members = family_members or {}

    async def get_state(self, alias, kind):
        if kind != "members":
            return None
        return self.members if alias == CLAN.alias else self.family_members

    async def links_by_user(self, user_id):
        return list(self.links.get(user_id, []))

    async def family_of_clan(self, alias):
        return self.family

    async def family_clans(self, alias):
        return [SimpleNamespace(alias=CLAN.alias), SimpleNamespace(alias="clan-2")]


def source_of(module):
    return Path(module.__file__).read_text(encoding="utf-8")


def test_le_scadenze_condivise_hanno_una_sorgente_sola():
    assert gate.PENDING_TTL == ttl.RETRY_TTL == console.RETRY_TTL
    assert duels.PROPOSAL_TTL == ttl.ONBOARD_TTL == console.ONBOARD_TTL
    assert ambassadors.INVITE_TTL == ttl.GONE_TTL == console.GONE_TTL
    for module, name in ((gate, "PENDING_TTL"), (duels, "PROPOSAL_TTL"),
                         (ambassadors, "INVITE_TTL")):
        assert f"{name} = ttl." in source_of(module)
    assert "RETRY_TTL = 604800" not in source_of(console)


def test_i_posti_del_clan_e_le_scadenze_del_blocco_hanno_una_sorgente_sola():
    assert tournaments.SIGNUP_WINDOW == ttl.ONBOARD_TTL
    assert familyroom.NOTICE_TTL == ttl.GONE_TTL
    assert recruit.CLAN_SLOTS == util.CLAN_SLOTS == familyroom.CLAN_SLOTS
    assert "SIGNUP_WINDOW = ONBOARD_TTL" in source_of(tournaments)
    assert "NOTICE_TTL = GONE_TTL" in source_of(familyroom)
    assert "NOTICE_TTL = 2592000" not in source_of(familyroom)
    assert "CLAN_MAX" not in source_of(recruit)
    assert "= 50" not in source_of(recruit)


def test_lo_stemma_ha_un_solo_scaricatore():
    assert stickers.badge_of is media.badge
    assert "httpx" not in source_of(stickers)
    assert not hasattr(stickers, "badge_bytes")


def test_l_ora_dei_report_e_una_sola():
    assert poller_mod.REPORT_HOUR == leader_jobs.REPORT_HOUR == util.REPORT_HOUR
    assert all("REPORT_HOUR = " not in source_of(module)
               for module in (poller_mod, leader_jobs))


def test_approva_chi_e_collegato_a_un_membro_del_clan():
    store = RosterStore({"#P1": {"name": "Mario"}}, {LEADER: [link("#P1", LEADER, "Mario")]})
    assert asyncio.run(gate.verdict(store, CLAN, LEADER)) == ("approve", "Mario")


def test_approva_anche_chi_e_in_un_clan_della_famiglia():
    store = RosterStore({}, {LEADER: [link("#P9", LEADER, "Toad")]},
                        family=SimpleNamespace(alias="fam-1"),
                        family_members={"#P9": {"name": "Toad"}})
    assert asyncio.run(gate.verdict(store, CLAN, LEADER)) == ("approve", "Toad")


def test_lo_sconosciuto_resta_in_sospeso_e_non_viene_mai_rifiutato_da_solo():
    store = RosterStore({"#P1": {"name": "Mario"}}, {})
    assert asyncio.run(gate.verdict(store, CLAN, STRANGER)) == ("ask", None)


def test_il_collegato_a_un_altro_clan_resta_in_sospeso():
    store = RosterStore({"#P1": {"name": "Mario"}}, {STRANGER: [link("#PX", STRANGER, "Estraneo")]})
    assert asyncio.run(gate.verdict(store, CLAN, STRANGER)) == ("ask", None)


class Bot:
    def __init__(self, status=ChatMemberStatus.MEMBER, boom=False):
        self.status = status
        self.boom = boom

    async def get_chat_member(self, chat_id, user_id):
        if self.boom:
            raise TelegramError("niente")
        return SimpleNamespace(status=self.status)


class LinkStore:
    def __init__(self, links):
        self.links = links

    async def links_for_players(self, tags):
        return {tag: self.links[tag] for tag in tags if tag in self.links}


def test_promemoria_di_uscita_solo_per_chi_e_collegato_e_ancora_nel_gruppo():
    store = LinkStore({"#P4": link("#P4", 42, "Toad")})
    events = [{"type": "leave", "tag": "#P4", "name": "Toad"},
              {"type": "leave", "tag": "#P5", "name": "Peach"},
              {"type": "join", "tag": "#P6", "name": "Yoshi"}]
    rows = asyncio.run(gate.leavers_to_report(Bot(), store, CLAN, events))
    assert rows == [{"name": "Toad", "user_id": 42}]


def test_niente_promemoria_se_ha_gia_lasciato_il_gruppo_o_telegram_non_risponde():
    store = LinkStore({"#P4": link("#P4", 42, "Toad")})
    events = [{"type": "leave", "tag": "#P4", "name": "Toad"}]
    assert asyncio.run(gate.leavers_to_report(Bot(ChatMemberStatus.LEFT), store, CLAN, events)) == []
    assert asyncio.run(gate.leavers_to_report(Bot(boom=True), store, CLAN, events)) == []


def test_le_schede_del_filtro_hanno_i_bottoni_giusti():
    datas = [b.callback_data
             for row in leader_cards.gate_request_keyboard(IT, STRANGER).inline_keyboard for b in row]
    assert datas == [f"gt:ok:{STRANGER}", f"gt:no:{STRANGER}"]
    assert IT.t("leaders.gate.on") in leader_cards.gate_card(IT, True)
    assert IT.t("leaders.gate.off") in leader_cards.gate_card(IT, False)
    assert "Toad" in leader_cards.exit_card(IT, [{"name": "Toad", "user_id": 42}])
    assert "tg://user?id=42" in leader_cards.exit_card(IT, [{"name": "Toad", "user_id": 42}])


def test_la_scheda_della_richiesta_scappa_il_nome_di_chi_bussa():
    text = leader_cards.gate_request_card(IT, "<b>Cattivo</b>", "cat&tivo")
    assert "<b>Cattivo</b>" not in text
    assert "&lt;b&gt;Cattivo&lt;/b&gt;" in text
    assert "@cat&amp;tivo" in text


class FakeStore:
    def __init__(self, settings=None, members=None):
        self.state = {(CLAN.alias, "settings"): copy.deepcopy(settings or ROME),
                      (CLAN.alias, "members"): copy.deepcopy(MEMBERS if members is None else members)}
        self.links = [copy.copy(entry) for entry in LINKS]
        self.kv = {}
        self.ttl = {}
        self.log = []
        self.family = None
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
        return [entry for entry in self.links if entry.user_id == user_id]

    async def links_for_players(self, tags):
        wanted = set(tags)
        return {entry.tag: entry for entry in self.links if entry.tag in wanted}

    async def family_of_clan(self, alias):
        return self.family

    async def family_clans(self, alias):
        return []

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)
        self.ttl[key] = ttl

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def get_secret(self, kind):
        return None

    async def bot_by_alias(self, alias):
        return None

    async def add_log(self, alias, entry, at=None):
        self.log.append(entry)

    def saved(self):
        return self.state[(CLAN.alias, "settings")]


class RecordingBot:
    username = "ClanBoardFuturoBot"

    def __init__(self, boom=False):
        self.sent = []
        self.decided = []
        self.boom = boom

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append((chat_id, text, reply_markup))
        return SimpleNamespace(message_id=1)

    async def approve_chat_join_request(self, chat_id, user_id):
        if self.boom:
            raise TelegramError("niente")
        self.decided.append(("ok", chat_id, user_id))

    async def decline_chat_join_request(self, chat_id, user_id):
        if self.boom:
            raise TelegramError("niente")
        self.decided.append(("no", chat_id, user_id))


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


def press_update(data, user_id=LEADER):
    query = FakeQuery(data)
    return SimpleNamespace(callback_query=query, effective_message=query.message,
                           effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
                           effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                          first_name="Mario"))


def context_for(store, args=None, bot=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=list(args or []), user_data={},
                           bot=bot or SimpleNamespace(username="ClanBoardFuturoBot"))


class Request:
    def __init__(self, user_id=STRANGER, name="Estraneo", username="estraneo"):
        self.chat = SimpleNamespace(id=CLAN.chat_id)
        self.from_user = SimpleNamespace(id=user_id, first_name=name, username=username)
        self.user_chat_id = user_id
        self.approved = False

    async def approve(self):
        self.approved = True


def join(request, store, bot):
    asyncio.run(leader_tools.on_join_request(SimpleNamespace(chat_join_request=request),
                                             context_for(store, bot=bot)))


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_la_richiesta_in_sospeso_arriva_solo_ai_capi_anche_se_leaders_gate_punta_al_gruppo(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("group", None))
    store = FakeStore()
    request = Request()
    bot = RecordingBot()
    join(request, store, bot)
    assert request.approved is False
    assert bot.sent == []
    assert "Estraneo" in feed_rows(store, LEADER)[0]
    assert feed_rows(store, MEMBER) == []
    assert store.kv[f"gate:{CLAN.alias}:{STRANGER}"]["name"] == "Estraneo"


def test_il_collegato_entra_da_solo_e_riceve_benvenuto_e_regole():
    store = FakeStore(dict(ROME, texts={"welcome": "Ciao {name}!", "rules": "Niente spam"}))
    request = Request(user_id=MEMBER, name="Toad", username=None)
    bot = RecordingBot()
    join(request, store, bot)
    assert request.approved is True
    assert [chat_id for chat_id, _, _ in bot.sent] == [MEMBER, MEMBER]
    assert "Toad" in feed_rows(store, LEADER)[0]
    assert "Ciao Toad!" in bot.sent[0][1]
    assert "Niente spam" in bot.sent[1][1]


def test_senza_testi_il_nuovo_arrivato_riceve_lo_stesso_un_saluto():
    store = FakeStore()
    request = Request(user_id=MEMBER, name="Toad", username=None)
    bot = RecordingBot()
    join(request, store, bot)
    assert bot.sent[0][1] == IT.t("leaders.gate.hello", clan="Futuro")


def test_col_filtro_spento_il_bot_non_tocca_la_richiesta():
    store = FakeStore(dict(ROME, gate=False))
    request = Request()
    bot = RecordingBot()
    join(request, store, bot)
    assert request.approved is False
    assert bot.sent == []
    assert store.kv == {}


def test_se_non_sono_amministratore_lo_dico_ai_capi_una_volta():
    class Refusing(Request):
        async def approve(self):
            raise TelegramError("niente")

    store = FakeStore()
    bot = RecordingBot()
    join(Refusing(user_id=MEMBER, name="Toad", username=None), store, bot)
    assert bot.sent == []
    assert feed_rows(store, LEADER) == [leader_cards.gate_needs_admin(IT)]


def test_di_notte_l_avviso_di_ingresso_automatico_aspetta_il_mattino(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("group", None))
    monkeypatch.setattr(leaders, "now_utc", lambda: NIGHT)
    store = FakeStore(NIGHT_ROME)
    request = Request(user_id=MEMBER, name="Toad", username=None)
    bot = RecordingBot()
    join(request, store, bot)
    assert request.approved is True
    assert [chat_id for chat_id, _, _ in bot.sent] == [MEMBER]
    assert store.state[(CLAN.alias, "queue")] == [leader_cards.gate_auto(IT, "Toad", "Toad")]


def test_di_notte_la_richiesta_in_sospeso_arriva_lo_stesso(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("leaders_dm", None))
    monkeypatch.setattr(leaders, "now_utc", lambda: NIGHT)
    store = FakeStore(NIGHT_ROME)
    bot = RecordingBot()
    join(Request(), store, bot)
    assert bot.sent == []
    assert len(feed_rows(store, LEADER)) == 1
    assert (CLAN.alias, "queue_dm") not in store.state


def test_il_capo_decide_dal_bottone_e_la_scelta_finisce_nel_registro():
    store = FakeStore()
    bot = RecordingBot()
    join(Request(), store, bot)
    update = press_update(f"gt:ok:{STRANGER}")
    asyncio.run(leader_tools.on_gate_callback(update, context_for(store, bot=bot)))
    assert bot.decided == [("ok", CLAN.chat_id, STRANGER)]
    assert store.log[-1] == {"action": "gate", "by": LEADER, "by_name": "Mario", "detail": "ok"}
    assert f"gate:{CLAN.alias}:{STRANGER}" not in store.kv
    assert "Estraneo" in update.callback_query.edits[-1][0]


def test_il_capo_puo_anche_rifiutare():
    store = FakeStore()
    bot = RecordingBot()
    join(Request(), store, bot)
    update = press_update(f"gt:no:{STRANGER}")
    asyncio.run(leader_tools.on_gate_callback(update, context_for(store, bot=bot)))
    assert bot.decided == [("no", CLAN.chat_id, STRANGER)]
    assert store.log[-1]["detail"] == "no"


def test_un_membro_semplice_non_decide_chi_entra():
    store = FakeStore()
    bot = RecordingBot()
    join(Request(), store, bot)
    update = press_update(f"gt:ok:{STRANGER}", user_id=MEMBER)
    asyncio.run(leader_tools.on_gate_callback(update, context_for(store, bot=bot)))
    assert bot.decided == []
    assert update.callback_query.answers[-1] == (IT.t("leaders.only"), True)


def test_se_telegram_rifiuta_la_decisione_lo_dice_al_capo():
    store = FakeStore()
    join(Request(), store, RecordingBot())
    bot = RecordingBot(boom=True)
    update = press_update(f"gt:ok:{STRANGER}")
    asyncio.run(leader_tools.on_gate_callback(update, context_for(store, bot=bot)))
    assert update.callback_query.edits[-1][0] == leader_cards.gate_needs_admin(IT)
    assert store.log == []
    assert f"gate:{CLAN.alias}:{STRANGER}" in store.kv


def test_il_secondo_capo_non_si_sente_dire_che_non_sono_amministratore():
    store = FakeStore()
    bot = RecordingBot()
    join(Request(), store, bot)
    asyncio.run(leader_tools.on_gate_callback(press_update(f"gt:ok:{STRANGER}"),
                                              context_for(store, bot=bot)))
    second = press_update(f"gt:no:{STRANGER}")
    asyncio.run(leader_tools.on_gate_callback(second, context_for(store, bot=bot)))
    assert bot.decided == [("ok", CLAN.chat_id, STRANGER)]
    assert second.callback_query.edits[-1][0] == leader_cards.gate_gone(IT)
    assert leader_cards.gate_needs_admin(IT) not in [text for text, _ in second.callback_query.edits]
    assert [entry["detail"] for entry in store.log] == ["ok"]


def test_il_comando_mostra_la_scheda_e_l_interruttore_la_ribalta():
    store = FakeStore(dict(ROME, gate=False))
    update = group_update()
    asyncio.run(leader_tools.cmd_gate(update, context_for(store)))
    assert update.effective_message.sent[0][0] == leader_cards.gate_card(IT, False)
    press = press_update("gt:switch")
    asyncio.run(leader_tools.on_gate_switch(press, context_for(store)))
    assert leaders.gate_on(store.saved()) is True
    assert press.callback_query.edits[-1][0] == leader_cards.gate_card(IT, True)
    assert store.log[-1] == {"action": "gate", "by": LEADER, "by_name": "Mario", "detail": "on"}
    asyncio.run(leader_tools.on_gate_switch(press_update("gt:switch"), context_for(store)))
    assert leaders.gate_on(store.saved()) is False
    assert store.log[-1]["detail"] == "off"


def test_un_membro_semplice_non_tocca_l_interruttore():
    store = FakeStore(dict(ROME, gate=False))
    press = press_update("gt:switch", user_id=MEMBER)
    asyncio.run(leader_tools.on_gate_switch(press, context_for(store)))
    assert leaders.gate_on(store.saved()) is False
    assert press.callback_query.answers[-1] == (IT.t("leaders.only"), True)


class FakePoller:
    def __init__(self, store, bot):
        self.store = store
        self.bot = bot
        self.dispatched = []

    def bot_for(self, owner):
        return self.bot

    async def dispatch(self, t, event, render_text, member_tag=None):
        self.dispatched.append((event, render_text(t.L), member_tag))


def tick_for(settings, events=()):
    t = SimpleNamespace(clan=CLAN, now=NOW, chunks=[], dm=[], events=list(events),
                        settings=settings_mod.effective(settings), members=copy.deepcopy(MEMBERS))
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    return t


def test_chi_lascia_il_clan_ma_resta_nel_gruppo_finisce_nel_promemoria():
    poller = FakePoller(FakeStore(), Bot())
    events = [{"type": "leave", "tag": "#P9", "name": "Toad"}]
    asyncio.run(leader_jobs.run(poller, tick_for(ROME, events)))
    assert [event for event, _, _ in poller.dispatched] == ["leaders.exit"]
    assert "Toad" in poller.dispatched[0][1]


def test_senza_uscite_il_promemoria_tace():
    poller = FakePoller(FakeStore(), Bot())
    events = [{"type": "join", "tag": "#P9", "name": "Toad"}]
    asyncio.run(leader_jobs.run(poller, tick_for(ROME, events)))
    assert poller.dispatched == []


def test_chi_non_e_collegato_non_fa_rumore():
    poller = FakePoller(FakeStore(), Bot())
    events = [{"type": "leave", "tag": "#P8", "name": "Peach"}]
    asyncio.run(leader_jobs.run(poller, tick_for(ROME, events)))
    assert poller.dispatched == []


def test_il_comando_dell_ingresso_e_registrato():
    assert ("gate", ["ingresso"]) in handlers.COMMANDS
    assert handlers.HANDLERS["gate"] is leader_tools.HANDLERS["gate"]


def test_le_richieste_di_ingresso_arrivano_al_bot():
    assert Update.CHAT_JOIN_REQUEST in ALLOWED_UPDATES


@pytest.mark.parametrize("key", ["leaders.gate.title", "leaders.gate.on", "leaders.gate.off",
                                 "leaders.gate.btn_on", "leaders.gate.btn_off", "leaders.gate.request",
                                 "leaders.gate.btn_ok", "leaders.gate.btn_no", "leaders.gate.approved",
                                 "leaders.gate.declined", "leaders.gate.auto", "leaders.gate.needs_admin",
                                 "leaders.gate.gone",
                                 "leaders.exit.title", "leaders.exit.row", "leaders.exit.tail",
                                 "leaders.gate.hello", "cmd.gate"])
def test_le_chiavi_nuove_esistono(key):
    assert key in EN


GAME_TAG = "#2PP0JCCL"


class OneGroupStore:
    def __init__(self, role="leader"):
        self.clan = SimpleNamespace(alias=CLAN.alias, chat_id=CLAN.chat_id, tag=CLAN.tag,
                                    name=CLAN.name, bot_alias=CLAN.bot_alias, active=True)
        self.members = {"#P1": {"name": "Mario", "role": role},
                        "#P2": {"name": "Luigi", "role": "coLeader"}}
        self.people = [link("#P1", LEADER, "Mario"), link("#P2", MEMBER, "Luigi")]
        self.moved = []
        self.removed = []
        self.log = []
        self.added = []
        self.state = {}
        self.kv = {}
        self.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def set_link_lang(self, user_id, lang):
        return None

    async def active_clans(self, bot_alias=None):
        return [self.clan] if bot_alias in (None, self.clan.bot_alias) else []

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return self.clan if chat_id == self.clan.chat_id else None

    async def clan_by_alias(self, alias):
        return self.clan if alias == self.clan.alias else None

    async def get_state(self, alias, kind):
        if kind == "members":
            return copy.deepcopy(self.members)
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def links_by_user(self, user_id):
        return [row for row in self.people if row.user_id == user_id]

    async def links_for_players(self, tags):
        return {row.tag: row for row in self.people if row.tag in set(tags or ())}

    async def move_clan(self, old_chat_id, new_chat_id, bot_alias=None):
        self.moved.append((old_chat_id, new_chat_id, bot_alias))
        self.clan.chat_id = new_chat_id
        return True

    async def remove_clan(self, chat_id, bot_alias=None):
        self.removed.append((chat_id, bot_alias))
        return True

    async def add_clan(self, chat_id, tag, name, user_id, bot_alias):
        self.added.append((chat_id, tag, name, user_id, bot_alias))
        return self.clan

    async def add_log(self, alias, entry, at=None):
        self.log.append(dict(entry))

    async def count_clans(self, bot_alias):
        return 2

    async def bot_by_alias(self, alias):
        return None

    async def get_secret(self, kind):
        return None

    async def bot_for_tag(self, tag):
        return CLAN.bot_alias

    async def rename_clan(self, clan, name):
        return None


class NoClanStore(OneGroupStore):
    async def active_clans(self, bot_alias=None):
        return []

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

    async def bot_by_alias(self, alias):
        return SimpleNamespace(alias=alias, owner_id=LEADER)


class OwnerStore(OneGroupStore):
    async def get_secret(self, kind):
        return str(PLATFORM) if kind == "owner_id" else None


class NoClanOwnerStore(NoClanStore):
    async def get_secret(self, kind):
        return str(PLATFORM) if kind == "owner_id" else None


class OneGroupCoc:
    def __init__(self, store):
        self.store = store

    async def clan(self, tag):
        members = [{"tag": t, "name": row["name"], "role": row["role"]}
                   for t, row in self.store.members.items()]
        return {"tag": tag, "name": CLAN.name, "memberList": members, "location": None}, None

    async def player(self, tag):
        return None, "not_found"


class DemotingCoc(OneGroupCoc):
    async def player(self, tag):
        return {"tag": tag, "role": "coLeader", "clan": {"tag": CLAN.tag}}, None


class JoiningBot:
    def __init__(self):
        self.sent = []
        self.left = []
        self.unpinned = []
        self.deleted = []
        self.username = "ClanBoardFuturoBot"

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def leave_chat(self, chat_id):
        self.left.append(chat_id)
        return True

    async def unpin_chat_message(self, chat_id, message_id):
        self.unpinned.append((chat_id, message_id))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class GroupMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append(text)
        return SimpleNamespace(message_id=1)


def one_group_context(store, bot, args=None, coc=None):
    return SimpleNamespace(bot=bot, args=list(args or []), user_data={},
                           bot_data={"store": store, "coc": coc or OneGroupCoc(store),
                                     "bot_alias": CLAN.bot_alias})


def added_update(chat_id, user_id=LEADER):
    chat = SimpleNamespace(id=chat_id, type=ChatType.SUPERGROUP)
    user = SimpleNamespace(id=user_id, language_code="it", first_name="Mario")
    return SimpleNamespace(
        my_chat_member=SimpleNamespace(
            chat=chat, from_user=user,
            new_chat_member=SimpleNamespace(status=ChatMemberStatus.MEMBER),
            old_chat_member=SimpleNamespace(status=ChatMemberStatus.LEFT)),
        effective_chat=chat, effective_user=user, effective_message=None)


def setclan_update(chat_id, user_id, private=False):
    chat = SimpleNamespace(id=chat_id,
                           type=ChatType.PRIVATE if private else ChatType.SUPERGROUP)
    return SimpleNamespace(
        callback_query=None, effective_message=GroupMessage(), effective_chat=chat,
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Tizio"))


def command_of(name):
    app = SimpleNamespace(handlers=[])
    app.add_handler = app.handlers.append
    handlers.register(app)
    for handler in app.handlers:
        if getattr(handler, "commands", None) and name in handler.commands:
            return handler.callback
    raise AssertionError(name)


def test_il_bot_aggiunto_a_un_altro_gruppo_se_ne_va_senza_scrivere():
    store = OneGroupStore()
    bot = JoiningBot()
    asyncio.run(handlers.on_my_chat_member(added_update(999, MEMBER),
                                           one_group_context(store, bot)))
    assert bot.left == [999]
    assert bot.sent == [] and store.added == [] and store.moved == []


def test_nel_gruppo_del_clan_il_bot_resta():
    store = OneGroupStore()
    bot = JoiningBot()
    asyncio.run(handlers.on_my_chat_member(added_update(CLAN.chat_id),
                                           one_group_context(store, bot)))
    assert bot.left == []


def test_il_capo_del_gioco_che_lo_aggiunge_altrove_sposta_il_gruppo_e_lo_scrive():
    store = OneGroupStore()
    bot = JoiningBot()
    vecchio = CLAN.chat_id
    store.state[(CLAN.alias, "boards")] = {"message_id": 77, "digest": "abc", "updated": 10}
    asyncio.run(handlers.on_my_chat_member(added_update(999), one_group_context(store, bot)))
    assert store.moved == [(vecchio, 999, CLAN.bot_alias)]
    assert bot.left == [] and bot.sent == [] and store.added == []
    assert [row["action"] for row in store.log] == ["link"]
    assert store.log[0]["by"] == LEADER and store.log[0]["detail"] == CLAN.name
    assert bot.unpinned == [(vecchio, 77)] and bot.deleted == [(vecchio, 77)]
    assert store.state[(CLAN.alias, "boards")] == {}


def test_chi_non_e_piu_capo_nel_gioco_non_sposta_il_gruppo():
    store = OneGroupStore()
    bot = JoiningBot()
    asyncio.run(handlers.on_my_chat_member(
        added_update(999), one_group_context(store, bot, coc=DemotingCoc(store))))
    assert store.moved == [] and bot.left == [999] and bot.sent == []


def test_setclan_nel_gruppo_non_risponde_a_nessuno():
    store = OneGroupStore()
    update = setclan_update(CLAN.chat_id, LEADER)
    asyncio.run(command_of("setclan")(update, one_group_context(store, JoiningBot(), [GAME_TAG])))
    assert update.effective_message.sent == []
    assert store.moved == [] and store.added == []


def test_setclan_in_privato_non_collega_mai_la_chat_privata():
    store = OneGroupStore()
    update = setclan_update(555, LEADER, private=True)
    asyncio.run(command_of("setclan")(update, one_group_context(store, JoiningBot(), [GAME_TAG])))
    assert update.effective_message.sent == [IT.t("gate.other_group")]
    assert store.moved == [] and store.added == []


def test_setclan_in_privato_senza_clan_dice_dove_si_collega():
    store = NoClanStore()
    update = setclan_update(555, LEADER, private=True)
    asyncio.run(command_of("setclan")(update, one_group_context(store, JoiningBot(), [GAME_TAG])))
    assert update.effective_message.sent == [IT.t("h.setclan_usage")]
    assert store.moved == [] and store.added == []


def test_remove_in_privato_scollega_il_gruppo_del_clan():
    store = OneGroupStore()
    update = setclan_update(555, LEADER, private=True)
    asyncio.run(command_of("remove")(update, one_group_context(store, JoiningBot())))
    assert store.removed == [(CLAN.chat_id, CLAN.bot_alias)]
    assert update.effective_message.sent == [IT.t("h.unlinked")]


def test_remove_in_privato_vale_anche_per_chi_non_ha_un_villaggio_collegato():
    store = OwnerStore()
    update = setclan_update(555, PLATFORM, private=True)
    asyncio.run(command_of("remove")(update, one_group_context(store, JoiningBot())))
    assert store.removed == [(CLAN.chat_id, CLAN.bot_alias)]
    assert update.effective_message.sent == [IT.t("h.unlinked")]


def test_remove_in_privato_senza_nessun_clan_lo_dice():
    store = NoClanOwnerStore()
    update = setclan_update(555, PLATFORM, private=True)
    asyncio.run(command_of("remove")(update, one_group_context(store, JoiningBot())))
    assert store.removed == [] and update.effective_message.sent == [IT.t("h.removed_none")]


def test_remove_nel_gruppo_non_risponde_a_nessuno():
    store = OneGroupStore()
    update = setclan_update(CLAN.chat_id, LEADER)
    asyncio.run(command_of("remove")(update, one_group_context(store, JoiningBot())))
    assert store.removed == [] and update.effective_message.sent == []


def test_la_chiave_del_gruppo_unico_esiste():
    assert "gate.other_group" in EN
