import { html } from "../vendor/htm-preact-standalone.module.js";
import { BAND, Bars, TALL, Trend, WIDE } from "./charts.js";
import { agreed, chosen, claim, claimable, shown, typed, village, villageChips,
         villages } from "./me_link.js";
import { atLeast, fill, isLeader, isManager } from "./model.js";
import { app, buzz, forgetAll } from "./native.js";
import { TOAST } from "./manage_bits.js";
import { meForget, meGoal, meProved, meSet, meVerified } from "./guess.js";
import { Big, Card, Chip, Grid, Ring, Sheet, Sort, Switch, Tile } from "./ui.js";

const COUNTERS = ["donated", "war_stars", "levels"];
const VERIFY = "link.verify";
const ACCEPT = "on";
const WHISPER = "link.whisper";
const AVAILABILITY = "availability.set";
const FORGET = "data.forget";
const FORGET_KEY = "forget";
const GOAL_SET = "goal.set";
const SHARE_WEEK = "share.week";
const SHARE_CLAN = "share.clan";
const LANG_SET = "lang.set";
const SHEET = "sheet";
const GOAL = "goal";
const MEDAL = "medal";
const WON = "won";
const LOCKED = "locked";
const BOTH = 2;
const FULL_VIEW = "full";

function viewOf(state) {
  return (state && state.me_view) || {};
}

function what(one, words) {
  const said = words["goal_what_" + (one || {}).kind] || "";
  return fill(fill(said, "hero", (one || {}).hero || ""), "n", (one || {}).target || 0).trim();
}

function same(one, goal) {
  return one.kind === goal.kind && one.target === goal.target
         && (one.hero || null) === (goal.hero || null);
}

function ring(view, words, tools) {
  const goal = view.goal;
  if (!goal) {
    return null;
  }
  return html`
    <button class="ring-tap" onClick=${() => tools.pick(SHEET, { kind: GOAL })}>
      <${Ring} value=${goal.value} total=${goal.target} label=${what(goal, words)} />
    </button>`;
}

function goalSheet(view, words, tools) {
  const goal = view.goal || {};
  return html`
    <${Sheet} title=${words.goal_title}>
      <div class="chips">
        ${(goal.picks || []).map((one) => html`
          <${Chip} text=${what(one, words)} on=${same(one, goal)}
                   onTap=${() => tools.run(GOAL_SET, { goal: one.kind, hero: one.hero || "",
                                                       target: String(one.target) },
                                           meGoal(one))} />`)}
      </div>
    <//>`;
}

function four(view, words) {
  const profile = view.profile || {};
  const week = view.period || {};
  return [[profile.trophies, words.clan_sort_trophies], [profile.th, words.clan_sort_th],
          [profile.donations, words.clan_sort_donations],
          [Number(week.war_stars) || 0, words.growth_war_stars]];
}

function numbers(view, words, tools) {
  const profile = view.profile || {};
  if (profile.trophies === undefined) {
    return null;
  }
  return html`
    <${Card} hero stripe title=${view.name || view.tag}>
      <div class="me-head">
        ${ring(view, words, tools)}
        <${Grid}>
          ${four(view, words).map((one) => html`
            <${Big} value=${one[0]} label=${one[1]} />`)}
        <//>
      </div>
      ${profile.league === undefined ? null
        : html`<div class="sub">${profile.league || words.no_league}</div>`}
    <//>`;
}

function quick(view, words, conf, tools, full) {
  const options = full ? (conf.AVAIL || []) : [];
  const both = conf.SWITCH || [];
  const on = Boolean(view.whisper);
  if (!options.length && both.length !== BOTH) {
    return null;
  }
  return html`
    <${Card} tone="quick">
      ${options.length ? html`
        <div class="sub">${words.avail}</div>
        <${Sort} options=${options.map((one) => ({ id: one, label: words["avail_" + one] }))}
                 current=${view.avail}
                 onPick=${(one) => tools.run(AVAILABILITY, { choice: one },
                                             meSet("avail", one))} />` : null}
      ${both.length === BOTH ? html`
        <${Switch} on=${on} label=${words.link_whisper}
                   onTap=${() => tools.run(WHISPER, { village: view.tag,
                                                      on: on ? both[1] : both[0] },
                                           meSet("whisper", !on))} />` : null}
    <//>`;
}

function trend(view, words) {
  const grown = view.growth || {};
  const values = grown.trophies || [];
  if (!values.length) {
    return null;
  }
  return html`
    <${Card} title=${words.growth_trophies}>
      <${Trend} values=${values} labels=${grown.days || []} width=${WIDE} height=${TALL} />
    <//>`;
}

function week(view, words) {
  const found = view.period;
  if (!found) {
    return null;
  }
  return html`
    <${Card} title=${words.growth_week}>
      <${Bars} rows=${COUNTERS.map((field) => ({ label: words["growth_" + field],
                                                 value: found[field] }))}
               width=${WIDE} height=${BAND * COUNTERS.length} />
    <//>`;
}

function medals(view, words, conf, tools) {
  const glyphs = conf.MEDALS || {};
  const all = Object.keys(glyphs);
  if (!all.length) {
    return null;
  }
  const worn = (view.medals || []).map((one) => one.badge);
  return html`
    <${Card} title=${words.me_medals} tone="medals">
      <${Grid}>
        ${all.map((badge) => html`
          <${Tile} big=${glyphs[badge]} label=${words["badge_name_" + badge]}
                   tone=${worn.includes(badge) ? WON : LOCKED}
                   onTap=${() => tools.pick(SHEET, { kind: MEDAL, badge: badge })} />`)}
      <//>
    <//>`;
}

function medalSheet(words, conf, local) {
  const badge = (local.sheet || {}).badge;
  return html`
    <${Sheet} title=${words["badge_name_" + badge]}>
      <div class="big-value">${(conf.MEDALS || {})[badge]}</div>
      <div class="sub">${words["badge_how_" + badge]}</div>
    <//>`;
}

function share(state, words, tools, full) {
  if (!full) {
    return null;
  }
  return html`
    <${Card}>
      <div class="chips">
        <${Chip} text=${words.me_share} onTap=${() => tools.run(SHARE_WEEK, {})} />
        ${isManager(state) ? html`
          <${Chip} text=${words.me_share_clan} onTap=${() => tools.run(SHARE_CLAN, {})} />` : null}
      </div>
    <//>`;
}

function tongue(view, words, conf, tools) {
  const list = conf.LANGS || [];
  if (!list.length) {
    return null;
  }
  return html`
    <${Card} title=${words.me_lang}>
      <${Sort} options=${list.map((one) => ({ id: one.code, label: one.name }))}
               current=${view.lang}
               onPick=${(code) => tools.run(LANG_SET, { lang: code }, meSet("lang", code))} />
    <//>`;
}

function files(state, words, conf) {
  const mine = conf.MINE;
  if (!mine || !mine.json) {
    return null;
  }
  return html`
    <${Grid}>
      <${Tile} label=${words.me_json} href=${mine.json} />
      ${isLeader(state) ? html`<${Tile} label=${words.me_csv} href=${mine.csv} />` : null}
    <//>`;
}

function wipe(words, tools) {
  const phone = app();
  forgetAll(phone, () => {
    buzz(phone, "ok");
    tools.pick(TOAST, { text: words.manage_done });
  });
}

function data(state, words, conf, local, tools) {
  const armed = Boolean(local[FORGET_KEY]);
  return html`
    <${Card} title=${words.data_title}>
      ${files(state, words, conf)}
      ${armed ? html`<div class="sub">${words.data_gone}</div>` : null}
      <div class="chips">
        <${Chip} text=${armed ? words.data_sure : words.data_forget} on=${armed}
                 onTap=${() => (armed ? tools.run(FORGET, { sure: conf.SURE }, meForget())
                                      : tools.pick(FORGET_KEY, true))} />
        <${Chip} text=${words.data_device} onTap=${() => wipe(words, tools)} />
      </div>
    <//>`;
}

function sheet(view, words, conf, local, tools) {
  const open = local.sheet;
  if (!open) {
    return null;
  }
  if (open.kind === MEDAL) {
    return medalSheet(words, conf, local);
  }
  return open.kind === GOAL ? goalSheet(view, words, tools) : null;
}

export function me(state, words, conf, tools) {
  const kit = tools || {};
  const local = kit.local || {};
  const found = conf || {};
  const seat = viewOf(state);
  const view = shown(state, seat, chosen(seat, local));
  if (!view.tag) {
    return claim(words, found, local, kit);
  }
  return html`
    ${villageChips(state, seat, words, local, kit)}
    ${numbers(view, words, kit)}
    ${quick(view, words, found, kit, atLeast(state, FULL_VIEW))}
    ${medals(view, words, found, kit)}
    ${trend(view, words)}
    ${week(view, words)}
    ${share(state, words, kit, atLeast(state, FULL_VIEW))}
    ${tongue(view, words, found, kit)}
    ${data(state, words, found, local, kit)}
    ${villages(view, words, found, local, kit)}
    ${sheet(view, words, found, local, kit)}`;
}

export function mePrimary(state, words, conf, local) {
  const view = viewOf(state);
  const held = local || {};
  const token = String(held.token || "").trim();
  if (!view.tag) {
    const tag = village(typed(held));
    return claimable(held) && token
      ? { kind: VERIFY, label: words.link_mine, extra: proof(tag, token, held),
          optimistic: meProved({ tag: tag }) }
      : null;
  }
  if (!token || view.verified) {
    return null;
  }
  return { kind: VERIFY, label: words.link_verify,
           extra: proof(view.tag, token, held),
           optimistic: meVerified(view.tag) };
}

function proof(tag, token, held) {
  const extra = { village: tag, token: token };
  if (agreed(held)) {
    extra.terms = ACCEPT;
  }
  return extra;
}
