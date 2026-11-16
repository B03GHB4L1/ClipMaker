// Drawing and hit-testing for the analyst editor (docs/TELESTRATION_PLAN.md).
// Pure functions of an item and a canvas size, shared by the live view and
// screenshots so both draw exactly the same thing. Points are fractions of the
// frame; widths and text sizes are pixels on a 1080-pixel-high frame.

import { animation } from "./timeline.js";

export const TEXT_FONT = '"Segoe UI", "Helvetica Neue", Arial, system-ui, sans-serif';

export const DEFAULT_STYLE = {
  ring: { stroke: "#ffd400", width: 4 },
  spotlight: { fill: "#ffffff", fillOpacity: 0.3, stroke: "#ffffff", width: 3 },
  arrow: { stroke: "#ffd400", width: 5, dashed: false },
  line: { stroke: "#ffffff", width: 4, dashed: true },
  freehand: { stroke: "#ff4d4d", width: 5 },
  text: { color: "#ffffff", background: "#171817", size: 40, bold: false },
  zone: { stroke: "#2f80ed", fill: "#2f80ed", fillOpacity: 0.25, width: 3 },
};

export const styleOf = (item) => ({ ...DEFAULT_STYLE[item.kind], ...(item.style || {}) });
export const scaleFor = (height) => height / 1080;
export const visibleAt = (item, time) => animation(item, time) !== null;

const rgba = (hex, alpha) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
};

const px = (point, w, h) => [point[0] * w, point[1] * h];

export const textLines = (item) => String(item.text || "").split("\n");

export const textFont = (item, scale) => {
  const style = styleOf(item);
  return `${style.bold ? 700 : 500} ${Math.max(1, style.size * scale)}px ${TEXT_FONT}`;
};

/** The text's box in pixels: {x, y, width, height}. `measure(line, font)` gives a line's width. */
export const textBox = (item, w, h, measure) => {
  const scale = scaleFor(h);
  const style = styleOf(item);
  const font = textFont(item, scale);
  const size = style.size * scale;
  const pad = size * 0.35;
  const lines = textLines(item);
  const widest = Math.max(...lines.map((line) => (measure ? measure(line, font) : line.length * size * 0.56)));
  const [x, y] = px(item.points[0], w, h);
  return { x, y, width: widest + pad * 2, height: lines.length * size * 1.25 + pad * 2, pad, size, font };
};

const arrowHead = (ctx, from, to, size) => {
  const angle = Math.atan2(to[1] - from[1], to[0] - from[0]);
  ctx.beginPath();
  ctx.moveTo(to[0], to[1]);
  ctx.lineTo(to[0] - size * Math.cos(angle - 0.45), to[1] - size * Math.sin(angle - 0.45));
  ctx.lineTo(to[0] - size * Math.cos(angle + 0.45), to[1] - size * Math.sin(angle + 0.45));
  ctx.closePath();
  ctx.fill();
};

const FULL = { alpha: 1, draw: 1, scale: 1, offsetY: 0, pulse: null };

/** The first `share` (0-1) of a pixel path, by length. */
export const partialPath = (points, share, closed = false) => {
  const path = closed ? [...points, points[0]] : points;
  if (share >= 1 || path.length < 2) return path;
  const lengths = path.slice(1).map((point, index) => Math.hypot(point[0] - path[index][0], point[1] - path[index][1]));
  let remaining = lengths.reduce((sum, length) => sum + length, 0) * Math.max(0, share);
  const result = [path[0]];
  for (let index = 0; index < lengths.length; index += 1) {
    if (remaining >= lengths[index]) {
      result.push(path[index + 1]);
      remaining -= lengths[index];
    } else {
      const t = lengths[index] ? remaining / lengths[index] : 0;
      result.push([path[index][0] + (path[index + 1][0] - path[index][0]) * t, path[index][1] + (path[index + 1][1] - path[index][1]) * t]);
      break;
    }
  }
  return result;
};

const tracePath = (ctx, points) => {
  ctx.beginPath();
  points.forEach(([x, y], index) => (index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
};

/** The pixel point a drawing grows from and pulses around. */
const anchorOf = (item, points, w, h, measure) => {
  if (item.kind === "ring" || item.kind === "spotlight") return points[0];
  if (item.kind === "text") {
    const box = textBox(item, w, h, measure);
    return [box.x + box.width / 2, box.y + box.height / 2];
  }
  return [points.reduce((sum, p) => sum + p[0], 0) / points.length, points.reduce((sum, p) => sum + p[1], 0) / points.length];
};

/** Draw one item on a w×h canvas context, in animation `state` (see timeline.js animation()). */
export const drawItem = (ctx, item, w, h, state = FULL) => {
  if (state.alpha <= 0.001 || state.scale <= 0.001 || state.draw <= 0) return;
  const scale = scaleFor(h);
  const style = styleOf(item);
  const width = (style.width || 4) * scale;
  const measure = (line, font) => { ctx.font = font; return ctx.measureText(line).width; };
  const points = item.points.map((point) => px(point, w, h));
  const anchor = anchorOf(item, points, w, h, measure);
  ctx.save();
  ctx.globalAlpha *= state.alpha;
  if (state.offsetY) ctx.translate(0, state.offsetY * h);
  if (state.scale !== 1) {
    ctx.translate(anchor[0], anchor[1]);
    ctx.scale(state.scale, state.scale);
    ctx.translate(-anchor[0], -anchor[1]);
  }
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.lineWidth = width;
  if (style.stroke) ctx.strokeStyle = style.stroke;
  ctx.setLineDash(style.dashed ? [width * 3, width * 2.2] : []);
  switch (item.kind) {
    case "ring": {
      const [cx, cy] = points[0];
      const { rx, ry } = item.geometry;
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx * w, ry * h, 0, 0, Math.PI * 2);
      ctx.fillStyle = rgba(style.stroke, 0.18 * state.draw);
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx * w, ry * h, 0, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * state.draw);
      ctx.stroke();
      break;
    }
    case "spotlight": {
      const [cx, cy] = points[0];
      const { rx, ry, h: beam } = item.geometry;
      const top = cy - beam * h;
      const gradient = ctx.createLinearGradient(0, cy, 0, top);
      gradient.addColorStop(0, rgba(style.fill, style.fillOpacity));
      gradient.addColorStop(1, rgba(style.fill, 0));
      ctx.beginPath();
      ctx.moveTo(cx - rx * w, cy);
      ctx.lineTo(cx - rx * w * 0.55, top);
      ctx.lineTo(cx + rx * w * 0.55, top);
      ctx.lineTo(cx + rx * w, cy);
      ctx.closePath();
      ctx.fillStyle = gradient;
      ctx.fill();
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx * w, ry * h, 0, 0, Math.PI * 2);
      ctx.fillStyle = rgba(style.fill, Math.min(1, style.fillOpacity + 0.15));
      ctx.fill();
      ctx.stroke();
      break;
    }
    case "line":
    case "freehand":
      tracePath(ctx, partialPath(points, state.draw));
      ctx.stroke();
      break;
    case "arrow": {
      // The head rides the tip of the drawn part; the shaft stops short of it so
      // a thick line does not poke through.
      const drawn = partialPath(points, state.draw);
      const from = points[0];
      const to = drawn[drawn.length - 1];
      const head = Math.max(10 * scale, width * 3.2);
      const length = Math.hypot(points[1][0] - from[0], points[1][1] - from[1]) || 1;
      const ux = (points[1][0] - from[0]) / length;
      const uy = (points[1][1] - from[1]) / length;
      const shaft = Math.hypot(to[0] - from[0], to[1] - from[1]);
      const back = Math.min(head * 0.8, shaft);
      tracePath(ctx, [from, [to[0] - ux * back, to[1] - uy * back]]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = style.stroke;
      arrowHead(ctx, [to[0] - ux, to[1] - uy], to, Math.min(head, Math.max(shaft, 1)));
      break;
    }
    case "zone": {
      tracePath(ctx, points);
      ctx.closePath();
      ctx.fillStyle = rgba(style.fill, style.fillOpacity * state.draw);
      ctx.fill();
      tracePath(ctx, partialPath(points, state.draw, true));
      ctx.stroke();
      break;
    }
    case "text": {
      const box = textBox(item, w, h, measure);
      if (style.background) {
        ctx.fillStyle = style.background;
        const radius = box.size * 0.18;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(box.x, box.y, box.width, box.height, radius);
        else ctx.rect(box.x, box.y, box.width, box.height);
        ctx.fill();
      }
      ctx.font = box.font;
      ctx.fillStyle = style.color;
      ctx.textBaseline = "top";
      if (!style.background) {
        // Legible on any pitch without a box: a soft dark edge.
        ctx.shadowColor = "rgba(0, 0, 0, 0.75)";
        ctx.shadowBlur = box.size * 0.18;
      }
      textLines(item).forEach((line, index) => ctx.fillText(line, box.x + box.pad, box.y + box.pad + index * box.size * 1.25 + box.size * 0.1));
      break;
    }
    default:
      break;
  }
  ctx.restore();
  if (state.pulse !== null && state.pulse !== undefined) drawPulse(ctx, item, points, anchor, w, h, state, width);
};

// An outline in the drawing's colour that swells and fades, once per pulse.
const drawPulse = (ctx, item, points, anchor, w, h, state, width) => {
  const style = styleOf(item);
  const grow = 1 + 0.6 * state.pulse;
  ctx.save();
  ctx.globalAlpha *= state.alpha * (1 - state.pulse) * 0.8;
  if (state.offsetY) ctx.translate(0, state.offsetY * h);
  ctx.translate(anchor[0], anchor[1]);
  ctx.scale(grow * state.scale, grow * state.scale);
  ctx.translate(-anchor[0], -anchor[1]);
  ctx.lineWidth = width / grow;
  ctx.strokeStyle = style.stroke || style.fill;
  ctx.beginPath();
  if (item.kind === "zone") {
    points.forEach(([x, y], index) => (index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
  } else {
    ctx.ellipse(points[0][0], points[0][1], item.geometry.rx * w, item.geometry.ry * h, 0, 0, Math.PI * 2);
  }
  ctx.stroke();
  ctx.restore();
};

/** Draw every item visible at output time `time`, each in its animation state. */
export const drawItems = (ctx, items, w, h, time) => {
  items.forEach((item) => {
    const state = animation(item, time);
    if (state) drawItem(ctx, item, w, h, state);
  });
};

// ---------------------------------------------------------------------------
// Hit-testing (pixels)
// ---------------------------------------------------------------------------

const segmentDistance = ([x, y], [x1, y1], [x2, y2]) => {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / length)) : 0;
  return Math.hypot(x - (x1 + t * dx), y - (y1 + t * dy));
};

const insidePolygon = ([x, y], points) => {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};

/** True when pixel (x, y) touches the item; `tolerance` is in pixels. */
export const hitTest = (item, x, y, w, h, tolerance = 6, measure) => {
  const scale = scaleFor(h);
  const style = styleOf(item);
  const reach = tolerance + ((style.width || 4) * scale) / 2;
  const points = item.points.map((point) => px(point, w, h));
  const at = [x, y];
  switch (item.kind) {
    case "ring":
    case "spotlight": {
      const [cx, cy] = points[0];
      const rx = item.geometry.rx * w + reach;
      const ry = item.geometry.ry * h + reach;
      if (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1) return true;
      if (item.kind === "spotlight") {
        const top = cy - item.geometry.h * h;
        return y >= top && y <= cy && Math.abs(x - cx) <= item.geometry.rx * w;
      }
      return false;
    }
    case "arrow":
    case "line":
    case "freehand":
      return points.some((point, index) => index > 0 && segmentDistance(at, points[index - 1], point) <= reach)
        || (points.length === 1 && Math.hypot(x - points[0][0], y - points[0][1]) <= reach);
    case "zone":
      return insidePolygon(at, points)
        || points.some((point, index) => segmentDistance(at, points[(index || points.length) - 1], point) <= reach);
    case "text": {
      const box = textBox(item, w, h, measure);
      return x >= box.x - tolerance && x <= box.x + box.width + tolerance && y >= box.y - tolerance && y <= box.y + box.height + tolerance;
    }
    default:
      return false;
  }
};

/** The top-most item visible at `time` under (x, y), or null. Later items draw on top. */
export const itemAt = (items, x, y, w, h, time, measure) => {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    if (visibleAt(items[index], time) && hitTest(items[index], x, y, w, h, 6, measure)) return items[index];
  }
  return null;
};

/** Drag handles for a selected item: [{index, point}] in fractions; index "r" resizes a ring or spotlight. */
export const handlesFor = (item) => {
  if (item.kind === "freehand") return [];
  const handles = item.points.map((point, index) => ({ index, point }));
  if (item.kind === "ring" || item.kind === "spotlight") {
    handles.push({ index: "r", point: [item.points[0][0] + item.geometry.rx, item.points[0][1]] });
  }
  if (item.kind === "spotlight") {
    handles.push({ index: "h", point: [item.points[0][0], item.points[0][1] - item.geometry.h] });
  }
  return handles;
};
