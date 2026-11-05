import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram.error import BadRequest

from clashbot import (agenda, boards, feed, games, handlers, i18n, pinned, progress, render,
                      settings as settings_mod)
from clashbot.events import war_key
from clashbot.events_registry import EVENTS
from clashbot.poller import Poller, Tick
from test_routing import (ATTACKED, CLAN, ENDED, FUTURO, MEMBERS as CLAN_MEMBERS, FakeBot, FakeCoc,
                          FakeStore, link, routed, supervisor_for)

L = i18n.locale("it")
EN = i18n.locale("en")
TZ = "Europe/Rome"
INSIDE = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)
OUTSIDE = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)
MEMBERS = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}, "#P3": {"name": "Peach"}}
PROGRESS = {
    "#P1": {"name": "Mario", "now": {"games": 12000}},
    "#P2": {"name": "Luigi", "now": {"games": 8000}},
}


def edition(now=INSIDE):
    start, end = games.window(now)
    return games.open_edition(PROGRESS, MEMBERS, start, end)


def test_finestra_dei_giochi_e_quella_dell_agenda():
    start, end = games.window(INSIDE)
    assert start == datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    assert end == start + timedelta(days=6)
    assert games.edition_id(start) == "2026-09"
    assert games.window(OUTSIDE) == (None, None)


def test_la_base_non_e_mai_zero_per_chi_e_gia_conosciuto():
    e = edition()
    assert e["base"] == {"#P1": 12000, "#P2": 8000}
    assert e["points"] == {"#P1": 0, "#P2": 0}
    assert "#P3" not in e["base"]


def test_i_punti_sono_la_differenza_dentro_la_finestra():
    e = edition()
    games.track(e, [("#P1", "Mario", {"games": 14000}), ("#P3", "Peach", {"games": 30000})])
    assert e["points"]["#P1"] == 2000
    assert e["points"]["#P3"] == 0
    games.track(e, [("#P3", "Peach", {"games": 31000})])
    assert e["points"]["#P3"] == 1000
    assert games.total(e) == 3000
    assert [r["name"] for r in games.rows(e)] == ["Mario", "Peach", "Luigi"]


def test_chi_e_a_zero_e_il_digest_che_cambia_solo_con_i_punti():
    e = edition()
    prima = games.digest(e)
    assert [r["name"] for r in games.behind(e)] == ["Luigi", "Mario"]
    games.track(e, [("#P1", "Mario", {"games": 13000})])
    assert games.digest(e) != prima
    assert [r["name"] for r in games.behind(e)] == ["Luigi"]


def test_chi_lascia_il_clan_esce_dal_tabellone():
    e = edition()
    games.prune(e, {"#P1"})
    assert list(e["points"]) == ["#P1"] and list(e["base"]) == ["#P1"]


def test_tabellone_senza_soglie_inventate():
    e = edition()
    games.track(e, [("#P1", "Mario", {"games": 16500})])
    text = games.board_text(L, TZ, e, INSIDE)
    assert "4.000" not in text and "75.000" not in text
    assert "Mario" in text and "Luigi" in text
    assert L.t("games.board.title") in text
    e["record"] = {"name": "Peach", "points": 4000, "id": "2026-08"}
    con_record = games.board_text(L, TZ, e, INSIDE)
    assert "Peach" in con_record and "4.000" in con_record
    assert L.t("games.board.done") in con_record


def test_promemoria_a_due_giorni_e_una_volta_sola():
    e = edition()
    end = games.ends_at(e)
    assert games.due_reminder(e, end - timedelta(days=3)) is False
    assert games.due_reminder(e, end - timedelta(days=1)) is True
    e["reminded"] = True
    assert games.due_reminder(e, end - timedelta(days=1)) is False
    text = games.reminder_dm(L, TZ, e, end - timedelta(days=1))
    assert L.t("games.reminder.title") in text


def test_fuori_dalla_finestra_la_vista_dice_quando_riaprono():
    start, _ = agenda.clan_games(OUTSIDE)
    text = games.waiting_card(L, TZ, start, [], OUTSIDE)
    assert L.t("games.none.title") in text
    assert L.t("games.board.record").split("{")[0] not in text


def test_il_record_del_clan_viene_dalle_edizioni_registrate():
    history = [
        {"id": "2026-08", "best": {"name": "Peach", "points": 4000}},
        {"id": "2026-07", "best": {"name": "Mario", "points": 6100}},
        {"id": "2026-06", "best": {}},
    ]
    assert games.best_ever(history) == {"name": "Mario", "points": 6100, "id": "2026-07"}
    assert games.best_ever([]) is None
    text = games.waiting_card(L, TZ, datetime(2026, 10, 22, 8, tzinfo=timezone.utc), history, OUTSIDE)
    assert "Mario" in text and L.n(6100) in text


class Bot:
    def __init__(self, fail=None):
        self.sent = []
        self.edits = []
        self.pins = []
        self.unpins = []
        self.fail = fail

    async def send_message(self, chat_id, text, disable_notification=False, message_thread_id=None):
        self.sent.append((chat_id, text, disable_notification, message_thread_id))
        return type("M", (), {"message_id": 42})()

    async def edit_message_text(self, text, chat_id=None, message_id=None):
        if self.fail:
            raise self.fail
        self.edits.append((chat_id, message_id, text))

    async def pin_chat_message(self, chat_id, message_id, disable_notification=False):
        self.pins.append((chat_id, message_id))

    async def unpin_chat_message(self, chat_id, message_id):
        self.unpins.append((chat_id, message_id))


def test_tabellone_fissato_invia_fissa_modifica_e_sgancia():
    bot = Bot()
    state = asyncio.run(pinned.upkeep(bot, -100, None, "uno", "d1", 1000.0))
    assert state == {"message_id": 42, "digest": "d1", "updated": 1000.0}
    assert bot.pins == [(-100, 42)] and bot.sent[0][2] is False
    same = asyncio.run(pinned.upkeep(bot, -100, state, "uno", "d1", 1100.0))
    assert same is state and not bot.edits
    changed = asyncio.run(pinned.upkeep(bot, -100, state, "due", "d2", 1200.0))
    assert changed["digest"] == "d2" and bot.edits[-1][2] == "due"
    stantio = asyncio.run(pinned.upkeep(bot, -100, changed, "due", "d2", 1200.0 + pinned.STALE + 1))
    assert stantio["updated"] > changed["updated"]
    assert asyncio.run(pinned.drop(bot, -100, changed)) is None
    assert bot.unpins == [(-100, 42)]


def test_force_riscrive_anche_nello_stesso_istante():
    bot = Bot()
    state = asyncio.run(pinned.upkeep(bot, -100, None, "uno", "d1", 1000.0))
    assert asyncio.run(pinned.upkeep(bot, -100, state, "uno", "d1", 1000.0)) is state
    assert not bot.edits
    forzato = asyncio.run(pinned.upkeep(bot, -100, state, "finale", "d1", 1000.0, force=True))
    assert bot.edits[-1][2] == "finale" and forzato["updated"] == 1000.0


def test_tabellone_non_nasce_quando_non_deve():
    bot = Bot()
    assert asyncio.run(pinned.upkeep(bot, -100, None, "uno", "d1", 1000.0, create=False)) is None
    assert not bot.sent


def test_messaggio_sparito_senza_creazione_lascia_pulire_il_chiamante():
    state = {"message_id": 7, "digest": "d1", "updated": 0.0}
    sparito = Bot(fail=BadRequest("Message to edit not found"))
    assert asyncio.run(pinned.upkeep(sparito, -100, state, "finale", "d2", 2000.0, create=False)) is None
    assert not sparito.sent and not sparito.pins
    altro = Bot(fail=BadRequest("Message can't be deleted"))
    assert asyncio.run(pinned.upkeep(altro, -100, state, "finale", "d2", 2000.0, create=False)) is state
    assert not altro.sent


def counters(value):
    return {key: 0 for key in progress.COUNTERS} | {"games": value}


PROGRESS_STATE = {
    "#P1": {"name": "Mario", "now": counters(12000)},
    "#P2": {"name": "Luigi", "now": counters(8000)},
    "#P3": {"name": "Peach", "now": counters(30000)},
}


class Store(FakeStore):
    def __init__(self, state=None, links=None, history=()):
        super().__init__(state=state, links=links)
        self.history = list(history)
        self.stats = []

    async def recent_stats(self, alias, kind, limit=10):
        return copy.deepcopy(self.history[:limit])

    async def add_stat(self, alias, kind, stat_key, ended_at, obj):
        self.stats.append((alias, kind, stat_key, ended_at, copy.deepcopy(obj)))
        self.history.insert(0, copy.deepcopy(obj))
        return True


def fresh_links(**langs):
    return {tag: link(tag, user_id, name, lang=langs.get(tag))
            for tag, user_id, name in (("#P1", 7, "Mario"), ("#P2", 8, "Luigi"), ("#P3", 9, "Peach"))}


def setup(stored=FUTURO, state=None, now=INSIDE, history=(), members=None, links=None, coc=None):
    base = {(CLAN.alias, "progress"): copy.deepcopy(PROGRESS_STATE)}
    base.update(state or {})
    store = Store(state=base, links=links or fresh_links(), history=history)
    bot = FakeBot()
    poller = Poller(supervisor_for(bot), store, coc)
    t = Tick(CLAN, now)
    t.settings = settings_mod.effective(stored, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.quiet = settings_mod.is_quiet(t.settings, now)
    t.members = copy.deepcopy(CLAN_MEMBERS) if members is None else members
    return poller, store, bot, t


def next_tick(t, now):
    fresh = Tick(CLAN, now)
    fresh.settings = t.settings
    fresh.L = t.L
    fresh.tz = t.tz
    fresh.quiet = t.quiet
    fresh.members = copy.deepcopy(t.members)
    return fresh


def run_games(poller, t, swept=()):
    t.swept = list(swept)
    asyncio.run(poller.track_games(t))
    asyncio.run(poller.update_boards(t))


def stored_edition(store):
    return store.state.get((CLAN.alias, "games"))


def stored_boards(store):
    return store.state.get((CLAN.alias, "boards"))


def test_i_due_eventi_nuovi_vivono_nel_pacchetto_della_capitale():
    for name in ("games.board", "games.reminder"):
        assert EVENTS[name]["pack"] == "capital_games"
    conf = settings_mod.effective(FUTURO, None)
    assert settings_mod.route(conf, "games.board") == ("group", None)
    assert settings_mod.route(conf, "games.reminder") == ("member_dm", None)
    assert "member_dm" not in EVENTS["games.board"]["allowed"]
    assert "group" not in EVENTS["games.reminder"]["allowed"]


def test_dentro_la_finestra_il_tabellone_nasce_fissato_e_i_punti_stanno_nella_sezione():
    poller, store, bot, t = setup()
    run_games(poller, t)
    assert [chat for chat, _, _ in bot.sent] == [CLAN.chat_id]
    assert L.t("board.title.capital_games") not in bot.sent[0][1]
    assert boards.lines_of(stored_boards(store), "capital_games")[0].endswith(
        render.board_body(games.board_text(L, TZ, stored_edition(store), INSIDE)))
    assert bot.pins == [101]
    assert stored_edition(store)["base"] == {"#P1": 12000, "#P2": 8000, "#P3": 30000}
    dopo = next_tick(t, INSIDE + timedelta(minutes=5))
    run_games(poller, dopo)
    assert len(bot.sent) == 1
    assert len(boards.lines_of(stored_boards(store), "capital_games")) == 1
    ancora = next_tick(t, INSIDE + timedelta(minutes=10))
    run_games(poller, ancora, [("#P1", "Mario", counters(13000))])
    assert len(bot.sent) == 1
    righe = boards.lines_of(stored_boards(store), "capital_games")
    assert len(righe) == 2 and L.n(1000) in righe[-1]
    assert stored_edition(store)["points"]["#P1"] == 1000


def test_fuori_dalla_finestra_il_tabellone_non_nasce():
    poller, store, bot, t = setup(now=OUTSIDE)
    run_games(poller, t)
    assert len(bot.sent) == 1
    assert L.t("games.board.title") not in bot.sent[0][1]
    assert boards.lines_of(stored_boards(store), "capital_games") == []
    assert stored_edition(store) is None


def test_con_la_rotta_spenta_il_tabellone_non_nasce_e_quello_vecchio_si_sgancia():
    poller, store, bot, t = setup(
        stored=routed(FUTURO, "games.board", "off"),
        state={(CLAN.alias, "games_board"): {"message_id": 77, "digest": "x", "updated": 0.0}})
    bot.pins = [77]
    run_games(poller, t)
    assert len(bot.sent) == 1
    assert boards.lines_of(stored_boards(store), "capital_games") == []
    assert (CLAN.alias, "games_board") not in store.state
    assert stored_edition(store)["id"] == "2026-09"


def test_il_tabellone_dei_giochi_e_una_riga_della_sezione_capitale_e_giochi():
    poller, store, bot, t = setup()
    t.swept = []
    asyncio.run(poller.track_games(t))
    asyncio.run(poller.update_boards(t))
    assert [chat for chat, _, _ in bot.sent] == [CLAN.chat_id]
    assert L.t("board.title.capital_games") not in bot.sent[0][1]
    assert (CLAN.alias, "games_board") not in store.state
    assert boards.lines_of(stored_boards(store), "capital_games")[0].endswith(
        render.board_body(games.board_text(L, TZ, stored_edition(store), INSIDE)))


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_a_due_giorni_il_promemoria_va_nel_feed_di_chi_e_a_zero_e_non_si_ripete():
    poller, store, bot, t = setup()
    run_games(poller, t, [("#P1", "Mario", counters(13000))])
    due = next_tick(t, datetime(2026, 9, 27, 8, tzinfo=timezone.utc))
    run_games(poller, due)
    assert [uid for uid in (7, 8, 9) if feed_rows(store, uid)] == [8, 9]
    assert all(L.t("games.reminder.title") in feed_rows(store, uid)[0] for uid in (8, 9))
    assert stored_edition(store)["reminded"] is True
    ancora = next_tick(t, datetime(2026, 9, 27, 9, tzinfo=timezone.utc))
    run_games(poller, ancora)
    assert [len(feed_rows(store, uid)) for uid in (8, 9)] == [1, 1]


def test_il_promemoria_parla_la_lingua_del_membro():
    poller, store, bot, t = setup(links=fresh_links(**{"#P2": "en"}))
    run_games(poller, t, [("#P1", "Mario", counters(13000))])
    due = next_tick(t, datetime(2026, 9, 27, 8, tzinfo=timezone.utc))
    run_games(poller, due)
    assert EN.t("games.reminder.title") in feed_rows(store, 8)[0]
    assert L.t("games.reminder.title") in feed_rows(store, 9)[0]


def player_json(name, tag, games_value):
    return {
        "tag": tag, "name": name, "townHallLevel": 14, "trophies": 5000, "warStars": 100,
        "warPreference": "in",
        "achievements": [{"name": "Games Champion", "value": games_value}],
    }


def test_lo_sweep_dei_giocatori_alimenta_i_punti_senza_chiamate_in_piu():
    poller, store, bot, t = setup(coc=FakeCoc({"#P1": player_json("Mario", "#P1", 15000)}))
    run_games(poller, t)
    assert stored_edition(store)["points"]["#P1"] == 0
    dopo = next_tick(t, INSIDE + timedelta(minutes=10))
    dopo.members = {"#P1": CLAN_MEMBERS["#P1"]}
    asyncio.run(poller.sweep_players(dopo, per_tick=1))
    assert [tag for tag, _, _ in dopo.swept] == ["#P1"]
    asyncio.run(poller.track_games(dopo))
    assert stored_edition(store)["points"]["#P1"] == 3000


def test_una_lettura_fallita_del_clan_non_svuota_il_tabellone():
    poller, store, bot, t = setup()
    run_games(poller, t, [("#P1", "Mario", counters(13000))])
    cieco = next_tick(t, INSIDE + timedelta(minutes=10))
    cieco.members = None
    run_games(poller, cieco)
    assert stored_edition(store)["points"]["#P1"] == 1000
    assert list(stored_edition(store)["base"]) == ["#P1", "#P2", "#P3"]


def board_state(war, message_id=500, updated=0.0):
    return {"war": war_key(war), "message_id": message_id,
            "digest": render.board_digest(war), "updated": updated}


def test_la_guerra_in_corso_diventa_una_riga_della_sezione_guerre():
    poller, store, bot, t = setup(state={(CLAN.alias, "war"): ATTACKED})
    asyncio.run(poller.update_boards(t))
    assert len(bot.sent) == 1 and bot.pins == [101]
    assert L.t("board.title.wars") not in bot.sent[0][1]
    assert render.board_body(render.render_board(L, TZ, ATTACKED, "war", None, INSIDE)) in \
        boards.lines_of(stored_boards(store), "wars")[0]
    salvato = store.state[(CLAN.alias, "boards")]
    assert boards.digest_of(salvato, "wars") == render.board_digest(ATTACKED)
    assert boards.message_id(salvato) == 101
    assert (CLAN.alias, "board") not in store.state


def test_la_guerra_finita_entra_nel_fissato_e_la_vecchia_bacheca_si_sgancia():
    poller, store, bot, t = setup(state={
        (CLAN.alias, "war"): ENDED,
        (CLAN.alias, "board"): board_state(ENDED, updated=INSIDE.timestamp()),
    })
    bot.pins = [500]
    asyncio.run(poller.update_boards(t))
    assert bot.unpinned == [500] and bot.deleted == [500] and bot.edits == []
    assert len(bot.sent) == 1 and bot.pins == [101]
    assert render.board_body(render.render_board(L, TZ, ENDED, "war", None, INSIDE)) in \
        boards.lines_of(stored_boards(store), "wars")[0]
    assert (CLAN.alias, "board") not in store.state


def test_la_vecchia_bacheca_gia_sparita_lascia_lo_stato_pulito():
    poller, store, bot, t = setup(state={
        (CLAN.alias, "war"): ENDED,
        (CLAN.alias, "board"): board_state(ENDED, updated=INSIDE.timestamp()),
    })
    bot.fail_delete_with = BadRequest("Message to delete not found")
    asyncio.run(poller.update_boards(t))
    assert bot.deleted == [] and bot.unpinned == [500]
    assert (CLAN.alias, "board") not in store.state
    assert boards.message_id(store.state[(CLAN.alias, "boards")]) == 101


SETTINGS = {(CLAN.alias, "settings"): {"lang": "it", "tz": TZ}}


def view(monkeypatch, key, state, now):
    monkeypatch.setattr(handlers, "now_utc", lambda: now)
    context = SimpleNamespace(bot_data={"store": Store(state=state), "coc": None, "bot_alias": "bot-1"})
    return asyncio.run(handlers.build_view(key, CLAN, context))


def test_il_comando_giochi_apre_il_tabellone_o_dice_quando_riaprono(monkeypatch):
    assert ("games", ["giochi"]) in handlers.COMMANDS
    assert "games" in handlers.VIEWS and ["games", "builderbase"] in handlers.MENU_ROWS
    for key in ("cmd.games", "menu.games"):
        assert not EN.t(key).startswith("["), key
    e = edition()
    games.track(e, [("#P1", "Mario", counters(13000))])
    text, keyboard = view(monkeypatch, "games", SETTINGS | {(CLAN.alias, "games"): e}, INSIDE)
    assert L.t("games.board.title") in text and "Mario" in text
    datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "v:games" in datas and all(len(d.encode()) <= 64 for d in datas)
    vuoto, _ = view(monkeypatch, "games", dict(SETTINGS), OUTSIDE)
    assert L.t("games.none.title") in vuoto and L.t("games.board.sub") not in vuoto
