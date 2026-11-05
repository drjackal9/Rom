import asyncio
from datetime import timedelta
from types import SimpleNamespace

from telegram.constants import ChatType

from clashbot import i18n, recruit, recruit_cards, recruit_jobs, recruit_tools
from clashbot.crypto import Vault
from clashbot.db import Store

from test_recruit_apply import CLAN, NOW, FakeMessage, FakeQuery, FakeStore, context_for

IT = i18n.locale("it")
INFO = {"level": 18, "members": 46, "league": "Cristallo I", "country": "IT",
        "type": "open", "war_frequency": "always", "labels": ["Clan Wars"]}
FAMILY = SimpleNamespace(alias="fam-1", name="Casa Futuro", chat_id=202)


def test_board_view_nasconde_il_nome_di_chi_e_anonimo():
    rows = [{"code": "ab12cd", "name": None, "tag": None, "level": 18, "free": 4,
             "min_th": 14, "country": "IT", "lang": "it", "league": "Cristallo I"},
            {"code": "ef34gh", "name": "Futuro", "tag": "#CLAN1", "level": 20, "free": 2,
             "min_th": None, "country": "IT", "lang": "it", "league": None}]
    text = recruit_cards.board_view(IT, "Europe/Rome", rows, True, None)
    assert IT.t("recruit.net.anon", code="ab12cd") in text
    assert "Futuro" in text and "OpenClanProfile" in text
    assert "ab12cd" in text and text.count("OpenClanProfile") == 1
    assert len(text) <= 4000
    assert IT.t("recruit.req_th", th=14) in text and IT.t("recruit.req_any") in text


def test_board_view_invita_chi_non_ci_sta():
    text = recruit_cards.board_view(IT, "Europe/Rome", [], False, None)
    assert IT.t("recruit.net.off") in text
    assert IT.t("recruit.net.empty") in recruit_cards.board_view(IT, "Europe/Rome", [], True, None)


def test_board_keyboard_mostra_l_opt_in_solo_a_chi_comanda():
    plain = [b.callback_data for row in recruit_cards.board_keyboard(IT, False, True, "all").inline_keyboard
             for b in row]
    assert plain == ["rb:f:all", "rb:f:country", "rb:f:th"]
    manage = [b.callback_data for row in recruit_cards.board_keyboard(IT, True, False, "all").inline_keyboard
              for b in row]
    assert manage[-1] == "rb:on"
    assert recruit_cards.board_keyboard(IT, True, True, "all").inline_keyboard[-1][0].callback_data == "rb:off"
    assert recruit_cards.open_keyboard(IT).inline_keyboard[0][0].callback_data == "rb:open"


class NetStore(FakeStore):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.published = []
        self.row = None
        self.clock = 0

    def recruit_code(self, clan_alias):
        return "ab12cd"

    def _stamp(self):
        self.clock += 1
        return (NOW + timedelta(seconds=self.clock)).timestamp()

    async def recruit_publish(self, clan_alias, card):
        self.published.append(card)
        self.row = {"recruiting": True, "named": False, "card": card, "ts": self._stamp()}

    async def recruit_row(self, clan_alias):
        return self.row

    async def recruit_stop(self, clan_alias):
        self.row = None
        return True

    async def recruit_board(self, limit=20, country=None, min_th=None, lang=None):
        return []


class FakePoller:
    def __init__(self, store):
        self.store = store


def tick_for(store, settings=None):
    from clashbot import settings as settings_mod
    conf = settings_mod.effective(settings or {"lang": "it", "tz": "Europe/Rome", "min_th": 14})
    t = SimpleNamespace(clan=CLAN, now=NOW, settings=conf, members={"#P1": {"name": "Mario"}})
    t.L = i18n.locale(conf["lang"])
    t.tz = conf["tz"]
    return t


class FamilyStore(NetStore):
    def __init__(self, family=None, **kw):
        super().__init__(**kw)
        self.family = family

    async def family_of_clan(self, clan_alias):
        return self.family

    async def family_by_chat(self, chat_id, bot_alias=None):
        return self.family

    async def family_clans(self, family_alias):
        return [CLAN]


def group_update(query=None, user_id=9):
    return SimpleNamespace(callback_query=query,
                           effective_message=query.message if query else FakeMessage(),
                           effective_chat=SimpleNamespace(id=CLAN.chat_id, type=ChatType.GROUP),
                           effective_user=SimpleNamespace(id=user_id, language_code="it",
                                                          first_name="Toad"))


def recruit_store(family):
    store = FamilyStore(family=family)
    store.state[(CLAN.alias, "info")] = dict(INFO)
    return store


def test_recruit_con_famiglia_manda_una_scheda_sola_e_il_bottone_rete():
    update = group_update()
    asyncio.run(recruit_tools.cmd_recruit(update, context_for(recruit_store(FAMILY))))
    assert len(update.effective_message.sent) == 1
    text, markup = update.effective_message.sent[0]
    assert IT.t("recruit.net.title") not in text
    assert markup.inline_keyboard[0][0].callback_data == "rb:open"


def test_recruit_senza_famiglia_apre_subito_la_bacheca_di_rete():
    update = group_update()
    asyncio.run(recruit_tools.cmd_recruit(update, context_for(recruit_store(None))))
    assert len(update.effective_message.sent) == 1
    text, markup = update.effective_message.sent[0]
    assert IT.t("recruit.net.title") in text
    assert [b.callback_data for b in markup.inline_keyboard[0]] == ["rb:f:all", "rb:f:country", "rb:f:th"]


def test_il_bottone_rete_risponde_senza_cancellare_la_bacheca_di_famiglia():
    query = FakeQuery("rb:open")
    asyncio.run(recruit_tools.on_board_callback(group_update(query=query),
                                                context_for(recruit_store(FAMILY))))
    assert query.edits == []
    assert IT.t("recruit.net.title") in query.message.sent[0][0]


def test_publish_scrive_solo_se_il_clan_e_in_bacheca_e_solo_quando_cambia():
    store = NetStore()
    store.state[(CLAN.alias, "info")] = dict(INFO)
    poller = FakePoller(store)
    asyncio.run(recruit_jobs.publish(poller, tick_for(store)))
    assert store.published == []
    store.row = {"recruiting": True, "named": False, "card": None, "ts": 0}
    asyncio.run(recruit_jobs.publish(poller, tick_for(store)))
    assert store.published[-1]["free"] == 4 and store.published[-1]["name"] is None
    before = len(store.published)
    asyncio.run(recruit_jobs.publish(poller, tick_for(store)))
    assert len(store.published) == before


def test_publish_riscrive_la_riga_una_volta_al_giorno_anche_se_nulla_cambia():
    store = NetStore()
    store.state[(CLAN.alias, "info")] = dict(INFO)
    poller = FakePoller(store)
    t = tick_for(store)
    card = asyncio.run(recruit_jobs.card_for(store, CLAN, t.settings, False))
    store.row = {"recruiting": True, "named": False, "card": card,
                 "ts": (NOW - timedelta(days=1, seconds=1)).timestamp()}
    asyncio.run(recruit_jobs.publish(poller, t))
    assert store.published == [card]
    asyncio.run(recruit_jobs.publish(poller, t))
    assert len(store.published) == 1


def test_publish_toglie_dalla_bacheca_un_clan_pieno():
    store = NetStore()
    store.state[(CLAN.alias, "info")] = {**INFO, "members": 50}
    store.row = {"recruiting": True, "named": True, "card": {"free": 4}, "ts": 0}
    asyncio.run(recruit_jobs.publish(FakePoller(store), tick_for(store)))
    assert store.published[-1] is None


class RecruitPool:
    def __init__(self):
        self.rows = {}
        self.clock = 0

    def _row(self, alias, key_id, data):
        return self.rows.setdefault(alias, {"clan_alias": alias, "visible": False, "named": False,
                                            "key_id": key_id, "data": data, "recruiting": False,
                                            "recruit_data": None, "verified": False,
                                            "updated_at": NOW})

    def _stamp(self):
        self.clock += 1
        return NOW + timedelta(seconds=self.clock)

    async def execute(self, sql, *args):
        if "delete from network_clans" in sql:
            row = self.rows.get(args[0])
            if row and not row["visible"]:
                del self.rows[args[0]]
                return "DELETE 1"
            return "DELETE 0"
        if "set verified" in sql:
            row = self.rows.get(args[0])
            if not row or row["verified"] == args[1]:
                return "UPDATE 0"
            row["verified"] = args[1]
            return "UPDATE 1"
        if "update network_clans" in sql:
            row = self.rows.get(args[0])
            if not row or not row["recruiting"]:
                return "UPDATE 0"
            row.update(recruiting=False, recruit_data=None, updated_at=self._stamp())
            return "UPDATE 1"
        if len(args) == 5:
            alias, visible, named, key_id, data = args
            self._row(alias, key_id, data).update(visible=visible, named=named, key_id=key_id,
                                                  data=data, updated_at=self._stamp())
            return "INSERT 0 1"
        alias, key_id, data, recruit_data = args
        self._row(alias, key_id, data).update(recruiting=True, recruit_data=recruit_data,
                                              updated_at=self._stamp())
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        row = self.rows.get(args[0])
        if row and "and recruiting" in sql and not row["recruiting"]:
            return None
        return row

    async def fetch(self, sql, *args):
        rows = [row for row in self.rows.values() if row["recruiting"] and row["recruit_data"]]
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)


def store_with_pool(tmp_path):
    store = Store(Vault(tmp_path))
    store.pool = RecruitPool()
    return store


def test_lo_store_pubblica_legge_e_dimentica(tmp_path):
    store = store_with_pool(tmp_path)
    alias = CLAN.alias
    asyncio.run(store.recruit_publish(alias, {"level": 18, "free": 4, "min_th": 14, "country": "IT",
                                              "lang": "it", "name": "Futuro", "tag": "#CLAN1"}))
    row = asyncio.run(store.recruit_row(alias))
    assert row["recruiting"] is True and row["card"]["free"] == 4
    board = asyncio.run(store.recruit_board())
    assert [r["code"] for r in board] == [store.recruit_code(alias)]
    assert board[0]["name"] is None and board[0]["tag"] is None
    assert asyncio.run(store.recruit_board(country="ES")) == []
    assert asyncio.run(store.recruit_board(min_th=13)) == []
    assert len(asyncio.run(store.recruit_board(min_th=15))) == 1
    assert asyncio.run(store.recruit_stop(alias)) is True
    assert asyncio.run(store.recruit_row(alias)) is None


def test_il_nome_esce_solo_se_il_clan_e_nominato_nella_rete(tmp_path):
    store = store_with_pool(tmp_path)
    alias = CLAN.alias
    asyncio.run(store.recruit_publish(alias, {"level": 18, "free": 4,
                                              "name": "Futuro", "tag": "#CLAN1"}))
    asyncio.run(store.network_set(alias, True, True, {"name": "Futuro", "tag": "#CLAN1",
                                                      "week": "2026-W37", "metrics": {"avg": 40.7}}))
    board = asyncio.run(store.recruit_board())
    assert board[0]["name"] == "Futuro" and board[0]["tag"] == "#CLAN1"

    async def clan_by_alias(wanted):
        return CLAN if wanted == alias else None

    async def bot_by_alias(wanted):
        return SimpleNamespace(username="BotDelClan") if wanted == CLAN.bot_alias else None

    store.clan_by_alias = clan_by_alias
    store.bot_by_alias = bot_by_alias
    target = asyncio.run(store.recruit_target(board[0]["code"]))
    assert target["tag"] == CLAN.tag and target["bot"] == "BotDelClan"
    assert asyncio.run(store.recruit_target("zzzzzz")) is None


def test_uscire_dalla_bacheca_non_cancella_la_riga_di_rete(tmp_path):
    store = store_with_pool(tmp_path)
    alias = CLAN.alias
    asyncio.run(store.network_set(alias, True, False, {"name": "Futuro", "week": "2026-W37"}))
    asyncio.run(store.recruit_publish(alias, {"level": 18, "free": 4}))
    assert asyncio.run(store.recruit_stop(alias)) is True
    assert asyncio.run(store.recruit_row(alias)) is None
    assert asyncio.run(store.network_get(alias))["visible"] is True


def test_le_chiavi_nuove_esistono_in_inglese_e_non_doppiano_quelle_vecchie():
    from test_recruit_apply import EN
    for key in ("recruit.net.title", "recruit.net.row", "recruit.net.anon", "recruit.net.empty",
                "recruit.net.off", "recruit.net.note", "recruit.net.btn_join", "recruit.net.btn_leave",
                "recruit.net.btn_open", "recruit.net.joined", "recruit.net.left",
                "recruit.net.filter.all", "recruit.net.filter.country", "recruit.net.filter.th"):
        assert key in EN, key
    assert "recruit.net.req" not in EN and "recruit.net.req_any" not in EN
    assert EN["recruit.req_th"] and EN["recruit.req_any"]


def test_il_segno_verificato_esce_solo_per_chi_ha_il_capo_collegato():
    rows = [{"code": "ab12cd", "name": None, "tag": None, "level": 18, "free": 4,
             "min_th": None, "country": "IT", "lang": "it", "verified": True},
            {"code": "ef34gh", "name": None, "tag": None, "level": 20, "free": 2,
             "min_th": None, "country": "IT", "lang": "it", "verified": False}]
    text = recruit_cards.board_view(IT, "Europe/Rome", rows, True, None)
    assert text.count(IT.t("recruit.verified")) == 1
    assert recruit.is_verified(rows[0]) is True
    assert recruit.is_verified(rows[1]) is False
    assert recruit.is_verified(None) is False


class VerifyStore(NetStore):
    def __init__(self, members=None, people=(), **kw):
        super().__init__(**kw)
        self.members = dict(members or {})
        self.people = list(people)
        self.stamped = []

    async def links_for_players(self, tags):
        return {row.tag: row for row in self.people if row.tag in set(tags or ())}

    async def set_network_verified(self, clan_alias, value):
        self.stamped.append((clan_alias, value))


def person(tag, user_id):
    return SimpleNamespace(tag=tag, user_id=user_id, name="Mario", dm=True, lang="it")


def test_il_giro_marca_verificato_il_clan_col_capo_del_gioco_collegato():
    members = {"#P1": {"name": "Mario", "role": "leader"},
               "#P2": {"name": "Luigi", "role": "coLeader"}}
    store = VerifyStore(members=members, people=[person("#P1", 7)])
    t = tick_for(store)
    t.members = members
    asyncio.run(recruit_jobs.stamp_verified(FakePoller(store), t))
    assert store.stamped == [(CLAN.alias, True)]


def test_il_giro_toglie_il_verificato_se_resta_solo_un_co_capo():
    members = {"#P1": {"name": "Mario", "role": "coLeader"}}
    store = VerifyStore(members=members, people=[person("#P1", 7)])
    t = tick_for(store)
    t.members = members
    asyncio.run(recruit_jobs.stamp_verified(FakePoller(store), t))
    assert store.stamped == [(CLAN.alias, False)]


def test_lo_store_ricorda_il_clan_verificato_e_lo_porta_in_bacheca(tmp_path):
    store = store_with_pool(tmp_path)
    alias = CLAN.alias
    asyncio.run(store.recruit_publish(alias, {"level": 18, "free": 4, "min_th": None}))
    assert asyncio.run(store.recruit_board())[0]["verified"] is False
    asyncio.run(store.set_network_verified(alias, True))
    assert asyncio.run(store.recruit_board())[0]["verified"] is True
    assert asyncio.run(store.recruit_row(alias))["card"]["verified"] is True
    assert asyncio.run(store.network_get(alias))["verified"] is True

    async def clan_by_alias(wanted):
        return CLAN if wanted == alias else None

    async def bot_by_alias(wanted):
        return SimpleNamespace(username="BotDelClan") if wanted == CLAN.bot_alias else None

    store.clan_by_alias = clan_by_alias
    store.bot_by_alias = bot_by_alias
    code = store.recruit_code(alias)
    assert asyncio.run(store.recruit_target(code))["verified"] is True
    asyncio.run(store.set_network_verified(alias, False))
    assert asyncio.run(store.recruit_target(code))["verified"] is False
