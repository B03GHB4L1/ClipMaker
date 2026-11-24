// Picture inserts (docs/CODING_AND_PITCH_PLAN.md, section I): ui/annotate/board.js.
import assert from "node:assert/strict";
import { test } from "node:test";
import { addBoard, boardAt, changeBoard, drawBoard, itemsAt, pictureInsert, moveInsert, pictureRect, removeInsert } from "../ui/annotate/board.js";
import { freezeStart } from "../ui/annotate/timeline.js";

const clip = { fps: 25, duration: 2, frames: 50 };
const empty = () => ({ version: 1, items: [], freezes: [] });
const ID = "a".repeat(32);

// A canvas that remembers what was drawn, and an image of a given size.
const recorder = () => {
  const calls = [];
  const ctx = new Proxy({}, {
    get: (_, name) => (name === "calls" ? calls : (...args) => calls.push([name, ...args])),
    set: (_, name, value) => { calls.push(["set", name, value]); return true; },
  });
  return { ctx, calls };
};
const image = (naturalWidth, naturalHeight) => ({ naturalWidth, naturalHeight });

test("a whole picture fits inside the frame, centred, and a filled one covers it", () => {
  // A square chart in a 16:9 frame.
  assert.deepEqual(pictureRect(1000, 1000, 1600, 900, "contain"), { x: 350, y: 0, width: 900, height: 900 });
  assert.deepEqual(pictureRect(1000, 1000, 1600, 900, "fill"), { x: 0, y: -350, width: 1600, height: 1600 });
  // A wide picture in the same frame.
  assert.deepEqual(pictureRect(3200, 900, 1600, 900, "contain"), { x: 0, y: 225, width: 1600, height: 450 });
  // The same shape as the frame fills it either way.
  assert.deepEqual(pictureRect(800, 450, 1600, 900, "contain"), pictureRect(800, 450, 1600, 900, "fill"));
});

test("a picture insert is drawn over its colour, as the picture in the library", () => {
  const { ctx, calls } = recorder();
  const loaded = new Map([[ID, image(1000, 1000)]]);
  drawBoard(ctx, 1600, 900, pictureInsert(ID, "contain", "#f2f3ee"), loaded);
  assert.ok(calls.some(([name, value]) => name === "set" && value === "fillStyle"));
  assert.deepEqual(calls.find(([name]) => name === "fillRect"), ["fillRect", 0, 0, 1600, 900]);
  const [, , x, y, width, height] = calls.find(([name]) => name === "drawImage");
  assert.deepEqual([x, y, width, height], [350, 0, 900, 900]);
});

test("a picture that has not loaded leaves the colour and says so", () => {
  const { ctx, calls } = recorder();
  drawBoard(ctx, 1600, 900, pictureInsert(ID), new Map());
  assert.ok(!calls.some(([name]) => name === "drawImage"));
  assert.ok(calls.some(([name, text]) => name === "fillText" && /not available/.test(text)));
});

test("a board still draws as a board", () => {
  const { ctx, calls } = recorder();
  drawBoard(ctx, 1600, 900, { kind: "board", view: "full", theme: "grass" }, new Map());
  assert.ok(calls.some(([name]) => name === "stroke"), "the pitch lines");
  assert.ok(!calls.some(([name]) => name === "drawImage"));
});

test("an insert holds its picture for its seconds, with its own drawings, and is undone cleanly", () => {
  const start = addBoard(empty(), clip, 10, 4, pictureInsert(ID, "fill", "#000000"));
  assert.equal(start.freezes.length, 1);
  assert.deepEqual(start.freezes[0].background, { kind: "picture", id: ID, fit: "fill", colour: "#000000" });
  const at = freezeStart(10, clip, start.freezes) + 1;
  assert.equal(boardAt(start, clip, at).background.id, ID);
  assert.equal(boardAt(start, clip, 0.1), null, "the clip plays before it");
  // A drawing made on the insert shows only there.
  const ring = { id: "r1", kind: "ring", points: [[0.5, 0.5]], show: { from: at, to: at + 1 }, on: 10 };
  const withRing = { ...start, items: [ring] };
  assert.equal(itemsAt(withRing, clip, at).length, 1);
  assert.equal(itemsAt(withRing, clip, 0.1).length, 0);
  // Fit and colour change in place.
  const changed = changeBoard(withRing, 10, { fit: "contain", colour: "#2f6b3a" });
  assert.deepEqual(changed.freezes[0].background, { kind: "picture", id: ID, fit: "contain", colour: "#2f6b3a" });
  // Removing the insert takes its drawings with it.
  const gone = removeInsert(changed, clip, 10);
  assert.deepEqual([gone.freezes.length, gone.items.length], [0, 0]);
});

test("an insert moves to another frame with its length, picture and drawings, and the footage around it retimes", () => {
  const start = addBoard(empty(), clip, 10, 4, pictureInsert(ID, "fill", "#000000"));
  const from = freezeStart(10, clip, start.freezes);
  const ring = { id: "r1", kind: "ring", points: [[0.5, 0.5]], show: { from: from + 1, to: from + 3 }, on: 10 };
  const footage = { id: "f1", kind: "ring", points: [[0.2, 0.2]], show: { from: 4.9, to: 5.1 } }; // footage at 0.9 s, played after the insert
  const value = { ...start, items: [ring, footage] };
  const moved = moveInsert(value, clip, 10, 30);
  assert.deepEqual(moved.freezes.map((f) => [f.atFrame, f.seconds]), [[30, 4]]);
  assert.equal(moved.freezes[0].background.id, ID);
  const at = freezeStart(30, clip, moved.freezes);
  const inside = moved.items.find((item) => item.id === "r1");
  assert.deepEqual([inside.on, inside.show.from, inside.show.to], [30, at + 1, at + 3]);
  // That footage now plays before the insert, so its drawing moves to 0.9 s.
  assert.deepEqual([moved.items.find((item) => item.id === "f1").show.from, moved.items.find((item) => item.id === "f1").show.to], [0.9, 1.1]);
  // Moving back restores the document, and a taken or off-clip frame leaves it alone.
  assert.deepEqual(moveInsert(moved, clip, 30, 10), value);
  assert.equal(moveInsert(value, clip, 10, 10), value);
  assert.equal(moveInsert(value, clip, 10, 50), value);
  assert.equal(moveInsert(value, clip, 10, -1), value);
});
