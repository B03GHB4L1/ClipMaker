import * as THREE from "./vendor/three.module.js";
import { saveProject, flushProject, newProject, rememberProject, projectRequest, beginProjectOperation } from "./projects.js";

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
  if (Array.isArray(match.events)) renderEvents(match.events);
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
    list.appendChild(button);
  });
};

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
  } catch (error) { showToast(error.message); }
  finally { finish(); }
  input.value = "";
}));
document.querySelectorAll("[data-remove-period]").forEach((button) => button.addEventListener("click", async () => {
  const period = button.dataset.removePeriod;
  delete (activeMatch.period_videos || {})[period];
  document.querySelector(`[data-period-file="${period}"]`).textContent = "";
  try { await saveProject(activeMatch.id, { period_videos: activeMatch.period_videos || {} }); }
  catch (error) { showToast(error.message); }
}));
matchVideo.addEventListener("loadedmetadata", () => {
  previewDuration.textContent = formatTime(matchVideo.duration);
  document.querySelector("[data-timeline-end]").textContent = formatTime(
    matchVideo.duration,
  );
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
  previewName.textContent = "No footage selected";
  previewDuration.textContent = "--:--:--";
  document.querySelector("[data-timeline-end]").textContent = "--:--:--";
  document.querySelector("[data-timeline-time]").textContent = "00:00:00";
  playhead.style.left = "0%";
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
  renderEvents([]);
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
const setScrubTime = (seconds, updateMarker = false) => {
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
    if (activePeriod) { activePeriod.dataset.marker = value; activePeriod.dataset.markerSet = "true"; }
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
  const activePeriod = document.querySelector(".period-selector .is-active");
  const resetValue = "00:00:00";
  activePeriod.dataset.marker = resetValue;
  activePeriod.dataset.markerSet = "false";
  const seconds = resetValue
    .split(":")
    .reduce((total, part) => total * 60 + Number(part), 0);
  setScrubTime(seconds);
  updateMarkerTime(resetValue);
  persistIntake();
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
  const isControl = target.closest("button, a, summary, [role='tab'], dialog");
  if (isEditing || isControl || eventDialog.open) return;
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
    persistIntake();
  }
});

const periodLabels = {
  "1H": "First-half kick-off",
  "2H": "Second-half kick-off",
  ET1: "Extra-time first-half kick-off",
  ET2: "Extra-time second-half kick-off",
  PEN: "First penalty kick",
};
document.querySelector("[data-set-marker]").addEventListener("click", () => {
  if (!Number.isFinite(matchVideo.duration)) { showToast("Load footage before setting a marker from playback."); return; }
  setScrubTime(matchVideo.currentTime, true);
  persistIntake();
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
  const seconds = value
    .split(":")
    .reduce((total, part) => total * 60 + Number(part), 0);
  setScrubTime(seconds, false);
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
      updateMarkerTime(button.dataset.marker);
      if (activeMatch.id && (activeMatch.video_path || activeMatch.period_videos?.[button.dataset.period])) {
        apiRequest("/api/files/reopen", { method: "POST", body: JSON.stringify({ match_id: activeMatch.id, period: button.dataset.period }) })
          .then((result) => showSelectedVideo(result.file, false)).catch((error) => showToast(error.message));
      }
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
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const initializeBall = async () => {
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
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
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
    const resize = () => {
      const width = heroBall.clientWidth;
      const height = heroBall.clientHeight;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    resize();
    new ResizeObserver(resize).observe(heroBall);
    let visible = true;
    new IntersectionObserver(entries => visible = entries[0].isIntersecting).observe(heroBall);
    renderer.setAnimationLoop(time => {
      if (!visible || document.hidden) return;
      ball.rotation.y = reducedMotion.matches ? 0 : Math.sin(time * 0.00018) * 0.22;
      ball.rotation.x = reducedMotion.matches ? 0 : Math.sin(time * 0.00012) * 0.025;
      renderer.render(scene, camera);
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
renderEvents([]);
document.querySelector(".event-footer span").textContent = "No event data";
document.querySelector(".ticket-meta span:first-child").textContent = "No match loaded";
document.querySelector(".ticket-meta span:last-child").textContent = "";
document.querySelector(".ticket-foot span:last-child").textContent = "Awaiting data";
document.querySelector("main").inert = true;
document.querySelector("[data-new-project]").disabled = true;
initializeBall();
