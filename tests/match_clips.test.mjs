// Clips of a project that uses several matches keep the match they are from (ui/timeline.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { exportWindows, normaliseClips } from "../ui/timeline.js";

const windows = [
  { id: 1, start: 10, end: 20, label: "Ann - Goal @ 1:00 (P1)", period: 1, match_id: "m1", match_title: "Home A v Away A" },
  { id: 2, start: 30, end: 44, label: "Cat - Shot @ 2:30 (P1)", period: 1, match_id: "m2", match_title: "Home B v Away B" },
];

test("a clip keeps its match and the match's name", () => {
  const [first, second] = normaliseClips(windows);
  assert.equal(first.match_id, "m1");
  assert.equal(second.match_id, "m2");
  assert.equal(second.match_title, "Home B v Away B");
});

test("a clip from a single match has no match fields, as before", () => {
  const [clip] = normaliseClips([{ id: 1, start: 1, end: 2, label: "Goal", period: 1 }]);
  assert.equal("match_id" in clip, false);
  assert.equal("match_title" in clip, false);
});

test("exported windows say which match each clip is from, so each uses its own video", () => {
  const clips = normaliseClips(windows);
  assert.deepEqual(exportWindows(clips, "all").map((window) => window.match_id), ["m1", "m2"]);
  assert.deepEqual(exportWindows(clips, "selected", new Set([2])).map((window) => [window.number, window.match_id]), [[2, "m2"]]);
});

test("windows of a single match are exported without match fields", () => {
  const clips = normaliseClips([{ id: 1, start: 1, end: 2, label: "Goal", period: 1 }]);
  assert.deepEqual(Object.keys(exportWindows(clips)[0]).sort(), ["end", "label", "number", "period", "start"]);
});
