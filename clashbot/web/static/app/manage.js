import { html } from "../vendor/htm-preact-standalone.module.js";
import { Card, Chip, Empty, Grid, Item, Switch, Tile } from "./ui.js";
import { icon } from "./art.js";
import { MANAGE, isLeader, isManager } from "./model.js";
import { CONFIRM, UNDO, ask, kitOf, line, screen, switcher, wide } from "./manage_bits.js";
import { approved, inbox, reportSheet } from "./manage_inbox.js";
import { blocked, channels, family, familySheet, integrations, recruit, scheduleSheet,
         schedules, textSheet, texts } from "./manage_forms.js";
import { boardSet, delegateOff, delegateOn, delegatesOff, familyScore, gateSet, seatBack,
         seenSet, undone, warnVoid } from "./guess.js";

const SHEET = "sheet";
const PACK = "pack";
const SCHEDULE = "schedule";
const WARS = "wars";
const LEADERS = "leaders";
const PAUSE = "clan.pause";
const RESUME = "clan.resume";
const CLEAR = "delegates.clear";
const OPEN = "settings.open";
const PRESS = "settings.press";
const ARMED = [PAUSE, RESUME, UNDO, CLEAR];

function toolsOf(state, pack) {
  return ((state.me || {}).tools || {})[pack] || {};
}

function packs(state, view, words, conf, kit, full) {
  const live = view.packs || {};
  const gate = Boolean(toolsOf(state, LEADERS).gate);
  return html`
    <${Card} title=${words.manage_packs} tone="packs">
      <${Grid}>
        ${Object.keys(live).map((pack) => html`
          <${Tile} icon=${icon(pack)} label=${words["pack_" + pack]} on=${live[pack]}
                   sub=${live[pack] ? words.manage_state_on : words.manage_state_off}
                   onTap=${() => kit.pick(SHEET, { kind: PACK, pack: pack })} />`)}
      <//>
      ${full ? switcher(kit, conf, words, gate, "gate.toggle", words.manage_gate_title,
                        gateSet(!gate)) : null}
    <//>`;
}

export function packSheet(state, view, words, kit, full) {
  const open = kit.local[SHEET];
  if (!open || open.kind !== PACK) { return null; }
  const on = Boolean((view.packs || {})[open.pack]);
  const said = (state.sections || {})[open.pack] || [];
  const times = view.schedules || [];
  return html`
    <${Card} tone="sheet" title=${words["pack_" + open.pack]}>
      <${Grid}>
        <${Tile} icon=${icon(open.pack)} big=${said.length} on=${on}
                 label=${on ? words.manage_state_on : words.manage_state_off} />
        ${times.map((row) => html`
          <${Tile} big=${row.hhmm} label=${row.text} />`)}
      <//>
      ${times.length ? null : html`
        <${Empty} art="empty" text=${words.empty}
                  action=${full ? words.manage_sched_add : null}
                  onAction=${() => kit.pick(SHEET, { kind: SCHEDULE })} />`}
    <//>`;
}


export function lastAction(view) {
  return (view && (view.log || []).find((row) => row.of && row.ref)) || null;
}

function newest(view) {
  const first = ((view || {}).log || [])[0] || null;
  return first && first.of && first.ref ? first : null;
}

export function toastAct(state, toast) {
  if (!toast || toast.kind !== UNDO) { return null; }
  const found = toast.extra || newest((state || {}).manage_view);
  return found ? { kind: UNDO, extra: { of: found.of, ref: found.ref } } : null;
}

function staff(view, words, kit) {
  if (!view.chief) { return null; }
  const stopped = view.suspended || [];
  const last = lastAction(view);
  return html`
    <${Card} title=${words.manage_staff}>
      ${line([
        view.paused ? ask(kit, words.manage_resume, RESUME)
                    : ask(kit, words.manage_pause, PAUSE),
        last ? ask(kit, words.manage_undo, UNDO, { of: last.of, ref: last.ref }) : null,
      ])}
      ${stopped.length ? html`<div class="sub">${words.manage_suspended}</div>` : null}
      ${stopped.map((row) => html`
        <${Item} title=${row.name}>
          ${wide(html`
            <${Chip} text=${words.manage_lift}
                     onTap=${() => kit.run("suspension.lift", { who: String(row.who) },
                                           seatBack(row.who))} />`)}
        <//>`)}
    <//>`;
}

function delegates(view, words, kit) {
  const picked = view.delegates || [];
  const people = view.people || [];
  if (!picked.length && !people.length) { return null; }
  return html`
    <${Card} title=${words.manage_delegates}>
      ${picked.map((row) => html`
        <${Item} title=${row.name}>
          ${wide(html`
            <${Chip} text=${words.manage_delegate_off} on=${true}
                     onTap=${() => kit.run("delegate.remove", { who: String(row.who) },
                                           delegateOff(row.who))} />`)}
        <//>`)}
      ${people.map((row) => html`
        <${Item} title=${row.name}>
          ${wide(html`
            <${Chip} text=${words.manage_delegate_on}
                     onTap=${() => kit.run("delegate.add", { who: String(row.who) },
                                           delegateOn(row.who))} />`)}
        <//>`)}
      ${view.chief && picked.length ? line(ask(kit, words.manage_clear, CLEAR)) : null}
    <//>`;
}

function warned(state, view, words, kit) {
  const rows = toolsOf(state, WARS).warnings || [];
  if (!rows.length) { return null; }
  return html`
    <${Card} title=${words.manage_warn_list}>
      ${rows.map((row) => html`
        <${Item} title=${row.name}>
          ${view.chief ? wide(html`
            <${Chip} text=${words.manage_void}
                     onTap=${() => kit.run("warning.void", { ref: String(row.id) },
                                           warnVoid(row.id))} />`) : null}
        <//>`)}
    <//>`;
}

function seenRow(state, words, conf, kit, name) {
  const now = state.views || {};
  return html`
    <${Item} title=${words["views_" + name]}>
      ${line((conf.SEEN_BY || []).map((value) => html`
        <${Chip} text=${words["seen_" + value]} on=${now[name] === value}
                 onTap=${() => kit.run("view.set", { section: name, value: value },
                                       seenSet(name, value))} />`))}
    <//>`;
}

function seen(state, words, conf, kit) {
  const now = state.views || {};
  if (!now || !Object.keys(now).length) { return null; }
  return html`
    <${Card} title=${words.views_title} tone="views">
      ${(conf.SECTIONS || []).map((name) => seenRow(state, words, conf, kit, name))}
      <${Switch} on=${Boolean(now.family_score)} label=${words.views_family}
                 onTap=${() => kit.run("family.score.toggle", {},
                                       familyScore(!now.family_score))} />
    <//>`;
}

function page(view, words, conf, kit) {
  return html`
    <${Card} tone="page">
      ${switcher(kit, conf, words, Boolean(view.page_on), "page.toggle", words.page_state,
                 boardSet("page_on", !view.page_on))}
    <//>`;
}

function others(state, conf) {
  const mine = (state.me || {})[MANAGE] || {};
  const tiled = (conf.MANAGE || []).concat([conf.STAFF]);
  return (conf.AREAS || []).filter((area) => area in mine && !tiled.includes(area));
}

function board(state, words, conf, kit) {
  const mine = (state.me || {})[MANAGE] || {};
  const areas = others(state, conf);
  if (!areas.length) { return null; }
  return html`
    <${Card} title=${words.manage_settings}>
      ${areas.map((area) => screen(mine[area], kit, PRESS))}
      ${line(html`
        <${Chip} text=${words.manage_restart} onTap=${() => kit.run(OPEN, {})} />`)}
    <//>`;
}

function still(view, kind) {
  if (kind === PAUSE) { return !view.paused; }
  if (kind === RESUME) { return Boolean(view.paused); }
  if (kind === CLEAR) { return Boolean((view.delegates || []).length); }
  return Boolean(lastAction(view));
}

function sure(found) {
  const extra = found.extra || {};
  if (found.kind === PAUSE) { return boardSet("paused", true); }
  if (found.kind === RESUME) { return boardSet("paused", false); }
  if (found.kind === CLEAR) { return delegatesOff(); }
  return undone(extra.of, extra.ref);
}

export function primary(state, words, conf, local) {
  const found = (local || {})[CONFIRM] || null;
  if (!found || !ARMED.includes(found.kind) || !isManager(state)) { return null; }
  const view = state.manage_view || null;
  if (!view || !view.chief || !still(view, found.kind)) { return null; }
  return { label: words.manage_sure, kind: found.kind, extra: found.extra || {},
           optimistic: sure(found) };
}

export function manage(state, words, conf, tools) {
  const kit = kitOf(tools);
  if (!isManager(state)) {
    return html`<${Card}><${Empty} art="empty" text=${words.empty_screen} /><//>`;
  }
  const view = state.manage_view || null;
  const full = isLeader(state);
  return html`
    ${inbox(state, words, conf, kit)}
    ${view ? html`
      ${packs(state, view, words, conf, kit, full)}
      ${staff(view, words, kit)}
      ${delegates(view, words, kit)}
      ${warned(state, view, words, kit)}
      ${packSheet(state, view, words, kit, full)}` : null}
    ${view && full ? html`
      ${approved(view, words, conf, kit)}
      ${seen(state, words, conf, kit)}
      ${recruit(view, words, kit)}
      ${blocked(view, words, kit)}
      ${schedules(view, words, kit)}
      ${texts(view, words, kit)}
      ${page(view, words, conf, kit)}
      ${channels(view, words, conf, kit)}
      ${family(view, words, conf, kit)}
      ${integrations(view, words, conf, kit)}
      ${board(state, words, conf, kit)}
      ${scheduleSheet(words, conf, kit)}
      ${textSheet(view, words, conf, kit)}
      ${familySheet(view, words, kit)}` : null}
    ${reportSheet(words, kit)}`;
}
