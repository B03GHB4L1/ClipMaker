// Fit a loose box to the player inside it. The tracker follows what is in the box, so a box with
// a lot of grass round the player makes it lose them (docs/TELESTRATION_PLAN.md, "Fitting a box").
//
// The pitch is one colour, lit or in shadow, and a player is not: everything in the region that is
// not that colour is a candidate, gaps (socks, shorts) are closed, and the blob that sits on the
// middle of the analyst's box is the player. The pitch colour is read from the picture itself,
// because broadcasts grade it differently (one real match has yellow-green grass, hue 63).
// Pure and framework-free; the editor feeds it pixels cut from the video.

const HUE_TOLERANCE = 18; // degrees either side of the pitch's hue
const SHADOW_TOLERANCE = 34; // wider in shadow, where a dark pixel's hue wanders
const GRASS_SATURATION = 0.3; // pale things (white kit, lines) are not grass
const DEFAULT_HUE = 95; // a mid green, for callers that do not read the picture

const hsv = (r, g, b) => {
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  let hue = 0;
  if (delta > 0) {
    if (max === g) hue = 60 * ((b - r) / delta + 2);
    else if (max === r) hue = (60 * ((g - b) / delta) + 360) % 360;
    else hue = 60 * ((r - g) / delta + 4);
  }
  return [hue, max > 0 ? delta / max : 0, max];
};
const hueGap = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };

/** True for a pixel of the pitch: saturated, of hue `hue`, lit or in shadow. Shirts, skin, boots and lines are not. */
export const isGrass = (r, g, b, hue = DEFAULT_HUE) => {
  const [h, saturation, value] = hsv(r, g, b);
  return saturation >= GRASS_SATURATION && value >= 20 && hueGap(h, hue) <= (value < 90 ? SHADOW_TOLERANCE : HUE_TOLERANCE);
};

/** The hue most of the picture's saturated pixels have (the pitch), or null when too little is coloured. */
export const pitchHue = (data) => {
  const bins = new Float64Array(36);
  let coloured = 0;
  const pixels = data.length / 4;
  for (let i = 0; i < pixels; i += 1) {
    const [h, saturation, value] = hsv(data[i * 4], data[i * 4 + 1], data[i * 4 + 2]);
    if (saturation < 0.35 || value < 30) continue;
    bins[Math.floor(h / 10) % 36] += 1;
    coloured += 1;
  }
  if (coloured < pixels * 0.25) return null;
  let top = 0;
  for (let k = 1; k < 36; k += 1) if (bins[k] + bins[(k + 1) % 36] > bins[top] + bins[(top + 1) % 36]) top = k;
  return (top * 10 + 10) % 360; // the middle of the two neighbouring bins that hold most pixels
};

const MIN_BOX = [3, 6]; // smallest box worth fitting, in pixels
const MIN_FILL = 0.3; // share of its box a player's blob fills: thinner means a pitch line or a stand is attached
const MAX_GROWTH = 1.6; // the fitted box may be this much bigger than the analyst's, not more
const ASPECT = [0.12, 0.6]; // width over height of one player: wider is two players joined, or a pitch line stuck to them

/** Binary dilation (grow) or erosion (shrink) by `radius` with a square window, in two passes. */
const morph = (mask, width, height, radius, grow) => {
  if (radius < 1) return mask;
  const pass = (source, horizontal) => {
    const out = new Uint8Array(source.length);
    const [outer, inner] = horizontal ? [height, width] : [width, height];
    for (let a = 0; a < outer; a += 1) {
      let count = 0;
      const at = (i) => (horizontal ? a * width + i : i * width + a);
      for (let i = 0; i < Math.min(radius, inner); i += 1) count += source[at(i)];
      for (let i = 0; i < inner; i += 1) {
        if (i + radius < inner) count += source[at(i + radius)];
        if (i - radius - 1 >= 0) count -= source[at(i - radius - 1)];
        const size = Math.min(inner - 1, i + radius) - Math.max(0, i - radius) + 1;
        out[at(i)] = grow ? (count > 0 ? 1 : 0) : (count === size ? 1 : 0);
      }
    }
    return out;
  };
  return pass(pass(mask, true), false);
};

/** Connected pieces of `mask` (8-neighbour): [{area, x0, y0, x1, y1, core}] with `core` the pixels inside `keep`. */
const pieces = (mask, width, height, keep) => {
  const seen = new Uint8Array(mask.length);
  const found = [];
  const stack = [];
  for (let start = 0; start < mask.length; start += 1) {
    if (!mask[start] || seen[start]) continue;
    const piece = { area: 0, x0: width, y0: height, x1: -1, y1: -1, core: 0 };
    seen[start] = 1;
    stack.push(start);
    while (stack.length) {
      const index = stack.pop();
      const x = index % width;
      const y = (index - x) / width;
      piece.area += 1;
      if (x < piece.x0) piece.x0 = x;
      if (x > piece.x1) piece.x1 = x;
      if (y < piece.y0) piece.y0 = y;
      if (y > piece.y1) piece.y1 = y;
      if (x >= keep[0] && x <= keep[2] && y >= keep[1] && y <= keep[3]) piece.core += 1;
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
          const next = ny * width + nx;
          if (mask[next] && !seen[next]) { seen[next] = 1; stack.push(next); }
        }
      }
    }
    found.push(piece);
  }
  return found;
};

/**
 * `image` is {data (RGBA), width, height}: pixels cut from the video round the analyst's box, which is
 * `rect` = [x0, y0, x1, y1] in those pixels. `edges` names the sides of the image that are the video's
 * own edge (the box may legitimately run to them). Returns the tight [x0, y0, x1, y1], or null when the
 * player's outline cannot be told from what is round them (a crowd, a second player touching them, no
 * grass at all), in which case the analyst's box should be kept.
 */
export const fitBox = (image, rect, edges = {}, why = {}) => {
  const no = (reason) => { why.reason = reason; return null; };
  const { data, width, height } = image;
  const [rx0, ry0, rx1, ry1] = rect;
  const boxW = rx1 - rx0;
  const boxH = ry1 - ry0;
  if (boxW < MIN_BOX[0] || boxH < MIN_BOX[1]) return no("box too small");
  const hue = pitchHue(data);
  if (hue === null) return no("no pitch colour"); // hardly any colour: nothing to read the pitch from
  let mask = new Uint8Array(width * height);
  let grass = 0;
  for (let i = 0; i < mask.length; i += 1) {
    const isGreen = isGrass(data[i * 4], data[i * 4 + 1], data[i * 4 + 2], hue);
    mask[i] = isGreen ? 0 : 1;
    grass += isGreen ? 1 : 0;
  }
  if (grass < mask.length * 0.25) return no("not on the pitch"); // nothing to tell the player from
  // Close the gaps between a player's parts (socks, shorts, shirt).
  const closeBy = Math.max(1, Math.min(4, Math.round(boxH * 0.03)));
  const closed = morph(morph(mask, width, height, closeBy, true), width, height, closeBy, false);
  // Pitch lines are a few pixels thick and often touch a player's boots; opening removes what is thinner than
  // the opening, and a thicker opening also takes thin limbs. So try the gentler opening first.
  const openings = boxH >= 50 ? [1, 2] : [0, 1];
  for (const radius of openings) {
    const opened = radius ? morph(morph(closed, width, height, radius, false), width, height, radius, true) : closed;
    const found = outline(opened, width, height, rect, edges, no);
    if (found) return found;
  }
  return null;
};

/** The tight, padded box of the blob on the middle of `rect` in `mask`, or null (with the reason given to `no`). */
const outline = (mask, width, height, rect, edges, no) => {
  const [rx0, ry0, rx1, ry1] = rect;
  const boxW = rx1 - rx0;
  const boxH = ry1 - ry0;
  // The player sits on the middle of the analyst's box: the blob with most pixels there is theirs.
  const cx = (rx0 + rx1) / 2;
  const cy = (ry0 + ry1) / 2;
  const keep = [cx - boxW * 0.25, cy - boxH * 0.35, cx + boxW * 0.25, cy + boxH * 0.35];
  const best = pieces(mask, width, height, keep).sort((a, b) => b.core - a.core)[0];
  if (!best || best.core < 3) return no("nothing in the middle of the box");
  const grown = [best.x0, best.y0, best.x1 + 1, best.y1 + 1];
  const [gw, gh] = [grown[2] - grown[0], grown[3] - grown[1]];
  if (gw < MIN_BOX[0] || gh < MIN_BOX[1]) return no("blob too small");
  const aspect = gw / gh;
  if (aspect < ASPECT[0] || aspect > ASPECT[1]) return no(`shape ${aspect.toFixed(2)}`); // two players joined, or a line
  if (gw * gh > MAX_GROWTH * boxW * boxH) return no("bigger than the box"); // it has run into the background
  if (best.area < MIN_FILL * gw * gh) return no(`thin ${(best.area / (gw * gh)).toFixed(2)}`); // a thin tail: a pitch line stuck to the player
  // Touching the edge of the cut-out means the blob goes on outside it, unless that edge is the video's.
  const touches = (grown[0] <= 0 && !edges.left) || (grown[2] >= width && !edges.right)
    || (grown[1] <= 0 && !edges.top) || (grown[3] >= height && !edges.bottom);
  if (touches) return no("runs on past the cut-out");
  // A little room for the blurred edge of the player: the tracker likes the whole of them inside the box.
  const pad = Math.max(1, Math.round(gh * 0.03));
  return [Math.max(0, grown[0] - pad), Math.max(0, grown[1] - pad), Math.min(width, grown[2] + pad), Math.min(height, grown[3] + pad)];
};
