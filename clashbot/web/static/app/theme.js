const MAP = [["bg_color", "--bg"], ["text_color", "--text"], ["hint_color", "--hint"],
             ["link_color", "--link"], ["button_color", "--button"],
             ["button_text_color", "--button-text"], ["secondary_bg_color", "--bg2"]];

const DARK = "dark";
const READABLE = 4.5;
const STEP = 0.05;
const TRIES = 20;
const WHITE = 255;
const BLACK = 0;

function channel(value) {
  const part = value / 255;
  return part <= 0.04045 ? part / 12.92 : ((part + 0.055) / 1.055) ** 2.4;
}

function parse(color) {
  const raw = String(color || "").trim().replace("#", "");
  const full = raw.length === 3 ? raw.split("").map((one) => one + one).join("") : raw;
  if (full.length !== 6 || /[^0-9a-f]/i.test(full)) { return null; }
  return [0, 2, 4].map((at) => parseInt(full.slice(at, at + 2), 16));
}

function luma(rgb) {
  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

function paint(rgb) {
  return "#" + rgb.map((one) => Math.round(one).toString(16).padStart(2, "0")).join("");
}

export function contrast(one, other) {
  const first = parse(one);
  const second = parse(other);
  if (!first || !second) { return 0; }
  const high = Math.max(luma(first), luma(second));
  const low = Math.min(luma(first), luma(second));
  return (high + 0.05) / (low + 0.05);
}

function lift(color, bed) {
  const tint = parse(color);
  if (!tint || !parse(bed)) { return color; }
  const towards = contrast(paint([BLACK, BLACK, BLACK]), bed)
    >= contrast(paint([WHITE, WHITE, WHITE]), bed) ? BLACK : WHITE;
  let found = tint;
  for (let step = 0; step <= TRIES; step += 1) {
    found = tint.map((one) => one + (towards - one) * step * STEP);
    if (contrast(paint(found), bed) >= READABLE) { return paint(found); }
  }
  return paint(found);
}

function bedOf(root) {
  const own = root.style.getPropertyValue ? root.style.getPropertyValue("--bg") : "";
  if (own) { return own.trim(); }
  const view = globalThis.getComputedStyle;
  return view ? view(root).getPropertyValue("--bg").trim() : "";
}

export function applyAccent(color, root) {
  if (!color) { return; }
  root.style.setProperty("--accent", lift(color, bedOf(root)));
}

function applySurfaces(params, scheme, root) {
  const page = params.bg_color;
  const second = params.secondary_bg_color;
  if (!page || !second) { return; }
  root.style.setProperty("--card", scheme === DARK ? second : page);
  root.style.setProperty("--line", scheme === DARK ? page : second);
}

export function applyTheme(tg, root) {
  const params = (tg && tg.themeParams) || {};
  for (const [from, to] of MAP) {
    if (params[from]) { root.style.setProperty(to, params[from]); }
  }
  applySurfaces(params, tg && tg.colorScheme, root);
  if (tg && tg.colorScheme) { root.dataset.scheme = tg.colorScheme; }
}

export function applySafeArea(tg, root) {
  const device = (tg && tg.safeAreaInset) || {};
  const content = (tg && tg.contentSafeAreaInset) || {};
  root.style.setProperty("--safe-bottom", (device.bottom || 0) + "px");
  root.style.setProperty("--safe-top", ((device.top || 0) + (content.top || 0)) + "px");
}

export function watchTheme(tg, root) {
  applyTheme(tg, root);
  applySafeArea(tg, root);
  if (tg && tg.onEvent) {
    tg.onEvent("themeChanged", () => applyTheme(tg, root));
    tg.onEvent("safeAreaChanged", () => applySafeArea(tg, root));
    tg.onEvent("contentSafeAreaChanged", () => applySafeArea(tg, root));
  }
}
