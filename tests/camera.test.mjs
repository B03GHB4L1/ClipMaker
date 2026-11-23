// The pitch on every frame from marked frames and the followed camera (P2, ui/annotate/camera.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { apply, fitHomography, invert, landmark } from "../ui/annotate/pitch.js";
import { CHECK_BELOW, keyAt, pitchKeys, pitchTrack, withCamera, withKey, withoutKey } from "../ui/annotate/camera.js";
import { placeFlat, projectItems } from "../ui/annotate/flat.js";
import { newItem } from "../ui/annotate/document.js";

const ASPECT = 16 / 9;
const FRAMES = 60;
const near = (actual, expected, tolerance, message) => assert.ok(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} vs ${expected}`);
const nearPoint = (a, b, tolerance, message) => { near(a[0], b[0], tolerance, `${message} x`); near(a[1], b[1], tolerance, `${message} y`); };

// A camera panning right and zooming in over the clip: pitch metres -> frame fractions on frame f.
const CORNERS = [[0, -34], [52.5, -34], [52.5, 34], [0, 34]];
const camera = (f) => {
  const zoom = 1 + 0.004 * f;
  const at = [[0.3, 0.22], [1.25, 0.24], [1.05, 1.35], [-0.55, 1.15]]
    .map(([x, y]) => [0.5 + (x - 0.5 - 0.012 * f) * zoom, 0.5 + (y - 0.5) * zoom]);
  return fitHomography(CORNERS, at);
};
const multiply = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((s, v, k) => s + v * B[k][j], 0)));
const rowOf = (M, sure = 0.9) => { const n = M.map((r) => r.map((v) => v / M[2][2])); return [...n[0], ...n[1], n[2][0], n[2][1], sure]; };
// The engine's path: frame f -> first frame of its stretch (frame `start`).
const path = (starts = [0], sure = () => 0.9) => ({
  from: 0,
  starts,
  rows: Array.from({ length: FRAMES }, (_, f) => {
    const start = Math.max(...starts.filter((s) => s <= f));
    return rowOf(multiply(camera(start), invert(camera(f))), f === start ? 1 : sure(f));
  }),
});
const marks = (f) => ["half-far", "circle-right", "box-r-far", "box-r-near", "spot-r", "centre"]
  .map((id) => ({ id, at: apply(camera(f), landmark(id).at) }));
const doc = (keys, cameraPath) => ({ version: 1, items: [], freezes: [], pitch: { keys: keys.map((f) => ({ frame: f, pairs: marks(f) })), ...(cameraPath ? { camera: cameraPath } : {}) } });
// Where pitch point `metres` really is on frame f.
const truth = (f, metres) => apply(camera(f), metres);

test("from one marked frame the followed camera gives every frame its pitch", () => {
  const track = pitchTrack(doc([0], path()), ASPECT);
  assert.equal(track.at(0).state, "key");
  for (const f of [1, 20, 59]) {
    const here = track.at(f);
    assert.equal(here.state, "followed");
    nearPoint(here.calibration.toFrame([30, 5]), truth(f, [30, 5]), 1e-4, `frame ${f}`);
    const [x, y] = here.calibration.toPitch(truth(f, [40, -10]));
    near(x, 40, 0.01, "back to the pitch x");
    near(y, -10, 0.01, "back to the pitch y");
  }
  assert.equal(track.at(FRAMES), null, "past the followed frames no pitch is known");
  assert.deepEqual(track.runs("check"), []);
  assert.deepEqual(track.runs("none"), []);
});

test("between two marked frames the pitch leans on the nearer one, so it reaches each without a jump", () => {
  // The followed path drifts: every frame is off by a little more, as real following does.
  const drifting = path();
  drifting.rows = drifting.rows.map((row, f) => { const next = row.slice(); next[2] += 0.0006 * f; return next; });
  const one = pitchTrack(doc([0], drifting), ASPECT);
  const two = pitchTrack(doc([0, 40], drifting), ASPECT);
  const error = (track, f) => Math.hypot(...track.at(f).calibration.toFrame([30, 5]).map((v, i) => v - truth(f, [30, 5])[i]));
  assert.ok(error(one, 39) > 0.015, "from frame 0 alone the drift shows by frame 39");
  assert.ok(error(two, 39) < 0.002, "with frame 40 marked, frame 39 is nearly right");
  assert.ok(error(two, 20) < error(one, 20), "and the middle is better than one key alone");
  assert.ok(error(two, 1) < 0.001, "next to a marked frame it is that frame's pitch");
  assert.equal(two.at(40).state, "key");
  assert.deepEqual(two.keys, [0, 40]);
});

test("a scene cut ends the followed pitch until the pitch is marked after it", () => {
  const cut = path([0, 25]);
  const before = pitchTrack(doc([0], cut), ASPECT);
  assert.equal(before.at(24).state, "followed");
  assert.equal(before.at(25), null, "no guess after the cut");
  assert.deepEqual(before.runs("none"), [[25, FRAMES - 1]]);
  const after = pitchTrack(doc([0, 30], cut), ASPECT);
  assert.equal(after.at(25).state, "followed");
  nearPoint(after.at(27).calibration.toFrame([30, 5]), truth(27, [30, 5]), 1e-4, "after the cut");
  assert.deepEqual(after.runs("none"), []);
});

test("frames the camera was hard to follow on are flagged to check, unless a marked frame on the other side is sound", () => {
  const doubtful = path([0], (f) => (f === 12 ? CHECK_BELOW / 2 : 0.9));
  const one = pitchTrack(doc([0], doubtful), ASPECT);
  assert.equal(one.at(11).state, "followed");
  assert.equal(one.at(12).state, "check", "the doubtful step itself");
  assert.equal(one.at(30).state, "check", "and every frame reached through it");
  assert.deepEqual(one.runs("check"), [[12, FRAMES - 1]]);
  // Marked again after the doubtful step: each side is reached without crossing it.
  const two = pitchTrack(doc([0, 50], doubtful), ASPECT);
  assert.deepEqual(two.runs("check"), []);
  nearPoint(two.at(12).calibration.toFrame([30, 5]), truth(12, [30, 5]), 1e-4, "frame 12 from frame 50");
  nearPoint(two.at(11).calibration.toFrame([30, 5]), truth(11, [30, 5]), 1e-4, "frame 11 from frame 0");
});

test("without a followed camera each frame takes the nearest marked frame's pitch, as before (P1)", () => {
  const track = pitchTrack(doc([5, 40]), ASPECT);
  assert.equal(track.followed, false);
  assert.equal(track.at(10).state, "held");
  assert.equal(track.at(10).calibration, track.at(5).calibration);
  assert.equal(track.at(30).calibration, track.at(40).calibration);
});

test("a flat ring and arrow keep their place on the grass as the camera moves", () => {
  const track = pitchTrack(doc([0], path()), ASPECT);
  const fit0 = track.at(0).calibration;
  const centre = truth(10, [30, 5]);
  const ring = { ...newItem("ring", [centre], { from: 0, to: 2, geometry: { rx: 0.03, ry: 0.012 }, style: { flat: true } }), at: 10 };
  const arrow = { ...newItem("arrow", [truth(10, [10, 20]), truth(10, [40, -10])], { from: 0, to: 2, style: { flat: true } }), at: 10 };
  const size = projectItems([ring], track.at(10).calibration)[0].projected.metres;
  for (const f of [0, 10, 45]) {
    const placed = placeFlat(ring, track, f);
    nearPoint(placed.points[0], truth(f, [30, 5]), 1e-4, `ring centre on frame ${f}`);
    near(projectItems([placed], track.at(f).calibration)[0].projected.metres, size, 0.05 * size, `ring size on frame ${f}`);
    const pointed = placeFlat(arrow, track, f);
    nearPoint(pointed.points[1], truth(f, [40, -10]), 1e-4, `arrow tip on frame ${f}`);
  }
  assert.equal(placeFlat(ring, track, 10), ring, "on its own frame it is as drawn");
  // Older flat drawings without a frame are taken as drawn on the first marked frame.
  const old = newItem("ring", [apply(camera(0), [30, 5])], { from: 0, to: 2, geometry: { rx: 0.03, ry: 0.012 }, style: { flat: true } });
  nearPoint(placeFlat(old, track, 45).points[0], truth(45, [30, 5]), 1e-4, "older ring");
  // Not flat, on a board, or no pitch on that frame: left as it is.
  const plain = newItem("ring", [centre], { from: 0, to: 2, geometry: { rx: 0.03, ry: 0.012 } });
  assert.equal(placeFlat(plain, track, 45), plain);
  assert.equal(placeFlat({ ...ring, on: 3 }, track, 45).points, ring.points);
  assert.equal(placeFlat(ring, track, FRAMES + 5).offPitch, true, "where no pitch is known (after a cut) it is not drawn");
  assert.equal(placeFlat(ring, pitchTrack(doc([0]), ASPECT), 45), ring, "without a followed camera it stays as drawn (P1)");
  assert.ok(fit0);
});

test("marked frames are added, replaced and removed; the last one takes the camera with it", () => {
  let value = doc([10]);
  value = withKey(value, 3, marks(3));
  assert.deepEqual(pitchKeys(value).map((key) => key.frame), [3, 10]);
  value = withKey(value, 10, marks(11));
  assert.equal(pitchKeys(value).length, 2);
  assert.deepEqual(keyAt(value, 10).pairs, marks(11));
  value = withCamera(value, path());
  assert.equal(value.pitch.camera.rows.length, FRAMES);
  value = withoutKey(value, 3);
  assert.deepEqual(pitchKeys(value).map((key) => key.frame), [10]);
  assert.ok(value.pitch.camera, "the camera's path stays while a frame is marked");
  value = withoutKey(value, 10);
  assert.equal(value.pitch, undefined);
});
