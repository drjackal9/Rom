import asyncio
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import feed, handlers, i18n, recruit, recruit_cards, recruit_tools
from clashbot.crypto import Vault
from clashbot.db import Store

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1",
                       active=True)
OTHER = SimpleNamespace(alias="clan-2", chat_id=102, tag="#CLAN2", name="Passato", bot_alias="bot-1")
TYPED = "#2PP0JCCL"
SNAP = {"name": "Toad", "th": 15, "trophies": 4100, "best": 4300, "warStars": 900,
        "heroes": {"Barbarian King": 80}, "warPref": "in", "donations": 1200,
        "received": 900, "capital": 50000, "exp": 190, "clan": "#OLD"}
PLAYER = {"name": "Toad", "townHallLevel": 15, "trophies": 4100, "bestTrophies": 4300,
          "warStars": 900, "warPreference": "in", "donations": 1200, "donationsReceived": 900,
          "clanCapitalContributions": 50000, "expLevel": 190,
          "heroes": [{"name": "Barbarian King", "level": 80, "village": "home"}]}


def chief_link():
    return SimpleNamespace(alias="link-0", tag="#P1", user_id=5, name="Mario", dm=True)


class FakeStore:
    def __init__(self, settings=None, members=None, links=()):
        self.state = {(CLAN.alias, "settings"): dict(settings or {"lang": "it", "tz": "Europe/Rome"}),
                      (CLAN.alias, "members"): dict(members or {"#P1": {"name": "Mario", "role": "leader"}})}
        self.links = list(links)
        if not any(row.tag == "#P1" for row in self.links):
            self.links.append(chief_link())
        self.kv = {}

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

    def recruit_code(self, alias):
        return alias[-6:]

    async def recruit_row(self, alias):
        return None

    async def set_network_verified(self, alias, value):
        self.verified = bool(value)

    async def links_by_user(self, user_id):
        return [link for link in self.links if link.user_id == user_id]

    async def links_for_players(self, tags):
        return {link.tag: link for link in self.links if link.tag in set(tags)}

    async def bot_by_alias(self, alias):
        return None

    async def get_secret(self, kind):
        return None

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def add_log(self, alias, entry, at=None):
        return None


class FakeCoc:
    def __init__(self, player=None):
        self.data = player

    async def player(self, tag):
        return (dict(self.data), None) if self.data else (None, "not_found")


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []
        self.message = FakeMessage()

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeBot:
    username = "ClanBoardFuturoBot"

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self.sent.append((chat_id, text, reply_markup))


def private_update(user_id=9, query=None, text=None):
    message = FakeMessage()
    if text is not None:
        message.text = text
    return SimpleNamespace(callback_query=query, effective_message=message,
                           effective_chat=SimpleNamespace(id=user_id, type=ChatType.PRIVATE),
                           effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                          first_name="Toad"))


def context_for(store, coc=None, args=None, user_data=None):
    return SimpleNamespace(bot_data={"store": store, "coc": coc or FakeCoc(PLAYER), "bot_alias": "bot-1"},
                           args=list(args or []), user_data=dict(user_data or {}), bot=FakeBot())


def link(tag="#P9", user_id=9):
    return SimpleNamespace(alias="link-1", tag=tag, user_id=user_id, name="Toad", dm=True)


def buttons(keyboard):
    return [b.callback_data for row in keyboard.inline_keyboard for b in row]


def two_clans(store):
    async def active_clans(bot_alias=None):
        return [CLAN, OTHER]

    async def clan_by_alias(alias):
        return {CLAN.alias: CLAN, OTHER.alias: OTHER}.get(alias)

    store.state[(OTHER.alias, "members")] = {"#P1": {"name": "Mario", "role": "leader"}}
    store.active_clans = active_clans
    store.clan_by_alias = clan_by_alias
    return store


def test_apply_nel_gruppo_manda_in_privato():
    store = FakeStore()
    update = private_update()
    update.effective_chat = SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP)
    asyncio.run(recruit_tools.cmd_apply(update, context_for(store)))
    text, keyboard = update.effective_message.sent[0]
    assert "ClanBoardFuturoBot" in text
    assert keyboard.inline_keyboard[0][0].url.endswith("?start=apply_clan-1")


def test_chi_e_collegato_sceglie_il_suo_account():
    store = FakeStore(links=[link()])
    update = private_update()
    context = context_for(store)
    asyncio.run(recruit_tools.cmd_apply(update, context))
    keyboard = update.effective_message.sent[-1][1]
    assert buttons(keyboard) == ["rc:acc:0"]
    assert context.user_data["flow"]["kind"] == "apply"
    assert "#P9" not in repr(keyboard.inline_keyboard[0][0].callback_data)


def test_chi_non_e_collegato_scrive_il_tag_e_resta_non_verificato():
    store = FakeStore()
    context = context_for(store)
    update = private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context))
    assert context.user_data["flow"]["step"] == "tag"
    asyncio.run(recruit_tools.on_text(private_update(text=TYPED), context, context.user_data["flow"]))
    assert context.user_data["flow"]["step"] == "goals"
    assert context.user_data["flow"]["verified"] is False


def test_un_tag_storto_non_fa_andare_avanti():
    store = FakeStore()
    context = context_for(store)
    asyncio.run(recruit_tools.cmd_apply(private_update(), context))
    update = private_update(text="ciao")
    asyncio.run(recruit_tools.on_text(update, context, context.user_data["flow"]))
    assert update.effective_message.sent[-1][0] == IT.t("h.tag_invalid")
    assert context.user_data["flow"]["step"] == "tag"


def test_con_piu_clan_si_sceglie_a_bottoni():
    store = two_clans(FakeStore())
    context = context_for(store)
    update = private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context))
    keyboard = update.effective_message.sent[-1][1]
    assert buttons(keyboard) == ["rc:clan:0", "rc:clan:1"]
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=FakeQuery("rc:clan:1")), context))
    assert context.user_data["flow"]["clan"] == OTHER.alias
    assert context.user_data["flow"]["step"] == "tag"


def test_il_filtro_avvisa_e_non_rifiuta_da_solo():
    store = FakeStore(settings={"lang": "it", "tz": "Europe/Rome", "min_th": 16})
    context = context_for(store)
    asyncio.run(recruit_tools.cmd_apply(private_update(), context))
    tagged = private_update(text=TYPED)
    asyncio.run(recruit_tools.on_text(tagged, context, context.user_data["flow"]))
    assert context.user_data["flow"]["step"] == "below"
    body, keyboard = tagged.effective_message.sent[-1]
    assert "16" in body and "15" in body
    assert buttons(keyboard) == ["rc:anyway", "rc:stop"]
    query = FakeQuery("rc:anyway")
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=query), context))
    assert context.user_data["flow"]["below"] is True
    assert context.user_data["flow"]["step"] == "goals"


def test_chi_lascia_perdere_non_lascia_niente_dietro():
    store = FakeStore(settings={"lang": "it", "tz": "Europe/Rome", "min_th": 16})
    context = context_for(store)
    asyncio.run(recruit_tools.cmd_apply(private_update(), context))
    asyncio.run(recruit_tools.on_text(private_update(text=TYPED), context, context.user_data["flow"]))
    query = FakeQuery("rc:stop")
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=query), context))
    assert "flow" not in context.user_data
    assert query.message.sent[-1][0] == IT.t("recruit.apply.stopped")
    assert (CLAN.alias, recruit.KIND) not in store.state


def test_chi_e_gia_nel_clan_non_si_candida():
    store = FakeStore(members={"#P9": {"name": "Toad", "role": "member"}}, links=[link()])
    update = private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context_for(store)))
    assert IT.t("recruit.apply.already_member") in update.effective_message.sent[-1][0]


def test_una_sola_candidatura_in_sospeso_per_persona():
    store = FakeStore(links=[link()])
    state, _ = recruit.add(recruit.state_of(None), "#P9", SNAP, 9, True, [], False, NOW)
    asyncio.run(store.set_state(CLAN.alias, recruit.KIND, state))
    update = private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context_for(store)))
    assert IT.t("recruit.apply.already_pending") in update.effective_message.sent[-1][0]


def test_la_scheda_arriva_nel_feed_dei_capi():
    store = FakeStore(links=[link(), link(tag="#P1", user_id=5)])
    context = context_for(store)
    update = private_update()
    asyncio.run(recruit_tools.cmd_apply(update, context))
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=FakeQuery("rc:acc:0")), context))
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=FakeQuery("rc:g:war")), context))
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=FakeQuery("rc:send")), context))
    state = recruit.state_of(store.state[(CLAN.alias, recruit.KIND)])
    app = recruit.pending(state)[0]
    assert app["tag"] == "#P9" and app["verified"] is True and app["goals"] == ["war"]
    saved = store.kv.get(feed.key_of(CLAN.alias, 5)) or {}
    righe = [row["text"] for row in saved.get("rows") or []]
    assert len(righe) == 1 and "Toad" in righe[0] and "TH15" in righe[0]
    assert [chat_id for chat_id, _, _ in context.bot.sent] == []
    assert "flow" not in context.user_data


def test_gli_obiettivi_si_accendono_e_si_spengono():
    store = FakeStore(links=[link()])
    context = context_for(store)
    asyncio.run(recruit_tools.cmd_apply(private_update(), context))
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=FakeQuery("rc:acc:0")), context))
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=FakeQuery("rc:g:capital")), context))
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=FakeQuery("rc:g:war")), context))
    assert context.user_data["flow"]["goals"] == ["war", "capital"]
    query = FakeQuery("rc:g:war")
    asyncio.run(recruit_tools.on_apply_callback(private_update(query=query), context))
    assert context.user_data["flow"]["goals"] == ["capital"]
    assert buttons(query.edits[-1][1]) == ["rc:g:war", "rc:g:cwl", "rc:g:capital", "rc:g:calm", "rc:send"]


def test_la_scheda_dice_quando_non_e_verificata_e_quando_e_sotto_requisito():
    app = {"id": "1", "tag": "#P9", "verified": False, "below": True, "goals": ["war", "capital"],
           "snap": SNAP, "state": "pending", "ts": NOW.timestamp()}
    text = recruit_cards.applicant_card(IT, app, "Futuro", 16)
    assert IT.t("recruit.card.unverified") in text and IT.t("recruit.card.below", th=16) in text
    assert "Toad" in text and "4100" in text.replace(".", "")
    assert IT.t("recruit.card.pref", pref=IT.t("me.pref_in")) in text
    assert len(text) <= 4000


def test_il_link_al_clan_e_quello_del_gioco():
    assert recruit_cards.clan_link(IT, CLAN.tag) == (
        "https://link.clashofclans.com/it?action=OpenClanProfile&tag=%23CLAN1")


def test_il_codice_del_clan_e_cieco_e_stabile(tmp_path):
    store = Store(Vault(tmp_path))
    code = store.recruit_code(CLAN.alias)
    assert len(code) == 6 and code == store.recruit_code(CLAN.alias)
    assert code != store.recruit_code(OTHER.alias)
    assert CLAN.alias not in code


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("cmd.apply", "cmd.applications", "recruit.apply.title", "recruit.apply.intro",
                "recruit.apply.private", "recruit.apply.req", "recruit.apply.req_any",
                "recruit.apply.ask_tag", "recruit.apply.pick_account", "recruit.apply.pick_clan",
                "recruit.apply.already_member", "recruit.apply.already_pending",
                "recruit.apply.goals", "recruit.apply.goal.war", "recruit.apply.goal.cwl",
                "recruit.apply.goal.capital", "recruit.apply.goal.calm", "recruit.apply.btn_send",
                "recruit.apply.sent", "recruit.apply.below", "recruit.apply.btn_anyway",
                "recruit.apply.btn_stop", "recruit.apply.stopped", "recruit.apply.no_clan",
                "recruit.card.title", "recruit.card.verified", "recruit.card.unverified",
                "recruit.card.below", "recruit.card.goals", "recruit.card.clan",
                "recruit.card.no_clan", "recruit.card.numbers", "recruit.card.heroes",
                "recruit.btn_accept", "recruit.btn_reject"):
        assert key in EN, key


def test_il_comando_e_agganciato():
    assert ("apply", ["candidati"]) in handlers.COMMANDS
    assert handlers.HANDLERS["apply"] is recruit_tools.cmd_apply
