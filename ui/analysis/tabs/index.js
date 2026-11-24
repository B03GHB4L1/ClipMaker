// Native tab renderers by slug. Each returns an optional cleanup function.
import { eventTab } from "./event-tab.js";
import { renderComparison } from "./comparison.js";
import { renderTactical } from "./tactical.js";

export const renderers = {
  "shot-map": eventTab("shot-map", "Shot Map"),
  "pass-map": eventTab("pass-map", "Pass Map"),
  "defensive-actions": eventTab("defensive-actions", "Defensive Actions"),
  "dribbles-carries": eventTab("dribbles-carries", "Dribbles & Carries"),
  "goalkeeper": eventTab("goalkeeper", "Goalkeeper"),
  "pressing": eventTab("pressing", "Pressing"),
  "build-up": eventTab("build-up", "Build-Up"),
  "comparison": renderComparison,
  "defensive-transitions": renderTactical,
  "attacking-transitions": renderTactical,
  "style-profile": renderTactical,
  "set-pieces": renderTactical,
  "video-lab": renderTactical,
};
