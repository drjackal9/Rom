export const TABS = ["war", "clan", "me", "more"];
const LEVELS = ["outsider", "reduced", "full", "manager"];
const TAB_LEVEL = { war: "full", clan: "outsider", me: "outsider", more: "reduced" };
export const MANAGE = "manage";
const LEADERS = "leaders";
export const FIRST = TABS[0];
export const DAY = 86400;
export const HOUR = 3600;
const MINUTE = 60;

export function phaseOf(war, now) {
  if (!war || !war.state || war.state === "notInWar") { return "none"; }
  if (war.state === "preparation") { return "preparation"; }
  if (war.state === "inWar") { return war.end && war.end <= now ? "warEnded" : "inWar"; }
  return war.state;
}

export function countdown(end, now) {
  const left = Math.max(0, Math.floor(end - now));
  return { d: Math.floor(left / DAY), h: Math.floor((left % DAY) / HOUR),
           m: Math.floor((left % HOUR) / MINUTE), s: left % MINUTE };
}

export function fill(text, name, value) {
  const raw = String(text === null || text === undefined ? "" : text);
  return raw.replace("{" + name + "}", String(value));
}

export function score(words, result, us, them) {
  return fill(fill(fill(words.war_score, "result", result), "stars", us),
              "opp_stars", them).trim();
}

export function percent(words, value) {
  return fill(words.war_destr, "destr", Math.round(Number(value) || 0));
}

export function label(text) {
  return fill(text, "n", "").trim();
}

export function isManager(state) {
  const me = (state && state.me) || null;
  return Boolean(me && (me.level || me[MANAGE] || me.tools));
}

export function isLeader(state) {
  return Boolean((((state || {}).me || {}).tools || {})[LEADERS]);
}

export function pendingOf(state) {
  const box = (state && state.inbox) || {};
  return Object.values(box).reduce((sum, rows) => sum + (Array.isArray(rows) ? rows.length : 0), 0);
}

function levelOf(state) {
  const found = ((state || {}).level) || "";
  return LEVELS.indexOf(found) < 0 ? LEVELS[0] : found;
}

export function atLeast(state, level) {
  return LEVELS.indexOf(levelOf(state)) >= LEVELS.indexOf(level);
}

function openTabs(state) {
  const mine = LEVELS.indexOf(levelOf(state));
  return TABS.filter((id) => LEVELS.indexOf(TAB_LEVEL[id]) <= mine);
}

export function firstTab(state) {
  return openTabs(state)[0] || FIRST;
}

export function tabsFor(state, words) {
  const tabs = openTabs(state).map((id) => ({ id: id, label: words["tab_" + id] }));
  if (isManager(state)) {
    tabs.push({ id: MANAGE, label: words.tab_manage, badge: pendingOf(state) });
  }
  return tabs;
}

export function applyEvent(state, event) {
  if (!event || typeof event !== "object") { return state; }
  return event;
}
