// Chart pictures from the Plotly save button (exportFigure in ui/save-clip.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { exportFigure } from "../ui/save-clip.js";

const chart = (annotations, margin = { l: 36, r: 36, t: 92, b: 116 }) => ({
  data: [{ type: "scatter", x: [1], y: [2] }],
  layout: { height: 806, margin, annotations },
  _fullLayout: { width: 1377, height: 806, margin },
  clientWidth: 1377,
  clientHeight: 806,
});

test("the picture keeps the chart's on-screen size, not Plotly's 700px box", () => {
  const figure = exportFigure(chart([]));
  assert.equal(figure.layout.width, 1377);
  assert.equal(figure.layout.height, 806);
});

test("hover hints are left out of the picture, the rest of the note stays", () => {
  const note = { text: "Pitch coordinates use a 0-100 event-data scale. Hover points or lines for event<br>details.", xref: "paper", yref: "paper", y: -0.08 };
  const title = { text: "ATTACK ->", xref: "x", yref: "y", y: 100 };
  const figure = exportFigure(chart([title, note]));
  assert.deepEqual(figure.layout.annotations.map((a) => a.text), ["ATTACK ->", "Pitch coordinates use a 0-100 event-data scale."]);
  assert.equal(figure.layout.height, 806);
});

test("a note that was only a hover hint goes with its room", () => {
  const figure = exportFigure(chart([{ text: "Hover for completion rates.", xref: "paper", yref: "paper", y: -0.1 }]));
  assert.deepEqual(figure.layout.annotations, []);
  assert.equal(figure.layout.margin.b, 40);
  assert.equal(figure.layout.height, 806 - 76);
});

test("the app's chart is not changed", () => {
  const live = chart([{ text: "Hover points for details.", xref: "paper", yref: "paper", y: -0.08 }]);
  exportFigure(live);
  assert.equal(live.layout.annotations.length, 1);
  assert.equal(live.layout.width, undefined);
});
