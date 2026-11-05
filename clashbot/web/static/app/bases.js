import { html } from "../vendor/htm-preact-standalone.module.js";
import { Card, Chip, Chips, Empty, Grid, Tile } from "./ui.js";
import { fill } from "./model.js";
import { copy } from "./native.js";
import { baseProposed } from "./guess.js";

const TABS = ["library", "clan", "videos"];
const FIRST = TABS[0];
const GAP = " ";

function joined(parts) {
  return parts.filter((one) => one || one === 0).join(GAP);
}

function opener(link, words) {
  return html`
    <a class="open" href=${link} target="_blank" rel="noopener noreferrer">${words.bases_open}</a>`;
}

function picker(list, current, label, onPick) {
  if (!list.length) { return null; }
  return html`
    <div class="chips">
      ${label ? html`<span class="sub">${label}</span>` : null}
      ${list.map((one) => html`
        <${Chip} text=${one.text} on=${one.value === current}
                 onTap=${() => onPick(one.value === current ? null : one.value)} />`)}
    </div>`;
}

function kindsOf(rows) {
  const found = [];
  rows.forEach((row) => {
    if (row.kind && !found.includes(row.kind)) { found.push(row.kind); }
  });
  return found;
}

function kept(rows, local) {
  return rows.filter((row) => (local.hall === undefined || local.hall === null
                               || row.hall === local.hall)
                              && (!local.kind || row.kind === local.kind));
}

function byOf(name, words) {
  return name ? fill(words.bases_by, "name", name) : "";
}

function hallOf(hall, words) {
  return hall ? fill(words.bases_hall, "hall", hall) : "";
}

function labelOf(kind, conf) {
  const names = conf.LABELS || [];
  return names.includes(kind) ? kind : (names[0] || "");
}

function moves(link, label, hall, words, kit) {
  return html`
    <${Chips}>
      ${opener(link, words)}
      <${Chip} text=${words.bases_copy} onTap=${() => copy(link)} />
      ${label ? html`
        <${Chip} text=${words.bases_propose}
                 onTap=${() => kit.run("base.propose", { link: link, label: label },
                                       baseProposed({ link: link, label: label,
                                                      hall: hall }))} />` : null}
    <//>`;
}

function baseTile(big, name, sub, link, label, words, kit) {
  return html`
    <${Tile} tone="base" big=${big} label=${name} sub=${html`
      <span>${sub}</span>
      ${moves(link, label, big, words, kit)}`} />`;
}

function grid(rows, words) {
  return rows.length ? html`<${Grid}>${rows}<//>`
                     : html`<${Empty} art="nobases" text=${words.empty} />`;
}

function library(found, words, conf, kit) {
  const rows = found.rows || [];
  const shown = kept(rows, kit.local);
  return html`
    ${picker((found.halls || []).map((hall) => ({ value: hall, text: hallOf(hall, words) })),
             kit.local.hall, null, (value) => kit.pick("hall", value))}
    ${picker(kindsOf(rows).map((kind) => ({ value: kind, text: kind })),
             kit.local.kind, words.bases_kind, (value) => kit.pick("kind", value))}
    <${Card}>
      ${grid(shown.map((row) => baseTile(
          row.hall, row.name, joined([row.kind, byOf(row.builder, words)]), row.link,
          labelOf(row.kind, conf), words, kit)), words)}
    <//>`;
}

function ours(rows, words, kit) {
  return html`
    <${Card}>
      ${grid(rows.map((row) => baseTile(
          row.hall, words["base_label_" + row.label] || row.label,
          joined([words["base_village_" + row.village], byOf(row.by, words)]), row.link,
          null, words, kit)), words)}
    <//>`;
}

function clip(row, conf) {
  return html`
    <img class="thumb" alt="" loading="lazy"
         src=${conf.THUMB + encodeURIComponent(row.id) + conf.THUMB_SIZE} />`;
}

function videoTile(row, words, conf, kit) {
  const links = row.links || [];
  return html`
    <${Tile} tone="video" icon=${clip(row, conf)} big=${links.length} label=${row.title}
             sub=${html`
      <span>${row.published}</span>
      ${links.map((link) => moves(link, labelOf(null, conf), row.hall, words, kit))}`} />`;
}

function videos(rows, words, conf, kit) {
  return html`
    <${Card}>
      ${grid(rows.map((row) => videoTile(row, words, conf, kit)), words)}
    <//>`;
}

export function bases(state, words, conf, kit) {
  const found = state.bases || {};
  const shelf = found.library || {};
  const tab = TABS.includes(kit.local.bases) ? kit.local.bases : FIRST;
  return html`
    ${picker(TABS.map((name) => ({ value: name, text: words["bases_" + name] })), tab, null,
             (value) => kit.pick("bases", value || tab))}
    ${tab === "clan" ? ours(found.clan || [], words, kit) : null}
    ${tab === "library" ? library(shelf, words, conf, kit) : null}
    ${tab === "videos" ? videos(shelf.videos || [], words, conf, kit) : null}`;
}
