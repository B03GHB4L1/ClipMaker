// Code screen helpers (ui/code/clock.js, ui/code/edits.js): the match clock shown for a coded moment must match
// the engine's table (app/coding/to_events.py), and hotkeys must not fire while typing.
import assert from "node:assert/strict";
import { test } from "node:test";
import { History, nudged, toggleInterval } from "../ui/code/edits.js";
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

const intervalCodes = [
  { id: "possession", kind: "interval", group: "possession" },
  { id: "press", kind: "interval", group: "press" },
];
let counter = 0;
const nextId = () => `c${String(++counter).padStart(6, "0")}`;

test("an interval starts on one press and stops on the next", () => {
  const first = toggleInterval([], intervalCodes, intervalCodes[0], "home", "1H", 100, nextId);
  assert.equal(first.started.end, null);
  const second = toggleInterval([first.started], intervalCodes, intervalCodes[0], "home", "1H", 130.25, nextId);
  assert.equal(second.started, null);
  assert.deepEqual(second.changes.map((change) => change.next.end), [130.25]);
});

test("starting an interval stops the running one of its group, not others", () => {
  const home = toggleInterval([], intervalCodes, intervalCodes[0], "home", "1H", 100, nextId).started;
  const press = toggleInterval([home], intervalCodes, intervalCodes[1], "away", "1H", 105, nextId).started;
  const away = toggleInterval([home, press], intervalCodes, intervalCodes[0], "away", "1H", 120, nextId);
  assert.deepEqual(away.changes.map((change) => [change.id, change.next.end]),
    [[home.id, 120], [away.started.id, null]]);
  // Pressed before its start (the analyst went back): it ends where it began, never before.
  const back = toggleInterval([away.started], intervalCodes, intervalCodes[0], "away", "1H", 90, nextId);
  assert.equal(back.changes[0].next.end, 120);
});

test("nudges keep an interval in order and inside the video", () => {
  const span = { id: "c1", t: 10, end: 12 };
  assert.equal(nudged(span, "t", 0.04).t, 10.04);
  assert.equal(nudged(span, "t", 5).t, 12); // not past its end
  assert.equal(nudged({ id: "c2", t: 0.02 }, "t", -1).t, 0);
  assert.equal(nudged({ id: "c3", t: 0 }, "t", -1), null); // nothing to move
  assert.equal(nudged(span, "end", -5).end, 10);
  assert.equal(nudged(span, "end", 5, 13).end, 13);
  assert.equal(nudged({ id: "c4", t: 1, end: null }, "end", 1), null);
});

test("undo and redo walk the steps; a new step clears redo", () => {
  const history = new History(2);
  history.push([{ id: "a" }], "one");
  history.push([{ id: "b" }], "two");
  history.push([{ id: "c" }], "three"); // the oldest falls off
  assert.equal(history.undo().label, "three");
  assert.equal(history.undo().label, "two");
  assert.equal(history.undo(), null);
  assert.equal(history.redo().label, "two");
  history.push([{ id: "d" }], "four");
  assert.equal(history.canRedo, false);
});
