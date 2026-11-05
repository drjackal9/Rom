import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import events_registry, feed, leaders, verify
from clashbot import settings as settings_mod

NOW = datetime(2026, 9, 14, 8, 30, tzinfo=timezone.utc)
NIGHT = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
CLAN = SimpleNamespace(alias="clan-1", chat_id=101, name="Futuro", bot_alias="bot-1")


def test_can_lead_solo_capo_e_co_capo():
    assert leaders.can_lead({"leader"}) is True
    assert leaders.can_lead({"coLeader", "member"}) is True
    assert leaders.can_lead({"admin"}) is False
    assert leaders.can_lead(set()) is False
    assert leaders.can_lead(None) is False


def test_sanitize_taglia_e_compatta():
    assert leaders.sanitize("  ciao  ", 10) == "ciao"
    assert leaders.sanitize("a\r\n\n\n\nb", 10) == "a\n\nb"
    assert leaders.sanitize("x" * 20, 5) == "xxxxx"
    assert leaders.sanitize(None, 5) == ""


def test_fill_scappa_prima_e_sostituisce_dopo():
    assert leaders.fill("<b>{name}</b> nel {clan}", "Mar<io>", "Fu&turo") == (
        "&lt;b&gt;Mar&lt;io&gt;&lt;/b&gt; nel Fu&amp;turo"
    )
    assert leaders.fill("{name}", None, None) == ""


def test_texts_legge_e_ripulisce():
    assert leaders.texts({"texts": {"rules": " no spam ", "welcome": "x" * 2000}})["rules"] == "no spam"
    assert len(leaders.texts({"texts": {"welcome": "x" * 2000}})["welcome"]) == leaders.TEXT_MAX
    assert leaders.texts({}) == {"welcome": "", "rules": ""}
    assert leaders.texts({"texts": "rotto"}) == {"welcome": "", "rules": ""}


def test_slot_accetta_solo_orari_veri():
    assert leaders.slot("08:30") == "08:30"
    assert leaders.slot(" 8:30") is None
    assert leaders.slot("24:00") is None
    assert leaders.slot("08:60") is None
    assert leaders.slot(None) is None


def test_schedule_scarta_le_voci_rotte_e_si_ferma_al_tetto():
    conf = {"scheduled": [
        {"id": "1", "hhmm": "08:00", "days": [0, 9, "x"], "text": " sveglia ", "by": 7},
        {"id": "2", "hhmm": "boh", "text": "no"},
        {"id": "3", "hhmm": "20:00", "text": ""},
    ] + [{"id": str(n), "hhmm": "21:00", "text": "ok"} for n in range(4, 12)]}
    rows = leaders.schedule(conf)
    assert len(rows) == leaders.SCHEDULE_MAX
    assert rows[0] == {"id": "1", "hhmm": "08:00", "days": [0], "text": "sveglia", "by": 7}


def test_new_entry_prende_il_primo_identificativo_libero_e_si_rifiuta_quando_e_pieno():
    entries = [{"id": "1"}, {"id": "3"}]
    assert leaders.new_entry(entries, "07:00", [1, 2], "su", 7)["id"] == "2"
    full = [{"id": str(n)} for n in range(1, leaders.SCHEDULE_MAX + 1)]
    assert leaders.new_entry(full, "07:00", [], "su", 7) is None


def test_due_rispetta_giorno_ora_fuso_e_memoria():
    entries = [{"id": "1", "hhmm": "10:00", "days": [], "text": "a"},
               {"id": "2", "hhmm": "09:00", "days": [0], "text": "b"}]
    due = leaders.due(entries, NOW, "Europe/Rome", {})
    assert [key for key, _ in due] == ["1:2026-09-14", "2:2026-09-14"]
    assert leaders.due(entries, NOW, "UTC", {}) == []
    assert [k for k, _ in leaders.due(entries, NOW, "Europe/Rome", {"1:2026-09-14": 1})] == ["2:2026-09-14"]


def test_prune_sent_tiene_solo_i_giorni_vicini():
    sent = {"vecchio": NOW.timestamp() - 8 * 86400, "nuovo": NOW.timestamp() - 3600, "rotto": "x"}
    assert leaders.prune_sent(sent, NOW) == {"nuovo": NOW.timestamp() - 3600}


class Store:
    def __init__(self, state=None):
        self.state = dict(state or {})
        self.kv = {}

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = obj

    async def bot_by_alias(self, alias):
        return None

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def links_for_players(self, tags):
        return {tag: SimpleNamespace(tag=tag, user_id=7, name="Mario", dm=True, lang=None)
                for tag in tags}


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=1)


def leader_store():
    return Store({(CLAN.alias, "members"): {"#P1": {"name": "Mario", "role": "leader"}}})


def conf_for(quiet=None):
    return settings_mod.effective({"lang": "it", "tz": "Europe/Rome", "quiet": quiet})


def send(store, bot, conf, text="avviso", reply_markup=None, now=NOW):
    return asyncio.run(leaders.notify(store, bot, CLAN, conf, "leaders.gate", text,
                                      reply_markup=reply_markup, now=now))


def test_di_notte_l_avviso_nel_gruppo_va_in_coda_invece_che_in_chat(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("group", None))
    store, bot = leader_store(), Bot()
    send(store, bot, conf_for([23, 7]), now=NIGHT)
    assert bot.sent == []
    assert store.state[(CLAN.alias, "queue")] == ["avviso"]


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def test_di_notte_l_avviso_ai_capi_va_nel_loro_feed(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("leaders_dm", None))
    store, bot = leader_store(), Bot()
    send(store, bot, conf_for([23, 7]), now=NIGHT)
    assert bot.sent == []
    assert feed_rows(store, 7) == ["avviso"]
    assert (CLAN.alias, "queue_dm") not in store.state


def test_di_giorno_e_senza_ore_di_silenzio_parte_subito(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("group", None))
    store, bot = leader_store(), Bot()
    send(store, bot, conf_for([23, 7]))
    assert [chat_id for chat_id, _, _ in bot.sent] == [CLAN.chat_id]
    assert (CLAN.alias, "queue") not in store.state
    muto = leader_store()
    send(muto, Bot(), conf_for(None), now=NIGHT)
    assert (CLAN.alias, "queue") not in muto.state


def test_un_messaggio_con_bottoni_finisce_nel_feed_come_gli_altri(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("leaders_dm", None))
    store, bot = leader_store(), Bot()
    send(store, bot, conf_for([23, 7]), text="decidi", reply_markup="bottoni", now=NIGHT)
    assert bot.sent == [] and feed_rows(store, 7) == ["decidi"]


def test_evento_spento_non_manda_e_non_accoda(monkeypatch):
    monkeypatch.setattr(settings_mod, "route", lambda conf, event: ("off", None))
    store, bot = leader_store(), Bot()
    assert send(store, bot, conf_for([23, 7]), now=NIGHT) == 0
    assert bot.sent == [] and store.state.get((CLAN.alias, "queue")) is None


def test_ogni_evento_del_blocco_e_nel_registro_con_il_suo_pacchetto():
    assert "leaders" in events_registry.PACKS
    for event in leaders.EVENTS:
        entry = events_registry.EVENTS[event]
        assert entry["pack"] == leaders.PACK
        assert entry["default"] in entry["allowed"]
        assert set(entry["allowed"]) <= set(events_registry.DESTINATIONS)


def test_il_pacchetto_dei_capi_e_acceso_in_tutti_i_preset_e_dopo_la_migrazione():
    for preset in settings_mod.PRESETS.values():
        assert preset["packs"]["leaders"] is True
    migrated = settings_mod.migrate({"defenses": True, "achievements": True, "agenda": True,
                                     "polls": True, "movements": True, "board": True})
    assert settings_mod.pack_on(settings_mod.effective(migrated), "leaders") is True


def test_le_chiavi_del_capo_sopravvivono_alla_migrazione():
    stored = {"texts": {"rules": "no spam"}, "scheduled": [{"id": "1", "hhmm": "08:00", "text": "su"}],
              "gate": True}
    conf = settings_mod.effective(settings_mod.migrate(stored))
    assert leaders.texts(conf)["rules"] == "no spam"
    assert leaders.schedule(conf)[0]["hhmm"] == "08:00"
    assert leaders.gate_on(conf) is True


def test_le_destinazioni_private_restano_private():
    conf = settings_mod.effective({})
    for event in ("leaders.promotion", "leaders.trial", "leaders.exit"):
        assert settings_mod.route(conf, event)[0] == "leaders_dm"


def test_i_ruoli_di_comando_sono_quelli_gia_in_uso():
    assert leaders.ROLES == frozenset(verify.LEADER_ROLES)
