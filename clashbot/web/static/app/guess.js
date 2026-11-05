import { isManager } from "./model.js";

function puts(found, changes) {
  return Object.assign({}, found || {}, changes);
}

function put(found, name, value) {
  return puts(found, { [name]: value });
}

function into(found, name, change) {
  return put(found, name, change(((found || {})[name]) || {}));
}

function rows(list, hit, change) {
  return (list || []).map((row) => (hit(row) ? change(row) : row));
}

function drop(list, hit) {
  return (list || []).filter((row) => !hit(row));
}

function war(change) {
  return (state) => into(state, "war_view", change);
}

function enemy(pos, change) {
  return war((view) => put(view, "enemy",
                           rows(view.enemy, (one) => one.pos === pos, change)));
}

function enemyPut(pos, name, value) {
  return enemy(pos, (one) => put(one, name, value));
}

export function warBook(row) {
  return (state) => {
    const name = ((state || {}).me_view || {}).name || "";
    const taken = war((view) => into(view, "mine",
                                     (seat) => put(seat, "target", { pos: row.pos, th: row.th,
                                                                     best: row.best })))(state);
    return enemyPut(row.pos, "assignee", name)(taken);
  };
}

export function warFree(pos) {
  return (state) => {
    const empty = war((view) => into(view, "mine",
                                     (seat) => put(seat, "target", null)))(state);
    return enemy(pos, (one) => puts(one, { assignee: null, note: null,
                                           swap_pending: false }))(empty);
  };
}

export function warClear() {
  return (state) => {
    const empty = war((view) => into(view, "mine",
                                     (seat) => put(seat, "target", null)))(state);
    return war((view) => put(view, "enemy",
                             rows(view.enemy, () => true,
                                  (one) => puts(one, { assignee: null, note: null,
                                                       swap_pending: false }))))(empty);
  };
}

export function warMirror() {
  return (state) => {
    const view = (state || {}).war_view || {};
    const seat = view.mine || {};
    const row = (view.enemy || []).find((one) => one.pos === seat.pos);
    return row ? warBook(row)(state) : state;
  };
}

export function warHand(pos, name) {
  return enemyPut(pos, "assignee", name);
}

export function warNote(pos, text) {
  return enemyPut(pos, "note", text);
}

export function warSwap(pos) {
  return enemyPut(pos, "swap_pending", true);
}

function lineup(tag, name, value) {
  return (state) => into(state, "cwl",
                         (found) => put(found, "lineup",
                                        rows(found.lineup, (one) => one.tag === tag,
                                             (one) => put(one, name, value))));
}

export function cwlSide(tag, on) {
  return lineup(tag, "in", on);
}

export function cwlPick(tag, on) {
  return lineup(tag, "picked", on);
}

export function cwlBonus(tag, on) {
  return lineup(tag, "bonus", on);
}

function me(change) {
  return (state) => into(state, "me_view", change);
}

export function meSet(name, value) {
  return me((view) => put(view, name, value));
}

export function meGoal(pick) {
  return me((view) => put(view, "goal",
                          Object.assign({}, view.goal || {},
                                        { kind: pick.kind, hero: pick.hero || null,
                                          target: pick.target })));
}

export function meProved(row) {
  return me((view) => Object.assign({}, view, {
    tag: view.tag || row.tag,
    verified: view.tag ? view.verified : true,
    villages: drop(view.villages, (one) => one.tag === row.tag)
      .concat([{ tag: row.tag, name: row.name || "", verified: true }]),
  }));
}

export function meVerified(tag) {
  return me((view) => Object.assign({}, view, {
    verified: true,
    villages: rows(view.villages, (one) => one.tag === tag, (one) => put(one, "verified", true)),
  }));
}

export function meDrop(tag) {
  return me((view) => {
    const left = drop(view.villages, (one) => one.tag === tag);
    return Object.assign({}, view, {
      tag: view.tag === tag ? (left[0] || {}).tag || "" : view.tag,
      villages: left,
    });
  });
}

export function meForget() {
  return me((view) => Object.assign({}, view, { tag: "", villages: [] }));
}

function todo(hit) {
  return (state) => put(state, "todo", drop((state || {}).todo, hit));
}

export function quizDone() {
  return todo((row) => row.kind === "quiz");
}

export function pollDone(poll) {
  return todo((row) => row.kind === "prediction" && String(row.poll) === String(poll));
}

export function duelDone(id) {
  return todo((row) => row.kind === "duel" && String(row.id) === String(id));
}

export function duelMade(name, metric) {
  return (state) => into(state, "more_view",
                         (view) => put(view, "duels",
                                       (view.duels || []).concat([{ rival: name,
                                                                    metric: metric }])));
}

export function baseProposed(row) {
  return (state) => (isManager(state)
    ? into(state, "bases", (found) => put(found, "clan", (found.clan || []).concat([row])))
    : state);
}

function tools(pack, change) {
  return (state) => into(state, "me",
                         (found) => into(found, "tools", (kit) => into(kit, pack, change)));
}

export function gateSet(on) {
  return tools("leaders", (found) => put(found, "gate", on));
}

export function noteSaved(tag, name, text) {
  return tools("leaders", (found) => {
    const left = drop(found.notes, (one) => one.tag === tag);
    return put(found, "notes",
               text ? left.concat([{ tag: tag, name: name, text: text }]) : left);
  });
}

export function warnVoid(id) {
  return tools("wars", (found) => put(found, "warnings",
                                      drop(found.warnings, (one) => one.id === id)));
}

function board(change) {
  return (state) => into(state, "manage_view", change);
}

export function seenSet(section, value) {
  return (state) => into(state, "views", (found) => put(found, section, value));
}

export function familyScore(on) {
  return (state) => into(state, "views", (found) => put(found, "family_score", on));
}

export function boardSet(name, value) {
  return board((view) => put(view, name, value));
}

export function textSaved(field, text) {
  return board((view) => into(view, "texts", (found) => put(found, field, text)));
}

export function schedAdd(row) {
  return board((view) => put(view, "schedules", (view.schedules || []).concat([row])));
}

export function schedDrop(id) {
  return board((view) => put(view, "schedules",
                             drop(view.schedules, (one) => String(one.id) === String(id))));
}

export function chanAdd(row) {
  return board((view) => put(view, "channels", (view.channels || []).concat([row])));
}

export function chanDrop(id) {
  return board((view) => put(view, "channels", drop(view.channels, (one) => one.id === id)));
}

export function seatBack(who) {
  return board((view) => put(view, "suspended",
                             drop(view.suspended, (one) => String(one.who) === String(who))));
}

export function undone(of, ref) {
  return board((view) => put(view, "log",
                             drop(view.log, (one) => one.of === of && one.ref === ref)));
}

function moved(who, from, to) {
  return board((view) => {
    const found = (view[from] || []).find((one) => String(one.who) === String(who));
    return Object.assign({}, view, {
      [from]: drop(view[from], (one) => String(one.who) === String(who)),
      [to]: found ? (view[to] || []).concat([found]) : view[to] || [],
    });
  });
}

export function delegateOn(who) {
  return moved(who, "people", "delegates");
}

export function delegateOff(who) {
  return moved(who, "delegates", "people");
}

export function delegatesOff() {
  return board((view) => Object.assign({}, view, {
    people: (view.people || []).concat(view.delegates || []),
    delegates: [],
  }));
}

function box(name, hit) {
  return (state) => into(state, "inbox", (found) => put(found, name, drop(found[name], hit)));
}

function same(who) {
  return (row) => String(row.who) === String(who);
}

export function personDone(who) {
  return box("pending", same(who));
}

export function personGone(who) {
  return board((view) => put(view, "approved", drop(view.approved, same(who))));
}

export function personTrust(who, on) {
  return board((view) => put(view, "approved",
                             rows(view.approved, same(who), (one) => put(one, "trusted", on))));
}

export function applyDone(id) {
  return box("applications", (row) => String(row.id) === String(id));
}

export function warnDone(tag) {
  return box("warnings", (row) => row.tag === tag);
}

export function baseDone(id) {
  return box("bases", (row) => String(row.id) === String(id));
}

export function minTh(th) {
  return board((view) => into(view, "recruit", (found) => put(found, "th", th)));
}

export function senderBlocked(row) {
  return (state) => board(
    (view) => into(view, "recruit",
                   (found) => put(found, "blocked", (found.blocked || []).concat([row]))))(
    box("applications", (one) => String(one.id) === String(row.id))(state));
}

export function senderFree(ref) {
  return board((view) => into(view, "recruit",
                              (found) => put(found, "blocked",
                                             drop(found.blocked,
                                                  (one) => String(one.id) === String(ref)))));
}

export function integSet(name, value) {
  return board((view) => into(view, "integrations", (found) => put(found, name, value)));
}
