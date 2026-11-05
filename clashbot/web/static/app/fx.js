const BEAT_EVERY = 2;
const TOAST_BEATS = 3;
const SECOND = 1000;
const SPECK = 6;
const WHOLE = 1;
const CALM = "(prefers-reduced-motion: reduce)";
const PULSE = "beat";
const MS = "ms";
const MEMORY = "fxWas";
const PACE = "--dur-sheet";
const REACH = "--tap";
const PX = "px";

export const BEAT = BEAT_EVERY * SECOND;
export const SPAN = BEAT_EVERY * TOAST_BEATS * SECOND;

function calm() {
  const ask = globalThis.matchMedia;
  return typeof ask === "function" && Boolean(ask.call(globalThis, CALM).matches);
}

function frame(step) {
  if (typeof globalThis.requestAnimationFrame === "function") {
    globalThis.requestAnimationFrame(step);
  }
}

function tint(canvas) {
  const look = globalThis.getComputedStyle ? globalThis.getComputedStyle(canvas) : null;
  return (look && look.color) || "";
}

export function confetti(canvas, count) {
  const paint = canvas && canvas.getContext ? canvas.getContext("2d") : null;
  if (!paint || calm()) { return () => {}; }
  const color = tint(canvas);
  const bits = Array.from({ length: count || 0 },
                          () => ({ x: Math.random(), y: Math.random() }));
  const born = Date.now();
  let alive = true;
  const wipe = () => paint.clearRect(0, 0, canvas.width, canvas.height);
  const step = () => {
    if (!alive) { return; }
    const gone = Math.min(WHOLE, (Date.now() - born) / SPAN);
    wipe();
    if (color) { paint.fillStyle = color; }
    paint.globalAlpha = WHOLE - gone;
    for (const bit of bits) {
      paint.fillRect(bit.x * canvas.width, ((bit.y + gone) % WHOLE) * canvas.height,
                     SPECK, SPECK);
    }
    if (gone < WHOLE) { frame(step); return; }
    alive = false;
    wipe();
  };
  step();
  return () => {
    if (!alive) { return; }
    alive = false;
    wipe();
  };
}

export function countUp(from, to, ms, onStep) {
  if (calm()) {
    onStep(to);
    return () => {};
  }
  const born = Date.now();
  let alive = true;
  const step = () => {
    if (!alive) { return; }
    const gone = ms > 0 ? Math.min(WHOLE, (Date.now() - born) / ms) : WHOLE;
    onStep(Math.round(from + (to - from) * gone));
    if (gone < WHOLE) { frame(step); return; }
    alive = false;
  };
  step();
  return () => { alive = false; };
}

export function pace(value) {
  const written = String(value || "").trim();
  if (written.endsWith(MS)) {
    return Math.round(Number(written.slice(0, -MS.length)) || 0);
  }
  if (written.endsWith("s")) {
    return Math.round((Number(written.slice(0, -1)) || 0) * SECOND);
  }
  return 0;
}

export function pixels(value) {
  const written = String(value || "").trim();
  if (!written.endsWith(PX)) { return 0; }
  return Math.round(Number(written.slice(0, -PX.length)) || 0);
}

export function since(node, mark) {
  const kept = node && node.dataset;
  if (!kept) { return null; }
  const was = kept[MEMORY];
  kept[MEMORY] = String(mark);
  return was === undefined || was === String(mark) ? null : was;
}

function token(node, name) {
  const ask = globalThis.getComputedStyle;
  const look = typeof ask === "function" ? ask.call(globalThis, node) : null;
  return look ? look.getPropertyValue(name) : "";
}

export function span(node) {
  return pace(token(node, PACE));
}

export function reach(node) {
  return pixels(token(node, REACH));
}

export function grow(node) {
  if (!node) { return; }
  const to = Number(node.dataset.to) || 0;
  const was = since(node, to);
  if (was === null) { return; }
  countUp(Number(was) || 0, to, span(node), (value) => { node.textContent = String(value); });
}

export function pulse(node, ms) {
  const skin = node && node.classList;
  if (!skin) { return () => {}; }
  skin.add(PULSE);
  let alive = true;
  let timer = null;
  const stop = () => {
    if (!alive) { return; }
    alive = false;
    if (timer !== null && typeof globalThis.clearTimeout === "function") {
      globalThis.clearTimeout(timer);
    }
    skin.remove(PULSE);
  };
  if (typeof globalThis.setTimeout === "function") { timer = globalThis.setTimeout(stop, ms); }
  return stop;
}

export function throb(node, mark) {
  if (node && since(node, mark) !== null) { pulse(node, span(node)); }
}
