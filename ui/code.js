// The Code screen (docs/CODING_AND_PITCH_PLAN.md, C1): press a key while the
// match video plays and an event is made at the playhead. Events are saved in
// video time; the engine turns them into the event table Filter and export read.
import { projectRequest, newProject, rememberProject, saveProject, beginProjectOperation } from "./projects.js";
import { formatClock, formatVideo, isTyping, place, sources } from "./code/clock.js";

const $ = (selector) => document.querySelector(selector);
const params = new URLSearchParams(location.search);
const projectId = params.get("project") || sessionStorage.getItem("clipmaker.active-match") || "";

const video = $("[data-video]");
const status = $("[data-code-status]");
const errorBox = $("[data-code-error]");
const grid = $("[data-code-grid]");
const list = $("[data-list]");
const lastLine = $("[data-last]");
const scrub = $("[data-scrub]");
const timeOut = $("[data-time]");
const playButton = $("[data-play]");
const sourceSelect = $("[data-source]");

let project = null;
let codes = [];
let events = [];
let unplaced = new Set();
let team = "home";
let src = "1H";
let selectedId = null;
const madeHere = []; // ids coded on this visit, newest last: Backspace removes them in turn

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
// Saving: changes queue up and go to the engine one batch at a time, so codes
// made faster than a save never wait for it and are never lost to a failure.
// ---------------------------------------------------------------------------
const pending = { add: [], delete: [] };
let sending = null;
let retryTimer = null;

const showSave = (text, failed = false) => {
  document.querySelectorAll("[data-project-status]").forEach((element) => {
    element.textContent = text;
    element.classList.toggle("save-failed", failed);
  });
};

const flush = () => {
  if (sending || (!pending.add.length && !pending.delete.length)) return sending;
  clearTimeout(retryTimer);
  const batch = { add: pending.add.splice(0), delete: pending.delete.splice(0) };
  const finish = beginProjectOperation();
  showSave("Saving locally...");
  sending = projectRequest(`/api/projects/${encodeURIComponent(project.id)}/codes`, batch)
    .then((result) => {
      project = result.project;
      unplaced = new Set(result.unplaced);
      // Codes made while this batch was on its way are still to send: keep them.
      const waiting = new Set(pending.add.map((event) => event.id));
      const removed = new Set(pending.delete);
      events = [...result.events.filter((event) => !removed.has(event.id)), ...pending.add.filter((event) => waiting.has(event.id))];
      showSave("Saved locally");
      showError("");
    })
    .catch((error) => {
      pending.add.unshift(...batch.add);
      pending.delete.unshift(...batch.delete);
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
  if (pending.add.length || pending.delete.length) { event.preventDefault(); event.returnValue = ""; }
});

const newId = () => `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

const addCode = (code) => {
  const event = { id: newId(), code: code.id, team, src, t: Math.round(video.currentTime * 1000) / 1000 };
  events.push(event);
  madeHere.push(event.id);
  pending.add.push(event);
  selectedId = event.id;
  const button = grid.querySelector(`[data-code="${code.id}"]`);
  button?.classList.remove("is-fired");
  void button?.offsetWidth; // restart the flash on repeated presses
  button?.classList.add("is-fired");
  const where = place(project, src, event.t);
  lastLine.textContent = `${code.label} · ${teamName(team)} · ${where ? `${formatClock(where.clock)} ${where.period.name}` : `${formatVideo(event.t)} in the video`}`;
  render();
  flush();
};

const removeCode = (id) => {
  const index = events.findIndex((event) => event.id === id);
  if (index < 0) return;
  const [event] = events.splice(index, 1);
  const queued = pending.add.findIndex((item) => item.id === id);
  if (queued >= 0) pending.add.splice(queued, 1);
  else pending.delete.push(id);
  const made = madeHere.indexOf(id);
  if (made >= 0) madeHere.splice(made, 1);
  if (selectedId === id) selectedId = null;
  lastLine.textContent = `Removed ${codeOf(event)?.label || "code"}.`;
  render();
  flush();
};

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------
const codeOf = (event) => codes.find((code) => code.id === event.code);
const teamName = (side) => (side === "home" ? project.home_team || "Home" : side === "away" ? project.away_team || "Away" : "No team");
const order = (event) => ["1H", "2H", "ET1", "ET2", "PEN"].indexOf(event.src) * 1e6 + event.t;

const renderGrid = () => {
  grid.replaceChildren(...codes.map((code) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.code = code.id;
    button.style.setProperty("--code-colour", code.colour);
    button.title = `${code.label} (${code.key.toUpperCase()})`;
    const name = document.createElement("span");
    name.textContent = code.label;
    const key = document.createElement("kbd");
    key.textContent = code.key.toUpperCase();
    button.append(name, key);
    button.onclick = () => addCode(code);
    button.addEventListener("animationend", () => button.classList.remove("is-fired"));
    return button;
  }));
};

const renderTeams = () => {
  for (const side of ["home", "away"]) {
    document.querySelector(`[data-team-name="${side}"]`).textContent = teamName(side);
    const input = document.querySelector(`[data-team-input="${side}"]`);
    if (document.activeElement !== input) input.value = (side === "home" ? project.home_team : project.away_team) || "";
  }
  document.querySelectorAll("[data-team]").forEach((button) => button.setAttribute("aria-checked", String(button.dataset.team === team)));
};

const render = () => {
  renderTeams();
  const sorted = [...events].sort((a, b) => order(a) - order(b));
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
    const where = place(project, event.src, event.t);
    const clock = document.createElement("span");
    clock.className = "code-clock";
    clock.textContent = where ? formatClock(where.clock) : "--:--";
    const label = document.createElement("span");
    label.className = "code-label";
    label.textContent = code?.label || event.code;
    const detail = document.createElement("small");
    detail.textContent = `${teamName(event.team)} · ${where ? where.period.name : "before kick-off"} · ${formatVideo(event.t)}`;
    jump.append(clock, label, detail);
    jump.title = "Jump to this moment";
    jump.onclick = () => jumpTo(event);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "code-remove";
    remove.setAttribute("aria-label", `Delete ${code?.label || "code"} at ${clock.textContent}`);
    remove.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5"/></svg>';
    remove.onclick = () => removeCode(event.id);
    item.append(jump, remove);
    if (unplaced.has(event.id) || !where) item.classList.add("is-unplaced");
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
const jumpTo = (event) => {
  selectedId = event.id;
  const go = () => { video.currentTime = Math.max(0, event.t); render(); };
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
};
video.addEventListener("timeupdate", showTime);
video.addEventListener("loadedmetadata", () => { scrub.max = String(video.duration || 1); showTime(); });
video.addEventListener("play", () => { playButton.classList.add("is-playing"); playButton.setAttribute("aria-label", "Pause"); });
video.addEventListener("pause", () => { playButton.classList.remove("is-playing"); playButton.setAttribute("aria-label", "Play"); });
scrub.addEventListener("input", () => { video.currentTime = Number(scrub.value); showTime(); });
const toggle = () => (video.paused ? video.play().catch(() => {}) : video.pause());
const seek = (seconds) => { video.currentTime = Math.min(video.duration || Infinity, Math.max(0, video.currentTime + seconds)); showTime(); };
playButton.onclick = toggle;
document.querySelectorAll("[data-seek]").forEach((button) => { button.onclick = () => seek(Number(button.dataset.seek)); });
sourceSelect.onchange = () => loadSource(sourceSelect.value).catch((error) => showError(error.message));

// ---------------------------------------------------------------------------
// Teams and keys
// ---------------------------------------------------------------------------
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
  if (!project || isTyping(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
  if (document.querySelector("dialog[open]")) return;
  const key = event.key.toLowerCase();
  if (key === " ") { event.preventDefault(); toggle(); return; }
  if (key === "arrowleft" || key === "arrowright") {
    event.preventDefault();
    seek((key === "arrowleft" ? -1 : 1) * (event.shiftKey ? 5 : 1));
    return;
  }
  if (key === "h" || key === "a") { chooseTeam(key === "h" ? "home" : "away"); return; }
  if (key === "backspace") {
    const last = madeHere[madeHere.length - 1];
    if (last) { event.preventDefault(); removeCode(last); }
    return;
  }
  if (event.repeat) return; // holding a key makes one code, not a burst
  const code = codes.find((item) => item.key === key);
  if (code) { event.preventDefault(); addCode(code); }
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
    events = result.events;
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
