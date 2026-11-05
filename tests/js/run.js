import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { FIRST, applyEvent, atLeast, countdown, fill, firstTab, label, pendingOf,
  phaseOf, tabsFor } from
  "../../clashbot/web/static/app/model.js";
import { primaries, views } from "../../clashbot/web/static/app/screens.js";
import { toastAct } from "../../clashbot/web/static/app/manage.js";
import { act, look, mark, refusal } from "../../clashbot/web/static/app/act.js";
import { adopt } from "../../clashbot/web/static/app/live.js";
import { Bars, Line, scale } from "../../clashbot/web/static/app/charts.js";
import { Bar, Big, Card, Chip, Chips, Empty, Grid, Ring, Sheet, Stars, Strip, Switch, Tabs, Tile,
         Toast } from "../../clashbot/web/static/app/ui.js";
import { backTo, banner, clanSheet, drop, flush, gate, head, hold, keyOf, primary, pump,
         seen as freshRow } from "../../clashbot/web/static/app/shell.js";
import { chosen as chosenVillage, shown as villageView } from
  "../../clashbot/web/static/app/me_link.js";
import { DONE, recapScreens } from "../../clashbot/web/static/app/recap.js";
import { spot } from "../../clashbot/web/static/app/war_tiles.js";
import { shotKey } from "../../clashbot/web/static/app/war.js";
import { VERSION, copy, forgetAll, jump, pullDown, recall, remember, shareMessage, sweep,
         top } from "../../clashbot/web/static/app/native.js";
import { icon, illustration, initials } from "../../clashbot/web/static/app/art.js";
import { away, climbTiles, peopleGrid } from "../../clashbot/web/static/app/clan_tiles.js";
import { ago, chronicle } from "../../clashbot/web/static/app/chronicle.js";
import { confetti, countUp, grow, pace, pixels, pulse, reach, since, span, throb } from
  "../../clashbot/web/static/app/fx.js";
import { every, find, text } from "./tree.js";

const state = JSON.parse(readFileSync(new URL("./state.json", import.meta.url), "utf8"));
const words = new Proxy({}, { get: (_, key) => "[" + String(key) + "]" });
const MOST = 3;
const conf = { STAFF: "staff", SHEETS: ["wars", "members"], FULL: MOST, SIDES: ["in", "out"],
               NOTE_MAX: 400, TOKEN_MAX: 32,
               AVAIL: ["in", "maybe", "out"], SWITCH: ["on", "off"], SURE: "yes",
               MEDALS: { th: "🏯", quiz: "🧠", bingo: "🎲" },
               LANGS: [{ code: "en", name: "English" }, { code: "it", name: "Italiano" }],
               AREAS: ["settings", "wars", "cwl", "leaders", "recruitment", "family",
                       "integrations", "staff"],
               MANAGE: ["wars", "cwl", "leaders", "recruitment", "family", "integrations"],
               METRICS: ["loot", "war_stars"], DURATIONS: ["raid", "week", "season"],
               GUESS_STARS: [0, 1, 2, 3],
               GUESS_PERCENTS: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
               DECIDED: ["accepted", "rejected"], WAR_FROM: ["now", "next"],
               SECTIONS: ["plans", "bases", "league", "numbers"],
               SEEN_BY: ["approved", "in_war", "managers"],
               WEEKDAYS: ["0", "1", "2", "3", "4", "5", "6"], TEXT_MAX: 1000,
               IDLE_MIN_DAYS: 3, LABELS: ["war", "farm", "hybrid", "trophy", "cwl"],
               REASONS: ["spam", "scam", "harassment", "impersonation", "other_no_text"],
               MINE: { csv: "/app/abc/export.csv?init=firma",
                       json: "/app/abc/mydata.json?init=firma" },
               THUMB: "https://i.ytimg.com/vi/", THUMB_SIZE: "/mqdefault.jpg" };
const said = new Proxy({ pos: "#{pos}", th: "TH{th}", target_th: "{target} · TH{th}",
                         name_count: "{name} ·{n}" },
                       { get: (base, key) => (key in base ? base[key] : "[" + String(key) + "]") });
const GLYPHS = /[★☆⭐]/u;
const DOTS = /·/u;
const failed = [];

function check(name, ok) {
  if (!ok) { failed.push(name); }
}

check("phase none", phaseOf(null, 0) === "none");
check("phase notInWar", phaseOf({ state: "notInWar" }, 0) === "none");
check("phase preparation", phaseOf({ state: "preparation", end: 100 }, 50) === "preparation");
check("phase inWar", phaseOf({ state: "inWar", end: 100 }, 50) === "inWar");
check("phase ended", phaseOf({ state: "inWar", end: 100 }, 150) === "warEnded");

const left = countdown(3725, 0);
check("countdown", left.d === 0 && left.h === 1 && left.m === 2 && left.s === 5);
check("countdown past", countdown(10, 99).s === 0);

check("tabs member", tabsFor({ level: "full", me: {} }, words)
                     .map((one) => one.id).join() === "war,clan,me,more");
check("tabs manager", tabsFor({ me: { level: "chief" }, inbox: { links: [1, 2] } },
                              words).pop().badge === 2);
check("tabs manager id", tabsFor({ me: { level: "chief" } }, words).pop().id === "manage");
const idsOf = (state) => tabsFor(state, words).map((one) => one.id).join();
check("tabs estraneo", idsOf({ level: "outsider", me: {} }) === "clan,me");
check("tabs ridotta", idsOf({ level: "reduced", me: {} }) === "clan,me,more");
check("tabs piena", idsOf({ level: "full", me: {} }) === "war,clan,me,more");
check("tabs gestore", idsOf({ level: "manager", me: { level: "chief" } })
      === "war,clan,me,more,manage");
check("prima scheda estraneo", firstTab({ level: "outsider" }) === "clan");
check("prima scheda piena", firstTab({ level: "full" }) === "war");
check("prima scheda senza livello", firstTab({}) === "clan");
check("prima scheda senza stato", firstTab(null) === "clan");
check("almeno piena da ridotta", atLeast({ level: "reduced" }, "full") === false);
check("almeno piena da piena", atLeast({ level: "full" }, "full") === true);
check("almeno piena da gestore", atLeast({ level: "manager" }, "full") === true);
check("almeno senza livello", atLeast({}, "full") === false);
check("almeno senza stato", atLeast(null, "full") === false);
check("un livello sconosciuto non apre niente",
      atLeast({ level: "sconosciuto" }, "reduced") === false);
check("senza stato le schede sono quelle dell'estraneo", idsOf(null) === "clan,me");
check("con un livello sconosciuto le schede sono quelle dell'estraneo",
      idsOf({ level: "sconosciuto", me: {} }) === "clan,me");
check("pending", pendingOf({ inbox: { a: [1], b: [1, 1] } }) === 3);
check("pending empty", pendingOf({}) === 0);
check("apply", applyEvent({ a: 1 }, { b: 2 }).b === 2);
check("apply nothing", applyEvent({ a: 1 }, null).a === 1);
check("fill", fill("#{pos}", "pos", 7) === "#7");
check("fill leaves the rest", fill("{a} {b}", "a", 1) === "1 {b}");
check("fill nothing", fill(null, "pos", 7) === "");
check("label", label("{n} stelle") === "stelle");

function tools(extra) {
  return Object.assign({ run: async () => true, now: 0, local: {}, pick() {} }, extra);
}

for (const name of Object.keys(views)) {
  try {
    const out = text(views[name](state, words, conf, tools({})));
    check("view " + name + " renders", typeof out === "string");
  } catch (error) {
    failed.push("view " + name + " throws: " + error.message);
  }
}

const view = state.war_view;
const warTree = views.war(state, words, conf, tools({ now: view.end - 100 }));
check("war shows both sides", text(warTree).includes(view.us.name)
                              && text(warTree).includes(view.them.name));
check("war shows free targets as chips",
      find(find(warTree, "chips")[0], "chip").length === view.free.length);
check("war lists who is missing", find(warTree, "missing").length === 1);
check("chi manca sta nella tessera con le iniziali e il numero, non col nome",
      (() => {
        const said_tree = views.war(state, said, conf, tools({ now: view.end - 100 }));
        const tiles = find(find(said_tree, "missing")[0], "tile");
        const row = view.missing[0];
        return tiles.length === view.missing.length
               && text(tiles[0]).includes(String(row.left))
               && text(tiles[0]).includes(initials(row.name))
               && !text(tiles[0]).includes(row.name);
      })());
const enemyCard = find(warTree, "enemy")[0];
check("la griglia ha una tessera per ogni base nemica",
      find(enemyCard, "tile").length === view.enemy.length);
check("la griglia nemica sta su tre colonne",
      find(enemyCard, "grid")[0].props.style === "--cols:3");
check("la scheda Guerra non porta nessuna riga", find(warTree, "row").length === 0);
check("i miei attacchi sono tessere col numero grande",
      (() => {
        const tiles = find(find(warTree, "attacks")[0], "tile");
        return tiles.length === 2 && text(tiles[0]).includes(String(view.mine.used))
               && text(tiles[1]).includes("[war_target]");
      })());
check("the enemy list carries its own tone", find(warTree, "enemy").length === 1);
check("war shows my share", find(warTree, "bar").length === 1);
check("war draws the stars in svg", find(warTree, "star").length === MOST * view.enemy.length);
check("war fills the stars taken", find(warTree, "on").length ===
                                   view.enemy.reduce((sum, one) => sum + one.best, 0));
check("war keeps no glyph in the text", !GLYPHS.test(text(warTree)));
check("war numbers the targets from the words",
      text(views.war(state, said, conf, tools({}))).includes("#1"));

const booked = Object.assign({}, state, { war_view: Object.assign({}, view, {
  mine: Object.assign({}, view.mine, { target: { pos: view.enemy[0].pos, th: view.enemy[0].th,
                                                 best: view.enemy[0].best } }) }) });
const bookedWar = find(views.war(booked, words, conf, tools({})), "chips")[0];
check("col bersaglio preso i chip liberi sono spenti e resta solo liberare",
      find(bookedWar, "chip").filter((one) => one.props.disabled).length === view.free.length
      && find(bookedWar, "chip").filter((one) => !one.props.disabled).length === 1
      && text(find(bookedWar, "chip")[0]) === "[war_release]");
check("senza bersaglio i chip liberi restano vivi",
      find(find(warTree, "chips")[0], "chip").every((one) => !one.props.disabled));

const wiped = [];
const clearChip = chipOf(views.war(booked, words, conf,
                                   tools({ run: async (kind, extra) => {
                                     wiped.push([kind, extra]);
                                   } })), "war_clear");
check("col piano prenotato chi guida puo azzerarlo", Boolean(clearChip));
if (clearChip) { clearChip.props.onClick(); }
check("azzerare il piano non porta nessun campo",
      wiped.length === 1 && wiped[0][0] === "target.clear"
      && Object.keys(wiped[0][1]).join() === "");
const plainWar = views.war(Object.assign({}, booked, { me: { tag: "#P4", name: "Toad" } }),
                           words, conf, tools({}));
check("chi non guida il clan non azzera il piano",
      chipOf(plainWar, "war_clear") === undefined);
const freePlan = Object.assign({}, state, { war_view: Object.assign({}, view, {
  enemy: view.enemy.map((one) => Object.assign({}, one, { assignee: null })) }) });
check("col piano gia vuoto non c'e niente da azzerare",
      chipOf(views.war(freePlan, words, conf, tools({})), "war_clear") === undefined);

const enemyTiles = (tree) => find(find(tree, "enemy")[0], "tile");
check("la tessera della mia base porta il tono mio",
      String(enemyTiles(views.war(booked, words, conf, tools({})))[0].props.class)
        .includes("mine"));
check("la tessera di un compagno porta il tono suo",
      String(enemyTiles(warTree)[0].props.class).includes("mate"));
check("la tessera libera resta libera",
      String(enemyTiles(warTree)[view.free[0].pos - 1].props.class).includes("free"));
check("la tessera nemica si illumina quando cambia",
      enemyTiles(warTree).every((one) => typeof one.ref === "function"));

const swapAsked = Object.assign({}, state, { war_view: Object.assign({}, view, {
  enemy: [Object.assign({}, view.enemy[0], { swap_pending: true })].concat(view.enemy.slice(1))
}) });
check("il cambio chiesto si vede sulla tessera",
      find(views.war(swapAsked, words, conf, tools({})), "dot").length === 1);

const opened_base = [];
enemyTiles(views.war(state, words, conf,
                     tools({ pick: (name, value) => opened_base.push([name, value]) })))[0]
  .props.onClick();
check("toccare la tessera apre il foglio della base",
      opened_base[0][0] === "sheet" && opened_base[0][1].kind === "base"
      && opened_base[0][1].pos === view.enemy[0].pos);

const onBase = { sheet: { kind: "base", pos: view.enemy[0].pos } };
const basePaper = find(views.war(state, words, conf, tools({ local: onBase })), "sheet")[0];
check("il foglio della base dice chi ha attaccato e con quante stelle",
      text(basePaper).includes(view.enemy[0].history[0].name)
      && find(basePaper, "star").length === MOST * view.enemy[0].history.length);
check("il foglio della base porta il consiglio del municipio",
      text(basePaper).includes(String(state.advice[String(view.enemy[0].th)].avg_stars))
      && text(basePaper).includes(state.advice[String(view.enemy[0].th)].best[0].name));
check("il foglio della base porta il video del municipio",
      text(basePaper).includes(state.attack_videos[String(view.enemy[0].th)][0].title));
check("il foglio della base nomina la base col numero e il municipio",
      text(find(views.war(state, said, conf, tools({ local: onBase })), "sheet")[0])
        .includes(spot(said, view.enemy[0].pos, view.enemy[0].th)));
check("il piano scritto arriva nella casella",
      find(basePaper, "note")[0].props.value === view.enemy[0].note
      && Number(find(basePaper, "note")[0].props.maxlength) === conf.TEXT_MAX);

const moved = [];
const onMove = tools({ local: onBase,
                       run: async (kind, extra) => { moved.push([kind, extra]); } });
const mateSheet = find(views.war(state, words, conf, onMove), "sheet")[0];
chipOf(mateSheet, "war_swap").props.onClick();
chipOf(mateSheet, "manage_save").props.onClick();
check("chiedere il cambio parte dal foglio della base",
      moved[0][0] === "target.swap" && moved[0][1].pos === String(view.enemy[0].pos)
      && Object.keys(moved[0][1]).join() === "pos");
check("il piano scritto si salva sulla prenotazione",
      moved[1][0] === "target.note" && moved[1][1].pos === String(view.enemy[0].pos)
      && moved[1][1].text === view.enemy[0].note);
check("sulla base di un compagno non si prenota",
      chipOf(mateSheet, "war_book") === undefined
      && chipOf(mateSheet, "war_release") === undefined);

const onFree = { sheet: { kind: "base", pos: view.free[0].pos } };
const taking = [];
const freeSheet = find(views.war(state, words, conf,
                                 tools({ local: onFree,
                                         run: async (kind, extra) => {
                                           taking.push([kind, extra]);
                                         } })), "sheet")[0];
chipOf(freeSheet, "war_book").props.onClick();
check("prenotare la base libera parte dal foglio",
      taking[0][0] === "target.set" && taking[0][1].pos === String(view.free[0].pos)
      && taking[0][1].who === String(view.mine.pos));
check("sulla base libera non si chiede il cambio",
      chipOf(freeSheet, "war_swap") === undefined);

function sheetOf(row) {
  return find(views.war(Object.assign({}, state, {
    war_view: Object.assign({}, view, { enemy: [row] }) }), words, conf,
    tools({ local: { sheet: { kind: "base", pos: row.pos } } })), "sheet")[0];
}

const spareBase = Object.assign({}, view.enemy[0], { assignee: null, best: MOST - 1 });
check("su una base gia a tre stelle non si prenota",
      chipOf(sheetOf(spareBase), "war_book") !== undefined
      && chipOf(sheetOf(Object.assign({}, spareBase, { best: MOST })),
                "war_book") === undefined);

const onMineSheet = { sheet: { kind: "base", pos: view.enemy[0].pos } };
const leaving = [];
const mineSheet = find(views.war(booked, words, conf,
                                 tools({ local: onMineSheet,
                                         run: async (kind, extra) => {
                                           leaving.push([kind, extra]);
                                         } })), "sheet")[0];
chipOf(mineSheet, "war_release").props.onClick();
check("la mia base si libera dal foglio",
      leaving[0][0] === "target.free" && leaving[0][1].pos === String(view.enemy[0].pos));

const prep = Object.assign({}, state, {
  war_view: Object.assign({}, view, { phase: "preparation" }) });
const handed = [];
const prepSheet = find(views.war(prep, words, conf,
                                 tools({ local: onBase,
                                         run: async (kind, extra) => {
                                           handed.push([kind, extra]);
                                         } })), "sheet")[0];
const tendina = find(prepSheet, "field")[0];
check("in preparazione il gestore ha la tendina dei compagni",
      Boolean(tendina) && state.ours.every((one) => text(tendina).includes(one.name)));
tendina.props.onChange({ target: { value: String(state.ours[2].pos) } });
check("la tendina assegna la base al compagno scelto",
      handed[0][0] === "target.set" && handed[0][1].pos === String(view.enemy[0].pos)
      && handed[0][1].who === String(state.ours[2].pos));
const plainPrep = Object.assign({}, prep, { me: { tag: "#P4", name: "Toad" } });
check("in guerra e senza gestione la tendina non c'e",
      find(find(views.war(plainPrep, words, conf, tools({ local: onBase })), "sheet")[0],
           "field").length === 0
      && find(basePaper, "field").length === 0);

const mirror = Object.assign({}, state, { war_view: Object.assign({}, view, {
  free: [{ pos: view.mine.pos, th: view.mine.th, best: 0 }].concat(view.free) }) });
check("the mirror stands out among the free targets",
      find(find(views.war(mirror, words, conf, tools({})), "chips")[0], "on").length === 1);

const taps = [];
const booking = views.war(state, words, conf,
                          tools({ run: async (kind, extra) => { taps.push([kind, extra]); } }));
find(booking, "chip")[0].props.onClick();
check("a chip books the target", taps[0][0] === "target.set"
                                 && taps[0][1].pos === String(view.free[0].pos)
                                 && taps[0][1].who === String(view.mine.pos));

const hit = view.mine.last_attack;
const shotCard = find(warTree, "shot")[0];
check("dopo l'attacco la card del risultato porta stelle e percentuale",
      Boolean(shotCard) && text(shotCard).includes(String(hit.stars))
      && Number(find(shotCard, "sub")[0].props["data-to"]) === Math.round(hit.destr));
const marked = { seen_attack: shotKey(view) };
check("la card del risultato se ne va quando l'attacco e gia visto",
      find(views.war(state, words, conf, tools({ local: marked })), "shot").length === 0);
check("il segno del colpo visto tiene dentro la guerra",
      shotKey(view) !== shotKey(Object.assign({}, view, { start: view.end })));
check("senza colpo non c'e segno", shotKey(Object.assign({}, view, { mine: null })) === null);
const nextWar = Object.assign({}, state, { war_view: Object.assign({}, view, {
  start: view.end }) });
check("la guerra dopo mostra il risultato anche con lo stesso numero di colpo",
      find(views.war(nextWar, words, conf, tools({ local: marked })), "shot").length === 1);
const tripled = Object.assign({}, state, { war_view: Object.assign({}, view, {
  mine: Object.assign({}, view.mine, {
    last_attack: Object.assign({}, hit, { stars: conf.FULL, destr: 100 }) }) }) });
check("i coriandoli escono solo sul tre stelle",
      find(views.war(tripled, words, conf, tools({})), "fx").length === 1
      && find(shotCard, "fx").length === 0);

check("nell'ultima ora il tempo si accende", find(warTree, "urgent").length === 1);
check("con tempo davanti il tempo resta calmo",
      find(views.war(state, words, conf, tools({ now: view.end - 7200 })), "urgent").length === 0);
const spent = Object.assign({}, state, { war_view: Object.assign({}, view, {
  mine: Object.assign({}, view.mine, { left: 0 }) }) });
check("chi non ha piu attacchi non vede il tempo acceso",
      find(views.war(spent, words, conf, tools({ now: view.end - 100 })), "urgent").length === 0);

const over = Object.assign({}, state, { war_view: Object.assign({}, view, {
  phase: "warEnded",
  ended: { result: "win", best: { pos: 1, name: "Mario", stars: 3, destr: 100 } } }) });
const overCard = find(views.war(over, words, conf, tools({ now: view.end + 100 })), "end")[0];
check("a guerra finita la card di fine porta esito, miglior attacco e la mia prestazione",
      Boolean(overCard) && text(overCard).includes("[war_win]")
      && text(overCard).includes("Mario") && text(overCard).includes("[war_top]")
      && text(overCard).includes("[war_yours]") && find(overCard, "tile").length === 4);
check("la card di fine prende il posto del tabellone",
      find(views.war(over, words, conf, tools({ now: view.end + 100 })), "match").length === 0
      && find(warTree, "match").length === 1);
check("a guerra aperta la card di fine non c'e", find(warTree, "end").length === 0);
check("a guerra finita la card del risultato non si ripete",
      find(views.war(over, words, conf, tools({ now: view.end + 100 })), "shot").length === 0
      && find(warTree, "shot").length === 1);

const heroMatch = find(warTree, "match")[0];
const heroScores = find(heroMatch, "big-value");
check("il tabellone e la card eroe con la striscia dell'accento",
      String(heroMatch.props.class).includes("hero")
      && String(heroMatch.props.class).includes("stripe"));
check("i due punteggi del tabellone sono numeri eroe",
      find(heroMatch, "big").length === 2
      && find(heroMatch, "big").every((one) => String(one.props.class).includes("hero")));
check("i punteggi salgono col contatore quando il tabellone cambia",
      heroScores.length === 2
      && Number(heroScores[0].props["data-to"]) === view.us.stars
      && Number(heroScores[1].props["data-to"]) === view.them.stars
      && heroScores.every((one) => typeof one.ref === "function"));
check("in battaglia il tempo e il chip in corso e batte quando il punteggio cambia",
      find(heroMatch, "live").length === 1
      && typeof find(heroMatch, "timer")[0].ref === "function");
check("in preparazione nessun chip in corso",
      find(find(views.war(prep, words, conf, tools({ now: view.start - 100 })), "match")[0],
           "live").length === 0);
check("la scheda Guerra tiene un solo tabellone", find(warTree, "score-row").length === 1);
check("la card di fine guerra prende la forma della card eroe",
      String(overCard.props.class).includes("hero")
      && String(overCard.props.class).includes("stripe")
      && find(overCard, "live").length === 0);
check("la scheda Guerra non alza nessuna parola", !/\p{Lu}{3,}/u.test(text(warTree)));
const cards = find(warTree, "card").map((one) => String(one.props.class).split(" "));
const seat = (name) => cards.findIndex((one) => one.includes(name));
check("in Guerra l'ordine e tabellone, il tuo colpo, i miei attacchi, chi manca, griglia nemica",
      seat("match") === 0 && seat("shot") === 1 && seat("attacks") === 2
      && seat("missing") === 3 && seat("enemy") === 4);

const warShared = [];
const overShare = find(views.war(over, words, conf, tools({
  now: view.end + 100,
  run: async (kind, extra) => { warShared.push([kind, extra]); return true; },
})), "end")[0];
chipOf(overShare, "[war_share]").props.onClick();
check("la card di fine guerra si condivide come immagine",
      warShared.length === 1 && warShared[0][0] === "share.war");

const homeless = Object.assign({}, state, {
  me_view: Object.assign({}, state.me_view, { tag: null }) });
const called = [];
const bandTree = views.war(homeless, words, conf,
                           tools({ now: view.end - 7200,
                                   pick: (name, value) => called.push([name, value]) }));
check("senza villaggio la striscia invita a collegarlo", find(bandTree, "strip").length === 1);
find(bandTree, "strip-do")[0].props.onClick();
check("la striscia del villaggio porta alla scheda Io",
      called[0][0] === "tab" && called[0][1] === "me");
check("con il villaggio collegato la striscia non c'e", find(warTree, "strip").length === 0);

const wanted = [];
const askTree = views.war(state, words, conf,
                          tools({ now: view.end - 7200, local: { whisper_asked: "" },
                                  run: async (kind, extra) => { wanted.push([kind, extra]); } }));
check("il sussurro si chiede una volta sola",
      find(askTree, "strip").length === 1
      && find(views.war(state, words, conf, tools({ local: { whisper_asked: "1" } })),
              "strip").length === 0);
find(askTree, "strip-do")[0].props.onClick();
check("dire di si accende il sussurro",
      wanted[0][0] === "link.whisper" && wanted[0][1].village === state.me_view.tag
      && wanted[0][1].on === conf.SWITCH[0]);
check("a chi ha gia il sussurro non si chiede niente",
      find(views.war(Object.assign({}, state, {
        me_view: Object.assign({}, state.me_view, { whisper: true }) }), words, conf,
        tools({ local: { whisper_asked: "" } })), "strip").length === 0);

const noWar = Object.assign({}, state, {
  war_view: null, next: { key: "raid", start: 100, end: 200, state: "upcoming" },
  last_war: { them: "Clan Nemico", us_stars: 3, them_stars: 1, result: "win" },
  todo: [{ kind: "link" }] });
const picks = [];
const quiet = views.war(noWar, words, conf,
                        tools({ now: 40, pick: (name, value) => picks.push([name, value]) }));
check("without a war the next event and the todo list appear",
      find(quiet, "next").length === 1 && find(quiet, "todo").length === 1);
check("without a war the last war is there", text(quiet).includes(noWar.last_war.them));
check("senza guerra l'ultima guerra e un tabellone, non una riga",
      find(quiet, "row").length === 0 && find(quiet, "score-row").length === 1
      && text(find(quiet, "score-row")[0]).includes(String(noWar.last_war.us_stars)));
find(quiet, "chip")[0].props.onClick();
check("the village to link leads to the Me tab", picks[0][0] === "tab" && picks[0][1] === "me");

const quizWait = { kind: "quiz", question: "Q?", options: ["a", "b"] };
const waiting = Object.assign({}, noWar,
                              { todo: [quizWait, { kind: "duel", id: "ab12", rival: "#P2" }] });
const opened = [];
const started = [];
const games = views.war(waiting, words, conf,
                        tools({ now: 40, pick: (name, value) => opened.push([name, value]),
                                run: async (kind, extra) => { started.push([kind, extra]); } }));
find(games, "chip")[0].props.onClick();
find(games, "chip")[1].props.onClick();
check("the quiz opens a sheet", opened[0][0] === "sheet" && opened[0][1].kind === "quiz");
check("the duel is taken from the list",
      started[0][0] === "duel.accept" && started[0][1].duel === "ab12");
const answers = [];
const sheet = views.war(waiting, words, conf,
                        tools({ now: 40, local: { sheet: quizWait },
                                run: async (kind, extra) => { answers.push([kind, extra]); } }));
check("the sheet shows the options", find(sheet, "chip").length === quizWait.options.length);
check("the sheet shows the question", text(sheet).includes(quizWait.question));
find(sheet, "chip")[1].props.onClick();
check("the answer carries the option", answers[0][0] === "quiz.answer"
                                       && answers[0][1].option === "1");
const strayedSheet = views.war(waiting, words, conf,
                               tools({ now: 40, local: { sheet: { kind: "person", tag: "#P1" } } }));
check("il foglio di un'altra scheda non copre la guerra",
      find(strayedSheet, "sheet").length === 0
      && find(strayedSheet, "todo").length === 1
      && find(strayedSheet, "next").length === 1);

const PLAYED = 2;
const rounds = [1, 2, 3, 4, 5, 6, 7].map((n) => ({
  n: n, them: "Girone " + n, us_stars: n <= PLAYED ? 27 : 0, them_stars: n <= PLAYED ? 18 : 0,
  result: n <= PLAYED ? "win" : null,
  state: n <= PLAYED ? "done" : (n === PLAYED + 1 ? "live" : "next") }));
const league = { season: "2026-09", day: PLAYED + 1, days: rounds,
                 lineup: [{ tag: "#P1", name: "Mario", th: 16, in: true, attacked: false,
                            picked: false, bonus: false },
                          { tag: "#P2", name: "Luigi", th: 15, in: false, attacked: true,
                            picked: true, bonus: true }],
                 table: [{ name: "Nostro Clan", stars: 27, destr: 170.5, rank: 1 }] };
const inLeague = Object.assign({}, state, { cwl: league });
const days = [];
const strip = views.war(inLeague, words, conf,
                        tools({ now: view.end - 100, pick: (name, value) => days.push([name, value]) }));
const dayTiles = find(find(strip, "days")[0], "tile");
check("la lega ha una tessera per ogni giornata", dayTiles.length === rounds.length);
check("la tessera della giornata giocata dice l'esito col suo bordo",
      text(dayTiles[0]).includes("[war_win]")
      && String(dayTiles[0].props.class).includes("win"));
check("la giornata in corso e quella da giocare portano il loro bordo",
      String(dayTiles[PLAYED].props.class).includes("live")
      && String(dayTiles[rounds.length - 1].props.class).includes("locked"));
const leagueWords = new Proxy({ cwl_day: "G{n} {result}",
                                war_score: "{result}{stars} - {opp_stars}" },
                              { get: (base, key) => (key in base ? base[key]
                                                                 : "[" + String(key) + "]") });
const numbered = find(find(views.war(inLeague, leagueWords, conf, tools({ now: view.end - 100 })),
                           "days")[0], "tile");
check("la tessera della giornata porta il numero e le stelle",
      text(numbered[0]).includes("G1")
      && text(numbered[0]).includes(rounds[0].us_stars + " - " + rounds[0].them_stars));
check("the live day names the rival of that day", text(strip).includes(rounds[PLAYED].them));
check("the live day is still fought with the war cards", find(strip, "match").length === 1);
check("la giornata di lega porta il suo tabellone e nessuna riga",
      find(strip, "score-row").length === 2 && find(strip, "row").length === 0
      && text(find(strip, "score-row")[0]).includes(rounds[PLAYED].them)
      && text(find(strip, "score-row")[0]).includes(state.clan.name));
dayTiles[0].props.onClick();
check("a day tile picks that day", days[0][0] === "cwl_day" && days[0][1] === rounds[0].n);
const older = views.war(inLeague, words, conf,
                        tools({ now: view.end - 100, local: { cwl_day: rounds[0].n } }));
check("the day I pick names its own rival", text(older).includes(rounds[0].them));
check("the standings name the clans of the group", text(strip).includes(league.table[0].name));
check("la classifica del girone e a tessere",
      find(find(strip, "table")[0], "tile").length === league.table.length);

const plain = Object.assign({}, inLeague,
  { me: Object.assign({}, state.me, { level: null, manage: undefined, tools: undefined }) });
const plainTree = views.war(plain, words, conf, tools({ now: view.end - 100 }));
const lineTiles = find(find(strip, "lineup")[0], "tile");
check("the line-up is there for everyone",
      lineTiles.length === league.lineup.length
      && find(find(plainTree, "lineup")[0], "tile").length === league.lineup.length);
check("la tessera dice chi c'e e chi salta",
      String(lineTiles[0].props.class).includes(conf.SIDES[0])
      && text(lineTiles[0]).includes("[avail_" + conf.SIDES[0] + "]")
      && String(lineTiles[1].props.class).includes(conf.SIDES[1])
      && text(lineTiles[1]).includes("[avail_" + conf.SIDES[1] + "]"));
check("chi e in formazione e chi ha il bonus porta il suo segno",
      find(lineTiles[1], "badge").length === 1 && find(lineTiles[1], "dot").length === 1
      && find(lineTiles[0], "badge").length === 0 && find(lineTiles[0], "dot").length === 0);
check("only a manager opens the line-up sheet",
      Boolean(lineTiles[0].props.onClick)
      && find(find(plainTree, "lineup")[0], "tile").every((one) => !one.props.onClick));
const seats = [];
find(find(views.war(inLeague, words, conf,
                    tools({ now: view.end - 100,
                            pick: (name, value) => seats.push([name, value]) })),
          "lineup")[0], "tile")[0].props.onClick();
check("toccare la tessera apre il foglio di quel giocatore",
      seats[0][0] === "sheet" && seats[0][1].kind === "cwl_seat"
      && seats[0][1].tag === league.lineup[0].tag);

const roster = [];
const seatOf = (row) => views.war(inLeague, words, conf,
                                  tools({ now: view.end - 100,
                                          local: { sheet: { kind: "cwl_seat", tag: row.tag } },
                                          run: async (kind, extra) => {
                                            roster.push([kind, extra]);
                                          } }));
const line = find(find(seatOf(league.lineup[0]), "sheet")[0], "chip");
check("il foglio del giocatore porta dentro, fuori, formazione e bonus",
      line.length === conf.SIDES.length + 2);
line[0].props.onClick();
line[conf.SIDES.length].props.onClick();
line[conf.SIDES.length + 1].props.onClick();
check("the chip declares who is in", roster[0][0] === "cwl.roster.set"
      && roster[0][1].village === league.lineup[0].tag
      && roster[0][1].choice === conf.SIDES[0]);
check("the line-up chip composes the day", roster[1][0] === "cwl.lineup.set"
      && roster[1][1].village === league.lineup[0].tag
      && Object.keys(roster[1][1]).join() === "village");
check("the bonus chip toggles the medal", roster[2][0] === "cwl.bonus.toggle"
      && roster[2][1].village === league.lineup[0].tag);
check("who is already in the line-up wears the chip on",
      String(find(find(seatOf(league.lineup[1]), "sheet")[0],
                  "chip")[conf.SIDES.length].props.class).includes("on"));
check("senza gestione il foglio del giocatore non si apre",
      find(views.war(plain, words, conf,
                     tools({ now: view.end - 100,
                             local: { sheet: { kind: "cwl_seat",
                                               tag: league.lineup[0].tag } } })),
           "sheet").length === 0);
check("the mirror stays on the live day",
      primaries.war(inLeague, words, conf, {}).kind === "target.mirror"
      && primaries.war(inLeague, words, conf, { cwl_day: rounds[0].n }) === null);

const taken = Object.assign({}, state, {
  war_view: Object.assign({}, view, { mine: Object.assign({}, view.mine, { target: { pos: 2 } }) }) });
check("primary mirrors when I have no target",
      primaries.war(state, words, conf, {}).kind === "target.mirror");
check("no primary when I already have a target", primaries.war(taken, words, conf, {}) === null);
check("no primary without a war", primaries.war(noWar, words, conf, {}) === null);

check("clan gives every member a tile",
      find(views.clan(state, words, conf, tools({})), "tile").length >= state.members.length);
check("clan never leaves the grid mute",
      find(views.clan({ level: "full", clan: state.clan, members: [] }, words, conf, tools({})),
           "empty").length >= 1);
check("nothing waiting is never a mute list",
      find(views.war(Object.assign({}, noWar, { next: null, last_war: null, todo: [] }),
                     words, conf, tools({})), "empty").length === 1);

function chipOf(node, name) {
  return find(node, "chip").find((one) => text(one).includes(name));
}

const TAG = state.people.rows[0].tag;
const clanPicks = [];
const held = { run: async () => true, now: 0, local: {},
               pick: (name, value) => clanPicks.push([name, value]) };
const clanTree = views.clan(state, words, conf, held);
const peopleTiles = find(peopleGrid(state, words, conf, held), "tile");
check("una tessera per ogni membro", peopleTiles.length === state.people.rows.length);
const mixed = Object.assign({}, state, {
  people: Object.assign({}, state.people, { rows: state.people.rows.slice().reverse() }) });
const byGift = mixed.people.rows.slice().sort((one, two) => two.donations - one.donations);
const giftTools = { run: held.run, now: 0, local: { sort: "donations" }, pick() {} };
const sorted = find(peopleGrid(mixed, words, conf, giftTools), "tile");
const kept = find(peopleGrid(mixed, words, conf,
                             { run: held.run, now: 0, local: {}, pick() {} }), "tile");
check("l'ordine per donazioni cambia la prima tessera",
      text(sorted[0]).includes(byGift[0].name)
      && !text(kept[0]).includes(byGift[0].name)
      && sorted.every((one, seat) => text(one).includes(byGift[seat].name)));
check("senza ordine chiesto le tessere restano come arrivano",
      kept.every((one, seat) => text(one).includes(mixed.people.rows[seat].name)));
function withAway(days) {
  return Object.assign({}, state, {
    people: Object.assign({}, state.people,
                          { rows: [Object.assign({}, state.people.rows[0],
                                                 { absent_days: days })] }) });
}
check("il pallino dell'assenza compare a tre giorni e non a due",
      find(peopleGrid(withAway(conf.IDLE_MIN_DAYS), words, conf, held), "dot").length === 1
      && find(peopleGrid(withAway(conf.IDLE_MIN_DAYS - 1), words, conf, held),
              "dot").length === 0);
check("l'assenza segue la soglia del bot", away({ absent_days: 3 }, conf)
      && !away({ absent_days: 2 }, conf) && !away({}, conf)
      && !away({ absent_days: 9 }, {}));
const spelled = text(find(peopleGrid(state, said, conf, held), "tile")[0]);
check("la tessera porta il municipio, le donazioni e il rapporto",
      spelled.includes(fill(said.th, "th", state.people.rows[0].th))
      && spelled.includes(String(state.people.rows[0].donations))
      && spelled.includes(String(state.people.rows[0].ratio)));
check("la griglia dei membri sta su tre colonne",
      find(peopleGrid(state, words, conf, held), "grid")[0].props.style === "--cols:3");
check("i fatti della tessera stanno separati e senza puntini",
      find(peopleTiles[0], "facts").length === 1 && !DOTS.test(spelled));
check("la tessera porta le iniziali e la spunta di chi e collegato",
      find(peopleTiles[0], "face").length === 1
      && find(peopleGrid(Object.assign({}, state, {
           people: Object.assign({}, state.people, {
             rows: [Object.assign({}, state.people.rows[0], { linked: true })] }) }),
           words, conf, held), "badge").length === 1);
peopleTiles[0].props.onClick();
check("a tap opens the person sheet", clanPicks[0][0] === "sheet" && clanPicks[0][1].kind === "person"
      && clanPicks[0][1].tag === TAG);
chipOf(clanTree, "clan_sort_donations").props.onClick();
check("the chips ask for the order", clanPicks[1][0] === "sort" && clanPicks[1][1] === "donations");
check("chi cresce e una tessera per posto sul podio",
      find(climbTiles(state, words, held), "tile").length === state.people.climb.week.length);
const monthTools = { run: held.run, now: 0, local: { period: "month" }, pick() {} };
check("il mese cambia le tessere di chi cresce",
      find(climbTiles(state, words, monthTools), "tile").length
      === state.people.climb.month.length);
chipOf(climbTiles(state, words, held), "clan_month").props.onClick();
check("il bottone del mese chiede il periodo",
      clanPicks[2][0] === "period" && clanPicks[2][1] === "month");
check("the clan keeps its own line", find(clanTree, "line-path").length === 1);
const warWords = new Proxy({ war_score: "{result} {stars} - {opp_stars}", war_destr: "{destr}%" },
                         { get: (base, key) => (key in base ? base[key] : "[" + String(key) + "]") });
const warTiles = find(views.clan(state, warWords, conf, held), "win")
                 .concat(find(views.clan(state, warWords, conf, held), "lose"));
check("lo storico guerre e una tessera per guerra con esito, stelle e percentuale",
      warTiles.length === state.wars.length
      && text(warTiles[0]).includes(state.wars[0].them)
      && text(warTiles[0]).includes(state.wars[0].us_stars + " - " + state.wars[0].them_stars)
      && text(warTiles[0]).includes(Math.round(state.wars[0].us_destr) + "%"));
check("senza guerre registrate lo storico non compare",
      find(views.clan(Object.assign({}, state, { wars: [] }), warWords, conf, held), "win")
        .length === 0);
const personSheet = views.clan(state, words, conf,
                               { run: held.run, now: 0,
                                 local: { sheet: { kind: "person", tag: TAG } }, pick() {} });
const paper = find(personSheet, "sheet")[0];
const drawn = state.growth.players[TAG].trophies.filter((one) => one !== null);
check("the sheet shows the person and a chart", find(personSheet, "sheet").length === 1
      && text(paper).includes(state.people.rows[0].name)
      && find(paper, "trend").length === 1
      && find(paper, "bar-fill").length === drawn.length);
check("il grafico porta il numero con il delta sopra e le barre sotto",
      find(find(paper, "trend")[0], "num").length === 1
      && text(find(find(paper, "trend")[0], "num")[0]) === String(drawn[drawn.length - 1])
      && text(find(find(paper, "trend")[0], "delta")[0])
         === "+" + String(drawn[drawn.length - 1] - drawn[0]));
check("the sheet shows the medals", find(paper, "medal").length === state.medals[TAG].length);
check("the sheet keeps the others out", !text(paper).includes(state.people.rows[1].name));
const done = [];
const clanBoss = { run: async (kind, extra) => { done.push([kind, extra]); return true; }, now: 0,
                   local: { sheet: { kind: "person", tag: TAG }, note: { tag: TAG, text: "ciao" } },
                   pick() {} };
const mineTree = views.clan(state, words, conf, clanBoss);
chipOf(mineTree, "manage_warn_yes").props.onClick();
chipOf(mineTree, "manage_save").props.onClick();
check("the manager warns by village", done[0][0] === "warning.confirm"
      && done[0][1].village === TAG && Object.keys(done[0][1]).join() === "village");
check("the note carries the village and the text", done[1][0] === "note.set"
      && done[1][1].village === TAG && done[1][1].text === "ciao");
check("the note stops where the catalogue stops",
      Number(find(mineTree, "note")[0].props.maxlength) === conf.NOTE_MAX);
const other = [];
const strayed = views.clan(state, words, conf,
                           { run: async (kind, extra) => { other.push([kind, extra]); return true; },
                             now: 0, pick() {},
                             local: { sheet: { kind: "person", tag: state.people.rows[1].tag },
                                      note: { tag: TAG, text: "ciao" } } });
chipOf(strayed, "manage_save").props.onClick();
check("a note written for one person never lands on another",
      other[0][1].village === state.people.rows[1].tag && other[0][1].text === ""
      && find(strayed, "note")[0].props.value === "");
const plainMember = views.clan(Object.assign({}, state, { me: { tag: "#P4", name: "Toad" } }),
                               words, conf,
                               { run: held.run, now: 0,
                                 local: { sheet: { kind: "person", tag: TAG } }, pick() {} });
check("a member gets no buttons on the person",
      chipOf(plainMember, "manage_warn_yes") === undefined
      && find(plainMember, "note").length === 0);
const clanCards = find(clanTree, "card").map((one) => String(one.props.class).split(" "));
check("la testata del clan e la sola card eroe, coi tre numeri",
      clanCards[0].includes("hero")
      && clanCards.filter((one) => one.includes("hero")).length === 1
      && find(find(clanTree, "card")[0], "big").length === 3);
const clanJumps = find(clanTree, "jumps")[0];
check("sotto la testata si salta a chi cresce e alla cronaca",
      Boolean(clanJumps) && find(clanJumps, "chip").length === 2
      && text(find(clanJumps, "chip")[0]).includes("[clan_climb]")
      && text(find(clanJumps, "chip")[1]).includes("[clan_chronicle]")
      && find(clanTree, "climb")[0].props.id === "climb");
if (clanJumps) { find(clanJumps, "chip")[1].props.onClick(); }
check("il salto alla cronaca la apre",
      clanPicks[clanPicks.length - 1][0] === "chronicle"
      && clanPicks[clanPicks.length - 1][1] === true);
check("il foglio persona e tessere e grafico, non righe",
      find(personSheet, "row").length === 0 && find(paper, "tile").length >= 4);
check("la scheda Clan non porta nessuna riga", find(clanTree, "row").length === 0);
const BADGE = "https://api-assets.clashofclans.com/badges/200/uno.png";
const fuori = { level: "outsider", clan: Object.assign({}, state.clan, { badge: BADGE }),
                recruit: { open: true, free: 7, requirement: 15, page_on: true, code: "ab12cd" },
                people: { rows: [] }, members: [] };
const fuoriTree = views.clan(fuori, words, conf, tools({}));
check("lo stemma del clan sta nella scheda Clan",
      every(fuoriTree).some((one) => one.type === "img" && one.props.src === BADGE));
check("l'estraneo legge i requisiti e come candidarsi",
      text(fuoriTree).includes("[more_requirement]") && text(fuoriTree).includes("[more_apply]"));
check("il richiamo alla candidatura non si ripete a chi e dentro",
      !text(views.clan(state, words, conf, tools({}))).includes("[more_apply]"));
check("senza stemma la scheda Clan non mette immagini",
      every(views.clan(state, words, conf, tools({}))).every((one) => one.type !== "img"));
check("i segni della persona stanno separati e senza puntini",
      find(paper, "facts").length === 1 && !DOTS.test(text(paper)));
const meTree = views.me(state, words, conf, { run: async () => true, now: 0, local: {}, pick() {} });
check("me shows my village", text(meTree).includes(state.me_view.tag));
const nobody = Object.assign({}, state, {
  me_view: Object.assign({}, state.me_view,
                         { tag: null, villages: [], growth: null, medals: [] }) });
const empty = views.me(nobody, words, conf,
                       { run: async () => true, now: 0, local: { tag: "#ABC123" }, pick() {} });
check("without a village the tag and the game code appear together",
      find(empty, "claim").length === 1 && find(empty, "verify").length === 1);
const proved = primaries.me(nobody, words, conf, { tag: "ABC123", token: " abc " });
check("primary proves the typed tag with the game code",
      proved.kind === "link.verify" && proved.extra.village === "#ABC123"
      && proved.extra.token === "abc");
const picked = [];
const firstLink = views.me(nobody, words, conf,
                           { run: async () => true, now: 0, local: { tag: "#ABC123" },
                             pick(key, value) { picked.push([key, value]); } });
const termsChip = chipOf(firstLink, "[link_terms]");
check("the first link shows the terms button", Boolean(termsChip)
      && !String(termsChip.props.class).split(" ").includes("on"));
if (termsChip) { termsChip.props.onClick(); }
check("the terms button marks the acceptance", picked.length === 1
      && picked[0][0] === "terms" && picked[0][1] === "on");
check("terms and privacy sit next to the terms button",
      every(firstLink).some((one) => one.props && one.props.href === "/terms")
      && every(firstLink).some((one) => one.props && one.props.href === "/privacy"));
const agreed = primaries.me(nobody, words, conf, { tag: "ABC123", token: "abc", terms: "on" });
check("the pressed terms button travels with the link", agreed.extra.terms === "on"
      && Object.keys(agreed.extra).join() === "village,token,terms");
check("without the button the link carries no acceptance",
      !("terms" in proved.extra));
const pressedChip = chipOf(views.me(nobody, words, conf,
                                    { run: async () => true, now: 0,
                                      local: { tag: "#ABC123", terms: "on" }, pick() {} }),
                           "[link_terms]");
check("the pressed terms button stays lit", Boolean(pressedChip)
      && String(pressedChip.props.class).split(" ").includes("on"));
check("primary is quiet without the game code",
      primaries.me(nobody, words, conf, { tag: "#ABC123" }) === null);
check("primary is quiet without a tag", primaries.me(nobody, words, conf, {}) === null);
const claimed = Object.assign({}, state, {
  me_view: Object.assign({}, state.me_view, { verified: false }) });
check("an unverified village asks for the game code",
      find(views.me(claimed, words, conf,
                    { run: async () => true, now: 0, local: {}, pick() {} }), "verify").length === 1);
const CANDIDATI = [{ tag: "#F1", name: "Mario" }, { tag: "#F2", name: "Marioo" },
                   { tag: "#F3", name: "Mari" }];
const restato = views.me(Object.assign({}, nobody, {
  roster: CANDIDATI.concat([{ tag: "#F9", name: "Bowser" }]),
  me_view: Object.assign({}, nobody.me_view, { candidates: CANDIDATI }) }),
                         words, conf, tools({}));
check("il flusso sei tu? non propone piu nessuna tessera",
      find(restato, "tile").length === 0 && !text(restato).includes("[me_you]"));
check("senza villaggio resta il campo del tag e nessun vuoto",
      find(restato, "claim").length === 1 && !text(restato).includes("[link_empty]"));
check("tag e token del gioco restano l'unica strada",
      find(restato, "field").length === 2 && find(restato, "verify").length === 1);
check("the typed tag gets its hash",
      primaries.me(nobody, words, conf, { tag: "abc123", token: "x" }).extra.village === "#ABC123");
const acted = [];
const doer = { run: async (kind, extra) => { acted.push([kind, extra]); return true; }, now: 0,
               local: { token: "abc123" }, pick() {} };
const meActs = views.me(state, words, conf, doer);
check("the code of the game has its field",
      find(meActs, "verify").length === 1 && find(meActs, "verify")[0].props.value === "abc123");
const asked = primaries.me(state, words, conf, { token: "abc123" });
check("primary verifies the village with the code", asked.kind === "link.verify"
      && asked.extra.village === state.me_view.tag
      && Object.keys(asked.extra).join() === "village,token");
check("nothing left to verify once the village is verified",
      primaries.me(Object.assign({}, state, {
        me_view: Object.assign({}, state.me_view, { verified: true }) }),
                   words, conf, { token: "abc123" }) === null);
chipOf(meActs, "avail_out").props.onClick();
check("the war choice carries only the choice", acted[0][0] === "availability.set"
      && acted[0][1].choice === "out" && Object.keys(acted[0][1]).join() === "choice");
const meKnob = (tree, label) => find(tree, "switch").find((one) => text(one).includes(label));
meKnob(meActs, "[link_whisper]").props.onClick();
check("the whisper turns on for my village", acted[1][0] === "link.whisper"
      && acted[1][1].village === state.me_view.tag && acted[1][1].on === conf.SWITCH[0]
      && Object.keys(acted[1][1]).join() === "village,on");
chipOf(meActs, "link_drop").props.onClick();
check("the unlink names only the village", acted[2][0] === "link.drop"
      && acted[2][1].village === state.me_view.tag
      && Object.keys(acted[2][1]).join() === "village");
const armedPicks = [];
chipOf(views.me(state, words, conf,
                { run: async () => true, now: 0, local: {},
                  pick: (name, value) => armedPicks.push([name, value]) }),
       "data_forget").props.onClick();
check("the first tap only arms the deletion",
      armedPicks.length === 1 && armedPicks[0][0] === "forget" && armedPicks[0][1] === true);
chipOf(views.me(state, words, conf, { run: doer.run, now: 0, local: { forget: true }, pick() {} }),
       "data_sure").props.onClick();
check("the second tap sends the word the server asks for", acted[3][0] === "data.forget"
      && acted[3][1].sure === conf.SURE && Object.keys(acted[3][1]).join() === "sure");
meKnob(views.me(Object.assign({}, state, {
  me_view: Object.assign({}, state.me_view, { whisper: true }) }), words, conf, doer),
       "[link_whisper]").props.onClick();
check("the whisper goes off from the other side of the switch", acted[4][0] === "link.whisper"
      && acted[4][1].on === conf.SWITCH[1]);
check("my card keeps the others out", !text(meTree).includes(state.people.rows[1].name)
      && !text(meTree).includes("uid"));
const meFiles = find(meTree, "tile").filter((one) => one.props.href);
check("i miei dati si scaricano da due link firmati",
      meFiles.length === 2
      && meFiles.every((one) => String(one.props.href).includes("init="))
      && String(meFiles[0].props.href) === conf.MINE.json
      && String(meFiles[1].props.href) === conf.MINE.csv);
const plainMe = views.me(Object.assign({}, state, { me: { tag: "#P4", name: "Toad" } }),
                         words, conf, tools({}));
check("chi non guida il clan scarica solo i suoi dati",
      find(plainMe, "tile").filter((one) => one.props.href).length === 1
      && String(find(plainMe, "tile").find((one) => one.props.href).props.href)
         === conf.MINE.json);
check("senza i link pronti il riquadro dei dati non inventa tessere",
      find(views.me(state, words, Object.assign({}, conf, { MINE: null }), tools({})), "tile")
        .filter((one) => one.props.href).length === 0);
const myDays = state.me_view.growth.trophies.filter((one) => one !== null);
check("my growth and my week are drawn", find(meTree, "trend").length === 1
      && find(meTree, "bar-fill").length === myDays.length + 3);
const WORN = state.me_view.medals.map((one) => one.badge);
const ALL = Object.keys(conf.MEDALS);
const medalTiles = find(find(meTree, "medals")[0], "tile");
check("la griglia porta tutte le medaglie, mie e da conquistare",
      medalTiles.length === ALL.length);
check("le medaglie non ancora mie restano grigie",
      find(meTree, "locked").length === ALL.length - WORN.length
      && find(meTree, "won").length === WORN.length);
const openedMedal = [];
find(find(views.me(state, words, conf,
                   { run: async () => true, now: 0, local: {},
                     pick: (name, value) => openedMedal.push([name, value]) }),
          "medals")[0], "tile")[0].props.onClick();
check("toccare una medaglia apre come si ottiene",
      openedMedal[0][0] === "sheet" && openedMedal[0][1].kind === "medal"
      && openedMedal[0][1].badge === ALL[0]);
const howPaper = find(views.me(state, words, conf,
                               { run: async () => true, now: 0,
                                 local: { sheet: { kind: "medal", badge: ALL[0] } },
                                 pick() {} }), "sheet")[0];
check("il foglio della medaglia dice il nome e come si ottiene",
      text(howPaper).includes("[badge_name_" + ALL[0] + "]")
      && text(howPaper).includes("[badge_how_" + ALL[0] + "]"));
const goalRing = find(meTree, "ring")[0];
check("l'anello porta l'obiettivo col numero dentro",
      Boolean(goalRing) && text(goalRing).includes(String(state.me_view.goal.value)));
const openedGoal = [];
find(views.me(state, words, conf,
              { run: async () => true, now: 0, local: {},
                pick: (name, value) => openedGoal.push([name, value]) }),
     "ring-tap")[0].props.onClick();
check("toccare l'anello apre il foglio dell'obiettivo",
      openedGoal[0][0] === "sheet" && openedGoal[0][1].kind === "goal");
const chosen = [];
const goalPaper = find(views.me(state, words, conf,
                                { run: async (kind, extra) => { chosen.push([kind, extra]); },
                                  now: 0, local: { sheet: { kind: "goal" } }, pick() {} }),
                       "sheet")[0];
const targets = find(goalPaper, "chip");
check("il foglio dell'obiettivo ha un bottone per ogni traguardo",
      targets.length === state.me_view.goal.picks.length
      && find(goalPaper, "on").length === 1);
targets[targets.length - 1].props.onClick();
check("scegliere il traguardo lo manda col suo tipo e il suo eroe",
      chosen[0][0] === "goal.set" && chosen[0][1].goal === "hero"
      && chosen[0][1].target === "45" && chosen[0][1].hero === "Barbarian King"
      && Object.keys(chosen[0][1]).sort().join() === "goal,hero,target");
const shared = [];
const sharing = { run: async (kind, extra) => { shared.push([kind, extra]); }, now: 0,
                  local: {}, pick() {} };
chipOf(views.me(state, words, conf, sharing), "[me_share]").props.onClick();
chipOf(views.me(state, words, conf, sharing), "[me_share_clan]").props.onClick();
check("il riquadro condividi chiama la settimana e la card del clan",
      shared[0][0] === "share.week" && shared[1][0] === "share.clan"
      && Object.keys(shared[0][1]).length === 0);
check("chi non gestisce non condivide la card del clan",
      chipOf(views.me(Object.assign({}, state, { me: { tag: "#P4", name: "Toad" } }),
                      words, conf, sharing), "[me_share_clan]") === undefined);
const spoken = [];
chipOf(views.me(state, words, conf,
                { run: async (kind, extra) => { spoken.push([kind, extra]); }, now: 0,
                  local: {}, pick() {} }), "English").props.onClick();
check("la lingua si sceglie dai bottoni delle venti lingue",
      spoken[0][0] === "lang.set" && spoken[0][1].lang === "en"
      && Object.keys(spoken[0][1]).join() === "lang");
const okTree = views.me(Object.assign({}, state, {
  me_view: Object.assign({}, state.me_view, { verified: true,
    villages: state.me_view.villages.map((one) => Object.assign({}, one, { verified: true })) }) }),
                        words, conf, tools({}));
check("a verified village shows the badge and asks for nothing",
      find(okTree, "verify").length === 0 && text(okTree).includes("[me_verified]"));
const meCards = find(meTree, "card").map((one) => String(one.props.class).split(" "));
const meFirst = find(meTree, "card")[0];
check("in Io la card in cima tiene l'anello a sinistra e quattro numeri a destra",
      meCards[0].includes("hero") && find(meFirst, "ring").length === 1
      && find(meFirst, "big").length === 4 && find(meFirst, "tile").length === 0);
check("sotto la card stanno gli interruttori rapidi e poi le medaglie",
      meCards[1].includes("quick") && meCards[2].includes("medals"));
check("gli interruttori rapidi portano disponibilita e sussurro",
      text(find(meTree, "quick")[0]).includes("[avail_in]")
      && find(find(meTree, "quick")[0], "switch").length === 1);
check("in Io non resta nessuna riga", find(meTree, "row").length === 0);
const OTHER = { tag: "#P2", name: "Luigi", verified: true };
const twoTown = Object.assign({}, state, {
  me_view: Object.assign({}, state.me_view,
                         { villages: [state.me_view.villages[0], OTHER] }) });
const villagePicks = [];
const twoTree = views.me(twoTown, said, conf,
                         { run: async () => true, now: 0, local: {},
                           pick: (name, value) => villagePicks.push([name, value]) });
const townChips = find(twoTree, "villages")[0];
check("con due villaggi una fila di chip col nome e il municipio",
      Boolean(townChips) && find(townChips, "chip").length === 2
      && text(find(townChips, "chip")[0]).includes(state.me_view.name)
      && text(find(townChips, "chip")[1]).includes(OTHER.name)
      && text(find(townChips, "chip")[1]).includes(
        fill(said.th, "th", state.people.rows[1].th)));
if (townChips) { find(townChips, "chip")[1].props.onClick(); }
check("toccare il chip sceglie il villaggio",
      villagePicks.length === 1 && villagePicks[0][0] === "village"
      && villagePicks[0][1] === OTHER.tag);
check("con un villaggio solo non compare nessun chip",
      find(meTree, "villages").length === 0);
check("il villaggio scelto e quello dei suoi, non uno qualsiasi",
      chosenVillage(twoTown.me_view, { village: OTHER.tag }) === OTHER.tag
      && chosenVillage(twoTown.me_view, {}) === state.me_view.tag
      && chosenVillage(twoTown.me_view, { village: "#P9" }) === state.me_view.tag);
const otherView = villageView(twoTown, twoTown.me_view, OTHER.tag);
check("il villaggio scelto porta la sua crescita, le sue medaglie e la sua settimana",
      otherView.tag === OTHER.tag && otherView.name === OTHER.name
      && otherView.growth.trophies.join() === state.growth.players[OTHER.tag].trophies.join()
      && otherView.medals.length === 0
      && otherView.period.war_stars === state.growth.period.week[OTHER.tag].war_stars
      && villageView(state, state.me_view, state.me_view.tag) === state.me_view);
const otherTree = views.me(twoTown, words, conf, tools({ local: { village: OTHER.tag } }));
const fourOf = (tree) => find(find(tree, "card")[0], "big-value").map(text).join();
const row2 = state.people.rows[1];
check("scelto l'altro villaggio, Io porta i suoi quattro numeri",
      fourOf(otherTree) === [row2.trophies, row2.th, row2.donations,
                             state.growth.period.week[OTHER.tag].war_stars].join()
      && fourOf(meTree) === [state.me_view.profile.trophies, state.me_view.profile.th,
                             state.me_view.profile.donations,
                             state.me_view.period.war_stars].join());
const otherWar = views.war(twoTown, words, conf,
                           tools({ now: view.end - 100, local: { village: OTHER.tag } }));
const otherHits = find(find(otherWar, "attacks")[0], "tile");
const mineHits = find(find(warTree, "attacks")[0], "tile");
const bigOf = (node) => text(find(node, "tile-big")[0]);
check("sul villaggio di un altro posto le prenotazioni non si toccano",
      find(find(otherWar, "attacks")[0], "chip").length === 0
      && find(find(warTree, "attacks")[0], "chip").length === view.free.length);
check("Guerra mostra i miei attacchi del villaggio scelto",
      bigOf(otherHits[0]) === String(view.per_member - state.ours[1].left)
      && bigOf(mineHits[0]) === String(view.mine.used)
      && String(otherHits[1].props.class).includes("mine")
      && String(mineHits[1].props.class).includes("free"));
check("no war at all leaves only what is waiting for me",
      text(views.war({ clan: state.clan, me_view: { tag: state.me_view.tag } }, words, conf,
                     tools({}))).split(/\s+/u).filter(Boolean).join(" ")
      === "[todo_title] [todo_empty]");
const LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH16%3AHV%3AAaBbCcDd";
const OTHER_LINK = "https://link.clashofclans.com/it?action=OpenLayout&id=TH15%3AHV%3AEeFfGgHh";
const shelf = {
  clan: [{ alias: "b1", label: "war", village: "home", hall: 16, link: LINK, by: "Mario" }],
  library: {
    halls: [16, 15],
    rows: [{ id: "aaa111", name: "Base A", hall: 16, village: "home", kind: "war", link: LINK,
             builder: "Chi disegna", tags: [], added: "2026-09-02" },
           { id: "bbb222", name: "Base B", hall: 15, village: "home", kind: "farm",
             link: OTHER_LINK, builder: "Altro", tags: [], added: "2026-09-01" }],
    videos: [{ id: "v1", channel: "UCx", title: "Video", published: "2026-09-03", links: [LINK] }],
  },
};
const wide = Object.assign({}, state, {
  bases: shelf,
  recruit: { open: true, free: 4, requirement: 14, page_on: true, code: "abc123" },
  family: { name: "Famiglia", code: "fam1", clans: [{ name: "Secondo Clan", code: "def456" }] },
  help: { support: "https://esempio.test/s", creator: "CLANBOARD",
          community: "https://t.me/clanboard", source: "https://esempio.test/c" },
  award: { rows: [{ name: "Mario", stars: 3, destr: 100 }], ends: 1789200000 },
  more_view: { rivals: [{ tag: "#P2", name: "Luigi" }],
               rival: { tag: "#P2", name: "Luigi", trophies: 5100 },
               guess: { th: 16, d_th: 15, done: false },
               duels: [{ id: "d1", rival: "Luigi", mate: null, metric: "loot", status: "open",
                         ends: 0 },
                       { id: "d2", rival: "Peach", mate: "Toad", metric: "loot", status: "open",
                         ends: 0 }] },
  todo: [{ kind: "duel", id: "d1", rival: "Luigi", metric: "loot" },
         { kind: "quiz", question: "Quante stelle?", options: ["uno", "due", "tre"] },
         { kind: "prediction", poll: "war", options: ["noi", "loro"] }],
});
const logged = [];
const kit = (local) => ({ run: async (kind, extra) => { logged.push([kind, extra]); return true; },
                            now: 0, local: local || {},
                            pick: (name, value) => logged.push([name, value]) });
const seen = (local) => views.more(wide, words, conf, kit(local));
const tapped = (local, label) => {
  const found = find(seen(local), "chip").find((one) => text(one) === label);
  if (found) { found.props.onClick(); }
  return Boolean(found);
};

const ALTRO = ["bases", "games", "recruit", "family", "help"];
const GAMES_ON = { more: "games" };
check("more shows the five sections", ALTRO.every(
  (name) => text(seen()).includes("[more_" + name + "]")));
check("in Altro l'ordine e basi, giochi, recluta, famiglia, aiuto",
      find(seen(), "chip").slice(0, ALTRO.length).map(text).join()
      === ALTRO.map((name) => "[more_" + name + "]").join()
      && find(seen(), "base").length === shelf.library.rows.length);
const GIOCHI = ["duel", "guess", "predict", "award"];
const ATTESE = ["duel", "guess", "predict"];
check("i giochi stanno in quattro riquadri",
      find(find(seen(GAMES_ON), "grid")[0], "tile").length === GIOCHI.length
      && GIOCHI.every(
        (name) => text(find(seen(GAMES_ON), "grid")[0]).includes("[more_" + name + "]")));
check("il quiz non sta piu fra i giochi dell'app",
      !text(seen(GAMES_ON)).includes("[more_quiz]"));
check("il riquadro dei giochi porta il suo conto",
      text(find(seen(GAMES_ON), "grid")[0]).includes(String(wide.more_view.duels.length)));
check("il riquadro di chi aspetta me porta il segno",
      find(find(seen(GAMES_ON), "grid")[0], "dot").length === ATTESE.length);
check("toccare un riquadro apre il suo foglio",
      (() => {
        const before = logged.length;
        find(find(seen(GAMES_ON), "grid")[0], "tile")[1].props.onClick();
        const last = logged[logged.length - 1];
        return logged.length === before + 1 && last[0] === "sheet" && last[1].kind === "guess";
      })());
const rivalWords = new Proxy({ more_rival: "Sfida {name}" },
                             { get: (base, key) => (key in base ? base[key]
                                                                : "[" + String(key) + "]") });
const rivalTile = find(seen(GAMES_ON), "tile").find(
  (one) => text(one).includes(String(wide.more_view.rival.trophies)));
check("la sfida consigliata porta il rivale e i suoi trofei",
      Boolean(rivalTile) && text(views.more(wide, rivalWords, conf, kit(GAMES_ON))).includes(
        "Sfida " + wide.more_view.rival.name));
check("la sfida consigliata parte con un tocco",
      (() => {
        rivalTile.props.onClick();
        const last = logged[logged.length - 1];
        return last[0] === "duel.challenge" && last[1].rival === wide.more_view.rival.tag
               && last[1].metric === conf.METRICS[0] && last[1].duration === conf.DURATIONS[0];
      })());
check("the library lists every base",
      find(seen({ more: "bases" }), "base").length === shelf.library.rows.length);
check("the town hall filters the library",
      find(seen({ more: "bases", hall: 15 }), "base").length === 1);
check("the kind filters the library",
      find(seen({ more: "bases", kind: "war" }), "base").length === 1);
check("the clan keeps its own bases",
      find(seen({ more: "bases", bases: "clan" }), "base").length === shelf.clan.length);
check("every base opens in the game", find(seen({ more: "bases" }), "open").every(
  (one) => String(one.props.href).startsWith("https://link.clashofclans.com/")));
check("the videos carry the links of the bases",
      find(seen({ more: "bases", bases: "videos" }), "open").length === 1);
check("la tessera del video porta l'anteprima",
      find(seen({ more: "bases", bases: "videos" }), "thumb").every(
        (one) => String(one.props.src).startsWith("https://i.ytimg.com/vi/")
                 && String(one.props.src).includes(shelf.library.videos[0].id))
      && find(seen({ more: "bases", bases: "videos" }), "thumb").length === 1);
check("ogni base della libreria si propone al clan",
      (() => {
        const found = find(seen({ more: "bases" }), "chip").filter(
          (one) => text(one) === "[bases_propose]");
        if (found.length !== shelf.library.rows.length) { return false; }
        found[0].props.onClick();
        const last = logged[logged.length - 1];
        return last[0] === "base.propose" && last[1].link === shelf.library.rows[0].link
               && last[1].label === shelf.library.rows[0].kind;
      })());
check("una base senza tipo conosciuto si propone con la prima etichetta",
      (() => {
        const odd = Object.assign({}, wide, { bases: Object.assign({}, shelf, {
          library: Object.assign({}, shelf.library, {
            rows: [Object.assign({}, shelf.library.rows[0], { kind: "pinco" })] }) }) });
        const found = find(views.more(odd, words, conf, kit({ more: "bases" })), "chip").find(
          (one) => text(one) === "[bases_propose]");
        found.props.onClick();
        return logged[logged.length - 1][1].label === conf.LABELS[0];
      })());
check("la base del clan non si ripropone al clan",
      find(seen({ more: "bases", bases: "clan" }), "chip").every(
        (one) => text(one) !== "[bases_propose]"));
check("il link della base si copia",
      (() => {
        const written = [];
        globalThis.navigator = { clipboard: { writeText: (raw) => written.push(raw) } };
        const found = find(seen({ more: "bases" }), "chip").find(
          (one) => text(one) === "[bases_copy]");
        found.props.onClick();
        delete globalThis.navigator;
        return written[0] === shelf.library.rows[0].link;
      })());
const shouted = [];
globalThis.navigator = { clipboard: { writeText: () => Promise.reject(new Error("vetro")) } };
globalThis.window = { Telegram: { WebApp: { showAlert: (raw) => shouted.push(raw) } } };
const copied = copy(shelf.library.rows[0].link);
await Promise.resolve();
await Promise.resolve();
delete globalThis.navigator;
const missed = [];
globalThis.window = { Telegram: { WebApp: { showAlert: (raw) => missed.push(raw) } } };
const gaveUp = copy(shelf.library.rows[0].link);
delete globalThis.window;
check("se la copia non riesce il link si mostra lo stesso",
      copied === true && shouted[0] === shelf.library.rows[0].link);
check("senza appunti il link si mostra e basta",
      gaveUp === false && missed[0] === shelf.library.rows[0].link);
const retapped = (tab) => {
  tapped({ more: "bases", bases: tab }, "[bases_" + tab + "]");
  return logged[logged.length - 1];
};
check("the open tab of the bases stays put when tapped again",
      ["library", "clan", "videos"].every((tab) => {
        const last = retapped(tab);
        return last[0] === "bases" && last[1] === tab;
      }));
check("the help says the creator code",
      text(seen({ more: "help", sheet: { kind: "support" } })).includes(wide.help.creator));
check("the family lists its clans",
      text(seen({ more: "family" })).includes(wide.family.clans[0].name));
check("the recruitment says the free seats",
      text(seen({ more: "recruit" })).includes(String(wide.recruit.free)));
check("recluta sta in tre riquadri",
      find(find(seen({ more: "recruit" }), "grid")[0], "tile").length === 3);
check("i riquadri dicono requisito e pagina pubblica",
      text(seen({ more: "recruit" })).includes("[manage_req_hint]")
      && text(seen({ more: "recruit" })).includes("[page_state]")
      && text(seen({ more: "recruit" })).includes("[manage_state_on]"));
check("il bottone candidati porta al contatto del clan",
      find(seen({ more: "recruit" }), "tile").some(
        (one) => String(one.props.href) === "/r/" + wide.recruit.code));
check("il clan fuori dalla bacheca non manda nessuno a bussare",
      find(views.more(Object.assign({}, wide, {
        recruit: Object.assign({}, wide.recruit, { open: false }) }), words, conf,
        kit({ more: "recruit" })), "tile").every((one) => !one.props.href));
check("la famiglia e a tessere",
      find(find(seen({ more: "family" }), "grid")[0], "tile").length
        === wide.family.clans.length
      && text(seen({ more: "family" })).includes(wide.family.clans[0].code));
check("l'aiuto sta in cinque riquadri coi suoi link",
      find(find(seen({ more: "help" }), "grid")[0], "tile").length === 5
      && find(seen({ more: "help" }), "tile").filter((one) => one.props.href)
           .map((one) => String(one.props.href)).join()
         === [wide.help.community, "/privacy", wide.help.source].join());
check("senza link dell'aiuto restano privacy e segnala",
      find(views.more(Object.assign({}, wide, { help: {} }), words, conf, kit({ more: "help" })),
           "tile").filter((one) => one.props.href)
        .map((one) => String(one.props.href)).join() === "/privacy");
const reportTile = find(seen({ more: "help" }), "tile").find(
  (one) => text(one).includes("[more_report]"));
check("l'aiuto porta la tessera per segnalare",
      Boolean(reportTile) && text(reportTile).includes("[more_report]"));
if (reportTile) { reportTile.props.onClick(); }
check("toccare segnala apre il foglio dei motivi",
      logged[logged.length - 1][0] === "sheet"
      && logged[logged.length - 1][1].kind === "report");
const reportPaper = find(seen({ more: "help", sheet: { kind: "report" } }), "sheet")[0] || null;
const reasonChips = reportPaper ? find(reportPaper, "chip") : [];
check("il foglio della segnalazione ha un chip per motivo",
      reasonChips.length === conf.REASONS.length
      && text(reportPaper).includes("[reason_" + conf.REASONS[0] + "]"));
if (reasonChips.length) { reasonChips[1].props.onClick(); }
check("toccare il motivo manda la segnalazione con quel motivo",
      logged[logged.length - 1][0] === "report.send"
      && logged[logged.length - 1][1].reason === conf.REASONS[1]
      && Object.keys(logged[logged.length - 1][1]).join() === "reason");
check("la segnalazione non nomina nessun compagno",
      !text(reportPaper).includes(state.people.rows[1].name));
const helpOf = (found) => views.more(Object.assign({}, wide, { help: found }), words, conf,
                                     kit({ more: "help" }));
const supportTile = find(seen({ more: "help" }), "tile").find(
  (one) => text(one).includes("[more_support]"));
check("l'aiuto porta la voce del sostegno senza mandarla fuori",
      Boolean(supportTile) && !supportTile.props.href);
if (supportTile && supportTile.props.onClick) { supportTile.props.onClick(); }
check("toccare il sostegno apre il foglio",
      logged[logged.length - 1][0] === "sheet"
      && logged[logged.length - 1][1].kind === "support");
const supportPaper = find(seen({ more: "help", sheet: { kind: "support" } }), "sheet")[0] || null;
const supportTiles = supportPaper ? find(supportPaper, "tile") : [];
check("il foglio del sostegno ha paypal, stelle e codice creatore",
      supportTiles.length === 2
      && String(supportTiles[0].props.href) === wide.help.support
      && text(supportPaper).includes("[more_stars]")
      && text(supportTiles[1]).includes(wide.help.creator));
check("le stelle non sono una tessera toccabile",
      supportTiles.every((one) => !text(one).includes("[more_stars]")));
const heldCode = [];
globalThis.navigator = { clipboard: { writeText: (raw) => heldCode.push(raw) } };
if (supportTiles.length === 2 && supportTiles[1].props.onClick) {
  supportTiles[1].props.onClick();
}
delete globalThis.navigator;
check("il codice creatore si copia con un tocco", heldCode[0] === wide.help.creator);
check("senza donazione ne codice creatore la voce del sostegno non c'e",
      find(helpOf({ community: wide.help.community }), "tile")
        .every((one) => !text(one).includes("[more_support]")));
check("col solo codice creatore la voce del sostegno resta",
      find(helpOf({ creator: wide.help.creator }), "tile")
        .some((one) => text(one).includes("[more_support]")));
check("col solo link della donazione la voce del sostegno resta",
      find(helpOf({ support: wide.help.support }), "tile")
        .some((one) => text(one).includes("[more_support]")));
check("il foglio del sostegno non nomina mai un compagno",
      !text(supportPaper).includes(state.people.rows[1].name));
const onDuels = { more: "games", sheet: { kind: "duel" } };
const duelTiles = find(find(seen(onDuels), "sheet")[0], "tile");
check("the challenges of the clan arrive from the page",
      duelTiles.length === wide.more_view.duels.length);
check("a duel between two others names them both",
      text(duelTiles[1]).includes(wide.more_view.duels[1].mate)
      && text(duelTiles[1]).includes(wide.more_view.duels[1].rival));
check("the duel is accepted with its id",
      (() => {
        duelTiles[0].props.onClick();
        const last = logged[logged.length - 1];
        return last[0] === "duel.accept" && last[1].duel === "d1";
      })());
check("una sfida fra altri due non si accetta",
      !duelTiles[1].props.onClick && Boolean(duelTiles[0].props.onClick));
const GUESS_ON = { more: "games", sheet: { kind: "guess" } };
const guessSeen = (found, local) => views.more(found, said, conf, kit(local));
const otherRound = (guess) => Object.assign({}, wide, {
  more_view: Object.assign({}, wide.more_view, { guess: guess }) });
const guessFoglio = find(guessSeen(wide, GUESS_ON), "sheet")[0];
check("il foglio della manche porta i due municipi e nessun nome",
      text(guessFoglio).includes("TH" + wide.more_view.guess.th)
      && text(guessFoglio).includes("TH" + wide.more_view.guess.d_th)
      && !text(guessFoglio).includes(wide.more_view.rival.name)
      && !text(guessFoglio).includes(wide.more_view.rival.tag));
check("la manche offre le stelle e le percentuali dichiarate",
      find(guessFoglio, "chips").length === 2
      && find(find(guessFoglio, "chips")[0], "chip").map(text).join()
      === conf.GUESS_STARS.join()
      && find(find(guessFoglio, "chips")[1], "chip").map(text).join()
      === conf.GUESS_PERCENTS.join());
check("senza guerre chiuse la manche dice alla prossima guerra",
      text(guessSeen(otherRound(null), GUESS_ON)).includes("[guess_wait]"));
check("dopo la risposta la manche dice fatto",
      text(guessSeen(otherRound({ th: 16, d_th: 15, done: true }), GUESS_ON)).includes(
        "[guess_done]"));
check("la risposta parte dal bottone principale con stelle e percentuale",
      (() => {
        const local = Object.assign({}, GUESS_ON, { guess: { stars: 2, percent: 60 } });
        const top = primaries.more(wide, words, conf, local);
        return Boolean(top) && top.kind === "guess.answer" && top.extra.stars === "2"
               && top.extra.percent === "60"
               && primaries.more(wide, words, conf, GUESS_ON) === null;
      })());
check("the forecast says which poll it answers",
      tapped({ more: "games", sheet: { kind: "prediction" } }, "noi")
      && logged.some((one) => one[0] === "prediction.set" && one[1].poll === "war"
                            && one[1].option === "0"));
check("the award is voted by its place",
      tapped({ more: "games", sheet: { kind: "award" } }, "Mario")
      && logged.some((one) => one[0] === "award.vote" && one[1].option === "0"));
check("the sheet of the duel offers rivals, metrics and durations",
      find(seen(onDuels), "sheet").length === 1
      && text(seen(onDuels)).includes("[duel_metric_loot]"));
check("the duel leaves only when the sheet is full",
      primaries.more(wide, words, conf, { sheet: { kind: "duel" } }) === null
      && primaries.more(wide, words, conf,
                        { sheet: { kind: "duel" },
                          duel: { rival: "#P2", metric: "loot", duration: "week" } }).kind
         === "duel.challenge");

const staffBoss = (local) => views.manage(state, words, conf, kit(local));
const only = (node, name) => find(node, name)[0] || null;
const inside = (node, label) => find(node, "chip").filter((one) => text(one) === label);
const press = (node, label) => {
  const found = inside(node, label)[0];
  if (found) { found.props.onClick(); }
  return Boolean(found);
};
const ran = (kind, holds) => logged.some((one) => one[0] === kind && holds(one[1]));
const tileOf = (node, label) => find(node, "tile").find((one) => text(one).includes(label));
const tap = (node, label) => {
  const found = tileOf(node, label);
  if (!found || typeof found.props.onClick !== "function") { return false; }
  found.props.onClick();
  return true;
};
const awaited = state.inbox.pending[0];
const approvedOne = state.manage_view.approved[0];
const chiefless = Object.assign({}, state, {
  manage_view: Object.assign({}, state.manage_view, { chief: false }),
});
const backable = Object.assign({}, state, {
  manage_view: Object.assign({}, state.manage_view, {
    log: [{ what: "pausa", who: "Mario", at: 1, of: "settings", ref: "prev" }],
  }),
});
const paused = Object.assign({}, state, {
  manage_view: Object.assign({}, state.manage_view, { paused: true }),
});
const bare = Object.assign({}, state, {
  manage_view: Object.assign({}, state.manage_view, { delegates: [] }),
});
const armed = (kind, extra) => ({ confirm: { kind: kind, extra: extra || {} } });
const member = Object.assign({}, state, { me: { tag: "#P1", name: "Mario", level: null },
                                          inbox: undefined, manage_view: undefined });
const narrow = Object.assign({}, state, {
  me: Object.assign({}, state.me, { level: null, manage: undefined,
                                    tools: { wars: state.me.tools.wars } }),
});

check("la casella sta in cima alla gestione", find(staffBoss({}), "inbox").length === 1);
check("la casella dà una card per voce, non una riga",
      find(only(staffBoss({}), "inbox"), "item").length === pendingOf(state)
      && find(only(staffBoss({}), "inbox"), "row").length === 0);
check("ogni voce della casella porta i suoi bottoni larghi",
      find(find(only(staffBoss({}), "inbox"), "item")[0], "wide").length === 1
      && find(find(only(staffBoss({}), "inbox"), "item")[0], "chip").length === 2);
check("la persona si approva con la sua impronta e la guerra subito",
      press(staffBoss({}), "[manage_now]")
      && ran("person.approve", (one) => one.who === String(awaited.who)
                                        && one.war_from === conf.WAR_FROM[0]));
check("la persona si approva dalla prossima guerra", press(staffBoss({}), "[manage_next]")
      && ran("person.approve", (one) => one.who === String(awaited.who)
                                        && one.war_from === conf.WAR_FROM[1]));
check("il segno va e viene si accende sull'approvato", press(staffBoss({}), "[manage_trust]")
      && ran("person.trust", (one) => one.who === String(approvedOne.who)
                                      && one.value === conf.SWITCH[0]));
check("l'approvato si revoca con la sua impronta", press(staffBoss({}), "[manage_revoke]")
      && ran("person.revoke", (one) => one.who === String(approvedOne.who)));
check("gli approvati stanno fuori dalla casella e solo al capo e ai co-capi",
      find(only(staffBoss({}), "inbox"), "item")
        .every((one) => !text(one).includes("[manage_revoke]"))
      && text(views.manage(state, words, conf, kit({}))).includes("[manage_approved]")
      && !text(views.manage(narrow, words, conf, kit({}))).includes("[manage_approved]"));
check("la casella non porta piu i villaggi rivendicati",
      !("claims" in state.inbox) && !text(staffBoss({})).includes("[manage_approve]"));
check("la candidatura si decide col suo numero", press(staffBoss({}), "[manage_accept]")
      && ran("application.decide",
             (one) => one.ref === state.inbox.applications[0].id
                      && one.choice === conf.DECIDED[0]));
check("l'ammonizione parte dal villaggio proposto", press(staffBoss({}), "[manage_warn_yes]")
      && ran("warning.confirm",
             (one) => one.village === state.inbox.warnings[0].tag));
check("la segnalazione apre il foglio col dettaglio", press(staffBoss({}), "[manage_seen]")
      && logged.some((one) => one[0] === "sheet" && one[1].kind === "report"
                            && one[1].code === state.inbox.reports[0].code));
const proposal = { id: "ab12", name: "Mario", label: "war", village: "home", hall: 16,
                   link: LINK };
const withBase = Object.assign({}, state, {
  inbox: Object.assign({}, state.inbox, { bases: [proposal] }),
});
const boxBase = (label) => {
  const tree = views.manage(withBase, words, conf, kit({}));
  const rows = find(only(tree, "inbox"), "item");
  const found = find(rows[rows.length - 1], "chip").find((one) => text(one) === label);
  if (found) { found.props.onClick(); }
  return Boolean(found);
};
check("la base proposta arriva nella casella con chi l'ha proposta e il suo link",
      (() => {
        const box = only(views.manage(withBase, words, conf, kit({})), "inbox");
        const rows = find(box, "item");
        return text(rows[rows.length - 1]).includes(proposal.name)
               && find(box, "open").some((one) => String(one.props.href) === LINK);
      })());
check("la base proposta si accetta col suo riferimento", boxBase("[manage_accept]")
      && ran("base.accept", (one) => one.ref === proposal.id));
check("la base proposta si rifiuta col suo riferimento", boxBase("[manage_reject]")
      && ran("base.reject", (one) => one.ref === proposal.id));
check("il foglio della segnalazione mostra il codice",
      text(staffBoss({ sheet: { kind: "report", code: "abc123", reason: "scam" } })).includes("abc123"));
check("l'ammonizione confermata si toglie col suo riferimento",
      press(staffBoss({}), "[manage_void]")
      && ran("warning.void", (one) => one.ref === state.me.tools.wars.warnings[0].id));
check("la pausa si arma senza partire", press(staffBoss({}), "[manage_pause]")
      && !ran("clan.pause", () => true)
      && logged.some((one) => one[0] === "confirm" && one[1] && one[1].kind === "clan.pause"));
check("la chip armata si vede",
      String(inside(staffBoss(armed("clan.pause")), "[manage_pause]")[0].props.class).includes("on"));
check("la chip armata toccata di nuovo disarma",
      press(staffBoss(armed("clan.pause")), "[manage_pause]")
      && logged.some((one) => one[0] === "confirm" && one[1] === null));
check("la conferma non è più una chip",
      inside(staffBoss(armed("clan.pause")), "[manage_sure]").length === 0);
check("la conferma della gestione non arma la cancellazione dei dati",
      chipOf(views.me(state, words, conf, kit(armed("clan.pause"))), "[data_forget]") !== undefined
      && chipOf(views.me(state, words, conf, kit(armed("clan.pause"))), "[data_sure]") === undefined);
check("la cancellazione armata in Io non arma niente in Gestione",
      primaries.manage(state, words, conf, { forget: true }) === null
      && inside(staffBoss({ forget: true }), "[manage_sure]").length === 0);
check("la pausa si conferma sul bottone principale",
      primaries.manage(state, words, conf, armed("clan.pause")).kind === "clan.pause"
      && primaries.manage(state, words, conf, armed("clan.pause")).label === "[manage_sure]");
check("senza niente di armato non c'è bottone principale",
      primaries.manage(state, words, conf, {}) === null);
check("il clan già in pausa si riprende, non si mette in pausa",
      primaries.manage(paused, words, conf, armed("clan.pause")) === null
      && primaries.manage(paused, words, conf, armed("clan.resume")).kind === "clan.resume");
check("chi non è capo non conferma niente",
      primaries.manage(chiefless, words, conf, armed("clan.pause")) === null);
check("chi non gestisce non conferma niente",
      primaries.manage(member, words, conf, armed("clan.pause")) === null);
check("un'azione fuori elenco non finisce sul bottone principale",
      primaries.manage(state, words, conf, armed("gate.toggle")) === null);
check("i delegati si tolgono tutti dal bottone principale",
      press(staffBoss({}), "[manage_clear]")
      && primaries.manage(state, words, conf, armed("delegates.clear")).kind
         === "delegates.clear");
check("senza delegati non si conferma di toglierli",
      primaries.manage(bare, words, conf, armed("delegates.clear")) === null);
check("chi non è capo non mette in pausa il clan",
      inside(views.manage(chiefless, words, conf, kit({})), "[manage_pause]").length === 0);
function seatRef(rows) {
  const found = (rows[0] || {}).who;
  return typeof found === "string" && found.length > 0 ? found : null;
}

check("il posto sospeso si riattiva col suo riferimento", press(staffBoss({}), "[manage_lift]")
      && ran("suspension.lift", (one) => one.who === seatRef(state.manage_view.suspended)));
check("la delega si dà e si toglie", press(staffBoss({}), "[manage_delegate_on]")
      && press(staffBoss({}), "[manage_delegate_off]")
      && ran("delegate.add", (one) => one.who === seatRef(state.manage_view.people))
      && ran("delegate.remove", (one) => one.who === seatRef(state.manage_view.delegates)));
check("l'ultima azione si arma col suo tipo e riferimento",
      press(views.manage(backable, words, conf, kit({})), "[manage_undo]")
      && logged.some((one) => one[0] === "confirm" && one[1] && one[1].kind === "undo.apply"
                            && one[1].extra.of === "settings" && one[1].extra.ref === "prev"));
check("l'annullamento si conferma sul bottone principale",
      primaries.manage(backable, words, conf,
                       armed("undo.apply", { of: "settings", ref: "prev" })).extra.ref === "prev");
check("senza voci da annullare non si conferma l'annullamento",
      primaries.manage(state, words, conf,
                       armed("undo.apply", { of: "settings", ref: "prev" })) === null);
check("senza voci da annullare non c'è il bottone",
      inside(staffBoss({}), "[manage_undo]").length === 0);
const knobOf = (node, label) => find(node, "switch").find((one) => text(one).includes(label));
const flip = (node, label) => {
  const found = knobOf(node, label);
  if (found) { found.props.onClick(); }
  return Boolean(found);
};
check("l'ingresso al gruppo si spegne con l'interruttore",
      flip(staffBoss({}), "[manage_gate_title]")
      && ran("gate.toggle", (one) => one.on === conf.SWITCH[1]));
check("i pacchetti sono tessere, non una lista",
      find(only(staffBoss({}), "packs"), "grid").length === 1
      && find(only(staffBoss({}), "packs"), "tile").length
         === Object.keys(state.manage_view.packs).length
      && find(only(staffBoss({}), "packs"), "chip").length === 0);
check("la tessera del pacchetto dice il suo stato",
      (() => {
        const tiles = find(only(staffBoss({}), "packs"), "tile");
        const on = tiles.find((one) => text(one).includes("[pack_wars]"));
        const off = tiles.find((one) => text(one).includes("[pack_cwl]"));
        return text(on).includes("[manage_state_on]") && String(on.props.class).includes("on")
               && text(off).includes("[manage_state_off]")
               && !String(off.props.class).includes("on") && on.type === "button";
      })());
const packTile = (label) => find(only(staffBoss({}), "packs"), "tile")
  .find((one) => text(one).includes(label));
packTile("[pack_wars]").props.onClick();
check("la tessera del pacchetto apre il suo foglio",
      logged.some((one) => one[0] === "sheet" && one[1] && one[1].kind === "pack"
                           && one[1].pack === "wars"));
const packPaper = only(views.manage(state, words, conf,
                                    kit({ sheet: { kind: "pack", pack: "wars" } })), "sheet");
check("il foglio del pacchetto porta dettagli e orari, non una lista",
      Boolean(packPaper) && text(packPaper).includes("[pack_wars]")
      && text(packPaper).includes("[manage_state_on]")
      && text(packPaper).includes(state.manage_view.schedules[0].hhmm)
      && find(packPaper, "row").length === 0
      && find(packPaper, "tile").length === state.manage_view.schedules.length + 1);
check("l'orario si toglie dalla sua tessera",
      tap(only(staffBoss({}), "schedules"), "[manage_sched_del]")
      && ran("schedule.delete", (one) => one.ref === state.manage_view.schedules[0].id));
check("l'orario nuovo parte con ora, giorni e testo",
      press(staffBoss({ sheet: { kind: "schedule" }, hhmm: "21:15", days: "12",
                   sched_text: "Ci siamo" }), "[manage_save]")
      && ran("schedule.add", (one) => one.hhmm === "21:15" && one.days === "12"
                                      && one.text === "Ci siamo"));
check("il foglio dei testi rispetta il limite del catalogo",
      (only(only(staffBoss({ sheet: { kind: "texts", field: "welcome" } }), "sheet"), "field")
       || { props: {} }).props.maxLength === conf.TEXT_MAX);
check("il benvenuto si salva dal foglio",
      press(staffBoss({ sheet: { kind: "texts", field: "welcome" }, text: "Ciao a tutti" }),
            "[manage_save]")
      && ran("welcome.set", (one) => one.text === "Ciao a tutti"));
check("le regole partono dal loro campo",
      press(staffBoss({ sheet: { kind: "texts", field: "rules" } }), "[manage_save]")
      && ran("rules.set", (one) => one.text === state.manage_view.texts.rules));
check("la pagina pubblica si accende con l'interruttore",
      flip(staffBoss({}), "[page_state]") && ran("page.toggle", (one) => one.on === conf.SWITCH[0]));
check("l'interruttore porta sotto la sua riga di stato",
      text(only(staffBoss({}), "page")).includes("[manage_state_off]"));
check("il canale del clan si toglie dalla sua tessera",
      tap(only(staffBoss({}), "channels"), "[manage_sched_del]")
      && ran("channel.drop", (one) => one.channel === state.manage_view.channels[0].id));
check("il canale nuovo parte dall'id scritto",
      press(only(staffBoss({ channel: "UCbbbbbbbbbbbbbbbbbbbbbb" }), "channels"),
            "[manage_sched_add]")
      && ran("channel.add", (one) => one.channel === "UCbbbbbbbbbbbbbbbbbbbbbb"));
check("le altre impostazioni si riaprono dal primo passo",
      press(staffBoss({}), "[manage_restart]") && ran("settings.open", () => true));
check("i bottoni delle impostazioni passano il loro dato",
      press(views.manage(Object.assign({}, state, {
        me: Object.assign({}, state.me, {
          manage: Object.assign({}, state.me.manage, {
            settings: { text: "<b>Passo</b>", buttons: [[{ label: "Avanti", data: "cfg:a:b" }]] },
          }),
        }),
      }), words, conf, kit({})), "Avanti")
      && ran("settings.press", (one) => one.data === "cfg:a:b"));
check("le impostazioni arrivano senza marcatori",
      !text(views.manage(Object.assign({}, state, {
        me: Object.assign({}, state.me, {
          manage: Object.assign({}, state.me.manage,
                                { settings: { text: "<b>Passo</b>", buttons: [] } }),
        }),
      }), words, conf, kit({}))).includes("<b>"));
check("chi non gestisce non vede niente",
      find(views.manage(member, words, conf, kit({})), "empty").length === 1);
check("chi gestisce poco non vede i comandi che non ha",
      find(views.manage(narrow, words, conf, kit({})), "inbox").length === 1
      && find(views.manage(narrow, words, conf, kit({})), "channels").length === 0
      && find(views.manage(narrow, words, conf, kit({})), "texts").length === 0
      && find(views.manage(narrow, words, conf, kit({})), "schedules").length === 0
      && find(views.manage(narrow, words, conf, kit({})), "switch").length === 0);
check("la gestione ha il suo bottone principale", typeof primaries.manage === "function");
check("in Gestione non resta nessuna riga", find(staffBoss({}), "row").length === 0);
check("la casella vuota e una riga sola, non un riquadro",
      (() => {
        const bare_box = views.manage(Object.assign({}, state, { inbox: {} }), words, conf,
                                      kit({}));
        const box = only(bare_box, "inbox");
        return find(box, "strip").length === 1 && find(box, "empty").length === 0
               && find(box, "item").length === 0;
      })());
check("i testi stanno in tessere col loro stato",
      find(only(staffBoss({}), "texts"), "tile").length === 2
      && text(only(staffBoss({}), "texts")).includes(state.manage_view.texts.welcome));

const familyless = Object.assign({}, state, {
  manage_view: Object.assign({}, state.manage_view, {
    family: Object.assign({}, state.manage_view.family,
                          { name: null, code: null, derby: null }),
  }),
});
const noTools = Object.assign({}, state, {
  manage_view: Object.assign({}, state.manage_view,
                             { recruit: null, family: null, integrations: null }),
});
const tiledOnly = Object.assign({}, state, {
  me: Object.assign({}, state.me, { manage: { staff: state.me.manage.staff } }),
});
const blocco = state.manage_view.recruit.blocked[0];

check("il municipio minimo sta in una tessera, non in una riga",
      find(only(staffBoss({}), "recruit"), "tile").length === 1
      && find(only(staffBoss({}), "recruit"), "row").length === 0);
check("il municipio minimo si alza e si abbassa di uno",
      press(only(staffBoss({}), "recruit"), "[manage_th_up]")
      && ran("recruit.requirements.set",
             (one) => one.th === String(state.manage_view.recruit.th + 1))
      && press(only(staffBoss({}), "recruit"), "[manage_th_down]")
      && ran("recruit.requirements.set",
             (one) => one.th === String(state.manage_view.recruit.th - 1)));
check("la candidatura si blocca col suo numero",
      press(staffBoss({}), "[manage_app_block]")
      && ran("sender.block", (one) => one.ref === String(state.inbox.applications[0].id)));
check("i bloccati stanno in tessere che sbloccano, non in righe",
      find(only(staffBoss({}), "blocked"), "row").length === 0
      && tap(only(staffBoss({}), "blocked"), "[manage_unblock]")
      && ran("sender.unblock", (one) => one.ref === String(blocco.id)));
check("la famiglia porta il codice e le tessere di derby e torneo",
      text(only(staffBoss({}), "family")).includes(state.manage_view.family.code)
      && find(only(staffBoss({}), "family"), "tile").length === 3
      && find(only(staffBoss({}), "family"), "row").length === 0);
check("la tessera del derby apre il suo foglio",
      tap(only(staffBoss({}), "family"), "[manage_derby]")
      && logged.some((one) => one[0] === "sheet" && one[1] && one[1].kind === "derby"));
check("la tessera del torneo apre il suo foglio",
      tap(only(staffBoss({}), "family"), "[manage_tourney]")
      && logged.some((one) => one[0] === "sheet" && one[1] && one[1].kind === "tourney"));
check("il foglio del derby manda il dato del suo bottone",
      press(staffBoss({ sheet: { kind: "derby" } }),
            state.manage_view.family.derby.buttons[0][0].label)
      && ran("family.derby",
             (one) => one.data === state.manage_view.family.derby.buttons[0][0].data));
check("il foglio del torneo manda il dato del suo bottone",
      press(staffBoss({ sheet: { kind: "tourney" } }),
            state.manage_view.family.tourney.buttons[0][0].label)
      && ran("family.tourney",
             (one) => one.data === state.manage_view.family.tourney.buttons[0][0].data));
const noFamily = (local) => views.manage(familyless, words, conf, kit(local));
check("senza famiglia si crea col nome e si entra col codice",
      tap(noFamily({ family_name: "Nuova", family_code: "fam2" }), "[manage_family_new]")
      && ran("family.create", (one) => one.name === "Nuova")
      && tap(noFamily({ family_name: "Nuova", family_code: "fam2" }), "[manage_family_invite]")
      && ran("family.invite", (one) => one.ref === "fam2"));
check("con la famiglia gia fatta non si entra in un'altra",
      tileOf(staffBoss({}), "[manage_family_invite]") === undefined);
check("senza famiglia non ci sono derby ne torneo",
      tileOf(noFamily({}), "[manage_derby]") === undefined
      && tileOf(noFamily({}), "[manage_tourney]") === undefined);
check("le integrazioni sono tre tessere, non righe",
      find(only(staffBoss({}), "integrations"), "tile").length === 3
      && find(only(staffBoss({}), "integrations"), "row").length === 0);
check("il canale twitch parte dal campo scritto",
      tap(staffBoss({ twitch: "nuovo" }), "[manage_twitch_title]")
      && ran("integration.twitch", (one) => one.channel === "nuovo"));
check("il ponte discord si stacca dalla sua tessera",
      tap(staffBoss({}), "[manage_discord_title]")
      && ran("integration.discord", (one) => one.on === conf.SWITCH[1]));
check("il calendario si accende dalla sua tessera",
      tap(staffBoss({}), "[manage_ics_title]")
      && ran("integration.ics", (one) => one.on === conf.SWITCH[0]));
check("per un membro nessuna di queste tessere compare",
      ["recruit", "blocked", "family", "integrations"].every(
        (name) => find(views.manage(member, words, conf, kit({})), name).length === 0
                  && find(views.manage(narrow, words, conf, kit({})), name).length === 0));
check("senza gli strumenti le tessere nuove restano via",
      ["recruit", "blocked", "family", "integrations"].every(
        (name) => find(views.manage(noTools, words, conf, kit({})), name).length === 0));
check("le altre impostazioni spariscono quando ogni area ha la sua tessera",
      inside(views.manage(tiledOnly, words, conf, kit({})), "[manage_restart]").length === 0
      && inside(staffBoss({}), "[manage_restart]").length === 1);

const settled = async (label) => {
  await new Promise((go) => setTimeout(go, 0));
  const from = logged.length;
  press(staffBoss({}), label);
  await new Promise((go) => setTimeout(go, 0));
  return logged.slice(from);
};
const afterClaim = await settled("[manage_now]");
check("una decisione nella casella mostra l'avviso",
      afterClaim.some((one) => one[0] === "toast" && one[1].text === "[manage_done]"
                             && one[1].kind === "undo.apply"));
const afterWarn = await settled("[manage_warn_yes]");
check("anche l'ammonizione decisa mostra l'avviso",
      afterWarn.some((one) => one[0] === "toast" && one[1].kind === "undo.apply"));
check("il bottone dell'avviso chiede l'ultima azione da annullare",
      toastAct(backable, { text: "[manage_done]", kind: "undo.apply" }).kind === "undo.apply"
      && toastAct(backable, { text: "x", kind: "undo.apply" }).extra.of === "settings"
      && toastAct(backable, { text: "x", kind: "undo.apply" }).extra.ref === "prev");
check("senza niente da annullare l'avviso non offre il bottone",
      toastAct(state, { text: "x", kind: "undo.apply" }) === null
      && toastAct(state, null) === null && toastAct(null, null) === null);
const layered = Object.assign({}, state, {
  manage_view: Object.assign({}, state.manage_view, {
    log: [{ what: "claim", who: "Mario", at: 2, of: null, ref: null },
          { what: "pausa", who: "Mario", at: 1, of: "settings", ref: "prev" }],
  }),
});
check("se l'ultima cosa fatta non si annulla, l'avviso non offre di annullare altro",
      toastAct(layered, { text: "x", kind: "undo.apply" }) === null
      && inside(views.manage(layered, words, conf, kit({})), "[manage_undo]").length === 1);
check("l'avviso con il suo riferimento non cerca nel registro",
      toastAct(state, { text: "x", kind: "undo.apply",
                        extra: { of: "warning", ref: "w1" } }).extra.ref === "w1");
check("l'editor mostra l'anteprima sotto il campo",
      (() => {
        const seen = only(staffBoss({ sheet: { kind: "texts", field: "welcome" },
                                      preview: "👋 <b>Benvenuto</b>\nCiao a tutti" }), "preview");
        return Boolean(seen) && text(seen).includes("Ciao a tutti")
               && !text(seen).includes("<b>");
      })());
check("senza anteprima il campo resta da solo",
      find(staffBoss({ sheet: { kind: "texts", field: "welcome" } }), "preview").length === 0);

check("primaries is an object", typeof primaries === "object" && primaries !== null);
check("mark is short and plain", /^[a-z0-9]{1,32}$/.test(mark(0.123456789)));
check("refusal falls back", refusal({ denied: "no", denied_chief: "chief" }, "x") === "no"
      && refusal({ denied: "no", denied_chief: "chief" }, "chief") === "chief");

const y = scale([10, 20, 30], 100);
check("scale maps min to bottom and max to top", y(10) === 100 && y(30) === 0 && y(20) === 50);
check("scale holds the middle without a span", scale([], 100)(5) === 50 && scale([7], 100)(7) === 50);
const chartLine = Line({ values: [10, null, 30], labels: ["a", "b", "c"], width: 200, height: 100 });
check("line skips holes", find(chartLine, "line-path").length === 1
      && String(find(chartLine, "line-path")[0].props.points).split(" ").length === 2);
check("line names the two ends", chartLine.props["aria-label"] === "10 30");

function sides(node) {
  return find(node, "chart-axis").map((one) => text(one).replace(/\s+/gu, " ").trim());
}

const openLine = Line({ values: [null, 20, 30], labels: ["a", "b", "c"], width: 200, height: 100 });
check("line names the day of the first value", sides(openLine)[0] === "b 20");
const closed = Line({ values: [10, 20, null], labels: ["a", "b", "c"], width: 200, height: 100 });
check("line names the day of the last value", sides(closed)[1] === "b 20");
check("line keeps the window when it has no values",
      sides(Line({ values: [null, null], labels: ["a", "b"], width: 200, height: 100 }))
        .join() === "a,b");
const bars = Bars({ rows: [{ label: "x", value: 5 }, { label: "y", value: 10 }],
                    width: 200, height: 40 });
check("bars scale to the max", find(bars, "bar-fill").length === 2);
check("bars keep the widths in proportion",
      Number(find(bars, "bar-fill")[0].props.width) * 2 ===
      Number(find(bars, "bar-fill")[1].props.width));

const sent = [];
globalThis.fetch = async (path, options) => {
  sent.push([path, options]);
  const body = JSON.parse(options.body);
  if (body.kind === "target.set") { return { ok: true, json: async () => ({ fresh: true }) }; }
  return { ok: false, status: 403, json: async () => ({ error: "chief" }) };
};
const okDone = await act("/app/x/act", "sig", "target.set", { pos: "3" });
check("act sends the kind, the extra and an id", sent[0][0] === "/app/x/act"
      && sent[0][1].method === "POST" && sent[0][1].headers["X-Init-Data"] === "sig"
      && JSON.parse(sent[0][1].body).pos === "3" && JSON.parse(sent[0][1].body).id.length > 0);
check("act returns the fresh state", okDone.ok === true && okDone.state.fresh === true);
const noDone = await act("/app/x/act", "sig", "clan.pause", {});
check("act reports the refusal", noDone.ok === false && noDone.error === "chief");
globalThis.fetch = async () => { throw new Error("giu"); };
const netDone = await act("/app/x/act", "sig", "target.set", {});
check("act survives the network", netDone.ok === false && netDone.error === "net");

const calls = [];
globalThis.fetch = async (path, options) => {
  calls.push([path, options]);
  return { ok: true, json: async () => ({ text: "👋 Benvenuto" }) };
};
const shown = await look("/app/x/preview", "sig", "welcome", "Ciao {name}");
check("l'anteprima si chiede col tipo e con la bozza",
      shown === "👋 Benvenuto" && calls[0][0].startsWith("/app/x/preview?kind=welcome")
      && calls[0][0].includes("text=Ciao%20%7Bname%7D")
      && calls[0][1].headers["X-Init-Data"] === "sig");
await look("/app/x/preview", "sig", "rules");
check("senza bozza l'anteprima chiede solo il tipo",
      calls[1][0] === "/app/x/preview?kind=rules");
globalThis.fetch = async () => ({ ok: false, json: async () => ({}) });
check("un'anteprima negata non mostra niente",
      (await look("/app/x/preview", "sig", "welcome")) === "");
globalThis.fetch = async () => { throw new Error("giu"); };
check("l'anteprima sopravvive alla rete",
      (await look("/app/x/preview", "sig", "welcome")) === "");

const PIECES = { Tile, Grid, Ring, Toast, Switch, Sheet, Strip };
for (const name of Object.keys(PIECES)) {
  try {
    check("il pezzo " + name + " si disegna", typeof text(PIECES[name]({})) === "string");
  } catch (error) {
    failed.push("il pezzo " + name + " si rompe: " + error.message);
  }
}

const dash = String(find(Ring({ value: 3, total: 4 }), "ring-arc")[0].props["stroke-dasharray"])
  .split(" ").map(Number);
check("l'anello riempie la sua parte", Math.abs(dash[0] / dash[1] - 3 / 4) < 1e-9);
check("l'anello vuoto non riempie niente",
      Number(String(find(Ring({ value: 0, total: 4 }), "ring-arc")[0]
        .props["stroke-dasharray"]).split(" ")[0]) === 0);
check("l'anello non trabocca",
      Number(String(find(Ring({ value: 9, total: 4 }), "ring-arc")[0]
        .props["stroke-dasharray"]).split(" ")[0]) ===
      Number(String(find(Ring({ value: 4, total: 4 }), "ring-arc")[0]
        .props["stroke-dasharray"]).split(" ")[0]));

const hits = [];
const tile = Tile({ big: 3, label: "[x]", sub: "[y]", tone: "good", on: true, badge: 2, dot: true,
                    onTap: () => hits.push(1) });
check("la tessera si tocca", tile.type === "button");
tile.props.onClick();
check("la tessera chiama chi la tocca", hits.length === 1);
check("la tessera mostra il conto e il segno",
      find(tile, "badge").length === 1 && find(tile, "dot").length === 1);
check("la tessera porta il tono e lo stato acceso",
      String(tile.props.class).includes("good") && String(tile.props.class).includes("on"));
check("la tessera ferma non e un bottone", Tile({ big: 1, label: "[x]" }).type !== "button");
check("la griglia tiene le sue colonne",
      String(Grid({ cols: 3, children: null }).props.style).includes("3"));

const switched = [];
const knob = Switch({ on: true, label: "[s]", onTap: () => switched.push(1) });
check("l'interruttore dice se e acceso", knob.props["aria-checked"] === "true");
knob.props.onClick();
check("l'interruttore chiama chi lo tocca", switched.length === 1);
check("l'interruttore spento lo dice", Switch({ on: false }).props["aria-checked"] === "false");

const fired = [];
const toast = Toast({ text: "[t]", action: "[a]", onAction: () => fired.push("toast") });
find(toast, "toast-do")[0].props.onClick();
const band = Strip({ text: "[t]", action: "[a]", tone: "warn",
                     onAction: () => fired.push("striscia") });
find(band, "strip-do")[0].props.onClick();
check("l'avviso e la striscia chiamano la loro azione", fired.join() === "toast,striscia");
check("la striscia porta il tono", String(band.props.class).includes("warn"));
check("senza azione non c'e bottone", find(Toast({ text: "[t]" }), "toast-do").length === 0
                                      && find(Strip({ text: "[t]" }), "strip-do").length === 0);

const heroCard = Card({ title: "[t]", hero: true, stripe: true, children: null });
check("la card eroe porta il suo grado e la striscia dell'accento",
      String(heroCard.props.class).includes("hero")
      && String(heroCard.props.class).includes("stripe"));
check("la card normale resta quieta",
      !String(Card({ children: null }).props.class).includes("hero")
      && !String(Card({ children: null }).props.class).includes("stripe"));
check("il numero dell'eroe si distingue dagli altri",
      String(find(Big({ value: 1, label: "[l]", hero: true }), "big")[0].props.class)
        .includes("hero")
      && !String(find(Big({ value: 1, label: "[l]" }), "big")[0].props.class).includes("hero"));
check("la barra porta il suo tono",
      String(Bar({ done: 1, total: 2, tone: "win" }).props.class).includes("win"));

const tabBar = Tabs({ tabs: [{ id: "war", label: "[w]" }, { id: "clan", label: "[c]", badge: 2 }],
                      current: "war", onPick: () => {} });
check("ogni scheda porta icona e parola",
      find(tabBar, "ico").length === 2 && text(tabBar).includes("[w]")
      && text(tabBar).includes("[c]"));
check("la scheda di adesso e segnata", find(tabBar, "pick").length === 1);

for (const name of ["war", "clan", "me", "more", "manage"]) {
  const drawn = icon(name);
  check("l'icona " + name + " sta sulla griglia 24 e prende il tratto dal foglio",
        drawn.type === "svg" && drawn.props.viewBox === "0 0 24 24"
        && drawn.props.stroke === "currentColor"
        && drawn.props["stroke-width"] === undefined);
}
check("un'icona che non c'e non rompe niente", icon("boh").type === "svg");

const MUTI = { Card, Tile, Big, Bar, Chip, Chips, Sheet, Empty, Strip, Toast, Switch, Grid, Ring,
               Stars, Tabs };
for (const name of Object.keys(MUTI)) {
  check("il pezzo " + name + " non porta parole sue",
        text(MUTI[name]({ tabs: [], children: null })).trim() === "");
}

check("il passo legge la durata dal token",
      pace("120ms") === 120 && pace("0.2s") === 200 && pace("0s") === 0 && pace("") === 0);
const beats = [];
const beaten = { classList: { add: (one) => beats.push("+" + one),
                              remove: (one) => beats.push("-" + one) } };
const calmDown = pulse(beaten, 200);
check("l'impulso accende il battito", beats.join() === "+beat");
calmDown();
check("l'impulso si spegne", beats.join() === "+beat,-beat");
globalThis.matchMedia = () => ({ matches: true });
const hushed = [];
const stopHushed = pulse({ classList: { add: (one) => hushed.push(one),
                                        remove: (one) => hushed.push("-" + one) } }, 200);
check("chi chiede meno movimento vede comunque il cambio di stato", hushed.join() === "beat");
stopHushed();
delete globalThis.matchMedia;

const memory = { dataset: {} };
check("il segno di prima torna solo quando cambia",
      since(memory, 1) === null && since(memory, 1) === null && since(memory, 2) === "1");
check("senza nodo non c'e segno", since(null, 1) === null);
const throbs = [];
const chipNode = { dataset: {},
                   classList: { add: (one) => throbs.push(one), remove: () => {} } };
throb(chipNode, "2-0");
check("al primo giro il chip non batte", throbs.length === 0);
throb(chipNode, "3-0");
check("il chip batte quando il punteggio cambia", throbs.join() === "beat");
const climbing = { dataset: { to: "5" }, textContent: "" };
grow(climbing);
check("il numero non parte al primo giro", climbing.textContent === "");
climbing.dataset.to = "9";
grow(climbing);
check("il numero sale fino al punteggio nuovo", climbing.textContent === "9");

for (const name of ["nowar", "nogames", "nomembers", "linked", "offline", "empty"]) {
  const drawn = illustration(name);
  check("il disegno " + name + " e un svg del colore del testo",
        drawn.type === "svg" && drawn.props.stroke === "currentColor");
}
check("un disegno che non c'e non rompe niente", illustration("boh").type === "svg");

for (const pack of ["wars", "cwl", "capital_games", "members", "challenges", "family",
                    "recruitment", "bases", "platform", "linked"]) {
  const drawn = icon(pack);
  check("l'icona " + pack + " e un svg del colore del testo",
        drawn.type === "svg" && drawn.props.stroke === "currentColor");
}
check("un'icona che non c'e non rompe niente", icon("boh").type === "svg");
check("le iniziali prendono il primo e l'ultimo nome",
      initials("Mario Rossi") === "MR" && initials("Mario") === "MA" && initials("") === ""
      && initials(null) === "");

const clock = { ago_now: "poco fa", ago_hours: "{n}h fa", ago_yesterday: "ieri",
                ago_days: "{n} gg fa" };
check("il quando della cronaca segue le soglie del bot",
      ago(0, clock) === "poco fa" && ago(7200, clock) === "2h fa"
      && ago(86400, clock) === "ieri" && ago(3 * 86400, clock) === "3 gg fa");

const chronPicks = [];
const shut = { run: async () => true, now: 0, local: {},
               pick: (name, value) => chronPicks.push([name, value]) };
const openTools = { run: shut.run, now: state.updated, local: { chronicle: true }, pick() {} };
check("la cronaca rende un riquadro per evento",
      find(chronicle(state, words, openTools), "tile").length
      === state.people.chronicle.length);
check("la cronaca sta dietro il salto della testata",
      chronicle(state, words, shut) === null
      && chronPicks.length === 0);
check("il riquadro porta chi, il numero e l'icona del pacchetto",
      text(find(chronicle(state, words, openTools), "tile")[0])
        .includes(state.people.chronicle[0].who)
      && find(chronicle(state, words, openTools), "ico").length
         === state.people.chronicle.length);
check("una cronaca vuota non resta muta",
      find(chronicle({ people: { chronicle: [] } }, words, openTools), "empty").length === 1);
check("il riquadro della cronaca tiene evento e quando separati, senza puntini",
      (() => {
        const drawn = chronicle(state, words, openTools);
        const boxes = find(drawn, "tile");
        return find(drawn, "facts").length === boxes.length && !DOTS.test(text(drawn));
      })());

globalThis.requestAnimationFrame = () => {};
const counted = [];
countUp(0, 10, 0, (value) => counted.push(value));
check("il contatore senza tempo arriva subito", counted[counted.length - 1] === 10);
const slow = [];
const stopCount = countUp(0, 10, 1000, (value) => slow.push(value));
check("il contatore parte dal primo numero", slow[0] === 0);
stopCount();

const strokes = [];
const ink = { clearRect: () => strokes.push("pulisce"), fillRect: () => strokes.push("dipinge"),
                fillStyle: "", globalAlpha: 1 };
const sheetCanvas = { width: 100, height: 50, getContext: () => ink };
const stopFx = confetti(sheetCanvas, 3);
check("i coriandoli dipingono", strokes.filter((one) => one === "dipinge").length === 3);
stopFx();
check("i coriandoli puliscono quando finiscono", strokes[strokes.length - 1] === "pulisce");
check("senza tela i coriandoli non rompono niente", typeof confetti(null, 3) === "function");

globalThis.matchMedia = () => ({ matches: true });
const still = [];
countUp(0, 10, 1000, (value) => still.push(value));
check("chi chiede meno movimento vede subito il numero finale",
      still.length === 1 && still[0] === 10);
const stillStrokes = [];
const stillInk = { clearRect: () => stillStrokes.push("pulisce"),
                   fillRect: () => stillStrokes.push("dipinge"), fillStyle: "", globalAlpha: 1 };
check("chi chiede meno movimento non vede coriandoli",
      typeof confetti({ width: 10, height: 10, getContext: () => stillInk }, 3) === "function"
      && stillStrokes.length === 0);
delete globalThis.matchMedia;

const { applyAccent, applySafeArea, applyTheme } =
  await import("../../clashbot/web/static/app/theme.js");
const painted = {};
const skin = { style: { setProperty: (k, v) => { painted[k] = v; } }, dataset: {} };
applyTheme({ colorScheme: "dark",
             themeParams: { bg_color: "#161614", secondary_bg_color: "#1e1c19" } }, skin);
check("al buio la scheda prende il fondo secondario",
      painted["--card"] === "#1e1c19" && painted["--line"] === "#161614");
applyTheme({ colorScheme: "light",
             themeParams: { bg_color: "#ffffff", secondary_bg_color: "#efeff4" } }, skin);
check("alla luce la scheda prende il fondo",
      painted["--card"] === "#ffffff" && painted["--line"] === "#efeff4");
applyAccent("#ff0000", skin);
check("l'accento del clan arriva al css", painted["--accent"] === "#ff0000");
painted["--accent"] = null;
applyAccent(null, skin);
check("senza accento niente cambia", painted["--accent"] === null);

const { contrast } = await import("../../clashbot/web/static/app/theme.js");
function surface(tone) {
  return { style: { setProperty: (k, v) => { painted[k] = v; },
                    getPropertyValue: (k) => (k === "--bg" ? tone : "") },
           dataset: {} };
}
const READABLE = 4.5;
applyAccent("#1c1c1a", surface("#161614"));
check("al buio un accento troppo cupo viene schiarito fino a leggersi",
      contrast(painted["--accent"], "#161614") >= READABLE);
applyAccent("#9dbdf5", surface("#161614"));
check("al buio un accento gia leggibile resta com'e", painted["--accent"] === "#9dbdf5");
applyAccent("#ffe000", surface("#fbfbf9"));
check("alla luce un accento troppo chiaro viene scurito fino a leggersi",
      contrast(painted["--accent"], "#fbfbf9") >= READABLE);
applyAccent("#2fb344", surface(""));
check("senza fondo noto l'accento passa com'e", painted["--accent"] === "#2fb344");

const setVars = {};
applySafeArea({ safeAreaInset: { top: 47, bottom: 34 }, contentSafeAreaInset: { top: 46 } },
              { style: { setProperty: (k, v) => { setVars[k] = v; } } });
check("safe area reaches the css", setVars["--safe-bottom"] === "34px" && setVars["--safe-top"] === "93px");
applySafeArea(null, { style: { setProperty: (k, v) => { setVars[k] = v; } } });
check("safe area falls back to zero", setVars["--safe-bottom"] === "0px");

const offWords = { live_seen: "aggiornato {when}", live_retry: "riprova", ago_now: "poco fa",
                   ago_hours: "{n}h fa", ago_yesterday: "ieri", ago_days: "{n} gg fa" };
const retried = [];
const offBand = banner(state, offWords, state.updated + 2 * 3600, () => retried.push("riprova"));
check("da spenti la striscia dice quanto e vecchio lo stato, non copre",
      find(offBand, "strip").length === 1 && text(offBand).includes("aggiornato 2h fa"));
find(offBand, "strip-do")[0].props.onClick();
check("la striscia offre di riprovare", retried.length === 1);
const freshTaps = [];
const freshLine = freshRow(state, offWords, state.updated + 2 * 3600,
                           () => freshTaps.push("ora"));
check("sotto la testata la riga dice quando lo stato e arrivato",
      find(freshLine, "seen").length === 1 && text(freshLine).includes("aggiornato 2h fa"));
find(freshLine, "seen")[0].props.onClick();
check("la riga si tocca e chiede lo stato", freshTaps.length === 1);
function phoneOf(held) {
  return { CloudStorage: {
    setItem: (key, value) => { held[key] = value; },
    getItem: (key, back) => back(null, held[key]),
    getItems: (keys, back) => back(null,
                                   Object.fromEntries(keys.map((key) => [key, held[key]]))),
    getKeys: (back) => back(null, Object.keys(held)),
    removeItems: (keys) => { keys.forEach((key) => { delete held[key]; }); } } };
}

const KEPT = 60;
const TAP = 44;
const VILLAGE_KEY = "village-v" + VERSION;
const heldKeys = {};
const fakePhone = phoneOf(heldKeys);
const recalled = [];
remember(fakePhone, "village", OTHER.tag, KEPT);
recall(fakePhone, "village", (value) => recalled.push(value));
recall({}, "village", (value) => recalled.push(value));
check("la scelta del villaggio resta sul telefono sotto la chiave della versione",
      Object.keys(heldKeys).join() === VILLAGE_KEY && recalled.join() === OTHER.tag);
check("la chiave sul telefono porta la scadenza",
      Number(String(heldKeys[VILLAGE_KEY]).split("/")[0]) - Math.floor(Date.now() / 1000)
      === KEPT);
heldKeys["old-v" + VERSION] = "1/" + OTHER.tag;
const expired = [];
recall(fakePhone, "old", (value) => expired.push(value));
check("una chiave scaduta vale come non scritta", expired.join() === "");
heldKeys["mai-v0"] = "0/x";
heldKeys.nudo = "x";
sweep(fakePhone, VERSION);
check("all'avvio restano solo le chiavi di questa versione ancora buone",
      Object.keys(heldKeys).join() === VILLAGE_KEY);
sweep({}, VERSION);
check("senza telefono l'avvio non tocca niente", Object.keys(heldKeys).join() === VILLAGE_KEY);
const gone = [];
forgetAll(fakePhone, () => gone.push("fatto"));
check("i dati sul dispositivo si cancellano tutti",
      Object.keys(heldKeys).length === 0 && gone.join() === "fatto");
forgetAll({}, () => gone.push("mai"));
check("senza telefono non si cancella niente", gone.join() === "fatto");

const preparati = [];
const phoneOld = { isVersionAtLeast: () => false, shareMessage: (one) => preparati.push(one) };
const phoneNew = { isVersionAtLeast: () => true, shareMessage: (one) => preparati.push(one) };
const phoneBlind = { shareMessage: (one) => preparati.push(one) };
shareMessage(phoneOld, "vecchio");
shareMessage(phoneBlind, "cieco");
shareMessage(phoneNew, "nuovo");
check("il messaggio pronto parte solo dalla versione di Telegram che lo regge",
      preparati.join() === "nuovo");

check("il tasto indietro chiude prima il foglio e poi torna a Guerra",
      backTo({ sheet: { kind: "base" } }, "clan") === "sheet"
      && backTo({}, "clan") === FIRST && backTo({}, FIRST) === null
      && backTo(null, FIRST) === null);

const fakePage = { scrollTop: 300 };
const listeners = {};
let sheetUp = null;
globalThis.document = { scrollingElement: fakePage,
                        querySelector: (what) => (what === ".sheet" ? sheetUp : null),
                        addEventListener: (kind, hand) => { listeners[kind] = hand; },
                        removeEventListener: (kind) => { delete listeners[kind]; } };
top();
check("il ritorno in cima azzera lo scorrimento", fakePage.scrollTop === 0);
const pulls = [];
const stopPull = pullDown(() => pulls.push("aggiorna"), TAP);
listeners.touchstart({ touches: [{ clientY: 10 }] });
listeners.touchmove({ touches: [{ clientY: 30 }] });
check("un trascinamento corto non chiede niente", pulls.length === 0);
listeners.touchmove({ touches: [{ clientY: 60 }] });
check("il trascina giu chiede lo stato", pulls.join() === "aggiorna");
listeners.touchmove({ touches: [{ clientY: 300 }] });
check("il trascina giu chiede lo stato una volta sola", pulls.length === 1);
stopPull();
check("il gesto si stacca", Object.keys(listeners).length === 0);
sheetUp = { tagName: "SECTION" };
const overSheet = [];
const stopSheet = pullDown(() => overSheet.push("aggiorna"), TAP);
listeners.touchstart({ touches: [{ clientY: 10 }] });
listeners.touchmove({ touches: [{ clientY: 300 }] });
check("col foglio aperto il trascinamento non chiede lo stato", overSheet.length === 0);
sheetUp = null;
listeners.touchstart({ touches: [{ clientY: 10 }] });
listeners.touchmove({ touches: [{ clientY: 300 }] });
check("chiuso il foglio il trascina giu torna a chiedere lo stato",
      overSheet.join() === "aggiorna");
stopSheet();
fakePage.scrollTop = 100;
const deep = [];
const stopDeep = pullDown(() => deep.push("mai"), TAP);
listeners.touchstart({ touches: [{ clientY: 10 }] });
listeners.touchmove({ touches: [{ clientY: 300 }] });
check("a meta pagina il trascinamento non chiede lo stato", deep.length === 0);
stopDeep();
check("senza distanza il gesto non si attacca",
      typeof pullDown(() => {}, 0) === "function" && Object.keys(listeners).length === 0);
delete globalThis.document;

const landed = [];
let lateCard = null;
const frames = [];
const beforeFrames = globalThis.requestAnimationFrame;
globalThis.document = { getElementById: (id) => (id === "chronicle" ? lateCard : null) };
globalThis.requestAnimationFrame = (step) => { frames.push(step); };
jump("chronicle");
check("il salto non chiama niente se la scheda non c'e ancora", landed.length === 0);
lateCard = { scrollIntoView: () => landed.push("chronicle") };
for (const step of frames.splice(0, frames.length)) { step(); }
check("il salto raggiunge la cronaca che compare col disegno dopo",
      landed.join() === "chronicle");
lateCard = { scrollIntoView: () => landed.push("subito") };
jump("chronicle");
check("la scheda gia disegnata si raggiunge senza aspettare il fotogramma",
      landed.join() === "chronicle,subito" && frames.length === 0);
globalThis.requestAnimationFrame = beforeFrames;
delete globalThis.document;

check("il passo legge la distanza dal token",
      pixels("44px") === 44 && pixels("") === 0 && pixels("2rem") === 0);
globalThis.getComputedStyle = () => ({
  getPropertyValue: (name) => (name === "--tap" ? "44px" : "200ms") });
check("la distanza del gesto e la durata del conto arrivano dal foglio",
      reach({}) === TAP && span({}) === 200);
delete globalThis.getComputedStyle;
check("senza foglio non c'e distanza ne durata", reach({}) === 0 && span({}) === 0);

check("il numero grande conta quando cambia",
      find(Big({ value: 7, label: "[l]" }), "big-value")[0].props["data-to"] === 7
      && find(Big({ value: "TH13", label: "[l]" }), "big-value")[0].props["data-to"] === null);
check("la tessera conta il suo numero",
      find(Tile({ big: 5, label: "[l]" }), "tile-big")[0].props["data-to"] === 5
      && find(Tile({ big: "AB", label: "[l]" }), "tile-big")[0].props["data-to"] === null);
check("l'anello conta il suo numero",
      find(Ring({ value: 3, total: 10, label: "[l]" }), "ring-value")[0].props["data-to"] === 3);
const cardBeats = [];
const cardNode = { dataset: {},
                   classList: { add: (one) => cardBeats.push(one), remove: () => {} } };
const carded = (mark) => Card({ mark: mark, children: null }).ref;
carded("2-0")(cardNode);
check("al primo giro la card non batte", cardBeats.length === 0);
carded("3-0")(cardNode);
check("la card batte quando le arriva uno stato nuovo", cardBeats.join() === "beat");
check("una card senza stato da guardare non batte", Card({ children: null }).ref === null);
check("la card di chi manca e quella della casella battono quando il numero cambia",
      typeof find(warTree, "missing")[0].ref === "function"
      && typeof find(views.manage(state, words, conf, kit({})), "inbox")[0].ref === "function");

const wipedKeys = { ["village-v" + VERSION]: "0/x" };
globalThis.window = { Telegram: { WebApp: phoneOf(wipedKeys) } };
const mePicks = [];
const meWipe = views.me(state, words, conf,
                        tools({ pick: (key, value) => mePicks.push([key, value]) }));
find(meWipe, "chip").filter((one) => text(one) === "[data_device]")
  .forEach((one) => one.props.onClick());
check("da Io si cancellano i dati sul dispositivo e si vede che e fatto",
      Object.keys(wipedKeys).length === 0
      && mePicks.filter((one) => one[0] === "toast").length === 1);
delete globalThis.window;

check("un vuoto porta il suo disegno",
      find(Empty({ text: "[t]", art: "nowar" }), "art").length === 1
      && find(Empty({ text: "[t]" }), "art").length === 0);
const emptied = [];
const box = Empty({ text: "[t]", art: "offline", action: "[a]",
                    onAction: () => emptied.push("fatto") });
find(box, "empty-do")[0].props.onClick();
check("un vuoto puo portare un'azione", emptied.length === 1);
check("la cronaca vuota mostra il disegno",
      find(chronicle({ people: { chronicle: [] } }, words, openTools), "art").length === 1);
for (const name of ["nocwl", "noinbox", "nobases", "nochronicle"]) {
  check("il disegno " + name + " e un svg del colore del testo",
        illustration(name).type === "svg" && illustration(name).props.stroke === "currentColor");
}

const headTaps = [];
const alone = head({ clan: { name: "Nostro Clan" }, clans: [{ slug: "a", name: "Nostro Clan" }] },
                   () => headTaps.push("apri"));
check("con un clan solo la testata non si tocca", alone.type === "div");
const many = head(state, () => headTaps.push("apri"));
check("con piu clan la testata si tocca", many.type === "button");
many.props.onClick();
check("la testata apre il foglio dei clan", headTaps.length === 1);
const swapped = [];
const clanBox = clanSheet(state, words, state.clans[0].slug, (next) => swapped.push(next));
check("il foglio porta un riquadro per clan",
      find(clanBox, "tile").length === state.clans.length);
check("il clan di adesso e segnato",
      String(find(clanBox, "tile")[0].props.class).includes("on"));
find(clanBox, "tile")[1].props.onClick();
check("toccare un clan cambia lo slug", swapped[0] === state.clans[1].slug);

const recapRuns = [];
const recapPicks = [];
const recapTools = { run: (kind) => { recapRuns.push(kind); return true; }, now: state.updated,
                     local: {}, pick: (name, value) => recapPicks.push([name, value]) };
const season = recapScreens(state, said, conf, recapTools);
check("il riepilogo rende schermate con numeri grandi e anello",
      find(season, "screens").length === 1 && find(season, "big").length >= 3
      && find(season, "ring").length === 1);
check("il riepilogo mostra le medaglie della stagione",
      find(season, "medal").length === state.recap.me.medals.length);
const recapChips = find(season, "chip");
recapChips[0].props.onClick();
recapChips[recapChips.length - 1].props.onClick();
check("il riepilogo si condivide come stagione e si chiude",
      recapRuns[0] === "share.season" && recapPicks[0][0] === "recap"
      && recapPicks[0][1] === DONE);
const guest = recapScreens({ recap: { season: "2026-08", me: null, clan: state.recap.clan } },
                           said, conf, recapTools);
check("senza posto resta il riepilogo del clan",
      find(guest, "big").length === 2 && find(guest, "ring").length === 0);
check("senza stagione chiusa non si mostra niente",
      recapScreens({}, said, conf, recapTools) === null);

const gated = [];
const alive = gate(false, (kind) => { gated.push(kind); return true; });
check("da accesi il gesto passa", alive("goal.set") === true && gated[0] === "goal.set");
const stopped = gate(true, (kind) => { gated.push(kind); return true; },
                     (kind) => { gated.push("coda:" + kind); return false; });
check("da spenti il gesto non parte ma resta in coda",
      stopped("goal.set") === false && gated[1] === "coda:goal.set");
check("da spenti non c'e bottone principale",
      primary(state, "war", true, said, conf, {}) === null);
check("da accesi il bottone principale c'e",
      Boolean(primary(state, "war", false, said, conf, {})));
check("senza stato niente bottone principale",
      primary(null, "war", false, said, conf, {}) === null);

const inRow = (tree, name) => find(tree, "row").some((one) => text(one).includes(name));
const inTile = (tree, name) => find(tree, "tile").some((one) => text(one).includes(name));
const cardsWith = (tree, label) => find(tree, "item")
  .filter((one) => find(one, "chip").some((chip) => text(chip) === label));
const rowsWith = (tree, label) => find(tree, "row")
  .filter((one) => find(one, "chip").some((chip) => text(chip) === label));
const hitRow = view.enemy[0].history[0];
const clipRow = state.attack_videos[String(view.enemy[0].th)][0];
const bestRow = state.advice[String(view.enemy[0].th)].best[0];
check("i colpi sulla base sono tessere, non righe",
      inTile(basePaper, hitRow.name) && !inRow(basePaper, hitRow.name));
check("i migliori del municipio sono tessere, non righe",
      inTile(basePaper, String(bestRow.stars)) && !inRow(basePaper, String(bestRow.stars)));
check("il video del municipio e una tessera che apre il canale",
      find(basePaper, "tile").some((one) => text(one).includes(clipRow.title)
                                            && String(one.props.href).includes(clipRow.video_id)));
const staffTree = staffBoss({});
check("il posto sospeso si riattiva da una card, non da una riga",
      cardsWith(staffTree, "[manage_lift]").length === 1
      && text(cardsWith(staffTree, "[manage_lift]")[0])
           .includes(state.manage_view.suspended[0].name)
      && rowsWith(staffTree, "[manage_lift]").length === 0);
check("la delega si da e si toglie da una card, non da una riga",
      cardsWith(staffTree, "[manage_delegate_on]").length === state.manage_view.people.length
      && cardsWith(staffTree, "[manage_delegate_off]").length
         === state.manage_view.delegates.length
      && rowsWith(staffTree, "[manage_delegate_on]").length === 0
      && rowsWith(staffTree, "[manage_delegate_off]").length === 0);
check("l'ammonizione si toglie da una card, non da una riga",
      cardsWith(staffTree, "[manage_void]").length === state.me.tools.wars.warnings.length
      && rowsWith(staffTree, "[manage_void]").length === 0);
check("il villaggio collegato e una card con il suo stato",
      cardsWith(meTree, "[link_drop]").length === state.me_view.villages.length
      && text(cardsWith(meTree, "[link_drop]")[0]).includes(state.me_view.villages[0].tag)
      && text(cardsWith(meTree, "[link_drop]")[0]).includes("[me_claimed]")
      && !inRow(meTree, state.me_view.villages[0].tag));

const bootSource = readFileSync(
  new URL("../../clashbot/web/static/app/boot.js", import.meta.url), "utf8");

function bootRun(dataset, initData) {
  const asked = [];
  const opened = [];
  const hears = {};
  const scope = {
    document: { getElementById: (id) => (id === "app" ? { dataset } : null) },
    fetch: (path, options) => {
      asked.push([path, options]);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ me: { tag: "#P1" } }) });
    },
    EventSource: function (url) {
      opened.push(url);
      this.addEventListener = (name, fn) => { hears[name] = fn; };
    },
    encodeURIComponent,
    Telegram: initData === null ? undefined : { WebApp: { initData } },
  };
  scope.window = scope;
  runInNewContext(bootSource, scope);
  return { scope, asked, opened, hears };
}

const bootOn = bootRun({ slug: "x", live: "/app/x/live" }, "sig");
check("l'avvio chiede lo stato firmato senza aspettare i moduli",
      bootOn.asked.length === 1 && bootOn.asked[0][0] === "/app/x/state"
      && bootOn.asked[0][1].headers["X-Init-Data"] === "sig");
check("l'avvio apre subito il canale vivo",
      bootOn.opened.length === 1 && bootOn.opened[0] === "/app/x/live?init=sig");
check("l'avvio lascia stato, sorgente e coda a chi arriva dopo",
      typeof bootOn.scope.clanboardBoot.state.then === "function"
      && Boolean(bootOn.scope.clanboardBoot.source)
      && bootOn.scope.clanboardBoot.events.length === 0);
check("lo stato chiesto dall'avvio arriva gia letto",
      (await bootOn.scope.clanboardBoot.state).me.tag === "#P1");
bootOn.hears.state({ data: JSON.stringify({ me: { tag: "#P3" } }) });
check("gli eventi arrivati prima dei moduli restano in coda",
      bootOn.scope.clanboardBoot.events.length === 1
      && bootOn.scope.clanboardBoot.events[0].me.tag === "#P3");
const queued = bootOn.scope.clanboardBoot;
bootOn.scope.window.clanboardBoot = null;
bootOn.hears.state({ data: JSON.stringify({ me: { tag: "#P9" } }) });
check("dopo l'aggancio la coda dell'avvio non cresce piu",
      queued.events.length === 1 && bootOn.asked.length === 1);

const bootBare = bootRun({ slug: "x", live: "/app/x/live" }, null);
check("fuori da Telegram l'avvio parte lo stesso senza firma",
      bootBare.opened[0] === "/app/x/live?init="
      && bootBare.asked[0][1].headers["X-Init-Data"] === "");

const bootNone = bootRun({ slug: "", live: "" }, "sig");
check("senza clan l'avvio non chiede niente",
      bootNone.asked.length === 0 && bootNone.opened.length === 0
      && bootNone.scope.clanboardBoot === undefined);

const heard = [];
const fell = [];
const openChannel = { readyState: 0, addEventListener(name, fn) { this[name] = fn; } };
const joined = adopt(openChannel, (found) => heard.push(found), () => fell.push(1));
openChannel.state({ data: JSON.stringify({ me: { tag: "#P5" } }) });
openChannel.onerror();
check("agganciarsi a un canale gia aperto porta lo stato",
      joined === openChannel && heard[0].me.tag === "#P5");
check("un errore mentre si riconnette non spegne l'app", fell.length === 0);
const closedDown = [];
adopt({ readyState: 2, addEventListener() {} }, () => {}, () => closedDown.push(1));
check("un canale gia chiuso risulta giu appena ci si aggancia", closedDown.length === 1);

const GIRI_TIMER = 1000;
const SENZA_FINE = "timer senza fine";

function tempoFinto() {
  const veroSet = globalThis.setTimeout;
  const veroClear = globalThis.clearTimeout;
  const attese = [];
  let adesso = 0;
  globalThis.setTimeout = (fn, ms) => attese.push({ fn, quando: adesso + (ms || 0) });
  globalThis.clearTimeout = (id) => {
    const uno = attese[id - 1];
    if (uno) { uno.fn = null; }
  };
  return {
    avanza(ms) {
      adesso += ms;
      for (let giro = 0; giro < GIRI_TIMER; giro += 1) {
        const uno = attese.find((altro) => altro.fn && altro.quando <= adesso);
        if (!uno) { return; }
        const chiamata = uno.fn;
        uno.fn = null;
        chiamata();
      }
      throw new Error(SENZA_FINE);
    },
    basta() {
      globalThis.setTimeout = veroSet;
      globalThis.clearTimeout = veroClear;
    },
  };
}

const BEAT_MS = 20;
const late = [];
const slowChannel = { readyState: 0, addEventListener(name, fn) { this[name] = fn; } };
const orologio = tempoFinto();
adopt(slowChannel, () => {}, () => late.push(1), (2 * BEAT_MS) / 1000);
orologio.avanza(BEAT_MS + BEAT_MS / 2);
slowChannel.ping();
check("un solo battito mancato non manda giu il canale", late.length === 0);
orologio.avanza(3 * BEAT_MS);
check("due battiti mancati mandano giu il canale", late.length === 1);
orologio.avanza(10 * BEAT_MS);
check("dopo il battito mancato il canale non cade due volte", late.length === 1);
orologio.basta();

const chiusi = [];
const chiuso = { readyState: 0, addEventListener(name, fn) { this[name] = fn; } };
const orologio2 = tempoFinto();
adopt(chiuso, () => {}, () => chiusi.push(1), (2 * BEAT_MS) / 1000);
chiuso.readyState = 2;
orologio2.avanza(10 * BEAT_MS);
check("il timer di una sorgente chiusa non manda giu l'app nuova", chiusi.length === 0);
orologio2.basta();

const su = [];
const giu = [];
const tornato = { readyState: 0, addEventListener(name, fn) { this[name] = fn; } };
const orologio3 = tempoFinto();
adopt(tornato, () => {}, () => giu.push(1), (2 * BEAT_MS) / 1000, () => su.push(1));
orologio3.avanza(3 * BEAT_MS);
tornato.ping();
check("un battito dopo la caduta riporta su l'app", giu.length === 1 && su.length === 1);
orologio3.basta();

const senzaFine = tempoFinto();
let giri = 0;
const ripeti = () => { giri += 1; globalThis.setTimeout(ripeti, 0); };
globalThis.setTimeout(ripeti, 0);
let scoppio = "";
try { senzaFine.avanza(1); } catch (errore) { scoppio = String(errore.message || errore); }
senzaFine.basta();
check("un timer che si riprogramma da solo ferma l'orologio finto invece di girare per sempre",
      scoppio === SENZA_FINE && giri === GIRI_TIMER);

const MARKS = { "target.set": ["pos"], "target.note": ["pos"], "prediction.set": ["poll"],
                "duel.challenge": ["rival"], "base.propose": ["link"], "schedule.add": ["hhmm"],
                "settings.press": ["data"], "family.derby": ["data"], "family.tourney": ["data"],
                "undo.apply": ["of", "ref"], "share.week": [], "goal.set": [] };
const park = (rows, kind, extra, id) => hold(rows, MARKS, { kind, extra, id });
const parcheggio = park(park([], "target.set", { pos: "3", who: "1" }, "i1"), "target.note",
                        { pos: "3", text: "piano" }, "i2");
check("la coda tiene un tocco per kind e bersaglio", parcheggio.length === 2);
const again = park(parcheggio, "target.set", { pos: "3", who: "9" }, "i3");
check("sullo stesso bersaglio vince l'ultimo",
      again.length === 2 && again[again.length - 1].extra.who === "9");
const treQueued = park(again, "target.set", { pos: "4", who: "1" }, "i4");
check("bersagli diversi stanno in coda tutti e due", treQueued.length === 3);
check("la coda parte nell'ordine in cui e nata",
      treQueued.map((one) => one.key).join("|")
      === "target.note:3|target.set:3|target.set:4");
check("la chiave del bersaglio viene dai campi dichiarati del gesto",
      keyOf(MARKS, "undo.apply", { of: "warning", ref: "7" }) === "undo.apply:warning:7"
      && keyOf(MARKS, "share.week", {}) === "share.week"
      && keyOf(MARKS, "target.set", {}) === "target.set:");
const sondaggi = park(park([], "prediction.set", { poll: "war", option: "1" }, "s1"),
                      "prediction.set", { poll: "cwl", option: "1" }, "s2");
check("due sondaggi diversi restano due tocchi", sondaggi.length === 2);
const stesso = park(sondaggi, "prediction.set", { poll: "war", option: "2" }, "s3");
check("sullo stesso sondaggio vince l'ultimo",
      stesso.length === 2 && stesso[1].extra.option === "2" && stesso[1].extra.poll === "war");
const sfide = park(park([], "duel.challenge", { rival: "#A", metric: "loot" }, "d1"),
                   "duel.challenge", { rival: "#B", metric: "loot" }, "d2");
check("due rivali diversi restano due sfide", sfide.length === 2);
const doppi = [["base.propose", { link: "uno", label: "war" }, { link: "due", label: "war" }],
               ["schedule.add", { hhmm: "0900" }, { hhmm: "2100" }],
               ["settings.press", { data: "cfg:a:b" }, { data: "cfg:c:d" }],
               ["family.derby", { data: "dy:a" }, { data: "dy:b" }],
               ["family.tourney", { data: "tr:a" }, { data: "tr:b" }]];
check("ogni bersaglio nuovo resta in coda da solo",
      doppi.every(([kind, uno, due]) => park(park([], kind, uno, "p1"), kind, due, "p2")
        .length === 2));
check("il gesto senza bersaglio tiene una voce sola",
      park(park([], "share.week", {}, "w1"), "share.week", {}, "w2").length === 1);
check("la coda porta l'id coniato al parcheggio",
      parcheggio[0].id === "i1" && again[again.length - 1].id === "i3");

const spediti = [];
const andati = [];
await flush(treQueued, (one) => { spediti.push([one.kind, one.extra.pos, one.id]); },
            (fatti) => andati.push(fatti), () => false);
check("la coda parte in ordine e ogni tocco porta il suo id",
      spediti.map((one) => one.join(":")).join("|")
      === "target.note:3:i2|target.set:3:i3|target.set:4:i4");
check("svuotata la coda esce tutta, gesto per gesto",
      andati.length === 1 && andati[0].join("|") === "i2|i3|i4");
const mandati = [];
const tolti = [];
let caduto = false;
await flush(treQueued, (one) => { mandati.push(one.key); caduto = true; },
            (fatti) => tolti.push(fatti), () => caduto);
check("il canale che ricade ferma la coda dopo il tocco in corso", mandati.length === 1);
check("quello che e partito esce dalla coda anche se il canale ricade",
      tolti.length === 1 && tolti[0].join("|") === "i2");
const fermi = [];
const restati = [];
await flush(treQueued, (one) => fermi.push(one.key), (fatti) => restati.push(fatti),
            () => true);
check("col canale gia giu nessun tocco parte e la coda resta intera",
      fermi.length === 0 && restati.length === 1 && restati[0].length === 0);

const respiro = () => new Promise((torna) => setTimeout(torna, 0));
const guardia = { busy: false };
const mai = [];
const fermo = (one) => mai.push(one.key);
check("col canale giu la coda non parte",
      pump(guardia, true, treQueued, fermo, () => {}) === undefined
      && mai.length === 0 && guardia.busy === false);
check("senza niente in coda non parte niente",
      pump(guardia, false, [], fermo, () => {}) === undefined
      && pump(guardia, false, null, fermo, () => {}) === undefined && mai.length === 0);
const usciti = [];
const rientrati = [];
let riprovato = false;
const rientra = async (one) => {
  usciti.push(one.key);
  if (!riprovato) {
    riprovato = true;
    rientrati.push(pump(guardia, false, treQueued, rientra, () => {}));
  }
};
const svuotate = [];
const stacca = pump(guardia, false, treQueued, rientra, (fatti) => svuotate.push(fatti));
await respiro();
check("mentre la coda sta partendo un secondo giro non rispedisce niente",
      typeof stacca === "function" && rientrati.length === 1
      && rientrati[0] === undefined
      && usciti.join("|") === "target.note:3|target.set:3|target.set:4");
check("finito l'invio la guardia si riapre",
      svuotate.length === 1 && guardia.busy === false);
let liberaAlKeep = null;
const seconda = { busy: false };
pump(seconda, false, treQueued, () => {}, () => { liberaAlKeep = seconda.busy; });
await respiro();
check("la guardia si apre prima di aggiornare la coda, cosi il giro dopo parte",
      liberaAlKeep === false);
const scoppiata = { busy: false };
const rumore = () => {};
process.on("unhandledRejection", rumore);
pump(scoppiata, false, treQueued, () => { throw new Error("rotto"); }, () => {});
await respiro();
process.off("unhandledRejection", rumore);
check("se l'invio scoppia la guardia si riapre lo stesso", scoppiata.busy === false);
const terza = { busy: false };
const partiti = [];
const staccata = pump(terza, false, treQueued, async (one) => { partiti.push(one.key); },
                      () => {});
staccata();
await respiro();
check("staccato l'effetto la coda si ferma dopo il tocco in corso", partiti.length === 1);

const banco = { rows: [], down: false, dep: null, stacca: null };
const latchQ = { busy: false };
const partitiQ = [];
const rispostaQ = [];
const inviaFermo = (one) => new Promise((torna) => {
  partitiQ.push(one.id);
  rispostaQ.push(torna);
});
const effetto = () => {
  const dep = String(banco.down) + "|" + banco.rows.length;
  if (dep === banco.dep) { return; }
  banco.dep = dep;
  if (banco.stacca) { banco.stacca(); }
  banco.stacca = pump(latchQ, banco.down, banco.rows, inviaFermo,
                      (fatti) => { banco.rows = drop(banco.rows, fatti); });
};
const tocca = (id) => {
  banco.rows = hold(banco.rows, MARKS, { kind: "target.set", extra: { pos: "4" }, id });
  effetto();
};
const canale = (giu) => { banco.down = giu; effetto(); };
canale(true);
tocca("q1");
canale(false);
await respiro();
canale(true);
tocca("q2");
rispostaQ[0]();
await respiro();
effetto();
canale(false);
await respiro();
check("il tocco parcheggiato mentre il primo e in volo non sparisce dalla coda",
      partitiQ.join("|") === "q1|q2");
rispostaQ.forEach((torna) => torna());
await respiro();
effetto();
check("finito il rinvio la coda resta vuota e la guardia aperta",
      banco.rows.length === 0 && latchQ.busy === false);
check("esce dalla coda il gesto partito, non il bersaglio",
      drop([{ key: "target.set:4", id: "q1" }, { key: "target.set:3", id: "q3" }], ["q1"])
        .map((row) => row.id).join("|") === "q3");

const rotture = [];
const nota = (errore) => rotture.push(String((errore && errore.message) || errore));
process.on("unhandledRejection", nota);
const quarta = { busy: false };
const restatiQ = [];
pump(quarta, false, treQueued, async (one) => {
  if (one.key === "target.set:3") { throw new Error("rete giu"); }
}, (fatti) => restatiQ.push(fatti));
await respiro();
await respiro();
process.off("unhandledRejection", nota);
check("se l'invio scoppia il rifiuto non resta senza padrone",
      rotture.join("|") === "");
check("se l'invio scoppia quello che era gia partito esce comunque dalla coda",
      restatiQ.length === 1 && restatiQ[0].join("|") === "i2");

const parked = [];
const closedGate = gate(true, () => true,
                        (kind, extra) => { parked.push([kind, extra]); return false; });
check("da spenti il tocco va in coda, non sparisce",
      closedGate("goal.set", { goal: "trophies" }) === false && parked.length === 1);
const waitBand = banner(state, Object.assign({}, offWords, { queued: "in coda" }),
                        state.updated, () => {}, 2);
check("da spenti con la coda la striscia dice in coda",
      text(waitBand).includes("in coda") && find(waitBand, "strip-do").length === 1);

const PLAIN = ["share.war", "share.week", "share.clan", "share.season",
               "settings.press", "settings.open", "award.vote", "report.send",
               "family.create", "family.invite", "family.derby", "family.tourney"];
const WATCH = {
  "target.set": (one) => JSON.stringify([(one.war_view.mine || {}).target,
                                         one.war_view.enemy.map((row) => row.assignee)]),
  "target.free": (one) => JSON.stringify([(one.war_view.mine || {}).target,
                                          one.war_view.enemy.map((row) => row.assignee)]),
  "target.mirror": (one) => JSON.stringify((one.war_view.mine || {}).target),
  "target.clear": (one) => JSON.stringify([(one.war_view.mine || {}).target,
                                           one.war_view.enemy.map((row) => row.assignee)]),
  "target.note": (one) => JSON.stringify(one.war_view.enemy.map((row) => row.note)),
  "target.swap": (one) => JSON.stringify(one.war_view.enemy.map((row) => row.swap_pending)),
  "cwl.roster.set": (one) => JSON.stringify(one.cwl.lineup),
  "cwl.lineup.set": (one) => JSON.stringify(one.cwl.lineup),
  "cwl.bonus.toggle": (one) => JSON.stringify(one.cwl.lineup),
  "link.whisper": (one) => String((one.me_view || {}).whisper),
  "link.verify": (one) => JSON.stringify([(one.me_view || {}).verified,
                                          (one.me_view || {}).villages]),
  "link.drop": (one) => JSON.stringify((one.me_view || {}).villages),
  "data.forget": (one) => JSON.stringify([(one.me_view || {}).tag, (one.me_view || {}).villages]),
  "availability.set": (one) => String((one.me_view || {}).avail),
  "goal.set": (one) => JSON.stringify((one.me_view || {}).goal),
  "lang.set": (one) => String((one.me_view || {}).lang),
  "quiz.answer": (one) => JSON.stringify(one.todo),
  "guess.answer": (one) => JSON.stringify((one.more_view || {}).guess),
  "prediction.set": (one) => JSON.stringify(one.todo),
  "duel.accept": (one) => JSON.stringify(one.todo),
  "duel.challenge": (one) => JSON.stringify(one.more_view.duels),
  "base.propose": (one) => JSON.stringify((one.bases || {}).clan),
  "note.set": (one) => JSON.stringify(one.me.tools.leaders.notes),
  "warning.confirm": (one) => JSON.stringify(one.inbox.warnings),
  "warning.void": (one) => JSON.stringify(one.me.tools.wars.warnings),
  "person.approve": (one) => JSON.stringify(one.inbox.pending),
  "person.revoke": (one) => JSON.stringify(one.manage_view.approved),
  "person.trust": (one) => JSON.stringify(one.manage_view.approved),
  "application.decide": (one) => JSON.stringify(one.inbox.applications),
  "base.accept": (one) => JSON.stringify(one.inbox.bases),
  "base.reject": (one) => JSON.stringify(one.inbox.bases),
  "gate.toggle": (one) => String(one.me.tools.leaders.gate),
  "page.toggle": (one) => String(one.manage_view.page_on),
  "clan.pause": (one) => String(one.manage_view.paused),
  "clan.resume": (one) => String(one.manage_view.paused),
  "delegate.add": (one) => JSON.stringify([one.manage_view.delegates, one.manage_view.people]),
  "delegate.remove": (one) => JSON.stringify([one.manage_view.delegates, one.manage_view.people]),
  "delegates.clear": (one) => JSON.stringify(one.manage_view.delegates),
  "suspension.lift": (one) => JSON.stringify(one.manage_view.suspended),
  "undo.apply": (one) => JSON.stringify(one.manage_view.log),
  "schedule.add": (one) => JSON.stringify(one.manage_view.schedules),
  "schedule.delete": (one) => JSON.stringify(one.manage_view.schedules),
  "welcome.set": (one) => JSON.stringify(one.manage_view.texts),
  "rules.set": (one) => JSON.stringify(one.manage_view.texts),
  "channel.add": (one) => JSON.stringify(one.manage_view.channels),
  "channel.drop": (one) => JSON.stringify(one.manage_view.channels),
  "recruit.requirements.set": (one) => String(one.manage_view.recruit.th),
  "sender.block": (one) => JSON.stringify(one.inbox.applications),
  "sender.unblock": (one) => JSON.stringify(one.manage_view.recruit.blocked),
  "integration.twitch": (one) => String(one.manage_view.integrations.twitch),
  "integration.discord": (one) => String(one.manage_view.integrations.discord),
  "integration.ics": (one) => String(one.manage_view.integrations.ics),
  "view.set": (one) => JSON.stringify(one.views),
  "family.score.toggle": (one) => String((one.views || {}).family_score),
};
const quickRuns = [];
const quickKit = (found, local) => ({
  run: async (kind, extra, made) => { quickRuns.push([kind, extra, made, found]); return true; },
  now: 0, local: local || {}, pick() {},
});

function quickValues(node, out = []) {
  if (!node || typeof node !== "object") { return out; }
  if (Array.isArray(node)) { node.forEach((one) => quickValues(one, out)); return out; }
  const props = node.props || {};
  if (node.type === "option" && props.value) { out.push(props.value); }
  return quickValues(props.children, out);
}

function quickPress(node) {
  if (!node || typeof node !== "object") { return; }
  if (Array.isArray(node)) { node.forEach(quickPress); return; }
  if (typeof node.type === "function") { quickPress(node.type(node.props || {})); return; }
  const props = node.props || {};
  if (typeof props.onClick === "function" && !props.disabled) { props.onClick(); }
  if (typeof props.onChange === "function") {
    const values = quickValues(props.children);
    if (values.length) { props.onChange({ target: { value: values[0] } }); }
  }
  quickPress(props.children);
}

const pollAsk = { kind: "prediction", poll: "war", options: ["noi", "loro"] };
const everyTodo = Object.assign({}, noWar, {
  todo: [quizWait, pollAsk, { kind: "duel", id: "ab12", rival: "#P2" }] });
const knownFaces = Object.assign({}, nobody, {
  me_view: Object.assign({}, nobody.me_view, { candidates: CANDIDATI }) });
const settingsBoss = Object.assign({}, state, {
  me: Object.assign({}, state.me, {
    manage: Object.assign({}, state.me.manage, {
      settings: { text: "Passo", buttons: [[{ label: "Avanti", data: "cfg:a:b" }]] } }) }) });
const warned = state.inbox.warnings[0];
const onMate = { sheet: { kind: "base", pos: view.enemy[0].pos },
                 plan: { pos: view.enemy[0].pos, text: "prima le regine" } };
const quickScenes = [
  [views.war, state, { whisper_asked: "" }],
  [views.war, booked, {}],
  [views.war, state, onMate],
  [views.war, state, { sheet: { kind: "base", pos: view.free[0].pos } }],
  [views.war, prep, onMate],
  [views.war, over, {}],
  [views.war, everyTodo, {}],
  [views.war, everyTodo, { sheet: quizWait }],
  [views.war, everyTodo, { sheet: pollAsk }],
  [views.war, inLeague, { sheet: { kind: "cwl_seat", tag: league.lineup[0].tag } }],
  [views.war, inLeague, { sheet: { kind: "cwl_seat", tag: league.lineup[1].tag } }],
  [views.me, state, {}],
  [views.me, state, { sheet: { kind: "goal" } }],
  [views.me, state, { forget: true }],
  [views.me, knownFaces, {}],
  [views.clan, state, { sheet: { kind: "person", tag: warned.tag },
                        note: { tag: warned.tag, text: "occhio" } }],
  [views.more, wide, { more: "games", sheet: { kind: "duel" } }],
  [views.more, wide, { more: "games", sheet: { kind: "guess" } }],
  [views.more, wide, { more: "games", sheet: { kind: "prediction" } }],
  [views.more, wide, { more: "games", sheet: { kind: "award" } }],
  [views.more, wide, { more: "games" }],
  [views.more, wide, { more: "bases" }],
  [views.more, wide, { more: "help", sheet: { kind: "report" } }],
  [views.manage, settingsBoss, {}],
  [views.manage, settingsBoss, { sheet: { kind: "schedule" }, hhmm: "21:15", days: "12",
                                 sched_text: "Ci siamo" }],
  [views.manage, settingsBoss, { sheet: { kind: "texts", field: "welcome" },
                                 text: "Ciao a tutti" }],
  [views.manage, settingsBoss, { sheet: { kind: "texts", field: "rules" },
                                 text: "Regole nuove" }],
  [views.manage, settingsBoss, { channel: "UCbbbbbbbbbbbbbbbbbbbbbb" }],
  [views.manage, settingsBoss, { twitch: "nuovo" }],
  [views.manage, settingsBoss, { sheet: { kind: "derby" } }],
  [views.manage, settingsBoss, { sheet: { kind: "tourney" } }],
  [views.manage, familyless, { family_name: "Nuova", family_code: "fam2" }],
  [views.manage, withBase, {}],
  [recapScreens, state, {}],
];
quickScenes.forEach(([show, found, local]) => {
  quickPress(show(found, words, conf, quickKit(found, local)));
});
const quickArmed = (kind, extra) => ({ confirm: { kind: kind, extra: extra || {} } });
const quickTops = [
  [primaries.war, state, {}],
  [primaries.me, nobody, { tag: "#ABC123", token: "abc123" }],
  [primaries.me, state, { token: "abc123" }],
  [primaries.more, wide, { sheet: { kind: "duel" },
                           duel: { rival: "#P2", metric: "loot", duration: "week" } }],
  [primaries.more, wide, { sheet: { kind: "guess" }, guess: { stars: 2, percent: 60 } }],
  [primaries.manage, state, quickArmed("clan.pause")],
  [primaries.manage, paused, quickArmed("clan.resume")],
  [primaries.manage, state, quickArmed("delegates.clear")],
  [primaries.manage, backable, quickArmed("undo.apply", { of: "settings", ref: "prev" })],
];
quickTops.forEach(([make, found, local]) => {
  const top = make(found, words, conf, local);
  if (!top) {
    failed.push("manca il bottone principale di " + JSON.stringify(local));
    return;
  }
  quickRuns.push([top.kind, top.extra, top.optimistic, found]);
});
const quickSeen = quickRuns.map((one) => one[0]);
check("ogni gesto o anticipa lo schermo o e dichiarato senza effetto",
      quickSeen.every((kind) => PLAIN.includes(kind) || Boolean(WATCH[kind])));
check("ogni gesto che cambia qualcosa e stato toccato in almeno una schermata",
      Object.keys(WATCH).every((kind) => quickSeen.includes(kind)));
check("anche i gesti senza effetto sono stati toccati",
      PLAIN.every((kind) => quickSeen.includes(kind)));
const quickMoved = {};
quickRuns.forEach(([kind, , made, found]) => {
  if (PLAIN.includes(kind)) {
    check("il gesto " + kind + " non finge niente", !made);
    return;
  }
  if (typeof made !== "function") {
    failed.push("il gesto " + kind + " non aggiorna lo schermo subito");
    return;
  }
  const before = JSON.stringify(found);
  const after = made(found);
  check("il gesto " + kind + " lascia uno stato nuovo", Boolean(after) && after !== found);
  check("il gesto " + kind + " lascia intatto lo stato di prima",
        JSON.stringify(found) === before);
  if (WATCH[kind] && WATCH[kind](after) !== WATCH[kind](found)) { quickMoved[kind] = true; }
});
const quickStill = Object.keys(WATCH).filter((kind) => !quickMoved[kind]);
check("ogni gesto porta il suo campo sullo schermo prima della risposta: " + quickStill.join(),
      quickStill.length === 0);

function quickOnce(show, found, local, take) {
  const runs = [];
  const tree = show(found, words, conf, {
    run: async (kind, extra, made) => { runs.push(made); return true; },
    now: 0, local: local || {}, pick() {},
  });
  take(tree);
  return runs[0] ? runs[0](found) : found;
}

const quickMine = quickOnce(views.war, state, {},
                            (tree) => find(find(tree, "chips")[0], "chip")[0].props.onClick());
const quickChips = find(find(views.war(quickMine, words, conf, tools({})), "chips")[0], "chip");
check("prenotata, la casella diventa mia e i chip liberi si spengono",
      String(find(views.war(quickMine, words, conf, tools({})), "tile")[view.free[0].pos - 1]
        .props.class).includes("mine")
      && quickChips.filter((one) => one.props.disabled).length === view.free.length);
check("prenotata, la casella porta subito il mio nome e il piano da scrivere",
      find(views.war(quickMine, words, conf,
                     tools({ local: { sheet: { kind: "base", pos: view.free[0].pos } } })),
           "note").length === 1
      && find(views.war(state, words, conf,
                        tools({ local: { sheet: { kind: "base", pos: view.free[0].pos } } })),
              "note").length === 0);
const quickAsked = quickOnce(views.war, state, { sheet: { kind: "base", pos: view.enemy[0].pos } },
                             (tree) => chipOf(find(tree, "sheet")[0], "war_swap").props.onClick());
check("chiesto il cambio, la tessera porta subito il suo segno",
      find(views.war(quickAsked, words, conf, tools({})), "dot").length === 1
      && find(warTree, "dot").length === 0);
const quickSpot = { sheet: { kind: "base", pos: view.free[0].pos } };
const quickBack = quickOnce(views.war, quickMine, {},
                            (tree) => find(find(tree, "chips")[0], "chip")[0].props.onClick());
const quickBackSheet = find(views.war(quickBack, words, conf, tools({ local: quickSpot })),
                            "sheet")[0];
check("liberata, la casella torna libera prima della risposta",
      String(enemyTiles(views.war(quickBack, words, conf, tools({})))[view.free[0].pos - 1]
        .props.class).includes("free")
      && chipOf(quickBackSheet, "war_book") !== undefined
      && chipOf(quickBackSheet, "war_swap") === undefined);
const quickNoted = quickOnce(views.war, booked, onMineSheet,
                             (tree) => chipOf(find(tree, "sheet")[0],
                                              "war_release").props.onClick());
check("liberata dal foglio, la casella non tiene piano ne segno di chi la teneva",
      quickNoted.war_view.enemy[0].assignee === null
      && quickNoted.war_view.enemy[0].note === null
      && quickNoted.war_view.enemy[0].swap_pending === false
      && view.enemy[0].note === state.war_view.enemy[0].note);
const quickLess = quickOnce(views.manage, state, {},
                            (tree) => inside(tree, "[manage_now]")[0].props.onClick());
check("decisa, la voce della casella sparisce prima della risposta",
      pendingOf(quickLess) === pendingOf(state) - 1
      && find(only(views.manage(quickLess, words, conf, kit({})), "inbox"), "item").length
         === pendingOf(state) - 1);

const TOCCABILI = ["button", "a"];
for (const name of Object.keys(views)) {
  const spots = every(views[name](state, words, conf, tools({})))
    .filter((one) => one.props && typeof one.props.onClick === "function");
  const wrong = spots.filter((one) => !TOCCABILI.includes(one.type));
  check("in " + name + " si tocca solo un bottone o un collegamento: "
        + wrong.map((one) => String(one.type)).join(),
        spots.length > 0 && wrong.length === 0);
}

if (failed.length) {
  console.log("FALLITI:\n" + failed.join("\n"));
  process.exit(1);
}
console.log("ok " + Object.keys(views).length + " viste");
