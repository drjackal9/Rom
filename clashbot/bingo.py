import hashlib
import random

from . import badges, challenges, render
from .events import performances, war_key

EVENT = "challenges.bingo"
ALIVE = ("preparation", "inWar", "warEnded")
LIVE = ("inWar", "warEnded")
SIZE = 3
CELLS = ("th_up", "opening", "no_missed", "all_scored", "perfect", "wall",
         "double", "streak3", "uphill", "no_triple_against", "total", "comeback")
TRIPLE = 3
STREAK = 3
FULL = 100
MARK = "✅"
BLANK = "▫️"


def card_for(key):
    seed = int(hashlib.sha256(str(key).encode()).hexdigest()[:12], 16)
    return random.Random(seed).sample(list(CELLS), SIZE * SIZE)


def attackers(war):
    rows = []
    for tag, member in (war.get("members") or {}).items():
        for attack in member.get("attacks") or []:
            defender = (war.get("defenders") or {}).get(attack.get("defender")) or {}
            rows.append({"tag": tag, "pos": member.get("pos"), "th": member.get("th"),
                         "stars": attack.get("stars") or 0, "order": attack.get("order") or 0,
                         "d_pos": defender.get("pos"), "d_th": defender.get("th")})
    rows.sort(key=lambda row: row["order"])
    return rows


def _conceded(war):
    taken = {}
    for member in (war.get("defenders") or {}).values():
        for attack in member.get("attacks") or []:
            target = attack.get("defender")
            taken[target] = max(taken.get(target, 0), attack.get("stars") or 0)
    return taken


def marks(war, behind=False):
    hit = set()
    attacks = attackers(war or {})
    if not attacks:
        return hit
    for row in attacks:
        if row["stars"] < TRIPLE:
            continue
        if row["d_th"] and row["th"] and row["d_th"] > row["th"]:
            hit.add("th_up")
        if row["d_pos"] and row["pos"] and row["d_pos"] < row["pos"]:
            hit.add("uphill")
    if attacks[0]["stars"] == TRIPLE:
        hit.add("opening")
    streak = 0
    for row in attacks:
        streak = streak + 1 if row["stars"] == TRIPLE else 0
        if streak >= STREAK:
            hit.add("streak3")
    rows = performances(war)
    if rows and not any(row["missed"] for row in rows):
        hit.add("no_missed")
    if rows and all(row["stars"] > 0 for row in rows):
        hit.add("all_scored")
    size = int(war.get("teamSize") or 0)
    clan, opponent = war.get("clan") or {}, war.get("opponent") or {}
    if size and clan.get("stars") == size * TRIPLE:
        hit.add("perfect")
    if float(clan.get("destr") or 0) >= FULL:
        hit.add("total")
    conceded = _conceded(war)
    if any(conceded.get(tag, 0) == 0 for tag in war.get("members") or ()):
        hit.add("wall")
    if TRIPLE not in set(conceded.values()):
        hit.add("no_triple_against")
    if clan.get("stars") and clan["stars"] >= 2 * (opponent.get("stars") or 0):
        hit.add("double")
    if behind and _ahead(clan, opponent):
        hit.add("comeback")
    return hit


def _ahead(clan, opponent):
    return ((clan.get("stars") or 0, clan.get("destr") or 0)
            > (opponent.get("stars") or 0, opponent.get("destr") or 0))


def bingo_lines(cells, hit):
    lines = []
    for i in range(SIZE):
        lines.append([cells[i * SIZE + j] for j in range(SIZE)])
        lines.append([cells[j * SIZE + i] for j in range(SIZE)])
    lines.append([cells[i * SIZE + i] for i in range(SIZE)])
    lines.append([cells[i * SIZE + (SIZE - 1 - i)] for i in range(SIZE)])
    return [line for line in lines if all(cell in hit for cell in line)]


def board(L, cells, hit):
    grid = "\n".join(" ".join(MARK if cells[i * SIZE + j] in hit else BLANK for j in range(SIZE))
                     for i in range(SIZE))
    legend = "\n".join((MARK if cell in hit else BLANK) + " " + L.t(f"bingo.cell.{cell}")
                       for cell in cells)
    return grid + "\n\n" + render.quote(legend)


def digest(current, ended):
    return "|".join(current.get("hit") or ()) + ("|end" if ended else "")


def section(L, state):
    current = state.get("bingo") or {}
    if not current.get("cells"):
        return None
    return L.t("bingo.section", done=len(current.get("hit") or []), total=SIZE * SIZE)


def card_text(L, current, ended):
    text = render.card("🎲", L.t("bingo.title"), board(L, current["cells"], set(current["hit"])))
    if ended:
        text += "\n" + L.t("bingo.closed", done=len(current["hit"]), total=SIZE * SIZE)
    return text


async def card(poller, t, current, ended, thread):
    fresh = digest(current, ended)
    if current.get("message_id") and current.get("digest") == fresh:
        return
    state = {"message_id": current.get("message_id"), "digest": current.get("digest")}
    updated = await poller.upkeep(t.clan, state, card_text(t.L, current, ended), fresh,
                                  t.now.timestamp(), t.quiet, thread=thread, pin=False)
    if updated is state:
        return
    current["message_id"] = (updated or {}).get("message_id")
    current["digest"] = (updated or {}).get("digest")


async def run(poller, t, war):
    dest, thread, _ = poller.destination(t.settings, EVENT)
    if dest == "off":
        return
    state = await challenges.load(poller.store, t.clan.alias)
    current = state["bingo"]
    if not war or war.get("state") not in ALIVE:
        if current.get("cells") or current.get("message_id"):
            state["bingo"] = {"done": current.get("done")}
            await challenges.save(poller.store, t.clan.alias, state)
        return
    key = war_key(war)
    if current.get("done") == key:
        return
    if current.get("war") != key:
        current = {"war": key, "cells": card_for(key), "hit": [], "behind": False, "bingo": False,
                   "done": current.get("done"), "message_id": None, "digest": None}
    if _ahead(war.get("opponent") or {}, war.get("clan") or {}):
        current["behind"] = True
    seen = set(current.get("hit") or ()) | marks(war, current["behind"])
    hit = {cell for cell in seen if cell in current["cells"]}
    current["hit"] = sorted(hit, key=current["cells"].index)
    ended = war.get("state") == "warEnded"
    line = bool(bingo_lines(current["cells"], hit)) and not current.get("bingo")
    if line:
        current["bingo"] = True
        badges.grant_all(state, sorted({row["tag"] for row in attackers(war)}), "bingo",
                         int(t.now.timestamp()))
        challenges.note(state, "bingo", war=key, cells=len(current["hit"]), ts=int(t.now.timestamp()))
    if war.get("state") in LIVE:
        await card(poller, t, current, ended, thread)
    if line:
        await poller.dispatch(t, EVENT,
                              lambda L: render.card("🎲", L.t("bingo.title"), L.t("bingo.done")))
    state["bingo"] = {"done": key} if ended else current
    await challenges.save(poller.store, t.clan.alias, state)
