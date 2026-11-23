// The Shape tool's geometric shapes (ui/annotate/shapes.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { SHAPES, hitTest, shapeOutline } from "../ui/annotate/shapes.js";
import { newItem } from "../ui/annotate/document.js";

test("every shape fills the box between its two corners, whichever way it was dragged", () => {
  for (const name of Object.keys(SHAPES)) {
    for (const [a, b] of [[[0.2, 0.3], [0.6, 0.7]], [[0.6, 0.7], [0.2, 0.3]], [[0.6, 0.3], [0.2, 0.7]]]) {
      const outline = shapeOutline(name, a, b);
      const xs = outline.map((p) => p[0]);
      const ys = outline.map((p) => p[1]);
      for (const [value, expected] of [[Math.min(...xs), 0.2], [Math.max(...xs), 0.6], [Math.min(...ys), 0.3], [Math.max(...ys), 0.7]]) {
        assert.ok(Math.abs(value - expected) < 1e-9, `${name}: ${value} vs ${expected}`);
      }
    }
  }
  assert.equal(shapeOutline("rect", [0, 0], [1, 1]).length, 4);
  assert.equal(shapeOutline("star", [0, 0], [1, 1]).length, 10);
  assert.equal(shapeOutline("unknown", [0, 0], [1, 1]).length, 4, "an unknown name draws a rectangle");
});

test("a shape is hit inside its outline, not in the empty corners of its box", () => {
  const shape = (name) => newItem("shape", [[0.2, 0.2], [0.6, 0.6]], { from: 0, to: 1, geometry: { shape: name } });
  const [w, h] = [1000, 1000];
  assert.ok(hitTest(shape("ellipse"), 400, 400, w, h));
  assert.ok(!hitTest(shape("ellipse"), 215, 215, w, h, 2), "the ellipse leaves the box's corners empty");
  assert.ok(hitTest(shape("rect"), 215, 215, w, h, 2));
  assert.ok(hitTest(shape("triangle"), 400, 590, w, h));
  assert.ok(!hitTest(shape("triangle"), 230, 230, w, h, 2));
  assert.ok(hitTest(shape("star"), 400, 420, w, h, 2), "the star's middle");
  assert.ok(!hitTest(shape("star"), 250, 250, w, h, 2), "between its points");
  assert.ok(!hitTest(shape("diamond"), 215, 585, w, h, 2));
});

test("a new shape keeps which shape it is, and draws in by default like a zone", () => {
  const item = newItem("shape", [[0.1, 0.1], [0.3, 0.4]], { from: 0, to: 2, geometry: { shape: "hexagon" } });
  assert.deepEqual(item.geometry, { shape: "hexagon" });
  assert.equal(item.style.fill, "#ffffff");
  assert.equal(newItem("shape", [[0.1, 0.1], [0.3, 0.4]], { from: 0, to: 2 }).geometry.shape, "rect");
});
