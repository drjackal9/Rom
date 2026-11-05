import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telegram.constants import ChatType
from telegram.error import TelegramError

from clashbot import acts, discipline, feed, i18n, mydata, privacy, privacy_cards, privacy_tools
from clashbot import reports, retention
from clashbot.db import REPORTS_KEY, Store

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1",
                       active=True)
OTHER = SimpleNamespace(alias="clan-2", chat_id=202, tag="#CLAN2", name="Altrove",
                        bot_alias="bot-2", active=True)


def link(tag="#P1", name="Mario", user_id=7, dm=True, lang="it"):
    return SimpleNamespace(alias=f"link-{tag}", user_id=user_id, tag=tag, name=name, dm=dm, lang=lang)


class FakeVault:
    def blind(self, label, value):
        return f"{label}-{value}-0123456789abcdef"


class FakeStore:
    def __init__(self, links=(), state=None, former=(), clans=None):
        self.vault = FakeVault()
        self.links = list(links)
        self.state = dict(state or {})
        self.former = {tuple(pair) for pair in former}
        self.clans = list(clans or [CLAN])
        self.kv = {}
        self.ttls = {}

    async def drop_former(self, alias, tag):
        if (alias, tag) not in self.former:
            return False
        self.former.discard((alias, tag))
        return True

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = obj

    async def recent_wars(self, alias, limit=10):
        return []

    async def links_by_user(self, user_id):
        return [row for row in self.links if row.user_id == user_id]

    async def unlink(self, user_id, tag):
        self.links = [row for row in self.links if row.tag != tag]
        return True

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return next((row for row in self.clans if row.chat_id == chat_id), None)

    async def clan_by_alias(self, alias):
        return next((row for row in self.clans if row.alias == alias), None)

    async def active_clans(self, bot_alias=None):
        return list(self.clans)

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj
        self.ttls[key] = ttl

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def report_add(self, clan_alias, user_id, reason, now):
        return await Store.report_add(self, clan_alias, user_id, reason, now)

    async def report_forget(self, clan_alias, user_id):
        return await Store.report_forget(self, clan_alias, user_id)


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))
        return SimpleNamespace(message_id=1)


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeBot:
    def __init__(self, fail=False):
        self.username = "ClanBoardFuturoBot"
        self.documents = []
        self.fail = fail

    async def send_document(self, chat_id, document=None, **kw):
        if self.fail:
            raise TelegramError("chiuso")
        self.documents.append((chat_id, document))


def update_for(chat_type=ChatType.PRIVATE, chat_id=7, user_id=7, data=None):
    return SimpleNamespace(
        callback_query=FakeQuery(data) if data else None,
        effective_message=FakeMessage(),
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"),
    )


def context_for(store, bot=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=[], user_data={}, bot=bot or FakeBot())


def store_with_data():
    return FakeStore(links=[link()], state={
        ("clan-1", "settings"): {"lang": "it", "tz": "Europe/Rome"},
        ("clan-1", "members"): {"#P1": {"name": "Mario", "role": "leader", "th": 15,
                                        "trophies": 5000, "donations": 900, "received": 100}},
    })


def test_mydata_in_un_gruppo_non_mostra_niente_e_rimanda_in_privato():
    store = store_with_data()
    update = update_for(chat_type=ChatType.SUPERGROUP, chat_id=101)
    asyncio.run(privacy_tools.cmd_mydata(update, context_for(store)))
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("privacy.private_only", bot="ClanBoardFuturoBot")
    assert markup is None and "#P1" not in text


def test_mydata_manda_la_scheda_i_bottoni_e_il_file():
    store = store_with_data()
    bot = FakeBot()
    update = update_for()
    asyncio.run(privacy_tools.cmd_mydata(update, context_for(store, bot)))
    text, markup = update.effective_message.sent[0]
    assert IT.t("privacy.title") in text and "#P1" in text
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == ["p:hide", "p:forget"]
    chat_id, document = bot.documents[0]
    assert chat_id == 7 and document.filename == privacy_cards.FILENAME
    payload = json.loads(document.input_file_content.decode())
    assert payload["accounts"][0]["tag"] == "#P1"


def store_with_twitch():
    store = store_with_data()
    store.state[("clan-1", "settings")] = {
        "lang": "it", "tz": "Europe/Rome",
        "twitch": {"channel": "capoclan", "members": {"#P1": "mariolive", "#P9": "altro"}}}
    return store


def test_il_canale_twitch_del_membro_sta_in_mydata_e_sparisce_con_forgetme():
    store = store_with_twitch()
    bot = FakeBot()
    asyncio.run(privacy_tools.cmd_mydata(update_for(), context_for(store, bot)))
    payload = json.loads(bot.documents[0][1].input_file_content.decode())
    assert payload["accounts"][0]["twitch"] == "mariolive"
    done = update_for(data="p:forget:yes")
    asyncio.run(privacy_tools.on_privacy_callback(done, context_for(store)))
    saved = store.state[("clan-1", "settings")]["twitch"]
    assert saved["members"] == {"#P9": "altro"} and saved["channel"] == "capoclan"
    assert privacy.twitch_members({"settings": store.state[("clan-1", "settings")]}) == \
        {"#P9": "altro"}


def test_chi_non_ha_un_canale_non_se_lo_vede_inventare():
    store = store_with_data()
    bot = FakeBot()
    asyncio.run(privacy_tools.cmd_mydata(update_for(), context_for(store, bot)))
    payload = json.loads(bot.documents[0][1].input_file_content.decode())
    assert payload["accounts"][0]["twitch"] is None
    assert "settings" in privacy.BUNDLE_KINDS


def test_il_secondo_export_nella_stessa_ora_viene_rimandato():
    store = store_with_data()
    bot = FakeBot()
    asyncio.run(privacy_tools.cmd_mydata(update_for(), context_for(store, bot)))
    second = update_for()
    asyncio.run(privacy_tools.cmd_mydata(second, context_for(store, bot)))
    assert second.effective_message.sent[-1][0] == IT.t("privacy.throttle", n=60)
    assert len(bot.documents) == 1
    assert store.ttls[privacy.user_key(store, "md", 7)] == privacy_tools.EXPORT_COOLDOWN


def test_chi_non_e_collegato_riceve_l_invito_a_collegarsi():
    from clashbot import render
    update = update_for()
    asyncio.run(privacy_tools.cmd_mydata(update, context_for(FakeStore())))
    assert update.effective_message.sent[-1][0] == render.not_linked_me(IT, "ClanBoardFuturoBot")


def test_se_il_file_non_parte_lo_diciamo():
    store = store_with_data()
    update = update_for()
    asyncio.run(privacy_tools.cmd_mydata(update, context_for(store, FakeBot(fail=True))))
    assert update.effective_message.sent[-1][0] == IT.t("privacy.file_failed")
    assert privacy.user_key(store, "md", 7) in store.kv


def test_il_tetto_scatta_solo_dopo_che_la_scheda_e_partita():
    store = store_with_data()
    muto = update_for()

    async def chiuso(text, reply_markup=None, **kw):
        raise TelegramError("chiuso")

    muto.effective_message.reply_text = chiuso
    with pytest.raises(TelegramError):
        asyncio.run(privacy_tools.cmd_mydata(muto, context_for(store)))
    assert privacy.user_key(store, "md", 7) not in store.kv
    dopo = update_for()
    asyncio.run(privacy_tools.cmd_mydata(dopo, context_for(store)))
    assert IT.t("privacy.title") in dopo.effective_message.sent[0][0]
    assert store.ttls[privacy.user_key(store, "md", 7)] == privacy_tools.EXPORT_COOLDOWN


def test_la_scheda_della_cancellazione_dice_che_il_diario_dei_capi_resta():
    testo = privacy_cards.forget_card(IT)
    assert IT.t("privacy.forget.body") in testo and IT.t("privacy.forget.log") in testo
    assert str(retention.LEADER_LOG_KEEP) in IT.t("privacy.forget.log")
    with (i18n.LOCALE_DIR / "en.json").open(encoding="utf-8") as handle:
        posto = list(json.load(handle)).index("privacy.forget.log")
    for code in sorted(i18n.LANGUAGES):
        with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
            catalogo = json.load(handle)
        assert catalogo["privacy.forget.log"].strip(), code
        assert list(catalogo).index("privacy.forget.log") == posto, code


def test_i_bottoni_tolgono_e_rimettono_nelle_classifiche():
    store = store_with_data()
    hide = update_for(data="p:hide")
    asyncio.run(privacy_tools.on_privacy_callback(hide, context_for(store)))
    assert asyncio.run(privacy.excluded(store, "clan-1")) == {"#P1"}
    assert IT.t("privacy.hidden_done") in hide.callback_query.edits[-1][0]
    show = update_for(data="p:show")
    asyncio.run(privacy_tools.on_privacy_callback(show, context_for(store)))
    assert asyncio.run(privacy.excluded(store, "clan-1")) == set()
    assert IT.t("privacy.shown_done") in show.callback_query.edits[-1][0]


def test_forgetme_chiede_conferma_e_poi_cancella():
    store = store_with_data()
    ask = update_for()
    asyncio.run(privacy_tools.cmd_forgetme(ask, context_for(store)))
    text, markup = ask.effective_message.sent[-1]
    assert IT.t("privacy.forget.title") in text
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == ["p:forget:yes", "p:forget:no"]
    done = update_for(data="p:forget:yes")
    asyncio.run(privacy_tools.on_privacy_callback(done, context_for(store)))
    assert store.links == []
    assert asyncio.run(privacy.excluded(store, "clan-1")) == {"#P1"}
    assert IT.t("privacy.forget.stays") in done.callback_query.edits[-1][0]


def test_la_scheda_rimanda_a_mybots_per_il_bot_che_resta():
    from clashbot import bot as bot_mod
    assert "mybots" in bot_mod.CONSOLE_PROFILE[0]
    for code in sorted(i18n.LANGUAGES):
        with (i18n.LOCALE_DIR / f"{code}.json").open(encoding="utf-8") as handle:
            assert "/mybots" in json.load(handle)["privacy.forget.stays"], code
    store = store_with_data()
    done = update_for(data="p:forget:yes")
    asyncio.run(privacy_tools.on_privacy_callback(done, context_for(store)))
    assert "/mybots" in done.callback_query.edits[-1][0]


def test_annullare_la_cancellazione_non_tocca_niente():
    store = store_with_data()
    update = update_for(data="p:forget:no")
    asyncio.run(privacy_tools.on_privacy_callback(update, context_for(store)))
    assert store.links and update.callback_query.edits[-1][0] == IT.t("h.cancelled")


def test_il_bottone_di_chi_si_e_scollegato_apre_la_scheda_non_un_avviso():
    from clashbot import render
    update = update_for(data="p:hide")
    asyncio.run(privacy_tools.on_privacy_callback(update, context_for(FakeStore())))
    assert update.callback_query.answers == [(None, False)]
    assert update.callback_query.edits[-1][0] == render.not_linked_me(IT, "ClanBoardFuturoBot")


def test_chi_non_ha_piu_niente_lo_sente_dire():
    update = update_for()
    asyncio.run(privacy_tools.cmd_forgetme(update, context_for(FakeStore())))
    assert update.effective_message.sent[-1][0] == IT.t("privacy.forget.nothing")


class FakeApp:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)


def test_i_comandi_e_i_bottoni_sono_agganciati_al_bot():
    from clashbot import handlers
    assert ("mydata", ["mieidati"]) in handlers.COMMANDS
    assert ("forgetme", ["dimenticami"]) in handlers.COMMANDS
    assert handlers.HANDLERS["mydata"] is privacy_tools.cmd_mydata
    assert handlers.HANDLERS["forgetme"] is privacy_tools.cmd_forgetme
    app = FakeApp()
    handlers.register(app)
    commands, patterns = set(), set()
    for handler in app.handlers:
        commands |= set(getattr(handler, "commands", []) or [])
        if getattr(handler, "pattern", None) is not None:
            patterns.add(handler.pattern.pattern)
    assert {"mydata", "mieidati", "forgetme", "dimenticami"} <= commands
    assert "^p:" in patterns


def store_with_everything():
    store = store_with_data()
    store.state[("clan-1", "members")]["#P2"] = {"name": "Luigi", "role": "coLeader", "th": 15,
                                                 "trophies": 4800, "donations": 500,
                                                 "received": 200}
    store.state[("clan-1", "members")]["#P9"] = {"name": "Altro", "role": "member", "th": 13,
                                                 "trophies": 4000, "donations": 100,
                                                 "received": 50}
    store.state[("clan-1", discipline.STATE)] = [
        {"id": "w1", "tag": "#P1", "name": "Mario", "war": "g1", "missed": 1, "at": 1, "by": "#P2"},
        {"id": "w2", "tag": "#P9", "name": "Altro", "war": "g1", "missed": 2, "at": 2, "by": "#P2"}]
    asyncio.run(feed.add(store, "clan-1", 7, "goal.done", "Roba mia", NOW))
    asyncio.run(feed.add(store, "clan-1", 9, "goal.done", "Roba sua", NOW))
    asyncio.run(store.report_add("clan-1", 7, "spam", NOW))
    asyncio.run(store.report_add("clan-1", 9, "scam", NOW))
    asyncio.run(store.kv_set(reports.flood_key("clan-1", 7), {"hits": [NOW.timestamp()]}))
    return store


def test_i_miei_dati_dall_app_sono_i_miei_e_non_quelli_degli_altri():
    store = store_with_everything()
    found = asyncio.run(mydata.bundle(store, "clan-1", 7, NOW))
    assert [row["tag"] for row in found["accounts"]] == ["#P1"]
    assert [row["tag"] for row in found["clans"]] == ["#CLAN1"]
    assert found["accounts"][0]["clan_row"]["name"] == "Mario"
    assert [row["by"] for row in found["warnings"]] == ["Luigi"]
    assert [row["missed"] for row in found["warnings"]] == [1]
    raw = json.dumps(found, ensure_ascii=False)
    assert "#P9" not in raw and "Altro" not in raw
    assert asyncio.run(mydata.bundle(store, "clan-9", 7, NOW)) is None


def store_with_two_clans():
    store = store_with_data()
    store.clans.append(OTHER)
    store.links.append(link(tag="#P5", name="Bowser"))
    store.state[("clan-2", "settings")] = {"lang": "it", "tz": "Europe/Rome"}
    store.state[("clan-2", "members")] = {"#P5": {"name": "Bowser", "role": "member", "th": 14,
                                                  "trophies": 4200, "donations": 300,
                                                  "received": 80}}
    store.state[("clan-1", discipline.STATE)] = [
        {"id": "w1", "tag": "#P5", "name": "Bowser", "war": "g0", "missed": 2, "at": 1, "by": "#P1"}]
    return store


def test_i_miei_dati_di_un_clan_non_parlano_del_mio_villaggio_in_un_altro_clan():
    store = store_with_two_clans()
    here = asyncio.run(mydata.bundle(store, "clan-1", 7, NOW))
    assert [row["tag"] for row in here["accounts"]] == ["#P1"]
    assert [row["tag"] for row in here["clans"]] == ["#CLAN1"]
    assert [row["missed"] for row in here["warnings"]] == [2]
    assert "#P5" not in json.dumps(here, ensure_ascii=False)
    assert "Bowser" not in json.dumps(here, ensure_ascii=False)
    there = asyncio.run(mydata.bundle(store, "clan-2", 7, NOW))
    assert [row["tag"] for row in there["accounts"]] == ["#P5"]
    assert [row["tag"] for row in there["clans"]] == ["#CLAN2"]
    assert there["warnings"] == []
    assert "#P1" not in json.dumps(there, ensure_ascii=False)
    assert "Mario" not in json.dumps(there, ensure_ascii=False)


def test_la_cancellazione_dall_app_porta_via_collegamento_novita_ammonizioni_e_segnalazioni():
    store = store_with_everything()
    counts = asyncio.run(mydata.forget(store, 7, NOW))
    assert store.links == []
    assert (counts["feed"], counts["warnings"], counts["reports"]) == (1, 1, 1)
    assert asyncio.run(feed.rows(store, "clan-1", 7)) == []
    assert [row["text"] for row in asyncio.run(feed.rows(store, "clan-1", 9))] == ["Roba sua"]
    assert [row["tag"] for row in store.state[("clan-1", discipline.STATE)]] == ["#P9"]
    assert [row["by"] for row in store.kv[f"{REPORTS_KEY}clan-1"]["rows"]] == [9]
    assert reports.flood_key("clan-1", 7) not in store.kv


def test_senza_conferma_dall_app_non_si_cancella_niente():
    store = store_with_everything()
    act = acts.Act(store=store, clan=CLAN, conf={}, kind="data.forget", body={"sure": "no"},
                   uid=7, tag="#P1", name="Mario", level=None, now=NOW, coc=None)
    assert asyncio.run(mydata.forget_act(act)) is False
    assert [row.tag for row in store.links] == ["#P1"]
    assert asyncio.run(feed.rows(store, "clan-1", 7))
    assert asyncio.run(mydata.forget_act(act._replace(body={"sure": mydata.SURE}))) is True
    assert store.links == []


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("privacy.title", "privacy.intro", "privacy.account", "privacy.in_clan",
                "privacy.alerts_on", "privacy.alerts_off",
                "privacy.hidden_on", "privacy.hidden_off", "privacy.counts", "privacy.titles", "privacy.note_yes",
                "privacy.file", "privacy.file_failed", "privacy.btn_hide", "privacy.btn_show", "privacy.btn_forget",
                "privacy.hidden_done", "privacy.shown_done", "privacy.private_only", "privacy.throttle",
                "privacy.no_clan", "privacy.forget.title", "privacy.forget.body", "privacy.forget.stays",
                "privacy.forget.btn_yes", "privacy.forget.done", "privacy.forget.nothing",
                "cmd.mydata", "cmd.forgetme"):
        assert key in EN, key
