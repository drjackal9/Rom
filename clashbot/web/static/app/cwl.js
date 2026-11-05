import { html } from "../vendor/htm-preact-standalone.module.js";
import { fill, isManager, score } from "./model.js";
import { cwlBonus, cwlPick, cwlSide } from "./guess.js";
import { icon } from "./art.js";
import { Card, Chip, Chips, Empty, Grid, Score, Sheet, Tile } from "./ui.js";

const FOUGHT = ["done", "live"];
const ROSTER = "cwl.roster.set";
const LINEUP = "cwl.lineup.set";
const BONUS = "cwl.bonus.toggle";
const SHEET = "sheet";
const SEAT = "cwl_seat";
const LIVE = "live";
const LATER = "locked";
const LINKED = "linked";

function dayText(words, row) {
  return fill(fill(words.cwl_day, "n", row.n),
              "result", row.result ? words["war_" + row.result] : "").trim();
}

function dayName(words, row) {
  return fill(fill(words.cwl_day, "n", row.n), "result", "").trim();
}

function tally(words, row) {
  return score(words, "", row.us_stars, row.them_stars);
}

function dayTone(row) {
  if (row.result) { return row.result; }
  return row.state === LIVE ? LIVE : LATER;
}

function rival(state, words, row) {
  if (!row.them) { return html`<${Empty} art="nocwl" text=${words.empty} />`; }
  const played = FOUGHT.includes(row.state);
  return html`
    <${Score} ours=${{ value: played ? row.us_stars : "", label: (state.clan || {}).name }}
              theirs=${{ value: played ? row.them_stars : "", label: row.them }}
              vs=${words.war_vs} />`;
}

function sides(row, words, conf, tools) {
  const first = (conf.SIDES || [])[0];
  return (conf.SIDES || []).map((side) => html`
    <${Chip} text=${words["avail_" + side]} on=${Boolean(row.in) && side === first}
             onTap=${() => tools.run(ROSTER, { village: String(row.tag), choice: side },
                                     cwlSide(row.tag, side === first))} />`);
}

function seat(row, words, conf, boss, tools) {
  const both = conf.SIDES || [];
  const side = row.in ? both[0] : both[1];
  return html`
    <${Tile} big=${fill(words.th, "th", row.th)} label=${row.name}
             sub=${words["avail_" + side]} tone=${side}
             badge=${row.picked ? icon(LINKED) : null} dot=${Boolean(row.bonus)}
             onTap=${boss ? () => tools.pick(SHEET, { kind: SEAT, tag: row.tag }) : null} />`;
}

function lineup(state, words, conf, tools) {
  const rows = (state.cwl || {}).lineup || [];
  const boss = isManager(state);
  return html`
    <${Card} tone="lineup" title=${words.cwl_lineup}>
      ${rows.length
        ? html`<${Grid}>${rows.map((row) => seat(row, words, conf, boss, tools))}<//>`
        : html`<${Empty} art="nocwl" text=${words.empty} />`}
    <//>`;
}

function seatSheet(state, words, conf, tools) {
  const open = (tools.local || {})[SHEET];
  if (!open || open.kind !== SEAT || !isManager(state)) { return null; }
  const row = ((state.cwl || {}).lineup || []).find((one) => one.tag === open.tag);
  if (!row) { return null; }
  return html`
    <${Sheet} title=${row.name}>
      <${Chips} tone="wide">
        ${sides(row, words, conf, tools)}
        <${Chip} text=${words.cwl_pick} on=${Boolean(row.picked)}
                 onTap=${() => tools.run(LINEUP, { village: String(row.tag) },
                                         cwlPick(row.tag, !row.picked))} />
        <${Chip} text=${words.cwl_bonus} on=${Boolean(row.bonus)}
                 onTap=${() => tools.run(BONUS, { village: String(row.tag) },
                                         cwlBonus(row.tag, !row.bonus))} />
      <//>
    <//>`;
}

function table(state, words) {
  const rows = (state.cwl || {}).table || [];
  return html`
    <${Card} tone="table" title=${words.cwl_table}>
      ${rows.length
        ? html`
          <${Grid}>
            ${rows.map((row) => html`
              <${Tile} big=${row.stars} label=${row.name}
                       sub=${fill(words.pos, "pos", row.rank)} />`)}
          <//>`
        : html`<${Empty} art="nocwl" text=${words.empty} />`}
    <//>`;
}

export function pickedDay(state, local) {
  const league = state.cwl || {};
  const days = league.days || [];
  return Number((local || {}).cwl_day || league.day || (days[0] || {}).n) || null;
}

export function cwlStrip(state, words, tools) {
  const league = state.cwl || {};
  const here = pickedDay(state, tools.local);
  return html`
    <${Card} tone="days" title=${league.season}>
      <${Grid} cols="4">
        ${(league.days || []).map((row) => html`
          <${Tile} big=${dayName(words, row)}
                   label=${row.result ? words["war_" + row.result] : row.them}
                   sub=${FOUGHT.includes(row.state) ? tally(words, row) : ""}
                   tone=${dayTone(row)} on=${row.n === here}
                   onTap=${() => tools.pick("cwl_day", row.n)} />`)}
      <//>
    <//>`;
}

export function cwlDay(state, words, conf, tools) {
  const here = pickedDay(state, tools.local);
  const row = ((state.cwl || {}).days || []).find((one) => one.n === here);
  return html`
    ${row ? html`<${Card} title=${dayText(words, row)}>${rival(state, words, row)}<//>`
      : null}
    ${lineup(state, words, conf, tools)}
    ${table(state, words)}
    ${seatSheet(state, words, conf, tools)}`;
}
