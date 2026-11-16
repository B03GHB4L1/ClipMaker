// The analyst editor: draw on a clip copied into the project
// (docs/TELESTRATION_PLAN.md, M1). Drawings are fixed in place for now;
// tracking (M3) will link their points to players.
import { projectRequest, newProject, rememberProject } from "./projects.js";
import { saveImage } from "./save-clip.js";
import { drawItem, drawItems, handlesFor, itemAt, styleOf, textFont, DEFAULT_STYLE, PATTERNS } from "./annotate/shapes.js";
import { createDocument, dragHandle, moveItem, newItem, ringGeometry, simplify, clampPoint } from "./annotate/document.js";
import { freezeStart, outputToSource, playStart, setFreeze, stops, totalSeconds } from "./annotate/timeline.js";
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
let doc;
let tool = "select";
let selectedId = null;
let gesture = null; // the drag or drawing in progress
let zoneDraft = null; // corners of a zone being drawn
let pointer = null; // last pointer position in fractions, for the zone preview
let textEdit = null; // {id | null, point}
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
  back.href = from && from.origin === location.origin && !from.pathname.endsWith("/annotate.html")
    ? from.pathname + from.search
    : `/analysis.html?view=analyst&project=${encodeURIComponent(projectId)}`;
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
const total = () => totalSeconds(clip, doc.freezes);
const source = () => outputToSource(outTime, clip, doc.freezes);
const formatTime = (seconds) => {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(2).padStart(5, "0")}`;
};
const clampTime = (t) => Math.min(total(), Math.max(0, t));
// Show the frame for output time `outTime`: the middle of that frame, so the decoder shows it and not its neighbour.
const showFrame = () => {
  const frame = source().frame;
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
  const list = stops(clip, doc.freezes);
  const target = direction > 0 ? list.find((t) => t > outTime + 1e-6) : [...list].reverse().find((t) => t < outTime - 1e-6);
  seekOutput(target ?? (direction > 0 ? list[list.length - 1] : 0));
};

const sortedFreezes = () => [...doc.freezes].sort((a, b) => a.atFrame - b.atFrame);
const play = () => {
  if (outTime >= total() - 1e-3) outTime = 0;
  const at = source();
  const freezes = sortedFreezes();
  if (at.freeze !== null) {
    const index = freezes.findIndex((f) => f.atFrame === at.freeze);
    run = { held: freezes.slice(0, index).reduce((sum, f) => sum + f.seconds, 0), next: index,
      freeze: { start: outTime, end: at.freezeStart + freezes[index].seconds, wall: performance.now() } };
    video.pause();
    showFrame();
  } else {
    const index = freezes.findIndex((f) => f.atFrame > at.frame);
    const next = index < 0 ? freezes.length : index;
    run = { held: freezes.slice(0, next).reduce((sum, f) => sum + f.seconds, 0), next, freeze: null };
    video.currentTime = at.time;
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
    if (next && video.currentTime >= next.atFrame / fps() - 1e-4) {
      video.pause();
      outTime = freezeStart(next.atFrame, clip, freezes);
      run.freeze = { start: outTime, end: outTime + next.seconds, wall: now };
      video.currentTime = (next.atFrame + 0.5) / fps();
    } else {
      outTime = Math.min(total(), video.currentTime + run.held);
      if (video.ended && !next) {
        outTime = total();
        pause();
      }
    }
  }
  render();
  showTime();
  if (playing) requestAnimationFrame(tick);
}

const showTime = () => {
  const at = source();
  const frozen = at.freeze !== null ? ' · <span class="is-frozen">frozen</span>' : "";
  $("[data-time]").innerHTML = `${formatTime(outTime)} / ${formatTime(total())} · frame ${at.frame + 1}/${clip.frames}${frozen}`;
  const scrub = $("[data-scrub]");
  scrub.max = String(total());
  if (document.activeElement !== scrub) scrub.value = String(outTime);
  $("[data-play]").classList.toggle("is-playing", playing);
  $("[data-play]").setAttribute("aria-label", playing ? "Pause" : "Play");
  $("[data-lane-head]").style.left = `${(outTime / total()) * 100}%`;
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
const frameNow = () => source().frame;
const shown = () => doc.items.map((item) => resolveItem(item, tracks(), frameNow()));
const shownItem = (id) => { const item = doc.find(id); return item ? resolveItem(item, tracks(), frameNow()) : null; };
const playerName = (track) => track.label || `Player ${tracks().indexOf(track) + 1}`;

const boxPixels = ([fx, fy, w, h]) => [(fx - w / 2) * canvas.width, (fy - h) * canvas.height, w * canvas.width, h * canvas.height];
const drawPlayerBox = (track) => {
  const at = boxAt(track, frameNow());
  if (!at) return;
  const [x, y, w, h] = boxPixels(at.box);
  ctx.save();
  ctx.setLineDash([5, 4]);
  ctx.lineWidth = 1.5 * (window.devicePixelRatio || 1);
  ctx.strokeStyle = at.held || at.state === REVIEW ? "#e8a317" : at.state === 1 ? "#c8f135" : "rgba(255, 255, 255, 0.7)";
  ctx.strokeRect(x, y, w, h);
  ctx.restore();
};
// Where a point dropped near a followed player's feet links to them.
const snapPoint = (point) => {
  const [x, y] = toPixels(point);
  for (const track of tracks()) {
    const at = boxAt(track, frameNow());
    if (!at) continue;
    const [fx, fy] = toPixels(at.box);
    if (Math.hypot(fx - x, fy - y) <= handleRadius() * 2.2) return { track: track.id, dx: 0, dy: 0 };
  }
  return point;
};

const render = () => {
  if (!clip) return;
  const { w, h } = size();
  ctx.clearRect(0, 0, w, h);
  const time = currentTime();
  const items = shown().map((item) => (gesture?.preview && item.id === gesture.preview.id ? gesture.preview : item));
  drawItems(ctx, items, w, h, time);
  const original = doc.find(selectedId);
  if (original) linkedTracks(original).forEach((id) => { const track = trackById(id); if (track) drawPlayerBox(track); });
  if (["ring", "spotlight", "arrow", "line", "zone"].includes(tool)) {
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
  if (draft) drawItem(ctx, draft, w, h);
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
    handlesFor(selected).forEach(({ point }) => drawHandle(point));
  }
};

function drawHandle(point, strong = false) {
  const [x, y] = toPixels(point);
  ctx.save();
  ctx.beginPath();
  ctx.arc(x, y, handleRadius(), 0, Math.PI * 2);
  ctx.fillStyle = strong ? "#c8f135" : "#ffffff";
  ctx.strokeStyle = "#171817";
  ctx.lineWidth = 2;
  ctx.fill();
  ctx.stroke();
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
  select: "Click a drawing to select it; drag it or its handles. Delete removes it.",
  ring: "Drag from a player's feet outwards to size the ring.",
  spotlight: "Drag from a player's feet outwards; drag the top handle to change the beam.",
  arrow: "Drag from where the arrow starts to where it points.",
  line: "Drag to draw a line.",
  freehand: "Hold and draw.",
  text: "Click where the text goes, type, then press Enter (Shift+Enter for a new line).",
  zone: "Click each corner. Finish with Enter, a double-click or a click on the first corner.",
  follow: "Drag a box around a player, head to boots. A ring follows them; drag it back if it slips.",
};
const FOLLOWABLE = ["ring", "spotlight", "text"];
let followTarget = null; // the drawing "Follow player" will link, or null for a new ring

const setTool = (next) => {
  finishText();
  zoneDraft = null;
  tool = next;
  document.querySelectorAll("[data-tool]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.tool === tool)));
  canvas.dataset.tool = tool;
  $("[data-hint]").textContent = HINTS[tool];
  if (tool !== "select") selectedId = null;
  renderInspector();
  scheduleRender();
};

const select = (id) => {
  selectedId = id;
  renderInspector();
  scheduleRender();
};

const KIND_NAMES = { ring: "Ring", spotlight: "Spotlight", arrow: "Arrow", line: "Line", freehand: "Freehand", text: "Text", zone: "Zone" };

const FIELDS = {
  stroke: { label: "Line colour", type: "color" },
  fill: { label: "Fill colour", type: "color" },
  pattern: { label: "Fill", type: "select", options: PATTERNS },
  color: { label: "Text colour", type: "color" },
  background: { label: "Background", type: "color", transparent: true },
  width: { label: "Thickness", type: "range", min: 1, max: 20, step: 1 },
  fillOpacity: { label: "Fill strength", type: "range", min: 0, max: 1, step: 0.05 },
  size: { label: "Text size", type: "range", min: 12, max: 120, step: 2 },
  dashed: { label: "Dashed", type: "checkbox" },
  bold: { label: "Bold", type: "checkbox" },
};

const updateStyle = (key, value) => {
  const item = doc.find(selectedId);
  if (item) {
    doc.replace({ ...item, style: { ...item.style, [key]: value } });
  } else {
    const kind = DEFAULT_STYLE[tool] ? tool : null;
    if (kind) toolStyle[kind][key] = value;
  }
};

const renderInspector = () => {
  const item = selectedId ? doc.find(selectedId) : null;
  const kind = item ? item.kind : DEFAULT_STYLE[tool] ? tool : null; // select and follow have no drawing style
  const fields = $("[data-style-fields]");
  fields.replaceChildren();
  $("[data-inspector-title]").textContent = item ? `${KIND_NAMES[item.kind]} settings` : kind ? `New ${KIND_NAMES[kind].toLowerCase()}` : "Nothing selected";
  if (!kind) {
    fields.append(Object.assign(document.createElement("p"), { className: "annotate-muted", textContent: "Choose a tool, or select a drawing to change it." }));
  } else {
    const style = item ? styleOf(item) : toolStyle[kind];
    Object.keys(DEFAULT_STYLE[kind]).forEach((key) => {
      const spec = FIELDS[key];
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
        input.oninput = () => {
          // Live preview while dragging the slider; one undo step on release.
          const current = doc.find(selectedId);
          if (current) {
            gesture = { preview: { ...current, style: { ...current.style, [key]: Number(input.value) } } };
            scheduleRender();
          }
        };
        input.onchange = () => { gesture = null; updateStyle(key, Number(input.value)); };
        label.append(`${spec.label} `, input);
      }
      fields.append(label);
    });
  }
  renderFollowPanel(item);
  const timing = $("[data-timing]");
  timing.hidden = !item;
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
    $("[data-pulse-row]").hidden = !["ring", "spotlight", "zone"].includes(item.kind);
    $("[data-pulse]").checked = Boolean(item.show.pulse);
  }
  renderList();
};

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
          : at.state === REVIEW ? `${playerName(track)}: check this frame. Still right, or drag the drawing back onto the player.`
            : at.state === 1 ? `${playerName(track)}: placed by you on this frame.`
              : `Following ${playerName(track)}.`;
    $("[data-follow-label]").value = track.label || "";
    $("[data-follow-label]").placeholder = playerName(track);
    $("[data-follow-confirm]").disabled = !at || (!at.held && at.state !== REVIEW);
    $("[data-follow-next]").disabled = !nextCheck(track);
  }
}

const renderList = () => {
  const list = $("[data-list]");
  $("[data-count]").textContent = `(${doc.items.length})`;
  list.replaceChildren(...doc.items.map((item) => {
    const entry = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = item.id === selectedId ? "is-selected" : "";
    const label = item.kind === "text" ? `Text: ${item.text.split("\n")[0].slice(0, 24)}` : KIND_NAMES[item.kind];
    button.textContent = `${label} · ${item.show.from.toFixed(2)}–${item.show.to.toFixed(2)}s`;
    button.onclick = () => {
      if (tool !== "select") setTool("select");
      if (currentTime() < item.show.from || currentTime() > item.show.to) seekOutput(item.show.from);
      select(item.id);
    };
    entry.append(button);
    return entry;
  }));
};

const removeSelected = () => {
  if (!selectedId) return;
  const id = selectedId;
  doc.commitDocument((value) => pruneTracks({ ...value, items: value.items.filter((item) => item.id !== id) }));
  select(null);
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
const endFrame = (item) => outputToSource(item.show.to, clip, doc.freezes).frame;
const followLimit = (trackId) => {
  const frames = doc.items.filter((item) => linkedTracks(item).has(trackId)).map(endFrame);
  return Math.min(clip.frames - 1, Math.max(frameNow(), ...frames));
};

async function startTracking(trackId, start, box, limit = followLimit(trackId)) {
  const track = trackById(trackId);
  if (!track) return;
  const end = spanEnd(track, start, Math.min(clip.frames - 1, limit));
  if (end <= start) return renderPlayers();
  await cancelTracking(trackId, true);
  try {
    const { job } = await projectRequest(`${editorPath()}/track`, { from_frame: start, to_frame: end, box });
    jobs.set(trackId, { id: job.id, progress: 0, start, end });
    trackStatus("");
    renderPlayers();
    pollTracking(trackId, job.id);
  } catch (error) {
    trackStatus(`Could not follow the player: ${error.message}`, true);
  }
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
  const entry = jobs.get(trackId);
  if (!entry) return;
  jobs.delete(trackId);
  try { await projectRequest(`/api/editor-jobs/${entry.id}/cancel`, {}); } catch { /* it may have just finished */ }
  if (!quiet) trackStatus("Tracking cancelled.");
  renderPlayers();
}

// The analyst moved the player's drawing on this frame: that frame becomes a
// keyframe and only the span after it is tracked again.
const correctTrack = (trackId, dx, dy) => {
  const track = trackById(trackId);
  const frame = frameNow();
  const at = track && boxAt(track, frame);
  if (!at) return;
  const box = [at.box[0] + dx, at.box[1] + dy, at.box[2], at.box[3]];
  const limit = Math.max(lastFrame(track), followLimit(trackId));
  updateTrack(trackId, (current) => setKeyframe(current, frame, box));
  startTracking(trackId, frame, box, limit);
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
  if (action === "confirm" && at) updateTrack(track.id, (current) => setKeyframe(current, frame, at.box));
  if (action === "next") {
    const run = nextCheck(track);
    if (run) seekOutput(playStart(run[0], clip, doc.freezes));
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
  const box = [(x0 + x1) / 2, y1, x1 - x0, y1 - y0].map((v) => Math.round(Math.min(1.5, Math.max(-0.5, v)) * 1e5) / 1e5);
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

const lanePercent = (frame) => `${(playStart(Math.min(frame, clip.frames - 1), clip, doc.freezes) / total()) * 100}%`;
const laneWidth = (first, last) => `${((playStart(Math.min(last + 1, clip.frames - 1), clip, doc.freezes) - playStart(first, clip, doc.freezes)) / total()) * 100}%`;

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
    add("annotate-cover", lanePercent(first), laneWidth(first, last));
    flaggedRuns(track, REVIEW).forEach(([a, b]) => add("annotate-flag is-review", lanePercent(a), laneWidth(a, b)));
    flaggedRuns(track, LOST).forEach(([a, b]) => add("annotate-flag is-lost", lanePercent(a), laneWidth(a, b)));
    keys.forEach((frame) => add("annotate-key", lanePercent(frame)));
    const job = jobs.get(track.id);
    if (job) add("annotate-progress", lanePercent(job.start), `${(job.progress * (playStart(job.end, clip, doc.freezes) - playStart(job.start, clip, doc.freezes)) / total()) * 100}%`);
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
const changeFreeze = (frame, seconds) => doc.commitDocument((value) => setFreeze(value, clip, frame, seconds));
const freezeHere = () => {
  const at = source();
  if (at.freeze === null && !doc.freezes.some((f) => f.atFrame === at.frame)) changeFreeze(at.frame, 2);
  seekOutput(freezeStart(at.frame, clip, doc.freezes)); // into the freeze, ready to draw on it
  document.querySelector(`[data-freeze-seconds="${at.frame}"]`)?.focus();
};

const renderFreezes = () => {
  const freezes = sortedFreezes();
  $("[data-scrub]").max = String(total());
  $("[data-freeze-count]").textContent = `(${freezes.length})`;
  $("[data-freeze-empty]").hidden = freezes.length > 0;
  $("[data-freeze-list]").replaceChildren(...freezes.map((freeze) => {
    const entry = document.createElement("li");
    const start = freezeStart(freeze.atFrame, clip, freezes);
    const go = Object.assign(document.createElement("button"), { type: "button", textContent: `Frame ${freeze.atFrame + 1} · ${formatTime(start)}` });
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
    remove.setAttribute("aria-label", `Remove the freeze at frame ${freeze.atFrame + 1}`);
    remove.onclick = () => changeFreeze(freeze.atFrame, 0);
    entry.append(go, seconds, Object.assign(document.createElement("span"), { textContent: "s" }), remove);
    return entry;
  }));
  const lane = $("[data-lane]");
  lane.querySelectorAll("[data-lane-freeze]").forEach((block) => block.remove());
  const length = total();
  freezes.forEach((freeze) => {
    const block = document.createElement("span");
    block.className = "annotate-lane-freeze";
    block.dataset.laneFreeze = String(freeze.atFrame);
    block.title = `Freeze at frame ${freeze.atFrame + 1}: ${freeze.seconds} s. Drag its right edge to change the length.`;
    block.style.left = `${(freezeStart(freeze.atFrame, clip, freezes) / length) * 100}%`;
    block.style.width = `${(freeze.seconds / length) * 100}%`;
    const edge = document.createElement("span");
    edge.className = "annotate-lane-edge";
    edge.dataset.edge = String(freeze.atFrame);
    block.append(edge);
    lane.append(block);
  });
};

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
    const edge = event.target.closest("[data-edge]");
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
    const item = newItem("text", [point], { from: currentTime(), to: total(), style: toolStyle.text, text });
    doc.add(item);
    select(item.id);
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
const nearHandle = (item, at) => {
  const [x, y] = toPixels(at);
  return handlesFor(item).find(({ point }) => {
    const [hx, hy] = toPixels(point);
    return Math.hypot(hx - x, hy - y) <= handleRadius() * 1.6;
  });
};

const finishZone = () => {
  if (zoneDraft && zoneDraft.length >= 3) {
    const item = newItem("zone", zoneDraft, { from: currentTime(), to: total(), style: toolStyle.zone });
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
  const [x, y] = toPixels(at);
  const { w, h } = size();
  const from = currentTime();
  if (tool === "select") {
    const selected = shownItem(selectedId);
    const handle = selected && nearHandle(selected, at);
    if (handle) {
      gesture = { type: "handle", id: selected.id, index: handle.index, base: selected, preview: selected };
    } else {
      const hit = itemAt(shown(), x, y, w, h, from, measure);
      select(hit?.id || null);
      if (hit) gesture = { type: "move", id: hit.id, start: at, base: hit, preview: hit };
    }
  } else if (tool === "follow") {
    gesture = { type: "box", start: clampPoint(at), end: clampPoint(at) };
  } else if (tool === "zone") {
    if (zoneDraft && zoneDraft.length >= 3) {
      const [fx, fy] = toPixels(zoneDraft[0]);
      if (Math.hypot(fx - x, fy - y) <= handleRadius() * 1.6) { finishZone(); return; }
    }
    zoneDraft = [...(zoneDraft || []), snapPoint(clampPoint(at))];
    if (zoneDraft.length >= 40) finishZone();
  } else if (tool === "text") {
    event.preventDefault();
    openText(clampPoint(at));
    return;
  } else {
    const style = toolStyle[tool];
    const geometry = tool === "spotlight" ? { ...ringGeometry(0.03, aspect()), h: 0.3 } : ringGeometry(0.03, aspect());
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
  if (zoneDraft) scheduleRender();
  if (!gesture?.type) {
    if (tool === "select") {
      const [x, y] = toPixels(at);
      const selected = doc.find(selectedId);
      const over = (selected && nearHandle(shownItem(selectedId), at)) || itemAt(shown(), x, y, canvas.width, canvas.height, currentTime(), measure);
      canvas.classList.toggle("is-over", Boolean(over));
    }
    return;
  }
  const item = gesture.base;
  if (gesture.type === "move" && item) {
    gesture.preview = moveItem(item, at[0] - gesture.start[0], at[1] - gesture.start[1]);
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
    const tooSmall = !current.moved && (draft.kind === "arrow" || draft.kind === "line" || draft.kind === "freehand");
    if (!tooSmall) {
      if (draft.kind === "freehand") {
        draft.points = simplify(draft.points.map(clampPoint), 3 * (window.devicePixelRatio || 1), canvas.width, canvas.height);
        if (draft.points.length < 2) return scheduleRender();
      }
      // Ring, spotlight, arrow and line ends dropped on a followed player's feet follow that player.
      const points = draft.kind === "freehand" ? draft.points : draft.points.map(snapPoint);
      const item = newItem(draft.kind, points, { from: draft.show.from, to: draft.show.to, style: draft.style, geometry: draft.geometry });
      doc.add(item);
      select(item.id);
    }
  } else if (current.type === "box") {
    followFromBox(current.start, current.end);
  } else if (current.preview) {
    applyEdit(current);
  }
  scheduleRender();
};
// A drag on a drawing: plain points move; a point linked to a player corrects
// that player on this frame (a keyframe), and a fixed point dropped on a
// followed player's feet starts following them.
function applyEdit({ type, id, index, base, preview }) {
  const original = doc.find(id);
  if (!original) return;
  if (type === "handle" && (index === "r" || index === "h")) {
    doc.replace({ ...original, geometry: preview.geometry });
    return;
  }
  if (type === "handle") {
    const point = original.points[index];
    const [dx, dy] = [preview.points[index][0] - base.points[index][0], preview.points[index][1] - base.points[index][1]];
    if (isLinked(point)) return correctTrack(point.track, dx, dy);
    const snapped = snapPoint(preview.points[index]);
    doc.replace({ ...original, points: original.points.map((each, i) => (i === index ? snapped : each)) });
    return;
  }
  const linked = [...linkedTracks(original)];
  if (!linked.length) {
    doc.replace({ ...original, points: preview.points });
  } else if (linked.length === 1 && original.points.every(isLinked)) {
    correctTrack(linked[0], preview.points[0][0] - base.points[0][0], preview.points[0][1] - base.points[0][1]);
  } else {
    trackStatus("This drawing's corners follow players. Drag one corner to correct that player on this frame.");
  }
}

canvas.addEventListener("pointerup", endGesture);
canvas.addEventListener("pointercancel", () => { gesture = null; scheduleRender(); });
canvas.addEventListener("dblclick", (event) => {
  if (tool === "zone") { if (zoneDraft) zoneDraft.pop(); finishZone(); return; } // the second click added a corner
  if (tool !== "select") return;
  const [x, y] = toPixels(toFraction(event));
  const hit = itemAt(shown(), x, y, canvas.width, canvas.height, currentTime(), measure);
  if (hit?.kind === "text") openText(hit.points[0], hit);
});

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------
const TOOL_KEYS = { v: "select", r: "ring", s: "spotlight", a: "arrow", l: "line", f: "freehand", t: "text", z: "zone", p: "follow" };
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setMenu(false);
  if (!clip) return;
  const typing = event.target.closest?.("input, textarea, select, [contenteditable]");
  if (typing) return;
  const command = event.ctrlKey || event.metaKey;
  const key = event.key.toLowerCase();
  if (command && key === "z") { event.preventDefault(); event.shiftKey ? doc.redo() : doc.undo(); return; }
  if (command && key === "y") { event.preventDefault(); doc.redo(); return; }
  if (command || event.altKey) return;
  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    step(event.key === "ArrowLeft" ? -1 : 1, event.shiftKey);
  } else if (event.key === " " && !event.target.closest("button")) {
    event.preventDefault();
    togglePlay();
  } else if ((event.key === "Delete" || event.key === "Backspace") && selectedId) {
    event.preventDefault();
    removeSelected();
  } else if (event.key === "Enter" && zoneDraft) {
    event.preventDefault();
    finishZone();
  } else if (event.key === "Escape") {
    if (zoneDraft) zoneDraft = null;
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
  context.drawImage(video, 0, 0, shot.width, shot.height);
  drawItems(context, shown(), shot.width, shot.height, currentTime());
  const type = format === "jpeg" ? "image/jpeg" : "image/png";
  const blob = await new Promise((resolve) => shot.toBlob(resolve, type, 0.92));
  const name = `${clip.name} frame ${source().frame + 1}.${format === "jpeg" ? "jpg" : "png"}`;
  button.disabled = true;
  try { await saveImage(blob, name); } finally { button.disabled = false; }
};

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
const wire = () => {
  document.querySelectorAll("[data-tool]").forEach((button) => { button.onclick = () => setTool(button.dataset.tool); });
  document.querySelectorAll("[data-step]").forEach((button) => { button.onclick = () => step(Number(button.dataset.step)); });
  $("[data-freeze]").onclick = freezeHere;
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
  $("[data-from]").onchange = (event) => setTiming("from", Number(event.target.value));
  $("[data-to]").onchange = (event) => setTiming("to", Number(event.target.value));
  $("[data-from-here]").onclick = () => setTiming("from", currentTime());
  $("[data-to-here]").onclick = () => setTiming("to", currentTime());
  $("[data-delete]").onclick = removeSelected;
  $("[data-follow-start]").onclick = () => followSelected("start");
  $("[data-follow-confirm]").onclick = () => followSelected("confirm");
  $("[data-follow-next]").onclick = () => followSelected("next");
  $("[data-follow-retrack]").onclick = () => followSelected("retrack");
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
    if (selectedId && !doc.find(selectedId)) selectedId = null;
    if (playing) pause();
    outTime = clampTime(outTime);
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
    if (!projectId || !/^[a-f0-9]{32}$/.test(clipId)) throw new Error("Open a clip with its Annotate button first.");
    const { project } = await projectRequest(`/api/projects/${encodeURIComponent(projectId)}`);
    rememberProject(project);
    const opened = await projectRequest(`/api/editor/${encodeURIComponent(projectId)}/${encodeURIComponent(clipId)}`);
    clip = opened.clip;
    doc = createDocument(opened.annotations);
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
start();
