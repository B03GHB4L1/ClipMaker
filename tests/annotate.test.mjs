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
