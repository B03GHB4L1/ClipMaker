// Output time with freezes, and animation progress. The same rules as
// app/telestration/timeline.py; tests/fixtures/timeline_cases.json checks both.
// clip = {fps, duration, frames}; freezes = [{atFrame, seconds}].

export const PULSE_SECONDS = 1.2;
export const SLIDE_DISTANCE = 0.04;
export const DEFAULT_ANIM_SECONDS = 0.5;
const EPS = 1e-6;

export const EASES = {
  linear: (p) => p,
  "ease-out": (p) => 1 - (1 - p) ** 3,
  "ease-in-out": (p) => (p < 0.5 ? 4 * p ** 3 : 1 - (-2 * p + 2) ** 3 / 2),
};

const sorted = (freezes) => [...(freezes || [])].sort((a, b) => a.atFrame - b.atFrame);
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

export const totalSeconds = (clip, freezes) => clip.duration + (freezes || []).reduce((sum, f) => sum + f.seconds, 0);

/** Output time where `frame` starts (its freeze, if any, starts here). */
export const freezeStart = (frame, clip, freezes) =>
  frame / clip.fps + (freezes || []).filter((f) => f.atFrame < frame).reduce((sum, f) => sum + f.seconds, 0);

/** Output time where `frame` starts playing, after any freeze on it. */
export const playStart = (frame, clip, freezes) =>
  frame / clip.fps + (freezes || []).filter((f) => f.atFrame <= frame).reduce((sum, f) => sum + f.seconds, 0);

/** The source frame shown at output time `t`, and the freeze holding it ({frame, time, freeze, freezeStart}). */
export const outputToSource = (t, clip, freezes) => {
  let held = 0;
  for (const freeze of sorted(freezes)) {
    const start = freeze.atFrame / clip.fps + held;
    if (t < start) break;
    if (t < start + freeze.seconds) return { time: freeze.atFrame / clip.fps, frame: freeze.atFrame, freeze: freeze.atFrame, freezeStart: start };
    held += freeze.seconds;
  }
  const time = clamp(t - held, 0, clip.duration);
  return { time, frame: clamp(Math.floor(time * clip.fps + EPS), 0, clip.frames - 1), freeze: null, freezeStart: null };
};

/** Every place the frame steppers stop: each frame's start, and each freeze's start and end. Sorted. */
export const stops = (clip, freezes) => {
  const byFrame = new Map((freezes || []).map((f) => [f.atFrame, f.seconds]));
  const result = [];
  let held = 0;
  for (let frame = 0; frame < clip.frames; frame += 1) {
    const start = frame / clip.fps + held;
    if (byFrame.has(frame)) {
      result.push(start);
      held += byFrame.get(frame);
    }
    result.push(frame / clip.fps + held);
  }
  return result;
};

/** How a drawing looks at output time `t`, or null when hidden. See timeline.py animation(). */
export const animation = (item, t) => {
  const show = item.show;
  if (t < show.from - 1e-3 || t > show.to + 1e-3) return null;
  const seconds = show.animSeconds ?? DEFAULT_ANIM_SECONDS;
  const ease = EASES[show.ease || "ease-out"];
  const progress = (span) => (seconds > 0 ? ease(clamp(span / seconds, 0, 1)) : 1);
  const state = { alpha: 1, draw: 1, scale: 1, offsetY: 0, pulse: null };
  const coming = progress(t - show.from);
  switch (show.animate || "none") {
    case "fade": state.alpha *= coming; break;
    case "draw":
      if (["arrow", "line", "freehand", "zone", "ring"].includes(item.kind)) state.draw = coming;
      else state.alpha *= coming;
      break;
    case "grow": state.scale = coming; break;
    case "slide": state.offsetY = (1 - coming) * SLIDE_DISTANCE; state.alpha *= coming; break;
    default: break;
  }
  if ((show.animateOut || "none") === "fade") state.alpha *= progress(show.to - t);
  if (show.pulse) state.pulse = ((((t - show.from) % PULSE_SECONDS) + PULSE_SECONDS) % PULSE_SECONDS) / PULSE_SECONDS;
  return state;
};

// ---------------------------------------------------------------------------
// Changing freezes. Drawing times are output seconds, so a freeze change moves
// every time after it; drawings stay on the same picture.
// ---------------------------------------------------------------------------
const retime = (value, items, map, total) => items.map((item) => ({
  ...item,
  show: { ...item.show, from: Math.round(clamp(map(item.show.from), 0, total) * 1000) / 1000, to: Math.round(clamp(map(item.show.to), 0, total) * 1000) / 1000 },
}));

/** The document with the freeze on `frame` set to `seconds` (0 removes it). */
export const setFreeze = (doc, clip, frame, seconds) => {
  const freezes = doc.freezes || [];
  const old = freezes.find((f) => f.atFrame === frame)?.seconds || 0;
  const next = Math.round(seconds * 1000) / 1000;
  if (old === next) return doc;
  const start = freezeStart(frame, clip, freezes);
  const delta = next - old;
  const map = (t) => {
    if (t >= start + old - EPS && (old > 0 || t > start + EPS)) return t + delta; // after the freeze
    if (t > start + next) return start + next; // inside a freeze that shrank
    return t;
  };
  const kept = freezes.find((f) => f.atFrame === frame) || {}; // a board keeps its background
  const nextFreezes = sorted([...freezes.filter((f) => f.atFrame !== frame), ...(next > 0 ? [{ ...kept, atFrame: frame, seconds: next }] : [])]);
  return { ...doc, freezes: nextFreezes, items: retime(doc, doc.items, map, totalSeconds(clip, nextFreezes)) };
};
