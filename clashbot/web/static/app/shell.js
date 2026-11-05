import { html } from "../vendor/htm-preact-standalone.module.js";
import { initials } from "./art.js";
import { ago } from "./chronicle.js";
import { FIRST, fill } from "./model.js";
import { primaries } from "./screens.js";
import { Grid, Sheet, Strip, Tile } from "./ui.js";

const SHEET = "sheet";
const MARK_SEP = ":";

export function banner(state, words, now, onRetry, waiting) {
  const seen = Number((state || {}).updated) || 0;
  const said = waiting ? words.queued
    : fill(words.live_seen, "when", ago(now - seen, words));
  return html`
    <${Strip} text=${said} action=${words.live_retry} onAction=${onRetry} />`;
}

export function keyOf(marks, kind, extra) {
  const names = (marks || {})[kind] || [];
  const parts = names.map((name) => {
    const value = (extra || {})[name];
    return value === undefined ? "" : String(value);
  });
  return [kind].concat(parts).join(MARK_SEP);
}

export function hold(rows, marks, one) {
  const key = keyOf(marks, one.kind, one.extra);
  return (rows || []).filter((row) => row.key !== key).concat([Object.assign({ key }, one)]);
}

export function drop(rows, sent) {
  return (rows || []).filter((row) => !(sent || []).includes(row.id));
}

export async function flush(rows, send, keep, stop) {
  const sent = [];
  try {
    for (const one of rows || []) {
      if (stop()) { break; }
      await send(one);
      sent.push(one.id);
    }
  } finally {
    keep(sent);
  }
}

export function pump(latch, down, rows, send, keep) {
  if (down || latch.busy || !(rows || []).length) { return undefined; }
  let gone = false;
  const apri = () => { latch.busy = false; };
  latch.busy = true;
  flush(rows, send, (sent) => { apri(); keep(sent); }, () => gone).finally(apri).catch(apri);
  return () => { gone = true; };
}

export function seen(state, words, now, onTap) {
  const when = Number((state || {}).updated) || 0;
  return html`
    <button class="seen sub" onClick=${onTap}>
      ${fill(words.live_seen, "when", ago(now - when, words))}
    </button>`;
}

export function head(state, onOpen) {
  const name = ((state || {}).clan || {}).name || "";
  const rows = (state || {}).clans || [];
  if (rows.length > 1) {
    return html`<button class="head" onClick=${onOpen}>${name}</button>`;
  }
  return html`<div class="head">${name}</div>`;
}

export function clanSheet(state, words, slug, onPick) {
  return html`
    <${Sheet} title=${words.tab_clan}>
      <${Grid}>
        ${((state || {}).clans || []).map((one) => html`
          <${Tile} big=${initials(one.name)} label=${one.name} on=${one.slug === slug}
                   onTap=${() => onPick(one.slug)} />`)}
      <//>
    <//>`;
}

export function backTo(local, tab) {
  if ((local || {}).sheet) { return SHEET; }
  return tab === FIRST ? null : FIRST;
}

export function gate(down, run, park) {
  return down ? park : run;
}

export function primary(state, tab, down, words, conf, local) {
  const make = down ? null : primaries[tab];
  return state && make ? make(state, words, conf, local) : null;
}
