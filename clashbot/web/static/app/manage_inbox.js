import { html } from "../vendor/htm-preact-standalone.module.js";
import { Card, Chip, Item, Row, Strip } from "./ui.js";
import { fill } from "./model.js";
import { TOAST, UNDO, after, wide } from "./manage_bits.js";
import { applyDone, baseDone, personDone, personGone, personTrust, senderBlocked,
         warnDone } from "./guess.js";

const SHEET = "sheet";
const REPORT = "report";
const PENDING = "pending";
const APPLICATIONS = "applications";
const REPORTS = "reports";
const WARNINGS = "warnings";
const BASES = "bases";

function boxOf(state, conf) {
  if (state.inbox) { return state.inbox; }
  const mine = ((state.me || {}).manage || {})[conf.STAFF] || {};
  return { [PENDING]: mine[PENDING] || [] };
}

function done(words) {
  return [[TOAST, { text: words.manage_done, kind: UNDO }]];
}

function group(label, rows) {
  if (!rows.length) { return null; }
  return html`<div class="sub">${label}</div>${rows}`;
}

function item(title, sub, buttons) {
  return html`
    <${Item} title=${title} sub=${sub}>${wide(buttons)}<//>`;
}

function approve(kit, words, row, from) {
  return () => after(kit, "person.approve", { who: String(row.who), war_from: from },
                     done(words), personDone(row.who));
}

function pending(rows, words, conf, kit) {
  const from = conf.WAR_FROM || [];
  return rows.map((row) => item(row.name, row.tag, html`
    <${Chip} text=${words.manage_now} onTap=${approve(kit, words, row, from[0])} />
    <${Chip} text=${words.manage_next} onTap=${approve(kit, words, row, from[1])} />`));
}

export function approved(view, words, conf, kit) {
  const rows = (view && view.approved) || [];
  if (!rows.length) { return null; }
  const both = conf.SWITCH || [];
  return html`
    <${Card} title=${words.manage_approved}>
      ${rows.map((row) => html`
        <${Item} title=${row.name}>
          ${wide(html`
            <${Chip} text=${words.manage_trust} on=${Boolean(row.trusted)}
                     onTap=${() => kit.run("person.trust",
                                           { who: String(row.who),
                                             value: row.trusted ? both[1] : both[0] },
                                           personTrust(row.who, !row.trusted))} />
            <${Chip} text=${words.manage_revoke}
                     onTap=${() => kit.run("person.revoke", { who: String(row.who) },
                                           personGone(row.who))} />`)}
        <//>`)}
    <//>`;
}

function applications(rows, words, conf, kit) {
  const outcome = conf.DECIDED || [];
  return rows.map((row) => item(
    row.name, row.th ? fill(words.manage_req_hint, "th", row.th) : "", html`
    <${Chip} text=${words.manage_accept}
             onTap=${() => after(kit, "application.decide",
                                 { ref: String(row.id), choice: outcome[0] }, done(words),
                                 applyDone(row.id))} />
    <${Chip} text=${words.manage_reject}
             onTap=${() => after(kit, "application.decide",
                                 { ref: String(row.id), choice: outcome[1] }, done(words),
                                 applyDone(row.id))} />
    <${Chip} text=${words.manage_app_block}
             onTap=${() => after(kit, "sender.block", { ref: String(row.id) }, done(words),
                                 senderBlocked({ id: row.id, name: row.name }))} />`));
}

function reports(rows, words, kit) {
  return rows.map((row) => item(
    words["reason_" + row.reason] || row.reason, row.code, html`
    <${Chip} text=${words.manage_seen}
             onTap=${() => kit.pick(SHEET, { kind: REPORT, code: row.code,
                                             reason: row.reason })} />`));
}

function warnings(rows, words, kit) {
  return rows.map((row) => item(row.name, row.tag, html`
    <${Chip} text=${fill(words.manage_warn_yes, "name", row.name)}
             onTap=${() => after(kit, "warning.confirm", { village: row.tag },
                                 done(words), warnDone(row.tag))} />`));
}

function proposals(rows, words, kit) {
  return rows.map((row) => item(
    row.name, words["base_label_" + row.label] || row.label, html`
    <a class="open" href=${row.link} target="_blank" rel="noopener noreferrer">
      ${words.bases_open}</a>
    <${Chip} text=${words.manage_accept}
             onTap=${() => after(kit, "base.accept", { ref: row.id }, done(words),
                                 baseDone(row.id))} />
    <${Chip} text=${words.manage_reject}
             onTap=${() => after(kit, "base.reject", { ref: row.id }, done(words),
                                 baseDone(row.id))} />`));
}

function many(box) {
  return Object.keys(box).reduce((sum, name) => sum + (box[name] || []).length, 0);
}

export function inbox(state, words, conf, kit) {
  const box = boxOf(state, conf);
  const rows = [
    group(words.manage_claims, pending(box[PENDING] || [], words, conf, kit)),
    group(words.manage_applications,
          applications(box[APPLICATIONS] || [], words, conf, kit)),
    group(words.manage_reports, reports(box[REPORTS] || [], words, kit)),
    group(words.manage_warnings, warnings(box[WARNINGS] || [], words, kit)),
    group(words.manage_bases, proposals(box[BASES] || [], words, kit)),
  ].filter(Boolean);
  return html`
    <${Card} title=${words.manage_inbox} tone="inbox" mark=${many(box)}>
      ${rows.length ? rows : html`<${Strip} text=${words.empty} />`}
    <//>`;
}

export function reportSheet(words, kit) {
  const open = kit.local[SHEET];
  if (!open || open.kind !== REPORT) { return null; }
  return html`
    <${Card} title=${words.manage_reports} tone="sheet">
      <${Row} left=${words["reason_" + open.reason] || open.reason} right=${open.code} />
    <//>`;
}
