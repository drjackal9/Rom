from datetime import datetime, timezone
from types import SimpleNamespace

from clashbot import agenda, events, i18n, leaderboards as boards, render, scoring, source
from clashbot.targets import mirror_plan, plan_rows
from fixtures import BASE_MEMBERS, clan_json, war_json

NOW = datetime(2026, 9, 11, 12, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 12, 7, 30, tzinfo=timezone.utc)
L = i18n.locale("it")
TZ = "Europe/Rome"


def test_new_views_render():
    members = events.member_snapshot(clan_json(BASE_MEMBERS))
    war = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E2", 2, 70)]}))
    plan = mirror_plan(war)
    names = {"#P2": '<a href="tg://user?id=5">Luigi</a>'}
    text = render.render_reminder(L, TZ, war, 14400, now=NOW, names=names, plan=plan)
    assert "tg://user?id=5" in text and "🎯 #2 Wario" in text
    m = events.missing_attackers(war)[0]
    assert "PROMEMORIA" in render.dm_reminder(L, TZ, war, m, now=NOW, plan=plan)
    assert "Municipio 15" in render.achievements_card(L, [
        {"type": "th", "name": "Mario", "level": 15}, {"type": "hero", "name": "Mario", "hero": "Regina", "level": 65},
        {"type": "league", "name": "Mario", "league": "Master"}, {"type": "warstars", "name": "Mario", "value": 1000},
        {"type": "record", "name": "Mario", "value": 5010}])
    assert "AGENDA" in render.agenda_view(L, TZ, agenda.upcoming(NOW), NOW)
    for item in agenda.upcoming(NOW):
        for phase in ("tomorrow", "start", "last"):
            render.agenda_announcement(L, TZ, item, phase, NOW)
    season = scoring.empty_season("2026-09")
    ended = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)]}))
    record = events.war_record(ended)
    scoring.apply_war(season, record)
    scoring.apply_prediction(season, 1, "Alex", True)
    text = render.points_view(L, season, scoring.leaderboard(season), scoring.streaks([record, record, record]))
    assert "Mario" in text and "🔥3" in text and "Veggenti" in text
    assert "TITOLI" in render.season_end_card(L, "2026-09", scoring.titles(season), scoring.leaderboard(season))
    hall = [{"season": "2026-08", "titles": {"MVP": ["Mario", 80]}}]
    assert "agosto 2026" in render.hall_view(L, hall)
    assert "Vuoto" in render.hall_view(L, [])
    players = {"#P1": {"name": "Mario", "th": 16, "warPref": "in", "heroes": {"Barbarian King": 95, "Archer Queen": 95}},
               "#P2": {"name": "Luigi", "th": 15, "warPref": "out", "heroes": {}}}
    assert "Fuori · 1" in render.ready_view(L, players, members)
    assert "👑95" in render.heroes_view(L, players, members)
    rows = plan_rows(war, plan)
    assert "BERSAGLI · 3/3" in render.targets_view(L, rows, war)
    assert "IL TUO BERSAGLIO" in render.my_targets_view(L, "Luigi", rows, [2])
    link = SimpleNamespace(alias="link-1", user_id=5, tag="#P1", name="Mario", dm=True)
    snap = {"#P1": {"name": "Mario", "th": 16, "league": "Legend", "trophies": 5600, "best": 5800, "warStars": 1200,
                    "heroes": {"Barbarian King": 95}, "donations": 3000, "warPref": "in"}}
    assert "IL TUO PROFILO" in render.me_view(L, [link], snap)
    assert "collega" in render.not_linked_me(L, "FuturoCoCBot")
    for fn in (render.link_ask_tag, render.onboard_ask_clan):
        assert "annulla" in fn(L)
    assert "Mario" in render.link_ask_token(L, "Mario", "#P1") and "Mario" in render.link_done(L, "Mario", "#P1")
    assert "Futuro" in render.onboard_ask_player(L, "Futuro") and "Mario" in render.onboard_ask_token(L, "Mario")
    assert "/setclan #ABC" in render.onboard_ready(L, "Futuro", "#ABC")
    family = SimpleNamespace(alias="fam-1", name="Futuro", owner_id=1, chat_id=None)
    rows = [{"alias": "clan-1", "chat_id": 1, "tag": "#ABC", "name": "Futuro", "level": 12, "members": 46, "league": "Crystal I", "min_th": 13, "note": "attivi"}]
    assert "4 posti" in render.family_view(L, family, rows)
    assert "TH13+" in render.recruit_board(L, TZ, family, rows, NOW)
    assert "DIGEST" in render.digest_card(L, family, [{"name": "Futuro", "wars": 2, "wins": 1, "losses": 1, "ties": 0, "stars": 60}],
                                          [("Mario", 12, "Futuro")], [("Luigi", 900, "Futuro")], [("Peach", 40000, "Futuro")])
    assert "passa da" in render.transfer_card(L, "Mario", "Futuro", "Futuro 2")
    clan = SimpleNamespace(name="Futuro")
    assert "Tutto in ordine" in render.leader_report(L, clan, [], [], [])
    assert "Mario" in render.leader_report(L, clan, [("Mario", 2)], ["Luigi"], ["Peach"])
    options = [L.t(f"poll.option.{i}") for i in range(scoring.POLL_OPTIONS)]
    assert "+3 pt" in render.prediction_result(L, 3, options, ["Alex"])


def test_english_locale_translates_the_same_cards():
    en = i18n.locale("en")
    war = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E2", 2, 70)]}))
    text = render.render_reminder(en, "Europe/London", war, 14400, now=NOW)
    assert "4 HOURS LEFT" in text and "Attacchi" not in text
    assert "NO WAR" in render.war_view(en, "UTC", None)
    assert "TARGETS · 0/0" in render.targets_view(en, [], None)


def test_italian_cards_are_unchanged():
    started = events.war_snapshot(war_json("inWar"))
    attacked = events.war_snapshot(war_json("inWar", our_attacks={"#P1": [("#E1", 3, 100)]},
                                            their_attacks={"#E2": [("#P3", 2, 78)]}))
    ended = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100)], "#P2": [("#E2", 2, 60), ("#E3", 1, 40)]},
                                         their_attacks={"#E2": [("#P3", 2, 78)]}))
    plan = mirror_plan(attacked)
    names = {"#P2": '<a href="tg://user?id=5">Luigi</a>'}
    raid = {"state": "ongoing", "startTime": "20260911T070000.000Z", "endTime": "20260912T200000.000Z",
            "members": [{"tag": "#P1", "name": "Mario", "attacks": 6, "attackLimit": 5, "bonusAttackLimit": 1,
                         "capitalResourcesLooted": 45000}],
            "capitalTotalLoot": 123456, "totalAttacks": 6, "enemyDistrictsDestroyed": 2}
    members = events.member_snapshot(clan_json(BASE_MEMBERS))

    assert render.render_war_events(L, TZ, events.war_events(started, attacked), attacked, "war", None, NOW) == (
        "💥 <b>ATTACCHI E DIFESE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🗡 <b>Mario</b> ➜ #1 <b>Bowser</b> · TH14\n"
        "      ⭐⭐⭐ 100% · 1º attacco\n"
        "🛡 <b>Wario</b> ➜ #3 <b>Peach</b>\n"
        "      ⭐⭐☆ 78%\n"
        "\n"
        "<blockquote>🏰 <b>3⭐</b> · 33,3%  ▰▰▰▱▱▱▱▱▱▱\n"
        "🏴 <b>2⭐</b> · 26,0%  ▰▰▰▱▱▱▱▱▱▱\n"
        "🟢 Avanti di 1 stella\n"
        "⏳ 22h 00m alla fine · sab 12/09 alle 12:00</blockquote>"
    )
    assert render.render_reminder(L, TZ, started, 14400, "war", None, LATER, names, plan) == (
        "⚠️ <b>MANCANO 4 ORE</b> · GUERRA\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ Fine sab 12/09 alle 12:00 (tra 2h 30m)\n"
        "\n"
        "🗡 <b>Attacchi da fare · 6</b>\n"
        "<blockquote>• <b>Mario</b> · 2 attacchi · 🎯 #1 Bowser\n"
        "• <a href=\"tg://user?id=5\">Luigi</a> · 2 attacchi · 🎯 #2 Wario\n"
        "• <b>Peach</b> · 2 attacchi · 🎯 #3 Waluigi</blockquote>\n"
        "\n"
        "Non riduciamoci all'ultimo minuto. 💪"
    )
    assert render.render_board(L, TZ, attacked, "war", None, NOW) == (
        "📌 <b>TABELLONE · GUERRA</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏰 <b>Nostro Clan</b>  🆚  🏴 <b>Clan Nemico</b>\n"
        "🏰 <b>3⭐</b> · 33,3%  ▰▰▰▱▱▱▱▱▱▱\n"
        "🏴 <b>2⭐</b> · 26,0%  ▰▰▰▱▱▱▱▱▱▱\n"
        "🟢 Avanti di 1 stella\n"
        "⏳ 22h 00m alla fine · sab 12/09 alle 12:00\n"
        "\n"
        "🗡 <b>Attacchi da fare · 5</b>\n"
        "<blockquote>Mario ·1   Luigi ·2   Peach ·2</blockquote>\n"
        "<i>aggiornato alle 14:00</i>"
    )
    assert render.render_war_end(L, ended, "win", "war", None) == (
        "🏆 <b>VITTORIA! 6⭐ – 2⭐</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<blockquote>🏰 <b>Nostro Clan</b> · <b>6⭐</b> · 66,7%\n"
        "🏴 <b>Clan Nemico</b> · <b>2⭐</b> · 26,0%</blockquote>\n"
        "\n"
        "🎖 <b>Migliori attaccanti</b>\n"
        "🥇 <b>Luigi</b> · 3⭐ · 50% medio\n"
        "🥈 <b>Mario</b> · 3⭐ · 100% medio\n"
        "✨ Triple totali: <b>1</b>\n"
        "\n"
        "😴 Attacchi saltati: Mario (1), Peach (2)\n"
        "\n"
        "Grande guerra, ragazzi. 🎉"
    )
    assert render.capital_view(L, TZ, raid, members, datetime(2026, 9, 12, 12, tzinfo=timezone.utc)) == (
        "🏛 <b>CAPITALE · WEEKEND IN CORSO</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<blockquote>💰 Bottino: <b>123.456</b>\n"
        "⚔️ Attacchi: <b>6</b>\n"
        "🏚 Distretti distrutti: <b>2</b></blockquote>\n"
        "⏳ Chiude sab 12/09 alle 22:00 (tra 8h 00m)\n"
        "\n"
        "⛏️ <b>Attacchi da fare · 3 membri</b>\n"
        "<blockquote>Luigi ·5   Peach ·5   Toad ·5</blockquote>"
    )


def activity_rows():
    return [
        {"tag": "#P1", "name": "Mario", "gold": 9000000, "elixir": 3300000, "dark": 800000, "loot": 12300000,
         "wins": 37, "games": 4000, "raid_loot": 120000, "capital_gold": 50000, "donated": 900, "war_stars": 12,
         "levels": 6, "th_up": 0, "score": 84, "since": "2026-09-07"},
        {"tag": "#P2", "name": "Luigi", "gold": 1500000, "elixir": 500000, "dark": 0, "loot": 2000000,
         "wins": 3, "games": 0, "raid_loot": 0, "capital_gold": 0, "donated": 200, "war_stars": 3,
         "levels": 14, "th_up": 1, "score": 70, "since": "2026-09-07"},
        {"tag": "#P3", "name": "Peach", "gold": 0, "elixir": 0, "dark": 0, "loot": 0,
         "wins": 12, "games": 500, "raid_loot": 0, "capital_gold": 0, "donated": 0, "war_stars": 0,
         "levels": 0, "th_up": 0, "score": 17, "since": "2026-09-07"},
        {"tag": "#P4", "name": "Toad", "gold": 0, "elixir": 0, "dark": 0, "loot": 0,
         "wins": 0, "games": 0, "raid_loot": 0, "capital_gold": 0, "donated": 0, "war_stars": 0,
         "levels": 0, "th_up": 0, "score": 0, "since": "2026-09-07"},
    ]


def test_board_view_farm_and_upgrade():
    rows = activity_rows()
    farm = boards.metric_rows("farm", rows)
    text = render.board_view(L, "farm", "week", farm)
    assert "questa settimana" in text and "🏹 <b>Farm</b>" in text
    assert "🥇 <b>Mario</b> · 12,3M 💰 · 0,8M ⚫" in text
    assert "🥈 <b>Luigi</b> · 2,0M 💰" in text
    assert "<b>Toad</b> · 0,0M" not in text
    assert "😴" not in text
    assert len(text) <= render.MAX_LEN
    upgrade = boards.metric_rows("upgrade", rows)
    text = render.board_view(L, "upgrade", "week", upgrade)
    assert "🥇 <b>Luigi</b> · +14 livelli · 🏠 +1" in text
    assert "🥈 <b>Mario</b> · +6 livelli" in text and "🥈 <b>Mario</b> · +6 livelli · 🏠" not in text
    en = i18n.locale("en")
    assert "+14 levels" in render.board_view(en, "upgrade", "month", upgrade)
    assert en.t("boards.period.month") in render.board_view(en, "upgrade", "month", upgrade)
    assert render.board_view(L, "farm", "week", []) == render.card(
        "🏹", render.board_label(L, "farm"), L.t("boards.empty"), L.t("boards.period.week"))


def test_the_clan_games_row_picks_the_plural_from_the_raw_count():
    ru = i18n.locale("ru")
    assert ru.t("activity.games_row", name="Mario", n=ru.n(4000), count=4000).endswith("очков")
    assert ru.t("activity.games_row", name="Mario", n=ru.n(1021), count=1021).endswith("очко")
    assert ru.t("activity.games_row", name="Mario", n=ru.n(1002), count=1002).endswith("очка")
    rows = [{"tag": "#P1", "name": "Mario", "value": 4000, "delta": 4000, "extra": 0}]
    assert ru.n(4000) + " очков" in render.board_view(ru, "games", "week", rows)
    pl = i18n.locale("pl")
    assert pl.n(4000) + " punktów" in render.board_view(pl, "games", "week", rows)


def test_activity_sections_in_the_existing_cards():
    season = scoring.empty_season("2026-09")
    ended = events.war_snapshot(war_json("warEnded", our_attacks={"#P1": [("#E1", 3, 100), ("#E2", 3, 100)]}))
    record = events.war_record(ended)
    scoring.apply_war(season, record)
    board = scoring.leaderboard(season)
    plain = render.points_view(L, season, board, {})
    assert "Attività del mese" not in plain
    assert render.points_view(L, season, board, {}, activity=None) == plain
    with_activity = render.points_view(L, season, board, {}, activity=activity_rows())
    assert "📈 <b>Attività del mese</b>" in with_activity
    assert "<b>Mario</b> · 84 pt attività" in with_activity
    family = SimpleNamespace(alias="fam-1", name="Futuro", owner_id=1, chat_id=None)
    clans = [{"alias": "clan-1", "chat_id": 1, "tag": "#ABC", "name": "Futuro", "level": 12, "members": 46,
              "league": "Crystal I", "min_th": 13, "note": "attivi"}]
    avg = [{"name": "Futuro", "avg": 42.0, "members": 46}, {"name": "Futuro 2", "avg": 18.4, "members": 30}]
    assert render.family_view(L, family, clans, activity=None) == render.family_view(L, family, clans)
    fam = render.family_view(L, family, clans, activity=avg)
    assert "📈 <b>Attività per membro</b>" in fam and "🥇 <b>Futuro</b> · 42 pt/membro" in fam
    zeros = [{"name": "Futuro", "avg": 0, "members": 46}, {"name": "Futuro 2", "avg": 0, "members": 30}]
    assert render.family_view(L, family, clans, activity=zeros) == render.family_view(L, family, clans)
    digest_rows = [{"name": "Futuro", "wars": 2, "wins": 1, "losses": 1, "ties": 0, "stars": 60}]
    plain_digest = render.digest_card(L, family, digest_rows, [], [], [])
    assert render.digest_card(L, family, digest_rows, [], [], [], activity=None) == plain_digest
    assert "🥈 <b>Futuro 2</b> · 18 pt/membro" in render.digest_card(L, family, digest_rows, [], [], [], activity=avg)
    assert render.digest_card(L, family, digest_rows, [], [], [], activity=zeros) == plain_digest
    clan = SimpleNamespace(name="Futuro")
    assert render.leader_report(L, clan, [], [], [], idle=None) == render.leader_report(L, clan, [], [], [])
    report = render.leader_report(L, clan, [], [], [], idle=[{"name": "Toad", "days": 7}])
    assert "😴 <b>Fermi da 7+ giorni</b>" in report and "Toad · 7 gg" in report
    many = [{"name": f"M{i}", "days": 30 - i} for i in range(25)]
    capped = render.leader_report(L, clan, [], [], [], idle=many)
    assert "M19" in capped and "M20" not in capped
    assert "Tutto in ordine" not in report


def test_activity_titles_have_icons_and_names():
    text = render.season_end_card(L, "2026-09", {"Farmer": ("Mario", 12300000), "Costruttore": ("Luigi", 14)},
                                  scoring.leaderboard(scoring.empty_season("2026-09")))
    assert "🏹 <b>Farmer</b> · Mario" in text and "🏗 <b>Costruttore</b> · Luigi" in text
    hall = [{"season": "2026-08", "titles": {"CampioneGiochi": ["Peach", 4000], "MVP": ["Mario", 80]}}]
    text = render.hall_view(L, hall)
    assert "🎮 Campione dei Giochi: <b>Peach</b>" in text and "🏆 MVP: <b>Mario</b>" in text
    en = i18n.locale("en")
    assert "Games Champion" in render.hall_view(en, hall) and "Builder" in render.season_end_card(
        en, "2026-09", {"Costruttore": ("Luigi", 14)}, [])


DONATE = "https://ko-fi.com/clanboard?ref=a&b=1"


def test_support_card_with_link_and_creator_code():
    text = render.support_card(L, DONATE, "CLANBOARD")
    assert text.startswith("💛 <b>" + L.t("support.title") + "</b>")
    assert L.t("support.intro") in text
    assert L.t("support.donate", url="https://ko-fi.com/clanboard?ref=a&amp;b=1") in text
    assert L.t("support.creator", code="CLANBOARD") in text
    assert render.quote(L.t("console.attribution")) in text
    assert L.t("support.none") not in text
    assert text.index(L.t("support.intro")) < text.index("ko-fi") < text.index("CLANBOARD")
    assert text.index("CLANBOARD") < text.index(L.t("console.attribution"))


def test_support_card_shows_only_what_is_configured():
    only_link = render.support_card(L, DONATE, None)
    assert "ko-fi.com" in only_link and "<code>" not in only_link
    assert L.t("support.intro") in only_link and L.t("support.none") not in only_link
    only_code = render.support_card(L, None, "CLANBOARD")
    assert L.t("support.creator", code="CLANBOARD") in only_code and "https://" not in only_code
    assert L.t("support.intro") in only_code
    for text in (only_link, only_code):
        assert L.t("console.attribution") in text


def test_support_card_without_anything_is_neutral():
    text = render.support_card(L, None, None)
    assert text == render.support_card(L, "", "")
    assert L.t("support.none") in text and L.t("support.intro") not in text
    assert "https://" not in text and "<code>" not in text
    assert render.quote(L.t("console.attribution")) in text
    assert render.quote(source.lines(L, None)) in text
    en = i18n.locale("en")
    english = render.support_card(en, None, "CLANBOARD")
    assert en.t("support.title") in english and en.t("console.attribution") in english
    assert L.t("support.title") not in english


def test_support_texts_promise_nothing_in_return():
    for code in ("it", "en"):
        catalog = i18n.locale(code)
        for key in ("support.intro", "support.donate", "support.creator", "support.none"):
            text = catalog.t(key, url="https://x", code="X").lower()
            assert not text.startswith("["), (code, key)
            assert "premium" not in text and "vip" not in text and "esclusiv" not in text and "exclusive" not in text


def test_share_card_spiega_come_passare_il_bot_e_chiude_col_link_personale():
    personal = "https://t.me/ClanBoardBot?start=ambXyZ"
    text = render.share_card(L, personal)
    assert text.startswith("🤝 <b>" + L.t("share.title") + "</b>")
    assert L.t("share.body") in text
    assert text.endswith(L.t("amb.invite", link=personal))
    plain = render.share_card(L)
    assert L.t("share.body") in plain and "https://" not in plain
    english = render.share_card(i18n.locale("en"))
    assert i18n.locale("en").t("share.title") in english and L.t("share.title") not in english


def test_me_view_mostra_prontezza_e_andamento():
    link = SimpleNamespace(tag="#P1", name="Mario", dm=True)
    snap = {"#P1": {"name": "Mario", "th": 13, "trophies": 5000, "best": 5200, "warStars": 900,
                    "league": "Crystal I", "heroes": {"Barbarian King": 75, "Archer Queen": 75},
                    "warPref": "in", "donations": 100, "labels": []}}
    trends = {"#P1": [{"d": "2026-09-11", "trophies": 4900}, {"d": "2026-09-12", "trophies": 5000}]}
    text = render.me_view(L, [link], snap, trends=trends)
    assert "🦸" in text and "75/75" in text
    assert "▁" in text or "█" in text


def test_me_view_senza_andamento_resta_la_scheda_semplice():
    link = SimpleNamespace(tag="#P1", name="Mario", dm=True)
    snap = {"#P1": {"name": "Mario", "th": 13, "trophies": 5000, "best": 5200, "warStars": 900,
                    "league": "Crystal I", "heroes": {"Barbarian King": 75}, "warPref": "in",
                    "donations": 100, "labels": []}}
    text = render.me_view(L, [link], snap)
    assert "🦸" in text and "📈" not in text


def test_il_profilo_non_promette_piu_promemoria_in_privato():
    link = SimpleNamespace(tag="#P1", name="Mario", dm=True)
    snap = {"#P1": {"name": "Mario", "th": 13, "trophies": 5000, "best": 5200, "warStars": 900,
                    "league": "Crystal I", "heroes": {"Barbarian King": 75}, "warPref": "in",
                    "donations": 100, "labels": []}}
    text = render.me_view(L, [link], snap)
    assert L.t("me.dm_on") not in text and L.t("me.dm_off") not in text


def test_heroes_view_mostra_il_tetto_del_municipio():
    players = {"#P1": {"th": 13, "heroes": {"Barbarian King": 70}}}
    members = {"#P1": {"name": "Mario"}}
    assert "70/75" in render.heroes_view(L, players, members)


def test_ready_view_mostra_la_prontezza_media():
    players = {"#P1": {"th": 13, "warPref": "in", "heroes": {"Barbarian King": 75, "Archer Queen": 75,
                                                             "Minion Prince": 60, "Grand Warden": 50,
                                                             "Royal Champion": 25}}}
    members = {"#P1": {"name": "Mario"}}
    assert "100" in render.ready_view(L, players, members)


def test_ready_view_tace_sulla_prontezza_se_non_ha_letto_nessuno():
    members = {"#P1": {"name": "Mario"}, "#P2": {"name": "Luigi"}}
    text = render.ready_view(L, {}, members)
    assert L.t("ready.unknown", n=2) in text
    assert "Prontezza" not in text


def test_la_carta_dei_traguardi_dice_le_stelle_guadagnate():
    text = render.achievements_card(L, [{"type": "stars", "name": "Mario", "goal": "Sweet Victory!",
                                         "stars": 2, "gained": 1}])
    assert "[ach.stars]" not in text
    assert L.t("ach.stars", name="Mario", goal="Sweet Victory!", n=1) in text
    assert "stella" in text and "Sweet Victory!" in text
    english = render.achievements_card(i18n.locale("en"), [
        {"type": "stars", "name": "Mario", "goal": "Sweet Victory!", "stars": 3, "gained": 2}])
    assert "2 stars" in english


def test_heroes_view_di_un_clan_al_massimo_resta_un_messaggio_valido():
    heroes = {"Barbarian King": 100, "Archer Queen": 100, "Minion Prince": 90,
              "Grand Warden": 75, "Royal Champion": 50}
    players = {f"#P{i}": {"th": 17, "heroes": heroes} for i in range(50)}
    members = {f"#P{i}": {"name": f"Giocatore{i}"} for i in range(50)}
    text = render.heroes_view(L, players, members)
    assert len(text) <= render.MAX_LEN
    assert not text.endswith("…")
    assert text.count("<blockquote>") == text.count("</blockquote>") == 1
    assert text.count("<b>") == text.count("</b>")


def test_player_card_mostra_etichette_e_prontezza():
    snap = {"name": "Mario", "th": 13, "trophies": 5000, "best": 5200, "warStars": 900,
            "league": "Crystal I", "heroes": {"Barbarian King": 75}, "warPref": "in",
            "donations": 100, "labels": ["Farming", "Clan Wars"]}
    text = render.player_card(L, snap, "#P1")
    assert "Mario" in text and "Farming" in text and "🦸" in text
    assert text.count("75/75") == 1
    assert text.count("👑") == 2


def test_vs_card_segna_il_vincitore_di_ogni_riga():
    rows = [{"key": "trophies", "mode": "n", "left": 5000, "right": 4800, "winner": "left"},
            {"key": "th", "mode": "plain", "left": 15, "right": 15, "winner": None}]
    text = render.vs_card(L, L.t("vs.title"), "Mario", "Luigi", rows)
    assert "Mario" in text and "Luigi" in text and "◀" in text and "=" in text
    assert "5.000" in text and "[vs.field.trophies]" not in text
    assert "🏷" not in text


def test_vs_card_mostra_le_etichette_dei_due_giocatori():
    rows = [{"key": "trophies", "mode": "n", "left": 5000, "right": 4800, "winner": "left"}]
    text = render.vs_card(L, L.t("vs.title"), "Mario", "Luigi", rows,
                          ["Farming", "Clan Wars"], ["Trophy Pushing"])
    assert "Mario 🏷 Farming · Clan Wars" in text
    assert "Luigi 🏷 Trophy Pushing" in text
    only_left = render.vs_card(L, L.t("vs.title"), "Mario", "Luigi", rows, ["Farming"], [])
    assert only_left.count("🏷") == 1


def test_le_etichette_del_clan_compaiono_nel_menu_e_nel_reclutamento():
    clan = SimpleNamespace(name="Futuro", tag="#ABC")
    info = {"level": 12, "members": 46, "league": "Crystal I", "streak": 3,
            "labels": ["Clan Wars", "Trophy Pushing"]}
    menu = render.menu_view(L, clan, info)
    assert "🏷" in menu and "Clan Wars" in menu and "Trophy Pushing" in menu
    assert "🏷" not in render.menu_view(L, clan, {"level": 12})
    family = SimpleNamespace(alias="fam-1", name="Futuro", owner_id=1, chat_id=None)
    rows = [{"alias": "clan-1", "chat_id": 1, "tag": "#ABC", "name": "Futuro", "level": 12,
             "members": 46, "league": "Crystal I", "min_th": 13, "note": "attivi",
             "labels": ["Clan Wars"]}]
    board = render.recruit_board(L, TZ, family, rows, NOW)
    assert "attivi · 🏷 Clan Wars" in board


def test_me_view_mostra_le_etichette_del_giocatore():
    link = SimpleNamespace(alias="link-1", user_id=5, tag="#P1", name="Mario", dm=True)
    snap = {"#P1": {"name": "Mario", "th": 16, "league": "Legend", "trophies": 5600, "best": 5800,
                    "warStars": 1200, "heroes": {"Barbarian King": 95}, "donations": 3000,
                    "warPref": "in", "labels": ["Farming"]}}
    assert "🏷 Farming" in render.me_view(L, [link], snap)
