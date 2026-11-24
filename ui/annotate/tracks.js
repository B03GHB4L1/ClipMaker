// Followed players (docs/TELESTRATION_PLAN.md, M3). Pure functions.
//
// A track: {id, label?, keyframes: {"<frame>": [footX, footY, w, h]}, from, boxes: [row | null]}
// where a row is [footX, footY, w, h, confidence, state] for frame `from + index`
// (states: 0 tracked, 1 keyframe, 2 review, 3 lost; see app/telestration/segments.py).
// A drawing point is fixed [x, y] or linked {track, dx, dy}: an offset from the player's feet.

export const TRACKED = 0;
export const KEYFRAME = 1;
export const REVIEW = 2;
export const LOST = 3;

const round = (value) => Math.round(value * 1e5) / 1e5;
let counter = 0;
export const newTrackId = () => `t${Date.now().toString(36)}${(counter++).toString(36)}`;

export const isLinked = (point) => !Array.isArray(point);
export const linkedTracks = (item) => new Set(item.points.filter(isLinked).map((point) => point.track));

/** A track's own box on `frame`: {box, state} from a keyframe or a usable row, else null. */
export const ownBox = (track, frame) => {
  const key = track.keyframes[String(frame)];
  if (key) return { box: key, state: KEYFRAME };
  const row = track.boxes[frame - track.from];
  if (row && row[5] !== LOST) return { box: row.slice(0, 4), state: row[5] };
  return null;
};

/** Where the player is on `frame`: {box, state, held}. Gaps hold the nearest earlier position (else the next one). */
export const boxAt = (track, frame) => {
  const own = ownBox(track, frame);
  if (own) return { ...own, held: false };
  const known = [...Object.keys(track.keyframes).map(Number),
    ...track.boxes.map((row, index) => (row && row[5] !== LOST ? track.from + index : null)).filter((f) => f !== null)];
  if (!known.length) return null;
  const earlier = known.filter((f) => f < frame);
  const nearest = earlier.length ? Math.max(...earlier) : Math.min(...known);
  return { ...ownBox(track, nearest), held: true };
};

const trackMap = (tracks) => (tracks instanceof Map ? tracks : new Map((tracks || []).map((track) => [track.id, track])));

/** A point's position on `frame`, as [x, y] fractions. */
export const resolvePoint = (point, tracks, frame) => {
  if (!isLinked(point)) return point;
  const track = trackMap(tracks).get(point.track);
  const at = track && boxAt(track, frame);
  return at ? [at.box[0] + point.dx, at.box[1] + point.dy] : [0.5 + point.dx, 0.5 + point.dy];
};

/** The item with every linked point placed for `frame` (the same item when nothing is linked). */
export const resolveItem = (item, tracks, frame) => {
  if (!item.points.some(isLinked)) return item;
  const map = trackMap(tracks);
  return { ...item, points: item.points.map((point) => resolvePoint(point, map, frame)) };
};

/** The link from a fixed point to a player's feet on `frame`. */
export const linkTo = (track, point, frame) => {
  const at = boxAt(track, frame);
  return { track: track.id, dx: round(point[0] - at.box[0]), dy: round(point[1] - at.box[1]) };
};

export const newTrack = (frame, box, label = "") => ({
  id: newTrackId(), ...(label ? { label } : {}), keyframes: { [String(frame)]: box.map(round) }, from: frame, boxes: [],
});

/** The track with the analyst's box on `frame` (keyframes always win over tracking). */
export const setKeyframe = (track, frame, box) => ({ ...track, keyframes: { ...track.keyframes, [String(frame)]: box.map(round) } });

/** The last frame tracking from `start` should cover: just before the next keyframe, or `limit`. */
export const spanEnd = (track, start, limit) => {
  const later = Object.keys(track.keyframes).map(Number).filter((frame) => frame > start);
  return later.length ? Math.min(limit, Math.min(...later) - 1) : limit;
};

/** The last frame the track says anything about. */
export const lastFrame = (track) => Math.max(...Object.keys(track.keyframes).map(Number), track.from + track.boxes.length - 1);

/** The track with frames start..end replaced by a tracking result (rows from `start`; rows may stop early). */
export const mergeRows = (track, start, end, rows) => {
  const from = Math.min(track.from, start);
  const last = Math.max(track.from + track.boxes.length - 1, end);
  const boxes = Array.from({ length: last - from + 1 }, (_, index) => track.boxes[from + index - track.from] ?? null);
  for (let frame = start; frame <= end; frame += 1) boxes[frame - from] = rows[frame - start] ?? null;
  // Drop empty frames at either end so the stored list stays short.
  let head = 0;
  while (head < boxes.length && boxes[head] === null) head += 1;
  let tail = boxes.length;
  while (tail > head && boxes[tail - 1] === null) tail -= 1;
  return { ...track, from: head < tail ? from + head : Math.min(...Object.keys(track.keyframes).map(Number)), boxes: boxes.slice(head, tail) };
};

/** Frames needing the analyst's eye, as [first, last] runs: state 2 (review) or 3 (lost). */
export const flaggedRuns = (track, state) => {
  const runs = [];
  track.boxes.forEach((row, index) => {
    if (!row || row[5] !== state || track.keyframes[String(track.from + index)]) return;
    const frame = track.from + index;
    const last = runs[runs.length - 1];
    if (last && last[1] === frame - 1) last[1] = frame;
    else runs.push([frame, frame]);
  });
  return runs;
};

/** The document without tracks no drawing uses any more. */
export const pruneTracks = (doc) => {
  const used = new Set(doc.items.flatMap((item) => [...linkedTracks(item)]));
  const tracks = (doc.tracks || []).filter((track) => used.has(track.id));
  const next = { ...doc, tracks };
  if (!tracks.length) delete next.tracks;
  return next;
};
