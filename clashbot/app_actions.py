from telegram import MenuButtonWebApp, WebAppInfo
from telegram.error import TelegramError

from . import (availability, awards, challenges, duels, goals, guess_attack, handlers, i18n,
               polls, predictions, quiz, reasons, reports, scoring, share_cards)
from .quizbank import OPTIONS as QUIZ_OPTIONS
from .reasons import refuse
from .scoring import POLL_OPTIONS
from .web import app_people, app_recap, payload

MENU = "web.app.menu"


def _int(value):
    raw = str(value or "")
    return int(raw) if raw.isdigit() else -1


def _voted(voted):
    return True if voted is not None else refuse(reasons.CLOSED)


async def availability_set(act):
    picked = str(act.body.get("choice") or "")
    if picked not in availability.OPTIONS:
        return refuse(reasons.BAD)
    return _voted(await polls.set_vote(act.store, act.clan.alias, availability.STATE, act.uid,
                                       act.name, availability.OPTIONS.index(picked)))


async def goal_set(act):
    villages = (await act.store.get_state(act.clan.alias, "players") or {}).get("tags") or {}
    wanted = str(act.body.get("goal") or "")
    hero = str(act.body.get("hero") or "") or None
    target = _int(act.body.get("target"))
    chosen = next((pick for pick in goals.choices(villages.get(act.tag), wanted)
                   if pick["target"] == target and pick["hero"] == hero), None)
    if not chosen:
        return refuse(reasons.BAD)
    stored = await act.store.get_state(act.clan.alias, "goals") or {}
    stored[act.tag] = {"kind": wanted, "hero": chosen["hero"], "target": chosen["target"]}
    await act.store.set_state(act.clan.alias, "goals", stored)
    return True


async def quiz_answer(act):
    return _voted(await polls.set_vote(act.store, act.clan.alias, quiz.STATE_KEY, act.uid,
                                       act.name, _int(act.body.get("option")),
                                       size=QUIZ_OPTIONS))


async def guess_answer(act):
    tz = (act.conf or {}).get("tz")
    day = guess_attack.day_of(act.now, tz)
    found = guess_attack.round_for(
        await act.store.recent_wars(act.clan.alias, guess_attack.WARS), act.clan.alias, day)
    if not found:
        return refuse(reasons.CLOSED)
    stars, percent = _int(act.body.get("stars")), _int(act.body.get("percent"))
    if not guess_attack.fits(stars, percent):
        return refuse(reasons.BAD)
    state = await act.store.get_state(act.clan.alias, guess_attack.STATE) or {}
    got = guess_attack.answer(state, act.uid, found, stars, percent)
    if got is None:
        return refuse(reasons.TAKEN)
    await act.store.set_state(act.clan.alias, guess_attack.STATE, state)
    season = (await act.store.get_state(act.clan.alias, "season")
              or scoring.empty_season(scoring.season_id(act.now, tz or "UTC")))
    scoring.apply_play(season, act.uid, act.name, points=got)
    await act.store.set_state(act.clan.alias, "season", season)
    return True


async def award_vote(act):
    poll = await awards.load_poll(act.store, act.clan.alias)
    return _voted(await polls.set_vote(act.store, act.clan.alias, awards.STATE_KEY, act.uid,
                                       act.name, _int(act.body.get("option")),
                                       size=len((poll or {}).get("rows") or ())))


async def prediction_set(act):
    wanted = str(act.body.get("poll") or "")
    if wanted not in predictions.KINDS:
        return refuse(reasons.BAD)
    return _voted(await polls.set_vote(act.store, act.clan.alias, predictions.state_key(wanted),
                                       act.uid, act.name, _int(act.body.get("option")),
                                       size=POLL_OPTIONS))


async def duel_challenge(act):
    links, _ = await duels.rivals_of(act.store, act.clan, act.uid)
    other = links.get(str(act.body.get("rival") or ""))
    if not other or other.user_id == act.uid:
        return refuse(reasons.BAD)
    state = await challenges.load(act.store, act.clan.alias)
    duel = duels.propose(state, {"tag": act.tag, "name": act.name, "user_id": act.uid},
                         {"tag": other.tag, "name": other.name, "user_id": other.user_id},
                         str(act.body.get("metric") or ""), str(act.body.get("duration") or ""),
                         act.now)
    if not duel:
        return refuse(reasons.TAKEN)
    await challenges.save(act.store, act.clan.alias, state)
    return True


async def duel_accept(act):
    state = await challenges.load(act.store, act.clan.alias)
    progress = await act.store.get_state(act.clan.alias, "progress") or {}
    duel = duels.accept(state, str(act.body.get("duel") or ""), act.uid, progress, act.now)
    if not duel:
        return refuse(reasons.GONE)
    await challenges.save(act.store, act.clan.alias, state)
    return True


async def report_send(act):
    reason = str(act.body.get("reason") or "")
    if reason not in reports.REASONS:
        return refuse(reasons.BAD)
    if not await reports.add(act.store, act.clan.alias, act.uid, reason, act.now):
        return refuse(reasons.BRAKE)
    return True


async def _locale(act):
    links = await act.store.links_by_user(act.uid)
    lang = next((link.lang for link in links if link.tag == act.tag), None)
    return i18n.locale(lang or (act.conf or {}).get("lang"))


async def _page(act):
    slug = payload.slug_for(act.store.vault, act.clan.alias)
    return await act.store.web_page(slug, payload.APP) or {}


def _shared(prepared):
    return True if prepared else refuse(reasons.GONE)


async def share_week(act):
    page = await _page(act)
    seat = (page.get("seats") or {}).get(str(act.uid)) or {}
    view = app_people.me_view(page, dict(seat, uid=act.uid))
    if not view.get("tag"):
        return refuse(reasons.NOT_LINKED)
    spec = share_cards.week_card(await _locale(act), view)
    return _shared(await share_cards.prepare(act.bot, act.store, act.clan.alias, act.uid, spec,
                                             act.body.get("id")))


async def share_season(act):
    page = await _page(act)
    seat = (page.get("seats") or {}).get(str(act.uid)) or {}
    view = app_recap.view_of(page, seat)
    if not view or not view.get("me"):
        return refuse(reasons.GONE)
    spec = share_cards.season_card(await _locale(act), view, act.name)
    return _shared(await share_cards.prepare(act.bot, act.store, act.clan.alias, act.uid, spec,
                                             act.body.get("id")))


async def share_war(act):
    war, kind, day = await handlers.active_war(act.store, act.clan, handlers.ENDED_WAR)
    if not war:
        return refuse(reasons.NOT_IN_WAR)
    spec = share_cards.war_card(await _locale(act), war, kind, day)
    return _shared(await share_cards.prepare(act.bot, act.store, act.clan.alias, act.uid, spec,
                                             act.body.get("id")))


async def share_clan(act):
    people = app_people.members_view(await _page(act))
    if not (people.get("climb") or {}).get(share_cards.WEEK):
        return refuse(reasons.GONE)
    spec = share_cards.clan_card(await _locale(act), people)
    return _shared(await share_cards.prepare(act.bot, act.store, act.clan.alias, act.uid, spec,
                                             act.body.get("id")))


async def lang_set(act):
    wanted = str(act.body.get("lang") or "")
    if wanted not in i18n.LANGUAGES:
        return refuse(reasons.BAD)
    await act.store.set_link_lang(act.uid, wanted)
    return True


async def app_opened(act):
    url = await handlers.app_url(act.store, act.clan)
    if not act.bot or not url:
        return refuse(reasons.GONE)
    L = await _locale(act)
    try:
        await act.bot.set_chat_menu_button(
            chat_id=act.uid,
            menu_button=MenuButtonWebApp(text=L.t(MENU), web_app=WebAppInfo(url=url)))
    except TelegramError:
        return refuse(reasons.GONE)
    return True


HANDLERS = {
    "availability.set": availability_set,
    "goal.set": goal_set,
    "quiz.answer": quiz_answer,
    "guess.answer": guess_answer,
    "duel.challenge": duel_challenge,
    "duel.accept": duel_accept,
    "award.vote": award_vote,
    "prediction.set": prediction_set,
    "report.send": report_send,
    "share.week": share_week,
    "share.season": share_season,
    "share.war": share_war,
    "share.clan": share_clan,
    "lang.set": lang_set,
    "app.opened": app_opened,
}
