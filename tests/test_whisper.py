import asyncio
import copy
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fixtures import war_json
from telegram.error import BadRequest, Forbidden

from clashbot import events, i18n, whisper

ALIAS = "clan-1"
GROUP = -100
END = datetime(2026, 9, 12, 10, tzinfo=timezone.utc)
NOW = END - timedelta(minutes=20)


def snap(state="inWar", **kw):
    return events.war_snapshot(war_json(state, **kw))


def link(tag, user_id, name, on=True):
    return SimpleNamespace(alias=f"link-{tag}", tag=tag, user_id=user_id, name=name,
                           dm=True, lang=None, whisper=on)


class FakeBot:
    def __init__(self, error=None, delete_error=None):
        self.sent = []
        self.deleted = []
        self.error = error
        self.delete_error = delete_error

    async def send_message(self, chat_id, text, **kw):
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text, kw.get("disable_notification")))
        return SimpleNamespace(message_id=500 + len(self.sent))

    async def delete_message(self, chat_id, message_id):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append((chat_id, message_id))


class FakeStore:
    def __init__(self, state=None, links=()):
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.links = list(links)
        self.muted = []

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def del_state(self, alias, kind):
        self.state.pop((alias, kind), None)

    async def links_for_players(self, tags):
        wanted = set(tags or ())
        return {row.tag: row for row in self.links if row.tag in wanted}

    async def set_link_whisper(self, user_id, tag, value):
        self.muted.append((user_id, tag, value))
        for row in self.links:
            if row.user_id == user_id and row.tag == tag:
                row.whisper = value


def nudges(store):
    return store.state.get((ALIAS, whisper.STATE))


def stored(war, **rows):
    key = events.war_key(war)
    return {tag: [dict(entry, war=entry.get("war", key)) for entry in entries]
            for tag, entries in rows.items()}


def test_il_sussurro_parte_solo_per_chi_lo_ha_chiesto_e_arriva_senza_suono():
    bot = FakeBot()
    acceso = link("#P2", 8, "Luigi")
    assert asyncio.run(whisper.send(bot, acceso, "manca il tuo attacco", NOW)) == {
        "chat_id": 8, "message_id": 501,
    }
    assert bot.sent == [(8, "manca il tuo attacco", True)]


def test_senza_il_sussurro_acceso_il_bot_non_scrive_in_privato():
    bot = FakeBot()
    assert asyncio.run(whisper.send(bot, link("#P3", 9, "Peach", on=False), "ciao", NOW)) is None
    assert bot.sent == []


def test_chi_ha_chiuso_il_privato_si_spegne_il_sussurro_senza_errori():
    bot = FakeBot(error=Forbidden("bot was blocked by the user"))
    chiuso = link("#P2", 8, "Luigi")
    assert asyncio.run(whisper.send(bot, chiuso, "manca il tuo attacco", NOW)) is None
    assert chiuso.whisper is False and bot.sent == []


def test_un_guasto_di_telegram_non_ferma_il_giro():
    bot = FakeBot(error=BadRequest("message text is empty"))
    acceso = link("#P2", 8, "Luigi")
    assert asyncio.run(whisper.send(bot, acceso, "manca il tuo attacco", NOW)) is None
    assert acceso.whisper is True


def test_le_menzioni_si_ricordano_sotto_il_tag_di_chi_e_nominato():
    store = FakeStore()
    war = snap()
    rows = whisper.group_rows(
        [(None, {"war": events.war_key(war), "tags": ["#P2", "#P3"]})], None, GROUP, 42,
    )
    asyncio.run(whisper.remember(store, ALIAS, rows))
    asyncio.run(whisper.remember(store, ALIAS, rows))
    voce = {"chat_id": GROUP, "message_id": 42, "war": events.war_key(war)}
    assert nudges(store) == {"#P2": [voce], "#P3": [voce]}


def test_le_menzioni_di_un_altro_filo_non_finiscono_nel_ricordo():
    war = snap()
    named = [(7, {"war": events.war_key(war), "tags": ["#P2"]})]
    assert whisper.group_rows(named, None, GROUP, 42) == []
    assert [row["tag"] for row in whisper.group_rows(named, 7, GROUP, 42)] == ["#P2"]


def test_senza_un_id_di_messaggio_non_si_ricorda_niente():
    named = [(None, {"war": "k", "tags": ["#P2"]})]
    assert whisper.group_rows(named, None, GROUP, None) == []
    assert whisper.group_rows(named, None, GROUP, True) == []


def shape(groups):
    return [([kind for kind, _ in group], marked) for group, marked in groups]


def test_chi_nomina_persone_esce_staccato_da_chi_non_nomina_nessuno():
    named = [(None, {"war": "k", "tags": ["#P2"], "kind": "reminder"})]
    chunks = [("reminder", "manca il tuo attacco"), ("war.risk", "rischio sconfitta")]
    assert shape(whisper.split_named(named, None, chunks)) == [
        (["reminder"], {"reminder"}), (["war.risk"], set()),
    ]


def test_i_pezzi_che_nominano_persone_restano_insieme():
    named = [(None, {"war": "k", "tags": ["#P2"], "kind": "reminder"}),
             (None, {"war": "k", "tags": ["#P3"], "kind": "war.last_call"})]
    chunks = [("war.risk", "rischio"), ("reminder", "promemoria"), ("war.last_call", "ultima")]
    assert shape(whisper.split_named(named, None, chunks)) == [
        (["war.risk"], set()), (["reminder", "war.last_call"], {"reminder", "war.last_call"}),
    ]


def test_senza_menzioni_i_pezzi_restano_un_messaggio_solo():
    chunks = [("war_end", "finita"), ("war.risk", "rischio")]
    assert shape(whisper.split_named([], None, chunks)) == [(["war_end", "war.risk"], set())]
    assert whisper.split_named([], None, []) == []


def test_le_menzioni_di_un_altro_filo_non_staccano_i_pezzi():
    named = [(7, {"war": "k", "tags": ["#P2"], "kind": "reminder"})]
    chunks = [("reminder", "promemoria"), ("war.risk", "rischio")]
    assert shape(whisper.split_named(named, None, chunks)) == [(["reminder", "war.risk"], set())]


def test_ogni_menzione_si_ricorda_solo_nel_messaggio_in_cui_e_uscita():
    named = [(None, {"war": "k", "tags": ["#P2"], "kind": "reminder"}),
             (None, {"war": "k", "tags": ["#P3"], "kind": "war.last_call"})]
    assert [row["tag"] for row in whisper.group_rows(named, None, GROUP, 42, {"reminder"})] == ["#P2"]
    assert [row["tag"] for row in whisper.group_rows(named, None, GROUP, 42)] == ["#P2", "#P3"]


def test_il_messaggio_del_gruppo_resta_finche_uno_dei_nominati_non_ha_attaccato():
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)],
                            "#P2": [("#E2", 3, 100), ("#E3", 2, 50)]})
    bot = FakeBot()
    store = FakeStore(state={(ALIAS, whisper.STATE): stored(
        war,
        **{"#P2": [{"chat_id": GROUP, "message_id": 42}, {"chat_id": 8, "message_id": 77}],
           "#P3": [{"chat_id": GROUP, "message_id": 42}]},
    )})
    asyncio.run(whisper.settle(bot, store, ALIAS, war, NOW))
    assert bot.deleted == [(8, 77)]
    assert nudges(store) == {"#P3": [{"chat_id": GROUP, "message_id": 42,
                                      "war": events.war_key(war)}]}


def test_quando_tutti_i_nominati_hanno_attaccato_la_menzione_sparisce():
    war = snap(our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 2, 60)],
                            "#P2": [("#E2", 3, 100), ("#E3", 2, 50)],
                            "#P3": [("#E3", 3, 100), ("#E1", 1, 30)]})
    bot = FakeBot()
    store = FakeStore(state={(ALIAS, whisper.STATE): stored(
        war,
        **{"#P2": [{"chat_id": GROUP, "message_id": 42}],
           "#P3": [{"chat_id": GROUP, "message_id": 42}]},
    )})
    asyncio.run(whisper.settle(bot, store, ALIAS, war, NOW))
    assert bot.deleted == [(GROUP, 42)]
    assert nudges(store) is None


def test_a_guerra_finita_le_menzioni_se_ne_vanno_tutte():
    war = snap("warEnded")
    bot = FakeBot()
    store = FakeStore(state={(ALIAS, whisper.STATE): stored(
        war,
        **{"#P2": [{"chat_id": GROUP, "message_id": 42}, {"chat_id": 8, "message_id": 77}],
           "#P3": [{"chat_id": GROUP, "message_id": 42}]},
    )})
    asyncio.run(whisper.settle(bot, store, ALIAS, war, END + timedelta(minutes=1)))
    assert sorted(bot.deleted) == [(GROUP, 42), (8, 77)]
    assert nudges(store) is None


def test_le_menzioni_di_una_guerra_ancora_viva_non_si_toccano():
    war = snap()
    altra = events.war_snapshot(war_json("inWar", end="20260915T100000.000Z", opp_tag="#ALTRO"))
    bot = FakeBot()
    salvate = stored(altra, **{"#P2": [{"chat_id": GROUP, "message_id": 9}]})
    store = FakeStore(state={(ALIAS, whisper.STATE): salvate})
    asyncio.run(whisper.settle(bot, store, ALIAS, war, NOW))
    assert bot.deleted == [] and nudges(store) == salvate


def test_chi_blocca_il_bot_perde_il_sussurro_anche_alla_cancellazione():
    war = snap(our_attacks={"#P2": [("#E2", 3, 100), ("#E3", 2, 50)]})
    bot = FakeBot(delete_error=Forbidden("bot was blocked by the user"))
    luigi = link("#P2", 8, "Luigi")
    store = FakeStore(
        state={(ALIAS, whisper.STATE): stored(war, **{"#P2": [{"chat_id": 8, "message_id": 77}]})},
        links=[luigi],
    )
    asyncio.run(whisper.settle(bot, store, ALIAS, war, NOW))
    assert store.muted == [(8, "#P2", False)] and luigi.whisper is False
    assert nudges(store) is None


def test_l_interruttore_del_sussurro_ha_le_sue_due_chiavi_in_tutti_i_cataloghi():
    for code in sorted(i18n.LANGUAGES):
        locale = i18n.locale(code)
        for key in ("whisper.on", "whisper.off"):
            assert not locale.t(key).startswith("["), (code, key)
    assert i18n.locale("it").t("whisper.on") != i18n.locale("en").t("whisper.on")


def test_il_sussurro_e_l_unica_strada_privata_dei_bot_dei_clan():
    root = pathlib.Path(whisper.__file__).parent
    for name in ("poller.py", "war_live.py"):
        assert "send_message" not in (root / name).read_text(encoding="utf-8"), name
    privati = [path.name for path in sorted(root.glob("*.py"))
               if "send_message(link.user_id" in path.read_text(encoding="utf-8")]
    assert privati == ["whisper.py"]


def test_senza_bot_le_menzioni_restano_in_attesa():
    war = snap(our_attacks={"#P2": [("#E2", 3, 100), ("#E3", 2, 50)]})
    salvate = stored(war, **{"#P2": [{"chat_id": 8, "message_id": 77}]})
    store = FakeStore(state={(ALIAS, whisper.STATE): salvate})
    asyncio.run(whisper.settle(None, store, ALIAS, war, NOW))
    assert nudges(store) == salvate
