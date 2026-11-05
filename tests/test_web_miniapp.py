import ast
import asyncio
import base64
import json
import logging
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from clashbot import (acts, agenda, badges, base_videos, boards, discipline, exports, feed,
                      goals, i18n, intents, leader_cards, mydata, progress, reasons, retention,
                      settings, share_cards, source, targets)
from clashbot.crypto import Vault
from clashbot.db import SCHEMA, Clan, Store
from clashbot.events import member_snapshot, war_snapshot
from clashbot.web import (app as web_app, app_manage, app_war, ban, http, live, miniapp, payload,
                          static, style)
from fixtures import BASE_MEMBERS, clan_json, war_json
from test_app_manage import MANAGE_STAFF, MANAGE_TOOLS
from test_web_auth import TOKEN, signed
from test_web_page import PageStore
from test_web_status import request

FOGLIO = (static.ROOT / "app" / "app.css").read_text(encoding="utf-8")
BASE = (static.ROOT / "base.css").read_text(encoding="utf-8")
NOW = datetime.fromtimestamp(1789000000, timezone.utc)
SLUG = "abcdef0123456789"
OTHER = "0123456789abcdef"
CLAN = Clan(alias="clan-a1", chat_id=-100, tag="#CLAN1", name="Nostro Clan", active=True,
            failures=0, last_seen=None, bot_alias="bot-1")
WAR = war_snapshot(war_json("inWar", {"#P1": [("#E1", 2, 80.0)]}))
INFO = {"level": 12, "league": "Crystal League I", "members": 4}
MEMBERS = member_snapshot(clan_json(BASE_MEMBERS))
SAMPLE_GOAL = {"kind": "trophies", "hero": None, "target": 5500, "value": 5400,
               "picks": [{"kind": "trophies", "hero": None, "target": 5500},
                         {"kind": "trophies", "hero": None, "target": 6000},
                         {"kind": "hero", "hero": "Barbarian King", "target": 45}]}
SEATS = {"777": {"tag": "#P1", "name": "Mario", "level": "manager", "lang": "it",
                 "avail": "in", "goal": SAMPLE_GOAL},
         "888": {"tag": "#P3", "name": "Peach", "level": None, "lang": "en", "avail": None}}
SECTIONS = {"wars": ["10:00 · <b>Mario</b> ➜ #1"], "members": []}
PROFILES = {"777": {"name": "Mario", "tag": "#P1", "th": 16, "league": "Crystal League I",
                    "trophies": 5400, "best": 5600, "stars": 900, "heroes": "👑40",
                    "donations": 1200, "pref": "in"}}


SAMPLE_RECORD = {"wars": 30, "wins": 18}
SAMPLE_GROWTH = {"days": ["2026-09-20", "2026-09-21", "2026-09-22"],
                 "players": {"#P1": {"trophies": [5300, 5350, 5400], "th": [16, 16, 16]},
                             "#P2": {"trophies": [5000, None, 5100], "th": [15, 15, 15]}},
                 "clan": {"trophies": [10300, 10350, 10500]},
                 "period": {"week": {"#P1": {"donated": 300, "war_stars": 12, "levels": 2,
                                             "score": 40},
                                     "#P2": {"donated": 200, "war_stars": 9, "levels": 1,
                                             "score": 30}},
                            "month": {"#P1": {"donated": 900, "war_stars": 40, "levels": 6,
                                              "score": 120},
                                      "#P2": {"donated": 700, "war_stars": 30, "levels": 4,
                                              "score": 90},
                                      "#P3": {"donated": 400, "war_stars": 20, "levels": 3,
                                              "score": 60}}}}
SAMPLE_MEDALS = {"#P1": [{"badge": "th", "ts": 1789000000}]}
SAMPLE_ADVICE = {"14": {"avg_stars": 1.75,
                        "best": [{"name": "Mario", "stars": 3.0, "count": 2},
                                 {"name": "Luigi", "stars": 1.5, "count": 2}]}}
SAMPLE_VIDEOS = {"14": [{"video_id": "vid1", "title": "TH14 anti tre stelle",
                         "channel": "UCcanale"}]}
SAMPLE_EVENTS = [{"pack": "members", "kind": "join", "who": "Toad", "n": 13,
                  "at": 1788900000},
                 {"pack": "members", "kind": "leave", "who": "Wario", "n": None,
                  "at": 1788950000},
                 {"pack": "wars", "kind": "war_end", "who": "Clan Nemico", "n": 3,
                  "at": 1788990000}]
SAMPLE_IDLE = [{"tag": "#P4", "name": "Toad", "days": 5}]
SAMPLE_RECAP = {"season": "2026-08",
                "players": [{"tag": "#P1", "name": "Mario", "score": 120, "wins": 40,
                             "war_stars": 30, "donated": 900, "levels": 6},
                            {"tag": "#P2", "name": "Luigi", "score": 90, "wins": 30,
                             "war_stars": 20, "donated": 700, "levels": 4}],
                "medals": {"#P1": ["th", "quiz"]}}
SAMPLE_CLANS = [{"slug": SLUG, "name": "Nostro Clan"}, {"slug": OTHER, "name": "Altro Clan"}]
SAMPLE_WARS = [{"them": "Clan Nemico", "us_stars": 30, "them_stars": 28, "us_destr": 91.5,
                "them_destr": 88.0, "result": "win", "ended": 1788990000},
               {"them": "Altro Clan", "us_stars": 24, "them_stars": 27, "us_destr": 80.0,
                "them_destr": 84.25, "result": "lose", "ended": 1788900000}]


def regole(testo):
    pulito = testo.replace("\n", "")
    return dict(blocco.split("{", 1) for blocco in pulito.split("}") if "{" in blocco)


def body(plan=None, seats=None, sections=None, profiles=None, war=WAR, info=INFO, record=None,
         growth=None, medals=None):
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome"})
    return payload.app_payload(
        CLAN, conf, info, MEMBERS, war, "war", None, plan or {},
        SEATS if seats is None else seats, SECTIONS if sections is None else sections,
        PROFILES if profiles is None else profiles, NOW, record=record, growth=growth,
        medals=medals)


class AppStore(PageStore):
    def __init__(self, pages=None, token=TOKEN, pending=(), links=(), clans=(), vault=None):
        super().__init__(pages)
        self.token = token
        self.intents = []
        self.pending = set(pending)
        self.kv = {}
        self.links = list(links)
        self.clans = {clan.alias: clan for clan in clans}
        self.vault = vault

    async def links_by_user(self, user_id):
        return [one for one in self.links if one.user_id == user_id]

    async def clan_by_alias(self, alias):
        return self.clans.get(alias)

    async def get_secret(self, kind):
        return self.token if kind == "console_token" else None

    async def kv_get(self, key):
        return self.kv.get(key)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj

    async def kv_del(self, key):
        self.kv.pop(key, None)

    async def web_app_alias(self, slug):
        return CLAN.alias if (slug, payload.APP) in self.pages else None

    async def web_intent_for(self, slug, kind, body):
        self.intents.append((slug, kind, body))
        return len(self.intents)

    async def web_intent_pending(self, intent_id):
        return intent_id in self.pending


def init(uid=777, at=None, code=SLUG, token=TOKEN, name="Mario"):
    fields = {"auth_date": str(int(time.time()) if at is None else at),
              "user": json.dumps({"id": uid, "first_name": name}, separators=(",", ":"))}
    if code:
        fields["start_param"] = code
    return signed(fields, token=token)


def serve(store, path, method="GET", uid=777, data=None, code=SLUG, token=TOKEN, name="Mario"):
    headers = b""
    if uid:
        headers += f"X-Init-Data: {init(uid, code=code, token=token, name=name)}\r\n".encode()
    if data is not None:
        headers += b"Content-Type: application/json\r\n"
    req = request(path, method, headers=headers)
    if data is not None:
        req.body = json.dumps(data).encode()
    site = web_app.Site(store)
    return asyncio.run(site.router(req))


def looked(store, slug=None, code=SLUG, token=TOKEN):
    req = request("/app", headers=f"X-Init-Data: {init(code=code, token=token)}\r\n".encode())
    return asyncio.run(web_app.Site(store).viewer(req, slug))


def test_the_app_payload_shows_the_board_and_who_can_touch_it():
    found = body({"1": {"tag": "#P2", "name": "Luigi"}})
    assert found["war"]["state"] == "inWar"
    assert found["clan"] == {"name": "Nostro Clan", "level": 12, "badge": None,
                             "league": "Crystal League I", "members": 4, "accent": None}
    assert [row["pos"] for row in found["rows"]] == [1, 2, 3]
    assert found["rows"][0]["best"] == 2 and found["rows"][0]["by"] == ["Mario"]
    assert found["rows"][0]["assignee"] == "Luigi"
    assert [our["left"] for our in found["ours"]] == [1, 2, 2]
    assert [our["tag"] for our in found["ours"]] == ["#P1", "#P2", "#P3"]
    assert found["seats"]["777"]["level"] == "manager"
    assert found["sections"] == SECTIONS and found["profiles"] == PROFILES
    assert [row["name"] for row in found["members"]] == ["Mario", "Luigi", "Peach", "Toad"]
    assert "defenders" not in found and "viewers" not in found


def test_la_pagina_porta_l_ultimo_attacco_di_ogni_villaggio():
    found = body()
    assert found["war"]["last_attacks"] == [{"tag": "#P1", "stars": 2, "destr": 80.0, "at": 1}]
    assert [our["stars"] for our in found["ours"]] == [2, 0, 0]
    assert [our["destr"] for our in found["ours"]] == [80.0, 0.0, 0.0]


def test_di_ogni_villaggio_resta_solo_il_colpo_piu_recente():
    due = war_snapshot(war_json("inWar", {"#P1": [("#E1", 2, 80.0), ("#E2", 3, 100.0)]}))
    found = body(war=due)
    assert found["war"]["last_attacks"] == [{"tag": "#P1", "stars": 3, "destr": 100.0, "at": 2}]
    assert found["ours"][0]["stars"] == 5 and found["ours"][0]["destr"] == 90.0


def test_the_page_carries_the_agenda_the_last_war_and_the_games():
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome"})
    agenda = [{"key": "raid", "start": 10, "end": 20, "state": "upcoming"}]
    last = {"them": "Loro", "us_stars": 30, "them_stars": 28, "us_destr": 90.0,
            "them_destr": 85.5, "result": "win", "ended": 5}
    games = {"duels": [], "quiz": None, "predictions": []}
    found = payload.app_payload(CLAN, conf, INFO, MEMBERS, WAR, "war", None, {}, SEATS, SECTIONS,
                                PROFILES, NOW, agenda=agenda, last_war=last, games=games)
    assert found["agenda"] == agenda and found["last_war"] == last and found["games"] == games
    plain = body()
    assert plain["agenda"] == [] and plain["last_war"] is None and plain["games"] is None


def test_la_striscia_della_lega_arriva_a_tutti_nello_stato():
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome"})
    cwl = {"season": "2026-09", "day": 2,
           "days": [{"n": n, "them": "Clan Due", "us_stars": 0, "them_stars": 0,
                     "result": None, "state": "next"} for n in range(1, 8)],
           "lineup": [{"tag": "#P1", "name": "Mario", "th": 16, "in": True, "attacked": False,
                       "bonus": False}],
           "table": [{"name": "Nostro Clan", "stars": 27, "destr": 170.0, "rank": 1}]}
    found = payload.app_payload(CLAN, conf, INFO, MEMBERS, WAR, "cwl", 2, {}, SEATS, SECTIONS,
                                PROFILES, NOW, cwl=cwl)
    assert found["cwl"] == cwl and body()["cwl"] is None
    out = miniapp.state_body(found, {"uid": 888, **SEATS["888"]}, 0, now=int(NOW.timestamp()))
    assert out["cwl"] == cwl


def test_without_a_war_the_board_is_still_there():
    conf = settings.effective(None)
    empty = payload.app_payload(CLAN, conf, None, {}, {"state": "notInWar"}, "war", None,
                                {}, {}, SECTIONS, {}, NOW)
    assert empty["war"] is None and empty["rows"] == [] and empty["ours"] == []
    assert empty["sections"] == SECTIONS and empty["clan"]["name"] == "Nostro Clan"


def test_member_rows_carry_tag_link_and_availability():
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome"})
    found = payload.app_payload(CLAN, conf, INFO, MEMBERS, WAR, "war", None, {}, SEATS, SECTIONS,
                                PROFILES, NOW, links={"#P1": {"verified": True}},
                                avail={"#P1": "in"})
    mario = next(row for row in found["members"] if row["name"] == "Mario")
    assert mario["tag"] == "#P1" and mario["linked"] is True and mario["verified"] is True
    assert mario["avail"] == "in"
    luigi = next(row for row in found["members"] if row["name"] == "Luigi")
    assert luigi["tag"] == "#P2" and luigi["linked"] is False and luigi["avail"] is None
    assert luigi["verified"] is False


def test_the_public_rows_stay_without_tags():
    assert all("tag" not in row for row in payload.member_rows(MEMBERS))
    assert payload.member_rows(MEMBERS)[0] == {"name": "Mario", "role": "leader", "th": 16,
                                               "trophies": 5400, "donations": 1200,
                                               "received": 300}


def test_the_page_carries_record_growth_and_medals():
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome"})
    growth = {"days": ["2026-09-20", "2026-09-21"],
              "players": {"#P1": {"trophies": [5000, 5100], "th": [16, 16]}},
              "clan": {"trophies": [12000, 12300]},
              "period": {"week": {"#P1": {"donated": 40, "war_stars": 5, "levels": 3,
                                          "score": 9}}}}
    found = payload.app_payload(CLAN, conf, INFO, MEMBERS, WAR, "war", None, {}, SEATS, SECTIONS,
                                PROFILES, NOW,
                                record={"wars": 10, "wins": 7,
                                        "streak": {"current": 2, "best": 5}},
                                growth=growth, medals={"#P1": [{"badge": "th", "ts": 1}]})
    assert found["record"]["wins"] == 7 and found["record"]["streak"]["best"] == 5
    assert found["growth"] == growth
    assert found["medals"]["#P1"][0]["badge"] == "th"


def test_without_them_the_page_keeps_the_places_empty():
    found = body()
    assert found["record"] == {} and found["medals"] == {} and found["growth"] == {}


def test_the_state_never_carries_the_seats_of_the_others():
    out = miniapp.state_body(body(), {"uid": 777, **SEATS["777"]}, 0)
    assert "seats" not in out and "profiles" not in out
    assert out["me"] == dict(SEATS["777"], profile=PROFILES["777"])
    assert out["rows"] == body()["rows"] and out["unread"] == 0


def test_the_state_carries_the_war_of_the_person_and_what_waits_for_her():
    page = dict(body(), agenda=[{"key": "raid", "start": 10, "end": 30, "state": "ongoing"}],
                games={"duels": [], "predictions": [],
                       "quiz": {"open": True, "question": "Q?", "options": ["a", "b"],
                                "answered": ["#P9"]}})
    out = miniapp.state_body(page, {"uid": 777, **SEATS["777"]}, 0, now=20)
    assert "games" not in out and out["last_war"] is None
    assert out["war_view"]["phase"] == "inWar" and out["war_view"]["mine"]["pos"] == 1
    assert out["next"] == {"key": "raid", "start": 10, "end": 30, "state": "ongoing"}
    assert [row["kind"] for row in out["todo"]] == ["quiz", "link"]
    assert "answered" not in out["todo"][0]


def test_without_the_clock_the_state_asks_it():
    out = miniapp.state_body(body(), {"uid": 777, **SEATS["777"]})
    assert out["war_view"]["size"] == 3 and out["next"] is None
    assert out["todo"] == [{"kind": "link"}]


def test_the_state_carries_the_clan_list_and_my_corner():
    conf = settings.effective({"lang": "it", "tz": "Europe/Rome"})
    growth = {"days": ["2026-09-20", "2026-09-21"],
              "players": {"#P1": {"trophies": [5000, 5100], "th": [16, 16]}},
              "clan": {"trophies": [12000, 12300]},
              "period": {"week": {"#P1": {"donated": 40, "war_stars": 5, "levels": 3,
                                          "score": 9}}}}
    page = payload.app_payload(CLAN, conf, INFO, MEMBERS, WAR, "war", None, {}, SEATS, SECTIONS,
                               PROFILES, NOW, record={"wars": 10, "wins": 7}, growth=growth,
                               medals={"#P1": [{"badge": "th", "ts": 1}]})
    seat = {"uid": 777, **SEATS["777"], "verified": True, "whisper": False}
    out = miniapp.state_body(page, seat, 0)
    assert out["people"]["record"]["wins"] == 7
    assert [row["name"] for row in out["people"]["rows"]] == [row["name"]
                                                              for row in page["members"]]
    assert out["people"]["rows"][0]["absent_days"] == 0 and out["people"]["rows"][0]["ratio"] == 4.0
    assert out["people"]["climb"]["week"][0]["name"] == "Mario"
    assert out["me_view"]["growth"]["trophies"] == [5000, 5100]
    assert out["me_view"]["medals"][0]["badge"] == "th"
    assert out["me_view"]["period"]["levels"] == 3
    assert out["me_view"]["villages"] == [{"tag": "#P1", "name": "Mario", "verified": True}]
    assert out["me_view"]["profile"] == PROFILES["777"]
    assert "888" not in json.dumps(out["me_view"], ensure_ascii=False)


def manager_page(plan=None):
    return dict(body(plan), **{payload.MANAGE: {"777": {"settings": None,
                                                        acts.STAFF: MANAGE_STAFF}},
                               payload.TOOLS: MANAGE_TOOLS})


def sample_page(seats=None):
    return dict(body({"1": {"tag": "#P2", "name": "Luigi", "note": "regine prima"}},
                     seats=seats, record=SAMPLE_RECORD, growth=SAMPLE_GROWTH,
                     medals=SAMPLE_MEDALS),
                agenda=[{"key": "raid", "start": 10, "end": 30, "state": "ongoing"}],
                advice=SAMPLE_ADVICE, attack_videos=SAMPLE_VIDEOS,
                games={"duels": [], "predictions": [],
                       "quiz": {"open": True, "question": "Q?", "options": ["a", "b"],
                                "answered": ["#P9"]}},
                events=SAMPLE_EVENTS, idle=SAMPLE_IDLE, recap=SAMPLE_RECAP,
                wars=SAMPLE_WARS, last_war=SAMPLE_WARS[0],
                **{payload.MANAGE: {"777": {"settings": None, acts.STAFF: MANAGE_STAFF}},
                   payload.TOOLS: MANAGE_TOOLS})


def test_the_sample_state_is_written_for_the_js_tests():
    page = sample_page()
    found = miniapp.state_body(page, {"uid": 777, **SEATS["777"]}, 0, NOW.timestamp(),
                               clans=SAMPLE_CLANS)
    path = Path(__file__).parent / "js" / "state.json"
    path.write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert path.stat().st_size > 100
    assert found["me"]["name"] and found["clan"]["name"] and found["members"]
    assert found["war_view"]["phase"] == "inWar"
    assert [row["kind"] for row in found["todo"]] == ["quiz", "link"]
    assert found["people"]["record"]["wins"] and found["people"]["climb"]["week"]
    assert [row["kind"] for row in found["people"]["chronicle"]] == ["war_end", "leave", "join"]
    assert len(found["people"]["climb"]["week"]) == 2 and len(found["people"]["climb"]["month"]) == 3
    assert [row["absent_days"] for row in found["people"]["rows"]] == [0, 0, 0, 5]
    assert found["growth"]["clan"]["trophies"] and found["medals"]
    assert found["inbox"]["pending"] and found["manage_view"]["packs"]
    assert found["manage_view"]["approved"] and "claims" not in found["inbox"]
    assert found["me_view"]["goal"] == SAMPLE_GOAL and found["me_view"]["lang"] == "it"
    assert "candidates" not in found["me_view"]
    assert found["advice"] == SAMPLE_ADVICE and found["attack_videos"] == SAMPLE_VIDEOS
    assert found["war_view"]["enemy"][0]["note"] == "regine prima"
    assert found["war_view"]["enemy"][0]["history"][0]["name"] == "Mario"
    assert found["clans"] == SAMPLE_CLANS
    assert found["recap"]["me"]["rank"] == 1 and found["recap"]["clan"]["people"] == 2
    assert found["recap"]["me"]["medals"] == ["th", "quiz"]
    assert found["wars"] == SAMPLE_WARS and found["last_war"] == SAMPLE_WARS[0]


def test_la_casella_e_lo_stato_arrivano_solo_a_chi_ha_gli_strumenti():
    page = manager_page()
    mine = miniapp.state_body(page, {"uid": 777, **SEATS["777"]})
    assert mine["inbox"] == app_manage.inbox_for(page, {"uid": 777}, MANAGE_TOOLS)
    assert mine["manage_view"]["chief"] is True and mine["manage_view"]["page_on"] is False
    assert mine["manage_view"]["packs"] == {pack: pack in SECTIONS
                                            for pack in boards.SECTION_ORDER}
    plain = miniapp.state_body(page, {"uid": 888, **SEATS["888"]})
    assert "inbox" not in plain and "manage_view" not in plain
    assert "segreto" not in str(plain) and "segreto" not in str(mine["inbox"])


def test_la_casella_dell_anziano_porta_solo_quello_che_puo_decidere():
    page = manager_page()
    elder = miniapp.state_body(page, {"uid": 888, "tag": "#P3", "level": settings.LIMITED})
    assert elder["inbox"] == {"pending": [], "applications": [], "reports": [], "bases": [],
                              "warnings": MANAGE_TOOLS["wars"]["proposals"]}
    assert elder["manage_view"]["channels"] == [] and elder["manage_view"]["texts"] == {}


def test_lo_stato_di_chi_non_gestisce_non_porta_i_posti_altrui():
    page = manager_page()
    altrui = [row["who"] for row in MANAGE_STAFF["delegates"] + MANAGE_STAFF["people"]
              + MANAGE_STAFF["suspended"] + MANAGE_STAFF["pending"] + MANAGE_STAFF["approved"]]
    assert len(altrui) == 5 and all(isinstance(one, str) and one for one in altrui)
    for seat in ({"uid": 888, **SEATS["888"]},
                 {"uid": 888, "tag": "#P3", "level": settings.LIMITED}):
        found = json.dumps(miniapp.state_body(page, seat), ensure_ascii=False)
        assert '"uid"' not in found
        for one in altrui:
            assert one not in found
    mine = json.dumps(miniapp.state_body(page, {"uid": 777, **SEATS["777"]}), ensure_ascii=False)
    assert '"uid"' not in mine and all(one in mine for one in altrui)


BASE_LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16%3AHV%3AAaBbCcDd"
BASES = {"clan": [{"alias": "base-1", "label": "war", "village": "home", "hall": 16,
                   "link": BASE_LINK, "by": "Mario"}],
         "library": {"halls": [16, 15, 14], "rows": [], "videos": []}}
RECRUIT = {"open": True, "free": 46, "requirement": 14, "page_on": False, "code": "abc123"}
FAMILY = {"name": "Nostra Famiglia", "code": "fam-1",
          "clans": [{"name": "Secondo Clan", "code": "def456"}]}
LINKS = {"console": "ClanBoardBot", "base": "https://esempio.test",
         "community": "https://t.me/clanboard", "support": "https://esempio.test/sostegno",
         "creator": "CLANBOARD", "source": "https://esempio.test/codice",
         "thanks": "https://esempio.test/grazie", "checklist": "https://esempio.test/lista"}


class HelpStore(AppStore):
    async def get_secret(self, kind):
        return self.secrets.get(kind) or await super().get_secret(kind)


def test_the_app_payload_carries_bases_recruitment_and_family():
    found = payload.app_payload(
        CLAN, settings.effective({"lang": "it"}), INFO, MEMBERS, WAR, "war", None, {}, SEATS,
        SECTIONS, PROFILES, NOW, bases=BASES, recruit=RECRUIT, family=FAMILY)
    assert found["bases"] == BASES and found["recruit"] == RECRUIT and found["family"] == FAMILY
    plain = body()
    assert plain["bases"] == {} and plain["recruit"] == {} and plain["family"] is None


def test_the_state_carries_only_the_four_help_links_of_the_site():
    seat = {"uid": 777, **SEATS["777"]}
    out = miniapp.state_body(body(), seat, 0, help=LINKS)
    assert out["help"] == {"support": "https://esempio.test/sostegno", "creator": "CLANBOARD",
                           "community": "https://t.me/clanboard",
                           "source": "https://esempio.test/codice"}
    assert miniapp.state_body(body(), seat)["help"] == {"support": "", "creator": "",
                                                        "community": "", "source": ""}


def test_lo_stato_servito_porta_l_aiuto_letto_dal_sito():
    store = HelpStore({(SLUG, payload.APP): body()})
    store.secrets = {"channel_url": "https://t.me/clanboard", "creator_code": "CLANBOARD",
                     "support_url": "https://esempio.test/sostegno",
                     source.SECRET: "https://esempio.test/codice"}
    found = json.loads(serve(store, f"/app/{SLUG}/state").body)
    assert found["help"] == {"support": "https://esempio.test/sostegno", "creator": "CLANBOARD",
                             "community": "https://t.me/clanboard",
                             "source": "https://esempio.test/codice"}
    acted = serve(store, f"/app/{SLUG}/act", "POST",
                  data={"kind": "target.mirror", "id": "ab12"})
    assert json.loads(acted.body)["help"]["creator"] == "CLANBOARD"


def test_only_known_gestures_become_intents():
    assert miniapp.intent({"kind": "target.set", "pos": "3", "who": "1", "id": "ab12"},
                          "#P1", 777) == {"kind": "target.set", "pos": "3", "who": "1",
                                          "by": 777, "tag": "#P1", "id": "ab12"}
    assert miniapp.intent({"kind": "target.clear", "id": "ab12"}, "#P1", 777) == {
        "kind": "target.clear", "by": 777, "tag": "#P1", "id": "ab12"}
    for bad in ({"kind": "pinco", "id": "ab12"}, {}, {"kind": "target.clear"},
                {"kind": "target.set", "pos": "x", "who": "1", "id": "ab12"},
                {"kind": "target.set", "pos": "3", "id": "ab12"},
                {"kind": "target.free", "pos": "", "id": "ab12"},
                {"kind": "target.clear", "id": "ab 12"},
                {"kind": "target.clear", "id": "a" * 99}):
        assert miniapp.intent(bad, "#P1", 777) is None


def test_ogni_gesto_del_membro_ha_la_sua_forma():
    good = {"availability.set": {"choice": "out"},
            "goal.set": {"goal": "trophies", "target": "4500", "hero": ""},
            "quiz.answer": {"option": "2"},
            "guess.answer": {"stars": "3", "percent": "40"},
            "duel.challenge": {"rival": "#P1", "metric": "donated", "duration": "week"},
            "duel.accept": {"duel": "ab12cd34"},
            "award.vote": {"option": "1"},
            "prediction.set": {"poll": "war", "option": "0"},
            "report.send": {"reason": "scam"},
            "target.mirror": {},
            "link.verify": {"village": "#P2", "token": "abc123"},
            "link.whisper": {"village": "#P2", "on": "on"},
            "link.drop": {"village": "#P2"},
            "data.forget": {"sure": "yes"},
            "share.week": {},
            "share.season": {},
            "share.war": {},
            "lang.set": {"lang": "en"},
            "app.opened": {},
            "base.propose": {"link": BASE_LINK, "label": "war"}}
    assert set(good) | set(acts.TARGET_KINDS) == set(intents.KINDS_MEMBER)
    assert miniapp.manager_only("target.clear") is True
    for kind, fields in good.items():
        found = miniapp.intent(dict(fields, kind=kind, id="ab12"), "#P1", 777)
        assert found and found["kind"] == kind and found["by"] == 777
        assert all(found[name] == value for name, value in fields.items())
        assert miniapp.manager_only(kind) is False
    for bad in ({"kind": "report.send", "reason": "pinco"},
                {"kind": "availability.set", "choice": ""},
                {"kind": "goal.set", "goal": "trophies", "target": "x", "hero": ""},
                {"kind": "quiz.answer", "option": "-1"},
                {"kind": "duel.challenge", "rival": "P1", "metric": "donated",
                 "duration": "week"},
                {"kind": "lang.set", "lang": "klingon"},
                {"kind": "base.propose", "link": "https://esempio.test", "label": "war"},
                {"kind": "base.propose", "link": BASE_LINK, "label": "pinco"}):
        assert miniapp.intent(dict(bad, id="ab12"), "#P1", 777) is None


def test_the_page_is_served_with_telegram_allowed_and_nothing_else():
    res = serve(AppStore({(SLUG, payload.APP): body()}), f"/app/{SLUG}")
    assert res.status == 200
    csp = res.headers["Content-Security-Policy"]
    assert "script-src 'self' https://telegram.org" in csp
    assert "frame-ancestors https://web.telegram.org https://telegram.org" in csp
    assert "connect-src 'self'" in csp
    assert res.headers["Cache-Control"] == "no-store"
    text = res.body.decode()
    assert '<script src="https://telegram.org/js/telegram-web-app.js" defer></script>' in text
    assert 'data-live="/app/%s/live"' % SLUG in text
    assert static.url_for("app/main.js") in text and 'type="module"' in text
    assert "/app.js" not in text and "telegram-web-app.js" in text
    assert "data-conf=" in text and "TOKEN_MAX" in text
    assert text.index("</script>") < text.index('id="app"')
    assert "#P1" not in text and "Mario" not in text


def test_the_old_script_route_is_gone():
    assert serve(AppStore(), "/app.js").status == 404


def test_the_app_ships_every_module_as_a_static_file():
    found = static.manifest()["files"]
    for name in ("main", "theme", "live", "model", "ui", "screens"):
        assert f"app/{name}.js" in found
    assert len(static.read("app/main.js")) > 0


def test_the_page_declares_every_module_before_the_scripts():
    res = serve(AppStore({(SLUG, payload.APP): body()}), f"/app/{SLUG}")
    text = res.body.decode()
    names = static.app_modules()
    assert "app/main.js" in names and "app/ui.js" in names
    for name in names:
        assert f'<link rel="modulepreload" href="{static.url_for(name)}">' in text, name
    assert text.count("modulepreload") == len(names)
    assert text.rindex("modulepreload") < text.index('<script')


def test_the_page_starts_the_state_and_the_channel_before_the_modules():
    res = serve(AppStore({(SLUG, payload.APP): body()}), f"/app/{SLUG}")
    text = res.body.decode()
    boot = static.url_for(static.BOOT)
    assert f'<script src="{boot}" defer></script>' in text
    assert f'<link rel="modulepreload" href="{boot}">' not in text
    assert text.index(f'<script src="{boot}"') < text.index('<script type="module"')
    assert text.index("telegram-web-app.js") < text.index(f'<script src="{boot}"')


def test_no_module_of_the_app_writes_raw_html():
    for name in static.manifest()["files"]:
        if not name.startswith("app/"):
            continue
        source = static.read(name).decode()
        assert "innerHTML" not in source and "dangerouslySetInnerHTML" not in source, name
        assert len(source.splitlines()) <= 400, name


def test_the_state_wants_a_real_signature():
    store = AppStore({(SLUG, payload.APP): body()})
    assert serve(store, f"/app/{SLUG}/state").status == 200
    assert serve(store, f"/app/{SLUG}/state", uid=0).status == 401
    assert serve(store, f"/app/{SLUG}/state", uid=888).status == 200
    assert serve(AppStore(), f"/app/{SLUG}/state").status == 404


def test_the_app_knows_who_opens_it_from_the_console_and_the_clan_from_the_code():
    store = AppStore({(SLUG, payload.APP): body()})
    page, seat = looked(store)
    assert page["clan"]["name"] == "Nostro Clan"
    assert seat == {"uid": 777, "who": "Mario", payload.MARK: None, **SEATS["777"]}
    assert looked(store, slug=SLUG, code="") == (page, seat)


def test_only_the_signature_of_the_console_opens_the_app():
    store = AppStore({(SLUG, payload.APP): body()})
    assert looked(store, token="43:bot-del-clan") == (None, None)
    assert serve(store, f"/app/{SLUG}/state", token="43:bot-del-clan").status == 401


def test_a_code_of_a_clan_that_is_not_there_finds_nothing():
    assert looked(AppStore()) == (None, None)
    assert looked(AppStore({(SLUG, payload.APP): body()}), code="") == (None, None)


def test_the_code_in_the_address_cannot_change_clan():
    store = AppStore({(SLUG, payload.APP): body(), (OTHER, payload.APP): body()})
    assert looked(store, slug=OTHER) == (None, None)
    assert serve(store, f"/app/{OTHER}/state").status == 404


def test_chi_non_ha_il_villaggio_vede_solo_nome_stemma_e_requisiti():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/state", uid=999)
    found = json.loads(res.body)
    assert res.status == 200 and found["me"] == {"level": None}
    assert found["level"] == miniapp.OUTSIDER
    assert found["clan"]["name"] == "Nostro Clan" and found["war_view"] is None
    assert [row["kind"] for row in found["todo"]] == ["link"]
    for key in ("sections", "members", "cwl", "war", "rows", "ours"):
        assert key not in found, key
    assert found["people"]["rows"] == [] and found["unread"] == 0
    assert "#P1" not in str(found) and "Mario" not in str(found)
    mine = json.loads(serve(store, f"/app/{SLUG}/state").body)
    assert mine["sections"] == SECTIONS and mine["members"]
    assert mine["level"] == miniapp.BOSS
    assert serve(store, f"/app/{SLUG}/feed", uid=999).status == 401
    denied = serve(store, f"/app/{SLUG}/act", "POST", uid=999,
                   data={"kind": "target.mirror", "id": "ab12"})
    assert denied.status == 403 and store.intents == []
    quiet = serve(store, f"/app/{SLUG}/act", "POST", uid=999,
                  data={"kind": "availability.set", "choice": "in", "id": "ab13"})
    assert quiet.status == 403 and store.intents == []


def test_the_state_carries_the_sections_and_the_profile_of_who_asks():
    store = AppStore({(SLUG, payload.APP): body()})
    found = json.loads(serve(store, f"/app/{SLUG}/state").body)
    assert found["sections"] == SECTIONS
    assert found["me"]["tag"] == "#P1" and found["me"]["level"] == "manager"
    assert found["me"]["profile"] == PROFILES["777"] and found["unread"] == 0
    other = json.loads(serve(store, f"/app/{SLUG}/state", uid=888).body)
    assert "profile" not in other["me"] and other["me"]["level"] is None


def test_the_news_are_given_once_and_then_they_are_read():
    store = AppStore({(SLUG, payload.APP): body()})
    asyncio.run(feed.add(store, CLAN.alias, 777, "goal.done", "Obiettivo raggiunto", NOW))
    assert json.loads(serve(store, f"/app/{SLUG}/state").body)["unread"] == 1
    res = serve(store, f"/app/{SLUG}/feed")
    assert res.status == 200
    assert [row["text"] for row in json.loads(res.body)["rows"]] == ["Obiettivo raggiunto"]
    assert json.loads(serve(store, f"/app/{SLUG}/state").body)["unread"] == 0


def test_the_app_has_the_four_tabs_and_the_manage_one():
    found = miniapp.words(i18n.locale("it"))
    assert miniapp.TABS == ("war", "clan", "me", "more")
    assert found["tab_war"] == "Guerra" and found["tab_clan"] == "Clan"
    assert found["tab_me"] == "Il mio" and found["tab_more"] == "Altro"
    assert all(f"tab_{name}" in found for name in miniapp.TABS)
    assert found["pack_wars"] == i18n.locale("it").t("board.title.wars")
    assert found["empty"] == i18n.locale("it").t("board.all.empty")
    english = miniapp.words(i18n.locale("en"))
    assert english["tab_clan"] == "Clan" and english["tab_more"] == "More"
    for name in ("tab_manage", "live_off", "empty_screen"):
        assert found[name] and not found[name].startswith("["), name
        assert english[name] and not english[name].startswith("["), name


def test_the_number_of_the_target_comes_from_the_catalogue():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        assert found["pos"] == L.t("target.hint_pos")
        assert "{pos}" in found["pos"] and not found["pos"].startswith("[")


def test_la_scheda_gestione_si_vede_solo_a_chi_gestisce():
    L = i18n.locale("it")
    found = miniapp.words(L)
    assert found["tab_manage"] == L.t("web.app.tab.manage")
    assert found["manage_restart"] == L.t("web.app.manage.restart")
    assert not found["tab_manage"].startswith("[")
    assert miniapp.words(i18n.locale("en"))["tab_manage"] == "Manage"
    assert "manage" not in miniapp.TABS


def test_ogni_parola_della_gestione_arriva_dal_catalogo():
    for code in ("it", "en"):
        found = miniapp.words(i18n.locale(code))
        for name in miniapp.MANAGE_WORDS:
            assert found["manage_" + name] and not found["manage_" + name].startswith("["), name
        for pack in miniapp.MANAGE_PACKS:
            assert found["pack_" + pack] and not found["pack_" + pack].startswith("["), pack


def test_la_scheda_gestione_ha_una_parola_per_ogni_sua_sezione():
    nomi = ("inbox", "applications", "reports", "warnings", "approve", "reject", "accept",
            "void", "seen", "packs", "schedules", "undo", "suspended", "texts", "welcome",
            "rules", "channels", "sure", "settings")
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in nomi:
            assert miniapp.MANAGE_WORDS[name] == "web.app.manage." + name, name
            assert found["manage_" + name] == L.t("web.app.manage." + name), name
            assert not found["manage_" + name].startswith("["), name
        assert found["manage_sched_every"] == L.t("leaders.schedule.every_day")
        for day in acts.WEEKDAYS:
            assert found["weekday_" + day] == L.t("weekday." + day)
            assert not found["weekday_" + day].startswith("["), day
    assert len(set(miniapp.words(i18n.locale("it"))[f"manage_{name}"] for name in nomi)) == len(nomi)


def test_la_pagina_consegna_al_javascript_i_giorni_della_settimana():
    assert miniapp.CONF["WEEKDAYS"] == list(acts.WEEKDAYS)
    assert json.loads(json.dumps(miniapp.CONF))["WEEKDAYS"] == list(acts.WEEKDAYS)


def test_il_foglio_della_gestione_ha_il_suo_campo_nello_stile():
    assert ".field{" in FOGLIO


def test_la_pagina_consegna_al_javascript_le_costanti_della_gestione():
    conf = miniapp.CONF
    assert conf["AREAS"] == list(miniapp.AREAS) and conf["MANAGE"] == list(miniapp.MANAGE_PACKS)
    assert conf["STAFF"] == acts.STAFF and conf["SHEETS"] == list(miniapp.SHEET_KINDS)
    assert conf["SIDES"] == [miniapp.IN, miniapp.OUT]
    assert conf["SWITCH"] == list(miniapp.SWITCH) and conf["DECIDED"] == list(miniapp.DECIDED)
    assert conf["TOKEN_MAX"] == acts.FIELD_MAX and conf["TEXT_MAX"] == miniapp.TEXT_MAX
    assert conf["NOTE_MAX"] == miniapp.NOTE_MAX
    assert json.loads(json.dumps(conf)) == conf


def test_l_area_del_capo_si_apre_solo_a_chi_ha_il_suo_riquadro():
    L = i18n.locale("it")
    found = miniapp.words(L)
    assert miniapp.AREAS[-1] == acts.STAFF
    assert found["manage_staff"] == L.t("web.app.manage.staff")
    assert found["manage_delegates"] == L.t("setup.delegates.label")
    assert found["manage_seats"] == L.t("panel.seats.title")
    assert found["manage_log"] == L.t("leaders.log.title")
    page = dict(body(), **{payload.MANAGE: {"777": {"settings": None, acts.STAFF: {"log": []}}}})
    mine = miniapp.state_body(page, {"uid": 777, **SEATS["777"]})
    assert mine["me"][payload.MANAGE][acts.STAFF] == {"log": []}
    assert payload.MANAGE not in miniapp.state_body(page, {"uid": 888, **SEATS["888"]})["me"]


def test_il_riquadro_ridotto_porta_chi_aspetta_il_si_a_chi_gestisce_poco():
    attesa = [{"who": "9a0b1c2d3e4f5061", "name": "Peach", "tag": "#P3"}]
    page = dict(body(), **{payload.MANAGE: {
        "777": {"settings": None, acts.STAFF: {"log": [], "pending": attesa}},
        "888": {acts.STAFF: {"pending": attesa}}}})
    elder = miniapp.state_body(page, {"uid": 888, "tag": "#P3", "level": settings.LIMITED})
    assert elder["me"][payload.MANAGE] == {acts.STAFF: {"pending": attesa}}
    assert "settings" not in elder["me"][payload.MANAGE]
    plain = miniapp.state_body(page, {"uid": 111, "tag": "#P4", "level": None})
    assert payload.MANAGE not in plain["me"]


def test_il_gesto_di_un_gestore_limitato_si_ferma_gia_alla_porta():
    page = body()
    elder = {"uid": 888, "tag": "#P3", "level": settings.LIMITED}
    manager = {"uid": 777, "tag": "#P1", "level": settings.MANAGER}
    for kind in acts.KINDS_MANAGER:
        wanted = acts.LEVELS[kind] == settings.LIMITED
        assert miniapp.may(kind, elder, page) is wanted, kind
        assert miniapp.may(kind, manager, page) is True, kind
        assert miniapp.may(kind, {"uid": 999, "tag": "#P4", "level": None}, page) is False, kind
    plain = {"uid": 999, "tag": "#P4", "level": None}
    for kind in acts.TARGET_KINDS:
        assert miniapp.may(kind, elder, page) is True, kind
    for kind in acts.TARGET_OWN:
        assert miniapp.may(kind, plain, page) is True, kind
    assert miniapp.may("target.clear", plain, page) is False
    assert miniapp.may("target.set", {"uid": 999, "level": None}, page) is False


def chief_page(undo=True):
    return dict(body(), **{payload.MANAGE: {
        "777": {"settings": None, acts.STAFF: {"log": [], "undo": undo}}}})


def test_i_gesti_del_capo_si_fermano_alla_porta_per_chi_capo_non_e():
    manager = {"uid": 777, **SEATS["777"]}
    assert acts.CHIEF_KINDS == ("delegates.clear", "warning.void", "clan.pause", "clan.resume",
                                "undo.apply", "suspension.lift")
    for kind in acts.CHIEF_KINDS:
        assert miniapp.why(chief_page(), manager, kind) is None, kind
        assert miniapp.why(chief_page(False), manager, kind) == miniapp.CHIEF_ONLY, kind
        assert miniapp.why(body(), manager, kind) == miniapp.CHIEF_ONLY, kind
    for kind in ("settings.press", "note.set", "delegate.add", "person.approve"):
        assert miniapp.why(chief_page(False), manager, kind) is None, kind
    assert miniapp.why(chief_page(), {"uid": 888, **SEATS["888"]},
                       "clan.pause") == reasons.NOT_MANAGER
    assert miniapp.why(chief_page(), {"uid": 999}, "goal.set") == reasons.NOT_LINKED


def test_il_gesto_del_capo_chiesto_da_un_altro_torna_col_suo_motivo():
    store = AppStore({(SLUG, payload.APP): chief_page(False)})
    res = serve(store, f"/app/{SLUG}/act", "POST",
                data={"kind": "clan.pause", "id": "ab12"})
    assert res.status == 403 and store.intents == []
    assert json.loads(res.body) == {"error": miniapp.CHIEF_ONLY}
    aperto = AppStore({(SLUG, payload.APP): chief_page()})
    assert serve(aperto, f"/app/{SLUG}/act", "POST",
                 data={"kind": "clan.pause", "id": "ab13"}).status == 200
    L = i18n.locale("it")
    assert miniapp.words(L)["denied_" + miniapp.CHIEF_ONLY] == L.t("web.app.denied_chief")
    assert not miniapp.words(L)["denied_" + miniapp.CHIEF_ONLY].startswith("[")
    assert miniapp.words(i18n.locale("en"))["denied_" + miniapp.CHIEF_ONLY].startswith("Only")


def test_gli_strumenti_arrivano_solo_a_chi_ha_il_posto_giusto():
    tools = {"wars": {"proposals": [], "warnings": []},
             "leaders": {"notes": [{"tag": "#P1", "name": "Mario", "text": "segreto"}]}}
    page = dict(body(), **{payload.TOOLS: tools})
    manager = miniapp.state_body(page, {"uid": 777, **SEATS["777"]})
    assert manager["me"][payload.TOOLS] == tools and payload.TOOLS not in manager
    elder = miniapp.state_body(page, {"uid": 888, "tag": "#P3", "level": settings.LIMITED})
    assert set(elder["me"][payload.TOOLS]) == set(miniapp.LIMITED_PACKS)
    assert "segreto" not in str(elder)
    plain = miniapp.state_body(page, {"uid": 888, **SEATS["888"]})
    assert payload.TOOLS not in plain["me"] and "segreto" not in str(plain)


def test_nello_stato_di_una_persona_non_entra_l_uid_di_nessuno():
    page = dict(chief_page(), **{payload.TOOLS: {"wars": {"proposals": [{"tag": "#P3"}]}},
                                 "medals": SAMPLE_MEDALS, "growth": SAMPLE_GROWTH})
    for uid in (777, 888):
        seat = {"uid": uid, **SEATS[str(uid)]}
        found = miniapp.state_body(page, seat, 0)
        assert found["me"]["tag"] == seat["tag"] and found["me_view"]["tag"] == seat["tag"]
        outside = {key: value for key, value in found.items() if key != "me"}
        assert "uid" not in json.dumps(outside, ensure_ascii=False)
        whole = json.dumps(found, ensure_ascii=False)
        assert "uid" not in whole
        for who in SEATS:
            assert who not in whole, who


def test_l_esportazione_pronta_si_scarica_solo_da_chi_gestisce():
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[exports.ready_key(CLAN.alias, 777)] = {"sheet": "members", "at": 1789000000,
                                                    "text": "tag,name\n#P1,Mario\n"}
    res = serve(store, f"/app/{SLUG}/export.csv")
    assert res.status == 200 and res.kind == web_app.http.SHEET
    assert res.headers["Content-Disposition"].endswith('filename="members-1789000000.csv"')
    assert res.body.decode("utf-8-sig") == "tag,name\n#P1,Mario\n"
    assert res.headers["Cache-Control"] == "no-store"
    assert serve(store, f"/app/{SLUG}/export.csv", uid=888).status == 401
    assert serve(store, f"/app/{SLUG}/export.csv", uid=0).status == 401


def test_l_esportazione_si_scarica_dal_link_che_porta_la_firma():
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[exports.ready_key(CLAN.alias, 777)] = {"sheet": "members", "at": 1789000000,
                                                    "text": "tag,name\n#P1,Mario\n"}
    firma = quote(init(777), safe="")
    res = serve(store, f"/app/{SLUG}/export.csv?init={firma}", uid=0)
    assert res.status == 200 and res.body.decode("utf-8-sig") == "tag,name\n#P1,Mario\n"
    assert serve(store, f"/app/{SLUG}/export.csv?init=pinco", uid=0).status == 401
    altrui = quote(init(888), safe="")
    assert serve(store, f"/app/{SLUG}/export.csv?init={altrui}", uid=0).status == 401
    assert serve(store, f"/app/{SLUG}/state?init={firma}", uid=0).status == 401


def test_senza_esportazione_pronta_la_pagina_non_inventa_niente():
    store = AppStore({(SLUG, payload.APP): body()})
    assert serve(store, f"/app/{SLUG}/export.csv").status == 404


def test_l_anteprima_del_testo_la_rende_il_bot_e_la_vede_solo_chi_gestisce():
    store = AppStore({(SLUG, payload.APP): manager_page()})
    res = serve(store, f"/app/{SLUG}/preview?kind=welcome")
    assert res.status == 200 and res.headers["Cache-Control"] == "no-store"
    stored = MANAGE_TOOLS["leaders"]["texts"]["welcome"]
    assert json.loads(res.body)["text"] == leader_cards.welcome_card(
        i18n.locale("it"), stored, None, CLAN.name)
    regole = serve(store, f"/app/{SLUG}/preview?kind=rules")
    assert json.loads(regole.body)["text"] == leader_cards.rules_card(
        i18n.locale("it"), MANAGE_TOOLS["leaders"]["texts"]["rules"])
    assert serve(store, f"/app/{SLUG}/preview?kind=welcome", uid=888).status == 401
    assert serve(store, f"/app/{SLUG}/preview?kind=welcome", uid=0).status == 401
    assert serve(store, f"/app/{SLUG}/preview?kind=note").status == 400
    assert serve(AppStore(), f"/app/{SLUG}/preview?kind=welcome").status == 404


def test_l_anteprima_rende_la_bozza_e_non_scrive_niente():
    page = manager_page()
    store = AppStore({(SLUG, payload.APP): page})
    bozza = quote("Ciao {name}, benvenuto in {clan}", safe="")
    res = serve(store, f"/app/{SLUG}/preview?kind=welcome&text={bozza}")
    assert json.loads(res.body)["text"] == leader_cards.welcome_card(
        i18n.locale("it"), "Ciao {name}, benvenuto in {clan}", None, CLAN.name)
    vuota = serve(store, f"/app/{SLUG}/preview?kind=welcome&text=")
    assert MANAGE_TOOLS["leaders"]["texts"]["welcome"] not in json.loads(vuota.body)["text"]
    assert store.intents == [] and store.kv == {}
    assert page[payload.TOOLS]["leaders"]["texts"] == MANAGE_TOOLS["leaders"]["texts"]


def test_the_app_opens_without_the_code_in_the_address():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app?tgWebAppStartParam={SLUG}", uid=0)
    assert res.status == 200 and res.headers["Cache-Control"] == "no-store"
    text = res.body.decode()
    assert 'data-slug=""' in text and "telegram-web-app.js" in text
    assert "Nostro Clan" not in text and "#P1" not in text
    main = static.read("app/main.js").decode()
    assert "initDataUnsafe" in main and "start_param" in main


@pytest.mark.parametrize("uid", [0, 777])
def test_l_app_senza_clan_rimanda_alla_home(uid):
    res = serve(AppStore({(SLUG, payload.APP): body()}), "/app", uid=uid)
    assert res.status == 303 and res.headers["Location"] == "/"
    assert res.headers["Cache-Control"] == "no-store"
    assert res.body in (b"", "")


@pytest.mark.parametrize("coda", [
    "?tgWebAppStartParam=", f"?tgWebAppStartParam={OTHER}", "?tgWebAppStartParam=a%27b%3Cc",
    "?tgWebAppStartParam=..%2Fstate", f"?slug={SLUG}", f"?startapp={SLUG}",
])
def test_l_app_con_un_clan_che_non_c_e_rimanda_alla_home_e_non_mostra_niente(coda):
    res = serve(AppStore({(SLUG, payload.APP): body()}), "/app" + coda, uid=0)
    assert res.status == 303 and res.headers["Location"] == "/"
    assert res.body in (b"", "")


def test_l_app_di_un_clan_si_apre_come_prima():
    res = serve(AppStore({(SLUG, payload.APP): body()}), f"/app/{SLUG}", uid=0)
    assert res.status == 200 and f'data-slug="{SLUG}"' in res.body.decode()
    assert serve(AppStore(), f"/app/{SLUG}", uid=0).status == 404


def test_il_membro_prenota_e_solo_l_azzera_tutto_resta_ai_capi():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/act", "POST", uid=888,
                data={"kind": "target.set", "pos": "3", "who": "1", "id": "ab12"})
    assert res.status == 200 and len(store.intents) == 1
    denied = serve(store, f"/app/{SLUG}/act", "POST", uid=888,
                   data={"kind": "target.clear", "id": "ab13"})
    assert denied.status == 403 and len(store.intents) == 1


def test_il_membro_senza_livello_agisce_lo_stesso_sulle_sue_cose():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/act", "POST", uid=888,
                data={"kind": "availability.set", "choice": "out", "id": "ab12"})
    assert res.status == 200
    slug, kind, sent = store.intents[0]
    assert slug == SLUG and kind == "availability.set"
    assert sent == {"kind": "availability.set", "choice": "out", "by": 888, "tag": "#P3",
                    "id": "ab12"}


def test_a_touch_becomes_an_intent_and_gives_back_the_fresh_state():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/act", "POST",
                data={"kind": "target.set", "pos": "3", "who": "1", "id": "ab12"})
    assert res.status == 200
    slug, kind, sent = store.intents[0]
    assert slug == SLUG and kind == "target.set"
    assert sent == {"kind": "target.set", "pos": "3", "who": "1", "by": 777, "tag": "#P1",
                    "id": "ab12"}
    assert json.loads(res.body)["me"]["level"] == "manager"


def test_a_touch_does_not_wipe_the_counter_of_the_news():
    store = AppStore({(SLUG, payload.APP): body()})
    asyncio.run(feed.add(store, CLAN.alias, 777, "goal.done", "Obiettivo raggiunto", NOW))
    res = serve(store, f"/app/{SLUG}/act", "POST",
                data={"kind": "target.mirror", "id": "ab12"})
    assert res.status == 200 and json.loads(res.body)["unread"] == 1


def test_a_broken_touch_says_so_without_writing():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "pinco", "id": "ab12"})
    assert res.status == 400 and store.intents == []
    bad = serve(store, f"/app/{SLUG}/act", "POST",
                data={"kind": "report.send", "reason": "pinco", "id": "ab12"})
    assert bad.status == 400 and store.intents == []


def test_the_answer_waits_for_the_bot_but_does_not_hang_for_ever(monkeypatch):
    monkeypatch.setattr(web_app, "APP_WAIT", 0.2)
    monkeypatch.setattr(web_app, "APP_STEP", 0.05)

    class Slow(AppStore):
        def __init__(self):
            super().__init__({(SLUG, payload.APP): body()}, pending=(1,))
            self.asked = 0

        async def web_intent_pending(self, intent_id):
            self.asked += 1
            return self.asked < 3

    store = Slow()
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "target.mirror", "id": "ab12"})
    assert res.status == 200 and 2 <= store.asked <= 5


class QueuePool:
    def __init__(self, rows):
        self.rows = list(rows)
        self.sql = []

    async def fetch(self, sql, *args):
        self.sql.append(" ".join(sql.split()))
        taken = [row for row in self.rows if row["taken_at"] is None][:args[0]]
        for row in taken:
            row["taken_at"] = "preso"
        return taken

    async def fetchval(self, sql, *args):
        self.sql.append(" ".join(sql.split()))
        return 1 if any(row["id"] == args[0] for row in self.rows) else None

    async def execute(self, sql, *args):
        self.sql.append(" ".join(sql.split()))
        self.rows = [row for row in self.rows if row["id"] != args[0]]
        return "DELETE 1"


class Queue:
    def __init__(self, rows):
        self.rows = list(rows)
        self.done = []
        self.kv = {}

    async def web_intents_take(self, limit=50):
        taken, self.rows = self.rows, []
        return taken

    async def web_intent_done(self, intent_id):
        self.done.append(intent_id)

    async def kv_set(self, key, obj, ref=None, ttl=None):
        self.kv[key] = obj


def queued(ident):
    return {"id": ident, "clan": CLAN.alias, "kind": "target.clear", "body": {"by": 777}}


def test_the_queue_keeps_the_gesture_until_the_bot_has_really_written_it(tmp_path):
    store = Store(Vault(tmp_path))
    data = store.vault.encrypt_json({"kind": "target.clear", "by": 777},
                                    f"web:intent:{CLAN.alias}")
    store.pool = QueuePool([{"id": 4, "clan_alias": CLAN.alias, "kind": "target.clear",
                             "data": data, "taken_at": None}])
    taken = asyncio.run(store.web_intents_take(10))
    assert [row["id"] for row in taken] == [4] and taken[0]["body"]["by"] == 777
    assert "update web_intents set taken_at" in store.pool.sql[0]
    assert asyncio.run(store.web_intents_take(10)) == []
    assert asyncio.run(store.web_intent_pending(4)) is True
    asyncio.run(store.web_intent_done(4))
    assert asyncio.run(store.web_intent_pending(4)) is False
    assert "alter table web_intents add column if not exists taken_at timestamptz" in SCHEMA
    assert "taken_at" not in retention.DELETE_SQL["intenti_appesi"]


def test_a_gesture_that_blows_up_is_closed_with_a_reason(monkeypatch):
    async def boom(store, beat, row, now):
        raise RuntimeError("niente")

    monkeypatch.setattr(intents, "apply_one", boom)
    store = Queue([queued(4)])
    assert asyncio.run(intents.drain(store, None, NOW)) == 0
    assert store.done == [4]
    assert store.kv[intents.refused_key(4)]["code"] == reasons.REFUSED


def test_a_gesture_leaves_the_queue_when_the_bot_has_answered(monkeypatch):
    seen = []

    async def quiet(store, beat, row, now):
        seen.append(row["id"])
        return row["id"] == 4

    monkeypatch.setattr(intents, "apply_one", quiet)
    store = Queue([queued(4), queued(5)])
    assert asyncio.run(intents.drain(store, None, NOW)) == 1
    assert seen == [4, 5] and store.done == [4, 5]
    assert list(store.kv) == [intents.refused_key(5)]


def test_il_registro_dei_gesti_dice_il_motivo_e_non_porta_persone(monkeypatch, caplog):
    async def refuses(store, beat, row, now):
        return reasons.refuse(reasons.NOT_IN_WAR)

    monkeypatch.setattr(intents, "apply_one", refuses)
    row = dict(queued(9), body={"by": 777, "tag": "#P1", "text": "piano segreto"})
    store = Queue([row])
    with caplog.at_level(logging.INFO, logger="clashbot.intents"):
        assert asyncio.run(intents.drain(store, None, NOW)) == 0
    assert store.kv[intents.refused_key(9)]["code"] == reasons.NOT_IN_WAR
    assert "target.clear" in caplog.text and reasons.NOT_IN_WAR in caplog.text
    for secret in ("777", "#P1", "piano segreto"):
        assert secret not in caplog.text, secret


def test_l_app_riceve_il_codice_del_rifiuto_arrivato_dal_bot():
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[intents.refused_key(1)] = {"at": 1, "code": reasons.NOT_IN_WAR}
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "target.mirror", "id": "ab19"})
    assert res.status == 403
    assert json.loads(res.body) == {"error": reasons.NOT_IN_WAR}


def test_chi_non_ha_il_posto_riceve_un_codice_dichiarato_e_non_accoda_niente():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/act", "POST", uid=999,
                data={"kind": "clan.pause", "id": "ab21"})
    found = json.loads(res.body)
    assert res.status == 403 and store.intents == []
    assert found["error"] in reasons.REASONS


def test_una_richiesta_storta_non_arriva_alla_coda_e_dice_il_motivo():
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "pinco.pallo", "id": "ab22"})
    assert res.status == 400 and store.intents == []
    assert json.loads(res.body) == {"error": reasons.BAD}


def test_un_rifiuto_senza_codice_resta_quello_generico():
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[intents.refused_key(1)] = {"at": 1}
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "target.mirror", "id": "ab20"})
    assert res.status == 403 and json.loads(res.body) == {"error": reasons.REFUSED}


def test_ogni_motivo_ha_la_sua_parola_corta_in_tutte_le_lingue():
    for code in i18n.LANGUAGES:
        found = miniapp.words(i18n.locale(code))
        for reason in reasons.REASONS:
            word = found["denied_" + reason]
            assert word and not word.startswith("["), (code, reason)
    assert miniapp.words(i18n.locale("it"))["queued"]


def test_il_battito_del_canale_e_la_tolleranza_arrivano_all_app():
    assert miniapp.CONF["BEAT"] == http.READ_TIMEOUT
    assert miniapp.CONF["GRACE"] == live.LIVE_GRACE == 2 * http.READ_TIMEOUT
    assert live.PING.startswith("event: ping")


MODULI_DEL_PACCHETTO = ("acts.py", "app_actions.py", "base_packs.py", "intents.py",
                        "linking.py", "manager_actions.py", "manager_net.py",
                        "manager_staff.py", "manager_tools.py", "reasons.py",
                        "web/app.py", "web/miniapp.py")
TETTO_RIGHE = 60


def _troppo_lunghe(sorgente):
    albero = ast.parse(sorgente)
    return sorted(nodo.name for nodo in ast.walk(albero)
                  if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and nodo.end_lineno - nodo.lineno + 1 > TETTO_RIGHE)


def test_nessuna_funzione_del_pacchetto_supera_il_tetto_di_righe():
    radice = Path(miniapp.__file__).parents[1]
    lunghe = {nome: _troppo_lunghe((radice / nome).read_text(encoding="utf-8"))
              for nome in MODULI_DEL_PACCHETTO}
    assert lunghe == {nome: [] for nome in MODULI_DEL_PACCHETTO}


def test_la_regola_del_livello_e_scritta_una_volta_sola():
    sorgente = Path(miniapp.__file__).read_text(encoding="utf-8")
    assert sorgente.count("allowed(None, ACTIONS[kind]") == 1


def test_la_porta_e_il_motivo_non_si_scollano_mai():
    for kind in sorted(acts.FIELDS):
        for seat in ({}, {"tag": "#P1"}, {"tag": "#P1", "level": settings.MANAGER},
                     {"tag": "#P1", "level": "limited"}, {"level": settings.MANAGER}):
            motivo = miniapp.why(chief_page(), seat, kind)
            assert (motivo == reasons.NOT_MANAGER) is (
                miniapp.manager_only(kind)
                and not settings.allowed(None, acts.ACTIONS[kind], seat.get("level"))), kind
            assert (motivo is None) is (miniapp.may(kind, seat, chief_page())
                                        and (kind not in acts.CHIEF_KINDS
                                             or miniapp.chief_seat(chief_page(), seat))), kind


def test_ogni_gesto_dichiara_il_suo_bersaglio_per_la_coda():
    assert set(acts.MARKS) == set(acts.FIELDS)
    for kind, names in acts.MARKS.items():
        assert set(names) <= set(acts.FIELDS[kind]), kind
        assert len(set(names)) == len(names), kind


def test_i_bersagli_che_la_coda_perdeva_ora_sono_dichiarati():
    assert acts.MARKS["prediction.set"] == ("poll",)
    assert acts.MARKS["duel.challenge"] == ("rival",)
    assert acts.MARKS["base.propose"] == ("link",)
    assert acts.MARKS["schedule.add"] == ("hhmm",)
    assert acts.MARKS["settings.press"] == ("data",)
    assert acts.MARKS["family.derby"] == ("data",)
    assert acts.MARKS["family.tourney"] == ("data",)
    assert acts.MARKS["undo.apply"] == ("of", "ref")
    assert "link.approve" not in acts.MARKS


def test_i_bersagli_della_coda_arrivano_all_app():
    portati = miniapp.CONF["MARKS"]
    assert portati == {kind: list(names) for kind, names in acts.MARKS.items() if names}
    assert json.loads(json.dumps(portati)) == portati
    assert "MARKS" not in static.read("app/shell.js").decode()
    assert "conf.MARKS" in app_shell()


def test_the_board_says_how_much_time_is_left():
    assert "countdown(" in static.read("app/war.js").decode()
    clock = static.read("app/ui.js").decode()
    for unit in miniapp.UNITS:
        assert "words.unit_" + unit in clock, unit
    found = miniapp.words(i18n.locale("it"))
    assert (found["unit_d"], found["unit_h"], found["unit_m"]) == ("g", "h", "m")
    assert miniapp.words(i18n.locale("en"))["unit_d"] == "d"
    assert body()["war"]["end"] == int(datetime(2026, 9, 12, 10, tzinfo=timezone.utc).timestamp())


def test_la_scheda_guerra_prende_dal_catalogo_ogni_parola_che_mostra():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in miniapp.WAR_WORDS:
            assert found["war_" + name] == L.t("web.app.war." + name), name
            assert not found["war_" + name].startswith("["), name
        for name in miniapp.TODO + ("title", "empty"):
            assert found["todo_" + name] == L.t("web.app.todo." + name), name
            assert not found["todo_" + name].startswith("["), name
        for key in miniapp.AGENDA:
            assert found["next_" + key] == L.t("agenda.item." + key), key
        for result in miniapp.RESULTS:
            assert found["war_" + result] == L.t("foe.result." + result), result
        for name, key in (("th", "members.join.th"), ("target_th", "attack.target_th"),
                          ("name_count", "common.name_count"), ("war_score", "card.war.title")):
            assert found[name] == L.t(key) and not found[name].startswith("["), name
        assert found["unit_s"] == L.t("unit.s") and not found["unit_s"].startswith("[")
    assert miniapp.CONF["FULL"] == app_war.FULL
    assert miniapp.CONF["WATCH"] == base_videos.WATCH
    assert set(miniapp.AGENDA) == {row["key"] for row in agenda.upcoming(NOW)}


def test_le_strisce_prendono_dal_catalogo_ogni_parola_che_mostrano():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in miniapp.STRIP_WORDS:
            assert found["strip_" + name] == L.t("web.app.strip." + name), name
            assert not found["strip_" + name].startswith("["), name
    for name in ("shot", "top", "yours"):
        assert name in miniapp.WAR_WORDS, name
    assert all("strip_" + name in miniapp.words(i18n.locale("de"))
               for name in miniapp.STRIP_WORDS)


def test_l_app_avvisa_nell_ultima_ora_e_ricorda_di_aver_chiesto_il_sussurro():
    war = static.read("app/war.js").decode()
    assert "FLOOD_WINDOW = 3600" in war
    main = app_shell()
    assert "recall(" in main and "remember(" in main and 'buzz(tg, "warning")' in main
    assert "CloudStorage" in static.read("app/native.js").decode()
    assert "app/war_end.js" in static.manifest()["files"]


def test_la_lega_prende_dal_catalogo_ogni_parola_che_mostra():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in miniapp.CWL_WORDS:
            assert found["cwl_" + name] == L.t("web.app.cwl." + name), name
            assert not found["cwl_" + name].startswith("["), name
        assert "{n}" in found["cwl_day"] and "{result}" in found["cwl_day"]
        for side in miniapp.CONF["SIDES"]:
            assert found["avail_" + side] and not found["avail_" + side].startswith("["), side


def test_every_word_that_reaches_the_page_goes_through_the_escape():
    L = i18n.locale("it")
    page = dict(body(), clan={"name": "<b>'Clan'</b>", "level": 1, "league": None, "members": 1})
    text = miniapp.app_page(L, page, "a'b<c")
    assert "<b>" not in text.split("</head>")[1] and "&lt;b&gt;" in text
    assert 'data-slug="a&#x27;b&lt;c"' in text
    assert "<title>&lt;b&gt;" in text


def test_the_words_and_the_numbers_travel_as_attributes_never_as_a_script():
    res = serve(AppStore({(SLUG, payload.APP): body()}), f"/app/{SLUG}")
    text = res.body.decode()
    assert "<script>" not in text and text.count("<script ") == 3
    assert text.count('<script src="') == 2 and text.count('<script type="module"') == 1
    raw = text.split("data-conf='")[1].split("'")[0]
    assert json.loads(unescape(raw))["TOKEN_MAX"] == miniapp.CONF["TOKEN_MAX"]


def test_lo_schermo_tiene_l_avviso_e_chiede_l_anteprima_al_bot():
    main = app_shell()
    assert "Toast" in main and "toastAct(" in main
    assert "look(path, signed()" in main and 'preview: stem + "/preview"' in main
    assert "draft === undefined ? 0 : BEAT" in main
    assert "setTimeout(() => pick(TOASTED, null), SPAN)" in main
    forms = static.read("app/manage_forms.js").decode()
    assert 'class="preview"' in forms


def test_the_page_carries_the_words_of_the_time_left():
    res = serve(AppStore({(SLUG, payload.APP): body()}), f"/app/{SLUG}")
    raw = res.body.decode().split("data-words='")[1].split("'")[0]
    assert json.loads(unescape(raw))["unit_h"] == "h"


def test_lo_schermo_vive_del_canale_aperto_e_rilegge_tornando_in_primo_piano():
    main = app_shell()
    assert "connect(" in main and "pull(" in main
    assert "visibilitychange" in main
    assert main.count("setInterval(") == 1
    tick = main.split("setInterval(")[1].split("\n")[0]
    assert "setNow(" in tick and "pull(" not in tick and "connect(" not in tick


def app_shell():
    return "\n".join(static.read("app/" + name).decode() for name in ("main.js", "hooks.js"))


def app_sources():
    found = static.manifest()["files"]
    return "\n".join(body.decode() for name, body in found.items()
                     if name.startswith("app/") and name.endswith(".js"))


def test_ogni_parola_mandata_all_app_la_legge_il_javascript():
    js = app_sources()
    heads = {head for head in re.findall(r'words\["([a-z_]*)"\s*\+', js) if head}
    read = set(re.findall(r'words\.([A-Za-z_][A-Za-z0-9_]*)', js))
    read |= set(re.findall(r'words\["([^"]+)"\]', js))
    for key in miniapp.words(i18n.locale("it")):
        assert key in read or any(key.startswith(head) for head in heads), key


def test_lo_schermo_riusa_lo_stato_e_il_canale_partiti_con_la_pagina():
    boot = static.read(static.BOOT).decode()
    assert "import " not in boot and "export " not in boot
    assert "clanboardBoot" in boot and "new EventSource(" in boot and "fetch(" in boot
    assert "dataset.slug" in boot and "dataset.live" in boot and "initData" in boot
    main = app_shell()
    assert "window.clanboardBoot" in main and "adopt(started.source" in main
    assert main.index("started.events.forEach") < main.index("adopt(started.source")


def test_il_segno_del_sussurro_si_scrive_solo_sulla_scheda_guerra():
    main = app_shell()
    riga = next(line for line in main.splitlines() if "const asking" in line)
    assert "views[FIRST]" in riga and "!party" in riga
    assert "wants" in riga and "ASKED" in riga
    assert main.count("remember(tg, ASKED, MARK, conf.KEEP)") == 1


def test_i_bottoni_dell_app_coprono_le_azioni_che_la_pagina_sa_mostrare():
    found = miniapp.words(i18n.locale("it"))
    for choice in miniapp.AVAIL:
        assert found["avail_" + choice] == i18n.locale("it").t(f"avail.option.{choice}")
    for reason in miniapp.REASONS:
        assert found["reason_" + reason] == i18n.locale("it").t(f"report.reasons.{reason}")
    assert found["avail"] and found["denied"] and found["loading"]


def test_le_parole_dei_gesti_rimasti_scollegati_arrivano_all_app():
    found = miniapp.words(i18n.locale("it"))
    for key in ("me_csv", "me_json", "war_clear", "more_report"):
        assert found[key] and not found[key].startswith("["), key
    assert miniapp.CONF["REASONS"] == list(miniapp.REASONS)
    assert all(acts.FIELDS["report.send"]["reason"](one) for one in miniapp.CONF["REASONS"])
    assert all(found["reason_" + one] for one in miniapp.CONF["REASONS"])
    assert not acts.FIELDS["target.clear"]


def asking(path, uid=777):
    return request(path, headers=f"X-Init-Data: {init(uid)}\r\n".encode())


def test_lo_stato_dell_app_legge_la_pagina_una_volta_sola():
    class Counted(AppStore):
        def __init__(self):
            super().__init__({(SLUG, payload.APP): body()})
            self.reads = []

        async def get_secret(self, kind):
            self.reads.append("token")
            return await super().get_secret(kind)

        async def web_page(self, slug, kind):
            self.reads.append("page")
            return await super().web_page(slug, kind)

        async def web_app_alias(self, slug):
            self.reads.append("alias")
            return await super().web_app_alias(slug)

        async def kv_get(self, key):
            self.reads.append("ban" if key.startswith(ban.PREFIX) else "feed")
            return await super().kv_get(key)

    store = Counted()
    site = web_app.Site(store)
    state = f"/app/{SLUG}/state"
    assert asyncio.run(site.router(asking(state))).status == 200
    store.reads.clear()
    res = asyncio.run(site.router(asking(state)))
    assert res.status == 200 and store.reads == ["feed"]
    assert json.loads(res.body)["me"]["tag"] == "#P1"
    store.reads.clear()
    assert asyncio.run(site.router(asking(state, uid=999))).status == 200
    assert store.reads == []


def page_with(seats, level=None):
    return body(seats=seats, info=dict(INFO, level=level))


class CountingStore(AppStore):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.reads = 0
        self.listened = []

    async def web_page(self, slug, kind):
        self.reads += 1
        return await super().web_page(slug, kind)

    async def listen(self, channel, callback, connect=None):
        self.listened.append((channel, callback))
        return SimpleNamespace(is_closed=lambda: False)


def test_the_state_is_served_from_memory_after_the_first_read():
    store = CountingStore({(SLUG, payload.APP): page_with(SEATS)})
    site = web_app.Site(store)
    state = f"/app/{SLUG}/state"
    first = asyncio.run(site.router(asking(state)))
    second = asyncio.run(site.router(asking(state)))
    assert first.status == 200 and second.status == 200
    assert store.reads == 1


def test_a_page_notice_drops_the_cache_and_rereads_once():
    store = CountingStore({(SLUG, payload.APP): page_with(SEATS)})
    site = web_app.Site(store)

    async def go():
        assert not site.listening()
        await site.listen()
        assert site.listening()
        await site.page_of(SLUG)
        store.pages[(SLUG, payload.APP)] = page_with(SEATS, level=12)
        channel, callback = store.listened[0]
        callback(SLUG)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return channel, (await site.page_of(SLUG))["clan"]["level"]

    channel, level = asyncio.run(go())
    assert channel == "clanboard_page" and level == 12
    assert store.reads == 2 and site.notified == 1


def test_a_page_notice_without_open_apps_only_forgets_the_page():
    store = CountingStore({(SLUG, payload.APP): page_with(SEATS)})
    site = web_app.Site(store)

    async def go():
        await site.listen()
        await site.page_of(SLUG)
        channel, callback = store.listened[0]
        callback(SLUG)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return SLUG in site.pages

    assert asyncio.run(go()) is False
    assert store.reads == 1 and site.notified == 1


ONE_SEAT = {"777": {"tag": "#P1", "name": "Mario"}}


def live_request(uid=777):
    return request(f"/app/{SLUG}/live?init={quote(init(uid), safe='')}")


def test_the_live_route_sends_the_state_then_each_new_page():
    store = CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)})
    site = web_app.Site(store)
    req = live_request()

    async def go():
        res = await site.router(req)
        assert isinstance(res, http.StreamResponse)
        assert res.kind == http.EVENT_STREAM
        out = []
        gen = res.events.__aiter__()
        out.append(await gen.__anext__())
        site.pages[SLUG] = page_with(ONE_SEAT, level=12)
        for client in list(site.live[SLUG]):
            client.put_nowait(site.pages[SLUG])
        out.append(await gen.__anext__())
        for client in list(site.live[SLUG]):
            client.put_nowait(live.CLOSE)
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return out

    first, second = asyncio.run(go())
    assert first.startswith("event: state\ndata: ") and first.endswith("\n\n")
    assert '"level":null' in first and json.loads(first.split("data: ")[1])["me"]["tag"] == "#P1"
    assert second.startswith("event: state\ndata: ") and '"level":12' in second
    assert site.live.get(SLUG) in (None, set())


def test_a_page_notice_reaches_the_open_live_clients():
    store = CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)})
    site = web_app.Site(store)
    req = live_request()

    async def go():
        await site.listen()
        res = await site.router(req)
        gen = res.events.__aiter__()
        await gen.__anext__()
        store.pages[(SLUG, payload.APP)] = page_with(ONE_SEAT, level=12)
        store.listened[0][1](SLUG)
        pushed = await asyncio.wait_for(gen.__anext__(), 1)
        await gen.aclose()
        return pushed

    assert '"level":12' in asyncio.run(go())


def test_l_avviso_arrivato_mentre_si_prepara_il_primo_evento_non_si_perde():
    store = CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)})
    site = web_app.Site(store)
    req = live_request()
    attached = []

    async def go():
        await site.listen()
        res = await site.router(req)
        gen = res.events.__aiter__()
        links = site.links

        async def while_shaping():
            attached.append(len(site.live.get(SLUG) or ()))
            store.pages[(SLUG, payload.APP)] = page_with(ONE_SEAT, level=12)
            store.listened[0][1](SLUG)
            return await links()

        site.links = while_shaping
        first = await gen.__anext__()
        pushed = await asyncio.wait_for(gen.__anext__(), 1)
        await gen.aclose()
        return first, pushed

    first, pushed = asyncio.run(go())
    assert attached[0] == 1
    assert '"level":12' not in first and '"level":12' in pushed


def test_il_rinfresco_della_pagina_resta_appeso_al_sito_finche_non_finisce():
    store = CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)})
    site = web_app.Site(store)
    req = live_request()

    async def go():
        await site.listen()
        res = await site.router(req)
        gen = res.events.__aiter__()
        await gen.__anext__()
        store.listened[0][1](SLUG)
        held = len(site.tasks)
        await asyncio.wait_for(gen.__anext__(), 1)
        await gen.aclose()
        await asyncio.sleep(0)
        return held, len(site.tasks)

    assert asyncio.run(go()) == (1, 0)


def test_a_second_live_connection_for_the_same_seat_closes_the_first():
    store = CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)})
    site = web_app.Site(store)
    first, second = live_request(), live_request()

    async def go():
        a = await site.router(first)
        ga = a.events.__aiter__()
        await ga.__anext__()
        b = await site.router(second)
        gb = b.events.__aiter__()
        await gb.__anext__()
        try:
            await asyncio.wait_for(ga.__anext__(), 1)
            answer = "aperta"
        except StopAsyncIteration:
            answer = "chiusa"
        left = len(site.live.get(SLUG) or ())
        await gb.aclose()
        return answer, left, site.live.get(SLUG)

    assert asyncio.run(go()) == ("chiusa", 1, None)


def test_the_live_route_pings_when_nothing_happens():
    site = web_app.Site(CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)}))

    async def go():
        gen = live.stream(site, SLUG, "777", "event: state\ndata: {}\n\n", ping=0.01).__aiter__()
        await gen.__anext__()
        beat = await gen.__anext__()
        await gen.aclose()
        return beat, site.live.get(SLUG)

    assert asyncio.run(go()) == (live.PING, None)


def test_the_live_seat_is_freed_the_moment_the_client_breaks():
    site = web_app.Site(CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)}))
    req = live_request()

    class Broken:
        def __init__(self):
            self.chunks = []
            self.open = []
            self.closed = False

        def get_extra_info(self, name):
            return ("127.0.0.9", 1234)

        def write(self, chunk):
            if self.chunks:
                self.open.append(len(site.live.get(SLUG) or ()))
                raise ConnectionError("via")
            self.chunks.append(chunk)

        async def drain(self):
            return None

        def close(self):
            self.closed = True

    async def go():
        res = await site.router(req)
        writer = Broken()
        try:
            await http.stream(writer, res)
        except ConnectionError:
            pass
        return writer.open, SLUG in site.live

    assert asyncio.run(go()) == ([1], False)


def test_the_live_route_refuses_who_is_not_signed():
    store = CountingStore({(SLUG, payload.APP): page_with(ONE_SEAT)})
    assert serve(store, f"/app/{SLUG}/live", uid=None).status == 401
    assert serve(CountingStore({}), f"/app/{SLUG}/live").status == 404


def app_link(tag, user_id, name, lang=None):
    return SimpleNamespace(tag=tag, user_id=user_id, name=name, dm=True, lang=lang)


class DataStore(AppStore):
    def __init__(self, pages=None, links=(), state=None):
        super().__init__(pages)
        self.links = list(links)
        self.state = dict(state or {})

    async def clan_by_alias(self, alias):
        return CLAN if alias == CLAN.alias else None

    async def links_by_user(self, user_id):
        return [row for row in self.links if int(row.user_id) == int(user_id)]

    async def get_state(self, alias, kind):
        return self.state.get((alias, kind))

    async def recent_wars(self, alias, limit=10):
        return []


def data_store():
    return DataStore({(SLUG, payload.APP): body()},
                     links=[app_link("#P1", 777, "Mario", "it"),
                            app_link("#P3", 888, "Peach", "en")],
                     state={(CLAN.alias, "members"): MEMBERS,
                            (CLAN.alias, "notes"): {"#P3": "nota su Peach"},
                            (CLAN.alias, discipline.STATE): [
                                {"id": "w1", "tag": "#P1", "name": "Mario", "war": "g1",
                                 "missed": 1, "at": 1, "by": "#P2"}]})


def test_my_data_is_a_page_of_the_app_and_only_for_who_opens_it():
    store = data_store()
    res = serve(store, f"/app/{SLUG}/mydata.json")
    assert res.status == 200 and res.headers["Cache-Control"] == "no-store"
    found = json.loads(res.body)
    assert [row["tag"] for row in found["accounts"]] == ["#P1"]
    assert found["accounts"][0]["clan_row"]["name"] == "Mario"
    assert [row["by"] for row in found["warnings"]] == ["Luigi"]
    assert "#P3" not in res.body.decode() and "Peach" not in res.body.decode()
    hers = json.loads(serve(store, f"/app/{SLUG}/mydata.json", uid=888).body)
    assert [row["tag"] for row in hers["accounts"]] == ["#P3"] and hers["warnings"] == []
    assert serve(store, f"/app/{SLUG}/mydata.json", uid=999).status == 401
    assert serve(store, f"/app/{SLUG}/mydata.json", uid=0).status == 401
    assert serve(DataStore(), f"/app/{SLUG}/mydata.json").status == 404


def test_i_miei_dati_si_scaricano_dal_link_che_porta_la_firma():
    store = data_store()
    firma = quote(init(777), safe="")
    res = serve(store, f"/app/{SLUG}/mydata.json?init={firma}", uid=0)
    assert res.status == 200
    assert [row["tag"] for row in json.loads(res.body)["accounts"]] == ["#P1"]
    assert serve(store, f"/app/{SLUG}/mydata.json?init=pinco", uid=0).status == 401
    altrui = quote(init(888), safe="")
    hers = serve(store, f"/app/{SLUG}/mydata.json?init={altrui}", uid=0)
    assert [row["tag"] for row in json.loads(hers.body)["accounts"]] == ["#P3"]


def test_the_page_of_my_data_is_never_written_by_the_web():
    class Frozen(DataStore):
        async def set_state(self, alias, kind, obj):
            raise AssertionError("la pagina dei miei dati non scrive")

        async def kv_set(self, key, obj, ref=None, ttl=None):
            raise AssertionError("la pagina dei miei dati non scrive")

    store = Frozen({(SLUG, payload.APP): body()}, links=[app_link("#P1", 777, "Mario", "it")],
                   state={(CLAN.alias, "members"): MEMBERS})
    assert serve(store, f"/app/{SLUG}/mydata.json").status == 200


def test_the_deletion_from_the_app_wants_two_touches_and_travels_as_an_intent():
    assert miniapp.intent({"kind": "data.forget", "sure": "yes", "id": "d1"}, "#P1", 777) == {
        "kind": "data.forget", "sure": "yes", "by": 777, "tag": "#P1", "id": "d1"}
    assert miniapp.intent({"kind": "data.forget", "id": "d2"}, "#P1", 777) is None
    assert miniapp.may("data.forget", {"tag": "#P1", "level": None}, body()) is True
    assert miniapp.may("data.forget", {"level": None}, body()) is False
    store = AppStore({(SLUG, payload.APP): body()})
    res = serve(store, f"/app/{SLUG}/act", "POST",
                data={"kind": "data.forget", "sure": "yes", "id": "d3"})
    assert res.status == 200 and store.intents[0][1] == "data.forget"
    assert serve(store, f"/app/{SLUG}/act", "POST", uid=999,
                 data={"kind": "data.forget", "sure": "yes", "id": "d4"}).status == 403
    L = i18n.locale("it")
    for name in miniapp.DATA_WORDS:
        assert miniapp.words(L)["data_" + name] == L.t("web.app.data." + name)
        assert not miniapp.words(L)["data_" + name].startswith("[")


def test_the_bot_applies_the_gesture_with_the_same_function():
    booked = {"pos": "3", "who": "1"}
    assert intents.next_plan("target.set", {}, WAR, booked, "#P1") == {"3": {"tag": "#P1",
                                                                            "name": "Mario"}}
    assert intents.next_plan("target.set", {}, WAR, {"pos": "3", "who": "99"}, "#P1") is None
    assert intents.next_plan("target.free", {"3": {"tag": "#P1"}}, WAR, {"pos": "3"},
                             "#P1") == {}
    assert intents.next_plan("target.mirror", {}, WAR, {}, "#P1") == targets.mirror_plan(WAR)
    assert intents.next_plan("target.clear", {"1": {}}, WAR, {}, "#P1") == {}
    assert intents.next_plan("target.note", {"3": {"tag": "#P1"}}, WAR, {"pos": "3",
                                                                        "text": "regine"},
                             "#P1") == {"3": {"tag": "#P1", "note": "regine"}}
    assert intents.next_plan("target.swap", {"3": {"tag": "#P1"}}, WAR, {"pos": "3"},
                             "#P2") == {"3": {"tag": "#P1", "swap": True}}
    assert intents.next_plan("target.swap", {"3": {"tag": "#P1"}}, WAR, {"pos": "3"},
                             "#P1") is None
    assert intents.next_plan("pinco", {}, WAR, {}, "#P1") is None


def test_le_parole_della_scheda_clan_arrivano_dal_catalogo():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in miniapp.CLAN_WORDS:
            assert found["clan_" + name] == L.t("web.app.clan." + name)
            assert not found["clan_" + name].startswith("["), (code, name)
        for name in miniapp.CLAN_SORTS:
            assert found["clan_sort_" + name] == L.t("web.app.clan.sort." + name)
            assert not found["clan_sort_" + name].startswith("["), (code, name)
        for name in miniapp.GROWTH_WORDS:
            assert found["growth_" + name] == L.t("web.app.growth." + name)
            assert not found["growth_" + name].startswith("["), (code, name)
        for role in miniapp.ROLES:
            assert found["role_" + role] == L.t("role." + role, n=1)
            assert not found["role_" + role].startswith("["), (code, role)
        assert "{n}" in found["clan_record"]
    assert miniapp.CONF["MEDALS"] == dict(badges.CATALOG)


def test_le_parole_della_scheda_io_arrivano_dal_catalogo():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in miniapp.ME_WORDS:
            assert found["me_" + name] == L.t("web.app.me." + name)
            assert not found["me_" + name].startswith("["), (code, name)
        for name in acts.AVAIL:
            assert not found["avail_" + name].startswith("["), (code, name)
        for name in ("link_title", "link_yours", "link_mine", "link_verify",
                     "link_steps", "link_token", "link_drop", "link_whisper",
                     "data_title", "data_forget", "data_sure", "data_gone", "avail"):
            assert found[name] and not found[name].startswith("["), (code, name)
    assert miniapp.CONF["AVAIL"] == list(acts.AVAIL)
    assert miniapp.CONF["SURE"] == mydata.SURE
    assert acts.FIELDS["data.forget"]["sure"](miniapp.CONF["SURE"])
    assert all(acts.FIELDS["availability.set"]["choice"](one) for one in miniapp.CONF["AVAIL"])
    assert all(acts.FIELDS["link.whisper"]["on"](one) for one in miniapp.CONF["SWITCH"])


def test_anche_la_riga_che_si_tocca_tiene_il_suo_filetto():
    rules = regole(FOGLIO)
    filetto = "border-bottom:1px solid var(--bg)"
    assert filetto in rules[".row"]
    touch = rules["button.row"]
    assert "border:0" in touch and filetto in touch
    assert touch.index("border:0") < touch.index(filetto)
    assert rules[".row:last-child"] == "border-bottom:0"


def test_le_tessere_e_gli_altri_pezzi_hanno_il_loro_stile():
    rules = regole(FOGLIO)
    for name in (".tile", ".grid", ".ring", ".toast", ".switch", ".strip"):
        assert name in rules, name
    assert "background:var(--card)" in rules[".card"]
    assert "border:1px solid var(--line)" in rules[".card"]
    assert "--card:" in regole(style.CSS)[":root"]
    assert "--line:" in regole(miniapp.STYLE)[":root"]
    assert "--accent:" in regole(BASE)[":root"]


def test_the_tab_bar_stays_above_the_gesture_area():
    assert "padding-bottom:max(var(--safe-bottom,0px),env(safe-area-inset-bottom,0px))" in FOGLIO
    assert "min-height:var(--tap)" in FOGLIO and "--tap:44px" in BASE
    assert "calc(var(--space-3) + var(--safe-top,0px))" in FOGLIO


def test_la_cronaca_e_l_assenza_arrivano_dal_riquadro_delle_persone_e_non_due_volte():
    page = dict(body(record=SAMPLE_RECORD, growth=SAMPLE_GROWTH),
                events=[{"pack": "members", "kind": "join", "who": "Toad", "n": 13, "at": 9}],
                idle=[{"tag": "#P3", "name": "Peach", "days": 5}])
    out = miniapp.state_body(page, {"uid": 777, **SEATS["777"]})
    assert "events" not in out and "idle" not in out
    assert out["people"]["chronicle"] == page["events"]
    away = {row["tag"]: row["absent_days"] for row in out["people"]["rows"]}
    assert away["#P3"] == 5 and away["#P1"] == 0


def test_il_pallino_dell_assenza_ha_la_soglia_del_bot():
    assert miniapp.CONF["IDLE_MIN_DAYS"] == progress.IDLE_MIN_DAYS == 3


def test_le_parole_della_cronaca_e_delle_tessere_arrivano_dal_catalogo():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for name in ("chronicle", "absent", "ratio", "week", "month"):
            assert found["clan_" + name] == L.t("web.app.clan." + name), name
            assert not found["clan_" + name].startswith("["), name
        for kind in miniapp.EVENT_KINDS:
            assert found["ev_" + kind] == L.t("web.app.clan.ev." + kind), kind
            assert not found["ev_" + kind].startswith("["), kind
        for name in miniapp.AGO:
            assert found["ago_" + name] == L.t("ago." + name), name
            assert not found["ago_" + name].startswith("["), name
    assert "{n}" in miniapp.words(i18n.locale("it"))["clan_absent"]


def test_le_parole_nuove_sono_scritte_in_italiano_e_in_inglese_e_in_inglese_altrove():
    catalogs = {code: json.loads((i18n.LOCALE_DIR / f"{code}.json").read_text(encoding="utf-8"))
                for code in i18n.LANGUAGES}
    keys = ["web.app.clan." + name for name in ("chronicle", "absent", "ratio", "week", "month")]
    keys += ["web.app.clan.ev." + kind for kind in miniapp.EVENT_KINDS]
    for key in keys:
        assert catalogs["it"][key] and catalogs["en"][key], key
        assert catalogs["it"][key] != catalogs["en"][key], key
        for code in catalogs:
            if code not in ("it", "en"):
                assert catalogs[code][key] == catalogs["en"][key], (code, key)


def test_le_medaglie_dicono_il_nome_e_come_si_ottengono():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        for row in badges.catalog():
            assert found["badge_name_" + row["badge"]] == L.t(row["name"]), row["badge"]
            assert found["badge_how_" + row["badge"]] == L.t(row["how"]), row["badge"]
            assert not found["badge_how_" + row["badge"]].startswith("["), row["badge"]
    assert list(miniapp.CONF["MEDALS"]) == [row["badge"] for row in badges.catalog()]


def test_l_angolo_mio_ha_le_parole_di_tag_condividi_obiettivo_e_lingua():
    for code in ("it", "en"):
        L = i18n.locale(code)
        found = miniapp.words(L)
        assert "me_you" not in found
        for name in ("tag", "share", "share_clan", "lang"):
            assert found["me_" + name] == L.t("web.app.me." + name), name
            assert not found["me_" + name].startswith("["), name
        assert found["goal_title"] == L.t("goal.title")
        for kind in goals.KINDS:
            assert found["goal_what_" + kind] == L.t("goal.what." + kind), kind
            assert "{" in found["goal_what_" + kind], kind
    assert [one["code"] for one in miniapp.CONF["LANGS"]] == list(i18n.LANGUAGES)
    assert miniapp.CONF["LANGS"][0]["name"] == i18n.LANGUAGES["en"]


def test_la_risposta_al_condividi_porta_il_messaggio_gia_pronto():
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[share_cards.ready_key(CLAN.alias, 777)] = {"id": "prep-1", "mark": "ab12"}
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "share.week", "id": "ab12"})
    assert res.status == 200 and json.loads(res.body)["prepared"] == "prep-1"
    altro = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "target.mirror", "id": "ab13"})
    assert "prepared" not in json.loads(altro.body)


def test_il_rifiuto_del_bot_torna_all_app_col_motivo():
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[intents.refused_key(1)] = {"at": 1}
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "target.mirror", "id": "ab12"})
    assert res.status == 403 and json.loads(res.body)["error"] == miniapp.REFUSED
    for code in ("it", "en"):
        parola = miniapp.words(i18n.locale(code))["denied_" + miniapp.REFUSED]
        assert parola and not parola.startswith("[")
    passato = serve(store, f"/app/{SLUG}/act", "POST",
                    data={"kind": "target.mirror", "id": "ab13"})
    assert passato.status == 200


def test_la_card_da_condividere_si_scarica_dal_sito():
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[share_cards.card_key("tok")] = {"png": base64.b64encode(b"\x89PNG").decode()}
    res = serve(store, "/card/tok.png", uid=0)
    assert res.status == 200 and res.body == b"\x89PNG"
    assert res.kind == http.PHOTO
    assert serve(store, "/card/altro.png", uid=0).status == 404


def test_il_messaggio_pronto_vale_solo_per_il_tocco_che_lo_ha_chiesto(monkeypatch):
    monkeypatch.setattr(web_app, "APP_WAIT", 0.2)
    monkeypatch.setattr(web_app, "APP_STEP", 0.05)
    store = AppStore({(SLUG, payload.APP): body()})
    store.kv[share_cards.ready_key(CLAN.alias, 777)] = {"id": "prep-1", "mark": "vecchio"}
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "share.week", "id": "ab12"})
    assert res.status == 200 and "prepared" not in json.loads(res.body)


def test_il_condividi_aspetta_la_card_anche_se_il_bot_e_lento(monkeypatch):
    monkeypatch.setattr(web_app, "APP_WAIT", 1.0)
    monkeypatch.setattr(web_app, "APP_STEP", 0.05)

    class Slow(AppStore):
        def __init__(self):
            super().__init__({(SLUG, payload.APP): body()})
            self.asked = 0

        async def kv_get(self, key):
            if key != share_cards.ready_key(CLAN.alias, 777):
                return await super().kv_get(key)
            self.asked += 1
            if self.asked < 3:
                return None
            return {"id": "prep-2", "mark": "ab12"}

    store = Slow()
    res = serve(store, f"/app/{SLUG}/act", "POST", data={"kind": "share.week", "id": "ab12"})
    assert res.status == 200 and json.loads(res.body)["prepared"] == "prep-2"
    assert store.asked >= 3


def test_il_condividi_passa_dal_messaggio_gia_pronto_di_telegram():
    assert "app/me_link.js" in static.manifest()["files"]
    assert "shareMessage" in static.read("app/native.js").decode()
    assert "shareMessage(tg, prepared)" in app_shell()


def link_row(alias, user_id, tag, name):
    return SimpleNamespace(alias=alias, user_id=user_id, tag=tag, name=name, dm=True, lang="it")


def second_clan():
    return Clan(alias="clan-b2", chat_id=-200, tag="#CLAN2", name="Altro Clan", active=True,
                failures=0, last_seen=None, bot_alias="bot-1")


def clans_store(tmp_path, rows):
    other = second_clan()
    return AppStore({(SLUG, payload.APP): body()}, links=rows, clans=(CLAN, other),
                    vault=Vault(tmp_path))


def test_lo_stato_dice_in_quali_clan_hai_un_posto(tmp_path):
    rows = [link_row(CLAN.alias, 777, "#P1", "Mario"),
            link_row("clan-b2", 777, "#P9", "Mario"),
            link_row(CLAN.alias, 777, "#P7", "Mario"),
            link_row("clan-b2", 888, "#P8", "Peach")]
    store = clans_store(tmp_path, rows)
    found = asyncio.run(miniapp.clans_of(store, 777))
    assert [one["name"] for one in found] == ["Altro Clan", "Nostro Clan"]
    assert found[1]["slug"] == payload.slug_for(store.vault, CLAN.alias)
    assert "777" not in json.dumps(found) and "uid" not in json.dumps(found)
    assert asyncio.run(miniapp.clans_of(store, 999)) == []


def test_il_cambio_clan_arriva_nello_stato_servito(tmp_path):
    rows = [link_row(CLAN.alias, 777, "#P1", "Mario"), link_row("clan-b2", 777, "#P9", "Mario")]
    store = clans_store(tmp_path, rows)
    res = serve(store, f"/app/{SLUG}/state")
    assert res.status == 200
    found = json.loads(res.body)
    assert [one["name"] for one in found["clans"]] == ["Altro Clan", "Nostro Clan"]
    assert miniapp.state_body(body(), {"uid": 777, **SEATS["777"]})["clans"] == []


def _righe_gesto(caplog):
    return [record.getMessage() for record in caplog.records]


def test_il_gesto_ancora_in_coda_non_finisce_a_registro_come_fatto(monkeypatch, caplog):
    monkeypatch.setattr(web_app, "APP_WAIT", 0.2)
    monkeypatch.setattr(web_app, "APP_STEP", 0.05)
    store = AppStore({(SLUG, payload.APP): body()}, pending=(1,))
    with caplog.at_level(logging.INFO, logger="clashbot.web"):
        res = serve(store, f"/app/{SLUG}/act", "POST",
                    data={"kind": "target.mirror", "id": "ab21"})
    assert res.status == 200
    assert intents.DONE not in caplog.text
    assert _righe_gesto(caplog) == ["gesto target.mirror: " + web_app.WAITING]


def test_il_gesto_passato_dal_bot_finisce_a_registro_come_fatto(caplog):
    store = AppStore({(SLUG, payload.APP): body()})
    with caplog.at_level(logging.INFO, logger="clashbot.web"):
        res = serve(store, f"/app/{SLUG}/act", "POST",
                    data={"kind": "target.mirror", "id": "ab22"})
    assert res.status == 200
    assert _righe_gesto(caplog) == ["gesto target.mirror: " + intents.DONE]


def test_i_fogli_della_pagina_e_quelli_del_manifesto_sono_due_cose_distinte():
    assert miniapp.CONF["SHEETS"] == list(miniapp.SHEET_KINDS) == ["wars", "members"]
    assert all(foglio.endswith(".css") for foglio in miniapp.SHEETS)
    assert not set(miniapp.SHEET_KINDS) & set(miniapp.SHEETS)
