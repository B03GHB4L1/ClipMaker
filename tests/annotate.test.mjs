// Analyst editor drawing model (ui/annotate/): undo/redo, editing and hit-testing.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createDocument, dragHandle, moveItem, newItem, ringGeometry, simplify } from "../ui/annotate/document.js";
import { handlesFor, hitTest, itemAt, visibleAt } from "../ui/annotate/shapes.js";

const W = 1920;
const H = 1080;
const ring = (x = 0.5, y = 0.5) => newItem("ring", [[x, y]], { from: 0, to: 2, geometry: ringGeometry(0.03, W / H) });

test("undo and redo step through every change, and a new change clears redo", () => {
  const doc = createDocument();
  const first = ring();
  doc.add(first);
  doc.replace(moveItem(first, 0.1, 0));
  assert.equal(doc.items[0].points[0][0], 0.6);
  assert.ok(doc.undo());
  assert.equal(doc.items[0].points[0][0], 0.5);
  assert.ok(doc.undo());
  assert.equal(doc.items.length, 0);
  assert.equal(doc.undo(), false);
  assert.ok(doc.redo());
  assert.equal(doc.items.length, 1);
  doc.remove(first.id);
  assert.equal(doc.canRedo, false);
});

test("a change that changes nothing is not an undo step", () => {
  const doc = createDocument();
  const item = ring();
  doc.add(item);
  assert.equal(doc.replace(doc.find(item.id)), false);
  doc.undo();
  assert.equal(doc.items.length, 0);
});

test("history snapshots are copies, so later edits cannot rewrite the past", () => {
  const doc = createDocument();
  const item = ring();
  doc.add(item);
  doc.items[0].points[0][0] = 0.9; // a careless caller mutating the live value
  doc.replace(moveItem(doc.find(item.id), 0, 0.1));
  doc.undo();
  assert.notEqual(doc.items[0].points[0][1], 0.6);
});

test("new drawings are clamped to the frame margin and timed", () => {
  const item = newItem("arrow", [[-2, 0.5], [0.5, 3]], { from: 1.23456, to: 4 });
  assert.deepEqual(item.points, [[-0.5, 0.5], [0.5, 1.5]]);
  assert.equal(item.show.from, 1.235);
  assert.equal(item.style.stroke, "#ffd400");
  assert.match(item.id, /^[A-Za-z0-9_-]{1,40}$/);
});

test("rings lie flat and keep their shape when resized", () => {
  const item = ring();
  assert.ok(Math.abs(item.geometry.ry * H - item.geometry.rx * W * 0.35) < 1);
  const bigger = dragHandle(item, "r", [0.56, 0.5]);
  assert.ok(Math.abs(bigger.geometry.rx - 0.06) < 1e-6);
  assert.ok(Math.abs(bigger.geometry.ry / bigger.geometry.rx - item.geometry.ry / item.geometry.rx) < 1e-3);
});

test("hit-testing finds lines, zones, rings and text, and only when visible", () => {
  const line = newItem("line", [[0.1, 0.1], [0.9, 0.1]], { from: 0, to: 1 });
  assert.ok(hitTest(line, W * 0.5, H * 0.1 + 5, W, H));
  assert.ok(!hitTest(line, W * 0.5, H * 0.3, W, H));
  const zone = newItem("zone", [[0.2, 0.4], [0.4, 0.4], [0.4, 0.6], [0.2, 0.6]], { from: 0, to: 1 });
  assert.ok(hitTest(zone, W * 0.3, H * 0.5, W, H));
  assert.ok(!hitTest(zone, W * 0.6, H * 0.5, W, H));
  const text = newItem("text", [[0.7, 0.7]], { from: 0, to: 1, text: "Press here" });
  assert.ok(hitTest(text, W * 0.7 + 30, H * 0.7 + 20, W, H));
  const later = ring(0.3, 0.5);
  later.show = { from: 1.5, to: 2, animate: "none" };
  assert.equal(itemAt([later], W * 0.3, H * 0.5, W, H, 0.5), null);
  assert.equal(visibleAt(later, 1.6), true);
});

test("the item drawn last wins where drawings overlap", () => {
  const under = ring(0.5, 0.5);
  const over = ring(0.5, 0.5);
  assert.equal(itemAt([under, over], W * 0.5, H * 0.5, W, H, 1).id, over.id);
});

test("spotlights can be grabbed by their beam and have size and beam handles", () => {
  const light = newItem("spotlight", [[0.5, 0.8]], { from: 0, to: 1, geometry: { ...ringGeometry(0.04, W / H), h: 0.3 } });
  assert.ok(hitTest(light, W * 0.5, H * 0.6, W, H));
  assert.deepEqual(handlesFor(light).map((handle) => handle.index), [0, "r", "h"]);
  assert.ok(Math.abs(dragHandle(light, "h", [0.5, 0.4]).geometry.h - 0.4) < 1e-6);
});

test("freehand strokes are thinned but keep both ends", () => {
  const points = Array.from({ length: 200 }, (_, i) => [i / 2000, 0.5]);
  const kept = simplify(points, 3, W, H);
  assert.ok(kept.length < 70);
  assert.deepEqual(kept[0], points[0]);
  assert.deepEqual(kept.at(-1), points.at(-1));
});

// ---------------------------------------------------------------------------
// M2: freezes and animation
// ---------------------------------------------------------------------------
import { readFileSync } from "node:fs";
import { animation, outputToSource, setFreeze, stops, totalSeconds, freezeStart } from "../ui/annotate/timeline.js";
import { partialPath } from "../ui/annotate/shapes.js";

const cases = JSON.parse(readFileSync(new URL("./fixtures/timeline_cases.json", import.meta.url), "utf-8"));

test("output time maps to source frames through freezes (shared fixture)", () => {
  assert.ok(Math.abs(totalSeconds(cases.clip, cases.freezes) - cases.total) < 1e-9);
  for (const c of cases.mapping) {
    const at = outputToSource(c.t, cases.clip, cases.freezes);
    assert.deepEqual([at.frame, at.freeze], [c.frame, c.freeze], `t=${c.t}`);
  }
});

test("animation progress matches the engine (shared fixture)", () => {
  for (const c of cases.animation) {
    const state = animation(c.item, c.t);
    if (c.state === null) { assert.equal(state, null); continue; }
    for (const [key, expected] of Object.entries(c.state)) {
      if (expected === null) assert.equal(state[key], null, key);
      else assert.ok(Math.abs(state[key] - expected) < 1e-6, `${key}: ${state[key]} vs ${expected} for ${JSON.stringify(c.item.show)}`);
    }
  }
});

test("frame stepping stops at every frame and at both ends of each freeze", () => {
  const clip = { fps: 10, duration: 0.5, frames: 5 };
  const list = stops(clip, [{ atFrame: 2, seconds: 1.5 }]);
  const expected = [0, 0.1, 0.2, 1.7, 1.8, 1.9];
  assert.equal(list.length, expected.length);
  list.forEach((t, i) => assert.ok(Math.abs(t - expected[i]) < 1e-9, `${t} vs ${expected[i]}`));
});

test("adding, resizing and removing a freeze keeps drawings on the same picture", () => {
  const clip = { fps: 25, duration: 4, frames: 100 };
  const at = (from, to) => ({ ...ring(), show: { from, to, animate: "none" } });
  let doc = { version: 1, freezes: [], items: [at(1, 3), at(0.5, 0.9), at(2, 4)] };
  doc = setFreeze(doc, clip, 25, 2); // frame 25 starts at 1.0 s
  assert.deepEqual(doc.freezes, [{ atFrame: 25, seconds: 2 }]);
  assert.deepEqual(doc.items.map((i) => [i.show.from, i.show.to]), [[1, 5], [0.5, 0.9], [4, 6]]);
  const inside = { ...ring(), show: { from: 2.5, to: 2.8, animate: "none" } }; // drawn during the freeze
  doc = { ...doc, items: [...doc.items, inside] };
  doc = setFreeze(doc, clip, 25, 1); // shrink by 1 s
  assert.deepEqual(doc.items.map((i) => [i.show.from, i.show.to]), [[1, 4], [0.5, 0.9], [3, 5], [2, 2]]);
  doc = setFreeze(doc, clip, 25, 0); // remove
  assert.deepEqual(doc.freezes, []);
  assert.deepEqual(doc.items.map((i) => [i.show.from, i.show.to]), [[1, 3], [0.5, 0.9], [2, 4], [1, 1]]);
  assert.equal(freezeStart(25, clip, []), 1);
});

test("freeze changes are one undo step with the drawings they move", () => {
  const clip = { fps: 25, duration: 4, frames: 100 };
  const doc = createDocument();
  doc.add({ ...ring(), show: { from: 2, to: 4, animate: "none" } });
  doc.commitDocument((value) => setFreeze(value, clip, 25, 2));
  assert.equal(doc.items[0].show.from, 4);
  doc.undo();
  assert.deepEqual([doc.freezes.length, doc.items[0].show.from], [0, 2]);
});

test("draw-on traces the first part of a path by length", () => {
  const path = [[0, 0], [10, 0], [10, 10]];
  assert.deepEqual(partialPath(path, 0.25), [[0, 0], [5, 0]]);
  assert.deepEqual(partialPath(path, 0.75), [[0, 0], [10, 0], [10, 5]]);
  assert.deepEqual(partialPath(path, 1), path);
  // A closed zone outline runs back to its first corner: perimeter 10 + 10 + 14.14, half way is 7.07 up the second side.
  const [x, y] = partialPath(path, 0.5, true).at(-1);
  assert.ok(Math.abs(x - 10) < 1e-9 && Math.abs(y - 7.0710678) < 1e-6, `${x}, ${y}`);
});

// ---------------------------------------------------------------------------
// M3: followed players and linked points
// ---------------------------------------------------------------------------
import { boxAt, flaggedRuns, linkTo, mergeRows, newTrack, pruneTracks, resolveItem, setKeyframe, spanEnd } from "../ui/annotate/tracks.js";

const row = (fx, state = 0) => [fx, 0.8, 0.02, 0.1, 0.9, state];

test("a player's position comes from keyframes first, then tracking, and holds across gaps", () => {
  let track = newTrack(10, [0.1, 0.8, 0.02, 0.1]);
  track = mergeRows(track, 10, 14, [row(0.1, 1), row(0.11), row(0.12, 2), null, row(0.14)]);
  assert.equal(boxAt(track, 11).box[0], 0.11);
  assert.equal(boxAt(track, 12).state, 2);
  assert.deepEqual([boxAt(track, 13).box[0], boxAt(track, 13).held], [0.12, true]); // gap: hold the last place
  assert.deepEqual([boxAt(track, 5).box[0], boxAt(track, 5).held], [0.1, true]); // before tracking: the first place
  assert.deepEqual([boxAt(track, 40).box[0], boxAt(track, 40).held], [0.14, true]);
  track = setKeyframe(track, 11, [0.3, 0.8, 0.02, 0.1]);
  assert.deepEqual([boxAt(track, 11).box[0], boxAt(track, 11).state], [0.3, 1]); // the analyst wins
});

test("lost frames are not used as positions", () => {
  const track = mergeRows(newTrack(0, [0.1, 0.8, 0.02, 0.1]), 0, 2, [row(0.1, 1), row(0.2), row(0.9, 3)]);
  assert.deepEqual([boxAt(track, 2).box[0], boxAt(track, 2).held], [0.2, true]);
  assert.deepEqual(flaggedRuns(track, 3), [[2, 2]]);
});

test("re-tracking a span replaces only that span and trims empty ends", () => {
  let track = mergeRows(newTrack(0, [0.1, 0.8, 0.02, 0.1]), 0, 5, [0, 1, 2, 3, 4, 5].map((i) => row(i / 10)));
  track = mergeRows(track, 3, 8, [row(0.33), row(0.44)]); // stopped early, after two frames
  assert.deepEqual(track.boxes.map((r) => r && r[0]), [0, 0.1, 0.2, 0.33, 0.44]);
  assert.equal(track.from, 0);
  const later = mergeRows(newTrack(20, [0.5, 0.8, 0.02, 0.1]), 20, 25, [row(0.5, 1), row(0.51)]);
  assert.deepEqual([later.from, later.boxes.length], [20, 2]);
});

test("tracking from a keyframe stops before the next one", () => {
  const track = setKeyframe(newTrack(10, [0.1, 0.8, 0.02, 0.1]), 40, [0.4, 0.8, 0.02, 0.1]);
  assert.equal(spanEnd(track, 10, 100), 39);
  assert.equal(spanEnd(track, 40, 100), 100);
  assert.equal(spanEnd(track, 10, 20), 20);
});

test("linked points follow their player; fixed points stay put", () => {
  const track = mergeRows(newTrack(0, [0.2, 0.8, 0.02, 0.1]), 0, 1, [row(0.2, 1), row(0.6)]);
  const zone = newItem("zone", [linkTo(track, [0.2, 0.8], 0), [0.9, 0.9], { track: track.id, dx: 0.05, dy: -0.1 }], { from: 0, to: 1 });
  assert.deepEqual(zone.points[0], { track: track.id, dx: 0, dy: 0 });
  const placed = resolveItem(zone, [track], 1);
  const expected = [[0.6, 0.8], [0.9, 0.9], [0.65, 0.7]];
  placed.points.forEach((point, i) => point.forEach((v, j) => assert.ok(Math.abs(v - expected[i][j]) < 1e-9, `${i},${j}`)));
  assert.equal(resolveItem(ring(), [track], 1).points[0][0], 0.5); // nothing linked: unchanged
  const moved = moveItem(zone, 0.1, 0);
  assert.deepEqual([moved.points[0], moved.points[1]], [zone.points[0], [1, 0.9]]); // only fixed points move
});

test("players nothing follows any more are dropped", () => {
  const kept = newTrack(0, [0.2, 0.8, 0.02, 0.1]);
  const gone = newTrack(0, [0.4, 0.8, 0.02, 0.1]);
  const item = newItem("ring", [{ track: kept.id, dx: 0, dy: 0 }], { from: 0, to: 1, geometry: ringGeometry(0.03, 16 / 9) });
  const doc = pruneTracks({ version: 1, freezes: [], items: [item], tracks: [kept, gone] });
  assert.deepEqual(doc.tracks.map((t) => t.id), [kept.id]);
  assert.equal("tracks" in pruneTracks({ ...doc, items: [] }), false);
});
