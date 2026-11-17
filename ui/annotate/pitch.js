// The pitch in metres, and the mapping between a video frame and the pitch
// (docs/TELESTRATION_PLAN.md, "Board from this frame"). Pure functions: no DOM.
//
// Pitch coordinates: metres from the centre spot, x to the right-hand goal as
// the main camera sees it, y towards the near touchline (down the screen).
// A frame point is [x, y] in fractions of the frame, like every drawing.

export const LENGTH = 105;
export const WIDTH = 68;
const HALF_L = LENGTH / 2;
const HALF_W = WIDTH / 2;
const BOX_DEPTH = 16.5;
const BOX_HALF = 20.16;
const SIX_DEPTH = 5.5;
const SIX_HALF = 9.16;
const SPOT = 11;
const CIRCLE = 9.15;
const GOAL_HALF = 3.66;

/** Points the analyst can click on the frame. Ids are stable; names are shown. */
export const LANDMARKS = (() => {
  const marks = [
    { id: "corner-fl", name: "Far left corner", at: [-HALF_L, -HALF_W] },
    { id: "corner-fr", name: "Far right corner", at: [HALF_L, -HALF_W] },
    { id: "corner-nl", name: "Near left corner", at: [-HALF_L, HALF_W] },
    { id: "corner-nr", name: "Near right corner", at: [HALF_L, HALF_W] },
    { id: "half-far", name: "Halfway line, far touchline", at: [0, -HALF_W] },
    { id: "half-near", name: "Halfway line, near touchline", at: [0, HALF_W] },
    { id: "centre", name: "Centre spot", at: [0, 0] },
    { id: "circle-far", name: "Centre circle, far side", at: [0, -CIRCLE] },
    { id: "circle-near", name: "Centre circle, near side", at: [0, CIRCLE] },
    { id: "circle-left", name: "Centre circle, left edge", at: [-CIRCLE, 0] },
    { id: "circle-right", name: "Centre circle, right edge", at: [CIRCLE, 0] },
  ];
  for (const [side, sign, name] of [["l", -1, "Left"], ["r", 1, "Right"]]) {
    const goal = sign * HALF_L;
    const front = sign * (HALF_L - BOX_DEPTH);
    const six = sign * (HALF_L - SIX_DEPTH);
    marks.push(
      { id: `box-${side}-far-goal`, name: `${name} box, far corner on the goal line`, at: [goal, -BOX_HALF] },
      { id: `box-${side}-near-goal`, name: `${name} box, near corner on the goal line`, at: [goal, BOX_HALF] },
      { id: `box-${side}-far`, name: `${name} box, far front corner`, at: [front, -BOX_HALF] },
      { id: `box-${side}-near`, name: `${name} box, near front corner`, at: [front, BOX_HALF] },
      { id: `six-${side}-far-goal`, name: `${name} 6-yard box, far corner on the goal line`, at: [goal, -SIX_HALF] },
      { id: `six-${side}-near-goal`, name: `${name} 6-yard box, near corner on the goal line`, at: [goal, SIX_HALF] },
      { id: `six-${side}-far`, name: `${name} 6-yard box, far front corner`, at: [six, -SIX_HALF] },
      { id: `six-${side}-near`, name: `${name} 6-yard box, near front corner`, at: [six, SIX_HALF] },
      { id: `spot-${side}`, name: `${name} penalty spot`, at: [sign * (HALF_L - SPOT), 0] },
      { id: `post-${side}-far`, name: `${name} goal, far post`, at: [goal, -GOAL_HALF] },
      { id: `post-${side}-near`, name: `${name} goal, near post`, at: [goal, GOAL_HALF] },
    );
  }
  return marks;
})();
export const landmark = (id) => LANDMARKS.find((mark) => mark.id === id) || null;

const arc = (cx, cy, r, from, to, steps = 32) => Array.from({ length: steps + 1 }, (_, i) => {
  const angle = from + ((to - from) * i) / steps;
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
});

/** The pitch markings as polylines in metres. Spots are short circles. */
export const LINES = (() => {
  const lines = [
    [[-HALF_L, -HALF_W], [HALF_L, -HALF_W], [HALF_L, HALF_W], [-HALF_L, HALF_W], [-HALF_L, -HALF_W]],
    [[0, -HALF_W], [0, HALF_W]],
    arc(0, 0, CIRCLE, 0, Math.PI * 2, 64),
    arc(0, 0, 0.25, 0, Math.PI * 2, 8),
  ];
  for (const sign of [-1, 1]) {
    const goal = sign * HALF_L;
    const front = sign * (HALF_L - BOX_DEPTH);
    const six = sign * (HALF_L - SIX_DEPTH);
    const spot = sign * (HALF_L - SPOT);
    lines.push([[goal, -BOX_HALF], [front, -BOX_HALF], [front, BOX_HALF], [goal, BOX_HALF]]);
    lines.push([[goal, -SIX_HALF], [six, -SIX_HALF], [six, SIX_HALF], [goal, SIX_HALF]]);
    lines.push(arc(spot, 0, 0.25, 0, Math.PI * 2, 8));
    // The arc of the penalty area: the part of the 9.15 m circle round the spot outside the box.
    const reach = Math.acos((BOX_DEPTH - SPOT) / CIRCLE); // half the angle of the arc outside the box
    const facing = sign > 0 ? Math.PI : 0; // towards the centre of the pitch
    lines.push(arc(spot, 0, CIRCLE, facing - reach, facing + reach, 24));
    lines.push([[goal, -GOAL_HALF], [goal + sign * 1.5, -GOAL_HALF], [goal + sign * 1.5, GOAL_HALF], [goal, GOAL_HALF]]);
    // Corner arcs, a quarter circle into the pitch.
    const corners = sign > 0 ? [[-1, Math.PI / 2, Math.PI], [1, Math.PI, Math.PI * 1.5]] : [[-1, 0, Math.PI / 2], [1, -Math.PI / 2, 0]];
    for (const [end, from, to] of corners) lines.push(arc(goal, end * HALF_W, 1, from, to, 8));
  }
  return lines;
})();

// ---------------------------------------------------------------------------
// Homography: 3x3 matrix H with [u, v, 1] ~ H [x, y, 1]
// ---------------------------------------------------------------------------

/** Solve A x = b (n x n) by Gaussian elimination with partial pivoting; null when singular. */
const solve = (A, b) => {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col += 1) {
    let pivot = col;
    for (let row = col + 1; row < n; row += 1) if (Math.abs(M[row][col]) > Math.abs(M[pivot][col])) pivot = row;
    if (Math.abs(M[pivot][col]) < 1e-12) return null;
    [M[col], M[pivot]] = [M[pivot], M[col]];
    for (let row = 0; row < n; row += 1) {
      if (row === col) continue;
      const factor = M[row][col] / M[col][col];
      for (let k = col; k <= n; k += 1) M[row][k] -= factor * M[col][k];
    }
  }
  return M.map((row, i) => row[n] / row[i]);
};

/** Move points to mean 0 and mean distance sqrt(2) (Hartley), for a stable fit. */
const normaliser = (points) => {
  const cx = points.reduce((s, p) => s + p[0], 0) / points.length;
  const cy = points.reduce((s, p) => s + p[1], 0) / points.length;
  const spread = points.reduce((s, p) => s + Math.hypot(p[0] - cx, p[1] - cy), 0) / points.length || 1;
  const k = Math.SQRT2 / spread;
  return [[k, 0, -k * cx], [0, k, -k * cy], [0, 0, 1]];
};

const multiply = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((s, v, k) => s + v * B[k][j], 0)));

export const invert = (M) => {
  const [[a, b, c], [d, e, f], [g, h, i]] = M;
  const det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
  if (Math.abs(det) < 1e-15) return null;
  return [
    [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
    [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
    [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
  ];
};

/** H (3x3) taking each `from` point to its `to` point, least squares for more than 4 pairs; null if degenerate. */
export const fitHomography = (from, to) => {
  if (from.length < 4 || from.length !== to.length) return null;
  const Tf = normaliser(from);
  const Tt = normaliser(to);
  const nf = from.map((p) => apply(Tf, p));
  const nt = to.map((p) => apply(Tt, p));
  // Rows of the linear system with h33 = 1; normal equations for least squares.
  const AtA = Array.from({ length: 8 }, () => new Array(8).fill(0));
  const Atb = new Array(8).fill(0);
  nf.forEach(([x, y], i) => {
    const [u, v] = nt[i];
    for (const [row, rhs] of [[[x, y, 1, 0, 0, 0, -u * x, -u * y], u], [[0, 0, 0, x, y, 1, -v * x, -v * y], v]]) {
      for (let r = 0; r < 8; r += 1) {
        Atb[r] += row[r] * rhs;
        for (let c = 0; c < 8; c += 1) AtA[r][c] += row[r] * row[c];
      }
    }
  });
  const h = solve(AtA, Atb);
  if (!h || h.some((value) => !Number.isFinite(value))) return null;
  const Hn = [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1]];
  const back = invert(Tt);
  if (!back) return null;
  const H = multiply(multiply(back, Hn), Tf);
  return H[2][2] ? H.map((row) => row.map((value) => value / H[2][2])) : null;
};

/** H applied to a point; null when the point maps to infinity or behind the camera. */
export function apply(H, [x, y]) {
  const w = H[2][0] * x + H[2][1] * y + H[2][2];
  if (Math.abs(w) < 1e-12) return null;
  return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w];
}

/** Sign of w for a pitch point under H (pitch -> frame): the same sign as the clicked points means in front of the camera. */
const depth = (H, [x, y]) => H[2][0] * x + H[2][1] * y + H[2][2];

/**
 * Whether pitch points can fix a homography: four of them with no three on one line.
 * Marks along one line (the halfway line, say) leave the rest of the pitch free to swing.
 */
export const pinsDown = (points) => {
  const area = (a, b, c) => Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2;
  const n = Math.min(points.length, 24);
  for (let i = 0; i < n; i += 1) for (let j = i + 1; j < n; j += 1) for (let k = j + 1; k < n; k += 1) {
    if (area(points[i], points[j], points[k]) < 20) continue;
    for (let l = k + 1; l < n; l += 1) {
      const quad = [points[i], points[j], points[k], points[l]];
      if ([[0, 1, 3], [0, 2, 3], [1, 2, 3]].every(([a, b, c]) => area(quad[a], quad[b], quad[c]) >= 20)) return true;
    }
  }
  return false;
};

/**
 * The calibration from clicked pairs [{id, at: [fx, fy]}]: frame -> pitch and back,
 * with the frame's width/height ratio so distances are not squeezed. Null below 4 points.
 */
export const calibrate = (pairs, aspect) => {
  const known = pairs.filter((pair) => landmark(pair.id));
  if (known.length < 4 || !pinsDown(known.map((pair) => landmark(pair.id).at))) return null;
  const frame = known.map((pair) => [pair.at[0] * aspect, pair.at[1]]);
  const pitch = known.map((pair) => landmark(pair.id).at);
  const toPitch = fitHomography(frame, pitch);
  const toFrame = toPitch && invert(toPitch);
  if (!toFrame) return null;
  const sign = Math.sign(depth(toFrame, pitch[0])) || 1;
  // How far each clicked point lands from where the fit puts it, in pitch metres.
  const residuals = known.map((pair, i) => {
    const mapped = apply(toPitch, frame[i]);
    return mapped ? Math.hypot(mapped[0] - pitch[i][0], mapped[1] - pitch[i][1]) : Infinity;
  });
  return {
    toPitch: (point) => apply(toPitch, [point[0] * aspect, point[1]]),
    toFrame: (metres) => {
      if (Math.sign(depth(toFrame, metres)) !== sign) return null;
      const at = apply(toFrame, metres);
      return at && [at[0] / aspect, at[1]];
    },
    worst: Math.max(...residuals),
  };
};

/** The pitch markings drawn through the calibration, as frame polylines (pieces behind the camera dropped). */
export const projectedLines = (calibration, step = 1.5) => LINES.map((line) => {
  const dense = [];
  line.forEach((point, index) => {
    if (!index) { dense.push(point); return; }
    const [px, py] = line[index - 1];
    const pieces = Math.max(1, Math.ceil(Math.hypot(point[0] - px, point[1] - py) / step));
    for (let k = 1; k <= pieces; k += 1) dense.push([px + ((point[0] - px) * k) / pieces, py + ((point[1] - py) * k) / pieces]);
  });
  return dense.map((point) => calibration.toFrame(point));
});

// ---------------------------------------------------------------------------
// The board: where the pitch sits on a frame-shaped picture
// ---------------------------------------------------------------------------
export const VIEWS = { full: "Full pitch", left: "Left half", right: "Right half", blank: "Blank" };
const MARGIN = 4; // metres of grass round the lines

/** The part of the pitch a view shows, in metres: [x0, y0, x1, y1]. */
const viewBounds = (view) => {
  if (view === "left") return [-HALF_L - MARGIN, -HALF_W - MARGIN, MARGIN, HALF_W + MARGIN];
  if (view === "right") return [-MARGIN, -HALF_W - MARGIN, HALF_L + MARGIN, HALF_W + MARGIN];
  return [-HALF_L - MARGIN, -HALF_W - MARGIN, HALF_L + MARGIN, HALF_W + MARGIN];
};

/** Board layout for a frame of ratio `aspect` (width / height): pitch metres <-> frame fractions, scale kept square. */
export const boardLayout = (view, aspect) => {
  const [x0, y0, x1, y1] = viewBounds(view);
  const scale = Math.min(aspect / (x1 - x0), 1 / (y1 - y0)); // frame heights per metre
  const left = (aspect - (x1 - x0) * scale) / 2;
  const top = (1 - (y1 - y0) * scale) / 2;
  return {
    toBoard: ([x, y]) => [(left + (x - x0) * scale) / aspect, top + (y - y0) * scale],
    toPitch: ([fx, fy]) => [(fx * aspect - left) / scale + x0, (fy - top) / scale + y0],
    metre: scale, // one metre in frame heights
  };
};

/**
 * The view for these pitch points on a frame of ratio `aspect`: a half when they all sit in it
 * and the half shows the pitch at least 10% bigger, else the full pitch. On a 16:9 frame the
 * pitch's height already sets the scale, so a half would only shift it: the full pitch is kept.
 */
export const viewFor = (points, aspect = 16 / 9) => {
  if (!points.length) return "full";
  const half = points.every(([x]) => x >= -MARGIN) ? "right" : points.every(([x]) => x <= MARGIN) ? "left" : null;
  if (!half) return "full";
  return boardLayout(half, aspect).metre >= boardLayout("full", aspect).metre * 1.1 ? half : "full";
};
