import * as THREE from "./vendor/three.module.js";
import { saveProject, flushProject, newProject, rememberProject, projectRequest, beginProjectOperation, deleteButton } from "./projects.js";

const body = document.body;
const drawerButton = document.querySelector("[data-drawer-toggle]");
const drawer = document.querySelector("#nav-drawer");
const overlay = document.querySelector("[data-drawer-overlay]");
const toast = document.querySelector("[data-toast]");
const engineState = document.querySelector("[data-engine-state]");
let toastTimer;
let apiAvailable = false;
let activeMatch = {
  home_team: "", away_team: "", event_count: 0, markers: {},
};

// The source names open the sites in the user's browser (the desktop window
// cannot show other sites). The engine opens only these two fixed addresses.
document.addEventListener("click", async (event) => {
  const link = event.target.closest?.("[data-source-site]");
  if (!link) return;
  event.preventDefault();
  try {
    await window.__TAURI__?.core?.invoke("allow_foreground").catch(() => {});
    const response = await fetch("/api/open-site", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site: link.dataset.sourceSite }),
    });
    if (!response.ok) throw new Error();
  } catch {
    window.open(link.href, "_blank", "noopener");
  }
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

// Every column of the event CSV (the API sends {columns, rows, periods}); the table
// scrolls sideways with the match clock pinned on the left.
const renderEvents = (
  table,
  eventBody = document.querySelector("[data-event-body]"),
  eventHead = document.querySelector("[data-event-head]"),
) => {
  const columns = Array.isArray(table?.columns) ? table.columns : [];
  const rows = Array.isArray(table?.rows) ? table.rows : [];
  const minute = columns.indexOf("minute");
  const second = columns.indexOf("second");
  const typeColumn = columns.indexOf("type");
  const headRow = document.createElement("tr");
  ["Time", ...columns].forEach((name) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = name;
    headRow.appendChild(cell);
  });
  eventHead.replaceChildren(...(columns.length ? [headRow] : []));
  eventBody.replaceChildren(
    ...rows.map((values, index) => {
      const row = document.createElement("tr");
      row.dataset.period = String(table.periods?.[index] ?? "");
      const clock = (column) => String(Number(values[column] || 0)).padStart(2, "0");
      const time = minute >= 0 ? `${clock(minute)}:${second >= 0 ? clock(second) : "00"}` : "—";
      [time, ...values].forEach((value, column) => {
        const cell = document.createElement(column === 0 ? "th" : "td");
        if (column === 0) cell.scope = "row";
        if (column - 1 === typeColumn && value) {
          const pill = document.createElement("span");
          pill.className = "event-pill";
          pill.textContent = String(value);
          cell.appendChild(pill);
        } else if (value === true) {
          cell.textContent = "✓";
          cell.className = "event-flag";
        } else if (value !== null && value !== false) {
          cell.textContent = String(value);
        }
        row.appendChild(cell);
      });
      return row;
    }),
  );
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
  activeMatch = { ...match };
  if (match.id) rememberProject(match);
  document.querySelector("#match-url").value = match.source_url || "";
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
  document.querySelector(".ticket-foot span:last-child").textContent = match.csv_path ? "Data saved locally" : "No match loaded";
  document.querySelector(".event-footer span").textContent = match.csv_path ? `${count} saved rows` : "No event data";
  if (match.events) renderEvents(match.events);
  if (match.markers) {
    document
      .querySelectorAll(".period-selector [data-period]")
      .forEach((button) => {
        const marker = match.markers[button.dataset.period];
        button.dataset.marker = marker || "00:00:00";
        button.dataset.markerSet = String(Boolean(marker));
      });
    const hasExtraTime = Boolean(match.had_extra_time || match.markers.ET1 || match.markers.ET2);
    document.querySelector("[data-extra-time]").checked = hasExtraTime;
    document.querySelector("[data-penalties]").checked = Boolean(
      match.had_penalties || match.markers.PEN,
    );
    setOptionalPeriods();
    const activePeriod = document.querySelector(".period-selector .is-active");
    if (activePeriod) updateMarkerTime(activePeriod.dataset.marker);
  }
};

const renderHistory = (matches) => {
  const list = document.querySelector("[data-recent-list]");
  list.replaceChildren();
  matches.forEach((match, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-row";

    const number = document.createElement("span");
    number.className = "recent-index";
    number.textContent = String(index + 1).padStart(2, "0");

    const details = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = match.project_name || `${match.home_team || "Home"} vs ${match.away_team || "Away"}`;
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
      try { await flushProject(); await openProject(match); }
      catch (error) { showToast(error.message); return; }
      document
        .querySelector(".workspace")
        .scrollIntoView({ behavior: "smooth", block: "start" });
    });
    const item = document.createElement("div");
    item.className = "recent-item";
    item.append(button, deleteButton(match));
    list.appendChild(item);
  });
};

document.addEventListener("vizorplay:project-deleted", async ({ detail }) => {
  try {
    const projects = detail.projects || [];
    if (detail.wasActive && !projects.length) {
      // The last project went; start a fresh one so Intake always has one open.
      const fresh = await newProject();
      projects.push(fresh);
    }
    renderHistory(projects);
    if (detail.wasActive) await openProject(projects[0]);
    showToast("Project moved to the project trash");
  } catch (error) { showToast(error.message); }
});

const connectApi = async () => {
  try {
    await apiRequest("/api/health");
    apiAvailable = true;
    const result = await apiRequest("/api/projects");
    renderHistory(result.projects || []);
    const requested = new URLSearchParams(location.search).get("project") || sessionStorage.getItem("clipmaker.active-match");
    const project = result.projects.find((item) => item.id === requested) || result.projects[0] || await newProject();
    await openProject(project);
    setEngineState("Engine ready", true);
    document.querySelector("[data-new-project]").disabled = false;
    document.querySelector("main").inert = false;
  } catch (error) {
    setEngineState("Engine unavailable", false);
    showToast(error.message);
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
  drawer.inert = !open;
  if (open) drawer.querySelector("button, a")?.focus();
  else if (drawer.contains(document.activeElement)) drawerButton.focus();
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

// The VizorPlay screen stays up a moment after the page loads, then peels away
// (styles.css .page-wipe). The engine connects straight away underneath it.
const WIPE_HOLD_MS = 1200;
window.addEventListener("load", () => {
  connectApi();
  setTimeout(() => requestAnimationFrame(() => body.classList.add("is-loaded")), WIPE_HOLD_MS);
});

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
    let finish;
    button.textContent = "···";
    document.querySelector("[data-match-ticket]").style.opacity = ".35";
    try {
      if (!apiAvailable) {
        await new Promise((resolve) => setTimeout(resolve, 700));
        showToast("Design preview: connect the local engine for live scraping");
      } else {
        const url = document.querySelector("#match-url").value.trim();
        await flushProject();
        finish = beginProjectOperation();
        const result = await apiRequest("/api/scrape", {
          method: "POST",
          body: JSON.stringify({ url, project_id: activeMatch.id }),
        });
        renderMatch(result.match);
        document.querySelector(".event-browser").open = true;
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
    } finally { finish?.(); }
  });

const videoInput = document.querySelector("[data-video-input]");
document.querySelector("[data-batch-fetch]").addEventListener("click", async (event) => {
  const urls = document.querySelector("[data-batch-urls]").value.split(/\r?\n/).map((url) => url.trim()).filter(Boolean);
  if (!urls.length || urls.length > 20) { showToast("Enter between 1 and 20 match URLs."); return; }
  const button = event.currentTarget;
  const output = document.querySelector("[data-batch-status]");
  button.disabled = true;
  const completed = [];
  const errors = [];
  let finish;
  try {
    await persistIntake();
    await flushProject();
    finish = beginProjectOperation();
    for (const [index, url] of urls.entries()) {
      output.textContent = `Scraping ${index + 1} of ${urls.length}...`;
      try {
        const { project } = await projectRequest("/api/projects", {});
        await saveProject(project.id, { source_url: url });
        const result = await apiRequest("/api/scrape", { method: "POST", body: JSON.stringify({ url, project_id: project.id }) });
        completed.push(result.match);
      } catch (error) { errors.push(`${index + 1}: ${error.message}`); }
    }
    output.textContent = `${completed.length} matches saved. ${errors.join("; ")}`;
    const result = await projectRequest("/api/projects");
    renderHistory(result.projects);
    if (completed.length) await openProject(completed[0]);
  } catch (error) { showToast(error.message); }
  finally { finish?.(); button.disabled = false; }
});
const matchVideo = document.querySelector("[data-match-video]");
const matchFrame = document.querySelector(".match-frame");
const previewName = document.querySelector(".preview-top span:first-child");
const previewDuration = document.querySelector(".preview-top span:last-child");
let videoUrl;
// Where to put the playhead once a reloaded period video is ready.
let pendingSeek = null;

const showSelectedVideo = ({ name, size, url, path }, save = true) => {
  if (videoUrl?.startsWith("blob:")) URL.revokeObjectURL(videoUrl);
  videoUrl = url;
  matchVideo.src = videoUrl;
  matchFrame.classList.add("has-video");
  document.querySelector("[data-file-row]").hidden = false;
  document.querySelector("[data-file-count]").textContent = "1 file";
  document.querySelector(".file-info strong").textContent = name;
  document.querySelector(".file-info strong").title = name;
  document.querySelector(".file-info small").textContent =
    `${(size / 1073741824).toFixed(1)} GB · local file`;
  previewName.textContent = name;
  previewName.title = name;
  document.querySelector(".play-button").disabled = false;
  setPlayerEnabled(true);
  if (save) {
    activeMatch.video_name = name;
    activeMatch.video_path = path || "";
  }
  if (save) persistIntake();
  showToast("Footage loaded locally. It never leaves this device.");
};

document
  .querySelector("[data-dropzone]")
  .addEventListener("click", async () => {
    if (!apiAvailable) {
      videoInput.click();
      return;
    }
    let finish;
    try {
      await flushProject();
      finish = beginProjectOperation();
      if (navigator.platform.toLowerCase().includes("mac")) { videoInput.click(); return; }
      const result = await apiRequest("/api/files/video", {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (result.browser_picker) videoInput.click();
      else if (!result.cancelled) showSelectedVideo(result.file);
    } catch (error) {
      showToast("Native picker unavailable. Choose the file in the browser.");
      videoInput.click();
    } finally { finish?.(); }
  });

const importFile = async (file) => {
  if (!activeMatch.id || !apiAvailable) throw new Error("The local engine must be connected before importing.");
  const response = await fetch(`/api/files/upload?project=${encodeURIComponent(activeMatch.id)}`, {
    method: "POST", headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name) }, body: file,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Could not import file.");
  return result;
};
videoInput.addEventListener("change", async () => {
  const file = videoInput.files[0];
  if (!file) return;
  const finish = beginProjectOperation();
  try { showToast("Copying footage into this local project..."); showSelectedVideo((await importFile(file)).file); }
  catch (error) { showToast(error.message); }
  finally { finish(); }
  videoInput.value = "";
});

document.querySelector("[data-csv-input]").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  let finish;
  try { await flushProject(); finish = beginProjectOperation(); renderMatch((await importFile(file)).match); showToast("Match data imported and saved locally"); }
  catch (error) { showToast(error.message); }
  finally { finish?.(); }
  event.target.value = "";
});
document.querySelectorAll("[data-period-video]").forEach((input) => input.addEventListener("change", async () => {
  const file = input.files[0];
  if (!file) return;
  const finish = beginProjectOperation();
  try {
    const result = await importFile(file);
    activeMatch.period_videos = { ...(activeMatch.period_videos || {}), [input.dataset.periodVideo]: result.file.path };
    document.querySelector(`[data-period-file="${input.dataset.periodVideo}"]`).textContent = file.name;
    await saveProject(activeMatch.id, { period_videos: activeMatch.period_videos });
    renderTimelineMarkers();
  } catch (error) { showToast(error.message); }
  finally { finish(); }
  input.value = "";
}));
document.querySelectorAll("[data-remove-period]").forEach((button) => button.addEventListener("click", async () => {
  const period = button.dataset.removePeriod;
  delete (activeMatch.period_videos || {})[period];
  document.querySelector(`[data-period-file="${period}"]`).textContent = "";
  renderTimelineMarkers();
  try { await saveProject(activeMatch.id, { period_videos: activeMatch.period_videos || {} }); }
  catch (error) { showToast(error.message); }
}));
matchVideo.addEventListener("loadedmetadata", () => {
  previewDuration.textContent = formatTime(matchVideo.duration);
  matchVideo.playbackRate = Number(playbackRate.value);
  renderTimelineMarkers();
  if (pendingSeek !== null) setScrubTime(pendingSeek);
  pendingSeek = null;
  syncPlaybackUi();
});
const clearFootage = () => {
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
  setPlayerEnabled(false);
  pendingSeek = null;
  previewName.textContent = "No footage selected";
  previewDuration.textContent = "--:--:--";
  previewSeconds = 0;
  renderTimeline();
  videoInput.value = "";
};
document.querySelector(".remove-button").addEventListener("click", () => {
  clearFootage();
  persistIntake();
  showToast("Video removed from this project");
});
document
  .querySelector("[data-new-project]")
  .addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await persistIntake();
      await openProject(await newProject());
      const result = await projectRequest("/api/projects");
      renderHistory(result.projects);
      showToast("New local project created");
    } catch (error) { showToast(error.message); }
    finally { button.disabled = false; }
  });

const getActiveMarkers = () => {
  const markers = {};
  document
    .querySelectorAll(".period-selector [data-period]")
    .forEach((button) => {
      if (!button.disabled && button.dataset.markerSet === "true")
        markers[button.dataset.period] = button.dataset.marker;
    });
  return markers;
};

const persistIntake = () => {
  if (!apiAvailable || !activeMatch.id) return Promise.resolve();
  const period = document.querySelector(".period-selector .is-active");
  const clock = document.querySelector("[data-time]").value.trim();
  if (/^\d{1,3}:[0-5]\d:[0-5]\d$/.test(clock) && clock !== period.dataset.marker) {
    period.dataset.marker = clock;
    period.dataset.markerSet = "true";
  }
  const patch = {
    project_name: document.querySelector("[data-project-name]").value.trim() || "Untitled project",
    source_url: document.querySelector("#match-url").value.trim(),
    markers: getActiveMarkers(), video_path: activeMatch.video_path || "",
    video_name: activeMatch.video_name || "",
    had_extra_time: document.querySelector("[data-extra-time]").checked,
    had_penalties: document.querySelector("[data-penalties]").checked,
  };
  activeMatch = { ...activeMatch, ...patch };
  const saving = saveProject(activeMatch.id, patch);
  saving.catch((error) => showToast(error.message));
  return saving;
};

const openProject = async (project) => {
  clearFootage();
  renderEvents(null);
  document.querySelector("[data-event-search]").value = "";
  document.querySelector("[data-period-filter]").value = "all";
  document.querySelector(".event-footer span").textContent = "No event data";
  document.querySelector(".ticket-meta span:first-child").textContent = "Saved match";
  document.querySelector(".ticket-meta span:last-child").textContent = "";
  document.querySelector(".ticket-foot span:last-child").textContent = project.csv_path ? "Data saved locally" : "No match loaded";
  renderMatch(project);
  document.querySelectorAll("[data-period-file]").forEach((span) => {
    span.textContent = (project.period_videos?.[span.dataset.periodFile] || "").split(/[\\/]/).pop();
  });
  const url = new URL(location.href);
  url.searchParams.set("project", project.id);
  history.replaceState({}, "", url);
  if (project.csv_path) {
    try {
      const result = await apiRequest("/api/events", { method: "POST", body: JSON.stringify({ csv_path: project.csv_path }) });
      renderEvents(result.events);
      document.querySelector(".event-footer span").textContent = `${result.event_count.toLocaleString()} saved rows`;
    } catch (error) { showToast("Saved event data is unavailable. Import the CSV or scrape the match again."); }
  }
  if (project.video_path) {
    try {
      const result = await apiRequest("/api/files/reopen", { method: "POST", body: JSON.stringify({ match_id: project.id }) });
      showSelectedVideo(result.file, false);
    } catch (error) { showToast(error.message); }
  }
};

document.querySelector("[data-project-name]").addEventListener("change", persistIntake);
document.querySelector("#match-url").addEventListener("change", persistIntake);
document.querySelector("[data-project-name]").addEventListener("input", persistIntake);
document.querySelector("#match-url").addEventListener("input", persistIntake);

document
  .querySelector("[data-continue]")
  .addEventListener("click", async () => {
    if (!apiAvailable) {
      showToast("Design preview: timeline confirmation is ready to connect");
      return;
    }
    try {
      if (!activeMatch.csv_path) throw new Error("Scrape or import event data before filtering.");
      await persistIntake();
      await flushProject();
      sessionStorage.setItem("clipmaker.active-match", activeMatch.id);
      window.location.href = `/filters.html?match=${encodeURIComponent(activeMatch.id)}`;
    } catch (error) {
      showToast(error.message);
    }
  });

const timeline = document.querySelector("[data-timeline]");
const playhead = document.querySelector("[data-playhead]");
const markerInput = document.querySelector("[data-time]");
const playbackTime = document.querySelector("[data-timeline-time]");
const timelineStart = document.querySelector("[data-timeline-start]");
const timelineEnd = document.querySelector("[data-timeline-end]");
const timelineMarkers = document.querySelector("[data-timeline-markers]");
const playButton = document.querySelector(".play-button");
const playerToggle = document.querySelector("[data-player-toggle]");
const playbackRate = document.querySelector("[data-playback-rate]");
const muteButton = document.querySelector("[data-mute]");
const setKickoffButton = document.querySelector("[data-set-marker]");
const periodLabels = {
  "1H": "First-half kick-off",
  "2H": "Second-half kick-off",
  ET1: "Extra-time first-half kick-off",
  ET2: "Extra-time second-half kick-off",
  PEN: "First penalty kick",
};
const updateMarkerTime = (value) => {
  markerInput.value = value;
};
const scrubCursor = document.querySelector(".scrub-cursor");
let scrubbing = false;
// Seconds shown when no footage is loaded (design preview), a zoomed view's
// width in seconds (0 = whole video) and where that view starts.
let previewSeconds = 0;
let zoomSpan = 0;
let viewStart = 0;
// One frame, measured from playback where the webview supports it.
const DEFAULT_FRAME_STEP = 1 / 25;
let measuredFrameStep = null;
const frameStep = () => measuredFrameStep || DEFAULT_FRAME_STEP;
const formatTime = (seconds) => {
  const safeSeconds = Number.isFinite(seconds)
    ? Math.max(0, Math.round(seconds))
    : 0;
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = safeSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
};
// Playhead readout with tenths, so frame steps visibly move it.
const formatPreciseTime = (seconds) => {
  const tenths = Math.floor((Number.isFinite(seconds) ? Math.max(0, seconds) : 0) * 10);
  return `${formatTime(Math.floor(tenths / 10))}.${tenths % 10}`;
};
const parseClock = (value) =>
  String(value).split(":").reduce((total, part) => total * 60 + Number(part), 0);
const hasVideo = () => matchFrame.classList.contains("has-video");
const hasDuration = () =>
  hasVideo() && Number.isFinite(matchVideo.duration) && matchVideo.duration > 0;
const videoDuration = () => (hasDuration() ? matchVideo.duration : 600);
const currentSeconds = () =>
  hasVideo() && Number.isFinite(matchVideo.currentTime) ? matchVideo.currentTime : previewSeconds;
const activePeriodButton = () => document.querySelector(".period-selector .is-active");

// The part of the video the timeline shows. A zoomed view follows the
// playhead when it leaves the window (playback, steps, marker jumps).
const timelineView = (current = currentSeconds()) => {
  const duration = videoDuration();
  if (!zoomSpan || zoomSpan >= duration) {
    viewStart = 0;
    return { start: 0, span: duration };
  }
  if (current < viewStart || current > viewStart + zoomSpan) viewStart = current - zoomSpan / 2;
  viewStart = Math.max(0, Math.min(viewStart, duration - zoomSpan));
  return { start: viewStart, span: zoomSpan };
};
const viewPercent = (seconds, view) => ((seconds - view.start) / view.span) * 100;
const renderTimeline = () => {
  const current = currentSeconds();
  const view = timelineView(current);
  playhead.style.left = `${Math.max(0, Math.min(100, viewPercent(current, view)))}%`;
  playbackTime.textContent = formatPreciseTime(current);
  timelineStart.textContent = formatTime(view.start);
  timelineEnd.textContent = hasDuration() ? formatTime(view.start + view.span) : "--:--:--";
  timelineMarkers.querySelectorAll("[data-marker-seconds]").forEach((marker) => {
    const percent = viewPercent(Number(marker.dataset.markerSeconds), view);
    marker.hidden = percent < 0 || percent > 100;
    marker.style.left = `${percent}%`;
  });
};
// Periods whose kick-off lies in the loaded file: a period with its own video
// file shows only its own marker; otherwise every period sharing the main video.
const periodsInLoadedVideo = () => {
  const own = activeMatch.period_videos || {};
  const active = activePeriodButton()?.dataset.period;
  if (active && own[active]) return new Set([active]);
  return new Set(Object.keys(periodLabels).filter((period) => !own[period]));
};
const renderTimelineMarkers = () => {
  const periods = periodsInLoadedVideo();
  const active = activePeriodButton();
  timelineMarkers.replaceChildren();
  document.querySelectorAll(".period-selector [data-period]").forEach((button) => {
    const period = button.dataset.period;
    if (button.disabled || button.dataset.markerSet !== "true" || !periods.has(period)) return;
    const marker = document.createElement("button");
    marker.type = "button";
    marker.className = `timeline-marker${button === active ? " is-active" : ""}`;
    marker.dataset.markerSeconds = String(parseClock(button.dataset.marker));
    marker.dataset.markerPeriod = period;
    marker.title = `${periodLabels[period]} ${button.dataset.marker}`;
    marker.setAttribute(
      "aria-label",
      `Jump to ${periodLabels[period].toLowerCase()} at ${button.dataset.marker}`,
    );
    const label = document.createElement("span");
    label.textContent = period;
    marker.append(label);
    marker.addEventListener("pointerdown", (event) => event.stopPropagation());
    marker.addEventListener("click", () => setScrubTime(Number(marker.dataset.markerSeconds)));
    timelineMarkers.append(marker);
  });
  renderTimeline();
};
// Markers change from many places (typing, reset, loading a project), so the
// period buttons' own data is the single source the timeline redraws from.
new MutationObserver(renderTimelineMarkers).observe(
  document.querySelector(".period-selector"),
  { subtree: true, attributes: true, attributeFilter: ["data-marker", "data-marker-set", "disabled", "class"] },
);
const setPlayerEnabled = (enabled) => {
  document
    .querySelectorAll("[data-player-toggle], [data-step], [data-playback-rate], [data-mute], [data-set-marker]")
    .forEach((control) => {
      control.disabled = !enabled;
    });
};
const updateKickoffButton = () => {
  const period = activePeriodButton()?.dataset.period || "1H";
  setKickoffButton.textContent =
    period === "PEN" ? "Set first penalty here" : `Set ${period} kick-off here`;
};
const syncPlaybackUi = () => {
  document.querySelector(".frame-score time").textContent =
    formatTime(currentSeconds()).slice(3);
  renderTimeline();
};
const setScrubTime = (seconds, updateMarker = false) => {
  const safeSeconds = Math.max(0, Math.min(seconds, videoDuration()));
  if (hasVideo()) matchVideo.currentTime = safeSeconds;
  else previewSeconds = safeSeconds;
  syncPlaybackUi();
  if (updateMarker) {
    const value = formatTime(safeSeconds);
    updateMarkerTime(value);
    const activePeriod = activePeriodButton();
    if (activePeriod) { activePeriod.dataset.marker = value; activePeriod.dataset.markerSet = "true"; }
  }
};
const updateTimeline = (clientX) => {
  const bounds = timeline.getBoundingClientRect();
  const ratio = Math.max(
    0,
    Math.min(1, (clientX - bounds.left) / bounds.width),
  );
  const view = timelineView();
  setScrubTime(view.start + ratio * view.span);
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
  persistIntake();
});
timeline.addEventListener("pointerenter", () =>
  scrubCursor.classList.add("is-visible"),
);
timeline.addEventListener("pointerleave", () => {
  scrubbing = false;
  scrubCursor.classList.remove("is-visible");
});
document.querySelector(".text-button").addEventListener("click", () => {
  const activePeriod = activePeriodButton();
  const resetValue = "00:00:00";
  activePeriod.dataset.marker = resetValue;
  activePeriod.dataset.markerSet = "false";
  setScrubTime(parseClock(resetValue));
  updateMarkerTime(resetValue);
  persistIntake();
  showToast("Kick-off marker reset");
});
const togglePlayback = () => {
  if (!hasVideo()) return;
  if (matchVideo.paused) matchVideo.play();
  else matchVideo.pause();
};
// The time to seek to for a frame step: the middle of the neighbouring frame.
// Adding a frame length to currentTime can land a hair before a frame boundary
// (101.08 - 0.04 = 101.039999), which shows the wrong frame.
const frameStepTarget = (current, direction, length) =>
  (Math.floor(current / length + 1e-3) + direction + 0.5) * length;
// A step is a number of seconds, or one frame back/forward. Frame steps pause.
const stepPlayback = (step) => {
  if (!hasVideo()) return;
  if (step === "frame-back" || step === "frame-forward") {
    matchVideo.pause();
    setScrubTime(frameStepTarget(matchVideo.currentTime, step === "frame-back" ? -1 : 1, frameStep()));
  } else {
    setScrubTime(matchVideo.currentTime + Number(step));
  }
};
playButton.addEventListener("click", togglePlayback);
playerToggle.addEventListener("click", togglePlayback);
document.querySelectorAll("[data-step]").forEach((button) =>
  button.addEventListener("click", () => stepPlayback(button.dataset.step)),
);
playbackRate.addEventListener("change", () => {
  matchVideo.defaultPlaybackRate = Number(playbackRate.value);
  matchVideo.playbackRate = Number(playbackRate.value);
});
muteButton.addEventListener("click", () => {
  matchVideo.muted = !matchVideo.muted;
  muteButton.setAttribute("aria-pressed", String(matchVideo.muted));
});
document.querySelectorAll("[data-zoom]").forEach((button) =>
  button.addEventListener("click", () => {
    zoomSpan = Number(button.dataset.zoom);
    document.querySelectorAll("[data-zoom]").forEach((item) =>
      item.setAttribute("aria-pressed", String(item === button)),
    );
    viewStart = currentSeconds() - zoomSpan / 2;
    renderTimeline();
  }),
);
matchVideo.addEventListener("timeupdate", syncPlaybackUi);
matchVideo.addEventListener("play", () => {
  playButton.textContent = "Ⅱ";
  playButton.setAttribute("aria-label", "Pause preview");
  playerToggle.textContent = "Ⅱ";
  playerToggle.setAttribute("aria-label", "Pause");
});
matchVideo.addEventListener("pause", () => {
  playButton.textContent = "▶";
  playButton.setAttribute("aria-label", "Play preview");
  playerToggle.textContent = "▶";
  playerToggle.setAttribute("aria-label", "Play");
});
if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
  // The smallest gap between presented frames is one frame: dropped frames
  // only lengthen gaps, and seeks or a new file reset the measurement.
  let lastMediaTime = null;
  const onFrame = (_now, metadata) => {
    if (lastMediaTime !== null) {
      const gap = metadata.mediaTime - lastMediaTime;
      if (gap > 0.008 && gap < 0.1) measuredFrameStep = Math.min(measuredFrameStep || gap, gap);
    }
    lastMediaTime = metadata.mediaTime;
    matchVideo.requestVideoFrameCallback(onFrame);
  };
  matchVideo.addEventListener("seeking", () => { lastMediaTime = null; });
  matchVideo.addEventListener("loadstart", () => { lastMediaTime = null; measuredFrameStep = null; });
  matchVideo.requestVideoFrameCallback(onFrame);
}

document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const isEditing =
    target instanceof HTMLInputElement ||
    target instanceof HTMLSelectElement ||
    target instanceof HTMLTextAreaElement ||
    target.isContentEditable;
  const isControl = target.closest("button, a, summary, [role='tab'], dialog");
  // Step keys keep working while focus is on the player's own buttons.
  const inPlayer = target.closest("[data-player-controls], .marker-controls, [data-timeline]");
  if (isEditing || eventDialog.open || !hasVideo()) return;
  if (isControl && !inPlayer) return;
  if (event.code === "Space") {
    if (isControl) return; // Space presses the focused button instead.
    event.preventDefault();
    togglePlayback();
  } else if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
    event.preventDefault();
    const seconds = event.ctrlKey || event.metaKey ? 60 : event.shiftKey ? 10 : 1;
    stepPlayback((event.key === "ArrowLeft" ? -1 : 1) * seconds);
  } else if (event.key === "," || event.key === ".") {
    event.preventDefault();
    stepPlayback(event.key === "," ? "frame-back" : "frame-forward");
  }
});

setKickoffButton.addEventListener("click", () => {
  if (!hasDuration()) {
    showToast("Load footage before setting a marker from playback.");
    return;
  }
  setScrubTime(matchVideo.currentTime, true);
  persistIntake();
  showToast(`${periodLabels[activePeriodButton().dataset.period]} set to ${formatTime(matchVideo.currentTime)}`);
});
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
  .forEach((input) => input.addEventListener("change", () => { setOptionalPeriods(); persistIntake(); }));

document.querySelector("[data-time]").addEventListener("change", (event) => {
  const value = event.currentTarget.value.trim();
  if (!/^\d{1,3}:[0-5]\d:[0-5]\d$/.test(value)) {
    const active = document.querySelector(".period-selector .is-active");
    updateMarkerTime(active.dataset.marker);
    showToast("Use kickoff time format HH:MM:SS");
    return;
  }
  const active = document.querySelector(".period-selector .is-active");
  active.dataset.marker = value;
  active.dataset.markerSet = "true";
  updateMarkerTime(value);
  setScrubTime(parseClock(value), false);
  persistIntake();
});
document.querySelector("[data-time]").addEventListener("input", (event) => {
  const value = event.currentTarget.value.trim();
  if (!/^\d{1,3}:[0-5]\d:[0-5]\d$/.test(value)) return;
  const active = document.querySelector(".period-selector .is-active");
  active.dataset.marker = value;
  active.dataset.markerSet = "true";
  persistIntake();
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
      updateKickoffButton();
      updateMarkerTime(button.dataset.marker);
      const seconds = parseClock(button.dataset.marker);
      if (activeMatch.id && (activeMatch.video_path || activeMatch.period_videos?.[button.dataset.period])) {
        // Reopening reloads the video, so land on this period's kick-off once it is ready.
        apiRequest("/api/files/reopen", { method: "POST", body: JSON.stringify({ match_id: activeMatch.id, period: button.dataset.period }) })
          .then((result) => { pendingSeek = seconds; showSelectedVideo(result.file, false); })
          .catch((error) => showToast(error.message));
      }
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
      renderEvents(result.events, fullEventBody, document.querySelector("[data-full-event-head]"));
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
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const initializeBall = async () => {
  // The supplied still is also the low-cost, accessible reduced-motion view.
  if (reducedMotion.matches) return;
  let renderer;
  let environment;
  try {
    const [{ GLTFLoader }, { RoomEnvironment }] = await Promise.all([
      import("./vendor/loaders/GLTFLoader.js"),
      import("./vendor/environments/RoomEnvironment.js"),
    ]);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    camera.position.set(0, 0.04, 4.9);
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.85;
    const studio = new RoomEnvironment();
    const generator = new THREE.PMREMGenerator(renderer);
    environment = generator.fromScene(studio, 0.03);
    studio.dispose();
    generator.dispose();
    scene.environment = environment.texture;
    const model = await new GLTFLoader().loadAsync("./assets/vizorplay-football.glb");
    const ball = model.scene;
    ball.traverse(object => {
      if (!object.isMesh) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach(material => {
        material.envMapIntensity = 0.75;
        material.roughness = Math.max(material.roughness, 0.28);
      });
    });
    scene.add(ball);
    heroBall.appendChild(renderer.domElement);
    let stillRendered = false;
    const resize = () => {
      const width = heroBall.clientWidth;
      const height = heroBall.clientHeight;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      stillRendered = false;
    };
    resize();
    new ResizeObserver(resize).observe(heroBall);
    let visible = true;
    new IntersectionObserver(entries => visible = entries[0].isIntersecting).observe(heroBall);
    let lastFrame = -Infinity;
    renderer.setAnimationLoop(time => {
      if (!visible || document.hidden || time - lastFrame < 1000 / 30) return;
      if (reducedMotion.matches && stillRendered) return;
      lastFrame = time;
      ball.rotation.y = reducedMotion.matches ? 0 : Math.sin(time * 0.00018) * 0.22;
      ball.rotation.x = reducedMotion.matches ? 0 : Math.sin(time * 0.00012) * 0.025;
      renderer.render(scene, camera);
      stillRendered = reducedMotion.matches;
      heroBall.classList.add("model-ready");
    });
    renderer.domElement.addEventListener("webglcontextlost", () => {
      heroBall.classList.remove("model-ready");
      renderer.setAnimationLoop(null);
    });
  } catch (error) {
    renderer?.dispose();
    environment?.dispose();
    console.warn("Chrome ball preview fallback:", error.message);
  }
};
renderMatch({ home_team: "", away_team: "", event_count: 0, markers: {} });
renderHistory([]);
renderEvents(null);
document.querySelector(".event-footer span").textContent = "No event data";
document.querySelector(".ticket-meta span:first-child").textContent = "No match loaded";
document.querySelector(".ticket-meta span:last-child").textContent = "";
document.querySelector(".ticket-foot span:last-child").textContent = "Awaiting data";
document.querySelector("main").inert = true;
document.querySelector("[data-new-project]").disabled = true;
initializeBall();
