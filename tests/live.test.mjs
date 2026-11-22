// Live playback helpers on the Code screen (ui/code/live.js, L1).
import test from "node:test";
import assert from "node:assert/strict";
import { AHEAD, formatBytes, holeEnd, liveSummary, markerText, nextKickoff, wanted } from "../ui/code/live.js";

test("kick-off marks the next period in the marker format", () => {
  assert.equal(nextKickoff({}).key, "1H");
  assert.equal(nextKickoff(undefined).key, "1H");
  assert.equal(nextKickoff({ "1H": "0:00:05" }).key, "2H");
  assert.equal(nextKickoff({ "1H": "0:00:05", "2H": "0:50:00", ET1: "1:40:00", ET2: "1:56:00", PEN: "2:15:00" }), null);
  assert.equal(markerText(5.9), "0:00:05");
  assert.equal(markerText(3723), "1:02:03");
  assert.equal(markerText(-2), "0:00:00");
});

const segments = [0, 2, 4, 6, 8].map((start, i) => ({ i, part: "part01", file: `seg_0000${i}.m4s`, start, duration: 2 }));
const ranges = (...pairs) => ({ length: pairs.length, start: (i) => pairs[i][0], end: (i) => pairs[i][1] });

test("buffers the segment playing and the ones just after it", () => {
  assert.deepEqual(wanted(segments, 3, 4), [1, 2, 3]);
  assert.deepEqual(wanted(segments, 0, AHEAD), [0, 1, 2, 3, 4]);
  assert.deepEqual(wanted(segments, 10, AHEAD), []);
});

test("steps over a short hole between segments, but not a long one or a buffered spot", () => {
  assert.equal(holeEnd(ranges([0, 1.88], [2, 14]), 1.9), 2.01);
  assert.equal(holeEnd(ranges([0, 1.88], [2, 14]), 1.0), null);
  assert.equal(holeEnd(ranges([0, 4], [9, 14]), 4.1), null);
  assert.ok(Math.abs(holeEnd(ranges([0.2, 4]), 0) - 0.21) < 1e-9);
  assert.equal(holeEnd(ranges([0, 4]), 6), null);
});

test("says what the recording is doing", () => {
  const base = { recorded_seconds: 754, free_bytes: 60 * 1024 ** 3, source: "rtmp://cam.club", push_address: "rtmp://127.0.0.1:1935/live" };
  assert.equal(liveSummary({ ...base, state: "recording" }), "Recording 12:34 · 60 GB free");
  assert.match(liveSummary({ ...base, state: "recording", gaps: [{ at: 300, length: 12 }] }), /1 break in the stream/);
  assert.match(liveSummary({ ...base, state: "waiting" }), /send to rtmp:\/\/127\.0\.0\.1:1935\/live \(any stream key\)/);
  assert.match(liveSummary({ ...base, state: "reconnecting" }), /dropped at 12:34/);
  assert.equal(liveSummary({ state: "failed", error: "Could not connect." }), "Could not connect.");
});

test("disk space reads in GB or MB", () => {
  assert.equal(formatBytes(60 * 1024 ** 3), "60 GB");
  assert.equal(formatBytes(1.5 * 1024 ** 3), "1.5 GB");
  assert.equal(formatBytes(300 * 1024 ** 2), "300 MB");
});
