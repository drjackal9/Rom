import { useEffect, useState } from "../vendor/htm-preact-standalone.module.js";
import { act, look, mark, refusal } from "./act.js";
import { adopt, connect, pull } from "./live.js";
import { BEAT, SPAN, reach } from "./fx.js";
import { applyEvent } from "./model.js";
import { backButton, buzz, note, pullDown, recall, remember, shareMessage } from "./native.js";
import { DONE } from "./recap.js";
import { drop, gate, hold, pump } from "./shell.js";
import { applyAccent } from "./theme.js";
import { lastHour, shotKey } from "./war.js";

export const ASKED = "whisper_asked";
export const FRESH = "";
export const RECAP = "recap";
export const TOASTED = "toast";
const SEEN = "seen_attack";
const PREVIEW = "preview";
const VILLAGE = "village";
const RECAP_KEY = "recap_";
const MARK = "1";
const OPENED = "app.opened";
const SECOND = 1000;

let waiting = window.clanboardBoot || null;
const sending = { busy: false };

export function useClock() {
  const [now, setNow] = useState(Math.floor(Date.now() / SECOND));
  useEffect(() => {
    const clock = setInterval(() => setNow(Math.floor(Date.now() / SECOND)), SECOND);
    return () => clearInterval(clock);
  }, []);
  return now;
}

export function useBack(tg, backs, onBack, retry) {
  useEffect(() => (backs ? backButton(tg, onBack) : undefined), [backs]);
  useEffect(() => pullDown(retry, reach(document.documentElement)), []);
}

export function useSignals(tg, state, now, local, pick) {
  const accent = state && state.clan ? state.clan.accent : null;
  const fight = (state && state.war_view) || null;
  const struck = fight ? shotKey(fight) : null;
  const urgent = Boolean(fight) && lastHour(fight, now);
  const toast = local[TOASTED] || null;
  const prepared = state && state.prepared;
  useEffect(() => applyAccent(accent, document.documentElement), [accent]);
  useEffect(() => {
    if (struck === null) { return undefined; }
    const held = setTimeout(() => pick(SEEN, struck), SPAN);
    return () => clearTimeout(held);
  }, [struck]);
  useEffect(() => {
    if (urgent) { buzz(tg, "warning"); }
  }, [urgent]);
  useEffect(() => {
    if (!toast) { return undefined; }
    const held = setTimeout(() => pick(TOASTED, null), SPAN);
    return () => clearTimeout(held);
  }, [toast]);
  useEffect(() => {
    if (prepared) { shareMessage(tg, prepared); }
  }, [prepared]);
}

export function useMemory(tg, conf, local, pick) {
  useEffect(() => { recall(tg, ASKED, (value) => pick(ASKED, value || FRESH)); }, []);
  useEffect(() => { recall(tg, VILLAGE, (value) => pick(VILLAGE, value || FRESH)); }, []);
  useEffect(() => {
    if (local[VILLAGE]) { remember(tg, VILLAGE, local[VILLAGE], conf.KEEP); }
  }, [local[VILLAGE]]);
}

export function useAsked(tg, conf, asking) {
  useEffect(() => {
    if (asking) { remember(tg, ASKED, MARK, conf.KEEP); }
  }, [asking]);
}

export function useRecap(tg, conf, season, local, pick) {
  useEffect(() => {
    if (season) { recall(tg, RECAP_KEY + season, (value) => pick(RECAP, value || FRESH)); }
  }, [season]);
  useEffect(() => {
    if (season && local[RECAP] === DONE) {
      remember(tg, RECAP_KEY + season, MARK, conf.KEEP);
    }
  }, [season, local[RECAP]]);
}

export function usePreview(path, signed, field, draft, pick) {
  useEffect(() => {
    if (!field) { return undefined; }
    let gone = false;
    const held = setTimeout(() => {
      look(path, signed(), field, draft).then((found) => {
        if (!gone) { pick(PREVIEW, found); }
      });
    }, draft === undefined ? 0 : BEAT);
    return () => { gone = true; clearTimeout(held); };
  }, [field, draft]);
}

function stream(paths, signed, conf, setState, setDown) {
  const started = waiting;
  waiting = null;
  let source = started ? started.source : null;
  let gone = false;
  const take = (found) => {
    setDown(false);
    setState((old) => applyEvent(old, found));
  };
  const fresh = async (given) => {
    const found = given ? await given : await pull(paths.state, signed());
    if (gone) { return; }
    setDown(!found);
    if (found) { setState((old) => applyEvent(old, found)); }
  };
  const wake = () => {
    if (!document.hidden) { fresh(null); }
  };
  const fell = () => {
    if (!gone) { setDown(true); }
  };
  const rose = () => {
    if (!gone) { setDown(false); }
  };
  fresh(started && started.state).then(() => {
    if (gone) { return; }
    if (started) {
      started.events.forEach(take);
      window.clanboardBoot = null;
      adopt(started.source, take, fell, conf.GRACE, rose);
    } else {
      source = connect(paths.live, signed(), take, fell, conf.GRACE, rose);
    }
  });
  document.addEventListener("visibilitychange", wake);
  return () => {
    gone = true;
    document.removeEventListener("visibilitychange", wake);
    if (source) { source.close(); }
  };
}

export function useLive(paths, signed, conf, slug, again, setState, setDown) {
  useEffect(() => {
    if (slug) { act(paths.act, signed(), OPENED); }
  }, [slug]);
  useEffect(() => stream(paths, signed, conf, setState, setDown), [slug, again]);
}

export function useSend(path, signed, conf, kit, state, down) {
  const [waited, setWaited] = useState([]);
  const run = async (kind, extra, optimistic, id) => {
    const before = state;
    if (optimistic) { kit.setState(optimistic(before)); }
    buzz(kit.tg, "tap");
    const done = await act(path, signed(), kind, extra, id);
    if (done.ok) {
      kit.setState((old) => applyEvent(old, done.state));
      if (done.state && done.state.pending) {
        buzz(kit.tg, "warning");
        note(kit.tg, kit.words.queued);
        return false;
      }
      buzz(kit.tg, "ok");
      return true;
    }
    kit.setState(before);
    buzz(kit.tg, "error");
    note(kit.tg, refusal(kit.words, done.error));
    return false;
  };
  const park = (kind, extra) => {
    setWaited((rows) => hold(rows, conf.MARKS, { kind, extra, id: mark() }));
    buzz(kit.tg, "tap");
    return false;
  };
  useEffect(() => pump(sending, down, waited,
                       (one) => run(one.kind, one.extra, null, one.id),
                       (sent) => setWaited((rows) => drop(rows, sent))),
            [down, waited.length]);
  return { run: run, fire: gate(down, run, park), held: waited.length };
}
