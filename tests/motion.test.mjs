// Followed players' speed, distance and the minimap (P3b, ui/annotate/motion.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { apply, calibrate, fitHomography, landmark } from "../ui/annotate/pitch.js";
import { MAX_KMH, minimapPlayers, motionOf, pitchPositions, speedAt } from "../ui/annotate/motion.js";

const ASPECT = 16 / 9;
const FPS = 25;
const near = (actual, expected, tolerance, message) => assert.ok(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} vs ${expected}`);

// A camera looking across the pitch from one side, panned sideways by `pan` (pitch metres -> frame fractions).
const CORNERS = [[-52.5, -34], [52.5, -34], [52.5, 34], [-52.5, 34]];
const view = (pan = 0) => fitHomography(CORNERS, [[0.15 + pan, 0.3], [0.85 + pan, 0.3], [1.25 + pan, 0.95], [-0.25 + pan, 0.95]]);
const calibration = (pan = 0) => {
  const H = view(pan);
  const ids = ["corner-fl", "corner-fr", "corner-nr", "corner-nl", "centre", "half-far", "half-near", "circle-far"];
  return calibrate(ids.map((id) => ({ id, at: apply(H, landmark(id).at) })), ASPECT);
};
// A followed player whose feet are at pitch position `where(frame)`, seen by a camera panned by `pan(frame)`.
const player = (frames, where, pan = () => 0, id = "t1") => ({
  id, keyframes: {}, from: 0,
  boxes: Array.from({ length: frames }, (_, f) => { const [x, y] = apply(view(pan(f)), where(f)); return [x, y, 0.03, 0.12, 0.9, 0]; }),
});
// The clip's pitch: each frame's calibration, as camera.js gives them (cached per pan).
const pitchOf = (pan = () => 0) => { const cache = new Map(); return { at: (f) => { const p = pan(f); if (!cache.has(p)) cache.set(p, calibration(p)); return { calibration: cache.get(p), state: "followed" }; } }; };

test("a player running at a steady pace is read in km/h and metres", () => {
  const frames = 75; // 3 seconds
  const runner = player(frames, (f) => [-10 + (8 * f) / FPS, 5]); // 8 m/s = 28.8 km/h
  const motion = motionOf(pitchPositions(runner, pitchOf(), 0, frames - 1), FPS, 0);
  near(speedAt(motion, 37), 28.8, 0.3, "mid-run speed");
  near(motion.top, 28.8, 0.3, "top speed");
  near(motion.distance, 8 * ((frames - 1) / FPS), 1, "distance run");
  near(speedAt(motion, 0), 28.8, 0.5, "the first frame leans on the frames after it");
  near(speedAt(motion, frames - 1), 28.8, 0.5, "and the last on those before");
});

test("the tracking box's jitter does not make a steady runner look fast or slow", () => {
  const frames = 100;
  const runner = player(frames, (f) => [-20 + (6 * f) / FPS, 8]); // 6 m/s = 21.6 km/h
  runner.boxes = runner.boxes.map(([x, y, w, h, c, s], f) => [x + 0.003 * Math.sin(f * 2.1), y + 0.003 * Math.cos(f * 1.7), w, h, c, s]);
  const motion = motionOf(pitchPositions(runner, pitchOf(), 0, frames - 1), FPS, 0);
  for (const f of [20, 50, 80]) near(speedAt(motion, f), 21.6, 2.5, `speed on frame ${f}`);
  assert.ok(motion.top < 27, `top speed ${motion.top} is not a jitter spike`);
  near(motion.distance, 6 * ((frames - 1) / FPS), 2.5, "distance");
});

test("a panning camera is not mistaken for the player running", () => {
  const frames = 75;
  const pan = (f) => 0.002 * f; // the picture slides right while the player stands still
  const stander = player(frames, () => [12, -8], pan);
  const moving = motionOf(pitchPositions(stander, pitchOf(pan), 0, frames - 1), FPS, 0);
  assert.ok(moving.top < 1.5, `standing still reads ${moving.top} km/h`);
  assert.ok(moving.distance < 2, `and covers ${moving.distance} m`);
  // Without the camera's pitch on each frame the same player would seem to run.
  const naive = motionOf(pitchPositions(stander, pitchOf(() => 0), 0, frames - 1), FPS, 0);
  assert.ok(naive.top > 4, "a fixed calibration would count the pan as running");
});

test("frames without a pitch or a position are skipped, and an impossible speed is not reported", () => {
  const frames = 60;
  const runner = player(frames, (f) => [0 + (6 * f) / FPS, 0]);
  runner.boxes[20] = null; // lost for a frame
  const noPitch = { at: (f) => (f >= 40 ? null : pitchOf().at(f)) }; // a cut at frame 40
  const positions = pitchPositions(runner, noPitch, 0, frames - 1);
  assert.equal(positions[20], null);
  assert.equal(positions[45], null);
  const motion = motionOf(positions, FPS, 0);
  near(motion.top, 21.6, 0.5, "speed from the frames that are known");
  assert.equal(speedAt(motion, 50), null);
  // A jump (a tracking slip onto another player) is dropped, not read as a sprint.
  const slip = player(frames, (f) => [(f < 30 ? 0 : 40) + (4 * f) / FPS, 0]);
  const slipped = motionOf(pitchPositions(slip, pitchOf(), 0, frames - 1), FPS, 0);
  assert.ok(slipped.top <= MAX_KMH, `top ${slipped.top}`);
  assert.ok(slipped.distance < 30, `the jump is not counted as ${slipped.distance} m run`);
  assert.equal(pitchPositions(runner, null, 0, 3).every((p) => p === null), true, "no pitch at all: no positions");
});

test("the minimap places each followed player on the pitch", () => {
  const fit = calibration();
  const a = player(10, () => [-20, 10], () => 0, "a");
  const b = { ...player(10, () => [30, -15], () => 0, "b"), label: "Winger" };
  const gone = { ...player(10, () => [0, 0], () => 0, "c"), from: 20 }; // not tracked on frame 5
  const players = minimapPlayers([a, b, gone], fit, 5);
  assert.deepEqual(players.map((p) => p.id), ["a", "b"]);
  near(players[0].at[0], -20, 0.05, "x");
  near(players[0].at[1], 10, 0.05, "y");
  assert.equal(players[1].label, "Winger");
  assert.deepEqual(minimapPlayers([a], null, 5), [], "no pitch on the frame: nobody is placed");
});
