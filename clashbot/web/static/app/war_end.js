import { html } from "../vendor/htm-preact-standalone.module.js";
import { percent } from "./model.js";
import { Big, Card, Chip, Chips, Grid, Tile } from "./ui.js";

const SHARE = "share.war";

export function warEnd(view, words, run) {
  const done = (view || {}).ended;
  if (!done) { return null; }
  const us = view.us || {};
  const them = view.them || {};
  const best = done.best;
  const mine = view.mine;
  return html`
    <${Card} tone="end" hero stripe title=${words.war_ended}>
      <${Big} value=${words["war_" + done.result]} label=${them.name} />
      <${Grid}>
        <${Tile} big=${us.stars} label=${us.name} sub=${percent(words, us.destr)} />
        <${Tile} big=${them.stars} label=${them.name} sub=${percent(words, them.destr)} />
        ${best ? html`
          <${Tile} big=${best.stars} label=${words.war_top} sub=${best.name} />` : null}
        ${mine ? html`
          <${Tile} big=${mine.stars} label=${words.war_yours}
                   sub=${percent(words, mine.destr)} />` : null}
      <//>
      <${Chips} tone="wide">
        <${Chip} text=${words.war_share} onTap=${() => run(SHARE, {})} />
      <//>
    <//>`;
}
