// Where followed players are on the pitch, how fast they run, and the minimap (P3b,
// docs/CODING_AND_PITCH_PLAN.md section P). A followed player's feet are a spot in the frame;
// each frame's own calibration (ui/annotate/camera.js) turns that spot into metres on the pitch,
// so a panning or zooming camera is not mistaken for the player running. Pure functions.

import { ownBox } from "./tracks.js";

export const SPEED_WINDOW = 0.5; // seconds a speed is measured over
export const SMOOTH_SECONDS = 0.3; // positions are averaged over this long before speeds are taken
export const MAX_KMH = 45; // faster than any player runs: a tracking slip, not speed
const MAX_GAP = 5; // frames without a position that still count as one run when adding up distance

const finite = (point) => point && Number.isFinite(point[0]) && Number.isFinite(point[1]);

/** The player's feet in pitch metres on frames `from` to `to` (inclusive): [x, y] or null where unknown. */
export const pitchPositions = (track, pitchTrack, from, to) => {
  const positions = [];
  for (let frame = from; frame <= to; frame += 1) {
    const own = pitchTrack ? ownBox(track, frame) : null;
    const calibration = own && pitchTrack.at(frame)?.calibration;
    const metres = calibration ? calibration.toPitch([own.box[0], own.box[1]]) : null;
    positions.push(finite(metres) ? metres : null);
  }
  return positions;
};

/**
 * Each position replaced by a straight line fitted through its neighbours within `reach` frames and
 * read at that frame: it takes out the box's jitter without pulling the ends, or the frames beside a
 * gap, towards the middle (an average would). Null where the frame or too many of its neighbours are unknown.
 */
const smooth = (positions, reach) => positions.map((_, index) => {
  if (!positions[index]) return null;
  const known = [];
  for (let i = Math.max(0, index - reach); i <= Math.min(positions.length - 1, index + reach); i += 1) {
    if (positions[i]) known.push([i - index, positions[i]]);
  }
  if (known.length < Math.min(3, reach + 1)) return null;
  const n = known.length;
  const [st, stt] = known.reduce(([a, b], [t]) => [a + t, b + t * t], [0, 0]);
  const det = n * stt - st * st;
  if (Math.abs(det) < 1e-9) return positions[index];
  // Least squares x(t) = a + b t; at t = 0 (this frame) the fit is a.
  const at = (axis) => {
    const [sx, stx] = known.reduce(([a, b], [t, p]) => [a + p[axis], b + t * p[axis]], [0, 0]);
    return (sx * stt - st * stx) / det;
  };
  return [at(0), at(1)];
});

/**
 * How a player moved over frames `from`..`to`, from their pitch positions at `fps`:
 * {speeds (km/h per frame, null where unknown), top, topFrame, distance (metres), seconds (with a position)}.
 */
export const motionOf = (positions, fps, from = 0) => {
  const reach = Math.max(1, Math.round((SMOOTH_SECONDS * fps) / 2));
  const half = Math.max(1, Math.round((SPEED_WINDOW * fps) / 2));
  const calm = smooth(positions, reach);
  // Speed over a window centred on the frame; at the start or end of what is known (or beside a gap) the
  // window leans forward or back instead, so the first and last moments of a track still read.
  const between = (i, j) => {
    const [a, b] = [calm[i], calm[j]];
    return a && b ? (Math.hypot(b[0] - a[0], b[1] - a[1]) / ((j - i) / fps)) * 3.6 : null;
  };
  const speeds = calm.map((point, index) => {
    if (!point) return null;
    for (const [i, j] of [[index - half, index + half], [index, index + 2 * half], [index - 2 * half, index]]) {
      const kmh = i >= 0 && j < calm.length ? between(i, j) : null;
      if (kmh !== null) return kmh <= MAX_KMH ? kmh : null;
    }
    return null;
  });
  let [distance, last, gap] = [0, null, 0];
  calm.forEach((point) => {
    if (!point) { gap += 1; return; }
    if (last && gap <= MAX_GAP) {
      const step = Math.hypot(point[0] - last[0], point[1] - last[1]);
      if ((step * fps * 3.6) <= MAX_KMH) distance += step;
    }
    last = point;
    gap = 0;
  });
  let [top, topFrame] = [0, null];
  speeds.forEach((kmh, index) => { if (kmh !== null && kmh > top) { top = kmh; topFrame = from + index; } });
  return { speeds, top, topFrame, distance, seconds: calm.filter(Boolean).length / fps, from };
};

/** Speed on `frame` in km/h (null where it cannot be read). */
export const speedAt = (motion, frame) => motion.speeds[frame - motion.from] ?? null;

/**
 * The followed players on the pitch for the minimap on `frame`: [{id, label, at: [x, y] metres}] for
 * those with a position there. `calibration` is the pitch on that frame (null: nobody can be placed).
 */
export const minimapPlayers = (tracks, calibration, frame, boxOf = ownBox) => {
  if (!calibration) return [];
  const players = [];
  (tracks || []).forEach((track) => {
    const own = boxOf(track, frame);
    const at = own && calibration.toPitch([own.box[0], own.box[1]]);
    if (finite(at) && Math.abs(at[0]) <= 60 && Math.abs(at[1]) <= 40) players.push({ id: track.id, label: track.label || "", at });
  });
  return players;
};
