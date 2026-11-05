import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from clashbot import __main__ as cli
from clashbot import delivery, events_registry, feed, integrations, leaders
from clashbot import poller as poller_mod
from clashbot import settings as settings_mod

NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")


class FakeStore:
    def __init__(self, state=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.failures = []
        self.links = []
        self.updated = []
        self.kv = {}

    async def bot_by_alias(self, alias):
        return None

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def links_for_players(self, tags):
        if self.links:
            return {link.tag: link for link in self.links if link.tag in set(tags)}
        return {tag: SimpleNamespace(tag=tag, user_id=700 + n, name=tag, dm=True)
                for n, tag in enumerate(sorted(tags))}

    async def mark_failure(self, alias):
        self.failures.append(alias)
        return {"failures": len(self.failures), "active": len(self.failures) < 3}

    async def links_by_user(self, user_id):
        return [link for link in self.links if link.user_id == int(user_id)]

    async def update_link(self, link):
        self.updated.append(link)


class FakeBot:
    def __init__(self, fail=False, error=None, fail_times=None):
        self.sent = []
        self.error = error or (TelegramError("rifiutato") if fail else None)
        self.left = fail_times

    async def send_message(self, chat_id, text, message_thread_id=None, disable_notification=False):
        if self.error is not None and (self.left is None or self.left > 0):
            if self.left is not None:
                self.left -= 1
            raise self.error
        self.sent.append((chat_id, text, message_thread_id, disable_notification))


def members_store():
    return FakeStore({(CLAN.alias, "members"): {
        "#P1": {"name": "Mario", "role": "leader"},
        "#P2": {"name": "Luigi", "role": "coLeader"},
        "#P3": {"name": "Toad", "role": "member"},
    }})


def test_il_pacchetto_e_i_suoi_eventi_sono_nel_registro():
    assert "integrations" in events_registry.PACKS
    for event in integrations.EVENTS:
        entry = events_registry.EVENTS[event]
        assert entry["pack"] == integrations.PACK
        assert entry["default"] in entry["allowed"]
        assert set(entry["allowed"]) <= set(events_registry.DESTINATIONS)
        assert entry["intensity"] is None


def test_il_pacchetto_e_acceso_in_tutti_i_preset_e_dopo_la_migrazione():
    for preset in settings_mod.PRESETS.values():
        assert preset["packs"]["integrations"] is True
    migrated = settings_mod.migrate({"defenses": True, "agenda": True, "movements": True})
    assert settings_mod.pack_on(settings_mod.effective(migrated), "integrations") is True


def test_le_chiavi_del_blocco_sopravvivono_alla_migrazione():
    stored = {"twitch": {"channel": "capoclan", "members": {"#P3": "toad"}}}
    conf = settings_mod.effective(settings_mod.migrate(stored))
    assert integrations.block(conf, "twitch")["channel"] == "capoclan"
    assert integrations.block(conf, "twitch")["members"] == {"#P3": "toad"}
    assert integrations.block(settings_mod.effective({}), "twitch") == {}
    assert integrations.block({"twitch": "rotto"}, "twitch") == {}


def test_il_calendario_non_ha_piu_un_interruttore_suo_nelle_impostazioni():
    conf = settings_mod.migrate({"ics": {"public": True, "token": "g1"}})
    assert "ics" not in conf and "ics" not in settings_mod.DEFAULTS
    assert settings_mod.web_conf(conf)["ics"] is False
    assert settings_mod.web_conf({"web": {"ics": True}})["ics"] is True


def test_send_event_nel_gruppo_e_nel_topic():
    store, bot = members_store(), FakeBot()
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.bridge", "ciao")) == 1
    assert bot.sent == [(101, "ciao", None, False)]
    topic = settings_mod.effective({"routes": {"integrations.bridge": {"to": "topic"}},
                                    "topics": {"integrations": 44}})
    asyncio.run(integrations.send_event(store, bot, CLAN, topic, "integrations.bridge", "nel topic"))
    assert bot.sent[-1] == (101, "nel topic", 44, False)


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_send_event_nel_feed_dei_soli_capi_e_co_capi():
    store, bot = members_store(), FakeBot()
    conf = settings_mod.effective({})
    sent = asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.notice", "guasto"))
    assert sent == 2 and bot.sent == []
    assert feed_rows(store, 700) == ["guasto"] and feed_rows(store, 701) == ["guasto"]
    assert feed_rows(store, 702) == []


def test_send_event_tace_quando_e_spento_o_senza_testo_o_senza_bot():
    store = members_store()
    off = settings_mod.effective({"packs": {"integrations": False}})
    assert asyncio.run(integrations.send_event(store, FakeBot(), CLAN, off, "integrations.bridge", "x")) == 0
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.send_event(store, FakeBot(), CLAN, conf, "integrations.bridge", "")) == 0
    assert asyncio.run(integrations.send_event(store, None, CLAN, conf, "integrations.bridge", "x")) == 0
    assert asyncio.run(integrations.send_event(store, FakeBot(fail=True), CLAN, conf,
                                               "integrations.bridge", "x")) == 0


def test_send_event_silenzioso_passa_il_silenzio_a_telegram():
    store, bot = members_store(), FakeBot()
    conf = settings_mod.effective({})
    asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.twitch_live", "diretta", silent=True))
    assert bot.sent == [(101, "diretta", None, True)]


def test_un_flood_wait_si_riaspetta_invece_di_perdere_il_messaggio(monkeypatch):
    attese = []

    async def senza_dormire(seconds):
        attese.append(seconds)

    monkeypatch.setattr(delivery.asyncio, "sleep", senza_dormire)
    store, bot = members_store(), FakeBot(error=RetryAfter(3), fail_times=1)
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf,
                                               "integrations.twitch_live", "diretta")) == 1
    assert attese == [4] and bot.sent == [(101, "diretta", None, False)]


def test_una_chat_vietata_conta_fra_i_guasti_del_clan():
    store, bot = members_store(), FakeBot(error=Forbidden("bloccato"))
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.bridge", "x")) == 0
    assert store.failures == [CLAN.alias]


def test_una_chat_sparita_conta_fra_i_guasti_del_clan():
    store, bot = members_store(), FakeBot(error=BadRequest("Bad Request: chat not found"))
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.bridge", "x")) == 0
    assert store.failures == [CLAN.alias]
    store, bot = members_store(), FakeBot(error=BadRequest("message text is empty"))
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.bridge", "x")) == 0
    assert store.failures == []


def test_un_capo_che_ha_bloccato_il_bot_legge_lo_stesso_nel_feed():
    store, bot = members_store(), FakeBot(error=Forbidden("bloccato"))
    store.links = [SimpleNamespace(tag="#P1", user_id=700, name="Mario", dm=True, lang=None)]
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.notice", "guasto")) == 1
    assert store.links[0].dm is True and store.updated == []
    assert feed_rows(store, 700) == ["guasto"] and store.failures == []


def test_ai_capi_coi_privati_spenti_il_feed_arriva_lo_stesso():
    store, bot = members_store(), FakeBot()
    store.links = [SimpleNamespace(tag="#P1", user_id=700, name="Mario", dm=False, lang=None),
                   SimpleNamespace(tag="#P2", user_id=701, name="Luigi", dm=True, lang=None)]
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.notice", "guasto")) == 2
    assert bot.sent == []
    assert feed_rows(store, 700) == ["guasto"] and feed_rows(store, 701) == ["guasto"]


def test_di_notte_l_avviso_che_invecchia_parte_muto_invece_che_in_coda(monkeypatch):
    store, bot = members_store(), FakeBot()
    conf = settings_mod.effective({"tz": "UTC", "quiet": [23, 7]})
    monkeypatch.setattr(leaders, "now_utc", lambda: NOW.replace(hour=23, minute=30))
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.twitch_live",
                                               "diretta", silent=True)) == 1
    assert bot.sent == [(101, "diretta", None, True)]
    assert (CLAN.alias, "queue") not in store.state


def test_di_notte_quello_che_puo_aspettare_resta_nella_coda_di_sempre(monkeypatch):
    store, bot = members_store(), FakeBot()
    conf = settings_mod.effective({"tz": "UTC", "quiet": [23, 7]})
    monkeypatch.setattr(leaders, "now_utc", lambda: NOW.replace(hour=23, minute=30))
    assert asyncio.run(integrations.send_event(store, bot, CLAN, conf, "integrations.bridge", "ciao")) == 1
    assert bot.sent == [] and (CLAN.alias, "queue") in store.state


def test_il_blocco_non_ha_un_instradamento_suo(monkeypatch):
    passato = []

    async def finto(store, bot, clan, conf, event, text, reply_markup=None, now=None, silent=False):
        passato.append((event, text, silent))
        return 3

    monkeypatch.setattr(leaders, "notify", finto)
    partiti = asyncio.run(integrations.send_event(None, None, CLAN, {}, "integrations.bridge", "x", silent=True))
    assert partiti == 3 and passato == [("integrations.bridge", "x", True)]


def test_la_consegna_e_una_sola_per_il_poller_e_per_il_blocco():
    assert poller_mod.delivery is delivery and leaders.delivery is delivery
    assert delivery.gone(BadRequest("Bad Request: chat not found")) is True
    assert delivery.gone(BadRequest("group chat was upgraded to a supergroup chat")) is True
    assert delivery.gone(BadRequest("message text is empty")) is False


class PollerBot:
    def __init__(self, error=None, only_thread=None):
        self.sent = []
        self.error = error
        self.only_thread = only_thread

    async def send_message(self, chat_id, text, **kw):
        if self.error is not None and (self.only_thread is None
                                       or kw.get("message_thread_id") == self.only_thread):
            raise self.error
        self.sent.append((chat_id, text, kw))
        return SimpleNamespace(message_id=100 + len(self.sent))


def poller_for(bot, store=None):
    store = store or members_store()
    supervisor = SimpleNamespace(bot=lambda alias: bot if alias == CLAN.bot_alias else None,
                                 running=lambda: [CLAN.bot_alias], default_alias=CLAN.bot_alias,
                                 owner_bot=lambda: bot)
    return poller_mod.Poller(supervisor, store, None), store


def test_il_poller_non_ha_una_consegna_sua_ma_passa_da_delivery(monkeypatch):
    visti = []

    async def finta_chat(store, bot, clan, text, **kw):
        visti.append(("gruppo", text, kw))
        return True

    monkeypatch.setattr(delivery, "to_chat", finta_chat)
    poller, _ = poller_for(PollerBot())
    assert asyncio.run(poller.send(CLAN, "ciao", 44, quiet=True)) is True
    dove, testo, parole = visti[0]
    assert (dove, testo) == ("gruppo", "ciao")
    assert parole["thread_id"] == 44 and parole["silent"] is True
    assert "link_preview_options" in parole["extra"]


def test_i_guasti_del_clan_li_conta_una_sola_gestione_anche_dal_poller():
    poller, store = poller_for(PollerBot(error=Forbidden("bloccato")))
    assert asyncio.run(poller.send(CLAN, "ciao")) is False
    assert store.failures == [CLAN.alias]
    poller, store = poller_for(PollerBot(error=BadRequest("Bad Request: chat not found")))
    assert asyncio.run(poller.send(CLAN, "ciao")) is False
    assert store.failures == [CLAN.alias]
    poller, store = poller_for(PollerBot(error=BadRequest("message text is empty")))
    assert asyncio.run(poller.send(CLAN, "ciao")) is False
    assert store.failures == []


def test_il_poller_non_ha_piu_una_strada_privata():
    poller, _ = poller_for(PollerBot())
    assert not hasattr(poller, "send_dm")
    assert not hasattr(delivery, "to_user") and not hasattr(delivery, "dm_open")


def test_il_topic_sparito_si_recupera_ancora_sulla_strada_del_poller():
    bot = PollerBot(error=BadRequest("Bad Request: message thread not found"), only_thread=44)
    poller, store = poller_for(bot)
    asyncio.run(store.set_state(CLAN.alias, "settings", {"topics": {"integrations": 44}}))
    assert asyncio.run(poller.send(CLAN, "ciao", 44)) is True
    assert [parole.get("message_thread_id") for _, _, parole in bot.sent] == [None]
    assert store.failures == [] and store.state[(CLAN.alias, "settings")]["topics"] == {}


def test_l_avviso_di_guasto_parte_una_volta_al_giorno_e_si_azzera_a_mano():
    store, bot = members_store(), FakeBot()
    conf = settings_mod.effective({})
    assert asyncio.run(integrations.notice(store, bot, CLAN, conf, "discord_token", "token", NOW)) == 2
    assert asyncio.run(integrations.notice(store, bot, CLAN, conf, "discord_token", "token", NOW)) == 0
    later = NOW.replace(day=15, hour=10)
    assert asyncio.run(integrations.notice(store, bot, CLAN, conf, "discord_token", "token", later)) == 2
    asyncio.run(integrations.clear_notice(store, CLAN.alias, "discord_token"))
    assert asyncio.run(integrations.notice(store, bot, CLAN, conf, "discord_token", "token", later)) == 2


def test_gli_avvisi_non_calpestano_le_altre_chiavi_di_notices():
    store, bot = members_store(), FakeBot()
    asyncio.run(store.set_state(CLAN.alias, "notices", {"private": True}))
    asyncio.run(integrations.notice(store, bot, CLAN, settings_mod.effective({}), "twitch_keys", "x", NOW))
    stored = store.state[(CLAN.alias, "notices")]
    assert stored["private"] is True and "int:twitch_keys" in stored


def test_i_segreti_nuovi_esistono_e_solo_il_client_id_e_in_chiaro():
    assert {"twitch_client_id", "twitch_client_secret"} <= set(cli.SECRET_KINDS)
    assert "twitch_client_id" in cli.PLAIN_KINDS
    assert "twitch_client_secret" not in cli.PLAIN_KINDS
    assert not {"twitch_client_id", "twitch_client_secret"} & set(cli.TOKEN_KINDS)
    assert {"twitch_client_id", "twitch_client_secret"} <= set(cli.CLEARABLE_KINDS)


def test_l_indirizzo_pubblico_e_un_segreto_solo_site_base():
    for group in (cli.SECRET_KINDS, cli.PLAIN_KINDS, cli.CLEARABLE_KINDS):
        assert "web_url" not in group
        assert "site_base" in group


def test_le_credenziali_twitch_hanno_la_lunghezza_che_twitch_consegna():
    assert cli.TWITCH_KEY_LEN == 30
    for good in ("abcdefghij0123456789abcdef1234", "A" * cli.TWITCH_KEY_LEN):
        assert cli.valid_twitch_key(good), good
    for bad in ("", None, "corta", "a" * 29, "a" * 31, "a" * 29 + " ", "a" * 29 + "-", "à" * 30):
        assert not cli.valid_twitch_key(bad), bad


class SecretStore:
    def __init__(self):
        self.saved = {}

    async def set_secret(self, kind, value):
        self.saved[kind] = value
        return "sec-1"


def test_store_secret_rifiuta_i_valori_sbagliati_senza_ripeterli():
    store = SecretStore()
    for kind, value in (("twitch_client_id", "corta"), ("twitch_client_secret", "a" * 31),
                        ("site_base", "http://esempio.it")):
        with pytest.raises(SystemExit) as refused:
            asyncio.run(cli.store_secret(store, kind, value))
        assert value not in str(refused.value) and kind in str(refused.value)
    assert store.saved == {}
    asyncio.run(cli.store_secret(store, "twitch_client_id", "abcdefghij0123456789abcdef1234"))
    asyncio.run(cli.store_secret(store, "twitch_client_secret", "0123456789abcdefghij0123456789"))
    asyncio.run(cli.store_secret(store, "site_base", "https://clanboard.example"))
    assert set(store.saved) == {"twitch_client_id", "twitch_client_secret", "site_base"}
