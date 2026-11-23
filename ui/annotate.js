// The analyst editor: draw on a clip copied into the project
// (docs/TELESTRATION_PLAN.md, M1). Drawings are fixed in place for now;
// tracking (M3) will link their points to players.
import { projectRequest, newProject, rememberProject } from "./projects.js";
import { saveImage, showSaved, showSaveError } from "./save-clip.js";
import { changedTiles, cropDrawn, drawItem, drawItems, handlesFor, itemAt, styleOf, textBox, textFont, visibleAt, DEFAULT_STYLE, PATTERNS, SHAPES } from "./annotate/shapes.js";
import { createDocument, dragHandle, moveItem, newItem, ringGeometry, simplify, clampPoint } from "./annotate/document.js";
import { animation, freezeStart, outputToSource, playStart, setFreeze, stops, totalSeconds } from "./annotate/timeline.js";
import { MAX_PARTS, cutClip, cutToSource, deletePart, duplicatePart, movePart, partAt, partSpans, sourceToCut, spansOf, splitAt, trimPart } from "./annotate/parts.js";
import { DEFAULT_TEAM_COLOURS, TEAMS, THEMES, BOARD_SECONDS, addBoard, boardAt, boardFrame, changeBoard, changeBoardView, drawBoard,
  itemsAt, newToken, removeInsert, textOn, tokensFromPlayers, placedAt, setMove, clearMoves, moveBoard, playersOnPitch } from "./annotate/board.js";
import { LANDMARKS, LINES, VIEWS, calibrate, landmark, projectedLines } from "./annotate/pitch.js";
import { isFlat, PITCH_KINDS, placeFlat, projectItems } from "./annotate/flat.js";
import { clipPitchTrack, keyAt, pitchKeys, withCamera, withKey, withoutKey } from "./annotate/camera.js";
import { fitBox } from "./annotate/fit.js";
import { showClipStrip, showLibrary } from "./annotate/library.js";
import { REVIEW, LOST, boxAt, flaggedRuns, isLinked, lastFrame, linkTo, linkedTracks, mergeRows, newTrack, pruneTracks,
  resolveItem, resolvePoint, setKeyframe, spanEnd } from "./annotate/tracks.js";

const $ = (selector) => document.querySelector(selector);
const params = new URLSearchParams(location.search);
const projectId = params.get("project") || sessionStorage.getItem("clipmaker.active-match") || "";
const clipId = params.get("clip") || "";

const video = $("[data-video]");
const canvas = $("[data-canvas]");
const stage = $("[data-stage]");
const ctx = canvas.getContext("2d");
const textInput = $("[data-text-input]");
const status = $("[data-annotate-status]");
const saveStatus = $("[data-save-status]");

let clip;
let timing; // the clip as the timeline sees it: its parts joined (annotate/parts.js)
let doc;
let selectedPart = null; // a part chosen on the Parts lane
let tool = "select";
let selectedId = null;
let selectedIds = []; // several drawings chosen at once (a drag round them, or Shift+click); empty otherwise
let selectedFreeze = null; // a freeze or board chosen on the Freezes lane (its frame)
let gesture = null; // the drag or drawing in progress
let zoneDraft = null; // corners of a zone being drawn
let pointer = null; // last pointer position in fractions, for the zone preview
let textEdit = null; // {id | null, point}
let tokenTeam = "home"; // the team new tokens join
let calib = null; // board from this frame, while the analyst marks the pitch: see "Board from this frame"
const toolStyle = Object.fromEntries(Object.entries(DEFAULT_STYLE).map(([kind, style]) => [kind, { ...style }]));

// ---------------------------------------------------------------------------
// Header: menu, workflow links, back link
// ---------------------------------------------------------------------------
const menu = $("#analysis-menu");
const menuButton = $("[data-analysis-menu]");
const setMenu = (open) => {
  if (!open && menu.contains(document.activeElement)) menuButton.focus();
  menu.hidden = !open;
  menuButton.setAttribute("aria-expanded", String(open));
  if (open) menu.querySelector("button")?.focus();
};
menuButton.onclick = () => setMenu(menu.hidden);
document.addEventListener("click", (event) => { if (!event.target.closest("#analysis-menu, [data-analysis-menu]")) setMenu(false); });
$("[data-new-project]").onclick = async () => {
  try { const project = await newProject(); location.href = `/?project=${project.id}`; } catch (error) { status.textContent = error.message; }
};
document.querySelectorAll(".filter-topbar nav a").forEach((link) => {
  const url = new URL(link.href, location.origin);
  url.searchParams.set("project", projectId);
  link.href = url.pathname + url.search;
});
{
  const back = $("[data-annotate-back]");
  const from = document.referrer ? new URL(document.referrer) : null;
  const library = `/annotate.html?project=${encodeURIComponent(projectId)}`;
  if (from && from.origin === location.origin && !from.pathname.endsWith("/annotate.html")) back.href = from.pathname + from.search;
  else if (clipId) {
    // Arrived from the session list or another clip of the session: go back to the list.
    back.href = library;
    $("[data-back-label]").textContent = "All sessions";
  } else back.href = `/analysis.html?view=analyst&project=${encodeURIComponent(projectId)}`;
}

// ---------------------------------------------------------------------------
// Time. The playhead is in output time: source frames with freezes inserted
// (annotate/timeline.js). During a freeze the video waits, silent, on the
// frozen frame while the drawings keep animating.
// ---------------------------------------------------------------------------
const fps = () => clip.fps;
let outTime = 0;
let playing = false;
let run = null; // while playing: {held, next, freeze: {start, end, wall} | null}
const currentTime = () => outTime;
const total = () => totalSeconds(timing, doc.freezes);
// `source()` is a place on the cut clip (its frames are what freezes and boards sit on); the picture, tracks and
// sound need the real source frame (annotate/parts.js).
const source = () => outputToSource(outTime, timing, doc.freezes);
const refreshTiming = () => { timing = cutClip(clip, doc.value.parts); };
const realFrame = (cut) => cutToSource(cut, doc.value.parts, clip.frames);
const sourceSeconds = (at) => (realFrame(at.frame) + (at.time * fps() - at.frame)) / fps(); // the moment `at` shows in the source
const formatTime = (seconds) => {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(2).padStart(5, "0")}`;
};
const clampTime = (t) => Math.min(total(), Math.max(0, t));
// Show the frame for output time `outTime`: the middle of that frame, so the decoder shows it and not its neighbour.
const showFrame = () => {
  const frame = realFrame(source().frame);
  const target = Math.min(clip.duration, (frame + 0.5) / fps());
  if (Math.abs(video.currentTime - target) > 0.25 / fps()) video.currentTime = target;
};
const pause = () => {
  playing = false;
  run = null;
  video.pause();
  scheduleRender();
};
const seekOutput = (t) => {
  pause();
  outTime = clampTime(t);
  showFrame();
  scheduleRender();
};
// One stop = the start of a frame, or the start or end of a freeze.
const step = (direction, big = false) => {
  if (big) return seekOutput(outTime + direction);
  const list = stops(timing, doc.freezes);
  const target = direction > 0 ? list.find((t) => t > outTime + 1e-6) : [...list].reverse().find((t) => t < outTime - 1e-6);
  seekOutput(target ?? (direction > 0 ? list[list.length - 1] : 0));
};

const sortedFreezes = () => [...doc.freezes].sort((a, b) => a.atFrame - b.atFrame);
// Each part as {from, to, cutStart}: source frames it plays, and the cut frame it starts at.
const playParts = () => {
  let offset = 0;
  return spansOf(doc.value.parts, clip.frames).map(([from, to]) => { const part = { from, to, cutStart: offset }; offset += to - from; return part; });
};
const cutSeconds = (videoSeconds, part) => (part.cutStart + videoSeconds * fps() - part.from) / fps(); // cut-clip seconds for a video time inside `part`
const play = () => {
  if (outTime >= total() - 1e-3) outTime = 0;
  const at = source();
  const freezes = sortedFreezes();
  const parts = playParts();
  const part = partAt(doc.value, clip, at.frame).index;
  if (at.freeze !== null) {
    const index = freezes.findIndex((f) => f.atFrame === at.freeze);
    run = { held: freezes.slice(0, index).reduce((sum, f) => sum + f.seconds, 0), next: index, part, parts,
      freeze: { start: outTime, end: at.freezeStart + freezes[index].seconds, wall: performance.now() } };
    video.pause();
    showFrame();
  } else {
    const index = freezes.findIndex((f) => f.atFrame > at.frame);
    const next = index < 0 ? freezes.length : index;
    run = { held: freezes.slice(0, next).reduce((sum, f) => sum + f.seconds, 0), next, part, parts, freeze: null };
    video.currentTime = sourceSeconds(at);
    video.play().catch(() => pause());
  }
  playing = true;
  requestAnimationFrame(tick);
};
const togglePlay = () => (playing ? pause() : play());
// A hidden window gets no animation frames, so the clock could not hold a
// freeze while the video ran on; stop instead.
document.addEventListener("visibilitychange", () => { if (document.hidden && playing) pause(); });

function tick(now) {
  if (!playing || !run) return;
  const freezes = sortedFreezes();
  if (run.freeze) {
    outTime = run.freeze.start + (now - run.freeze.wall) / 1000;
    if (outTime >= run.freeze.end) {
      outTime = run.freeze.end;
      run.held += freezes[run.next].seconds;
      run.next += 1;
      run.freeze = null;
      video.play().catch(() => pause());
    }
  } else {
    const next = freezes[run.next];
    const here = run.parts[run.part];
    const cutTime = cutSeconds(video.currentTime, here);
    if (next && cutTime >= next.atFrame / fps() - 1e-4) {
      video.pause();
      outTime = freezeStart(next.atFrame, timing, freezes);
      run.freeze = { start: outTime, end: outTime + next.seconds, wall: now };
      video.currentTime = (realFrame(next.atFrame) + 0.5) / fps();
    } else if (video.ended || video.currentTime >= (here.to - 0.5) / fps()) {
      // This part is over: carry on into the next one (a seek when it does not follow on in the source), or stop.
      const following = run.parts[run.part + 1];
      if (!following) {
        outTime = total();
        pause();
      } else {
        run.part += 1;
        if (following.from !== here.to) video.currentTime = (following.from + 0.1) / fps();
        outTime = Math.min(total(), following.cutStart / fps() + run.held);
      }
    } else {
      outTime = Math.min(total(), cutTime + run.held);
    }
  }
  render();
  showTime();
  if (playing) requestAnimationFrame(tick);
}

const showTime = () => {
  const at = source();
  const frozen = at.freeze !== null ? ` · <span class="is-frozen">${boardNow() ? "board" : "frozen"}</span>` : "";
  $("[data-time]").innerHTML = `${formatTime(outTime)} / ${formatTime(total())} · frame ${at.frame + 1}/${timing.frames}${doc.value.parts?.length > 1 ? ` · part ${partAt(doc.value, clip, at.frame).index + 1}/${doc.value.parts.length}` : ""}${frozen}`;
  const scrub = $("[data-scrub]");
  scrub.max = String(total());
  if (document.activeElement !== scrub) scrub.value = String(outTime);
  $("[data-play]").classList.toggle("is-playing", playing);
  $("[data-play]").setAttribute("aria-label", playing ? "Pause" : "Play");
  $("[data-lane-head]").style.left = `${(outTime / total()) * 100}%`;
  $("[data-drawing-head]").style.left = `${(outTime / total()) * 100}%`;
  document.querySelectorAll("[data-players] [data-head]").forEach((head) => { head.style.left = `${(outTime / total()) * 100}%`; });
  document.querySelectorAll("[data-lane-freeze]").forEach((block) => block.classList.toggle("is-current", Number(block.dataset.laneFreeze) === at.freeze));
};

// ---------------------------------------------------------------------------
// Drawing the overlay
// ---------------------------------------------------------------------------
const size = () => ({ w: canvas.width, h: canvas.height });
const measure = (line, font) => { ctx.font = font; return ctx.measureText(line).width; };
const toFraction = (event) => {
  const rect = canvas.getBoundingClientRect();
  return [(event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height];
};
const toPixels = ([x, y]) => [x * canvas.width, y * canvas.height];
const handleRadius = () => 7 * (window.devicePixelRatio || 1);

const draftItem = () => (gesture?.draft ? gesture.draft : null);
// Linked points follow their player: drawings are placed for the frame on screen.
const tracks = () => doc.value.tracks || [];
const trackById = (id) => tracks().find((track) => track.id === id) || null;
const frameNow = () => realFrame(source().frame); // the source frame on screen: tracks and the picture use it
const cutFrameNow = () => source().frame; // its place on the cut clip: freezes and boards sit there
const boardNow = () => (clip ? boardAt(doc.value, timing, outTime) : null);
// On a board only its own drawings show; elsewhere the clip's drawings (annotate/board.js).
// Moving board tokens are placed for the moment on screen (M8).
// Flat drawings keep their place on the pitch as the camera moves (P2, annotate/camera.js).
const placeNow = (item) => withPitch(placeFlat(resolveItem(placedAt(doc.value, timing, item, outTime), tracks(), frameNow()), clipTrack(), frameNow()));
// An offside line's or measure's place on the grass on this frame, so it can be hit-tested and outlined as drawn.
const withPitch = (item) => (PITCH_KINDS.has(item.kind) && !item.offPitch ? projectItems([item], pitchHere()?.calibration || null)[0] : item);
const shown = () => itemsAt(doc.value, timing, outTime).map(placeNow).filter((item) => !item.offPitch);
const shownItem = (id) => { const item = doc.find(id); const placed = item && placeNow(item); return placed && !placed.offPitch ? placed : null; };
// Seconds into the board that drawing `item` is on, at the playhead.
const boardSeconds = (item) => outTime - freezeStart(item.on, timing, doc.freezes);
const playerName = (track) => track.label || `Player ${tracks().indexOf(track) + 1}`;

const boxPixels = ([fx, fy, w, h]) => [(fx - w / 2) * canvas.width, (fy - h) * canvas.height, w * canvas.width, h * canvas.height];
// The corners of a player box [footX, footY, w, h] (fractions), named by compass point.
const boxCorners = ([fx, fy, w, h]) => [[fx - w / 2, fy - h, "nw"], [fx + w / 2, fy - h, "ne"], [fx - w / 2, fy, "sw"], [fx + w / 2, fy, "se"]];
const drawPlayerBox = (track) => {
  const at = boxAt(track, frameNow());
  if (!at) return;
  const resizing = gesture?.type === "resize" && gesture.trackId === track.id;
  const box = resizing ? gesture.box : at.box;
  const [x, y, w, h] = boxPixels(box);
  ctx.save();
  ctx.setLineDash([5, 4]);
  ctx.lineWidth = 1.5 * (window.devicePixelRatio || 1);
  ctx.strokeStyle = at.held || at.state === REVIEW ? "#e8a317" : at.state === 1 || resizing ? "#c8f135" : "rgba(255, 255, 255, 0.7)";
  ctx.strokeRect(x, y, w, h);
  // Corner handles: drag one to fit the box to the player (a tight box tracks better).
  ctx.setLineDash([]);
  ctx.restore();
  boxCorners(box).forEach(([cx, cy]) => drawSquareHandle([cx, cy]));
};
// Where a point dropped near a followed player's feet links to them.
const snapPoint = (point) => {
  if (boardNow()) return point; // a board has no players to follow
  const [x, y] = toPixels(point);
  for (const track of tracks()) {
    const at = boxAt(track, frameNow());
    if (!at) continue;
    const [fx, fy] = toPixels(at.box);
    if (Math.hypot(fx - x, fy - y) <= handleRadius() * 2.2) return { track: track.id, dx: 0, dy: 0 };
  }
  return point;
};

// Text placed or dropped with the pointer on a followed player (inside their box, or on their feet) follows them,
// keeping its place beside them: the link to `point` from that player on this frame, or null.
const linkToPlayerAt = (point, pointerAt = point) => {
  if (boardNow() || !pointerAt) return null;
  const [x, y] = toPixels(pointerAt);
  const margin = handleRadius() * 1.5;
  for (const track of [...tracks()].reverse()) {
    const at = boxAt(track, frameNow());
    if (!at) continue;
    const [bx, by, bw, bh] = boxPixels(at.box);
    if (x >= bx - margin && x <= bx + bw + margin && y >= by - margin && y <= by + bh + margin) return linkTo(track, point, frameNow());
  }
  return null;
};

const render = () => {
  if (!clip) return;
  const { w, h } = size();
  ctx.clearRect(0, 0, w, h);
  const time = currentTime();
  const board = boardNow();
  if (board) drawBoard(ctx, w, h, board.background);
  const items = shown().map((item) => (gesture?.previews?.[item.id] || (gesture?.preview && item.id === gesture.preview.id ? gesture.preview : item)));
  const here = board ? null : pitchHere();
  const pitch = here?.calibration || null;
  drawItems(ctx, projectItems(items, pitch), w, h, time);
  if (calib) return drawCalibration();
  if (pitchLines && pitch) drawPitchLines(pitch, here.state === "check");
  const original = doc.find(selectedId);
  if (original && !board) linkedTracks(original).forEach((id) => { const track = trackById(id); if (track) drawPlayerBox(track); });
  if (!board && ["ring", "spotlight", "arrow", "line", "zone", "text"].includes(tool)) {
    // Feet a new drawing can link to.
    tracks().forEach((track) => { const at = boxAt(track, frameNow()); if (at) drawHandle([at.box[0], at.box[1]], true); });
  }
  if (gesture?.type === "box") {
    const [x0, y0] = toPixels(gesture.start);
    const [x1, y1] = toPixels(gesture.end);
    ctx.save();
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 2 * (window.devicePixelRatio || 1);
    ctx.strokeStyle = "#c8f135";
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.restore();
  }
  const draft = draftItem();
  if (draft) drawItem(ctx, projectItems([draft], pitch)[0], w, h);
  if (zoneDraft) {
    const placed = zoneDraft.map((point) => resolvePoint(point, tracks(), frameNow()));
    const points = pointer ? [...placed, pointer] : placed;
    ctx.save();
    ctx.strokeStyle = toolStyle.zone.stroke;
    ctx.lineWidth = 2 * (window.devicePixelRatio || 1);
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    points.forEach((point, index) => { const [x, y] = toPixels(point); index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    ctx.restore();
    placed.forEach((point, index) => drawHandle(point, index === 0));
  }
  const selected = items.find((item) => item.id === selectedId);
  if (selected && !draft) {
    handlesFor(selected).forEach(({ index, point }) => (typeof index === "string" ? drawSquareHandle(point) : drawHandle(point)));
  }
  // Several drawings selected: a thin outline round each.
  if (selectedIds.length > 1) items.filter((item) => selectedIds.includes(item.id)).forEach((item) => outlineBox(itemBounds(item)));
  if (gesture?.type === "marquee") {
    const [x0, y0] = toPixels(gesture.start);
    const [x1, y1] = toPixels(gesture.end);
    ctx.save();
    ctx.fillStyle = "rgba(200, 241, 53, 0.12)";
    ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    ctx.strokeStyle = "#c8f135";
    ctx.lineWidth = window.devicePixelRatio || 1;
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.restore();
  }
};

// The box round a drawing as placed on screen, in pixels: [left, top, right, bottom].
function itemBounds(item) {
  const { w, h } = size();
  if (item.kind === "text") {
    const box = textBox(item, w, h, measure);
    return [box.x, box.y, box.x + box.width, box.y + box.height];
  }
  const points = item.kind === "offside" && item.projected ? [...item.projected.segments.flat(), item.points[0]].map(toPixels) : item.points.map(toPixels);
  if (item.kind === "ring" || item.kind === "spotlight") {
    const [cx, cy] = points[0];
    const rx = item.geometry.rx * w;
    const ry = item.geometry.ry * h;
    return [cx - rx, cy - (item.kind === "spotlight" ? item.geometry.h * h : ry), cx + rx, cy + ry];
  }
  if (item.kind === "token") {
    const r = (styleOf(item).size / 2) * (h / 1080);
    return [points[0][0] - r, points[0][1] - r, points[0][0] + r, points[0][1] + r];
  }
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
function outlineBox([x0, y0, x1, y1]) {
  const pad = 4 * (window.devicePixelRatio || 1);
  ctx.save();
  ctx.strokeStyle = "#c8f135";
  ctx.lineWidth = window.devicePixelRatio || 1;
  ctx.setLineDash([4, 3]);
  ctx.strokeRect(x0 - pad, y0 - pad, x1 - x0 + pad * 2, y1 - y0 + pad * 2);
  ctx.restore();
}

// Handles are drawn small and thin, like a design tool's, so they never hide the picture; the area that
// catches the pointer (handleRadius) stays larger than what is drawn.
function drawHandle(point, strong = false) {
  const ratio = window.devicePixelRatio || 1;
  const [x, y] = toPixels(point);
  ctx.save();
  ctx.beginPath();
  ctx.arc(x, y, (strong ? 3.5 : 3) * ratio, 0, Math.PI * 2);
  ctx.fillStyle = strong ? "#c8f135" : "#ffffff";
  ctx.strokeStyle = "rgba(23, 24, 23, 0.9)";
  ctx.lineWidth = ratio;
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}
// A square handle: a size or a corner (resize), as opposed to a round point handle.
function drawSquareHandle(point) {
  const ratio = window.devicePixelRatio || 1;
  const [x, y] = toPixels(point);
  const half = 3.5 * ratio;
  ctx.save();
  ctx.fillStyle = "#ffffff";
  ctx.strokeStyle = "rgba(23, 24, 23, 0.9)";
  ctx.lineWidth = ratio;
  ctx.fillRect(x - half, y - half, half * 2, half * 2);
  ctx.strokeRect(x - half + ratio / 2, y - half + ratio / 2, half * 2 - ratio, half * 2 - ratio);
  ctx.restore();
}

let frameRequest = 0;
const scheduleRender = () => {
  if (frameRequest) return;
  frameRequest = requestAnimationFrame(() => { frameRequest = 0; render(); showTime(); });
};

const fitCanvas = () => {
  const rect = stage.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  scheduleRender();
};

// ---------------------------------------------------------------------------
// Saving: debounced, whole document, validated by the engine
// ---------------------------------------------------------------------------
let saveTimer = 0;
let saving = Promise.resolve();
let dirty = false;
const setSaveStatus = (text, failed = false) => {
  saveStatus.textContent = text;
  saveStatus.classList.toggle("save-failed", failed);
};
const save = () => {
  clearTimeout(saveTimer);
  if (!dirty) return saving;
  dirty = false;
  const body = { annotations: doc.value };
  setSaveStatus("Saving...");
  saving = saving.then(() => projectRequest(`/api/editor/${encodeURIComponent(projectId)}/${encodeURIComponent(clipId)}`, body))
    .then(() => { if (!dirty) setSaveStatus("Saved locally"); })
    .catch((error) => { dirty = true; setSaveStatus(`Save failed: ${error.message}`, true); });
  return saving;
};
const queueSave = () => {
  dirty = true;
  setSaveStatus("Unsaved changes");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 600);
};
window.addEventListener("beforeunload", (event) => {
  if (!dirty) return;
  // Try once more on the way out, then warn.
  fetch(`/api/editor/${encodeURIComponent(projectId)}/${encodeURIComponent(clipId)}`, {
    method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ annotations: doc.value }),
  }).catch(() => {});
  event.preventDefault();
  event.returnValue = "";
});
// Leaving through a link waits for the save first.
document.addEventListener("click", async (event) => {
  const link = event.target.closest("a[href]");
  if (!link || !dirty) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  await save();
  if (!dirty) location.href = link.href;
}, true);

// ---------------------------------------------------------------------------
// Tools and the inspector
// ---------------------------------------------------------------------------
const HINTS = {
  select: "Click a drawing to edit it, or drag round several to select them all. Shift+click adds one.",
  ring: "Drag from a player's feet outwards to size the ring.",
  spotlight: "Drag from a player's feet outwards; drag the top handle to change the beam.",
  arrow: "Drag from where the arrow starts to where it points.",
  line: "Drag to draw a line.",
  freehand: "Hold and draw.",
  text: "Click where the text goes, type, then press Enter (Shift+Enter for a new line). Click on a followed player to make the text follow them.",
  zone: "Click each corner. Finish with Enter, a double-click or a click on the first corner.",
  shape: "Drag to draw the shape. Hold Shift for equal sides, as a square or a circle.",
  offside: "Click the spot to draw the offside line through, such as a defender's boot. The line lies across the pitch and follows the camera.",
  measure: "Drag from one spot on the grass to another to read the distance between them in metres.",
  follow: "Drag a box around a player, head to boots. It is fitted to them, and a ring follows them; drag it back if it slips.",
  token: "Click to place a player token. On a board it belongs to that board; on the video it is a fixed marker that does not follow anyone.",
};
const FOLLOWABLE = ["ring", "spotlight", "text"];
let followTarget = null; // the drawing "Follow player" will link, or null for a new ring

const setTool = (next) => {
  finishText();
  zoneDraft = null;
  tool = next;
  document.querySelectorAll("button[data-tool]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.tool === tool)));
  $("[data-shape-button]").setAttribute("aria-pressed", String(tool === "shape"));
  canvas.dataset.tool = tool;
  $("[data-hint]").textContent = HINTS[tool];
  $("[data-hint]").title = HINTS[tool];
  if (tool !== "select") { selectedId = null; selectedIds = []; }
  canvas.style.cursor = "";
  renderInspector();
  scheduleRender();
};

const select = (id) => {
  selectedId = id;
  selectedIds = id ? [id] : [];
  if (id) { selectedPart = null; selectedFreeze = null; }
  renderParts();
  renderInspector();
  scheduleRender();
};

const KIND_NAMES = { ring: "Ring", spotlight: "Spotlight", arrow: "Arrow", line: "Line", freehand: "Freehand", text: "Text", zone: "Zone", token: "Token", shape: "Shape", offside: "Offside line", measure: "Measure" };
const itemName = (item) => (item.kind === "text" ? `Text: ${item.text.split("\n")[0].slice(0, 24)}`
  : item.kind === "shape" ? SHAPES[item.geometry?.shape] || "Shape"
  : item.kind === "token" ? ["Token", item.label, item.name].filter(Boolean).join(" ") : KIND_NAMES[item.kind]);
// Some settings read differently on a token.
const KIND_LABELS = { token: { fill: "Colour", color: "Number colour", stroke: "Outline", size: "Size", width: "Outline width" } };
const KIND_RANGES = { token: { size: { min: 16, max: 80 }, width: { min: 0, max: 8 } } };

const FIELDS = {
  stroke: { label: "Line colour", type: "color" },
  fill: { label: "Fill colour", type: "color" },
  pattern: { label: "Fill style", type: "select", options: PATTERNS },
  color: { label: "Text colour", type: "color" },
  background: { label: "Background", type: "color", transparent: true },
  width: { label: "Thickness", type: "range", min: 1, max: 20, step: 1, show: (v) => `${v}` },
  fillOpacity: { label: "Fill strength", type: "range", min: 0, max: 1, step: 0.05, show: (v) => `${Math.round(v * 100)}%` },
  size: { label: "Text size", type: "range", min: 12, max: 120, step: 2, show: (v) => `${v}` },
  dashed: { label: "Dashed", type: "checkbox" },
  flat: { label: "Flat on the pitch", type: "checkbox" },
  bold: { label: "Bold", type: "checkbox" },
};

const updateStyle = (key, value) => {
  const item = doc.find(selectedId);
  if (item && key === "flat") {
    // Laid flat on this frame, or taken off the pitch where it is on screen now.
    const base = value ? item : rebased(item);
    const next = { ...base, style: { ...base.style, flat: value } };
    if (value) next.at = frameNow();
    else delete next.at;
    doc.replace(next);
  } else if (item) {
    doc.replace({ ...item, style: { ...item.style, [key]: value } });
  } else {
    const kind = DEFAULT_STYLE[tool] ? tool : null;
    if (kind) toolStyle[kind][key] = value;
  }
};

// What an offside line or measure reads off the pitch, or what it needs.
const pitchToolNote = (item, kind) => {
  const note = (text) => Object.assign(document.createElement("p"), { className: "annotate-muted", textContent: text });
  if (!pitchKeys(doc.value).length) return note('Mark the pitch first (under "Add at this frame"): this is read from it.');
  const reading = item && shownItem(item.id)?.projected;
  if (!item) return note(kind === "offside" ? "Click the spot to draw the line through." : "Drag between two spots on the grass.");
  if (!reading) return note("This frame has no pitch to read it from. Mark the pitch here, or move to a frame that has it.");
  return note(kind === "measure" ? `${reading.metres.toFixed(1)} m on the pitch.`
    : `${reading.fromLeft.toFixed(1)} m from the left goal line, ${reading.fromRight.toFixed(1)} m from the right.`);
};

const renderInspector = () => {
  const item = selectedId ? doc.find(selectedId) : null;
  const kind = item ? item.kind : DEFAULT_STYLE[tool] ? tool : null; // select and follow have no drawing style
  const fields = $("[data-style-fields]");
  fields.replaceChildren();
  const empty = !doc?.items.length && !doc?.freezes.length && !(doc?.value.parts?.length > 1);
  const many = selectedIds.length > 1;
  const freeze = selectedFreeze !== null ? doc.freezes.find((f) => f.atFrame === selectedFreeze) : null;
  $("[data-inspector-title]").textContent = many ? `${selectedIds.length} drawings selected`
    : freeze ? `${freeze.background ? "Board" : "Freeze"} at frame ${freeze.atFrame + 1}`
      : item ? `${KIND_NAMES[item.kind]} settings` : kind ? `New ${KIND_NAMES[kind].toLowerCase()}` : empty ? "How to start" : "Nothing selected";
  if (many) {
    fields.append(Object.assign(document.createElement("p"), { className: "annotate-muted",
      textContent: "Drag one of them to move them all, or press Delete to remove them. Shift+click adds or removes a drawing; Esc clears the selection." }));
    const remove = Object.assign(document.createElement("button"), { type: "button", className: "annotate-danger", textContent: `Delete ${selectedIds.length} drawings` });
    remove.onclick = removeSelected;
    fields.append(remove);
  } else if (freeze) {
    fields.append(Object.assign(document.createElement("p"), { className: "annotate-muted",
      textContent: freeze.background
        ? "A tactical board, with its own tokens and drawings. Press Delete to remove it with everything on it; Undo brings it back."
        : "The picture holds still here. Drag its right edge on the timeline to change the length, or press Delete to remove it." }));
    const remove = Object.assign(document.createElement("button"), { type: "button", className: "annotate-danger",
      textContent: freeze.background ? "Delete board" : "Delete freeze" });
    remove.onclick = () => removeFreeze(freeze.atFrame);
    fields.append(remove);
  } else if (!kind && empty) {
    // First use: the four steps from a blank clip to an exported video.
    const steps = document.createElement("ol");
    steps.className = "annotate-steps";
    steps.append(...[
      ["Find the moment", "Play, or drag the playhead under the video."],
      ["Cut the clip", "Optional: press X to split at the playhead. Then drag parts to move them, drag their edges to trim, or press Delete to remove one."],
      ["Pick a tool", "Choose one under Draw, Highlight or Mark a player, then drag on the video."],
      ["Adjust it", "Click a drawing to change its look and when it shows."],
      ["Export video", "When you are done. Your work saves as you go."],
    ].map(([title, text]) => {
      const step = document.createElement("li");
      step.append(Object.assign(document.createElement("strong"), { textContent: title }), Object.assign(document.createElement("span"), { textContent: text }));
      return step;
    }));
    fields.append(steps);
  } else if (!kind) {
    fields.append(Object.assign(document.createElement("p"), { className: "annotate-muted", textContent: "Click a drawing on the video or in Drawings below to change it, or pick a tool to add one." }));
  } else {
    const style = item ? styleOf(item) : toolStyle[kind];
    if (kind === "token") fields.append(...tokenFields(item));
    if (kind === "shape") fields.append(shapeField(item));
    let flatNote = null;
    Object.keys(DEFAULT_STYLE[kind]).forEach((key) => {
      if (key === "flat" && PITCH_KINDS.has(kind)) return; // always on the pitch
      if (key === "flat" && !pitchKeys(doc.value).length) {
        // Flat drawings need the clip's pitch first (P1).
        fields.append(Object.assign(document.createElement("p"), { className: "annotate-muted",
          textContent: `Mark the pitch (under "Add at this frame") to lay ${kind === "ring" ? "rings" : "arrows"} flat on the grass.` }));
        return;
      }
      if (key === "flat" && item && style.flat) {
        const flat = projectItems([shownItem(item.id) || item], pitchHere()?.calibration)[0].projected;
        if (flat) {
          flatNote = Object.assign(document.createElement("p"), { className: "annotate-muted", // shown under the checkbox
            textContent: kind === "ring" ? `${(flat.metres * 2).toFixed(1)} m across on the pitch.` : `${flat.metres.toFixed(1)} m long on the pitch.` });
        }
      }
      const spec = { ...FIELDS[key], ...KIND_RANGES[kind]?.[key], ...(KIND_LABELS[kind]?.[key] ? { label: KIND_LABELS[kind][key] } : {}) };
      const label = document.createElement("label");
      label.className = spec.type === "checkbox" ? "annotate-check" : "";
      if (spec.type === "select") {
        const choose = document.createElement("select");
        choose.append(...Object.entries(spec.options).map(([value, text]) => new Option(text, value, false, style[key] === value)));
        choose.onchange = () => updateStyle(key, choose.value);
        label.append(`${spec.label} `, choose);
        fields.append(label);
        return;
      }
      const input = document.createElement("input");
      input.type = spec.type;
      if (spec.type === "checkbox") {
        input.checked = Boolean(style[key]);
        input.onchange = () => updateStyle(key, input.checked);
        label.append(input, ` ${spec.label}`);
      } else if (spec.type === "color") {
        input.value = style[key] || "#171817";
        input.disabled = spec.transparent && style[key] === null;
        input.onchange = () => updateStyle(key, input.value);
        label.append(`${spec.label} `, input);
        if (spec.transparent) {
          const clear = document.createElement("input");
          clear.type = "checkbox";
          clear.checked = style[key] === null;
          clear.onchange = () => updateStyle(key, clear.checked ? null : input.value);
          const wrap = document.createElement("span");
          wrap.className = "annotate-check";
          wrap.append(clear, " None");
          label.append(wrap);
        }
      } else {
        Object.assign(input, { min: spec.min, max: spec.max, step: spec.step, value: style[key] });
        const readout = Object.assign(document.createElement("output"), { textContent: spec.show(Number(input.value)) });
        input.addEventListener("input", () => { readout.textContent = spec.show(Number(input.value)); });
        input.oninput = () => {
          // Live preview while dragging the slider; one undo step on release.
          const current = doc.find(selectedId);
          if (current) {
            gesture = { preview: { ...current, style: { ...current.style, [key]: Number(input.value) } } };
            scheduleRender();
          }
        };
        input.onchange = () => { gesture = null; updateStyle(key, Number(input.value)); };
        const slider = Object.assign(document.createElement("span"), { className: "annotate-slider" });
        slider.append(input, readout);
        label.append(`${spec.label} `, slider);
      }
      fields.append(label);
    });
    if (flatNote) fields.append(flatNote);
    if (PITCH_KINDS.has(kind)) fields.append(pitchToolNote(item, kind));
  }
  renderFollowPanel(many ? null : item);
  const timing = $("[data-timing]");
  timing.hidden = !item || many;
  $("[data-delete]").disabled = !item && !many && !freeze;
  if (item) {
    $("[data-from]").value = item.show.from;
    $("[data-to]").value = item.show.to;
    $("[data-from]").max = $("[data-to]").max = total();
    $("[data-anim-in]").value = item.show.animate || "none";
    $("[data-anim-out]").value = item.show.animateOut || "none";
    $("[data-anim-seconds]").value = item.show.animSeconds ?? 0.5;
    $("[data-ease]").value = item.show.ease || "ease-out";
    const animated = (item.show.animate || "none") !== "none" || (item.show.animateOut || "none") !== "none";
    document.querySelectorAll("[data-anim-detail]").forEach((row) => { row.hidden = !animated; });
    $("[data-pulse-row]").hidden = !["ring", "spotlight", "zone", "shape"].includes(item.kind);
    $("[data-pulse]").checked = Boolean(item.show.pulse);
  }
  renderList();
};

// Which shape a shape drawing is (or the next one drawn).
function shapeField(item) {
  const label = document.createElement("label");
  const choose = document.createElement("select");
  const current = item?.geometry?.shape || shapeKind;
  choose.append(...Object.entries(SHAPES).map(([value, text]) => new Option(text, value, false, value === current)));
  choose.onchange = () => {
    if (item) {
      const latest = doc.find(item.id);
      if (latest) doc.replace({ ...latest, geometry: { shape: choose.value } });
    } else chooseShape(choose.value, false);
  };
  label.append("Shape ", choose);
  return label;
}

// ---------------------------------------------------------------------------
// The Shape tool's menu: opens beside its button (below it on a phone, where the tools are a row)
// ---------------------------------------------------------------------------
let shapeKind = "rect";
const shapeMenu = $("[data-shape-menu]");
const shapeButton = $("[data-shape-button]");
const shapeItems = () => [...shapeMenu.querySelectorAll("[data-shape]")];
function placeShapeMenu() {
  const box = shapeButton.getBoundingClientRect();
  const column = getComputedStyle($("[data-tools]")).flexDirection === "column";
  const width = shapeMenu.offsetWidth;
  const height = shapeMenu.offsetHeight;
  const margin = 8;
  let left = column ? box.right + 6 : box.left;
  let top = column ? box.top : box.bottom + 6;
  left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
  top = Math.max(margin, Math.min(top, window.innerHeight - height - margin));
  shapeMenu.style.left = `${left}px`;
  shapeMenu.style.top = `${top}px`;
}
function openShapeMenu() {
  shapeMenu.hidden = false;
  shapeButton.setAttribute("aria-expanded", "true");
  placeShapeMenu();
  (shapeItems().find((button) => button.dataset.shape === shapeKind) || shapeItems()[0]).focus();
}
function closeShapeMenu(refocus = false) {
  if (shapeMenu.hidden) return;
  shapeMenu.hidden = true;
  shapeButton.setAttribute("aria-expanded", "false");
  if (refocus) shapeButton.focus();
}
/** The shape the Shape tool draws next; `start` picks the tool too. */
function chooseShape(name, start = true) {
  if (!SHAPES[name]) return;
  shapeKind = name;
  shapeItems().forEach((button) => button.setAttribute("aria-checked", String(button.dataset.shape === name)));
  const icon = shapeItems().find((button) => button.dataset.shape === name).querySelector("svg").cloneNode(true);
  $("[data-shape-icon]").replaceChildren(icon);
  shapeButton.title = `Shape (G): ${SHAPES[name].toLowerCase()}. Click for other shapes.`;
  if (start) setTool("shape");
}
function wireShapeMenu() {
  shapeButton.onclick = () => (shapeMenu.hidden ? openShapeMenu() : closeShapeMenu());
  shapeItems().forEach((button) => {
    button.onclick = () => { chooseShape(button.dataset.shape); closeShapeMenu(true); };
  });
  shapeMenu.addEventListener("keydown", (event) => {
    const buttons = shapeItems();
    const index = buttons.indexOf(document.activeElement);
    const moves = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (event.key in moves) buttons[(index + moves[event.key] + buttons.length) % buttons.length].focus();
    else if (event.key === "Home") buttons[0].focus();
    else if (event.key === "End") buttons[buttons.length - 1].focus();
    else if (event.key === "Escape") closeShapeMenu(true);
    else if (event.key === "Tab") closeShapeMenu();
    else return;
    event.preventDefault();
    event.stopPropagation();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!shapeMenu.hidden && !shapeMenu.contains(event.target) && !shapeButton.contains(event.target)) closeShapeMenu();
  });
  window.addEventListener("resize", () => closeShapeMenu());
  window.addEventListener("scroll", () => { if (!shapeMenu.hidden) placeShapeMenu(); }, { passive: true });
  $("[data-tools]").addEventListener("scroll", () => closeShapeMenu(), { passive: true });
}

// Team, number and name of a token (or the team of the next one).
function tokenFields(item) {
  const team = document.createElement("label");
  const choose = document.createElement("select");
  choose.append(...Object.entries(TEAMS).map(([value, text]) => new Option(text, value, false, (item?.team || tokenTeam) === value)));
  choose.onchange = () => {
    tokenTeam = choose.value;
    if (!item) return;
    const current = doc.find(item.id);
    const fill = teamColours(current.on)[choose.value];
    doc.replace({ ...current, team: choose.value, style: { ...current.style, fill, color: textOn(fill) } });
  };
  team.append("Team ", choose);
  if (!item) return [team];
  const text = (labelText, key, max, placeholder) => {
    const label = document.createElement("label");
    const input = Object.assign(document.createElement("input"), { type: "text", maxLength: max, value: item[key] || "", placeholder });
    input.dataset.tokenField = key;
    input.onchange = () => {
      const current = doc.find(item.id);
      if (!current) return;
      const value = input.value.trim().slice(0, max);
      const next = { ...current, [key]: value };
      if (key === "name" && !value) delete next.name;
      doc.replace(next);
    };
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); input.blur(); canvas.focus(); } });
    label.append(`${labelText} `, input);
    return label;
  };
  const rows = [team, text("Number", "label", 3, "10"), text("Name", "name", 30, "Optional")];
  if (item.on !== undefined) {
    const count = item.moves?.length || 0;
    const row = Object.assign(document.createElement("span"), { className: "annotate-token-moves" });
    const note = Object.assign(document.createElement("span"), { className: "annotate-muted",
      textContent: count ? `${count} move${count === 1 ? "" : "s"} on this board` : "Still. Drag it later in the board to make it move." });
    row.append(note);
    if (count) {
      const clear = Object.assign(document.createElement("button"), { type: "button", textContent: "Clear moves" });
      clear.onclick = () => { const current = doc.find(item.id); if (current) doc.replace(clearMoves(current)); };
      row.append(clear);
    }
    rows.push(row);
  }
  return rows;
}

// The colours of the teams on board `frame` (found from the shirts), or the defaults.
function teamColours(frame = boardNow()?.atFrame) {
  const board = doc.freezes.find((f) => f.atFrame === frame)?.background;
  return { ...DEFAULT_TEAM_COLOURS, ...(board?.home ? { home: board.home } : {}), ...(board?.away ? { away: board.away } : {}) };
}

function renderFollowPanel(item) {
  const panel = $("[data-follow-panel]");
  const linked = item ? [...linkedTracks(item)] : [];
  panel.hidden = !item || (!linked.length && !FOLLOWABLE.includes(item.kind));
  if (panel.hidden) return;
  const track = linked.length === 1 ? trackById(linked[0]) : null;
  $("[data-follow-start]").hidden = linked.length > 0;
  document.querySelectorAll("[data-follow-linked]").forEach((row) => { row.hidden = !track; });
  const state = $("[data-follow-state]");
  if (!linked.length) {
    state.textContent = "Make this drawing follow a player through the clip.";
  } else if (!track) {
    state.textContent = `Corners follow ${linked.length} players. Drag a corner to correct that player on this frame.`;
  } else {
    const at = boxAt(track, frameNow());
    const job = jobs.get(track.id);
    state.textContent = job ? `Following ${playerName(track)}: tracking ${Math.round(job.progress * 100)}%...`
      : !at ? `Following ${playerName(track)}.`
        : at.held ? `${playerName(track)}: not tracked on this frame, so the drawing holds its last place. Drag it onto the player to carry on.`
          : at.state === REVIEW ? `${playerName(track)}: the tracker was unsure here. If the drawing is on them, press Confirm this frame; if not, drag it onto them.`
            : at.state === 1 ? `${playerName(track)}: placed by you on this frame.`
              : `Following ${playerName(track)}.`;
    $("[data-follow-label]").value = track.label || "";
    $("[data-follow-label]").placeholder = playerName(track);
    $("[data-follow-confirm]").disabled = !at || (!at.held && at.state !== REVIEW);
    $("[data-follow-next]").disabled = !nextCheck(track);
  }
}

const renderList = () => {
  renderDrawingLane();
  const list = $("[data-list]");
  $("[data-count]").textContent = `(${doc.items.length})`;
  list.replaceChildren(...doc.items.map((item) => {
    const entry = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = selectedIds.includes(item.id) ? "is-selected" : "";
    button.textContent = `${itemName(item)}${item.on !== undefined ? " (board)" : ""} · ${item.show.from.toFixed(2)}–${item.show.to.toFixed(2)}s`;
    button.onclick = (event) => (event.shiftKey ? toggleSelected(item.id) : selectDrawing(item));
    entry.append(button);
    return entry;
  }));
};

// Drawings lane: one bar per drawing in output time, stacked so overlapping drawings stay apart.
// Click a bar to select it; drag the selected bar's ends to change when it shows.
const BAR_ROW = 10;
const renderDrawingLane = () => {
  const lane = $("[data-drawing-lane]");
  lane.querySelectorAll("[data-bar]").forEach((bar) => bar.remove());
  if (!clip) return;
  const length = total();
  // A board's tokens and drawings share one row (boards never overlap); the clip's drawings stack below.
  const boardRow = doc.items.some((item) => item.on !== undefined) ? 1 : 0;
  const rowsEnd = [];
  [...doc.items].sort((a, b) => a.show.from - b.show.from).forEach((item) => {
    let row = 0;
    if (item.on === undefined) {
      row = rowsEnd.findIndex((end) => end <= item.show.from);
      if (row < 0) row = rowsEnd.push(0) - 1;
      rowsEnd[row] = item.show.to;
      row += boardRow;
    }
    const bar = document.createElement("span");
    bar.className = `annotate-lane-drawing${selectedIds.includes(item.id) ? " is-selected" : ""}`;
    bar.dataset.bar = item.id;
    bar.title = `${itemName(item)}, ${item.show.from.toFixed(2)}–${item.show.to.toFixed(2)} s`;
    bar.style.left = `${(item.show.from / length) * 100}%`;
    bar.style.width = `${(Math.max(0, item.show.to - item.show.from) / length) * 100}%`;
    bar.style.top = `${4 + row * BAR_ROW}px`;
    if (item.id === selectedId) {
      for (const grip of ["from", "to"]) {
        const handle = document.createElement("span");
        handle.className = "annotate-lane-grip";
        handle.dataset.grip = grip;
        bar.append(handle);
      }
    }
    lane.append(bar);
  });
  lane.style.height = `${Math.max(18, (rowsEnd.length + boardRow) * BAR_ROW + 6)}px`;
};

// A drawing made on a board belongs to it: it shows only there, for the board's time.
const placeNew = (item) => {
  const board = boardNow();
  if (!board) return item;
  const start = Math.round(freezeStart(board.atFrame, timing, doc.freezes) * 1000) / 1000;
  const end = Math.round((start + board.seconds) * 1000) / 1000;
  return { ...item, on: board.atFrame, show: { ...item.show, from: Math.min(end, Math.max(start, item.show.from)), to: end } };
};

const selectDrawing = (item) => {
  if (tool !== "select") setTool("select");
  if (currentTime() < item.show.from || currentTime() > item.show.to) seekOutput(item.show.from);
  select(item.id);
};

const removeSelected = () => {
  if (selectedFreeze !== null && !selectedIds.length) return removeFreeze(selectedFreeze);
  const ids = new Set(selectedIds.length ? selectedIds : selectedId ? [selectedId] : []);
  if (!ids.size) return;
  doc.commitDocument((value) => pruneTracks({ ...value, items: value.items.filter((item) => !ids.has(item.id)) }));
  select(null);
  if (ids.size > 1) trackStatus(`${ids.size} drawings deleted. Undo brings them back.`);
};

// Several drawings at once: Shift+click adds or removes one; one left behaves as a normal selection.
const selectMany = (ids) => {
  if (ids.length <= 1) return select(ids[0] || null);
  selectedId = null;
  selectedIds = ids;
  selectedPart = null;
  selectedFreeze = null;
  renderParts();
  renderInspector();
  scheduleRender();
};
const toggleSelected = (id) => {
  const current = selectedIds.length ? selectedIds : selectedId ? [selectedId] : [];
  selectMany(current.includes(id) ? current.filter((each) => each !== id) : [...current, id]);
};

const setAnimation = (patch) => {
  const item = doc.find(selectedId);
  if (!item) return;
  const show = { ...item.show, ...patch };
  if ((show.animate || "none") === "none" && (show.animateOut || "none") === "none") {
    delete show.animSeconds;
    delete show.ease;
  } else {
    show.animSeconds = show.animSeconds ?? 0.5;
    show.ease = show.ease || "ease-out";
  }
  if (!show.animateOut || show.animateOut === "none") delete show.animateOut;
  if (!show.pulse) delete show.pulse;
  doc.replace({ ...item, show });
};

const setTiming = (key, value) => {
  const item = doc.find(selectedId);
  if (!item || !Number.isFinite(value)) return renderInspector();
  const show = { ...item.show, [key]: Math.round(clampTime(value) * 1000) / 1000 };
  if (show.to < show.from) show[key === "from" ? "to" : "from"] = show[key];
  doc.replace({ ...item, show });
};

// ---------------------------------------------------------------------------
// Following players: tracking jobs, corrections and lanes
// ---------------------------------------------------------------------------
const editorPath = () => `/api/editor/${encodeURIComponent(projectId)}/${encodeURIComponent(clipId)}`;
const jobs = new Map(); // track id -> {id, progress, start, end}
const queued = new Map(); // track id -> spans to track once the running job ends: [{start, limit}]
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const trackStatus = (text, problem = false) => {
  const line = $("[data-track-status]");
  line.textContent = text;
  line.hidden = !text;
  line.classList.toggle("is-problem", problem);
};
const updateTrack = (id, change) => doc.commitDocument((value) => ({
  ...value, tracks: (value.tracks || []).map((track) => (track.id === id ? change(track) : track)),
}));
// The source frame a drawing stops showing on.
const endFrame = (item) => realFrame(outputToSource(item.show.to, timing, doc.freezes).frame);
const followLimit = (trackId) => {
  const frames = doc.items.filter((item) => linkedTracks(item).has(trackId)).map(endFrame);
  return Math.min(clip.frames - 1, Math.max(frameNow(), ...frames));
};

async function startTracking(trackId, start, box, limit = followLimit(trackId)) {
  const track = trackById(trackId);
  if (!track) return;
  const end = spanEnd(track, start, Math.min(clip.frames - 1, limit));
  if (end <= start) {
    renderPlayers();
    return runQueued(trackId);
  }
  await cancelTracking(trackId, true);
  // A keyframe just after the span: the engine also tracks back from it and blends the two (M5),
  // so the drawing arrives on that keyframe instead of jumping to it.
  const next = track.keyframes[String(end + 1)];
  try {
    const { job } = await projectRequest(`${editorPath()}/track`, { from_frame: start, to_frame: end, box, ...(next ? { to_box: next } : {}) });
    jobs.set(trackId, { id: job.id, progress: 0, start, end });
    trackStatus("");
    renderPlayers();
    pollTracking(trackId, job.id);
  } catch (error) {
    trackStatus(`Could not follow the player: ${error.message}`, true);
  }
}

// The next span waiting for this player, if any (see correctTrack).
function runQueued(trackId) {
  const following = queued.get(trackId)?.shift();
  if (!queued.get(trackId)?.length) queued.delete(trackId);
  const track = following && trackById(trackId);
  const seed = track && track.keyframes[String(following.start)];
  if (seed) startTracking(trackId, following.start, seed, following.limit);
}

async function pollTracking(trackId, jobId) {
  for (;;) {
    await sleep(250);
    const entry = jobs.get(trackId);
    if (!entry || entry.id !== jobId) return; // replaced or cancelled
    let job;
    try {
      ({ job } = await projectRequest(`/api/editor-jobs/${jobId}`));
    } catch (error) {
      jobs.delete(trackId);
      trackStatus(`Tracking stopped: ${error.message}`, true);
      return renderPlayers();
    }
    if (job.status === "running") {
      entry.progress = job.progress || 0;
      renderPlayers();
      continue;
    }
    jobs.delete(trackId);
    if (job.status === "done") applyTracking(trackId, entry, job.result);
    else if (job.status === "failed") trackStatus(`Tracking failed: ${job.error}`, true);
    else trackStatus("Tracking cancelled.");
    renderPlayers();
    renderInspector();
    if (job.status === "done") runQueued(trackId);
    else queued.delete(trackId);
    return;
  }
}

function applyTracking(trackId, entry, result) {
  if (!trackById(trackId)) return;
  updateTrack(trackId, (track) => mergeRows(track, entry.start, entry.end, result.rows));
  const track = trackById(trackId);
  const checks = flaggedRuns(track, REVIEW).filter(([first]) => first >= entry.start && first <= entry.end).length;
  const messages = [];
  if (result.notice) messages.push(result.notice);
  if (result.stopped?.reason === "scene-cut") {
    messages.push(`Scene cut at frame ${result.stopped.frame + 1}: ${playerName(track)} is held in place after it. Drag the drawing onto them after the cut to carry on.`);
  } else if (result.stopped?.reason === "lost") {
    messages.push(`Lost ${playerName(track)} at frame ${result.stopped.frame + 1}. Drag the drawing back onto them to carry on.`);
  }
  if (checks) messages.push(`${checks} moment${checks === 1 ? "" : "s"} marked amber to check.`);
  trackStatus(messages.join(" ") || `${playerName(track)} followed to frame ${entry.end + 1}.`,
    Boolean(result.notice || result.stopped?.reason === "scene-cut" || result.stopped?.reason === "lost" || checks));
}

async function cancelTracking(trackId, quiet = false) {
  if (!quiet) queued.delete(trackId);
  const entry = jobs.get(trackId);
  if (!entry) return;
  jobs.delete(trackId);
  try { await projectRequest(`/api/editor-jobs/${entry.id}/cancel`, {}); } catch { /* it may have just finished */ }
  if (!quiet) trackStatus("Tracking cancelled.");
  renderPlayers();
}

// A box fitted to the player inside `box` ([footX, footY, w, h] fractions of the frame) on the frame on screen,
// or null when their outline cannot be told from what is round them (annotate/fit.js).
const fitCut = document.createElement("canvas");
const fitPlayerBox = (box) => {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh || boardNow()) return null;
  const [fx, fy, w, h] = box;
  const [x0, x1, y0, y1] = [(fx - w / 2) * vw, (fx + w / 2) * vw, (fy - h) * vh, fy * vh];
  const [mx, my] = [(x1 - x0) * 0.25, (y1 - y0) * 0.25]; // room round the box, for a box that cuts the player off
  const [sx, sy] = [Math.max(0, Math.floor(x0 - mx)), Math.max(0, Math.floor(y0 - my))];
  const [ex, ey] = [Math.min(vw, Math.ceil(x1 + mx)), Math.min(vh, Math.ceil(y1 + my))];
  if (ex - sx < 8 || ey - sy < 12) return null;
  const scale = Math.min(1, 360 / (ey - sy)); // at most 360 px high: plenty to see a player, and quick
  fitCut.width = Math.max(1, Math.round((ex - sx) * scale));
  fitCut.height = Math.max(1, Math.round((ey - sy) * scale));
  const cutCtx = fitCut.getContext("2d", { willReadFrequently: true });
  let image;
  try {
    cutCtx.drawImage(video, sx, sy, ex - sx, ey - sy, 0, 0, fitCut.width, fitCut.height);
    image = cutCtx.getImageData(0, 0, fitCut.width, fitCut.height);
  } catch {
    return null; // the picture cannot be read back
  }
  const rect = [(x0 - sx) * scale, (y0 - sy) * scale, (x1 - sx) * scale, (y1 - sy) * scale];
  const found = fitBox(image, rect, { left: sx === 0, right: ex === vw, top: sy === 0, bottom: ey === vh });
  if (!found) return null;
  const [a0, b0, a1, b1] = [sx + found[0] / scale, sy + found[1] / scale, sx + found[2] / scale, sy + found[3] / scale];
  return [(a0 + a1) / 2 / vw, b1 / vh, (a1 - a0) / vw, (b1 - b0) / vh].map((value) => Math.round(value * 1e5) / 1e5);
};

// The analyst moved the player's drawing on this frame: that frame becomes a
// keyframe and the spans on both sides of it are tracked again.
const correctTrack = (trackId, dx, dy) => {
  const track = trackById(trackId);
  const at = track && boxAt(track, frameNow());
  if (!at) return;
  keyTrack(trackId, [at.box[0] + dx, at.box[1] + dy, at.box[2], at.box[3]]);
};
// Make `box` the player's keyframe on this frame and track the clip again either side of it.
const keyTrack = (trackId, box) => {
  const track = trackById(trackId);
  const frame = frameNow();
  if (!track) return;
  const limit = Math.max(lastFrame(track), followLimit(trackId));
  updateTrack(trackId, (current) => setKeyframe(current, frame, box));
  // Then track the stretch before the correction again, back from it, so the drawing glides
  // onto the corrected position instead of jumping there.
  const earlier = Object.keys(track.keyframes).map(Number).filter((key) => key < frame);
  if (earlier.length && frame - Math.max(...earlier) > 1) queued.set(trackId, [{ start: Math.max(...earlier), limit: frame - 1 }]);
  else queued.delete(trackId);
  return startTracking(trackId, frame, box, limit); // resolves once the job has started (its status line then clears)
};

function nextCheck(track) {
  const frame = frameNow();
  const runs = [...flaggedRuns(track, REVIEW), ...flaggedRuns(track, LOST)].sort((a, b) => a[0] - b[0]);
  return runs.find(([first]) => first > frame) || null;
}

const followSelected = (action) => {
  const item = doc.find(selectedId);
  const ids = item ? [...linkedTracks(item)] : [];
  const track = ids.length === 1 ? trackById(ids[0]) : null;
  if (action === "start") {
    followTarget = selectedId;
    setTool("follow");
    return;
  }
  if (!track) return;
  const frame = frameNow();
  const at = boxAt(track, frame);
  if (action === "fit" && at) {
    const fitted = fitPlayerBox(at.box);
    if (!fitted) {
      trackStatus("Could not tell the player's outline from what is round them on this frame. Drag a corner of the dashed box to fit it by hand.", true);
      return;
    }
    keyTrack(track.id, fitted).then(() => trackStatus("Box fitted to the player on this frame; the rest of the clip is tracked again from it. Undo puts it back."));
    return;
  }
  if (action === "confirm" && at) updateTrack(track.id, (current) => setKeyframe(current, frame, at.box));
  if (action === "next") {
    const run = nextCheck(track);
    const place = run && sourceToCut(run[0], doc.value.parts, clip.frames)[0];
    if (place !== undefined) seekOutput(playStart(place, timing, doc.freezes));
    else if (run) trackStatus("That frame is not in any part of the clip now.", true);
  }
  if (action === "retrack" && at) {
    updateTrack(track.id, (current) => setKeyframe(current, frame, at.box));
    startTracking(track.id, frame, at.box);
  }
  if (action === "stop") {
    cancelTracking(track.id, true);
    const placed = resolveItem(item, tracks(), frame);
    doc.commitDocument((value) => pruneTracks({ ...value, items: value.items.map((each) => (each.id === item.id ? { ...each, points: placed.points.map((p) => p.map((v) => Math.round(v * 1e5) / 1e5)) } : each)) }));
    trackStatus(`${playerName(track)} no longer followed by this drawing.`);
  }
};

// A box drawn round a player: follow them with the chosen drawing, or a new ring.
const followFromBox = (start, end) => {
  const [x0, x1] = [Math.min(start[0], end[0]), Math.max(start[0], end[0])];
  const [y0, y1] = [Math.min(start[1], end[1]), Math.max(start[1], end[1])];
  if ((x1 - x0) * canvas.width < 6 || (y1 - y0) * canvas.height < 10) {
    trackStatus("Drag a box around the whole player, head to boots.", true);
    return;
  }
  const frame = frameNow();
  const drawn = [(x0 + x1) / 2, y1, x1 - x0, y1 - y0].map((v) => Math.round(Math.min(1.5, Math.max(-0.5, v)) * 1e5) / 1e5);
  const box = fitPlayerBox(drawn) || drawn; // a tight box tracks far better than a loose one
  const track = newTrack(frame, box);
  const target = followTarget && doc.find(followTarget);
  followTarget = null;
  let itemId;
  doc.commitDocument((value) => {
    const next = { ...value, tracks: [...(value.tracks || []), track] };
    if (target) {
      const placed = resolveItem(target, value.tracks || [], frame);
      itemId = target.id;
      next.items = value.items.map((item) => (item.id === target.id
        ? { ...item, points: item.points.map((point, index) => (index === 0 ? linkTo(track, placed.points[0], frame) : point)) } : item));
    } else {
      const ring = newItem("ring", [{ track: track.id, dx: 0, dy: 0 }], {
        from: currentTime(), to: total(), style: toolStyle.ring, geometry: ringGeometry(Math.max(0.008, (x1 - x0) * 0.75), aspect()),
      });
      itemId = ring.id;
      next.items = [...value.items, ring];
    }
    return next;
  });
  setTool("select");
  select(itemId);
  startTracking(track.id, frame, box);
};

// Where source frames `first` to `last` play on the timeline: [left %, width %], one for each place they play
// (a repeated part plays them again, a cut part not at all).
const laneSpans = (first, last) => {
  const found = [];
  let offset = 0;
  for (const [from, to] of spansOf(doc.value.parts, clip.frames)) {
    const a = Math.max(first, from);
    const b = Math.min(last + 1, to);
    if (b > a) {
      const left = playStart(offset + a - from, timing, doc.freezes);
      const right = offset + b - from >= timing.frames ? total() : freezeStart(offset + b - from, timing, doc.freezes);
      found.push([(left / total()) * 100, (Math.max(right - left, 0) / total()) * 100]);
    }
    offset += to - from;
  }
  return found;
};

function renderPlayers() {
  const box = $("[data-players]");
  box.replaceChildren(...tracks().map((track) => {
    const row = document.createElement("div");
    row.className = "annotate-row annotate-player";
    const name = Object.assign(document.createElement("span"), { className: "annotate-row-name", textContent: playerName(track), title: playerName(track) });
    const lane = document.createElement("div");
    lane.className = "annotate-lane";
    lane.setAttribute("aria-hidden", "true");
    const keys = Object.keys(track.keyframes).map(Number);
    const first = Math.min(track.from, ...keys);
    const last = lastFrame(track);
    const add = (className, left, width) => {
      const mark = document.createElement("span");
      mark.className = className;
      mark.style.left = left;
      if (width) mark.style.width = width;
      lane.append(mark);
    };
    const place = (className, a, b) => laneSpans(a, b).forEach(([left, width]) => add(className, `${left}%`, `${width}%`));
    place("annotate-cover", first, last);
    flaggedRuns(track, REVIEW).forEach(([a, b]) => place("annotate-flag is-review", a, b));
    flaggedRuns(track, LOST).forEach(([a, b]) => place("annotate-flag is-lost", a, b));
    keys.forEach((frame) => laneSpans(frame, frame).forEach(([left]) => add("annotate-key", `${left}%`)));
    const job = jobs.get(track.id);
    if (job) laneSpans(job.start, job.end).forEach(([left, width]) => add("annotate-progress", `${left}%`, `${job.progress * width}%`));
    add("annotate-lane-head", `${(outTime / total()) * 100}%`);
    lane.lastChild.dataset.head = "";
    lane.addEventListener("pointerdown", (event) => {
      const rect = lane.getBoundingClientRect();
      seekOutput(((event.clientX - rect.left) / rect.width) * total());
    });
    const action = document.createElement("button");
    action.type = "button";
    action.className = job ? "annotate-row-action is-busy" : "annotate-row-action";
    if (job) {
      action.textContent = `Cancel ${Math.round(job.progress * 100)}%`;
      action.onclick = () => cancelTracking(track.id);
    } else {
      action.textContent = "Select";
      action.title = `Select the drawing following ${playerName(track)}`;
      action.onclick = () => {
        const item = doc.items.find((each) => linkedTracks(each).has(track.id));
        if (item) { setTool("select"); select(item.id); }
      };
    }
    row.append(name, lane, action);
    return row;
  }));
  const item = doc.find(selectedId);
  if (item) renderFollowPanel(item);
}

// ---------------------------------------------------------------------------
// Freezes
// ---------------------------------------------------------------------------
const changeFreeze = (frame, seconds) => doc.commitDocument((value) => (seconds > 0 ? setFreeze(value, timing, frame, seconds) : removeInsert(value, timing, frame)));
// Remove a freeze, or a board with its tokens and drawings, in one undoable step.
const removeFreeze = (frame) => {
  const freeze = doc.freezes.find((f) => f.atFrame === frame);
  if (!freeze) return;
  if (selectedFreeze === frame) selectedFreeze = null;
  changeFreeze(frame, 0);
  trackStatus(`${freeze.background ? "Board" : "Freeze"} at frame ${frame + 1} deleted. Undo brings it back.`);
};
const selectFreeze = (frame) => {
  selectedFreeze = frame;
  selectedId = null;
  selectedIds = [];
  selectedPart = null;
  renderParts();
  renderFreezes();
  renderInspector();
  scheduleRender();
};
const freezeHere = () => {
  const at = source();
  if (at.freeze === null && !doc.freezes.some((f) => f.atFrame === at.frame)) changeFreeze(at.frame, 2);
  seekOutput(freezeStart(at.frame, timing, doc.freezes)); // into the freeze, ready to draw on it
  document.querySelector(`[data-freeze-seconds="${at.frame}"]`)?.focus();
};

let freezesShown = 0;
const renderFreezes = () => {
  const freezes = sortedFreezes();
  if (freezes.length > freezesShown) $("[data-freeze-panel]").open = true;
  freezesShown = freezes.length;
  $("[data-scrub]").max = String(total());
  $("[data-freeze-count]").textContent = `(${freezes.length})`;
  $("[data-freeze-empty]").hidden = freezes.length > 0;
  $("[data-freeze-list]").replaceChildren(...freezes.map((freeze) => {
    const entry = document.createElement("li");
    const board = freeze.background;
    const start = freezeStart(freeze.atFrame, timing, freezes);
    const go = Object.assign(document.createElement("button"), { type: "button",
      textContent: `${board ? "Board" : "Frame"} ${freeze.atFrame + 1} · ${formatTime(start)}` });
    go.onclick = () => seekOutput(start);
    const seconds = Object.assign(document.createElement("input"), { type: "number", min: "0.04", max: "60", step: "0.1", value: String(freeze.seconds) });
    seconds.dataset.freezeSeconds = String(freeze.atFrame);
    seconds.setAttribute("aria-label", `Freeze length in seconds at frame ${freeze.atFrame + 1}`);
    seconds.onchange = () => {
      const value = Number(seconds.value);
      if (Number.isFinite(value) && value >= 0.04 && value <= 60) changeFreeze(freeze.atFrame, value);
      else seconds.value = String(freeze.seconds);
    };
    const remove = Object.assign(document.createElement("button"), { type: "button", className: "annotate-remove", title: "Remove this freeze",
      innerHTML: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>' });
    remove.setAttribute("aria-label", `Remove the ${board ? "board" : "freeze"} at frame ${freeze.atFrame + 1}`);
    if (board) remove.title = "Remove this board with its tokens and drawings";
    remove.onclick = () => removeFreeze(freeze.atFrame);
    entry.append(go, seconds, Object.assign(document.createElement("span"), { textContent: "s" }), remove);
    if (board) {
      entry.className = "is-board";
      const settings = Object.assign(document.createElement("span"), { className: "annotate-board-settings" });
      const choice = (label, options, value, change) => {
        const select = document.createElement("select");
        select.setAttribute("aria-label", `${label} of the board at frame ${freeze.atFrame + 1}`);
        select.append(...Object.entries(options).map(([key, text]) => new Option(typeof text === "string" ? text : text.name, key, false, key === value)));
        select.onchange = () => change(select.value);
        return select;
      };
      settings.append(
        choice("View", VIEWS, board.view, (view) => doc.commitDocument((value) => changeBoardView(value, freeze.atFrame, view, aspect()))),
        choice("Look", THEMES, board.theme, (theme) => doc.commitDocument((value) => changeBoard(value, freeze.atFrame, { theme }))),
      );
      entry.append(settings);
    }
    return entry;
  }));
  const lane = $("[data-lane]");
  lane.querySelectorAll("[data-lane-freeze]").forEach((block) => block.remove());
  const length = total();
  freezes.forEach((freeze) => {
    const block = document.createElement("span");
    block.className = `annotate-lane-freeze${freeze.background ? " is-board" : ""}${freeze.atFrame === selectedFreeze ? " is-selected" : ""}`;
    block.dataset.laneFreeze = String(freeze.atFrame);
    block.title = `${freeze.background ? "Board" : "Freeze"} at frame ${freeze.atFrame + 1}: ${freeze.seconds} s. Click to select it (Delete removes it); drag its right edge to change the length.`;
    const remove = Object.assign(document.createElement("button"), { type: "button", className: "annotate-lane-remove",
      innerHTML: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg>' });
    remove.dataset.freezeRemove = String(freeze.atFrame);
    remove.title = freeze.background ? "Delete this board with its tokens and drawings" : "Delete this freeze";
    remove.setAttribute("aria-label", remove.title);
    block.append(remove);
    block.style.left = `${(freezeStart(freeze.atFrame, timing, freezes) / length) * 100}%`;
    block.style.width = `${(freeze.seconds / length) * 100}%`;
    const edge = document.createElement("span");
    edge.className = "annotate-lane-edge";
    edge.dataset.edge = String(freeze.atFrame);
    block.append(edge);
    lane.append(block);
  });
};

// ---------------------------------------------------------------------------
// Parts: cut, reorder and repeat (annotate/parts.js)
// ---------------------------------------------------------------------------
const partName = (index) => `Part ${index + 1}`;
const ICONS = {
  earlier: '<path d="M10 3L5 8l5 5"/>', later: '<path d="M6 3l5 5-5 5"/>',
  copy: '<rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 3.5v-.5a1 1 0 00-1-1h-6a1 1 0 00-1 1v6a1 1 0 001 1h.5"/>',
  remove: '<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5M7 7v3.5M9 7v3.5"/>',
};
const partAction = (name, text, label, onclick, disabled = false) => {
  const button = Object.assign(document.createElement("button"), { type: "button", className: "annotate-part-act", title: label, disabled,
    innerHTML: `<svg viewBox="0 0 16 16" aria-hidden="true">${ICONS[name]}</svg>${text}` });
  button.setAttribute("aria-label", label);
  button.onclick = onclick;
  return button;
};

const selectPart = (index) => {
  selectedPart = index;
  if (index !== null) { selectedId = null; selectedIds = []; selectedFreeze = null; }
  renderParts();
  renderInspector();
  scheduleRender();
};

const editParts = (change) => {
  let changed = false;
  doc.commitDocument((value) => {
    const next = change(value);
    changed = next !== null;
    return next || value;
  });
  return changed;
};

function splitHere() {
  if (!clip || playing) return;
  const frame = cutFrameNow();
  if (!editParts((value) => splitAt(value, clip, frame))) {
    trackStatus("Move the playhead to a frame inside a part to split it there.", true);
    return;
  }
  selectedPart = partAt(doc.value, clip, frame).index;
  renderParts();
  trackStatus(`Split at ${formatTime(outTime)}. Drag a part to move it, drag its edges to trim it, or select one and press Delete.`);
}

function removePart(index) {
  const gone = partSpans(doc.value, clip)[index];
  if (!gone || !editParts((value) => deletePart(value, clip, index))) {
    trackStatus("A clip keeps at least one part.", true);
    return;
  }
  selectedPart = null;
  renderParts();
  seekOutput(gone.outStart);
  trackStatus(`${partName(index)} removed: the clip is ${formatTime(gone.outEnd - gone.outStart)} shorter, with its drawings. Undo brings it back.`);
}

function moveSelectedPart(index, target) {
  if (!editParts((value) => movePart(value, clip, index, target))) return;
  selectedPart = target;
  renderParts();
  seekOutput(partSpans(doc.value, clip)[target].outStart);
  trackStatus(`${partName(index)} is now part ${target + 1}. Its freezes, boards and drawings went with it.`);
}

function duplicateAt(index) {
  if (!editParts((value) => duplicatePart(value, clip, index))) {
    trackStatus(`A clip can hold up to ${MAX_PARTS} parts.`, true);
    return;
  }
  selectedPart = index + 1;
  renderParts();
  seekOutput(partSpans(doc.value, clip)[index + 1].outStart);
  trackStatus(`${partName(index)} repeated as part ${index + 2}. Its drawings came too; freezes and boards stay with the first.`);
}

let partsShown = 1;
function renderParts() {
  if (!clip || !doc) return;
  const spans = partSpans(doc.value, clip);
  if (selectedPart !== null && selectedPart >= spans.length) selectedPart = null;
  if (spans.length > partsShown) $("[data-parts-panel]").open = true;
  partsShown = spans.length;
  const length = total();
  const lane = $("[data-parts-lane]");
  lane.querySelectorAll(".annotate-part").forEach((block) => block.remove());
  spans.forEach((span) => {
    const block = document.createElement("span");
    block.className = `annotate-part${span.index === selectedPart ? " is-selected" : ""}`;
    block.dataset.part = String(span.index);
    block.style.left = `${(span.outStart / length) * 100}%`;
    block.style.width = `${((span.outEnd - span.outStart) / length) * 100}%`;
    block.title = `${partName(span.index)}, ${formatTime(span.outEnd - span.outStart)}. Click to select, drag to move it, drag an edge to trim it.`;
    block.append(Object.assign(document.createElement("span"), { className: "annotate-part-label", textContent: spans.length > 1 ? `${span.index + 1} · ${formatTime(span.outEnd - span.outStart)}` : "Whole clip" }));
    ["from", "to"].forEach((edge) => {
      const handle = Object.assign(document.createElement("span"), { className: `annotate-part-edge is-${edge}` });
      handle.dataset.partEdge = edge;
      block.append(handle);
    });
    lane.append(block);
  });
  $("[data-parts-count]").textContent = `(${spans.length})`;
  $("[data-parts-list]").replaceChildren(...spans.map((span) => {
    const entry = document.createElement("li");
    entry.className = span.index === selectedPart ? "is-selected" : "";
    const go = Object.assign(document.createElement("button"), { type: "button", className: "annotate-part-go",
      textContent: `${partName(span.index)} · ${formatTime(span.outEnd - span.outStart)}` });
    go.title = `Frames ${span.from + 1} to ${span.to} of the source clip`;
    go.setAttribute("aria-pressed", String(span.index === selectedPart));
    go.onclick = () => { selectPart(span.index); seekOutput(span.outStart); };
    entry.append(go);
    if (span.index === selectedPart) {
      // The selected part's actions, with words: Earlier and Later change its place in the clip.
      const actions = Object.assign(document.createElement("span"), { className: "annotate-part-actions" });
      actions.append(
        partAction("earlier", "Earlier", `Move ${partName(span.index)} earlier`, () => moveSelectedPart(span.index, span.index - 1), span.index === 0),
        partAction("later", "Later", `Move ${partName(span.index)} later`, () => moveSelectedPart(span.index, span.index + 1), span.index === spans.length - 1),
        partAction("copy", "Repeat", `Repeat ${partName(span.index)} after itself`, () => duplicateAt(span.index), spans.length >= MAX_PARTS),
        partAction("remove", "Remove", `Remove ${partName(span.index)} and close the gap`, () => removePart(span.index), spans.length < 2));
      entry.append(actions);
    }
    return entry;
  }));
  $("[data-parts-empty]").hidden = spans.length > 1;
}

{
  // Click a part to select it and put the playhead there. Drag it to move it; drag an edge to trim it.
  const lane = $("[data-parts-lane]");
  let drag = null;
  const timeAt = (event) => {
    const rect = lane.getBoundingClientRect();
    return Math.min(total(), Math.max(0, ((event.clientX - rect.left) / rect.width) * total()));
  };
  lane.addEventListener("pointerdown", (event) => {
    if (!clip || event.button !== 0) return;
    const block = event.target.closest("[data-part]");
    if (!block) { seekOutput(timeAt(event)); return; }
    const index = Number(block.dataset.part);
    const span = partSpans(doc.value, clip)[index];
    drag = { index, span, edge: event.target.closest("[data-part-edge]")?.dataset.partEdge || null, x: event.clientX, width: lane.getBoundingClientRect().width,
      length: total(), block, moved: false, target: index, next: null, click: timeAt(event) };
    lane.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  lane.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) < 4) return;
    drag.moved = true;
    if (drag.edge) {
      const frames = Math.round(((dx / drag.width) * drag.length) * fps());
      const base = drag.edge === "to" ? drag.span.to : drag.span.from;
      drag.next = Math.min(drag.edge === "to" ? clip.frames : drag.span.to - 1, Math.max(drag.edge === "to" ? drag.span.from + 1 : 0, base + frames));
      const grew = drag.edge === "to" ? drag.next - drag.span.to : drag.span.from - drag.next;
      drag.block.style.width = `${(((drag.span.outEnd - drag.span.outStart) + grew / fps()) / drag.length) * 100}%`;
      drag.block.title = `${grew >= 0 ? "+" : ""}${grew} frames`;
    } else {
      const t = timeAt(event);
      const spans = partSpans(doc.value, clip);
      drag.target = (spans.find((span) => t >= span.outStart && t < span.outEnd) || spans[spans.length - 1]).index;
      drag.block.classList.add("is-dragging");
      lane.querySelectorAll(".annotate-part").forEach((block) => block.classList.toggle("is-drop", Number(block.dataset.part) === drag.target && drag.target !== drag.index));
    }
  });
  const finish = () => {
    const done = drag;
    drag = null;
    if (!done) return;
    if (!done.moved) { selectPart(done.index); seekOutput(done.click); return; }
    if (done.edge) {
      if (done.next === null || !editParts((value) => trimPart(value, clip, done.index, done.edge, done.next))) { renderParts(); return; }
      selectedPart = done.index;
      renderParts();
      trackStatus(`${partName(done.index)} trimmed: it is now ${formatTime(partSpans(doc.value, clip)[done.index].cutLength / fps())} long.`);
    } else if (done.target !== done.index) moveSelectedPart(done.index, done.target);
    else renderParts();
  };
  lane.addEventListener("pointerup", finish);
  lane.addEventListener("pointercancel", () => { drag = null; renderParts(); });
}

{
  // Click or drag on the lane to move the playhead; drag a freeze's right edge to resize it.
  const lane = $("[data-lane]");
  let drag = null;
  const timeAt = (event) => {
    const rect = lane.getBoundingClientRect();
    return ((event.clientX - rect.left) / rect.width) * total();
  };
  lane.addEventListener("pointerdown", (event) => {
    if (!clip) return;
    const removeButton = event.target.closest("[data-freeze-remove]");
    if (removeButton) { event.preventDefault(); removeFreeze(Number(removeButton.dataset.freezeRemove)); return; }
    const edge = event.target.closest("[data-edge]");
    const block = event.target.closest("[data-lane-freeze]");
    if (block && !edge) {
      const frame = Number(block.dataset.laneFreeze);
      selectFreeze(frame);
      seekOutput(freezeStart(frame, timing, doc.freezes));
      return;
    }
    if (edge) {
      const frame = Number(edge.dataset.edge);
      const freeze = doc.freezes.find((f) => f.atFrame === frame);
      drag = { frame, x: event.clientX, seconds: freeze.seconds, length: total(), width: lane.getBoundingClientRect().width, block: edge.parentElement };
    } else {
      drag = { seek: true };
      seekOutput(timeAt(event));
    }
    lane.setPointerCapture(event.pointerId);
  });
  lane.addEventListener("pointermove", (event) => {
    if (!drag) return;
    if (drag.seek) return seekOutput(timeAt(event));
    drag.next = Math.round(Math.min(60, Math.max(0.04, drag.seconds + ((event.clientX - drag.x) / drag.width) * drag.length)) * 10) / 10;
    drag.block.style.width = `${(drag.next / drag.length) * 100}%`;
    drag.block.title = `${drag.next} s`;
  });
  const finish = () => {
    if (drag?.next) changeFreeze(drag.frame, drag.next);
    drag = null;
  };
  lane.addEventListener("pointerup", finish);
  lane.addEventListener("pointercancel", () => { drag = null; renderFreezes(); });
}

{
  const lane = $("[data-drawing-lane]");
  let drag = null;
  const timeAt = (event) => {
    const rect = lane.getBoundingClientRect();
    return Math.min(total(), Math.max(0, ((event.clientX - rect.left) / rect.width) * total()));
  };
  lane.addEventListener("pointerdown", (event) => {
    if (!clip) return;
    const bar = event.target.closest("[data-bar]");
    const grip = event.target.closest("[data-grip]");
    if (grip && bar) {
      drag = { key: grip.dataset.grip, bar, item: doc.find(bar.dataset.bar) };
    } else if (bar) {
      const item = doc.find(bar.dataset.bar);
      if (item) selectDrawing(item);
      return;
    } else {
      drag = { seek: true };
      seekOutput(timeAt(event));
    }
    lane.setPointerCapture(event.pointerId);
  });
  lane.addEventListener("pointermove", (event) => {
    if (!drag) return;
    if (drag.seek) return seekOutput(timeAt(event));
    drag.next = timeAt(event);
    const from = drag.key === "from" ? Math.min(drag.next, drag.item.show.to) : drag.item.show.from;
    const to = drag.key === "to" ? Math.max(drag.next, drag.item.show.from) : drag.item.show.to;
    drag.bar.style.left = `${(from / total()) * 100}%`;
    drag.bar.style.width = `${((to - from) / total()) * 100}%`;
    drag.bar.title = `${from.toFixed(2)}–${to.toFixed(2)} s`;
  });
  lane.addEventListener("pointerup", () => {
    if (drag?.next !== undefined && selectedId === drag.item.id) {
      const { key, item, next } = drag;
      setTiming(key, key === "from" ? Math.min(next, item.show.to) : Math.max(next, item.show.from));
    }
    drag = null;
  });
  lane.addEventListener("pointercancel", () => { drag = null; renderDrawingLane(); });
}

// ---------------------------------------------------------------------------
// Board from this frame (M7). The analyst marks pitch points on the frame;
// the pitch lines are drawn back through the fit so a bad fit shows; then the
// player finder puts a token for each player on a board inserted at the frame.
// ---------------------------------------------------------------------------
const SVG = "http://www.w3.org/2000/svg";
const calibPanel = $("[data-calibrate]");
// The clip's own pitch (P1): marks kept on one frame, so rings and arrows can lie flat on the grass.
let pitchLines = false;
const clipTrack = () => (clip ? clipPitchTrack(doc.value, aspect()) : null);
const pitchHere = () => clipTrack()?.at(frameNow()) || null; // {calibration, state} on the frame on screen
const CAMERA_FRAMES = 4500; // the engine follows the camera for up to 3 minutes at a time
let cameraJob = null; // {id, progress} while the camera is being followed
// A flat drawing is kept for the frame it was placed on (`at`). Edited on another frame, it is kept
// as it is on screen now, for this frame: what the analyst sees is what is saved.
const rebased = (original) => {
  if (!original || !isFlat(original) || !pitchHere()) return original;
  const placed = shownItem(original.id);
  if (!placed) return original;
  const { projected, ...rest } = placed;
  return { ...original, points: rest.points, ...(rest.geometry ? { geometry: rest.geometry } : {}), at: frameNow() };
};
// Offside lines and measures are read from the pitch: say what is missing rather than draw nothing.
const pitchToolBlocked = () => {
  const why = boardNow() ? "Offside lines and measurements go on the video, not on a board."
    : !pitchKeys(doc.value).length ? 'Mark the pitch first (under "Add at this frame"): offside lines and distances are read from it.'
      : !pitchHere() ? "This frame has no pitch (after a cut). Mark the pitch here, or move to a frame that has it." : "";
  if (why) trackStatus(why, true);
  return Boolean(why);
};
const calibPair = (id) => (calib && id ? calib.pairs.find((pair) => pair.id === id) || null : null);
const calibFit = () => (calib ? calibrate(calib.pairs, aspect()) : null);
const round5 = (value) => Math.round(value * 1e5) / 1e5;

function buildPitch() {
  const svg = $("[data-calib-pitch]");
  if (svg.childElementCount) return;
  const make = (name, attributes) => {
    const element = document.createElementNS(SVG, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  };
  svg.append(make("rect", { x: -56, y: -37.5, width: 112, height: 75, rx: 1.5, class: "annotate-pitch-ground" }));
  LINES.forEach((line) => svg.append(make("polyline", { points: line.map(([x, y]) => `${x},${y}`).join(" "), class: "annotate-pitch-line" })));
  LANDMARKS.forEach((mark) => {
    const group = make("g", { class: "annotate-pitch-mark", tabindex: 0, role: "button", "aria-label": mark.name, "data-mark": mark.id });
    const title = make("title", {});
    title.textContent = mark.name;
    group.append(title, make("circle", { cx: mark.at[0], cy: mark.at[1], r: 2.8, class: "annotate-pitch-hit" }),
      make("circle", { cx: mark.at[0], cy: mark.at[1], r: 1.2, class: "annotate-pitch-dot" }));
    group.addEventListener("click", () => pickMark(mark.id));
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); pickMark(mark.id); }
    });
    svg.append(group);
  });
}

function openCalibration(mode = "board") {
  if (!clip || calib || exporting) return;
  if (boardNow()) { trackStatus(mode === "pitch" ? "Go to a frame of the clip to mark the pitch on it." : "Go to a frame of the clip to make a board from it.", true); return; }
  finishText();
  zoneDraft = null;
  pause();
  select(null);
  // The clip's pitch marks come back when it is reopened on their frame, for either mode.
  const saved = keyAt(doc.value, frameNow());
  const pairs = saved ? saved.pairs.map((pair) => ({ id: pair.id, at: [...pair.at] })) : [];
  calib = { mode, frame: frameNow(), cut: cutFrameNow(), pairs, pick: null, selected: null, drag: null, job: null, model: null, message: null };
  buildPitch();
  const board = mode === "board";
  $("[data-calib-title]").textContent = board ? "Board from frame" : "Mark the pitch on frame";
  $("[data-calib-find]").hidden = $("[data-calib-empty]").hidden = $("[data-calib-board-note]").hidden = !board;
  $("[data-calib-save]").hidden = board;
  $("[data-calib-forget]").hidden = board || !saved;
  // Boards before this frame with tokens: their players can glide to where they are here (M8).
  const earlier = sortedFreezes().filter((f) => f.background && f.atFrame < calib.cut
    && doc.items.some((item) => item.on === f.atFrame && item.kind === "token"));
  const target = $("[data-calib-target]");
  target.replaceChildren(new Option("A new board", ""), ...earlier.reverse().map((f) => new Option(`Players of board ${f.atFrame + 1} move here`, String(f.atFrame))));
  target.value = "";
  $("[data-calib-target-row]").hidden = !earlier.length || !board;
  calibPanel.hidden = false;
  document.querySelectorAll("[data-calib-hide]").forEach((element) => { element.hidden = true; });
  $(board ? "[data-board]" : "[data-pitch]").setAttribute("aria-expanded", "true");
  renderCalibration();
  calibPanel.querySelector("[data-mark]")?.focus({ preventScroll: true });
}

function closeCalibration() {
  if (!calib) return;
  if (calib.job) projectRequest(`/api/editor-jobs/${calib.job.id}/cancel`, {}).catch(() => {});
  calib = null;
  pointer = null;
  calibPanel.hidden = true;
  document.querySelectorAll("[data-calib-hide]").forEach((element) => { element.hidden = false; });
  $("[data-board]").setAttribute("aria-expanded", "false");
  $("[data-pitch]").setAttribute("aria-expanded", "false");
  scheduleRender();
  showTime();
}

/** Keep the marks as the pitch on this frame: a new marked frame, or new marks for this one (P2). */
function savePitch() {
  if (!calib || calib.mode !== "pitch" || !calibFit()) return;
  const frame = calib.frame;
  const pairs = calib.pairs.map((pair) => ({ id: pair.id, at: pair.at }));
  const first = !pitchKeys(doc.value).length;
  doc.commitDocument((value) => withKey(value, frame, pairs));
  closeCalibration();
  pitchLines = true;
  renderPitchSaved();
  trackStatus(first
    ? `Pitch marked on frame ${frame + 1}. Rings and arrows can now lie flat on it: tick "Flat on the pitch" in their settings. Follow the camera to keep them on the grass as it moves.`
    : `Pitch marked on frame ${frame + 1} too: the pitch is taken from the nearest marked frames either side.`);
}

function forgetPitch() {
  if (!calib || !keyAt(doc.value, calib.frame)) return;
  const frame = calib.frame;
  doc.commitDocument((value) => withoutKey(value, frame));
  closeCalibration();
  renderPitchSaved();
  trackStatus(pitchKeys(doc.value).length
    ? `The pitch marks on frame ${frame + 1} are removed. Undo brings them back.`
    : "The clip's pitch is removed; flat drawings are drawn as usual again. Undo brings it back.");
}

function renderPitchSaved() {
  const keys = clip ? pitchKeys(doc.value) : [];
  $("[data-pitch-saved]").hidden = !keys.length;
  if (!keys.length) return;
  const track = clipTrack();
  $("[data-pitch-lines]").setAttribute("aria-pressed", String(pitchLines));
  $("[data-pitch-go]").textContent = keys.length === 1 ? `Go to frame ${keys[0].frame + 1}` : "Next marked frame";
  $("[data-pitch-follow]").textContent = track?.followed ? "Follow again" : "Follow the camera";
  $("[data-pitch-follow]").disabled = Boolean(cameraJob || exporting);
  $("[data-pitch-progress]").hidden = !cameraJob;
  if (cameraJob) $("[data-pitch-progress] progress").value = cameraJob.progress;
  const marked = `Marked on ${keys.length} frame${keys.length === 1 ? "" : "s"}.`;
  let state = `${marked} Follow the camera so flat drawings and pitch lines stay on the grass as it moves.`;
  let todo = 0;
  if (cameraJob) state = `${marked} Following the camera...`;
  else if (track?.followed) {
    const checks = track.runs("check").length;
    const none = track.runs("none").length;
    todo = checks + none;
    const parts = [`${marked} Camera followed.`];
    if (checks) parts.push(`${checks} stretch${checks === 1 ? " was" : "es were"} hard to follow: check the pitch lines there.`);
    if (none) parts.push(`${none} stretch${none === 1 ? " has" : "es have"} no pitch (after a cut, or where the camera was lost): mark the pitch there.`);
    if (!todo) parts.push("Turn on Pitch lines and play to check it.");
    state = parts.join(" ");
  }
  $("[data-pitch-state]").textContent = state;
  $("[data-pitch-next]").hidden = !todo || Boolean(cameraJob);
}

/** Show recorded frame `frame` (pausing), or say it was cut out. */
function goToSourceFrame(frame, what) {
  const place = sourceToCut(frame, doc.value.parts, clip.frames)[0];
  if (place === undefined) { trackStatus(`Frame ${frame + 1}, ${what}, is cut out of the clip now.`, true); return false; }
  pause();
  seekOutput(playStart(place, timing, doc.freezes));
  return true;
}

/** The next marked frame after the one on screen (round to the first). */
function goToPitchFrame() {
  const keys = pitchKeys(doc.value).map((key) => key.frame);
  if (!keys.length) return;
  const next = keys.find((frame) => frame > frameNow()) ?? keys[0];
  goToSourceFrame(next, "where the pitch is marked");
}

/** The next stretch to check, or without a pitch, after the frame on screen (round to the first). */
function goToPitchCheck() {
  const track = clipTrack();
  if (!track) return;
  const runs = [...track.runs("check"), ...track.runs("none")].sort((a, b) => a[0] - b[0]);
  if (!runs.length) return;
  const [first, last] = runs.find(([start]) => start > frameNow()) || runs[0];
  if (!goToSourceFrame(first, "the start of the stretch to check")) return;
  pitchLines = true;
  renderPitchSaved();
  trackStatus(track.at(first)
    ? `Frames ${first + 1} to ${last + 1} were hard to follow. If the pitch lines are off, mark the pitch on one of these frames.`
    : `Frames ${first + 1} to ${last + 1} have no pitch. Mark the pitch on one of them to carry on.`, true);
}

/** Follow the camera through the clip in the background (P2), then keep its path with the pitch. */
async function followCamera() {
  const keys = pitchKeys(doc.value).map((key) => key.frame);
  if (!clip || cameraJob || exporting || !keys.length) return;
  const span = Math.min(clip.frames, CAMERA_FRAMES);
  const start = Math.max(0, Math.min(clip.frames - span, keys[0] - Math.floor(span / 2)));
  const end = start + span - 1;
  try {
    const { job } = await projectRequest(`${editorPath()}/camera`, { from_frame: start, to_frame: end });
    cameraJob = { id: job.id, progress: 0 };
    renderPitchSaved();
    for (;;) {
      await sleep(250);
      if (cameraJob?.id !== job.id) return; // cancelled
      const { job: now } = await projectRequest(`/api/editor-jobs/${job.id}`);
      if (now.status === "running") { cameraJob.progress = now.progress || 0; renderPitchSaved(); continue; }
      cameraJob = null;
      if (now.status === "done") {
        doc.commitDocument((value) => (value.pitch ? withCamera(value, now.result) : value));
        pitchLines = true;
        trackStatus(span < clip.frames
          ? `Camera followed from frame ${start + 1} to ${end + 1} (3 minutes at a time, round the first marked frame).`
          : "Camera followed through the clip. Flat drawings now keep their place on the grass.");
      } else if (now.status === "failed") trackStatus(`Following the camera failed: ${now.error}`, true);
      else trackStatus("Following the camera was cancelled.");
      renderPitchSaved();
      scheduleRender();
      return;
    }
  } catch (error) {
    cameraJob = null;
    renderPitchSaved();
    trackStatus(`Could not follow the camera: ${error.message}`, true);
  }
}

function stopCamera() {
  if (!cameraJob) return;
  const { id } = cameraJob;
  cameraJob = null;
  projectRequest(`/api/editor-jobs/${id}/cancel`, {}).catch(() => {});
  renderPitchSaved();
  trackStatus("Following the camera was cancelled.");
}

function pickMark(id) {
  if (!calib || calib.job) return;
  calib.pick = calib.pick === id ? null : id;
  calib.selected = calibPair(id) ? id : null;
  calib.message = null;
  renderCalibration();
}

function removeCalibrationPoint() {
  if (!calib || !calib.selected) return;
  calib.pairs = calib.pairs.filter((pair) => pair.id !== calib.selected);
  if (calib.pick === calib.selected) calib.pick = null;
  calib.selected = null;
  renderCalibration();
}

function calibrationDown(event, at) {
  if (calib.job) return;
  const [x, y] = toPixels(at);
  const near = calib.pairs.find((pair) => {
    const [px, py] = toPixels(pair.at);
    return Math.hypot(px - x, py - y) <= handleRadius() * 1.8;
  });
  calib.message = null;
  if (near && near.id !== calib.pick) {
    calib.drag = near.id; // drag a placed mark to fine-tune it
    calib.selected = near.id;
  } else if (calib.pick) {
    const point = [round5(Math.min(1, Math.max(0, at[0]))), round5(Math.min(1, Math.max(0, at[1])))];
    calib.pairs = [...calib.pairs.filter((pair) => pair.id !== calib.pick), { id: calib.pick, at: point }];
    calib.selected = calib.drag = calib.pick;
    calib.pick = null;
  } else {
    calib.selected = null;
    calib.message = "Pick a mark on the pitch first, then click the same spot on the video.";
    return renderCalibration();
  }
  canvas.setPointerCapture(event.pointerId);
  renderCalibration();
}

function calibrationMove(at) {
  const pair = calibPair(calib.drag);
  if (pair) pair.at = [round5(Math.min(1, Math.max(0, at[0]))), round5(Math.min(1, Math.max(0, at[1])))];
  scheduleRender();
}

function renderCalibration() {
  if (!calib) return;
  $("[data-calib-frame]").textContent = String(calib.frame + 1);
  document.querySelectorAll("[data-mark]").forEach((group) => {
    const id = group.dataset.mark;
    group.classList.toggle("is-placed", Boolean(calibPair(id)));
    group.classList.toggle("is-picked", calib.pick === id);
    group.classList.toggle("is-selected", calib.selected === id && calib.pick !== id);
    group.setAttribute("aria-pressed", String(calib.pick === id));
  });
  const count = calib.pairs.length;
  const fit = calibFit();
  $("[data-calib-help]").textContent = calib.pick
    ? `Now click "${landmark(calib.pick).name}" on the video. Hold and drag to place it exactly; the loupe shows the detail.`
    : "Pick a mark on the pitch, then click the same spot on the video. Use at least 4 marks spread across the frame; 6 or more is better.";
  let state;
  let problem = false;
  if (calib.job) state = calib.job.text;
  else if (calib.message) [state, problem] = [calib.message, /fail|stopp|could not|not fit|first/i.test(calib.message)];
  else if (count < 4) state = `${count} of 4 marks placed.`;
  else if (!fit) [state, problem] = ["These marks do not pin the pitch down: several lie on one line. Add marks away from that line, spread across the frame.", true];
  else if (count === 4) state = "4 marks always fit exactly, so check the green lines on the video. More marks across the frame give a better fit.";
  else if (fit.worst < 1.5) state = `Good fit: the marks agree within ${fit.worst.toFixed(1)} m. Check the green lines on the video.`;
  else if (fit.worst < 4) [state, problem] = [`Rough fit: one mark is ${fit.worst.toFixed(1)} m out. Move marks that sit off their lines.`, true];
  else [state, problem] = [`Poor fit: one mark is ${Math.round(fit.worst)} m out and may be on the wrong mark.`, true];
  const line = $("[data-calib-state]");
  line.textContent = state;
  line.classList.toggle("is-problem", problem);
  const busy = Boolean(calib.job);
  const moving = $("[data-calib-target]").value !== "";
  $("[data-calib-find]").disabled = !fit || busy;
  $("[data-calib-find]").textContent = moving ? "Find players and move" : "Find players";
  $("[data-calib-empty]").disabled = busy || moving;
  $("[data-calib-remove]").disabled = !calibPair(calib.selected) || busy;
  $("[data-calib-save]").disabled = !fit || busy;
  const others = pitchKeys(doc.value).filter((key) => key.frame !== calib.frame).length;
  if (calib.mode === "pitch" && others && !keyAt(doc.value, calib.frame) && !problem && count >= 4) {
    line.textContent = `${state} Saving adds this frame to the ${others} marked already.`;
  }
  $("[data-calib-progress]").hidden = !busy;
  if (busy) $("[data-calib-progress] progress").value = calib.job.progress;
  $("[data-calib-stop]").disabled = Boolean(calib.job?.stopping);
  const install = $("[data-calib-install]");
  install.hidden = !calib.model || busy;
  if (calib.model) {
    const megabytes = (calib.model.bytes / 1e6).toFixed(1);
    $("[data-calib-install-text]").textContent = `Finding players needs a one-time ${megabytes} MB download: ${calib.model.label}, from the official YOLOX release. It is checked against its known fingerprint, kept with VizorPlay's data and run only on this computer.`;
    $("[data-calib-download]").textContent = `Download ${megabytes} MB`;
  }
  scheduleRender();
}

// The pitch lines through the fit, the placed marks, and a loupe while placing.
function drawCalibration() {
  const fit = calibFit();
  if (fit) drawPitchLines(fit);
  calib.pairs.forEach((pair) => drawMark(pair.at, pair.id === calib.selected));
  const focus = calibPair(calib.drag)?.at || (calib.pick && pointer) || null;
  if (focus) drawLoupe(focus);
}

function drawPitchLines(fit, doubtful = false) {
  const ratio = window.devicePixelRatio || 1;
  {
    ctx.save(); // the fitted pitch markings, in the calibration's green (amber where the camera was hard to follow)
    ctx.strokeStyle = doubtful ? "rgba(232, 163, 23, 0.95)" : "rgba(200, 241, 53, 0.9)";
    ctx.lineWidth = 1.5 * ratio;
    ctx.lineJoin = "round";
    projectedLines(fit).forEach((line) => {
      ctx.beginPath();
      let open = false;
      line.forEach((point) => {
        // Points behind the camera or far off screen break the line.
        if (!point || !(Math.abs(point[0] - 0.5) < 3 && Math.abs(point[1] - 0.5) < 3)) { open = false; return; }
        const [x, y] = toPixels(point);
        if (open) ctx.lineTo(x, y);
        else ctx.moveTo(x, y);
        open = true;
      });
      ctx.stroke();
    });
    ctx.restore();
  }
}

function drawMark(point, strong) {
  const [x, y] = toPixels(point);
  const r = handleRadius();
  ctx.save();
  ctx.lineWidth = 3;
  ctx.strokeStyle = "rgba(23, 24, 23, 0.85)";
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = strong ? "#c8f135" : "#ffffff";
  ctx.stroke();
  ctx.fillStyle = strong ? "#c8f135" : "#ffffff";
  ctx.fillRect(x - 1, y - 1, 2, 2);
  ctx.restore();
}

function drawLoupe(point) {
  if (!video.videoWidth) return;
  const ratio = window.devicePixelRatio || 1;
  const radius = 58 * ratio;
  const zoom = 3;
  const [x, y] = toPixels(point);
  // Beside the pointer, away from the edges, so it never hides the spot being placed.
  const cx = x + (x > canvas.width - radius * 3 ? -1 : 1) * radius * 1.7;
  const cy = y + (y < radius * 2.2 ? 1 : -1) * radius * 1.7;
  const sw = ((2 * radius) / zoom) * (video.videoWidth / canvas.width);
  const sh = ((2 * radius) / zoom) * (video.videoHeight / canvas.height);
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = "#0d0e0c";
  ctx.fill();
  ctx.clip();
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(video, point[0] * video.videoWidth - sw / 2, point[1] * video.videoHeight - sh / 2, sw, sh, cx - radius, cy - radius, radius * 2, radius * 2);
  ctx.strokeStyle = "#c8f135";
  ctx.lineWidth = ratio;
  ctx.beginPath();
  ctx.moveTo(cx - radius, cy); ctx.lineTo(cx - 4 * ratio, cy);
  ctx.moveTo(cx + 4 * ratio, cy); ctx.lineTo(cx + radius, cy);
  ctx.moveTo(cx, cy - radius); ctx.lineTo(cx, cy - 4 * ratio);
  ctx.moveTo(cx, cy + 4 * ratio); ctx.lineTo(cx, cy + radius);
  ctx.stroke();
  ctx.restore();
  ctx.save();
  ctx.lineWidth = 2 * ratio;
  ctx.strokeStyle = "#ffffff";
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

// A job of the player finder (download or search), shown in the panel with its progress.
async function runCalibrationJob(job, text) {
  const mine = calib;
  mine.job = { id: job.id, progress: 0, text: `${text}...` };
  renderCalibration();
  for (;;) {
    await sleep(250);
    if (calib !== mine || mine.job?.id !== job.id) return null; // closed
    const { job: now } = await projectRequest(`/api/editor-jobs/${job.id}`);
    if (calib !== mine) return null;
    if (now.status === "running") {
      mine.job.progress = now.progress || 0;
      if (!mine.job.stopping) mine.job.text = `${text}: ${Math.round(mine.job.progress * 100)}%`;
      renderCalibration();
      continue;
    }
    mine.job = null;
    if (now.status === "done") return now.result;
    mine.message = now.status === "cancelled" ? `${text} cancelled.` : `${text} failed: ${now.error}`;
    renderCalibration();
    return null;
  }
}

function stopCalibrationJob() {
  if (!calib?.job) return;
  calib.job.stopping = true;
  calib.job.text = "Cancelling...";
  renderCalibration();
  projectRequest(`/api/editor-jobs/${calib.job.id}/cancel`, {}).catch(() => {});
}

async function findPlayers() {
  if (!calib || calib.job || !calibFit()) return;
  const mine = calib;
  mine.message = null;
  mine.model = null;
  try {
    // Ask first, so a missing model is an offer to download rather than a failed request.
    const { players: model } = await projectRequest("/api/editor-models");
    if (calib !== mine) return;
    if (!model.installed) { mine.model = model; return renderCalibration(); }
    const response = await fetch(`${editorPath()}/players`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ frame: mine.frame }),
    });
    const payload = await response.json().catch(() => ({}));
    if (calib !== mine) return;
    if (response.status === 409 && payload.model) { mine.model = payload.model; return renderCalibration(); }
    if (!response.ok) throw new Error(payload.error || `request failed (${response.status})`);
    const result = await runCalibrationJob(payload.job, "Finding players");
    if (result && calib === mine) makeBoard(result);
  } catch (error) {
    if (calib !== mine) return;
    mine.job = null;
    mine.message = `Could not find players: ${error.message}`;
    renderCalibration();
  }
}

async function downloadModel() {
  if (!calib || calib.job) return;
  const mine = calib;
  mine.model = null;
  mine.message = null;
  try {
    const { job } = await projectRequest("/api/editor-models/players", {});
    if (job && !(await runCalibrationJob(job, "Downloading the player finder"))) return;
    if (calib === mine) await findPlayers();
  } catch (error) {
    if (calib !== mine) return;
    mine.job = null;
    mine.message = `The download failed: ${error.message}`;
    renderCalibration();
  }
}

// Insert the board (one undo step): tokens for the players found, or empty.
// Two team colours are the same teams when each is nearer its partner than to the other one.
const colourGap = (a, b) => {
  const [x, y] = [a, b].map((hex) => { const n = parseInt(String(hex).slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; });
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]);
};

// The players found here are where the tokens of an earlier board glide to.
function moveBoardHere(target, result) {
  const colours = teamColours(target);
  // The finder lists the bigger team first in each frame, so the order can flip between frames.
  const swap = colourGap(colours.home, result.teams[1]) + colourGap(colours.away, result.teams[0])
    < colourGap(colours.home, result.teams[0]) + colourGap(colours.away, result.teams[1]);
  const players = playersOnPitch(result.players.map((player) => ({ ...player, team: swap && player.team < 2 ? 1 - player.team : player.team })), calibFit());
  let report;
  doc.commitDocument((value) => {
    report = moveBoard(value, timing, target, players, aspect(), colours);
    return report.value;
  });
  const from = calib.frame;
  closeCalibration();
  setTool("select");
  seekOutput(freezeStart(target, timing, doc.freezes));
  const parts = [`${report.matched} player${report.matched === 1 ? "" : "s"} glide to where they are on frame ${from + 1}`];
  if (report.added) parts.push(`${report.added} new appear${report.added === 1 ? "s" : ""}`);
  if (report.kept) parts.push(`${report.kept} not found there stay${report.kept === 1 ? "s" : ""} put`);
  trackStatus(`${parts.join("; ")}. The board is now 3 s longer; press Play to watch. Drag a token to correct it.`);
}

function makeBoard(result) {
  const target = $("[data-calib-target]").value;
  if (result && target !== "") return moveBoardHere(Number(target), result);
  const frame = boardFrame(doc.value, timing, calib.cut);
  if (frame === null) {
    calib.message = "There is no free frame after this one for a board.";
    return renderCalibration();
  }
  const background = { kind: "board", view: "full", theme: "grass", fromFrame: calib.frame };
  let tokens = () => [];
  let summary = "Empty board added. Place players with the Token tool (K).";
  if (result) {
    const colours = { ...DEFAULT_TEAM_COLOURS, home: result.teams[0], away: result.teams[1] };
    const found = tokensFromPlayers(result.players, calibFit(), aspect(), colours);
    Object.assign(background, { view: found.view, home: colours.home, away: colours.away });
    tokens = found.tokens;
    summary = found.placed
      ? `Board added with ${found.placed} player${found.placed === 1 ? "" : "s"}${found.skipped ? ` (${found.skipped} found off the pitch left out)` : ""}. Players hidden or cut off by the camera are missing. Click a token to fix its team or add the shirt number.`
      : "No players were found on the pitch in this frame, so the board is empty. Place players with the Token tool (K).";
  }
  doc.commitDocument((value) => addBoard(value, timing, frame, BOARD_SECONDS, background, tokens));
  closeCalibration();
  setTool("select");
  seekOutput(freezeStart(frame, timing, doc.freezes));
  trackStatus(summary);
}

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------
const openText = (point, item = null) => {
  const style = item ? styleOf(item) : toolStyle.text;
  textEdit = { id: item?.id || null, point };
  const rect = stage.getBoundingClientRect();
  const scale = rect.height / 1080;
  Object.assign(textInput.style, {
    left: `${point[0] * 100}%`, top: `${point[1] * 100}%`,
    font: textFont({ kind: "text", style }, scale),
    color: style.color, background: style.background || "rgba(23, 24, 23, 0.35)",
  });
  textInput.value = item?.text || "";
  textInput.hidden = false;
  textInput.focus();
  scheduleRender();
};

function finishText(cancel = false) {
  if (!textEdit) return;
  const { id, point } = textEdit;
  textEdit = null;
  const text = textInput.value.replace(/\s+$/, "").slice(0, 300);
  textInput.hidden = true;
  textInput.value = "";
  if (cancel) return scheduleRender();
  const existing = id ? doc.find(id) : null;
  if (existing) {
    if (!text.trim()) doc.remove(id);
    else doc.replace({ ...existing, text });
  } else if (text.trim()) {
    const link = linkToPlayerAt(point);
    const item = placeNew(newItem("text", [link || point], { from: currentTime(), to: total(), style: toolStyle.text, text }));
    doc.add(item);
    select(item.id);
    if (link) trackStatus(`The text follows ${playerName(trackById(link.track))}. Drag it to change where it sits beside them.`);
  }
  canvas.focus();
}

textInput.addEventListener("keydown", (event) => {
  event.stopPropagation();
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); finishText(); }
  if (event.key === "Escape") { event.preventDefault(); finishText(true); }
});
textInput.addEventListener("input", () => { textInput.style.width = "auto"; textInput.style.width = `${textInput.scrollWidth + 4}px`; });
textInput.addEventListener("blur", () => finishText());

// ---------------------------------------------------------------------------
// Pointer gestures
// ---------------------------------------------------------------------------
const aspect = () => clip.width / clip.height;
// The followed player's box the selected drawing is linked to (when exactly one), if it is on this frame.
const selectedTrackBox = () => {
  const item = doc.find(selectedId);
  const ids = item && !boardNow() ? [...linkedTracks(item)] : [];
  const track = ids.length === 1 ? trackById(ids[0]) : null;
  const at = track && boxAt(track, frameNow());
  return at ? { trackId: track.id, box: at.box } : null;
};
// The nearest corner of that box within reach of `at`: {trackId, box, corner, distance} (pixels).
const nearBoxCorner = (at) => {
  const found = selectedTrackBox();
  if (!found) return null;
  const [x, y] = toPixels(at);
  const near = boxCorners(found.box).map(([cx, cy, corner]) => {
    const [px, py] = toPixels([cx, cy]);
    return { ...found, corner, distance: Math.hypot(px - x, py - y) };
  }).filter((entry) => entry.distance <= handleRadius() * 1.6);
  return near.sort((a, b) => a.distance - b.distance)[0] || null;
};

const nearHandle = (item, at) => {
  const [x, y] = toPixels(at);
  return handlesFor(item).find(({ point }) => {
    const [hx, hy] = toPixels(point);
    return Math.hypot(hx - x, hy - y) <= handleRadius() * 1.6;
  });
};

// Two corners count as one when they are the same player, or a few pixels apart (a double-click's second click).
const sameCorner = (a, b) => {
  if (isLinked(a) && isLinked(b)) return a.track === b.track;
  const [ax, ay] = toPixels(resolvePoint(a, tracks(), frameNow()));
  const [bx, by] = toPixels(resolvePoint(b, tracks(), frameNow()));
  return Math.hypot(ax - bx, ay - by) <= handleRadius();
};
// The corners without repeats: one next to its neighbour, or a last corner back on the first.
const zoneCorners = (points) => {
  const kept = [];
  points.forEach((point) => { if (!kept.length || !sameCorner(kept[kept.length - 1], point)) kept.push(point); });
  while (kept.length > 1 && sameCorner(kept[0], kept[kept.length - 1])) kept.pop();
  return kept;
};
const finishZone = () => {
  const corners = zoneDraft ? zoneCorners(zoneDraft) : [];
  if (zoneDraft && corners.length < 3) {
    trackStatus("A zone needs at least 3 different corners.", true);
  } else if (zoneDraft) {
    const item = placeNew(newItem("zone", corners, { from: currentTime(), to: total(), style: toolStyle.zone }));
    doc.add(item);
    select(item.id);
  }
  zoneDraft = null;
  scheduleRender();
};

canvas.addEventListener("pointerdown", (event) => {
  if (!clip || event.button !== 0) return;
  if (textEdit) { finishText(); return; }
  canvas.focus();
  if (playing) pause();
  const at = toFraction(event);
  if (calib) { calibrationDown(event, at); return; }
  const [x, y] = toPixels(at);
  const { w, h } = size();
  const from = currentTime();
  if (tool === "select") {
    const selected = shownItem(selectedId);
    const handle = selected && nearHandle(selected, at);
    const corner = nearBoxCorner(at);
    const handleDistance = handle ? Math.hypot(...toPixels(handle.point).map((value, i) => value - toPixels(at)[i])) : Infinity;
    if (corner && corner.distance <= handleDistance) {
      gesture = { type: "resize", trackId: corner.trackId, corner: corner.corner, base: corner.box, box: corner.box.slice() };
    } else if (handle && !event.shiftKey) {
      gesture = { type: "handle", id: selected.id, index: handle.index, start: at, moved: false, base: selected, preview: selected };
    } else {
      const hit = itemAt(shown(), x, y, w, h, from, measure);
      const chosen = selectedIds.length ? selectedIds : [];
      if (event.shiftKey && hit) {
        toggleSelected(hit.id);
      } else if (hit && chosen.length > 1 && chosen.includes(hit.id)) {
        // Drag one of several selected drawings: they all move together.
        gesture = { type: "group", start: at, moved: false, bases: chosen.map(shownItem).filter(Boolean), previews: {} };
      } else if (hit) {
        select(hit.id);
        gesture = { type: "move", id: hit.id, start: at, moved: false, base: hit, preview: hit };
      } else {
        // A drag on empty picture draws a selection box; Shift keeps what is already selected.
        if (!event.shiftKey) select(null);
        gesture = { type: "marquee", start: clampPoint(at), end: clampPoint(at), keep: event.shiftKey ? chosen.slice() : [] };
      }
    }
  } else if (tool === "follow") {
    if (boardNow()) { trackStatus("Follow players on the clip itself; a board has no video.", true); return; }
    gesture = { type: "box", start: clampPoint(at), end: clampPoint(at) };
  } else if (tool === "token") {
    const placed = placeNew(newToken(clampPoint(at), { team: tokenTeam, colours: teamColours(), from, to: total() }));
    const { fill, color, ...shape } = toolStyle.token; // the team decides the colour
    const item = { ...placed, style: { ...placed.style, ...shape } };
    doc.add(item);
    select(item.id);
    $('[data-token-field="label"]')?.focus(); // type the shirt number straight away
    return;
  } else if (tool === "zone") {
    // The first corner may follow a player: compare with where it is on this frame.
    // A click that lands on the same player as the first corner closes the zone too.
    const corner = snapPoint(clampPoint(at));
    if (zoneDraft && zoneCorners(zoneDraft).length >= 3) {
      const [fx, fy] = toPixels(resolvePoint(zoneDraft[0], tracks(), frameNow()));
      if (Math.hypot(fx - x, fy - y) <= handleRadius() * 1.6 || (isLinked(corner) && sameCorner(zoneDraft[0], corner))) { finishZone(); return; }
    }
    zoneDraft = [...(zoneDraft || []), corner];
    if (zoneCorners(zoneDraft).length >= 40) finishZone();
  } else if (tool === "text") {
    event.preventDefault();
    openText(clampPoint(at));
    return;
  } else if (tool === "offside" || tool === "measure") {
    if (pitchToolBlocked()) return;
    if (tool === "offside") {
      // One click: the line is drawn through that spot, on this frame's pitch.
      const item = { ...placeNew(newItem("offside", [clampPoint(at)], { from, to: total(), style: toolStyle.offside })), at: frameNow() };
      doc.add(item);
      select(item.id);
      return;
    }
    gesture = { type: "draw", start: at, draft: newItem("measure", [at, at], { from, to: total(), style: toolStyle.measure }), moved: false };
  } else {
    const style = toolStyle[tool];
    const geometry = tool === "shape" ? { shape: shapeKind }
      : tool === "spotlight" ? { ...ringGeometry(0.03, aspect()), h: 0.3 } : ringGeometry(0.03, aspect());
    const points = tool === "ring" || tool === "spotlight" ? [at] : tool === "freehand" ? [at] : [at, at];
    gesture = { type: "draw", start: at, draft: newItem(tool, points, { from, to: total(), style, geometry }), moved: false };
  }
  canvas.setPointerCapture(event.pointerId);
  scheduleRender();
});

canvas.addEventListener("pointermove", (event) => {
  if (!clip) return;
  const at = toFraction(event);
  pointer = clampPoint(at);
  if (calib) { calibrationMove(at); return; }
  if (zoneDraft) scheduleRender();
  if (!gesture?.type) {
    if (tool === "select") canvas.style.cursor = cursorAt(at);
    return;
  }
  const item = gesture.base;
  if ((gesture.type === "move" || gesture.type === "handle" || gesture.type === "group") && !gesture.moved) {
    // A click is not an edit: only a real drag (a few pixels) moves a drawing.
    gesture.moved = Math.hypot((at[0] - gesture.start[0]) * canvas.width, (at[1] - gesture.start[1]) * canvas.height) > 3 * (window.devicePixelRatio || 1);
    if (!gesture.moved) return;
  }
  if (gesture.type === "resize") {
    // The dragged corner follows the pointer; the opposite corner stays where it is.
    const [fx, fy, bw, bh] = gesture.base;
    const point = clampPoint(at);
    const minW = 4 / canvas.width;
    const minH = 8 / canvas.height;
    let [x0, x1, y0, y1] = [fx - bw / 2, fx + bw / 2, fy - bh, fy];
    if (gesture.corner.includes("w")) x0 = Math.min(point[0], x1 - minW); else x1 = Math.max(point[0], x0 + minW);
    if (gesture.corner.includes("n")) y0 = Math.min(point[1], y1 - minH); else y1 = Math.max(point[1], y0 + minH);
    gesture.box = [(x0 + x1) / 2, y1, x1 - x0, y1 - y0];
  } else if (gesture.type === "marquee") {
    gesture.end = clampPoint(at);
  } else if (gesture.type === "group") {
    const [dx, dy] = [at[0] - gesture.start[0], at[1] - gesture.start[1]];
    gesture.previews = Object.fromEntries(gesture.bases.map((base) => [base.id, moveItem(base, dx, dy)]));
  } else if (gesture.type === "move" && item) {
    gesture.end = clampPoint(at); // where it was dropped: text dropped on a followed player follows them
    gesture.preview = moveItem(item, at[0] - gesture.start[0], at[1] - gesture.start[1]); // `item` is placed for this frame
  } else if (gesture.type === "handle" && item) {
    gesture.preview = dragHandle(item, gesture.index, at);
  } else if (gesture.type === "box") {
    gesture.end = clampPoint(at);
  } else if (gesture.type === "draw") {
    const draft = gesture.draft;
    const dx = (at[0] - gesture.start[0]) * canvas.width;
    const dy = (at[1] - gesture.start[1]) * canvas.height;
    if (Math.hypot(dx, dy) > 4) gesture.moved = true;
    if (draft.kind === "ring" || draft.kind === "spotlight") {
      const radius = Math.hypot(dx, dy) / canvas.width;
      draft.geometry = { ...draft.geometry, ...ringGeometry(Math.max(radius, 0.01), aspect()) };
    } else if (draft.kind === "freehand") {
      const last = draft.points[draft.points.length - 1];
      if (Math.hypot((at[0] - last[0]) * canvas.width, (at[1] - last[1]) * canvas.height) >= 2 && draft.points.length < 4000) {
        draft.points.push(clampPoint(at));
      }
    } else if (draft.kind === "shape" && event.shiftKey) {
      // Equal sides on screen: a square, a circle, a regular polygon.
      const side = Math.max(Math.abs(dx), Math.abs(dy));
      draft.points[1] = clampPoint([gesture.start[0] + (Math.sign(dx) || 1) * side / canvas.width,
        gesture.start[1] + (Math.sign(dy) || 1) * side / canvas.height]);
    } else {
      draft.points[1] = clampPoint(at);
    }
  }
  scheduleRender();
});

const endGesture = () => {
  const current = gesture;
  gesture = null;
  if (!current?.type) return;
  if (current.type === "draw") {
    const draft = current.draft;
    const tooSmall = !current.moved && ["arrow", "line", "freehand", "shape", "measure"].includes(draft.kind);
    if (!tooSmall) {
      if (draft.kind === "freehand") {
        draft.points = simplify(draft.points.map(clampPoint), 3 * (window.devicePixelRatio || 1), canvas.width, canvas.height);
        if (draft.points.length < 2) return scheduleRender();
      }
      // Ring, spotlight, arrow and line ends dropped on a followed player's feet follow that player.
      const points = ["freehand", "shape", "measure"].includes(draft.kind) ? draft.points : draft.points.map(snapPoint);
      const item = placeNew(newItem(draft.kind, points, { from: draft.show.from, to: draft.show.to, style: draft.style, geometry: draft.geometry }));
      if (isFlat(item)) item.at = frameNow();
      doc.add(item);
      select(item.id);
    }
  } else if (current.type === "marquee") {
    const [ax, ay] = toPixels(current.start);
    const [bx, by] = toPixels(current.end);
    const [x0, x1, y0, y1] = [Math.min(ax, bx), Math.max(ax, bx), Math.min(ay, by), Math.max(ay, by)];
    if (x1 - x0 < 3 && y1 - y0 < 3) return scheduleRender(); // a plain click on empty picture: nothing selected
    // Every drawing on screen the box touches.
    const caught = shown().filter((item) => visibleAt(item, currentTime())).filter((item) => {
      const [l, t, r, b] = itemBounds(item);
      return r >= x0 && l <= x1 && b >= y0 && t <= y1;
    }).map((item) => item.id);
    selectMany([...new Set([...current.keep, ...caught])]);
  } else if (current.type === "group") {
    if (current.moved) moveGroup(current);
  } else if (current.type === "box") {
    followFromBox(current.start, current.end);
  } else if (current.type === "resize") {
    const same = current.box.every((value, i) => Math.abs(value - current.base[i]) < 1e-4);
    if (!same) {
      keyTrack(current.trackId, current.box.map((v) => Math.round(v * 1e5) / 1e5))
        .then(() => trackStatus("Box fitted to the player on this frame; the rest of the clip is tracked again from it."));
    }
  } else if (current.preview && (current.moved || (current.type !== "move" && current.type !== "handle"))) {
    applyEdit(current); // a plain click on a drawing only selects it: no edit, and no new keyframe on a followed player
  }
  scheduleRender();
};
// Several drawings dragged together, as one undo step. Points linked to a player stay with the player;
// a board token's drag sets its move at this moment, as when it is dragged alone.
function moveGroup({ bases, previews }) {
  const changed = new Map(bases.map((base) => [base.id, previews[base.id]]).filter(([, preview]) => preview));
  let skipped = 0;
  doc.commit((items) => items.map((original) => {
    const preview = changed.get(original.id);
    if (!preview) return original;
    if (original.points.some(isLinked)) { skipped += 1; return original; }
    if (isFlat(original)) return { ...rebased(original), points: preview.points };
    if (original.kind === "token" && original.on !== undefined) return setMove(original, boardSeconds(original), preview.points[0]);
    return { ...original, points: preview.points };
  }));
  if (skipped) trackStatus(`${skipped} drawing${skipped === 1 ? " follows a player, so it stayed" : "s follow players, so they stayed"} with ${skipped === 1 ? "them" : "their players"}.`);
}

// The pointer for what is under it, as in a design tool: a two-headed arrow on a size handle or a box corner,
// the four-headed move arrow on a drawing or a point that moves it whole.
const CORNER_CURSORS = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize" };
function cursorAt(at) {
  const selected = selectedId ? shownItem(selectedId) : null;
  const handle = selected && nearHandle(selected, at);
  const corner = nearBoxCorner(at);
  if (corner && (!handle || corner.distance <= Math.hypot(...toPixels(handle.point).map((v, i) => v - toPixels(at)[i])))) return CORNER_CURSORS[corner.corner];
  if (handle) {
    if (handle.index === "r") return "ew-resize";
    if (handle.index === "h") return "ns-resize";
    // The centre of a ring, spotlight or text moves it whole; an end or a corner of a line or zone is a point to place.
    return ["ring", "spotlight", "text"].includes(selected.kind) ? "move" : "crosshair";
  }
  const [x, y] = toPixels(at);
  return itemAt(shown(), x, y, canvas.width, canvas.height, currentTime(), measure) ? "move" : "";
}

// A drag on a drawing: plain points move; a point linked to a player corrects
// that player on this frame (a keyframe), and a fixed point dropped on a
// followed player's feet starts following them.
function applyEdit({ type, id, index, base, preview, end: pointerAt }) {
  const original = rebased(doc.find(id));
  if (!original) return;
  if (original.kind === "text") { // its one handle moves it too
    // Text that follows a player keeps following: a drag changes where it sits next to them (the player's
    // box is not touched). Unlinked text dropped on a followed player starts following them.
    const [dx, dy] = [preview.points[0][0] - base.points[0][0], preview.points[0][1] - base.points[0][1]];
    const point = original.points[0];
    const next = isLinked(point)
      ? { ...point, dx: Math.round((point.dx + dx) * 1e5) / 1e5, dy: Math.round((point.dy + dy) * 1e5) / 1e5 }
      : linkToPlayerAt(preview.points[0], pointerAt || preview.points[0]) || preview.points[0];
    doc.replace({ ...original, points: [next] });
    if (!isLinked(point) && isLinked(next)) trackStatus(`The text now follows ${playerName(trackById(next.track))}. Drag it to change where it sits; Stop following keeps it where it is.`);
    return;
  }
  if (type === "handle" && (index === "r" || index === "h")) {
    doc.replace({ ...original, geometry: preview.geometry });
    return;
  }
  if (type === "handle") {
    const point = original.points[index];
    const [dx, dy] = [preview.points[index][0] - base.points[index][0], preview.points[index][1] - base.points[index][1]];
    if (isLinked(point)) return correctTrack(point.track, dx, dy);
    const snapped = PITCH_KINDS.has(original.kind) ? preview.points[index] : snapPoint(preview.points[index]); // on the grass, never on a player
    doc.replace({ ...original, points: original.points.map((each, i) => (i === index ? snapped : each)) });
    return;
  }
  const linked = [...linkedTracks(original)];
  if (original.kind === "token" && original.on !== undefined) {
    const seconds = boardSeconds(original);
    doc.replace(setMove(original, seconds, preview.points[0]));
    if (seconds >= 0.05) trackStatus(`Move set at ${seconds.toFixed(1)} s into the board: the token glides there. Drag it at the board's start to change where it begins.`);
  } else if (!linked.length) {
    doc.replace({ ...original, points: preview.points });
  } else if (linked.length === 1 && original.points.every(isLinked)) {
    correctTrack(linked[0], preview.points[0][0] - base.points[0][0], preview.points[0][1] - base.points[0][1]);
  } else {
    trackStatus("This drawing's corners follow players. Drag one corner to correct that player on this frame.");
  }
}

canvas.addEventListener("pointerup", () => {
  if (!calib) return endGesture();
  calib.drag = null;
  return renderCalibration();
});
canvas.addEventListener("pointercancel", () => { gesture = null; if (calib) calib.drag = null; scheduleRender(); });
canvas.addEventListener("pointerleave", () => { if (calib) { pointer = null; scheduleRender(); } });
canvas.addEventListener("dblclick", (event) => {
  if (tool === "zone") { finishZone(); return; } // the double-click's second corner is a repeat, dropped there
  if (tool !== "select") return;
  const [x, y] = toPixels(toFraction(event));
  const hit = itemAt(shown(), x, y, canvas.width, canvas.height, currentTime(), measure);
  if (hit?.kind === "text") openText(hit.points[0], hit);
});

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------
const TOOL_KEYS = { v: "select", r: "ring", s: "spotlight", a: "arrow", l: "line", f: "freehand", t: "text", z: "zone", p: "follow", k: "token", g: "shape", o: "offside", m: "measure" };
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setMenu(false);
  if (!clip) return;
  const typing = event.target.closest?.("input, textarea, select, [contenteditable]");
  if (typing) return;
  const command = event.ctrlKey || event.metaKey;
  const key = event.key.toLowerCase();
  if (calib) {
    if (event.key === "Escape") closeCalibration();
    else if ((event.key === "Delete" || event.key === "Backspace") && calibPair(calib.selected)) { event.preventDefault(); removeCalibrationPoint(); }
    return;
  }
  if (command && key === "z") { event.preventDefault(); event.shiftKey ? doc.redo() : doc.undo(); return; }
  if (command && key === "y") { event.preventDefault(); doc.redo(); return; }
  if (command || event.altKey) return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    step(event.key === "ArrowLeft" ? -1 : 1, event.shiftKey);
  } else if (event.key === " " && !event.target.closest("button")) {
    event.preventDefault();
    togglePlay();
  } else if ((event.key === "Delete" || event.key === "Backspace") && (selectedId || selectedIds.length || selectedFreeze !== null)) {
    event.preventDefault();
    removeSelected();
  } else if ((event.key === "Delete" || event.key === "Backspace") && selectedPart !== null) {
    event.preventDefault();
    removePart(selectedPart);
  } else if (key === "x" && !event.shiftKey) {
    event.preventDefault();
    splitHere();
  } else if (event.key === "Enter" && zoneDraft) {
    event.preventDefault();
    finishZone();
  } else if (event.key === "Escape") {
    if (zoneDraft) zoneDraft = null;
    else if (selectedPart !== null) selectPart(null);
    else if (selectedFreeze !== null) { selectedFreeze = null; renderFreezes(); renderInspector(); }
    else select(null);
    scheduleRender();
  } else if (TOOL_KEYS[key] && !event.shiftKey) {
    setTool(TOOL_KEYS[key]);
  }
});

// ---------------------------------------------------------------------------
// Screenshot: the frame at full size with its drawings
// ---------------------------------------------------------------------------
const screenshot = async (button) => {
  if (playing) pause();
  const format = $("[data-shot-format]").value;
  const shot = document.createElement("canvas");
  shot.width = video.videoWidth || clip.width;
  shot.height = video.videoHeight || clip.height;
  const context = shot.getContext("2d");
  const board = boardNow();
  if (board) drawBoard(context, shot.width, shot.height, board.background);
  else context.drawImage(video, 0, 0, shot.width, shot.height);
  drawItems(context, projectItems(shown(), board ? null : pitchHere()?.calibration), shot.width, shot.height, currentTime());
  const type = format === "jpeg" ? "image/jpeg" : "image/png";
  const blob = await new Promise((resolve) => shot.toBlob(resolve, type, 0.92));
  const name = `${clip.name} frame ${frameNow() + 1}.${format === "jpeg" ? "jpg" : "png"}`;
  button.disabled = true;
  try { await saveImage(blob, name); } finally { button.disabled = false; }
};

// ---------------------------------------------------------------------------
// Export video (M4). The page draws each overlay with the same code as the
// preview, at the clip's own size, and sends the drawn pixels wherever the
// drawings change (raw, cropped: picture encoding stalls in a hidden window); the engine lays them over the frames, holds the freezes (silent)
// and encodes the clip into the user's VizorPlay folder.
// ---------------------------------------------------------------------------
let exporting = null; // {session, job, cancelled}
const exportPanel = $("[data-export-panel]");
const exportStatus = (text, share) => {
  exportPanel.hidden = false;
  $("[data-export-text]").textContent = text;
  $("[data-export-progress]").value = Math.max(0, Math.min(1, share));
};
const endExport = (text) => {
  exporting = null;
  $("[data-export]").disabled = false;
  $("[data-export-cancel]").disabled = false;
  if (text) {
    exportStatus(text, 0);
    setTimeout(() => { if (!exporting) exportPanel.hidden = true; }, 4000);
  } else {
    exportPanel.hidden = true;
  }
};
const DRAWING_SHARE = 0.35; // of the progress bar: drawing overlays, then rendering

/** What the overlay looks like on output frame `n`: a key that changes only when the picture does. */
const overlayKey = (value, n, pitch = null) => {
  const t = n / clip.fps;
  const cut = cutClip(clip, value.parts);
  const frame = cutToSource(outputToSource(t, cut, value.freezes).frame, value.parts, clip.frames);
  const board = boardAt(value, cut, t);
  const shown = [];
  itemsAt(value, cut, t).forEach((item) => {
    const state = animation(item, t);
    const placed = state && placeFlat(resolveItem(placedAt(value, cut, item, t), value.tracks || [], frame), pitch, frame);
    if (placed && !placed.offPitch) shown.push(placed, state);
  });
  const key = JSON.stringify([board ? [board.atFrame, board.background] : null, ...shown.map((entry) => (entry.points ? [entry.id, entry.points] : entry))]);
  return { t, board, shown, key, frame };
};

// Overlays go in batches: every request is a new connection to the engine, and
// thousands of them in a few seconds can run Windows out of local ports.
const BATCH_BYTES = 8_000_000;
const BATCH_FRAMES = 150;
const sendBatch = async (sessionId, entries) => {
  // A patch lists the tiles that changed over the overlay before it; a crop is a whole new overlay.
  const header = new TextEncoder().encode(JSON.stringify(entries.map(({ frame, crop, tiles }) => (tiles
    ? { frame, tiles: tiles.map((tile) => [tile.x, tile.y, tile.w, tile.h]) }
    : { frame, box: crop ? [crop.x, crop.y, crop.w, crop.h] : null }))));
  const size = new Uint8Array(4);
  new DataView(size.buffer).setUint32(0, header.length);
  const body = new Blob([size, header, ...entries.flatMap((entry) => (entry.tiles ? entry.tiles.map((tile) => tile.pixels) : entry.crop ? [entry.crop.pixels] : []))]);
  const response = await fetch(`/api/editor-exports/${sessionId}/overlays`, {
    method: "POST", headers: { "Content-Type": "application/octet-stream" }, body,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
};

const exportVideo = async () => {
  if (exporting) return;
  if (playing) pause();
  finishText();
  await save();
  if (dirty) {
    showSaveError("Save the drawings first; the export uses the saved version.", "Video");
    return;
  }
  const run = { session: null, job: null, cancelled: false };
  exporting = run;
  $("[data-export]").disabled = true;
  exportStatus("Starting export...", 0);
  try {
    const value = doc.value; // the saved document; edits made during the export are not in it
    ({ export: run.session } = await projectRequest(`${editorPath()}/export`, {}));
    const { id, frames, width, height } = run.session;
    const exportPitch = clipPitchTrack(value, aspect()); // flat drawings, as on screen
    const sheet = document.createElement("canvas");
    sheet.width = width;
    sheet.height = height;
    const context = sheet.getContext("2d", { willReadFrequently: true });
    let previous = null;
    let held = null; // the whole overlay the engine holds now (RGBA), for patches; null when clear
    let batch = [];
    let batchBytes = 0;
    let sending = Promise.resolve();
    const flush = async () => {
      if (!batch.length) return;
      const entries = batch;
      batch = [];
      batchBytes = 0;
      await sending; // one upload at a time, in order; the next batch is drawn meanwhile
      sending = sendBatch(id, entries);
    };
    for (let n = 0; n < frames; n += 1) {
      if (run.cancelled) return;
      const { board, shown, key, frame } = overlayKey(value, n, exportPitch);
      if (key !== previous) {
        previous = key;
        let entry = { frame: n, crop: null };
        if (shown.length || board) {
          context.clearRect(0, 0, width, height);
          if (board) drawBoard(context, width, height, board.background); // covers the frozen frame
          for (let index = 0; index < shown.length; index += 2) drawItem(context, projectItems([shown[index]], board ? null : exportPitch?.at(frame)?.calibration)[0], width, height, shown[index + 1]);
          const pixels = context.getImageData(0, 0, width, height).data;
          // Moving tokens change a few places: send those tiles over the overlay already held (M8).
          const tiles = held ? changedTiles(held, pixels, width, height) : null;
          if (tiles) entry = tiles.length ? { frame: n, tiles } : null;
          else entry = { frame: n, crop: cropDrawn(pixels, width, height) };
          held = entry?.crop === null ? null : pixels;
        } else {
          held = null;
        }
        if (entry) {
          batch.push(entry);
          batchBytes += entry.tiles ? entry.tiles.reduce((sum, tile) => sum + tile.pixels.length, 0) : entry.crop ? entry.crop.pixels.length : 0;
        }
        if (batchBytes >= BATCH_BYTES || batch.length >= BATCH_FRAMES) await flush();
      }
      if (n % 10 === 0) exportStatus(`Drawing overlays: frame ${n + 1} of ${frames}`, (n / frames) * DRAWING_SHARE);
    }
    await flush();
    await sending;
    if (run.cancelled) return;
    ({ job: run.job } = await projectRequest(`/api/editor-exports/${id}/render`, { name: `${clip.name} annotated` }));
    for (;;) {
      const { job } = await projectRequest(`/api/editor-jobs/${run.job.id}`);
      if (job.status === "running") {
        const share = DRAWING_SHARE + job.progress * (1 - DRAWING_SHARE);
        exportStatus(run.stopping ? "Cancelling..." : `Rendering video: ${Math.round(job.progress * 100)}%`, share);
        await new Promise((resolve) => setTimeout(resolve, 400));
        continue;
      }
      if (job.status === "done") {
        showSaved(job.result.saved, "Video");
        endExport();
      } else if (job.status === "cancelled") {
        endExport("Export cancelled.");
      } else {
        showSaveError(job.error || "The export stopped.", "Video");
        endExport();
      }
      return;
    }
  } catch (error) {
    if (!run.cancelled) {
      showSaveError(error.message, "Video");
      if (run.session && !run.job) fetch(`/api/editor-exports/${run.session.id}/cancel`, { method: "POST" }).catch(() => {});
      endExport();
    }
  }
};

const cancelExport = async () => {
  const run = exporting;
  if (!run) return;
  $("[data-export-cancel]").disabled = true;
  run.stopping = true;
  exportStatus("Cancelling...", $("[data-export-progress]").value);
  if (run.job) {
    // The render notices within a frame; the poll above then reports it.
    await projectRequest(`/api/editor-jobs/${run.job.id}/cancel`, {}).catch(() => {});
    return;
  }
  run.cancelled = true;
  if (run.session) await projectRequest(`/api/editor-exports/${run.session.id}/cancel`, {}).catch(() => {});
  endExport("Export cancelled.");
};

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
const wire = () => {
  document.querySelectorAll("[data-tool]").forEach((button) => { button.onclick = () => setTool(button.dataset.tool); });
  wireShapeMenu();
  document.querySelectorAll("[data-step]").forEach((button) => { button.onclick = () => step(Number(button.dataset.step)); });
  $("[data-freeze]").onclick = freezeHere;
  $("[data-split]").onclick = splitHere;
  $("[data-board]").onclick = () => openCalibration("board");
  $("[data-pitch]").onclick = () => openCalibration("pitch");
  $("[data-calib-save]").onclick = savePitch;
  $("[data-calib-forget]").onclick = forgetPitch;
  $("[data-pitch-lines]").onclick = () => {
    pitchLines = !pitchLines;
    renderPitchSaved();
    if (pitchLines && !pitchHere()) goToPitchFrame();
    scheduleRender();
  };
  $("[data-pitch-go]").onclick = goToPitchFrame;
  $("[data-pitch-follow]").onclick = followCamera;
  $("[data-pitch-stop]").onclick = stopCamera;
  $("[data-pitch-next]").onclick = goToPitchCheck;
  $("[data-calib-find]").onclick = findPlayers;
  $("[data-calib-empty]").onclick = () => makeBoard(null);
  $("[data-calib-remove]").onclick = removeCalibrationPoint;
  $("[data-calib-close]").onclick = closeCalibration;
  $("[data-calib-stop]").onclick = stopCalibrationJob;
  $("[data-calib-download]").onclick = downloadModel;
  $("[data-calib-target]").onchange = renderCalibration;
  $("[data-anim-in]").onchange = (event) => setAnimation({ animate: event.target.value });
  $("[data-anim-out]").onchange = (event) => setAnimation({ animateOut: event.target.value });
  $("[data-anim-seconds]").onchange = (event) => {
    const value = Number(event.target.value);
    if (Number.isFinite(value) && value >= 0.05 && value <= 5) setAnimation({ animSeconds: value });
    else renderInspector();
  };
  $("[data-ease]").onchange = (event) => setAnimation({ ease: event.target.value });
  $("[data-pulse]").onchange = (event) => setAnimation({ pulse: event.target.checked });
  $("[data-play]").onclick = togglePlay;
  const scrub = $("[data-scrub]");
  scrub.oninput = () => seekOutput(Number(scrub.value));
  $("[data-undo]").onclick = () => doc.undo();
  $("[data-redo]").onclick = () => doc.redo();
  $("[data-screenshot]").onclick = (event) => screenshot(event.currentTarget);
  $("[data-export]").onclick = exportVideo;
  $("[data-export-cancel]").onclick = cancelExport;
  $("[data-from]").onchange = (event) => setTiming("from", Number(event.target.value));
  $("[data-to]").onchange = (event) => setTiming("to", Number(event.target.value));
  $("[data-from-here]").onclick = () => setTiming("from", currentTime());
  $("[data-to-here]").onclick = () => setTiming("to", currentTime());
  $("[data-delete]").onclick = removeSelected;
  $("[data-follow-start]").onclick = () => followSelected("start");
  $("[data-follow-confirm]").onclick = () => followSelected("confirm");
  $("[data-follow-next]").onclick = () => followSelected("next");
  $("[data-follow-retrack]").onclick = () => followSelected("retrack");
  $("[data-follow-fit]").onclick = () => followSelected("fit");
  $("[data-follow-stop]").onclick = () => followSelected("stop");
  $("[data-follow-label]").onchange = (event) => {
    const item = doc.find(selectedId);
    const ids = item ? [...linkedTracks(item)] : [];
    if (ids.length !== 1) return;
    const label = event.target.value.trim().slice(0, 40);
    updateTrack(ids[0], (track) => { const next = { ...track }; if (label) next.label = label; else delete next.label; return next; });
  };
  for (const name of ["seeked", "loadeddata"]) video.addEventListener(name, scheduleRender);
  new ResizeObserver(fitCanvas).observe(stage);
  window.addEventListener("resize", fitCanvas);
  doc.onChange(() => {
    refreshTiming();
    renderPitchSaved();
    if (selectedId && !doc.find(selectedId)) selectedId = null;
    selectedIds = selectedIds.filter((id) => doc.find(id));
    if (selectedFreeze !== null && !doc.freezes.some((f) => f.atFrame === selectedFreeze)) selectedFreeze = null;
    if (playing) pause();
    outTime = clampTime(outTime);
    showFrame(); // the parts may have changed what the playhead shows
    renderParts();
    renderFreezes();
    renderPlayers();
    $("[data-undo]").disabled = !doc.canUndo;
    $("[data-redo]").disabled = !doc.canRedo;
    renderInspector();
    scheduleRender();
    queueSave();
  });
};

const start = async () => {
  try {
    if (!projectId) throw new Error("Open a saved project first, then come back to Annotate.");
    if (!clipId) return await startLibrary();
    if (!/^[a-f0-9]{32}$/.test(clipId)) throw new Error("This clip link is not valid. Open the clip from Annotate.");
    const { project } = await projectRequest(`/api/projects/${encodeURIComponent(projectId)}`);
    rememberProject(project);
    showClipStrip($("[data-clip-strip]"), projectId, clipId);
    const opened = await projectRequest(`/api/editor/${encodeURIComponent(projectId)}/${encodeURIComponent(clipId)}`);
    clip = opened.clip;
    doc = createDocument(opened.annotations);
    refreshTiming();
    renderPitchSaved();
    document.title = `VizorPlay - Annotate ${clip.name}`;
    $("[data-annotate-title]").textContent = clip.name;
    $("[data-annotate-changed]").hidden = !opened.changed;
    $("[data-annotate-workspace]").style.setProperty("--clip-ratio", String(clip.width / clip.height));
    await new Promise((resolve, reject) => {
      video.addEventListener("loadeddata", resolve, { once: true });
      video.addEventListener("error", () => reject(new Error("The clip's video could not be played.")), { once: true });
      video.src = opened.url;
    });
    $("[data-annotate-workspace]").hidden = false;
    wire();
    fitCanvas();
    setTool("select");
    renderParts();
    renderFreezes();
    renderPlayers();
    seekOutput(0);
    status.textContent = `${clip.width}×${clip.height} · ${clip.fps} fps`;
    setSaveStatus("Saved locally");
  } catch (error) {
    status.textContent = "Clip needs attention";
    const output = $("[data-annotate-error]");
    output.textContent = error.message;
    output.hidden = false;
  }
};

// No clip chosen: the Annotate tab lists the project's sessions.
async function startLibrary() {
  const { project } = await projectRequest(`/api/projects/${encodeURIComponent(projectId)}`);
  rememberProject(project);
  document.body.classList.add("annotate-library-mode");
  document.title = "VizorPlay - Annotate";
  $("[data-annotate-title]").textContent = "Annotate";
  await showLibrary($("[data-library]"), projectId, (text) => { status.textContent = text; });
}
start();
