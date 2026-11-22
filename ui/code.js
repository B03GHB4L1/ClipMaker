// The Code screen (docs/CODING_AND_PITCH_PLAN.md, C1 to C4): press a key while
// the match video plays and an event is made at the playhead; interval codes
// start on one press and stop on the next. Tags (Shift+letter) label an event,
// a number after a code names its player, and a code can start or stop
// intervals; a click on the pitch places the chosen event. Events are saved in video time; the engine turns them into the
// event table Filter and export read. The panel of codes comes from a template.
import { projectRequest, newProject, rememberProject, saveProject, beginProjectOperation } from "./projects.js";
import { PERIODS, formatClock, formatVideo, isTyping, parseMarker, place, sources } from "./code/clock.js";
import { pitchPoint, placed } from "./code/pitch.js";
import { LINK_LIMITS, linkSummary, linkTargets, pruneLinks, setStart, toggleLink } from "./code/links.js";
import { History, linkedChanges, nudged, parseSquad, squadText, startingTags, toggleInterval, toggledTags } from "./code/edits.js";
import { showSaved, showSaveError } from "./save-clip.js";
import { LivePlayer, RECORDING_STATES, liveSummary, markerText, nextKickoff } from "./code/live.js";

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
let tags = [];
let panel = null;
let squads = { home: [], away: [] };
let armed = []; // tag ids waiting for the next event
let templates = [];
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
let pendingSquads = null;
let sending = null;
let retryTimer = null;

const showSave = (text, failed = false) => {
  document.querySelectorAll("[data-project-status]").forEach((element) => {
    element.textContent = text;
    element.classList.toggle("save-failed", failed);
  });
};

const flush = () => {
  if (sending || (!dirty.size && !Object.keys(leadsDirty).length && !pendingSquads)) return sending;
  clearTimeout(retryTimer);
  const sent = new Map(dirty);
  const sentLeads = leadsDirty;
  const sentSquads = pendingSquads;
  dirty.clear();
  leadsDirty = {};
  pendingSquads = null;
  const batch = { add: [], update: [], delete: [] };
  for (const [id, event] of sent) {
    if (event === null) { if (saved.has(id)) batch.delete.push(id); }
    else (saved.has(id) ? batch.update : batch.add).push(event);
  }
  if (Object.keys(sentLeads).length) batch.leads = sentLeads;
  if (sentSquads) batch.squads = sentSquads;
  const finish = beginProjectOperation();
  showSave("Saving locally...");
  sending = projectRequest(`/api/projects/${encodeURIComponent(project.id)}/codes`, batch)
    .then((result) => {
      project = result.project;
      unplaced = new Set(result.unplaced);
      saved = new Set(result.events.map((event) => event.id));
      squads = result.squads || squads;
      showSave("Saved locally");
      showError("");
    })
    .catch((error) => {
      // Put back what was sent, unless it changed again meanwhile.
      for (const [id, event] of sent) if (!dirty.has(id)) dirty.set(id, event);
      leadsDirty = { ...sentLeads, ...leadsDirty };
      if (sentSquads && !pendingSquads) pendingSquads = sentSquads;
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
  if (dirty.size || Object.keys(leadsDirty).length || pendingSquads) { event.preventDefault(); event.returnValue = ""; }
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

const tagLabel = (id) => tags.find((tag) => tag.id === id)?.label || id;
const linkText = (changes, ownId) => {
  const parts = changes.filter((change) => change.id !== ownId).map((change) => {
    const label = codeOf(change.next)?.label || change.next.code;
    return change.next.end == null ? `started ${label} for ${teamName(change.next.team)}` : `stopped ${label}`;
  });
  return parts.length ? ` (${parts.join(", ")})` : "";
};
// Changes to running intervals by the code's links, merged with `own` (later ones win).
const withLinks = (code, own) => {
  const linked = linkedChanges([...events.values()], codes, code, team, src, now(), newId);
  const merged = new Map(linked.map((change) => [change.id, change]));
  for (const change of own) merged.set(change.id, change);
  return [...merged.values()];
};

const addCode = (code) => {
  const event = { id: newId(), code: code.id, team, src, t: now() };
  const chosen = startingTags(code, armed, tags);
  if (chosen.length) event.tags = chosen;
  armed = [];
  madeHere.push(event.id);
  selectedId = event.id;
  digits.since = performance.now();
  flash(code);
  const changes = withLinks(code, [{ id: event.id, next: event }]);
  lastLine.textContent = `${code.label} · ${teamName(team)} · ${whereText(event)}${chosen.length ? ` · ${chosen.map(tagLabel).join(", ")}` : ""}${linkText(changes, event.id)}`;
  commit(changes, code.label);
};

const pressInterval = (code) => {
  const { changes, started } = toggleInterval([...events.values()], codes, code, team, src, now(), newId);
  if (started) {
    madeHere.push(started.id);
    selectedId = started.id;
    digits.since = performance.now();
    const chosen = startingTags(code, armed, tags);
    if (chosen.length) started.tags = chosen;
    armed = [];
  }
  flash(code);
  const all = started ? withLinks(code, changes) : changes;
  const stopped = changes.filter((change) => change.next.end != null);
  lastLine.textContent = started
    ? `${code.label} started · ${teamName(team)} · ${whereText(started)}${stopped.length ? ` (stopped ${stopped.map((c) => codeOf(c.next).label).join(", ")})` : ""}${linkText(all.filter((c) => !changes.includes(c)), started.id)}`
    : `${code.label} stopped · ${formatVideo(stopped[0].next.end - stopped[0].next.t)} long`;
  commit(all, started ? `start ${code.label}` : `stop ${code.label}`);
};

// Shift+letter (or a tag button): tag the chosen event, or arm the tag for the next one.
const pressTag = (tag) => {
  const event = events.get(selectedId);
  if (event) {
    const next = toggledTags(event.tags, tags, tag.id);
    const on = next.includes(tag.id);
    lastLine.textContent = `${on ? "Tagged" : "Untagged"} ${codeOf(event)?.label || "code"}: ${tag.label}.`;
    commit([{ id: event.id, next: { ...event, tags: next } }], `${on ? "tag" : "untag"} ${tag.label}`);
    return;
  }
  armed = toggledTags(armed, tags, tag.id);
  lastLine.textContent = armed.length ? `Next code gets: ${armed.map(tagLabel).join(", ")}.` : "No tags waiting.";
  render();
};

// Numbers typed within a second of each other build one shirt number ("1", "0": 10),
// for the chosen event; it is saved once typing pauses.
const digits = { text: "", timer: null, since: 0 };
const pressDigit = (digit) => {
  const event = events.get(selectedId);
  if (!event) { lastLine.textContent = "Choose or make a code first, then type the player's number."; return; }
  digits.text = (digits.text + digit).slice(-2);
  clearTimeout(digits.timer);
  const number = Number(digits.text);
  lastLine.textContent = `${codeOf(event)?.label || "Code"}: player ${number}${playerName(event.team, number) ? ` ${playerName(event.team, number)}` : ""}...`;
  const done = () => {
    digits.text = "";
    const current = events.get(event.id);
    if (!current || current.player === number) return;
    commit([{ id: current.id, next: { ...current, player: number } }], `player ${number}`);
    lastLine.textContent = `${codeOf(current)?.label || "Code"} · ${playerText(current.team, number)}.`;
  };
  if (digits.text.length >= 2) done(); else digits.timer = setTimeout(done, 900);
};
const playerName = (side, number) => (squads[side] || []).find((player) => player.number === number)?.name || "";
const playerText = (side, number) => `#${number}${playerName(side, number) ? ` ${playerName(side, number)}` : ""}`;

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
  intervalGrid.hidden = !codes.some((code) => code.kind === "interval");
  $("#intervals-title").hidden = intervalGrid.hidden;
  $("[data-tag-section]").hidden = !tags.length;
  $("[data-tag-grid]").replaceChildren(...tags.map((tag) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.tag = tag.id;
    button.setAttribute("aria-pressed", "false");
    const name = document.createElement("span");
    name.textContent = tag.label;
    const key = document.createElement("kbd");
    key.textContent = `⇧${tag.key}`;
    button.append(name, key);
    button.title = `${tag.label} (Shift+${tag.key})${tag.group ? `, one of its group` : ""}`;
    button.onclick = () => pressTag(tag);
    return button;
  }));
  $("[data-panel-name]").textContent = panel?.name || "";
};

// A tag is pressed when the chosen event has it, or (with none chosen) when it waits for the next one.
const renderTags = () => {
  const event = events.get(selectedId);
  const on = event ? event.tags || [] : armed;
  $("[data-tag-hint]").textContent = event ? "Shift+letter tags the chosen event" : "Shift+letter tags the next code";
  document.querySelectorAll("[data-tag]").forEach((button) => {
    button.setAttribute("aria-pressed", String(on.includes(button.dataset.tag)));
    button.classList.toggle("is-armed", !event && on.includes(button.dataset.tag));
  });
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
    document.querySelector(`[data-squad-name="${side}"]`).textContent = teamName(side);
    const squadInput = document.querySelector(`[data-squad="${side}"]`);
    if (document.activeElement !== squadInput && !pendingSquads) squadInput.value = squadText(squads[side]);
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
  const player = $("[data-edit-player]");
  if (document.activeElement !== player) player.value = event.player ?? "";
  $("[data-edit-player-name]").textContent = event.player != null ? playerName(event.team, event.player) : "";
  $("[data-edit-tags]").replaceChildren(...(event.tags || []).map((id) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "code-chip";
    chip.textContent = tagLabel(id);
    chip.setAttribute("aria-label", `Remove tag ${tagLabel(id)}`);
    chip.title = "Remove this tag";
    chip.onclick = () => { const tag = tags.find((item) => item.id === id); if (tag) pressTag(tag); };
    return chip;
  }));
};

const render = () => {
  renderTeams();
  renderRunning();
  renderEditor();
  renderTags();
  renderPitch();
  $("[data-undo]").disabled = !history.canUndo;
  $("[data-redo]").disabled = !history.canRedo;
  const sorted = [...events.values()].sort((a, b) => order(a) - order(b));
  $("[data-count]").textContent = `(${sorted.length})`;
  $("[data-list-empty]").hidden = sorted.length > 0;
  $("[data-filter-link]").hidden = !sorted.length || (project.source && !["coded", "both"].includes(project.source));
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
    const extra = [event.player != null ? playerText(event.team, event.player) : "", ...(event.tags || []).map(tagLabel)].filter(Boolean);
    detail.textContent = `${teamName(event.team)}${extra.length ? ` · ${extra.join(", ")}` : ""} · ${where ? where.period.name : "before kick-off"}${span} · ${formatVideo(event.t)}`;
    jump.append(clock, label, detail);
    jump.title = "Choose and jump to this moment";
    jump.onclick = () => jumpTo(event);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "code-remove";
    remove.setAttribute("aria-label", `Delete ${code?.label || "code"} at ${clock.textContent}`);
    remove.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5"/></svg>';
    remove.onclick = () => removeCode(event.id);
    item.append(jump);
    if (liveMode && event.end !== null) {
      const clip = document.createElement("button");
      clip.type = "button";
      clip.className = "code-remove code-clip";
      clip.title = "Save this moment as a clip now";
      clip.setAttribute("aria-label", `Save a clip of ${code?.label || "code"} at ${clock.textContent}`);
      clip.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.5v7.5M5 7l3 3 3-3M3 12.5h10"/></svg>';
      clip.onclick = () => saveLiveClip(event, clip);
      item.append(clip);
    }
    item.append(remove);
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
  if (liveMode && !(project.markers || {})["1H"]) text = "Press Kick-off above when the match starts, so your codes get a match clock. They are saved meanwhile.";
  else if (project.source === "both" && !(project.markers || {})["1H"]) text = "Set the first-half kick-off on Intake so your codes join the match feed's events in Filter.";
  else if (project.source === "both") text = before
    ? `Your codes join the match feed's events in Filter and export; ${before} before the first kick-off on this video ${before === 1 ? "is" : "are"} left out. The Analyst Room keeps using the feed alone.`
    : "Your codes join the match feed's events in Filter and export. The Analyst Room keeps using the feed alone, so nothing is counted twice.";
  else if (scraped) text = "This project's events come from a match feed. Your first code adds your codes to them in Filter and export.";
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
$("[data-edit-player]").onchange = (change) => {
  const text = change.target.value.trim();
  const number = Math.round(Number(text));
  if (text && !(Number.isFinite(number) && number >= 0 && number <= 99)) { renderEditor(); return; }
  edit(selectedId, { player: text ? number : null }, text ? `player ${number}` : "clear player");
};
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
  if (key === "escape") { selectedId = null; armed = []; render(); return; }
  if (!event.shiftKey && (key === "h" || key === "a")) { chooseTeam(key === "h" ? "home" : "away"); return; }
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
  if (/^[0-9]$/.test(event.key)) { event.preventDefault(); pressDigit(event.key); return; }
  if (event.shiftKey && /^[a-z]$/.test(key)) {
    const tag = tags.find((item) => item.key === key.toUpperCase());
    if (tag) { event.preventDefault(); pressTag(tag); }
    return;
  }
  const code = codes.find((item) => item.key === key);
  if (!code) return;
  event.preventDefault();
  if (code.kind === "interval") pressInterval(code); else addCode(code);
});

// ---------------------------------------------------------------------------
// Pitch location (C4): click where the chosen event happened, drag to its end.
// The pitch is drawn with the event's team attacking to the right, in the feeds'
// scale (x along, y across from the right touchline), so lane and depth filters work.
// ---------------------------------------------------------------------------
const pitch = $("[data-pitch]");
const marks = $("[data-pitch-marks]");
const svgPoint = (pointer) => {
  const point = pitch.createSVGPoint();
  point.x = pointer.clientX;
  point.y = pointer.clientY;
  return point.matrixTransform(pitch.getScreenCTM().inverse());
};
const svg = (tag, attrs) => {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
};
const drawMarks = (start, end) => {
  const parts = [];
  if (start && end) parts.push(svg("line", { class: "code-pitch-path", x1: start.sx, y1: start.sy, x2: end.sx, y2: end.sy }),
    svg("circle", { class: "code-pitch-end", cx: end.sx, cy: end.sy, r: 1.3 }));
  if (start) parts.push(svg("circle", { class: "code-pitch-start", cx: start.sx, cy: start.sy, r: 1.7 }));
  marks.replaceChildren(...parts);
};
let dragStart = null;
const renderPitch = () => {
  const event = events.get(selectedId);
  pitch.classList.toggle("is-idle", !event);
  $("[data-pitch-direction]").textContent = event ? `${teamName(event.team)} attack →` : "";
  $("[data-pitch-clear]").hidden = !event || event.x == null;
  $("[data-pitch-status]").textContent = !event ? "· choose or make a code first"
    : event.x == null ? "· not placed" : `· ${placed(event)}`;
  if (dragStart) return;
  const at = event && event.x != null ? pitchPoint.toSvg(event.x, event.y) : null;
  const end = event && event.endX != null ? pitchPoint.toSvg(event.endX, event.endY) : null;
  drawMarks(at, end);
};
pitch.addEventListener("pointerdown", (pointer) => {
  if (pointer.button !== 0) return;
  if (!events.get(selectedId)) { lastLine.textContent = "Choose or make a code, then click where it happened."; return; }
  pitch.setPointerCapture(pointer.pointerId);
  const { x, y } = svgPoint(pointer);
  dragStart = pitchPoint.fromSvg(x, y);
  drawMarks(pitchPoint.toSvg(dragStart.x, dragStart.y), null);
});
pitch.addEventListener("pointermove", (pointer) => {
  if (!dragStart) return;
  const { x, y } = svgPoint(pointer);
  const end = pitchPoint.fromSvg(x, y);
  drawMarks(pitchPoint.toSvg(dragStart.x, dragStart.y), pitchPoint.moved(dragStart, end) ? pitchPoint.toSvg(end.x, end.y) : null);
});
const finishDrag = (pointer, cancelled = false) => {
  if (!dragStart) return;
  const start = dragStart;
  dragStart = null;
  const event = events.get(selectedId);
  if (cancelled || !event) { renderPitch(); return; }
  const { x, y } = svgPoint(pointer);
  const end = pitchPoint.fromSvg(x, y);
  const next = { ...event, x: start.x, y: start.y, endX: null, endY: null };
  if (pitchPoint.moved(start, end)) Object.assign(next, { endX: end.x, endY: end.y });
  commit([{ id: event.id, next }], `place ${codeOf(event)?.label || "code"}`);
  lastLine.textContent = `${codeOf(event)?.label || "Code"} placed: ${placed(next)}.`;
};
pitch.addEventListener("pointerup", (pointer) => finishDrag(pointer));
pitch.addEventListener("pointercancel", (pointer) => finishDrag(pointer, true));
$("[data-pitch-clear]").onclick = () => {
  const event = events.get(selectedId);
  if (event) commit([{ id: event.id, next: { ...event, x: null, y: null, endX: null, endY: null } }], "clear location");
};

// ---------------------------------------------------------------------------
// Squads and code panels (templates)
// ---------------------------------------------------------------------------
document.querySelectorAll("[data-squad]").forEach((input) => {
  input.addEventListener("change", () => {
    try {
      const players = parseSquad(input.value);
      squads = { ...squads, [input.dataset.squad]: players };
      pendingSquads = { ...squads };
      showError("");
      flush();
      render();
    } catch (error) { showError(`${teamName(input.dataset.squad)} squad: ${error.message}`); }
  });
});

function usePanel(next, nextSquads) {
  panel = next;
  codes = next.codes;
  tags = next.tags || [];
  if (nextSquads) squads = nextSquads;
  armed = armed.filter((id) => tags.some((tag) => tag.id === id));
  $("[data-leads] tbody").replaceChildren();
}

const templateSelect = $("[data-template-select]");
const renderTemplates = () => {
  const chosen = templateSelect.value;
  const own = templates.filter((item) => !item.builtin);
  const group = (label, items) => {
    const element = document.createElement("optgroup");
    element.label = label;
    element.append(...items.map((item) => new Option(item.name, item.id)));
    return element;
  };
  templateSelect.replaceChildren(group("Built in", templates.filter((item) => item.builtin)), ...(own.length ? [group("Yours", own)] : []));
  templateSelect.value = templates.some((item) => item.id === chosen) ? chosen
    : templates.some((item) => item.id === panel?.id) ? panel.id : templates[0]?.id || "";
  syncTemplateButtons();
};
const syncTemplateButtons = () => {
  const chosen = templates.find((item) => item.id === templateSelect.value);
  $("[data-template-delete]").disabled = !chosen || chosen.builtin;
  $("[data-template-use]").disabled = !chosen;
};
templateSelect.onchange = syncTemplateButtons;
const loadTemplates = async () => {
  try { templates = (await projectRequest("/api/code-templates")).templates; renderTemplates(); }
  catch (error) { showError(error.message); }
};

// The project's panel changes on the engine first: it refuses a panel that lacks codes the project has used.
const applyPanel = async (next, label) => {
  await flush();
  const { builtin, ...clean } = next;
  const result = await projectRequest(`/api/projects/${encodeURIComponent(project.id)}/codes`, { panel: clean });
  project = result.project;
  unplaced = new Set(result.unplaced);
  usePanel(result.panel, result.squads);
  renderGrid();
  renderLeads();
  render();
  lastLine.textContent = `Now coding with ${result.panel.name}${label ? ` (${label})` : ""}.`;
};

$("[data-template-use]").onclick = async () => {
  const chosen = templates.find((item) => item.id === templateSelect.value);
  if (!chosen) return;
  try { await applyPanel(chosen); showError(""); } catch (error) { showError(error.message); }
};
$("[data-template-save]").onclick = async () => {
  const nameInput = $("[data-template-name]");
  const name = nameInput.value.trim() || panel.name;
  try {
    const result = await projectRequest("/api/code-templates", { template: { ...panel, name } });
    templates = result.templates;
    renderTemplates();
    templateSelect.value = result.template.id;
    syncTemplateButtons();
    nameInput.value = "";
    lastLine.textContent = `Saved the template ${result.template.name}; every project can use it.`;
    showError("");
  } catch (error) { showError(error.message); }
};
$("[data-template-delete]").onclick = async () => {
  const chosen = templates.find((item) => item.id === templateSelect.value);
  if (!chosen || chosen.builtin) return;
  try {
    templates = (await projectRequest("/api/code-templates/delete", { id: chosen.id })).templates;
    renderTemplates();
    lastLine.textContent = `Deleted the template ${chosen.name}. Projects coded with it keep their own copy.`;
  } catch (error) { showError(error.message); }
};
$("[data-template-export]").onclick = async () => {
  try {
    const result = await projectRequest("/api/code-templates/export", { template: panel });
    showSaved(result.saved, "Code panel");
  } catch (error) { showSaveError(error.message, "Code panel"); }
};
const fileInput = $("[data-template-file]");
$("[data-template-import]").onclick = () => fileInput.click();
fileInput.onchange = async () => {
  const file = fileInput.files[0];
  fileInput.value = "";
  if (!file) return;
  try {
    if (file.size > 200000) throw new Error("That file is too large to be a code panel.");
    let value;
    try { value = JSON.parse(await file.text()); } catch { throw new Error("That file is not a code panel (it is not JSON)."); }
    const result = await projectRequest("/api/code-templates", { template: value });
    templates = result.templates;
    renderTemplates();
    templateSelect.value = result.template.id;
    syncTemplateButtons();
    lastLine.textContent = `Imported ${result.template.name}. Choose Use to code with it.`;
    showError("");
  } catch (error) { showError(`Could not import: ${error.message}`); }
};

// Editing the panel: names, keys, colours, codes, tags, and the links between them
// (a code starting or stopping interval codes, or adding tags).
const dialog = $("[data-panel-dialog]");
const draft = { codes: [], tags: [] };
const openLinks = new Set(); // codes whose links row is open
const slug = (text, taken) => {
  const base = String(text).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32) || "item";
  let id = base;
  for (let n = 2; taken.has(id); n += 1) id = `${base}-${n}`;
  return id;
};
const cellInput = (attrs, onInput) => {
  const input = document.createElement("input");
  Object.assign(input, attrs);
  input.addEventListener("input", () => onInput(input.value));
  const cell = document.createElement("td");
  cell.append(input);
  return cell;
};
const removeCell = (label, onRemove) => {
  const cell = document.createElement("td");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "code-remove";
  button.setAttribute("aria-label", label);
  button.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
  button.onclick = onRemove;
  cell.append(button);
  return cell;
};
const element = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  node.append(...children);
  return node;
};
const LINK_LIMIT_TEXT = { starts: `A code starts at most ${LINK_LIMITS.starts} intervals.`,
  stops: `A code stops at most ${LINK_LIMITS.stops} intervals.`, tags: `A code adds at most ${LINK_LIMITS.tags} tags.` };
const linkCount = (code) => [code.starts, code.stops, code.tags].reduce((sum, list) => sum + (list?.length || 0), 0);
// One code's links: which intervals it starts (and for which team), stops, and which tags it adds.
const linksEditor = (index) => {
  const code = draft.codes[index];
  const targets = linkTargets(draft.codes, code);
  const note = element("p", { className: "code-links-note" });
  note.setAttribute("role", "status");
  const update = (next, field, revert) => {
    if (!next) { note.textContent = LINK_LIMIT_TEXT[field]; revert(); return; }
    note.textContent = "";
    draft.codes[index] = next;
    const toggle = $(`[data-links-for="${CSS.escape(code.id)}"]`);
    if (toggle) {
      const summary = linkSummary(next, draft.codes, draft.tags);
      toggle.querySelector(".code-links-count").textContent = linkCount(next) || "";
      toggle.title = summary || "No links";
    }
  };
  const group = (title, items, empty, build) => element("fieldset", { className: "code-links-group" },
    element("legend", {}, title), ...(items.length ? items.map(build) : [element("p", { className: "code-links-empty" }, empty)]));
  const teamOf = (target) => (draft.codes[index].starts || []).find((link) => link.code === target.id)?.team || "";
  const starts = group("Starts", targets, "Add an interval code to start it from here.", (target) => {
    const select = element("select", {}, new Option("No", ""), new Option("Same team", "same"), new Option("Other team", "other"));
    select.setAttribute("aria-label", `${code.label} starts ${target.label}`);
    select.value = teamOf(target);
    let before = select.value;
    select.onchange = () => {
      update(setStart(draft.codes[index], target.id, select.value), "starts", () => { select.value = before; });
      before = select.value;
    };
    return element("label", { className: "code-links-item" }, element("span", {}, target.label), select);
  });
  const checks = (field) => (item) => {
    const box = element("input", { type: "checkbox", checked: (draft.codes[index][field] || []).includes(item.id) });
    box.onchange = () => update(toggleLink(draft.codes[index], field, item.id, box.checked), field, () => { box.checked = !box.checked; });
    return element("label", { className: "code-links-item code-links-check" }, box, element("span", {}, item.label));
  };
  const stops = group("Stops", targets, "Add an interval code to stop it from here.", checks("stops"));
  const tags = group("Adds tags", draft.tags, "Add a tag to the panel first.", checks("tags"));
  return element("tr", { className: "code-links-row", id: `links-${code.id}` },
    element("td", { colSpan: 6 }, element("p", { className: "code-links-kind" }, code.kind === "interval" ? "Interval code" : "Instant code"),
      element("div", { className: "code-links" }, starts, stops, tags), note));
};
const renderDraft = () => {
  // Links to codes or tags that were removed go with them.
  draft.codes = draft.codes.map((code) => pruneLinks(code, draft.codes, draft.tags));
  $("[data-panel-codes]").replaceChildren(...draft.codes.flatMap((code, index) => {
    const row = document.createElement("tr");
    row.append(
      cellInput({ type: "text", value: code.label, maxLength: 40, ariaLabel: "Code name" }, (value) => { draft.codes[index].label = value; }),
      cellInput({ type: "text", value: code.key, maxLength: 1, className: "code-key-input", ariaLabel: `${code.label}: key` }, (value) => { draft.codes[index].key = value.toLowerCase(); }),
      cellInput({ type: "color", value: code.colour, ariaLabel: `${code.label}: colour` }, (value) => { draft.codes[index].colour = value; }),
    );
    const kind = document.createElement("td");
    kind.textContent = code.kind === "interval" ? "Interval" : "Instant";
    const open = openLinks.has(code.id);
    const summary = linkSummary(code, draft.codes, draft.tags);
    const toggle = element("button", { type: "button", className: "code-links-toggle", title: summary || "No links" },
      "Links", element("span", { className: "code-links-count" }, String(linkCount(code) || "")));
    toggle.dataset.linksFor = code.id;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-controls", `links-${code.id}`);
    toggle.setAttribute("aria-label", `${code.label}: links`);
    toggle.onclick = () => {
      // Read the current state: a rename or a link change since this row was drawn must not be lost.
      if (openLinks.has(code.id)) openLinks.delete(code.id); else openLinks.add(code.id);
      renderDraft();
      $(`[data-links-for="${CSS.escape(code.id)}"]`)?.focus();
    };
    row.append(kind, element("td", {}, toggle),
      removeCell(`Remove ${code.label}`, () => { draft.codes.splice(index, 1); renderDraft(); }));
    return open ? [row, linksEditor(index)] : [row];
  }));
  $("[data-panel-tags]").replaceChildren(...draft.tags.map((tag, index) => {
    const row = document.createElement("tr");
    row.append(
      cellInput({ type: "text", value: tag.label, maxLength: 40, ariaLabel: "Tag name" }, (value) => { tag.label = value; }),
      cellInput({ type: "text", value: tag.key, maxLength: 1, className: "code-key-input", ariaLabel: `${tag.label}: key` }, (value) => { tag.key = value.toUpperCase(); }),
      cellInput({ type: "text", value: tag.group || "", maxLength: 40, ariaLabel: `${tag.label}: group`, placeholder: "none" }, (value) => { tag.group = value; }),
      removeCell(`Remove ${tag.label}`, () => { draft.tags.splice(index, 1); renderDraft(); }),
    );
    return row;
  }));
};
const freeKey = (used, letters) => [...letters].find((letter) => !used.has(letter)) || "";
$("[data-template-edit]").onclick = () => {
  draft.name = panel.name;
  draft.codes = structuredClone(panel.codes);
  draft.tags = structuredClone(panel.tags || []);
  openLinks.clear();
  $("[data-panel-edit-name]").value = panel.name;
  $("[data-panel-error]").hidden = true;
  renderDraft();
  dialog.showModal();
};
dialog.querySelectorAll("[data-add-code]").forEach((button) => {
  button.onclick = () => {
    const interval = button.dataset.addCode === "interval";
    const label = interval ? "New interval" : "New code";
    const key = freeKey(new Set(draft.codes.map((code) => code.key)), "qwertyuiopsdfgjklzxcvbnm");
    draft.codes.push({ id: slug(label, new Set(draft.codes.map((code) => code.id))), label, kind: interval ? "interval" : "instant",
      type: label, outcome: "Successful", key, colour: "#8fd3ff", before: interval ? 3 : 5, after: interval ? 2 : 5 });
    renderDraft();
    $("[data-panel-codes]").lastElementChild?.querySelector("input")?.select();
  };
});
$("[data-add-tag]").onclick = () => {
  const key = freeKey(new Set(draft.tags.map((tag) => tag.key)), "ABCDEFGIJKLMNOPQRSTUVWXYZ");
  draft.tags.push({ id: slug("tag", new Set(draft.tags.map((tag) => tag.id))), label: "New tag", key });
  renderDraft();
  $("[data-panel-tags]").lastElementChild?.querySelector("input")?.select();
};
$("[data-panel-cancel]").onclick = () => dialog.close();
$("[data-panel-form]").onsubmit = async (submit) => {
  submit.preventDefault();
  const next = {
    version: 1, id: panel.id, name: $("[data-panel-edit-name]").value.trim(),
    // A new code's event type follows its name; links to removed codes or tags are dropped.
    codes: draft.codes.map((code) => pruneLinks(
      { ...code, type: code.type === "New code" || code.type === "New interval" ? code.label : code.type }, draft.codes, draft.tags)),
    tags: draft.tags.map((tag) => {
      const item = { ...tag };
      if (!item.group) delete item.group; else item.group = slug(item.group, new Set());
      return item;
    }),
  };
  try {
    await applyPanel(next, "edited");
    dialog.close();
  } catch (error) {
    const box = $("[data-panel-error]");
    box.textContent = error.message;
    box.hidden = false;
  }
};

// ---------------------------------------------------------------------------
// Live recording (L1): a project without a video can record a stream, play it back while it
// records, and gets the joined recording as its match video when it is saved.
// ---------------------------------------------------------------------------
const liveForm = $("[data-live-form]");
const liveBar = $("[data-live-bar]");
const liveText = $("[data-live-text]");
const liveApi = () => `/api/projects/${encodeURIComponent(projectId)}/live`;
let livePlayer = null;
let liveTimer = 0;
let liveMode = false;

const setLiveMode = (on) => {
  liveMode = on;
  liveBar.hidden = !on;
  $("[data-code-workspace]").classList.toggle("is-live", on);
  if (on) showKickoff();
  if (project) render();
};

// Kick-offs while it records (L2): each press marks the next period's kick-off at the playhead,
// so codes get a match clock from the first one. Intake can still correct them afterwards.
const kickoffButton = $("[data-live-kickoff]");
const showKickoff = () => {
  const next = nextKickoff(project?.markers);
  kickoffButton.textContent = next ? `Kick-off: ${next.name}` : "All kick-offs marked";
  kickoffButton.disabled = !next;
};
kickoffButton.onclick = async () => {
  const next = nextKickoff(project.markers);
  if (!next) return;
  const seconds = Math.floor(video.currentTime);
  const earlier = PERIODS.slice(0, PERIODS.indexOf(next)).map((period) => parseMarker((project.markers || {})[period.key])).filter((value) => value != null);
  if (earlier.some((value) => value >= seconds)) {
    showError(`The ${next.name} kick-off must come after the earlier one. Move the playhead to it first.`);
    return;
  }
  try {
    const result = await saveProject(project.id, { markers: { ...(project.markers || {}), [next.key]: markerText(seconds) } });
    project = result || project;
    rememberProject(project);
    showError("");
    showKickoff();
    render();
    lastLine.textContent = `${next.name} kick-off marked at ${formatVideo(seconds)} in the recording. Intake can correct it.`;
  } catch (error) { showError(error.message); }
};

/** Cut the clip of one coded event from the recording, with its code's lead-in and lead-out. */
const saveLiveClip = async (event, button) => {
  const lead = leadOf(event.code);
  const end = (event.end ?? event.t) + Number(lead.after || 0);
  button.disabled = true;
  try {
    const code = codeOf(event);
    const where = place(project, event.src, event.t);
    const result = await projectRequest(`${liveApi()}/clip`, {
      start: Math.max(0, event.t - Number(lead.before || 0)), end,
      name: `${code?.label || "Clip"} ${where ? formatClock(where.clock) : formatVideo(event.t)}`.replace(/:/g, "."),
    });
    showSaved(result.saved, "Clip");
  } catch (error) {
    showSaveError(error.message, "Clip");
  } finally {
    button.disabled = false;
  }
};

const showLiveForm = async () => {
  $("[data-code-empty-text]").textContent = "Choose the match video on Intake, or record a live stream here. Then press a key each time something happens, and VizorPlay makes the events for you.";
  try {
    const capabilities = await projectRequest("/api/live/capabilities");
    const protocol = $("[data-live-protocol]");
    protocol.replaceChildren(...capabilities.listen.map((name) => new Option(name.toUpperCase(), name)));
    const setPort = () => { $("[data-live-port]").value = String(capabilities.ports[protocol.value] || ""); };
    protocol.onchange = setPort;
    setPort();
    const listen = liveForm.querySelector('input[value="listen"]');
    listen.disabled = !capabilities.listen.length;
    liveForm.hidden = false;
  } catch (error) {
    showError(error.message);
  }
};

liveForm.addEventListener("change", () => {
  const kind = liveForm.querySelector('input[name="live-kind"]:checked').value;
  $("[data-live-url-row]").hidden = kind !== "url";
  $("[data-live-listen-row]").hidden = kind !== "listen";
});

liveForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formError = $("[data-live-form-error]");
  formError.hidden = true;
  const kind = liveForm.querySelector('input[name="live-kind"]:checked').value;
  const source = kind === "url"
    ? { kind, url: $("[data-live-url]").value.trim() }
    : { kind, protocol: $("[data-live-protocol]").value, port: Number($("[data-live-port]").value) };
  const button = liveForm.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    const { live } = await projectRequest(`${liveApi()}/start`, { source });
    enterLive(live);
  } catch (error) {
    formError.textContent = error.message;
    formError.hidden = false;
  } finally {
    button.disabled = false;
  }
});

const enterLive = (live) => {
  $("[data-code-empty]").hidden = true;
  $("[data-code-workspace]").hidden = false;
  sourceSelect.replaceChildren(new Option("Live recording", "1H"));
  $("[data-source-row]").hidden = true;
  setLiveMode(true);
  livePlayer = new LivePlayer(video, (item) => `/api/live/${encodeURIComponent(projectId)}/${item.part}/${item.file}`);
  status.textContent = "Recording live";
  showLive(live);
  clearInterval(liveTimer);
  liveTimer = setInterval(pollLive, 1000);
};

const showLive = (live) => {
  if (!livePlayer) return;
  livePlayer.add(live.new_segments || [], live.codecs);
  liveText.textContent = liveSummary(live);
  liveBar.dataset.state = live.state;
  liveBar.classList.toggle("is-low-disk", Boolean(live.low_disk));
  $("[data-live-stop]").disabled = live.state === "joining";
  scrub.max = String(livePlayer.end || 1);
  livePlayer.pump().catch((error) => showError(error.message));
};

const pollLive = async () => {
  if (!livePlayer) return;
  try {
    const { live } = await projectRequest(`${liveApi()}?after=${livePlayer.segments.length}`);
    if (live.state === "done") return finishLive(live);
    if (live.state === "failed" || live.state === "join_failed" || live.state === "idle") return leaveLive(live);
    showLive(live);
  } catch (error) {
    liveText.textContent = error.message;
  }
};

const stopLive = () => { clearInterval(liveTimer); livePlayer?.close(); livePlayer = null; setLiveMode(false); };

const finishLive = async (live) => {
  stopLive();
  const result = await projectRequest(`/api/projects/${encodeURIComponent(projectId)}`);
  project = result.project;
  rememberProject(project);
  if (!project.video_path) return leaveLive({ error: `The recording was saved as ${live.video_path}, but this project already had a video.` });
  sourceSelect.replaceChildren(new Option("Main video", "1H"));
  renderLeads();
  loadTemplates();
  await loadSource("1H");
  status.textContent = "Ready to code";
  lastLine.textContent = `Recording saved as ${live.video_name}. It is now this match's video.`;
  render();
};

const leaveLive = (live) => {
  stopLive();
  $("[data-code-workspace]").hidden = true;
  $("[data-code-empty]").hidden = false;
  status.textContent = "No video";
  if (live.error) showError(live.error);
  showLiveStart(live);
};

/** The empty screen of a project without a video: the record form, or the unfinished recording to save. */
const showLiveStart = (live) => {
  const unfinished = live.state === "interrupted" || live.state === "join_failed";
  $("[data-live-unfinished]").hidden = !unfinished;
  if (unfinished) {
    $("[data-live-unfinished-text]").textContent = `${formatVideo(live.recorded_seconds)} of a live recording was not saved${live.state === "join_failed" ? " because saving failed" : " before VizorPlay closed"}. Save it to use it as this match's video.`;
    liveForm.hidden = true;
  } else {
    showLiveForm();
  }
};

$("[data-live-save]").onclick = async () => {
  try {
    const { live } = await projectRequest(`${liveApi()}/stop`, {});
    showError("");
    enterLive(live);
  } catch (error) { showError(error.message); }
};
// Stopping ends the recording for good, so it takes a second press within a few seconds.
let stopArmed = 0;
$("[data-live-stop]").onclick = async (event) => {
  const button = event.currentTarget;
  if (!stopArmed) {
    button.textContent = "Press again to stop";
    button.classList.add("is-armed");
    stopArmed = setTimeout(() => { stopArmed = 0; button.textContent = "Stop and save"; button.classList.remove("is-armed"); }, 4000);
    return;
  }
  clearTimeout(stopArmed);
  stopArmed = 0;
  button.textContent = "Stop and save";
  button.classList.remove("is-armed");
  try { showLive((await projectRequest(`${liveApi()}/stop`, {})).live); } catch (error) { showError(error.message); }
};
$("[data-live-edge]").onclick = () => livePlayer?.toEdge();
video.addEventListener("seeking", () => livePlayer?.pump().catch(() => {}));
video.addEventListener("waiting", () => livePlayer?.skipHole());

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
    usePanel(result.panel, result.squads);
    for (const event of result.events) events.set(event.id, event);
    saved = new Set(result.events.map((event) => event.id));
    leads = result.leads || {};
    unplaced = new Set(result.unplaced);
    $("[data-code-project]").textContent = project.project_name || "Untitled project";
    const available = sources(project);
    if (!available.length) {
      renderGrid();
      const { live } = await projectRequest(liveApi());
      if (RECORDING_STATES.has(live.state) || live.state === "joining") {
        enterLive(live);
        return;
      }
      status.textContent = "No video";
      $("[data-code-empty]").hidden = false;
      showLiveStart(live);
      return;
    }
    sourceSelect.replaceChildren(...available.map((item) => new Option(item.key === "1H" ? "Main video" : `${item.key} video`, item.key)));
    $("[data-source-row]").hidden = available.length < 2;
    renderGrid();
    renderLeads();
    loadTemplates();
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
