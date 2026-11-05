const CONF = window.PROVA;
const FRAME = document.getElementById("f");
const STEP = 40;
const CAP = 60;
const MIN = 3;
const QUIET = 2;
const MOSTRA = 5;
const TETTO = 20;
const SEL = "button, a[href], [role=button], input, select, textarea, summary";
const NAV = ".tabs button";
const PRONTO = ".tabs, .screens";
const FOGLIO = ".sheet, dialog[open], [role=dialog]";
const OROLOGIO = ".clock, .seen";
const STRISCIA = ".strip span";
const RIPROVA = ".strip-do";
const CADUTO = "cade";
const RUMORE = /viewport|safe_area|theme_changed|ready|expand|setup_|request_/;
const ETICHETTA = 48;
const CLASSE = 40;
const TESTO = 160;
const SCATOLE = ["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA"];
const THEME = { bg_color: "#17212b", text_color: "#f5f5f5", hint_color: "#708499",
                link_color: "#6ab3f3", button_color: "#5288c1", button_text_color: "#ffffff",
                secondary_bg_color: "#232e3c", section_bg_color: "#17212b",
                header_bg_color: "#17212b", accent_text_color: "#6ab3f3",
                destructive_text_color: "#ec3942" };

const PERSONA = { id: 1, first_name: "Prova", language_code: CONF.lingua };
const DATI = "user=" + encodeURIComponent(JSON.stringify(PERSONA)) + "&auth_date=1&hash=x";
const HASH = "#tgWebAppData=" + encodeURIComponent(DATI)
  + "&tgWebAppVersion=" + CONF.versione + "&tgWebAppPlatform=ios"
  + "&tgWebAppThemeParams=" + encodeURIComponent(JSON.stringify(THEME));

const store = {};
const detti = [];
let giro = 0;

function sonno(ms) {
  return new Promise((torna) => setTimeout(torna, ms));
}

function rispondi(tipo, dati) {
  FRAME.contentWindow.postMessage(JSON.stringify({ eventType: tipo, eventData: dati }), "*");
}

function magazzino(dati) {
  const chiesto = dati.params || {};
  if (dati.method === "getStorageValues") {
    const fuori = {};
    for (const chiave of chiesto.keys || []) { fuori[chiave] = store[chiave] || ""; }
    return fuori;
  }
  if (dati.method === "saveStorageValue") { store[chiesto.key] = chiesto.value; return true; }
  if (dati.method === "deleteStorageValues") {
    for (const chiave of chiesto.keys || []) { delete store[chiave]; }
    return true;
  }
  if (dati.method === "getStorageKeys") { return Object.keys(store); }
  return true;
}

function ospite(evento) {
  let messaggio = null;
  try { messaggio = JSON.parse(evento.data); } catch { return; }
  if (!messaggio || !messaggio.eventType) { return; }
  const tipo = messaggio.eventType;
  const dati = messaggio.eventData || {};
  detti.push(tipo);
  if (tipo === "web_app_invoke_custom_method") {
    rispondi("custom_method_invoked", { req_id: dati.req_id, result: magazzino(dati) });
  }
  if (tipo === "web_app_request_viewport") {
    rispondi("viewport_changed", { height: CONF.altezza, width: CONF.larghezza,
                                   is_expanded: true, is_state_stable: true });
  }
  if (tipo === "web_app_request_safe_area") {
    rispondi("safe_area_changed", { top: 0, bottom: 34, left: 0, right: 0 });
  }
  if (tipo === "web_app_request_content_safe_area") {
    rispondi("content_safe_area_changed", { top: 0, bottom: 0, left: 0, right: 0 });
  }
  if (tipo === "web_app_request_theme") { rispondi("theme_changed", { theme_params: THEME }); }
  if (tipo === "web_app_open_popup") {
    const scelte = dati.buttons || [];
    const preso = scelte.find((uno) => uno.type !== "cancel" && uno.type !== "close")
      || scelte[0] || {};
    rispondi("popup_closed", { button_id: preso.id || "" });
  }
}

window.addEventListener("message", ospite);

function vista() {
  return FRAME.contentWindow;
}

function carta() {
  const foglio = FRAME.contentDocument;
  return foglio.scrollingElement || foglio.documentElement;
}

function visibile(elemento) {
  const misura = elemento.getBoundingClientRect();
  return misura.width > 0 && misura.height > 0;
}

function etichetta(elemento) {
  const detto = elemento.getAttribute("aria-label") || elemento.textContent
    || elemento.value || elemento.placeholder || "";
  return detto.trim().replace(/\s+/g, " ").slice(0, ETICHETTA);
}

function nome(elemento) {
  return elemento.tagName.toLowerCase() + "." + String(elemento.className).slice(0, CLASSE);
}

function schede(foglio) {
  return [...foglio.querySelectorAll(NAV)].filter(visibile);
}

function bersagli(foglio) {
  const barra = new Set(schede(foglio));
  const presi = [];
  for (const elemento of foglio.querySelectorAll(SEL)) {
    if (!visibile(elemento) || barra.has(elemento)) { continue; }
    const dentro = presi.some((altro) => altro.contains(elemento));
    if (dentro && !SCATOLE.includes(elemento.tagName)) { continue; }
    presi.push(elemento);
  }
  return presi;
}

function fuoriSchermo(foglio) {
  const largo = vista().innerWidth;
  const male = [];
  for (const elemento of foglio.querySelectorAll("#app *")) {
    if (male.length >= TETTO) { break; }
    const misura = elemento.getBoundingClientRect();
    if (misura.width > 0 && (misura.right > largo + 1 || misura.left < -1)) {
      male.push(nome(elemento) + " " + Math.round(misura.left) + ".." + Math.round(misura.right));
    }
  }
  return { quanti: male.length, largo: largo, esempi: male.slice(0, MOSTRA),
           scorre: foglio.documentElement.scrollWidth };
}

function conta(righe) {
  let quanti = 0;
  for (const riga of righe) {
    const preso = riga.target.nodeType === 3 ? riga.target.parentElement : riga.target;
    if (preso && preso.closest && preso.closest(OROLOGIO)) { continue; }
    quanti += 1;
  }
  return quanti;
}

function occhio(foglio, alza) {
  const Osservatore = vista().MutationObserver;
  const guarda = new Osservatore((righe) => alza(conta(righe)));
  guarda.observe(foglio.documentElement,
                 { childList: true, subtree: true, attributes: true, characterData: true });
  return guarda;
}

async function calma(foglio) {
  let mosse = 0;
  let visto = -1;
  let fermo = 0;
  const guarda = occhio(foglio, (quanti) => { mosse += quanti; });
  for (let passo = 0; passo < CAP; passo += 1) {
    await sonno(STEP);
    fermo = mosse === visto ? fermo + 1 : 0;
    visto = mosse;
    if (passo >= MIN && fermo >= QUIET) { break; }
  }
  guarda.disconnect();
}

async function finche(prova) {
  for (let passo = 0; passo < CAP; passo += 1) {
    if (prova()) { return true; }
    await sonno(STEP);
  }
  return false;
}

function parole(foglio) {
  const app = foglio.getElementById("app");
  try { return JSON.parse((app && app.dataset.words) || "{}"); } catch { return {}; }
}

function inCoda(foglio) {
  const detto = String(parole(foglio).queued || "");
  if (!detto) { return false; }
  return [...foglio.querySelectorAll(STRISCIA)]
    .some((uno) => (uno.textContent || "").trim() === detto);
}

async function chiudiRiepilogo(foglio) {
  if (!foglio.querySelector(".screens")) { return; }
  for (const chip of foglio.querySelectorAll(".chip")) {
    if ((chip.textContent || "").trim() === String(parole(foglio).manage_done || "")) {
      chip.click();
      await calma(foglio);
      return;
    }
  }
}

async function carica() {
  FRAME.src = "about:blank";
  await sonno(STEP);
  giro += 1;
  const pronto = new Promise((torna) => { FRAME.onload = torna; });
  FRAME.src = CONF.pagina + "?x=" + giro + HASH;
  await pronto;
  await finche(() => Boolean(FRAME.contentDocument
    && FRAME.contentDocument.querySelector(PRONTO)));
  const foglio = FRAME.contentDocument;
  await calma(foglio);
  await chiudiRiepilogo(foglio);
  return foglio;
}

async function quantoLog() {
  const risposta = await fetch("/__log");
  return (await risposta.json()).length;
}

async function dalLog(da) {
  const risposta = await fetch("/__log");
  return (await risposta.json()).slice(da);
}

async function segna() {
  return { errori: (vista().__errs || []).length, csp: (vista().__csp || []).length,
           risorse: (vista().__risorse || []).length, detti: detti.length,
           log: await quantoLog(), scorre: carta().scrollTop };
}

async function dopo(foglio, prima, mosse) {
  const righe = await dalLog(prima.log);
  const finestra = vista();
  return { cambi: mosse,
           inviati: righe.filter((riga) => riga.tipo === "azione").map((riga) => riga.kind),
           richieste: righe.filter((riga) => riga.tipo !== "azione").length,
           detti: detti.slice(prima.detti).filter((uno) => !RUMORE.test(uno)),
           foglio: Boolean(foglio.querySelector(FOGLIO)),
           coda: inCoda(foglio),
           scorre: carta().scrollTop - prima.scorre,
           errori: (finestra.__errs || []).slice(prima.errori),
           csp: (finestra.__csp || []).slice(prima.csp),
           risorse: (finestra.__risorse || []).slice(prima.risorse),
           fuori: fuoriSchermo(foglio) };
}

function descrivi(elemento, indice) {
  return { i: indice, tag: elemento.tagName.toLowerCase(),
           cls: String(elemento.className).slice(0, CLASSE), etichetta: etichetta(elemento),
           tipo: elemento.type || "", href: elemento.getAttribute("href") || "" };
}

async function tocca(quale, indice) {
  const foglio = await carica();
  const barra = schede(foglio);
  if (!barra[quale]) { return null; }
  barra[quale].click();
  await calma(foglio);
  const elemento = bersagli(foglio)[indice];
  if (!elemento) { return null; }
  const prima = await segna();
  let mosse = 0;
  const guarda = occhio(foglio, (quanti) => { mosse += quanti; });
  const voce = descrivi(elemento, indice);
  try { elemento.click(); } catch (errore) { voce.lancio = String(errore); }
  await calma(foglio);
  guarda.disconnect();
  return Object.assign(voce, await dopo(foglio, prima, mosse));
}

function primaVista(foglio) {
  const app = foglio.getElementById("app");
  const finestra = vista();
  return { testo: (app ? app.textContent : "").trim().slice(0, TESTO),
           schede: schede(foglio).map(etichetta), fuori: fuoriSchermo(foglio),
           errori: (finestra.__errs || []).slice(0), csp: (finestra.__csp || []).slice(0),
           risorse: (finestra.__risorse || []).slice(0),
           detti: detti.filter((uno) => !RUMORE.test(uno)) };
}

async function passaScheda(quale) {
  const foglio = await carica();
  const barra = schede(foglio);
  const chi = etichetta(barra[quale]);
  barra[quale].click();
  await calma(foglio);
  const quanti = bersagli(foglio).length;
  const voce = { scheda: chi, bersagli: quanti, fuori: fuoriSchermo(foglio),
                 errori: (vista().__errs || []).slice(0), csp: (vista().__csp || []).slice(0),
                 tocchi: [] };
  for (let indice = 0; indice < quanti && indice < CONF.perScheda; indice += 1) {
    const fatto = await tocca(quale, indice);
    if (fatto) { fatto.scheda = chi; voce.tocchi.push(fatto); }
  }
  return voce;
}

async function correre() {
  const esito = { prima: null, schede: [] };
  const foglio = await carica();
  esito.prima = primaVista(foglio);
  const quante = schede(foglio).length;
  for (let quale = 0; quale < quante && quale < TETTO; quale += 1) {
    esito.schede.push(await passaScheda(quale));
  }
  return esito;
}

function manda(esito) {
  return fetch("/__esito", { method: "POST", body: JSON.stringify(esito) });
}

function tasti(foglio) {
  return bersagli(foglio).filter((uno) => uno.tagName === "BUTTON"
    && !uno.matches(RIPROVA) && !uno.closest(FOGLIO));
}

async function accoda(foglio) {
  const visti = new Set();
  for (let passo = 0; passo < TETTO; passo += 1) {
    const preso = tasti(foglio).find((uno) => !visti.has(uno));
    if (!preso) { return null; }
    visti.add(preso);
    const voce = descrivi(preso, passo);
    try { preso.click(); } catch (errore) { voce.lancio = String(errore); }
    await calma(foglio);
    if (inCoda(foglio)) { return voce; }
  }
  return null;
}

async function attendiAzione(da) {
  for (let passo = 0; passo < CAP; passo += 1) {
    const righe = await dalLog(da);
    const partite = righe.filter((riga) => riga.tipo === "azione").map((riga) => riga.kind);
    if (partite.length) { return partite; }
    await sonno(STEP);
  }
  return [];
}

async function ripristino() {
  if (CONF.canale !== CADUTO) { return { saltato: "canale vivo" }; }
  const foglio = await carica();
  const messo = await accoda(foglio);
  const prima = await segna();
  await fetch(CONF.riapri);
  const tasto = foglio.querySelector(RIPROVA);
  if (tasto) { tasto.click(); }
  const partite = messo && tasto ? await attendiAzione(prima.log) : [];
  await calma(foglio);
  return { coda: Boolean(messo), tocco: messo ? messo.etichetta : "", tasto: Boolean(tasto),
           inviati: partite, coda_dopo: inCoda(foglio),
           errori: (vista().__errs || []).slice(0) };
}

correre()
  .then(async (esito) => manda(Object.assign(esito, { ripristino: await ripristino() })))
  .then(() => { document.getElementById("out").textContent = "fatto"; })
  .catch((errore) => manda({ crollo: String((errore && errore.stack) || errore) }));
