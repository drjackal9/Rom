const MARK = "-v";
const SHARE_SINCE = "8.0";
const SHEET = ".sheet";
const CUT = "/";
const GONE = "";
const FRESH = 0;
const SECOND = 1000;

export const VERSION = "1";

function box(tg) {
  return (tg && tg.CloudStorage) || null;
}

function now() {
  return Math.floor(Date.now() / SECOND);
}

function keyed(key) {
  return key + MARK + VERSION;
}

function alive(value, clock) {
  const written = value === undefined || value === null ? GONE : String(value);
  const cut = written.indexOf(CUT);
  if (cut < 0) { return null; }
  const dies = Number(written.slice(0, cut)) || FRESH;
  return dies && dies <= clock ? null : written.slice(cut + 1);
}

function page() {
  const paper = globalThis.document;
  return paper ? paper.scrollingElement || paper.documentElement : null;
}

export function note(tg, text) {
  if (tg && tg.showAlert) {
    tg.showAlert(text);
  } else if (typeof alert === "function") {
    alert(text);
  }
}

export function app() {
  if (typeof window === "undefined") { return null; }
  return (window.Telegram && window.Telegram.WebApp) || null;
}

export function copy(link) {
  const board = typeof navigator === "undefined" ? null : navigator.clipboard;
  if (board && board.writeText) {
    const done = board.writeText(link);
    if (done && done.catch) { done.catch(() => note(app(), link)); }
    return true;
  }
  note(app(), link);
  return false;
}

export function buzz(tg, kind) {
  const haptic = tg && tg.HapticFeedback;
  if (!haptic) { return; }
  if (kind === "ok" || kind === "error" || kind === "warning") {
    haptic.notificationOccurred(kind === "ok" ? "success" : kind);
  } else {
    haptic.impactOccurred("light");
  }
}

export function mainButton(tg, label, onTap) {
  const button = tg && tg.MainButton;
  if (!button) { return () => {}; }
  button.setText(label);
  button.onClick(onTap);
  button.show();
  return () => {
    button.offClick(onTap);
    button.hide();
  };
}

export function backButton(tg, onTap) {
  const button = tg && tg.BackButton;
  if (!button) { return () => {}; }
  button.onClick(onTap);
  button.show();
  return () => {
    button.offClick(onTap);
    button.hide();
  };
}

function abile(tg, since) {
  return Boolean(tg && tg.isVersionAtLeast && tg.isVersionAtLeast(since));
}

export function shareMessage(tg, prepared) {
  if (tg && tg.shareMessage && abile(tg, SHARE_SINCE)) {
    tg.shareMessage(prepared);
  }
}

export function recall(tg, key, onValue) {
  const store = box(tg);
  if (!store || !store.getItem) { return; }
  store.getItem(keyed(key), (error, value) => {
    if (!error) { onValue(alive(value, now()) || GONE); }
  });
}

export function place(slug) {
  if (typeof history === "undefined" || !history.replaceState) { return; }
  try {
    history.replaceState(null, "", "/app/" + slug + location.hash);
  } catch {
    return;
  }
}

export function remember(tg, key, value, ttl) {
  const store = box(tg);
  if (!store || !store.setItem) { return; }
  const dies = ttl > 0 ? now() + ttl : FRESH;
  store.setItem(keyed(key), String(dies) + CUT + value);
}

function drop(store, keys) {
  if (keys.length) { store.removeItems(keys); }
}

function dying(store, keys) {
  if (!keys.length || !store.getItems) { return; }
  store.getItems(keys, (error, found) => {
    if (error) { return; }
    const clock = now();
    drop(store, keys.filter((key) => alive((found || {})[key], clock) === null));
  });
}

function keysOf(tg, onKeys) {
  const store = box(tg);
  if (!store || !store.getKeys || !store.removeItems) { return; }
  store.getKeys((error, keys) => {
    if (!error) { onKeys(store, Array.isArray(keys) ? keys : []); }
  });
}

export function sweep(tg, version) {
  const ours = (key) => String(key).endsWith(MARK + version);
  keysOf(tg, (store, keys) => {
    drop(store, keys.filter((key) => !ours(key)));
    dying(store, keys.filter(ours));
  });
}

export function forgetAll(tg, onGone) {
  keysOf(tg, (store, keys) => {
    drop(store, keys);
    onGone();
  });
}

export function top() {
  const paper = page();
  if (paper) { paper.scrollTop = 0; }
}

function covered(paper) {
  return Boolean(paper.querySelector && paper.querySelector(SHEET));
}

function finger(event) {
  const touch = ((event || {}).touches || [])[0] || {};
  return Number(touch.clientY) || 0;
}

export function pullDown(onPull, reach) {
  const paper = globalThis.document;
  if (!(reach > 0) || !paper || !paper.addEventListener) { return () => {}; }
  let from = null;
  const start = (event) => {
    const up = page();
    from = up && up.scrollTop <= 0 && !covered(paper) ? finger(event) : null;
  };
  const move = (event) => {
    if (from === null || finger(event) - from < reach) { return; }
    from = null;
    onPull();
  };
  paper.addEventListener("touchstart", start, { passive: true });
  paper.addEventListener("touchmove", move, { passive: true });
  return () => {
    paper.removeEventListener("touchstart", start);
    paper.removeEventListener("touchmove", move);
  };
}

export function jump(id) {
  if (typeof document === "undefined") { return; }
  const reach = () => {
    const found = document.getElementById(id);
    if (found && found.scrollIntoView) { found.scrollIntoView(); }
    return Boolean(found);
  };
  if (reach() || typeof globalThis.requestAnimationFrame !== "function") { return; }
  globalThis.requestAnimationFrame(reach);
}
