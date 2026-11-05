import asyncio
import json
from types import SimpleNamespace

from clashbot import (acts, door, events_registry, feed, i18n, linking, platform_ban, reasons,
                      retention, roles, settings)
from clashbot.db import SCHEMA, Store
from clashbot.poller import link_names
from clashbot.web import miniapp, payload
from test_db_multibot import links_store
from test_intents import ActStore, app_store, applied
from test_web_miniapp import SLUG, AppStore, body as app_body, serve
from test_web_publish import CLAN, INFO, NOW, beat_for

TOKEN = "abcdef0123456789"
STRANGER = 999
OTHER = 888


class FakeCoc:
    def __init__(self, good=None):
        self.good = dict(good or {})
        self.asked = []

    async def verify_token(self, tag, token):
        self.asked.append((tag, token))
        return self.good.get(tag) == token, None


class LinkStore(ActStore):
    claim_add = Store.claim_add
    claims_pending = Store.claims_pending

    def find(self, tag):
        return next((link for link in self.links if link.tag == tag), None)

    def _fresh(self, user_id, tag, name, dm, lang, verified):
        return SimpleNamespace(alias=f"link-{tag}", user_id=int(user_id), tag=tag, name=name,
                               dm=dm, lang=lang, whisper=False, verified=verified)

    async def add_claim(self, user_id, tag, name):
        if self.find(tag):
            return None
        self.links.append(self._fresh(user_id, tag, name, False, None, False))
        return f"link-{tag}"

    async def link_player(self, user_id, tag, name, dm=False, lang=None):
        link = self.find(tag)
        if not link:
            self.links.append(self._fresh(user_id, tag, name, dm, lang, True))
            return f"link-{tag}"
        link.user_id, link.name, link.verified = int(user_id), name, True
        return link.alias

    async def set_link_verified(self, user_id, tag, value):
        link = self.find(tag)
        if link and link.user_id == int(user_id):
            link.verified = bool(value)

    async def set_link_whisper(self, user_id, tag, value):
        link = self.find(tag)
        if link and link.user_id == int(user_id):
            link.whisper = bool(value)

    async def unlink(self, user_id, tag):
        link = self.find(tag)
        if not link or link.user_id != int(user_id):
            return False
        self.links.remove(link)
        return True


def store_with(tmp_path, links=None):
    store = app_store(tmp_path, cls=LinkStore)
    if links is not None:
        store.links = list(links)
    return store


def published(store):
    return store.pages[(CLAN.alias, payload.APP)][1]


def told(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def managers_of(store):
    conf = settings.effective(asyncio.run(store.get_state(CLAN.alias, "settings")), None)
    members = asyncio.run(store.get_state(CLAN.alias, "members")) or {}
    return asyncio.run(roles.managers(store, CLAN, conf, members))


def waiting(store):
    return asyncio.run(store.claims_pending(CLAN.alias))


def it(key, **fields):
    return i18n.locale("it").t(key, **fields)


def claimed_by(uid, tag="#P2", name="Luigi"):
    return SimpleNamespace(alias=f"link-{tag}", user_id=uid, tag=tag, name=name, dm=False,
                           lang=None, whisper=False, verified=False)


def with_old_claim(tmp_path, uid=STRANGER):
    store = store_with(tmp_path)
    store.links.append(claimed_by(uid))
    return store


def test_il_villaggio_rivendicato_dall_app_da_il_posto_ma_non_il_comando(tmp_path):
    store = with_old_claim(tmp_path)
    members = asyncio.run(store.get_state(CLAN.alias, "members"))
    conf = settings.effective(asyncio.run(store.get_state(CLAN.alias, "settings")), None)
    assert asyncio.run(beat_for(store).app(CLAN, conf, members, INFO, NOW)) is True
    claimed = store.find("#P2")
    seats = published(store)["seats"]
    assert seats[str(STRANGER)]["tag"] == "#P2" and seats[str(STRANGER)]["level"] is None
    assert seats[str(STRANGER)]["verified"] is False
    mentions = link_names([{"tag": "#P2", "name": "Luigi"}], {"#P2": claimed})
    assert str(STRANGER) in mentions["#P2"]
    assert STRANGER not in managers_of(store)


def test_la_rivendicazione_per_nome_risponde_serve_il_token_e_non_scrive(tmp_path):
    store = store_with(tmp_path)
    before = list(store.links)
    assert applied(store, "link.claim", {"village": "#P2"}, uid=STRANGER) == reasons.NEEDS_TOKEN
    assert store.links == before and store.find("#P2") is None
    assert store.pages == {} and told(store, STRANGER) == [] and waiting(store) == []


def test_il_bandito_dalla_piattaforma_non_collega_un_villaggio(tmp_path):
    store = store_with(tmp_path)
    asyncio.run(platform_ban.ban(store, STRANGER, [], 1789000000.0))
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "on"}, uid=STRANGER,
                   coc=coc) == reasons.BANNED
    assert store.find("#P2") is None and told(store, STRANGER) == []


def test_il_bando_sul_villaggio_ferma_anche_il_token(tmp_path):
    store = store_with(tmp_path)
    asyncio.run(platform_ban.ban(store, OTHER, ["#P2"], 1789000000.0))
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "on"}, uid=STRANGER,
                   coc=coc) == reasons.BANNED
    assert store.find("#P2") is None


def test_la_seconda_rivendicazione_per_nome_non_aspetta_nessun_gestore(tmp_path):
    store = with_old_claim(tmp_path)
    assert applied(store, "link.claim", {"village": "#P2"}, uid=OTHER, ident="c2") == (
        reasons.NEEDS_TOKEN)
    assert store.find("#P2").user_id == STRANGER and waiting(store) == []
    assert told(store, OTHER) == [] and told(store, STRANGER) == []


def test_il_token_del_gioco_fa_del_co_capo_un_gestore(tmp_path):
    store = with_old_claim(tmp_path)
    coc = FakeCoc({"#P2": TOKEN})
    assert STRANGER not in managers_of(store)
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "on"}, uid=STRANGER,
                   ident="v1", coc=coc) is True
    assert store.find("#P2").verified is True
    assert managers_of(store)[STRANGER] == roles.MANAGER
    assert coc.asked == [("#P2", TOKEN)]
    assert told(store, STRANGER)[-1] == it("feed.link.verified", name="Luigi")
    assert published(store)["seats"][str(STRANGER)]["verified"] is True


def test_un_token_sbagliato_lascia_il_collegamento_dov_era_e_lo_dice(tmp_path):
    store = with_old_claim(tmp_path)
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": "sbagliato", "terms": "on"}, uid=STRANGER,
                   ident="v2", coc=coc) == reasons.BAD
    assert store.find("#P2").verified is False
    assert told(store, STRANGER)[-1] == it(linking.NOTES[linking.BAD_TOKEN], name="Luigi")


def test_il_token_vince_sul_collegamento_per_nome_di_un_altro(tmp_path):
    store = with_old_claim(tmp_path, uid=OTHER)
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "on"}, uid=STRANGER,
                   ident="v4", coc=coc) is True
    held = store.find("#P2")
    assert (held.user_id, held.verified) == (STRANGER, True)
    assert told(store, OTHER)[-1] == it("feed.link.lost", name="Luigi")


def test_il_rivendicato_approvato_vede_la_ridotta_e_col_token_la_piena(tmp_path):
    store = store_with(tmp_path)
    store.links = [one for one in store.links if one.tag != "#P4"]
    store.links.append(claimed_by(STRANGER, "#P4", "Toad"))
    asyncio.run(store.set_state(CLAN.alias, door.KIND,
                                door.seed(door.state_of(None), [STRANGER], NOW.timestamp())))
    members = asyncio.run(store.get_state(CLAN.alias, "members"))
    conf = settings.effective(asyncio.run(store.get_state(CLAN.alias, "settings")), None)
    assert asyncio.run(beat_for(store).app(CLAN, conf, members, INFO, NOW)) is True
    assert door.state_of(asyncio.run(store.get_state(CLAN.alias, door.KIND)))[door.YES]
    slug = payload.slug_for(store.vault, CLAN.alias)
    served = AppStore({(slug, payload.APP): published(store)}, vault=store.vault)
    seen = json.loads(serve(served, f"/app/{slug}/state", uid=STRANGER, name="Toad",
                            code=slug).body)
    assert seen["level"] == miniapp.REDUCED and "war" not in seen
    coc = FakeCoc({"#P4": TOKEN})
    assert applied(store, "link.verify", {"village": "#P4", "token": TOKEN, "terms": "on"}, uid=STRANGER,
                   ident="v5", coc=coc) is True
    slug = payload.slug_for(store.vault, CLAN.alias)
    served = AppStore({(slug, payload.APP): published(store)}, vault=store.vault)
    seen = json.loads(serve(served, f"/app/{slug}/state", uid=STRANGER, name="Toad",
                            code=slug).body)
    assert seen["level"] == miniapp.FULL_VIEW


def test_il_villaggio_di_un_altro_e_rifiutato_e_il_proprietario_lo_sa(tmp_path):
    store = store_with(tmp_path)
    coc = FakeCoc({"#P4": TOKEN})
    assert applied(store, "link.verify", {"village": "#P4", "token": TOKEN, "terms": "on"}, uid=OTHER,
                   ident="v3", coc=coc) == reasons.TAKEN
    assert store.find("#P4").user_id == 11 and coc.asked == []
    assert told(store, OTHER)[-1] == it(linking.NOTES[linking.TAKEN], name="Toad")
    assert told(store, 11)[-1] == i18n.locale("en").t("feed.link.owner", name="Toad")


def test_il_token_non_resta_da_nessuna_parte_dopo_il_gesto(tmp_path):
    store = store_with(tmp_path)
    coc = FakeCoc({"#P2": TOKEN})
    assert applied(store, "link.verify", {"village": "#P2", "token": TOKEN, "terms": "on"}, uid=STRANGER,
                   coc=coc) is True
    for kept in (store.kv, store.state, store.pages, store.links):
        assert TOKEN not in str(kept)


def test_il_sussurro_della_guerra_si_accende_e_si_spegne_dall_app(tmp_path):
    store = store_with(tmp_path)
    assert applied(store, "link.whisper", {"village": "#P4", "on": "on"}, uid=11) is True
    assert store.find("#P4").whisper is True
    assert published(store)["seats"]["11"]["whisper"] is True
    assert applied(store, "link.whisper", {"village": "#P4", "on": "off"}, uid=11,
                   ident="w2") is True
    assert store.find("#P4").whisper is False
    assert applied(store, "link.whisper", {"village": "#P2", "on": "on"}, uid=11,
                   ident="w3") == reasons.NOT_LINKED


def test_il_villaggio_di_un_altro_non_si_scollega_mai(tmp_path):
    store = store_with(tmp_path)
    assert applied(store, "link.drop", {"village": "#P1"}, uid=11) == reasons.NOT_LINKED
    assert applied(store, "link.drop", {"village": "#P4"}, uid=11, ident="d2") is True
    assert store.find("#P4") is None


def test_i_nomi_che_somigliano_al_mio_non_si_propongono_piu():
    assert not hasattr(payload, "proposals")
    assert not hasattr(payload, "looks_like")
    assert not hasattr(payload, "PROPOSED")


def test_l_app_non_offre_piu_i_villaggi_liberi_a_chi_arriva(tmp_path):
    store = store_with(tmp_path, links=[])
    members = asyncio.run(store.get_state(CLAN.alias, "members"))
    conf = settings.effective(asyncio.run(store.get_state(CLAN.alias, "settings")), None)
    assert asyncio.run(beat_for(store).app(CLAN, conf, members, INFO, NOW)) is True
    page = published(store)
    assert "roster" not in page
    served = AppStore({(SLUG, payload.APP): page}, vault=store.vault)
    body = json.loads(serve(served, f"/app/{SLUG}/state", uid=STRANGER, name="Peach").body)
    assert "roster" not in body and body["me"] == {"level": None}
    assert "#P1" not in json.dumps(body)


def test_la_pagina_pubblicata_non_porta_piu_la_rosa_dei_liberi(tmp_path):
    store = store_with(tmp_path)
    members = asyncio.run(store.get_state(CLAN.alias, "members"))
    conf = settings.effective(asyncio.run(store.get_state(CLAN.alias, "settings")), None)
    assert asyncio.run(beat_for(store).app(CLAN, conf, members, INFO, NOW)) is True
    page = published(store)
    assert "roster" not in page
    assert sorted(page[miniapp.APPROVED].values(), key=lambda row: row["since"])


def test_chi_non_ha_il_villaggio_puo_solo_verificarlo_col_token():
    store = AppStore({(SLUG, payload.APP): app_body()})
    for kind in acts.TOKEN_ONLY:
        res = serve(store, f"/app/{SLUG}/act", "POST", uid=STRANGER,
                    data={"kind": kind, "village": "#P2", "who": "ab12", "id": "ab11"})
        assert res.status == 403, kind
        assert json.loads(res.body) == {"error": reasons.NEEDS_TOKEN}, kind
    assert store.intents == []
    res = serve(store, f"/app/{SLUG}/act", "POST", uid=STRANGER,
                data={"kind": "link.verify", "village": "#P2", "token": TOKEN, "terms": "on", "id": "ab12"})
    assert res.status == 200
    assert [kind for _, kind, _ in store.intents] == ["link.verify"]
    refused = serve(store, f"/app/{SLUG}/act", "POST", uid=STRANGER,
                    data={"kind": "link.drop", "village": "#P2", "id": "ab13"})
    assert refused.status == 403 and len(store.intents) == 1


def test_i_gesti_per_nome_non_stanno_piu_fra_le_azioni():
    assert acts.TOKEN_ONLY == ("link.claim", "link.approve", "link.reject")
    for kind in acts.TOKEN_ONLY:
        assert kind not in acts.FIELDS and kind not in acts.MARKS, kind
        assert kind not in acts.KINDS_MEMBER + acts.KINDS_MANAGER, kind
    assert acts.NO_SEAT == ("link.verify", "app.opened")
    assert not hasattr(acts, "CLAIM_KINDS")


def test_la_schermata_che_collega_il_villaggio_accompagna_nel_gioco():
    for kind in acts.LINK_KINDS:
        assert kind in acts.KINDS_MEMBER, kind
    assert miniapp.CONF["TOKEN_MAX"] == acts.FIELD_MAX
    words = miniapp.words(i18n.locale("it"))
    for name in miniapp.LINK_WORDS:
        assert not words["link_" + name].startswith("["), name
    assert words["link_title"] == it("web.app.link.title")


def test_le_novita_dei_collegamenti_sono_righe_di_feed_non_eventi_instradabili():
    assert linking.LINK_NEWS == events_registry.LINK_NEWS
    assert linking.LINK_NEWS in events_registry.FEED_ONLY
    assert not events_registry.routed(linking.LINK_NEWS)


def test_le_rivendicazioni_in_attesa_si_misurano_coi_numeri_di_casa():
    from clashbot.db import CLAIMS_KEEP, CLAIMS_TTL
    from clashbot.platform_guard import IDLE_TTL

    assert CLAIMS_KEEP is retention.WAR_HISTORY_KEEP
    assert CLAIMS_TTL is IDLE_TTL


def test_la_colonna_che_distingue_i_collegamenti_verificati(tmp_path):
    assert ("alter table links add column if not exists verified boolean "
            "not null default true") in SCHEMA
    store = links_store(tmp_path)
    assert asyncio.run(store.add_claim(7, "#ABC", "Alex")) is not None
    claimed = asyncio.run(store.links_by_user(7))[0]
    assert (claimed.tag, claimed.verified) == ("#ABC", False)
    assert asyncio.run(store.add_claim(8, "#ABC", "Bea")) is None
    assert asyncio.run(store.links_by_user(8)) == []
    asyncio.run(store.link_player(7, "#ABC", "Alex"))
    assert asyncio.run(store.links_by_user(7))[0].verified is True
    asyncio.run(store.set_link_verified(7, "#ABC", False))
    assert asyncio.run(store.links_by_user(7))[0].verified is False


async def nothing(*args):
    return None


def test_una_rivendicazione_persa_in_volata_non_finge_di_essere_riuscita(tmp_path):
    store = links_store(tmp_path)
    asyncio.run(store.link_player(7, "#ABC", "Alex"))
    store.pool.fetchrow = nothing
    assert asyncio.run(store.add_claim(8, "#ABC", "Bea")) is None
    assert [link.user_id for link in asyncio.run(store.links_by_user(7))] == [7]


def test_le_rivendicazioni_in_attesa_restano_cento_per_clan(tmp_path):
    from clashbot.db import CLAIMS_KEEP

    store = store_with(tmp_path)
    for number in range(CLAIMS_KEEP + 5):
        asyncio.run(store.claim_add(CLAN.alias, number, f"#T{number}", f"Tale {number}", NOW))
    rows = waiting(store)
    assert len(rows) == CLAIMS_KEEP and rows[-1]["by"] == CLAIMS_KEEP + 4
    asyncio.run(store.claim_add(CLAN.alias, 3, "#T3", "Tale 3", NOW))
    assert len([row for row in waiting(store) if row["by"] == 3]) == 1


def test_le_rivendicazioni_restano_nel_gruppo_intero_anche_senza_gesto(tmp_path):
    store = store_with(tmp_path)
    asyncio.run(store.claim_add(CLAN.alias, 3, "#T3", "Tale 3", NOW))
    assert asyncio.run(Store.claim_drop(store, CLAN.alias, 3, "#T9")) is False
    assert asyncio.run(Store.claim_drop(store, CLAN.alias, 3, "#T3")) is True
    assert waiting(store) == []


def test_serve_il_token_e_un_motivo_con_la_sua_parola_in_ogni_lingua():
    assert reasons.NEEDS_TOKEN == "needs_token" and reasons.NEEDS_TOKEN in reasons.REASONS
    assert reasons.NEEDS_TOKEN not in reasons.RESERVED
    for lang in ("it", "en", "de"):
        said = miniapp.denied_words(i18n.locale(lang))["denied_needs_token"]
        assert said and not said.startswith("["), lang
