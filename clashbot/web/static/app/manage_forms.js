import { html } from "../vendor/htm-preact-standalone.module.js";
import { Card, Chip, Grid, Tile } from "./ui.js";
import { icon } from "./art.js";
import { fill } from "./model.js";
import { after, line, lines, screen } from "./manage_bits.js";
import { chanAdd, chanDrop, integSet, minTh, schedAdd, schedDrop, senderFree,
         textSaved } from "./guess.js";

const SHEET = "sheet";
const SCHEDULE = "schedule";
const TEXTS = "texts";
const CHANNEL = "channel";
const DAYS = "days";
const CLOCK = "hhmm";
const SAID = "sched_text";
const BODY = "text";
const PREVIEW = "preview";
const FIELDS = ["welcome", "rules"];
const RECRUIT = "recruit";
const FAMILY = "family";
const TOURNEY = "tourney";
const DERBY = "derby";
const GAMES = "challenges";
const HIRING = "recruitment";
const WARS = "wars";
const FAMILY_NAME = "family_name";
const FAMILY_CODE = "family_code";
const TWITCH = "twitch";
const DISCORD = "discord";
const ICS = "ics";
const INTEGRATIONS = "integrations";
const FLOOR = 0;
const STEP = 1;

export function schedules(view, words, kit) {
  return html`
    <${Card} title=${words.manage_schedules} tone="schedules">
      <${Grid}>
        ${(view.schedules || []).map((row) => html`
          <${Tile} big=${row.hhmm} label=${words.manage_sched_del} sub=${row.text}
                   onTap=${() => kit.run("schedule.delete", { ref: String(row.id) },
                                         schedDrop(row.id))} />`)}
      <//>
      ${line(html`
        <${Chip} text=${words.manage_sched_add}
                 onTap=${() => kit.pick(SHEET, { kind: SCHEDULE })} />`)}
    <//>`;
}

function dayChips(words, conf, kit) {
  const picked = String(kit.local[DAYS] || "");
  return (conf.WEEKDAYS || []).map((day) => html`
    <${Chip} text=${words["weekday_" + day]} on=${picked.includes(day)}
             onTap=${() => kit.pick(DAYS, picked.includes(day)
                                         ? picked.split(day).join("") : picked + day)} />`);
}

export function scheduleSheet(words, conf, kit) {
  const open = kit.local[SHEET];
  if (!open || open.kind !== SCHEDULE) { return null; }
  const when = kit.local[CLOCK] || "";
  const said = kit.local[SAID] || "";
  return html`
    <${Card} title=${words.manage_schedules} tone="sheet">
      <input class="field" type="time" value=${when}
             onInput=${(event) => kit.pick(CLOCK, event.target.value)} />
      ${line(dayChips(words, conf, kit))}
      ${kit.local[DAYS] ? null : html`<div class="sub">${words.manage_sched_every}</div>`}
      <textarea class="field" maxLength=${conf.TEXT_MAX} value=${said}
                onInput=${(event) => kit.pick(SAID, event.target.value)} />
      ${line(html`
        <${Chip} text=${words.manage_save}
                 onTap=${() => after(kit, "schedule.add",
                                     { hhmm: when, days: String(kit.local[DAYS] || ""),
                                       text: said },
                                     [[SHEET, null], [SAID, ""]],
                                     schedAdd({ hhmm: when, text: said }))} />`)}
    <//>`;
}

export function texts(view, words, kit) {
  const stored = view.texts || {};
  return html`
    <${Card} title=${words.manage_texts} tone="texts">
      <${Grid}>
        ${FIELDS.map((field) => html`
          <${Tile} big=${words["manage_" + field]} label=${stored[field] || words.empty}
                   onTap=${() => {
                     kit.pick(BODY, undefined);
                     kit.pick(PREVIEW, "");
                     kit.pick(SHEET, { kind: TEXTS, field: field });
                   }} />`)}
      <//>
    <//>`;
}

export function textSheet(view, words, conf, kit) {
  const open = kit.local[SHEET];
  if (!open || open.kind !== TEXTS) { return null; }
  const stored = (view.texts || {})[open.field] || "";
  const said = kit.local[BODY] === undefined ? stored : kit.local[BODY];
  const shown = lines(kit.local[PREVIEW]);
  return html`
    <${Card} title=${words["manage_" + open.field]} tone="sheet">
      <textarea class="field" maxLength=${conf.TEXT_MAX} value=${said}
                onInput=${(event) => kit.pick(BODY, event.target.value)} />
      ${shown.length ? html`
        <div class="preview">${shown.map((row) => html`<div>${row}</div>`)}</div>` : null}
      ${line(html`
        <${Chip} text=${words.manage_save}
                 onTap=${() => after(kit, open.field + ".set", { text: said },
                                     [[SHEET, null], [BODY, undefined], [PREVIEW, ""]],
                                     textSaved(open.field, said))} />`)}
    <//>`;
}

export function channels(view, words, conf, kit) {
  const wanted = kit.local[CHANNEL] || "";
  return html`
    <${Card} title=${words.manage_channels} tone="channels">
      <${Grid}>
        ${(view.channels || []).map((row) => html`
          <${Tile} big=${row.title || row.id} label=${words.manage_sched_del} sub=${row.id}
                   onTap=${() => kit.run("channel.drop", { channel: row.id },
                                         chanDrop(row.id))} />`)}
      <//>
      <input class="field" value=${wanted} maxLength=${conf.TOKEN_MAX}
             onInput=${(event) => kit.pick(CHANNEL, event.target.value)} />
      ${line(html`
        <${Chip} text=${words.manage_sched_add}
                 onTap=${() => after(kit, "channel.add", { channel: wanted },
                                     [[CHANNEL, ""]], chanAdd({ id: wanted }))} />`)}
    <//>`;
}

export function recruit(view, words, kit) {
  const found = view[RECRUIT] || null;
  if (!found) { return null; }
  const th = Number(found.th || FLOOR);
  const aim = (next) => () => kit.run("recruit.requirements.set", { th: String(next) },
                                      minTh(next));
  return html`
    <${Card} title=${words.more_recruit} tone=${RECRUIT}>
      <${Grid}>
        <${Tile} icon=${icon(HIRING)} on=${Boolean(th)}
                 big=${th ? fill(words.manage_req_hint, "th", th) : words.req_none}
                 label=${words.more_requirement} />
      <//>
      ${line([
        html`<${Chip} text=${words.manage_th_down}
                      onTap=${aim(Math.max(FLOOR, th - STEP))} />`,
        html`<${Chip} text=${words.manage_th_up} onTap=${aim(th + STEP)} />`,
      ])}
    <//>`;
}

export function blocked(view, words, kit) {
  const rows = (view[RECRUIT] || {}).blocked || [];
  if (!rows.length) { return null; }
  return html`
    <${Card} title=${words.manage_block_title} tone="blocked">
      <${Grid}>
        ${rows.map((row) => html`
          <${Tile} big=${row.name || row.id} label=${words.manage_unblock}
                   onTap=${() => kit.run("sender.unblock", { ref: String(row.id) },
                                         senderFree(row.id))} />`)}
      <//>
    <//>`;
}

function joined(found, words, kit) {
  return html`
    <${Grid}>
      <${Tile} icon=${icon(FAMILY)} big=${found.name || found.code}
               label=${words.manage_family_code} sub=${found.code} />
      ${found[DERBY] ? html`
        <${Tile} icon=${icon(WARS)} label=${words.manage_derby}
                 onTap=${() => kit.pick(SHEET, { kind: DERBY })} />` : null}
      ${found[TOURNEY] ? html`
        <${Tile} icon=${icon(GAMES)} label=${words.manage_tourney}
                 onTap=${() => kit.pick(SHEET, { kind: TOURNEY })} />` : null}
    <//>`;
}

function alone(words, conf, kit) {
  const named = kit.local[FAMILY_NAME] || "";
  const coded = kit.local[FAMILY_CODE] || "";
  return html`
    <input class="field" value=${named} maxLength=${conf.TOKEN_MAX}
           aria-label=${words.manage_family_name}
           onInput=${(event) => kit.pick(FAMILY_NAME, event.target.value)} />
    <input class="field" value=${coded} maxLength=${conf.TOKEN_MAX}
           aria-label=${words.manage_family_code}
           onInput=${(event) => kit.pick(FAMILY_CODE, event.target.value)} />
    <${Grid}>
      <${Tile} icon=${icon(FAMILY)} big=${words.manage_family_new}
               label=${words.manage_family_name}
               onTap=${() => after(kit, "family.create", { name: named },
                                   [[FAMILY_NAME, ""]])} />
      <${Tile} icon=${icon(FAMILY)} big=${words.manage_family_invite}
               label=${words.manage_family_code}
               onTap=${() => after(kit, "family.invite", { ref: coded },
                                   [[FAMILY_CODE, ""]])} />
    <//>`;
}

export function family(view, words, conf, kit) {
  const found = view[FAMILY] || null;
  if (!found) { return null; }
  return html`
    <${Card} title=${words.more_family} tone=${FAMILY}>
      ${found.code ? joined(found, words, kit) : alone(words, conf, kit)}
    <//>`;
}

export function familySheet(view, words, kit) {
  const open = kit.local[SHEET];
  const found = view[FAMILY] || {};
  if (!open || (open.kind !== DERBY && open.kind !== TOURNEY)) { return null; }
  const shown = open.kind === DERBY ? found[DERBY] : found[TOURNEY];
  if (!shown) { return null; }
  return html`
    <${Card} tone="sheet"
             title=${open.kind === DERBY ? words.manage_derby : words.manage_tourney}>
      ${screen(shown, kit, open.kind === DERBY ? "family.derby" : "family.tourney")}
    <//>`;
}

export function integrations(view, words, conf, kit) {
  const found = view[INTEGRATIONS] || null;
  if (!found) { return null; }
  const both = conf.SWITCH || [];
  const typed = kit.local[TWITCH] === undefined ? found[TWITCH] : kit.local[TWITCH];
  const saying = (on) => (on ? words.manage_state_on : words.manage_state_off);
  return html`
    <${Card} title=${words.manage_integrations} tone=${INTEGRATIONS}>
      <input class="field" value=${typed} maxLength=${conf.TOKEN_MAX}
             aria-label=${words.manage_twitch_title}
             onInput=${(event) => kit.pick(TWITCH, event.target.value)} />
      <${Grid}>
        <${Tile} big=${found[TWITCH] || saying(false)} label=${words.manage_twitch_title}
                 on=${Boolean(found[TWITCH])}
                 onTap=${() => kit.run("integration.twitch", { channel: typed },
                                       integSet(TWITCH, typed))} />
        <${Tile} big=${saying(found[DISCORD])} label=${words.manage_discord_title}
                 on=${found[DISCORD]}
                 onTap=${found[DISCORD]
                         ? () => kit.run("integration.discord", { on: both[1] },
                                         integSet(DISCORD, false))
                         : null} />
        <${Tile} big=${saying(found[ICS])} label=${words.manage_ics_title} on=${found[ICS]}
                 onTap=${() => kit.run("integration.ics",
                                       { on: found[ICS] ? both[1] : both[0] },
                                       integSet(ICS, !found[ICS]))} />
      <//>
    <//>`;
}
