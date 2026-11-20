import { saveProject, flushProject, newProject, rememberProject } from "./projects.js";
import { annotateClip, revealFolder, saveClip } from "./save-clip.js";
import { openPlayerSearch } from "./player-search.js";
import {
  duration, exportWindows, formatClock, isTrimmed, normaliseClips, parseClock,
  restoreSelection, totalDuration, trimClip,
} from "./timeline.js";

const form = document.querySelector("[data-filter-form]");
const toast = document.querySelector("[data-toast]");
const engineState = document.querySelector("[data-engine-state]");
const matchSelect = document.querySelector("[data-match-select]");
const teamOptions = document.querySelector("[data-team-options]");
const playerOptions = document.querySelector("[data-player-options]");
const actionOptions = document.querySelector("[data-action-options]");
const qualifierGroups = document.querySelector("[data-qualifier-groups]");
const exportButton = document.querySelector("[data-export-button]");
const annotateButton = document.querySelector("[data-annotate-focused]");
const planOutput = document.querySelector("[data-plan-output]");
const jobState = document.querySelector("[data-job-state]");
const jobLogs = document.querySelector("[data-job-logs]");
const jobProgress = document.querySelector("[data-job-progress]");
const cancelJobButton = document.querySelector("[data-cancel-job]");
const snapshotSelect = document.querySelector("[data-snapshot-select]");
const video = document.querySelector("[data-editor-video]");
const track = document.querySelector("[data-clip-list]");
const snapshotStorageKey = "clipmaker.filter-snapshots.v1";
const PERIOD_KEYS = { 1: "1H", 2: "2H", 3: "ET1", 4: "ET2", 5: "PEN" };
let snapshotLibrary = {};

let activeMatch;
let filterMetadata;
let activeJobId;
let toastTimer;
let corrections = [];
let previewRevision = 0;
let previewBusy = false;
let shotsAndKeyPasses = false;
let restoringProject = false;

// Timeline editor state.
let clips = [];
let selected = new Set();
let focusIndex = 0;
let lastRemoved;
let sources = new Map(); // period -> Promise<media url>
let sourceUrls = new Map(); // file path -> media url, so periods in one file share it
let fallbackMode = false; // the footage cannot play here, so clips are rendered
let playAllActive = false;
let draggingEdge = false;

const field = (name) => document.querySelector(`[data-${name}]`);

const persistFilters = () => {
  if (!activeMatch?.id || restoringProject) return Promise.resolve();
  const saving = saveProject(activeMatch.id, {
    project_name: document.querySelector("[data-project-name]").value.trim() || "Untitled project",
    filter_settings: collectOptions(true),
    preview_windows: structuredClone(clips),
    preview_range: { selected: [...selected] },
  });
  saving.catch((error) => showToast(error.message));
  return saving;
};
let persistTimer;
const persistSoon = () => {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(persistFilters, 350);
};

const setExportBusy = (busy) => {
  document
    .querySelectorAll(".filter-rail, .trim-panel, .trim-strip, .clip-timeline, .export-bar fieldset, .export-settings")
    .forEach((element) => (element.inert = busy));
  matchSelect.disabled = busy;
};

const apiRequest = async (path, options = {}) => {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
};

const showToast = (message) => {
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 3200);
};

const setEngineState = (label, connected) => {
  engineState.querySelector("span").textContent = label;
  engineState.classList.toggle("is-offline", !connected);
};

const humanize = (value) =>
  String(value)
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

const makeChoice = ({ name, value, label, count, checked = false }) => {
  const wrapper = document.createElement("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = name;
  input.value = value;
  input.checked = checked;
  const text = document.createElement("span");
  text.textContent = label;
  wrapper.append(input, text);
  if (count !== undefined) {
    const badge = document.createElement("small");
    badge.textContent = Number(count).toLocaleString();
    wrapper.appendChild(badge);
  }
  return wrapper;
};

const selectedValues = (selector) =>
  Array.from(
    form.querySelectorAll(`${selector}:checked`),
    (input) => input.value,
  );

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

const currentTeam = () =>
  form.querySelector('input[name="team"]:checked')?.value || "";

const playerPool = () => {
  const map = filterMetadata?.team_players || {};
  const team = currentTeam();
  if (team) return map[team] || [];
  return [...new Set(Object.values(map).flat())].sort((a, b) =>
    a.localeCompare(b),
  );
};

const renderPlayers = (chosen = []) => {
  const validSelection = new Set(chosen);
  playerOptions.replaceChildren();
  playerPool().forEach((player) => {
    playerOptions.appendChild(
      makeChoice({
        name: "player",
        value: player,
        label: player,
        checked: validSelection.has(player),
      }),
    );
  });
};

const renderTeams = () => {
  teamOptions.replaceChildren();
  const teams = Object.keys(filterMetadata.team_players || {});
  [["", "Both teams"], ...teams.map((team) => [team, team])].forEach(
    ([value, label], index) => {
      const wrapper = document.createElement("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "team";
      input.value = value;
      input.checked = index === 0;
      const text = document.createElement("span");
      text.textContent = label;
      wrapper.append(input, text);
      teamOptions.appendChild(wrapper);
    },
  );
  renderPlayers();
};

const renderActions = () => {
  actionOptions.replaceChildren();
  (filterMetadata.action_types || []).forEach((type) => {
    actionOptions.appendChild(
      makeChoice({ name: "action", value: type, label: humanize(type) }),
    );
  });
};

const renderQualifiers = () => {
  qualifierGroups.replaceChildren();
  const available = filterMetadata.qualifiers.filter(
    (qualifier) => qualifier.available,
  );
  const grouped = new Map();
  available.forEach((qualifier) => {
    if (!grouped.has(qualifier.group)) grouped.set(qualifier.group, []);
    grouped.get(qualifier.group).push(qualifier);
  });
  grouped.forEach((qualifiers, groupName) => {
    const group = document.createElement("details");
    group.open = false;
    group.className = "qualifier-group";
    const heading = document.createElement("summary");
    heading.textContent = groupName;
    const choices = document.createElement("div");
    qualifiers.forEach((qualifier) => {
      choices.appendChild(
        makeChoice({
          name: "qualifier",
          value: qualifier.flag,
          label: qualifier.label,
          count: qualifier.count,
        }),
      );
    });
    group.append(heading, choices);
    qualifierGroups.appendChild(group);
  });
  document.querySelector("[data-qualifier-availability]").textContent =
    `${available.length} of ${filterMetadata.qualifiers.length} available`;
};

const HALF_PERIODS = { "1st half only": 1, "2nd half only": 2 };

// Count what is left in the chosen scope (team, period, players): events per
// action type, and per qualifier within the scope and any chosen action types.
// Returns null when the engine sent no event index (older engine).
const scopeCounts = (index = filterMetadata?.events) => {
  if (!index || !Array.isArray(index.type)) return null;
  const team = currentTeam();
  const teamPosition = team ? index.teams.indexOf(team) : null;
  const players = new Set(
    selectedValues('input[name="player"]').map((name) => index.players.indexOf(name)),
  );
  const period =
    HALF_PERIODS[form.querySelector('input[name="half"]:checked')?.value] || 0;
  const actionTypes = filterMetadata.action_types || [];
  const chosenTypes = new Set(
    selectedValues('input[name="action"]').map((type) => actionTypes.indexOf(type)),
  );
  const inScope = new Uint8Array(index.type.length);
  const types = new Map();
  for (let row = 0; row < index.type.length; row += 1) {
    if (teamPosition !== null && index.team[row] !== teamPosition) continue;
    if (players.size && !players.has(index.player[row])) continue;
    if (period && index.period[row] !== period) continue;
    const type = index.type[row];
    if (type >= 0) types.set(actionTypes[type], (types.get(actionTypes[type]) || 0) + 1);
    if (!chosenTypes.size || chosenTypes.has(type)) inScope[row] = 1;
  }
  const qualifiers = new Map();
  Object.entries(index.qualifiers || {}).forEach(([flag, rows]) => {
    qualifiers.set(flag, rows.reduce((total, row) => total + inScope[row], 0));
  });
  return { types, qualifiers };
};

const setChoiceCount = (input, count) => {
  const wrapper = input.closest("label");
  let badge = wrapper.querySelector("small");
  if (!badge) {
    badge = document.createElement("small");
    wrapper.appendChild(badge);
  }
  badge.textContent = Number(count).toLocaleString();
  wrapper.classList.toggle("is-empty", count === 0);
};

const refreshScopeCounts = () => {
  const counts = scopeCounts();
  if (!counts) return;
  form.querySelectorAll('input[name="action"]').forEach((input) => {
    setChoiceCount(input, counts.types.get(input.value) || 0);
  });
  let available = 0;
  form.querySelectorAll('input[name="qualifier"]').forEach((input) => {
    const count = counts.qualifiers.get(input.value) || 0;
    if (count) available += 1;
    setChoiceCount(input, count);
  });
  document.querySelector("[data-qualifier-availability]").textContent =
    `${available} of ${filterMetadata.qualifiers.length} available`;
};

const renderMatchContext = () => {
  document.querySelector("[data-match-name]").textContent =
    `${activeMatch.home_team} vs ${activeMatch.away_team}`;
  document.querySelector("[data-match-score]").textContent =
    `${activeMatch.home_score || 0} - ${activeMatch.away_score || 0} ${activeMatch.score_status || "FT"}`;
  document.querySelector("[data-match-events]").textContent = Number(
    filterMetadata.event_count || activeMatch.event_count || 0,
  ).toLocaleString();
  document.querySelector("[data-match-video]").textContent =
    activeMatch.video_name || "Not selected";
  document.querySelector("[data-xt-min]").disabled = !filterMetadata.has_xt;
  document.querySelector("[data-top-n]").disabled = !filterMetadata.has_xt;
};

const updateSummary = () => {
  const team = currentTeam();
  const players = selectedValues('input[name="player"]');
  const half = form.querySelector('input[name="half"]:checked')?.value;
  const actions = selectedValues('input[name="action"]');
  const qualifiers = selectedValues('input[name="qualifier"]');
  field("summary-team").textContent = team || "Both teams";
  field("summary-players").textContent = players.length
    ? players.length <= 2
      ? players.join(", ")
      : `${players.length} players`
    : "All players";
  field("summary-half").textContent = half;
  field("summary-actions").textContent = actions.length
    ? actions.length <= 2
      ? actions.map(humanize).join(", ")
      : `${actions.length} action types`
    : "All actions";
  field("summary-qualifiers").textContent =
    qualifiers.length ? `${qualifiers.length} active` : "None";
  field("action-count").textContent = actions.length ? `${actions.length} chosen` : "All";
  field("timing-summary").textContent =
    `${field("before-buffer").value || 0}s + ${field("after-buffer").value || 0}s`;
  refreshScopeCounts();
};

// Previews use the same encoding settings as the export.
const encodingSettings = () => ({
  video_crf: Number(field("video-crf").value),
  encoder_preset: field("encoder-preset").value,
  video_encoder: field("video-encoder").value,
  audio_bitrate: field("audio-bitrate").value,
});

const exportScope = () => document.querySelector('input[name="export-scope"]:checked')?.value || "all";
const exportAs = () => document.querySelector('input[name="export-as"]:checked')?.value || "reel";

const collectOptions = (dryRun) => {
  const options = {
    dry_run: dryRun,
    filter_types: selectedValues('input[name="action"]'),
    team_filter: currentTeam(),
    player_filters: selectedValues('input[name="player"]'),
    half_filter: form.querySelector('input[name="half"]:checked').value,
    qualifier_logic: form.querySelector('input[name="qualifier-logic"]:checked')
      .value,
    before_buffer: Number(field("before-buffer").value),
    after_buffer: Number(field("after-buffer").value),
    min_gap: Number(field("min-gap").value),
    pitch_zone_filter: field("pitch-zone").value,
    depth_zone_filter: field("depth-zone").value,
    xt_min: Number(field("xt-min").value),
    top_n: Number(field("top-n").value) || null,
    output_filename: field("output-name").value.trim() || "Highlights.mp4",
    individual_clips: exportAs() === "files",
    export_scope: exportScope(),
    shots_and_key_passes_only: shotsAndKeyPasses,
    timeline_corrections: structuredClone(corrections),
    output_dir: field("output-dir").value.trim(),
    output_format: field("output-format").value,
    ...encodingSettings(),
  };
  selectedValues('input[name="qualifier"]').forEach((flag) => {
    options[flag] = true;
  });
  return options;
};

const setCheckedValues = (name, values = []) => {
  const chosen = new Set(values);
  form.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
    input.checked = chosen.has(input.value);
  });
};

const setRadio = (name, value) => {
  const input = document.querySelector(`input[name="${name}"][value="${CSS.escape(value)}"]`);
  if (input) input.checked = true;
};

const resetFilters = () => {
  form.reset();
  shotsAndKeyPasses = false;
  corrections = [];
  renderCorrections();
  setCheckedValues("action");
  setCheckedValues("qualifier");
  const bothTeams = form.querySelector('input[name="team"][value=""]');
  if (bothTeams) bothTeams.checked = true;
  renderPlayers();
  resetPreview();
  updateSummary();
};

const applyOptions = (options = {}) => {
  resetFilters();
  shotsAndKeyPasses = Boolean(options.shots_and_key_passes_only);
  setCheckedValues("action", options.filter_types || []);
  const team = form.querySelector(
    `input[name="team"][value="${CSS.escape(options.team_filter || "")}"]`,
  );
  if (team) team.checked = true;
  renderPlayers(options.player_filters || []);
  const half = Array.from(form.querySelectorAll('input[name="half"]')).find(
    (input) => input.value === options.half_filter,
  );
  if (half) half.checked = true;
  setRadio("qualifier-logic", options.qualifier_logic || "any");
  const qualifierFlags = Object.keys(options).filter(
    (key) => key.endsWith("_only") && options[key] === true,
  );
  setCheckedValues("qualifier", qualifierFlags);
  const values = {
    "[data-pitch-zone]": options.pitch_zone_filter || "",
    "[data-depth-zone]": options.depth_zone_filter || "",
    "[data-xt-min]": options.xt_min ?? 0,
    "[data-top-n]": options.top_n ?? 0,
    "[data-before-buffer]": options.before_buffer ?? 5,
    "[data-after-buffer]": options.after_buffer ?? 8,
    "[data-min-gap]": options.min_gap ?? 6,
    "[data-output-name]": options.output_filename || "Highlights.mp4",
    "[data-output-dir]": options.output_dir || "",
    "[data-output-format]": options.output_format || ".mp4",
    "[data-video-crf]": options.video_crf ?? 20,
    "[data-encoder-preset]": options.encoder_preset || "veryfast",
    "[data-video-encoder]": options.video_encoder === "software" ? "software" : "auto",
    "[data-audio-bitrate]": options.audio_bitrate || "128k",
  };
  Object.entries(values).forEach(([selector, value]) => {
    document.querySelector(selector).value = value;
  });
  setRadio("export-as", options.individual_clips ? "files" : "reel");
  setRadio("export-scope", options.export_scope === "selected" ? "selected" : "all");
  corrections = structuredClone(options.timeline_corrections || []);
  renderCorrections();
  field("quality").value = "custom";
  updateSummary();
};

const presets = {
  "set-pieces": {
    filter_types: ["Pass"],
    corners_only: true,
    freekicks_only: true,
  },
  progression: {
    filter_types: ["Pass", "Carry"],
    progressive_only: true,
  },
  attacking: {
    filter_types: [
      "Pass",
      "SavedShot",
      "MissedShot",
      "MissedShots",
      "Goal",
      "ShotOnPost",
      "BlockedShot",
      "AttemptSaved",
      "Attempt",
    ],
    shots_and_key_passes_only: true,
    key_passes_only: true,
    depth_zone_filter: "Attacking Third",
  },
  defensive: {
    filter_types: [
      "Tackle",
      "Interception",
      "Clearance",
      "BallRecovery",
      "BlockedPass",
      "Block",
      "Aerial",
      "OffsideProvoked",
    ],
    depth_zone_filter: "Defensive Third",
  },
};

const getSnapshots = () => structuredClone(snapshotLibrary);

const renderSnapshots = () => {
  const snapshots = getSnapshots();
  const names = Object.keys(snapshots).sort((a, b) => a.localeCompare(b));
  snapshotSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = names.length
    ? "Choose a snapshot"
    : "No snapshots saved";
  snapshotSelect.appendChild(placeholder);
  names.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    snapshotSelect.appendChild(option);
  });
  field("load-snapshot").disabled = true;
  field("delete-snapshot").disabled = true;
};

const clockSeconds = (value) => {
  if (!/^\d+:\d{2}(?::\d{2})?$/.test(value.trim()))
    throw new Error("Use MM:SS or HH:MM:SS.");
  const parts = value.trim().split(":").map(Number);
  if (parts.slice(1).some((part) => part > 59))
    throw new Error("Seconds and minutes must be below 60.");
  return parts.reduce((total, part) => total * 60 + part, 0);
};
const renderCorrections = () => {
  field("correction-list").replaceChildren();
  field("correction-count").textContent = corrections.length ? `${corrections.length} active` : "None active";
  corrections.forEach((correction, index) => {
    const row = document.createElement("div");
    const label = document.createElement("span");
    const shift = Number(correction.seconds ?? correction.amount_seconds ?? 0);
    const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
    const from = correction.clock || clock(Number(correction.at_seconds || 0));
    label.textContent = `P${correction.period} from ${from}: ${shift < 0 ? "missing footage" : "extra footage"}, ` +
      `events after that point move ${clock(Math.abs(shift))} ${shift < 0 ? "earlier" : "later"}${correction.note ? ` (${correction.note})` : ""}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.onclick = () => {
      corrections.splice(index, 1);
      renderCorrections();
      resetPreview();
      persistFilters();
    };
    row.append(label, remove);
    field("correction-list").append(row);
  });
};

// ---------------------------------------------------------------------------
// Timeline editor
// ---------------------------------------------------------------------------

const hasFootage = () => Boolean(activeMatch?.video_path);
const clipCount = (count) => `${count} clip${count === 1 ? "" : "s"}`;
const focused = () => clips[focusIndex];

const resetPreview = () => {
  previewRevision++;
  video.pause();
  clips = [];
  selected = new Set();
  focusIndex = 0;
  lastRemoved = undefined;
  field("preview-results").hidden = true;
  field("editor-empty").hidden = false;
  refreshExportState();
  field("summary-note").textContent = "Find clips to build the timeline.";
};

const sourceFor = (period) => {
  const key = PERIOD_KEYS[period] || "1H";
  if (!sources.has(key)) {
    const request = apiRequest("/api/files/reopen", {
      method: "POST",
      body: JSON.stringify({ match_id: activeMatch.id, period: key }),
    }).then(({ file }) => {
      if (!sourceUrls.has(file.path)) sourceUrls.set(file.path, file.url);
      return sourceUrls.get(file.path);
    });
    request.catch(() => sources.delete(key));
    sources.set(key, request);
  }
  return sources.get(key);
};

// Resolves once the element shows `url` with its duration known.
const loadSource = (url) => {
  if (video.dataset.src === url && video.readyState >= 1) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const done = () => { video.removeEventListener("loadedmetadata", ok); video.removeEventListener("error", fail); };
    const ok = () => { done(); resolve(); };
    const fail = () => { done(); reject(new Error("This footage cannot be played in the app's player.")); };
    video.addEventListener("loadedmetadata", ok);
    video.addEventListener("error", fail);
    video.dataset.src = url;
    video.src = url;
  });
};

const footageLimit = (clip) =>
  !fallbackMode && video.dataset.period === String(clip.period) && Number.isFinite(video.duration)
    ? video.duration : Infinity;

const enterFallback = (message) => {
  fallbackMode = true;
  video.pause();
  const notice = field("viewer-message");
  notice.textContent = `${message} Render a clip to watch it.`;
  notice.hidden = false;
  field("render-fallback").hidden = false;
  field("trim-playhead").hidden = true;
};

// Show clip `index` in the viewer; optionally start playing it.
const showClip = async (index, { play = false, at } = {}) => {
  if (!clips.length) return;
  focusIndex = Math.max(0, Math.min(index, clips.length - 1));
  renderFocus();
  const clip = focused();
  if (fallbackMode || !hasFootage()) return;
  const generation = previewRevision;
  try {
    const url = await sourceFor(clip.period);
    if (generation !== previewRevision || clip !== focused()) return;
    await loadSource(url);
    video.dataset.period = String(clip.period);
    if (clip !== focused()) return;
    if (!draggingEdge) renderTrimPanel(); // the footage length now bounds the trim bar
    video.currentTime = at ?? clip.start;
    if (play) await video.play();
  } catch (error) {
    if (error.name === "AbortError" || error.name === "NotAllowedError") return;
    enterFallback(error.message);
  }
};

const updatePlayhead = () => {
  const clip = focused();
  if (!clip) return;
  const now = fallbackMode ? 0 : video.currentTime;
  const inside = Math.min(Math.max(now - clip.start, 0), duration(clip));
  field("clip-clock").textContent = `${formatClock(inside)} / ${formatClock(duration(clip))}`;
  const { from, to } = trimContext(clip);
  const playhead = field("trim-playhead");
  playhead.style.left = `${((now - from) / (to - from)) * 100}%`;
  playhead.hidden = fallbackMode || now < from || now > to;
};

// Stop at the clip's end, or carry on into the next clip.
const watchPlayback = () => {
  if (video.paused) return;
  const clip = focused();
  if (clip && !draggingEdge && video.currentTime >= clip.end - 0.04) {
    if (playAllActive && focusIndex < clips.length - 1) {
      showClip(focusIndex + 1, { play: true });
    } else {
      video.pause();
      video.currentTime = clip.end;
    }
  }
  updatePlayhead();
  requestAnimationFrame(watchPlayback);
};

const setPlayIcon = (playing) => {
  const button = field("play-clip");
  button.setAttribute("aria-label", playing ? "Pause clip" : "Play clip");
  document.querySelector("[data-play-icon]").setAttribute("d", playing ? "M4 3h3v10H4zM9 3h3v10H9z" : "M5 3l8 5-8 5z");
};

const togglePlay = async () => {
  const clip = focused();
  if (!clip) return;
  if (fallbackMode) {
    if (video.src) video.paused ? video.play() : video.pause();
    return;
  }
  if (!video.paused) {
    video.pause();
    return;
  }
  const inside = video.dataset.period === String(clip.period)
    && video.currentTime >= clip.start && video.currentTime < clip.end - 0.1;
  await showClip(focusIndex, { play: true, at: inside ? video.currentTime : clip.start });
};

// The trim bar shows the clip with some footage either side to extend into.
let trimFrame;
const trimContext = (clip) => {
  if (draggingEdge && trimFrame) return trimFrame;
  const pad = Math.max(8, duration(clip) * 0.5);
  const to = clip.end + pad;
  trimFrame = { from: Math.max(0, clip.start - pad), to: Number.isFinite(footageLimit(clip)) ? Math.min(footageLimit(clip), to) : to };
  return trimFrame;
};

const renderTrimPanel = () => {
  const clip = focused();
  if (!clip) return;
  field("trim-number").textContent = `Clip ${focusIndex + 1}`;
  field("trim-label").textContent = clip.label;
  const { from, to } = trimContext(clip);
  field("trim-from").textContent = formatClock(from, false);
  field("trim-to").textContent = formatClock(to, false);
  const position = (seconds) => ((seconds - from) / (to - from)) * 100;
  const region = field("trim-region");
  region.style.left = `${position(clip.start)}%`;
  region.style.width = `${position(clip.end) - position(clip.start)}%`;
  document.querySelector('[data-trim-handle="start"]').style.left = `${position(clip.start)}%`;
  document.querySelector('[data-trim-handle="end"]').style.left = `${position(clip.end)}%`;
  document.querySelector('[data-trim-handle="start"]').setAttribute("aria-valuetext", formatClock(clip.start));
  document.querySelector('[data-trim-handle="end"]').setAttribute("aria-valuetext", formatClock(clip.end));
  document.querySelectorAll("[data-edge-input]").forEach((input) => {
    if (document.activeElement !== input) input.value = formatClock(clip[input.dataset.edgeInput]);
    input.removeAttribute("aria-invalid");
  });
  field("clip-duration").textContent = `${duration(clip).toFixed(1)}s`;
  field("reset-clip").disabled = !isTrimmed(clip);
  field("prev-clip").disabled = focusIndex === 0;
  field("next-clip").disabled = focusIndex >= clips.length - 1;
  updatePlayhead();
};

const blockWidth = (clip) => `${Math.max(64, duration(clip) * Number(field("zoom").value))}px`;

const describeBlock = (item, clip, index) => {
  item.style.width = blockWidth(clip);
  item.querySelector(".clip-number").textContent = index + 1;
  item.querySelector(".clip-length").textContent = `${duration(clip).toFixed(1)}s`;
  item.classList.toggle("is-trimmed", isTrimmed(clip));
  item.querySelector(".clip-body").setAttribute("aria-label",
    `Clip ${index + 1}: ${clip.label}, ${duration(clip).toFixed(1)} seconds${isTrimmed(clip) ? ", trimmed" : ""}`);
};

const renderTimeline = () => {
  track.replaceChildren();
  clips.forEach((clip, index) => {
    const item = document.createElement("li");
    item.className = "clip-block";
    item.dataset.id = clip.id;
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.className = "clip-tick";
    tick.checked = selected.has(clip.id);
    tick.setAttribute("aria-label", `Select clip ${index + 1}`);
    tick.onchange = () => {
      tick.checked ? selected.add(clip.id) : selected.delete(clip.id);
      if (tick.checked && selected.size === 1) setRadio("export-scope", "selected");
      if (!selected.size) setRadio("export-scope", "all");
      item.classList.toggle("is-selected", tick.checked);
      refreshExportState();
      persistFilters();
    };
    const body = document.createElement("button");
    body.type = "button";
    body.className = "clip-body";
    body.innerHTML = '<span class="clip-number"></span><span class="clip-label"></span><span class="clip-length"></span>';
    body.querySelector(".clip-label").textContent = clip.label;
    body.onclick = () => showClip(clips.indexOf(clip));
    body.ondblclick = () => showClip(clips.indexOf(clip), { play: true });
    const handles = ["start", "end"].map((edge) => {
      const handle = document.createElement("span");
      handle.className = `clip-handle clip-handle-${edge}`;
      handle.setAttribute("role", "slider");
      handle.tabIndex = 0;
      handle.setAttribute("aria-label", `Clip ${index + 1} ${edge}`);
      handle.dataset.edge = edge;
      return handle;
    });
    item.classList.toggle("is-selected", selected.has(clip.id));
    item.append(handles[0], tick, body, handles[1]);
    describeBlock(item, clip, index);
    track.append(item);
  });
  field("preview-count").textContent = clips.length;
  field("preview-noun").textContent = clips.length === 1 ? "clip" : "clips";
  field("total-duration").textContent = clips.length ? `· ${formatClock(totalDuration(clips), false)}` : "";
  field("undo-remove").hidden = !lastRemoved;
  renderFocus();
  refreshExportState();
};

const renderFocus = () => {
  track.querySelectorAll(".clip-block").forEach((item, index) => {
    const current = index === focusIndex;
    item.classList.toggle("is-focused", current);
    item.querySelector(".clip-body").setAttribute("aria-current", current ? "true" : "false");
  });
  // Scroll the timeline sideways only; moving the page would hide the viewer.
  const item = track.children[focusIndex];
  if (item) {
    const left = item.offsetLeft; // the track is the offset parent
    if (left < track.scrollLeft || left + item.offsetWidth > track.scrollLeft + track.clientWidth) {
      track.scrollTo({ left: Math.max(0, left - 24), behavior: "smooth" });
    }
  }
  renderTrimPanel();
  resetRenderedClip();
};

// Update one clip after a trim, without rebuilding the timeline.
const applyTrim = (index, clip, { seek = true } = {}) => {
  clips[index] = clip;
  const item = track.children[index];
  if (item) describeBlock(item, clip, index);
  field("total-duration").textContent = `· ${formatClock(totalDuration(clips), false)}`;
  if (index === focusIndex) {
    renderTrimPanel();
    resetRenderedClip();
  }
  persistSoon();
  return clip;
};

const trimEdge = (index, edge, seconds, options) => {
  const clip = clips[index];
  if (!clip) return;
  const next = applyTrim(index, trimClip(clip, edge, seconds, footageLimit(clip)), options);
  if (options?.seek !== false && index === focusIndex && !fallbackMode && video.dataset.period === String(next.period)) {
    video.pause();
    video.currentTime = edge === "start" ? next.start : Math.max(next.start, next.end - 0.05);
  }
};

const removeClip = (index) => {
  const [clip] = clips.splice(index, 1);
  if (!clip) return;
  lastRemoved = { clip, index, wasSelected: selected.delete(clip.id) };
  focusIndex = Math.min(index, clips.length - 1);
  if (!clips.length) {
    video.pause();
    field("summary-note").textContent = "Every clip was removed. Undo, or find clips again.";
  }
  renderTimeline();
  persistFilters();
  if (clips.length) showClip(focusIndex);
};

const refreshExportState = () => {
  const scope = exportScope();
  const count = scope === "selected" ? selected.size : clips.length;
  const withCount = (node, label, count) => {
    const badge = document.createElement("b");
    badge.className = "seg-count";
    badge.textContent = count;
    node.replaceChildren(`${label} `, badge);
  };
  withCount(field("scope-all"), "All clips", clips.length);
  withCount(field("scope-selected"), "Selected", selected.size);
  // Nothing ticked: "Selected" has nothing to export, so it cannot be chosen.
  document.querySelector('input[name="export-scope"][value="selected"]').disabled = !selected.size;
  field("selection-count").textContent = `${selected.size} selected`;
  const files = exportAs() === "files";
  exportButton.textContent = files
    ? `Export ${count} clip${count === 1 ? "" : "s"}`
    : scope === "selected" ? `Export reel of ${count}` : "Export reel";
  exportButton.disabled = !clips.length || !count || Boolean(activeJobId) || !hasFootage();
  exportButton.title = hasFootage() ? "" : "Add match footage in Intake before exporting.";
  annotateButton.disabled = !clips.length || !hasFootage();
  setAnnotateLabel();
};

// Annotate takes the clip in the player, or every ticked clip when more than one is ticked
// (they go into one session on the Annotate tab).
const MAX_ANNOTATE = 30;
const annotateTargets = () => (selected.size > 1 ? clips.filter((clip) => selected.has(clip.id)) : [focused()].filter(Boolean));
const setAnnotateLabel = () => {
  const count = selected.size > 1 ? selected.size : 1;
  const label = [...annotateButton.childNodes].find((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
  if (label) label.textContent = count > 1 ? `Annotate ${count} clips` : "Annotate clip";
  annotateButton.title = count > 1
    ? `Put the ${count} ticked clips into one annotate session and open the first`
    : "Draw on the clip in the player in the analyst editor";
};

const showClips = (windows, savedSelection) => {
  clips = normaliseClips(windows);
  selected = restoreSelection(savedSelection, clips);
  if (savedSelection && !Array.isArray(savedSelection.selected) && selected.size) {
    setRadio("export-scope", "selected");
  }
  focusIndex = 0;
  lastRemoved = undefined;
  fallbackMode = false;
  field("viewer-message").hidden = true;
  field("render-fallback").hidden = true;
  field("editor-empty").hidden = clips.length > 0;
  field("preview-results").hidden = clips.length === 0;
  renderTimeline();
  if (!hasFootage()) {
    const notice = field("viewer-message");
    notice.textContent = "Add the match footage in Intake to watch and export these clips.";
    notice.hidden = false;
  } else {
    showClip(0);
  }
};

// Rendered clips are the fallback for footage the app's player cannot decode.
let renderRevision = 0;
const resetRenderedClip = () => {
  renderRevision++;
  if (!fallbackMode) return;
  video.pause();
  video.removeAttribute("src");
  delete video.dataset.src;
  video.load();
  field("render-download").hidden = true;
  field("render-annotate").hidden = true;
  field("render-status").textContent = "";
};

const renderClip = async () => {
  const clip = focused();
  if (!clip) return;
  const version = ++renderRevision;
  const generation = previewRevision;
  const button = field("render-clip");
  button.disabled = true;
  field("render-status").textContent = "Rendering clip...";
  try {
    const result = await apiRequest("/api/previews/render", {
      method: "POST",
      body: JSON.stringify({ match_id: activeMatch.id, start: clip.start, end: clip.end, period: clip.period, ...encodingSettings() }),
    });
    if (version !== renderRevision || generation !== previewRevision) return;
    video.dataset.src = result.file.url;
    video.src = result.file.url;
    const save = field("render-download");
    save.onclick = () => saveClip(result.file.url, clip.label || `Clip ${focusIndex + 1}`, save);
    save.hidden = false;
    const annotate = field("render-annotate");
    annotate.onclick = () => annotateClip(result.file.url, clip.label || `Clip ${focusIndex + 1}`, annotate, activeMatch.id);
    annotate.hidden = false;
    field("render-status").textContent = "Clip ready";
  } catch (error) {
    field("render-status").textContent = error.message;
  } finally {
    button.disabled = false;
  }
};

// ---------------------------------------------------------------------------
// Find clips and export
// ---------------------------------------------------------------------------

const formatDuration = (seconds) => {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};
const formatSize = (bytes) => {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  const power = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** power).toFixed(power > 1 ? 1 : 0)} ${units[power]}`;
};
// What the engine is doing right now, in words, from its progress report.
const exportStage = (progress) => {
  if (!progress) return "Getting the footage ready";
  const clipTotal = progress.clip_total;
  if (progress.phase === "clips" && clipTotal) return `Cut ${Math.min(progress.current, clipTotal)} of ${clipTotal} clip${clipTotal === 1 ? "" : "s"}`;
  if (progress.phase === "files" && progress.total) return `Saved ${progress.current} of ${progress.total} clip${progress.total === 1 ? "" : "s"}`;
  if (progress.phase === "concat") return "Joining the clips into one reel";
  if (progress.phase === "assembly") return "Building the reel";
  if (progress.phase === "done") return "Finishing up";
  return progress.total ? `Step ${progress.current} of ${progress.total}` : "Working";
};

let finishedJobId;
const renderJob = (job) => {
  const labels = {
    queued: "Queued",
    running: "Exporting",
    complete: "Export complete",
    failed: "Export failed",
    cancelled: "Export cancelled",
  };
  const finished = ["complete", "failed", "cancelled"].includes(job.status);
  const logs = job.logs || [];
  planOutput.dataset.jobStatus = job.status;
  jobState.textContent = labels[job.status] || job.status;
  jobLogs.textContent = logs.join("\n") || "Preparing clips...";
  jobLogs.scrollTop = jobLogs.scrollHeight;
  const progress = job.progress;
  const ratio = job.status === "complete" ? 1 : progress?.total ? Math.min(1, progress.current / progress.total) : 0;
  const percent = Math.round(ratio * 100);
  jobProgress.style.width = `${Math.max(finished ? 0 : 3, percent)}%`;
  field("job-bar").setAttribute("aria-valuenow", String(percent));
  field("job-percent").textContent = finished ? "" : `${percent}%`;
  const elapsed = Number(progress?.elapsed || 0);
  const remaining = ratio > 0.05 && ratio < 1 ? elapsed / ratio - elapsed : null;
  field("job-meta").textContent = finished || !elapsed ? "" :
    `${formatDuration(elapsed)} elapsed${remaining === null ? "" : ` · about ${formatDuration(remaining)} left`}`;
  const files = job.files || [];
  field("job-detail").textContent =
    job.status === "complete" ? (files.length === 1 ? "1 file saved" : `${files.length} files saved`) :
    job.status === "failed" ? (logs[logs.length - 1] || "The engine stopped before finishing.") :
    job.status === "cancelled" ? "Stopped before it finished." :
    job.status === "queued" ? "Waiting for the engine" : exportStage(progress);
  if (job.status === "failed") field("job-log").open = true;
  cancelJobButton.hidden = finished;
  if (!finished) return;
  activeJobId = undefined;
  setExportBusy(false);
  refreshExportState();
  if (job.status !== "complete") return;
  finishedJobId = job.id;
  field("export-folder").textContent = job.output_dir || "";
  field("export-folder").title = job.output_dir || "";
  field("export-done").hidden = false;
  const list = field("export-files");
  list.replaceChildren();
  files.forEach((file) => {
    const row = document.createElement("div");
    row.className = "export-file";
    const link = document.createElement("a");
    link.href = file.url;
    link.download = file.name;
    link.textContent = file.name;
    const size = document.createElement("span");
    size.textContent = formatSize(file.size);
    row.append(link, size);
    list.append(row);
  });
  const previous = activeMatch.export_history || [];
  activeMatch.export_history = [...previous, { id: job.id, finished_at: job.finished_at, files: job.files || [] }].slice(-50);
  saveProject(activeMatch.id, { status: "complete", export_history: activeMatch.export_history }).catch((error) => showToast(error.message));
};

const pollJob = async (jobId) => {
  try {
    const result = await apiRequest(`/api/jobs/${jobId}`);
    renderJob(result.job);
    if (!["complete", "failed", "cancelled"].includes(result.job.status)) {
      setTimeout(() => pollJob(jobId), 300);
    }
  } catch (error) {
    jobState.textContent = "Connection interrupted";
    field("job-detail").textContent = "Reconnecting to the engine...";
    jobLogs.textContent = error.message;
    setTimeout(() => pollJob(jobId), 2000);
  }
};

const startExport = async () => {
  if (activeJobId || previewBusy || !clips.length) return;
  if (!hasFootage()) {
    showToast("Add match footage in Intake before exporting");
    return;
  }
  const windows = exportWindows(clips, exportScope(), selected);
  if (!windows.length) {
    showToast("Tick the clips to export first.");
    return;
  }
  video.pause();
  planOutput.hidden = false;
  setExportBusy(true);
  cancelJobButton.hidden = false;
  exportButton.disabled = true;
  planOutput.dataset.jobStatus = "queued";
  jobState.textContent = "Starting export";
  field("job-detail").textContent = "Getting the footage ready";
  field("job-percent").textContent = "";
  field("job-meta").textContent = "";
  field("job-log").open = false;
  jobLogs.textContent = "Preparing clips...";
  jobProgress.style.width = "3%";
  field("export-done").hidden = true;
  field("export-files").replaceChildren();
  try {
    await persistFilters();
    await flushProject();
    const result = await apiRequest("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        match_id: activeMatch.id,
        options: { ...collectOptions(false), clip_windows: windows },
      }),
    });
    activeJobId = result.job.id;
    renderJob(result.job);
    pollJob(activeJobId);
  } catch (error) {
    activeJobId = undefined;
    setExportBusy(false);
    cancelJobButton.hidden = true;
    planOutput.dataset.jobStatus = "failed";
    jobState.textContent = "Setup needs attention";
    field("job-detail").textContent = error.message;
    jobLogs.textContent = error.message;
    jobProgress.style.width = "0%";
    refreshExportState();
    showToast(error.message);
  }
};

const buildPreview = async () => {
  if (activeJobId || previewBusy) return;
  if (!activeMatch?.id) {
    showToast("Choose a match first.");
    return;
  }
  resetPreview();
  const generation = previewRevision;
  previewBusy = true;
  const button = form.querySelector("[type=submit]");
  button.disabled = true;
  field("summary-note").textContent = "Finding clips...";
  try {
    const result = await apiRequest("/api/previews", {
      method: "POST",
      body: JSON.stringify({
        match_id: activeMatch.id,
        options: collectOptions(true),
      }),
    });
    if (generation !== previewRevision) return;
    setRadio("export-scope", "all");
    showClips(result.windows);
    await persistFilters();
    field("summary-note").textContent = clips.length
      ? `${clipCount(clips.length)} ready to review.`
      : "No matching clips. Adjust the filters.";
    if (clips.length && window.matchMedia("(max-width: 900px)").matches) {
      document.querySelector(".editor").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    showToast(error.message);
    field("summary-note").textContent = error.message;
  } finally {
    previewBusy = false;
    button.disabled = false;
  }
};

const loadMatch = async (matchId) => {
  resetPreview();
  activeMatch = undefined;
  sources = new Map();
  sourceUrls = new Map();
  video.removeAttribute("src");
  delete video.dataset.src;
  delete video.dataset.period;
  const revision = previewRevision;
  const result = await apiRequest("/api/filter-options", {
    method: "POST",
    body: JSON.stringify({ match_id: matchId }),
  });
  if (revision !== previewRevision) return;
  activeMatch = result.match;
  filterMetadata = result;
  sessionStorage.setItem("clipmaker.active-match", activeMatch.id);
  rememberProject(activeMatch);
  const url = new URL(window.location.href);
  url.searchParams.set("match", activeMatch.id);
  history.replaceState({}, "", url);
  renderMatchContext();
  renderTeams();
  renderActions();
  renderQualifiers();
  restoringProject = true;
  applyOptions(activeMatch.filter_settings || {});
  if (activeMatch.preview_windows?.length) {
    showClips(activeMatch.preview_windows, activeMatch.preview_range || {});
    field("summary-note").textContent = hasFootage()
      ? `${clipCount(clips.length)} ready to review.`
      : "Clips found. Add match footage in Intake before exporting.";
  }
  restoringProject = false;
};

const connect = async () => {
  try {
    await apiRequest("/api/health");
    setEngineState("Engine ready", true);
    snapshotLibrary = (await apiRequest("/api/snapshots")).snapshots;
    try {
      const legacy = JSON.parse(localStorage.getItem(snapshotStorageKey) || "{}");
      for (const [name, options] of Object.entries(legacy)) {
        if (!(name in snapshotLibrary) && options && typeof options === "object") {
          snapshotLibrary = (await apiRequest("/api/snapshots", { method: "POST", body: JSON.stringify({ name, options }) })).snapshots;
        }
      }
      localStorage.removeItem(snapshotStorageKey);
    } catch (error) { showToast(error.message); }
    const historyResult = await apiRequest("/api/matches");
    const matches = (historyResult.matches || []).filter((match) => match.csv_path);
    if (!matches.length) {
      throw new Error("Scrape and save a match in Intake before filtering.");
    }
    matchSelect.replaceChildren();
    matches.forEach((match) => {
      const option = document.createElement("option");
      option.value = match.id;
      option.textContent = match.project_name || `${match.home_team} vs ${match.away_team}`;
      matchSelect.appendChild(option);
    });
    const requested = new URLSearchParams(window.location.search).get("match");
    const remembered = sessionStorage.getItem("clipmaker.active-match");
    const chosen = matches.find(
      (match) =>
        match.id === requested || (!requested && match.id === remembered),
    );
    matchSelect.value = chosen?.id || matches[0].id;
    await loadMatch(matchSelect.value);
    renderSnapshots();
  } catch (error) {
    setEngineState("Engine unavailable", false);
    showToast(error.message);
  }
};

// ---------------------------------------------------------------------------
// Events: filters
// ---------------------------------------------------------------------------

matchSelect.addEventListener("change", async () => {
  try {
    await persistFilters();
    await flushProject();
    await loadMatch(matchSelect.value);
  } catch (error) {
    showToast(error.message);
  }
});

teamOptions.addEventListener("change", () => {
  renderPlayers();
  resetPreview();
  updateSummary();
});

form.addEventListener("input", (event) => {
  if (event.target.closest("#snapshots, #corrections")) return;
  if (event.target.name === "action" || event.target.name === "qualifier")
    shotsAndKeyPasses = false;
  resetPreview();
  updateSummary();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await buildPreview();
});

field("select-all-actions").addEventListener("click", () => {
  form.querySelectorAll('input[name="action"]').forEach((input) => {
    input.checked = true;
  });
  resetPreview();
  updateSummary();
});

field("clear-actions").addEventListener("click", () => {
  setCheckedValues("action");
  resetPreview();
  updateSummary();
});

field("select-all-players").addEventListener("click", () => {
  form.querySelectorAll('input[name="player"]').forEach((input) => {
    input.checked = true;
  });
  resetPreview();
  updateSummary();
});

field("clear-players").addEventListener("click", () => {
  setCheckedValues("player");
  resetPreview();
  updateSummary();
});

document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => {
    const current = collectOptions(true);
    applyOptions({
      ...presets[button.dataset.preset],
      timeline_corrections: current.timeline_corrections,
      output_dir: current.output_dir,
      output_format: current.output_format,
      output_filename: current.output_filename,
      individual_clips: current.individual_clips,
      video_crf: current.video_crf,
      encoder_preset: current.encoder_preset,
      video_encoder: current.video_encoder,
      audio_bitrate: current.audio_bitrate,
    });
    showToast(`${button.textContent.trim()} preset applied`);
  });
});

field("reset-filters").addEventListener("click", () => {
  resetFilters();
  showToast("All filters cleared");
});

field("save-snapshot").addEventListener("click", async () => {
  const name = field("snapshot-name").value.trim();
  if (!name) {
    showToast("Enter a snapshot name first");
    return;
  }
  try {
    snapshotLibrary = (await apiRequest("/api/snapshots", { method: "POST", body: JSON.stringify({ name, options: collectOptions(true) }) })).snapshots;
    renderSnapshots();
    snapshotSelect.value = name;
    snapshotSelect.dispatchEvent(new Event("change"));
    showToast(`Saved snapshot: ${name}`);
  } catch (error) { showToast(error.message); }
});

snapshotSelect.addEventListener("change", () => {
  const enabled = Boolean(snapshotSelect.value);
  field("load-snapshot").disabled = !enabled;
  field("delete-snapshot").disabled = !enabled;
});

field("load-snapshot").addEventListener("click", () => {
  const name = snapshotSelect.value;
  const snapshot = getSnapshots()[name];
  if (!snapshot) return;
  applyOptions(snapshot);
  // applyOptions resets the form, including this library selection.
  snapshotSelect.value = name;
  snapshotSelect.dispatchEvent(new Event("change"));
  showToast(`Loaded snapshot: ${name}`);
});

field("delete-snapshot").addEventListener("click", async () => {
  const name = snapshotSelect.value;
  try {
    snapshotLibrary = (await apiRequest("/api/snapshots/delete", { method: "POST", body: JSON.stringify({ name }) })).snapshots;
    renderSnapshots();
    showToast(`Deleted snapshot: ${name}`);
  } catch (error) { showToast(error.message); }
});

const correctionFields = ["correction-period", "correction-clock", "correction-direction", "correction-amount", "correction-note"];
field("add-correction").onclick = () => {
  try {
    // The form starts blank so no example value is mistaken for a real correction.
    if (!field("correction-period").value) throw new Error("Choose the period the recording problem is in.");
    if (!field("correction-clock").value.trim()) throw new Error("Enter the match clock where the problem starts, as MM:SS.");
    if (!field("correction-direction").value) throw new Error("Choose what happened to the recording.");
    if (!field("correction-amount").value.trim()) throw new Error("Enter how much footage is missing or extra, as MM:SS.");
    const at = clockSeconds(field("correction-clock").value);
    const amount = clockSeconds(field("correction-amount").value);
    if (!amount) throw new Error("Enter a non-zero correction.");
    corrections.push({
      period: Number(field("correction-period").value),
      at_seconds: at,
      seconds:
        amount * (field("correction-direction").value === "subtract" ? -1 : 1),
      note: field("correction-note").value.trim(),
    });
    correctionFields.forEach((name) => { field(name).value = ""; });
    renderCorrections();
    resetPreview();
    persistFilters();
  } catch (error) {
    showToast(error.message);
  }
};

// ---------------------------------------------------------------------------
// Events: editor and export
// ---------------------------------------------------------------------------

field("clear-preview").onclick = () => {
  resetPreview();
  persistFilters();
};
field("undo-remove").onclick = () => {
  if (!lastRemoved) return;
  const { clip, index, wasSelected } = lastRemoved;
  clips.splice(Math.min(index, clips.length), 0, clip);
  if (wasSelected) selected.add(clip.id);
  lastRemoved = undefined;
  field("editor-empty").hidden = true;
  field("preview-results").hidden = false;
  renderTimeline();
  showClip(index);
  persistFilters();
};
field("play-clip").onclick = togglePlay;
field("prev-clip").onclick = () => showClip(focusIndex - 1);
field("next-clip").onclick = () => showClip(focusIndex + 1);
field("play-all").onchange = (event) => { playAllActive = event.target.checked; };
field("reset-clip").onclick = () => {
  const clip = focused();
  if (!clip) return;
  applyTrim(focusIndex, { ...clip, start: clip.source_start, end: clip.source_end });
  showClip(focusIndex);
};
field("remove-clip").onclick = () => removeClip(focusIndex);
field("render-clip").onclick = renderClip;
field("select-all-clips").onclick = () => {
  selected = new Set(clips.map((clip) => clip.id));
  renderTimeline();
  persistFilters();
};
field("select-no-clips").onclick = () => {
  selected = new Set();
  setRadio("export-scope", "all");
  renderTimeline();
  persistFilters();
};
field("zoom").addEventListener("input", () => {
  track.querySelectorAll(".clip-block").forEach((item, index) => describeBlock(item, clips[index], index));
});
document.querySelectorAll("[data-export-scope], [data-export-as]").forEach((input) =>
  input.addEventListener("change", () => { refreshExportState(); persistFilters(); }));

document.querySelectorAll("[data-nudge]").forEach((button) => {
  button.onclick = () => {
    const clip = focused();
    if (clip) trimEdge(focusIndex, button.dataset.nudge, clip[button.dataset.nudge] + Number(button.dataset.step));
  };
});
document.querySelectorAll("[data-set-edge]").forEach((button) => {
  button.onclick = () => {
    if (!focused() || fallbackMode) return;
    trimEdge(focusIndex, button.dataset.setEdge, video.currentTime, { seek: false });
  };
});
document.querySelectorAll("[data-edge-input]").forEach((input) => {
  input.addEventListener("change", () => {
    const seconds = parseClock(input.value);
    if (!Number.isFinite(seconds)) {
      input.setAttribute("aria-invalid", "true");
      showToast("Use minutes:seconds, like 54:31.5");
      return;
    }
    trimEdge(focusIndex, input.dataset.edgeInput, seconds);
    input.value = formatClock(focused()[input.dataset.edgeInput]);
  });
});

video.addEventListener("play", () => { setPlayIcon(true); requestAnimationFrame(watchPlayback); });
video.addEventListener("pause", () => { setPlayIcon(false); updatePlayhead(); });
video.addEventListener("seeked", updatePlayhead);

// Drag an edge: a timeline handle (seconds per pixel from the zoom) or a trim
// bar handle (seconds per pixel from the bar's span). Clicking the trim bar seeks.
const startDrag = (event, target, index, edge, secondsPerPixel) => {
  event.preventDefault();
  try { target.setPointerCapture(event.pointerId); } catch { /* pointer already gone */ }
  const origin = event.clientX;
  const initial = clips[index][edge];
  draggingEdge = true;
  if (index === focusIndex) trimContext(clips[index]);
  target.classList.add("is-dragging");
  const move = (moveEvent) => {
    trimEdge(index, edge, initial + (moveEvent.clientX - origin) * secondsPerPixel);
  };
  const end = () => {
    draggingEdge = false;
    target.classList.remove("is-dragging");
    target.removeEventListener("pointermove", move);
    target.removeEventListener("pointerup", end);
    target.removeEventListener("pointercancel", end);
    if (index === focusIndex) renderTrimPanel();
    persistFilters();
  };
  target.addEventListener("pointermove", move);
  target.addEventListener("pointerup", end);
  target.addEventListener("pointercancel", end);
};

track.addEventListener("pointerdown", (event) => {
  const handle = event.target.closest(".clip-handle");
  if (!handle) return;
  const index = [...track.children].indexOf(handle.closest(".clip-block"));
  if (index !== focusIndex) showClip(index);
  startDrag(event, handle, index, handle.dataset.edge, 1 / Number(field("zoom").value));
});

const nudgeKeys = { ArrowLeft: -0.5, ArrowRight: 0.5, ArrowDown: -0.5, ArrowUp: 0.5 };
track.addEventListener("keydown", (event) => {
  const handle = event.target.closest(".clip-handle");
  if (!handle || !(event.key in nudgeKeys)) return;
  event.preventDefault();
  event.stopPropagation();
  const index = [...track.children].indexOf(handle.closest(".clip-block"));
  const step = nudgeKeys[event.key] * (event.shiftKey ? 4 : 1);
  trimEdge(index, handle.dataset.edge, clips[index][handle.dataset.edge] + step);
});

const trimBar = field("trim-bar");
document.querySelectorAll("[data-trim-handle]").forEach((handle) => {
  handle.addEventListener("pointerdown", (event) => {
    const clip = focused();
    if (!clip) return;
    const { from, to } = trimContext(clip);
    startDrag(event, handle, focusIndex, handle.dataset.trimHandle, (to - from) / trimBar.getBoundingClientRect().width);
  });
  handle.addEventListener("keydown", (event) => {
    if (!(event.key in nudgeKeys)) return;
    event.preventDefault();
    event.stopPropagation();
    const edge = handle.dataset.trimHandle;
    trimEdge(focusIndex, edge, focused()[edge] + nudgeKeys[event.key] * (event.shiftKey ? 4 : 1));
  });
});
trimBar.addEventListener("pointerdown", (event) => {
  if (event.target.closest("[data-trim-handle]") || fallbackMode || !focused()) return;
  const { from, to } = trimContext(focused());
  const box = trimBar.getBoundingClientRect();
  const seconds = from + ((event.clientX - box.left) / box.width) * (to - from);
  showClip(focusIndex, { at: Math.max(0, seconds) });
});

// Editor shortcuts, ignored while typing in a field.
document.querySelector(".editor").addEventListener("keydown", (event) => {
  if (!clips.length || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.target.closest("input, select, textarea, summary, .clip-handle, [data-trim-handle]")) return;
  const key = event.key.toLowerCase();
  const clip = focused();
  if (key === " " && !event.target.closest("button, a")) {
    event.preventDefault();
    togglePlay();
  } else if (key === "i" && !fallbackMode) {
    trimEdge(focusIndex, "start", video.currentTime, { seek: false });
  } else if (key === "o" && !fallbackMode) {
    trimEdge(focusIndex, "end", video.currentTime, { seek: false });
  } else if ((key === "arrowleft" || key === "arrowright") && !fallbackMode && clip) {
    event.preventDefault();
    const step = (key === "arrowleft" ? -1 : 1) * (event.shiftKey ? 5 : 1);
    showClip(focusIndex, { at: Math.max(0, video.currentTime + step), play: !video.paused });
  } else if (key === "arrowup" || key === "arrowdown") {
    event.preventDefault();
    showClip(focusIndex + (key === "arrowup" ? -1 : 1));
  }
});

exportButton.addEventListener("click", startExport);

// Annotate (export line): cut the clip in the player, then open it in the analyst editor.
annotateButton.addEventListener("click", async () => {
  const targets = annotateTargets();
  if (targets.length > 1) return annotateMany(targets);
  const clip = targets[0];
  if (!clip || !activeMatch) return;
  const content = [...annotateButton.childNodes]; // icon and label, put back after the busy text
  annotateButton.disabled = true;
  annotateButton.textContent = "Preparing clip...";
  try {
    const result = await apiRequest("/api/previews/render", {
      method: "POST",
      body: JSON.stringify({ match_id: activeMatch.id, start: clip.start, end: clip.end, period: clip.period, ...encodingSettings() }),
    });
    // annotateClip reports its own errors and leaves the page only once the clip is in the project.
    const opened = await annotateClip(result.file.url, clip.label || `Clip ${focusIndex + 1}`, annotateButton, activeMatch.id);
    if (!opened) annotateButton.replaceChildren(...content);
  } catch (error) {
    field("summary-note").textContent = `Could not prepare the clip for annotating: ${error.message}`;
    annotateButton.replaceChildren(...content);
    annotateButton.disabled = false;
  }
});

// Several ticked clips: cut each, copy it into the project under one shared session, then open the first.
async function annotateMany(targets) {
  if (!activeMatch) return;
  const note = field("summary-note");
  if (targets.length > MAX_ANNOTATE) {
    note.textContent = `Tick at most ${MAX_ANNOTATE} clips to annotate together (${targets.length} are ticked).`;
    return;
  }
  const content = [...annotateButton.childNodes];
  annotateButton.disabled = true;
  const sessionName = `${activeMatch.home_team} vs ${activeMatch.away_team}: ${targets.length} clips`;
  let session = null;
  let first = null;
  try {
    for (const [index, clip] of targets.entries()) {
      annotateButton.textContent = `Preparing ${index + 1} of ${targets.length}...`;
      const result = await apiRequest("/api/previews/render", {
        method: "POST",
        body: JSON.stringify({ match_id: activeMatch.id, start: clip.start, end: clip.end, period: clip.period, ...encodingSettings() }),
      });
      const added = await apiRequest("/api/editor/clips", {
        method: "POST",
        body: JSON.stringify({
          project_id: activeMatch.id, media: String(result.file.url).split("/").pop(),
          name: clip.label || `Clip ${clips.indexOf(clip) + 1}`,
          ...(session ? { session_id: session.id } : { session_name: sessionName }),
        }),
      });
      session = added.session;
      first = first || added.clip;
    }
    window.location.href = `/annotate.html?project=${encodeURIComponent(activeMatch.id)}&clip=${encodeURIComponent(first.id)}`;
  } catch (error) {
    note.textContent = first
      ? `Annotated ${session.clips.length} of ${targets.length} clips, then stopped: ${error.message.replace(/\.?$/, ".")} The ones done are on the Annotate tab.`
      : `Could not prepare the clips for annotating: ${error.message}`;
    annotateButton.replaceChildren(...content);
    annotateButton.disabled = false;
  }
}

cancelJobButton.addEventListener("click", async () => {
  if (!activeJobId) return;
  try {
    await apiRequest(`/api/jobs/${activeJobId}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    jobState.textContent = "Cancelling";
  } catch (error) {
    showToast(error.message);
  }
});

field("reveal-export").onclick = async () => {
  if (!finishedJobId) return;
  try {
    await revealFolder(`/api/jobs/${finishedJobId}/reveal`);
  } catch (error) {
    showToast(error.message);
  }
};
// Exports go to Videos/VizorPlay (Movies/VizorPlay on macOS) unless a folder is chosen.
apiRequest("/api/folders/output/default")
  .then((result) => { if (result.path) field("output-dir").placeholder = result.path; })
  .catch(() => {});
field("browse-output").onclick = async () => {
  try {
    const result = await apiRequest("/api/folders/output", {
      method: "POST",
      body: JSON.stringify({ initial_dir: field("output-dir").value || field("output-dir").placeholder }),
    });
    if (!result.cancelled) field("output-dir").value = result.path;
    persistFilters();
  } catch (error) {
    showToast(error.message);
  }
};
field("quality").onchange = () => {
  const values = {
    balanced: [20, "veryfast", "128k"],
    small: [24, "veryfast", "96k"],
    high: [18, "slow", "160k"],
  }[field("quality").value];
  if (values)
    ["video-crf", "encoder-preset", "audio-bitrate"].forEach(
      (key, index) => (field(key).value = values[index]),
    );
  persistFilters();
};
["video-crf", "encoder-preset", "audio-bitrate"].forEach((key) =>
  field(key).addEventListener("change", () => (field("quality").value = "custom")),
);
document.querySelector(".export-settings").addEventListener("change", persistFilters);

form.addEventListener("change", persistFilters);
form.addEventListener("input", persistFilters);
document.querySelector("[data-project-name]").addEventListener("change", persistFilters);
document.querySelectorAll("[data-preset], [data-reset-filters], [data-load-snapshot], [data-select-all-actions], [data-clear-actions], [data-select-all-players], [data-clear-players]").forEach((button) => button.addEventListener("click", persistFilters));
const menuButton = document.querySelector("[data-filter-menu]");
const menu = document.querySelector("#filter-menu");
const closeMenu = () => {
  if (menu.contains(document.activeElement)) menuButton.focus();
  menu.hidden = true;
  menuButton.setAttribute("aria-expanded", "false");
};
menuButton.onclick = () => {
  if (!menu.hidden) { closeMenu(); return; }
  menu.hidden = false;
  menuButton.setAttribute("aria-expanded", "true");
  menu.querySelector("a, button")?.focus();
};
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeMenu(); });
document.addEventListener("click", (event) => { if (!event.target.closest("#filter-menu, [data-filter-menu]")) closeMenu(); });
document.querySelector("[data-new-project]").onclick = async (event) => {
  event.currentTarget.disabled = true;
  try {
    await persistFilters();
    const project = await newProject();
    location.href = `/?project=${encodeURIComponent(project.id)}`;
  } catch (error) { event.currentTarget.disabled = false; showToast(error.message); }
};
document.querySelectorAll('.filter-topbar a, .context-edit').forEach((link) => link.setAttribute("data-project-navigation", ""));

// Players across every saved match (ui/player-search.js): starts with the players ticked here.
{
  const across = Object.assign(document.createElement("button"), { type: "button", className: "context-across", textContent: "Players across matches" });
  across.dataset.playersAcross = "";
  across.title = "Find one or more players' clips in all your saved matches";
  across.onclick = () => openPlayerSearch({ pageOptions: () => collectOptions(true), preset: selectedValues('input[name="player"]') });
  document.querySelector(".context-edit")?.before(across);
}

connect();
