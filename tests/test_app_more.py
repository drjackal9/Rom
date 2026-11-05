import asyncio
from datetime import datetime, timezone
from pathlib import Path

from clashbot import base_videos, bases, challenges, duels, i18n, media, more_lists, settings
from clashbot.db import Clan
from clashbot.web import app_more, miniapp, payload

NOW = datetime.fromtimestamp(1789000000, timezone.utc)
CLAN = Clan(alias="clan-a1", chat_id=-100, tag="#CLAN1", name="Nostro Clan", active=True,
            failures=0, last_seen=None, bot_alias="bot-1")
SEATS = {"777": {"tag": "#P1", "name": "Mario", "level": "manager"},
         "888": {"tag": "#P3", "name": "Peach", "level": None},
         "999": {"tag": None, "name": "Senza villaggio", "level": None}}
RAW_DUEL = {"id": "abcd1234", "status": "open", "metric": "loot", "duration": "week",
            "proposed": 0, "base": {}, "ends": 0,
            "a": {"tag": "#P1", "name": "Mario", "user_id": 777},
            "b": {"tag": "#P3", "name": "Peach", "user_id": 888}}
RAW_PROPOSED = dict(RAW_DUEL, id="ef567890", status="proposed")
DUEL = {"id": "abcd1234", "metric": "loot", "status": "open", "ends": 0,
        "a": {"tag": "#P1", "name": "Mario"}, "b": {"tag": "#P3", "name": "Peach"}}
VOTE = {"poll_id": "p1", "message_id": 5, "votes": {"777": {"option": 1, "name": "Mario"}},
        "season": "2026-09", "ends": 1789200000,
        "rows": [{"name": "Mario", "tag": "#P1", "stars": 3, "destr": 100.0, "th_up": True,
                  "uphill": False, "opponent": "Clan Nemico"}]}


class MoreStore:
    def __init__(self, vote=None):
        self.state = {challenges.KIND: dict(challenges.empty(), awards={"given": [], "vote": vote})}

    def recruit_code(self, clan_alias):
        return "abc123"

    async def get_state(self, alias, kind):
        return self.state.get(kind)

    async def set_state(self, alias, kind, obj):
        self.state[kind] = obj

    async def clan_bases(self, clan_alias, village=None, hall=None, limit=None):
        return []

    async def library_rows(self, hall=None, village=None, kind=None, limit=None):
        return []

    async def videos_rows(self, scope=None, limit=None):
        return []

    async def recruit_row(self, clan_alias):
        return None

    async def family_of_clan(self, clan_alias):
        return None


ROSTER = [{"tag": "#P1", "name": "Mario"}, {"tag": "#P3", "name": "Peach"}]


def page_of(**extra):
    return dict({"clan": {"name": CLAN.name}, "seats": SEATS, "members": ROSTER}, **extra)


def test_le_sfide_del_clan_arrivano_senza_gli_uid_di_nessuno():
    view = app_more.view_of(page_of(duels=[DUEL]), {"uid": 777, "tag": "#P1"})
    assert view["duels"] == [{"id": "abcd1234", "metric": "loot", "status": "open", "ends": 0,
                              "rival": "Peach", "mate": None}]
    assert "777" not in str(view["duels"]) and "888" not in str(view["duels"])


def test_la_sfida_fra_altri_due_mostra_tutti_e_due_i_nomi_e_nessun_tag():
    view = app_more.view_of(page_of(duels=[DUEL]), {"uid": 999, "tag": None})
    assert view["duels"][0]["mate"] == "Mario" and view["duels"][0]["rival"] == "Peach"
    assert "#P1" not in str(view["duels"]) and "#P3" not in str(view["duels"])


def test_i_rivali_sono_i_compagni_collegati_senza_me_e_senza_il_loro_uid():
    view = app_more.view_of(page_of(), {"uid": 777, "tag": "#P1"})
    assert view["rivals"] == [{"tag": "#P3", "name": "Peach"}]
    assert "888" not in str(view) and "777" not in str(view)


def test_senza_partite_la_vista_altro_resta_vuota_senza_inventare():
    view = app_more.view_of({}, {})
    assert view == {"duels": [], "rivals": [], "rival": None, "guess": None}


def test_lo_stato_porta_la_vista_altro_a_chi_lo_chiede():
    found = miniapp.state_body(page_of(duels=[DUEL]),
                               {"uid": 888, "tag": "#P3", "name": "Peach"})
    assert found["more_view"]["rivals"] == [{"tag": "#P1", "name": "Mario"}]
    assert found["more_view"]["duels"][0]["id"] == "abcd1234"
    assert found["more_view"]["duels"][0]["rival"] == "Mario"
    assert "duels" not in {key for key in found if key != "more_view"}
    assert "777" not in str(found["more_view"])


def test_il_premio_in_corso_non_dice_chi_ha_votato_ne_i_tag():
    found = asyncio.run(more_lists.award_of(MoreStore(VOTE), CLAN))
    assert found == {"rows": [{"name": "Mario", "stars": 3, "destr": 100.0}],
                     "ends": 1789200000}
    assert asyncio.run(more_lists.award_of(MoreStore(), CLAN)) is None


def test_le_liste_dell_altro_portano_anche_il_premio():
    conf = settings.effective({"lang": "it"})
    found = asyncio.run(more_lists.of(MoreStore(VOTE), CLAN, conf, {}))
    assert found["award"]["rows"][0]["name"] == "Mario"
    assert "poll_id" not in str(found["award"]) and "#P1" not in str(found["award"])


def test_le_liste_dell_altro_portano_le_sfide_in_corso_senza_gli_uid():
    store = MoreStore()
    state = challenges.empty()
    state["duels"]["open"] = [RAW_DUEL, RAW_PROPOSED]
    asyncio.run(challenges.save(store, CLAN.alias, state))
    conf = settings.effective({"lang": "it"})
    found = asyncio.run(more_lists.of(store, CLAN, conf, {}))
    assert found["duels"] == [DUEL]
    assert "777" not in str(found["duels"]) and "888" not in str(found["duels"])


def test_la_pagina_porta_il_premio_del_mese_o_niente():
    conf = settings.effective({"lang": "it"})
    award = {"rows": [{"name": "Mario", "stars": 3, "destr": 100.0}], "ends": 1789200000}
    body = payload.app_payload(CLAN, conf, {}, {}, None, "war", None, {}, SEATS, {}, {}, NOW,
                               award=award)
    assert body["award"] == award
    assert payload.app_payload(CLAN, conf, {}, {}, None, "war", None, {}, SEATS, {}, {},
                               NOW)["award"] is None


def test_la_pagina_consegna_al_javascript_le_costanti_della_sfida():
    assert miniapp.CONF["METRICS"] == list(duels.METRICS)
    assert miniapp.CONF["DURATIONS"] == list(duels.DURATION_KEYS)


def test_ogni_parola_dell_altro_arriva_dal_catalogo():
    L = i18n.locale("it")
    found = miniapp.words(L)
    for name in miniapp.MORE_WORDS:
        assert found["more_" + name] == L.t("web.app.more." + name)
    for name in miniapp.BASES_WORDS:
        assert found["bases_" + name] == L.t("web.app.bases." + name)
    assert found["bases_clan"] == L.t("bases.tab.clan")
    assert found["bases_library"] == L.t("bases.tab.library")
    assert found["duel_accept"] == L.t("duel.btn_accept")
    assert found["duel_metric_loot"] == L.t("duel.metric.loot")
    assert found["duel_duration_season"] == L.t("duel.duration.season")
    assert found["base_label_war"] == L.t("bases.label.war")
    assert found["base_village_home"] == L.t("bases.village.home")
    assert found["req_none"] == L.t("h.requirements_none")
    assert found["page_state"] == L.t("web.set.page")
    assert not any(str(value).startswith("[") for value in found.values())


def test_recluta_e_aiuto_prendono_dal_catalogo_le_parole_nuove():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in ("requirement", "apply", "how"):
            assert name in miniapp.MORE_WORDS, name
            assert found["more_" + name] == L.t("web.app.more." + name), name
            assert not found["more_" + name].startswith("["), name
        assert "\n" not in found["more_how"]
        assert found["more_privacy"] == L.t("web.privacy.title")
        assert not found["more_privacy"].startswith("[")


def test_le_parole_a_una_chiave_stanno_scritte_in_un_posto_solo():
    sorgente = Path(miniapp.__file__).read_text(encoding="utf-8")
    assert [name for name in miniapp.SINGLE_WORDS if f'found["{name}"]' in sorgente] == []


def test_il_sostegno_prende_le_parole_dalla_mappa_a_una_chiave():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        assert found["more_donate"] == L.t("web.home.donate")
        assert found["more_stars"] == L.t("web.home.stars")
        assert not found["more_donate"].startswith("[")
        assert not found["more_stars"].startswith("[")


MEMBERS = [{"tag": "#P1", "name": "Mario", "trophies": 5000, "linked": True},
           {"tag": "#P3", "name": "Peach", "trophies": 4800, "linked": True}]


def test_la_vista_altro_porta_il_rivale_consigliato_senza_uid():
    view = app_more.view_of(page_of(members=MEMBERS), {"uid": 777, "tag": "#P1"})
    assert view["rival"] == {"tag": "#P3", "name": "Peach", "trophies": 4800}
    assert "777" not in str(view["rival"]) and "888" not in str(view["rival"])
    assert app_more.view_of(page_of(), {"uid": 777, "tag": "#P1"})["rival"] is None


def test_l_app_lascia_passare_solo_le_anteprime_dei_video_e_lo_stemma():
    assert (f"img-src data: {base_videos.THUMB_HOST} https://{media.BADGE_HOST};"
            in miniapp.CSP)
    assert base_videos.THUMB_HOST == "https://i.ytimg.com"
    assert media.BADGE_HOST == "api-assets.clashofclans.com"
    assert miniapp.CONF["THUMB"] == base_videos.THUMB == base_videos.THUMB_HOST + "/vi/"
    assert miniapp.CONF["THUMB_SIZE"] == base_videos.THUMB_SIZE
    assert miniapp.CONF["LABELS"] == list(bases.LABELS)
