import asyncio
import copy
from datetime import timedelta
from types import SimpleNamespace

from test_routing import CLAN, FUTURO, MONDAY, TZ, FakeCoc, FakeStore, link, routed, setup

from clashbot import boards, builder, feed, handlers, i18n, settings as settings_mod
from clashbot.achievements import player_snapshot
from clashbot.events import member_snapshot
from clashbot.events_registry import EVENTS
from clashbot.poller import Tick

L = i18n.locale("it")
EN = i18n.locale("en")

MEMBERS = [
    {"tag": "#P1", "name": "Mario", "role": "leader", "townHallLevel": 16, "trophies": 5400,
     "donations": 10, "donationsReceived": 5, "builderBaseTrophies": 4200},
    {"tag": "#P2", "name": "Luigi", "role": "member", "townHallLevel": 15, "trophies": 5100,
     "donations": 0, "donationsReceived": 0, "builderBaseTrophies": 3800},
    {"tag": "#P3", "name": "Peach", "role": "member", "townHallLevel": 14, "trophies": 4700,
     "donations": 0, "donationsReceived": 0},
]


def members():
    return member_snapshot({"memberList": MEMBERS})


def test_i_trofei_del_costruttore_arrivano_dal_json_del_clan():
    snapshot = members()
    assert snapshot["#P1"]["bb"] == 4200 and snapshot["#P3"].get("bb") is None


def test_classifica_con_salita_della_settimana_e_municipio():
    players = {"#P1": {"bh": 10}, "#P2": {"bh": 9}}
    rows = builder.trophy_rows(members(), {"#P1": 4100, "#P2": 3900}, players)
    assert [r["name"] for r in rows] == ["Mario", "Luigi"]
    assert rows[0]["value"] == 4200 and rows[0]["delta"] == 100 and rows[0]["extra"] == 10
    assert rows[1]["delta"] == -100
    assert builder.climber(rows)["name"] == "Mario"
    assert builder.climber([]) is None
    assert builder.baseline(members()) == {"#P1": 4200, "#P2": 3800}


def test_card_della_classifica():
    rows = builder.trophy_rows(members(), None, {"#P1": {"bh": 10}})
    text = builder.board_card(L, rows)
    assert "Mario" in text and "4.200" in text and "Peach" not in text
    assert L.t("builder.board.empty") in builder.board_card(L, [])


def test_le_righe_restano_pulite_senza_municipio_conosciuto():
    rows = builder.trophy_rows(members(), {"#P2": 3700}, {"#P1": {"bh": 10}})
    for locale in (L, EN):
        text = builder.board_card(locale, rows)
        assert "  " not in text and " \n" not in text


def test_traguardo_del_municipio_del_costruttore():
    old = player_snapshot({"name": "Mario", "townHallLevel": 16, "builderHallLevel": 9,
                           "builderBaseTrophies": 4100, "bestBuilderBaseTrophies": 4300})
    new = player_snapshot({"name": "Mario", "townHallLevel": 16, "builderHallLevel": 10,
                           "builderBaseTrophies": 4200, "bestBuilderBaseTrophies": 4300})
    assert old["bh"] == 9 and new["bb"] == 4200 and new["bb_best"] == 4300
    events = builder.milestones(old, new)
    assert events == [{"type": "builder_hall", "name": "Mario", "level": 10}]
    assert builder.milestones(new, new) == []
    assert builder.milestones(None, new) == []
    assert "10" in builder.milestone_card(L, events)
    assert builder.milestone_card(L, []) is None


def test_i_due_eventi_nuovi_vivono_nel_pacchetto_dei_membri():
    for name in ("members.builder_board", "members.builder_goal"):
        assert EVENTS[name]["pack"] == "members"
    conf = settings_mod.effective(FUTURO, None)
    assert settings_mod.route(conf, "members.builder_board") == ("group", None)
    assert settings_mod.route(conf, "members.builder_goal") == ("group", None)
    assert "member_dm" not in EVENTS["members.builder_board"]["allowed"]
    assert "member_dm" in EVENTS["members.builder_goal"]["allowed"]


def builder_setup(stored=FUTURO, state=None, now=MONDAY, coc=None, links=None):
    poller, store, bot, t = setup(stored, state=state, links=links, now=now, coc=coc)
    t.members = members()
    return poller, store, bot, t


def next_tick(t, now):
    fresh = Tick(CLAN, now)
    fresh.settings = t.settings
    fresh.L = t.L
    fresh.tz = t.tz
    fresh.quiet = t.quiet
    fresh.season = t.season
    fresh.members = copy.deepcopy(t.members)
    return fresh


def run_builder(poller, t):
    asyncio.run(poller.track_builder(t))
    asyncio.run(poller.flush(t))


def test_lunedi_la_classifica_esce_una_volta_sola_e_salva_la_base():
    poller, store, bot, t = builder_setup()
    run_builder(poller, t)
    assert bot.sent == []
    righe = boards.lines_of(t.boards, "members")
    assert len(righe) == 1 and "Mario" in righe[0]
    assert store.state[(CLAN.alias, "builder")]["base"] == {"#P1": 4200, "#P2": 3800}
    ancora = next_tick(t, MONDAY + timedelta(hours=2))
    run_builder(poller, ancora)
    assert boards.lines_of(ancora.boards, "members") == []


def test_martedi_la_classifica_non_parte():
    poller, store, bot, t = builder_setup(now=MONDAY + timedelta(days=1))
    run_builder(poller, t)
    assert bot.sent == [] and t.boards is None
    assert (CLAN.alias, "builder") not in store.state


def test_la_salita_si_misura_sulla_base_del_lunedi_prima():
    poller, store, bot, t = builder_setup()
    run_builder(poller, t)
    dopo = next_tick(t, MONDAY + timedelta(days=7))
    dopo.members["#P2"]["bb"] = 3900
    run_builder(poller, dopo)
    righe = boards.lines_of(dopo.boards, "members")
    assert len(righe) == 1
    assert L.t("builder.board.climber", name="Luigi", n=100) in righe[0]
    assert store.state[(CLAN.alias, "builder")]["base"]["#P2"] == 3900


def test_la_rotta_spenta_salva_la_base_senza_dire_niente():
    poller, store, bot, t = builder_setup(stored=routed(FUTURO, "members.builder_board", "off"))
    run_builder(poller, t)
    assert bot.sent == [] and t.boards is None
    assert store.state[(CLAN.alias, "builder")]["base"] == {"#P1": 4200, "#P2": 3800}


def player_json(bh):
    return {"tag": "#P1", "name": "Mario", "townHallLevel": 16, "trophies": 5400, "warStars": 100,
            "warPreference": "in", "builderHallLevel": bh, "builderBaseTrophies": 4200,
            "bestBuilderBaseTrophies": 4300}


def sweep(stored=FUTURO, links=None, bh=10):
    players = {"tags": {"#P1": player_snapshot(player_json(9))}, "cursor": 0, "out_since": {}}
    poller, store, bot, t = builder_setup(stored, state={(CLAN.alias, "players"): players},
                                          links=links, coc=FakeCoc({"#P1": player_json(bh)}))
    t.members = {"#P1": members()["#P1"]}
    asyncio.run(poller.sweep_players(t, per_tick=1))
    asyncio.run(poller.flush(t))
    return store, bot, t


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_il_municipio_che_sale_durante_lo_sweep_si_annuncia_una_volta():
    store, bot, t = sweep()
    assert bot.sent == []
    righe = boards.lines_of(t.boards, "members")
    assert len(righe) == 1 and "10" in righe[0]
    assert store.state[(CLAN.alias, "players")]["tags"]["#P1"]["bh"] == 10


def test_il_municipio_fermo_non_dice_niente():
    store, bot, t = sweep(bh=9)
    assert bot.sent == [] and t.boards is None


def test_il_traguardo_personale_arriva_nel_feed_del_membro():
    links = {"#P1": link("#P1", 7, "Mario", lang="en")}
    store, bot, t = sweep(stored=routed(FUTURO, "members.builder_goal", "member_dm"), links=links)
    assert bot.sent == []
    assert EN.t("builder.goal.title") in feed_rows(store, 7)[0]


def build_view(state):
    context = SimpleNamespace(bot_data={"store": FakeStore(state=state), "coc": None, "bot_alias": "bot-1"})
    return asyncio.run(handlers.build_view("builderbase", CLAN, context))


def test_il_comando_apre_la_classifica_anche_senza_base_salvata():
    assert ("builderbase", ["basecostruttore", "base2"]) in handlers.COMMANDS
    assert "builderbase" in handlers.VIEWS and ["games", "builderbase"] in handlers.MENU_ROWS
    for key in ("cmd.builderbase", "menu.builderbase"):
        assert not EN.t(key).startswith("["), key
        assert not L.t(key).startswith("["), key
    state = {(CLAN.alias, "settings"): {"lang": "it", "tz": TZ},
             (CLAN.alias, "members"): members(),
             (CLAN.alias, "players"): {"tags": {"#P1": {"bh": 10}}}}
    text, keyboard = build_view(state)
    assert L.t("builder.board.title") in text and "Mario" in text and "🔨10" in text
    datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "v:builderbase" in datas and all(len(d.encode()) <= 64 for d in datas)
    vuoto, _ = build_view({(CLAN.alias, "settings"): {"lang": "it", "tz": TZ}})
    assert L.t("builder.board.empty") in vuoto


def test_il_menu_mostra_ogni_bottone_una_volta_sola():
    keys = [key for row in handlers.MENU_ROWS for key in row]
    assert len(keys) == len(set(keys))
    assert set(keys) <= set(handlers.VIEWS)
    assert ["boards", "agenda"] in handlers.MENU_ROWS


def test_i_nomi_del_bottone_non_riusano_il_titolo_di_stagione():
    assert L.t("menu.builderbase") != L.t("title.Costruttore")
    assert EN.t("menu.builderbase") != EN.t("title.Costruttore")
