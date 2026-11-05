import { html } from "../vendor/htm-preact-standalone.module.js";
import { icon } from "./art.js";
import { DAY, HOUR, fill } from "./model.js";
import { Card, Empty, Facts, Grid, Tile } from "./ui.js";

export const CHRONICLE = "chronicle";
const YESTERDAY = 1;

export function ago(seconds, words) {
  const gone = Math.max(0, Math.floor(Number(seconds) || 0));
  if (gone < HOUR) {
    return words.ago_now;
  }
  if (gone < DAY) {
    return fill(words.ago_hours, "n", Math.floor(gone / HOUR));
  }
  const days = Math.floor(gone / DAY);
  return days === YESTERDAY ? words.ago_yesterday : fill(words.ago_days, "n", days);
}

function rowsOf(state) {
  return ((state || {}).people || {}).chronicle || [];
}

function when(row, words, now) {
  return html`
    <${Facts} items=${[words["ev_" + row.kind], ago(now - (Number(row.at) || 0), words)]} />`;
}

function box(row, words, now) {
  return html`
    <${Tile} icon=${icon(row.pack)} tone=${row.kind}
             big=${row.n === null || row.n === undefined ? "" : row.n}
             label=${row.who} sub=${when(row, words, now)} />`;
}

export function chronicle(state, words, tools) {
  const local = tools.local || {};
  const rows = rowsOf(state);
  if (!local[CHRONICLE]) {
    return null;
  }
  return html`
    <${Card} at=${CHRONICLE} tone="chronicle">
      ${rows.length
        ? html`<${Grid}>${rows.map((row) => box(row, words, tools.now))}<//>`
        : html`<${Empty} art="nochronicle" text=${words.empty} />`}
    <//>`;
}
