// Parts of a clip: cut, reorder and repeat (docs/TELESTRATION_PLAN.md, M9). The same rules as
// app/telestration/parts.py; tests/fixtures/parts_cases.json checks both.
//
// document.parts = [{from, to}] are source frame ranges (`to` exclusive) in play order. The parts
// joined end to end are the "cut clip" with its own frame numbers. Freezes, boards and output time
// count cut frames, so ./timeline.js works on cutClip(clip, parts) as it is. Only the picture, the
// tracks and the sound need the real source frame (cutToSource).
import { freezeStart } from "./timeline.js";
import { newId } from "./document.js";

export const MAX_PARTS = 200;
const EPS = 1e-6;
const round3 = (value) => Math.round(value * 1000) / 1000;

export const spansOf = (parts, frames) => (parts?.length ? parts.map((part) => [part.from, part.to]) : [[0, frames]]);
export const cutFrames = (parts, frames) => spansOf(parts, frames).reduce((sum, [from, to]) => sum + to - from, 0);

/** The clip as the timeline sees it: the cut clip's frame count and length. */
export const cutClip = (clip, parts) => {
  if (!parts?.length) return clip;
  const frames = cutFrames(parts, clip.frames);
  return { ...clip, frames, duration: frames / clip.fps };
};

/** The source frame that cut frame `frame` shows. */
export const cutToSource = (frame, parts, frames) => {
  if (!parts?.length) return Math.min(frames - 1, Math.max(0, frame));
  let remaining = Math.max(0, frame);
  for (const [from, to] of spansOf(parts, frames)) {
    if (remaining < to - from) return from + remaining;
    remaining -= to - from;
  }
  return parts[parts.length - 1].to - 1;
};

/** Every cut frame that plays source frame `frame` (a repeated part plays it more than once). */
export const sourceToCut = (frame, parts, frames) => {
  const found = [];
  let offset = 0;
  for (const [from, to] of spansOf(parts, frames)) {
    if (frame >= from && frame < to) found.push(offset + frame - from);
    offset += to - from;
  }
  return found;
};

/** Each part with where it sits: cut frames and output time (a freeze belongs to the part it starts in). */
export const partSpans = (doc, clip) => {
  const cut = cutClip(clip, doc.parts);
  let offset = 0;
  return spansOf(doc.parts, clip.frames).map(([from, to], index) => {
    const span = { index, from, to, cutStart: offset, cutLength: to - from,
      outStart: freezeStart(offset, cut, doc.freezes), outEnd: freezeStart(offset + to - from, cut, doc.freezes) };
    offset += to - from;
    return span;
  });
};

/** The part holding cut frame `frame`, with the frame's offset inside it. */
export const partAt = (doc, clip, frame) => {
  const spans = partSpans(doc, clip);
  const found = spans.find((span) => frame >= span.cutStart && frame < span.cutStart + span.cutLength) || spans[spans.length - 1];
  return { ...found, offset: frame - found.cutStart };
};

const specOf = (doc, clip) => spansOf(doc.parts, clip.frames).map(([from, to], origin) => ({ from, to, origin }));

/**
 * The document with its parts set to `spec` ([{from, to, origin, copy?}]: `origin` is the old part a new
 * one came from; a `copy` is a repeat of it). Freezes and boards move with the frames they sit on and go
 * when those frames do (a board takes its tokens); every drawing's times move the same way. A copy takes the
 * old part's plain drawings with it, not its freezes or boards.
 */
export const reshape = (doc, clip, spec) => {
  const oldSpans = partSpans(doc, clip);
  const oldClip = cutClip(clip, doc.parts);
  const newParts = spec.map(({ from, to }) => ({ from, to }));
  const identity = newParts.length === 1 && newParts[0].from === 0 && newParts[0].to === clip.frames;
  const newClip = cutClip(clip, identity ? null : newParts);
  let offset = 0;
  const starts = spec.map((entry) => { const start = offset; offset += entry.to - entry.from; return start; });

  // Where the old frames that survive land: {oldStart, newStart, length} in cut frames, in old order.
  const pieces = [];
  spec.forEach((entry, k) => {
    if (entry.copy) return;
    const old = oldSpans[entry.origin];
    const first = Math.max(old.from, entry.from);
    const last = Math.min(old.to, entry.to);
    if (last > first) pieces.push({ oldStart: old.cutStart + first - old.from, newStart: starts[k] + first - entry.from, length: last - first });
  });
  pieces.sort((a, b) => a.oldStart - b.oldStart);
  const pieceOf = (frame) => pieces.find((piece) => frame >= piece.oldStart && frame < piece.oldStart + piece.length);

  const freezes = [];
  const gone = new Set();
  (doc.freezes || []).forEach((freeze) => {
    const piece = pieceOf(freeze.atFrame);
    if (piece) freezes.push({ ...freeze, atFrame: freeze.atFrame - piece.oldStart + piece.newStart });
    else gone.add(freeze.atFrame);
  });
  freezes.sort((a, b) => a.atFrame - b.atFrame);
  const moved = new Map((doc.freezes || []).filter((f) => pieceOf(f.atFrame)).map((f) => { const piece = pieceOf(f.atFrame); return [f.atFrame, f.atFrame - piece.oldStart + piece.newStart]; }));

  const spans = pieces.map((piece) => ({
    oldStart: freezeStart(piece.oldStart, oldClip, doc.freezes),
    oldEnd: freezeStart(piece.oldStart + piece.length, oldClip, doc.freezes),
    newStart: freezeStart(piece.newStart, newClip, freezes),
  }));
  const total = newClip.duration + freezes.reduce((sum, f) => sum + f.seconds, 0);
  const clamp = (t) => round3(Math.min(total, Math.max(0, t)));
  // The new time of an old time: the start of a drawing sits in the piece that plays then; its end in the
  // piece that has just played. Time in a gap (deleted frames) falls to the edge of the piece after / before it.
  const mapStart = (t) => {
    const hit = spans.find((s) => t >= s.oldStart - EPS && t < s.oldEnd - EPS);
    if (hit) return hit.newStart + (t - hit.oldStart);
    const after = spans.find((s) => s.oldStart >= t - EPS);
    return after ? after.newStart : total;
  };
  const mapEnd = (t) => {
    const hit = spans.find((s) => t > s.oldStart + EPS && t <= s.oldEnd + EPS);
    if (hit) return hit.newStart + (t - hit.oldStart);
    const before = [...spans].reverse().find((s) => s.oldEnd <= t + EPS);
    return before ? before.newStart + (before.oldEnd - before.oldStart) : 0;
  };

  const items = [];
  doc.items.forEach((item) => {
    if (item.on !== undefined) {
      if (gone.has(item.on)) return; // its board went
      const on = moved.get(item.on);
      if (on === undefined) return;
      items.push({ ...item, on, show: { ...item.show, from: clamp(mapStart(item.show.from)), to: clamp(mapEnd(item.show.to)) } });
      return;
    }
    let from = mapStart(item.show.from);
    let to = mapEnd(item.show.to);
    if (item.show.to - item.show.from > EPS && to - from < 0.04 - EPS && from <= to) return; // only deleted time was shown
    if (from > to) [from, to] = [to, from]; // it spanned parts that were reordered: cover both
    items.push({ ...item, show: { ...item.show, from: clamp(from), to: clamp(to) } });
  });

  spec.forEach((entry, k) => {
    if (!entry.copy) return;
    const old = oldSpans[entry.origin];
    const start = freezeStart(starts[k], newClip, freezes);
    const end = freezeStart(starts[k] + entry.to - entry.from, newClip, freezes);
    doc.items.forEach((item) => {
      if (item.on !== undefined || item.show.from < old.outStart - EPS || item.show.to > old.outEnd + EPS) return;
      const from = start + (item.show.from - old.outStart);
      const to = Math.min(end, start + (item.show.to - old.outStart));
      if (to - from < 0.04 - EPS) return;
      items.push({ ...JSON.parse(JSON.stringify(item)), id: newId(), show: { ...item.show, from: clamp(from), to: clamp(to) } });
    });
  });

  const next = { ...doc, freezes, items };
  if (identity) delete next.parts;
  else next.parts = newParts;
  return next;
};

/** Cut the part at cut frame `frame` into two (the playhead). Null when it is on a part's first frame. */
export const splitAt = (doc, clip, frame) => {
  const part = partAt(doc, clip, frame);
  if (part.offset <= 0 || part.offset >= part.cutLength || spansOf(doc.parts, clip.frames).length >= MAX_PARTS) return null;
  const cutAt = part.from + part.offset;
  const spec = [];
  specOf(doc, clip).forEach((entry) => {
    if (entry.origin === part.index) spec.push({ ...entry, to: cutAt }, { ...entry, from: cutAt });
    else spec.push(entry);
  });
  return reshape(doc, clip, spec);
};

/** Remove part `index`; the rest closes up. Null for the last part. */
export const deletePart = (doc, clip, index) => {
  const spec = specOf(doc, clip);
  if (spec.length < 2 || !spec[index]) return null;
  return reshape(doc, clip, spec.filter((_, i) => i !== index));
};

/** Move part `index` so it is at position `target` (0 = first). */
export const movePart = (doc, clip, index, target) => {
  const spec = specOf(doc, clip);
  if (!spec[index] || target < 0 || target >= spec.length || target === index) return null;
  const [entry] = spec.splice(index, 1);
  spec.splice(target, 0, entry);
  return reshape(doc, clip, spec);
};

/** Repeat part `index` right after itself. */
export const duplicatePart = (doc, clip, index) => {
  const spec = specOf(doc, clip);
  if (!spec[index] || spec.length >= MAX_PARTS) return null;
  spec.splice(index + 1, 0, { ...spec[index], copy: true });
  return reshape(doc, clip, spec);
};

/** Trim one end of part `index` so it starts or ends on source frame `frame`. Null when nothing changes or it would be empty. */
export const trimPart = (doc, clip, index, edge, frame) => {
  const spec = specOf(doc, clip);
  const entry = spec[index];
  if (!entry) return null;
  const next = { ...entry, [edge]: Math.round(frame) };
  if (next.from < 0 || next.to > clip.frames || next.to - next.from < 1 || (next.from === entry.from && next.to === entry.to)) return null;
  spec[index] = next;
  return reshape(doc, clip, spec);
};
