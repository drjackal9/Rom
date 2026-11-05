import { html } from "../vendor/htm-preact-standalone.module.js";
import { countdown, fill } from "./model.js";
import { duelDone, meSet, pollDone, quizDone, warBook, warFree, warMirror } from "./guess.js";
import { initials } from "./art.js";
import { chosen } from "./me_link.js";
import { cwlDay, cwlStrip, pickedDay } from "./cwl.js";
import { FREE, MINE, PREP, baseSheet, enemyGrid, spot } from "./war_tiles.js";
import { warEnd } from "./war_end.js";
import { confetti, countUp, span } from "./fx.js";
import { Bar, Big, Card, Chip, Chips, Empty, Grid, Score, Strip, Tile, Timer } from "./ui.js";

const PHASES = { preparation: "prep", inWar: "left", warEnded: "ended" };
const ANSWER = { quiz: "quiz.answer", prediction: "prediction.set" };
const FLOOD_WINDOW = 3600;
const FOUGHT = "inWar";
const URGENT = "urgent";
const LIVE = "live";
const WHISPER = "link.whisper";
const SEEN = "seen_attack";
const JOIN = ":";
const ASKED = "whisper_asked";
const ME = "me";

export function lastHour(view, now) {
  const me = (view || {}).mine;
  if (!me || !me.left || !view.end || view.phase !== FOUGHT) { return false; }
  return view.end - now < FLOOD_WINDOW;
}

export function shotKey(view) {
  const last = ((view || {}).mine || {}).last_attack;
  if (!last) { return null; }
  return String(view.start) + JOIN + String(last.at);
}

export function wantsWhisper(state) {
  const me = (state || {}).me_view || {};
  const mine = ((state || {}).war_view || {}).mine;
  return Boolean(me.tag && !me.whisper && mine && mine.left > 0);
}

function sparks(canvas) {
  if (canvas) { confetti(canvas, Number(canvas.dataset.specks) || 0); }
}

function climb(node) {
  if (!node) { return; }
  const shape = node.dataset.shape || "";
  countUp(0, Number(node.dataset.to) || 0, span(node),
          (value) => { node.textContent = fill(shape, "destr", value); });
}

function tempo(view, now) {
  if (view.phase !== FOUGHT) { return null; }
  return lastHour(view, now) ? LIVE + " " + URGENT : LIVE;
}

function clock(words, view, now, mark) {
  const end = view.phase === PREP ? view.start : view.end;
  return html`<${Timer} left=${countdown(end || now, now)} words=${words} mark=${mark}
                        tone=${tempo(view, now)}
                        label=${words["war_" + (PHASES[view.phase] || "left")]} />`;
}

function shot(view, words, conf, tools) {
  const last = (view.mine || {}).last_attack;
  if (!last || (tools.local || {})[SEEN] === shotKey(view)) { return null; }
  const whole = Math.round(Number(last.destr) || 0);
  const most = Number(conf.FULL) || 0;
  const shape = words.war_destr;
  const tally = html`<span class="sub" data-to=${whole} data-shape=${shape}
                           ref=${climb}>${fill(shape, "destr", whole)}</span>`;
  return html`
    <${Card} tone="shot" title=${words.war_shot}>
      ${most > 0 && last.stars >= most ? html`
        <canvas class="fx" data-specks=${whole} ref=${sparks}></canvas>` : null}
      <${Big} value=${last.stars} label=${tally} />
    <//>`;
}

function strips(state, words, conf, tools) {
  const me = state.me_view || {};
  return html`
    ${me.tag ? null : html`
      <${Strip} text=${words.strip_link} action=${words.strip_go}
                onAction=${() => tools.pick("tab", ME)} />`}
    ${wantsWhisper(state) && (tools.local || {})[ASKED] === "" ? html`
      <${Strip} text=${words.strip_whisper} action=${words.strip_yes}
                onAction=${() => tools.run(WHISPER, { village: me.tag,
                                                      on: (conf.SWITCH || [])[0] },
                                           meSet("whisper", true))} />` : null}`;
}

function match(words, view, now) {
  const us = view.us || {};
  const them = view.them || {};
  const ours = Number(us.stars) || 0;
  const theirs = Number(them.stars) || 0;
  return html`
    <${Card} tone="match" hero stripe>
      <${Score} hero ours=${{ value: ours, label: us.name }}
                theirs=${{ value: theirs, label: them.name }}
                vs=${html`
                  ${clock(words, view, now, ours + JOIN + theirs)}
                  <span class="sub">${words.war_vs}</span>`} />
    <//>`;
}

function mineOf(state, view, tag) {
  const seat = ((state || {}).me_view || {}).tag;
  if (!tag || tag === seat) { return view.mine; }
  const row = ((state || {}).ours || []).find((one) => one.tag === tag);
  if (!row) { return null; }
  const left = Number(row.left) || 0;
  const held = ((state || {}).rows || []).find((one) => one.assignee_tag === tag) || null;
  return { pos: row.pos, th: row.th, left: left,
           used: Math.max(0, (Number(view.per_member) || 0) - left),
           stars: Number(row.stars) || 0, destr: Number(row.destr) || 0,
           target: held ? { pos: held.pos, th: held.th } : null, last_attack: null };
}

function mine(words, view, run, me, own) {
  if (!me) { return null; }
  const held = me.target;
  return html`
    <${Card} tone="attacks" title=${words.war_mine}>
      <${Grid}>
        <${Tile} big=${me.used} label=${words.war_hits} mark=${me.used} />
        <${Tile} big=${held ? fill(words.pos, "pos", held.pos) : words.war_free}
                 label=${words.war_target} tone=${held ? MINE : FREE}
                 sub=${held ? fill(words.th, "th", held.th)
                            : (own ? words.war_change : "")}
                 mark=${held ? held.pos : ""} />
      <//>
      <${Bar} done=${me.used} total=${view.per_member} />
      ${own ? html`
      <${Chips}>
        ${held ? html`
          <${Chip} text=${words.war_release}
                   onTap=${() => run("target.free", { pos: String(held.pos) },
                                     warFree(held.pos))} />` : null}
        ${(view.free || []).map((row) => html`
          <${Chip} text=${spot(words, row.pos, row.th)} on=${row.pos === me.pos}
                   locked=${Boolean(held)}
                   onTap=${() => run("target.set", { pos: String(row.pos),
                                                     who: String(me.pos) },
                                 warBook(row))} />`)}
      <//>` : null}
    <//>`;
}

function missing(words, view) {
  const rows = view.missing || [];
  if (!rows.length) { return null; }
  return html`
    <${Card} tone="missing" title=${words.war_missing} mark=${rows.length}>
      <${Grid} cols="3">
        ${rows.map((row) => html`
          <${Tile} big=${row.left} label=${initials(row.name)} mark=${row.left} />`)}
      <//>
    <//>`;
}

function waiting(row, tools) {
  if (row.kind === "duel") {
    return () => tools.run("duel.accept", { duel: String(row.id) }, duelDone(row.id));
  }
  if (row.kind === "link") { return () => tools.pick("tab", ME); }
  return () => tools.pick("sheet", row);
}

function todo(words, state, tools) {
  const rows = state.todo || [];
  return html`
    <${Card} title=${words.todo_title}>
      ${rows.length ? html`
        <${Chips} tone="todo">
          ${rows.map((row) => html`
            <${Chip} text=${words["todo_" + row.kind]} onTap=${waiting(row, tools)} />`)}
        <//>` : html`<${Empty} art="empty" text=${words.todo_empty} />`}
    <//>`;
}

async function answer(row, option, tools) {
  const quiz = row.kind === "quiz";
  const extra = quiz ? { option: String(option) }
                     : { poll: String(row.poll), option: String(option) };
  const made = quiz ? quizDone() : pollDone(row.poll);
  if (await tools.run(ANSWER[row.kind], extra, made)) { tools.pick("sheet", null); }
}

function sheet(words, row, tools) {
  return html`
    <${Card} tone="sheet" title=${row.question || words["todo_" + row.kind]}>
      <${Chips}>
        ${(row.options || []).map((label, seat) => html`
          <${Chip} text=${label} onTap=${() => answer(row, seat, tools)} />`)}
      <//>
    <//>`;
}

function quiet(words, state, tools) {
  const next = state.next;
  const last = state.last_war;
  return html`
    ${next ? html`
      <${Card} tone="next">
        <${Timer} left=${countdown(next.state === "ongoing" ? next.end : next.start, tools.now)}
                  words=${words} label=${words["next_" + next.key]} />
      <//>` : null}
    ${last ? html`
      <${Card} title=${words.war_last}>
        <${Score} ours=${{ value: last.us_stars, label: words["war_" + last.result] }}
                  theirs=${{ value: last.them_stars, label: last.them }} vs=${words.war_vs} />
      <//>` : null}
    ${todo(words, state, tools)}`;
}

function seatOf(state) {
  return ((state || {}).me_view || {}).tag || null;
}

function fought(state, words, view, conf, tools) {
  const tag = chosen(state.me_view, tools.local);
  return html`
    ${warEnd(view, words, tools.run)}
    ${view.ended ? null : match(words, view, tools.now)}
    ${view.ended ? null : shot(view, words, conf, tools)}
    ${mine(words, view, tools.run, mineOf(state, view, tag), tag === seatOf(state))}
    ${missing(words, view)}
    ${enemyGrid(state, view, words, conf, tools)}
    ${baseSheet(state, words, conf, tools)}`;
}

export function war(state, words, conf, tools) {
  const open = (tools.local || {}).sheet;
  if (open && ANSWER[open.kind]) { return sheet(words, open, tools); }
  const view = state.war_view;
  if (!state.cwl) {
    return html`
      ${strips(state, words, conf, tools)}
      ${view ? fought(state, words, view, conf, tools) : quiet(words, state, tools)}`;
  }
  const here = pickedDay(state, tools.local) === state.cwl.day;
  return html`
    ${strips(state, words, conf, tools)}
    ${cwlStrip(state, words, tools)}
    ${cwlDay(state, words, conf, tools)}
    ${view && here ? fought(state, words, view, conf, tools) : quiet(words, state, tools)}`;
}

export function warPrimary(state, words, conf, local) {
  const me = state.war_view && state.war_view.mine;
  if (state.cwl && pickedDay(state, local) !== state.cwl.day) { return null; }
  if (!me || me.target) { return null; }
  return { label: words.war_mirror, kind: "target.mirror", extra: {},
           optimistic: warMirror() };
}
