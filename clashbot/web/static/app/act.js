const MARK_BASE = 36;
const MARK_FROM = 2;
const MARK_TO = 10;

export function mark(random) {
  return (random === undefined ? Math.random() : random).toString(MARK_BASE).slice(MARK_FROM, MARK_TO);
}

export async function act(path, signed, kind, extra, id) {
  const body = Object.assign({ kind: kind, id: id || mark() }, extra || {});
  let res = null;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "X-Init-Data": signed, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, error: "net" };
  }
  if (res.ok) {
    return { ok: true, state: await res.json() };
  }
  const found = await res.json().catch(() => null);
  return { ok: false, error: (found && found.error) || String(res.status) };
}

export function refusal(words, error) {
  return words["denied_" + (error || "")] || words.denied;
}

export async function look(path, signed, kind, text) {
  const ask = path + "?kind=" + encodeURIComponent(kind)
    + (text === undefined ? "" : "&text=" + encodeURIComponent(text));
  let res = null;
  try {
    res = await fetch(ask, { headers: { "X-Init-Data": signed } });
  } catch {
    return "";
  }
  if (!res.ok) {
    return "";
  }
  const found = await res.json().catch(() => null);
  return (found && found.text) || "";
}
