// Board from this frame (ui/annotate/pitch.js, board.js): pitch maths, boards in
// the document and tokens. docs/TELESTRATION_PLAN.md, M7.
import assert from "node:assert/strict";
import { test } from "node:test";
import { LANDMARKS, apply, boardLayout, calibrate, fitHomography, invert, landmark, pinsDown, projectedLines, viewFor } from "../ui/annotate/pitch.js";
import { addBoard, boardAt, boardFrame, changeBoard, changeBoardView, itemsAt, newToken, removeInsert, textOn, tokensFromPlayers } from "../ui/annotate/board.js";
import { freezeStart, setFreeze } from "../ui/annotate/timeline.js";
import { newItem } from "../ui/annotate/document.js";
import { hitTest, handlesFor } from "../ui/annotate/shapes.js";

const ASPECT = 16 / 9;
const clip = { fps: 25, duration: 4, frames: 100 };
const near = (actual, expected, tolerance, message) => assert.ok(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} vs ${expected}`);

// A broadcast-like camera: pitch metres -> frame fractions through a known homography.
const camera = [[9, 1.5, 520], [0, -3.2, 240], [0, 0.012, 1]];
const toFrame = ([x, y]) => { const [u, v] = apply(camera, [x, y]); return [u / 1000 / ASPECT, v / 1000]; };
const shot = (id) => ({ id, at: toFrame(landmark(id).at) });

test("a homography fitted from four or more points maps them back", () => {
  const from = [[0, 0], [10, 0], [10, 5], [0, 5], [5, 2]];
  const to = from.map((p) => apply(camera, p));
  const fit = fitHomography(from, to);
  from.forEach((p, i) => {
    const [x, y] = apply(fit, p);
    near(x, to[i][0], 1e-6, "x");
    near(y, to[i][1], 1e-6, "y");
  });
  const back = invert(fit);
  const [x, y] = apply(back, to[2]);
  near(x, 10, 1e-6, "inverse x");
  near(y, 5, 1e-6, "inverse y");
  assert.equal(fitHomography(from.slice(0, 3), to.slice(0, 3)), null);
});

test("calibration from clicked marks finds feet on the pitch and draws lines back", () => {
  const pairs = ["box-r-far", "box-r-near", "box-r-far-goal", "box-r-near-goal", "half-far", "spot-r"].map(shot);
  assert.equal(calibrate(pairs.slice(0, 3), ASPECT), null);
  const fit = calibrate(pairs, ASPECT);
  near(fit.worst, 0, 1e-6, "exact clicks fit exactly");
  const feet = toFrame([30, 12]);
  const [x, y] = fit.toPitch(feet);
  near(x, 30, 1e-6, "feet x");
  near(y, 12, 1e-6, "feet y");
  const [fx, fy] = fit.toFrame([30, 12]);
  near(fx, feet[0], 1e-9, "back to the frame x");
  near(fy, feet[1], 1e-9, "back to the frame y");
  const lines = projectedLines(fit);
  assert.ok(lines.length > 5 && lines.every((line) => line.length >= 2));
  // A mark clicked on the wrong spot shows up in the fit's worst error.
  const wrong = pairs.map((pair, i) => (i === 5 ? { ...pair, at: toFrame([30, 10]) } : pair));
  assert.ok(calibrate(wrong, ASPECT).worst > 1);
});

test("marks along one line do not make a calibration", () => {
  // Three marks on the halfway line and one off it: the far half could swing freely.
  const onOneLine = ["half-far", "circle-far", "circle-near", "circle-right"].map(shot);
  assert.equal(calibrate(onOneLine, ASPECT), null);
  assert.ok(calibrate([...onOneLine, shot("box-r-far")], ASPECT));
  assert.equal(pinsDown([[0, -34], [0, -9.15], [0, 9.15], [0, 34], [9.15, 0]]), false);
});

test("every landmark has a unique id and sits on or near the pitch", () => {
  assert.equal(new Set(LANDMARKS.map((mark) => mark.id)).size, LANDMARKS.length);
  LANDMARKS.forEach((mark) => assert.ok(Math.abs(mark.at[0]) <= 52.5 && Math.abs(mark.at[1]) <= 34, mark.id));
});

test("board layouts round-trip and keep metres square", () => {
  for (const view of ["full", "left", "right"]) {
    const layout = boardLayout(view, ASPECT);
    const point = view === "left" ? [-30, 10] : [30, -10];
    const [x, y] = layout.toPitch(layout.toBoard(point));
    near(x, point[0], 1e-9, `${view} x`);
    near(y, point[1], 1e-9, `${view} y`);
    const [a] = layout.toBoard([0, 0]);
    const [b] = layout.toBoard([1, 0]);
    near((b - a) * ASPECT, layout.metre, 1e-12, `${view} square`);
  }
  // A half only when it shows the pitch bigger: on 4:3 it does, on 16:9 the height already sets the scale.
  assert.equal(viewFor([[10, 0], [40, 20]], 4 / 3), "right");
  assert.equal(viewFor([[-10, 0], [-40, 20]], 4 / 3), "left");
  assert.equal(viewFor([[-30, 0], [30, 20]], 4 / 3), "full");
  assert.equal(viewFor([[10, 0], [40, 20]], 16 / 9), "full");
});

const board = { kind: "board", view: "full", theme: "grass" };
const blank = () => ({ version: 1, freezes: [], tracks: [], items: [newItem("arrow", [[0.1, 0.1], [0.3, 0.3]], { from: 0, to: 4 })] });

test("a board is a freeze with a picture: its tokens show only on it, clip drawings only off it", () => {
  const value = addBoard(blank(), clip, 25, 2, board, (from, to) => [newToken([0.5, 0.5], { team: "away", label: "9", from, to })]);
  const start = freezeStart(25, clip, value.freezes);
  assert.equal(start, 1);
  assert.deepEqual(value.freezes, [{ atFrame: 25, seconds: 2, background: board }]);
  const token = value.items.find((item) => item.kind === "token");
  assert.deepEqual([token.on, token.show.from, token.show.to, token.team, token.label], [25, 1, 3, "away", "9"]);
  assert.equal(boardAt(value, clip, 2).atFrame, 25);
  assert.equal(boardAt(value, clip, 3.5), null);
  assert.deepEqual(itemsAt(value, clip, 2).map((item) => item.kind), ["token"]);
  assert.deepEqual(itemsAt(value, clip, 3.5).map((item) => item.kind), ["arrow"]);
  // The clip drawing was retimed round the board: it now ends 2 s later.
  assert.equal(value.items.find((item) => item.kind === "arrow").show.to, 6);
});

test("changing a board's length keeps its picture; removing it removes its drawings", () => {
  const value = addBoard(blank(), clip, 25, 2, board, (from, to) => [newToken([0.5, 0.5], { from, to })]);
  const longer = setFreeze(value, clip, 25, 3);
  assert.deepEqual(longer.freezes[0].background, board);
  const removed = removeInsert(longer, clip, 25);
  assert.deepEqual(removed.freezes, []);
  assert.deepEqual(removed.items.map((item) => item.kind), ["arrow"]);
  assert.equal(removed.items[0].show.to, 4);
});

test("a board goes on the next free frame, and its view change keeps tokens on the same pitch spot", () => {
  const frozen = setFreeze(blank(), clip, 25, 1);
  assert.equal(boardFrame(frozen, clip, 25), 26);
  assert.equal(boardFrame(frozen, clip, 24), 24);
  const full = boardLayout("full", ASPECT);
  const spot = [30, -10];
  const value = addBoard(blank(), clip, 10, 2, board, (from, to) => [newToken(full.toBoard(spot), { from, to })]);
  const right = changeBoardView(value, 10, "right", ASPECT);
  assert.equal(right.freezes[0].background.view, "right");
  const [x, y] = boardLayout("right", ASPECT).toPitch(right.items.find((item) => item.on === 10).points[0]);
  near(x, spot[0], 1e-3, "x on the pitch");
  near(y, spot[1], 1e-3, "y on the pitch");
  assert.equal(changeBoard(value, 10, { theme: "light" }).freezes[0].background.theme, "light");
});

test("players found on a frame become tokens; off-pitch ones are left out", () => {
  const pairs = ["box-r-far", "box-r-near", "box-r-far-goal", "box-r-near-goal", "half-far", "spot-r"].map(shot);
  const fit = calibrate(pairs, ASPECT);
  const players = [
    { box: [...toFrame([30, 5]), 0.02, 0.06], team: 0 },
    { box: [...toFrame([40, -20]), 0.02, 0.06], team: 1 },
    { box: [...toFrame([20, 0]), 0.02, 0.06], team: 2 },
    { box: [...toFrame([30, 45]), 0.02, 0.06], team: 0 }, // on the far side of the touchline: a steward
  ];
  const found = tokensFromPlayers(players, fit, ASPECT, { home: "#ff0000", away: "#0000ff", other: "#ffff00" });
  assert.deepEqual([found.view, found.placed, found.skipped], ["full", 3, 1]);
  const tokens = found.tokens(1, 3);
  assert.deepEqual(tokens.map((token) => [token.team, token.style.fill]), [["home", "#ff0000"], ["away", "#0000ff"], ["other", "#ffff00"]]);
  const [x, y] = boardLayout("full", ASPECT).toPitch(tokens[1].points[0]);
  near(x, 40, 1e-3, "token x");
  near(y, -20, 1e-3, "token y");
});

test("tokens are hit as discs, have no handles and read on their colour", () => {
  const token = newToken([0.5, 0.5], { team: "home", label: "10", from: 0, to: 2 });
  assert.equal(token.style.color, textOn(token.style.fill));
  assert.equal(textOn("#f2f3ee"), "#171817");
  assert.equal(textOn("#1f5fd1"), "#ffffff");
  assert.deepEqual(handlesFor(token), []);
  assert.ok(hitTest(token, 960 + 10, 540 + 10, 1920, 1080));
  assert.ok(!hitTest(token, 960 + 60, 540, 1920, 1080));
  assert.equal(newToken([0.5, 0.5], { label: "1234", name: "x".repeat(40), from: 0, to: 1 }).label, "123");
});
