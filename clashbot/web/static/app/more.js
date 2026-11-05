import { html } from "../vendor/htm-preact-standalone.module.js";
import { Card, Chip, Empty, Grid, Sheet, Tile } from "./ui.js";
import { countdown, fill } from "./model.js";
import { icon, initials } from "./art.js";
import { bases } from "./bases.js";
import { copy } from "./native.js";
import { duelDone, duelMade, pollDone } from "./guess.js";
import { GUESS, guessCount, guessPrimary, guessSheet } from "./guess_attack.js";

const SECTIONS = ["bases", "games", "recruit", "family", "help"];
const FIRST = SECTIONS[0];
const SHEET = "sheet";
const DUEL = "duel";
const FORECAST = "prediction";
const AWARD = "award";
const GAMES = [DUEL, GUESS, FORECAST, AWARD];
const WORD = { duel: "duel", guess: "guess", prediction: "predict", award: "award" };
const PARTS = ["rival", "metric", "duration"];
const RECRUITMENT = "recruitment";
const HOP = "/r/";
const REPORT = "report";
const SUPPORT = "support";
const PRIVACY = "/privacy";

function kitOf(tools) {
  const found = tools || {};
  return { run: found.run || (() => {}), pick: found.pick || (() => {}),
           local: found.local || {}, now: found.now || 0 };
}

function chips(list, current, onPick) {
  return html`
    <div class="chips">
      ${list.map((one) => html`
        <${Chip} text=${one.text} on=${one.value === current}
                 onTap=${() => onPick(one.value)} />`)}
    </div>`;
}

function options(list, onPick) {
  return chips(list.map((text, index) => ({ text: text, value: String(index) })), null, onPick);
}

function duelsOf(state) {
  const rows = ((state.more_view || {}).duels || []).map((row) => Object.assign({}, row));
  const seen = rows.map((row) => row.id);
  (state.todo || []).forEach((row) => {
    if (row.kind === DUEL && !seen.includes(row.id)) { rows.push(row); }
  });
  return rows;
}

function waiting(state, name) {
  return (state.todo || []).filter((row) => row.kind === name);
}

function awardRows(state) {
  return ((state.award || {}).rows || []);
}

function countOf(state, name) {
  if (name === DUEL) { return duelsOf(state).length; }
  if (name === AWARD) { return awardRows(state).length; }
  if (name === GUESS) { return guessCount(state); }
  return waiting(state, name).length;
}

function dotOf(state, name) {
  if (name === GUESS) { return guessCount(state) > 0; }
  return waiting(state, name).length > 0;
}

function endsOf(state, name) {
  if (name === AWARD) { return Number((state.award || {}).ends) || 0; }
  if (name !== DUEL) { return 0; }
  const times = duelsOf(state).map((row) => Number(row.ends) || 0).filter(Boolean);
  return times.length ? Math.min(...times) : 0;
}

function when(ends, words, now) {
  if (!ends || ends <= now) { return ""; }
  const left = countdown(ends, now);
  if (left.d) { return left.d + words.unit_d; }
  if (left.h) { return left.h + words.unit_h; }
  return left.m + words.unit_m;
}

function openOn(kit) {
  const open = kit.local[SHEET];
  return open && GAMES.includes(open.kind) ? open.kind : null;
}

function tiles(state, words, kit) {
  const shown = openOn(kit);
  return html`
    <${Grid}>
      ${GAMES.map((name) => html`
        <${Tile} big=${countOf(state, name)} label=${words["more_" + WORD[name]]}
                 sub=${when(endsOf(state, name), words, kit.now)}
                 dot=${dotOf(state, name)} on=${shown === name}
                 onTap=${() => kit.pick(SHEET, shown === name ? null : { kind: name })} />`)}
    <//>`;
}

function rivalTile(state, words, conf, kit) {
  const found = (state.more_view || {}).rival;
  const metrics = conf.METRICS || [];
  const times = conf.DURATIONS || [];
  if (!found || !found.tag || !metrics.length || !times.length) { return null; }
  return html`
    <${Grid} cols="1">
      <${Tile} big=${found.trophies} label=${fill(words.more_rival, "name", found.name)}
               onTap=${() => kit.run("duel.challenge", { rival: found.tag, metric: metrics[0],
                                                         duration: times[0] },
                                     duelMade(found.name, metrics[0]))} />
    <//>`;
}

function duelSheet(state, words, conf, kit) {
  const mine = waiting(state, DUEL).map((row) => row.id);
  const rows = duelsOf(state);
  const picked = kit.local[DUEL] || {};
  const lists = [
    ((state.more_view || {}).rivals || []).map((row) => ({ value: row.tag, text: row.name })),
    (conf.METRICS || []).map((name) => ({ value: name, text: words["duel_metric_" + name] })),
    (conf.DURATIONS || []).map((name) => ({ value: name, text: words["duel_duration_" + name] })),
  ];
  return html`
    ${rows.length ? html`
      <${Grid}>
        ${rows.map((row) => html`
          <${Tile} big=${row.rival} label=${words["duel_metric_" + row.metric]}
                   sub=${row.mate || ""} dot=${mine.includes(row.id)}
                   badge=${mine.includes(row.id) ? words.duel_accept : null}
                   onTap=${mine.includes(row.id)
                     ? () => kit.run("duel.accept", { duel: row.id }, duelDone(row.id))
                     : null} />`)}
      <//>`
      : html`<${Empty} art="nogames" text=${words.empty} />`}
    ${PARTS.map((part, index) => chips(lists[index], picked[part], (value) => kit.pick(
      DUEL, Object.assign({}, picked, { [part]: value }))))}`;
}

function forecastSheet(state, words, kit) {
  const rows = waiting(state, FORECAST);
  if (!rows.length) { return html`<${Empty} art="nogames" text=${words.empty} />`; }
  return rows.map((row) => options(
    row.options || [],
    (option) => kit.run("prediction.set", { poll: row.poll, option: option },
                        pollDone(row.poll))));
}

function awardSheet(state, words, kit) {
  const rows = awardRows(state);
  if (!rows.length) { return html`<${Empty} art="nogames" text=${words.empty} />`; }
  return options(rows.map((row) => row.name),
                 (option) => kit.run("award.vote", { option: option }));
}

function sheetOf(state, words, conf, kit) {
  const shown = openOn(kit);
  if (!shown) { return null; }
  const inside = {
    duel: () => duelSheet(state, words, conf, kit),
    guess: () => guessSheet(state, words, conf, kit),
    prediction: () => forecastSheet(state, words, kit),
    award: () => awardSheet(state, words, kit),
  };
  return html`<${Sheet} title=${words["more_" + WORD[shown]]}>${inside[shown]()}<//>`;
}

function games(state, words, conf, kit) {
  return html`
    ${tiles(state, words, kit)}
    ${rivalTile(state, words, conf, kit)}
    ${sheetOf(state, words, conf, kit)}`;
}

export function recruit(state, words) {
  const found = state.recruit || {};
  const th = found.requirement;
  return html`
    <${Card} title=${words.more_recruit}>
      <${Grid} cols="3">
        <${Tile} big=${found.free || 0} label=${words.more_free} />
        <${Tile} big=${th ? fill(words.manage_req_hint, "th", th) : words.req_none}
                 label=${words.more_requirement} />
        <${Tile} big=${found.page_on ? words.manage_state_on : words.manage_state_off}
                 label=${words.page_state} on=${Boolean(found.page_on)} />
      <//>
      ${found.open && found.code ? html`
        <${Grid} cols="1">
          <${Tile} icon=${icon(RECRUITMENT)} big=${words.more_apply}
                   href=${HOP + found.code} />
        <//>` : null}
    <//>`;
}

function family(state, words) {
  const found = state.family;
  const rows = (found || {}).clans || [];
  if (!found || !rows.length) {
    return html`<${Card}><${Empty} art="nomembers" text=${words.empty} /><//>`;
  }
  return html`
    <${Card} title=${found.name}>
      <${Grid}>
        ${rows.map((one) => html`
          <${Tile} big=${initials(one.name)} label=${one.name} sub=${one.code} />`)}
      <//>
    <//>`;
}

async function flag(reason, kit) {
  if (await kit.run("report.send", { reason: reason })) { kit.pick(SHEET, null); }
}

function reportSheet(words, conf, kit) {
  if ((kit.local[SHEET] || {}).kind !== REPORT) { return null; }
  return html`
    <${Sheet} title=${words.more_report}>
      ${chips((conf.REASONS || []).map((name) => ({ value: name,
                                                    text: words["reason_" + name] })),
              null, (reason) => flag(reason, kit))}
    <//>`;
}

function supportSheet(state, words, kit) {
  const found = state.help || {};
  if ((kit.local[SHEET] || {}).kind !== SUPPORT) { return null; }
  return html`
    <${Sheet} title=${words.more_support}>
      <${Grid}>
        ${found.support ? html`
          <${Tile} label=${words.more_donate} href=${found.support} />` : null}
        ${found.creator ? html`
          <${Tile} big=${found.creator} label=${words.more_creator}
                   onTap=${() => copy(found.creator)} />` : null}
      <//>
      <${Empty} text=${words.more_stars} />
    <//>`;
}

function help(state, words, conf, kit) {
  const found = state.help || {};
  const open = (kit.local[SHEET] || {}).kind;
  const paper = (kind) => kit.pick(SHEET, open === kind ? null : { kind: kind });
  return html`
    <${Card} title=${words.more_help}>
      <${Grid}>
        ${found.support || found.creator ? html`
          <${Tile} label=${words.more_support} on=${open === SUPPORT}
                   onTap=${() => paper(SUPPORT)} />` : null}
        ${found.community ? html`
          <${Tile} label=${words.more_community} href=${found.community} />` : null}
        <${Tile} label=${words.more_privacy} href=${PRIVACY} />
        ${found.source ? html`
          <${Tile} label=${words.more_source} sub=${words.more_how}
                   href=${found.source} />` : null}
        <${Tile} label=${words.more_report} on=${open === REPORT}
                 onTap=${() => paper(REPORT)} />
      <//>
    <//>
    ${reportSheet(words, conf, kit)}
    ${supportSheet(state, words, kit)}`;
}

export function more(state, words, conf, tools) {
  const kit = kitOf(tools);
  const section = SECTIONS.includes(kit.local.more) ? kit.local.more : FIRST;
  const views = {
    games: () => games(state, words, conf, kit),
    recruit: () => recruit(state, words),
    family: () => family(state, words),
    bases: () => bases(state, words, conf, kit),
    help: () => help(state, words, conf, kit),
  };
  return html`
    ${chips(SECTIONS.map((name) => ({ value: name, text: words["more_" + name] })), section,
            (value) => kit.pick("more", value))}
    ${views[section]()}`;
}

export function primary(state, words, conf, local) {
  const found = local || {};
  if ((found.sheet || {}).kind === GUESS) { return guessPrimary(state, words, found); }
  if (!found.sheet || found.sheet.kind !== DUEL) { return null; }
  const picked = found[DUEL] || {};
  if (PARTS.some((part) => !picked[part])) { return null; }
  const rival = (((state || {}).more_view || {}).rivals || []).find(
    (one) => one.tag === picked.rival) || {};
  return { label: words.more_duel, kind: "duel.challenge",
           extra: { rival: picked.rival, metric: picked.metric, duration: picked.duration },
           optimistic: duelMade(rival.name || picked.rival, picked.metric) };
}
