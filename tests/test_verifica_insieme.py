import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

from clashbot import (console, door, feed, i18n, intents, linking, platform, platform_ban,
                      reasons, verify, views)
from clashbot.web import app as web_app, miniapp, payload
from test_console import (CLAN as CLAN_NUOVO, FakeStore as ConsoleStore, FakeSupervisor,
                          FakeTelegramBot, IT, OWNER, TAG, USER, account, born, context, last,
                          make_bot, pressed)
from test_web_miniapp import CLAN
from test_web_door import BOSS, FULL, door_of, mark, page_with, run, seat_of, vault
from test_web_miniapp import AppStore, NOW, SLUG, init, serve
from test_web_status import request

RADICE = Path(__file__).resolve().parents[1]
TENUTO = "web.security.kept"


def evento(riga):
    return json.loads(riga.split("data: ")[1])


def canale(site, uid):
    firma = f"X-Init-Data: {init(uid, code=SLUG)}\r\n".encode()
    return request(f"/app/{SLUG}/live", headers=firma)


def test_il_canale_gia_aperto_rilegge_il_posto_dalla_pagina_fresca(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    dopo = page_with(box, **door_of(box, approved=[BOSS]))
    dopo["seats"].pop(str(FULL), None)
    dopo["members"] = [row for row in dopo["members"] if row.get("tag") != "#P3"]
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    site = web_app.Site(store)
    req = canale(site, FULL)

    async def go():
        res = await site.router(req)
        gen = res.events.__aiter__()
        primo = await gen.__anext__()
        store.pages[(SLUG, payload.APP)] = dopo
        site.pages.pop(SLUG, None)
        await site.refresh_page(SLUG)
        return primo, await asyncio.wait_for(gen.__anext__(), 1)

    primo, secondo = asyncio.run(go())
    assert evento(primo)["level"] == miniapp.FULL_VIEW
    found = evento(secondo)
    assert found["level"] == miniapp.OUTSIDER, found["level"]
    for key in ("war", "rows", "ours", "members"):
        assert key not in found, key


def test_il_villaggio_provato_dopo_la_prima_semina_aspetta_il_si_nella_casella():
    prima = door.seed(door.state_of(None), [BOSS], NOW.timestamp())
    dopo = door.seed(prima, [BOSS, FULL], NOW.timestamp())
    assert sorted(int(uid) for uid in dopo[door.YES]) == [BOSS]
    assert dopo[door.SEEDED] is True and door.pending(dopo, [BOSS, FULL]) == [FULL]


def test_chi_prova_il_villaggio_dopo_la_semina_esce_dalla_ridotta_col_si(tmp_path):
    box = vault(tmp_path)
    state = door.seed(door.state_of(None), [BOSS], NOW.timestamp())
    state = door.seed(state, [BOSS, FULL], NOW.timestamp())
    page = page_with(box, **door.marks(state, lambda uid: mark(box, uid)))
    assert miniapp.level_of(page, seat_of(page, FULL, box)) == miniapp.REDUCED
    state = door.approve(state, FULL, NOW.timestamp(), door.war_from("now", NOW.timestamp()))
    page = page_with(box, **door.marks(state, lambda uid: mark(box, uid)))
    assert miniapp.level_of(page, seat_of(page, FULL, box)) == miniapp.FULL_VIEW


def test_gli_interruttori_chiudono_anche_le_bacheche(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS, FULL]))
    page["sections"] = {"cwl": ["lega"], "wars": ["guerra"], "bases": ["basi"],
                        "members": ["numeri"]}
    page[views.KIND] = {name: views.STAFF_ONLY for name in views.SECTIONS}
    found = miniapp.state_body(page, seat_of(page, FULL, box), now=NOW.timestamp())
    assert found["level"] == miniapp.FULL_VIEW
    assert "sections" not in found, found.get("sections")
    capo = miniapp.state_body(page, seat_of(page, BOSS, box), now=NOW.timestamp())
    assert capo["sections"]["cwl"] == ["lega"]


def test_l_approvato_dalla_prossima_guerra_non_riceve_la_storia_delle_guerre(tmp_path):
    box = vault(tmp_path)
    domani = int(NOW.timestamp()) + 200000
    page = page_with(box, **door_of(box, approved=[FULL], war_from=domani))
    page["wars"] = [{"end": 1, "result": "win"}]
    page["last_war"] = {"end": 1, "result": "win"}
    found = miniapp.state_body(page, seat_of(page, FULL, box), now=NOW.timestamp())
    assert found["level"] == miniapp.FULL_VIEW
    for key in ("war", "wars", "last_war"):
        assert key not in found, key


def test_la_casella_non_si_apre_alla_vista_ridotta(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    assert miniapp.level_of(page, seat_of(page, FULL, box)) == miniapp.REDUCED
    assert run(store, f"/app/{SLUG}/feed", FULL).status == 401
    assert run(store, f"/app/{SLUG}/feed", BOSS).status == 200


def test_la_vista_ridotta_non_conta_nemmeno_i_non_letti(tmp_path):
    box = vault(tmp_path)
    page = page_with(box, **door_of(box, approved=[BOSS]))
    store = AppStore({(SLUG, payload.APP): page}, vault=box)
    for uid in (FULL, BOSS):
        store.kv[feed.key_of(CLAN.alias, uid)] = {"rows": [{"at": 9, "text": "piano"}],
                                                  "read_at": 0}
    ridotto = json.loads(run(store, f"/app/{SLUG}/state", FULL).body)
    capo = json.loads(run(store, f"/app/{SLUG}/state", BOSS).body)
    assert ridotto["level"] == miniapp.REDUCED and ridotto["unread"] == 0
    assert capo["unread"] == 1


class BanVault:
    def blind(self, kind, value):
        return f"{kind}:{value}"


class BanStore:
    def __init__(self, rows):
        self.rows = rows
        self.linked = []
        self.vault = BanVault()

    async def kv_get(self, key):
        if key == "terms:user:9999":
            return {"day": "2026-09-01"}
        return self.rows if key == platform_ban.KEY else None

    async def links_for_players(self, tags):
        return {}

    async def kv_del(self, key):
        return None

    async def link_player(self, user_id, tag, name, dm=False, lang=None):
        self.linked.append((int(user_id), tag))


def banditi(uid=4242, tags=("#P7",)):
    return BanStore(platform_ban.with_ban(platform_ban.state_of(None), uid, list(tags), 1.0))


def test_il_bandito_non_collega_il_villaggio_passando_dalla_verifica():
    store = banditi()
    assert asyncio.run(verify.link_verified(store, 4242, "#P7", "Tizio")) == reasons.BANNED
    assert store.linked == []


def test_un_altro_telegram_non_collega_il_villaggio_bandito():
    store = banditi()
    assert asyncio.run(verify.link_verified(store, 9999, "#P7", "Tizio")) == reasons.BANNED
    assert store.linked == []


def test_il_villaggio_pulito_si_collega_ancora():
    store = banditi()
    assert asyncio.run(verify.link_verified(store, 9999, "#P8", "Tizio")) is None
    assert store.linked == [(9999, "#P8")]


def test_il_bandito_non_collega_il_villaggio_dalla_chat_del_bot():
    state = platform_ban.with_ban(platform_ban.state_of(None), 4242, ["#P7"], 1.0)
    store = BanStore(state)
    who = linking.Who(4242, "it")
    _, error = asyncio.run(linking.link_player(store, None, who, "#P7", "Tizio", "tok", NOW))
    assert error == reasons.BANNED


def test_il_bandito_con_un_altro_telegram_non_crea_il_bot():
    store = ConsoleStore(accounts=[account(OWNER, TAG)])
    asyncio.run(platform_ban.ban(store, USER, [TAG], time.time()))
    tg = FakeTelegramBot()
    ctx = context(store, FakeSupervisor(), bot=tg,
                  user_data={"newbot": {"request_id": 7, "tag": TAG, "clan": CLAN_NUOVO}})
    update = born(user_id=OWNER)
    asyncio.run(console.on_managed_created(update, ctx))
    assert store.added == [] and tg.token_calls == []
    assert last(update) == IT.t("console.newbot_banned")


class Coda:
    def __init__(self, rows):
        self.rows = list(rows)
        self.kv = {}
        self.done = []

    async def web_intents_take(self, limit=50):
        found, self.rows = self.rows, []
        return found[:limit]

    async def web_intent_done(self, intent_id):
        self.done.append(intent_id)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj


def test_un_gesto_che_scoppia_nel_bot_si_chiude_con_un_motivo(monkeypatch):
    async def boom(store, beat, row, now):
        raise RuntimeError("niente")

    monkeypatch.setattr(intents, "apply_one", boom)
    store = Coda([{"id": 4, "clan": "clan-1", "kind": "target.set", "body": {}}])
    assert asyncio.run(intents.drain(store, None, NOW)) == 0
    assert store.done == [4]
    assert store.kv[intents.refused_key(4)]["code"] == reasons.REFUSED


def test_il_gesto_ancora_in_coda_lo_dice_all_app():
    store = AppStore({(SLUG, payload.APP): page_with(vault(Path("/tmp")))}, pending=[1])
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "target.mirror", "id": "ab19"})
    found = json.loads(res.body)
    assert res.status == 200 and found["pending"] is True


def test_la_tessera_di_cosa_teniamo_dice_tutto_quello_che_teniamo():
    atteso = {TENUTO: "Encrypted, the minimum",
              "web.security.keep.id": "Blind Telegram id",
              "web.security.keep.tags": "Linked village tags",
              "web.security.keep.game": "Public game data",
              "web.security.keep.notes": "Clan notes and settings",
              "web.security.keep.terms": "Day the terms were accepted"}
    for code in sorted(i18n.LANGUAGES):
        found = json.loads((i18n.LOCALE_DIR / f"{code}.json").read_text(encoding="utf-8"))
        assert {key: found.get(key) for key in atteso} == atteso, code


def test_la_tessera_delle_stelle_non_finge_di_essere_un_bottone():
    testo = (RADICE / "clashbot/web/static/app/more.js").read_text(encoding="utf-8")
    riga = next(one for one in testo.splitlines() if "more_stars" in one)
    assert "Tile" not in riga, riga


def test_il_motivo_della_piattaforma_vale_un_tocco_solo():
    store = ConsoleStore(rows=[make_bot("bot-z", owner_id=USER)], owner=str(OWNER))
    ctx = context(store, FakeSupervisor(running=["bot-z"]), user_data={})
    platform.hold(ctx.user_data, "bot-z")
    tocco, _ = pressed("b:remove:bot-z", user_id=OWNER)
    asyncio.run(console.on_bot_callback(tocco, ctx))
    assert ctx.user_data.get(platform.OPEN_HELD) is None


def test_la_guardia_delle_righe_vede_crescere_anche_le_funzioni_gia_lunghe():
    from test_python_righe import OLTRE_IL_TETTO, oltre_il_tetto

    assert isinstance(OLTRE_IL_TETTO, dict)
    misurate = dict(oltre_il_tetto())
    for nome, righe in OLTRE_IL_TETTO.items():
        assert misurate.get(nome, 0) <= righe, (nome, misurate.get(nome), righe)


def test_l_ingresso_approvato_al_gruppo_segna_la_porta():
    import test_gate

    store = test_gate.FakeStore()
    richiesta = test_gate.Request(user_id=test_gate.MEMBER, name="Toad", username="toad")
    test_gate.join(richiesta, store, test_gate.RecordingBot())
    assert richiesta.approved is True
    state = door.state_of(asyncio.run(store.get_state(test_gate.CLAN.alias, door.KIND)))
    assert state[door.SEEN] == [test_gate.MEMBER]


def test_la_porta_scrive_solo_quando_cambia():
    async def go():
        store = SimpleNamespace(scritte=[])
        letto = {}

        async def get_state(alias, kind):
            return letto.get((alias, kind))

        async def set_state(alias, kind, obj):
            letto[(alias, kind)] = obj
            store.scritte.append(obj)

        store.get_state, store.set_state = get_state, set_state
        await door.note_seen(store, "clan-1", 9)
        await door.note_seen(store, "clan-1", 9)
        return store.scritte

    assert len(asyncio.run(go())) == 1


class Collegati:
    def __init__(self, links):
        self.links = list(links)

    async def links_by_user(self, user_id):
        return [link for link in self.links if link.user_id == user_id]


def test_rivendicato_non_provato_non_e_capo_verificato():
    ruoli = {"#L1": "leader", "#C2": "coLeader", "#M3": "member"}
    rivendicato = account(USER, "#L1", verified=False)
    assert asyncio.run(verify.linked_leader(Collegati([rivendicato]), USER, ruoli)) is None
    provato = account(USER, "#C2")
    assert asyncio.run(verify.linked_leader(Collegati([rivendicato, provato]), USER, ruoli)) is provato
    membro = account(USER, "#M3")
    assert asyncio.run(verify.linked_leader(Collegati([membro]), USER, ruoli)) is None
    assert asyncio.run(verify.linked_leader(Collegati([provato]), OWNER, ruoli)) is None
