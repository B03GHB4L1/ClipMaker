// Fitting a loose box to the player (ui/annotate/fit.js).
import assert from "node:assert/strict";
import { test } from "node:test";
import { fitBox, isGrass, pitchHue } from "../ui/annotate/fit.js";

// A grass-coloured picture with noise, to which parts of players are added.
const picture = (width, height) => {
  const data = new Uint8ClampedArray(width * height * 4);
  let seed = 7;
  const noise = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return (seed >> 8) % 40; };
  for (let i = 0; i < width * height; i += 1) {
    const n = noise();
    data.set([60 + n, 140 + n, 40 + (n >> 1), 255], i * 4);
  }
  const rect = (x, y, w, h, colour) => {
    for (let yy = y; yy < y + h; yy += 1) for (let xx = x; xx < x + w; xx += 1) data.set([...colour, 255], (yy * width + xx) * 4);
  };
  return { data, width, height, rect };
};
// A standing player: head, shirt, shorts and socks with small gaps between, 16 wide and 44 tall at (x, y).
const player = (image, x, y, shirt = [30, 50, 170]) => {
  image.rect(x + 4, y, 8, 8, [225, 180, 150]); // head
  image.rect(x, y + 8, 16, 14, shirt);
  image.rect(x + 2, y + 24, 12, 8, [20, 20, 30]); // shorts, a gap of two rows above them
  image.rect(x + 3, y + 34, 4, 10, [240, 240, 240]); // socks, another gap
  image.rect(x + 9, y + 34, 4, 10, [240, 240, 240]);
  return [x, y, x + 16, y + 44];
};
const near = (actual, expected, tolerance, message) => assert.ok(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} vs ${expected}`);

test("grass is green in light or shadow; shirts, skin and lines are not", () => {
  assert.ok(isGrass(120, 170, 40));
  assert.ok(isGrass(30, 70, 20)); // shadowed
  assert.ok(!isGrass(30, 50, 170)); // blue shirt
  assert.ok(!isGrass(200, 40, 40)); // red shirt
  assert.ok(!isGrass(240, 240, 240)); // white kit or a pitch line
  assert.ok(!isGrass(225, 180, 150)); // skin
});

test("the pitch colour is read from the picture, so a yellow-green broadcast works too", () => {
  const image = picture(120, 120);
  for (let i = 0; i < 120 * 120; i += 1) image.data.set([150 + (i % 7), 158 + (i % 5), 20 + (i % 9), 255], i * 4); // hue 63, as on the real clip
  const truth = player(image, 52, 40);
  near(pitchHue(image.data), 63, 12, "hue");
  const fitted = fitBox(image, [30, 25, 90, 100]);
  assert.ok(fitted, "found the player");
  fitted.forEach((value, i) => near(value, truth[i], 2, `side ${i}`));
});

test("a loose box shrinks onto the player, shadow and gaps included", () => {
  const image = picture(120, 120);
  const truth = player(image, 52, 40);
  image.rect(50, 83, 30, 4, [25, 60, 20]); // a dark shadow on the grass: still grass
  const loose = [30, 25, 90, 100]; // four times too big, player off-centre
  const fitted = fitBox(image, loose);
  assert.ok(fitted, "found the player");
  fitted.forEach((value, i) => near(value, truth[i] + (i > 1 ? 0 : 0), 2, `side ${i}`));
});

test("a box that cuts the player off grows to take in the rest of them, within limits", () => {
  const image = picture(120, 120);
  const truth = player(image, 52, 40);
  const fitted = fitBox(image, [50, 38, 70, 70]); // misses the feet and one side
  assert.ok(fitted);
  near(fitted[3], truth[3], 2, "reaches the boots");
  near(fitted[2], truth[2], 2, "reaches the right side");
});

test("two players touching are not told apart: the analyst's box is kept", () => {
  const image = picture(140, 120);
  player(image, 50, 40);
  player(image, 62, 40, [200, 40, 40]); // overlaps the first
  assert.equal(fitBox(image, [44, 34, 84, 90]), null);
});

test("the player is picked by the middle of the box, not by size", () => {
  const image = picture(160, 120);
  const mine = player(image, 40, 40);
  image.rect(110, 30, 30, 60, [180, 60, 160]); // a bigger blob elsewhere in the cut-out
  const fitted = fitBox(image, [30, 30, 66, 94]);
  assert.ok(fitted);
  near(fitted[0], mine[0], 2, "left");
  near(fitted[2], mine[2], 2, "right");
});

test("a thin pitch line through the box is not part of the player", () => {
  const image = picture(140, 140);
  const truth = player(image, 60, 50);
  image.rect(0, 100, 140, 2, [245, 245, 245]); // a line at the player's boots, 2 px thick
  const fitted = fitBox(image, [40, 40, 100, 110]);
  assert.ok(fitted);
  near(fitted[3], truth[3] + 0, 3, "boots, not the line");
  near(fitted[2] - fitted[0], 16, 3, "width");
});

test("a thin line touching the player is left out; a thick one that cannot be separated gives nothing", () => {
  const image = picture(160, 140);
  const truth = player(image, 60, 40);
  for (let k = 0; k < 60; k += 1) image.rect(76 + k, 84 - Math.round(k * 0.5), 2, 2, [245, 245, 245]); // a thin diagonal line leaving the boots
  const fitted = fitBox(image, [44, 30, 100, 100]);
  assert.ok(fitted, "the line is thinner than the opening, so it goes");
  near(fitted[2], truth[2], 2, "right side");
  near(fitted[3], truth[3], 2, "boots");
  const thick = picture(160, 140);
  player(thick, 60, 40);
  for (let k = 0; k < 60; k += 1) thick.rect(76 + k, 80 - Math.round(k * 0.5), 6, 6, [245, 245, 245]); // as thick as a limb, curving away
  assert.equal(fitBox(thick, [44, 30, 100, 100]), null);
});

test("no grass, a crowd or a tiny box give nothing", () => {
  const night = picture(80, 80);
  night.rect(0, 0, 80, 80, [90, 90, 100]); // no pitch at all
  assert.equal(fitBox(night, [20, 20, 60, 70]), null);
  const crowd = picture(100, 100);
  crowd.rect(0, 0, 100, 45, [150, 100, 90]); // a stand across the top of the cut-out
  player(crowd, 42, 30); // the player's head is in front of it, joined to it
  assert.equal(fitBox(crowd, [30, 20, 70, 80]), null);
  assert.equal(fitBox(picture(40, 40), [10, 10, 12, 14]), null);
});

test("a box at the video's own edge may run to it", () => {
  const image = picture(80, 100);
  player(image, 0, 40);
  assert.equal(fitBox(image, [0, 34, 30, 90]), null, "the blob touches the cut-out's edge: it might go on");
  const fitted = fitBox(image, [0, 34, 30, 90], { left: true });
  assert.ok(fitted);
  assert.equal(fitted[0], 0);
});
