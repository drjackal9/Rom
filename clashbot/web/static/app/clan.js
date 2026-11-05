import { html } from "../vendor/htm-preact-standalone.module.js";
import { TALL, Trend, WIDE } from "./charts.js";
import { CHRONICLE, chronicle } from "./chronicle.js";
import { away, climbTiles, peopleGrid, peopleOf, rowsOf } from "./clan_tiles.js";
import { atLeast, fill, isManager, label, percent, score } from "./model.js";
import { recruit as recruitCard } from "./more.js";
import { jump } from "./native.js";
import { noteSaved, warnDone } from "./guess.js";
import { Big, Card, Chip, Chips, Facts, Grid, Medals, Sheet, Tile } from "./ui.js";

const PERSON = "person";
const WEEK = "week";
const CLIMB = "climb";
const REDUCED = "reduced";

function recordOf(state) {
  return peopleOf(state).record || state.record || {};
}

function growthOf(state) {
  return state.growth || {};
}

function weekOf(state, tag) {
  return ((growthOf(state).period || {})[WEEK] || {})[tag] || null;
}

function marks(row, words) {
  return html`
    <${Facts} items=${[words["role_" + row.role], row.linked ? words.clan_linked : null,
                       row.avail ? words["avail_" + row.avail] : null]} />`;
}

function crest(found) {
  if (!found.badge) {
    return null;
  }
  return html`<img class="crest" alt="" loading="lazy" src=${found.badge} />`;
}

function head(state, words) {
  const found = state.clan || {};
  const score = recordOf(state);
  return html`
    <${Card} hero stripe title=${found.name}>
      ${crest(found)}
      <div class="score-row">
        <${Big} value=${found.level || 0} label=${label(words.level)} />
        <${Big} value=${found.members || 0} label=${words.members} />
        <${Big} value=${score.wins || 0} label=${fill(words.clan_record, "n", score.wars || 0)} />
      </div>
      ${found.league ? html`<div class="sub">${found.league}</div>` : null}
    <//>`;
}

function jumps(words, tools) {
  const open = Boolean((tools.local || {})[CHRONICLE]);
  return html`
    <${Chips} tone="jumps">
      <${Chip} text=${words.clan_climb} onTap=${() => jump(CLIMB)} />
      <${Chip} text=${words.clan_chronicle} on=${open}
               onTap=${() => {
                 tools.pick(CHRONICLE, !open);
                 jump(CHRONICLE);
               }} />
    <//>`;
}

function history(state, words) {
  const grown = growthOf(state);
  const values = (grown.clan || {}).trophies || [];
  if (!values.length) {
    return null;
  }
  return html`
    <${Card} title=${words.clan_history}>
      <${Trend} line values=${values} labels=${grown.days || []} width=${WIDE}
                height=${TALL} />
    <//>`;
}

function wars(state, words) {
  const rows = state.wars || [];
  if (!rows.length) {
    return null;
  }
  return html`
    <${Card} title=${words.clan_wars}>
      <${Grid} cols="4">
        ${rows.map((row) => html`
          <${Tile} big=${score(words, "", row.us_stars, row.them_stars)} label=${row.them}
                   sub=${percent(words, row.us_destr)} tone=${row.result} />`)}
      <//>
    <//>`;
}

function numbers(row, words, conf) {
  return html`
    <${Grid}>
      <${Tile} big=${row.trophies} label=${words.clan_sort_trophies} />
      <${Tile} big=${row.th} label=${words.clan_sort_th} />
      <${Tile} big=${row.donations} label=${words.clan_sort_donations} />
      ${row.ratio === null || row.ratio === undefined ? null
        : html`<${Tile} big=${row.ratio} label=${words.clan_ratio} />`}
      ${away(row, conf)
        ? html`<${Tile} big=${row.absent_days} label=${label(words.clan_absent)} />` : null}
    <//>`;
}

function week(found, words) {
  if (!found) {
    return null;
  }
  return html`
    <div class="sub">${words.growth_week}</div>
    <${Grid} cols="3">
      <${Tile} big=${found.donated} label=${words.growth_donated} />
      <${Tile} big=${found.war_stars} label=${words.growth_war_stars} />
      <${Tile} big=${found.levels} label=${words.growth_levels} />
    <//>`;
}

function chart(state, tag, words) {
  const grown = growthOf(state);
  const values = ((grown.players || {})[tag] || {}).trophies || [];
  if (!values.length) {
    return null;
  }
  return html`
    <div class="sub">${words.growth_trophies}</div>
    <${Trend} values=${values} labels=${grown.days || []} width=${WIDE} height=${TALL} />`;
}

function medals(state, tag, conf) {
  const worn = (state.medals || {})[tag] || [];
  if (!worn.length) {
    return null;
  }
  return html`<${Medals} worn=${worn} glyphs=${conf.MEDALS} />`;
}

function draftOf(local, tag) {
  const held = local.note || {};
  return held.tag === tag ? String(held.text || "") : "";
}

function boss(state, row, words, conf, local, tools) {
  if (!isManager(state)) {
    return null;
  }
  const draft = draftOf(local, row.tag);
  return html`
    <${Chip} text=${fill(words.manage_warn_yes, "name", row.name)}
             onTap=${() => tools.run("warning.confirm", { village: row.tag },
                                     warnDone(row.tag))} />
    <div class="sub">${words.manage_note_title}</div>
    <textarea class="note" maxlength=${conf.NOTE_MAX} value=${draft}
              onInput=${(event) =>
                tools.pick("note", { tag: row.tag, text: event.target.value })}></textarea>
    <${Chip} text=${words.manage_save}
             onTap=${() => tools.run("note.set", { village: row.tag, text: draft },
                                     noteSaved(row.tag, row.name, draft))} />`;
}

function person(state, words, conf, local, tools) {
  const want = local.sheet;
  if (!want || want.kind !== PERSON) {
    return null;
  }
  const row = rowsOf(state).find((one) => one.tag === want.tag);
  if (!row) {
    return null;
  }
  return html`
    <${Sheet} title=${row.name}>
      <div class="sub">${row.tag}</div>
      <div class="sub">${marks(row, words)}</div>
      ${numbers(row, words, conf)}
      ${week(weekOf(state, row.tag), words)}
      ${chart(state, row.tag, words)}
      ${medals(state, row.tag, conf)}
      ${boss(state, row, words, conf, local, tools)}
    <//>`;
}

export function clan(state, words, conf, tools) {
  const kit = tools || {};
  const local = kit.local || {};
  const dress = conf || {};
  if (!atLeast(state, REDUCED)) {
    return html`
      ${head(state, words)}
      ${recruitCard(state, words)}`;
  }
  return html`
    ${head(state, words)}
    ${jumps(words, kit)}
    ${peopleGrid(state, words, dress, kit)}
    ${climbTiles(state, words, kit)}
    ${history(state, words)}
    ${wars(state, words)}
    ${chronicle(state, words, kit)}
    ${person(state, words, dress, local, kit)}`;
}
