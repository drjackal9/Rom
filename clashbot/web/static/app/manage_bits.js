import { html } from "../vendor/htm-preact-standalone.module.js";
import { Chip, Chips, Switch } from "./ui.js";

const MARKS = /<[^>]*>/g;
const BREAK = "\n";
const NONE = { run: () => {}, pick: () => {}, local: {}, now: 0 };

export const CONFIRM = "confirm";
export const TOAST = "toast";
export const UNDO = "undo.apply";

export function kitOf(tools) {
  return Object.assign({}, NONE, tools || {});
}

export function line(children) {
  return html`<div class="chips">${children}</div>`;
}

export function wide(children) {
  return html`<${Chips} tone="wide">${children}<//>`;
}

export function after(kit, kind, extra, picks, made) {
  Promise.resolve(kit.run(kind, extra, made)).then((ok) => {
    if (ok) { (picks || []).forEach((one) => kit.pick(one[0], one[1])); }
  });
}

export function ask(kit, label, kind, extra) {
  const found = kit.local[CONFIRM] || null;
  const on = Boolean(found) && found.kind === kind;
  return html`
    <${Chip} text=${label} on=${on}
             onTap=${() => kit.pick(CONFIRM, on ? null : { kind: kind, extra: extra || {} })} />`;
}

export function switcher(kit, conf, words, on, kind, label, made) {
  const both = conf.SWITCH || [];
  return html`
    <${Switch} on=${on} label=${label}
               onTap=${() => kit.run(kind, { on: on ? both[1] : both[0] }, made)} />
    <div class="sub">${on ? words.manage_state_on : words.manage_state_off}</div>`;
}

export function lines(raw) {
  return String(raw || "").replace(MARKS, "").split(BREAK).filter((one) => one.trim());
}

export function screen(found, kit, kind) {
  if (!found) { return null; }
  return html`
    ${lines(found.text).map((row) => html`<div class="sub">${row}</div>`)}
    ${(found.buttons || []).map((row) => line(row.map((one) => html`
      <${Chip} text=${one.label} onTap=${() => kit.run(kind, { data: one.data })} />`)))}`;
}
