// The pitch on every frame of the clip (P2, docs/CODING_AND_PITCH_PLAN.md section P).
// The analyst marks the pitch on one or more frames (keys, P1). The engine follows the
// camera (app/telestration/camera.py): for each frame, the homography taking its points to
// the first frame of its stretch (a stretch ends at a scene cut or a lost camera). Chaining
// that from a key gives the frame's own calibration; between two keys the two are blended,
// leaning on the nearer one, so the pitch arrives on each key without a jump. Pure functions.
//
// value.pitch = {keys: [{frame, pairs}], camera?: {from, rows: [[h11..h32, sure]], starts: [frame]}}

import { apply, calibrate, fitHomography, invert } from "./pitch.js";

export const CHECK_BELOW = 0.15; // a step the engine is less sure of than this asks for a look
const GRID = [0.15, 0.5, 0.85].flatMap((x) => [0.2, 0.55, 0.9].map((y) => [x, y]));

const multiply = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((s, v, k) => s + v * B[k][j], 0)));
const matrix = (row) => [[row[0], row[1], row[2]], [row[3], row[4], row[5]], [row[6], row[7], 1]];
const finite = (point) => point && Number.isFinite(point[0]) && Number.isFinite(point[1]);

export const pitchKeys = (value) => value?.pitch?.keys || [];
export const keyAt = (value, frame) => pitchKeys(value).find((key) => key.frame === frame) || null;

/** The camera's path: stretch and path matrix per frame, with sureness. Null without one. */
const pathOf = (camera) => {
  if (!camera?.rows?.length) return null;
  const starts = new Set(camera.starts || []);
  const stretch = [];
  let current = -1;
  camera.rows.forEach((row, index) => {
    if (starts.has(camera.from + index) || current < 0) current = camera.from + index;
    stretch.push(row ? current : null);
  });
  return { from: camera.from, rows: camera.rows, stretch };
};

/** The calibration `through` on frame-to-key matrix K: a frame point goes to the key's frame, then to the pitch. */
const through = (key, K) => {
  const back = invert(K);
  if (!back) return null;
  return {
    toPitch: (point) => { const at = apply(K, point); return at && key.toPitch(at); },
    toFrame: (metres) => { const at = key.toFrame(metres); return at && apply(back, at); },
    worst: key.worst,
  };
};

/** Two calibrations mixed, `share` of the way from a to b (pitch positions of a grid of frame points averaged). */
const blend = (a, b, share, aspect) => {
  const frame = [];
  const pitch = [];
  GRID.forEach((point) => {
    const pa = a.toPitch(point);
    const pb = b.toPitch(point);
    if (!finite(pa) || !finite(pb)) return;
    frame.push([point[0] * aspect, point[1]]);
    pitch.push([pa[0] + (pb[0] - pa[0]) * share, pa[1] + (pb[1] - pa[1]) * share]);
  });
  const toPitch = frame.length >= 4 ? fitHomography(frame, pitch) : null;
  const toFrame = toPitch && invert(toPitch);
  if (!toFrame) return share < 0.5 ? a : b;
  // In front of the camera: the same side as the grid's own pitch points.
  const side = (metres) => Math.sign(toFrame[2][0] * metres[0] + toFrame[2][1] * metres[1] + toFrame[2][2]);
  const sign = side(pitch[0]) || 1;
  return {
    toPitch: (point) => apply(toPitch, [point[0] * aspect, point[1]]),
    toFrame: (metres) => {
      if (side(metres) !== sign) return null;
      const at = apply(toFrame, metres);
      return at && [at[0] / aspect, at[1]];
    },
    worst: Math.max(a.worst, b.worst),
  };
};

/**
 * The clip's pitch on every frame. `at(frame)` gives {calibration, state} or null, where state is
 * "key" (a marked frame), "followed", "check" (the camera was hard to follow on the way from the
 * key) or "held" (no camera followed yet: the nearest key's pitch, as drawn in P1).
 */
export const pitchTrack = (value, aspect) => {
  const keys = pitchKeys(value)
    .map((key) => ({ frame: key.frame, fit: calibrate(key.pairs, aspect) }))
    .filter((key) => key.fit)
    .sort((a, b) => a.frame - b.frame);
  const path = pathOf(value?.pitch?.camera);
  const cache = new Map();
  const rowOf = (frame) => (path && frame >= path.from && frame < path.from + path.rows.length ? path.rows[frame - path.from] : null);
  const stretchOf = (frame) => (rowOf(frame) ? path.stretch[frame - path.from] : null);
  // Least sure step between two frames of one stretch (both ends included, the start's own step left out).
  const sureBetween = (a, b) => {
    let least = 1;
    for (let frame = Math.min(a, b) + 1; frame <= Math.max(a, b); frame += 1) least = Math.min(least, rowOf(frame)?.[8] ?? 0);
    return least;
  };
  const chain = (key, frame) => {
    // Frame -> stretch start -> key: inverse of the key's path after the frame's path.
    const back = invert(matrix(rowOf(key.frame)));
    return back && through(key.fit, multiply(back, matrix(rowOf(frame))));
  };
  const compute = (frame) => {
    if (!keys.length) return null;
    const own = keys.find((key) => key.frame === frame);
    if (own) return { calibration: own.fit, state: "key" };
    const stretch = stretchOf(frame);
    if (stretch === null) {
      if (path) return null; // outside the followed frames: no pitch is known there
      const nearest = keys.reduce((best, key) => (Math.abs(key.frame - frame) < Math.abs(best.frame - frame) ? key : best));
      return { calibration: nearest.fit, state: "held" };
    }
    const mine = keys.filter((key) => stretchOf(key.frame) === stretch);
    const before = mine.filter((key) => key.frame < frame).pop();
    const after = mine.find((key) => key.frame > frame);
    if (!before && !after) return null; // a stretch nobody marked: no pitch rather than a guess
    // A side whose way here crosses a step the engine doubted is left out while the other side is sound.
    let a = before && chain(before, frame);
    let b = after && chain(after, frame);
    const soundA = Boolean(a) && sureBetween(before.frame, frame) >= CHECK_BELOW;
    const soundB = Boolean(b) && sureBetween(frame, after.frame) >= CHECK_BELOW;
    if (soundA !== soundB) [a, b] = soundA ? [a, null] : [null, b];
    const state = soundA || soundB ? "followed" : "check";
    if (a && b) return { calibration: blend(a, b, (frame - before.frame) / (after.frame - before.frame), aspect), state };
    return a || b ? { calibration: a || b, state } : null;
  };
  const at = (frame) => {
    if (!cache.has(frame)) cache.set(frame, compute(frame));
    return cache.get(frame);
  };
  /** Runs of frames [first, last] whose state is `state` ("check", or "none" for followed frames without a pitch). */
  const runs = (state) => {
    if (!path) return [];
    const found = [];
    for (let frame = path.from; frame < path.from + path.rows.length; frame += 1) {
      const here = at(frame);
      const match = state === "none" ? !here : here?.state === state;
      if (!match) continue;
      const last = found[found.length - 1];
      if (last && last[1] === frame - 1) last[1] = frame;
      else found.push([frame, frame]);
    }
    return found;
  };
  return { at, runs, followed: Boolean(path), keys: keys.map((key) => key.frame) };
};

let memo = { pitch: null, aspect: 0, track: null };
/** The clip's pitch track, rebuilt only when the document's pitch changes. */
export const clipPitchTrack = (value, aspect) => {
  const pitch = value?.pitch || null;
  if (memo.pitch !== pitch || memo.aspect !== aspect) memo = { pitch, aspect, track: pitch ? pitchTrack(value, aspect) : null };
  return memo.track;
};

/** The document with a key on `frame` set to `pairs` (added, or replacing that frame's marks). */
export const withKey = (value, frame, pairs) => {
  const keys = pitchKeys(value).filter((key) => key.frame !== frame);
  keys.push({ frame, pairs });
  keys.sort((a, b) => a.frame - b.frame);
  return { ...value, pitch: { ...(value.pitch || {}), keys } };
};

/** The document without the key on `frame`; without the pitch (and its camera) when it was the last. */
export const withoutKey = (value, frame) => {
  const keys = pitchKeys(value).filter((key) => key.frame !== frame);
  const next = { ...value };
  if (keys.length) next.pitch = { ...value.pitch, keys };
  else delete next.pitch;
  return next;
};

/** The document with the engine's camera path (replacing any earlier one). */
export const withCamera = (value, camera) => ({ ...value, pitch: { ...value.pitch, camera } });
