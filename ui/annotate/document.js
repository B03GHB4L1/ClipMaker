// The drawings for one clip, with undo and redo. Every change goes through
// commit(), which keeps a snapshot; the server validates the same shape
// (app/telestration/annotations.py).
import { DEFAULT_STYLE } from "./shapes.js";

export const COORD_MIN = -0.5;
export const COORD_MAX = 1.5;
const HISTORY_LIMIT = 100;

const copy = (value) => JSON.parse(JSON.stringify(value));
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
export const clampPoint = ([x, y]) => [clamp(x, COORD_MIN, COORD_MAX), clamp(y, COORD_MIN, COORD_MAX)];
const round = (value) => Math.round(value * 1e5) / 1e5;

let counter = 0;
export const newId = () => `d${Date.now().toString(36)}${(counter++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

/** A new drawing of `kind`, shown from `from` to `to` seconds. */
export const newItem = (kind, points, { from, to, style, geometry, text } = {}) => {
  const item = {
    id: newId(),
    kind,
    points: points.map((point) => (Array.isArray(point) ? clampPoint(point).map(round) : { ...point })), // linked points stay linked
    style: { ...DEFAULT_STYLE[kind], ...(style || {}) },
    show: { from: Math.round(from * 1000) / 1000, to: Math.round(to * 1000) / 1000, animate: "none" },
  };
  if (kind === "ring" || kind === "spotlight") item.geometry = { ...geometry };
  if (kind === "shape") item.geometry = { shape: geometry?.shape || "rect" };
  if (kind === "text") item.text = text;
  return item;
};

/** The item moved by (dx, dy) fractions of the frame. */
export const moveItem = (item, dx, dy) => ({
  ...item,
  points: item.points.map((point) => (Array.isArray(point) ? clampPoint([point[0] + dx, point[1] + dy]).map(round) : point)),
});

/** The item with handle `index` dragged to `point` (see shapes.handlesFor). */
export const dragHandle = (item, index, point) => {
  const next = copy(item);
  const [x, y] = clampPoint(point);
  if (index === "r") {
    const rx = clamp(Math.abs(x - item.points[0][0]), 0.004, 0.5);
    // Keep the ring's shape as it grows.
    next.geometry.rx = round(rx);
    next.geometry.ry = round(clamp((rx * item.geometry.ry) / item.geometry.rx, 0.002, 0.5));
  } else if (index === "h") {
    next.geometry.h = round(clamp(item.points[0][1] - y, 0.02, 1));
  } else {
    next.points[index] = [round(x), round(y)];
  }
  return next;
};

/** Ring size from a drag of `rxFraction` of the frame width: flat, as if on the grass. */
export const ringGeometry = (rxFraction, aspect) => {
  const rx = clamp(rxFraction, 0.004, 0.5);
  return { rx: round(rx), ry: round(clamp(rx * aspect * 0.35, 0.002, 0.5)) };
};

/** Drop points closer than `minimum` pixels to the last kept one; always keeps the end. */
export const simplify = (points, minimum, w, h) => {
  if (points.length < 3) return points;
  const kept = [points[0]];
  for (let index = 1; index < points.length - 1; index += 1) {
    const last = kept[kept.length - 1];
    if (Math.hypot((points[index][0] - last[0]) * w, (points[index][1] - last[1]) * h) >= minimum) kept.push(points[index]);
  }
  kept.push(points[points.length - 1]);
  return kept.slice(0, 2000);
};

export const createDocument = (saved) => {
  let current = copy(saved || { version: 1, items: [], freezes: [] });
  const past = [];
  const future = [];
  const listeners = new Set();
  const emit = () => listeners.forEach((listener) => listener(current));
  return {
    get value() { return current; },
    get items() { return current.items; },
    get freezes() { return current.freezes || []; },
    get canUndo() { return past.length > 0; },
    get canRedo() { return future.length > 0; },
    find: (id) => current.items.find((item) => item.id === id) || null,
    onChange: (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    /** Apply `change(document) -> document` as one undoable step (freezes and drawings together). */
    commitDocument(change) {
      const next = change(copy(current));
      if (JSON.stringify(next) === JSON.stringify(current)) return false;
      past.push(current);
      if (past.length > HISTORY_LIMIT) past.shift();
      future.length = 0;
      current = copy(next);
      emit();
      return true;
    },
    /** Apply `change(items) -> items` as one undoable step. */
    commit(change) { return this.commitDocument((value) => ({ ...value, items: change(value.items) })); },
    add(item) { return this.commit((items) => [...items, item]); },
    replace(item) { return this.commit((items) => items.map((each) => (each.id === item.id ? item : each))); },
    remove(id) { return this.commit((items) => items.filter((item) => item.id !== id)); },
    undo() {
      if (!past.length) return false;
      future.push(current);
      current = past.pop();
      emit();
      return true;
    },
    redo() {
      if (!future.length) return false;
      past.push(current);
      current = future.pop();
      emit();
      return true;
    },
  };
};
