// Moving boards (ui/annotate/board.js, shapes.js): token moves, matching a later
// frame's players, and export patches. docs/TELESTRATION_PLAN.md, M8.
import assert from "node:assert/strict";
import { test } from "node:test";
import { addBoard, clearMoves, matchPlayers, moveBoard, newToken, placedAt, positionAt, setMove, MOVE_SECONDS, GLIDE_SECONDS } from "../ui/annotate/board.js";
import { boardLayout } from "../ui/annotate/pitch.js";
import { freezeStart } from "../ui/annotate/timeline.js";
import { changedTiles, TILE } from "../ui/annotate/shapes.js";

const ASPECT = 16 / 9;
const clip = { fps: 25, duration: 4, frames: 100 };
const near = (actual, expected, tolerance = 1e-6) => assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} vs ${expected}`);
const board = { kind: "board", view: "full", theme: "grass" };

test("a token glides from key to key, easing in and out, then holds", () => {
  const token = setMove(setMove(newToken([0.2, 0.5], { from: 0, to: 4 }), 1, [0.2, 0.5]), 3, [0.6, 0.5]);
  assert.deepEqual(token.moves, [[1, 0.2, 0.5], [3, 0.6, 0.5]]);
  near(positionAt(token, 0)[0], 0.2);
  near(positionAt(token, 1)[0], 0.2); // holds until the glide
  near(positionAt(token, 2)[0], 0.4); // half way, half the distance
  assert.ok(positionAt(token, 1.5)[0] < 0.29); // slow start: linear would be at 0.3
  near(positionAt(token, 3.5)[0], 0.6); // holds at the end
  assert.deepEqual(positionAt(clearMoves(token), 2), [0.2, 0.5]);
});

test("dragging sets the start near the beginning, else a key; a key close to another replaces it", () => {
  const token = newToken([0.2, 0.5], { from: 0, to: 4 });
  assert.deepEqual(setMove(token, 0.01, [0.3, 0.3]).points, [[0.3, 0.3]]);
  const once = setMove(token, 2, [0.5, 0.5]);
  const again = setMove(once, 2.02, [0.7, 0.5]);
  assert.deepEqual(again.moves, [[2.02, 0.7, 0.5]]);
  assert.deepEqual(setMove(again, 1, [0.4, 0.5]).moves.map(([s]) => s), [1, 2.02]);
});

test("moving tokens are placed for the moment on screen, in output time", () => {
  const value = addBoard({ version: 1, freezes: [], tracks: [], items: [] }, clip, 25, 4, board,
    (from, to) => [setMove(newToken([0.2, 0.5], { from, to }), 2, [0.6, 0.5])]);
  const start = freezeStart(25, clip, value.freezes);
  const token = value.items[0];
  near(placedAt(value, clip, token, start + 1).points[0][0], 0.4);
  near(placedAt(value, clip, token, start + 3).points[0][0], 0.6);
  const still = { ...token, moves: undefined };
  assert.equal(placedAt(value, clip, still, start + 1), still);
});

test("players are matched within their team, nearest first, within 20 m", () => {
  const tokens = [{ team: "home", metres: [0, 0] }, { team: "home", metres: [10, 0] }, { team: "away", metres: [5, 5] }];
  const players = [{ team: "home", metres: [11, 0] }, { team: "away", metres: [0, 1] }, { team: "home", metres: [1, 0] }, { team: "home", metres: [50, 30] }];
  assert.deepEqual(matchPlayers(tokens, players).sort(), [[0, 2], [1, 0], [2, 1]].sort());
  assert.deepEqual(matchPlayers([{ team: "home", metres: [0, 0] }], [{ team: "home", metres: [25, 0] }]), []);
});

test("moving a board's players to a later frame grows the board and adds keys", () => {
  const layout = boardLayout("full", ASPECT);
  const value = addBoard({ version: 1, freezes: [], tracks: [], items: [] }, clip, 25, 4, board, (from, to) => [
    newToken(layout.toBoard([0, 0]), { team: "home", from, to }),
    newToken(layout.toBoard([30, 10]), { team: "away", from, to }),
  ]);
  const players = [{ team: "home", metres: [8, 2] }, { team: "home", metres: [-40, -20] }];
  const { value: moved, matched, added, kept } = moveBoard(value, clip, 25, players, ASPECT);
  assert.deepEqual([matched, added, kept], [1, 1, 1]);
  assert.equal(moved.freezes[0].seconds, 4 + MOVE_SECONDS);
  const [home, away, fresh] = moved.items;
  assert.equal(home.moves.length, 2);
  assert.equal(home.moves[1][0] - home.moves[0][0], GLIDE_SECONDS);
  const [x, y] = layout.toPitch(positionAt(home, 7));
  near(x, 8, 1e-3);
  near(y, 2, 1e-3);
  assert.equal(away.moves, undefined); // not found there: stays put
  assert.equal(away.show.to, home.show.to); // but shows for the whole longer board
  const start = freezeStart(25, clip, moved.freezes);
  near(fresh.show.from, start + home.moves[1][0], 1e-3); // appears when the glide ends
  assert.equal(fresh.on, 25);
});

test("export patches carry only the tiles that changed", () => {
  const width = 200;
  const height = 130;
  const before = new Uint8ClampedArray(width * height * 4);
  const after = new Uint8ClampedArray(before);
  after[(70 * width + 150) * 4 + 3] = 255; // one pixel in tile (2, 1)
  const tiles = changedTiles(before, after, width, height);
  assert.deepEqual(tiles.map(({ x, y, w, h }) => [x, y, w, h]), [[2 * TILE, TILE, TILE, TILE]]);
  assert.equal(tiles[0].pixels.length, TILE * TILE * 4);
  assert.equal(tiles[0].pixels[((70 - TILE) * TILE + (150 - 2 * TILE)) * 4 + 3], 255);
  assert.deepEqual(changedTiles(before, before, width, height), []);
  const edge = new Uint8ClampedArray(before);
  edge[(129 * width + 199) * 4] = 1; // the last, partial tile
  assert.deepEqual(changedTiles(before, edge, width, height).map(({ x, y, w, h }) => [x, y, w, h]), [[192, 128, 8, 2]]);
  assert.equal(changedTiles(before, new Uint8ClampedArray(before.length).fill(9), width, height), null); // all changed
});
