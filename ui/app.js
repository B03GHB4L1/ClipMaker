import * as THREE from "./vendor/three.module.js";

const body = document.body;
const drawerButton = document.querySelector("[data-drawer-toggle]");
const drawer = document.querySelector("#nav-drawer");
const overlay = document.querySelector("[data-drawer-overlay]");
const toast = document.querySelector("[data-toast]");
const engineState = document.querySelector("[data-engine-state]");
let toastTimer;
let apiAvailable = false;
let activeMatch = {
  home_team: "Arsenal",
  away_team: "Newcastle",
  event_count: 1486,
  source: "scoresway",
};
let workflowStep = 1;

const setWorkflowStep = (step) => {
  workflowStep = Math.max(workflowStep, step);
  document
    .querySelectorAll("[data-workflow-progress] [data-step]")
    .forEach((button) => {
      const buttonStep = Number(button.dataset.step);
      button.classList.toggle("is-current", buttonStep === workflowStep);
      button.classList.toggle("is-complete", buttonStep < workflowStep);
    });
  document.querySelector("[data-step-label]").textContent =
    `${workflowStep} / 4`;
};

const workflowTargets = {
  1: ".workspace",
  2: ".sync-section",
};

document
  .querySelectorAll("[data-workflow-progress] [data-step]")
  .forEach((button) => {
    button.addEventListener("click", () => {
      if (Number(button.dataset.step) >= 3) {
        const query = activeMatch.id
          ? `?match=${encodeURIComponent(activeMatch.id)}`
          : "";
        window.location.href = `/filters.html${query}`;
        return;
      }
      document
        .querySelector(workflowTargets[button.dataset.step])
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

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

const setEngineState = (label, connected) => {
  engineState.querySelector("span").textContent = label;
  engineState.classList.toggle("is-offline", !connected);
};

const renderEvents = (
  events,
  eventBody = document.querySelector("[data-event-body]"),
) => {
  eventBody.replaceChildren();
  events.forEach((event) => {
    const minute = Number(event.minute || 0);
    const second = Number(event.second || 0);
    const time = `${String(minute).padStart(2, "0")}:${String(second).padStart(2, "0")}`;
    const values = [
      time,
      event.playerName || "—",
      event.type || "Event",
      event.team || "—",
      event.xT ?? "—",
    ];
    const row = document.createElement("tr");
    row.dataset.period = String(event.period || "");
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      if (index === 2) {
        const pill = document.createElement("span");
        pill.className = "event-pill";
        pill.textContent = String(value);
        cell.appendChild(pill);
      } else {
        cell.textContent = String(value);
      }
      row.appendChild(cell);
    });
    eventBody.appendChild(row);
  });
};

const shortTeamName = (name = "") =>
  name
    .trim()
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 3)
    .toUpperCase() || "—";

const renderMatch = (match) => {
  activeMatch = { ...activeMatch, ...match };
  document.querySelector("[data-home-team]").textContent =
    match.home_team || "Home";
  document.querySelector("[data-away-team]").textContent =
    match.away_team || "Away";
  const homeScore = Number(match.home_score || 0);
  const awayScore = Number(match.away_score || 0);
  document.querySelector("[data-home-score]").textContent = homeScore;
  document.querySelector("[data-away-score]").textContent = awayScore;
  document.querySelector("[data-score-status]").textContent =
    match.score_status || "FT";
  document.querySelector(".team-badge.arsenal").textContent = (
    match.home_team || "H"
  )
    .trim()
    .charAt(0)
    .toUpperCase();
  document.querySelector(".team-badge.newcastle").textContent = (
    match.away_team || "A"
  )
    .trim()
    .charAt(0)
    .toUpperCase();
  document.querySelector("[data-frame-home]").textContent = shortTeamName(
    match.home_team,
  );
  document.querySelector("[data-frame-away]").textContent = shortTeamName(
    match.away_team,
  );
  document.querySelector("[data-frame-score]").textContent =
    `${homeScore} - ${awayScore}`;
  const count = Number(match.event_count || 0).toLocaleString();
  document.querySelector("[data-event-count]").textContent =
    `${count} events found`;
  document.querySelector("[data-row-count]").textContent = `${count} rows`;
  if (Array.isArray(match.events)) renderEvents(match.events);
  if (match.markers) {
    document
      .querySelectorAll(".period-selector [data-period]")
      .forEach((button) => {
        const marker = match.markers[button.dataset.period];
        if (marker) button.dataset.marker = marker;
      });
    const hasExtraTime = Boolean(match.markers.ET1 || match.markers.ET2);
    document.querySelector("[data-extra-time]").checked = hasExtraTime;
    document.querySelector("[data-penalties]").checked = Boolean(
      match.markers.PEN,
    );
    setOptionalPeriods();
    const activePeriod = document.querySelector(".period-selector .is-active");
    if (activePeriod) updateMarkerTime(activePeriod.dataset.marker);
  }
};

const renderHistory = (matches) => {
  if (!matches.length) return;
  const list = document.querySelector("[data-recent-list]");
  list.replaceChildren();
  matches.slice(0, 5).forEach((match, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-row";

    const number = document.createElement("span");
    number.className = "recent-index";
    number.textContent = String(index + 1).padStart(2, "0");

    const details = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = `${match.home_team || "Home"} vs ${match.away_team || "Away"}`;
    const subtitle = document.createElement("small");
    const updated = match.updated_at
      ? new Date(match.updated_at).toLocaleString([], {
          dateStyle: "medium",
          timeStyle: "short",
        })
      : "Saved locally";
    subtitle.textContent = `${Number(match.event_count || 0).toLocaleString()} events · ${updated}`;
    details.append(title, subtitle);

    const state = document.createElement("span");
    state.className = `recent-state${match.status === "complete" ? " done" : ""}`;
    state.textContent =
      match.status === "complete" ? "Complete" : "In progress";
    const arrow = document.createElement("i");
    arrow.textContent = "↗";
    button.append(number, details, state, arrow);
    button.addEventListener("click", async () => {
      renderMatch(match);
      if (apiAvailable && match.video_path) {
        try {
          const result = await apiRequest("/api/files/reopen", {
            method: "POST",
            body: JSON.stringify({ match_id: match.id }),
          });
          showSelectedVideo(result.file);
          showToast("Saved match and footage reopened");
        } catch (error) {
          showToast(error.message);
        }
      } else {
        showToast("Saved match reopened");
      }
      document
        .querySelector(".workspace")
        .scrollIntoView({ behavior: "smooth", block: "start" });
    });
    list.appendChild(button);
  });
};

const connectApi = async () => {
  try {
    await apiRequest("/api/health");
    apiAvailable = true;
    setEngineState("Engine ready", true);
    const history = await apiRequest("/api/matches");
    renderHistory(history.matches || []);
  } catch {
    setEngineState("Design preview", false);
  }
};

const showToast = (message) => {
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2600);
};

const setDrawer = (open) => {
  body.classList.toggle("drawer-open", open);
  drawerButton.setAttribute("aria-expanded", String(open));
  drawer.setAttribute("aria-hidden", String(!open));
};

drawerButton.addEventListener("click", () =>
  setDrawer(!body.classList.contains("drawer-open")),
);
overlay.addEventListener("click", () => setDrawer(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setDrawer(false);
});
document
  .querySelectorAll(".drawer-link")
  .forEach((link) => link.addEventListener("click", () => setDrawer(false)));

window.addEventListener("load", () =>
  requestAnimationFrame(() => {
    body.classList.add("is-loaded");
    connectApi();
  }),
);

const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  },
  { rootMargin: "0px 0px -10% 0px", threshold: 0.08 },
);
document
  .querySelectorAll(".reveal")
  .forEach((element) => observer.observe(element));

document
  .querySelector("[data-fetch]")
  .addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.textContent = "···";
    document.querySelector("[data-match-ticket]").style.opacity = ".35";
    try {
      if (!apiAvailable) {
        await new Promise((resolve) => setTimeout(resolve, 700));
        showToast("Design preview: connect the local engine for live scraping");
      } else {
        const url = document.querySelector("#match-url").value.trim();
        const result = await apiRequest("/api/scrape", {
          method: "POST",
          body: JSON.stringify({ url }),
        });
        renderMatch(result.match);
        document.querySelector(".event-browser").open = true;
        setWorkflowStep(2);
        showToast(
          `${Number(result.match.event_count).toLocaleString()} events loaded from Python`,
        );
      }
      button.textContent = "✓";
      document.querySelector("[data-match-ticket]").style.opacity = "1";
    } catch (error) {
      button.textContent = "↗";
      document.querySelector("[data-match-ticket]").style.opacity = "1";
      showToast(error.message);
    }
  });

const videoInput = document.querySelector("[data-video-input]");
const matchVideo = document.querySelector("[data-match-video]");
const matchFrame = document.querySelector(".match-frame");
const previewName = document.querySelector(".preview-top span:first-child");
const previewDuration = document.querySelector(".preview-top span:last-child");
let videoUrl;

const showSelectedVideo = ({ name, size, url, path }) => {
  if (videoUrl?.startsWith("blob:")) URL.revokeObjectURL(videoUrl);
  videoUrl = url;
  matchVideo.src = videoUrl;
  matchFrame.classList.add("has-video");
  document.querySelector("[data-file-row]").hidden = false;
  document.querySelector("[data-file-count]").textContent = "1 file";
  document.querySelector(".file-info strong").textContent = name;
  document.querySelector(".file-info small").textContent =
    `${(size / 1073741824).toFixed(1)} GB · local file`;
  previewName.textContent = name;
  document.querySelector(".play-button").disabled = false;
  setWorkflowStep(2);
  activeMatch.video_name = name;
  activeMatch.video_path = path || "";
  if (jobState?.textContent === "Clip plan ready") {
    exportButton.disabled = !activeMatch.video_path;
  }
  showToast("Footage loaded locally. It never leaves this device.");
};

document
  .querySelector("[data-dropzone]")
  .addEventListener("click", async () => {
    if (!apiAvailable) {
      videoInput.click();
      return;
    }
    try {
      const result = await apiRequest("/api/files/video", {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (!result.cancelled) showSelectedVideo(result.file);
    } catch (error) {
      showToast(error.message);
    }
  });

videoInput.addEventListener("change", () => {
  const file = videoInput.files[0];
  if (!file) return;
  showSelectedVideo({
    name: file.name,
    size: file.size,
    url: URL.createObjectURL(file),
    path: "",
  });
});
matchVideo.addEventListener("loadedmetadata", () => {
  previewDuration.textContent = formatTime(matchVideo.duration);
  document.querySelector("[data-timeline-end]").textContent = formatTime(
    matchVideo.duration,
  );
  syncPlaybackUi();
});
document.querySelector(".remove-button").addEventListener("click", () => {
  document.querySelector("[data-file-row]").hidden = true;
  matchVideo.pause();
  matchVideo.removeAttribute("src");
  matchFrame.classList.remove("has-video");
  if (videoUrl?.startsWith("blob:")) URL.revokeObjectURL(videoUrl);
  videoUrl = undefined;
  activeMatch.video_name = "";
  activeMatch.video_path = "";
  document.querySelector("[data-file-count]").textContent = "No file";
  document.querySelector(".play-button").disabled = true;
  previewName.textContent = "No footage selected";
  previewDuration.textContent = "--:--:--";
  document.querySelector("[data-timeline-end]").textContent = "--:--:--";
  document.querySelector("[data-timeline-time]").textContent = "00:00:00";
  playhead.style.left = "0%";
  videoInput.value = "";
  showToast("Video removed from this setup");
});
document
  .querySelector("[data-new-project]")
  .addEventListener("click", () => showToast("New project workspace ready"));

const getActiveMarkers = () => {
  const markers = {};
  document
    .querySelectorAll(".period-selector [data-period]")
    .forEach((button) => {
      if (!button.disabled)
        markers[button.dataset.period] = button.dataset.marker;
    });
  return markers;
};

document
  .querySelector("[data-continue]")
  .addEventListener("click", async () => {
    if (!apiAvailable) {
      showToast("Design preview: timeline confirmation is ready to connect");
      return;
    }
    try {
      const saved = await apiRequest("/api/matches", {
        method: "POST",
        body: JSON.stringify({
          ...activeMatch,
          source_url: document.querySelector("#match-url").value.trim(),
          video_name: document.querySelector(".file-info strong").textContent,
          markers: getActiveMarkers(),
          status: "in_progress",
        }),
      });
      const history = await apiRequest("/api/matches");
      renderHistory(history.matches || []);
      activeMatch = saved.match;
      setWorkflowStep(3);
      sessionStorage.setItem("clipmaker.active-match", activeMatch.id);
      window.location.href = `/filters.html?match=${encodeURIComponent(activeMatch.id)}`;
    } catch (error) {
      showToast(error.message);
    }
  });

const filterForm = document.querySelector("[data-filter-form]");
const planButton = document.querySelector("[data-plan-button]");
const exportButton = document.querySelector("[data-export-button]");
const planOutput = document.querySelector("[data-plan-output]");
const jobState = document.querySelector("[data-job-state]");
const jobLogs = document.querySelector("[data-job-logs]");
const jobProgress = document.querySelector("[data-job-progress]");
const cancelJobButton = document.querySelector("[data-cancel-job]");
let activeJobId;

const renderJob = (job) => {
  const labels = {
    queued: "Queued",
    running: "Calculating clip windows",
    complete: "Clip plan ready",
    failed: "Could not build plan",
    cancelled: "Plan cancelled",
  };
  const finished = ["complete", "failed", "cancelled"].includes(job.status);
  jobState.textContent = labels[job.status] || job.status;
  jobLogs.textContent = (job.logs || []).join("\n") || "Reading match events…";
  jobLogs.scrollTop = jobLogs.scrollHeight;
  const progress = job.progress;
  const ratio = progress?.total ? progress.current / progress.total : 0;
  jobProgress.style.width = `${job.status === "complete" ? 100 : Math.min(100, ratio * 100)}%`;
  planButton.disabled = !finished;
  exportButton.disabled = !finished || !activeMatch.video_path;
  cancelJobButton.hidden = finished;
  if (finished) {
    activeJobId = undefined;
    document.querySelector("[data-plan-summary]").textContent =
      job.status === "complete"
        ? job.dry_run
          ? "The plan is ready for review"
          : "Your reel has been exported"
        : labels[job.status];
    if (job.status === "complete") setWorkflowStep(4);
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
    planButton.disabled = false;
    cancelJobButton.hidden = true;
    jobState.textContent = "Connection interrupted";
    jobLogs.textContent = error.message;
  }
};

const getFilterOptions = (dryRun) => {
  const options = {
    dry_run: dryRun,
    filter_types: Array.from(
      filterForm.querySelectorAll(
        '.event-choices input[type="checkbox"]:checked',
      ),
      (input) => input.value,
    ),
    half_filter: document.querySelector("[data-half-filter]").value,
    before_buffer: Number(document.querySelector("[data-before-buffer]").value),
    after_buffer: Number(document.querySelector("[data-after-buffer]").value),
    min_gap: Number(document.querySelector("[data-min-gap]").value),
    pitch_zone_filter: document.querySelector("[data-pitch-zone]").value,
    depth_zone_filter: document.querySelector("[data-depth-zone]").value,
  };
  filterForm.querySelectorAll("[data-filter-flag]").forEach((input) => {
    options[input.dataset.filterFlag] = input.checked;
  });
  return options;
};

const startClipJob = async (dryRun) => {
  if (!apiAvailable) {
    showToast("Start the ClipMaker engine to calculate a real clip plan");
    return;
  }
  if (!activeMatch.id) {
    showToast("Confirm the match setup before building a clip plan");
    document.querySelector("[data-continue]").focus();
    return;
  }
  if (!dryRun && !activeMatch.video_path) {
    showToast("Choose match footage before exporting the reel");
    return;
  }
  planOutput.hidden = false;
  planButton.disabled = true;
  exportButton.disabled = true;
  cancelJobButton.hidden = false;
  jobState.textContent = dryRun ? "Starting engine" : "Starting export";
  jobLogs.textContent = dryRun
    ? "Preparing event filters…"
    : "Preparing video export…";
  jobProgress.style.width = "4%";
  try {
    const saved = await apiRequest("/api/matches", {
      method: "POST",
      body: JSON.stringify({
        ...activeMatch,
        markers: getActiveMarkers(),
        status: "in_progress",
      }),
    });
    activeMatch = saved.match;
    const result = await apiRequest("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        match_id: activeMatch.id,
        options: getFilterOptions(dryRun),
      }),
    });
    activeJobId = result.job.id;
    renderJob(result.job);
    pollJob(activeJobId);
  } catch (error) {
    activeJobId = undefined;
    planButton.disabled = false;
    exportButton.disabled = !activeMatch.video_path;
    cancelJobButton.hidden = true;
    jobState.textContent = "Setup needs attention";
    jobLogs.textContent = error.message;
    jobProgress.style.width = "0%";
    showToast(error.message);
  }
};

filterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await startClipJob(true);
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

const timeline = document.querySelector("[data-timeline]");
const playhead = document.querySelector("[data-playhead]");
const markerInput = document.querySelector("[data-time]");
const playbackTime = document.querySelector("[data-timeline-time]");
const playButton = document.querySelector(".play-button");
const updateMarkerTime = (value) => {
  markerInput.value = value;
};
const scrubCursor = document.querySelector(".scrub-cursor");
let scrubbing = false;
const formatTime = (seconds) => {
  const safeSeconds = Number.isFinite(seconds)
    ? Math.max(0, Math.round(seconds))
    : 0;
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = safeSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
};
const syncPlaybackUi = () => {
  const current = Number.isFinite(matchVideo.currentTime)
    ? matchVideo.currentTime
    : 0;
  const duration = Number.isFinite(matchVideo.duration)
    ? matchVideo.duration
    : 0;
  playbackTime.textContent = formatTime(current);
  document.querySelector(".frame-score time").textContent =
    formatTime(current).slice(3);
  playhead.style.left = `${duration ? (current / duration) * 100 : 0}%`;
};
const setScrubTime = (seconds, updateMarker = true) => {
  const duration = Number.isFinite(matchVideo.duration)
    ? matchVideo.duration
    : 600;
  const safeSeconds = Math.max(0, Math.min(seconds, duration));
  if (matchFrame.classList.contains("has-video")) {
    matchVideo.currentTime = safeSeconds;
    syncPlaybackUi();
  } else {
    playbackTime.textContent = formatTime(safeSeconds);
    playhead.style.left = `${(safeSeconds / duration) * 100}%`;
  }
  if (updateMarker) {
    const value = formatTime(safeSeconds);
    updateMarkerTime(value);
    const activePeriod = document.querySelector(".period-selector .is-active");
    if (activePeriod) activePeriod.dataset.marker = value;
  }
};
const updateTimeline = (clientX) => {
  const bounds = timeline.getBoundingClientRect();
  const ratio = Math.max(
    0,
    Math.min(1, (clientX - bounds.left) / bounds.width),
  );
  const duration = Number.isFinite(matchVideo.duration)
    ? matchVideo.duration
    : 600;
  setScrubTime(ratio * duration);
};
timeline.addEventListener("pointerdown", (event) => {
  scrubbing = true;
  timeline.setPointerCapture(event.pointerId);
  updateTimeline(event.clientX);
});
timeline.addEventListener("pointermove", (event) => {
  scrubCursor.style.left = `${event.clientX}px`;
  scrubCursor.style.top = `${event.clientY}px`;
  if (scrubbing) updateTimeline(event.clientX);
});
timeline.addEventListener("pointerup", () => {
  scrubbing = false;
});
timeline.addEventListener("pointerenter", () =>
  scrubCursor.classList.add("is-visible"),
);
timeline.addEventListener("pointerleave", () => {
  scrubbing = false;
  scrubCursor.classList.remove("is-visible");
});
document.querySelector(".text-button").addEventListener("click", () => {
  const activePeriod = document.querySelector(".period-selector .is-active");
  const resetValue = activePeriod?.dataset.defaultMarker || "00:00:00";
  const seconds = resetValue
    .split(":")
    .reduce((total, part) => total * 60 + Number(part), 0);
  setScrubTime(seconds);
  showToast("Kick-off marker reset");
});
const togglePlayback = () => {
  if (!matchFrame.classList.contains("has-video")) return;
  if (matchVideo.paused) matchVideo.play();
  else matchVideo.pause();
};
playButton.addEventListener("click", togglePlayback);
matchVideo.addEventListener("timeupdate", syncPlaybackUi);
matchVideo.addEventListener("play", () => {
  playButton.textContent = "Ⅱ";
  playButton.setAttribute("aria-label", "Pause preview");
});
matchVideo.addEventListener("pause", () => {
  playButton.textContent = "▶";
  playButton.setAttribute("aria-label", "Play preview");
});

document.addEventListener("keydown", (event) => {
  const target = event.target;
  const isEditing =
    target instanceof HTMLInputElement ||
    target instanceof HTMLSelectElement ||
    target instanceof HTMLTextAreaElement ||
    target.isContentEditable;
  if (isEditing || eventDialog.open) return;
  if (event.code === "Space" && matchFrame.classList.contains("has-video")) {
    event.preventDefault();
    togglePlayback();
  }
  if (
    ["ArrowLeft", "ArrowRight"].includes(event.key) &&
    matchFrame.classList.contains("has-video")
  ) {
    event.preventDefault();
    const direction = event.key === "ArrowLeft" ? -1 : 1;
    setScrubTime(
      matchVideo.currentTime + direction * (event.shiftKey ? 10 : 5),
    );
  }
});

const periodLabels = {
  "1H": "First-half kick-off",
  "2H": "Second-half kick-off",
  ET1: "Extra-time first-half kick-off",
  ET2: "Extra-time second-half kick-off",
  PEN: "First penalty kick",
};
const setOptionalPeriods = () => {
  const extraTime = document.querySelector("[data-extra-time]").checked;
  const penalties = document.querySelector("[data-penalties]").checked;
  document.querySelector('[data-period="ET1"]').disabled = !extraTime;
  document.querySelector('[data-period="ET2"]').disabled = !extraTime;
  document.querySelector('[data-period="PEN"]').disabled = !penalties;
  const active = document.querySelector(".period-selector .is-active");
  if (active?.disabled) document.querySelector('[data-period="1H"]').click();
};

document
  .querySelectorAll("[data-extra-time], [data-penalties]")
  .forEach((input) => input.addEventListener("change", setOptionalPeriods));

document.querySelector("[data-time]").addEventListener("change", (event) => {
  const value = event.currentTarget.value.trim();
  if (!/^\d{2}:\d{2}:\d{2}$/.test(value)) {
    const active = document.querySelector(".period-selector .is-active");
    updateMarkerTime(active.dataset.marker);
    showToast("Use kickoff time format HH:MM:SS");
    return;
  }
  const active = document.querySelector(".period-selector .is-active");
  active.dataset.marker = value;
  updateMarkerTime(value);
  const seconds = value
    .split(":")
    .reduce((total, part) => total * 60 + Number(part), 0);
  setScrubTime(seconds, false);
});

document
  .querySelectorAll(".period-selector [data-period]")
  .forEach((button) => {
    button.dataset.defaultMarker = button.dataset.marker;
    button.addEventListener("click", () => {
      document
        .querySelectorAll(".period-selector [data-period]")
        .forEach((item) => {
          const selected = item === button;
          item.classList.toggle("is-active", selected);
          item.setAttribute("aria-selected", String(selected));
        });
      document.querySelector("[data-period-label]").textContent =
        periodLabels[button.dataset.period];
      updateMarkerTime(button.dataset.marker);
      const seconds = button.dataset.marker
        .split(":")
        .reduce((total, part) => total * 60 + Number(part), 0);
      if (Number.isFinite(matchVideo.duration)) {
        setScrubTime(seconds, false);
      }
    });
  });

const filterEvents = () => {
  const query = document
    .querySelector("[data-event-search]")
    .value.trim()
    .toLowerCase();
  const period = document.querySelector("[data-period-filter]").value;
  document.querySelectorAll("[data-event-body] tr").forEach((row) => {
    row.hidden = !(
      (period === "all" || row.dataset.period === period) &&
      row.textContent.toLowerCase().includes(query)
    );
  });
};
document
  .querySelector("[data-event-search]")
  .addEventListener("input", filterEvents);
document
  .querySelector("[data-period-filter]")
  .addEventListener("change", filterEvents);

const eventDialog = document.querySelector("[data-event-dialog]");
const fullEventBody = document.querySelector("[data-full-event-body]");
const filterFullEvents = () => {
  const query = document
    .querySelector("[data-full-event-search]")
    .value.trim()
    .toLowerCase();
  const period = document.querySelector("[data-full-period-filter]").value;
  let visible = 0;
  fullEventBody.querySelectorAll("tr").forEach((row) => {
    row.hidden = !(
      (period === "all" || row.dataset.period === period) &&
      row.textContent.toLowerCase().includes(query)
    );
    if (!row.hidden) visible += 1;
  });
  document.querySelector("[data-full-row-count]").textContent =
    `${visible.toLocaleString()} rows shown`;
};

document
  .querySelector("[data-open-table]")
  .addEventListener("click", async () => {
    if (!apiAvailable || !activeMatch.csv_path) {
      showToast("Scrape or reopen a saved match to view its full event table");
      return;
    }
    eventDialog.showModal();
    document.querySelector("[data-table-title]").textContent =
      `${activeMatch.home_team} vs ${activeMatch.away_team}`;
    document.querySelector("[data-full-row-count]").textContent =
      "Loading events…";
    fullEventBody.replaceChildren();
    try {
      const result = await apiRequest("/api/events", {
        method: "POST",
        body: JSON.stringify({ csv_path: activeMatch.csv_path }),
      });
      renderEvents(result.events || [], fullEventBody);
      filterFullEvents();
      if (result.truncated) showToast("Showing the first 5,000 events");
    } catch (error) {
      eventDialog.close();
      showToast(error.message);
    }
  });

document
  .querySelectorAll("[data-close-table]")
  .forEach((button) =>
    button.addEventListener("click", () => eventDialog.close()),
  );
document
  .querySelector("[data-full-event-search]")
  .addEventListener("input", filterFullEvents);
document
  .querySelector("[data-full-period-filter]")
  .addEventListener("change", filterFullEvents);
eventDialog.addEventListener("click", (event) => {
  if (event.target === eventDialog) eventDialog.close();
});

const heroBall = document.querySelector("[data-hero-ball]");
const reducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)",
).matches;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
camera.position.z = 6.6;
const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(heroBall.clientWidth, heroBall.clientHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
heroBall.appendChild(renderer.domElement);

const textureCanvas = document.createElement("canvas");
textureCanvas.width = 1024;
textureCanvas.height = 512;
const textureContext = textureCanvas.getContext("2d");
textureContext.fillStyle = "#d9d9d5";
textureContext.fillRect(0, 0, 1024, 512);
textureContext.strokeStyle = "#60635e";
textureContext.lineWidth = 9;
for (let x = -100; x < 1124; x += 150) {
  for (let y = -70; y < 600; y += 130) {
    textureContext.beginPath();
    for (let side = 0; side < 6; side += 1) {
      const angle = (Math.PI / 3) * side;
      const px = x + (y % 260 ? 75 : 0) + Math.cos(angle) * 52;
      const py = y + Math.sin(angle) * 52;
      if (side === 0) textureContext.moveTo(px, py);
      else textureContext.lineTo(px, py);
    }
    textureContext.closePath();
    textureContext.stroke();
  }
}
const ballTexture = new THREE.CanvasTexture(textureCanvas);
ballTexture.colorSpace = THREE.SRGBColorSpace;
const ballGroup = new THREE.Group();
const sphere = new THREE.Mesh(
  new THREE.SphereGeometry(1.56, 96, 64),
  new THREE.MeshPhysicalMaterial({
    map: ballTexture,
    color: 0xf5f6ef,
    metalness: 0.72,
    roughness: 0.14,
    clearcoat: 1,
    clearcoatRoughness: 0.08,
  }),
);
ballGroup.add(sphere);
const badgeCanvas = document.createElement("canvas");
badgeCanvas.width = 768;
badgeCanvas.height = 320;
const badgeContext = badgeCanvas.getContext("2d");
badgeContext.fillStyle = "#10120e";
badgeContext.font = "800 210px Arial";
badgeContext.textAlign = "center";
badgeContext.fillText("CM", 330, 230);
badgeContext.fillStyle = "#c8f135";
badgeContext.font = "800 76px Arial";
badgeContext.fillText("1.3", 610, 112);
const badgeTexture = new THREE.CanvasTexture(badgeCanvas);
badgeTexture.colorSpace = THREE.SRGBColorSpace;
const badge = new THREE.Mesh(
  new THREE.PlaneGeometry(1.7, 0.71),
  new THREE.MeshBasicMaterial({ map: badgeTexture, transparent: true }),
);
badge.position.z = 1.68;
ballGroup.add(badge);
scene.add(ballGroup);
scene.add(new THREE.HemisphereLight(0xffffff, 0x575b50, 2.8));
const rimLight = new THREE.DirectionalLight(0xc8f135, 5);
rimLight.position.set(-3, 2, 4);
scene.add(rimLight);
const keyLight = new THREE.DirectionalLight(0xffffff, 7);
keyLight.position.set(4, 4, 5);
scene.add(keyLight);
const renderBall = () => {
  if (!reducedMotion) {
    ballGroup.rotation.y = Math.sin(performance.now() * 0.00022) * 0.12;
    ballGroup.rotation.x = Math.sin(performance.now() * 0.00035) * 0.06;
  }
  renderer.render(scene, camera);
  requestAnimationFrame(renderBall);
};
renderBall();
new ResizeObserver(() => {
  renderer.setSize(heroBall.clientWidth, heroBall.clientHeight);
}).observe(heroBall);
