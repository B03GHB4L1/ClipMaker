// Native tab renderers by slug. Each returns an optional cleanup function.
import { renderShotMap } from "./shot-map.js";

export const renderers = {
  "shot-map": renderShotMap,
};
