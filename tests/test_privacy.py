import asyncio
import copy
import json
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import feed, handlers, leaderboards, privacy, reports
from clashbot.db import Store
from clashbot.poller import Poller, Tick

NOW = datetime(2026, 9, 14, 9, tzinfo=timezone.utc)
ALIAS = "clan-1"
CLAN = SimpleNamespace(alias=ALIAS, chat_id=101, tag="#CLAN1", name="Futuro", bot_alias="bot-1")
FAR = SimpleNamespace(alias="clan-9", chat_id=909, tag="#CLAN9", name="Altrove", bot_alias="bot-9")


def link(tag, name, user_id=7, dm=False):
    return SimpleNamespace(alias=f"link-{tag}", user_id=user_id, tag=tag, name=name, dm=dm)


class FakeVault:
    def blind(self, label, value):
        return f"{label}-{value}-0123456789abcdef"


class FakeStore:
    def __init__(self, state=None, links=(), wars=None, clans=(CLAN,), former=()):
        self.vault = FakeVault()
        self.state = {key: copy.deepcopy(value) for key, value in (state or {}).items()}
        self.links = list(links)
        self.wars = {alias: list(rows) for alias, rows in (wars or {}).items()}
        self.clans = list(clans)
        self.former = {tuple(pair) for pair in former}
        self.asked = []
        self.kv = {}
        self.ttls = {}
        self.deleted = []

    async def drop_former(self, alias, tag):
        if (alias, tag) not in self.former:
            return False
        self.former.discard((alias, tag))
        return True

    async def get_state(self, alias, kind):
        return copy.deepcopy(self.state.get((alias, kind)))

    async def set_state(self, alias, kind, obj):
        self.state[(alias, kind)] = copy.deepcopy(obj)

    async def active_clans(self, bot_alias=None):
        self.asked.append(bot_alias)
        return [clan for clan in self.clans if bot_alias is None or clan.bot_alias == bot_alias]

    async def recent_wars(self, alias, limit=10):
        return copy.deepcopy(self.wars.get(alias, [])[:limit])

    async def links_by_user(self, user_id):
        return [row for row in self.links if row.user_id == user_id]

    async def unlink(self, user_id, tag):
        before = len(self.links)
        self.links = [row for row in self.links if not (row.user_id == user_id and row.tag == tag)]
        return len(self.links) < before

    async def kv_get(self, key):
        return copy.deepcopy(self.kv.get(key))

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = copy.deepcopy(obj)
        self.ttls[key] = ttl

    async def kv_del(self, key):
        self.deleted.append(key)
        self.kv.pop(key, None)

    async def report_add(self, clan_alias, user_id, reason, now):
        return await Store.report_add(self, clan_alias, user_id, reason, now)

    async def report_forget(self, clan_alias, user_id):
        return await Store.report_forget(self, clan_alias, user_id)


def test_l_esclusione_vive_nello_stato_delle_classifiche():
    assert privacy.KIND == leaderboards.STATE_KIND
    assert privacy.EXPORT_WARS == privacy.WAR_HISTORY_KEEP


def test_normalize_legge_lista_e_dizionario_e_butta_la_spazzatura():
    assert privacy.normalize(["#P1", "#P2"]) == {
        "#P1": {"since": 0, "name": None, "gone": 0},
        "#P2": {"since": 0, "name": None, "gone": 0},
    }
    assert privacy.normalize({"#P1": {"since": 5, "name": "Mario", "gone": None}}) == {
        "#P1": {"since": 5, "name": "Mario", "gone": 0}
    }
    assert privacy.normalize({"P1": {}, 7: {}, "#P3": "rotto"}) == {"#P3": {"since": 0, "name": None, "gone": 0}}
    assert privacy.normalize(None) == {} and privacy.normalize("x") == {}


def test_esclusione_scritta_letta_e_togliibile_senza_toccare_il_resto_delle_classifiche():
    store = FakeStore({(ALIAS, privacy.KIND): {"sent": {"season": "2026-08"}}})
    assert asyncio.run(privacy.set_excluded(store, ALIAS, "#P1", True, "Mario", NOW)) is True
    assert asyncio.run(privacy.set_excluded(store, ALIAS, "#P1", True, "Mario", NOW)) is False
    assert asyncio.run(privacy.excluded(store, ALIAS)) == {"#P1"}
    state = store.state[(ALIAS, privacy.KIND)]
    assert state["sent"] == {"season": "2026-08"}
    assert state[privacy.KEY]["#P1"] == {"since": int(NOW.timestamp()), "name": "Mario", "gone": 0}
    assert asyncio.run(privacy.set_excluded(store, ALIAS, "#P1", False)) is True
    assert asyncio.run(privacy.set_excluded(store, ALIAS, "#P1", False)) is False
    assert asyncio.run(privacy.excluded(store, ALIAS)) == set()


def test_i_tag_di_una_persona_si_nascondono_e_si_rimostrano_insieme():
    store = FakeStore()
    for tag in ("#P1", "#P9"):
        assert asyncio.run(privacy.set_excluded(store, ALIAS, tag, True, None, NOW)) is True
    assert asyncio.run(privacy.excluded(store, ALIAS)) == {"#P1", "#P9"}
    for tag in ("#P1", "#P9"):
        assert asyncio.run(privacy.set_excluded(store, ALIAS, tag, False)) is True
    assert asyncio.run(privacy.excluded(store, ALIAS)) == set()
    assert privacy.hidden_in({privacy.KEY: ["#P2"]}) == {"#P2"}
    assert privacy.hidden_in(None) == set()


def test_la_scelta_resta_un_anno_dopo_l_uscita_dal_clan():
    old = int((NOW - timedelta(days=privacy.FORGET_KEEP_DAYS + 1)).timestamp())
    store = FakeStore({(ALIAS, privacy.KIND): {privacy.KEY: {
        "#P1": {"since": 1, "name": "Mario", "gone": 0},
        "#P2": {"since": 1, "name": "Luigi", "gone": 0},
        "#P3": {"since": 1, "name": "Peach", "gone": old},
        "#P4": {"since": 1, "name": "Toad", "gone": old},
    }}})
    dropped = asyncio.run(privacy.prune_excluded(store, ALIAS, {"#P1": {}, "#P4": {}}, NOW))
    rows = store.state[(ALIAS, privacy.KIND)][privacy.KEY]
    assert dropped == 1 and "#P3" not in rows
    assert rows["#P1"]["gone"] == 0 and rows["#P4"]["gone"] == 0
    assert rows["#P2"]["gone"] == int(NOW.timestamp())
    assert asyncio.run(privacy.prune_excluded(FakeStore(), ALIAS, {}, NOW)) == 0


def test_la_lista_piatta_di_prima_diventa_un_dizionario_senza_perdere_nessuno():
    store = FakeStore({(ALIAS, privacy.KIND): {privacy.KEY: ["#P1", "#P2"]}})
    assert asyncio.run(privacy.prune_excluded(store, ALIAS, {"#P1": {}}, NOW)) == 0
    rows = store.state[(ALIAS, privacy.KIND)][privacy.KEY]
    assert rows["#P1"] == {"since": 0, "name": None, "gone": 0}
    assert rows["#P2"]["gone"] == int(NOW.timestamp())
    assert asyncio.run(privacy.excluded(store, ALIAS)) == {"#P1", "#P2"}


def test_keep_visible_e_il_filtro_unico_delle_classifiche():
    rows = [{"tag": "#P1", "name": "Mario"}, {"tag": "#P2", "name": "Luigi"}, {"name": "senza tag"}]
    assert privacy.keep_visible(rows, {"#P2"}) == [rows[0], rows[2]]
    assert privacy.keep_visible(rows, set()) == rows
    assert privacy.keep_visible(None, {"#P1"}) == []


def test_le_chiavi_kv_di_una_persona_sono_cieche_e_una_sola_famiglia():
    store = FakeStore()
    keys = privacy.user_keys(store, 7)
    assert keys[0] == privacy.userclan_key(store, 7)
    assert keys[0] == handlers.userclan_key(store, 7)
    assert [key.split(":")[0] for key in keys] == ["userclan", "fb", "md", "tip", "terms"]
    assert keys[0] == "userclan:" + store.vault.blind("user", 7)
    assert keys[1] == "fb:" + store.vault.blind("user", 7)
    assert len(set(keys)) == len(keys)


def test_l_insieme_delle_esclusioni_ha_un_padrone_solo():
    owners = []
    for path in sorted(pathlib.Path(privacy.__file__).parent.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if '"excluded"' in text or "'excluded'" in text:
            owners.append(path.name)
    assert owners == ["privacy.py"]


SEASON = {"id": "2026-09", "members": {"#P1": {
    "name": "Mario", "wars": 3, "attacks": 6, "stars": 14, "triples": 2, "missed": 0,
    "raid_attacks": 5, "loot": 240000, "donations": 900,
}}, "raids": [], "predictions": {"7": {"name": "Mario", "correct": 2, "total": 3}}}

WAR = {"members": [{"tag": "#P1", "name": "Mario", "attacks": [{"stars": 3, "destr": 100.0}], "missed": 0}],
       "attacksPerMember": 2}

HALL = {"seasons": [{"season": "2026-08", "titles": {"MVP": ["Mario", 120], "Donatore": ["Luigi", 900]}}]}


def full_store():
    return FakeStore(
        state={
            (ALIAS, "members"): {"#P1": {"name": "Mario", "role": "leader", "th": 15,
                                         "trophies": 5000, "donations": 900, "received": 100}},
            (ALIAS, "progress"): {"#P1": {"name": "Mario", "now": {"gold": 10}, "last_active": 1,
                                          "week": {"since": 1, "gold": 5}, "month": {"since": 1, "gold": 0}}},
            (ALIAS, "season"): copy.deepcopy(SEASON),
            (ALIAS, "hall"): copy.deepcopy(HALL),
            (ALIAS, "notes"): {"#P1": {"name": "Mario", "text": "riservata ai capi", "by": 9,
                                       "by_name": "Capo", "ts": 1, "gone": None}},
            (ALIAS, "queue_dm"): {"7": ["arretrato"]},
            (ALIAS, privacy.KIND): {privacy.KEY: {"#P1": {"since": 1, "name": "Mario", "gone": 0}}},
        },
        links=[link("#P1", "Mario", dm=True)],
        wars={ALIAS: [copy.deepcopy(WAR)]},
    )


def far_store():
    return FakeStore(
        state={
            (ALIAS, "members"): {"#P1": {"name": "Mario", "role": "member"}},
            ("clan-9", "members"): {"#P9": {"name": "Mario", "role": "coLeader"}},
            ("clan-9", "progress"): {"#P9": {"name": "Mario", "week": {"since": 1, "gold": 5}}},
            ("clan-9", "season"): {"id": "2026-09", "members": {"#P9": {"name": "Mario", "stars": 4}}},
        },
        links=[link("#P1", "Mario", dm=True), link("#P9", "Mario", dm=True)],
        clans=(CLAN, FAR),
    )


def test_collect_mette_dentro_tutto_il_personale_e_lascia_fuori_la_nota_dei_capi():
    payload = asyncio.run(privacy.collect(full_store(), 7, [link("#P1", "Mario", dm=True)], NOW))
    account = payload["accounts"][0]
    assert payload["clans"] == [{"name": "Futuro", "tag": "#CLAN1",
                                 "predictions": {"name": "Mario", "correct": 2, "total": 3}, "queued": 1}]
    assert payload["generated"] == "2026-09-14T09:00:00+00:00"
    assert account["clan"] == {"name": "Futuro", "tag": "#CLAN1"}
    assert account["tag"] == "#P1" and account["private_alerts"] is True
    assert account["hidden_from_boards"] is True
    assert account["clan_row"]["role"] == "leader"
    assert account["activity"]["week"] == {"since": 1, "gold": 5}
    assert account["season"]["stars"] == 14 and account["season_points"] == 70
    assert account["wars"] == {"name": "Mario", "wars": 1, "attacks": 1, "stars": 3,
                               "destr": 100.0, "triples": 1, "missed": 0, "expected": 2}
    assert account["titles"] == [{"season": "2026-08", "title": "MVP"}]
    assert account["leader_note"] is True
    assert "riservata ai capi" not in json.dumps(payload, ensure_ascii=False)


def test_export_e_json_leggibile_anche_per_chi_non_sta_in_nessun_clan():
    payload = asyncio.run(privacy.collect(FakeStore(), 7, [link("#P1", "Mario")], NOW))
    data = json.loads(privacy.export_bytes(payload).decode())
    assert data["clans"] == [] and data["accounts"][0]["clan"] is None
    assert data["accounts"][0]["tag"] == "#P1" and data["accounts"][0]["season_points"] == 0
    assert privacy.export_bytes(payload).startswith(b"{\n")


def test_i_dati_seguono_la_persona_anche_nei_clan_di_un_altro_bot():
    store = far_store()
    payload = asyncio.run(privacy.collect(store, 7, store.links, NOW))
    assert store.asked == [None]
    assert [row["tag"] for row in payload["clans"]] == ["#CLAN1", "#CLAN9"]
    assert [account["clan"]["tag"] for account in payload["accounts"]] == ["#CLAN1", "#CLAN9"]
    assert payload["accounts"][1]["clan_row"]["role"] == "coLeader"


def omonimo_store():
    return FakeStore(
        state={
            (ALIAS, "members"): {"#P1": {"name": "Ares"}},
            ("clan-9", "members"): {"#G1": {"name": "Ares"}, "#G2": {"name": "Zeus"}},
            ("clan-9", "hall"): {"seasons": [{"season": "2026-08",
                                              "titles": {"MVP": ["Ares", 120], "Donatore": ["Zeus", 900]}}]},
        },
        links=[link("#P1", "Ares")],
        clans=(CLAN, FAR),
    )


def test_un_omonimo_in_un_altro_clan_non_ci_tira_dentro_e_non_perde_il_suo_titolo():
    store = omonimo_store()
    links = [link("#P1", "Ares")]
    assert [clan.alias for clan, _ in asyncio.run(privacy.places(store, 7, links))] == [ALIAS]
    payload = asyncio.run(privacy.collect(store, 7, links, NOW))
    assert [row["tag"] for row in payload["clans"]] == ["#CLAN1"]
    counts = asyncio.run(privacy.erase(store, 7, links, NOW))
    assert counts["titles"] == 0
    assert store.state[("clan-9", "hall")]["seasons"][0]["titles"] == {"MVP": ["Ares", 120],
                                                                      "Donatore": ["Zeus", 900]}
    assert asyncio.run(privacy.excluded(store, "clan-9")) == set()


def test_il_titolo_sparisce_dove_la_persona_ha_davvero_un_tag():
    store = FakeStore(
        state={(ALIAS, "progress"): {"#P1": {"name": "Ares"}},
               (ALIAS, "hall"): {"seasons": [{"season": "2026-08", "titles": {"MVP": ["Ares", 120]}}]}},
        links=[link("#P1", "Ares")],
    )
    counts = asyncio.run(privacy.erase(store, 7, [link("#P1", "Ares")], NOW))
    assert counts["titles"] == 1
    assert store.state[(ALIAS, "hall")]["seasons"][0]["titles"] == {}
    assert privacy.local_names({"members": {"#P1": {"name": "Ares"}}}, [link("#P1", "Ares")]) == {"Ares"}
    assert privacy.local_names({"members": {"#G1": {"name": "Ares"}}}, [link("#P1", "Ares")]) == set()


def test_forgetme_ripulisce_e_nasconde_anche_nel_clan_dell_altro_bot():
    store = far_store()
    counts = asyncio.run(privacy.erase(store, 7, list(store.links), NOW))
    assert counts["links"] == 2 and counts["hidden"] == 2 and counts["activity"] == 1 and counts["season"] == 1
    assert asyncio.run(privacy.excluded(store, ALIAS)) == {"#P1"}
    assert asyncio.run(privacy.excluded(store, "clan-9")) == {"#P9"}
    assert store.state[("clan-9", "progress")] == {}
    assert store.state[("clan-9", "season")]["members"] == {}


def test_erase_cancella_il_personale_accende_l_esclusione_e_si_puo_ripetere():
    store = full_store()
    counts = asyncio.run(privacy.erase(store, 7, [link("#P1", "Mario", dm=True)], NOW))
    assert counts == {"links": 1, "keys": 5, "activity": 1, "season": 1, "titles": 1,
                      "notes": 1, "queued": 1, "twitch": 0, "former": 0, "hidden": 0,
                      "feed": 0, "warnings": 0, "reports": 0}
    assert store.links == []
    assert set(store.deleted) == set(privacy.user_keys(store, 7)) | {
        feed.key_of(ALIAS, 7), reports.flood_key(ALIAS, 7)}
    assert store.state[(ALIAS, "progress")] == {}
    assert store.state[(ALIAS, "season")]["members"] == {}
    assert store.state[(ALIAS, "season")]["predictions"] == {}
    assert store.state[(ALIAS, "hall")]["seasons"][0]["titles"] == {"Donatore": ["Luigi", 900]}
    assert store.state[(ALIAS, "notes")] == {}
    assert store.state[(ALIAS, "queue_dm")] == {}
    assert asyncio.run(privacy.excluded(store, ALIAS)) == {"#P1"}
    again = asyncio.run(privacy.erase(store, 7, [], NOW))
    assert again["links"] == 0 and again["activity"] == 0 and again["titles"] == 0


def test_il_pronostico_e_la_posta_in_coda_seguono_l_id_anche_senza_tag():
    store = FakeStore(state={
        (ALIAS, "season"): {"id": "2026-09", "members": {},
                            "predictions": {"7": {"name": "Mario", "correct": 1, "total": 2}}},
        (ALIAS, "queue_dm"): {"7": ["arretrato"]},
    })
    assert [clan.alias for clan, _ in asyncio.run(privacy.places(store, 7, []))] == [ALIAS]
    payload = asyncio.run(privacy.collect(store, 7, [], NOW))
    assert payload["clans"][0]["queued"] == 1 and payload["accounts"] == []
    counts = asyncio.run(privacy.erase(store, 7, [], NOW))
    assert counts["queued"] == 1 and counts["hidden"] == 0
    assert store.state[(ALIAS, "season")]["predictions"] == {}
    assert store.state[(ALIAS, "queue_dm")] == {}


def test_erase_toglie_anche_la_scheda_di_chi_ha_gia_lasciato_il_clan():
    store = FakeStore(state={(ALIAS, "members"): {"#P1": {"name": "Mario"}}},
                      links=[link("#P1", "Mario"), link("#P9", "Uscito")],
                      former=[(ALIAS, "#P1"), (ALIAS, "#P9"), ("clan-9", "#P1")])
    counts = asyncio.run(privacy.erase(store, 7, [link("#P1", "Mario"), link("#P9", "Uscito")], NOW))
    assert counts["former"] == 2
    assert store.former == {("clan-9", "#P1")}
    again = asyncio.run(privacy.erase(store, 7, [link("#P1", "Mario")], NOW))
    assert again["former"] == 0


def test_erase_accende_l_esclusione_solo_dove_la_persona_e_ancora_nel_clan():
    store = FakeStore(state={(ALIAS, "members"): {"#P1": {"name": "Mario"}}},
                      links=[link("#P1", "Mario"), link("#P9", "Uscito")])
    counts = asyncio.run(privacy.erase(store, 7, [link("#P1", "Mario"), link("#P9", "Uscito")], NOW))
    assert counts["hidden"] == 1
    assert asyncio.run(privacy.excluded(store, ALIAS)) == {"#P1"}


def test_lo_scollegamento_resta_uno_solo():
    store = FakeStore(links=[link("#P1", "Mario")])
    assert asyncio.run(handlers.drop_link(store, 7, link("#P1", "Mario"))) is True
    assert store.deleted == [privacy.userclan_key(store, 7)]
    assert asyncio.run(privacy.drop_link(store, 7, link("#P1", "Mario"))) is False


def test_la_potatura_delle_esclusioni_gira_nel_giro_del_poller():
    store = FakeStore({(ALIAS, privacy.KIND): {privacy.KEY: {
        "#P1": {"since": 1, "name": "Mario", "gone": 0},
        "#P2": {"since": 1, "name": "Luigi", "gone": 0},
    }}})
    t = Tick(CLAN, NOW)
    t.members = {"#P1": {"name": "Mario"}}
    asyncio.run(Poller(SimpleNamespace(), store, None).track_progress(t, []))
    rows = store.state[(ALIAS, privacy.KIND)][privacy.KEY]
    assert rows["#P1"]["gone"] == 0 and rows["#P2"]["gone"] == int(NOW.timestamp())
