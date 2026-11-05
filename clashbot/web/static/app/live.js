const CLOSED = 2;
const SECOND = 1000;

export async function pull(path, signed) {
  let res = null;
  try {
    res = await fetch(path, { headers: { "X-Init-Data": signed } });
  } catch {
    return null;
  }
  return res.ok ? res.json() : null;
}

export function adopt(source, onState, onDown, grace, onUp) {
  let held = null;
  const late = () => {
    if (source.readyState !== CLOSED) { onDown(); }
  };
  const beat = () => {
    if (held !== null) { clearTimeout(held); }
    held = grace ? setTimeout(late, grace * SECOND) : null;
  };
  const alive = () => {
    if (onUp) { onUp(); }
    beat();
  };
  source.addEventListener("state", (event) => { alive(); onState(JSON.parse(event.data)); });
  source.addEventListener("ping", alive);
  source.addEventListener("open", alive);
  source.onerror = () => {
    if (source.readyState === CLOSED) { onDown(); }
  };
  if (source.readyState === CLOSED) { onDown(); return source; }
  beat();
  return source;
}

export function connect(path, signed, onState, onDown, grace, onUp) {
  return adopt(new EventSource(path + "?init=" + encodeURIComponent(signed)), onState, onDown,
               grace, onUp);
}
