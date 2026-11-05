import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from telegram.error import BadRequest

from clashbot import agenda, boards, events as events_mod, feed, i18n, progress
from clashbot.events_registry import CLAN_PACKS
from clashbot.web import payload as payload_mod
from clashbot import settings as settings_mod
from fixtures import war_json
from test_routing import CLAN, FUTURO, setup

L = i18n.locale("it")
TZ = "Europe/Rome"
NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
END = "20260917T141000.000Z"
NEW_KEYS = ("board.all.title", "board.all.updated", "board.all.empty", "board.title.bases",
            "board.all.open", "board.all.lost", "board.short.missing", "board.short.next")
SYMBOL_KEYS = ("board.short.stars",)
TICKER_KEYS = ("ticker.war", "ticker.cwl", "ticker.raid", "ticker.idle")
ALL_DONE = {"#P1": [("#E1", 3, 100)], "#P2": [("#E2", 3, 100)], "#P3": [("#E3", 3, 100)]}


def war_now(our_attacks=None, day=None, state="inWar"):
    war = events_mod.war_snapshot(war_json(state, our_attacks=our_attacks, end=END, per_member=1))
    if day is not None:
        war["day"] = day
    return war


def test_le_sezioni_sono_i_pacchetti_del_clan_in_un_ordine_fisso():
    assert boards.SECTION_ORDER == ("wars", "cwl", "capital_games", "members", "challenges",
                                    "family", "recruitment", "bases")
    assert set(boards.SECTION_ORDER) <= set(CLAN_PACKS)


def test_il_fissato_unico_ha_una_sezione_per_pacchetto_acceso_nell_ordine_fisso():
    state = boards.append({}, "members", ["Mario è salito al TH15"], NOW, TZ)
    state = boards.append(state, "wars", ["Guerra contro X: 3⭐ a 2⭐"], NOW, TZ)
    text = boards.render_all(L, state, ["wars", "members", "cwl"], "Futuro", TZ)
    assert text.index(L.t("board.title.wars")) < text.index(L.t("board.title.members"))
    assert L.t("board.title.cwl") in text and L.t("board.all.empty") in text
    assert L.t("board.all.title", clan="Futuro") in text and len(text) <= boards.LIMIT
    assert L.t("board.all.updated", time="14:00") in text
    assert L.t("board.title.family") not in text


def test_ogni_sezione_del_fissato_ha_il_suo_titolo_nel_catalogo():
    text = boards.render_all(L, {}, boards.SECTION_ORDER, "Futuro", TZ)
    assert "[board." not in text
    assert L.t("board.all.updated", time="14:00") not in text
    for pack in boards.SECTION_ORDER:
        assert L.t(f"board.title.{pack}") in text


def test_quando_il_testo_supera_il_limite_si_tolgono_prima_le_righe_vecchie_della_sezione_piu_lunga():
    state = {}
    for i in range(400):
        state = boards.append(state, "members", [f"riga {i} " + "x" * 40], NOW, TZ)
    state = boards.append(state, "wars", ["ultima guerra"], NOW, TZ)
    text = boards.render_all(L, state, ["wars", "members"], "Futuro", TZ)
    assert len(text) <= boards.LIMIT and "ultima guerra" in text
    assert "riga 399" in text and "riga 0 " not in text


def test_il_taglio_non_lascia_mai_una_sezione_senza_la_sua_ultima_riga():
    state = {}
    for pack in boards.SECTION_ORDER:
        for i in range(10):
            state = boards.append(state, pack, [f"{pack} riga {i} " + "y" * 100], NOW, TZ)
    text = boards.render_all(L, state, boards.SECTION_ORDER, "Futuro", TZ)
    assert len(text) <= boards.LIMIT
    for pack in boards.SECTION_ORDER:
        assert f"{pack} riga 9 " in text and f"{pack} riga 0 " not in text


def test_anche_con_una_riga_sola_ma_enorme_per_sezione_il_testo_sta_nel_limite():
    state = {}
    for pack in boards.SECTION_ORDER:
        state = boards.append(state, pack, ["y" * 900], NOW, TZ)
    assert len(boards.render_all(L, state, boards.SECTION_ORDER, "Futuro", TZ)) <= boards.LIMIT


def test_lo_stato_tiene_un_solo_message_id_e_ricorda_quelli_vecchi():
    state = boards.published({}, "wars", 11)
    state = boards.published(state, "members", 12)
    assert sorted(boards.legacy_ids(state)) == [11, 12]
    state = boards.publish_all(state, 99)
    assert boards.message_id(state) == 99 and boards.legacy_ids(state) == []


def test_pubblicare_il_fissato_spegne_le_bacheche_da_aggiornare_e_tiene_le_righe():
    state = boards.append({}, "members", ["Alex è entrato nel clan"], NOW, TZ)
    assert boards.dirty(state) == ["members"] and boards.message_id(state) is None
    state = boards.publish_all(state, 7)
    assert boards.dirty(state) == [] and boards.message_id(state) == 7
    assert boards.lines_of(state, "members") == ["14:00 · Alex è entrato nel clan"]


def stored(store):
    return store.state.get((CLAN.alias, "boards"))


def board_round(poller, t, events=()):
    async def go():
        for event, text in events:
            await poller.dispatch(t, event, lambda L, text=text: text)
        await poller.flush(t)
        await poller.update_boards(t)

    asyncio.run(go())


def test_due_pacchetti_sporchi_fanno_un_fissato_solo_e_le_righe_restano_nello_stato():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    board_round(poller, t, [("members.movement", "Alex è entrato nel clan"),
                            ("boards.week", "Mario primo della settimana")])
    assert len(bot.sent) == 1 and bot.pins == [101] and bot.edits == []
    text = bot.sent[0][1]
    assert text.split("\n")[0] == L.t("board.all.title", clan=CLAN.name)
    assert "Alex" not in text and "Mario" not in text
    assert L.t("board.title.members") not in text and L.t("board.title.challenges") not in text
    state = stored(store)
    assert "Alex" in boards.lines_of(state, "members")[0]
    assert "Mario" in boards.lines_of(state, "challenges")[0]
    assert boards.message_id(state) == 101 and boards.dirty(state) == []
    board_round(poller, t, [("members.movement", "Bruno ha lasciato il clan")])
    assert len(bot.sent) == 1 and bot.edits == []
    assert "Bruno" in boards.lines_of(stored(store), "members")[1]


def test_il_bottone_della_bacheca_compare_solo_col_sito():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    board_round(poller, t, [("members.movement", "Alex è entrato nel clan")])
    assert bot.markups == [None]
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    poller.site = "https://clanboard.it"
    store.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
    asyncio.run(store.kv_set("console:username", "ClanBoardBot"))
    board_round(poller, t, [("members.movement", "Alex è entrato nel clan")])
    button = bot.markups[0].inline_keyboard[0][0]
    assert button.text == L.t("board.all.open")
    assert button.url == ("https://t.me/ClanBoardBot/ClanBoard?startapp="
                          + payload_mod.slug_for(store.vault, CLAN.alias))


def test_il_bottone_arriva_sul_fissato_gia_scritto_appena_il_sito_risponde():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    board_round(poller, t, [("members.movement", "Alex è entrato nel clan")])
    assert bot.markups == [None] and bot.edits == []
    prima = boards.pin_of(stored(store))["digest"]
    poller.site = "https://clanboard.it"
    store.vault = SimpleNamespace(blind=lambda label, value: f"{label}:{value}")
    asyncio.run(store.kv_set("console:username", "ClanBoardBot"))
    board_round(poller, t)
    assert len(bot.edits) == 1
    button = bot.markups[-1].inline_keyboard[0][0]
    assert button.url == ("https://t.me/ClanBoardBot/ClanBoard?startapp="
                          + payload_mod.slug_for(store.vault, CLAN.alias))
    dopo = boards.pin_of(stored(store))["digest"]
    assert dopo != prima
    board_round(poller, t)
    assert len(bot.edits) == 1 and boards.pin_of(stored(store))["digest"] == dopo


def test_le_vecchie_bacheche_si_sfissano_si_cancellano_e_nasce_il_fissato_nuovo():
    poller, store, bot, t = setup(
        settings_mod.migrate(FUTURO),
        state={(CLAN.alias, "boards"): {"wars": {"lines": ["14:00 · vecchia guerra"], "message_id": 11},
                                        "members": {"lines": ["14:00 · vecchio arrivo"], "message_id": 12}},
               (CLAN.alias, "board"): {"message_id": 101, "digest": "x", "updated": 0.0}})
    bot.pins = [11, 12, 101]
    board_round(poller, t)
    assert bot.unpinned == [11, 12, 101] and bot.deleted == [11, 12, 101]
    assert len(bot.sent) == 1 and bot.pins == [101]
    assert (CLAN.alias, "board") not in store.state
    assert (CLAN.alias, "cwl_board") not in store.state
    state = stored(store)
    assert boards.message_id(state) == 101 and boards.legacy_ids(state) == []
    assert boards.lines_of(state, "wars") == ["14:00 · vecchia guerra"]
    assert boards.lines_of(state, "members") == ["14:00 · vecchio arrivo"]


def test_il_fissato_perso_due_volte_avvisa_i_gestori_e_si_ferma():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO))
    board_round(poller, t, [("members.movement", "Alex è entrato nel clan")])
    assert boards.message_id(stored(store)) == 101
    bot.fail_edit_with = BadRequest("message to edit not found")
    t.now = NOW + timedelta(minutes=11)
    board_round(poller, t)
    assert len(bot.sent) == 2 and boards.message_id(stored(store)) == 102
    assert asyncio.run(feed.rows(store, CLAN.alias, 7)) == []
    t.now = NOW + timedelta(minutes=22)
    board_round(poller, t)
    assert len(bot.sent) == 2
    voci = asyncio.run(feed.rows(store, CLAN.alias, 7))
    assert [(voce["kind"], voce["text"]) for voce in voci] == [("board.lost", L.t("board.all.lost"))]
    assert asyncio.run(feed.rows(store, CLAN.alias, 8)) == voci
    assert asyncio.run(feed.rows(store, CLAN.alias, 9)) == []
    t.now = NOW + timedelta(minutes=25)
    board_round(poller, t)
    assert len(bot.sent) == 2 and len(asyncio.run(feed.rows(store, CLAN.alias, 7))) == 1


def test_la_prima_riga_dice_la_guerra_in_corso_con_gli_attacchi_che_mancano():
    snapshot = boards.ticker_snapshot("Futuro", war_now(), None, None, NOW)
    line = boards.ticker(L, snapshot)
    assert line == L.t("ticker.war", missing=3, left="2h 10m")
    text = boards.render_all(L, {}, ["wars"], "Futuro", TZ, snapshot)
    assert text.split("\n")[0] == line
    assert L.t("board.all.title", clan="Futuro") in text


def test_a_riposo_la_prima_riga_resta_il_titolo_della_bacheca():
    snapshot = boards.ticker_snapshot("Futuro", None, None, None, NOW)
    line = boards.ticker(L, snapshot)
    assert line == L.t("ticker.idle", clan="Futuro") == L.t("board.all.title", clan="Futuro")
    text = boards.render_all(L, {}, ["wars"], "Futuro", TZ, snapshot)
    assert text.split("\n")[0] == line and text.count(line) == 1
    assert text == boards.render_all(L, {}, ["wars"], "Futuro", TZ)


class LingueDiverse:
    def t(self, key, **kw):
        return key

    def delta(self, end, now):
        return "2h"

    def clock(self, when, tz):
        return "12:00"


def test_a_riposo_il_titolo_non_si_ripete_nemmeno_quando_le_lingue_divergono():
    parlata = LingueDiverse()
    riposo = boards.ticker_snapshot("Futuro", None, None, None, NOW)
    assert boards.head_all(parlata, {}, [], "Futuro", TZ, riposo) == "ticker.idle"
    guerra = boards.ticker_snapshot("Futuro", war_now(), None, None, NOW)
    assert boards.head_all(parlata, {}, [], "Futuro", TZ, guerra).split("\n") == \
        ["ticker.war", "board.all.title"]
    assert boards.head_all(parlata, {}, [], "Futuro", TZ).split("\n") == ["board.all.title"]


def test_la_lega_parla_solo_quando_non_ce_la_guerra_normale():
    lega = war_now(our_attacks={"#P1": [("#E1", 3, 100)]}, day=4)
    con_guerra = boards.ticker_snapshot("Futuro", war_now(), lega, None, NOW)
    assert boards.ticker(L, con_guerra) == L.t("ticker.war", missing=3, left="2h 10m")
    solo_lega = boards.ticker_snapshot("Futuro", None, lega, None, NOW)
    assert boards.ticker(L, solo_lega) == L.t("ticker.cwl", day=4, missing=2)


def test_il_raid_parla_quando_guerra_e_lega_non_hanno_piu_niente_da_fare():
    finita = war_now(our_attacks=ALL_DONE)
    aperto = {"state": "ongoing", "free": 5}
    assert boards.ticker(L, boards.ticker_snapshot("Futuro", finita, None, aperto, NOW)) == \
        L.t("ticker.raid", free=5)
    chiuso = {"state": "ended", "free": 5}
    assert boards.ticker(L, boards.ticker_snapshot("Futuro", finita, None, chiuso, NOW)) == \
        L.t("ticker.idle", clan="Futuro")


def test_la_riga_fissa_che_cambia_riscrive_il_fissato_anche_senza_righe_nuove():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO),
                                  state={(CLAN.alias, "war"): war_now()}, now=NOW)
    board_round(poller, t)
    assert len(bot.sent) == 1 and bot.edits == []
    assert bot.sent[0][1].split("\n")[0] == L.t("ticker.war", missing=3, left="2h 10m")
    board_round(poller, t)
    assert bot.edits == []
    t.now = NOW + timedelta(minutes=10)
    board_round(poller, t)
    assert len(bot.sent) == 1 and len(bot.edits) == 1
    assert bot.edits[0][1].split("\n")[0] == L.t("ticker.war", missing=3, left="2h 00m")


def test_le_chiavi_nuove_sono_scritte_in_italiano_e_in_inglese_e_in_inglese_altrove():
    catalogs = {code: json.load(open(i18n.LOCALE_DIR / f"{code}.json", encoding="utf-8"))
                for code in i18n.LANGUAGES}
    for key in NEW_KEYS + TICKER_KEYS:
        assert catalogs["it"][key] and catalogs["en"][key], key
        assert catalogs["it"][key] != catalogs["en"][key], key
        for code in catalogs:
            if code not in ("it", "en"):
                assert catalogs[code][key] == catalogs["en"][key], (code, key)
    for key in SYMBOL_KEYS:
        for code, catalog in catalogs.items():
            assert catalog[key] == catalogs["en"][key], (code, key)


def test_i_numeri_del_fissato_sono_stelle_attacchi_mancanti_e_prossimo_appuntamento():
    numbers = boards.numbers_of(war_now(), agenda.upcoming(NOW), NOW)
    assert numbers["stars"] == (0, 0) and numbers["missing"] == 3
    assert numbers["next"] == {"key": "raid", "in_seconds": 68400}
    finita = war_now(our_attacks=ALL_DONE)
    fatti = boards.numbers_of(finita, agenda.upcoming(NOW), NOW)
    assert fatti["stars"] == (9, 0) and fatti["missing"] == 0
    riposo = boards.numbers_of(None, agenda.upcoming(NOW), NOW)
    assert riposo["stars"] is None and riposo["missing"] == 0
    assert riposo["next"]["key"] == "raid"
    attesa = events_mod.war_snapshot(war_json("preparation", end=END, per_member=1))
    assert boards.numbers_of(attesa, [], NOW) == {"stars": None, "missing": 0, "next": None}
    assert boards.numbers_of(None, [], NOW)["next"] is None


def test_il_fissato_corto_ha_la_riga_viva_e_i_numeri_e_nessuna_sezione():
    war = war_now()
    snapshot = boards.ticker_snapshot("Futuro", war, None, None, NOW)
    text = boards.render_short(L, "Futuro", snapshot,
                               boards.numbers_of(war, agenda.upcoming(NOW), NOW))
    righe = text.split("\n")
    assert len(righe) <= 3
    assert righe[0] == L.t("ticker.war", missing=3, left="2h 10m")
    assert L.t("board.short.stars", us=0, them=0) in righe[1]
    assert L.t("board.short.missing", n=3) not in righe[1]
    assert L.t("board.short.next", what=L.t("agenda.item.raid"), left="19h") in righe[1]
    numeri = boards.numbers_of(war, agenda.upcoming(NOW), NOW)
    assert L.t("board.short.missing", n=3) in boards.numbers_row(L, numeri)
    for pack in boards.SECTION_ORDER:
        assert L.t(f"board.title.{pack}") not in text


def test_senza_guerra_il_fissato_corto_dice_solo_il_prossimo_appuntamento():
    snapshot = boards.ticker_snapshot("Futuro", None, None, None, NOW)
    text = boards.render_short(L, "Futuro", snapshot,
                               boards.numbers_of(None, agenda.upcoming(NOW), NOW))
    righe = text.split("\n")
    assert len(righe) == 2
    assert righe[0] == L.t("ticker.idle", clan="Futuro")
    assert righe[1] == L.t("board.short.next", what=L.t("agenda.item.raid"), left="19h")
    assert boards.render_short(L, "Futuro", None, None) == \
        L.t("board.all.title", clan="Futuro")


def test_il_tempo_che_manca_all_appuntamento_sta_in_una_misura_sola():
    domani = {"key": "games", "in_seconds": 2 * 86400 + 3600}
    assert boards.left_in(L, domani["in_seconds"]) == "2" + L.t("unit.d")
    assert boards.left_in(L, 68400) == "19" + L.t("unit.h")
    assert boards.left_in(L, 300) == "5" + L.t("unit.m")
    assert boards.left_in(L, 0) == "0" + L.t("unit.m")
    assert (boards.DAY, boards.HOUR, boards.MINUTE) == (progress.DAY, progress.DAY // 24,
                                                        progress.DAY // 24 // 60)


def test_il_fissato_corto_non_si_riscrive_per_le_righe_nuove_del_tabellone():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO),
                                  state={(CLAN.alias, "war"): war_now()}, now=NOW)
    board_round(poller, t, [("members.movement", "Alex è entrato nel clan")])
    assert len(bot.sent) == 1 and bot.edits == []
    assert "Alex" not in bot.sent[0][1]
    prima = boards.pin_of(stored(store))["digest"]
    board_round(poller, t, [("members.movement", "Bruno ha lasciato il clan")])
    assert bot.edits == [] and boards.pin_of(stored(store))["digest"] == prima
    righe = boards.lines_of(stored(store), "members")
    assert len(righe) == 2 and "Bruno" in righe[-1]


def test_il_fissato_corto_si_riscrive_quando_cambiano_i_numeri():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO),
                                  state={(CLAN.alias, "war"): war_now()}, now=NOW)
    board_round(poller, t)
    assert len(bot.sent) == 1 and bot.edits == []
    assert L.t("board.short.missing", n=3) not in bot.sent[0][1]
    assert L.t("ticker.war", missing=3, left="2h 10m") in bot.sent[0][1]
    asyncio.run(store.set_state(CLAN.alias, "war", war_now(our_attacks=ALL_DONE)))
    board_round(poller, t)
    assert len(bot.edits) == 1
    assert L.t("board.short.stars", us=9, them=0) in bot.edits[0][1]
    assert L.t("board.short.missing", n=3) not in bot.edits[0][1]


def test_la_riga_del_tabellone_porta_anche_l_evento_strutturato():
    state = boards.append({}, "members", ["Mario è salito al TH15"], NOW, TZ,
                          facts=[{"kind": "th_up", "who": "Mario", "n": 15}])
    assert boards.lines_of(state, "members") == ["14:00 · Mario è salito al TH15"]
    assert boards.events_of(state) == [{"pack": "members", "kind": "th_up", "who": "Mario",
                                        "n": 15, "at": int(NOW.timestamp())}]


def test_gli_eventi_strutturati_arrivano_solo_dai_pacchetti_chiesti_e_dal_piu_fresco():
    state = boards.append({}, "members", ["dentro"], NOW, TZ,
                          facts=[{"kind": "join", "who": "Toad", "n": 13}])
    state = boards.append(state, "wars", ["finita"], NOW + timedelta(minutes=5), TZ,
                          facts=[{"kind": "war_end", "who": "Clan Nemico", "n": 3}])
    assert [row["kind"] for row in boards.events_of(state)] == ["war_end", "join"]
    assert [row["kind"] for row in boards.events_of(state, ("members",))] == ["join"]
    assert boards.events_of({}) == []


def test_la_cronaca_non_cresce_piu_del_tabellone():
    state = {}
    for number in range(40):
        state = boards.append(state, "members", [f"riga {number} " + "x" * 90],
                              NOW + timedelta(minutes=number), TZ,
                              facts=[{"kind": "join", "who": f"Tizio {number}", "n": number}])
    kept = boards.events_of(state)
    assert len(kept) == len(boards.lines_of(state, "members")) < 40
    assert kept[0]["who"] == "Tizio 39"


def test_la_guerra_finita_lascia_anche_l_evento_strutturato_sul_tabellone():
    poller, store, bot, t = setup(settings_mod.migrate(FUTURO),
                                  state={(CLAN.alias, "war"): war_now(ALL_DONE, state="inWar")},
                                  now=NOW)
    board_round(poller, t)
    assert boards.events_of(t.boards) == []
    asyncio.run(store.set_state(CLAN.alias, "war", war_now(ALL_DONE, state="warEnded")))
    board_round(poller, t)
    told = boards.events_of(t.boards)
    assert [row["kind"] for row in told] == ["war_end"]
    assert told[0]["pack"] == "wars" and told[0]["who"] == "Clan Nemico" and told[0]["n"] == 9


def test_una_riga_troppo_lunga_per_il_tabellone_non_lascia_la_cronaca_dietro():
    state = boards.append({}, "members", ["dentro"], NOW, TZ,
                          facts=[{"kind": "join", "who": "Alex", "n": 14}])
    assert len(boards.events_of(state)) == 1
    state = boards.append(state, "members", ["x" * (boards.LIMIT + 1)], NOW, TZ,
                          facts=[{"kind": "leave", "who": "Bruno", "n": None}])
    assert boards.lines_of(state, "members") == []
    assert boards.events_of(state) == []
