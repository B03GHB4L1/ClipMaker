// The sequence track (T2, ui/annotate/sequence.js): blocks sized by play length, and reordering.
import assert from "node:assert/strict";
import { test } from "node:test";
// sequence.js loads the page's request helpers, which listen on the document: give them one.
globalThis.document ??= { addEventListener() {} };
globalThis.window ??= { addEventListener() {} };
const { clipSeconds, clock, dropIndex, moveInOrder, sequenceLayout } = await import("../ui/annotate/sequence.js");

test("blocks are sized by how long each clip plays once exported", () => {
  const layout = sequenceLayout([{ id: "a", seconds: 10, duration: 8 }, { id: "b", duration: 30 }]);
  assert.deepEqual(layout.map((block) => block.id), ["a", "b"]);
  assert.equal(layout[0].start, 0);
  assert.equal(layout[0].width, 0.25);
  assert.equal(layout[1].start, 0.25);
  assert.equal(layout[1].width, 0.75);
});

test("a clip with no known length still gets a block", () => {
  assert.equal(clipSeconds({}), 0.1);
  assert.equal(sequenceLayout([{ id: "a" }])[0].width, 1);
});

test("moving a clip keeps every other clip in order", () => {
  assert.deepEqual(moveInOrder(["a", "b", "c", "d"], 0, 2), ["b", "c", "a", "d"]);
  assert.deepEqual(moveInOrder(["a", "b", "c", "d"], 3, 0), ["d", "a", "b", "c"]);
  assert.deepEqual(moveInOrder(["a", "b"], 1, 9), ["a", "b"]);
});

test("a dropped block lands after every block whose middle it passed", () => {
  const layout = sequenceLayout([{ id: "a", seconds: 1 }, { id: "b", seconds: 1 }, { id: "c", seconds: 1 }, { id: "d", seconds: 1 }]);
  assert.equal(dropIndex(layout, 0, 0.6), 1); // past b's middle (0.375), not c's (0.625)
  assert.equal(dropIndex(layout, 0, 0.7), 2);
  assert.equal(dropIndex(layout, 0, 0.9), 3);
  assert.equal(dropIndex(layout, 3, 0.05), 0);
  assert.equal(dropIndex(layout, 1, 0.3), 1); // barely moved: stays put
});

test("lengths read as minutes and seconds", () => {
  assert.equal(clock(65.4), "1:05");
  assert.equal(clock(-3), "0:00");
});
