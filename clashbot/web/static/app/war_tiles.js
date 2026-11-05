import { html } from "../vendor/htm-preact-standalone.module.js";
import { fill, isManager } from "./model.js";
import { warBook, warClear, warFree, warHand, warNote, warSwap } from "./guess.js";
import { Card, Chip, Chips, Empty, Grid, Row, Sheet, Stars, Tile } from "./ui.js";

const BASE = "base";
const SHEET = "sheet";
const PLAN = "plan";
export const MINE = "mine";
export const FREE = "free";
export const PREP = "preparation";
const MATE = "mate";
const DONE = "done";
const CLEAR = "target.clear";

export function spot(words, pos, th) {
  return fill(fill(words.target_th, "target", fill(words.pos, "pos", pos)), "th", th);
}

export function stars(best, conf) {
  const most = Number(conf.FULL) || 0;
  return html`<${Stars} got=${Math.max(0, Math.min(most, Number(best) || 0))} most=${most} />`;
}

function isMine(view, row) {
  const target = (view.mine || {}).target;
  return Boolean(target && target.pos === row.pos);
}

function toneOf(view, row, conf) {
  if (isMine(view, row)) { return MINE; }
  if (row.assignee) { return MATE; }
  return (Number(row.best) || 0) >= (Number(conf.FULL) || 0) ? DONE : FREE;
}

function wipe(state, rows, words, tools) {
  if (!isManager(state) || !rows.some((row) => row.assignee)) { return null; }
  return html`
    <${Chips}>
      <${Chip} text=${words.war_clear} onTap=${() => tools.run(CLEAR, {}, warClear())} />
    <//>`;
}

export function enemyGrid(state, view, words, conf, tools) {
  const rows = view.enemy || [];
  return html`
    <${Card} tone="enemy" title=${words.war_enemy}>
      ${rows.length ? html`
        <${Grid} cols="3">
          ${rows.map((row) => html`
            <${Tile} big=${fill(words.pos, "pos", row.pos)} label=${fill(words.th, "th", row.th)}
                     sub=${stars(row.best, conf)} tone=${toneOf(view, row, conf)}
                     dot=${Boolean(row.swap_pending)} mark=${row.best}
                     onTap=${() => tools.pick(SHEET, { kind: BASE, pos: row.pos })} />`)}
        <//>`
        : html`<${Empty} art="nowar" text=${words.empty} />`}
      ${wipe(state, rows, words, tools)}
    <//>`;
}

function hits(row, words, conf) {
  const rows = row.history || [];
  if (!rows.length) { return null; }
  return html`
    <div class="sub">${words.war_hits}</div>
    <${Grid}>
      ${rows.map((one) => html`
        <${Tile} big=${fill(words.war_destr, "destr", one.destr)} label=${one.name}
                 sub=${stars(one.stars, conf)} />`)}
    <//>`;
}

function tips(state, row, words) {
  const found = (state.advice || {})[String(row.th)];
  if (!found) { return null; }
  return html`
    <${Row} left=${words.war_avg} right=${found.avg_stars} />
    ${(found.best || []).length ? html`<div class="sub">${words.war_best}</div>` : null}
    ${(found.best || []).length ? html`
      <${Grid}>
        ${(found.best || []).map((one) => html`
          <${Tile} big=${one.stars} label=${one.name}
                   sub=${fill(fill(words.name_count, "name", one.name), "n", one.count)} />`)}
      <//>` : null}`;
}

function clips(state, row, words, conf) {
  const rows = (state.attack_videos || {})[String(row.th)] || [];
  if (!rows.length) { return null; }
  return html`
    <div class="sub">${words.bases_videos}</div>
    <${Grid}>
      ${rows.map((one) => html`
        <${Tile} tone="video" big=${words.war_watch} label=${one.title}
                 href=${conf.WATCH + encodeURIComponent(one.video_id)} />`)}
    <//>`;
}

function draftOf(local, row) {
  const kept = local[PLAN] || {};
  return kept.pos === row.pos ? String(kept.text || "") : String(row.note || "");
}

function written(state, view, row, words, conf, tools) {
  if (!row.assignee) { return null; }
  const local = tools.local || {};
  if (!isMine(view, row) && !isManager(state)) {
    return row.note ? html`<${Row} left=${words.war_plan} sub=${row.note} right="" />` : null;
  }
  const draft = draftOf(local, row);
  return html`
    <div class="sub">${words.war_plan}</div>
    <textarea class="note" maxlength=${conf.TEXT_MAX} value=${draft}
              onInput=${(event) => tools.pick(PLAN, { pos: row.pos,
                                                      text: event.target.value })}></textarea>
    <${Chip} text=${words.manage_save}
             onTap=${() => tools.run("target.note", { pos: String(row.pos), text: draft },
                                     warNote(row.pos, draft))} />`;
}

function seatOf(state, row) {
  const found = (state.ours || []).find((one) => one.name === row.assignee);
  return found ? String(found.pos) : "";
}

function mateOf(state, seat) {
  const found = (state.ours || []).find((one) => String(one.pos) === String(seat));
  return found ? found.name : "";
}

function mates(state, view, row, words, tools) {
  if (view.phase !== PREP || !isManager(state)) { return null; }
  return html`
    <select class="field" value=${seatOf(state, row)}
            onChange=${(event) => event.target.value
              && tools.run("target.set", { pos: String(row.pos), who: event.target.value },
                           warHand(row.pos, mateOf(state, event.target.value)))}>
      <option value="">${words.war_free}</option>
      ${(state.ours || []).map((one) => html`
        <option value=${String(one.pos)}>${one.name}</option>`)}
    </select>`;
}

function moves(view, row, words, conf, tools) {
  const seat = view.mine || {};
  const mine = isMine(view, row);
  const open = !row.assignee && (Number(row.best) || 0) < (Number(conf.FULL) || 0);
  return html`
    <${Chips}>
      ${open && seat.pos && !seat.target ? html`
        <${Chip} text=${words.war_book}
                 onTap=${() => tools.run("target.set", { pos: String(row.pos),
                                                        who: String(seat.pos) },
                                         warBook(row))} />` : null}
      ${mine ? html`
        <${Chip} text=${words.war_release}
                 onTap=${() => tools.run("target.free", { pos: String(row.pos) },
                                         warFree(row.pos))} />` : null}
      ${row.assignee && !mine ? html`
        <${Chip} text=${words.war_swap}
                 onTap=${() => tools.run("target.swap", { pos: String(row.pos) },
                                         warSwap(row.pos))} />` : null}
    <//>`;
}

export function baseSheet(state, words, conf, tools) {
  const open = (tools.local || {})[SHEET];
  const view = state.war_view;
  if (!open || open.kind !== BASE || !view) { return null; }
  const row = (view.enemy || []).find((one) => one.pos === open.pos);
  if (!row) { return null; }
  return html`
    <${Sheet} title=${spot(words, row.pos, row.th)}>
      ${row.assignee ? html`<${Row} left=${words.war_target} right=${row.assignee} />` : null}
      ${hits(row, words, conf)}
      ${tips(state, row, words)}
      ${clips(state, row, words, conf)}
      ${written(state, view, row, words, conf, tools)}
      ${mates(state, view, row, words, tools)}
      ${moves(view, row, words, conf, tools)}
    <//>`;
}
