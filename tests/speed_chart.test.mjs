// The speed-over-time chart (P3c, ui/annotate/speedchart.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { drawSpeedChart, speedSeries } from "../ui/annotate/speedchart.js";

const recorder = () => {
  const calls = [];
  const ctx = new Proxy({}, {
    get: (_, name) => (name === "calls" ? calls : (...args) => calls.push([name, ...args])),
    set: (_, name, value) => { calls.push(["set", name, value]); return true; },
  });
  return { ctx, calls };
};

test("unknown speeds break the line, and the scale rounds up to a clean top", () => {
  const motion = { from: 10, speeds: [8, 12.2, null, null, 21.3, 18] };
  const { runs, ceiling } = speedSeries(motion, 10);
  assert.deepEqual(runs.map((run) => run.length), [2, 2]);
  assert.deepEqual(runs[0][0], [1, 8], "seconds are clip time: frame 10 at 10 fps");
  assert.equal(ceiling, 25);
  assert.equal(speedSeries({ from: 0, speeds: [null, null] }, 25).ceiling, 10, "an empty chart still has a scale");
});

test("a chart draws its line and playhead, a title when asked, and says so when there is nothing", () => {
  const motion = { from: 0, speeds: [5, 10, 15, 20, 15, 10] };
  const drawn = recorder();
  drawSpeedChart(drawn.ctx, 400, 200, motion, 5, { frame: 2, title: "Player 1 speed" });
  assert.ok(drawn.calls.some(([name, text]) => name === "fillText" && text === "Player 1 speed"));
  assert.ok(drawn.calls.filter(([name]) => name === "stroke").length > 6, "grid, line and playhead");
  const empty = recorder();
  drawSpeedChart(empty.ctx, 400, 200, { from: 0, speeds: [null] }, 25);
  assert.ok(empty.calls.some(([name, text]) => name === "fillText" && /No speed/.test(text)));
});
