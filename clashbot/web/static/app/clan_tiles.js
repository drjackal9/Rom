import { html } from "../vendor/htm-preact-standalone.module.js";
import { icon, initials } from "./art.js";
import { fill } from "./model.js";
import { Card, Empty, Facts, Grid, Sort, Tile } from "./ui.js";

const SORTS = ["th", "trophies", "donations", "role"];
const PERIODS = ["week", "month"];
const BY_ROLE = "role";
const TROPHIES = "trophies";
const WEEK = "week";
const PERSON = "person";
const SHEET = "sheet";
const SORT = "sort";
const PERIOD = "period";
const LINKED = "linked";
const AWAY = "mute";

export function peopleOf(state) {
  return (state || {}).people || {};
}

export function rowsOf(state) {
  return peopleOf(state).rows || (state || {}).members || [];
}

export function ordered(rows, sort) {
  if (!sort || sort === BY_ROLE) {
    return rows;
  }
  return rows.slice().sort((one, two) => (Number(two[sort]) || 0) - (Number(one[sort]) || 0));
}

export function counted(row, sort) {
  return Number(row[!sort || sort === BY_ROLE ? TROPHIES : sort]) || 0;
}

export function away(row, conf) {
  const least = Number((conf || {}).IDLE_MIN_DAYS) || 0;
  return least > 0 && (Number(row.absent_days) || 0) >= least;
}

function facts(row, words) {
  const said = [fill(words.th, "th", row.th), Number(row.donations) || 0];
  if (row.ratio !== null && row.ratio !== undefined) {
    said.push(row.ratio);
  }
  return html`<${Facts} items=${said} />`;
}

function person(row, words, conf, tools) {
  return html`
    <${Tile} icon=${html`<span class="face">${initials(row.name)}</span>`}
             big=${counted(row, (tools.local || {}).sort)} label=${row.name}
             sub=${facts(row, words)} tone=${String(row.role || "").toLowerCase()}
             badge=${row.linked ? icon(LINKED) : null} dot=${away(row, conf) ? AWAY : false}
             onTap=${() => tools.pick(SHEET, { kind: PERSON, tag: row.tag })} />`;
}

export function peopleGrid(state, words, conf, tools) {
  const local = tools.local || {};
  const rows = ordered(rowsOf(state), local.sort);
  return html`
    <${Card} tone="people">
      <${Sort} options=${SORTS.map((id) => ({ id: id, label: words["clan_sort_" + id] }))}
               current=${local.sort || BY_ROLE} onPick=${(id) => tools.pick(SORT, id)} />
      ${rows.length
        ? html`<${Grid} cols="3">${rows.map((row) => person(row, words, conf, tools))}<//>`
        : html`<${Empty} art="nomembers" text=${words.empty} />`}
    <//>`;
}

export function climbTiles(state, words, tools) {
  const local = tools.local || {};
  const when = local[PERIOD] || WEEK;
  const rows = (peopleOf(state).climb || {})[when] || [];
  return html`
    <${Card} at="climb" tone="climb" title=${words.clan_climb}>
      <${Sort} options=${PERIODS.map((id) => ({ id: id, label: words["clan_" + id] }))}
               current=${when} onPick=${(id) => tools.pick(PERIOD, id)} />
      ${rows.length
        ? html`
          <${Grid} cols=${rows.length}>
            ${rows.map((row) => html`
              <${Tile} big=${row.score} label=${row.name} />`)}
          <//>`
        : html`<${Empty} art="nomembers" text=${words.empty} />`}
    <//>`;
}
