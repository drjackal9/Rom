import logging
import time

from . import (accent, advice, availability, badges, base_videos, boards, challenges, cwl_app,
               door, goals, growth, intents, linking, manager_actions, manager_lists, media,
               more_lists, platform_ban, progress, recap, recruit_block, render, roles, usage,
               views, warstats)
from .handlers import active_war, current_plan
from .poller import FAST_INTERVAL
from .retention import WAR_HISTORY_KEEP
from .settings import pack_on
from .util import now_utc
from .web import app_page, payload

log = logging.getLogger("clashbot.publish")

ACCENT = "clan_accent"
BEAT_EVERY = 2
NOTES_EVERY = 60
KEEP_ERRORS = WAR_HISTORY_KEEP
TEXT_MAX = render.MAX_LEN
LEFT_NOTE = "feed.person.left"


class Recent(logging.Handler):
    def __init__(self, keep=KEEP_ERRORS):
        super().__init__(level=logging.WARNING)
        self.keep = keep
        self.rows = []

    def emit(self, record):
        try:
            text = record.getMessage()[:TEXT_MAX]
        except Exception:
            return
        self.rows.append({"at": int(record.created), "level": record.levelname,
                          "who": record.name, "text": text})
        del self.rows[:-self.keep]

    def errors_in(self, window, now=None):
        edge = (time.time() if now is None else float(now)) - float(window)
        return [row for row in self.rows if row.get("at", 0) >= edge]


RECENT = Recent()


def watch_errors():
    root = logging.getLogger("clashbot")
    if RECENT not in root.handlers:
        root.addHandler(RECENT)


async def db_ok(store):
    try:
        return await store.pool.fetchval("select 1") == 1
    except Exception:
        return False


def beat_age(path, now):
    try:
        return max(0.0, now - path.stat().st_mtime)
    except OSError:
        return float("inf")


class Beat:
    def __init__(self, store, supervisor, coc, heartbeat, clock=time.monotonic, client=None):
        self.store = store
        self.supervisor = supervisor
        self.coc = coc
        self.heartbeat = heartbeat
        self.clock = clock
        self.client = client
        self.last_notes = None
        self.digests = {}
        self.wars = {}

    async def once(self):
        moved = await intents.drain(self.store, self, now_utc()) > 0
        if self.last_notes is None or self.clock() - self.last_notes >= NOTES_EVERY:
            self.last_notes = self.clock()
            await self.notes()
            moved = True
        return moved

    async def notes(self):
        now = now_utc()
        wanted = set(self.supervisor.fixed) | {
            bot.alias for bot in await self.store.bots(active_only=True)
        }
        interval = getattr(self.supervisor.poller, "interval", FAST_INTERVAL)
        note = payload.services_note(
            now, beat_age(self.heartbeat, time.time()), interval, await db_ok(self.store),
            self.coc.keys_alive(), len(self.coc.keys), len(self.supervisor.running()), len(wanted),
        )
        await self.store.web_note_set("services", note)
        await self.platform()

    async def platform(self):
        now = now_utc()
        bots = await self.store.bots()
        console = next((bot for bot in bots if bot.kind == "console"), None)
        await self.store.web_note_set("login", {
            "bot": console.username if console else None,
            "url": (await media.site_base(self.store) or "").rstrip("/") or None,
        })
        counts = {bot.alias: await self.store.count_clans(bot.alias) for bot in bots}
        await self.store.web_note_set("report", usage.report(
            now, bots, self.supervisor.running(), await self.store.active_clans(),
            RECENT.rows, counts))
        await self.store.web_note_set(
            "usage", await usage.snapshot(self.store, self.supervisor, now))

    async def clan(self, clan, kind, body, slug):
        seen = self.digests.get((clan.alias, kind))
        fresh = payload.digest(body)
        if seen and seen[0] == fresh and self.clock() - seen[1] < payload.REFRESH:
            return False
        await self.store.web_publish(clan.alias, kind, slug, body)
        self.digests[(clan.alias, kind)] = (fresh, self.clock())
        return True

    async def accent_of(self, clan, info):
        url = (info or {}).get("badge")
        if not url:
            return None
        saved = await self.store.get_state(clan.alias, ACCENT) or {}
        if url in saved:
            return saved[url]
        data = await media.badge(url, self.client)
        tone = accent.dominant(data)
        if data is not None:
            await self.store.set_state(clan.alias, ACCENT, {url: tone})
        return tone

    async def wars_of(self, clan, fought):
        seen = self.wars.get(clan.alias)
        if seen and seen[0] == fought:
            return seen[1]
        records = await self.store.recent_wars(clan.alias, WAR_HISTORY_KEEP)
        self.wars[clan.alias] = (fought, records)
        return records

    async def advice_of(self, clan, war):
        if not war:
            return {}
        return advice.by_th(await self.store.recent_wars(clan.alias, WAR_HISTORY_KEEP))

    async def walled_of(self, state):
        found = set(platform_ban.uids(state))
        wanted = platform_ban.tags(state)
        rows = await self.store.links_for_players(wanted) if wanted else {}
        for link in rows.values():
            found.add(int(link.user_id))
        return sorted(found)

    async def left_name(self, uid, members):
        links = await self.store.links_by_user(int(uid))
        if not links or any(link.tag in members for link in links):
            return ""
        return links[0].name or ""

    async def told_left(self, clan, conf, levels, out, now, members):
        for uid in out:
            name = await self.left_name(uid, members)
            if not name:
                continue
            for manager in sorted(levels or {}):
                await linking.tell(self.store, clan.alias, manager, conf,
                                   lambda L, name=name: L.t(LEFT_NOTE, name=name), now)

    async def door_of(self, clan, slug, verified, now, members=None, conf=None, levels=None,
                      here=None):
        state = door.state_of(await self.store.get_state(clan.alias, door.KIND))
        fresh = door.seed(state, verified, now.timestamp())
        here = verified if here is None else here
        out = door.told(fresh, here) if members else []
        fresh = door.present(door.left(fresh, here), here) if members else fresh
        blocked = recruit_block.state_of(await self.store.get_state(clan.alias,
                                                                   recruit_block.KIND))
        fresh = door.bans(fresh, [row["who"] for row in recruit_block.rows(blocked)])
        fresh = door.walls(fresh, await self.walled_of(await platform_ban.load(self.store)))
        if fresh != state:
            await self.store.set_state(clan.alias, door.KIND, fresh)
        await self.told_left(clan, conf, levels, out, now, members or {})
        return door.marks(fresh, lambda uid: payload.mark_for(self.store.vault, slug, uid))

    async def seats_of(self, clan, members, links, levels):
        found = {"seats": {}, "profiles": {}, "linked": {}, "avail": {}, "approved": [],
                 "here": []}
        snapshots = (await self.store.get_state(clan.alias, "players") or {}).get("tags") or {}
        said = (await self.store.get_state(clan.alias, availability.STATE) or {}).get("votes") or {}
        wanted = await self.store.get_state(clan.alias, "goals") or {}
        found["snapshots"] = snapshots
        for tag, link in links.items():
            uid = str(link.user_id)
            choice = availability.choice(said.get(uid))
            verified = getattr(link, "verified", True)
            found["seats"][uid] = {"tag": tag, "name": link.name,
                                   "level": levels.get(link.user_id), "lang": link.lang,
                                   "avail": choice,
                                   "verified": verified,
                                   "whisper": getattr(link, "whisper", False),
                                   "goal": goals.view(snapshots.get(tag), wanted.get(tag))}
            found["linked"][tag] = {"verified": verified}
            found["avail"][tag] = choice
            if snapshots.get(tag):
                found["profiles"][uid] = render.me_facts(tag, snapshots[tag])
            if tag in members:
                found["here"].append(link.user_id)
            if verified and tag in members:
                found["approved"].append(link.user_id)
        return found

    async def app(self, clan, conf, members, info, now):
        war, kind, day = await active_war(self.store, clan)
        members = members or {}
        links = await self.store.links_for_players(
            sorted(set(members) | set((war or {}).get("members") or {})))
        levels = await roles.managers(self.store, clan, conf, members)
        who = await self.seats_of(clan, members, links, levels)
        seats, profiles, snapshots = who["seats"], who["profiles"], who["snapshots"]
        slug = payload.slug_for(self.store.vault, clan.alias)
        porta = await self.door_of(clan, slug, who["approved"], now, members, conf, levels,
                                   who["here"])
        board_state = await self.store.get_state(clan.alias, "boards") or {}
        sections = {pack: boards.lines_of(board_state, pack)
                    for pack in boards.SECTION_ORDER if pack_on(conf, pack)}
        cwl = await self.store.get_state(clan.alias, "cwl")
        hall = warstats.hall_state(await self.store.get_state(clan.alias, "hall"))
        fought = int(hall["records"].get("wars") or 0)
        walked = await self.store.get_state(clan.alias, "progress")
        grown = growth.growth_of(await self.store.get_state(clan.alias, "trend"), walked, members)
        medals = badges.by_player(await challenges.load(self.store, clan.alias), members,
                                  owners={tag: link.user_id for tag, link in links.items()})
        more = await more_lists.of(self.store, clan, conf, members)
        body = payload.app_payload(clan, conf, info, members, war, kind, day,
                                   await current_plan(self.store, clan, war), seats, sections,
                                   profiles, now,
                                   await manager_actions.screens(self.store, clan, conf, members,
                                                                 levels),
                                   await manager_lists.of(self.store, clan, conf, war, levels),
                                   cwl=await cwl_app.summary(self.store, clan, cwl, snapshots),
                                   links=who["linked"], avail=who["avail"],
                                   record=hall["records"],
                                   growth=grown, medals=medals,
                                   bases=more["bases"], recruit=more["recruit"],
                                   family=more["family"], award=more["award"],
                                   duels=more["duels"],
                                   advice=await self.advice_of(clan, war),
                                   attack_videos=base_videos.attack_videos(
                                       more["bases"]["library"]["videos"]),
                                   accent=await self.accent_of(clan, info),
                                   events=boards.events_of(board_state, sections),
                                   idle=[row for row in progress.idle(walked, now)
                                         if row["tag"] in members],
                                   recap=recap.build(walked, medals, members, now,
                                                     conf.get("tz") or "UTC"),
                                   door=porta,
                                   views=views.state_of(
                                       await self.store.get_state(clan.alias, views.KIND)),
                                   badge=(info or {}).get("badge"),
                                   **await app_page.extras(self.store, clan, conf, links, now,
                                                           await self.wars_of(clan, fought)))
        return await self.clan(clan, payload.APP, body, slug)
