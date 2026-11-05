import { html } from "../vendor/htm-preact-standalone.module.js";

export const WIDE = 320;
export const TALL = 120;
export const BAND = 26;

const AXIS = 10;
const MORE = "+";
const LESS = "\u2212";

function numbers(values) {
  return (values || []).filter((one) => one !== null && one !== undefined).map(Number);
}

function marks(values) {
  const at = [];
  (values || []).forEach((one, index) => {
    if (one !== null && one !== undefined) { at.push(index); }
  });
  return at;
}

function pair(one, two) {
  return [one, two].filter((part) => part !== "" && part !== null && part !== undefined).join(" ");
}

export function scale(values, height) {
  const kept = numbers(values);
  const high = kept.length ? Math.max(...kept) : 0;
  const span = kept.length ? high - Math.min(...kept) : 0;
  return (value) => (span ? height * (high - value) / span : height / 2);
}

export function Line({ values, labels, width, height }) {
  const list = values || [];
  const names = labels || [];
  const at = marks(list);
  const y = scale(list, height - AXIS);
  const step = list.length > 1 ? width / (list.length - 1) : 0;
  const points = at.map((index) =>
    (index * step).toFixed(1) + "," + y(Number(list[index])).toFixed(1));
  const head = at.length ? at[0] : 0;
  const tail = at.length ? at[at.length - 1] : names.length - 1;
  const first = at.length ? Number(list[head]) : "";
  const last = at.length ? Number(list[tail]) : "";
  return html`
    <svg class="chart" viewBox=${"0 0 " + width + " " + height} width=${width} height=${height}
         role="img" aria-label=${pair(first, last)}>
      ${points.length ? html`
        <polyline class="line-path" points=${points.join(" ")} />` : null}
      <text class="chart-axis" x="0" y=${height} font-size=${AXIS}>
        ${pair(names[head], first)}
      </text>
      <text class="chart-axis" x=${width} y=${height} font-size=${AXIS} text-anchor="end">
        ${pair(names[tail], last)}
      </text>
    </svg>`;
}

export function Bars({ rows, width, height }) {
  const list = rows || [];
  const top = list.reduce((most, one) => Math.max(most, Number(one.value) || 0), 0);
  const band = list.length ? height / list.length : height;
  const line = band / 2;
  const thick = line / 2;
  return html`
    <svg class="chart" viewBox=${"0 0 " + width + " " + height} width=${width} height=${height}>
      ${list.map((one, at) => html`
        <text class="chart-axis" x="0" y=${band * at + line} font-size=${line}>
          ${one.label}
        </text>
        <text class="chart-axis" x=${width} y=${band * at + line} font-size=${line}
              text-anchor="end">
          ${one.value}
        </text>
        <rect class="bar-fill" x="0" y=${band * at + line + thick / 2} height=${thick}
              width=${top ? width * (Number(one.value) || 0) / top : 0}
              style=${"height:" + thick + "px"} />`)}
    </svg>`;
}

export function Trend({ values, labels, width, height, line }) {
  const kept = [];
  (values || []).forEach((one, at) => {
    if (one !== null && one !== undefined) {
      kept.push({ label: (labels || [])[at] || "", value: Number(one) });
    }
  });
  const last = kept.length ? kept[kept.length - 1].value : 0;
  const gap = kept.length ? last - kept[0].value : 0;
  return html`
    <div class="trend">
      <span class="num">${last}</span>
      <span class="delta">${(gap < 0 ? LESS : MORE) + Math.abs(gap)}</span>
    </div>
    ${line
      ? html`<${Line} values=${values} labels=${labels} width=${width} height=${height} />`
      : html`<${Bars} rows=${kept} width=${width} height=${BAND * kept.length} />`}`;
}
