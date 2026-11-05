import { html } from "../vendor/htm-preact-standalone.module.js";
import { Chip, Chips, Empty, Grid, Tile } from "./ui.js";
import { fill } from "./model.js";

export const GUESS = "guess";
const ART = "nogames";

function roundOf(state) {
  return ((state || {}).more_view || {}).guess || null;
}

function row(list, current, onPick) {
  return html`
    <${Chips}>
      ${(list || []).map((one) => html`
        <${Chip} text=${String(one)} on=${one === current} onTap=${() => onPick(one)} />`)}
    <//>`;
}

export function guessCount(state) {
  const found = roundOf(state);
  return found && !found.done ? 1 : 0;
}

function guessDone() {
  return (state) => {
    const view = (state || {}).more_view || {};
    return Object.assign({}, state, {
      more_view: Object.assign({}, view,
                               { guess: Object.assign({}, view.guess || {}, { done: true }) }),
    });
  };
}

export function guessSheet(state, words, conf, kit) {
  const found = roundOf(state);
  if (!found) { return html`<${Empty} art=${ART} text=${words.guess_wait} />`; }
  if (found.done) { return html`<${Empty} art=${ART} text=${words.guess_done} />`; }
  const picked = kit.local[GUESS] || {};
  const keep = (name) => (value) => kit.pick(
    GUESS, Object.assign({}, picked, { [name]: value }));
  return html`
    <${Grid} cols="2">
      <${Tile} big=${fill(words.th, "th", found.th)} label=${words.guess_mine} />
      <${Tile} big=${fill(words.th, "th", found.d_th)} label=${words.guess_foe} />
    <//>
    <div class="sub">${words.guess_stars}</div>
    ${row(conf.GUESS_STARS, picked.stars, keep("stars"))}
    <div class="sub">${words.guess_percent}</div>
    ${row(conf.GUESS_PERCENTS, picked.percent, keep("percent"))}`;
}

export function guessPrimary(state, words, local) {
  const found = roundOf(state);
  const picked = (local || {})[GUESS] || {};
  if (!found || found.done || picked.stars === undefined || picked.percent === undefined) {
    return null;
  }
  return { label: words.guess_send, kind: "guess.answer",
           extra: { stars: String(picked.stars), percent: String(picked.percent) },
           optimistic: guessDone() };
}
