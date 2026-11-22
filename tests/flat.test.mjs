// Drawings flat on the pitch through the clip's calibration (P1, ui/annotate/flat.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { apply, fitHomography, landmark } from "../ui/annotate/pitch.js";
import { arrowOnPitch, pitchCalibration, pitchKey, projectItems, ringOnPitch } from "../ui/annotate/flat.js";
import { newItem } from "../ui/annotate/document.js";

const ASPECT = 16 / 9;
const near = (actual, expected, tolerance, message) => assert.ok(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} vs ${expected}`);

// A broadcast view of the right half: pitch metres -> frame fractions.
const camera = fitHomography([[0, -34], [52.5, -34], [52.5, 34], [0, 34]], [[0.3, 0.22], [1.25, 0.24], [1.05, 1.35], [-0.55, 1.15]]);
const frameOf = (metres) => apply(camera, metres);
const pairs = ["half-far", "circle-right", "box-r-far", "box-r-near", "spot-r", "centre"].map((id) => ({ id, at: frameOf(landmark(id).at) }));
const value = { version: 1, items: [], freezes: [], pitch: { keys: [{ frame: 12, pairs }] } };

test("the clip's calibration comes from its saved key, and none without one", () => {
  assert.equal(pitchKey(value).frame, 12);
  assert.equal(pitchKey({ version: 1, items: [] }), null);
  assert.equal(pitchCalibration({ version: 1, items: [] }, ASPECT), null);
  const fit = pitchCalibration(value, ASPECT);
  assert.ok(fit.worst < 0.01);
  assert.equal(pitchCalibration(value, ASPECT), fit, "the same key and shape are not fitted twice");
});

test("a flat ring is a circle on the grass, so many metres across", () => {
  const fit = pitchCalibration(value, ASPECT);
  const centre = frameOf([30, 5]);
  const edge = frameOf([33, 5]); // 3 m to the right on the pitch
  // The radius is the ring's drag sideways on screen, measured on the grass (not quite 3 m: the
  // screen's sideways is not the pitch's under perspective).
  const ring = ringOnPitch(centre, edge[0] - centre[0], fit);
  const side = fit.toPitch([edge[0], centre[1]]);
  near(ring.metres, Math.hypot(side[0] - 30, side[1] - 5), 1e-6, "radius");
  near(ring.metres, 3, 0.2, "about 3 m");
  // Every point of the outline is that far from the centre on the pitch.
  for (const point of ring.outline) {
    const [x, y] = fit.toPitch(point);
    near(Math.hypot(x - 30, y - 5), ring.metres, 0.01, "outline");
  }
  // Further from the camera the same circle looks smaller.
  const far = ringOnPitch(frameOf([30, -25]), frameOf([33, -25])[0] - frameOf([30, -25])[0], fit);
  const height = (outline) => Math.max(...outline.map((p) => p[1])) - Math.min(...outline.map((p) => p[1]));
  assert.ok(height(far.outline) < height(ring.outline));
});

test("a flat arrow's head lies on the pitch at its tip", () => {
  const fit = pitchCalibration(value, ASPECT);
  const arrow = arrowOnPitch(frameOf([10, 20]), frameOf([40, -10]), fit);
  near(arrow.metres, Math.hypot(30, 30), 0.05, "length");
  const [tip] = arrow.head;
  const [x, y] = fit.toPitch(tip);
  near(x, 40, 0.01, "tip x");
  near(y, -10, 0.01, "tip y");
  const neck = fit.toPitch(arrow.neck);
  near(Math.hypot(neck[0] - 40, neck[1] + 10), 4, 0.01, "a long arrow's head is 4 m of grass");
  assert.equal(arrowOnPitch(frameOf([10, 20]), frameOf([10, 20.05]), fit), null, "too short to point anywhere");
});

test("only flat rings and arrows with fixed points are projected, and the document is not changed", () => {
  const fit = pitchCalibration(value, ASPECT);
  const ring = newItem("ring", [frameOf([30, 5])], { from: 0, to: 2, geometry: { rx: 0.02, ry: 0.01 }, style: { flat: true } });
  const plain = newItem("ring", [frameOf([30, 5])], { from: 0, to: 2, geometry: { rx: 0.02, ry: 0.01 } });
  const arrow = newItem("arrow", [frameOf([10, 20]), frameOf([40, -10])], { from: 0, to: 2, style: { flat: true } });
  const linked = { ...ring, id: "linked", points: [{ track: "t1", dx: 0, dy: 0 }] };
  const zone = { ...newItem("zone", [[0.1, 0.5], [0.4, 0.5], [0.4, 0.8]], { from: 0, to: 2 }), style: { flat: true } };
  const out = projectItems([ring, plain, arrow, linked, zone], fit);
  assert.ok(out[0].projected.outline.length > 60);
  assert.equal(out[1], plain);
  assert.ok(out[2].projected.head);
  assert.equal(out[3], linked, "a ring on a followed player stays as it is");
  assert.equal(out[4], zone);
  assert.equal(ring.projected, undefined);
  assert.equal(projectItems([ring], null)[0], ring, "without a calibration a flat ring is an ordinary ring");
  assert.equal(newItem("ring", [[0.5, 0.5]], { from: 0, to: 1, geometry: { rx: 0.02, ry: 0.01 } }).style.flat, false);
});
