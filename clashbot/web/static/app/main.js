import { html, render, useEffect, useState } from "../vendor/htm-preact-standalone.module.js";
import { ASKED, FRESH, RECAP, TOASTED, useAsked, useBack, useClock, useLive, useMemory,
         usePreview, useRecap, useSend, useSignals } from "./hooks.js";
import { FIRST, firstTab, tabsFor } from "./model.js";
import { VERSION, mainButton, place, sweep, top } from "./native.js";
import { toastAct } from "./manage.js";
import { recapScreens } from "./recap.js";
import { views } from "./screens.js";
import { backTo, banner, clanSheet, head, primary, seen } from "./shell.js";
import { watchTheme } from "./theme.js";
import { Empty, Tabs, Toast } from "./ui.js";
import { wantsWhisper } from "./war.js";

const DRAFT = "text";
const TEXTS = "texts";
const SHEET = "sheet";
const CLANS = "clans";
const TAB = "tab";

const root = document.getElementById("app");
const words = JSON.parse(root.dataset.words);
const conf = JSON.parse(root.dataset.conf);
const tg = window.Telegram && window.Telegram.WebApp;
const known = root.dataset.slug;
const START = known || (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || "";

function signed() {
  return (tg && tg.initData) || "";
}

function pathsOf(slug) {
  const stem = "/app/" + slug;
  return { live: stem + "/live", state: stem + "/state", act: stem + "/act",
           preview: stem + "/preview", csv: stem + "/export.csv",
           json: stem + "/mydata.json" };
}

function dressOf(paths) {
  const firm = "?init=" + encodeURIComponent(signed());
  return Object.assign({}, conf, { MINE: { csv: paths.csv + firm, json: paths.json + firm } });
}

function hop(pick, setState, setSlug) {
  return (next) => {
    pick(SHEET, null);
    setState(null);
    setSlug(next);
    place(next);
  };
}

function fieldOf(local) {
  const sheet = local[SHEET] || null;
  return sheet && sheet.kind === TEXTS ? sheet.field : null;
}

function waitingScreen(down, retry) {
  return html`
    <${Empty} art=${down ? "offline" : "empty"} text=${down ? words.live_off : words.loading}
              action=${down ? words.live_retry : null} onAction=${retry} />`;
}

function App() {
  const [slug, setSlug] = useState(START);
  const [state, setState] = useState(null);
  const [tab, setTab] = useState(FIRST);
  const [down, setDown] = useState(false);
  const [again, setAgain] = useState(0);
  const [local, setLocal] = useState({});
  const pick = (name, value) => setLocal((old) => Object.assign({}, old, { [name]: value }));
  const now = useClock();
  const open = tabsFor(state, words);
  const wanted = local[TAB] || tab;
  const shown = open.some((one) => one.id === wanted) ? wanted : firstTab(state);
  const choose = (id) => {
    if (id === shown) { top(); return; }
    pick(TAB, null);
    setTab(id);
  };
  const paths = pathsOf(slug);
  const dress = dressOf(paths);
  const retry = () => setAgain((count) => count + 1);
  const backs = backTo(local, shown);
  useBack(tg, backs, () => (backs === SHEET ? pick(SHEET, null) : choose(FIRST)), retry);
  useSignals(tg, state, now, local, pick);
  useMemory(tg, conf, local, pick);
  usePreview(paths.preview, signed, fieldOf(local), local[DRAFT], pick);
  const season = state && state.recap ? state.recap.season : null;
  useRecap(tg, conf, season, local, pick);
  useLive(paths, signed, conf, slug, again, setState, setDown);
  const sent = useSend(paths.act, signed, conf, { tg, words, setState }, state, down);
  const party = Boolean(season) && local[RECAP] === FRESH;
  const view = views[shown] || views[FIRST];
  const wants = Boolean(state) && wantsWhisper(state);
  const asking = wants && !party && view === views[FIRST] && local[ASKED] === FRESH;
  useAsked(tg, conf, asking);
  const main = party ? null : primary(state, shown, down, words, dress, local);
  useEffect(() => {
    if (!main) { return undefined; }
    return mainButton(tg, main.label, () => sent.run(main.kind, main.extra, main.optimistic));
  }, [shown, down, main && main.label, main && main.kind]);
  if (!state) { return waitingScreen(down, retry); }
  const tools = { run: sent.fire, now, local, pick };
  if (party) { return recapScreens(state, words, dress, tools); }
  const toast = local[TOASTED] || null;
  const back = toastAct(state, toast);
  return html`
    ${head(state, () => pick(SHEET, { kind: CLANS }))}
    ${down ? banner(state, words, now, retry, sent.held) : seen(state, words, now, retry)}
    ${view(state, words, dress, tools)}
    ${(local[SHEET] || {}).kind === CLANS
      ? clanSheet(state, words, slug, hop(pick, setState, setSlug)) : null}
    ${toast ? html`
      <${Toast} text=${toast.text} action=${back ? words.manage_undo_now : null}
                onAction=${() => { pick(TOASTED, null); tools.run(back.kind, back.extra); }} />`
      : null}
    <${Tabs} tabs=${open} current=${shown} onPick=${choose} />`;
}

root.textContent = "";
if (tg) {
  watchTheme(tg, document.documentElement);
  sweep(tg, VERSION);
  if (tg.ready) { tg.ready(); }
  if (tg.expand) { tg.expand(); }
  if (tg.disableVerticalSwipes) { tg.disableVerticalSwipes(); }
  render(html`<${App} />`, root);
} else {
  render(html`<${Empty} art="empty" text=${words.denied} />`, root);
}
