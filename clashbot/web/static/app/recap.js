import { html } from "../vendor/htm-preact-standalone.module.js";
import { fill } from "./model.js";
import { Big, Card, Chip, Chips, Grid, Medals, Ring } from "./ui.js";

export const DONE = "done";
const KEY = "recap";
const SHARE = "share.season";

function numbers(me, words) {
  const rows = [[me.score, words.points], [me.war_stars, words.growth_war_stars],
                [me.donated, words.growth_donated]];
  return html`
    <${Grid} cols=${rows.length}>
      ${rows.map(([value, label]) => html`<${Big} value=${value} label=${label} />`)}
    <//>`;
}

function standing(view, words) {
  const me = view.me;
  const top = view.clan.top || {};
  return html`
    <${Card} title=${words.tab_clan}>
      ${me ? html`
        <${Ring} value=${me.score} total=${top.score || me.score}
                 label=${fill(words.pos, "pos", me.rank)} />` : null}
      <${Grid}>
        <${Big} value=${view.clan.people} label=${words.members} />
        <${Big} value=${view.clan.score} label=${words.points} />
      <//>
    <//>`;
}

function won(me, words, conf) {
  const worn = (me && me.medals) || [];
  if (!worn.length) { return null; }
  return html`
    <${Card} title=${words.me_medals}>
      <${Medals} worn=${worn.map((badge) => ({ badge: badge }))} glyphs=${conf.MEDALS} />
    <//>`;
}

export function recapScreens(state, words, conf, tools) {
  const view = (state || {}).recap;
  if (!view) { return null; }
  return html`
    <div class="screens">
      <${Card} title=${fill(words.recap_title, "season", view.season)}>
        ${view.me ? numbers(view.me, words) : null}
      <//>
      ${standing(view, words)}
      ${won(view.me, words, conf)}
    </div>
    <${Chips} tone="wide">
      <${Chip} text=${words.recap_share} onTap=${() => tools.run(SHARE)} />
      <${Chip} text=${words.manage_done} onTap=${() => tools.pick(KEY, DONE)} />
    <//>`;
}
