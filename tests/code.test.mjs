// Code screen helpers (ui/code/clock.js): the match clock shown for a coded moment must match
// the engine's table (app/coding/to_events.py), and hotkeys must not fire while typing.
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatClock, formatVideo, isTyping, parseMarker, place, sources, videoOf } from "../ui/code/clock.js";

const single = { video_path: "match.mp4", period_videos: {}, markers: { "1H": "0:05:00", "2H": "0:55:00", ET1: "1:50:00", ET2: "2:08:00" } };

test("markers read like the intake clock", () => {
  assert.equal(parseMarker("1:02:03"), 3723);
  assert.equal(parseMarker("62:03"), 3723);
  for (const bad of ["", null, "a:b", "-1:00", "1:2:3:4"]) assert.equal(parseMarker(bad), null, String(bad));
});

test("video time becomes match clock across halves and extra time", () => {
  const at = (t) => { const where = place(single, "1H", t); return where && `${where.period.key} ${formatClock(where.clock)}`; };
  assert.equal(at(120), null); // before kick-off
  assert.equal(at(300), "1H 0:00");
  assert.equal(at(2999.6), "1H 45:00");
  assert.equal(at(3301.2), "2H 45:01");
  assert.equal(at(7000.7), "ET1 96:41");
  assert.equal(at(8000.2), "ET2 110:20");
});

test("a period with its own file only takes codes made on that file", () => {
  const split = { video_path: "first.mp4", period_videos: { "2H": "second.mp4" }, markers: { "1H": "0:01:00", "2H": "0:00:10" } };
  assert.equal(videoOf(split, 2), "second.mp4");
  assert.equal(videoOf(split, 3), "second.mp4");
  assert.deepEqual(sources(split).map((item) => item.key), ["1H", "2H"]);
  assert.equal(formatClock(place(split, "1H", 3000).clock), "49:00");
  assert.equal(place(split, "2H", 30).period.key, "2H");
  assert.equal(formatClock(place(split, "2H", 30).clock), "45:20");
});

test("video times format with hours only when needed", () => {
  assert.equal(formatVideo(65.9), "1:05");
  assert.equal(formatVideo(3723), "1:02:03");
});

test("hotkeys stay quiet while typing in a field", () => {
  const inside = (selector) => ({ closest: (query) => (query.split(",").some((part) => part.trim().startsWith(selector)) ? {} : null) });
  assert.equal(isTyping(inside("input")), true);
  assert.equal(isTyping(inside("textarea")), true);
  assert.equal(isTyping(inside("select")), true);
  assert.equal(isTyping({ closest: () => null }), false);
  assert.equal(isTyping(null), false);
});
