import { html } from "../vendor/htm-preact-standalone.module.js";
import { icon, illustration } from "./art.js";
import { grow, throb } from "./fx.js";

const wake = (mark) => (mark === undefined ? null : (node) => throb(node, mark));
const tally = (value) => (typeof value === "number" ? value : null);
const climb = (node) => {
  if (node && node.dataset && node.dataset.to !== undefined) { grow(node); }
};

const STAR = "12,2 14.4,8.8 21.5,8.9 15.8,13.2 17.9,20.1 12,16 6.1,20.1 8.2,13.2 2.5,8.9 9.6,8.8";

export const Stars = ({ got, most }) => html`
  <span class="stars" role="img" aria-label=${got + "/" + most}>
    ${Array.from({ length: most }, (_, seat) => html`
      <svg class=${"star" + (seat < got ? " on" : "")} viewBox="0 0 24 24" width="14" height="14">
        <polygon points=${STAR} />
      </svg>`)}
  </span>`;

export const Card = ({ title, children, tone, hero, stripe, at, mark }) => html`
  <section id=${at} ref=${wake(mark)}
           class=${"card" + (tone ? " " + tone : "") + (hero ? " hero" : "")
                   + (stripe ? " stripe" : "")}>
    ${title ? html`<h2 class="card-title">${title}</h2>` : null}
    ${children}
  </section>`;

export const Item = ({ title, sub, badge, children }) => html`
  <${Card} tone="item">
    <div>${title}${badge ? html`<span class="badge">${badge}</span>` : null}</div>
    ${sub ? html`<div class="sub">${sub}</div>` : null}
    ${children}
  <//>`;

export const Big = ({ value, label, hero }) => html`
  <div class=${"big" + (hero ? " hero" : "")}>
    <div class="big-value" data-to=${tally(value)} ref=${climb}>${value}</div>
    <div class="big-label">${label}</div>
  </div>`;

export const Bar = ({ done, total, tone }) => html`
  <div class=${"bar" + (tone ? " " + tone : "")} role="progressbar" aria-valuenow=${done}
       aria-valuemax=${total}>
    <div class="bar-fill" style=${"width:" + (total ? Math.round(100 * done / total) : 0) + "%"}></div>
  </div>`;

export const Chip = ({ text, on, locked, onTap }) => html`
  <button class=${"chip" + (on ? " on" : "") + (locked ? " locked" : "")}
          disabled=${Boolean(locked)} onClick=${onTap}>${text}</button>`;

export const Chips = ({ tone, children }) => html`
  <div class=${"chips" + (tone ? " " + tone : "")}>${children}</div>`;

export const Score = ({ ours, theirs, vs, hero }) => html`
  <div class="score-row">
    <${Big} value=${ours.value} label=${ours.label} hero=${hero} />
    <div class="vs">${vs}</div>
    <${Big} value=${theirs.value} label=${theirs.label} hero=${hero} />
  </div>`;

function ticking(left, words) {
  if (left.d) { return left.d + words.unit_d + " " + left.h + words.unit_h; }
  if (left.h) { return left.h + words.unit_h + " " + left.m + words.unit_m; }
  return left.m + words.unit_m + " " + left.s + words.unit_s;
}

export const Timer = ({ left, label, words, tone, mark }) => html`
  <div class=${"timer" + (tone ? " " + tone : "")} ref=${wake(mark)}>
    <span class="clock">${ticking(left, words)}</span>
    ${label ? html`<span class="sub">${label}</span>` : null}
  </div>`;

const side = (left, right, sub) => html`
  <div><div>${left}</div>${sub ? html`<div class="sub">${sub}</div>` : null}</div>
  <div class="right">${right}</div>`;

export const Row = ({ left, right, sub, onTap }) => (onTap
  ? html`<button class="row" onClick=${onTap}>${side(left, right, sub)}</button>`
  : html`<div class="row">${side(left, right, sub)}</div>`);

export const Sort = ({ options, current, onPick }) => html`
  <div class="sort">
    ${options.map((one) => html`
      <${Chip} text=${one.label} on=${one.id === current} onTap=${() => onPick(one.id)} />`)}
  </div>`;

export const Medals = ({ worn, glyphs }) => html`
  <div class="medals">
    ${(worn || []).map((one) => html`
      <span class="medal">${(glyphs || {})[one.badge] || one.badge}</span>`)}
  </div>`;

export const Sheet = ({ title, children }) => html`
  <section class="sheet">
    ${title ? html`<h2 class="card-title">${title}</h2>` : null}
    ${children}
  </section>`;

export const Empty = ({ text, art, action, onAction }) => html`
  <div class="empty">
    ${art ? illustration(art) : null}
    <span>${text}</span>
    ${action ? html`
      <button class="chip empty-do" onClick=${onAction}>${action}</button>` : null}
  </div>`;

export const Tabs = ({ tabs, current, onPick }) => html`
  <nav class="tabs">
    ${tabs.map((one) => html`
      <button class=${"tab" + (one.id === current ? " pick" : "")} onClick=${() => onPick(one.id)}>
        <span class="tab-mark">${icon(one.id)}</span>
        <span class="tab-name">${one.label}</span>
        ${one.badge ? html`<span class="badge">${one.badge}</span>` : null}
      </button>`)}
  </nav>`;

const spot = (dot) => (dot
  ? html`<span class=${"dot" + (typeof dot === "string" ? " " + dot : "")}></span>`
  : null);

const face = (big, label, sub, badge, dot, icon) => html`
  ${spot(dot)}
  ${badge ? html`<span class="badge">${badge}</span>` : null}
  ${icon ? html`<span class="tile-icon">${icon}</span>` : null}
  <span class="tile-big" data-to=${tally(big)} ref=${climb}>${big}</span>
  <span class="tile-label">${label}</span>
  ${sub ? html`<span class="sub">${sub}</span>` : null}`;

export const Tile = ({ big, label, sub, tone, on, onTap, badge, dot, icon, href, mark }) => {
  const dress = "tile" + (tone ? " " + tone : "") + (on ? " on" : "");
  const seen = face(big, label, sub, badge, dot, icon);
  const beat = wake(mark);
  if (href) {
    return html`
      <a class=${dress} ref=${beat} href=${href} target="_blank"
         rel="noopener noreferrer">${seen}</a>`;
  }
  return onTap
    ? html`<button class=${dress} ref=${beat} onClick=${onTap}>${seen}</button>`
    : html`<div class=${dress} ref=${beat}>${seen}</div>`;
};

export const Grid = ({ cols, children }) => html`
  <div class="grid" style=${cols ? "--cols:" + cols : null}>${children}</div>`;

const told = (one) => one !== null && one !== undefined && one !== false && one !== "";

export const Facts = ({ items }) => html`
  <span class="facts">
    ${(items || []).filter(told).map((one) => html`<span>${one}</span>`)}
  </span>`;

const RING_BOX = 44;
const RING_EDGE = 4;
const RING_R = (RING_BOX - RING_EDGE) / 2;
const RING_ROUND = 2 * Math.PI * RING_R;
const RING_MID = RING_BOX / 2;

export const Ring = ({ value, total, label }) => {
  const done = total ? Math.max(0, Math.min(value || 0, total)) / total : 0;
  return html`
    <div class="ring">
      <svg viewBox=${"0 0 " + RING_BOX + " " + RING_BOX} width=${RING_BOX} height=${RING_BOX}
           role="img" aria-label=${(value || 0) + "/" + (total || 0)}>
        <circle class="ring-bed" cx=${RING_MID} cy=${RING_MID} r=${RING_R} />
        <circle class="ring-arc" cx=${RING_MID} cy=${RING_MID} r=${RING_R}
                stroke-dasharray=${RING_ROUND * done + " " + RING_ROUND} />
      </svg>
      <span class="ring-face">
        <span class="ring-value" data-to=${tally(value)} ref=${climb}>${value}</span>
        ${label ? html`<span class="sub">${label}</span>` : null}
      </span>
    </div>`;
};

export const Toast = ({ text, action, onAction }) => html`
  <div class="toast" role="status">
    <span>${text}</span>
    ${action ? html`<button class="toast-do" onClick=${onAction}>${action}</button>` : null}
  </div>`;

export const Strip = ({ text, action, onAction, tone }) => html`
  <div class=${"strip" + (tone ? " " + tone : "")}>
    <span>${text}</span>
    ${action ? html`<button class="strip-do" onClick=${onAction}>${action}</button>` : null}
  </div>`;

export const Switch = ({ on, onTap, label }) => html`
  <button class=${"switch" + (on ? " on" : "")} role="switch" aria-checked=${on ? "true" : "false"}
          onClick=${onTap}>
    ${label ? html`<span>${label}</span>` : null}
    <span class="switch-knob"></span>
  </button>`;
