import asyncio
import logging
import time
from datetime import timedelta
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram.error import TelegramError

from . import (agenda, awards, badges, base_packs, bases as bases_mod, bingo, boards, builder,
               capital, cards, challenges, cwl_bonus, cwl_cards, cwl_roster, cwl_scout,
               cwl_season, cwl_store, cwl_table, delivery, derby, diagnostics, duels,
               family as family_mod, familyroom, feed, games, goals as goals_mod,
               guard as guard_mod, i18n, ics,
               key_watch, leader_jobs, leaderboards, legend as legend_mod, media, missions,
               news_feed, night,
               pinned, predictions, privacy, progress as progress_mod, quiet, quiz, rankings,
               recruit, recruit_jobs, render, roles, roster as roster_mod, scoring, scouting,
               stickers, survey, topics, tourney_results,
               tourney_ui, tournaments, trend as trend_mod, twitch_jobs, war_live, warstats, webmenu,
               whisper)
from .achievements import player_events, player_snapshot
from .cwl import current_round, group_summary, war_summary
from .events import (capital_events, due_reminders, member_events, member_facts, member_snapshot,
                     member_stats, missing_attackers, orient_war, war_end_fact, war_events,
                     war_key, war_record, war_snapshot)
from .events_registry import BOARD_LOST, EVENTS, PERSONAL
from .platform_guard import MINUTE, PER_MINUTE, Guard, notify as platform_notify
from .retention import STAT_HISTORY_KEEP, WAR_HISTORY_KEEP
from .selfmetrics import PLATFORM_INTERVAL, POLL_KEY
from .settings import clan_locale, effective, is_quiet, migrate, pack_on, route, web_conf
from .util import REPORT_HOUR, esc, now_utc, parse_coc_time
from .verify import LEADER_ROLES
from .web import payload as payload_mod

log = logging.getLogger("clashbot.poller")
HEARTBEAT = Path("/tmp/clashbot.heartbeat")
MOON = "🌙"
REPORT_IDLE_DAYS = 7
FAST_INTERVAL = 60
SLOW_INTERVAL = 120
CLANS_PER_KEY = 200
GROUP_DESTINATIONS = ("group", "topic")
MENTION_DESTINATIONS = ("group", "dm")
LINK_DESTINATIONS = ("leaders_dm", "staff_dm")
WAR_EVENTS = {"war_prep": "war.prep", "war_start": "war.start", "attack": "war.attack",
              "defense": "war.defense", "war_end": "war.end"}
CAPITAL_EVENTS = {"capital_start": "capital.start", "capital_reminder": "capital.reminder",
                  "capital_end": "capital.end"}
AGENDA_EVENTS = {"cwl": "cwl.signup", "games": "games.start", "season": "challenges.season"}
FIGHTS = ("attack", "defense")
CHUNK_KINDS = {"war.reminder": "reminder", "cwl.reminder": "reminder", "war.end": "war_end"}
CONSOLE_NAME = "console:username"
BOARD_PHASES = ("inWar", "warEnded")
LEGACY_BOARDS = ("board", "cwl_board", "games_board")
LOST_WINDOW = PER_MINUTE * MINUTE
NUDGE_PERIOD = 7 * 86400
HANDOVER_DAYS = 14
HANDOVER_INTERVAL = 21600


def poll_interval(clans, keys):
    return FAST_INTERVAL if clans <= CLANS_PER_KEY * keys else SLOW_INTERVAL


def war_event(kind, type_):
    return "cwl.day" if kind == "cwl" else WAR_EVENTS[type_]


def reminder_event(kind):
    return "cwl.reminder" if kind == "cwl" else "war.reminder"


def agenda_event(key, phase):
    return "games.last_day" if key == "games" and phase == "last" else AGENDA_EVENTS[key]


def chunk_kind(event):
    return CHUNK_KINDS.get(event, event)


def bot_username(bot):
    try:
        return bot.username if bot else None
    except Exception:
        return None


async def member_locale(store, link, clan_conf):
    return i18n.locale(link.lang or (clan_conf or {}).get("lang"))


def link_names(members, links):
    villages = {}
    for m in members:
        link = (links or {}).get(m.get("tag"))
        if link:
            villages.setdefault(link.user_id, []).append((m["tag"], esc(m.get("name") or link.name)))
    names = {}
    for user_id, group in villages.items():
        tag, name = group[0]
        mention = f"<a href=\"tg://user?id={user_id}\">{name}</a>"
        others = [other_name for _, other_name in group[1:]]
        names[tag] = f"{mention} ({', '.join(others)})" if others else mention
        for other_tag, other_name in group[1:]:
            names[other_tag] = other_name
    return names


class Tick:
    def __init__(self, clan, now):
        self.clan = clan
        self.now = now
        self.chunks = []
        self.threads = {}
        self.cards = []
        self.badge_url = None
        self.events = []
        self.boards = None
        self.boards_saved = None
        self.links = {}
        self.named = []
        self.nudges = []
        self.season = None
        self.closed_season = None
        self.members = None
        self.swept = []
        self.settings = effective(None, None)
        self.L = i18n.locale(self.settings["lang"])
        self.tz = self.settings["tz"]
        self.quiet = False
        self.sticker = None
        self.sticker_event = None

    @property
    def defer(self):
        return night.defers(self.settings, self.quiet)


class Poller:
    def __init__(self, supervisor, store, coc, concurrency=5):
        self.supervisor = supervisor
        self.store = store
        self.coc = coc
        self.interval = FAST_INTERVAL
        self.concurrency = concurrency
        self.goldpass = None
        self.purged = 0.0
        self.twitch = None
        self.owners_checked = 0.0
        self.platform_checked = 0.0
        self.site = None
        self.web = getattr(supervisor, "web", None)
        self.guard = Guard(store, supervisor)

    def alias_of(self, owner):
        return getattr(owner, "bot_alias", None) or self.supervisor.default_alias

    def bot_for(self, owner):
        return self.supervisor.bot(self.alias_of(owner))

    def served(self, owner):
        return self.alias_of(owner) in self.supervisor.running()

    def pace(self, clans):
        keys = self.coc.keys_alive()
        interval = poll_interval(clans, keys)
        if interval != self.interval:
            log.info("controllo ogni %ss (clan %s, chiavi Clash vive %s)", interval, clans, keys)
            self.interval = interval

    async def run(self):
        log.info("controllo ogni %ss", self.interval)
        await self.guard.load()
        while True:
            started = time.monotonic()
            clans = []
            try:
                self.site = await media.site_base(self.store)
                clans = [clan for clan in await self.store.active_clans() if self.served(clan)]
                self.pace(len(clans))
                sem = asyncio.Semaphore(self.concurrency)
                await asyncio.gather(*(self.tick(clan, sem) for clan in clans))
                await self.family_jobs(now_utc())
                await twitch_jobs.run(self, now_utc())
                await key_watch.check(self.store, self.supervisor.owner_bot(), self.coc, time.time())
                await self.tournament_jobs(now_utc())
                if time.monotonic() - self.owners_checked > HANDOVER_INTERVAL:
                    self.owners_checked = time.monotonic()
                    await self.owner_jobs(now_utc())
                if time.monotonic() - self.platform_checked > PLATFORM_INTERVAL:
                    self.platform_checked = time.monotonic()
                    await self.guard.daily(now_utc())
                if time.monotonic() - self.purged > 3600:
                    await self.store.kv_purge()
                    self.purged = time.monotonic()
                await self.guard.save()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("giro di controllo fallito")
            await self.note_round(time.monotonic() - started, len(clans), time.time())
            try:
                HEARTBEAT.touch()
            except OSError:
                pass
            await asyncio.sleep(max(5.0, self.interval - (time.monotonic() - started)))

    async def note_round(self, took, clans, at):
        try:
            await self.store.kv_set(POLL_KEY, {"took": took, "interval": self.interval,
                                               "clans": clans, "at": at},
                                    ttl=2 * PLATFORM_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("giro non misurato (%s)", type(e).__name__)

    async def tick(self, clan, sem):
        async with sem:
            try:
                t = Tick(clan, now_utc())
                if await guard_mod.paused(self.store, clan.alias):
                    await self.pause_board(t)
                    return
                await self._tick(t)
            except Exception:
                log.exception("%s: errore nel controllo", clan.alias)

    async def pause_board(self, t):
        state = await self.board_state(t)
        pin = boards.pin_of(state)
        if not pin.get("message_id"):
            return
        L, _ = await clan_locale(self.store, t.clan)
        text = L.t(guard_mod.PAUSED_LINE, clan=t.clan.name)
        markup = await self.board_markup(t, L)
        digest = boards.keyboard_digest(text, markup)
        if pin.get("digest") == digest:
            return
        updated = await self.upkeep(t.clan, pin, text, digest, t.now.timestamp(), create=False,
                                    markup=markup)
        if updated:
            await self.save_boards(t, boards.keep_pin(state, updated))

    async def _tick(self, t):
        clan = t.clan
        clan_json, error = await self.coc.clan(clan.tag)
        if error in ("invalid_ip", "invalid_key", "private"):
            return
        await self.load_settings(t, clan_json)
        await self.season_for(t)
        if clan_json:
            await self.store.rename_clan(clan, clan_json.get("name") or clan.name)
            new_members = member_snapshot(clan_json)
            old_members = await self.store.get_state(clan.alias, "members")
            t.members = new_members
            t.badge_url = (clan_json.get("badgeUrls") or {}).get("medium")
            if old_members is not None:
                events = member_events(old_members, new_members)
                t.events = events
                await self.dispatch(t, "members.movement",
                                    lambda L: render.render_member_events(L, events),
                                    facts=member_facts(events))
                if events:
                    await self.track_moves(t, events)
                await self.track_roster(t, events)
            await self.track_activity(t, old_members, new_members)
            await self.store.set_state(clan.alias, "members", new_members)
            await self.store.set_state(clan.alias, "info", {
                "level": clan_json.get("clanLevel"),
                "members": clan_json.get("members"),
                "league": (clan_json.get("warLeague") or {}).get("name"),
                "wins": clan_json.get("warWins"),
                "streak": clan_json.get("warWinStreak"),
                "points": clan_json.get("clanPoints"),
                **recruit.info_fields(clan_json),
                "badge": (clan_json.get("badgeUrls") or {}).get("medium"),
                "location": clan_json.get("location"),
            })
            await self.bump_streak(t, clan_json.get("warWinStreak"))
            today = t.now.astimezone(ZoneInfo(t.tz)).strftime("%Y-%m-%d")
            if t.season.get("donations_day") != today:
                scoring.apply_donations(t.season, new_members)
                t.season["donations_day"] = today
        else:
            t.members = await self.store.get_state(clan.alias, "members")
        war_json, war_error = await self.coc.current_war(clan.tag)
        if war_json:
            await self.track_war(t, war_snapshot(war_json), "war", None)
        await self.diagnose(t, True if war_error == "private" else (False if war_json else None))
        await self.track_cwl(t)
        await self.track_capital(t, clan_json)
        await self.sweep_players(t)
        await self.track_boards(t)
        await self.track_games(t)
        await self.track_agenda(t)
        await recruit_jobs.run(self, t)
        await quiz.run(self, t)
        await duels.run(self, t)
        await missions.run(self, t)
        await awards.run(self, t, t.closed_season)
        await bingo.run(self, t, await self.store.get_state(clan.alias, "war"))
        await self.leader_report(t)
        await self.track_legend(t)
        await self.member_report(t)
        await leader_jobs.run(self, t)
        await self.track_builder(t)
        await self.store.set_state(clan.alias, "season", t.season)
        await base_packs.weekly_poll(self, t)
        await self.announce_bases(t)
        await self.announce_stickers(t)
        await self.flush(t)
        await self.update_boards(t)
        await self.publish_web(t)
        await self.store.mark_ok(clan.alias)

    async def publish_public(self, t, web, info):
        clan = t.clan
        war = await self.store.get_state(clan.alias, "war")
        kind, day = "war", None
        if not war or war.get("state") in (None, "notInWar"):
            cwl = await self.store.get_state(clan.alias, "cwl") or {}
            tracked = await self.store.get_state(clan.alias, "cwl_war")
            if tracked and cwl.get("active"):
                war, kind, day = tracked, "cwl", tracked.get("day")
        goldpass = await self.goldpass_end(t.now)
        code = self.store.recruit_code(clan.alias)
        calendar = ics.build(t.L, code, clan.name, t.now, goldpass, war) if web["ics"] else None
        body = payload_mod.public_payload(
            clan, dict(t.settings, web=web), info, war, kind, day,
            await self.store.get_state(clan.alias, "hall"),
            agenda.upcoming(t.now, goldpass), t.now, calendar,
            bot=bot_username(self.bot_for(clan)), code=code,
        )
        if await self.web.clan(clan, payload_mod.PUBLIC, body, code):
            await self.announce_web(t, web)

    async def publish_web(self, t):
        if self.web is None:
            return
        clan = t.clan
        web = web_conf(t.settings)
        info = await self.store.get_state(clan.alias, "info")
        if web["page"]:
            await self.publish_public(t, web, info)
        else:
            await self.store.web_drop_page(clan.alias, payload_mod.PUBLIC)
            self.web.digests.pop((clan.alias, payload_mod.PUBLIC), None)
        await self.web.app(clan, t.settings, t.members, info, t.now)

    async def announce_web(self, t, web):
        url = await media.site_base(self.store)
        if not url:
            return
        notices = await self.store.get_state(t.clan.alias, "notices") or {}
        if notices.get("web_ready"):
            return
        code = self.store.recruit_code(t.clan.alias)
        await self.dispatch(t, "web.ready", lambda L: webmenu.ready_text(L, url, code, web))
        notices["web_ready"] = True
        await self.store.set_state(t.clan.alias, "notices", notices)

    async def load_settings(self, t, clan_json):
        stored = await self.store.get_state(t.clan.alias, "settings")
        conf = effective(stored, clan_json)
        country = ((clan_json or {}).get("location") or {}).get("countryCode")
        derive = bool(country) and any((stored or {}).get(key) is None for key in ("lang", "tz"))
        if stored is not None or derive:
            doc = migrate(stored)
            if derive:
                doc["lang"], doc["tz"] = conf["lang"], conf["tz"]
            if doc != stored:
                await self.store.set_state(t.clan.alias, "settings", doc)
        t.settings = conf
        t.L = i18n.locale(conf["lang"])
        t.tz = conf["tz"]
        t.quiet = is_quiet(conf, t.now)

    def destination(self, conf, event):
        to, intensity = route(conf, event)
        thread = topics.thread_for(conf, event)
        if to == "topic" and not thread:
            to = "group"
        return to, thread, intensity

    async def link_of(self, t, tag):
        if tag not in t.links:
            found = await self.store.links_for_players([tag])
            t.links[tag] = found.get(tag)
        return t.links[tag]

    async def fill_links(self, t, tags):
        missing = [tag for tag in tags if tag not in t.links]
        if missing:
            found = await self.store.links_for_players(missing)
            t.links.update({tag: found.get(tag) for tag in missing})
        return [t.links[tag] for tag in tags if t.links.get(tag)]

    async def member_links(self, t):
        tags = list(t.members or {})
        return len(await self.fill_links(t, tags)), len(tags)

    async def diagnose(self, t, war_private=None):
        state = await self.store.get_state(t.clan.alias, "diagnostics")
        if not diagnostics.due(state, t.now.timestamp()):
            return
        results = await diagnostics.inspect(self.bot_for(t.clan), t.clan.chat_id, t.settings, war_private)
        news = diagnostics.fresh(state, results)
        await self.store.set_state(t.clan.alias, "diagnostics",
                                   diagnostics.merged(state, results, t.now.timestamp()))
        if news:
            await self.dispatch(t, "system.diagnostic", lambda L: render.diagnostic_card(L, news))
        await topics.propose(self, t)

    async def link_nudge(self, t):
        if self.destination(t.settings, "system.link_nudge")[0] == "off":
            return
        key = f"nudge:{t.clan.alias}"
        if await self.store.kv_get(key):
            return
        linked, total = await self.member_links(t)
        if not total or linked * 2 >= total:
            return
        await self.dispatch(t, "system.link_nudge",
                            lambda L: render.link_nudge(L, linked, total, bot_username(self.bot_for(t.clan))))
        await self.store.kv_set(key, {"at": t.now.timestamp()}, ref=t.clan.alias, ttl=NUDGE_PERIOD)

    async def dispatch(self, t, event, render_text, member_tag=None, chunk=None, card=None,
                       nudged=None, facts=None):
        to, thread, _ = self.destination(t.settings, event)
        if to == "off":
            return
        kind = chunk or chunk_kind(event)
        if member_tag is not None:
            link = await self.link_of(t, member_tag)
            if link:
                await self.feed_member(t, link, kind, render_text)
            return
        if to in PERSONAL:
            if to in LINK_DESTINATIONS:
                await self.feed_managers(t, to, kind, render_text)
            return
        text = render_text(t.L)
        if not text:
            return
        if kind not in quiet.URGENT:
            pack = EVENTS[event]["pack"]
            if pack:
                t.boards = boards.append(await self.board_state(t), pack,
                                         [render.board_body(render.clip(text))], t.now, t.tz,
                                         facts=facts)
            return
        if card is not None:
            t.cards.append((event, kind, card(t.L), text, render_text, [(t.clan.chat_id, thread)]))
            return
        if thread:
            t.threads.setdefault(thread, []).append((kind, text))
        else:
            t.chunks.append((kind, text))
        if nudged and nudged.get("tags"):
            t.named.append((thread, dict(nudged, kind=kind)))

    async def whisper_war(self, t, event, war, rows, kind, day, plan):
        if self.destination(t.settings, event)[0] not in GROUP_DESTINATIONS:
            return
        bot = self.bot_for(t.clan)
        key = war_key(war)
        for m in rows:
            link = t.links.get(m["tag"])
            if not link or not getattr(link, "whisper", False):
                continue
            L = await member_locale(self.store, link, t.settings)
            entry = await whisper.send(bot, link,
                                       render.dm_reminder(L, t.tz, war, m, kind, day, t.now, plan),
                                       t.now)
            if entry:
                t.nudges.append(dict(entry, tag=m["tag"], war=key))
            elif not link.whisper:
                await self.store.set_link_whisper(link.user_id, link.tag, False)

    def note_nudges(self, t, thread, kinds, message_id):
        t.nudges += whisper.group_rows(t.named, thread, t.clan.chat_id, message_id, kinds)

    async def feed_member(self, t, link, kind, render_text):
        text = render_text(await member_locale(self.store, link, t.settings))
        if text:
            await feed.add(self.store, t.clan.alias, link.user_id, kind, text, t.now)

    async def feed_managers(self, t, to, kind, render_text):
        for uid in await roles.managers_for(self.store, t.clan, t.settings, t.members, to):
            text = render_text(await self.dm_locale(uid, t.settings, t.L))
            if text:
                await feed.add(self.store, t.clan.alias, uid, kind, text, t.now)

    def buckets(self, t):
        return [(None, t.chunks)] + sorted(t.threads.items())

    async def draw_card(self, t, spec):
        try:
            return await media.render_card(spec, t.badge_url)
        except Exception:
            log.exception("%s: card non disegnata", t.clan.alias)
            return None

    async def flush_cards(self, t):
        if not t.cards:
            return
        pending, t.cards = t.cards, []
        bot = self.bot_for(t.clan)
        alias = self.alias_of(t.clan)
        for event, kind, spec, text, render_text, targets in pending:
            head, rest = media.caption(text)
            done, failed = [], []
            png = await self.draw_card(t, spec) if bot and targets else None
            if png:
                for chat_id, thread_id in targets:
                    ok = await media.send_card(bot, self.store, alias, chat_id, png, head,
                                               quiet=t.quiet, thread_id=thread_id)
                    (done if ok else failed).append((chat_id, thread_id))
            if not done:
                await self.dispatch(t, event, render_text, chunk=kind)
                continue
            for chat_id, thread_id in failed:
                await self.send_to(bot, chat_id, text, thread_id=thread_id, quiet=t.quiet)
            if rest:
                for chat_id, thread_id in done:
                    await self.send_to(bot, chat_id, rest, thread_id=thread_id, quiet=t.quiet)

    async def send_chunks(self, t, thread, chunks, silent):
        for group, marked in whisper.split_named(t.named, thread, chunks):
            await self.send(t.clan, "\n\n".join(text for _, text in group), thread, quiet=silent,
                            note=partial(self.note_nudges, t, thread, marked) if marked else None)

    async def flush(self, t):
        await self.flush_cards(t)
        if t.defer:
            for thread, chunks in self.buckets(t):
                urgent, deferrable = quiet.split_urgent(chunks)
                await self.send_chunks(t, thread, urgent, True)
                if deferrable:
                    await self.enqueue(t.clan.alias, [text for _, text in deferrable], thread)
            await self.flush_held(t)
        else:
            await self.flush_queues(t)
            for thread, chunks in self.buckets(t):
                await self.send_chunks(t, thread, chunks, t.quiet)
        await whisper.remember(self.store, t.clan.alias, t.nudges)
        if t.sticker:
            kind, t.sticker = t.sticker, None
            await self.send_sticker(t, kind)

    def digest_parts(self, L, texts):
        entries = [text for text in (texts or []) if text]
        if not entries:
            return []
        body = quiet.digest(L, entries)
        head = render.card(MOON, L.t("quiet.digest.title"))
        if len(head) + 1 + len(body) <= render.MAX_LEN:
            return [head + "\n" + body]
        return [render.clip(text) for text in entries]

    async def flush_queues(self, t):
        queued = await self.store.get_state(t.clan.alias, "queue")
        if queued:
            sent = True
            for part in self.digest_parts(t.L, queued):
                if not await self.send(t.clan, part, hold=False, quiet=t.quiet):
                    sent = False
            if sent:
                await self.store.del_state(t.clan.alias, "queue")
        await self.flush_map(t, "queue_topics",
                             lambda thread, part: self.send(t.clan, part, int(thread), hold=False, quiet=t.quiet))
        await self.flush_held(t)

    async def dm_locale(self, user_id, clan_conf, fallback):
        links = await self.store.links_by_user(int(user_id))
        return await member_locale(self.store, links[0], clan_conf) if links else fallback

    async def flush_held(self, t):
        await self.flush_map(t, "queue_hold",
                             lambda thread, part: self.send(t.clan, part, int(thread) or None, hold=False,
                                                            quiet=t.quiet),
                             self.plain_parts)

    def plain_parts(self, L, texts):
        return [render.clip(text) for text in (texts or []) if text]

    async def flush_map(self, t, key, send, parts=None, locale_of=None):
        stored = await self.store.get_state(t.clan.alias, key)
        if not stored:
            return
        build = parts or self.digest_parts
        left = {}
        for target, texts in stored.items():
            L = await locale_of(target) if locale_of else t.L
            for part in build(L, texts):
                if not await send(target, part):
                    left[target] = texts
                    break
        if left:
            await self.store.set_state(t.clan.alias, key, left)
        else:
            await self.store.del_state(t.clan.alias, key)

    async def enqueue(self, alias, texts, thread=None):
        if thread:
            await self.enqueue_map(alias, "queue_topics", {str(thread): texts})
            return
        await quiet.enqueue(self.store, alias, texts, partial(self.merged, alias))

    async def enqueue_map(self, alias, key, pending):
        await quiet.enqueue_map(self.store, alias, key, pending, partial(self.merged, alias))

    async def hold_back(self, clan, text, thread=None):
        await self.enqueue_map(clan.alias, "queue_hold", {str(thread or 0): [text]})
        self.guard.delay(clan.alias)

    def merged(self, alias, queued, texts):
        merged = quiet.merge_queue(queued, texts)
        self.guard.drop(alias, len([text for text in list(queued) + list(texts) if text]) - len(merged))
        return merged

    async def clan_conf(self, clan):
        return effective(await self.store.get_state(clan.alias, "settings"), None)

    async def deliver(self, clan, text, event, member_tag=None):
        if not text or event not in EVENTS:
            return
        conf = await self.clan_conf(clan)
        to, thread, _ = self.destination(conf, event)
        if to == "off":
            return
        kind = chunk_kind(event)
        if member_tag is not None or to in PERSONAL:
            await self.deliver_feed(clan, conf, to, kind, text, member_tag)
            return
        pack = EVENTS[event]["pack"]
        if kind not in quiet.URGENT:
            if pack:
                state = boards.append(await self.store.get_state(clan.alias, "boards") or {}, pack,
                                      [render.board_body(render.clip(text))], now_utc(), conf["tz"])
                await self.store.set_state(clan.alias, "boards", state)
            return
        in_quiet = is_quiet(conf, now_utc())
        if night.defers(conf, in_quiet):
            await self.enqueue(clan.alias, [text], thread)
        else:
            await self.send(clan, text, thread, quiet=in_quiet)

    async def deliver_feed(self, clan, conf, to, kind, text, member_tag=None):
        now = now_utc()
        if member_tag is not None:
            link = (await self.store.links_for_players([member_tag])).get(member_tag)
            if link:
                await feed.add(self.store, clan.alias, link.user_id, kind, text, now)
            return
        if to not in LINK_DESTINATIONS:
            return
        members = await self.store.get_state(clan.alias, "members") or {}
        for uid in await roles.managers_for(self.store, clan, conf, members, to):
            await feed.add(self.store, clan.alias, uid, kind, text, now)

    async def season_for(self, t):
        sid = scoring.season_id(t.now, t.tz)
        season = await self.store.get_state(t.clan.alias, "season")
        closing = bool(season) and season.get("id") != sid
        if closing:
            records = await self.store.wars_since(t.clan.alias, warstats.month_start(season["id"], t.tz))
            wall = warstats.wall(warstats.defense_rows(records))
            deltas = await self.month_activity(t)
            mvp = leaderboards.mvp_rows("month", season, member_stats(records), deltas)
            best = mvp[0] if mvp else None
            titles = scoring.titles(season, deltas, wall=wall,
                                    mvp=(best["name"], best["total"]) if best else None)
            board = scoring.leaderboard(season)
            await self.dispatch(t, "boards.mvp",
                                lambda L: render.season_end_card(L, season["id"], titles, board,
                                                                 best["parts"] if best else None),
                                card=lambda L: cards.build_season(L, season["id"], titles,
                                                                  t.clan.tag, self.site))
            await self.store.add_stat(t.clan.alias, "war_month", season["id"],
                                      warstats.month_end(season["id"], t.tz),
                                      warstats.month_snapshot(season["id"], records))
            if titles:
                hall = warstats.hall_state(await self.store.get_state(t.clan.alias, "hall"))
                hall["seasons"].append({"season": season["id"],
                                        "titles": {k: list(v) for k, v in titles.items()}})
                await self.store.set_state(t.clan.alias, "hall", warstats.hall_state(hall))
            t.closed_season = season["id"]
            season = None
        t.season = season or scoring.empty_season(sid)
        if closing:
            await self.store.set_state(t.clan.alias, "season", t.season)

    async def read_progress(self, t):
        stored = await self.store.get_state(t.clan.alias, "progress")
        if stored is None:
            return {}
        if not isinstance(stored, dict):
            log.warning("%s: stato attività illeggibile, riparto da zero", t.clan.alias)
            return {}
        return stored

    async def month_activity(self, t):
        try:
            return progress_mod.deltas(await self.read_progress(t), "month")
        except Exception:
            log.exception("%s: attività del mese non leggibile", t.clan.alias)
            return []

    async def closed_activity(self, t, period):
        try:
            return progress_mod.closed(await self.read_progress(t), period,
                                       progress_mod.period_start(t.now, t.tz, period))
        except Exception:
            log.exception("%s: attività del periodo chiuso non leggibile", t.clan.alias)
            return []

    async def idle_members(self, t):
        try:
            return [{"name": r["name"], "days": r["days"]}
                    for r in progress_mod.idle(await self.read_progress(t), t.now)
                    if r["days"] >= REPORT_IDLE_DAYS]
        except Exception:
            log.exception("%s: fermi non calcolabili", t.clan.alias)
            return []

    async def track_progress(self, t, swept):
        if t.members:
            try:
                await privacy.prune_excluded(self.store, t.clan.alias, t.members, t.now)
            except Exception:
                log.exception("%s: esclusioni non potate", t.clan.alias)
        try:
            progress = await self.read_progress(t)
            members = t.members or {}
            if not swept and not any(tag not in members for tag in progress):
                return
            for tag, name, counters in swept:
                progress = progress_mod.update(progress, tag, name, counters, t.now, t.tz)
            await self.store.set_state(t.clan.alias, "progress", progress_mod.prune(progress, members))
        except Exception:
            log.exception("%s: attività non registrata", t.clan.alias)

    async def names_map(self, t, war):
        missing = missing_attackers(war)
        tags = [m["tag"] for m in missing]
        links = await self.store.links_for_players(tags)
        t.links.update({tag: links.get(tag) for tag in tags})
        if t.settings["mentions"] != "group":
            return {}
        return link_names(missing, links)

    async def plan_for(self, t, war):
        plan = await self.store.get_state(t.clan.alias, "plan")
        if plan and plan.get("war") == war_key(war):
            return plan.get("targets") or {}
        return {}

    async def track_war(self, t, new, kind, day):
        clan = t.clan
        key = "war" if kind == "war" else "cwl_war"
        if day is not None:
            new["day"] = day
        old = await self.store.get_state(clan.alias, key)
        events = war_events(old, new)
        await self.announce_war(t, events, new, kind, day)
        for e in events:
            if e["type"] == "war_end":
                rows = warstats.war_defense(e["war"])
                await self.dispatch(t, war_event(kind, "war_end"),
                                    lambda L, e=e, rows=rows: render.render_war_end(L, e["war"], e["result"],
                                                                                    kind, day, rows),
                                    chunk="war_end",
                                    card=lambda L, e=e: cards.build_war_end(L, e["war"], e["result"], kind,
                                                                            day, t.clan.tag, self.site))
                t.sticker = {"win": "win", "lose": "loss"}.get(e["result"])
                t.sticker_event = war_event(kind, "war_end")
        if kind == "war" and any(e["type"] == "war_start" for e in events):
            await self.open_poll(t, new)
        if any(e["type"] == "war_prep" for e in events):
            await self.opponent_history(t, new, kind, day)
        if new.get("state") == "inWar":
            reminders_key = key + "_reminders"
            sent = await self.store.get_state(clan.alias, reminders_key) or {}
            wk = war_key(new)
            done = sent.get(wk, [])
            due = [cp for cp in due_reminders(new, done, t.now) if cp in t.settings["reminders"]]
            if due:
                event = reminder_event(kind)
                names = await self.names_map(t, new)
                plan = await self.plan_for(t, new)
                missing = missing_attackers(new)
                await self.dispatch(t, event,
                                    lambda L: render.render_reminder(L, t.tz, new, min(due), kind, day,
                                                                     t.now, names, plan),
                                    nudged={"war": war_key(new),
                                            "tags": [m["tag"] for m in missing if names.get(m["tag"])]})
                await self.whisper_war(t, event, new, missing, kind, day, plan)
                if t.settings["mentions"] in MENTION_DESTINATIONS:
                    for m in missing:
                        await self.dispatch(t, event,
                                            lambda L, m=m: render.dm_reminder(L, t.tz, new, m, kind, day,
                                                                              t.now, plan),
                                            member_tag=m["tag"])
                await self.store.set_state(clan.alias, reminders_key, {wk: sorted(set(done) | set(due))})
        if any(e["type"] == "war_end" for e in events):
            ended = parse_coc_time(new.get("endTime")) or t.now
            record = war_record(new, kind, day)
            if await self.store.add_war(clan.alias, war_key(new), ended, record):
                scoring.apply_war(t.season, record)
                await self.bump_records(t, record)
                log.info("%s: %s registrata nello storico", clan.alias, render.war_title(t.L, kind, day).lower())
            if kind == "war":
                await self.settle_poll(t, new)
            plan = await self.store.get_state(clan.alias, "plan")
            if plan and plan.get("war") == war_key(new):
                await self.store.del_state(clan.alias, "plan")
            await self.link_nudge(t)
            await survey.open(self, t)
        await war_live.run(self, t, old, new, kind, day, events)
        await whisper.settle(self.bot_for(clan), self.store, clan.alias, new, t.now)
        await self.store.set_state(clan.alias, key, new)
        return events

    async def opponent_history(self, t, war, kind, day):
        opponent = war.get("opponent") or {}
        records = await self.store.recent_wars(t.clan.alias, WAR_HISTORY_KEEP)
        row = warstats.opponent_row(records, opponent.get("tag"), opponent.get("name"))
        if not row:
            return
        await self.dispatch(t, "war.opponent_history",
                            lambda L: render.foe_card(L, row, kind, day, t.now))

    async def bump_records(self, t, record):
        hall = warstats.hall_state(await self.store.get_state(t.clan.alias, "hall"))
        await self.announce_records(t, hall, warstats.update_records(hall["records"], record))

    async def bump_streak(self, t, streak):
        if streak is None:
            return
        hall = warstats.hall_state(await self.store.get_state(t.clan.alias, "hall"))
        after = warstats.update_streak(hall["records"], streak)
        if after == hall["records"]:
            return
        await self.announce_records(t, hall, after)

    async def announce_records(self, t, hall, after, event="war.record"):
        names = warstats.beaten(hall["records"], after)
        hall["records"] = after
        await self.store.set_state(t.clan.alias, "hall", hall)
        if names:
            await self.dispatch(t, event, lambda L: render.record_card(L, names, after))

    async def announce_war(self, t, events, new, kind, day):
        batches = {}
        for e in events:
            if e["type"] == "war_end":
                continue
            event = war_event(kind, e["type"])
            to, thread, intensity = self.destination(t.settings, event)
            if to == "off" or (e["type"] in FIGHTS and intensity == "summary"):
                continue
            batches.setdefault((to, thread), (event, []))[1].append(e)
        for event, batch in batches.values():
            await self.dispatch(t, event,
                                lambda L, batch=batch: render.render_war_events(L, t.tz, batch, new,
                                                                                kind, day, t.now))

    async def open_poll(self, t, war):
        await predictions.start(self, t, "war", war_key(war), opponent=war["opponent"]["name"])

    async def settle_poll(self, t, war):
        await predictions.settle(self, t, "war", war_key(war), war["clan"]["stars"],
                                 int(war.get("teamSize") or 0) * 3)

    async def board_state(self, t):
        if t.boards is None:
            t.boards = await self.store.get_state(t.clan.alias, "boards") or {}
            t.boards_saved = t.boards
        return t.boards

    async def update_boards(self, t):
        state = await self.drop_legacy(t, await self.board_state(t))
        state = await self.war_rows(t, state)
        state = await self.update_games_board(t, state)
        ts = t.now.timestamp()
        packs = self.board_packs(t)
        if not boards.given_up(state, ts, LOST_WINDOW) and (packs or boards.message_id(state)):
            state = await self.publish_pinned(t, state, ts)
        await self.save_boards(t, state)

    async def board_live(self, t):
        cwl = await self.store.get_state(t.clan.alias, "cwl") or {}
        war = await self.store.get_state(t.clan.alias, "war")
        cwl_war = await self.store.get_state(t.clan.alias, "cwl_war") if cwl.get("active") else None
        snapshot = boards.ticker_snapshot(
            t.clan.name, war, cwl_war, await self.store.get_state(t.clan.alias, "capital"), t.now)
        current = cwl_war if cwl_war and not boards.fighting(war) else war
        numbers = boards.numbers_of(
            current, agenda.upcoming(t.now, (self.goldpass or {}).get("end")), t.now)
        return snapshot, numbers

    async def publish_pinned(self, t, state, ts):
        snapshot, numbers = await self.board_live(t)
        text = boards.render_short(t.L, t.clan.name, snapshot, numbers)
        pin = boards.pin_of(state)
        markup = await self.board_markup(t)
        updated = await self.upkeep(t.clan, pin, text, boards.keyboard_digest(text, markup), ts,
                                    t.quiet, thread=topics.saved(t.settings).get("all"),
                                    create=not boards.rebuilt(state, ts, LOST_WINDOW),
                                    markup=markup)
        if updated is pin:
            return state
        if pin.get("message_id") and (updated or {}).get("message_id") != pin["message_id"]:
            state = boards.lost(state, ts, LOST_WINDOW)
            if boards.given_up(state, ts, LOST_WINDOW):
                await self.tell_board_lost(t)
        return boards.keep_pin(state, updated) if updated else state

    def board_packs(self, t):
        return [pack for pack in boards.SECTION_ORDER if pack_on(t.settings, pack)]

    async def save_boards(self, t, state):
        if state is t.boards_saved:
            return
        t.boards = state
        t.boards_saved = state
        await self.store.set_state(t.clan.alias, "boards", state)

    async def drop_legacy(self, t, state):
        bot = self.bot_for(t.clan)
        for pack in boards.legacy_packs(state):
            await pinned.erase(bot, t.clan.chat_id, boards.message_of(state, pack))
            state = boards.retire(state, pack)
        for kind in LEGACY_BOARDS:
            old = await self.store.get_state(t.clan.alias, kind)
            if not old:
                continue
            await pinned.erase(bot, t.clan.chat_id, old.get("message_id"))
            await self.store.del_state(t.clan.alias, kind)
        return state

    async def board_markup(self, t, L=None):
        console = await self.store.kv_get(CONSOLE_NAME) if self.site else None
        if not console:
            return None
        return boards.open_markup(L or t.L, console,
                                  payload_mod.slug_for(self.store.vault, t.clan.alias))

    async def tell_board_lost(self, t):
        await self.feed_managers(t, "staff_dm", BOARD_LOST, lambda L: L.t("board.all.lost"))

    async def war_rows(self, t, state):
        if self.destination(t.settings, "war.board")[0] not in GROUP_DESTINATIONS:
            return state
        state = self.war_row(t, state, await self.store.get_state(t.clan.alias, "war"),
                             "wars", "war", None)
        cwl = await self.store.get_state(t.clan.alias, "cwl")
        cwl_war = await self.store.get_state(t.clan.alias, "cwl_war")
        if cwl_war and cwl and cwl.get("active"):
            state = self.war_row(t, state, cwl_war, "cwl", "cwl", cwl_war.get("day"))
        return state

    def war_row(self, t, state, war, pack, kind, day):
        if not war or war.get("state") not in BOARD_PHASES or not pack_on(t.settings, pack):
            return state
        digest = render.board_digest(war)
        if boards.digest_of(state, pack) == digest:
            return state
        body = render.board_body(render.render_board(t.L, t.tz, war, kind, day, t.now))
        over = war.get("state") == "warEnded"
        return boards.append(state, pack, [body], t.now, t.tz, digest=digest,
                             facts=[war_end_fact(war)] if over else None)

    async def update_games_board(self, t, state):
        edition = await self.store.get_state(t.clan.alias, "games")
        if not edition or edition.get("closed"):
            return state
        if self.destination(t.settings, "games.board")[0] == "off":
            return state
        digest = f"{edition.get('id')}:{games.digest(edition)}"
        if boards.digest_of(state, "capital_games") == digest:
            return state
        body = render.board_body(games.board_text(t.L, t.tz, edition, t.now))
        return boards.append(state, "capital_games", [body], t.now, t.tz, digest=digest)

    async def track_games(self, t):
        clan, now = t.clan, t.now
        start, end = games.window(now)
        edition = await self.store.get_state(clan.alias, "games")
        if not start:
            if edition and not edition.get("closed"):
                await self.close_games(t, edition)
            return
        if not edition or edition.get("id") != games.edition_id(start) or edition.get("closed"):
            if edition and not edition.get("closed"):
                await self.close_games(t, edition)
            history = await self.store.recent_stats(clan.alias, "games", STAT_HISTORY_KEEP)
            edition = games.open_edition(await self.read_progress(t), t.members or {}, start, end,
                                         games.best_ever(history))
        games.track(edition, t.swept)
        if t.members:
            games.prune(edition, t.members)
        if games.due_reminder(edition, now):
            await self.remind_games(t, edition)
            edition["reminded"] = True
        await self.store.set_state(clan.alias, "games", edition)

    async def close_games(self, t, edition):
        entry = games.record(edition)
        history = await self.store.recent_stats(t.clan.alias, "games", STAT_HISTORY_KEEP)
        previous = history[0] if history else None
        await self.store.add_stat(t.clan.alias, "games", entry["id"] or "",
                                  games.ends_at(edition) or t.now, entry)
        await self.store.del_state(t.clan.alias, "games")
        if entry["total"] > 0:
            best = games.best_ever(history)
            await self.dispatch(t, "games.end", lambda L: games.end_card(L, entry, previous, best))

    async def remind_games(self, t, edition):
        zero = games.behind(edition)
        if not zero:
            return

        def text(L):
            return games.reminder_dm(L, t.tz, edition, t.now)

        if self.destination(t.settings, "games.reminder")[0] != "member_dm":
            await self.dispatch(t, "games.reminder", text)
            return
        for row in zero:
            await self.dispatch(t, "games.reminder", text, member_tag=row["tag"])

    async def upkeep(self, owner, state, text, digest, now_ts, quiet=False, thread=None,
                     stale=pinned.STALE, create=True, force=False, pin=True, markup=None):
        bot = self.bot_for(owner)
        if not bot:
            return state
        if create and not (state or {}).get("message_id") and not self.guard.allow(owner.chat_id):
            log.info("%s: tetto di messaggi al minuto, tabellone rimandato al giro dopo",
                     getattr(owner, "alias", None))
            return state
        return await pinned.upkeep(bot, owner.chat_id, state, text, digest, now_ts, quiet,
                                   stale=stale, create=create, thread_id=thread, force=force,
                                   pin=pin, markup=markup)

    async def track_cwl(self, t):
        clan, now = t.clan, t.now
        cwl = await self.store.get_state(clan.alias, "cwl") or {}
        ts = now.timestamp()
        interval = 600 if cwl.get("active") else 1800
        if ts - cwl.get("checked", 0) >= interval:
            group, error = await self.coc.league_group(clan.tag)
            if group:
                summary = group_summary(group)
                if summary["season"] != cwl.get("season"):
                    cwl = {"season": summary["season"], "our": {}, "wars": {}}
                    await self.store.del_state(clan.alias, "cwl_war")
                    await self.store.del_state(clan.alias, "cwl_war_reminders")
                    await self.store.del_state(clan.alias, "cwl_roster")
                    await self.store.del_state(clan.alias, "cwl_scout")
                info = await self.store.get_state(clan.alias, "info") or {}
                cwl.update({
                    "active": summary["state"] != "ended",
                    "state": summary["state"],
                    "clans": summary["clans"],
                    "rounds": summary["rounds"],
                    "league": info.get("league"),
                })
                wars = cwl.setdefault("wars", {})
                our = cwl.setdefault("our", {})
                for index, tags in enumerate(summary["rounds"]):
                    if not tags or all((wars.get(tag) or {}).get("state") == "warEnded" for tag in tags):
                        continue
                    for tag in tags:
                        war_json, _ = await self.coc.league_war(tag)
                        if not war_json:
                            continue
                        wars[tag] = war_summary(war_json)
                        if clan.tag in (wars[tag]["clan"]["tag"], wars[tag]["opponent"]["tag"]):
                            our[str(index)] = tag
            elif error == "not_found":
                cwl["active"] = False
            cwl["checked"] = ts
            await self.store.set_state(clan.alias, "cwl", cwl)
        if not cwl.get("closed"):
            await self.track_cwl_scout(t, cwl)
            await self.cwl_bonus(t, cwl)
            await self.close_cwl_season(t, cwl)
        if not cwl.get("active"):
            return
        index = current_round(cwl.get("rounds", []), cwl.get("our", {}), cwl.get("wars", {}))
        if index is None:
            return
        tag = cwl["our"][str(index)]
        tracked = await self.store.get_state(clan.alias, "cwl_war") or {}
        if (cwl["wars"].get(tag) or {}).get("state") == "warEnded" and tracked.get("state") == "warEnded":
            return
        war_json, _ = await self.coc.league_war(tag)
        if not war_json:
            return
        war_json = orient_war(war_json, clan.tag)
        snapshot = war_snapshot(war_json)
        snapshot["warTag"] = tag
        cwl["wars"][tag] = war_summary(war_json)
        await self.store.set_state(clan.alias, "cwl", cwl)
        await self.track_war(t, snapshot, "cwl", index + 1)
        await predictions.cwl_open(self, t, cwl, snapshot)
        await self.cwl_lineup(t, cwl, snapshot)
        await self.cwl_day_table(t, cwl)

    async def cwl_lineup(self, t, cwl, war):
        if not war or war.get("state") != "preparation" or not war.get("day"):
            return False
        clan = t.clan
        state = cwl_roster.for_season(await self.store.get_state(clan.alias, "cwl_roster"),
                                      cwl.get("season"))
        sent = state.setdefault("sent", {}).setdefault("lineup", {})
        day = str(war.get("day"))
        if day in sent:
            return False
        records = cwl_season.season_wars(await self.store.recent_wars(clan.alias, 20), cwl.get("season"))
        players = (await self.store.get_state(clan.alias, "players") or {}).get("tags", {})
        rows = cwl_roster.rows(cwl_roster.registered(cwl, clan.tag), state,
                               cwl_roster.played_days(records), records, players)
        if not rows:
            return False
        proposed, bench = cwl_roster.lineup(rows, war.get("teamSize"),
                                            cwl_roster.picked(state))
        await self.dispatch(t, "cwl.roster",
                            lambda L: cwl_cards.lineup_card(L, proposed, bench, war.get("day")))
        sent[day] = t.now.timestamp()
        await self.store.set_state(clan.alias, "cwl_roster", state)
        return True

    async def track_cwl_scout(self, t, cwl):
        if not cwl or not cwl.get("clans"):
            return False
        clan = t.clan
        scout = cwl_scout.for_season(await self.store.get_state(clan.alias, "cwl_scout"),
                                     cwl.get("season"))
        todo = cwl_scout.missing(cwl, scout)
        if todo:
            tag = todo[0]
            clan_json, _ = await self.coc.clan(tag)
            if clan_json is None:
                return False
            cwl_scout.remember(scout, tag, (cwl.get("clans") or {}).get(tag), clan_json,
                               t.now.timestamp())
            await self.store.set_state(clan.alias, "cwl_scout", scout)
            return False
        await self.learn_cwl_zones(t, cwl)
        if scout.get("sent"):
            return False
        await self.dispatch(t, "cwl.scout", lambda L: cwl_cards.scout_card(
            L, cwl_scout.rows(scout, clan.tag), cwl.get("season")))
        scout["sent"] = t.now.timestamp()
        await self.store.set_state(clan.alias, "cwl_scout", scout)
        return True

    async def cwl_bonus(self, t, cwl):
        if not cwl_season.finished(cwl):
            return False
        clan = t.clan
        state = cwl_roster.for_season(await self.store.get_state(clan.alias, "cwl_roster"),
                                      cwl.get("season"))
        if state.get("sent", {}).get("bonus"):
            return False
        records = cwl_season.season_wars(await self.store.recent_wars(clan.alias, 20), cwl.get("season"))
        rows = cwl_bonus.proposal(cwl_season.member_rows(records, state),
                                  cwl_bonus.past_bonus(await cwl_store.seasons(self.store, clan.alias, 12)),
                                  state.get("bonus"))
        if not rows:
            return False
        await self.dispatch(t, "cwl.bonus", lambda L: cwl_cards.bonus_card(L, rows))
        state.setdefault("sent", {})["bonus"] = t.now.timestamp()
        await self.store.set_state(clan.alias, "cwl_roster", state)
        return True

    async def close_cwl_season(self, t, cwl):
        if not cwl or cwl.get("closed") or not cwl.get("season") or not cwl_season.finished(cwl):
            return False
        clan = t.clan
        records = cwl_season.season_wars(await self.store.recent_wars(clan.alias, 20), cwl.get("season"))
        roster = await self.store.get_state(clan.alias, "cwl_roster") or {}
        record = cwl_season.season_record(cwl, clan.tag, records, roster)
        await cwl_store.save_season(self.store, clan.alias, record["season"],
                                    cwl_season.ended_at(record, t.now), record)
        await self.dispatch(t, "cwl.season", lambda L: cwl_cards.season_card(L, record))
        await predictions.cwl_settle(self, t, record, records)
        zones = await self.store.get_state(clan.alias, "cwl_zones") or {"leagues": {}, "last": None}
        zones["last"] = cwl_table.snapshot(cwl, record)
        await self.store.set_state(clan.alias, "cwl_zones", zones)
        cwl["closed"] = True
        await self.store.set_state(clan.alias, "cwl", cwl)
        return True

    async def league_order(self, now):
        cached = await self.store.kv_get("warleagues") or {}
        if cached.get("order") and now.timestamp() - cached.get("fetched", 0) < 86400:
            return cached["order"]
        data, _ = await self.coc.war_leagues()
        order = cwl_table.league_order(data)
        if order:
            await self.store.kv_set("warleagues", {"order": order, "fetched": now.timestamp()})
            return order
        return cached.get("order") or {}

    async def cwl_day_table(self, t, cwl):
        rows = cwl_table.table(cwl, t.clan.tag)
        ours = next((r for r in rows if r["us"]), None)
        day = ours["played"] if ours else 0
        sent = cwl.setdefault("sent", {})
        if not day or sent.get("table") == day:
            return False
        war = await self.store.get_state(t.clan.alias, "cwl_war") or {}
        zones = await self.store.get_state(t.clan.alias, "cwl_zones") or {}
        entry = (zones.get("leagues") or {}).get(cwl.get("league"))
        total = len(cwl.get("rounds") or [])
        rows = cwl_table.projection(rows, total, war.get("teamSize"))
        await self.dispatch(t, "cwl.standings",
                            lambda L: cwl_cards.table_card(L, rows, day, total, entry))
        sent["table"] = day
        await self.store.set_state(t.clan.alias, "cwl", cwl)
        return True

    async def learn_cwl_zones(self, t, cwl):
        clan = t.clan
        zones = await self.store.get_state(clan.alias, "cwl_zones") or {"leagues": {}, "last": None}
        last = zones.get("last")
        if not last or last.get("season") == cwl.get("season"):
            return False
        leagues = last.setdefault("leagues", {})
        todo = [tag for tag in sorted(last.get("ranks") or {}) if tag not in leagues]
        if todo:
            data, error = await self.coc.clan(todo[0])
            if data is None and error in scouting.RETRY:
                return False
            leagues[todo[0]] = ((data or {}).get("warLeague") or {}).get("name")
            await self.store.set_state(clan.alias, "cwl_zones", zones)
            return False
        order = await self.league_order(t.now)
        if not order:
            return False
        entry = cwl_table.observe(last, leagues, order)
        move = cwl_table.move_of(last.get("league"), cwl.get("league"), order)
        if move:
            stored = next((r for r in await cwl_store.seasons(self.store, clan.alias, 1)
                           if r.get("season") == last.get("season")), None)
            if stored and stored.get("move") != move:
                stored["move"] = move
                await cwl_store.save_season(self.store, clan.alias, stored["season"],
                                            cwl_season.ended_at(stored, t.now), stored)
        if entry:
            entry["season"] = cwl.get("season")
            zones.setdefault("leagues", {})[last.get("league")] = entry
        zones["last"] = None
        await self.store.set_state(clan.alias, "cwl_zones", zones)
        return bool(entry)

    async def track_capital(self, t, clan_json=None):
        clan, now = t.clan, t.now
        cap = await self.store.get_state(clan.alias, "capital") or {}
        hall = capital.hall_snapshot(clan_json)
        if hall:
            for event in capital.hall_events(cap.get("hall"), hall):
                await self.dispatch(t, "capital.level",
                                    lambda L, event=event: capital.level_cards(L, [event])[0])
            cap["hall"] = hall
        if now.timestamp() - cap.get("checked", 0) >= 600:
            data, _ = await self.coc.capital_raids(clan.tag)
            items = (data or {}).get("items") or []
            if items:
                cap = await self.capital_raid(t, cap, items[0])
            cap["checked"] = now.timestamp()
        await self.store.set_state(clan.alias, "capital", cap)

    async def capital_raid(self, t, cap, raid):
        hall = cap.get("hall")
        closing = cap.get("state") == "ongoing" and raid.get("state") == "ended" and not cap.get("summary_sent")
        cap, events = capital_events(cap, raid, t.members or {}, t.now)
        if hall:
            cap["hall"] = hall
        cap["free"] = capital.free_attacks(raid, t.members or {}) if raid.get("state") == "ongoing" else 0
        capital.track_gold(cap, await self.read_progress(t), t.members or {})
        for event in events:
            name = CAPITAL_EVENTS[event["type"]]
            if name != "capital.end":
                await self.dispatch(t, name,
                                    lambda L, event=event: render.render_capital_events(L, t.tz, [event]))
                continue

            def end_text(L, event=event):
                body = render.render_capital_events(L, t.tz, [event])
                extra = capital.end_extra(L, raid)
                return body + ("\n\n" + extra if body and extra else "")

            await self.dispatch(t, name, end_text)
        if any(e["type"] == "capital_start" for e in events):
            await predictions.capital_open(self, t, raid)
        if any(e["type"] == "capital_end" for e in events):
            await predictions.capital_settle(self, t, raid)
        if raid.get("state") == "ended" and scoring.apply_raid(t.season, raid):
            log.info("%s: raid capitale conteggiato nei punti", t.clan.alias)
        if closing:
            await self.capital_closed(t, cap, raid)
        return cap

    async def capital_closed(self, t, cap, raid):
        ended = parse_coc_time(raid.get("endTime")) or t.now
        await self.store.add_stat(t.clan.alias, "capital", raid.get("startTime") or ended.isoformat(),
                                  ended, capital.raid_record(raid))
        next_start, _ = agenda.raid_weekend(t.now)
        to = self.destination(t.settings, "capital.skipped")[0]
        for row in capital.skipped_rows(raid, t.members or {}):
            await self.dispatch(t, "capital.skipped",
                                lambda L, row=row: capital.skipped_dm(L, t.tz, row, next_start),
                                member_tag=row["tag"] if to == "member_dm" else None)
        rows = capital.gold_since(await self.read_progress(t), cap)
        if capital.gold_rows(rows):
            await self.dispatch(t, "capital.gold", lambda L: capital.gold_card(L, rows))

    async def sweep_players(self, t, per_tick=2):
        if not t.members:
            return
        clan = t.clan
        players = await self.store.get_state(clan.alias, "players") or {"tags": {}, "cursor": 0, "out_since": {}}
        trend_state = await self.store.get_state(clan.alias, "trend") or {}
        day = trend_mod.day_key(t.now, t.tz)
        goal_state = await self.store.get_state(clan.alias, "goals") or {}
        done = []
        tags = sorted(t.members)
        count = len(tags)
        cursor = players.get("cursor", 0) % count
        events = []
        by_member = {}
        swept = []
        builder_events = []
        builder_by_member = {}
        for i in range(min(per_tick, count)):
            tag = tags[(cursor + i) % count]
            data, _ = await self.coc.player(tag)
            if not data:
                continue
            snapshot = player_snapshot(data)
            previous = players["tags"].get(tag)
            found = player_events(previous, snapshot)
            if found:
                by_member[tag] = found
            events += found
            grown = builder.milestones(previous, snapshot)
            if grown:
                builder_by_member[tag] = grown
            builder_events += grown
            players["tags"][tag] = snapshot
            trend_state = trend_mod.record(
                trend_state, tag, snapshot.get("name"), day, snapshot.get("trophies"),
                snapshot.get("th"), (snapshot.get("legend") or {}).get("trophies"),
            )
            goal = goal_state.get(tag)
            if goals_mod.reached(goal, snapshot):
                done.append({"tag": tag, "name": snapshot.get("name"), "goal": goal})
                goal_state.pop(tag, None)
            if isinstance(data, dict) and data.get("achievements"):
                swept.append((tag, snapshot.get("name"), snapshot.get("counters")))
            if snapshot.get("warPref") == "out":
                players.setdefault("out_since", {}).setdefault(tag, t.now.timestamp())
            else:
                players.setdefault("out_since", {}).pop(tag, None)
        players["cursor"] = (cursor + per_tick) % count
        for tag in list(players["tags"]):
            if tag not in t.members:
                players["tags"].pop(tag, None)
                players.get("out_since", {}).pop(tag, None)
        to, _, _ = self.destination(t.settings, "members.achievement")
        if to == "member_dm":
            for tag, found in by_member.items():
                await self.dispatch(t, "members.achievement",
                                    lambda L, found=found: render.achievements_card(L, found),
                                    member_tag=tag)
        else:
            await self.dispatch(t, "members.achievement", lambda L: render.achievements_card(L, events))
        await self.grant_badges(t, by_member)
        to, _, _ = self.destination(t.settings, "members.builder_goal")
        if to == "member_dm":
            for tag, grown in builder_by_member.items():
                await self.dispatch(t, "members.builder_goal",
                                    lambda L, grown=grown: builder.milestone_card(L, grown),
                                    member_tag=tag)
        elif builder_events:
            await self.dispatch(t, "members.builder_goal",
                                lambda L: builder.milestone_card(L, builder_events))
        to, _, _ = self.destination(t.settings, "members.goal")
        if to == "member_dm":
            for row in done:
                await self.dispatch(t, "members.goal",
                                    lambda L, row=row: render.goal_done_card(L, [row]),
                                    member_tag=row["tag"])
        elif done:
            await self.dispatch(t, "members.goal", lambda L: render.goal_done_card(L, done))
        await self.store.set_state(clan.alias, "goals",
                                   {tag: g for tag, g in goal_state.items() if tag in t.members})
        await self.store.set_state(clan.alias, "trend", trend_mod.prune(trend_state, t.members))
        await self.store.set_state(clan.alias, "players", players)
        t.swept = swept
        await self.track_progress(t, swept)

    async def grant_badges(self, t, by_member):
        if not by_member:
            return
        to, _, _ = self.destination(t.settings, "challenges.badge")
        private = to == "member_dm"
        state = await challenges.load(self.store, t.clan.alias)
        for tag, found in by_member.items():
            fresh = badges.from_player_events(state, tag, found, int(t.now.timestamp()))
            if not fresh or to == "off":
                continue
            name = None if private else found[0].get("name")
            icons = " ".join(badges.CATALOG[mark] for mark in fresh)
            await self.dispatch(t, "challenges.badge",
                                lambda L, name=name, icons=icons: render.badge_card(L, name, icons),
                                member_tag=tag if private else None)
        await challenges.save(self.store, t.clan.alias, state)

    async def track_activity(self, t, old_members, new_members):
        activity = await self.store.get_state(t.clan.alias, "activity") or {}
        ts = t.now.timestamp()
        for tag, m in new_members.items():
            old = (old_members or {}).get(tag)
            fresh = (m.get("donations"), m.get("received"), m.get("trophies"))
            if old is None or fresh != (old.get("donations"), old.get("received"), old.get("trophies")):
                activity[tag] = ts
            else:
                activity.setdefault(tag, ts)
        for tag in list(activity):
            if tag not in new_members:
                del activity[tag]
        await self.store.set_state(t.clan.alias, "activity", activity)

    async def goldpass_end(self, now):
        kept = self.goldpass or {}
        if now.timestamp() - float(kept.get("fetched") or 0) < news_feed.SEASON_TTL:
            return kept.get("end")
        self.goldpass = await news_feed.season(self.store, self.coc, now) or {}
        return self.goldpass.get("end")

    async def track_boards(self, t):
        if not t.members:
            return
        clan = t.clan
        state = await self.store.get_state(clan.alias, leaderboards.STATE_KIND) or {}
        goldpass = await self.goldpass_end(t.now)
        state = leaderboards.update_trophies(state, t.members, t.now, t.tz, goldpass)
        sent = state.get("sent") if isinstance(state.get("sent"), dict) else {}
        local = t.now.astimezone(ZoneInfo(t.tz))
        week = leaderboards.closed_period_id(t.now, t.tz, "week")
        if local.weekday() == 0 and local.hour >= REPORT_HOUR and sent.get("week") != week:
            state = await self.publish_week(t, state, week)
            sent["week"] = week
        season = leaderboards.period_id(t.now, t.tz, "season", goldpass)
        _, end = leaderboards.window(t.now, t.tz, "season", goldpass)
        if sent.get("season") != season and t.now >= end - timedelta(hours=1):
            state = await self.publish_season(t, state, season, goldpass)
            sent["season"] = season
        day = local.strftime("%Y-%m-%d")
        if sent.get("ranks_day") != day:
            state = await self.check_rankings(t, state)
            sent["ranks_day"] = day
        state["sent"] = sent
        await self.store.set_state(clan.alias, leaderboards.STATE_KIND, state)

    async def publish_week(self, t, state, week):
        start, end = leaderboards.closed_window(t.now, t.tz, "week")
        rows = await self.closed_activity(t, "week")
        report = leaderboards.week_report(state, t.members, rows, t.season, privacy.hidden_in(state),
                                          int(end.timestamp()))
        await self.dispatch(t, "boards.week", lambda L: render.week_summary(
            L, L.t("boards.period.week"), report["blocks"], report["climb"],
            report["climb_points"]))
        recent = await self.store.recent_wars(t.clan.alias, WAR_HISTORY_KEEP)
        hall = warstats.hall_state(await self.store.get_state(t.clan.alias, "hall"))
        after = warstats.update_board_records(hall["records"], leaderboards.record_candidates(
            report["farm"], report["donations"], scoring.streaks(recent)))
        await self.announce_records(t, hall, after, "boards.record")
        await self.store.add_stat(t.clan.alias, "boards_week", week, t.now,
                                  {"farm": report["farm"][:leaderboards.PODIUM],
                                   "donations": report["donations"][:leaderboards.PODIUM]})
        row = await self.store.network_get(t.clan.alias)
        if row and row["visible"]:
            wars = warstats.in_window(await self.store.wars_since(t.clan.alias, start), start, end)
            await self.store.network_set(t.clan.alias, True, row["named"],
                                         leaderboards.network_payload(t.clan.name, t.clan.tag, week,
                                                                      rows, member_stats(wars),
                                                                      t.members))
        return state

    async def publish_season(self, t, state, season, goldpass):
        start, _ = leaderboards.window(t.now, t.tz, "season", goldpass)
        stats = member_stats(await self.store.wars_since(t.clan.alias, start))
        deltas = progress_mod.deltas(await self.read_progress(t), "season")
        rows = leaderboards.mvp_rows("season", t.season, stats, deltas, privacy.hidden_in(state))
        players = (await self.store.get_state(t.clan.alias, "players") or {}).get("tags") or {}
        leagues = leaderboards.season_leagues(players, t.members)
        await self.dispatch(t, "boards.season",
                            lambda L: render.season_summary(L, season, rows, leagues))
        await self.store.add_stat(t.clan.alias, "boards_season", season, t.now,
                                  {"mvp": rows[:leaderboards.PODIUM]})
        return state

    async def check_rankings(self, t, state):
        location = (await self.store.get_state(t.clan.alias, "info") or {}).get("location") or {}
        if not location.get("isCountry") or not location.get("id"):
            return state
        clans_json, clans_error = await self.coc.location_clans(location["id"], rankings.TOP_N)
        players_json, players_error = await self.coc.location_players(location["id"], rankings.TOP_N)
        previous = state.get("ranks") or {}
        current = dict(previous)
        if not clans_error:
            current["clan"] = rankings.clan_entry(clans_json, t.clan.tag)
        if not players_error:
            current["players"] = rankings.player_entries(players_json, list(t.members or ()))
        current = rankings.merge(previous, current)
        moves = rankings.changes(previous, current)
        if moves:
            await self.dispatch(t, "boards.rank", lambda L: render.rank_card(L, moves))
        state["ranks"] = current
        return state

    async def track_agenda(self, t):
        state = await self.store.get_state(t.clan.alias, "agenda") or {"sent": {}}
        due = agenda.due_announcements(t.now, await self.goldpass_end(t.now), state["sent"])
        if not due:
            return
        for key, item, phase in due:
            await self.dispatch(t, agenda_event(item["key"], phase),
                                lambda L, item=item, phase=phase: render.agenda_announcement(L, t.tz, item,
                                                                                             phase, t.now))
            state["sent"][key] = t.now.timestamp()
        cutoff = t.now.timestamp() - 60 * 86400
        state["sent"] = {k: v for k, v in state["sent"].items() if v > cutoff}
        await self.store.set_state(t.clan.alias, "agenda", state)

    async def announce_bases(self, t):
        pending = await self.store.get_state(t.clan.alias, "bases_new")
        if pending:
            await self.store.del_state(t.clan.alias, "bases_new")
            for entry in pending[:bases_mod.PAGE]:
                await self.dispatch(t, "bases.new", lambda L, entry=entry: render.card(
                    "🏰", L.t("bases.title"),
                    L.t("bases.new", name=render.esc(entry.get("name") or "?"),
                        hall=bases_mod.hall_name(entry.get("village"), entry.get("hall")),
                        label=bases_mod.label_name(L, entry.get("label")))))
        packs = await self.store.get_state(t.clan.alias, base_packs.PACK_QUEUE)
        if not packs:
            return
        await self.store.del_state(t.clan.alias, base_packs.PACK_QUEUE)
        for entry in packs[:bases_mod.PAGE]:
            source = await self.store.clan_by_alias(entry.get("source"))
            await self.dispatch(t, base_packs.PACK_EVENT,
                                lambda L, entry=entry, source=source: render.card(
                                    "📦", L.t("bases.tab.packs"),
                                    L.t("bases.pack.new",
                                        clan=render.esc(source.name if source else "?"),
                                        name=base_packs.pack_title(L, entry), n=entry.get("n"))))

    async def announce_stickers(self, t):
        pending = await self.store.get_state(t.clan.alias, stickers.QUEUE)
        if not pending:
            return
        await self.store.del_state(t.clan.alias, stickers.QUEUE)
        await self.dispatch(t, stickers.EVENT, lambda L: render.card(
            "🎨", L.t("stickers.title"), L.t("stickers.ready", set=pending["set"])))

    async def leader_report(self, t):
        local = t.now.astimezone(ZoneInfo(t.tz))
        if local.weekday() != 0 or local.hour < REPORT_HOUR or not t.members:
            return
        week = local.strftime("%G-W%V")
        reports = await self.store.get_state(t.clan.alias, "reports") or {}
        if reports.get("week") == week:
            return
        reports["week"] = week
        await self.store.set_state(t.clan.alias, "reports", reports)
        records = await self.store.wars_since(t.clan.alias, t.now - timedelta(days=7))
        missed = {}
        for record in records:
            for m in record.get("members", []):
                if m.get("missed"):
                    missed[m["name"]] = missed.get(m["name"], 0) + m["missed"]
        missed = sorted(missed.items(), key=lambda kv: -kv[1])
        activity = await self.store.get_state(t.clan.alias, "activity") or {}
        cutoff = t.now.timestamp() - 14 * 86400
        inactive = sorted(m["name"] for tag, m in t.members.items() if activity.get(tag, t.now.timestamp()) < cutoff)
        players = await self.store.get_state(t.clan.alias, "players") or {}
        cutoff_out = t.now.timestamp() - 21 * 86400
        out = sorted(t.members[tag]["name"] for tag, since in players.get("out_since", {}).items()
                     if since < cutoff_out and tag in t.members)
        idle = await self.idle_members(t)
        debt = []
        if self.destination(t.settings, "boards.donations")[0] != "off":
            debt = leaderboards.donation_debt(t.members, await privacy.excluded(self.store, t.clan.alias))
        waiting = recruit.state_of(await self.store.get_state(t.clan.alias, recruit.KIND))
        await self.dispatch(t, "members.report",
                            lambda L: render.leader_report(L, t.clan, missed, inactive, out,
                                                           idle=idle, debt=debt)
                            + recruit_jobs.report_line(L, waiting))

    async def member_report(self, t):
        local = t.now.astimezone(ZoneInfo(t.tz))
        if local.weekday() != 0 or local.hour < REPORT_HOUR or not t.members:
            return
        week = local.strftime("%G-W%V")
        reports = await self.store.get_state(t.clan.alias, "reports") or {}
        if reports.get("member_week") == week:
            return
        reports["member_week"] = week
        await self.store.set_state(t.clan.alias, "reports", reports)
        rows = {r["tag"]: r for r in await self.closed_activity(t, "week")}
        trend_state = await self.store.get_state(t.clan.alias, "trend") or {}
        to = self.destination(t.settings, "members.progress")[0]
        for tag in t.members:
            row = rows.get(tag)
            if not row or not row.get("score"):
                continue
            await self.dispatch(t, "members.progress",
                                lambda L, row=row, tag=tag: render.member_week_card(
                                    L, row, trend_mod.series(trend_state, tag)),
                                member_tag=tag if to == "member_dm" else None)

    async def track_legend(self, t):
        local = t.now.astimezone(ZoneInfo(t.tz))
        if local.hour < REPORT_HOUR or not t.members:
            return
        day = local.strftime("%Y-%m-%d")
        state = await self.store.get_state(t.clan.alias, "legend") or {}
        if state.get("day") == day:
            return
        players = (await self.store.get_state(t.clan.alias, "players") or {}).get("tags", {})
        trend_state = await self.store.get_state(t.clan.alias, "trend") or {}
        rows = legend_mod.rows(players, trend_state, t.members)
        await self.store.set_state(t.clan.alias, "legend", {"day": day})
        to = self.destination(t.settings, "members.legend")[0]
        for row in rows:
            await self.dispatch(t, "members.legend",
                                lambda L, row=row: render.legend_card(L, row),
                                member_tag=row["tag"] if to == "member_dm" else None)

    async def track_builder(self, t):
        local = t.now.astimezone(ZoneInfo(t.tz))
        if local.weekday() != 0 or local.hour < REPORT_HOUR or not t.members:
            return
        week = local.strftime("%G-W%V")
        state = await self.store.get_state(t.clan.alias, "builder") or {}
        if state.get("week") == week:
            return
        players = (await self.store.get_state(t.clan.alias, "players") or {}).get("tags", {})
        rows = builder.trophy_rows(t.members, state.get("base"), players)
        await self.store.set_state(t.clan.alias, "builder",
                                   {"week": week, "base": builder.baseline(t.members)})
        if rows:
            await self.dispatch(t, "members.builder_board", lambda L: builder.board_card(L, rows))

    async def track_roster(self, t, events):
        now_ts = int(t.now.timestamp())
        stored = await self.store.get_state(t.clan.alias, "roster")
        back = []
        for event in events or ():
            if event.get("type") != "join":
                continue
            history = await self.store.former_member(t.clan.alias, event["tag"])
            if not history:
                continue
            stored = roster_mod.readmit(stored, event["tag"], history, now_ts)
            await self.store.drop_former(t.clan.alias, event["tag"])
            facts = roster_mod.return_facts(history, now_ts)
            facts["name"] = event.get("name") or facts["name"]
            back.append(facts)
        state, _, gone = roster_mod.apply(stored, t.members, events, now_ts)
        for tag, row in gone:
            await self.store.archive_member(t.clan.alias, tag, roster_mod.archive(row, now_ts), t.now)
        due = roster_mod.anniversaries(state, now_ts)
        for row in due:
            roster_mod.mark(state, row["tag"], row["years"])
        await self.store.set_state(t.clan.alias, "roster", state)
        if back:
            await self.dispatch(t, "members.rejoin", lambda L: render.rejoin_card(L, back))
        if due:
            await self.dispatch(t, "members.anniversary", lambda L: render.anniversary_card(L, due))

    async def track_moves(self, t, events):
        family = await self.store.family_of_clan(t.clan.alias)
        if not family:
            return
        key = f"fam:{family.alias}:moves"
        moves = await self.store.kv_get(key) or {}
        ts = t.now.timestamp()
        moves = {tag: mv for tag, mv in moves.items() if mv.get("ts", 0) > ts - 72 * 3600}
        for e in events:
            if e["type"] == "leave":
                moves[e["tag"]] = {"from": t.clan.alias, "from_name": t.clan.name, "name": e["name"], "ts": ts}
        for e in events:
            if e["type"] == "join" and e["tag"] in moves and moves[e["tag"]]["from"] != t.clan.alias:
                move = moves.pop(e["tag"])
                await self.dispatch(t, "family.transfer",
                                    lambda L, e=e, move=move: render.transfer_card(L, e["name"],
                                                                                   move["from_name"], t.clan.name))
                done = {t.clan.chat_id}
                other = await self.store.clan_by_alias(move["from"])
                if other and other.chat_id not in done:
                    other_L, _ = await clan_locale(self.store, other)
                    await self.deliver(other,
                                       render.transfer_card(other_L, e["name"], move["from_name"], t.clan.name),
                                       "family.transfer")
                    done.add(other.chat_id)
                if family.chat_id and family.chat_id not in done:
                    conf = await self.family_conf(family)
                    await self.family_deliver(
                        family, "family.transfer",
                        render.transfer_card(i18n.locale(conf["lang"]), e["name"], move["from_name"], t.clan.name),
                        conf=conf)
        await self.store.kv_set(key, moves)

    async def family_conf(self, family):
        clans = await self.store.family_clans(family.alias)
        if not clans:
            return effective(None, None)
        return await self.clan_conf(clans[0])

    async def family_deliver(self, family, event, text, conf=None, markup=None):
        if not family.chat_id or not text:
            return False
        conf = conf if conf is not None else await self.family_conf(family)
        if self.destination(conf, event)[0] == "off":
            return False
        return await self.send_to(self.bot_for(family), family.chat_id, text, markup)

    async def family_jobs(self, now):
        for family in await self.store.families():
            if not self.served(family):
                continue
            try:
                await self.family_derby(family, now)
                await self.family_suggest(family, now)
                await self.family_recruit(family, now)
                await self.family_digest(family, now)
            except Exception:
                log.exception("%s: lavori famiglia falliti", family.alias)

    async def owner_jobs(self, now):
        running = self.supervisor.running()
        for bot in await self.store.bots(active_only=True):
            if bot.kind == "console" or bot.alias not in running:
                continue
            try:
                await self.handover(bot, now)
            except Exception:
                log.exception("%s: passaggio di consegne non riuscito", bot.alias)
        await self.guard.idle_bots(now)

    async def handover(self, bot, now):
        key = f"handover:{bot.alias}"
        clans = await self.store.active_clans(bot.alias)
        if not clans:
            await self.store.kv_del(key)
            return
        owner_tags = {link.tag for link in await self.store.links_by_user(bot.owner_id)}
        heir, heir_clan = None, None
        for clan in clans:
            members = await self.store.get_state(clan.alias, "members") or {}
            if owner_tags & {tag for tag, m in members.items() if m.get("role") in LEADER_ROLES}:
                await self.store.kv_del(key)
                return
            if heir:
                continue
            leaders = [tag for tag, m in members.items() if m.get("role") == "leader"]
            found = await self.store.links_for_players(leaders) if leaders else {}
            for tag in leaders:
                link = found.get(tag)
                if link and link.user_id != bot.owner_id:
                    heir, heir_clan = link, clan
                    break
        state = await self.store.kv_get(key) or {}
        since = state.get("since")
        if not since:
            await self.store.kv_set(key, {"since": now.timestamp()}, ref=bot.alias,
                                    ttl=(HANDOVER_DAYS + 16) * 86400)
            return
        if not heir or now.timestamp() - since < HANDOVER_DAYS * 86400:
            return
        old_owner = bot.owner_id
        await self.store.set_bot_owner(bot.alias, heir.user_id)
        self.supervisor.owner_changed(bot.alias, heir.user_id)
        conf = await self.clan_conf(heir_clan)
        clan_L = i18n.locale(conf["lang"])
        heir_L = await member_locale(self.store, heir, conf)
        old_L = await self.dm_locale(old_owner, conf, clan_L)
        sender = self.supervisor.bot(bot.alias)
        await self.send_to(sender, heir.user_id, render.handover_new(heir_L, heir_clan.name, HANDOVER_DAYS))
        await self.send_to(sender, old_owner, render.handover_old(old_L, heir.name, HANDOVER_DAYS))
        await self.store.kv_del(key)
        log.info("%s: gestione passata al capo collegato", bot.alias)

    async def family_derby(self, family, now):
        conf = await self.family_conf(family)
        L, tz = i18n.locale(conf["lang"]), conf["tz"]
        key = derby.saved_key(family.alias)
        records_key = f"fam:{family.alias}:records"
        saved = await self.store.kv_get(key) or {}
        doc = await self.store.tournament(saved["alias"]) if saved.get("alias") else None
        if doc and doc.get("status") != "done":
            before = tournaments.ensure(doc)
            ts = now.timestamp()
            if ts < before["ends"] and ts - saved.get("checked", 0) < familyroom.CHECK_EVERY:
                return
            doc = await derby.scores(self.store, family, before, now)
            records = await self.store.kv_get(records_key) or {}
            rows = tournaments.table(doc)
            doc["mission"] = derby.mission_of(records, doc["metric"],
                                              rows[0]["value"] if rows else 0)
            if ts < doc["ends"]:
                if doc != before or before["status"] != "running":
                    await self.store.save_tournament(doc["alias"], doc, "running")
                await self.store.kv_set(key, dict(saved, checked=ts))
                return
            await self.store.save_tournament(doc["alias"], doc, "done")
            records[doc["metric"]] = max(int(records.get(doc["metric"]) or 0), doc["mission"]["value"])
            records["metric"] = doc["metric"]
            await self.store.kv_set(records_key, records)
            clans = await self.store.family_clans(family.alias)
            for clan in clans:
                clan_L, _ = await clan_locale(self.store, clan)
                await self.deliver(clan, derby.end_card(clan_L, family, doc), "family.derby.end")
            await self.family_deliver(family, "family.derby.end", derby.end_card(L, family, doc),
                                      conf=conf)
            await self.crown(doc, clans)
        local = now.astimezone(ZoneInfo(tz))
        week = derby.week_id(now, tz)
        if local.weekday() != 0 or local.hour < REPORT_HOUR or saved.get("week") == week:
            return
        fresh = await derby.build(self.store, family, now, tz)
        if len(fresh["entries"]) < 2:
            await self.store.kv_set(key, {"week": week})
            return
        alias = await self.store.create_tournament(fresh, family.owner_id, family_alias=family.alias)
        await self.store.kv_set(key, {"week": week, "alias": alias})
        fresh["alias"] = alias
        await self.family_deliver(family, "family.derby.open", derby.view(L, family, fresh, True),
                                  conf=conf, markup=derby.keyboard(L, fresh))
        for clan in await self.store.family_clans(family.alias):
            clan_L, _ = await clan_locale(self.store, clan)
            await self.deliver(clan, derby.view(clan_L, family, fresh, True), "family.derby.open")
        await familyroom.push_notice(self.store, family, "derby", derby.notice(L, fresh), now)

    async def family_notices(self, family, conf=None):
        conf = conf if conf is not None else await self.family_conf(family)
        return i18n.locale(conf["lang"]), await familyroom.notices_of(self.store, family)

    async def derby_running(self, family):
        saved = await self.store.kv_get(derby.saved_key(family.alias)) or {}
        doc = await self.store.tournament(saved["alias"]) if saved.get("alias") else None
        return doc if doc and doc.get("status") == "running" else None

    async def family_suggest(self, family, now):
        conf = await self.family_conf(family)
        local = now.astimezone(ZoneInfo(conf["tz"]))
        key = f"fam:{family.alias}:suggest"
        saved = await self.store.kv_get(key) or {}
        week = local.strftime("%G-W%V")
        if local.weekday() != 0 or local.hour < REPORT_HOUR or saved.get("week") == week:
            return
        rows = await family_mod.rows(self.store, family)
        clans = await self.store.family_clans(family.alias)
        members = {clan.alias: await self.store.get_state(clan.alias, "members") or {}
                   for clan in clans}
        proposals = familyroom.suggestions(rows, members)
        digest = familyroom.suggest_digest(proposals)
        await self.store.kv_set(key, {"week": week, "digest": digest}, ttl=familyroom.NOTICE_TTL)
        if not proposals or saved.get("digest") == digest:
            return
        for clan in clans:
            mine = [row for row in proposals
                    if clan.alias in (row["from_alias"], row["to_alias"])]
            if not mine:
                continue
            clan_L, _ = await clan_locale(self.store, clan)
            await self.deliver(clan, familyroom.suggest_card(clan_L, family, mine),
                               "family.suggest")

    async def family_recruit(self, family, now):
        if not family.chat_id:
            return
        conf = await self.family_conf(family)
        if self.destination(conf, "family.recruit")[0] == "off":
            return
        key = f"fam:{family.alias}:recruit"
        board = await self.store.kv_get(key) or {}
        ts = now.timestamp()
        if ts - board.get("checked", 0) < familyroom.CHECK_EVERY:
            return
        rows = await family_mod.rows(self.store, family)
        L, notices = await self.family_notices(family, conf)
        running = await self.derby_running(family)
        lines = familyroom.notice_lines(L, notices,
                                        derby.board_lines(L, running) if running else None)
        digest = family_mod.recruit_digest(rows, lines)
        board["checked"] = ts
        if board.get("digest") == digest and ts - board.get("updated", 0) < 86400:
            await self.store.kv_set(key, board)
            return
        text = render.recruit_board(L, conf["tz"], family, rows, now, notices=lines)
        updated = await self.upkeep(family, board, text, digest, ts)
        if updated and updated is not board:
            board.update(updated)
        await self.store.kv_set(key, board)

    async def family_digest(self, family, now):
        if not family.chat_id:
            return
        conf = await self.family_conf(family)
        if self.destination(conf, "family.digest")[0] == "off":
            return
        L = i18n.locale(conf["lang"])
        local = now.astimezone(ZoneInfo(conf["tz"]))
        if local.weekday() != 0 or local.hour < REPORT_HOUR:
            return
        key = f"fam:{family.alias}:digest"
        week = local.strftime("%G-W%V")
        state = await self.store.kv_get(key) or {}
        if state.get("week") == week:
            return
        await self.store.kv_set(key, {"week": week})
        clan_rows, top_stars, top_donors, top_loot = await family_mod.digest_data(self.store, family, now)
        if not clan_rows:
            return
        activity = await self.family_activity(family, "month")
        await self.family_deliver(family, "family.digest",
                                  render.digest_card(L, family, clan_rows, top_stars, top_donors, top_loot,
                                                     activity=activity),
                                  conf=conf)

    async def family_activity(self, family, period):
        try:
            return await family_mod.activity_rows(self.store, family, period)
        except Exception:
            log.exception("%s: attività di famiglia non leggibile", family.alias)
            return []

    async def tournament_clans(self, doc):
        doc = tournaments.ensure(doc)
        aliases = [entry["ref"] for entry in doc["entries"] if entry["type"] == "clan"]
        if doc["scope"] == "family" and doc["family_alias"]:
            aliases += [clan.alias for clan in await self.store.family_clans(doc["family_alias"])]
        for alias in (doc["origin"], doc["clan_alias"]):
            if alias:
                aliases.insert(0, alias)
        clans, seen = [], set()
        for alias in aliases:
            if alias in seen:
                continue
            seen.add(alias)
            clan = await self.store.clan_by_alias(alias)
            if clan and clan.active and self.served(clan):
                clans.append(clan)
        return clans

    async def tournament_jobs(self, now):
        for doc in await self.store.live_tournaments():
            try:
                await self.tournament_tick(doc, now)
            except Exception:
                log.exception("%s: torneo non aggiornato", doc.get("alias"))

    async def tournament_excluded(self, doc):
        alias = doc.get("clan_alias")
        if not alias:
            return []
        return sorted(await privacy.excluded(self.store, alias))

    async def tournament_tick(self, doc, now):
        before = tournaments.ensure(doc)
        doc = tournaments.eligible(before, await self.tournament_excluded(before))
        doc, results = await tourney_results.refresh(self.store, doc, now)
        doc, events = tournaments.advance(doc, now.timestamp())
        events = results + events
        status = "done" if any(e["type"] in ("final", "empty") for e in events) else (
            "running" if tournaments.started(doc) else "signup")
        if doc != before or status != before["status"]:
            await self.store.save_tournament(doc["alias"], doc, status)
        if not events:
            return
        clans = await self.tournament_clans(doc)
        for clan in clans:
            L, _ = await clan_locale(self.store, clan)
            for event in events:
                text = tourney_ui.announcement(L, doc, event)
                if text:
                    name = "final" if event["type"] == "empty" else event["type"]
                    await self.deliver(clan, text, tournaments.event(name, doc["scope"]))
        posted = [event for event in events if event["type"] in ("signup", "final")]
        if posted and doc.get("family_alias"):
            family = await self.store.family_by_alias(doc["family_alias"])
            if family:
                conf = await self.family_conf(family)
                FL = i18n.locale(conf["lang"])
                for event in posted:
                    await familyroom.push_notice(self.store, family, "tournament",
                                                 tourney_ui.notice(FL, doc, event), now)
        if any(event["type"] == "final" for event in events):
            await self.crown(doc, clans)

    async def crown(self, doc, clans):
        eid = tournaments.winner(doc)
        if not eid:
            return
        title = "Derby" if doc["kind"] == "derby" else "Torneo"
        name = tournaments.name_of(doc, eid)
        for clan in clans:
            _, tz = await clan_locale(self.store, clan)
            hall = warstats.hall_state(await self.store.get_state(clan.alias, "hall"))
            season = scoring.season_id(now_utc(), tz)
            row = next((item for item in hall["seasons"] if item.get("season") == season), None)
            if row is None:
                row = {"season": season, "titles": {}}
                hall["seasons"].append(row)
            titles = row.get("titles")
            row["titles"] = dict(titles if isinstance(titles, dict) else {},
                                 **{title: [name, len(doc["entries"])]})
            await self.store.set_state(clan.alias, "hall", warstats.hall_state(hall))

    async def send_to(self, bot, chat_id, text, markup=None, thread_id=None, quiet=False):
        extra = {"link_preview_options": media.preview(text, self.site)}
        if markup:
            extra["reply_markup"] = markup
        if thread_id:
            extra["message_thread_id"] = thread_id
        if quiet:
            extra["disable_notification"] = True
        return await platform_notify(bot, chat_id, text, **extra)

    async def send(self, clan, text, thread=None, hold=True, quiet=False, markup=None, note=None):
        bot = self.bot_for(clan)
        if not bot:
            log.warning("%s: nessun bot in esecuzione per questo clan", clan.alias)
            return False
        if not self.guard.allow(clan.chat_id):
            if hold:
                await self.hold_back(clan, text, thread)
                log.info("%s: tetto di messaggi al minuto, rimando al giro dopo", clan.alias)
            return False

        async def flooded(error):
            if await self.guard.flood(self.alias_of(clan)):
                if hold:
                    await self.hold_back(clan, text, thread)
                return False
            await asyncio.sleep(error.retry_after + 1)
            return True

        async def refused(error):
            if thread and topics.is_missing_thread(error):
                await self.drop_thread(clan, thread)
                return await self.send(clan, text, hold=hold, quiet=quiet, markup=markup, note=note)
            return None

        def sent(message):
            self.guard.note_sent(clan.alias)
            if note is not None:
                note(getattr(message, "message_id", None))

        return await delivery.to_chat(self.store, bot, clan, text, thread_id=thread or None, silent=quiet,
                                      reply_markup=markup or None, on_flood=flooded, on_refused=refused,
                                      on_sent=sent,
                                      extra={"link_preview_options": media.preview(text, self.site)})

    async def send_sticker(self, t, kind):
        to, thread, _ = self.destination(t.settings, t.sticker_event)
        if to not in GROUP_DESTINATIONS:
            return
        state = await self.store.get_state(t.clan.alias, stickers.STATE) or {}
        file_id = (state.get("files") or {}).get(kind)
        bot = self.bot_for(t.clan)
        if not file_id or not bot:
            return
        try:
            await bot.send_sticker(t.clan.chat_id, file_id, disable_notification=t.quiet,
                                   message_thread_id=thread)
        except TelegramError as e:
            log.warning("%s: sticker non inviato: %s", t.clan.alias, e)

    async def drop_thread(self, clan, thread):
        stored = await self.store.get_state(clan.alias, "settings") or {}
        left = topics.forget(stored, thread)
        if left != (stored.get("topics") or {}):
            stored["topics"] = left
            await self.store.set_state(clan.alias, "settings", stored)
