// The Code screen's pitch (C4): from a click on the drawing to the location scraped
// feeds use, and back. The drawing is 105 by 68 (metres), the event's team attacking
// to the right. Feeds measure x from 0 (own goal line) to 100 (opponent's) and y from
// 0 (the team's right touchline, the bottom of the drawing) to 100 (its left).
// Pure functions, so tests/code.test.mjs can check them.

const LENGTH = 105;
const WIDTH = 68;
const clamp = (value) => Math.min(100, Math.max(0, Math.round(value * 10) / 10));

export const pitchPoint = {
  fromSvg: (sx, sy) => ({ x: clamp((sx / LENGTH) * 100), y: clamp(100 - (sy / WIDTH) * 100) }),
  toSvg: (x, y) => ({ sx: (x / 100) * LENGTH, sy: (1 - y / 100) * WIDTH }),
  // A drag counts as an end point once it travels about two metres.
  moved: (start, end) => Math.hypot(((end.x - start.x) / 100) * LENGTH, ((end.y - start.y) / 100) * WIDTH) >= 2,
};

const third = (x) => (x < 34 ? "defensive third" : x < 67 ? "middle third" : "attacking third");
const lane = (y) => {
  const across = 100 - y; // as whoscored_scraper._pitch_zone(y, flip=True)
  return across < 20 ? "left wing" : across < 37 ? "left half-space" : across < 63 ? "centre"
    : across < 80 ? "right half-space" : "right wing";
};

/** "left wing, attacking third", with " to centre, attacking third" for an end point. */
export const placed = (event) => {
  if (event.x == null) return "";
  const where = (x, y) => `${lane(y)}, ${third(x)}`;
  return event.endX != null ? `${where(event.x, event.y)} to ${where(event.endX, event.endY)}` : where(event.x, event.y);
};
