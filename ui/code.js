// The Code screen (docs/CODING_AND_PITCH_PLAN.md, C1 and C2): press a key while
// the match video plays and an event is made at the playhead; interval codes
// start on one press and stop on the next. Events are saved in video time; the
// engine turns them into the event table Filter and export read.
import { projectRequest, newProject, rememberProject, saveProject, beginProjectOperation } from "./projects.js";
import { formatClock, formatVideo, isTyping, place, sources } from "./code/clock.js";
import { History, nudged, toggleInterval } from "./code/edits.js";

const $ = (selector) => document.querySelector(selector);
const params = new URLSearchParams(location.search);
const projectId = params.get("project") || sessionStorage.getItem("clipmaker.active-match") || "";

const video = $("[data-video]");
const status = $("[data-code-status]");
const errorBox = $("[data-code-error]");
const grid = $("[data-code-grid]");
const intervalGrid = $("[data-interval-grid]");
const list = $("[data-list]");
const lastLine = $("[data-last]");
const scrub = $("[data-scrub]");
const timeOut = $("[data-time]");
const playButton = $("[data-play]");
const sourceSelect = $("[data-source]");
const editor = $("[data-editor]");

let project = null;
let codes = [];
const events = new Map(); // id -> event: what the analyst sees, saved or not
let unplaced = new Set();
let leads = {};
let team = "home";
let src = "1H";
let selectedId = null;
let frameStep = 0.04; // one frame; measured from the video once it plays (25 fps until then)
const madeHere = []; // ids coded on this visit, newest last: Backspace removes them in turn
const history = new History();

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------
const menu = $("#code-menu");
const menuButton = $("[data-code-menu]");
const setMenu = (open) => {
  if (!open && menu.contains(document.activeElement)) menuButton.focus();
  menu.hidden = !open;
  menuButton.setAttribute("aria-expanded", String(open));
  if (open) menu.querySelector("button")?.focus();
};
menuButton.onclick = () => setMenu(menu.hidden);
document.addEventListener("click", (event) => { if (!event.target.closest("#code-menu, [data-code-menu]")) setMenu(false); });
$("[data-new-project]").onclick = async () => {
  try { const created = await newProject(); location.href = `/?project=${created.id}`; } catch (error) { showError(error.message); }
};
document.querySelectorAll("a[data-project-navigation]").forEach((link) => {
  const url = new URL(link.href, location.origin);
  if (projectId) url.searchParams.set("project", projectId);
  link.href = url.pathname + url.search;
});

const showError = (message) => {
  errorBox.textContent = message;
  errorBox.hidden = !message;
};

// ---------------------------------------------------------------------------
// Saving. Each change marks its event dirty; a save sends every dirty event in
// its latest state (add, update or delete), so codes made faster than a save
// never wait for it, and a failed save is retried without losing any.
// ---------------------------------------------------------------------------
const dirty = new Map(); // id -> event, or null when deleted
let saved = new Set(); // ids the engine has
let leadsDirty = {};
let sending = null;
let retryTimer = null;

const showSave = (text, failed = false) => {
  document.querySelectorAll("[data-project-status]").forEach((element) => {
    element.textContent = text;
    element.classList.toggle("save-failed", failed);
  });
};

const flush = () => {
  if (sending || (!dirty.size && !Object.keys(leadsDirty).length)) return sending;
  clearTimeout(retryTimer);
  const sent = new Map(dirty);
  const sentLeads = leadsDirty;
  dirty.clear();
  leadsDirty = {};
  const batch = { add: [], update: [], delete: [] };
  for (const [id, event] of sent) {
    if (event === null) { if (saved.has(id)) batch.delete.push(id); }
    else (saved.has(id) ? batch.update : batch.add).push(event);
  }
  if (Object.keys(sentLeads).length) batch.leads = sentLeads;
  const finish = beginProjectOperation();
  showSave("Saving locally...");
  sending = projectRequest(`/api/projects/${encodeURIComponent(project.id)}/codes`, batch)
    .then((result) => {
      project = result.project;
      unplaced = new Set(result.unplaced);
      saved = new Set(result.events.map((event) => event.id));
      showSave("Saved locally");
      showError("");
    })
    .catch((error) => {
      // Put back what was sent, unless it changed again meanwhile.
      for (const [id, event] of sent) if (!dirty.has(id)) dirty.set(id, event);
      leadsDirty = { ...sentLeads, ...leadsDirty };
      showSave("Save failed", true);
      showError(`${error.message} Your codes are kept here and saving tries again.`);
      retryTimer = setTimeout(flush, 3000);
    })
    .finally(() => {
      finish();
      sending = null;
      render();
      if (!errorBox.textContent) flush();
    });
  return sending;
};

window.addEventListener("beforeunload", (event) => {
  if (dirty.size || Object.keys(leadsDirty).length) { event.preventDefault(); event.returnValue = ""; }
});

// Apply [{id, next}] (next null deletes): one step the analyst can undo.
const commit = (changes, label, record = true) => {
  const steps = changes.map(({ id, next }) => ({ id, prev: events.get(id) || null, next }));
  for (const { id, next } of steps) {
    if (next) events.set(id, next); else events.delete(id);
    dirty.set(id, next);
  }
  if (record) history.push(steps, label);
  render();
  flush();
};

const undo = () => {
  const step = history.undo();
  if (!step) return;
  commit(step.steps.map(({ id, prev }) => ({ id, next: prev })), step.label, false);
  if (step.steps.length === 1 && events.has(step.steps[0].id)) selectedId = step.steps[0].id;
  lastLine.textContent = `Undone: ${step.label}.`;
  render();
};
const redo = () => {
  const step = history.redo();
  if (!step) return;
  commit(step.steps.map(({ id, next }) => ({ id, next })), step.label, false);
  lastLine.textContent = `Redone: ${step.label}.`;
};

// ---------------------------------------------------------------------------
// Coding
// ---------------------------------------------------------------------------
const newId = () => `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
const now = () => Math.round(video.currentTime * 1000) / 1000;
const codeOf = (event) => codes.find((code) => code.id === event.code);
const teamName = (side) => (side === "home" ? project.home_team || "Home" : side === "away" ? project.away_team || "Away" : "No team");
const whereText = (event) => {
  const where = place(project, event.src, event.t);
  return where ? `${formatClock(where.clock)} ${where.period.name}` : `${formatVideo(event.t)} in the video`;
};

const flash = (code) => {
  const button = document.querySelector(`[data-code="${code.id}"]`);
  button?.classList.remove("is-fired");
  void button?.offsetWidth; // restart the flash on repeated presses
  button?.classList.add("is-fired");
};

const addCode = (code) => {
  const event = { id: newId(), code: code.id, team, src, t: now() };
  madeHere.push(event.id);
  selectedId = event.id;
  flash(code);
  lastLine.textContent = `${code.label} · ${teamName(team)} · ${whereText(event)}`;
  commit([{ id: event.id, next: event }], code.label);
};

const pressInterval = (code) => {
  const { changes, started } = toggleInterval([...events.values()], codes, code, team, src, now(), newId);
  if (started) { madeHere.push(started.id); selectedId = started.id; }
  flash(code);
  const stopped = changes.filter((change) => change.next.end != null);
  lastLine.textContent = started
    ? `${code.label} started · ${teamName(team)} · ${whereText(started)}${stopped.length ? ` (stopped ${stopped.map((c) => codeOf(c.next).label).join(", ")})` : ""}`
    : `${code.label} stopped · ${formatVideo(stopped[0].next.end - stopped[0].next.t)} long`;
  commit(changes, started ? `start ${code.label}` : `stop ${code.label}`);
};

const removeCode = (id) => {
  const event = events.get(id);
  if (!event) return;
  const made = madeHere.indexOf(id);
  if (made >= 0) madeHere.splice(made, 1);
  if (selectedId === id) selectedId = null;
  lastLine.textContent = `Removed ${codeOf(event)?.label || "code"}. Ctrl+Z puts it back.`;
  commit([{ id, next: null }], `delete ${codeOf(event)?.label || "code"}`);
};

const edit = (id, change, label) => {
  const event = events.get(id);
  if (!event) return;
  commit([{ id, next: { ...event, ...change } }], label);
};

const nudge = (id, edge, seconds) => {
  const event = events.get(id);
  if (!event || (edge === "end" && event.end == null)) return;
  const next = nudged(event, edge, seconds, video.duration || Infinity);
  if (next) commit([{ id, next }], `nudge ${codeOf(event)?.label || "code"}`);
  if (next) { video.currentTime = edge === "end" ? next.end : next.t; showTime(); }
};

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------
const order = (event) => ["1H", "2H", "ET1", "ET2", "PEN"].indexOf(event.src) * 1e6 + event.t;

const codeButton = (code) => {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.code = code.id;
  button.style.setProperty("--code-colour", code.colour);
  button.title = `${code.label} (${code.key.toUpperCase()})`;
  const name = document.createElement("span");
  name.textContent = code.label;
  const key = document.createElement("kbd");
  key.textContent = code.key.toUpperCase();
  button.append(name);
  if (code.kind === "interval") {
    button.setAttribute("aria-pressed", "false");
    const elapsed = document.createElement("output");
    elapsed.className = "code-elapsed";
    elapsed.dataset.elapsed = code.id;
    button.append(elapsed);
    button.onclick = () => pressInterval(code);
  } else button.onclick = () => addCode(code);
  button.append(key);
  button.addEventListener("animationend", () => button.classList.remove("is-fired"));
  return button;
};

const renderGrid = () => {
  grid.replaceChildren(...codes.filter((code) => code.kind !== "interval").map(codeButton));
  intervalGrid.replaceChildren(...codes.filter((code) => code.kind === "interval").map(codeButton));
};

// Running intervals glow and count up with the video.
const renderRunning = () => {
  const running = [...events.values()].filter((event) => event.end === null);
  for (const code of codes.filter((item) => item.kind === "interval")) {
    const button = intervalGrid.querySelector(`[data-code="${code.id}"]`);
    const open = running.filter((event) => event.code === code.id);
    button.classList.toggle("is-running", open.length > 0);
    button.setAttribute("aria-pressed", String(open.length > 0));
    const elapsed = button.querySelector("[data-elapsed]");
    elapsed.textContent = open.length ? formatVideo(Math.max(0, video.currentTime - open[0].t)) : "";
    button.title = open.length ? `${code.label} running for ${open.map((event) => teamName(event.team)).join(" and ")} (${code.key.toUpperCase()} stops it)`
      : `${code.label} (${code.key.toUpperCase()})`;
  }
};

const renderTeams = () => {
  for (const side of ["home", "away"]) {
    document.querySelector(`[data-team-name="${side}"]`).textContent = teamName(side);
    const input = document.querySelector(`[data-team-input="${side}"]`);
    if (document.activeElement !== input) input.value = (side === "home" ? project.home_team : project.away_team) || "";
  }
  document.querySelectorAll("[data-team]").forEach((button) => button.setAttribute("aria-checked", String(button.dataset.team === team)));
  const teamSelect = $("[data-edit-team]");
  teamSelect.options[0].textContent = teamName("home");
  teamSelect.options[1].textContent = teamName("away");
};

const renderLeads = () => {
  const body = $("[data-leads] tbody");
  if (body.children.length) {
    body.querySelectorAll("input").forEach((input) => {
      if (document.activeElement !== input) input.value = leadOf(input.dataset.leadCode)[input.dataset.leadSide];
    });
    return;
  }
  body.replaceChildren(...codes.map((code) => {
    const row = document.createElement("tr");
    const name = document.createElement("th");
    name.scope = "row";
    name.textContent = code.label;
    row.append(name);
    for (const side of ["before", "after"]) {
      const cell = document.createElement("td");
      const input = document.createElement("input");
      Object.assign(input, { type: "number", min: 0, max: 60, step: 1, value: leadOf(code.id)[side] });
      input.dataset.leadCode = code.id;
      input.dataset.leadSide = side;
      input.setAttribute("aria-label", `${code.label}: seconds ${side === "before" ? "before" : "after"}`);
      input.addEventListener("change", () => {
        const value = Math.round(Number(input.value));
        if (!Number.isFinite(value) || value < 0 || value > 60) { input.value = leadOf(code.id)[side]; return; }
        leads[code.id] = { ...leads[code.id], [side]: value };
        leadsDirty[code.id] = { ...leadsDirty[code.id], [side]: value };
        flush();
      });
      cell.append(input);
      row.append(cell);
    }
    return row;
  }));
};
const leadOf = (codeId) => {
  const code = codes.find((item) => item.id === codeId);
  return { before: code.before, after: code.after, ...leads[codeId] };
};

const renderEditor = () => {
  const event = events.get(selectedId);
  editor.hidden = !event;
  if (!event) return;
  const code = codeOf(event);
  const interval = code?.kind === "interval";
  $("[data-editor-title]").textContent = `${code?.label || event.code} · ${teamName(event.team)} · ${whereText(event)}`
    + (interval ? (event.end == null ? " · running" : ` · ${formatVideo(event.end - event.t)} long`) : "");
  $("[data-end-row]").hidden = !interval;
  const select = $("[data-edit-code]");
  select.replaceChildren(...codes.filter((item) => item.kind === code?.kind).map((item) => new Option(item.label, item.id)));
  select.value = event.code;
  $("[data-edit-team]").value = event.team;
};

const render = () => {
  renderTeams();
  renderRunning();
  renderEditor();
  $("[data-undo]").disabled = !history.canUndo;
  $("[data-redo]").disabled = !history.canRedo;
  const sorted = [...events.values()].sort((a, b) => order(a) - order(b));
  $("[data-count]").textContent = `(${sorted.length})`;
  $("[data-list-empty]").hidden = sorted.length > 0;
  $("[data-filter-link]").hidden = !sorted.length || (project.source && project.source !== "coded");
  list.replaceChildren(...sorted.map((event) => {
    const code = codeOf(event);
    const item = document.createElement("li");
    item.className = "code-row";
    item.classList.toggle("is-selected", event.id === selectedId);
    item.style.setProperty("--code-colour", code?.colour || "var(--cm-muted)");
    const jump = document.createElement("button");
    jump.type = "button";
    jump.className = "code-jump";
    jump.setAttribute("aria-pressed", String(event.id === selectedId));
    const where = place(project, event.src, event.t);
    const clock = document.createElement("span");
    clock.className = "code-clock";
    clock.textContent = where ? formatClock(where.clock) : "--:--";
    const label = document.createElement("span");
    label.className = "code-label";
    label.textContent = code?.label || event.code;
    const detail = document.createElement("small");
    const span = code?.kind === "interval" ? (event.end == null ? " · running" : ` · ${formatVideo(event.end - event.t)} long`) : "";
    detail.textContent = `${teamName(event.team)} · ${where ? where.period.name : "before kick-off"}${span} · ${formatVideo(event.t)}`;
    jump.append(clock, label, detail);
    jump.title = "Choose and jump to this moment";
    jump.onclick = () => jumpTo(event);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "code-remove";
    remove.setAttribute("aria-label", `Delete ${code?.label || "code"} at ${clock.textContent}`);
    remove.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5"/></svg>';
    remove.onclick = () => removeCode(event.id);
    item.append(jump, remove);
    if (unplaced.has(event.id) || !where) item.classList.add("is-unplaced");
    if (event.end === null) item.classList.add("is-running");
    return item;
  }));
  list.querySelector(".is-selected")?.scrollIntoView({ block: "nearest" });
  renderKickoffNote(sorted);
};

const renderKickoffNote = (sorted) => {
  const note = $("[data-kickoff-note]");
  const before = sorted.filter((event) => !place(project, event.src, event.t)).length;
  const scraped = project.source && project.source !== "coded" && project.csv_path;
  let text = "";
  if (scraped) text = "This project's events come from a match feed, so Filter keeps using them. Your codes are saved; adding them to the feed's events comes in a later version.";
  else if (!(project.markers || {})["1H"]) text = "Set the first-half kick-off on Intake to give codes a match clock. They are saved meanwhile.";
  else if (before) text = `${before} ${before === 1 ? "code is" : "codes are"} before the first kick-off on this video, so ${before === 1 ? "it is" : "they are"} left out of Filter and export.`;
  note.textContent = text;
  note.hidden = !text;
};

// ---------------------------------------------------------------------------
// Video
// ---------------------------------------------------------------------------
const jumpTo = (event, edge = "t") => {
  selectedId = event.id;
  const go = () => { video.currentTime = Math.max(0, edge === "end" && event.end != null ? event.end : event.t); render(); };
  if (event.src !== src) loadSource(event.src).then(go);
  else go();
};

const loadSource = async (key) => {
  const { file } = await projectRequest("/api/files/reopen", { match_id: project.id, period: key });
  src = key;
  sourceSelect.value = key;
  video.src = file.url;
  await new Promise((resolve) => video.addEventListener("loadedmetadata", resolve, { once: true }));
};

const showTime = () => {
  const where = place(project, src, video.currentTime);
  timeOut.textContent = where ? `${formatClock(where.clock)} ${where.period.name}` : formatVideo(video.currentTime);
  timeOut.title = `${formatVideo(video.currentTime)} in the video`;
  if (document.activeElement !== scrub) scrub.value = String(video.currentTime);
  if (project) renderRunning();
};
video.addEventListener("timeupdate", showTime);
video.addEventListener("loadedmetadata", () => { scrub.max = String(video.duration || 1); showTime(); });
video.addEventListener("play", () => { playButton.classList.add("is-playing"); playButton.setAttribute("aria-label", "Pause"); measureFrame(); });
video.addEventListener("pause", () => { playButton.classList.remove("is-playing"); playButton.setAttribute("aria-label", "Play"); });
scrub.addEventListener("input", () => { video.currentTime = Number(scrub.value); showTime(); });
const toggle = () => (video.paused ? video.play().catch(() => {}) : video.pause());
const seek = (seconds) => { video.currentTime = Math.min(video.duration || Infinity, Math.max(0, video.currentTime + seconds)); showTime(); };
playButton.onclick = toggle;
document.querySelectorAll("[data-seek]").forEach((button) => { button.onclick = () => seek(Number(button.dataset.seek)); });

// One frame of this video, from two frames shown back to back while it plays.
const measureFrame = () => {
  if (!video.requestVideoFrameCallback) return;
  let last = null;
  const sample = (_, meta) => {
    if (last && meta.presentedFrames === last.presentedFrames + 1) {
      const step = meta.mediaTime - last.mediaTime;
      if (step > 0.005 && step < 0.2) { frameStep = Math.round(step * 10000) / 10000; return; }
    }
    last = meta;
    if (!video.paused) video.requestVideoFrameCallback(sample);
  };
  video.requestVideoFrameCallback(sample);
};

// A running interval ends on the file it started on: stop it there before switching.
sourceSelect.onchange = async () => {
  const running = [...events.values()].filter((event) => event.end === null && event.src === src);
  if (running.length) commit(running.map((event) => ({ id: event.id, next: { ...event, end: Math.max(event.t, now()) } })), "stop intervals");
  try { await loadSource(sourceSelect.value); } catch (error) { showError(error.message); }
};

// ---------------------------------------------------------------------------
// Editor, teams, keys
// ---------------------------------------------------------------------------
editor.querySelectorAll("[data-edge]").forEach((row) => {
  row.querySelectorAll("[data-nudge]").forEach((button) => {
    button.onclick = () => nudge(selectedId, row.dataset.edge, Number(button.dataset.nudge) === 0.04 ? frameStep
      : Number(button.dataset.nudge) === -0.04 ? -frameStep : Number(button.dataset.nudge));
  });
  row.querySelector("[data-here]").onclick = () => {
    const event = events.get(selectedId);
    if (!event) return;
    const at = now();
    const next = row.dataset.edge === "end" ? { ...event, end: Math.max(event.t, at) } : { ...event, t: event.end != null ? Math.min(at, event.end) : at };
    commit([{ id: event.id, next }], `move ${codeOf(event)?.label || "code"}`);
  };
});
$("[data-edit-code]").onchange = (change) => edit(selectedId, { code: change.target.value }, "change code");
$("[data-edit-team]").onchange = (change) => edit(selectedId, { team: change.target.value }, "change team");
$("[data-edit-delete]").onclick = () => removeCode(selectedId);
$("[data-undo]").onclick = undo;
$("[data-redo]").onclick = redo;

const chooseTeam = (side) => { team = side; renderTeams(); };
document.querySelectorAll("[data-team]").forEach((button) => { button.onclick = () => chooseTeam(button.dataset.team); });
document.querySelectorAll("[data-team-input]").forEach((input) => {
  input.addEventListener("change", async () => {
    const field = input.dataset.teamInput === "home" ? "home_team" : "away_team";
    try {
      project = (await saveProject(project.id, { [field]: input.value.trim().slice(0, 60) })) || project;
      render();
    } catch (error) { showError(error.message); }
  });
});

document.addEventListener("keydown", (event) => {
  if (!project || isTyping(event.target) || event.altKey) return;
  if (document.querySelector("dialog[open]")) return;
  const key = event.key.toLowerCase();
  if (event.ctrlKey || event.metaKey) {
    if (key === "z" && !event.shiftKey) { event.preventDefault(); undo(); }
    else if ((key === "z" && event.shiftKey) || key === "y") { event.preventDefault(); redo(); }
    return;
  }
  if (key === " ") { event.preventDefault(); toggle(); return; }
  if (key === "arrowleft" || key === "arrowright") {
    event.preventDefault();
    seek((key === "arrowleft" ? -1 : 1) * (event.shiftKey ? 5 : 1));
    return;
  }
  if (event.code === "Comma" || event.code === "Period") {
    if (!selectedId) return;
    event.preventDefault();
    nudge(selectedId, "t", (event.code === "Comma" ? -1 : 1) * (event.shiftKey ? 1 : frameStep));
    return;
  }
  if (key === "escape") { selectedId = null; render(); return; }
  if (key === "h" || key === "a") { chooseTeam(key === "h" ? "home" : "away"); return; }
  if (key === "delete") {
    if (selectedId) { event.preventDefault(); removeCode(selectedId); }
    return;
  }
  if (key === "backspace") {
    const last = madeHere[madeHere.length - 1];
    if (last) { event.preventDefault(); removeCode(last); }
    return;
  }
  if (event.repeat) return; // holding a key makes one code, not a burst
  const code = codes.find((item) => item.key === key);
  if (!code) return;
  event.preventDefault();
  if (code.kind === "interval") pressInterval(code); else addCode(code);
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
const start = async () => {
  if (!projectId) {
    status.textContent = "No project open";
    $("[data-code-empty]").hidden = false;
    $("[data-code-empty-text]").textContent = "Open or start a project on Intake, choose its match video, then come back here to code it.";
    return;
  }
  try {
    const result = await projectRequest(`/api/projects/${encodeURIComponent(projectId)}/codes`);
    project = result.project;
    rememberProject(project);
    codes = result.codes;
    for (const event of result.events) events.set(event.id, event);
    saved = new Set(result.events.map((event) => event.id));
    leads = result.leads || {};
    unplaced = new Set(result.unplaced);
    $("[data-code-project]").textContent = project.project_name || "Untitled project";
    const available = sources(project);
    if (!available.length) {
      status.textContent = "No video";
      $("[data-code-empty]").hidden = false;
      return;
    }
    sourceSelect.replaceChildren(...available.map((item) => new Option(item.key === "1H" ? "Main video" : `${item.key} video`, item.key)));
    $("[data-source-row]").hidden = available.length < 2;
    renderGrid();
    renderLeads();
    $("[data-code-workspace]").hidden = false;
    render();
    await loadSource(available[0].key);
    status.textContent = "Ready to code";
  } catch (error) {
    status.textContent = "Could not open";
    showError(error.message);
  }
};
start();
