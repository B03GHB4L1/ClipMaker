import { saveProject, flushProject, newProject, rememberProject } from "./projects.js";

const form = document.querySelector("[data-filter-form]");
const toast = document.querySelector("[data-toast]");
const engineState = document.querySelector("[data-engine-state]");
const matchSelect = document.querySelector("[data-match-select]");
const teamOptions = document.querySelector("[data-team-options]");
const playerOptions = document.querySelector("[data-player-options]");
const actionOptions = document.querySelector("[data-action-options]");
const qualifierGroups = document.querySelector("[data-qualifier-groups]");
const exportButton = document.querySelector("[data-export-button]");
const planOutput = document.querySelector("[data-plan-output]");
const jobState = document.querySelector("[data-job-state]");
const jobLogs = document.querySelector("[data-job-logs]");
const jobProgress = document.querySelector("[data-job-progress]");
const cancelJobButton = document.querySelector("[data-cancel-job]");
const snapshotSelect = document.querySelector("[data-snapshot-select]");
const snapshotStorageKey = "clipmaker.filter-snapshots.v1";
let snapshotLibrary = {};

let activeMatch;
let filterMetadata;
let activeJobId;
let previewComplete = false;
let toastTimer;
let corrections = [];
let previewWindows = [];
let previewRevision = 0;
let previewBusy = false;
let shotsAndKeyPasses = false;
let selectedRange = { first: 1, last: null };
let restoringProject = false;
const persistFilters = () => {
  if (!activeMatch?.id || restoringProject) return Promise.resolve();
  const saving = saveProject(activeMatch.id, {
    project_name: document.querySelector("[data-project-name]").value.trim() || "Untitled project",
    filter_settings: collectOptions(true), preview_windows: structuredClone(previewWindows),
    preview_range: selectedRange,
  });
  saving.catch((error) => showToast(error.message));
  return saving;
};
const setExportBusy = (busy) => {
  document
    .querySelectorAll(".filter-flow, .preset-row, [data-preview-results]")
    .forEach((element) => (element.inert = busy));
  matchSelect.disabled = busy;
  form.querySelector("[type=submit]").disabled = busy;
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

const resetPreview = () => {
  previewRevision++;
  previewWindows = [];
  selectedRange = { first: 1, last: null };
  document
    .querySelectorAll("[data-clip-list] video")
    .forEach((video) => video.pause());
  document.querySelector("[data-preview-results]").hidden = true;
  previewComplete = false;
  exportButton.disabled = true;
  document.querySelector("[data-summary-note]").textContent =
    "Preview first to confirm the matching clips.";
};

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

const renderPlayers = (selected = []) => {
  const validSelection = new Set(selected);
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
  document.querySelector("[data-summary-team]").textContent =
    team || "Both teams";
  document.querySelector("[data-summary-players]").textContent = players.length
    ? players.length <= 2
      ? players.join(", ")
      : `${players.length} players`
    : "All players";
  document.querySelector("[data-summary-half]").textContent = half;
  document.querySelector("[data-summary-actions]").textContent = actions.length
    ? actions.length <= 2
      ? actions.map(humanize).join(", ")
      : `${actions.length} action types`
    : "All actions";
  document.querySelector("[data-summary-qualifiers]").textContent =
    qualifiers.length ? `${qualifiers.length} active` : "None";
  document.querySelector("[data-summary-title]").textContent =
    actions.length || qualifiers.length
      ? "Custom clip selection"
      : "All match events";
};

const collectOptions = (dryRun) => {
  const options = {
    dry_run: dryRun,
    filter_types: selectedValues('input[name="action"]'),
    team_filter: currentTeam(),
    player_filters: selectedValues('input[name="player"]'),
    half_filter: form.querySelector('input[name="half"]:checked').value,
    qualifier_logic: form.querySelector('input[name="qualifier-logic"]:checked')
      .value,
    before_buffer: Number(document.querySelector("[data-before-buffer]").value),
    after_buffer: Number(document.querySelector("[data-after-buffer]").value),
    min_gap: Number(document.querySelector("[data-min-gap]").value),
    pitch_zone_filter: document.querySelector("[data-pitch-zone]").value,
    depth_zone_filter: document.querySelector("[data-depth-zone]").value,
    xt_min: Number(document.querySelector("[data-xt-min]").value),
    top_n: Number(document.querySelector("[data-top-n]").value) || null,
    output_filename:
      document.querySelector("[data-output-name]").value.trim() ||
      "Highlights.mp4",
    individual_clips: document.querySelector("[data-individual-clips]").checked,
    shots_and_key_passes_only: shotsAndKeyPasses,
    timeline_corrections: structuredClone(corrections),
    output_dir: document.querySelector("[data-output-dir]").value.trim(),
    output_format: document.querySelector("[data-output-format]").value,
    video_crf: Number(document.querySelector("[data-video-crf]").value),
    encoder_preset: document.querySelector("[data-encoder-preset]").value,
    audio_bitrate: document.querySelector("[data-audio-bitrate]").value,
  };
  selectedValues('input[name="qualifier"]').forEach((flag) => {
    options[flag] = true;
  });
  return options;
};

const setCheckedValues = (name, values = []) => {
  const selected = new Set(values);
  form.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
    input.checked = selected.has(input.value);
  });
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
  const logic = form.querySelector(
    `input[name="qualifier-logic"][value="${options.qualifier_logic || "any"}"]`,
  );
  if (logic) logic.checked = true;
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
    "[data-audio-bitrate]": options.audio_bitrate || "128k",
  };
  Object.entries(values).forEach(([selector, value]) => {
    document.querySelector(selector).value = value;
  });
  document.querySelector("[data-individual-clips]").checked = Boolean(
    options.individual_clips,
  );
  corrections = structuredClone(options.timeline_corrections || []);
  renderCorrections();
  document.querySelector("[data-quality]").value = "custom";
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

const getSnapshots = () => {
  return structuredClone(snapshotLibrary);
};

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
  document.querySelector("[data-load-snapshot]").disabled = true;
  document.querySelector("[data-delete-snapshot]").disabled = true;
};

const renderJob = (job) => {
  const labels = {
    queued: "Queued",
    running: job.dry_run ? "Calculating clip windows" : "Exporting reel",
    complete: job.dry_run ? "Clip plan ready" : "Export complete",
    failed: "Could not build plan",
    cancelled: "Job cancelled",
  };
  const finished = ["complete", "failed", "cancelled"].includes(job.status);
  jobState.textContent = labels[job.status] || job.status;
  jobLogs.textContent =
    (job.logs || []).join("\n") || "Reading match events...";
  jobLogs.scrollTop = jobLogs.scrollHeight;
  const progress = job.progress;
  const ratio = progress?.total ? progress.current / progress.total : 0;
  jobProgress.style.width = `${job.status === "complete" ? 100 : Math.min(100, ratio * 100)}%`;
  cancelJobButton.hidden = finished;
  if (!finished) return;
  activeJobId = undefined;
  setExportBusy(false);
  exportButton.disabled = !previewComplete || !activeMatch?.video_path;
  if (job.status === "complete" && job.dry_run) {
    previewComplete = true;
    exportButton.disabled = !activeMatch.video_path;
    document.querySelector("[data-summary-note]").textContent =
      activeMatch.video_path
        ? "Plan ready. Export will use the same filters."
        : "Plan ready. Add match footage in Intake before exporting.";
  } else if (job.status === "complete") {
    document.querySelector("[data-summary-note]").textContent =
      "Export finished. See the log for the saved file location.";
    const list = document.querySelector("[data-export-files]");
    list.replaceChildren();
    (job.files || []).forEach((file) => {
      const link = document.createElement("a");
      link.href = file.url;
      link.download = file.name;
      link.textContent = file.name;
      list.append(link);
    });
    const previous = activeMatch.export_history || [];
    activeMatch.export_history = [...previous, { id: job.id, finished_at: job.finished_at, files: job.files || [] }].slice(-50);
    saveProject(activeMatch.id, { status: "complete", export_history: activeMatch.export_history }).catch((error) => showToast(error.message));
  }
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
    jobLogs.textContent = error.message;
    setTimeout(() => pollJob(jobId), 2000);
  }
};

const startClipJob = async (dryRun) => {
  if (activeJobId || previewBusy) return;
  if (dryRun) return buildPreview();
  if (!previewComplete || !previewWindows.length) return;
  if (!activeMatch?.id) {
    showToast("Choose a saved match before filtering");
    return;
  }
  if (!dryRun && !activeMatch.video_path) {
    showToast("Add match footage in Intake before exporting");
    return;
  }
  planOutput.hidden = false;
  setExportBusy(true);
  cancelJobButton.hidden = false;
  exportButton.disabled = true;
  jobState.textContent = dryRun ? "Starting preview" : "Starting export";
  jobLogs.textContent = "Preparing filters...";
  jobProgress.style.width = "4%";
  try {
    await persistFilters();
    await flushProject();
    const result = await apiRequest("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        match_id: activeMatch.id,
        options: { ...collectOptions(dryRun), clip_windows: exportWindows() },
      }),
    });
    activeJobId = result.job.id;
    renderJob(result.job);
    pollJob(activeJobId);
  } catch (error) {
    activeJobId = undefined;
    setExportBusy(false);
    cancelJobButton.hidden = true;
    jobState.textContent = "Setup needs attention";
    jobLogs.textContent = error.message;
    jobProgress.style.width = "0%";
    exportButton.disabled = !previewComplete || !activeMatch.video_path;
    showToast(error.message);
  }
};

const loadMatch = async (matchId) => {
  resetPreview();
  activeMatch = undefined;
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
    previewWindows = structuredClone(activeMatch.preview_windows);
    selectedRange = activeMatch.preview_range || { first: 1, last: null };
    previewComplete = true;
    renderPreviews();
    exportButton.disabled = !activeMatch.video_path;
    document.querySelector("[data-summary-note]").textContent = activeMatch.video_path
      ? `${previewWindows.length} clips ready to review.`
      : "Plan ready. Add match footage in Intake before exporting.";
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
    const selected = matches.find(
      (match) =>
        match.id === requested || (!requested && match.id === remembered),
    );
    matchSelect.value = selected?.id || matches[0].id;
    await loadMatch(matchSelect.value);
    renderSnapshots();
  } catch (error) {
    setEngineState("Engine unavailable", false);
    showToast(error.message);
  }
};

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
  if (event.target.closest("#export-settings, #snapshots, #corrections"))
    return;
  if (event.target.name === "action" || event.target.name === "qualifier")
    shotsAndKeyPasses = false;
  resetPreview();
  updateSummary();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await startClipJob(true);
});

document
  .querySelector("[data-select-all-actions]")
  .addEventListener("click", () => {
    form.querySelectorAll('input[name="action"]').forEach((input) => {
      input.checked = true;
    });
    resetPreview();
    updateSummary();
  });

document.querySelector("[data-clear-actions]").addEventListener("click", () => {
  setCheckedValues("action");
  resetPreview();
  updateSummary();
});

document
  .querySelector("[data-select-all-players]")
  .addEventListener("click", () => {
    form.querySelectorAll('input[name="player"]').forEach((input) => {
      input.checked = true;
    });
    resetPreview();
    updateSummary();
  });

document.querySelector("[data-clear-players]").addEventListener("click", () => {
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
      video_crf: current.video_crf,
      encoder_preset: current.encoder_preset,
      audio_bitrate: current.audio_bitrate,
    });
    showToast(`${button.textContent.trim()} preset applied`);
  });
});

document.querySelector("[data-reset-filters]").addEventListener("click", () => {
  resetFilters();
  showToast("All filters cleared");
});

document.querySelector("[data-save-snapshot]").addEventListener("click", async () => {
  const name = document.querySelector("[data-snapshot-name]").value.trim();
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
  document.querySelector("[data-load-snapshot]").disabled = !enabled;
  document.querySelector("[data-delete-snapshot]").disabled = !enabled;
});

document.querySelector("[data-load-snapshot]").addEventListener("click", () => {
  const snapshot = getSnapshots()[snapshotSelect.value];
  if (!snapshot) return;
  applyOptions(snapshot);
  showToast(`Loaded snapshot: ${snapshotSelect.value}`);
});

document
  .querySelector("[data-delete-snapshot]")
  .addEventListener("click", async () => {
    const name = snapshotSelect.value;
    try {
      snapshotLibrary = (await apiRequest("/api/snapshots/delete", { method: "POST", body: JSON.stringify({ name }) })).snapshots;
      renderSnapshots();
      showToast(`Deleted snapshot: ${name}`);
    } catch (error) { showToast(error.message); }
  });

exportButton.addEventListener("click", () => startClipJob(false));

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

const field = (name) => document.querySelector(`[data-${name}]`);
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
  field("correction-count").textContent = `${corrections.length} active`;
  corrections.forEach((correction, index) => {
    const row = document.createElement("div");
    const label = document.createElement("span");
    label.textContent = `P${correction.period} from ${correction.clock || correction.at_seconds + "s"}: ${correction.seconds ?? correction.amount_seconds}s ${correction.note || ""}`;
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
field("add-correction").onclick = () => {
  try {
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
    renderCorrections();
    resetPreview();
    persistFilters();
  } catch (error) {
    showToast(error.message);
  }
};
field("browse-output").onclick = async () => {
  try {
    const result = await apiRequest("/api/folders/output", {
      method: "POST",
      body: JSON.stringify({ initial_dir: field("output-dir").value }),
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
  field(key).addEventListener(
    "change",
    () => (field("quality").value = "custom"),
  ),
);
field("clear-preview").onclick = resetPreview;

const renderPreviews = () => {
  const list = field("clip-list");
  list.querySelectorAll("video").forEach((video) => video.pause());
  list.replaceChildren();
  field("preview-results").hidden = false;
  field("preview-count").textContent = previewWindows.length;
  field("range-first").max = previewWindows.length || 1;
  field("range-last").max = previewWindows.length || 1;
  selectedRange.first = Math.min(selectedRange.first || 1, previewWindows.length || 1);
  selectedRange.last = Math.min(selectedRange.last || previewWindows.length || 1, previewWindows.length || 1);
  field("range-first").value = selectedRange.first;
  field("range-last").value = selectedRange.last;
  field("range-count").textContent = `${Math.max(0, selectedRange.last - selectedRange.first + 1)} selected`;
  previewWindows.forEach((window, index) => {
    const item = document.createElement("details");
    item.className = "clip-preview";
    const summary = document.createElement("summary");
    summary.textContent = `${index + 1}. ${window.label}`;
    const controls = document.createElement("div");
    controls.className = "clip-editor";
    const video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.hidden = true;
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    const play = document.createElement("button");
    play.type = "button";
    play.textContent = "Render preview";
    const download = document.createElement("a");
    download.hidden = true;
    download.textContent = "Download clip";
    let revision = 0;
    ["start", "end"].forEach((key) => {
      const label = document.createElement("label");
      label.textContent = `${key === "start" ? "Start" : "End"} (video seconds)`;
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = "0.1";
      input.value = window[key];
      input.oninput = () => {
        revision++;
        video.pause();
        video.hidden = true;
        download.hidden = true;
        window[key] = Number(input.value);
        const valid = previewWindows.every(
          (clip) =>
            Number.isFinite(clip.start) &&
            Number.isFinite(clip.end) &&
            clip.start >= 0 &&
            clip.end > clip.start,
        );
        exportButton.disabled =
          !valid || Boolean(activeJobId) || !activeMatch.video_path;
        status.textContent = valid
          ? "Window changed. Render to review."
          : "End must be later than start.";
        if (valid) persistFilters();
      };
      label.append(input);
      controls.append(label);
    });
    play.onclick = async () => {
      if (!(window.end > window.start && window.start >= 0)) {
        status.textContent = "Enter a valid clip window.";
        return;
      }
      const version = revision;
      const generation = previewRevision;
      play.disabled = true;
      status.textContent = "Rendering preview...";
      try {
        const result = await apiRequest("/api/previews/render", {
          method: "POST",
          body: JSON.stringify({ match_id: activeMatch.id, ...window }),
        });
        if (version !== revision || generation !== previewRevision) return;
        video.src = result.file.url;
        video.hidden = false;
        download.href = result.file.url;
        download.download = `clip-${index + 1}.mp4`;
        download.hidden = false;
        status.textContent = "Preview ready";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        play.disabled = false;
      }
    };
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Exclude clip";
    remove.onclick = () => {
      previewWindows.splice(index, 1);
      renderPreviews();
      exportButton.disabled =
        !previewWindows.length ||
        Boolean(activeJobId) ||
        !activeMatch.video_path;
      persistFilters();
    };
    controls.append(play, remove, download);
    item.append(summary, controls, status, video);
    list.append(item);
  });
};
const buildPreview = async () => {
  if (!activeMatch?.id) {
    showToast("Choose a match first.");
    return;
  }
  resetPreview();
  const generation = previewRevision;
  previewBusy = true;
  const button = form.querySelector("[type=submit]");
  button.disabled = true;
  field("summary-note").textContent = "Calculating clip windows...";
  try {
    const result = await apiRequest("/api/previews", {
      method: "POST",
      body: JSON.stringify({
        match_id: activeMatch.id,
        options: collectOptions(true),
      }),
    });
    if (generation !== previewRevision) return;
    previewWindows = result.windows;
    previewComplete = previewWindows.length > 0;
    renderPreviews();
    await persistFilters();
    exportButton.disabled = !previewComplete || !activeMatch.video_path;
    field("summary-note").textContent = previewComplete
      ? `${previewWindows.length} clips ready to review.`
      : "No matching clips. Adjust the filters.";
    field("preview-results").scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  } catch (error) {
    showToast(error.message);
    field("summary-note").textContent = error.message;
  } finally {
    previewBusy = false;
    button.disabled = false;
  }
};

const exportWindows = () => {
  const first = Number(field("range-first").value);
  const last = Number(field("range-last").value);
  if (!Number.isInteger(first) || !Number.isInteger(last) || first < 1 || last > previewWindows.length || last < first) {
    throw new Error("Choose a valid first and last clip.");
  }
  return previewWindows.slice(first - 1, last);
};
["range-first", "range-last"].forEach((key) => field(key).addEventListener("input", () => {
  try {
    const windows = exportWindows();
    selectedRange = { first: Number(field("range-first").value), last: Number(field("range-last").value) };
    field("range-count").textContent = `${windows.length} selected`;
    exportButton.disabled = Boolean(activeJobId) || !activeMatch?.video_path;
    persistFilters();
  } catch (error) { field("range-count").textContent = error.message; exportButton.disabled = true; }
}));

form.addEventListener("change", persistFilters);
form.addEventListener("input", persistFilters);
document.querySelector("[data-project-name]").addEventListener("change", persistFilters);
document.querySelectorAll("[data-preset], [data-reset-filters], [data-load-snapshot], [data-select-all-actions], [data-clear-actions], [data-select-all-players], [data-clear-players], [data-clear-preview]").forEach((button) => button.addEventListener("click", persistFilters));
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

connect();
