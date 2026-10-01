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

let activeMatch;
let filterMetadata;
let activeJobId;
let previewComplete = false;
let toastTimer;

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
    const group = document.createElement("section");
    group.className = "qualifier-group";
    const heading = document.createElement("h3");
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
  };
  Object.entries(values).forEach(([selector, value]) => {
    document.querySelector(selector).value = value;
  });
  document.querySelector("[data-individual-clips]").checked = Boolean(
    options.individual_clips,
  );
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
  try {
    const value = JSON.parse(localStorage.getItem(snapshotStorageKey) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
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
  if (job.status === "complete" && job.dry_run) {
    previewComplete = true;
    exportButton.disabled = !activeMatch.video_path;
    document.querySelector("[data-summary-note]").textContent =
      activeMatch.video_path
        ? "Plan ready. Export will use the same filters."
        : "Plan ready. Add match footage in Intake before exporting.";
  } else if (job.status === "complete") {
    document.querySelector("[data-summary-note]").textContent =
      "The reel was saved in ClipMaker's local exports folder.";
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
    cancelJobButton.hidden = true;
  }
};

const startClipJob = async (dryRun) => {
  if (!activeMatch?.id) {
    showToast("Choose a saved match before filtering");
    return;
  }
  if (!dryRun && !activeMatch.video_path) {
    showToast("Add match footage in Intake before exporting");
    return;
  }
  planOutput.hidden = false;
  cancelJobButton.hidden = false;
  exportButton.disabled = true;
  jobState.textContent = dryRun ? "Starting preview" : "Starting export";
  jobLogs.textContent = "Preparing filters...";
  jobProgress.style.width = "4%";
  try {
    const result = await apiRequest("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        match_id: activeMatch.id,
        options: collectOptions(dryRun),
      }),
    });
    activeJobId = result.job.id;
    renderJob(result.job);
    pollJob(activeJobId);
  } catch (error) {
    activeJobId = undefined;
    cancelJobButton.hidden = true;
    jobState.textContent = "Setup needs attention";
    jobLogs.textContent = error.message;
    jobProgress.style.width = "0%";
    exportButton.disabled = !previewComplete || !activeMatch.video_path;
    showToast(error.message);
  }
};

const loadMatch = async (matchId) => {
  const result = await apiRequest("/api/filter-options", {
    method: "POST",
    body: JSON.stringify({ match_id: matchId }),
  });
  activeMatch = result.match;
  filterMetadata = result;
  sessionStorage.setItem("clipmaker.active-match", activeMatch.id);
  const url = new URL(window.location.href);
  url.searchParams.set("match", activeMatch.id);
  history.replaceState({}, "", url);
  renderMatchContext();
  renderTeams();
  renderActions();
  renderQualifiers();
  resetFilters();
};

const connect = async () => {
  try {
    await apiRequest("/api/health");
    setEngineState("Engine ready", true);
    const historyResult = await apiRequest("/api/matches");
    const matches = historyResult.matches || [];
    if (!matches.length) {
      throw new Error("Scrape and save a match in Intake before filtering.");
    }
    matchSelect.replaceChildren();
    matches.forEach((match) => {
      const option = document.createElement("option");
      option.value = match.id;
      option.textContent = `${match.home_team} vs ${match.away_team}`;
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

form.addEventListener("change", () => {
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
    applyOptions(presets[button.dataset.preset]);
    showToast(`${button.textContent.trim()} preset applied`);
  });
});

document.querySelector("[data-reset-filters]").addEventListener("click", () => {
  resetFilters();
  showToast("All filters cleared");
});

document.querySelector("[data-save-snapshot]").addEventListener("click", () => {
  const name = document.querySelector("[data-snapshot-name]").value.trim();
  if (!name) {
    showToast("Enter a snapshot name first");
    return;
  }
  const snapshots = getSnapshots();
  snapshots[name] = collectOptions(true);
  localStorage.setItem(snapshotStorageKey, JSON.stringify(snapshots));
  renderSnapshots();
  snapshotSelect.value = name;
  snapshotSelect.dispatchEvent(new Event("change"));
  showToast(`Saved snapshot: ${name}`);
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
  .addEventListener("click", () => {
    const name = snapshotSelect.value;
    const snapshots = getSnapshots();
    delete snapshots[name];
    localStorage.setItem(snapshotStorageKey, JSON.stringify(snapshots));
    renderSnapshots();
    showToast(`Deleted snapshot: ${name}`);
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

connect();
