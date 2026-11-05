import asyncio
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from telegram.constants import ChatType

from clashbot import i18n, integration_cards, integration_tools, twitch, twitch_jobs
from clashbot import settings as settings_mod

EN = json.load(open(i18n.LOCALE_DIR / "en.json", encoding="utf-8"))
IT = i18n.locale("it")
NOW = datetime(2026, 9, 14, 15, tzinfo=timezone.utc)
NIGHT = datetime(2026, 9, 15, 1, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")


class FakeStore:
    def __init__(self, state=None, secrets=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.secrets = dict(secrets or {})
        self.kv = {}

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def active_clans(self, bot_alias=None):
        return [CLAN]

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return CLAN if chat_id == CLAN.chat_id else None

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def links_for_players(self, tags):
        owners = {"#P1": 7, "#P3": 8}
        return {tag: SimpleNamespace(tag=tag, user_id=owners.get(tag, 700), name=tag, dm=True)
                for tag in tags}

    async def links_by_user(self, user_id):
        return [SimpleNamespace(tag="#P1" if user_id == 7 else "#P3", user_id=user_id,
                                name="Mario" if user_id == 7 else "Toad", dm=True)]

    async def bot_by_alias(self, alias):
        return None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, message_thread_id=None, disable_notification=False):
        self.sent.append((chat_id, text, disable_notification))


class FakePoller:
    def __init__(self, store, bot=None):
        self.store = store
        self.telegram = bot or FakeBot()
        self.twitch = None

    def served(self, owner):
        return True

    def bot_for(self, owner):
        return self.telegram


def stream(login, sid, title="Farm", game="Clash of Clans", name=None):
    return {"id": sid, "user_login": login, "user_name": name or login, "title": title, "game_name": game}


def api_with(routes, calls=None):
    def handler(request):
        (calls if calls is not None else []).append(str(request.url))
        for path, reply in routes:
            if request.url.path == path:
                return reply(request) if callable(reply) else reply
        return httpx.Response(404, json={})

    return twitch.TwitchApi("cid-1", "sec-1", transport=httpx.MockTransport(handler))


TOKEN_OK = ("/oauth2/token", httpx.Response(200, json={"access_token": "tok-1", "expires_in": 7200}))


def clan_store(settings=None, secrets=None):
    return FakeStore({(CLAN.alias, "settings"): settings or {"lang": "it", "tz": "Europe/Rome"},
                      (CLAN.alias, "members"): {"#P1": {"name": "Mario", "role": "leader"},
                                                "#P3": {"name": "Toad", "role": "member"}}},
                     secrets or {"twitch_client_id": "cid-1", "twitch_client_secret": "sec-1"})


def context_for(store, args=None):
    return SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"},
                           args=list(args or []), user_data={},
                           bot=SimpleNamespace(id=99, username="ClanBoardFuturoBot"))


class FakeMessage:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.texts.append(text)


def group_update(user_id=7):
    return SimpleNamespace(callback_query=None, effective_message=FakeMessage(),
                           effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.SUPERGROUP),
                           effective_user=SimpleNamespace(id=user_id, language_code="it", first_name="Mario"))


def test_normalize_login_accetta_nome_e_indirizzo():
    for raw, expected in (("CapoClan", "capoclan"), (" capo_clan ", "capo_clan"),
                          ("@capoclan", "capoclan"), ("https://twitch.tv/CapoClan", "capoclan"),
                          ("twitch.tv/capoclan/about", "capoclan")):
        assert twitch.normalize_login(raw) == expected, raw
    for bad in ("", None, "ab", "a" * 26, "capo clan", "capo-clan", "https://youtube.com/capoclan", "capò"):
        assert twitch.normalize_login(bad) is None, bad


def test_il_token_d_applicazione_si_prende_una_volta_e_resta_in_kv():
    calls, store = [], FakeStore()
    api = api_with([TOKEN_OK], calls)
    assert asyncio.run(api.app_token(store, NOW)) == "tok-1"
    assert asyncio.run(api.app_token(store, NOW)) == "tok-1"
    assert len(calls) == 1 and store.kv[twitch.TOKEN_KEY]["expires"] == NOW.timestamp() + 7200
    fresh = api_with([TOKEN_OK], calls)
    assert asyncio.run(fresh.app_token(store, NOW)) == "tok-1" and len(calls) == 1
    asyncio.run(api.close())
    asyncio.run(fresh.close())


def test_senza_credenziali_non_si_chiama_nessuno():
    api = twitch.TwitchApi(None, None)
    assert api.ready() is False
    assert asyncio.run(api.app_token(FakeStore(), NOW)) is None
    assert asyncio.run(api.streams(FakeStore(), ["a"], NOW)) == ({}, "no_token")
    asyncio.run(api.close())


def test_le_dirette_si_chiedono_a_gruppi_di_cento():
    calls = []
    logins = [f"c{n:03d}" for n in range(150)]

    def streams(request):
        asked = [value for key, value in request.url.params.multi_items() if key == "user_login"]
        assert len(asked) <= twitch.LOGINS_PER_CALL
        return httpx.Response(200, json={"data": [stream(asked[0], "s-" + asked[0])]})

    api = api_with([TOKEN_OK, ("/helix/streams", streams)], calls)
    live, error = asyncio.run(api.streams(FakeStore(), logins, NOW))
    assert error is None and set(live) == {"c000", "c100"}
    assert len([url for url in calls if "streams" in url]) == 2
    asyncio.run(api.close())


def test_un_401_butta_il_token_e_riprova_una_volta_sola():
    calls, store = [], FakeStore()
    state = {"n": 0}

    def streams(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(401, json={"message": "invalid"})
        return httpx.Response(200, json={"data": [stream("capoclan", "s-1")]})

    api = api_with([TOKEN_OK, ("/helix/streams", streams)], calls)
    live, error = asyncio.run(api.streams(store, ["capoclan"], NOW))
    assert error is None and live["capoclan"]["id"] == "s-1"
    assert len([url for url in calls if "token" in url]) == 2
    asyncio.run(api.close())


def test_rate_limit_e_guasti_non_scrivono_nulla():
    api = api_with([TOKEN_OK, ("/helix/streams", httpx.Response(429, json={}))])
    assert asyncio.run(api.streams(FakeStore(), ["capoclan"], NOW)) == ({}, "rate")
    asyncio.run(api.close())
    broken = api_with([TOKEN_OK, ("/helix/streams", httpx.Response(500, text="boom"))])
    assert asyncio.run(broken.streams(FakeStore(), ["capoclan"], NOW)) == ({}, "http_500")
    asyncio.run(broken.close())


def test_i_login_del_clan_sono_quelli_del_capo_piu_quelli_dei_membri():
    conf = settings_mod.effective({"twitch": {"channel": "CapoClan", "members": {"#P3": "toad", "#P4": "nope!"}}})
    assert twitch_jobs.channels(conf) == ["capoclan", "toad"]
    assert twitch_jobs.channels(settings_mod.effective({})) == []


def test_una_diretta_si_annuncia_una_volta_sola():
    store = clan_store({"lang": "it", "tz": "Europe/Rome", "twitch": {"channel": "capoclan"}})
    poller = FakePoller(store)
    live = {"capoclan": {"id": "s-1", "login": "capoclan", "name": "CapoClan",
                         "title": "Push in Leggenda", "game": "Clash of Clans"}}
    conf = settings_mod.effective(store.state[(CLAN.alias, "settings")])
    assert asyncio.run(twitch_jobs.announce(poller, CLAN, conf, ["capoclan"], live, NOW)) == 1
    assert "CapoClan" in poller.telegram.sent[0][1] and "twitch.tv/capoclan" in poller.telegram.sent[0][1]
    assert asyncio.run(twitch_jobs.announce(poller, CLAN, conf, ["capoclan"], live, NOW)) == 0
    assert store.state[(CLAN.alias, "twitch")] == {"live": {"capoclan": "s-1"}}
    di_nuovo = {"capoclan": dict(live["capoclan"], id="s-2")}
    assert asyncio.run(twitch_jobs.announce(poller, CLAN, conf, ["capoclan"], di_nuovo, NOW)) == 1
    assert asyncio.run(twitch_jobs.announce(poller, CLAN, conf, ["capoclan"], {}, NOW)) == 0
    assert store.state[(CLAN.alias, "twitch")] == {"live": {}}


def test_di_notte_l_avviso_parte_silenzioso():
    settings = {"lang": "it", "tz": "Europe/Rome", "quiet": [23, 7], "twitch": {"channel": "capoclan"}}
    store = clan_store(settings)
    poller = FakePoller(store)
    live = {"capoclan": {"id": "s-1", "login": "capoclan", "name": "CapoClan", "title": "", "game": ""}}
    conf = settings_mod.effective(settings)
    asyncio.run(twitch_jobs.announce(poller, CLAN, conf, ["capoclan"], live, NIGHT))
    assert poller.telegram.sent[0][2] is True


def test_il_giro_salta_i_clan_col_pacchetto_spento():
    store = clan_store({"lang": "it", "tz": "Europe/Rome", "packs": {"integrations": False},
                        "twitch": {"channel": "capoclan"}})
    assert asyncio.run(twitch_jobs.targets(FakePoller(store))) == []


USERS_OK = ("/helix/users", httpx.Response(200, json={"data": [{"id": "1", "login": "toad"}]}))
USERS_EMPTY = ("/helix/users", httpx.Response(200, json={"data": []}))


def patch_api(monkeypatch, routes=(TOKEN_OK, USERS_OK), ready=True):
    built = []

    async def factory(store):
        api = api_with(list(routes)) if ready else twitch.TwitchApi(None, None)
        built.append(api)
        return api

    monkeypatch.setattr(integration_tools, "twitch_api", factory)
    return built


def test_il_membro_imposta_solo_il_proprio_canale(monkeypatch):
    patch_api(monkeypatch)
    store = clan_store()
    update = group_update(user_id=9)
    asyncio.run(integration_tools.cmd_twitch(update, context_for(store, ["toad"])))
    saved = store.state[(CLAN.alias, "settings")]["twitch"]
    assert saved == {"members": {"#P3": "toad"}}
    assert IT.t("twitch.saved") in update.effective_message.texts[0]
    rifiutato = group_update(user_id=9)
    asyncio.run(integration_tools.cmd_twitch(rifiutato, context_for(store, ["clan", "altro"])))
    assert store.state[(CLAN.alias, "settings")]["twitch"] == saved
    assert IT.t("int.only") in rifiutato.effective_message.texts[0]


def test_il_capo_imposta_e_toglie_il_canale_del_clan(monkeypatch):
    patch_api(monkeypatch)
    store = clan_store()
    asyncio.run(integration_tools.cmd_twitch(group_update(), context_for(store, ["clan", "CapoClan"])))
    assert store.state[(CLAN.alias, "settings")]["twitch"]["channel"] == "capoclan"
    asyncio.run(integration_tools.cmd_twitch(group_update(), context_for(store, ["clan", "-"])))
    assert store.state[(CLAN.alias, "settings")]["twitch"]["channel"] is None


def test_un_canale_scritto_male_o_inesistente_viene_rifiutato(monkeypatch):
    patch_api(monkeypatch)
    store = clan_store()
    update = group_update()
    asyncio.run(integration_tools.cmd_twitch(update, context_for(store, ["clan", "no spazi"])))
    assert IT.t("twitch.invalid") in update.effective_message.texts[0]
    assert store.state[(CLAN.alias, "settings")].get("twitch") in (None, {})
    patch_api(monkeypatch, routes=(TOKEN_OK, USERS_EMPTY))
    ignoto = group_update()
    asyncio.run(integration_tools.cmd_twitch(ignoto, context_for(store, ["clan", "fantasma"])))
    assert IT.t("twitch.unknown") in ignoto.effective_message.texts[0]
    assert store.state[(CLAN.alias, "settings")].get("twitch") in (None, {})


def test_la_card_dice_quando_il_gestore_non_ha_ancora_le_credenziali(monkeypatch):
    patch_api(monkeypatch, ready=False)
    store = clan_store(secrets={})
    update = group_update()
    asyncio.run(integration_tools.cmd_twitch(update, context_for(store)))
    assert IT.t("twitch.not_ready") in update.effective_message.texts[0]


def test_la_riga_del_canale_compare_sotto_support_solo_se_c_e():
    conf = settings_mod.effective({"twitch": {"channel": "capoclan"}})
    assert "twitch.tv/capoclan" in integration_cards.support_extra(IT, conf)
    assert integration_cards.support_extra(IT, settings_mod.effective({})) == ""


def test_le_chiavi_nuove_esistono_in_inglese():
    for key in ("cmd.twitch", "twitch.title", "twitch.clan", "twitch.clan_none", "twitch.members",
                "twitch.member_row", "twitch.live_now", "twitch.help", "twitch.saved", "twitch.removed",
                "twitch.invalid", "twitch.unknown", "twitch.not_linked", "twitch.not_ready",
                "twitch.live.title", "twitch.live.body", "twitch.support"):
        assert key in EN, key
