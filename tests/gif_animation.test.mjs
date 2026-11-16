// Match Clock and Shot Flight (the chart GIF animations) run inside the chart
// component page. These tests lift the timeline helpers out of that page and
// check the order and timing they produce.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = readFileSync(new URL("../app/smp_component/frontend/index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");

// The source of `function name(...) { ... }` or `const NAME = ...;` from the page.
const lift = (name) => {
  const fn = page.indexOf(`  function ${name}(`);
  if (fn >= 0) {
    let depth = 0;
    for (let i = page.indexOf("{", fn); i < page.length; i++) {
      if (page[i] === "{") depth += 1;
      if (page[i] === "}" && --depth === 0) return page.slice(fn, i + 1);
    }
  }
  const constant = page.indexOf(`  const ${name} =`);
  assert.ok(constant >= 0, `${name} is in the chart page`);
  return page.slice(constant, page.indexOf(";\n", constant) + 1);
};

const names = ["stripHtml", "hexToRgba", "isLineOnlyTrace", "eventSeconds", "secondsFromText", "timesForPoints", "buildTimeline",
  "clockLabel", "withAlpha", "POINT_KEYS", "pickPoints", "easeOut", "tracesAtTime", "animationOptionsForArgs",
  "CLOCK_FRAMES", "CLOCK_DELAY", "FINAL_HOLD", "matchClockSteps", "shotFlightSteps"];
const context = vm.createContext({});
vm.runInContext(`${names.map(lift).join("\n")}\nthis.api = { ${names.join(", ")} };`, context);
const api = context.api;
const plain = (value) => JSON.parse(JSON.stringify(value));

test("GIF animations: Pulse, Still and Build are gone; shot maps lead with Shot Flight", () => {
  const labels = (args) => plain(api.animationOptionsForArgs(args).map(([, label]) => label));
  assert.deepEqual(labels({ component_type: "shot_map" }), ["Shot Flight", "Match Clock"]);
  assert.deepEqual(labels({ component_type: "pass_map" }), ["Match Clock", "Arrow Flow"]);
  assert.deepEqual(labels({ component_type: "pass_map", mode: "network" }), ["Network Grow"]);
  assert.deepEqual(labels({ component_type: "build_up_map" }), ["Sequence", "Arrow Flow"]);
  for (const type of ["defensive_map", "dribble_carry_map", "goalkeeper_map", "penalty_shootout", "echarts_option"]) {
    assert.deepEqual(labels({ component_type: type }), ["Match Clock"], type);
  }
  assert.doesNotMatch(page, /\["(pulse|still|build)",/);
});

test("match time is read from cmTime or from hover text such as 63'07\"", () => {
  assert.equal(api.secondsFromText("<b>Player</b><br>63'07\"<br>Goal"), 63 * 60 + 7);
  assert.equal(api.secondsFromText("Tackle 5'"), 300);
  assert.equal(api.secondsFromText("Successful"), null);
  assert.deepEqual(plain(api.timesForPoints(3, [10, null, "x"], null)), [10, null, null]);
  assert.deepEqual(plain(api.timesForPoints(2, 90, null)), [90, 90]);
  assert.equal(api.timesForPoints(2, null, ["no", "time"]), null);
});

test("Match Clock runs 0' to 90' and shows each event once its minute has passed", () => {
  const timeline = api.buildTimeline([[600, 3000], null]);
  assert.equal(timeline.start, 0);
  assert.equal(timeline.end, 90 * 60);
  assert.equal(timeline.ordinal, false);
  const traces = [
    { x: [10, 20], y: [10, 20], mode: "markers", marker: { size: 12, color: ["a", "b"] }, text: ["10'00\"", "50'00\""] },
    { x: [0], y: [0], mode: "markers", marker: { size: 8 } },
  ];
  const at20 = api.tracesAtTime(traces, timeline, 20 * 60, 60);
  assert.deepEqual(plain(at20[0].x), [10]);
  assert.deepEqual(plain(at20[0].marker.color), ["a"]);
  assert.equal(at20[1], traces[1]); // untimed traces (averages, labels) always show
  const justNow = api.tracesAtTime(traces, timeline, 50 * 60, 60);
  assert.ok(justNow[0].marker.size[1] > 12, "the newest event is drawn larger for a moment");
  assert.equal(justNow[0].marker.size[0], 12);
  assert.equal(api.clockLabel(timeline, 63 * 60 + 40), "63'");
});

test("Match Clock draws a new pass out from its start rather than all at once", () => {
  const timeline = api.buildTimeline([[600, 600, null, 3000, 3000]]);
  const line = { x: [0, 10, null, 50, 60], y: [0, 0, null, 0, 0], mode: "lines" };
  const [halfway] = api.tracesAtTime([line], timeline, 600 + 30, 60);
  assert.equal(halfway.x.length, 3); // the 50' pass has not happened yet
  assert.ok(halfway.x[1] > 0 && halfway.x[1] < 10, `partly drawn: ${halfway.x[1]}`);
  const [done] = api.tracesAtTime([line], timeline, 3600, 60);
  assert.deepEqual(plain(done.x), [0, 10, null, 50, 60]);
});

test("a chart without a spread of times (a shoot-out) plays in drawing order", () => {
  const timeline = api.buildTimeline([[7200, 7200, 7200]]);
  assert.equal(timeline.ordinal, true);
  assert.deepEqual(plain(timeline.groups[0]), [0, 1, 2]);
  assert.equal(api.clockLabel(timeline, 1), "");
});

test("Match Clock frames end on the full chart and hold it", () => {
  const traces = [{ x: [1, 2], y: [1, 2], mode: "markers", marker: { size: 10 }, text: ["5'00\"", "80'00\""] }];
  const frames = [];
  const steps = api.matchClockSteps(traces, (shown, clock) => frames.push({ shown, clock }));
  assert.equal(steps.length, api.CLOCK_FRAMES + 1);
  steps.forEach((step) => step.render());
  assert.equal(frames[0].shown[0].x.length, 0);
  assert.equal(frames.at(-1).shown[0].x.length, 2);
  assert.equal(frames.at(-1).clock.fraction, 1);
  assert.equal(steps.at(-1).delay, api.FINAL_HOLD);
  const seconds = steps.reduce((total, step) => total + step.delay, 0) / 1000;
  assert.ok(seconds > 5 && seconds < 9, `about 6-8 seconds long: ${seconds}`);
});

test("Shot Flight sends shots in match order to the goal line and flashes goals", () => {
  const shot = (type, tx, ty) => ({ type, tx, ty });
  const traces = [{
    x: [50, 40], y: [30, 20], mode: "markers", marker: { size: 13, line: { color: ["#1f77b4", "#1f77b4"] } },
    cmTime: [80 * 60, 10 * 60], cmShot: [shot("Goal", 52, 0), shot("BlockedShot", 50, 0)],
  }];
  const frames = [];
  const steps = api.shotFlightSteps(traces, (shown, clock) => frames.push({ shown, clock }), false);
  steps.forEach((step) => step.render());
  // The 10' shot (second in the trace) goes first.
  const first = frames[0].shown;
  assert.deepEqual(plain(first[0].x), [40]);
  assert.equal(frames[0].clock.label, "10'");
  const flights = (frame) => frame.shown.slice(1).filter((trace) => trace.mode === "lines");
  // A blocked shot stops well short of the goal line.
  const blockedEnd = flights(frames[6]).find((trace) => trace.x[0] === 40);
  assert.ok(blockedEnd.y[1] > 10, `blocked shot stops short: ${blockedEnd.y[1]}`);
  // The goal reaches the goal line, then a ring flashes there.
  const last = frames.at(-1);
  const goalLine = flights(last).find((trace) => trace.x[0] === 50);
  assert.deepEqual(plain([goalLine.x[1], goalLine.y[1]]), [52, 0]);
  const rings = frames.flatMap((frame) => frame.shown.filter((trace) => trace.marker && trace.marker.symbol === "circle-open"));
  assert.ok(rings.length >= 2, "the goal flashes");
  assert.ok(rings.every((ring) => ring.x[0] === 52 && ring.y[0] === 0));
  assert.equal(last.shown[0].x.length, 2);
  assert.equal(steps.at(-1).delay, api.FINAL_HOLD);
});

test("Shot Flight on the goal-frame view drops shots into place (no flight line)", () => {
  const traces = [{ x: [45], y: [20], mode: "markers", marker: { size: 13 }, cmTime: [600], cmShot: [{ type: "SavedShot", tx: null, ty: null }] }];
  const frames = [];
  api.shotFlightSteps(traces, (shown) => frames.push(shown), false).forEach((step) => step.render());
  assert.ok(frames[0][0].marker.size[0] > 13, "lands from larger");
  assert.equal(frames.at(-1)[0].marker.size[0], 13);
  assert.ok(frames.every((shown) => shown.length === 1));
});
