// Drawing and hit-testing for the analyst editor (docs/TELESTRATION_PLAN.md).
// Pure functions of an item and a canvas size, shared by the live view and
// screenshots so both draw exactly the same thing. Points are fractions of the
// frame; widths and text sizes are pixels on a 1080-pixel-high frame.

import { animation } from "./timeline.js";
import { LENGTH, LINES, WIDTH } from "./pitch.js";

export const TEXT_FONT = '"Segoe UI", "Helvetica Neue", Arial, system-ui, sans-serif';

export const DEFAULT_STYLE = {
  ring: { stroke: "#ffd400", width: 4, flat: false },
  spotlight: { fill: "#ffffff", fillOpacity: 0.3, stroke: "#ffffff", width: 3 },
  arrow: { stroke: "#ffd400", width: 5, dashed: false, flat: false },
  line: { stroke: "#ffffff", width: 4, dashed: true },
  freehand: { stroke: "#ff4d4d", width: 5 },
  text: { color: "#ffffff", background: "#171817", size: 40, bold: false },
  zone: { stroke: "#2f80ed", width: 3, fill: "#2f80ed", pattern: "solid", fillOpacity: 0.25 },
  shape: { stroke: "#ffffff", width: 3, fill: "#ffffff", pattern: "solid", fillOpacity: 0.15, dashed: false },
  token: { fill: "#d6262e", color: "#ffffff", stroke: "#ffffff", size: 34, width: 2 },
  // P3: always on the pitch (flat), so they are read through the clip's calibration.
  offside: { stroke: "#ffd400", width: 4, dashed: false, flat: true },
  measure: { stroke: "#ffffff", width: 4, dashed: false, flat: true },
  // P3b: a small pitch in a corner of the picture with the followed players on it; `size` is its width in tens of pixels.
  minimap: { stroke: "#ffffff", width: 2, fill: "#1f6f3a", fillOpacity: 0.85, color: "#ffd400", size: 60 },
};

const MINIMAP_MARGIN = 4; // metres of grass drawn round the pitch's lines
/** A minimap's box in pixels on a w×h canvas: {x, y, width, height}; the point is its top-left corner. */
export const minimapBox = (item, w, h) => {
  const width = styleOf(item).size * 4 * scaleFor(h);
  const [x, y] = px(item.points[0], w, h);
  return { x, y, width, height: (width * (WIDTH + 2 * MINIMAP_MARGIN)) / (LENGTH + 2 * MINIMAP_MARGIN) };
};

/** Geometric shapes (the Shape tool): drawn in the box between two dragged corners. */
export const SHAPES = { rect: "Rectangle", ellipse: "Ellipse", triangle: "Triangle", diamond: "Diamond", pentagon: "Pentagon", hexagon: "Hexagon", star: "Star" };

// Each shape's outline in a unit box (0..1 both ways), filling it.
const fitBox = (points) => {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const [x0, y0] = [Math.min(...xs), Math.min(...ys)];
  const [w, h] = [Math.max(...xs) - x0 || 1, Math.max(...ys) - y0 || 1];
  return points.map(([x, y]) => [(x - x0) / w, (y - y0) / h]);
};
const around = (count, radius = () => 1) => fitBox(Array.from({ length: count }, (_, i) => {
  const angle = -Math.PI / 2 + (Math.PI * 2 * i) / count; // from the top, clockwise
  return [Math.cos(angle) * radius(i), Math.sin(angle) * radius(i)];
}));
const UNIT_OUTLINES = {
  rect: [[0, 0], [1, 0], [1, 1], [0, 1]],
  ellipse: around(72),
  triangle: [[0.5, 0], [1, 1], [0, 1]],
  diamond: [[0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]],
  pentagon: around(5),
  hexagon: around(6),
  star: around(10, (i) => (i % 2 ? 0.382 : 1)),
};

/** A shape's outline (closed polygon) in the box between corners `a` and `b`, in the same units as they are. */
export const shapeOutline = (name, a, b) => {
  const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
  const [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
  return (UNIT_OUTLINES[name] || UNIT_OUTLINES.rect).map(([u, v]) => [x0 + u * (x1 - x0), y0 + v * (y1 - y0)]);
};

/** Zone fills: a wash of colour, or lines across the zone (hatching). */
export const PATTERNS = { solid: "Solid", lines: "Lines", cross: "Crossed lines" };

/** Diagonal lines across the zone's box, clipped to the zone by the caller. Spacing follows the frame height. */
const hatch = (ctx, points, h, angles) => {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const [left, right, top, bottom] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const gap = Math.max(5, h * 0.018);
  const reach = right - left + bottom - top;
  ctx.beginPath();
  angles.forEach((slope) => {
    // Lines x - slope*y = c, for every c that crosses the box.
    const low = slope > 0 ? left - slope * bottom : left - slope * top;
    for (let c = low - gap; c <= low + reach + gap; c += gap) {
      ctx.moveTo(c + slope * top, top);
      ctx.lineTo(c + slope * bottom, bottom);
    }
  });
  ctx.stroke();
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
      if (item.projected?.outline) {
        // Flat on the pitch (P1): a true circle on the grass, seen through the calibration.
        const outline = item.projected.outline.map((point) => px(point, w, h));
        tracePath(ctx, outline);
        ctx.closePath();
        ctx.fillStyle = rgba(style.stroke, 0.18 * state.draw);
        ctx.fill();
        tracePath(ctx, partialPath(outline, state.draw));
        ctx.stroke();
        break;
      }
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
    case "minimap": {
      // The pitch as seen from above, far side up as in the picture, with a dot for each followed player.
      const box = minimapBox(item, w, h);
      const k = box.width / (LENGTH + 2 * MINIMAP_MARGIN);
      const onMap = ([x, y]) => [box.x + (x + LENGTH / 2 + MINIMAP_MARGIN) * k, box.y + (y + WIDTH / 2 + MINIMAP_MARGIN) * k];
      ctx.setLineDash([]);
      ctx.fillStyle = rgba(style.fill, style.fillOpacity);
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(box.x, box.y, box.width, box.height, box.width * 0.03);
      else ctx.rect(box.x, box.y, box.width, box.height);
      ctx.fill();
      ctx.strokeStyle = rgba(style.stroke, 0.85);
      ctx.lineWidth = Math.max(1, width * 0.5);
      LINES.forEach((line) => { tracePath(ctx, line.map(onMap)); ctx.stroke(); });
      (item.projected?.players || []).forEach((player) => {
        const [x, y] = onMap(player.at);
        ctx.beginPath();
        ctx.arc(x, y, Math.max(2.5, box.width * 0.022), 0, Math.PI * 2);
        ctx.fillStyle = style.color;
        ctx.fill();
        ctx.lineWidth = Math.max(1, box.width * 0.006);
        ctx.strokeStyle = "rgba(23, 24, 23, 0.85)";
        ctx.stroke();
      });
      break;
    }
    case "offside": {
      // A line across the pitch at the clicked spot's depth, and a dot where the spot is.
      const segments = item.projected?.segments;
      (segments || []).forEach((segment) => {
        const line = segment.map((point) => px(point, w, h));
        tracePath(ctx, segments.length === 1 ? partialPath(line, state.draw) : line);
        ctx.stroke();
      });
      ctx.setLineDash([]);
      ctx.fillStyle = style.stroke;
      ctx.beginPath();
      ctx.arc(points[0][0], points[0][1], Math.max(3, width * 0.9), 0, Math.PI * 2);
      ctx.fill();
      break;
    }
    case "measure": {
      tracePath(ctx, partialPath(points, state.draw));
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = style.stroke;
      points.forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, Math.max(3, width * 0.9), 0, Math.PI * 2); ctx.fill(); });
      if (item.projected && state.draw >= 1) {
        // The distance on the grass, on a dark pill at the middle of the line.
        const [mx, my] = px(item.projected.mid, w, h);
        const size = Math.max(1, 30 * scale);
        const label = `${item.projected.metres.toFixed(1)} m`;
        ctx.font = `700 ${size}px ${TEXT_FONT}`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const pill = ctx.measureText(label).width + size * 0.9;
        ctx.fillStyle = "rgba(23, 24, 23, 0.82)";
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(mx - pill / 2, my - size * 0.8, pill, size * 1.6, size * 0.4);
        else ctx.rect(mx - pill / 2, my - size * 0.8, pill, size * 1.6);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.fillText(label, mx, my + size * 0.04);
      }
      break;
    }
    case "arrow": {
      if (item.projected?.head && state.draw >= 1) {
        // Flat on the pitch (P1): the head lies on the grass, smaller the further away it is.
        const [tip, left, right] = item.projected.head.map((point) => px(point, w, h));
        tracePath(ctx, [points[0], px(item.projected.neck, w, h)]);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = style.stroke;
        tracePath(ctx, [tip, left, right]);
        ctx.closePath();
        ctx.fill();
        break;
      }
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
    case "zone":
    case "shape": {
      const outline = item.kind === "shape" ? shapeOutline(item.geometry?.shape, points[0], points[1]) : points;
      tracePath(ctx, outline);
      ctx.closePath();
      if (style.pattern === "lines" || style.pattern === "cross") {
        // Hatching: a faint wash under lines strong enough to read on grass.
        ctx.fillStyle = rgba(style.fill, style.fillOpacity * 0.3 * state.draw);
        ctx.fill();
        ctx.save();
        ctx.clip();
        ctx.strokeStyle = rgba(style.fill, Math.min(1, style.fillOpacity * 2.6) * state.draw);
        ctx.lineWidth = Math.max(1.5, width * 0.6);
        ctx.setLineDash([]);
        hatch(ctx, outline, h, style.pattern === "cross" ? [1, -1] : [1]);
        ctx.restore(); // back to the outline's colour, width and dashes
      } else {
        ctx.fillStyle = rgba(style.fill, style.fillOpacity * state.draw);
        ctx.fill();
      }
      tracePath(ctx, partialPath(outline, state.draw, true));
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
    case "token": {
      const [cx, cy] = points[0];
      const radius = (style.size / 2) * scale;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fillStyle = style.fill;
      ctx.shadowColor = "rgba(0, 0, 0, 0.35)";
      ctx.shadowBlur = radius * 0.35;
      ctx.fill();
      ctx.shadowColor = "transparent";
      if (style.width) {
        ctx.lineWidth = style.width * scale;
        ctx.strokeStyle = style.stroke;
        ctx.stroke();
      }
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      if (item.label) {
        ctx.font = `700 ${Math.max(1, radius * (item.label.length > 2 ? 0.8 : 1.0))}px ${TEXT_FONT}`;
        ctx.fillStyle = style.color;
        ctx.fillText(item.label, cx, cy + radius * 0.05);
      }
      if (item.name) {
        // The name sits on a dark pill under the disc, readable on grass and on a light board.
        const size = Math.max(1, radius * 0.72);
        ctx.font = `600 ${size}px ${TEXT_FONT}`;
        const width = ctx.measureText(item.name).width + size * 0.8;
        const top = cy + radius + size * 0.3;
        ctx.fillStyle = "rgba(23, 24, 23, 0.78)";
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(cx - width / 2, top, width, size * 1.45, size * 0.35);
        else ctx.rect(cx - width / 2, top, width, size * 1.45);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.fillText(item.name, cx, top + size * 0.75);
      }
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
    case "minimap": {
      const box = minimapBox(item, w, h);
      return x >= box.x - tolerance && x <= box.x + box.width + tolerance && y >= box.y - tolerance && y <= box.y + box.height + tolerance;
    }
    case "offside": {
      const lines = (item.projected?.segments || []).map((segment) => segment.map((point) => px(point, w, h)));
      return Math.hypot(x - points[0][0], y - points[0][1]) <= reach + 4
        || lines.some((line) => line.some((point, index) => index > 0 && segmentDistance(at, line[index - 1], point) <= reach));
    }
    case "arrow":
    case "line":
    case "measure":
    case "freehand":
      return points.some((point, index) => index > 0 && segmentDistance(at, points[index - 1], point) <= reach)
        || (points.length === 1 && Math.hypot(x - points[0][0], y - points[0][1]) <= reach);
    case "zone":
    case "shape": {
      const outline = item.kind === "shape" ? shapeOutline(item.geometry?.shape, points[0], points[1]) : points;
      return insidePolygon(at, outline)
        || outline.some((point, index) => segmentDistance(at, outline[(index || outline.length) - 1], point) <= reach);
    }
    case "token":
      return Math.hypot(x - points[0][0], y - points[0][1]) <= (style.size / 2) * scale + tolerance;
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
  if (item.kind === "freehand" || item.kind === "token") return []; // tokens move whole
  const handles = item.points.map((point, index) => ({ index, point }));
  if (item.kind === "ring" || item.kind === "spotlight") {
    handles.push({ index: "r", point: [item.points[0][0] + item.geometry.rx, item.points[0][1]] });
  }
  if (item.kind === "spotlight") {
    handles.push({ index: "h", point: [item.points[0][0], item.points[0][1] - item.geometry.h] });
  }
  return handles;
};

// ---------------------------------------------------------------------------
// Export (M4): the drawn part of an overlay, sent to the engine as raw pixels
// ---------------------------------------------------------------------------

/** The box of pixels that has any drawing in it, as {x, y, w, h, pixels}, or null when nothing is drawn. */
export const cropDrawn = (data, width, height) => {
  const words = new Uint32Array(data.buffer, data.byteOffset, width * height); // a pixel is 0 where nothing is drawn
  let top = -1;
  let bottom = -1;
  let left = width;
  let right = -1;
  for (let y = 0; y < height; y += 1) {
    const row = y * width;
    let first = -1;
    for (let x = 0; x < width; x += 1) if (words[row + x]) { first = x; break; }
    if (first < 0) continue;
    if (top < 0) top = y;
    bottom = y;
    if (first < left) left = first;
    for (let x = width - 1; x > right; x -= 1) if (words[row + x]) { right = x; break; }
  }
  if (top < 0) return null;
  const w = right - left + 1;
  const h = bottom - top + 1;
  const pixels = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y += 1) pixels.set(data.subarray(((top + y) * width + left) * 4, ((top + y) * width + left + w) * 4), y * w * 4);
  return { x: left, y: top, w, h, pixels };
};

export const TILE = 64;
/**
 * The 64 px tiles where `current` differs from `previous` (both RGBA of the whole frame),
 * as [{x, y, w, h, pixels}]; null when more than half the tiles changed, so a whole
 * overlay is cheaper. A moving board changes only round its tokens (M8).
 */
export const changedTiles = (previous, current, width, height, share = 0.5) => {
  const before = new Uint32Array(previous.buffer, previous.byteOffset, width * height);
  const after = new Uint32Array(current.buffer, current.byteOffset, width * height);
  const columns = Math.ceil(width / TILE);
  const rows = Math.ceil(height / TILE);
  const tiles = [];
  for (let ty = 0; ty < rows; ty += 1) {
    for (let tx = 0; tx < columns; tx += 1) {
      const x = tx * TILE;
      const y = ty * TILE;
      const w = Math.min(TILE, width - x);
      const h = Math.min(TILE, height - y);
      let changed = false;
      for (let row = y; row < y + h && !changed; row += 1) {
        const start = row * width + x;
        for (let i = start; i < start + w; i += 1) if (before[i] !== after[i]) { changed = true; break; }
      }
      if (!changed) continue;
      if (tiles.length + 1 > columns * rows * share) return null;
      const pixels = new Uint8Array(w * h * 4);
      for (let row = 0; row < h; row += 1) pixels.set(current.subarray(((y + row) * width + x) * 4, ((y + row) * width + x + w) * 4), row * w * 4);
      tiles.push({ x, y, w, h, pixels });
    }
  }
  return tiles;
};
