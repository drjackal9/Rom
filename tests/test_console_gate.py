import asyncio
import logging

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove

from clashbot import console, i18n, platform, render
from clashbot.crypto import Vault
from clashbot.db import Store
from test_console import (CLAN, DELEGATE_ID, DELEGATE_NAME, LEADER_TAG, MEMBER_TAG, OWNER, TAG,
                          USER, FakeCoc, FakeStore, account, context, last, make_bot, private,
                          request_of)

IT = i18n.locale("it")
GAME_TOKEN = "tok-123"
GIRI = 5
OTHER_TAG = "#8QQ9UVL"


def no_button(update):
    return not any(isinstance(markup, ReplyKeyboardMarkup) for _, markup in update.effective_message.sent)


def texts(update):
    return [text for text, _ in update.effective_message.sent]


class GatePool:
    def __init__(self, clans=(), pending=(), born=()):
        self.clans = list(clans)
        self.pending = list(pending)
        self.born = list(born)
        self.seen = []
        self.written = []

    async def fetchval(self, sql, *args):
        self.seen.append((" ".join(sql.split()), args))
        rows = self.born if "from bots" in sql else self.clans
        return next((alias for index, alias in rows if index == args[0]), None)

    async def fetchrow(self, sql, *args):
        self.seen.append((" ".join(sql.split()), args))
        assert "from kv" in sql and "limit 1" in sql
        return next(({"k": key, "data": data} for ref, key, data in self.pending if ref == args[0]), None)

    async def fetch(self, sql, *args):
        raise AssertionError("nessuno scorre le righe: " + " ".join(sql.split()))

    async def execute(self, sql, *args):
        self.written.append((" ".join(sql.split()), args))


def store_with_pool(tmp_path):
    store = Store(Vault(tmp_path))
    store.pool = GatePool()
    return store


def pending_row(store, code, tag, bot_alias):
    key = f"ob:{code}"
    payload = {"tag": tag, "name": CLAN, "user_id": USER, "bot_alias": bot_alias}
    return store.vault.blind("tag", tag), key, store.vault.encrypt_json(payload, f"kv:{key}")


def born_row(store, alias, tag):
    return store.vault.blind("tag", tag), alias


def test_a_bot_born_for_a_clan_and_never_brought_to_a_group_still_holds_it(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.born = [born_row(store, "bot-c", TAG)]
    assert asyncio.run(store.bot_for_tag(TAG)) == "bot-c"
    asked = next(sql for sql, _ in store.pool.seen if "from bots" in sql)
    assert "not exists" in asked and "clans" in asked
    assert asyncio.run(store.bot_for_tag(OTHER_TAG)) is None


def test_an_unreadable_bot_does_not_stop_the_check(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.born = [born_row(store, "bot-rotto", OTHER_TAG), born_row(store, "bot-c", TAG)]
    assert asyncio.run(store.bot_for_tag(TAG)) == "bot-c"
    asked = [(sql, args) for sql, args in store.pool.seen if "from bots" in sql]
    assert asked and all("identity" not in sql and "limit 1" in sql for sql, _ in asked)
    assert all(args == (store.vault.blind("tag", TAG),) for _, args in asked)


def test_a_born_bot_comes_before_the_pending_record_of_a_bot_that_lost_the_clan(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.pending = [pending_row(store, "abc", TAG, "bot-vecchio")]
    store.pool.born = [born_row(store, "bot-nuovo", TAG)]
    assert asyncio.run(store.bot_for_tag(TAG)) == "bot-nuovo"


def test_the_clan_of_a_served_clan_names_its_bot(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.clans = [(store.vault.blind("tag", TAG), "bot-a")]
    assert asyncio.run(store.bot_for_tag(TAG)) == "bot-a"
    assert all(TAG not in str(args) for _, args in store.pool.seen)


def test_a_creation_still_waiting_for_the_group_already_holds_the_clan(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.pending = [pending_row(store, "abc", TAG, "bot-b")]
    assert asyncio.run(store.bot_for_tag(TAG)) == "bot-b"
    assert any("expires_at" in sql for sql, _ in store.pool.seen)


def test_a_clan_nobody_serves_stays_free(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.clans = [(store.vault.blind("tag", OTHER_TAG), "bot-a")]
    store.pool.pending = [pending_row(store, "abc", OTHER_TAG, "bot-b")]
    assert asyncio.run(store.bot_for_tag(TAG)) is None
    assert asyncio.run(store.bot_for_tag("pippo")) is None


def test_an_unreadable_pending_record_does_not_stop_the_check(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.pending = [(store.vault.blind("tag", TAG), "ob:rotto", b"x" * 40),
                          pending_row(store, "abc", OTHER_TAG, "bot-b")]
    assert asyncio.run(store.bot_for_tag(TAG)) is None
    assert asyncio.run(store.bot_for_tag(OTHER_TAG)) == "bot-b"


def test_la_prenotazione_si_cerca_per_indice_e_non_si_scorre(tmp_path):
    store = store_with_pool(tmp_path)
    store.pool.pending = [pending_row(store, f"c{n}", OTHER_TAG, "bot-x") for n in range(GIRI)]
    store.pool.pending.append(pending_row(store, "abc", TAG, "bot-b"))
    assert asyncio.run(store.bot_for_tag(TAG)) == "bot-b"
    asked = [(sql, args) for sql, args in store.pool.seen if "from kv" in sql]
    assert len(asked) == 1 and "ref=$1" in asked[0][0] and "limit 1" in asked[0][0]
    assert asked[0][1] == (store.vault.blind("tag", TAG),)


def test_la_prenotazione_di_un_bot_porta_l_indice_cieco_del_clan(tmp_path):
    store = store_with_pool(tmp_path)
    cieco = store.vault.blind("tag", TAG)
    scritte = (("ob:abc", {"tag": TAG.lower(), "bot_alias": "bot-b"}, None, cieco),
               ("ob:legacy", {"tag": TAG, "bot_alias": None}, None, None),
               ("altro:abc", {"tag": TAG, "bot_alias": "bot-b"}, None, None),
               ("claims:1", {"rows": []}, "clan-1", "clan-1"))
    for key, body, ref, _ in scritte:
        asyncio.run(store.kv_set(key, body, ref=ref, ttl=60))
    assert [(args[0], args[1]) for _, args in store.pool.written] == [(key, atteso) for key, _, _, atteso in scritte]
    assert TAG.strip("#") not in cieco


def test_a_member_who_is_not_leader_never_gets_the_creation_button():
    store = FakeStore(accounts=[account(tag=MEMBER_TAG)])
    coc = FakeCoc()
    ctx = context(store, coc=coc, args=[TAG])
    asked = private()
    asyncio.run(console.cmd_newbot(asked, ctx))
    assert last(asked) == render.onboard_ask_player(IT, CLAN) and no_button(asked)
    refused = private(text=MEMBER_TAG)
    asyncio.run(console.on_newbot_text(refused, ctx))
    assert last(refused) == IT.t("h.onboard_not_leader", clan=CLAN)
    assert no_button(refused) and coc.players == [] and coc.verified == []


def test_a_linked_leader_passes_without_the_game_token():
    store = FakeStore(accounts=[account()])
    coc = FakeCoc()
    ctx = context(store, coc=coc, args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    assert request_of(update).request_managed_bot.suggested_name == CLAN
    assert coc.players == [] and coc.verified == []
    assert ctx.user_data["newbot"]["tag"] == TAG
    assert "step" not in ctx.user_data["newbot"]


def test_a_leader_without_an_account_passes_after_a_valid_token():
    store, coc = FakeStore(), FakeCoc()
    ctx = context(store, coc=coc, args=[TAG])
    asked = private()
    asyncio.run(console.cmd_newbot(asked, ctx))
    assert last(asked) == render.onboard_ask_player(IT, CLAN) and no_button(asked)
    player = private(text=LEADER_TAG)
    asyncio.run(console.on_newbot_text(player, ctx))
    assert last(player) == render.onboard_ask_token(IT, "Mario") and no_button(player)
    given = private(text=GAME_TOKEN)
    asyncio.run(console.on_newbot_text(given, ctx))
    assert coc.verified == [LEADER_TAG]
    assert store.linked == [(USER, LEADER_TAG, "Mario")] and store.link_langs == ["it"]
    assert request_of(given).request_managed_bot.suggested_name == CLAN
    assert ctx.user_data["newbot"]["tag"] == TAG
    assert all(GAME_TOKEN not in text for text in texts(given))


def test_a_token_the_game_refuses_leaves_the_creation_closed(caplog):
    store, coc = FakeStore(), FakeCoc(token_ok=False)
    ctx = context(store, coc=coc, args=[TAG])
    asyncio.run(console.cmd_newbot(private(), ctx))
    asyncio.run(console.on_newbot_text(private(text=LEADER_TAG), ctx))
    given = private(text=GAME_TOKEN)
    with caplog.at_level(logging.DEBUG, logger="clashbot.console"):
        asyncio.run(console.on_newbot_text(given, ctx))
    assert last(given) == IT.t("h.token_invalid") and no_button(given)
    assert store.linked == [] and ctx.user_data["newbot"]["step"] == "token"
    assert GAME_TOKEN not in caplog.text


def test_a_second_bot_for_the_same_clan_is_refused():
    store = FakeStore(accounts=[account()], taken="bot-a")
    ctx = context(store, coc=FakeCoc(), args=[TAG])
    update = private()
    asyncio.run(console.cmd_newbot(update, ctx))
    text, markup = update.effective_message.sent[-1]
    assert text == IT.t("console.newbot_clan_taken")
    assert isinstance(markup, ReplyKeyboardRemove) and no_button(update)
    assert "newbot" not in ctx.user_data


def test_the_platform_manager_skips_the_limit_and_the_check():
    rows = [make_bot(f"bot-{i}", owner_id=OWNER, bot_id=i) for i in range(3)]
    store = FakeStore(rows=rows, owner=str(OWNER), taken="bot-a")
    coc = FakeCoc(roles=())
    ctx = context(store, coc=coc, args=[TAG])
    update = private(user_id=OWNER)
    asyncio.run(console.cmd_newbot(update, ctx))
    assert request_of(update).request_managed_bot.suggested_name == CLAN
    assert coc.players == [] and coc.verified == []


def test_newbot_without_a_tag_asks_for_it_and_then_checks_it():
    store = FakeStore(accounts=[account()])
    coc = FakeCoc()
    ctx = context(store, coc=coc)
    asked = private()
    asyncio.run(console.cmd_newbot(asked, ctx))
    assert last(asked) == render.onboard_ask_clan(IT) and no_button(asked)
    assert coc.asked == [] and ctx.user_data["newbot"]["step"] == "tag"
    answer = private(text=TAG)
    asyncio.run(console.on_newbot_text(answer, ctx))
    assert coc.asked == [TAG]
    assert request_of(answer).request_managed_bot.suggested_name == CLAN


def test_an_answer_that_is_not_a_tag_is_asked_again():
    ctx = context(FakeStore(accounts=[account()]), coc=FakeCoc())
    asyncio.run(console.cmd_newbot(private(), ctx))
    answer = private(text="pippo")
    asyncio.run(console.on_newbot_text(answer, ctx))
    assert last(answer) == IT.t("console.newbot_bad_tag")
    assert ctx.user_data["newbot"]["step"] == "tag" and no_button(answer)


def test_a_message_outside_a_creation_is_left_alone():
    ctx = context(FakeStore(), coc=FakeCoc())
    update = private(text="ciao")
    asyncio.run(console.on_newbot_text(update, ctx))
    assert update.effective_message.sent == []


def test_cancel_closes_the_verification_too():
    store = FakeStore()
    ctx = context(store, coc=FakeCoc())
    asyncio.run(console.cmd_newbot(private(), ctx))
    asyncio.run(console.cmd_cancel(private(), ctx))
    assert "newbot" not in ctx.user_data
    ignored = private(text=TAG)
    asyncio.run(console.on_newbot_text(ignored, ctx))
    assert ignored.effective_message.sent == []


def test_the_clan_taken_notice_speaks_every_language():
    for code in i18n.LANGUAGES:
        text = i18n.locale(code).t("console.newbot_clan_taken")
        assert not text.startswith("[") and "/mybots" in text, code


def named(user_id, username, text=""):
    update = private(user_id=user_id, text=text)
    update.effective_user.username = username
    return update


def delegate_store(rows):
    store = FakeStore(owner=str(OWNER), secrets={"owner_lang": "it"})
    store.kv[platform.KEY] = list(rows)
    return store


def test_i_tre_gradi_della_piattaforma_si_distinguono():
    store = delegate_store([{"username": DELEGATE_NAME, "user_id": DELEGATE_ID, "since": 1.0}])

    async def gradi():
        return (await platform.level(store, OWNER), await platform.level(store, DELEGATE_ID),
                await platform.level(store, USER), await platform.level(store, None))

    assert asyncio.run(gradi()) == (platform.OWNER, platform.DELEGATE, None, None)


def test_finche_il_delegato_non_scrive_start_il_console_non_gli_risponde():
    store = delegate_store([{"username": DELEGATE_NAME, "user_id": None, "since": 1.0}])
    ctx = context(store)
    chiuso = named(DELEGATE_ID, DELEGATE_NAME, text="/pannello")
    asyncio.run(console.cmd_panel(chiuso, ctx))
    assert last(chiuso) == IT.t("console.owner_only")
    assert asyncio.run(platform.level(store, DELEGATE_ID)) is None
    inizio = named(DELEGATE_ID, DELEGATE_NAME.capitalize(), text="/start")
    asyncio.run(console.cmd_start(inizio, ctx))
    assert IT.t("console.delegate.welcome") in texts(inizio)[-1]
    riga = store.kv[platform.KEY][0]
    assert store.kv[platform.KEY] == [riga]
    assert riga["username"] == DELEGATE_NAME and riga["user_id"] == DELEGATE_ID
    assert riga["since"] == 1.0 and riga["bound"] > riga["since"]
    aperto = named(DELEGATE_ID, DELEGATE_NAME, text="/pannello")
    asyncio.run(console.cmd_panel(aperto, ctx))
    assert IT.t("panel.title") in last(aperto)


def test_tolto_il_delegato_il_console_torna_a_ignorarlo():
    store = delegate_store([{"username": DELEGATE_NAME, "user_id": DELEGATE_ID, "since": 1.0}])
    ctx = context(store)

    async def togli():
        return await platform.drop(store, f"@{DELEGATE_NAME}")

    assert asyncio.run(togli()) == DELEGATE_NAME
    assert store.kv[platform.KEY] == []
    chiuso = named(DELEGATE_ID, DELEGATE_NAME, text="/pannello")
    asyncio.run(console.cmd_panel(chiuso, ctx))
    assert last(chiuso) == IT.t("console.owner_only")
    ancora = named(DELEGATE_ID, DELEGATE_NAME, text="/start")
    asyncio.run(console.cmd_start(ancora, ctx))
    assert all(IT.t("console.delegate.welcome") not in text for text in texts(ancora))


def test_lo_start_di_chi_non_e_delegato_non_tocca_la_lista():
    store = delegate_store([{"username": DELEGATE_NAME, "user_id": None, "since": 1.0}])
    estraneo = named(USER, "passante", text="/start")
    asyncio.run(console.cmd_start(estraneo, context(store)))
    assert len(estraneo.effective_message.sent) == 1
    assert store.kv[platform.KEY] == [{"username": DELEGATE_NAME, "user_id": None, "since": 1.0}]
    senza_nome = private(text="/start")
    asyncio.run(console.cmd_start(senza_nome, context(store)))
    assert len(senza_nome.effective_message.sent) == 1


def test_chi_riprende_lo_username_del_delegato_non_ne_eredita_il_grado():
    legata = {"username": DELEGATE_NAME, "user_id": DELEGATE_ID, "since": 1.0}
    store = delegate_store([dict(legata)])
    ctx = context(store)
    subentrato = named(USER, DELEGATE_NAME.upper(), text="/start")
    asyncio.run(console.cmd_start(subentrato, ctx))
    assert all(IT.t("console.delegate.welcome") not in text for text in texts(subentrato))
    assert store.kv[platform.KEY] == [legata]
    assert asyncio.run(platform.level(store, USER)) is None
    assert asyncio.run(platform.level(store, DELEGATE_ID)) == platform.DELEGATE
    chiuso = named(USER, DELEGATE_NAME, text="/pannello")
    asyncio.run(console.cmd_panel(chiuso, ctx))
    assert last(chiuso) == IT.t("console.owner_only")


def test_lo_username_del_delegato_si_scrive_in_un_modo_solo():
    assert platform.clean(" @Cyfren1 ") == "Cyfren1"
    assert platform.clean("cyfren_1") == "cyfren_1"
    for raw in (None, "", "@", "chi va là?", "nome cognome", "nome:altro", "nomè"):
        assert platform.clean(raw) is None, raw
