// Parts of a clip (ui/annotate/parts.js): cut, reorder, repeat. docs/TELESTRATION_PLAN.md, M9.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { cutClip, cutFrames, cutToSource, deletePart, duplicatePart, movePart, partAt, partSpans, sourceToCut, splitAt, trimPart } from "../ui/annotate/parts.js";
import { freezeStart, totalSeconds } from "../ui/annotate/timeline.js";

const clip = { fps: 10, duration: 10, frames: 100 };
const near = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} vs ${expected}`);
const drawing = (id, from, to, extra = {}) => ({ id, kind: "arrow", points: [[0.1, 0.1], [0.2, 0.2]], style: {}, show: { from, to, animate: "none" }, ...extra });
const doc = (items = [], freezes = [], parts) => ({ version: 1, items, freezes, ...(parts ? { parts } : {}) });
const times = (value, id) => { const { from, to } = value.items.find((item) => item.id === id).show; return [from, to]; };
const board = { kind: "board", view: "full", theme: "grass" };

test("the cut clip maps to source frames the same way in both languages", () => {
  const cases = JSON.parse(readFileSync(new URL("./fixtures/parts_cases.json", import.meta.url), "utf8"));
  for (const c of cases) {
    assert.equal(cutFrames(c.parts, c.frames), c.cutFrames, c.name);
    c.map.forEach(([cut, source]) => assert.equal(cutToSource(cut, c.parts, c.frames), source, `${c.name}: cut frame ${cut}`));
    (c.again || []).forEach(([source, cuts]) => assert.deepEqual(sourceToCut(source, c.parts, c.frames), cuts, `${c.name}: source ${source}`));
  }
  assert.equal(cutClip(clip, null), clip);
  const cut = cutClip(clip, [{ from: 0, to: 30 }, { from: 60, to: 100 }]);
  assert.deepEqual([cut.frames, cut.duration], [70, 7]);
});

test("a split changes no time and keeps freezes where they are", () => {
  const start = doc([drawing("a", 1, 5)], [{ atFrame: 20, seconds: 2 }]);
  const split = splitAt(start, clip, 50);
  assert.deepEqual(split.parts, [{ from: 0, to: 50 }, { from: 50, to: 100 }]);
  assert.deepEqual(split.freezes, start.freezes);
  assert.deepEqual(times(split, "a"), [1, 5]);
  assert.equal(totalSeconds(cutClip(clip, split.parts), split.freezes), 12);
  assert.equal(splitAt(split, clip, 50), null, "on a part's first frame");
  assert.equal(splitAt(start, clip, 0), null);
  assert.equal(partAt(split, clip, 70).index, 1);
});

// Three parts: cut frames 0-30, 30-60, 60-100. A 1 s freeze at frame 10 and a 2 s one at frame 40.
const three = () => splitAt(splitAt(doc([], [{ atFrame: 10, seconds: 1 }, { atFrame: 40, seconds: 2 }]), clip, 30), clip, 60);

test("part spans count freezes into the part they start in", () => {
  const spans = partSpans(three(), clip);
  assert.deepEqual(spans.map((s) => [s.outStart, s.outEnd]), [[0, 4], [4, 9], [9, 13]]);
});

test("deleting a part closes the gap and removes what only lived in it", () => {
  const value = three();
  value.items = [drawing("in-first", 1, 3), drawing("in-middle", 5, 6), drawing("straddles", 3.5, 10), drawing("board-token", 5, 7, { on: 40 })];
  value.freezes = [{ atFrame: 10, seconds: 1 }, { atFrame: 40, seconds: 2, background: board }];
  const after = deletePart(value, clip, 1);
  assert.deepEqual(after.parts, [{ from: 0, to: 30 }, { from: 60, to: 100 }]);
  assert.deepEqual(after.freezes, [{ atFrame: 10, seconds: 1 }], "the freeze and board in the deleted part are gone");
  assert.deepEqual(after.items.map((i) => i.id), ["in-first", "straddles"], "its drawings and the board's token are gone");
  assert.deepEqual(times(after, "in-first"), [1, 3]);
  assert.deepEqual(times(after, "straddles"), [3.5, 5], "shortened to the time that is left");
  near(totalSeconds(cutClip(clip, after.parts), after.freezes), 8, "length");
  assert.equal(deletePart(doc(), clip, 0), null, "the last part stays");
});

test("moving a part takes its freezes and drawings with it", () => {
  const value = three();
  value.items = [drawing("first", 1, 3)];
  const after = movePart(value, clip, 2, 0);
  assert.deepEqual(after.parts, [{ from: 60, to: 100 }, { from: 0, to: 30 }, { from: 30, to: 60 }]);
  assert.deepEqual(after.freezes.map((f) => f.atFrame), [50, 80]);
  assert.deepEqual(times(after, "first"), [5, 7], "it plays after the 4 s part now");
  const back = movePart(after, clip, 0, 2);
  assert.deepEqual(back.parts, value.parts);
  assert.deepEqual(back.freezes, value.freezes);
  assert.deepEqual(times(back, "first"), [1, 3]);
  assert.equal(movePart(value, clip, 1, 1), null);
});

test("repeating a part copies its drawings, not its freezes or boards", () => {
  const value = splitAt(doc([drawing("d", 1, 3), drawing("late", 6, 8), drawing("board-token", 6, 7, { on: 80 })], [{ atFrame: 80, seconds: 1, background: board }]), clip, 50);
  const after = duplicatePart(value, clip, 0);
  assert.deepEqual(after.parts, [{ from: 0, to: 50 }, { from: 0, to: 50 }, { from: 50, to: 100 }]);
  assert.deepEqual(after.freezes.map((f) => f.atFrame), [130], "the board moved after the copy, once");
  const copy = after.items.find((i) => !["d", "late", "board-token"].includes(i.id));
  assert.deepEqual([copy.show.from, copy.show.to], [6, 8], "it plays 5 s later");
  assert.deepEqual(times(after, "d"), [1, 3]);
  assert.deepEqual(times(after, "late"), [11, 13], "later drawings moved out of the way");
  assert.equal(after.items.filter((i) => i.on !== undefined).length, 1);
});

test("trimming an end removes the frames, and what sat on them", () => {
  const value = doc([drawing("a", 5, 8), drawing("token", 8.2, 8.8, { on: 80 })], [{ atFrame: 80, seconds: 1, background: board }]);
  const end = trimPart(value, clip, 0, "to", 60);
  assert.deepEqual(end.parts, [{ from: 0, to: 60 }]);
  assert.deepEqual(end.freezes, []);
  assert.deepEqual(end.items.map((i) => i.id), ["a"]);
  assert.deepEqual(times(end, "a"), [5, 6], "shortened to the 6 s that are left");
  const start = trimPart(value, clip, 0, "from", 20);
  assert.deepEqual(start.parts, [{ from: 20, to: 100 }]);
  assert.deepEqual(start.freezes.map((f) => f.atFrame), [60]);
  assert.deepEqual(times(start, "a"), [3, 6], "two seconds earlier");
  near(freezeStart(60, cutClip(clip, start.parts), start.freezes), 6, "the freeze starts where it did on the picture");
  const longer = trimPart(start, clip, 0, "from", 10);
  assert.deepEqual(longer.parts, [{ from: 10, to: 100 }]);
  assert.deepEqual(times(longer, "a"), [4, 7]);
  assert.equal(trimPart(value, clip, 0, "to", 0), null, "a part keeps a frame");
  assert.equal(trimPart(value, clip, 0, "to", 100), null, "nothing to change");
  assert.equal(trimPart(value, clip, 0, "to", 101), null, "past the clip");
});

test("a clip back to one whole part drops the parts list", () => {
  const split = splitAt(doc(), clip, 50);
  const merged = deletePart(split, clip, 1);
  assert.equal(merged.parts?.length, 1);
  const whole = trimPart(merged, clip, 0, "to", 100);
  assert.equal(whole.parts, undefined);
});
