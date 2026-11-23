// The offside line and the measure (P3, ui/annotate/flat.js and shapes.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { apply, calibrate, fitHomography, landmark } from "../ui/annotate/pitch.js";
import { isFlat, measureOnPitch, offsideOnPitch, placeFlat, projectItems } from "../ui/annotate/flat.js";
import { hitTest, minimapBox } from "../ui/annotate/shapes.js";
import { newItem } from "../ui/annotate/document.js";

const ASPECT = 16 / 9;
const near = (actual, expected, tolerance, message) => assert.ok(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} vs ${expected}`);

// A camera looking across the pitch from one side: pitch metres -> frame fractions, shifted sideways by `pan`.
const CORNERS = [[-52.5, -34], [52.5, -34], [52.5, 34], [-52.5, 34]];
const view = (pan = 0) => fitHomography(CORNERS, [[0.15 + pan, 0.3], [0.85 + pan, 0.3], [1.25 + pan, 0.95], [-0.25 + pan, 0.95]]);
const calibration = (pan = 0) => {
  const H = view(pan);
  const ids = ["corner-fl", "corner-fr", "corner-nr", "corner-nl", "centre", "half-far", "half-near", "circle-far"];
  return calibrate(ids.map((id) => ({ id, at: apply(H, landmark(id).at) })), ASPECT);
};
const frameOf = (pan, metres) => apply(view(pan), metres);

test("an offside line runs across the pitch at the depth of the clicked spot, touchline to touchline", () => {
  const fit = calibration();
  const line = offsideOnPitch(frameOf(0, [10, 5]), fit);
  assert.ok(line, "the spot is on the pitch");
  near(line.x, 10, 0.05, "its place along the pitch");
  near(line.fromLeft, 62.5, 0.05, "from the left goal line");
  near(line.fromRight, 42.5, 0.05, "from the right goal line");
  const ys = [];
  for (const segment of line.segments) {
    for (const point of segment) {
      const [x, y] = fit.toPitch(point);
      near(x, 10, 0.05, "every point is at the same depth");
      ys.push(y);
    }
  }
  near(Math.min(...ys), -36, 0.1, "runs past the far touchline");
  near(Math.max(...ys), 36, 0.1, "and the near one");
  assert.equal(offsideOnPitch(frameOf(0, [70, 0]), fit), null, "a spot far off the pitch gives no line");
});

test("a measure reads the distance on the grass, not on the screen", () => {
  const fit = calibration();
  const along = measureOnPitch(frameOf(0, [-10, 20]), frameOf(0, [20, 20]), fit);
  near(along.metres, 30, 0.05, "30 m along the near side");
  const far = measureOnPitch(frameOf(0, [-10, -30]), frameOf(0, [20, -30]), fit);
  near(far.metres, 30, 0.05, "the same distance on the far side, which is smaller on screen");
  const screen = (a, b) => Math.hypot((a[0] - b[0]) * ASPECT, a[1] - b[1]);
  assert.ok(screen(frameOf(0, [-10, -30]), frameOf(0, [20, -30])) < 0.7 * screen(frameOf(0, [-10, 20]), frameOf(0, [20, 20])));
  const [mx, my] = along.mid;
  const [ex, ey] = frameOf(0, [5, 20]);
  near(mx, ex, 1e-4, "the label sits at the middle of the grass between them");
  near(my, ey, 1e-4, "the label's height too");
  assert.equal(measureOnPitch([0.5, 0.5], [0.5, 0.5], fit), null, "no distance between one spot and itself");
});

test("offside lines and measures are always flat, and are read through the calibration", () => {
  const fit = calibration();
  const offside = newItem("offside", [frameOf(0, [10, 5])], { from: 0, to: 2 });
  const measure = newItem("measure", [frameOf(0, [0, 0]), frameOf(0, [20, 0])], { from: 0, to: 2 });
  assert.ok(isFlat(offside) && isFlat(measure));
  assert.ok(isFlat({ ...offside, style: {} }), "whatever the style says");
  assert.ok(!isFlat({ ...offside, on: 3 }), "not on a board");
  assert.ok(!isFlat({ ...offside, points: [{ track: "t", dx: 0, dy: 0 }] }), "not following a player");
  const [a, b] = projectItems([offside, measure], fit);
  assert.ok(a.projected.segments.length && Number.isFinite(a.projected.x));
  near(b.projected.metres, 20, 0.05, "the measure's length");
  assert.equal(projectItems([offside], null)[0], offside, "without a calibration they are as drawn");
});

test("they keep their place on the grass as the camera pans", () => {
  const then = calibration(0);
  const now = calibration(0.2);
  const track = { followed: true, keys: [0], at: (frame) => ({ calibration: frame === 0 ? then : now }) };
  const offside = { ...newItem("offside", [frameOf(0, [10, 5])], { from: 0, to: 2 }), at: 0 };
  const placed = placeFlat(offside, track, 10);
  near(now.toPitch(placed.points[0])[0], 10, 0.05, "the offside line is still at 10 m");
  const measure = { ...newItem("measure", [frameOf(0, [0, 10]), frameOf(0, [20, 10])], { from: 0, to: 2 }), at: 0 };
  const moved = placeFlat(measure, track, 10);
  near(measureOnPitch(moved.points[0], moved.points[1], now).metres, 20, 0.05, "and the measure is still 20 m");
  assert.equal(placeFlat(offside, { ...track, at: () => null }, 10).offPitch, true, "no pitch on the frame: not drawn");
});

test("an offside line is hit on its line and on its spot, and a measure along its length", () => {
  const fit = calibration();
  const [w, h] = [1600, 900];
  const [offside] = projectItems([newItem("offside", [frameOf(0, [10, 5])], { from: 0, to: 2 })], fit);
  const onLine = offside.projected.segments[0][Math.floor(offside.projected.segments[0].length / 2)];
  assert.ok(hitTest(offside, onLine[0] * w, onLine[1] * h, w, h, 4));
  assert.ok(hitTest(offside, offside.points[0][0] * w, offside.points[0][1] * h, w, h, 4));
  const away = frameOf(0, [40, 0]);
  assert.ok(!hitTest(offside, away[0] * w, away[1] * h, w, h, 4));
  const measure = newItem("measure", [[0.2, 0.5], [0.6, 0.5]], { from: 0, to: 2 });
  assert.ok(hitTest(measure, 0.4 * w, 0.5 * h, w, h, 4));
  assert.ok(!hitTest(measure, 0.4 * w, 0.7 * h, w, h, 4));
});

test("a minimap is a box from its top-left corner, hit anywhere inside it", () => {
  const [w, h] = [1600, 900];
  const map = newItem("minimap", [[0.7, 0.05]], { from: 0, to: 2 });
  const box = minimapBox(map, w, h);
  near(box.x, 0.7 * w, 1e-6, "left edge");
  near(box.y, 0.05 * h, 1e-6, "top edge");
  near(box.width, 60 * 4 * (h / 1080), 1e-6, "width follows the frame height");
  near(box.height / box.width, (68 + 8) / (105 + 8), 1e-6, "in the pitch's own proportions, with grass round it");
  assert.ok(hitTest(map, box.x + box.width / 2, box.y + box.height / 2, w, h, 4));
  assert.ok(!hitTest(map, box.x - 40, box.y + 5, w, h, 4));
  assert.ok(!isFlat(map), "it is placed on the picture, not on the grass");
  assert.equal(projectItems([map], calibration())[0], map, "and is not read through the calibration");
});

test("a measure end linked to a followed player moves with them", async () => {
  const { newTrack, linkTo, resolveItem } = await import("../ui/annotate/tracks.js");
  // A player who walks from left to right across the frame over 50 frames.
  const track = { ...newTrack(0, [0.2, 0.9, 0.05, 0.2]), boxes: [] };
  track.keyframes["50"] = [0.6, 0.9, 0.05, 0.2];
  const fixed = [0.9, 0.5];
  const measure = newItem("measure", [linkTo(track, [0.2, 0.9], 0), fixed], { from: 0, to: 60 });
  const early = resolveItem(measure, [track], 0).points;
  const late = resolveItem(measure, [track], 50).points;
  near(early[0][0], 0.2, 1e-6, "starts at the player's feet");
  near(late[0][0], 0.6, 1e-6, "ends where the player is later");
  assert.deepEqual(late[1], fixed, "the other end stays put");
});
