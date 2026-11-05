import asyncio
import copy
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import boards, handlers, i18n, render, roster, settings as settings_mod
from clashbot.events_registry import EVENTS
from clashbot.poller import Poller, Tick

DAY = roster.DAY
NOW = 1_800_000_000
YEAR = roster.YEAR_DAYS * DAY

TICK_NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
IT = i18n.locale("it")


def members(*names):
    return {tag: {"name": name} for tag, name in names}


def test_primo_avvistamento_crea_la_riga_con_la_data_di_oggi():
    state, joined, gone = roster.apply({}, members(("#P1", "Mario")), [], NOW)
    assert joined == [] and gone == []
    assert state["#P1"] == {"name": "Mario", "first": NOW, "joined": NOW, "seen": NOW,
                            "stints": 1, "days": 0, "anniv": 0, "optout": False}


def test_giro_successivo_aggiorna_solo_visto_e_nome():
    state, _, _ = roster.apply({}, members(("#P1", "Mario")), [], NOW)
    state, _, _ = roster.apply(state, members(("#P1", "Mario il Grande")), [], NOW + DAY)
    assert state["#P1"]["first"] == NOW and state["#P1"]["joined"] == NOW
    assert state["#P1"]["seen"] == NOW + DAY
    assert state["#P1"]["name"] == "Mario il Grande"


def test_chi_esce_viene_tolto_e_restituito_per_l_archivio():
    state, _, _ = roster.apply({}, members(("#P1", "Mario"), ("#P2", "Luigi")), [], NOW)
    events = [{"type": "leave", "tag": "#P2", "name": "Luigi"}]
    state, _, gone = roster.apply(state, members(("#P1", "Mario")), events, NOW + 10 * DAY)
    assert list(state) == ["#P1"]
    assert [tag for tag, _ in gone] == ["#P2"]
    archived = roster.archive(gone[0][1], NOW + 10 * DAY)
    assert archived["left"] == NOW + 10 * DAY and archived["days"] == 10 and archived["stints"] == 1


def test_chi_sparisce_senza_evento_viene_comunque_archiviato_una_volta_sola():
    state, _, _ = roster.apply({}, members(("#P1", "Mario"), ("#P2", "Luigi")), [], NOW)
    state, _, gone = roster.apply(state, members(("#P1", "Mario")), [], NOW + DAY)
    assert [tag for tag, _ in gone] == ["#P2"]
    state, _, gone = roster.apply(state, members(("#P1", "Mario")), [], NOW + 2 * DAY)
    assert gone == []


def test_il_rientro_riporta_i_giorni_e_conta_un_periodo_in_piu():
    history = {"name": "Luigi", "first": NOW, "joined": NOW, "left": NOW + 10 * DAY,
               "stints": 1, "days": 10, "anniv": 0, "optout": False}
    state = roster.readmit({}, "#P2", history, NOW + 40 * DAY)
    assert state["#P2"]["first"] == NOW
    assert state["#P2"]["joined"] == NOW + 40 * DAY
    assert state["#P2"]["days"] == 10 and state["#P2"]["stints"] == 2
    facts = roster.return_facts(history, NOW + 40 * DAY)
    assert facts == {"name": "Luigi", "away": 30, "days": 10, "stints": 1}


def test_i_giorni_si_sommano_tra_periodi():
    history = {"name": "Luigi", "first": NOW, "joined": NOW, "left": NOW + 10 * DAY,
               "stints": 1, "days": 10, "anniv": 0, "optout": False}
    state = roster.readmit({}, "#P2", history, NOW + 40 * DAY)
    assert roster.tenure_days(state["#P2"], NOW + 45 * DAY) == 15
    archived = roster.archive(state["#P2"], NOW + 45 * DAY)
    assert archived["days"] == 15 and archived["stints"] == 2


def test_elenco_ex_membri_ordinato_dal_piu_recente():
    records = [
        {"name": "Peach", "left": NOW - 3 * DAY, "days": 4, "stints": 1},
        {"name": "Toad", "left": NOW - DAY, "days": 100, "stints": 2},
    ]
    rows = roster.former_rows(records, NOW)
    assert [r["name"] for r in rows] == ["Toad", "Peach"]
    assert rows[0] == {"name": "Toad", "away": 1, "days": 100, "stints": 2}


def test_stato_illeggibile_non_fa_esplodere_nulla():
    state, joined, gone = roster.apply("rotto", members(("#P1", "Mario")), None, NOW)
    assert list(state) == ["#P1"] and joined == [] and gone == []
    assert roster.former_rows(None, NOW) == []
    assert roster.tenure_days(None, NOW) == 0


def test_il_nuovo_arrivato_torna_nella_lista_degli_ingressi():
    events = [{"type": "join", "tag": "#P9", "name": "Yoshi"}]
    state, joined, gone = roster.apply({}, members(("#P9", "Yoshi")), events, NOW)
    assert joined == ["#P9"] and gone == []
    assert state["#P9"]["stints"] == 1


class RosterStore:
    def __init__(self, state=None, former=None):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.former = {key: copy.deepcopy(value) for key, value in (former or {}).items()}
        self.archived = []
        self.dropped = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def former_member(self, alias, tag):
        return copy.deepcopy(self.former.get((alias, tag)))

    async def drop_former(self, alias, tag):
        self.dropped.append(tag)
        return self.former.pop((alias, tag), None) is not None

    async def archive_member(self, alias, tag, obj, left_at):
        self.archived.append((tag, obj, left_at))
        self.former[(alias, tag)] = copy.deepcopy(obj)

    async def former_members(self, alias, limit=40):
        rows = [copy.deepcopy(value) for (clan, _), value in self.former.items() if clan == alias]
        return sorted(rows, key=lambda row: row["left"], reverse=True)[:limit]


def tick_with(store, members_now):
    poller = Poller(SimpleNamespace(bot=lambda alias: None, running=lambda: [],
                                    default_alias="bot-1", owner_bot=lambda: None), store, None)
    t = Tick(CLAN, TICK_NOW)
    t.settings = settings_mod.effective({"lang": "it", "tz": "Europe/Rome"}, None)
    t.L = IT
    t.tz = t.settings["tz"]
    t.members = copy.deepcopy(members_now)
    return poller, t


def test_levento_del_rientro_e_nel_registro_con_le_destinazioni_dei_membri():
    meta = EVENTS["members.rejoin"]
    assert meta["pack"] == "members"
    assert meta["default"] == "group" and "off" in meta["allowed"]
    assert meta["intensity"] is None


def test_il_giro_archivia_chi_esce_e_tiene_lanagrafe():
    stored = {"#P1": roster.new_row("Mario", NOW), "#P2": roster.new_row("Luigi", NOW)}
    store = RosterStore(state={(CLAN.alias, "roster"): stored})
    poller, t = tick_with(store, {"#P1": {"name": "Mario"}})
    asyncio.run(poller.track_roster(t, [{"type": "leave", "tag": "#P2", "name": "Luigi"}]))
    assert [tag for tag, _, _ in store.archived] == ["#P2"]
    assert store.archived[0][2] == TICK_NOW
    assert list(store.state[(CLAN.alias, "roster")]) == ["#P1"]
    assert t.chunks == []


def test_chi_rientra_viene_annunciato_e_lasciato_fuori_dagli_ex():
    history = roster.archive(roster.new_row("Luigi", NOW), NOW + 10 * DAY)
    store = RosterStore(state={(CLAN.alias, "roster"): {"#P1": roster.new_row("Mario", NOW)}},
                        former={(CLAN.alias, "#P2"): history})
    poller, t = tick_with(store, {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}})
    asyncio.run(poller.track_roster(t, [{"type": "join", "tag": "#P2", "name": "Luigi"}]))
    assert store.dropped == ["#P2"]
    row = store.state[(CLAN.alias, "roster")]["#P2"]
    assert row["stints"] == 2 and row["days"] == 10
    assert row["joined"] == int(TICK_NOW.timestamp())
    righe = boards.lines_of(t.boards, "members")
    assert len(righe) == 1 and "Luigi" in righe[0]
    assert store.archived == []


def test_chi_entra_per_la_prima_volta_non_viene_annunciato_come_rientro():
    store = RosterStore(state={(CLAN.alias, "roster"): {"#P1": roster.new_row("Mario", NOW)}})
    poller, t = tick_with(store, {"#P1": {"name": "Mario"}, "#P9": {"name": "Yoshi"}})
    asyncio.run(poller.track_roster(t, [{"type": "join", "tag": "#P9", "name": "Yoshi"}]))
    assert t.chunks == [] and store.dropped == []
    assert store.state[(CLAN.alias, "roster")]["#P9"]["stints"] == 1


def test_la_carta_del_bentornato_elenca_assenza_e_giorni():
    text = render.rejoin_card(IT, [{"name": "Luigi", "away": 30, "days": 10, "stints": 1}])
    assert IT.t("rejoin.title") in text and "Luigi" in text
    assert IT.t("activity.days", n=30) in text and IT.t("rejoin.tail") in text


def test_la_vista_degli_ex_membri_ordina_e_conta():
    rows = roster.former_rows([
        {"name": "Peach", "left": NOW - 3 * DAY, "days": 4, "stints": 1},
        {"name": "Toad", "left": NOW - DAY, "days": 100, "stints": 2},
    ], NOW)
    text = render.former_view(IT, rows)
    assert IT.t("former.title") in text
    assert text.index("Toad") < text.index("Peach")
    assert IT.t("former.count", n=2) in text and IT.t("former.note") in text
    assert IT.t("former.none") in render.former_view(IT, [])


def test_la_vista_degli_ex_membri_dice_anche_in_quanti_periodi():
    rows = roster.former_rows([
        {"name": "Peach", "left": NOW - 3 * DAY, "days": 4, "stints": 1},
        {"name": "Toad", "left": NOW - DAY, "days": 100, "stints": 2},
    ], NOW)
    text = render.former_view(IT, rows)
    assert IT.t("former.stints", n=1) == "1 periodo"
    assert IT.t("former.stints", n=2) == "2 periodi"
    for row in rows:
        assert IT.t("former.row", name=row["name"], away=IT.t("activity.days", n=row["away"]),
                    days=IT.t("activity.days", n=row["days"]),
                    stints=IT.t("former.stints", n=row["stints"])) in text
    en = i18n.locale("en")
    inglese = render.former_view(en, rows)
    assert en.t("former.stints", n=1) in inglese and en.t("former.stints", n=2) in inglese


def test_il_comando_ex_membri_apre_la_lista_degli_usciti():
    assert ("former", ["ex"]) in handlers.COMMANDS
    assert "former" in handlers.VIEWS and ["former"] in handlers.MENU_ROWS
    for key in ("cmd.former", "menu.former"):
        assert not IT.t(key).startswith("["), key
        assert not i18n.locale("en").t(key).startswith("["), key
    left = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
    store = RosterStore(state={(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"}})
    store.former[(CLAN.alias, "#P2")] = {"name": "Luigi", "left": int(left.timestamp()),
                                         "days": 10, "stints": 1}
    context = SimpleNamespace(bot_data={"store": store, "coc": None, "bot_alias": "bot-1"})
    text, keyboard = asyncio.run(handlers.build_view("former", CLAN, context))
    assert IT.t("former.title") in text and "Luigi" in text
    datas = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "v:former" in datas and all(len(d.encode()) <= 64 for d in datas)
    vuota = RosterStore(state={(CLAN.alias, "settings"): {"lang": "it", "tz": "Europe/Rome"}})
    empty, _ = asyncio.run(handlers.build_view(
        "former", CLAN, SimpleNamespace(bot_data={"store": vuota, "coc": None, "bot_alias": "bot-1"})))
    assert IT.t("former.none") in empty


def test_un_anno_pieno_produce_un_anniversario_una_volta_sola():
    state, _, _ = roster.apply({}, members(("#P1", "Mario")), [], NOW)
    assert roster.anniversaries(state, NOW + YEAR - DAY) == []
    due = roster.anniversaries(state, NOW + YEAR)
    assert due == [{"tag": "#P1", "name": "Mario", "years": 1, "days": 365}]
    roster.mark(state, "#P1", 1)
    assert roster.anniversaries(state, NOW + YEAR + DAY) == []
    assert roster.anniversaries(state, NOW + 2 * YEAR) == [
        {"tag": "#P1", "name": "Mario", "years": 2, "days": 730}
    ]


def test_l_anniversario_conta_dal_primo_avvistamento_anche_dopo_un_rientro():
    history = {"name": "Luigi", "first": NOW, "joined": NOW, "left": NOW + 10 * DAY,
               "stints": 1, "days": 10, "anniv": 0, "optout": False}
    state = roster.readmit({}, "#P2", history, NOW + 40 * DAY)
    assert roster.anniversaries(state, NOW + YEAR)[0]["years"] == 1


def test_chi_ha_l_opt_out_non_compare_negli_anniversari():
    state, _, _ = roster.apply({}, members(("#P1", "Mario")), [], NOW)
    state = roster.set_optout(state, "#P1", True)
    assert roster.optout(state, "#P1") is True
    assert roster.anniversaries(state, NOW + YEAR) == []
    state = roster.set_optout(state, "#P1", False)
    assert roster.anniversaries(state, NOW + YEAR) != []


def test_l_opt_out_sopravvive_a_uscita_e_rientro():
    state, _, _ = roster.apply({}, members(("#P1", "Mario")), [], NOW)
    state = roster.set_optout(state, "#P1", True)
    archived = roster.archive(state["#P1"], NOW + DAY)
    assert archived["optout"] is True
    assert roster.readmit({}, "#P1", archived, NOW + 2 * DAY)["#P1"]["optout"] is True


def test_lo_stato_illeggibile_non_produce_anniversari():
    assert roster.anniversaries(None, NOW) == []
    assert roster.anniversaries({"#P1": "rotto"}, NOW) == []
    assert roster.optout(None, "#P1") is False
    assert roster.mark({}, "#P1", 1) == {}
    assert roster.set_optout(None, "#P1", True) == {}


def test_levento_dellanniversario_e_nel_registro_con_le_destinazioni_dei_membri():
    meta = EVENTS["members.anniversary"]
    assert meta["pack"] == "members"
    assert meta["default"] == "group" and "off" in meta["allowed"]
    assert meta["intensity"] is None


def test_la_carta_dellanniversario_dice_gli_anni_e_i_giorni():
    text = render.anniversary_card(IT, [{"tag": "#P1", "name": "Mario", "years": 1, "days": 365}])
    assert IT.t("anniv.title") in text and "Mario" in text
    assert IT.t("activity.days", n=365) in text and IT.t("anniv.tail") in text
    assert IT.t("anniv.row", name="Mario", n=1, days=IT.t("activity.days", n=365)) in text


def test_il_giro_annuncia_lanniversario_una_volta_sola_e_lo_segna():
    now_ts = int(TICK_NOW.timestamp())
    stored = {"#P1": roster.new_row("Mario", now_ts - YEAR)}
    store = RosterStore(state={(CLAN.alias, "roster"): stored})
    poller, t = tick_with(store, {"#P1": {"name": "Mario"}})
    asyncio.run(poller.track_roster(t, []))
    righe = boards.lines_of(t.boards, "members")
    assert len(righe) == 1 and "Mario" in righe[0]
    assert store.state[(CLAN.alias, "roster")]["#P1"]["anniv"] == 1
    poller, t = tick_with(store, {"#P1": {"name": "Mario"}})
    asyncio.run(poller.track_roster(t, []))
    assert t.boards is None


def test_il_giro_non_annuncia_lanniversario_di_chi_ha_lopt_out():
    now_ts = int(TICK_NOW.timestamp())
    stored = {"#P1": roster.set_optout({"#P1": roster.new_row("Mario", now_ts - YEAR)}, "#P1", True)["#P1"]}
    store = RosterStore(state={(CLAN.alias, "roster"): stored})
    poller, t = tick_with(store, {"#P1": {"name": "Mario"}})
    asyncio.run(poller.track_roster(t, []))
    assert t.chunks == []
    assert store.state[(CLAN.alias, "roster")]["#P1"]["anniv"] == 0
