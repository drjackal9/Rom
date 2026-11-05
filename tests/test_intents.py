import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from telegram.error import TelegramError

from clashbot import (acts, availability, challenges, feed, guard, i18n, intents, leaders, media,
                      predictions, progress, quizbank, reasons, recap, settings, share_cards)
from clashbot.crypto import Vault
from clashbot.db import REPORTS_KEY, Store
from clashbot.events import member_snapshot, war_key, war_snapshot
from clashbot.web import payload
from fixtures import BASE_MEMBERS, clan_json, war_json
from test_web_publish import CLAN, INFO, NOW, TZ, IntentStore, beat_for, feed_rows

GESTI = ("availability.set", "goal.set", "quiz.answer", "duel.challenge", "duel.accept",
         "award.vote", "prediction.set", "report.send", "guess.answer",
         "target.set", "target.free", "target.mirror", "target.note", "target.swap",
         "target.clear",
         "link.verify", "link.whisper", "link.drop",
         "data.forget", "share.week", "share.season", "share.war", "lang.set",
         "base.propose",
         "app.opened")
WAR = war_snapshot(war_json("inWar", {"#P1": [("#E1", 3, 100.0)]}))
ROSTER = BASE_MEMBERS + [("#P5", "Yoshi", "coLeader", 15, 5000, 100, 100)]
MEMBERS = member_snapshot(clan_json(ROSTER))
TAGS = {7: "#P1", 9: "#P5", 11: "#P4", 13: "#P3"}
VILLAGES = {"tags": {"#P4": {"name": "Toad", "th": 13, "league": "Gold League I",
                             "trophies": 4200, "best": 4300, "warStars": 300,
                             "donations": 50, "received": 10,
                             "heroes": {"Barbarian King": 40}, "warPref": "in"}}}
VOTE_ROWS = [{"tag": "#P1", "name": "Mario", "stars": 6, "destr": 100.0},
             {"tag": "#P2", "name": "Luigi", "stars": 3, "destr": 90.0}]


def link(tag, user_id, name, lang=None):
    return SimpleNamespace(tag=tag, user_id=user_id, name=name, dm=True, lang=lang)


LINKS = [link("#P1", 7, "Mario", "it"), link("#P5", 9, "Yoshi"), link("#P4", 11, "Toad", "en")]
SEMPLICE = [(tag, name, "member" if tag == "#P3" else role, th, cups, don, rec)
            for tag, name, role, th, cups, don, rec in ROSTER]
PEACH = link("#P3", 13, "Peach", "it")


class ActStore(IntentStore):
    async def links_by_user(self, user_id):
        return [one for one in self.links if one.user_id == user_id]

    async def report_add(self, clan_alias, user_id, reason, now):
        key = f"{REPORTS_KEY}{clan_alias}"
        rows = list((await self.kv_get(key) or {}).get("rows") or [])
        rows.append({"at": now.timestamp(), "by": int(user_id), "reason": reason})
        await self.kv_set(key, {"rows": rows}, ref=clan_alias)
        return len(rows)

    async def report_forget(self, clan_alias, user_id):
        return await Store.report_forget(self, clan_alias, user_id)

    async def reports_for(self, clan_alias):
        return await Store.reports_for(self, clan_alias)

    async def active_clans(self, bot_alias=None):
        return [CLAN]

    async def drop_former(self, clan_alias, tag):
        return False

    async def set_link_lang(self, user_id, lang):
        for one in self.links:
            if one.user_id == user_id:
                one.lang = lang

    async def unlink(self, user_id, tag):
        before = len(self.links)
        self.links = [one for one in self.links
                      if not (one.user_id == user_id and one.tag == tag)]
        return len(self.links) < before


def app_store(tmp_path, war=None, players=None, cls=ActStore):
    store = cls(Vault(tmp_path))
    store.links = list(LINKS)
    asyncio.run(store.set_state(CLAN.alias, "settings", {"lang": "it", "tz": "Europe/Rome"}))
    asyncio.run(store.set_state(CLAN.alias, "members", MEMBERS))
    asyncio.run(store.set_state(CLAN.alias, "info", INFO))
    if war:
        asyncio.run(store.set_state(CLAN.alias, "war", war))
    if players:
        asyncio.run(store.set_state(CLAN.alias, "players", players))
    return store


def row(kind, body, uid=11, ident="a1", number=1):
    return {"id": number, "clan": CLAN.alias, "kind": kind,
            "body": dict(body, kind=kind, by=uid, tag=TAGS.get(uid, "#P1"), id=ident)}


def applied(store, kind, body, uid=11, ident="a1", coc=None, beat=None):
    return asyncio.run(intents.apply_one(store, beat or beat_for(store, coc=coc),
                                         row(kind, body, uid, ident), NOW))


def state_of(store, kind):
    return asyncio.run(store.get_state(CLAN.alias, kind))


def poll_state(**extra):
    return dict({"poll_id": "p1", "message_id": 3, "votes": {}}, **extra)


def with_challenges(store, **blocks):
    state = challenges.empty()
    for name, value in blocks.items():
        state[name] = value
    asyncio.run(challenges.save(store, CLAN.alias, state))


def reported(store):
    return ((store.kv.get(f"{REPORTS_KEY}{CLAN.alias}") or {}).get("rows") or [])


def test_ogni_gesto_del_membro_ha_il_suo_posto_nel_registro():
    assert intents.KINDS_MEMBER == acts.KINDS_MEMBER == GESTI
    assert set(acts.FIELDS) == set(intents.REGISTRY)
    for kind in acts.KINDS_MEMBER:
        action, handler = intents.REGISTRY[kind]
        assert callable(handler), kind
        assert acts.LEVELS[kind] == settings.ACTIONS.get(action), kind
    assert acts.LEVELS["availability.set"] is None
    assert all(acts.LEVELS[kind] is None for kind in acts.TARGET_OWN)
    assert acts.LEVELS["target.clear"] == settings.LIMITED
    assert acts.AVAIL == availability.OPTIONS


def test_il_registro_resta_aperto_ai_gesti_dei_blocchi_dopo():
    kind = "blocco.dopo"
    acts.FIELDS[kind] = dict(acts.FIELDS["target.mirror"])
    try:
        intents.register(kind, None, intents.targets_act)
        assert intents.REGISTRY[kind] == (None, intents.targets_act)
        assert kind not in intents.KINDS_MEMBER
    finally:
        acts.FIELDS.pop(kind)
        intents.REGISTRY.pop(kind, None)


def test_il_dentro_o_fuori_dall_app_vota_come_il_bottone_di_oggi(tmp_path):
    store = app_store(tmp_path, war=WAR)
    asyncio.run(store.set_state(CLAN.alias, availability.STATE, poll_state(war=war_key(WAR))))
    assert applied(store, "availability.set", {"choice": "out"}) is True
    assert state_of(store, availability.STATE)["votes"] == {
        "11": {"name": "Toad", "option": availability.OUT}}
    seats = store.pages[(CLAN.alias, "app")][1]["seats"]
    assert seats["11"]["avail"] == "out" and seats["7"]["avail"] is None
    assert applied(store, "availability.set", {"choice": "pinco"}, ident="a2") == reasons.BAD
    assert state_of(store, availability.STATE)["votes"]["11"]["option"] == availability.OUT


def test_senza_sondaggio_aperto_la_disponibilita_non_si_inventa(tmp_path):
    store = app_store(tmp_path, war=WAR)
    assert applied(store, "availability.set", {"choice": "in"}) == reasons.CLOSED
    assert state_of(store, availability.STATE) is None


def test_l_obiettivo_scelto_dall_app_finisce_fra_quelli_del_clan(tmp_path):
    store = app_store(tmp_path, players=VILLAGES)
    assert applied(store, "goal.set", {"goal": "trophies", "target": "4500"}) is True
    assert state_of(store, "goals") == {"#P4": {"kind": "trophies", "hero": None, "target": 4500}}
    assert applied(store, "goal.set", {"goal": "trophies", "target": "4321"}, ident="b2") == reasons.BAD
    assert state_of(store, "goals")["#P4"]["target"] == 4500


def test_chi_non_ha_il_villaggio_collegato_non_muove_niente(tmp_path):
    store = app_store(tmp_path, players=VILLAGES)
    assert applied(store, "goal.set", {"goal": "trophies", "target": "4500"}, uid=999) == reasons.NOT_LINKED
    assert state_of(store, "goals") is None and store.pages == {}


def test_il_villaggio_dichiarato_dall_app_non_conta(tmp_path):
    store = app_store(tmp_path, players=VILLAGES)
    forged = row("goal.set", {"goal": "trophies", "target": "4500"}, uid=11)
    forged["body"]["tag"] = "#P1"
    assert asyncio.run(intents.apply_one(store, beat_for(store), forged, NOW)) is True
    assert list(state_of(store, "goals")) == ["#P4"]


def test_il_membro_senza_livello_non_assegna_i_bersagli(tmp_path):
    store = app_store(tmp_path, war=WAR)
    assert applied(store, "target.set", {"pos": "3", "who": "1"}, uid=11) == reasons.TAKEN
    assert state_of(store, "plan") is None


def plain_store(tmp_path):
    store = app_store(tmp_path, war=WAR)
    asyncio.run(store.set_state(CLAN.alias, "members", member_snapshot(clan_json(SEMPLICE))))
    store.links = list(LINKS) + [PEACH]
    return store


def test_il_membro_prenota_una_base_libera_per_il_suo_posto(tmp_path):
    store = plain_store(tmp_path)
    assert applied(store, "target.set", {"pos": "1", "who": "3"}, uid=13) is True
    assert state_of(store, "plan")["targets"] == {"1": {"tag": "#P3", "name": "Peach"}}
    assert applied(store, "target.free", {"pos": "1"}, uid=13, ident="m2") is True
    assert state_of(store, "plan") is None


def test_il_membro_prende_il_suo_specchio_e_scrive_il_piano(tmp_path):
    store = plain_store(tmp_path)
    assert applied(store, "target.mirror", {}, uid=13) is True
    assert state_of(store, "plan")["targets"] == {"3": {"tag": "#P3", "name": "Peach"}}
    assert applied(store, "target.note", {"pos": "3", "text": "regine prima"}, uid=13,
                   ident="m2") is True
    assert state_of(store, "plan")["targets"]["3"]["note"] == "regine prima"


def test_il_membro_non_tocca_il_posto_e_la_base_di_un_altro(tmp_path):
    store = plain_store(tmp_path)
    assert applied(store, "target.set", {"pos": "1", "who": "1"}, uid=13) == reasons.TAKEN
    assert applied(store, "target.clear", {}, uid=13, ident="m2") == reasons.NOT_MANAGER
    assert state_of(store, "plan") is None
    assert applied(store, "target.set", {"pos": "2", "who": "2"}, uid=7, ident="m3") is True
    assert applied(store, "target.set", {"pos": "2", "who": "3"}, uid=13, ident="m4") == reasons.TAKEN
    assert applied(store, "target.free", {"pos": "2"}, uid=13, ident="m5") == reasons.TAKEN
    assert applied(store, "target.note", {"pos": "2", "text": "mia"}, uid=13, ident="m6") == reasons.TAKEN
    assert state_of(store, "plan")["targets"] == {"2": {"tag": "#P2", "name": "Luigi"}}
    assert applied(store, "target.swap", {"pos": "2"}, uid=13, ident="m7") is True
    assert state_of(store, "plan")["targets"]["2"]["swap"] is True


def test_chi_ha_gia_una_base_non_ne_prende_una_seconda(tmp_path):
    store = plain_store(tmp_path)
    assert applied(store, "target.set", {"pos": "1", "who": "3"}, uid=13) is True
    assert applied(store, "target.set", {"pos": "2", "who": "3"}, uid=13, ident="m2") == reasons.TAKEN
    assert applied(store, "target.mirror", {}, uid=13, ident="m3") == reasons.TAKEN
    assert state_of(store, "plan")["targets"] == {"1": {"tag": "#P3", "name": "Peach"}}
    assert applied(store, "target.set", {"pos": "1", "who": "3"}, uid=13, ident="m4") is True
    assert applied(store, "target.free", {"pos": "1"}, uid=13, ident="m5") is True
    assert applied(store, "target.set", {"pos": "2", "who": "3"}, uid=13, ident="m6") is True
    assert state_of(store, "plan")["targets"] == {"2": {"tag": "#P3", "name": "Peach"}}


def test_lo_specchio_gia_preso_non_si_ruba(tmp_path):
    store = plain_store(tmp_path)
    assert applied(store, "target.set", {"pos": "3", "who": "1"}, uid=7) is True
    assert applied(store, "target.mirror", {}, uid=13, ident="m2") == reasons.TAKEN
    assert state_of(store, "plan")["targets"] == {"3": {"tag": "#P1", "name": "Mario"}}


def test_il_gestore_assegna_come_prima(tmp_path):
    store = app_store(tmp_path, war=WAR)
    assert applied(store, "target.set", {"pos": "3", "who": "1"}, uid=7) is True
    assert state_of(store, "plan")["targets"] == {"3": {"tag": "#P1", "name": "Mario"}}
    assert applied(store, "target.clear", {}, uid=7, ident="c2") is True
    assert state_of(store, "plan") is None


def test_il_gestore_sospeso_non_assegna_piu(tmp_path):
    store = app_store(tmp_path, war=WAR)
    assert applied(store, "target.set", {"pos": "3", "who": "1"}, uid=7) is True
    asyncio.run(store.kv_set(guard.suspended_key(CLAN.alias, 7), {"at": 1}))
    assert applied(store, "target.clear", {}, uid=7, ident="c3") == reasons.NOT_MANAGER
    assert state_of(store, "plan")["targets"]


def test_il_piano_scritto_sta_sulla_prenotazione(tmp_path):
    store = app_store(tmp_path, war=WAR)
    assert applied(store, "target.set", {"pos": "3", "who": "1"}, uid=7) is True
    assert applied(store, "target.note", {"pos": "3", "text": "regine prima"}, uid=7,
                   ident="n1") is True
    assert state_of(store, "plan")["targets"]["3"] == {"tag": "#P1", "name": "Mario",
                                                       "note": "regine prima"}
    assert applied(store, "target.note", {"pos": "2", "text": "niente"}, uid=7,
                   ident="n2") == reasons.TAKEN
    assert acts.checked({"kind": "target.note", "id": "n3", "pos": "3",
                         "text": "x" * (leaders.TEXT_MAX + 1)}, "#P1", 7) is None
    assert acts.checked({"kind": "target.note", "id": "n3", "pos": "3",
                         "text": "x" * leaders.TEXT_MAX}, "#P1", 7)["pos"] == "3"


def test_chiedere_il_cambio_avvisa_chi_ha_prenotato(tmp_path):
    store = app_store(tmp_path, war=WAR)
    assert applied(store, "target.set", {"pos": "3", "who": "1"}, uid=7) is True
    assert applied(store, "target.swap", {"pos": "3"}, uid=9, ident="s1") is True
    assert state_of(store, "plan")["targets"]["3"]["swap"] is True
    detto = feed_rows(store, 7)
    assert len(detto) == 1 and "Yoshi" in detto[0] and "#3" in detto[0]
    assert feed_rows(store, 9) == []
    assert applied(store, "target.swap", {"pos": "3"}, uid=7, ident="s2") == reasons.TAKEN
    assert applied(store, "target.swap", {"pos": "2"}, uid=9, ident="s3") == reasons.TAKEN


def test_riassegnare_la_base_toglie_il_cambio_chiesto(tmp_path):
    store = app_store(tmp_path, war=WAR)
    assert applied(store, "target.set", {"pos": "3", "who": "1"}, uid=7) is True
    assert applied(store, "target.swap", {"pos": "3"}, uid=9, ident="s1") is True
    assert applied(store, "target.set", {"pos": "3", "who": "2"}, uid=7, ident="s2") is True
    assert state_of(store, "plan")["targets"]["3"] == {"tag": "#P2", "name": "Luigi"}


def test_senza_guerra_i_bersagli_non_si_toccano(tmp_path):
    store = app_store(tmp_path)
    assert applied(store, "target.mirror", {}, uid=7) == reasons.NOT_IN_WAR
    assert state_of(store, "plan") is None


def test_le_risposte_alle_sfide_entrano_nei_sondaggi_di_oggi(tmp_path):
    store = app_store(tmp_path)
    with_challenges(store,
                    quiz={"open": poll_state(id=quizbank.QUESTIONS[0]["id"], occurrence="x"),
                          "used": [], "last": None},
                    awards={"given": [], "vote": poll_state(season="2026-09", rows=VOTE_ROWS,
                                                            ends=0)})
    asyncio.run(store.set_state(CLAN.alias, predictions.state_key("war"),
                                poll_state(war=war_key(WAR))))
    assert applied(store, "quiz.answer", {"option": "2"}) is True
    assert applied(store, "award.vote", {"option": "1"}, ident="e2") is True
    assert applied(store, "prediction.set", {"poll": "war", "option": "3"}, ident="e3") is True
    fresh = asyncio.run(challenges.load(store, CLAN.alias))
    assert fresh["quiz"]["open"]["votes"] == {"11": {"name": "Toad", "option": 2}}
    assert fresh["awards"]["vote"]["votes"]["11"]["option"] == 1
    assert state_of(store, predictions.state_key("war"))["votes"]["11"]["option"] == 3
    assert applied(store, "quiz.answer", {"option": "9"}, ident="e4") == reasons.CLOSED
    assert applied(store, "award.vote", {"option": "5"}, ident="e5") == reasons.CLOSED
    assert applied(store, "prediction.set", {"poll": "pinco", "option": "1"}, ident="e6") == reasons.BAD


def test_il_duello_proposto_dall_app_aspetta_il_si_dell_altro(tmp_path):
    store = app_store(tmp_path)
    assert applied(store, "duel.challenge",
                   {"rival": "#P1", "metric": "donated", "duration": "week"}) is True
    duel = asyncio.run(challenges.load(store, CLAN.alias))["duels"]["open"][0]
    assert duel["status"] == "proposed"
    assert {duel["a"]["tag"], duel["b"]["tag"]} == {"#P4", "#P1"}
    assert applied(store, "duel.accept", {"duel": duel["id"]}, uid=11, ident="f2") == reasons.GONE
    assert applied(store, "duel.accept", {"duel": duel["id"]}, uid=7, ident="f3") is True
    after = asyncio.run(challenges.load(store, CLAN.alias))["duels"]["open"][0]
    assert after["status"] in ("pending", "open")


def test_il_duello_contro_se_stessi_o_con_una_misura_finta_non_parte(tmp_path):
    store = app_store(tmp_path)
    assert applied(store, "duel.challenge",
                   {"rival": "#P4", "metric": "donated", "duration": "week"}) == reasons.BAD
    assert applied(store, "duel.challenge",
                   {"rival": "#P1", "metric": "pinco", "duration": "week"}, ident="g2") == reasons.TAKEN
    assert asyncio.run(challenges.load(store, CLAN.alias))["duels"]["open"] == []


def test_la_segnalazione_passa_dal_freno_gia_scritto(tmp_path):
    store = app_store(tmp_path)
    assert applied(store, "report.send", {"reason": "harassment"}) is True
    rows = reported(store)
    assert len(rows) == 1 and rows[0]["reason"] == "harassment" and rows[0]["by"] == 11
    assert applied(store, "report.send", {"reason": "pinco"}, ident="d2") == reasons.BAD
    assert len(reported(store)) == 1


def test_due_intenti_uguali_fanno_un_solo_effetto(tmp_path):
    store = app_store(tmp_path)
    store.queued = [row("report.send", {"reason": "scam"}, ident="z9", number=1),
                    row("report.send", {"reason": "scam"}, ident="z9", number=2)]
    assert asyncio.run(intents.drain(store, beat_for(store), NOW)) == 1
    assert len(reported(store)) == 1 and store.done == [1, 2]


def test_un_intento_senza_gestore_esce_dalla_coda_senza_effetti(tmp_path):
    store = app_store(tmp_path)
    store.queued = [row("pinco.pallino", {}, number=4)]
    assert asyncio.run(intents.drain(store, beat_for(store), NOW)) == 0
    assert store.done == [4] and store.pages == {}


def test_chi_cancella_i_suoi_dati_dall_app_si_porta_via_il_posto(tmp_path):
    store = app_store(tmp_path)
    assert applied(store, "report.send", {"reason": "spam"}) is True
    asyncio.run(feed.add(store, CLAN.alias, 11, "goal.done", "Roba di Toad", NOW))
    assert store.pages[(CLAN.alias, "app")][1]["seats"]["11"]["tag"] == "#P4"
    assert applied(store, "data.forget", {"sure": "no"}, ident="h1") == reasons.REFUSED
    assert [one.tag for one in store.links] == ["#P1", "#P5", "#P4"]
    assert applied(store, "data.forget", {"sure": "yes"}, ident="h2") is True
    assert [one.tag for one in store.links] == ["#P1", "#P5"]
    assert asyncio.run(feed.rows(store, CLAN.alias, 11)) == []
    assert reported(store) == []
    seats = store.pages[(CLAN.alias, "app")][1]["seats"]
    assert "11" not in seats and "7" in seats


def test_la_chiave_del_gesto_gia_fatto_non_porta_numeri_in_chiaro(tmp_path):
    store = app_store(tmp_path, players=VILLAGES)
    assert applied(store, "goal.set", {"goal": "trophies", "target": "4500"}) is True
    marks = [key for key in store.kv if key.startswith("intent:")]
    assert marks == [intents.once_key(store, {"by": 11, "id": "a1"})]
    assert "11:a1" not in marks[0] and marks[0] != intents.once_key(store, {"by": 7, "id": "a1"})
    assert intents.once_key(store, {"by": 11}) == ""


class Prepared:
    def __init__(self, ident):
        self.id = ident


class ShareBot:
    def __init__(self):
        self.asked = []

    async def save_prepared_inline_message(self, user_id, result, **extra):
        self.asked.append((user_id, result, extra))
        return Prepared("prep-1")


class OneBot:
    def __init__(self, bot):
        self.bot = bot

    def owner_bot(self):
        return self.bot


WALKED = {"#P1": {"name": "Mario", "week": {"since": 1}, "month": {"since": 1},
                  "now": {"donated": 40, "war_stars": 5, "levels": 3}},
          "#P4": {"name": "Toad", "week": {"since": 1}, "month": {"since": 1},
                  "now": {"donated": 10, "war_stars": 1, "levels": 0}}}


def share_beat(store, bot, walked=None):
    asyncio.run(store.set_state(CLAN.alias, "progress", walked or WALKED))
    beat = beat_for(store, supervisor=OneBot(bot))
    conf = settings.effective(asyncio.run(store.get_state(CLAN.alias, "settings")), None)
    asyncio.run(beat.app(CLAN, conf, MEMBERS, INFO, NOW))
    return beat


def season_walked():
    closed = {"until": progress.period_start(NOW, TZ, recap.PERIOD), "since": 0, "score": 120,
              "wins": 40, "war_stars": 30, "donated": 900, "levels": 6}
    return {tag: dict(row, last_month=dict(closed)) for tag, row in WALKED.items()}


def test_condividi_la_settimana_prepara_il_messaggio_col_disegno_del_bot(tmp_path):
    media.forget()
    store = app_store(tmp_path, players=VILLAGES)
    store.url = "https://esempio.test"
    bot = ShareBot()
    beat = share_beat(store, bot)
    assert applied(store, "share.week", {}, beat=beat) is True
    uid, result, _ = bot.asked[0]
    token = share_cards.token_for(store.vault, CLAN.alias, 11, share_cards.WEEK)
    assert uid == 11 and result.photo_url == share_cards.card_url(store.url, token)
    ready = store.kv.get(share_cards.ready_key(CLAN.alias, 11)) or {}
    assert ready == {"id": "prep-1", "mark": "a1"}
    assert share_cards.png_of(store.kv.get(share_cards.card_key(token)))[:4] == b"\x89PNG"


def test_senza_sito_non_si_prepara_niente_da_condividere(tmp_path):
    media.forget()
    store = app_store(tmp_path, players=VILLAGES)
    bot = ShareBot()
    beat = share_beat(store, bot)
    assert applied(store, "share.week", {}, beat=beat) == reasons.GONE
    assert bot.asked == []


def test_condividi_la_stagione_prepara_la_card_del_riepilogo(tmp_path):
    media.forget()
    store = app_store(tmp_path, players=VILLAGES)
    store.url = "https://esempio.test"
    bot = ShareBot()
    beat = share_beat(store, bot, season_walked())
    assert applied(store, "share.season", {}, beat=beat) is True
    uid, result, _ = bot.asked[0]
    token = share_cards.token_for(store.vault, CLAN.alias, 11, share_cards.SEASON)
    assert uid == 11 and result.photo_url == share_cards.card_url(store.url, token)
    assert token != share_cards.token_for(store.vault, CLAN.alias, 11, share_cards.WEEK)
    assert share_cards.png_of(store.kv.get(share_cards.card_key(token)))[:4] == b"\x89PNG"
    assert acts.LEVELS["share.season"] is None


def test_senza_stagione_chiusa_non_si_condivide_il_riepilogo(tmp_path):
    media.forget()
    store = app_store(tmp_path, players=VILLAGES)
    store.url = "https://esempio.test"
    bot = ShareBot()
    beat = share_beat(store, bot)
    assert applied(store, "share.season", {}, beat=beat) == reasons.GONE
    assert bot.asked == []


def test_la_card_del_clan_la_condivide_chi_gestisce(tmp_path):
    media.forget()
    store = app_store(tmp_path, players=VILLAGES)
    store.url = "https://esempio.test"
    bot = ShareBot()
    beat = share_beat(store, bot)
    assert applied(store, "share.clan", {}, uid=9, beat=beat) is True
    assert bot.asked[0][0] == 9
    assert acts.LEVELS["share.clan"] == settings.ACTIONS[acts.TOOLS]
    assert acts.LEVELS["share.week"] is None


def test_la_card_di_fine_guerra_si_condivide_come_immagine(tmp_path):
    media.forget()
    store = app_store(tmp_path, war=war_snapshot(war_json("warEnded",
                                                          {"#P1": [("#E1", 3, 100.0)]})))
    store.url = "https://esempio.test"
    bot = ShareBot()
    beat = share_beat(store, bot)
    assert applied(store, "share.war", {}, beat=beat) is True
    uid, result, _ = bot.asked[0]
    token = share_cards.token_for(store.vault, CLAN.alias, 11, share_cards.WAR)
    assert uid == 11 and result.photo_url == share_cards.card_url(store.url, token)
    assert token != share_cards.token_for(store.vault, CLAN.alias, 11, share_cards.WEEK)
    assert share_cards.png_of(store.kv.get(share_cards.card_key(token)))[:4] == b"\x89PNG"
    assert acts.LEVELS["share.war"] is None


def test_senza_guerra_finita_non_si_condivide_la_card(tmp_path):
    media.forget()
    store = app_store(tmp_path, war=WAR)
    store.url = "https://esempio.test"
    bot = ShareBot()
    beat = share_beat(store, bot)
    assert applied(store, "share.war", {}, beat=beat) == reasons.NOT_IN_WAR
    assert bot.asked == []


def test_la_lingua_si_cambia_dall_app(tmp_path):
    store = app_store(tmp_path)
    assert applied(store, "lang.set", {"lang": "en"}) is True
    assert [one.lang for one in store.links if one.user_id == 11] == ["en"]
    assert applied(store, "lang.set", {"lang": "klingon"}, ident="a2") == reasons.BAD
    assert [one.lang for one in store.links if one.user_id == 11] == ["en"]


class MenuBot:
    def __init__(self, broken=False):
        self.menus = []
        self.broken = broken

    async def set_chat_menu_button(self, chat_id=None, menu_button=None):
        if self.broken:
            raise TelegramError("no")
        self.menus.append((chat_id, menu_button))
        return True


def menu_beat(store, bot):
    return beat_for(store, supervisor=OneBot(bot))


def test_aprire_l_app_mette_il_tabellone_nel_menu_del_bot_console(tmp_path):
    media.forget()
    store = app_store(tmp_path)
    store.url = "https://esempio.test"
    bot = MenuBot()
    assert applied(store, "app.opened", {}, beat=menu_beat(store, bot)) is True
    chat_id, button = bot.menus[0]
    slug = payload.slug_for(store.vault, CLAN.alias)
    assert chat_id == 11
    assert button.web_app.url == f"https://esempio.test/app/{slug}"
    assert button.text == i18n.locale("en").t("web.app.menu")


def test_senza_sito_o_senza_bot_il_menu_resta_com_e(tmp_path):
    media.forget()
    store = app_store(tmp_path)
    bot = MenuBot()
    assert applied(store, "app.opened", {}, beat=menu_beat(store, bot)) == reasons.GONE
    assert bot.menus == []
    media.forget()
    store.url = "https://esempio.test"
    rotto = MenuBot(broken=True)
    assert applied(store, "app.opened", {}, ident="a2", beat=menu_beat(store, rotto)) == reasons.GONE


def test_il_tabellone_si_apre_anche_senza_posto_nel_clan():
    assert "app.opened" in acts.NO_SEAT
    assert acts.LEVELS["app.opened"] is None
    assert acts.FIELDS["app.opened"] == {}


def test_ogni_rifiuto_del_gestore_porta_il_suo_codice(tmp_path):
    store = app_store(tmp_path, players=VILLAGES)
    assert reasons.code_of(applied(store, "goal.set", {"goal": "trophies", "target": "4321"},
                                   ident="z1")) == reasons.BAD
    assert reasons.code_of(applied(store, "goal.set", {"goal": "trophies", "target": "4500"},
                                   uid=999, ident="z2")) == reasons.NOT_LINKED
    assert reasons.code_of(applied(store, "target.set", {"pos": "3", "who": "1"},
                                   ident="z3")) == reasons.NOT_IN_WAR
    assert reasons.code_of(applied(store, "report.send", {"reason": "pinco"},
                                   ident="z4")) == reasons.BAD


def test_il_bersaglio_di_un_altro_si_rifiuta_dicendo_che_e_preso(tmp_path):
    store = plain_store(tmp_path)
    assert applied(store, "target.set", {"pos": "3", "who": "9"}, uid=13, ident="z5") == reasons.TAKEN
    assert reasons.code_of(applied(store, "target.set", {"pos": "3", "who": "9"}, uid=13,
                                   ident="z6")) == reasons.TAKEN


def test_il_gesto_di_un_clan_sparito_dice_che_non_c_e_piu(tmp_path):
    store = app_store(tmp_path, players=VILLAGES)
    lost = row("goal.set", {"goal": "trophies", "target": "4500"})
    lost["clan"] = "clan-mai-esistito"
    outcome = asyncio.run(intents.apply_one(store, beat_for(store), lost, NOW))
    assert reasons.code_of(outcome) == reasons.GONE


def test_lo_stesso_gesto_due_volte_dice_che_era_gia_fatto(tmp_path):
    store = app_store(tmp_path, players=VILLAGES)
    assert applied(store, "goal.set", {"goal": "trophies", "target": "4500"}, ident="z7") is True
    assert reasons.code_of(applied(store, "goal.set", {"goal": "trophies", "target": "4500"},
                                   ident="z7")) == reasons.TAKEN


def _alias_dei_motivi(albero):
    moduli, presi = set(), {}
    for node in ast.walk(albero):
        if isinstance(node, ast.Import):
            for one in node.names:
                if one.name.split(".")[-1] == "reasons":
                    moduli.add(one.asname or one.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            for one in node.names:
                if (node.module or "").split(".")[-1] == "reasons":
                    presi[one.asname or one.name] = one.name
                elif one.name == "reasons":
                    moduli.add(one.asname or one.name)
    return moduli, presi


def _scritti_nel_file(testo, nomi):
    albero = ast.parse(testo)
    moduli, presi = _alias_dei_motivi(albero)
    trovati = set()
    for node in ast.walk(albero):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in moduli and node.attr in nomi:
                trovati.add(nomi[node.attr])
        elif isinstance(node, ast.Name) and nomi.get(presi.get(node.id, "")):
            trovati.add(nomi[presi[node.id]])
    return trovati


def _codici_scritti():
    radice = Path(intents.__file__).parent
    nomi = {nome: code for nome, code in vars(reasons).items()
            if nome.isupper() and isinstance(code, str)}
    trovati = {reasons.code_of("fuori catalogo")}
    for path in sorted(radice.rglob("*.py")):
        if path.name == "reasons.py":
            continue
        trovati.update(_scritti_nel_file(path.read_text(encoding="utf-8"), nomi))
    return trovati


def test_ogni_motivo_ha_chi_lo_scrive_o_e_dichiarato_in_attesa():
    assert set(reasons.RESERVED) < set(reasons.REASONS)
    assert sorted(set(reasons.REASONS) - _codici_scritti()) == sorted(reasons.RESERVED)


def test_un_codice_inventato_non_esce_dal_modulo_dei_motivi():
    import pytest as _pytest

    with _pytest.raises(ValueError):
        reasons.refuse("motivo-inventato")
    assert reasons.code_of(True) == reasons.REFUSED and reasons.code_of(False) == reasons.REFUSED
    assert reasons.refuse(reasons.BAD) == reasons.BAD
    assert reasons.done(True) is True and reasons.done(reasons.BAD) is False
