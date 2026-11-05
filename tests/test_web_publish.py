import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from clashbot import (agenda, availability, base_videos, bases, boards, challenges, cwl_roster,
                      feed, guard, i18n, ics, intents, leaderboards, news_feed, predictions,
                      progress, publish, quizbank, recap, scoring, settings, util)
from clashbot.crypto import Vault
from clashbot.db import Clan, Family, Store
from clashbot.events import member_snapshot, war_record, war_snapshot
from clashbot.poller import Poller, Tick
from clashbot.web import app as web_app, miniapp, payload
from cwl_fixtures import SEASON, cwl_state, war_records
from fixtures import BASE_MEMBERS, clan_json, war_json
from test_flows import FakeBot, FakeStore, fake_supervisor
from test_web_status import request

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
TZ = "Europe/Rome"
URL = "https://esempio.test"
SLUG = "abcdef0123456789"
CLAN = Clan(alias="clan-a1", chat_id=-100, tag="#CLAN1", name="Nostro Clan", active=True,
            failures=0, last_seen=None, bot_alias="bot-1")
CWL_CLAN = Clan(alias="clan-a1", chat_id=-100, tag="#C1", name="Nostro Clan", active=True,
                failures=0, last_seen=None, bot_alias="bot-1")
INFO = {"level": 12, "members": 4, "league": "Crystal League I", "wins": 210, "streak": 3,
        "points": 32000}
BADGE = "https://api-assets.clashofclans.com/badges/200/uno.png"
PLAYER = {"name": "Mario", "th": 16, "trophies": 5400, "best": 5600, "warStars": 900,
          "league": "Crystal League I", "heroes": {"Barbarian King": 90},
          "warPref": "in", "donations": 1200}
KEPT = object()


def season_with_points():
    season = scoring.empty_season("2026-09")
    scoring.apply_war(season, {"members": [
        {"tag": "#P1", "name": "Mario", "attacks": [{"stars": 3}, {"stars": 2}], "missed": 0},
        {"tag": "#P2", "name": "Luigi", "attacks": [{"stars": 1}], "missed": 0},
    ]})
    return season


def boards_state(base=None, final=None):
    return {"trophies": {"last_week": {
        "base": base or {"#P1": 5000, "#P2": 4000},
        "final": final or {"#P1": 5400, "#P2": 4100}}}}


def built(conf_web=None, war=KEPT, hall=None):
    stored = {"lang": "it", "tz": "Europe/Rome"}
    if conf_web:
        stored["web"] = conf_web
    conf = settings.effective(stored, clan_json(BASE_MEMBERS))
    fought = war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]})) if war is KEPT else war
    calendar = ics.build(i18n.locale(conf["lang"]), SLUG, CLAN.name, NOW, None, fought)
    return payload.public_payload(
        CLAN, conf, INFO, fought, "war", None, hall or [], agenda.upcoming(NOW), NOW, calendar,
    )


class WebStore(FakeStore):
    recruit_code = Store.recruit_code
    reports_for = Store.reports_for

    def __init__(self, vault, url=None, **kw):
        super().__init__(**kw)
        self.vault = vault
        self.url = url
        self.pages = {}
        self.dropped = []
        self.bases = []
        self.library = []
        self.videos = {}
        self.recruiting = False
        self.family = None
        self.family_rows = []

    async def get_secret(self, kind):
        return self.url if kind == "site_base" else await super().get_secret(kind)

    async def web_note(self, name):
        return None

    async def web_publish(self, clan_alias, kind, slug, body):
        self.pages[(clan_alias, kind)] = (slug, body)

    async def web_drop_page(self, clan_alias, kind):
        self.dropped.append((clan_alias, kind))
        self.pages.pop((clan_alias, kind), None)

    async def web_page(self, slug, kind):
        for (_, saved), (found, body) in self.pages.items():
            if saved == kind and found == slug:
                return body
        return None

    async def clan_bases(self, clan_alias, village=None, hall=None, limit=None):
        return [dict(row) for row in self.bases][:limit]

    async def add_base(self, clan_alias, layout, label, payload, keep=None):
        alias = f"base-{len(self.bases) + 1}"
        self.bases.append({"alias": alias, "clan_alias": clan_alias, "label": label,
                           "village": layout["village"], "hall": layout["hall"], **payload,
                           "id": layout["id"]})
        return alias

    async def library_rows(self, hall=None, village=None, kind=None, limit=None):
        found = [dict(row) for row in self.library if hall is None or row["hall"] == hall]
        return found[:limit]

    async def videos_rows(self, scope=None, limit=None):
        return [dict(row) for row in self.videos.get(scope) or ()][:limit]

    async def recruit_row(self, clan_alias):
        if not self.recruiting:
            return None
        return {"recruiting": True, "named": False, "card": None, "ts": 0}

    async def family_of_clan(self, clan_alias):
        return self.family

    async def family_clans(self, family_alias):
        return list(self.family_rows)


def feed_rows(store, uid):
    saved = store.kv.get(feed.key_of(CLAN.alias, uid)) or {}
    return [row["text"] for row in saved.get("rows") or []]


def beat_for(store, clock=None, coc=None, supervisor=None):
    return publish.Beat(store, supervisor, coc, None, clock=clock or (lambda: 0.0))


class NoGoldpass:
    def __init__(self, data=None):
        self.data = data
        self.calls = 0

    async def goldpass(self):
        self.calls += 1
        return self.data, None


def poller_for(store, beat, bot=None, coc=None):
    supervisor = fake_supervisor(bot if bot is not None else FakeBot())
    supervisor.web = beat
    return Poller(supervisor, store, coc or NoGoldpass())


PAGE_ON = {"lang": "it", "tz": "Europe/Rome", "web": {"page": True}}


def tick_for(stored=None, members=None):
    t = Tick(CLAN, NOW)
    t.settings = settings.effective(stored or {"lang": "it", "tz": "Europe/Rome"}, None)
    t.L = i18n.locale(t.settings["lang"])
    t.tz = t.settings["tz"]
    t.members = members if members is not None else member_snapshot(clan_json(BASE_MEMBERS))
    t.season = scoring.empty_season("2026-09")
    return t


def test_il_pass_oro_si_legge_e_si_scrive_in_un_posto_solo(tmp_path):
    store = WebStore(Vault(tmp_path))
    coc = NoGoldpass({"startTime": "20260901T080000.000Z", "endTime": "20260928T050000.000Z"})
    poller = poller_for(store, beat_for(store), coc=coc)
    assert asyncio.run(poller.goldpass_end(NOW)) == "20260928T050000.000Z"
    assert set(store.kv[news_feed.SEASON_KEY]) == {"start", "end", "fetched"}
    assert asyncio.run(poller.goldpass_end(NOW)) == "20260928T050000.000Z"
    assert coc.calls == 1
    poller.goldpass = None
    assert asyncio.run(poller.goldpass_end(NOW)) == "20260928T050000.000Z"
    assert coc.calls == 1
    assert asyncio.run(news_feed.season(store, None, NOW))["end"] == "20260928T050000.000Z"


def test_the_slug_is_a_blind_index_and_does_not_change(tmp_path):
    vault = Vault(tmp_path)
    slug = payload.slug_for(vault, "clan-a1")
    assert len(slug) == 16 and slug.isalnum() and slug == payload.slug_for(vault, "clan-a1")
    assert slug != payload.slug_for(vault, "clan-a2")
    assert "clan-a1" not in slug


def test_the_public_payload_never_leaks_telegram_or_tags():
    body = built()
    flat = str(body)
    assert str(CLAN.chat_id) not in flat and CLAN.alias not in flat
    for tag, _, _, _, _, _, _ in BASE_MEMBERS:
        assert tag not in flat
    assert body["clan"] == {"name": "Nostro Clan", "tag": "#CLAN1", "level": 12,
                            "league": "Crystal League I", "points": 32000, "wins": 210,
                            "streak": 3, "members": 4, "badge": None}
    assert body["v"] == payload.VERSION and body["updated"] == int(NOW.timestamp())
    assert body["lang"] == "it" and body["tz"] == "Europe/Rome"


def test_la_pagina_pubblica_non_porta_nomi_ne_tag_dei_membri():
    for stored in (None, {"members": True, "stats": True}):
        body = built(stored)
        assert "members" not in body and "stats" not in body and "show" not in body
        flat = str(body)
        for tag, name, _, _, _, _, _ in BASE_MEMBERS:
            assert tag not in flat and name not in flat


def test_the_war_is_told_without_the_roster():
    body = built()
    war = body["war"]
    assert war["state"] == "inWar" and war["kind"] == "war" and war["size"] == 3
    assert war["us"] == {"name": "Nostro Clan", "stars": 3, "destr": 33.33, "attacks": 1}
    assert war["them"]["name"] == "Clan Nemico"
    assert war["end"] == int(datetime(2026, 9, 12, 10, tzinfo=timezone.utc).timestamp())
    assert "members" not in war and "defenders" not in war


def test_no_war_no_lies():
    assert built(war={"state": "notInWar"})["war"] is None
    assert built(war=None)["war"] is None


def test_the_calendar_rows_come_from_the_agenda():
    rows = built()["events"]
    assert [r["key"] for r in rows] == [i["key"] for i in agenda.upcoming(NOW)]
    assert all(isinstance(r["start"], int) and isinstance(r["end"], int) for r in rows)
    assert all(r["state"] in ("ongoing", "upcoming") for r in rows)


def test_the_digest_ignores_the_clock_and_the_calendar_stamp():
    first = built({"ics": True})
    second = dict(first, updated=first["updated"] + 60)
    second["ics"] = ics.build(i18n.locale("it"), SLUG, CLAN.name,
                              NOW + timedelta(minutes=5), None, None)
    assert second["ics"] != first["ics"]
    assert payload.digest(first) == payload.digest(second)
    third = dict(first)
    third["clan"] = dict(first["clan"], level=13)
    assert payload.digest(first) != payload.digest(third)


def test_the_hall_rows_come_from_the_titles_already_kept_for_the_clan():
    hall = {"seasons": [{"season": "2026-08", "titles": {"MVP": ["Mario", 120]}},
                        {"season": "2026-09", "titles": {"MVP": ["Luigi", 90]}}],
            "records": {}}
    rows = payload.stat_rows(scoring.empty_season("2026-09"), hall)["hall"]
    assert rows == [{"kind": "MVP", "name": "Luigi", "value": 90}]
    assert payload.stat_rows(scoring.empty_season("2026-09"), [])["hall"] == []


def test_the_points_come_from_the_season_the_bot_really_keeps():
    season = season_with_points()
    rows = payload.stat_rows(season, [])["points"]
    assert [row["name"] for row in rows] == ["Mario", "Luigi"]
    assert rows[0]["value"] == scoring.points(season["members"]["#P1"]) > 0
    assert [tag for tag, _, _ in scoring.leaderboard(season)] == ["#P1", "#P2"]
    assert "#P1" not in str(rows)
    assert payload.stat_rows(scoring.empty_season("2026-09"), [])["points"] == []
    senza_nome = scoring.empty_season("2026-09")
    scoring.apply_war(senza_nome, {"members": [
        {"tag": "#P7", "name": None, "attacks": [{"stars": 3}], "missed": 0}]})
    assert "#P7" not in str(payload.stat_rows(senza_nome, [])["points"])


def test_who_climbed_the_most_comes_from_the_week_the_boards_already_closed():
    members = member_snapshot(clan_json(BASE_MEMBERS))
    rows = payload.stat_rows(None, [], boards_state(), members)["climb"]
    assert rows == [{"name": "Mario", "value": 400}, {"name": "Luigi", "value": 100}]
    hidden = payload.stat_rows(None, [], boards_state(), members, {"#P1"})["climb"]
    assert [row["name"] for row in hidden] == ["Luigi"]
    assert payload.stat_rows(None, [], None, members)["climb"] == []
    anonimi = {tag: {"name": None, "trophies": row.get("trophies")}
               for tag, row in members.items()}
    assert "#P1" not in str(payload.stat_rows(None, [], boards_state(), anonimi)["climb"])
    assert leaderboards.closed_trophy_rows(boards_state(), members)[0]["tag"] == "#P1"


def test_the_page_is_written_again_only_when_something_really_changes(tmp_path):
    clock = [0.0]
    store = WebStore(Vault(tmp_path))
    beat = beat_for(store, lambda: clock[0])
    body = built()
    code = store.recruit_code(CLAN.alias)
    assert asyncio.run(beat.clan(CLAN, payload.PUBLIC, body, code)) is True
    slug, written = store.pages[(CLAN.alias, payload.PUBLIC)]
    assert slug == code and written == body
    assert asyncio.run(beat.clan(CLAN, payload.PUBLIC,
                                 dict(body, updated=body["updated"] + 60), code)) is False
    clock[0] = payload.REFRESH
    assert asyncio.run(beat.clan(CLAN, payload.PUBLIC, body, code)) is True
    clock[0] = payload.REFRESH + 1
    assert asyncio.run(beat.clan(CLAN, payload.PUBLIC,
                                 dict(body, clan=dict(body["clan"], level=13)), code)) is True


def public_with(stored=None, info=None, hall=None, **kw):
    conf = settings.effective(dict({"lang": "it", "tz": "Europe/Rome"}, **(stored or {})),
                              clan_json(BASE_MEMBERS))
    return payload.public_payload(
        CLAN, conf, info or INFO, None, "war", None, hall or [], agenda.upcoming(NOW), NOW, **kw)


def test_la_pagina_pubblica_non_porta_un_secondo_interruttore():
    assert "public" not in public_with()
    assert "public" not in public_with({"web": {"page": True}})


def test_la_riga_pubblica_e_la_sola_fonte_dell_acceso_e_dello_spento(tmp_path):
    store = WebStore(Vault(tmp_path), URL)
    poller = poller_for(store, beat_for(store))
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    asyncio.run(poller.publish_web(tick_for(PAGE_ON)))
    code = store.recruit_code(CLAN.alias)
    assert asyncio.run(store.web_page(code, payload.PUBLIC))
    assert asyncio.run(store.web_page(payload.slug_for(store.vault, CLAN.alias),
                                      payload.PUBLIC)) is None
    asyncio.run(poller.publish_web(tick_for({"lang": "it", "tz": "Europe/Rome",
                                             "web": {"page": False}})))
    assert asyncio.run(store.web_page(code, payload.PUBLIC)) is None


def test_la_pagina_pubblica_porta_posti_requisiti_record_stemma_e_candidatura():
    body = public_with({"web": {"page": True}, "min_th": 15}, info=dict(INFO, badge=BADGE),
                       hall={"records": {"wars": 8, "wins": 5}}, bot="ClanUnoBot", code="ab12cd")
    assert body["free"] == util.CLAN_SLOTS - INFO["members"]
    assert body["min_th"] == 15
    assert body["record"] == {"wars": 8, "wins": 5}
    assert body["clan"]["badge"] == BADGE
    assert body["bot"] == "ClanUnoBot" and body["code"] == "ab12cd"


def test_lo_stemma_entra_solo_se_arriva_dall_indirizzo_ufficiale():
    assert public_with(info=dict(INFO, badge="https://altro.example/uno.png"))["clan"]["badge"] \
        is None
    assert public_with()["clan"]["badge"] is None


def test_la_pagina_pubblica_porta_il_bot_del_clan_e_il_codice_della_candidatura(tmp_path):
    store = WebStore(Vault(tmp_path), URL)
    bot = FakeBot()
    bot.username = "ClanUnoBot"
    poller = poller_for(store, beat_for(store), bot=bot)
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    asyncio.run(poller.publish_web(tick_for(PAGE_ON)))
    _, body = store.pages[(CLAN.alias, payload.PUBLIC)]
    assert body["bot"] == "ClanUnoBot" and body["code"] == store.recruit_code(CLAN.alias)


def test_the_calendar_travels_inside_the_public_page_or_not_at_all():
    assert built()["ics"] is None
    page = built({"ics": True})
    assert page["ics"].startswith("BEGIN:VCALENDAR") and page["extras"]["ics"] is True
    assert f"-{SLUG}@clanboard" in page["ics"]
    assert CLAN.alias not in page["ics"]


def test_la_pagina_pubblica_si_apre_col_codice_e_non_con_la_chiave_dell_app(tmp_path):
    store = WebStore(Vault(tmp_path), URL)
    poller = poller_for(store, beat_for(store))
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    asyncio.run(poller.publish_web(tick_for(PAGE_ON)))
    code = store.recruit_code(CLAN.alias)
    slug = payload.slug_for(store.vault, CLAN.alias)
    aperta = asyncio.run(web_app.Site(store).router(request(f"/c/{code}")))
    assert aperta.status == 200 and slug not in aperta.body.decode()
    assert asyncio.run(web_app.Site(store).router(request(f"/c/{slug}"))).status == 404


def test_the_control_round_publishes_the_page_and_calls_the_leaders_once(tmp_path):
    store = WebStore(Vault(tmp_path), URL)
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    poller = poller_for(store, beat_for(store))
    t = tick_for(PAGE_ON)
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    asyncio.run(store.set_state(CLAN.alias, "war",
                                war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]}))))
    asyncio.run(poller.publish_web(t))
    slug, body = store.pages[(CLAN.alias, payload.PUBLIC)]
    assert slug == store.recruit_code(CLAN.alias)
    assert slug != payload.slug_for(store.vault, CLAN.alias)
    assert body["clan"]["name"] == CLAN.name and body["war"]["state"] == "inWar"
    ready = feed_rows(store, 7)
    assert len(ready) == 1 and f"{URL}/c/{slug}" in ready[0]
    assert payload.slug_for(store.vault, CLAN.alias) not in ready[0]
    asyncio.run(poller.publish_web(t))
    assert len(feed_rows(store, 7)) == 1


def test_without_a_public_address_the_leaders_are_not_called(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    poller = poller_for(store, beat_for(store))
    t = tick_for(PAGE_ON)
    asyncio.run(poller.publish_web(t))
    assert (CLAN.alias, payload.PUBLIC) in store.pages and feed_rows(store, 7) == []


def test_la_pagina_pubblica_nasce_spenta_e_l_app_esce_lo_stesso(tmp_path):
    assert settings.WEB_DEFAULTS["page"] is False
    store = WebStore(Vault(tmp_path), URL)
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    poller = poller_for(store, beat_for(store))
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    asyncio.run(poller.publish_web(tick_for()))
    assert (CLAN.alias, payload.PUBLIC) not in store.pages
    assert (CLAN.alias, payload.APP) in store.pages
    assert feed_rows(store, 7) == []


def published_app(store, members, conf=None, info=None, clan=CLAN):
    assert asyncio.run(beat_for(store).app(
        clan, conf or tick_for().settings, members, info or INFO, NOW)) is True
    return store.pages[(clan.alias, payload.APP)][1]


def test_the_mini_app_opens_to_who_commands_the_clan_not_only_to_who_is_in_the_war(tmp_path):
    roster = BASE_MEMBERS + [("#P5", "Yoshi", "coLeader", 15, 5000, 100, 100)]
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None),
                   SimpleNamespace(tag="#P5", user_id=9, name="Yoshi", dm=True, lang="it"),
                   SimpleNamespace(tag="#P4", user_id=11, name="Toad", dm=True, lang=None)]
    members = member_snapshot(clan_json(roster))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, "war",
                                war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]}))))
    body = published_app(store, members)
    assert body["seats"]["9"] == {"tag": "#P5", "name": "Yoshi", "level": "manager",
                                  "lang": "it", "avail": None, "verified": True,
                                  "whisper": False, "goal": None}
    assert body["seats"]["7"]["level"] == "manager"
    assert body["seats"]["11"]["level"] is None
    assert [our["name"] for our in body["ours"]] == ["Mario", "Luigi", "Peach"]
    assert body["clan"] == {"name": CLAN.name, "level": 12, "league": "Crystal League I",
                            "members": 4, "accent": None, "badge": None}


def test_the_app_page_stays_online_without_a_war_with_sections_and_profiles(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang="it")]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, "boards", {"wars": {"lines": ["10:00 · prima riga"]}}))
    asyncio.run(store.set_state(CLAN.alias, "players", {"tags": {"#P1": PLAYER}}))
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome",
                               "packs": {"members": False}}, None)
    body = published_app(store, members, conf)
    assert store.dropped == [] and body["war"] is None and body["rows"] == []
    assert body["sections"]["wars"] == ["10:00 · prima riga"]
    assert body["sections"]["cwl"] == [] and "members" not in body["sections"]
    assert body["profiles"]["7"] == {"name": "Mario", "tag": "#P1", "th": 16,
                                     "league": "Crystal League I", "trophies": 5400,
                                     "best": 5600, "stars": 900, "heroes": "👑90",
                                     "donations": 1200, "pref": "in"}


def test_a_suspended_manager_keeps_the_seat_without_the_power(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.kv_set(guard.suspended_key(CLAN.alias, 7), {"at": 1}))
    body = published_app(store, members)
    assert body["seats"]["7"] == {"tag": "#P1", "name": "Mario", "level": None, "lang": None,
                                  "avail": None, "verified": True, "whisper": False,
                                  "goal": None}
    assert body["profiles"] == {}


def test_ogni_posto_porta_la_disponibilita_che_ha_detto(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None),
                   SimpleNamespace(tag="#P4", user_id=11, name="Toad", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, availability.STATE, {
        "poll_id": "p1", "message_id": 3,
        "votes": {"7": {"name": "Mario", "option": availability.OUT}}}))
    body = published_app(store, members)
    assert body["seats"]["7"]["avail"] == "out" and body["seats"]["11"]["avail"] is None


def test_ogni_posto_porta_l_anello_dell_obiettivo(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, "players", {"tags": {"#P1": PLAYER}}))
    asyncio.run(store.set_state(CLAN.alias, "goals",
                                {"#P1": {"kind": "trophies", "hero": None, "target": 6000}}))
    body = published_app(store, members)
    goal = body["seats"]["7"]["goal"]
    assert goal["kind"] == "trophies" and goal["target"] == 6000
    assert goal["value"] == PLAYER["trophies"] and goal["picks"]


def challenge_state(quiz_poll=None):
    state = challenges.empty()
    state["duels"]["open"] = [{"id": "d1", "status": "proposed", "metric": "donated",
                               "duration": "week", "proposed": int(NOW.timestamp()),
                               "base": {}, "ends": 0,
                               "a": {"tag": "#P1", "name": "Mario", "user_id": 7},
                               "b": {"tag": "#P4", "name": "Toad", "user_id": 11}}]
    state["quiz"]["open"] = quiz_poll
    return state


def test_la_pagina_dell_app_porta_agenda_ultima_guerra_e_giochi(tmp_path):
    ended = war_snapshot(war_json("warEnded", {"#P1": [("#E1", 3, 100.0)]}))
    store = WebStore(Vault(tmp_path), wars=[war_record(ended)])
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang="it"),
                   SimpleNamespace(tag="#P4", user_id=11, name="Toad", dm=True, lang="it")]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, challenges.KIND, challenge_state(
        {"poll_id": "q1", "message_id": 5, "id": "w1", "occurrence": "20260911",
         "votes": {"11": {"name": "Toad", "option": 0}}})))
    asyncio.run(store.set_state(CLAN.alias, predictions.state_key("war"),
                                {"poll_id": "p1", "message_id": 6, "war": "chiave",
                                 "votes": {"7": {"name": "Mario", "option": 1}}}))
    body = published_app(store, members)
    L = i18n.locale("it")
    assert [row["key"] for row in body["agenda"]] == [item["key"] for item in agenda.upcoming(NOW)]
    assert all(isinstance(row["start"], int) and isinstance(row["end"], int)
               for row in body["agenda"])
    assert body["last_war"] == {
        "them": "Clan Nemico", "us_stars": 3, "them_stars": 0, "us_destr": 33.33,
        "them_destr": 0.0, "result": "win",
        "ended": int(datetime(2026, 9, 12, 10, tzinfo=timezone.utc).timestamp())}
    games = body["games"]
    assert games["duels"] == [{"id": "d1", "challenger": "#P1", "rival": "#P4",
                               "metric": "donated", "status": "proposed", "ends": 0}]
    assert games["quiz"] == {"open": True, "question": L.t("quiz.q.w1"),
                             "options": [L.t(f"quiz.q.w1.{i}") for i in range(quizbank.OPTIONS)],
                             "answered": ["#P4"]}
    assert games["predictions"] == [
        {"poll": "war", "options": [L.t(f"poll.option.{i}") for i in range(scoring.POLL_OPTIONS)],
         "voted": ["#P1"]}]
    assert L.t("quiz.q.w1.why") not in str(games) and "user_id" not in str(games)


def test_lo_storico_delle_guerre_sta_nella_pagina_e_si_rilegge_solo_a_guerra_nuova(tmp_path):
    ended = war_snapshot(war_json("warEnded", {"#P1": [("#E1", 3, 100.0)]}))
    store = WebStore(Vault(tmp_path), wars=[war_record(ended)])
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang="it")]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, "hall", {"records": {"wars": 1}}))
    reads = []
    plain = store.recent_wars

    async def counted(alias, limit=10):
        reads.append(limit)
        return await plain(alias, limit)

    store.recent_wars = counted
    beat = beat_for(store)
    conf = tick_for().settings
    asyncio.run(beat.app(CLAN, conf, members, INFO, NOW))
    body = store.pages[(CLAN.alias, payload.APP)][1]
    assert body["wars"] == [body["last_war"]]
    assert body["wars"][0]["them"] == "Clan Nemico" and body["wars"][0]["result"] == "win"
    asyncio.run(beat.app(CLAN, conf, members, INFO, NOW))
    assert reads == [publish.WAR_HISTORY_KEEP]
    store.wars.append(war_record(war_snapshot(war_json("warEnded", {"#P1": [("#E1", 1, 40.0)]}))))
    asyncio.run(store.set_state(CLAN.alias, "hall", {"records": {"wars": 2}}))
    asyncio.run(beat.app(CLAN, conf, members, INFO, NOW))
    assert reads == [publish.WAR_HISTORY_KEEP, publish.WAR_HISTORY_KEEP]
    assert len(store.pages[(CLAN.alias, payload.APP)][1]["wars"]) == 2


def test_senza_giochi_aperti_la_pagina_non_inventa_niente(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang="it")]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    body = published_app(store, members)
    assert body["last_war"] is None and body["agenda"]
    assert body["games"] == {"duels": [], "quiz": None, "predictions": [],
                             "guess": None}


def cwl_store(tmp_path, cwl, wars, roster=None, cwl_war=None):
    store = WebStore(Vault(tmp_path), wars=wars)
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CWL_CLAN.alias, "members", members))
    asyncio.run(store.set_state(CWL_CLAN.alias, "cwl", cwl))
    if roster is not None:
        asyncio.run(store.set_state(CWL_CLAN.alias, cwl_roster.STATE, roster))
    if cwl_war is not None:
        asyncio.run(store.set_state(CWL_CLAN.alias, "cwl_war", cwl_war))
    return store, members


def test_la_pagina_porta_le_sette_giornate_di_lega_la_formazione_e_la_classifica(tmp_path):
    roster = {"season": SEASON, "avail": {"#P1": {"state": "in", "by": 7, "ts": 0}},
              "bonus": ["#P2"], "lineup": ["#P1"], "sent": {}}
    store, members = cwl_store(tmp_path, cwl_state(), war_records(), roster)
    cwl = published_app(store, members, clan=CWL_CLAN)["cwl"]
    assert cwl["season"] == SEASON and cwl["day"] is None
    assert [row["n"] for row in cwl["days"]] == [1, 2, 3, 4, 5, 6, 7]
    assert cwl["days"][0] == {"n": 1, "them": "Clan Due", "us_stars": 9, "them_stars": 6,
                              "result": "win", "state": "done"}
    assert cwl["days"][1]["result"] == "lose" and cwl["days"][1]["us_stars"] == 8
    assert [row["state"] for row in cwl["days"][2:]] == ["next"] * 5
    assert cwl["days"][6] == {"n": 7, "them": None, "us_stars": 0, "them_stars": 0,
                              "result": None, "state": "next"}
    assert [(row["name"], row["th"], row["in"], row["bonus"]) for row in cwl["lineup"]] == [
        ("Mario", 15, True, False), ("Peach", 13, False, False), ("Luigi", 14, False, True)]
    assert all(row["attacked"] is False for row in cwl["lineup"])
    assert {row["name"]: row["picked"] for row in cwl["lineup"]} == {
        "Mario": True, "Luigi": False, "Peach": False}
    assert cwl["table"] == [{"name": "Nostro Clan", "stars": 27, "destr": 170.0, "rank": 1},
                            {"name": "Clan Due", "stars": 24, "destr": 155.0, "rank": 2}]


def test_la_giornata_in_corso_dice_chi_ha_gia_attaccato(tmp_path):
    state = cwl_state(state="inWar", active=True)
    state["wars"]["#W2"]["state"] = "inWar"
    war = war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]}))
    war["day"] = 2
    store, members = cwl_store(tmp_path, state, war_records()[:1], cwl_war=war)
    body = published_app(store, members, clan=CWL_CLAN)
    cwl = body["cwl"]
    assert body["war"]["kind"] == "cwl" and body["war"]["day"] == 2
    assert cwl["day"] == 2
    assert [row["state"] for row in cwl["days"][:3]] == ["done", "live", "next"]
    assert cwl["days"][1] == {"n": 2, "them": "Clan Due", "us_stars": 8, "them_stars": 8,
                              "result": None, "state": "live"}
    assert {row["name"]: row["attacked"] for row in cwl["lineup"]} == {
        "Mario": True, "Luigi": False, "Peach": False}


def test_fuori_dalla_lega_la_pagina_non_inventa_la_striscia(tmp_path):
    store, members = cwl_store(tmp_path, None, war_records())
    assert published_app(store, members, clan=CWL_CLAN)["cwl"] is None
    fuori, members = cwl_store(tmp_path, cwl_state(), war_records())
    assert published_app(fuori, members)["cwl"] is None


def test_the_app_page_carries_the_record_the_growth_and_the_medals(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, "hall", {"seasons": [], "records": {
        "wars": 10, "wins": 7, "streak": {"current": 2, "best": 5}}}))
    asyncio.run(store.set_state(CLAN.alias, "trend", {"#P1": {"name": "Mario", "days": [
        {"d": "2026-09-20", "trophies": 5000, "th": 16},
        {"d": "2026-09-21", "trophies": 5100, "th": 16}]}}))
    asyncio.run(store.set_state(CLAN.alias, "progress", {"#P1": {
        "name": "Mario", "week": {"since": 1}, "month": {"since": 1},
        "now": {"donated": 40, "war_stars": 5, "levels": 3}}}))
    asyncio.run(store.set_state(CLAN.alias, challenges.KIND,
                                {"badges": {"#P1": {"th": {"n": 1, "ts": 7}}}}))
    body = published_app(store, members)
    assert body["record"]["wars"] == 10 and body["record"]["streak"] == {"current": 2, "best": 5}
    assert body["growth"]["days"] == ["2026-09-20", "2026-09-21"]
    assert body["growth"]["players"]["#P1"]["trophies"] == [5000, 5100]
    assert body["growth"]["clan"]["trophies"] == [5000, 5100]
    assert body["growth"]["period"]["week"]["#P1"] == {"donated": 40, "war_stars": 5,
                                                       "levels": 3, "score": 9}
    assert body["medals"] == {"#P1": [{"badge": "th", "ts": 7}]}
    assert body["members"][0]["tag"] == "#P1" and body["members"][0]["linked"] is True
    assert body["members"][0]["verified"] is True and body["members"][1]["linked"] is False


def test_the_app_page_shows_the_medals_won_with_the_telegram_number(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, challenges.KIND, {"badges": {
        "#P1": {"th": {"n": 1, "ts": 7}},
        "7": {"quiz": {"n": 1, "ts": 9}, "veggente": {"n": 1, "ts": 11}},
        "11": {"ambasciatore": {"n": 1, "ts": 13}}}}))
    body = published_app(store, members)
    assert body["medals"]["#P1"] == [{"badge": "quiz", "ts": 9}, {"badge": "th", "ts": 7},
                                     {"badge": "veggente", "ts": 11}]
    assert list(body["medals"]) == ["#P1"]


def test_the_app_page_says_the_availability_of_every_member(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None),
                   SimpleNamespace(tag="#P4", user_id=11, name="Toad", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, availability.STATE, {
        "poll_id": "p1", "message_id": 3,
        "votes": {"7": {"name": "Mario", "option": availability.OUT}}}))
    body = published_app(store, members)
    rows = {row["tag"]: row for row in body["members"]}
    assert rows["#P1"]["avail"] == "out" and rows["#P4"]["avail"] is None
    assert rows["#P2"]["avail"] is None and rows["#P2"]["linked"] is False
    assert body["record"]["wars"] == 0 and body["medals"] == {}
    assert body["growth"]["days"] == [] and body["growth"]["period"]["week"] == {}


LAYOUT = "TH16:HV:AAAABBBBCCCC"
UPLOADER = 4242
FAKE_HOST_LINK = "https://link.clashofclans.example/it?action=OpenLayout&id=TH16:HV:AAAABBBB"
BROKEN_ID_LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16:HV:x"
OTHER_CLAN = Clan(alias="clan-b2", chat_id=-200, tag="#CLAN2", name="Secondo Clan", active=True,
                  failures=0, last_seen=None, bot_alias="bot-1")


def clan_base(alias="base-1", label="war", village="home", hall=16, name="Mario"):
    return {"alias": alias, "clan_alias": CLAN.alias, "label": label, "village": village,
            "hall": hall, "shared": False, "published": False, "created_at": NOW,
            "id": LAYOUT, "name": name, "by": UPLOADER}


def library_base(ident, hall, added, village="home", kind="war"):
    return {"id": ident, "name": f"Base {ident}", "hall": hall, "village": village, "kind": kind,
            "link": bases.link_url(i18n.locale("it"), LAYOUT), "builder": "Chi la disegna",
            "tags": ["anti3"], "added": added}


def clip(ident, published, channel="UCcanale"):
    return {"id": ident, "channel": channel, "title": f"Video {ident}", "published": published,
            "links": [bases.link_url(i18n.locale("it"), LAYOUT)]}


def members_of(halls):
    rows = [(f"#P{n}", f"Tale{n}", "member", hall, 4000, 10, 10)
            for n, hall in enumerate(halls, start=1)]
    return member_snapshot(clan_json(rows))


def test_la_pagina_porta_le_basi_del_clan_senza_dire_chi_le_ha_caricate(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.bases = [clan_base(), clan_base(alias="base-2", label="farm", hall=15, name="Luigi")]
    body = published_app(store, members_of([16, 15]))
    assert body["bases"]["clan"] == [
        {"alias": "base-1", "label": "war", "village": "home", "hall": 16,
         "link": bases.link_url(i18n.locale("it"), LAYOUT), "by": "Mario"},
        {"alias": "base-2", "label": "farm", "village": "home", "hall": 15,
         "link": bases.link_url(i18n.locale("it"), LAYOUT), "by": "Luigi"},
    ]
    assert str(UPLOADER) not in str(body["bases"])


def test_la_libreria_aperta_arriva_per_il_municipio_piu_comune_e_i_due_sotto(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.library = [library_base("aaa111", 16, "2026-09-02"),
                     library_base("bbb222", 15, "2026-09-03"),
                     library_base("ccc333", 12, "2026-09-04")]
    library = published_app(store, members_of([16, 15]))["bases"]["library"]
    assert library["halls"] == [16, 15, 14]
    assert [row["id"] for row in library["rows"]] == ["bbb222", "aaa111"]
    assert library["rows"][0]["builder"] == "Chi la disegna"
    comune = published_app(WebStore(Vault(tmp_path)), members_of([15, 15, 16]))["bases"]["library"]
    assert comune["halls"] == [15, 14, 13]


def test_i_video_sono_quelli_di_piattaforma_piu_quelli_del_clan_senza_doppioni(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.videos = {base_videos.PLATFORM: [clip("v1", "2026-09-01")],
                    CLAN.alias: [clip("v2", "2026-09-05"), clip("v1", "2026-09-01")],
                    OTHER_CLAN.alias: [clip("v9", "2026-09-09")]}
    library = published_app(store, members_of([16]))["bases"]["library"]
    assert [row["id"] for row in library["videos"]] == ["v2", "v1"]
    assert library["videos"][0]["links"] == [bases.link_url(i18n.locale("it"), LAYOUT)]


def test_la_pagina_porta_i_consigli_e_i_video_d_attacco_per_municipio(tmp_path):
    ricordo = [war_record(war_snapshot(war_json("warEnded", {"#P1": [("#E1", 3, 100.0)]})))]
    store = WebStore(Vault(tmp_path), wars=ricordo)
    store.videos = {base_videos.PLATFORM: [{**clip("v1", "2026-09-01"),
                                            "title": "TH14 anti tre stelle"},
                                           {**clip("v2", "2026-09-02"), "title": "basi nuove"}]}
    asyncio.run(store.set_state(CLAN.alias, "war",
                                war_snapshot(war_json("inWar", {"#P1": [("#E1", 2, 80.0)]}))))
    page = published_app(store, members_of([14]))
    assert page["advice"]["14"]["avg_stars"] == 3.0
    assert page["advice"]["14"]["best"] == [{"name": "Mario", "stars": 3.0, "count": 1}]
    assert [row["video_id"] for row in page["attack_videos"]["14"]] == ["v1"]
    assert page["attack_videos"]["14"][0]["channel"] == "UCcanale"


def test_senza_guerra_i_consigli_non_si_calcolano(tmp_path):
    ricordo = [war_record(war_snapshot(war_json("warEnded", {"#P1": [("#E1", 3, 100.0)]})))]
    store = WebStore(Vault(tmp_path), wars=ricordo)
    assert published_app(store, members_of([14]))["advice"] == {}


def test_i_link_della_libreria_e_dei_video_sono_rivalidati_prima_di_mostrarli(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.library = [library_base("aaa111", 16, "2026-09-02"),
                     {**library_base("zzz999", 16, "2026-09-06"), "link": FAKE_HOST_LINK},
                     {**library_base("yyy888", 16, "2026-09-07"), "link": BROKEN_ID_LINK}]
    store.videos = {base_videos.PLATFORM: [
        {**clip("v1", "2026-09-01"),
         "links": [FAKE_HOST_LINK, bases.link_url(i18n.locale("it"), LAYOUT), BROKEN_ID_LINK]},
        {**clip("v2", "2026-09-02"), "links": [BROKEN_ID_LINK]}]}
    library = published_app(store, members_of([16]))["bases"]["library"]
    assert [row["id"] for row in library["rows"]] == ["aaa111"]
    assert [row["id"] for row in library["videos"]] == ["v2", "v1"]
    assert library["videos"][1]["links"] == [bases.link_url(i18n.locale("it"), LAYOUT)]
    assert library["videos"][0]["links"] == []
    assert FAKE_HOST_LINK not in str(library) and BROKEN_ID_LINK not in str(library)


def test_la_pagina_dice_posti_requisito_e_stato_della_pagina_pubblica(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.recruiting = True
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome", "min_th": 14,
                               "web": {"page": False}}, None)
    body = published_app(store, member_snapshot(clan_json(BASE_MEMBERS)), conf)
    assert body["recruit"] == {"open": True, "free": 46, "requirement": 14, "page_on": False,
                               "code": store.recruit_code(CLAN.alias)}
    acceso = settings.effective({"lang": "it", "tz": "Europe/Rome", "web": {"page": True}}, None)
    aperto = published_app(store, member_snapshot(clan_json(BASE_MEMBERS)), acceso)["recruit"]
    assert aperto["page_on"] is True
    chiuso = published_app(WebStore(Vault(tmp_path)), members_of([16]))["recruit"]
    assert chiuso["open"] is False and chiuso["requirement"] is None and chiuso["page_on"] is False


def test_la_pagina_porta_la_famiglia_con_i_codici_pubblici_dei_clan(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.family = Family(alias="fam-1", name="Nostra Famiglia", owner_id=7, chat_id=None,
                          bot_alias="bot-1")
    store.family_rows = [CLAN, OTHER_CLAN]
    body = published_app(store, members_of([16]))
    assert body["family"] == {
        "name": "Nostra Famiglia", "code": "fam-1",
        "clans": [{"name": CLAN.name, "code": store.recruit_code(CLAN.alias)},
                  {"name": OTHER_CLAN.name, "code": store.recruit_code(OTHER_CLAN.alias)}],
    }
    assert published_app(WebStore(Vault(tmp_path)), members_of([16]))["family"] is None


MARIO_UID = 4242
LUIGI_UID = 5353
PEACH_UID = 6464


def duel_state(status="open", metric="loot", duration="week"):
    state = challenges.empty()
    state["duels"]["open"] = [{
        "id": "abcd1234", "status": status, "metric": metric, "duration": duration,
        "proposed": 0, "base": {}, "ends": 1789200000,
        "a": {"tag": "#P1", "name": "Mario", "user_id": MARIO_UID},
        "b": {"tag": "#P2", "name": "Luigi", "user_id": LUIGI_UID}}]
    return state


def store_with_duel(tmp_path, status="open"):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=MARIO_UID, name="Mario", dm=True, lang=None),
                   SimpleNamespace(tag="#P2", user_id=LUIGI_UID, name="Luigi", dm=True, lang=None),
                   SimpleNamespace(tag="#P3", user_id=PEACH_UID, name="Peach", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(challenges.save(store, CLAN.alias, duel_state(status)))
    return store, members


def test_la_sfida_in_corso_arriva_dalla_pagina_pubblicata_fino_a_chi_la_guarda(tmp_path):
    store, members = store_with_duel(tmp_path)
    body = published_app(store, members)
    assert body[payload.DUELS] == [
        {"id": "abcd1234", "metric": "loot", "status": "open", "ends": 1789200000,
         "a": {"tag": "#P1", "name": "Mario"}, "b": {"tag": "#P2", "name": "Luigi"}}]
    assert str(MARIO_UID) not in str(body[payload.DUELS])
    assert str(LUIGI_UID) not in str(body[payload.DUELS])
    seen = miniapp.state_body(body, {"uid": LUIGI_UID, "tag": "#P2", "name": "Luigi"})
    assert seen["more_view"]["duels"] == [
        {"id": "abcd1234", "metric": "loot", "status": "open", "ends": 1789200000,
         "rival": "Mario", "mate": None}]
    assert payload.DUELS not in seen
    assert str(MARIO_UID) not in str(seen["more_view"]["duels"])
    assert str(LUIGI_UID) not in str(seen["more_view"]["duels"])


def test_chi_guarda_da_fuori_vede_i_due_sfidanti_e_nessun_tag(tmp_path):
    store, members = store_with_duel(tmp_path)
    seen = miniapp.state_body(published_app(store, members),
                              {"uid": PEACH_UID, "tag": "#P3", "name": "Peach"})
    assert seen["more_view"]["duels"][0]["mate"] == "Mario"
    assert seen["more_view"]["duels"][0]["rival"] == "Luigi"
    assert "#P1" not in str(seen["more_view"]["duels"])
    assert "#P2" not in str(seen["more_view"]["duels"])


def test_la_sfida_solo_proposta_non_finisce_nella_pagina_di_tutto_il_clan(tmp_path):
    store, members = store_with_duel(tmp_path, status="proposed")
    assert published_app(store, members)[payload.DUELS] == []


class IntentStore(WebStore):
    def __init__(self, vault, rows=()):
        super().__init__(vault)
        self.queued = [dict(row) for row in rows]
        self.done = []

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def web_intents_take(self, limit=50):
        taken, self.queued = self.queued, []
        return taken

    async def web_intent_done(self, intent_id):
        self.done.append(intent_id)


def test_a_gesture_from_the_app_rewrites_the_page_within_the_beat(tmp_path):
    store = IntentStore(Vault(tmp_path), [{"id": 3, "clan": CLAN.alias,
                                           "kind": "target.mirror", "body": {"by": 7}}])
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang="it")]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    asyncio.run(store.set_state(CLAN.alias, "war",
                                war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]}))))
    assert asyncio.run(intents.drain(store, beat_for(store), NOW)) == 1
    assert store.done == [3]
    slug, body = store.pages[(CLAN.alias, payload.APP)]
    assert slug == payload.slug_for(store.vault, CLAN.alias)
    assert body["clan"] == {"name": CLAN.name, "level": 12, "league": "Crystal League I",
                            "members": 4, "accent": None, "badge": None}
    assert body["seats"]["7"]["level"] == "manager"
    assert [row["assignee"] for row in body["rows"]] == ["Mario", "Luigi", "Peach"]


def test_il_battito_svuota_gli_intenti_a_ogni_giro(tmp_path):
    store = IntentStore(Vault(tmp_path), [{"id": 3, "clan": CLAN.alias, "kind": "target.mirror",
                                           "body": {"kind": "target.mirror", "by": 7,
                                                    "id": "ab12"}}])
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang="it")]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    asyncio.run(store.set_state(CLAN.alias, "war",
                                war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]}))))
    beat = beat_for(store)
    beat.last_notes = beat.clock()
    assert asyncio.run(beat.once()) is True
    assert store.done == [3] and store.queued == []
    assert asyncio.run(store.get_state(CLAN.alias, "plan"))["targets"]
    assert publish.BEAT_EVERY == 2


def test_with_the_page_off_only_the_public_page_leaves_the_web(tmp_path):
    store = WebStore(Vault(tmp_path), URL)
    poller = poller_for(store, beat_for(store))
    t = tick_for({"lang": "it", "tz": "Europe/Rome", "web": {"page": False}})
    asyncio.run(poller.publish_web(t))
    assert store.dropped == [(CLAN.alias, payload.PUBLIC)]
    assert list(store.pages) == [(CLAN.alias, payload.APP)]


def board_with_events():
    state = boards.append({}, "members", ["Toad è entrato"], NOW, TZ,
                          facts=[{"kind": "join", "who": "Toad", "n": 13}])
    state = boards.append(state, "members", ["Peach è uscita"], NOW + timedelta(minutes=5), TZ,
                          facts=[{"kind": "leave", "who": "Peach", "n": None}])
    return boards.append(state, "wars", ["guerra finita"], NOW + timedelta(minutes=10), TZ,
                         facts=[{"kind": "war_end", "who": "Clan Nemico", "n": 3}])


def progress_with_silence():
    counters = {key: 0 for key in progress.COUNTERS}
    state = progress.update({}, "#P2", "Luigi", counters, NOW - timedelta(days=4), TZ)
    return progress.update(state, "#P1", "Mario", counters, NOW, TZ)


def app_state(tmp_path, **state):
    store = WebStore(Vault(tmp_path), state={(CLAN.alias, kind): value
                                             for kind, value in state.items()})
    asyncio.run(beat_for(store).app(CLAN, tick_for().settings,
                                    member_snapshot(clan_json(BASE_MEMBERS)), INFO, NOW))
    return store.pages[(CLAN.alias, payload.APP)][1]


def test_la_pagina_porta_gli_eventi_strutturati_del_tabellone(tmp_path):
    body = app_state(tmp_path, boards=board_with_events())
    assert [row["kind"] for row in body["events"]] == ["war_end", "leave", "join"]
    assert body["events"][0] == {"pack": "wars", "kind": "war_end", "who": "Clan Nemico", "n": 3,
                                 "at": int((NOW + timedelta(minutes=10)).timestamp())}
    assert body["events"][2]["who"] == "Toad" and body["events"][2]["n"] == 13
    assert app_state(tmp_path)["events"] == []


def test_la_pagina_dice_da_quanto_uno_non_si_fa_vedere(tmp_path):
    body = app_state(tmp_path, progress=progress_with_silence())
    assert body["idle"] == [{"tag": "#P2", "name": "Luigi", "days": 4}]
    assert app_state(tmp_path)["idle"] == []


def test_la_pagina_dell_app_porta_il_riepilogo_della_stagione_chiusa(tmp_path):
    store = WebStore(Vault(tmp_path))
    store.links = [SimpleNamespace(tag="#P1", user_id=7, name="Mario", dm=True, lang=None)]
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    until = progress.period_start(NOW, TZ, recap.PERIOD)
    asyncio.run(store.set_state(CLAN.alias, "progress", {"#P1": {
        "name": "Mario", "week": {"since": 1}, "month": {"since": 1},
        "now": {"donated": 40, "war_stars": 5, "levels": 3},
        "last_month": {"until": until, "since": 0, "score": 120, "wins": 40, "war_stars": 30,
                       "donated": 900, "levels": 6}}}))
    body = published_app(store, members)
    assert body["recap"]["season"] == recap.season_of(NOW, TZ)
    assert body["recap"]["players"][0]["name"] == "Mario"
    assert miniapp.state_body(body, {"uid": 7, "tag": "#P1"})["recap"]["me"]["rank"] == 1
    assert "recap" not in str(miniapp.state_body(body, {"uid": 7, "tag": "#P1"})["clan"])


def test_senza_stagione_chiusa_la_pagina_non_inventa_il_riepilogo(tmp_path):
    store = WebStore(Vault(tmp_path))
    members = member_snapshot(clan_json(BASE_MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "members", members))
    body = published_app(store, members)
    assert body["recap"] is None
    assert miniapp.state_body(body, {"uid": 7, "tag": "#P1"})["recap"] is None
