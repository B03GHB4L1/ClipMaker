// Drawings flat on the pitch (P1 and P2, docs/CODING_AND_PITCH_PLAN.md section P). A ring or
// arrow set "flat" is drawn through the clip's calibration, so a ring is a true circle on the
// grass, so many metres across, and an arrow's head lies on the grass in perspective.
//
// A flat drawing's points are kept for the frame it was placed on (`at`, a recorded frame; older
// drawings without one use the first marked frame). Once the camera is followed (ui/annotate/camera.js)
// each frame has its own calibration, and placeFlat moves the drawing so it keeps its place on the pitch
// as the camera pans and zooms. Pure functions: no DOM.
//
// P3 adds two drawings that are always on the pitch: the offside line (a line across the pitch at
// the depth of a clicked spot) and the measure (the distance in metres between two spots).

import { LENGTH, WIDTH } from "./pitch.js";

export const FLAT_KINDS = new Set(["ring", "arrow", "offside", "measure"]);
/** Drawings that only make sense on the pitch: they are flat whether or not `style.flat` says so. */
export const PITCH_KINDS = new Set(["offside", "measure"]);
const RING_STEPS = 72;
const OFFSIDE_STEP = 2; // metres between the points of an offside line
const OFFSIDE_MARGIN = 2; // metres the line runs past each touchline
const FAR = 4; // a point further than this many frames from the picture is behind the horizon

/** Whether `item` lies flat on the pitch: a flat ring or arrow, or an offside line or measure, on the video (not a board) with fixed points. */
export const isFlat = (item) => (PITCH_KINDS.has(item.kind) || Boolean(item.style?.flat)) && FLAT_KINDS.has(item.kind)
  && item.on === undefined && item.points.every(Array.isArray);

const finite = (point) => point && Number.isFinite(point[0]) && Number.isFinite(point[1]);

/** A ring's circle on the pitch: centre `centre` (frame fractions), radius from `rx` (fraction of the width). */
export const ringOnPitch = (centre, rx, calibration) => {
  const middle = calibration.toPitch(centre);
  const edge = calibration.toPitch([centre[0] + rx, centre[1]]);
  if (!finite(middle) || !finite(edge)) return null;
  const metres = Math.hypot(edge[0] - middle[0], edge[1] - middle[1]);
  if (!(metres > 0.05 && metres < 60)) return null;
  // Start at the far side (the top of the ring on screen), as a flat ring's drawing animation does.
  const outline = [];
  for (let step = 0; step <= RING_STEPS; step += 1) {
    const angle = -Math.PI / 2 + (Math.PI * 2 * step) / RING_STEPS;
    const point = calibration.toFrame([middle[0] + metres * Math.cos(angle), middle[1] + metres * Math.sin(angle)]);
    if (!finite(point)) return null;
    outline.push(point);
  }
  return { outline, metres };
};

/** An arrow's head on the pitch: [tip, left, right] in frame fractions, its length in metres, or null. */
export const arrowOnPitch = (from, to, calibration) => {
  const a = calibration.toPitch(from);
  const b = calibration.toPitch(to);
  if (!finite(a) || !finite(b)) return null;
  const metres = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (!(metres > 0.2)) return null;
  const [ux, uy] = [(b[0] - a[0]) / metres, (b[1] - a[1]) / metres];
  const length = Math.min(4, Math.max(1.2, metres * 0.12)); // metres of grass under the head
  const half = length * 0.45;
  const base = [b[0] - ux * length, b[1] - uy * length];
  const head = [b, [base[0] - uy * half, base[1] + ux * half], [base[0] + uy * half, base[1] - ux * half]]
    .map((point) => calibration.toFrame(point));
  const neck = calibration.toFrame(base);
  return head.every(finite) && finite(neck) ? { head, neck, metres } : null;
};

const sane = (point) => finite(point) && Math.abs(point[0]) < FAR && Math.abs(point[1]) < FAR;

/**
 * An offside line through `point` (frame fractions): the line across the pitch at that spot's depth,
 * at the same distance from the goal lines all the way from touchline to touchline. `segments` are
 * its pieces in frame fractions (pieces behind the camera are left out); `x` is its place along
 * the pitch (metres from the centre line, positive towards the right goal), `fromLeft` and
 * `fromRight` its distances from the goal lines. Null where the point is off the pitch.
 */
export const offsideOnPitch = (point, calibration) => {
  const spot = calibration.toPitch(point);
  if (!finite(spot) || Math.abs(spot[0]) > LENGTH / 2 + 5) return null;
  const x = spot[0];
  const half = WIDTH / 2 + OFFSIDE_MARGIN;
  const steps = Math.ceil((half * 2) / OFFSIDE_STEP);
  const segments = [];
  let run = [];
  for (let step = 0; step <= steps; step += 1) {
    const at = calibration.toFrame([x, -half + (half * 2 * step) / steps]);
    if (sane(at)) run.push(at);
    else if (run.length) { segments.push(run); run = []; }
  }
  if (run.length) segments.push(run);
  const pieces = segments.filter((segment) => segment.length > 1);
  return pieces.length ? { segments: pieces, x, fromLeft: x + LENGTH / 2, fromRight: LENGTH / 2 - x } : null;
};

/** The distance on the pitch between two spots (frame fractions): {metres, mid} with mid the middle of it as drawn, or null. */
export const measureOnPitch = (from, to, calibration) => {
  const a = calibration.toPitch(from);
  const b = calibration.toPitch(to);
  if (!finite(a) || !finite(b)) return null;
  const metres = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (!(metres > 0.05 && metres < 250)) return null;
  const mid = calibration.toFrame([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]);
  return sane(mid) ? { metres, mid } : null;
};

/**
 * Items as drawItem draws them: a flat ring or arrow, an offside line or a measure gets `projected`
 * (frame fractions) when the clip has a calibration; without one a ring or arrow is drawn as an
 * ordinary one. The document's own items are never changed.
 */
export const projectItems = (items, calibration) => (calibration ? items.map((item) => {
  if (!isFlat(item)) return item;
  let projected;
  if (item.kind === "ring") projected = ringOnPitch(item.points[0], item.geometry?.rx || 0, calibration);
  else if (item.kind === "offside") projected = offsideOnPitch(item.points[0], calibration);
  else if (item.kind === "measure") projected = measureOnPitch(item.points[0], item.points[item.points.length - 1], calibration);
  else projected = arrowOnPitch(item.points[0], item.points[item.points.length - 1], calibration);
  return projected ? { ...item, projected } : item;
}) : items);

/** Metres on the pitch per fraction of the frame width, sideways at `point` (null off the pitch). */
const metresAcross = (point, calibration) => {
  const middle = calibration.toPitch(point);
  const side = calibration.toPitch([point[0] + 0.01, point[1]]);
  return finite(middle) && finite(side) ? Math.hypot(side[0] - middle[0], side[1] - middle[1]) / 0.01 : null;
};

/**
 * A flat drawing placed for `frame` through the clip's pitch track (camera.js): its points moved from
 * the frame it was drawn on to where the same spots of grass are now, and a ring's size kept in metres.
 * Once the camera is followed, a frame without a pitch (after a cut) gives the item marked `offPitch`:
 * its grass is not in the picture, so it is not drawn. Other drawings are given as they are.
 */
export const placeFlat = (item, track, frame) => {
  if (!track || !isFlat(item)) return item;
  const now = track.at(frame)?.calibration;
  if (!now && track.followed) return { ...item, offPitch: true };
  const anchor = item.at ?? track.keys[0];
  const then = anchor === undefined ? null : track.at(anchor)?.calibration;
  if (!now || !then || now === then) return item;
  const points = item.points.map((point) => { const metres = then.toPitch(point); return metres && now.toFrame(metres); });
  if (!points.every(finite)) return item;
  const placed = { ...item, points };
  if (item.kind === "ring" && item.geometry) {
    const before = metresAcross(item.points[0], then);
    const after = metresAcross(points[0], now);
    if (!before || !after) return item;
    const rx = (item.geometry.rx * before) / after;
    placed.geometry = { ...item.geometry, rx, ry: (item.geometry.ry * rx) / item.geometry.rx };
  }
  return placed;
};
