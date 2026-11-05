import asyncio
from types import SimpleNamespace

from clashbot import (acts, base_packs, base_videos, boards, cwl_roster, cwl_season, derby,
                      discipline, door,
                      exports, feed, guard, i18n, intents, leaders, ledger, manager_actions,
                      manager_lists, manager_net, manager_staff, platform_ban, reasons, recruit,
                      recruit_block,
                      retention,
                      roles, seats, setup_ui, undo)
from clashbot import settings as settings_mod
from clashbot.crypto import Vault
from clashbot.db import Store
from clashbot.events import member_snapshot, war_snapshot
from clashbot.events_registry import TEXT_REFUSED
from clashbot.web import app_manage, miniapp, payload
from fixtures import BASE_MEMBERS, clan_json, war_json
from test_intents import ActStore
from test_roles import FakeCoc
from test_web_publish import CLAN, INFO, NOW, beat_for

IT = i18n.locale("it")
CHIEF = 7
DEPUTY = 8
ELDER = 9
STRANGER = 11
GUEST = 13
RIVAL = 14
TAGS = {CHIEF: "#P1", DEPUTY: "#P2", ELDER: "#P3", STRANGER: "#P4"}
LIVE_LEADER = {"#P1": {"role": "leader", "clan": {"tag": CLAN.tag}}}
LIVE_MEMBER = {"#P1": {"role": "member", "clan": {"tag": CLAN.tag}}}
MEMBERS = member_snapshot(clan_json(BASE_MEMBERS))
STORED = {"lang": "it", "tz": "Europe/Rome"}
WAR = war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]}))
SEASON = "2026-09"
CWL = {"season": SEASON, "clans": {CLAN.tag: {"members": [
    {"tag": "#P1", "name": "Mario", "th": 16}, {"tag": "#P2", "name": "Luigi", "th": 15}]}}}
FAMILY = SimpleNamespace(alias="fam-1", name="Famiglia", owner_id=CHIEF, bot_alias="bot-1",
                         chat_id=None)
GESTI = ("settings.open", "settings.press", "welcome.set", "rules.set",
         "warning.confirm", "warning.void",
         "cwl.roster.set", "cwl.lineup.set", "cwl.bonus.toggle",
         "schedule.add", "schedule.delete", "gate.toggle", "note.set", "export.csv",
         "recruit.requirements.set", "application.decide", "sender.block", "sender.unblock",
         "family.create", "family.invite", "family.derby", "family.tourney",
         "integration.twitch", "integration.discord", "integration.ics",
         "page.toggle", "channel.add", "channel.drop",
         "delegate.add", "delegate.remove", "delegates.clear", "clan.pause", "clan.resume",
         "undo.apply", "suspension.lift", "share.clan",
         "base.accept", "base.reject", "view.set", "family.score.toggle",
         "person.approve", "person.revoke", "person.trust")
LIMITED_GESTI = ("warning.confirm", "person.approve")
WARN_ID = "0123456789abcdef01234567"
CHANNEL = {"id": "UCaaaaaaaaaaaaaaaaaaaaaa", "title": "Canale"}


def link(tag, user_id, name, verified=True):
    return SimpleNamespace(tag=tag, user_id=user_id, name=name, dm=True, lang="it",
                           verified=verified)


LINKS = [link("#P1", CHIEF, "Mario"), link("#P3", ELDER, "Peach"), link("#P4", STRANGER, "Toad")]


class NoRows:
    async def fetch(self, *args):
        return []


class ToolStore(ActStore):
    claim_add = Store.claim_add
    claims_pending = Store.claims_pending

    def __init__(self, vault):
        super().__init__(vault)
        self.families = {}
        self.in_family = {}
        self.docs = {}
        self.recruit_rows = {}
        self.pool = NoRows()

    async def link_player(self, user_id, tag, name, dm=False, lang=None):
        self.links = [one for one in self.links if one.tag != tag]
        self.links.append(link(tag, user_id, name))
        return f"link-{tag}"

    async def set_link_verified(self, user_id, tag, value):
        for one in self.links:
            if one.tag == tag and one.user_id == user_id:
                one.verified = bool(value)

    async def create_family(self, name, owner_id, bot_alias=None):
        alias = f"fam-{len(self.families) + 1}"
        self.families[alias] = SimpleNamespace(alias=alias, name=name, owner_id=owner_id,
                                               bot_alias=bot_alias, chat_id=None)
        return alias

    async def family_by_alias(self, alias):
        return self.families.get(alias)

    async def family_of_clan(self, clan_alias):
        return self.families.get(self.in_family.get(clan_alias))

    async def family_clans(self, family_alias):
        return [CLAN for alias, found in self.in_family.items()
                if found == family_alias and alias == CLAN.alias]

    async def add_family_clan(self, family_alias, clan_alias):
        self.in_family[clan_alias] = family_alias
        return True

    async def create_tournament(self, doc, owner_id, family_alias=None, clan_alias=None):
        alias = f"tr-{len(self.docs) + 1}"
        self.docs[alias] = dict(doc, alias=alias)
        return alias

    async def save_tournament(self, alias, doc, status=None):
        self.docs[alias] = dict(doc, alias=alias)
        return True

    async def tournament(self, alias):
        return self.docs.get(alias)

    async def recruit_row(self, clan_alias):
        return self.recruit_rows.get(clan_alias)


def manager_store(tmp_path, war=None, cwl=None, cls=ToolStore):
    store = cls(Vault(tmp_path))
    store.links = list(LINKS)
    asyncio.run(store.set_state(CLAN.alias, "settings", dict(STORED)))
    asyncio.run(store.set_state(CLAN.alias, "members", MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    if war:
        asyncio.run(store.set_state(CLAN.alias, "war", war))
    if cwl:
        asyncio.run(store.set_state(CLAN.alias, "cwl", cwl))
    return store


def ref_of(store, uid):
    return seats.seat_ref(store.vault, CLAN.alias, int(uid))


def mark_of(store, uid):
    return payload.mark_for(store.vault, payload.slug_for(store.vault, CLAN.alias), int(uid))


def with_ref(store, body):
    if "person" in body:
        kept = {key: value for key, value in body.items() if key != "person"}
        return dict(kept, who=mark_of(store, body["person"]))
    if "who" not in body:
        return body
    return dict(body, who=ref_of(store, body["who"]))


def row(kind, body, uid, ident):
    return {"id": 1, "clan": CLAN.alias, "kind": kind,
            "body": dict(body, kind=kind, by=uid, tag=TAGS[uid], id=ident)}


def applied(store, kind, body, uid=CHIEF, ident="a1", coc=None):
    return asyncio.run(intents.apply_one(store, beat_for(store, coc=coc),
                                         row(kind, with_ref(store, body), uid, ident), NOW))


def saved(store):
    return asyncio.run(store.get_state(CLAN.alias, "settings"))


def conf_of(store):
    return settings_mod.effective(saved(store), None)


def page_of(store):
    return store.pages[(CLAN.alias, payload.APP)][1]


def screen_of(store, uid=CHIEF):
    return ((page_of(store).get(payload.MANAGE) or {}).get(str(uid)) or {}).get("settings")


def staff_of(store, uid=CHIEF):
    return ((page_of(store).get(payload.MANAGE) or {}).get(str(uid)) or {}).get(acts.STAFF)


def tools_of(store, pack=None):
    found = page_of(store).get(payload.TOOLS) or {}
    return found.get(pack) if pack else found


def wizard_screen(store, step, uid=CHIEF):
    state = setup_ui.from_settings(conf_of(store), CLAN.alias, uid, None)
    state["step"] = step
    text, markup = setup_ui.screen(IT, state, step)
    return {"text": text,
            "buttons": [[{"label": button.text, "data": button.callback_data} for button in line]
                        for line in markup.inline_keyboard]}


def datas(screen):
    return [button["data"] for line in screen["buttons"] for button in line]


def cb(action, value=None):
    head = f"cfg:{CLAN.alias}:{action}"
    return head if value is None else f"{head}:{value}"


BASE_LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16%3AHV%3AAaBbCcDd"


def base_proposal(ref):
    return {"id": ref, "name": "Mario", "label": "war", "village": "home", "hall": 16,
            "link": f"{BASE_LINK}{ref}"}


def warning_row(tag="#P3", name="Peach"):
    return {"id": WARN_ID, "tag": tag, "name": name, "war": "w1", "missed": 2,
            "at": NOW.timestamp(), "by": "#P1"}


def with_everything(tmp_path):
    store = manager_store(tmp_path, war=WAR, cwl=CWL)
    store.links = [link("#P1", CHIEF, "Mario"), link("#P3", ELDER, "Peach"),
                   link("#P4", STRANGER, "Toad", False)]
    asyncio.run(store.set_state(CLAN.alias, discipline.STATE, [warning_row()]))
    entry = {"id": "1", "hhmm": "20:30", "days": [], "text": "Ci siamo", "by": CHIEF}
    asyncio.run(store.set_state(CLAN.alias, "settings",
                                dict(STORED, scheduled=[entry], delegates=[STRANGER])))
    asyncio.run(store.kv_set(guard.suspended_key(CLAN.alias, ELDER), {"at": NOW.timestamp()},
                             ref=CLAN.alias))
    asyncio.run(store.claim_add(CLAN.alias, GUEST, "#P4", "Toad", NOW))
    state, _ = recruit.add(recruit.state_of(None), "#N1", {"name": "Nuovo", "th": 15},
                           STRANGER, True, ["war"], False, NOW)
    asyncio.run(store.set_state(CLAN.alias, recruit.KIND, state))
    blocks, _ = recruit_block.add(recruit_block.state_of(None), GUEST, "Toad", NOW)
    asyncio.run(store.set_state(CLAN.alias, recruit_block.KIND, blocks))
    store.families[FAMILY.alias] = FAMILY
    store.in_family[CLAN.alias] = FAMILY.alias
    store.docs["dy-1"] = {"alias": "dy-1", "kind": "derby", "scope": "family", "metric": "both",
                          "format": "table", "opens": int(NOW.timestamp()),
                          "starts": int(NOW.timestamp()) + 60, "ends": int(NOW.timestamp()) + 600,
                          "entries": [], "log": [], "rounds": []}
    asyncio.run(store.kv_set(derby.saved_key(FAMILY.alias), {"alias": "dy-1"}, ref=FAMILY.alias))
    asyncio.run(store.set_state(CLAN.alias, base_packs.PROPOSED_STATE,
                                [base_proposal("ab12"), base_proposal("cd34")]))
    asyncio.run(store.set_state(CLAN.alias, door.KIND,
                                door.seed(door.state_of(None), [CHIEF], NOW.timestamp())))
    return store


def with_claim(tmp_path):
    store = manager_store(tmp_path)
    store.links = [link("#P1", CHIEF, "Mario"), link("#P3", ELDER, "Peach"),
                   link("#P4", STRANGER, "Toad", False)]
    asyncio.run(store.claim_add(CLAN.alias, GUEST, "#P4", "Toad", NOW))
    return store


BODIES = {
    "settings.press": {"data": cb("preset", "casual_clan")},
    "welcome.set": {"text": "Benvenuto {name}"},
    "rules.set": {"text": "Si attacca sempre"},
    "warning.confirm": {"village": "#P3"},
    "warning.void": {"ref": WARN_ID},
    "cwl.roster.set": {"village": "#P1", "choice": cwl_roster.IN},
    "cwl.lineup.set": {"village": "#P1"},
    "cwl.bonus.toggle": {"village": "#P1"},
    "schedule.add": {"hhmm": "21:15", "days": "135", "text": "Attacchiamo"},
    "schedule.delete": {"ref": "1"},
    "gate.toggle": {"on": "on"},
    "note.set": {"village": "#P3", "text": "Da seguire"},
    "export.csv": {"sheet": "members"},
    "recruit.requirements.set": {"th": "14"},
    "application.decide": {"ref": "1", "choice": "accepted"},
    "sender.block": {"ref": "1"},
    "sender.unblock": {"ref": "1"},
    "family.create": {"name": "Nuova Famiglia"},
    "family.invite": {"ref": FAMILY.alias},
    "family.derby": {"data": "dy:go"},
    "family.tourney": {"data": "tr:go"},
    "integration.twitch": {"channel": "canaletest"},
    "integration.discord": {"on": "off"},
    "integration.ics": {"on": "on"},
    "page.toggle": {"on": "on"},
    "channel.add": {"channel": CHANNEL["id"]},
    "channel.drop": {"channel": CHANNEL["id"]},
    "delegate.add": {"who": str(ELDER)},
    "delegate.remove": {"who": str(STRANGER)},
    "delegates.clear": {},
    "clan.pause": {},
    "clan.resume": {},
    "undo.apply": {"of": "warning", "ref": WARN_ID},
    "suspension.lift": {"who": str(ELDER)},
    "base.accept": {"ref": "ab12"},
    "base.reject": {"ref": "cd34"},
    "view.set": {"section": "league", "value": "managers"},
    "family.score.toggle": {},
    "person.approve": {"person": ELDER, "war_from": "now"},
    "person.revoke": {"person": CHIEF},
    "person.trust": {"person": CHIEF, "value": "on"},
}


def test_ogni_gesto_del_gestore_ha_il_suo_posto_nel_registro():
    assert intents.KINDS_MANAGER == acts.KINDS_MANAGER == GESTI
    assert set(acts.FIELDS) == set(intents.REGISTRY)
    for kind in acts.KINDS_MANAGER:
        action, handler = intents.REGISTRY[kind]
        wanted = settings_mod.LIMITED if kind in LIMITED_GESTI else settings_mod.MANAGER
        assert callable(handler), kind
        assert acts.LEVELS[kind] == settings_mod.ACTIONS[action] == wanted, kind
        assert miniapp.manager_only(kind) is True, kind


def test_ogni_gesto_del_gestore_lascia_la_sua_riga_nel_registro(tmp_path):
    assert set(BODIES) == (set(acts.KINDS_MANAGER) - set(acts.SETUP_KINDS)
                           - set(acts.SHARE_MANAGER) | {"settings.press"})
    for index, kind in enumerate(BODIES):
        store = with_everything(tmp_path)
        assert applied(store, kind, BODIES[kind], ident=f"g{index}") is True, kind
        assert len(store.logs) == 1, kind
        alias, entry = store.logs[0]
        assert alias == CLAN.alias and (entry.get("action") or entry.get("kind")), kind


def test_le_impostazioni_si_aprono_nell_app_col_primo_passo_del_wizard(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "settings.open", {}) is True
    found = screen_of(store)
    assert found == wizard_screen(store, setup_ui.STEPS[0])
    assert datas(found) == [cb("preset", name) for name in settings_mod.PRESETS] + [cb("next")]
    assert found["text"] and not found["text"].startswith("[")
    assert asyncio.run(manager_actions.step_of(store, CLAN.alias, CHIEF)) == setup_ui.STEPS[0]


def test_il_bottone_premuto_nell_app_avanza_e_salva_come_il_wizard(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "settings.press", {"data": cb("preset", "casual_clan")}) is True
    assert saved(store)["preset"] == "casual_clan"
    assert saved(store)["reminders"] == settings_mod.PRESETS["casual_clan"]["reminders"]
    assert asyncio.run(store.get_state(CLAN.alias, undo.SETTINGS_PREV)) is not None
    assert asyncio.run(manager_actions.step_of(store, CLAN.alias, CHIEF)) == "packs"
    assert screen_of(store) == wizard_screen(store, "packs")
    assert datas(screen_of(store))[0] == cb("pack", "wars")
    assert [entry["kind"] for _, entry in store.logs] == ["settings"]
    assert applied(store, "settings.press", {"data": cb("next")}, ident="a2") is True
    assert asyncio.run(manager_actions.step_of(store, CLAN.alias, CHIEF)) == "routes"


def test_il_gestore_limitato_non_tocca_le_impostazioni(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "settings.open", {}, uid=ELDER) == reasons.NOT_MANAGER
    assert applied(store, "settings.press", {"data": cb("preset", "casual_clan")},
                   uid=ELDER, ident="b2") == reasons.NOT_MANAGER
    assert applied(store, "welcome.set", {"text": "Ciao {name}"}, uid=ELDER, ident="b3") == reasons.NOT_MANAGER
    assert saved(store) == STORED and store.pages == {}
    assert asyncio.run(store.kv_get(manager_actions.step_key(CLAN.alias, ELDER))) is None


def test_il_bottone_di_un_altro_clan_non_muove_niente(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "settings.press", {"data": "cfg:clan-altro:preset:casual_clan"}) == reasons.BAD
    assert saved(store) == STORED


def test_la_schermata_del_gestore_resta_sua(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "settings.press", {"data": cb("preset", "casual_clan")}) is True
    body = page_of(store)
    assert sorted(body[payload.MANAGE]) == [str(CHIEF)]
    seat = {"uid": ELDER, "tag": "#P3", "level": settings_mod.LIMITED}
    assert payload.MANAGE not in miniapp.state_body(body, seat)
    assert "manage" not in miniapp.state_body(body, seat)["me"]
    mine = miniapp.state_body(body, {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER})
    assert payload.MANAGE not in mine
    assert mine["me"]["manage"]["settings"] == screen_of(store)


def test_il_benvenuto_col_link_torna_col_motivo_e_non_esce(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "welcome.set", {"text": "Ciao {name}, scrivici su altrove.example"}) == reasons.TEXT_REFUSED
    assert (saved(store) or {}).get("texts") is None
    rows = asyncio.run(feed.rows(store, CLAN.alias, CHIEF))
    assert [(entry["kind"], entry["text"]) for entry in rows] == [
        (TEXT_REFUSED, IT.t("texts.reject.link"))]
    assert applied(store, "welcome.set", {"text": "Benvenuto {name}"}, ident="c2") is True
    assert leaders.texts(saved(store))["welcome"] == "Benvenuto {name}"
    assert [entry["action"] for _, entry in store.logs] == ["welcome"]


def test_il_motivo_del_testo_rifiutato_parla_la_lingua_del_gestore(tmp_path):
    store = manager_store(tmp_path)
    inglese = link("#P1", CHIEF, "Mario")
    inglese.lang = "en"
    store.links = [inglese]
    assert applied(store, "welcome.set", {"text": "Ciao {name}, vieni su altrove.example"}) == reasons.TEXT_REFUSED
    rows = asyncio.run(feed.rows(store, CLAN.alias, CHIEF))
    assert [(entry["kind"], entry["text"]) for entry in rows] == [
        (TEXT_REFUSED, i18n.locale("en").t("texts.reject.link"))]
    assert rows[0]["text"] != IT.t("texts.reject.link")


def test_le_regole_passano_dallo_stesso_filtro_del_benvenuto(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "rules.set", {"text": "Scrivi a +39 333 1234567"}) == reasons.TEXT_REFUSED
    assert (saved(store) or {}).get("texts") is None
    assert applied(store, "rules.set", {"text": "Si attacca sempre"}, ident="r2") is True
    assert leaders.texts(saved(store))["rules"] == "Si attacca sempre"
    assert [entry["action"] for _, entry in store.logs] == ["rules"]


def test_l_ammonizione_si_conferma_dall_app_e_arriva_a_chi_riguarda(tmp_path):
    store = manager_store(tmp_path, war=WAR)
    assert applied(store, "warning.confirm", {"village": "#P3"}) is True
    entries = asyncio.run(store.get_state(CLAN.alias, discipline.STATE))
    assert [(entry["tag"], entry["name"], entry["missed"]) for entry in entries] == [
        ("#P3", "Peach", 2)]
    assert [entry["kind"] for _, entry in store.logs] == ["warning"]
    assert [entry["kind"] for entry in asyncio.run(feed.rows(store, CLAN.alias, ELDER))] == [
        discipline.EVENT]
    assert applied(store, "warning.confirm", {"village": "#NOPE"}, ident="w2") == reasons.REFUSED


def test_solo_il_capo_annulla_l_ammonizione_dall_app(tmp_path):
    store = manager_store(tmp_path, war=WAR)
    asyncio.run(store.set_state(CLAN.alias, discipline.STATE, [warning_row()]))
    assert applied(store, "warning.void", {"ref": WARN_ID}) is True
    assert asyncio.run(store.get_state(CLAN.alias, discipline.STATE)) == []
    assert [entry["kind"] for _, entry in store.logs] == ["undo"]
    assert applied(store, "warning.void", {"ref": WARN_ID}, ident="v2") == reasons.REFUSED


def test_la_rosa_la_formazione_e_le_medaglie_si_toccano_dall_app(tmp_path):
    store = manager_store(tmp_path, cwl=CWL)
    assert applied(store, "cwl.roster.set", {"village": "#P2", "choice": cwl_roster.OUT}) is True
    assert applied(store, "cwl.lineup.set", {"village": "#P1"}, ident="l1") is True
    assert applied(store, "cwl.bonus.toggle", {"village": "#P1"}, ident="b1") is True
    state = asyncio.run(store.get_state(CLAN.alias, cwl_roster.STATE))
    assert state["avail"]["#P2"]["state"] == cwl_roster.OUT
    assert cwl_roster.picked(state) == ["#P1"] and state["bonus"] == ["#P1"]
    assert [entry["action"] for _, entry in store.logs] == ["cwl", "cwl", "cwl"]
    assert applied(store, "cwl.lineup.set", {"village": "#P1"}, ident="l2") is True
    assert cwl_roster.picked(asyncio.run(store.get_state(CLAN.alias, cwl_roster.STATE))) == []
    assert applied(store, "cwl.roster.set", {"village": "#P9", "choice": cwl_roster.IN},
                   ident="l3") == reasons.REFUSED


def test_i_messaggi_programmati_si_aggiungono_e_si_tolgono_dall_app(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "schedule.add",
                   {"hhmm": "21:15", "days": "135", "text": "Attacchiamo"}) is True
    entries = leaders.schedule(saved(store))
    assert [(one["hhmm"], one["days"], one["text"]) for one in entries] == [
        ("21:15", [1, 3, 5], "Attacchiamo")]
    assert applied(store, "schedule.add", {"hhmm": "21:15", "text": "Vieni su altrove.example"},
                   ident="s2") == reasons.TEXT_REFUSED
    assert len(leaders.schedule(saved(store))) == 1
    assert applied(store, "schedule.delete", {"ref": entries[0]["id"]}, ident="s3") is True
    assert leaders.schedule(saved(store)) == []
    assert [entry["action"] for _, entry in store.logs] == ["schedule", "schedule"]


def test_il_cancello_e_le_note_si_toccano_dall_app(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "gate.toggle", {"on": "on"}) is True
    assert leaders.gate_on(saved(store)) is True
    assert applied(store, "gate.toggle", {"on": "off"}, ident="g2") is True
    assert leaders.gate_on(saved(store)) is False
    assert applied(store, "note.set", {"village": "#P3", "text": "Da seguire"}, ident="n1") is True
    assert (asyncio.run(ledger.note_get(store, CLAN.alias, "#P3")) or {})["text"] == "Da seguire"
    assert applied(store, "note.set", {"village": "#P3", "text": ""}, ident="n2") is True
    assert asyncio.run(ledger.note_get(store, CLAN.alias, "#P3")) is None
    assert applied(store, "note.set", {"village": "#P9", "text": "boh"}, ident="n3") == reasons.GONE


def test_l_esportazione_si_prepara_col_gesto_e_resta_pronta_da_scaricare(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "export.csv", {"sheet": "members"}) is True
    ready = asyncio.run(store.kv_get(exports.ready_key(CLAN.alias, CHIEF)))
    assert ready["sheet"] == "members"
    assert ready["text"].splitlines()[0].endswith(",".join(exports.MEMBERS_HEADER[-1:]))
    assert "Mario" in ready["text"]
    assert [entry["action"] for _, entry in store.logs] == ["export"]
    assert applied(store, "export.csv", {"sheet": "niente"}, ident="e2") == reasons.BAD


def test_requisiti_e_candidature_si_decidono_dall_app(tmp_path):
    store = manager_store(tmp_path)
    state, app = recruit.add(recruit.state_of(None), "#N1", {"name": "Nuovo", "th": 15},
                             STRANGER, True, ["war"], False, NOW)
    asyncio.run(store.set_state(CLAN.alias, recruit.KIND, state))
    assert applied(store, "recruit.requirements.set", {"th": "14"}) is True
    assert recruit.requirement(saved(store)) == 14
    assert applied(store, "application.decide", {"ref": app["id"], "choice": "accepted"},
                   ident="d1") is True
    decided = recruit.state_of(asyncio.run(store.get_state(CLAN.alias, recruit.KIND)))
    assert recruit.find(decided, app["id"])["state"] == "accepted"
    assert [entry["action"] for _, entry in store.logs] == ["settings", "apply"]
    assert applied(store, "application.decide", {"ref": app["id"], "choice": "rejected"},
                   ident="d2") == reasons.GONE


def test_la_famiglia_si_crea_e_si_raggiunge_dall_app(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "family.create", {"name": "Famiglia Nostra"}) is True
    alias = store.in_family[CLAN.alias]
    assert store.families[alias].name == "Famiglia Nostra"
    assert store.families[alias].owner_id == CHIEF
    store.families["fam-9"] = FAMILY
    assert applied(store, "family.invite", {"ref": "fam-9"}, ident="f2") is True
    assert store.in_family[CLAN.alias] == "fam-9"
    assert applied(store, "family.invite", {"ref": "fam-nope"}, ident="f3") == reasons.GONE
    assert [entry["action"] for _, entry in store.logs] == ["family", "family"]


def test_il_derby_della_famiglia_resta_al_proprietario(tmp_path):
    store = with_everything(tmp_path)
    store.links.append(link("#P2", DEPUTY, "Luigi"))
    prima = dict(store.docs["dy-1"])
    assert applied(store, "family.derby", {"data": "dy:skip"}, uid=DEPUTY) == reasons.NOT_MANAGER
    assert applied(store, "family.derby", {"data": "dy:drop:clan-a1"}, uid=DEPUTY,
                   ident="dy2") == reasons.NOT_MANAGER
    assert store.docs["dy-1"] == prima and store.logs == []
    assert applied(store, "family.derby", {"data": "dy:skip"}, ident="dy3") is True
    assert [entry["action"] for _, entry in store.logs] == ["family"]


def test_il_tabellone_del_derby_lo_vede_solo_il_proprietario(tmp_path):
    store = with_everything(tmp_path)
    assert applied(store, "gate.toggle", {"on": "on"}) is True
    body = page_of(store)
    assert body[payload.TOOLS]["family"]["owner"] == CHIEF
    suo = miniapp.state_body(body, {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER})
    assert suo["me"][payload.TOOLS]["family"]["derby"]["buttons"]
    altrui = miniapp.state_body(body, {"uid": DEPUTY, "tag": "#P2",
                                       "level": settings_mod.MANAGER})
    assert altrui["me"][payload.TOOLS]["family"]["derby"] is None
    assert altrui["me"][payload.TOOLS]["family"]["name"] == FAMILY.name
    assert "owner" not in suo["me"][payload.TOOLS]["family"]
    assert "owner" not in altrui["me"][payload.TOOLS]["family"]


def test_il_torneo_annullato_dall_app_svuota_la_bozza_e_non_scrive_nel_registro(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "family.tourney", {"data": "tr:scope:clan"}) is True
    assert asyncio.run(store.kv_get(manager_net.tourney_key(CLAN.alias))) is not None
    assert [entry["action"] for _, entry in store.logs] == ["family"]
    assert applied(store, "family.tourney", {"data": "tr:cancel"}, ident="tc2") is True
    assert asyncio.run(store.kv_get(manager_net.tourney_key(CLAN.alias))) is None
    assert [entry["action"] for _, entry in store.logs] == ["family"]


def test_le_integrazioni_si_accendono_dall_app(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "integration.twitch", {"channel": "canaletest"}) is True
    assert (saved(store).get("twitch") or {}).get("channel") == "canaletest"
    assert applied(store, "integration.ics", {"on": "on"}, ident="i2") is True
    assert settings_mod.web_conf(saved(store))["ics"] is True
    asyncio.run(store.set_state(CLAN.alias, "discord", {"token": "x"}))
    assert applied(store, "integration.discord", {"on": "off"}, ident="i3") is True
    assert asyncio.run(store.get_state(CLAN.alias, "discord")) is None
    assert [entry["action"] for _, entry in store.logs] == ["integration"] * 3


def test_l_anziano_conferma_le_ammonizioni_ma_non_tocca_gli_strumenti(tmp_path):
    store = manager_store(tmp_path, war=WAR)
    assert applied(store, "warning.confirm", {"village": "#P2"}, uid=ELDER) is True
    for kind in ("rules.set", "gate.toggle", "note.set", "export.csv", "cwl.bonus.toggle"):
        assert applied(store, kind, BODIES[kind], uid=ELDER, ident=f"x{kind}") == reasons.NOT_MANAGER
    assert [entry["kind"] for _, entry in store.logs] == ["warning"]


def test_le_liste_dei_gestori_arrivano_nella_pagina(tmp_path):
    store = with_everything(tmp_path)
    assert applied(store, "gate.toggle", {"on": "on"}) is True
    found = tools_of(store)
    assert set(found) == set(manager_lists.PACKS)
    assert [one["name"] for one in found["wars"]["proposals"]] == ["Luigi", "Peach", "Mario"]
    assert [one["id"] for one in found["wars"]["warnings"]] == [WARN_ID]
    assert [one["tag"] for one in found["cwl"]["rows"]] == ["#P1", "#P2"]
    assert found["leaders"]["gate"] is True
    assert [one["hhmm"] for one in found["leaders"]["scheduled"]] == ["20:30"]
    assert found["leaders"]["texts"] == {"welcome": "", "rules": ""}
    assert [one["name"] for one in found["recruitment"]["applications"]] == ["Nuovo"]
    assert [one["name"] for one in found["recruitment"]["blocked"]] == ["Toad"]
    assert found["family"]["name"] == FAMILY.name
    assert found["family"]["derby"]["buttons"]
    assert found["family"]["tourney"]["text"]
    assert found["integrations"] == {"twitch": "", "discord": False, "ics": False}


class WarsStore(ToolStore):
    def __init__(self, vault):
        super().__init__(vault)
        self.limits = []

    async def recent_wars(self, alias, limit=10):
        self.limits.append(limit)
        return await super().recent_wars(alias, limit)


def test_la_lista_della_lega_legge_la_stessa_finestra_di_guerre_dei_chiamanti(tmp_path):
    store = manager_store(tmp_path, cwl=CWL, cls=WarsStore)
    assert [one["tag"] for one in asyncio.run(manager_lists.cwl_lists(store, CLAN))["rows"]] == [
        "#P1", "#P2"]
    assert store.limits == [cwl_season.SEASON_WARS]
    assert cwl_season.SEASON_WARS < retention.WAR_HISTORY_KEEP


def test_le_note_non_escono_mai_da_chi_gestisce(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "note.set", {"village": "#P3", "text": "Da seguire"}) is True
    body = page_of(store)
    assert "Da seguire" not in str(miniapp.state_body(body, {"uid": ELDER, "tag": "#P3",
                                                            "level": settings_mod.LIMITED}))
    assert "Da seguire" not in str(miniapp.state_body(body, {"uid": STRANGER, "tag": "#P4",
                                                             "level": None}))
    mine = miniapp.state_body(body, {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER})
    assert [one["text"] for one in mine["me"][payload.TOOLS]["leaders"]["notes"]] == ["Da seguire"]


def test_l_anziano_vede_solo_le_ammonizioni_fra_gli_strumenti(tmp_path):
    store = with_everything(tmp_path)
    assert applied(store, "gate.toggle", {"on": "on"}) is True
    body = page_of(store)
    elder = miniapp.state_body(body, {"uid": ELDER, "tag": "#P3", "level": settings_mod.LIMITED})
    assert set(elder["me"][payload.TOOLS]) == set(miniapp.LIMITED_PACKS)
    assert payload.TOOLS not in elder
    plain = miniapp.state_body(body, {"uid": STRANGER, "tag": "#P4", "level": None})
    assert payload.TOOLS not in plain and payload.TOOLS not in plain["me"]


def test_le_deleghe_si_danno_e_si_tolgono_dall_app(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "delegate.add", {"who": str(ELDER)}) is True
    assert conf_of(store)["delegates"] == [ELDER]
    assert applied(store, "delegate.add", {"who": str(ELDER)}, ident="d2") == reasons.TAKEN
    assert applied(store, "delegate.add", {"who": "424242"}, ident="d3") == reasons.NOT_LINKED
    assert applied(store, "delegate.remove", {"who": str(ELDER)}, ident="d4") is True
    assert conf_of(store)["delegates"] == []
    assert [(entry["kind"], entry["ref"]) for _, entry in store.logs] == [
        ("delegate", ref_of(store, ELDER)), ("settings", manager_staff.DELEGATES)]
    assert len(store.kv[guard.abuse_key(CLAN.alias, CHIEF)]["hits"]) == 1


def test_solo_il_capo_azzera_le_deleghe_col_ruolo_letto_dal_vivo(tmp_path):
    store = manager_store(tmp_path)
    store.links.append(link("#P2", DEPUTY, "Luigi"))
    asyncio.run(store.set_state(CLAN.alias, "settings", dict(STORED, delegates=[ELDER])))
    assert applied(store, "delegates.clear", {}, uid=DEPUTY) == reasons.CHIEF_ONLY
    demoted = FakeCoc(LIVE_MEMBER)
    assert applied(store, "delegates.clear", {}, ident="z2", coc=demoted) == reasons.CHIEF_ONLY
    assert demoted.asked == ["#P1"]
    assert conf_of(store)["delegates"] == [ELDER]
    assert applied(store, "delegates.clear", {}, ident="z3", coc=FakeCoc(LIVE_LEADER)) is True
    assert conf_of(store)["delegates"] == []
    assert [entry["kind"] for _, entry in store.logs] == ["settings"]


def test_solo_il_capo_annulla_dal_registro_col_ruolo_letto_dal_vivo(tmp_path):
    store = manager_store(tmp_path, war=WAR)
    store.links.append(link("#P2", DEPUTY, "Luigi"))
    asyncio.run(store.set_state(CLAN.alias, discipline.STATE, [warning_row()]))
    fatto = {"of": "warning", "ref": WARN_ID}
    assert applied(store, "undo.apply", fatto, uid=DEPUTY) == reasons.GONE
    assert applied(store, "undo.apply", fatto, ident="u2", coc=FakeCoc(LIVE_MEMBER)) == reasons.GONE
    assert asyncio.run(store.get_state(CLAN.alias, discipline.STATE)) == [warning_row()]
    assert applied(store, "undo.apply", fatto, ident="u3", coc=FakeCoc(LIVE_LEADER)) is True
    assert asyncio.run(store.get_state(CLAN.alias, discipline.STATE)) == []
    assert [entry["kind"] for _, entry in store.logs] == ["undo"]
    assert applied(store, "undo.apply", {"of": "niente", "ref": WARN_ID}, ident="u4") == reasons.GONE


def test_anche_l_annullo_dell_ammonizione_rilegge_il_ruolo_dal_vivo(tmp_path):
    store = manager_store(tmp_path, war=WAR)
    asyncio.run(store.set_state(CLAN.alias, discipline.STATE, [warning_row()]))
    assert applied(store, "warning.void", {"ref": WARN_ID}, coc=FakeCoc(LIVE_MEMBER)) == reasons.REFUSED
    assert asyncio.run(store.get_state(CLAN.alias, discipline.STATE)) == [warning_row()]
    assert applied(store, "warning.void", {"ref": WARN_ID}, ident="v9",
                   coc=FakeCoc(LIVE_LEADER)) is True
    assert asyncio.run(store.get_state(CLAN.alias, discipline.STATE)) == []


def test_ogni_azione_sensibile_della_spec_rilegge_il_ruolo_dal_vivo():
    sensibili = set(acts.DELEGATE_KINDS + acts.PAUSE_KINDS + acts.SETUP_KINDS + acts.TEXT_KINDS)
    assert sensibili <= set(acts.SENSITIVE_KINDS) | set(acts.CHIEF_KINDS)
    assert not set(acts.SENSITIVE_KINDS) & set(acts.CHIEF_KINDS)
    assert intents.SENSITIVE == acts.SENSITIVE_KINDS


def test_le_deleghe_e_i_testi_non_passano_a_chi_il_gioco_ha_gia_retrocesso(tmp_path):
    store = manager_store(tmp_path)
    retrocesso = FakeCoc(LIVE_MEMBER)
    assert applied(store, "delegate.add", {"who": str(ELDER)}, coc=retrocesso) == reasons.NOT_MANAGER
    assert retrocesso.asked == ["#P1"]
    assert conf_of(store)["delegates"] == []
    assert applied(store, "welcome.set", {"text": "Benvenuto {name}"}, ident="lv2",
                   coc=FakeCoc(LIVE_MEMBER)) == reasons.NOT_MANAGER
    assert (saved(store) or {}).get("texts") is None
    assert applied(store, "settings.open", {}, ident="lv3", coc=FakeCoc(LIVE_MEMBER)) == reasons.NOT_MANAGER
    assert applied(store, "settings.press", {"data": cb("preset", "casual_clan")}, ident="lv4",
                   coc=FakeCoc(LIVE_MEMBER)) == reasons.NOT_MANAGER
    assert saved(store) == STORED and store.logs == []
    assert applied(store, "delegate.add", {"who": str(ELDER)}, ident="lv5",
                   coc=FakeCoc(LIVE_LEADER)) is True
    assert conf_of(store)["delegates"] == [ELDER]


def test_il_wizard_dall_app_chiede_il_ruolo_solo_alla_prima_scrittura(tmp_path):
    store = manager_store(tmp_path)
    vivo = FakeCoc(LIVE_LEADER)
    for index, data in enumerate((cb("preset", "casual_clan"), cb("pack", "wars"),
                                  cb("pack", "cwl"))):
        assert applied(store, "settings.press", {"data": data}, ident=f"lw{index}",
                       coc=vivo) is True
    assert vivo.asked == ["#P1"]
    assert saved(store)["preset"] == "casual_clan"


def test_l_impostazione_di_prima_torna_con_l_annullo_del_capo(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "settings.press", {"data": cb("preset", "casual_clan")}) is True
    assert saved(store)["preset"] == "casual_clan"
    assert applied(store, "undo.apply", {"of": "settings", "ref": undo.PREV},
                   ident="p9", coc=FakeCoc(LIVE_LEADER)) is True
    assert saved(store).get("preset") is None


def test_la_pausa_del_capo_si_accende_dall_app_e_la_pagina_lo_dice(tmp_path):
    store = manager_store(tmp_path)
    assert applied(store, "clan.pause", {}) is True
    assert asyncio.run(guard.paused(store, CLAN.alias))["by"] == CHIEF
    assert staff_of(store)["paused"] is True
    assert applied(store, "clan.resume", {}, ident="r2") is True
    assert asyncio.run(guard.paused(store, CLAN.alias)) is None
    assert staff_of(store)["paused"] is False
    assert [(entry["action"], entry["detail"]) for _, entry in store.logs] == [
        ("pause", acts.SWITCH[0]), ("pause", acts.SWITCH[1])]


def test_la_pausa_e_la_ripresa_restano_al_capo_del_gioco(tmp_path):
    store = manager_store(tmp_path)
    store.links.append(link("#P2", DEPUTY, "Luigi"))
    asyncio.run(store.set_state(CLAN.alias, "settings", dict(STORED, delegates=[STRANGER])))
    assert applied(store, "clan.pause", {}, uid=DEPUTY) == reasons.CHIEF_ONLY
    assert applied(store, "clan.pause", {}, uid=STRANGER, ident="pa2") == reasons.CHIEF_ONLY
    retrocesso = FakeCoc(LIVE_MEMBER)
    assert applied(store, "clan.pause", {}, ident="pa3", coc=retrocesso) == reasons.CHIEF_ONLY
    assert retrocesso.asked == ["#P1"]
    assert asyncio.run(guard.paused(store, CLAN.alias)) is None
    assert store.logs == []
    assert applied(store, "clan.pause", {}, ident="pa4", coc=FakeCoc(LIVE_LEADER)) is True
    assert asyncio.run(guard.paused(store, CLAN.alias))["by"] == CHIEF
    assert applied(store, "clan.resume", {}, uid=DEPUTY, ident="pa5") == reasons.CHIEF_ONLY
    assert applied(store, "clan.resume", {}, uid=STRANGER, ident="pa6") == reasons.CHIEF_ONLY
    assert asyncio.run(guard.paused(store, CLAN.alias))["by"] == CHIEF
    assert applied(store, "clan.resume", {}, ident="pa7", coc=FakeCoc(LIVE_LEADER)) is True
    assert asyncio.run(guard.paused(store, CLAN.alias)) is None


def test_il_capo_riattiva_il_posto_sospeso_e_torna_fra_i_gestori(tmp_path):
    store = manager_store(tmp_path, war=WAR)
    store.links.append(link("#P2", DEPUTY, "Luigi"))
    asyncio.run(store.kv_set(guard.suspended_key(CLAN.alias, ELDER), {"at": NOW.timestamp()},
                             ref=CLAN.alias))
    assert ELDER not in asyncio.run(roles.managers(store, CLAN, conf_of(store), MEMBERS))
    assert applied(store, "suspension.lift", {"who": str(ELDER)}, uid=DEPUTY) == reasons.CHIEF_ONLY
    assert applied(store, "suspension.lift", {"who": str(ELDER)}, ident="s2",
                   coc=FakeCoc(LIVE_LEADER)) is True
    assert asyncio.run(guard.suspended(store, CLAN.alias, ELDER)) is False
    assert asyncio.run(roles.managers(store, CLAN, conf_of(store),
                                      MEMBERS))[ELDER] == settings_mod.LIMITED
    assert [(entry["action"], entry["detail"]) for _, entry in store.logs] == [("seat", "Peach")]
    assert applied(store, "suspension.lift", {"who": str(ELDER)}, ident="s3",
                   coc=FakeCoc(LIVE_LEADER)) == reasons.GONE


def untouched(store):
    assert [(one.user_id, one.verified) for one in store.links if one.tag == "#P4"] == [
        (STRANGER, False)]
    assert [int(one["by"]) for one in asyncio.run(store.claims_pending(CLAN.alias))] == [GUEST]
    assert asyncio.run(feed.rows(store, CLAN.alias, GUEST)) == []
    assert store.logs == []


def test_le_rivendicazioni_in_attesa_le_decide_un_gestore(tmp_path):
    store = with_claim(tmp_path)
    assert applied(store, "link.approve", {"village": "#P4", "who": str(GUEST)},
                   uid=ELDER) == reasons.NEEDS_TOKEN
    untouched(store)


def test_la_rivendicazione_rifiutata_lascia_il_villaggio_a_chi_lo_aveva(tmp_path):
    store = with_claim(tmp_path)
    assert applied(store, "link.reject", {"village": "#P4", "who": str(GUEST)}) == (
        reasons.NEEDS_TOKEN)
    untouched(store)


def test_il_bandito_non_prende_il_villaggio_dalla_casella(tmp_path):
    store = with_claim(tmp_path)
    asyncio.run(platform_ban.ban(store, GUEST, ["#P4"], NOW.timestamp()))
    assert applied(store, "link.approve", {"village": "#P4", "who": str(GUEST)},
                   uid=ELDER) == reasons.NEEDS_TOKEN
    assert GUEST not in [one.user_id for one in store.links]


def test_il_villaggio_verificato_col_token_non_passa_di_mano(tmp_path):
    store = with_claim(tmp_path)
    for one in store.links:
        if one.tag == "#P4":
            one.verified = True
    assert applied(store, "link.approve", {"village": "#P4", "who": str(GUEST)}) == (
        reasons.NEEDS_TOKEN)
    assert [one.user_id for one in store.links if one.tag == "#P4"] == [STRANGER]
    assert len(asyncio.run(store.claims_pending(CLAN.alias))) == 1


def test_chi_si_e_verificato_mentre_aspettava_non_torna_indietro(tmp_path):
    store = with_claim(tmp_path)
    store.links = [one for one in store.links if one.tag != "#P4"] + [link("#P4", GUEST, "Toad")]
    assert applied(store, "link.approve", {"village": "#P4", "who": str(GUEST)}) == (
        reasons.NEEDS_TOKEN)
    assert [(one.user_id, one.verified) for one in store.links if one.tag == "#P4"] == [
        (GUEST, True)]


def test_la_pagina_del_capo_porta_deleghe_sospesi_chi_aspetta_il_si_e_registro(tmp_path):
    store = with_everything(tmp_path)
    assert applied(store, "clan.pause", {}) is True
    found = staff_of(store)
    assert found["paused"] is True and found["undo"] is True
    assert found["delegates"] == [{"who": ref_of(store, STRANGER), "name": "Toad"}]
    assert [one["name"] for one in found["people"]] == ["Mario", "Peach"]
    assert found["suspended"] == [{"who": ref_of(store, ELDER), "name": "Peach"}]
    assert found["pending"] == [{"who": mark_of(store, ELDER), "name": "Peach", "tag": "#P3"}]
    assert found["approved"] == [{"who": mark_of(store, CHIEF), "name": "Mario",
                                  "trusted": False}]
    assert "claims" not in found and "uid" not in str(found)
    assert all(len(one["who"]) == acts.FIELD_MAX
               for one in found["delegates"] + found["suspended"])
    assert all(len(one["who"]) == payload.SLUG_LEN
               for one in found["pending"] + found["approved"])
    assert [(one["what"], one["who"]) for one in found["log"]] == [
        (IT.t("leaders.log.action.pause"), "Mario")]
    assert found["log"][0]["of"] is None and found["log"][0]["at"] == int(NOW.timestamp())


def test_il_registro_nella_pagina_porta_l_annulla_solo_al_capo(tmp_path):
    store = manager_store(tmp_path, war=WAR)
    store.links.append(link("#P2", DEPUTY, "Luigi"))
    assert applied(store, "warning.confirm", {"village": "#P3"}) is True
    riga = staff_of(store)["log"][0]
    dato = asyncio.run(store.get_state(CLAN.alias, discipline.STATE))[0]
    assert riga["what"] == IT.t("leaders.log.action.warning")
    assert riga["of"] == "warning" and riga["ref"] == dato["id"]
    assert staff_of(store, DEPUTY)["undo"] is False
    assert staff_of(store, DEPUTY)["log"] == staff_of(store)["log"]


def test_gli_strumenti_del_capo_non_escono_da_chi_gestisce(tmp_path):
    store = with_everything(tmp_path)
    assert applied(store, "clan.pause", {}) is True
    body = page_of(store)
    for seat in ({"uid": ELDER, "tag": "#P3", "level": settings_mod.LIMITED},
                 {"uid": STRANGER, "tag": "#P4", "level": None}):
        assert acts.STAFF not in str(miniapp.state_body(body, seat)["me"])
    mine = miniapp.state_body(body, {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER})
    assert mine["me"][payload.MANAGE][acts.STAFF]["paused"] is True


def test_la_casella_del_gestore_nasce_dalle_liste_vere(tmp_path):
    store = with_everything(tmp_path)
    asyncio.run(store.report_add(CLAN.alias, GUEST, "scam", NOW))
    assert applied(store, "gate.toggle", {"on": "on"}) is True
    seat = {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER}
    found = app_manage.inbox_for(page_of(store), seat, tools_of(store))
    assert found["pending"] == [{"who": mark_of(store, ELDER), "name": "Peach", "tag": "#P3"}]
    assert "claims" not in found
    assert [one["id"] for one in found["applications"]] == ["1"]
    assert [one["reason"] for one in found["reports"]] == ["scam"]
    assert all(set(one) == {"code", "reason", "at"} for one in found["reports"])
    assert [one["name"] for one in found["warnings"]] == ["Luigi", "Peach", "Mario"]
    assert [one["tag"] for one in found["warnings"]] == ["#P2", "#P3", "#P1"]


def test_lo_stato_del_gestore_nasce_dalle_liste_vere(tmp_path):
    store = with_everything(tmp_path)
    asyncio.run(store.set_state(CLAN.alias, base_videos.STATE_KIND,
                                {base_videos.STATE_FIELD: [CHANNEL]}))
    assert applied(store, "note.set", {"village": "#P3", "text": "Da seguire"}) is True
    assert applied(store, "clan.pause", {}, ident="mv2") is True
    seat = {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER}
    found = app_manage.manage_view(page_of(store), seat, tools_of(store))
    assert found["paused"] is True and found["chief"] is True
    assert found["delegates"] == [{"who": ref_of(store, STRANGER), "name": "Toad"}]
    assert [one["name"] for one in found["people"]] == ["Mario", "Peach"]
    assert found["suspended"] == [{"who": ref_of(store, ELDER), "name": "Peach"}]
    assert [one["what"] for one in found["log"]] == [IT.t("leaders.log.action.pause"),
                                                     IT.t("leaders.log.action.note")]
    assert found["packs"]["wars"] is True and set(found["packs"]) == set(boards.SECTION_ORDER)
    assert [one["hhmm"] for one in found["schedules"]] == ["20:30"]
    assert found["texts"] == {"welcome": "", "rules": ""}
    assert found["channels"] == [CHANNEL]
    assert found["page_on"] is False
    assert "Da seguire" not in str(found)


def test_la_pagina_pubblica_del_clan_si_accende_e_si_spegne_dall_app(tmp_path):
    store = manager_store(tmp_path)
    seat = {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER}
    assert settings_mod.web_conf(saved(store))["page"] is False
    assert applied(store, "page.toggle", {"on": "on"}, ident="pp1") is True
    assert settings_mod.web_conf(saved(store))["page"] is True
    assert app_manage.manage_view(page_of(store), seat, tools_of(store))["page_on"] is True
    assert applied(store, "integration.ics", {"on": "on"}, ident="pp2") is True
    assert applied(store, "page.toggle", {"on": "off"}, ident="pp3") is True
    spento = settings_mod.web_conf(saved(store))
    assert spento["page"] is False and spento[manager_net.ICS_FIELD] is False
    assert app_manage.manage_view(page_of(store), seat, tools_of(store))["page_on"] is False
    assert [entry["action"] for _, entry in store.logs] == ["settings", "integration", "settings"]


def test_i_canali_del_clan_si_aggiungono_e_si_tolgono_dall_app(tmp_path):
    store = manager_store(tmp_path)
    seat = {"uid": CHIEF, "tag": "#P1", "level": settings_mod.MANAGER}
    salvati = [{"id": CHANNEL["id"], "title": ""}]
    assert applied(store, "channel.add", {"channel": CHANNEL["id"]}) is True
    assert asyncio.run(base_videos.stored_channels(store, CLAN.alias)) == salvati
    assert app_manage.manage_view(page_of(store), seat, tools_of(store))["channels"] == salvati
    assert applied(store, "channel.drop", {"channel": CHANNEL["id"]}, ident="cc2") is True
    assert asyncio.run(base_videos.stored_channels(store, CLAN.alias)) == []
    assert app_manage.manage_view(page_of(store), seat, tools_of(store))["channels"] == []
    assert [entry["action"] for _, entry in store.logs] == ["integration", "integration"]


def test_i_canali_del_clan_non_passano_il_numero_dei_gestori(tmp_path):
    assert manager_actions.CHANNELS_PER_CLAN == settings_mod.MANAGER
    store = manager_store(tmp_path)
    altro = "UC" + "b" * acts.CHANNEL_TAIL
    assert applied(store, "channel.add", {"channel": CHANNEL["id"]}) is True
    assert applied(store, "channel.add", {"channel": altro}, ident="cc3") == reasons.CLOSED
    assert applied(store, "channel.add", {"channel": CHANNEL["id"]}, ident="cc4") is True
    assert [row["id"] for row in
            asyncio.run(base_videos.stored_channels(store, CLAN.alias))] == [CHANNEL["id"]]


def test_togliere_un_canale_che_non_c_e_lascia_la_lista_com_e(tmp_path):
    store = manager_store(tmp_path)
    altro = "UC" + "b" * acts.CHANNEL_TAIL
    assert applied(store, "channel.add", {"channel": CHANNEL["id"]}) is True
    assert applied(store, "channel.drop", {"channel": altro}, ident="cd2") is True
    assert [row["id"] for row in
            asyncio.run(base_videos.stored_channels(store, CLAN.alias))] == [CHANNEL["id"]]


def test_la_forma_del_canale_del_clan_viene_dai_video():
    coda = base_videos.ID_EXTRA + "a" * (acts.CHANNEL_TAIL - len(base_videos.ID_EXTRA))
    buono = base_videos.ID_START + coda
    forma = acts.FIELDS["channel.add"]["channel"]
    assert base_videos.channel_of(buono) == buono and forma(buono) is True
    assert not hasattr(acts, "CHANNEL_HEAD") and not hasattr(acts, "CHANNEL_EXTRA")
    for storto in (coda, buono.lower(), buono + "a", buono[:-1], " " + buono,
                   buono[:-1] + "é", "https://www.youtube.com/@tizio"):
        assert forma(storto) is False, storto


def test_chi_non_gestisce_non_tocca_la_pagina_ne_i_canali(tmp_path):
    store = manager_store(tmp_path)
    gesti = (("page.toggle", {"on": "off"}),
             ("channel.add", {"channel": CHANNEL["id"]}),
             ("channel.drop", {"channel": CHANNEL["id"]}))
    for uid in (ELDER, STRANGER):
        for index, (kind, body) in enumerate(gesti):
            assert applied(store, kind, body, uid=uid, ident=f"nn{uid}{index}") == reasons.NOT_MANAGER, kind
    assert saved(store) == STORED and store.pages == {} and store.logs == []
    assert asyncio.run(base_videos.stored_channels(store, CLAN.alias)) is None


def test_il_gestore_limitato_vede_chi_aspetta_il_si_e_nient_altro(tmp_path):
    store = manager_store(tmp_path)
    asyncio.run(store.set_state(CLAN.alias, door.KIND,
                                door.seed(door.state_of(None), [CHIEF, ELDER], NOW.timestamp())))
    assert applied(store, "clan.pause", {}) is True
    seat = {"uid": ELDER, "tag": "#P3", "level": settings_mod.LIMITED}
    suo = miniapp.state_body(page_of(store), seat)["me"]
    assert suo[payload.MANAGE] == {
        acts.STAFF: {"pending": [{"who": mark_of(store, STRANGER), "name": "Toad",
                                  "tag": "#P4"}]}}
    assert "paused" not in str(suo) and "settings" not in suo[payload.MANAGE]
    nessuno = miniapp.state_body(page_of(store), {"uid": STRANGER, "tag": "#P4", "level": None})
    assert payload.MANAGE not in nessuno["me"]
    assert staff_of(store)["paused"] is True
    assert applied(store, "person.approve", {"person": STRANGER, "war_from": "now"},
                   uid=ELDER, ident="q2") is True
    assert payload.MANAGE not in miniapp.state_body(page_of(store), seat)["me"]


def test_il_freno_conta_una_volta_sola_la_sessione_delle_impostazioni_dall_app(tmp_path):
    store = manager_store(tmp_path)
    for index, data in enumerate((cb("preset", "casual_clan"), cb("pack", "wars"),
                                  cb("pack", "cwl"))):
        assert applied(store, "settings.press", {"data": data}, ident=f"f{index}") is True
    chiave = guard.abuse_key(CLAN.alias, CHIEF)
    assert len(store.kv[chiave]["hits"]) == 1
    assert applied(store, "settings.open", {}, ident="f9") is True
    assert applied(store, "settings.press", {"data": cb("preset", "war_clan")},
                   ident="f10") is True
    assert len(store.kv[chiave]["hits"]) == 2


def test_il_dato_del_bottone_arriva_solo_nella_forma_del_wizard():
    good = {"settings.open": {}, "settings.press": {"data": cb("ev", "wars:war.attack")},
            "welcome.set": {"text": "Benvenuto {name}"},
            "rules.set": {"text": "Si attacca"},
            "warning.confirm": {"village": "#P3"}, "warning.void": {"ref": WARN_ID},
            "cwl.roster.set": {"village": "#P1", "choice": cwl_roster.IN},
            "cwl.lineup.set": {"village": "#P1"}, "cwl.bonus.toggle": {"village": "#P1"},
            "schedule.add": {"hhmm": "21:15", "days": "135", "text": "Attacchiamo"},
            "schedule.delete": {"ref": "1"}, "gate.toggle": {"on": "off"},
            "note.set": {"village": "#P3", "text": "Da seguire"},
            "export.csv": {"sheet": "wars"},
            "recruit.requirements.set": {"th": "14"},
            "application.decide": {"ref": "1", "choice": "rejected"},
            "sender.block": {"ref": "1"}, "sender.unblock": {"ref": "2"},
            "family.create": {"name": "Famiglia Nostra"}, "family.invite": {"ref": "fam-1"},
            "family.derby": {"data": "dy:metric:stars"}, "family.tourney": {"data": "tr:go"},
            "integration.twitch": {"channel": "canaletest"},
            "integration.discord": {"on": "off"}, "integration.ics": {"on": "on"},
            "page.toggle": {"on": "off"}, "channel.add": {"channel": CHANNEL["id"]},
            "channel.drop": {"channel": CHANNEL["id"]},
            "delegate.add": {"who": "12345"}, "delegate.remove": {"who": "12345"},
            "delegates.clear": {}, "clan.pause": {}, "clan.resume": {},
            "undo.apply": {"of": "settings", "ref": undo.PREV},
            "suspension.lift": {"who": "12345"},
            "share.clan": {}, "base.accept": {"ref": "ab12"}, "base.reject": {"ref": "ab12"},
            "view.set": {"section": "plans", "value": "approved"},
            "family.score.toggle": {},
            "person.approve": {"who": "ab12cd34ef56ab78", "war_from": "next"},
            "person.revoke": {"who": "ab12cd34ef56ab78"},
            "person.trust": {"who": "ab12cd34ef56ab78", "value": "off"}}
    assert set(good) == set(acts.KINDS_MANAGER)
    for kind, fields in good.items():
        found = miniapp.intent(dict(fields, kind=kind, id="ab12"), "#P1", CHIEF)
        assert found and found["kind"] == kind and found["by"] == CHIEF
        assert all(found[name] == value for name, value in fields.items())
    for bad in ({"kind": "delegate.add", "who": "-1"},
                {"kind": "delegate.add", "who": "un o"},
                {"kind": "undo.apply", "of": "warning", "ref": "non va"},
                {"kind": "link.approve", "village": "P4", "who": "1"},
                {"kind": "settings.press"},
                {"kind": "settings.press", "data": ""},
                {"kind": "settings.press", "data": "pinco:clan-a1:next"},
                {"kind": "settings.press", "data": f"cfg:{CLAN.alias}:pre set"},
                {"kind": "settings.press", "data": f"cfg:{CLAN.alias}:{'x' * 99}"},
                {"kind": "welcome.set", "text": ""},
                {"kind": "welcome.set", "text": "x" * (leaders.TEXT_MAX + 1)},
                {"kind": "warning.confirm", "village": "P3"},
                {"kind": "cwl.roster.set", "village": "#P1", "choice": "forse"},
                {"kind": "schedule.add", "hhmm": "25:00", "days": "", "text": "ok"},
                {"kind": "schedule.add", "hhmm": "21:15", "days": "19", "text": "ok"},
                {"kind": "gate.toggle", "on": "forse"},
                {"kind": "note.set", "village": "#P3", "text": "x" * (leaders.NOTE_MAX + 1)},
                {"kind": "application.decide", "ref": "1", "choice": "forse"},
                {"kind": "sender.block", "ref": "uno"},
                {"kind": "sender.unblock", "ref": ""},
                {"kind": "family.derby", "data": "cfg:clan-a1:go"},
                {"kind": "family.tourney", "data": "tr:go:x y"},
                {"kind": "page.toggle", "on": "forse"},
                {"kind": "channel.add", "channel": "UC" + "a" * (acts.CHANNEL_TAIL - 1)},
                {"kind": "channel.add", "channel": "UC" + "a" * (acts.CHANNEL_TAIL + 1)},
                {"kind": "channel.add", "channel": "https://www.youtube.com/@tizio"},
                {"kind": "channel.drop", "channel": "AC" + "a" * acts.CHANNEL_TAIL},
                {"kind": "channel.drop", "channel": "UC" + "a" * (acts.CHANNEL_TAIL - 1) + "!"}):
        assert miniapp.intent(dict(bad, id="ab12"), "#P1", CHIEF) is None
