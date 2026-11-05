import { html } from "../vendor/htm-preact-standalone.module.js";
import { fill } from "./model.js";
import { meDrop } from "./guess.js";
import { Card, Chip, Chips, Item } from "./ui.js";

const HASH = "#";
const TAG_OK = /^#?[0-9A-Z]{3,}$/u;
const DROP = "link.drop";
const TAG = "tag";
const VILLAGE = "village";
const MANY = 2;
const GAP = " ";
const TERMS = "terms";
const ACCEPT = "on";
const RULES = "/terms";
const PRIVACY = "/privacy";

export function typed(local) {
  return String((local || {}).tag || "").trim().toUpperCase();
}

export function village(tag) {
  return tag.startsWith(HASH) ? tag : HASH + tag;
}

export function claimable(local) {
  return TAG_OK.test(typed(local));
}

function badge(one, words) {
  return one.verified ? words.me_verified : words.me_claimed;
}

export function claim(words, conf, local, tools) {
  return html`
    <${Card} title=${words.link_title}>
      <input class="field claim" value=${String(local.tag || "")} maxlength=${conf.TOKEN_MAX}
             placeholder=${words.me_tag}
             onInput=${(event) => tools.pick(TAG, event.target.value)} />
      ${steps({ verified: false }, words, conf, local, tools)}
    <//>`;
}

function steps(view, words, conf, local, tools) {
  if (view.verified) {
    return null;
  }
  return html`
    <div class="sub">${words.link_steps}</div>
    <input class="field verify" value=${String(local.token || "")} maxlength=${conf.TOKEN_MAX}
           placeholder=${words.link_token}
           onInput=${(event) => tools.pick("token", event.target.value)} />
    ${terms(words, local, tools)}`;
}

export function agreed(local) {
  return (local || {})[TERMS] === ACCEPT;
}

function terms(words, local, tools) {
  const on = agreed(local);
  return html`
    <${Chips} tone="terms">
      <${Chip} text=${words.link_terms} on=${on}
               onTap=${() => tools.pick(TERMS, on ? "" : ACCEPT)} />
      <a class="open" href=${RULES} target="_blank" rel="noopener noreferrer">${words.more_terms}</a>
      <a class="open" href=${PRIVACY} target="_blank" rel="noopener noreferrer">${words.more_privacy}</a>
    <//>`;
}

export function villages(view, words, conf, local, tools) {
  return html`
    <${Card} title=${words.link_yours}>
      ${(view.villages || []).map((one) => html`
        <${Item} title=${one.name || one.tag} sub=${one.tag} badge=${badge(one, words)}>
          <${Chips}>
            <${Chip} text=${words.link_drop}
                     onTap=${() => tools.run(DROP, { village: one.tag }, meDrop(one.tag))} />
          <//>
        <//>`)}
      ${steps(view, words, conf, local, tools)}
    <//>`;
}

export function chosen(view, local) {
  const rows = (view || {}).villages || [];
  const want = (local || {})[VILLAGE] || "";
  const found = rows.find((one) => one.tag === want);
  return (found ? found.tag : (view || {}).tag) || null;
}

function rowsOf(state) {
  return ((state || {}).people || {}).rows || [];
}

function named(one, state, words) {
  const row = rowsOf(state).find((found) => found.tag === one.tag);
  return [one.name || one.tag, row ? fill(words.th, "th", row.th) : ""].join(GAP).trim();
}

function seriesOf(grown, tag) {
  const lines = (grown.players || {})[tag];
  return lines ? Object.assign({ days: grown.days || [] }, lines) : null;
}

export function shown(state, view, tag) {
  const seen = view || {};
  const one = (seen.villages || []).find((row) => row.tag === tag);
  if (!one || tag === seen.tag) {
    return seen;
  }
  const row = rowsOf(state).find((found) => found.tag === tag) || {};
  const grown = (state || {}).growth || {};
  return Object.assign({}, seen, {
    tag: tag, name: one.name, verified: one.verified,
    profile: { th: row.th, trophies: row.trophies, donations: row.donations },
    growth: seriesOf(grown, tag),
    medals: ((state || {}).medals || {})[tag] || [],
    period: ((grown.period || {}).week || {})[tag] || null });
}

export function villageChips(state, view, words, local, tools) {
  const rows = (view || {}).villages || [];
  if (rows.length < MANY) {
    return null;
  }
  const here = chosen(view, local);
  return html`
    <${Chips} tone="villages">
      ${rows.map((one) => html`
        <${Chip} text=${named(one, state, words)} on=${one.tag === here}
                 onTap=${() => tools.pick(VILLAGE, one.tag)} />`)}
    <//>`;
}
