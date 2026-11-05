import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from fixtures import war_json
from telegram.error import BadRequest

from clashbot import boards, cards, events, feed, handlers, i18n, media, render, scoring
from clashbot import settings as settings_mod
from clashbot import warstats
from clashbot.poller import Poller, Tick

NOW = datetime(2026, 9, 12, 11, tzinfo=timezone.utc)
TZ = "Europe/Rome"
ALIAS = "bot-1"
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias=ALIAS)
IT = i18n.locale("it")
DE = i18n.locale("de")
PNG = b"\x89PNG finta immagine"
BADGE = f"https://{media.BADGE_HOST}/badges/200/abc.png"
ATTACKS = {"#P1": [("#E1", 3, 100), ("#E2", 3, 100)], "#P2": [("#E3", 2, 74)]}
MEMBERS = {"#P1": {"name": "Mario", "role": "leader"},
           "#P2": {"name": "Luigi", "role": "coLeader"},
           "#P3": {"name": "Peach", "role": "member"}}
DURING = events.war_snapshot(war_json("inWar", our_attacks=ATTACKS))
ENDED = events.war_snapshot(war_json("warEnded", our_attacks=ATTACKS))


def link(tag, user_id, name, dm=True, lang=None):
    return SimpleNamespace(alias=CLAN.alias, tag=tag, user_id=user_id, name=name, dm=dm, lang=lang)


class FakeStore:
    def __init__(self, state=None, links=(), secrets=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.links = {row.tag: row for row in links}
        self.secrets = dict(secrets or {})
        self.kv = {}
        self.wars = []
        self.stats = []
        self.langs = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def get_secret(self, kind):
        return self.secrets.get(kind)

    async def clan_by_chat(self, chat_id, bot_alias=None):
        return None

    async def bot_by_alias(self, alias):
        return None

    async def links_for_players(self, tags):
        return {tag: self.links[tag] for tag in tags if tag in self.links}

    async def links_by_user(self, user_id):
        return [row for row in self.links.values() if row.user_id == user_id]

    async def update_link(self, row):
        return row

    async def set_link_lang(self, user_id, lang):
        self.langs.append((user_id, lang))
        for row in self.links.values():
            if row.user_id == user_id:
                row.lang = lang

    async def add_war(self, alias, key, ended_at, record):
        self.wars.append(record)
        return True

    async def wars_since(self, alias, since):
        return []

    async def recent_wars(self, alias, keep):
        return []

    async def add_stat(self, alias, kind, index, ended_at, obj):
        self.stats.append((kind, index))

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def mark_failure(self, alias):
        return {"failures": 1, "active": True}


class FakeBot:
    def __init__(self, photo_error=None, photo_fails=()):
        self.messages = []
        self.photos = []
        self.photo_error = photo_error
        self.photo_fails = set(photo_fails)

    async def send_message(self, chat_id, text, **kw):
        self.messages.append((chat_id, text, kw))
        return SimpleNamespace(message_id=len(self.messages))

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        if self.photo_error:
            raise self.photo_error
        if chat_id in self.photo_fails:
            raise BadRequest("user restricted media")
        self.photos.append((chat_id, photo, caption, kw))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="file-grande")])


def poller_for(bot, store):
    supervisor = SimpleNamespace(bot=lambda alias: bot if alias == ALIAS else None,
                                 running=lambda: [ALIAS], default_alias=ALIAS, owner_bot=lambda: bot)
    return Poller(supervisor, store, None)


def conf(routes=None, topics=None):
    doc = settings_mod.migrate({"lang": "it", "tz": TZ})
    doc["routes"]["system.link_nudge"] = {"to": "off", "intensity": None}
    doc["routes"]["system.survey"] = {"to": "off", "intensity": None}
    for event, to in (routes or {}).items():
        doc["routes"][event] = {"to": to, "intensity": None}
    if topics:
        doc["topics"] = dict(topics)
    return settings_mod.effective(doc, None)


def tick(settings=None, quiet=False):
    t = Tick(CLAN, NOW)
    t.settings = settings or conf()
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.quiet = quiet
    t.members = copy.deepcopy(MEMBERS)
    t.season = scoring.empty_season("2026-09")
    t.badge_url = BADGE
    return t


def no_network(monkeypatch, drawn=None, error=None):
    async def fake_badge(url, client=None):
        return None

    def fake_draw(spec, badge=None):
        if error:
            raise error
        if drawn is not None:
            drawn.append(spec)
        return PNG

    monkeypatch.setattr(media, "badge", fake_badge)
    monkeypatch.setattr(media.cards, "draw", fake_draw)


def end_text(L=IT):
    return render.render_war_end(L, ENDED, events.war_result(ENDED), "war", None,
                                 warstats.war_defense(ENDED))


def run_war(poller, t):
    asyncio.run(poller.track_war(t, copy.deepcopy(ENDED), "war", None))


def war_messages(bot, L=IT):
    return [(chat, kw) for chat, text, kw in bot.messages if text == end_text(L)]


def war_setup(monkeypatch, settings=None, links=(), quiet=False, bot=None, drawn=None, error=None):
    no_network(monkeypatch, drawn=drawn, error=error)
    store = FakeStore(state={(CLAN.alias, "war"): DURING}, links=links)
    bot = bot or FakeBot()
    poller = poller_for(bot, store)
    return poller, store, bot, tick(settings, quiet=quiet)


def test_la_card_di_fine_guerra_parte_come_foto_col_testo_in_didascalia(monkeypatch):
    poller, store, bot, t = war_setup(monkeypatch)
    run_war(poller, t)
    assert [(event, kind, spec["kind"], targets) for event, kind, spec, _, _, targets in t.cards] == [
        ("war.end", "war_end", "war_end", [(CLAN.chat_id, None)])]
    asyncio.run(poller.flush(t))
    chat, photo, caption, kw = bot.photos[0]
    assert chat == CLAN.chat_id and photo is PNG
    assert caption == end_text()
    assert kw == {"disable_notification": False}
    assert bot.messages == []
    assert t.cards == []


def test_nelle_ore_di_silenzio_la_card_parte_muta(monkeypatch):
    poller, store, bot, t = war_setup(monkeypatch, quiet=True)
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert bot.photos[0][3] == {"disable_notification": True}


def test_se_la_foto_non_passa_il_testo_arriva_comunque(monkeypatch):
    bot = FakeBot(photo_error=BadRequest("not enough rights to send photos"))
    poller, store, _, t = war_setup(monkeypatch, bot=bot)
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert bot.photos == []
    assert end_text() in bot.messages[0][1]


def test_se_il_disegno_fallisce_il_testo_arriva_comunque(monkeypatch):
    poller, store, bot, t = war_setup(monkeypatch, error=OSError("carattere illeggibile"))
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert bot.photos == []
    assert end_text() in bot.messages[0][1]


def test_se_la_destinazione_e_spenta_la_card_non_si_disegna_nemmeno(monkeypatch):
    drawn = []
    poller, store, bot, t = war_setup(monkeypatch, settings=conf({"war.end": "off"}), drawn=drawn)
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert drawn == [] and bot.photos == [] and bot.messages == []


def test_la_card_finisce_nel_topic_del_pacchetto(monkeypatch):
    settings = conf({"war.end": "topic"}, topics={"wars": 42})
    poller, store, bot, t = war_setup(monkeypatch, settings=settings)
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert bot.photos[0][0] == CLAN.chat_id
    assert bot.photos[0][3]["message_thread_id"] == 42


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_la_card_per_i_capi_diventa_una_riga_nel_loro_feed(monkeypatch):
    poller, store, bot, t = war_setup(monkeypatch, settings=conf({"war.end": "leaders_dm"}),
                                      links=[link("#P1", 7, "Mario")])
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert bot.photos == [] and bot.messages == []
    assert end_text() in feed_rows(store, 7)


def test_senza_capi_collegati_niente_finisce_nel_gruppo(monkeypatch):
    poller, store, bot, t = war_setup(monkeypatch, settings=conf({"war.end": "leaders_dm"}))
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert bot.photos == [] and bot.messages == []
    assert [key for key in store.kv if key.startswith("feed:")] == []


def test_ogni_capo_legge_la_riga_nella_sua_lingua(monkeypatch):
    poller, store, bot, t = war_setup(monkeypatch, settings=conf({"war.end": "leaders_dm"}),
                                      links=[link("#P1", 7, "Mario"),
                                             link("#P2", 8, "Luigi", lang="de")])
    run_war(poller, t)
    asyncio.run(poller.flush(t))
    assert t.cards == [] and bot.photos == []
    assert end_text() in feed_rows(store, 7)
    assert end_text(DE) in feed_rows(store, 8)


def test_il_seguito_del_testo_lungo_arriva_a_chi_ha_avuto_la_foto(monkeypatch):
    no_network(monkeypatch)
    store = FakeStore()
    bot = FakeBot()
    poller = poller_for(bot, store)
    t = tick()
    lungo = "Titolo\n" + "riga di dettaglio\n" * 200
    spec = cards.build_war_end(IT, ENDED, "win", tag=CLAN.tag)
    t.cards.append(("war.end", "war_end", spec, lungo, lambda L: lungo, [(CLAN.chat_id, None)]))
    asyncio.run(poller.flush_cards(t))
    head, rest = media.caption(lungo)
    assert rest and bot.photos[0][2] == head
    assert [(chat, text) for chat, text, _ in bot.messages] == [(CLAN.chat_id, rest)]


def test_il_file_id_si_riusa_al_secondo_invio(monkeypatch):
    no_network(monkeypatch)
    store = FakeStore()
    bot = FakeBot()
    poller = poller_for(bot, store)
    for _ in range(2):
        t = tick()
        t.cards.append(("war.end", "war_end", cards.build_war_end(IT, ENDED, "win", tag=CLAN.tag),
                        end_text(), lambda L: end_text(), [(CLAN.chat_id, None)]))
        asyncio.run(poller.flush_cards(t))
    assert [photo[1] for photo in bot.photos] == [PNG, "file-grande"]


def closing_season():
    season = scoring.empty_season("2026-08")
    scoring.apply_war(season, events.war_record(ENDED, "war", None))
    return season


def test_la_card_dei_titoli_parte_quando_cambia_il_mese(monkeypatch):
    no_network(monkeypatch)
    store = FakeStore(state={(CLAN.alias, "season"): closing_season()})
    bot = FakeBot()
    poller = poller_for(bot, store)
    t = tick()
    asyncio.run(poller.season_for(t))
    assert t.cards == []
    asyncio.run(poller.flush(t))
    assert bot.photos == [] and bot.messages == []
    titoli = "\n".join(boards.lines_of(t.boards, "challenges"))
    assert IT.t("title.MVP") in titoli and "Mario" in titoli
    assert store.state[(CLAN.alias, "hall")]["seasons"][0]["season"] == "2026-08"


def test_il_piede_della_card_porta_il_sito_quando_ce(monkeypatch):
    no_network(monkeypatch)
    store = FakeStore(state={(CLAN.alias, "war"): DURING})
    bot = FakeBot()
    poller = poller_for(bot, store)
    poller.site = "clanboard.example"
    t = tick()
    run_war(poller, t)
    assert t.cards[0][2]["footer"] == cards.footer(IT, CLAN.tag, "clanboard.example")


PLAYER = {"tag": "#P1", "name": "Mario", "townHallLevel": 16, "trophies": 5600,
          "bestTrophies": 5800, "warStars": 1200, "donations": 3000, "warPreference": "in",
          "league": {"id": 29000022, "name": "Leggenda"},
          "heroes": [{"name": "Barbarian King", "level": 95, "village": "home"}],
          "clan": {"tag": "#CLAN1", "name": "Futuro", "badgeUrls": {"medium": BADGE}},
          "achievements": []}


class FakeCoc:
    async def player(self, tag):
        return copy.deepcopy(PLAYER), None


class FakeMessage:
    def __init__(self):
        self.photos = []
        self.texts = []
        self.sender_chat = None

    async def reply_photo(self, photo, caption=None, **kw):
        self.photos.append((photo, caption))
        return SimpleNamespace(photo=[SimpleNamespace(file_id="file-grande")])

    async def reply_text(self, text, **kw):
        self.texts.append(text)
        return SimpleNamespace(message_id=1)


def me_update(message):
    return SimpleNamespace(callback_query=None, effective_message=message,
                           effective_chat=SimpleNamespace(id=7, type="private"),
                           effective_user=SimpleNamespace(id=7, language_code="it",
                                                          first_name="Mario"))


def me_context(store):
    return SimpleNamespace(bot_data={"store": store, "coc": FakeCoc(), "bot_alias": ALIAS},
                           args=[], user_data={},
                           bot=SimpleNamespace(username="FuturoCoCBot"))


def test_me_risponde_con_la_card_del_giocatore(monkeypatch):
    no_network(monkeypatch)
    media.forget()
    store = FakeStore(links=[link("#P1", 7, "Mario")])
    message = FakeMessage()
    asyncio.run(handlers.cmd_me(me_update(message), me_context(store)))
    assert message.photos and message.photos[0][0] is PNG
    assert message.photos[0][1] == media.caption(render.me_view(
        IT, [store.links["#P1"]], {"#P1": handlers.player_snapshot(PLAYER)}))[0]
    assert message.texts == []


def test_me_torna_al_testo_quando_la_card_non_si_disegna(monkeypatch):
    no_network(monkeypatch, error=OSError("immagine rotta"))
    media.forget()
    store = FakeStore(links=[link("#P1", 7, "Mario")])
    message = FakeMessage()
    asyncio.run(handlers.cmd_me(me_update(message), me_context(store)))
    assert message.photos == []
    assert message.texts == [render.me_view(IT, [store.links["#P1"]],
                                            {"#P1": handlers.player_snapshot(PLAYER)})]


def test_me_torna_al_testo_quando_la_foto_non_passa(monkeypatch):
    no_network(monkeypatch)
    media.forget()

    class Refusing(FakeMessage):
        async def reply_photo(self, photo, caption=None, **kw):
            raise BadRequest("not enough rights to send photos")

    store = FakeStore(links=[link("#P1", 7, "Mario")])
    message = Refusing()
    asyncio.run(handlers.cmd_me(me_update(message), me_context(store)))
    assert message.photos == []
    assert message.texts == [render.me_view(IT, [store.links["#P1"]],
                                            {"#P1": handlers.player_snapshot(PLAYER)})]
