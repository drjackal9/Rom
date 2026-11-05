import { html } from "../vendor/htm-preact-standalone.module.js";

const BOX = "0 0 64 64";

const frame = (shapes) => html`
  <svg class="art" viewBox=${BOX} width="64" height="64" aria-hidden="true" fill="none"
       stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
    ${shapes}
  </svg>`;

const ART = {
  nowar: () => frame(html`
    <path d="M32 9 52 17v14c0 12-9 20-20 24-11-4-20-12-20-24V17Z" />
    <path d="M18 14 46 50" />`),
  nogames: () => frame(html`
    <rect x="13" y="13" width="38" height="38" rx="8" />
    <circle cx="25" cy="25" r="3" fill="currentColor" stroke="none" />
    <circle cx="39" cy="39" r="3" fill="currentColor" stroke="none" />
    <path d="M16 16 48 48" />`),
  nomembers: () => frame(html`
    <circle cx="32" cy="24" r="10" />
    <path d="M14 52c3-10 10-14 18-14s15 4 18 14" />`),
  linked: () => frame(html`
    <rect x="9" y="26" width="28" height="12" rx="6" />
    <rect x="27" y="26" width="28" height="12" rx="6" />`),
  offline: () => frame(html`
    <path d="M21 45a11 11 0 0 1 1-22 14 14 0 0 1 26 5 9 9 0 0 1-2 17Z" />
    <path d="M14 14 50 50" />`),
  nocwl: () => frame(html`
    <path d="M12 18 18 42h28l6-24-10 9-10-14-10 14Z" />
    <path d="M16 50h32" />
    <path d="M14 14 50 50" />`),
  noinbox: () => frame(html`
    <path d="M14 16h36l6 16v18H8V32Z" />
    <path d="M8 32h14l4 8h12l4-8h14" />`),
  nobases: () => frame(html`
    <path d="M12 52V26l20-14 20 14v26Z" />
    <path d="M14 14 50 50" />`),
  nochronicle: () => frame(html`
    <circle cx="32" cy="32" r="20" />
    <path d="M32 20v13l9 5" />`),
  empty: () => frame(html`
    <path d="M12 26h40v24H12Z" />
    <path d="M12 26 20 14h24l8 12" />
    <path d="M26 34h12" />`),
};

export function illustration(name) {
  return (ART[name] || ART.empty)();
}

const SMALL = "0 0 24 24";

const mark = (shapes) => html`
  <svg class="ico" viewBox=${SMALL} aria-hidden="true" fill="none" stroke="currentColor"
       stroke-linecap="round" stroke-linejoin="round">
    ${shapes}
  </svg>`;

const SAME = { war: "wars" };

const ICON = {
  wars: () => mark(html`<path d="M12 3 20 6v6c0 5-4 8-8 9-4-1-8-4-8-9V6Z" />`),
  clan: () => mark(html`
    <path d="M6 21V4" />
    <path d="M6 5h12l-3 4 3 4H6" />`),
  me: () => mark(html`
    <rect x="3" y="4" width="18" height="16" rx="5" />
    <circle cx="12" cy="10" r="2.5" />
    <path d="M7.5 17c1-2.4 2.6-3.4 4.5-3.4s3.5 1 4.5 3.4" />`),
  more: () => mark(html`
    <rect x="4" y="4" width="7" height="7" rx="2" />
    <rect x="13" y="4" width="7" height="7" rx="2" />
    <rect x="4" y="13" width="7" height="7" rx="2" />
    <rect x="13" y="13" width="7" height="7" rx="2" />`),
  manage: () => mark(html`
    <path d="M4 8h16M4 16h16" />
    <circle cx="9" cy="8" r="2.5" />
    <circle cx="15" cy="16" r="2.5" />`),
  cwl: () => mark(html`
    <path d="M5 6 8 15h8l3-9-4 3.5L12 4 8 9.5Z" />
    <path d="M7 19h10" />`),
  capital_games: () => mark(html`
    <rect x="3" y="9" width="18" height="10" rx="4" />
    <path d="M7 14h3M8.5 12.5v3" />
    <circle cx="16" cy="14" r="1" fill="currentColor" stroke="none" />`),
  members: () => mark(html`
    <circle cx="12" cy="9" r="4" />
    <path d="M5 20c1-4 4-6 7-6s6 2 7 6" />`),
  challenges: () => mark(html`
    <circle cx="12" cy="9" r="5" />
    <path d="m9 14-1 7 4-2 4 2-1-7" />`),
  family: () => mark(html`
    <circle cx="8" cy="9" r="3" />
    <circle cx="16" cy="9" r="3" />
    <path d="M2 19c1-3 3-4 6-4s5 1 6 4M12 19c1-3 3-4 6-4s4 1 4 4" />`),
  recruitment: () => mark(html`
    <circle cx="10" cy="9" r="4" />
    <path d="M3 20c1-4 4-6 7-6" />
    <path d="M17 14v7M13.5 17.5h7" />`),
  bases: () => mark(html`
    <path d="M4 20V10l8-6 8 6v10Z" />
    <path d="M10 20v-6h4v6" />`),
  platform: () => mark(html`
    <path d="M5 10v4h3l7 4V6l-7 4Z" />
    <path d="M18 9a4 4 0 0 1 0 6" />`),
  linked: () => mark(html`<path d="m5 13 4 4 10-10" />`),
  empty: () => mark(html`<circle cx="12" cy="12" r="7" />`),
};

export function icon(name) {
  return (ICON[SAME[name] || name] || ICON.empty)();
}

export function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) {
    return "";
  }
  const first = Array.from(parts[0]);
  const last = parts.length > 1 ? Array.from(parts[parts.length - 1]) : first.slice(1);
  return ((first[0] || "") + (last[0] || "")).toUpperCase();
}
