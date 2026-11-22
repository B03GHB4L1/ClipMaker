// Drawings flat on the pitch (P1, docs/CODING_AND_PITCH_PLAN.md section P). The clip keeps
// one calibrated frame: the analyst's pitch marks on it. A ring or arrow set "flat" is drawn
// through that calibration, so a ring is a true circle on the grass, so many metres across,
// and an arrow's head lies on the grass in perspective. Pure functions: no DOM.
//
// P2 (following the camera) will give each frame its own calibration; drawings then keep
// their place on the pitch as the camera pans. Until then the calibration is the one frame's.

import { calibrate } from "./pitch.js";

export const FLAT_KINDS = new Set(["ring", "arrow"]);
const RING_STEPS = 72;

/** The clip's saved calibration key ({frame, pairs}), or null. */
export const pitchKey = (value) => value?.pitch?.keys?.[0] || null;

let memo = { key: null, aspect: 0, fit: null };
/** The calibration for a frame of ratio `aspect` from the clip's document, or null. */
export const pitchCalibration = (value, aspect) => {
  const key = pitchKey(value);
  if (!key) return null;
  if (memo.key !== key || memo.aspect !== aspect) memo = { key, aspect, fit: calibrate(key.pairs, aspect) };
  return memo.fit;
};

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

/**
 * Items as drawItem draws them: a flat ring or arrow gets `projected` (frame fractions) when the
 * clip has a calibration; without one it is drawn as an ordinary ring or arrow. The document's
 * own items are never changed.
 */
export const projectItems = (items, calibration) => (calibration ? items.map((item) => {
  if (!item.style?.flat || !FLAT_KINDS.has(item.kind) || !item.points.every(Array.isArray)) return item;
  const projected = item.kind === "ring"
    ? ringOnPitch(item.points[0], item.geometry?.rx || 0, calibration)
    : arrowOnPitch(item.points[0], item.points[item.points.length - 1], calibration);
  return projected ? { ...item, projected } : item;
}) : items);
