import { clan } from "./clan.js";
import { manage, primary as managePrimary } from "./manage.js";
import { me, mePrimary } from "./me.js";
import { more, primary as morePrimary } from "./more.js";
import { war, warPrimary } from "./war.js";

export { war, clan, me, more, manage };

export const views = { war, clan, me, more, manage };

export const primaries = {
  war: warPrimary,
  me: mePrimary,
  more: morePrimary,
  manage: managePrimary,
};
