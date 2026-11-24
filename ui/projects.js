let writes = Promise.resolve();
const unsaved = [];
const operations = new Set();
let failure;

export const projectRequest = async (path, body) => {
  // Analysis charts are drawn for the app's light or dark theme (ui/theme.js).
  if (body && typeof body === "object" && !Array.isArray(body) && path.startsWith("/api/analysis/")) {
    body = { ...body, theme: window.vizorTheme?.get?.() || "light" };
  }
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Could not save the project.");
  return result;
};

const showSaveState = (text, failed = false) => {
  document.querySelectorAll("[data-project-status]").forEach((element) => {
    element.textContent = text;
    element.classList.toggle("save-failed", failed);
  });
};

export const rememberProject = (project) => {
  sessionStorage.setItem("clipmaker.active-match", project.id);
  const input = document.querySelector("[data-project-name]");
  if (input) input.value = project.project_name || (project.home_team ? `${project.home_team} vs ${project.away_team}` : "Untitled project");
  if (!unsaved.length && !failure) showSaveState("Saved locally");
};

const drainWrites = (entry) => {
  const result = writes.catch(() => {}).then(async () => {
    // Keep failed patches in order until a retry succeeds; later partial saves
    // must not hide or discard them.
    while (unsaved.length) {
      const next = unsaved[0];
      const value = await projectRequest(`/api/projects/${encodeURIComponent(next.id)}`, next.snapshot);
      next.project = value.project;
      unsaved.shift();
    }
    failure = undefined;
    showSaveState("Saved locally");
    return entry?.project;
  });
  writes = result.catch((error) => {
    failure = error;
    showSaveState("Save failed", true);
    throw error;
  });
  return writes;
};

export const saveProject = (id, patch) => {
  if (!id) return Promise.reject(new Error("No project is open."));
  const entry = { id, snapshot: structuredClone(patch) };
  unsaved.push(entry);
  showSaveState("Saving locally...");
  return drainWrites(entry);
};

export const flushProject = async () => {
  while (operations.size) await Promise.all([...operations]);
  await writes.catch(() => {});
  if (unsaved.length) await drainWrites();
  if (failure) throw failure;
};

export const beginProjectOperation = () => {
  let finish;
  const operation = new Promise((resolve) => { finish = resolve; });
  operations.add(operation);
  return () => { operations.delete(operation); finish(); };
};

export const newProject = async () => {
  await flushProject();
  const result = await projectRequest("/api/projects", {});
  rememberProject(result.project);
  return result.project;
};

export const projectTitle = (project) =>
  project.project_name || (project.home_team ? `${project.home_team} vs ${project.away_team}` : "Untitled project");

const TRASH_ICON = '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v4.5M9.2 6.5v4.5"/></svg>';

export const deleteButton = (project, onDeleted) => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "project-delete";
  button.innerHTML = TRASH_ICON;
  button.title = "Delete project";
  button.setAttribute("aria-label", `Delete project ${projectTitle(project)}`);
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    try {
      const result = await deleteProject(project);
      if (result) onDeleted?.(result);
    } catch (error) { showSaveState(error.message, true); }
  });
  return button;
};

const confirmDelete = (project) => new Promise((resolve) => {
  const dialog = document.createElement("dialog");
  dialog.className = "projects-dialog confirm-delete";
  const heading = document.createElement("h2");
  heading.textContent = `Delete “${projectTitle(project)}”?`;
  const text = document.createElement("p");
  text.textContent = "This deletes the project for good; it cannot be undone. Its matches stay saved with their events, kick-off times and video locations, so other projects can still use them. Your video files are not touched.";
  const actions = document.createElement("div");
  actions.className = "confirm-actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "Cancel";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "danger";
  confirm.textContent = "Delete project";
  // The buttons answer directly; the close event (Esc) is only a fallback,
  // since some windows deliver it late or not at all.
  let settled = false;
  const finish = (answer) => {
    if (settled) return;
    settled = true;
    if (dialog.open) dialog.close();
    dialog.remove();
    resolve(answer);
  };
  cancel.onclick = () => finish(false);
  confirm.onclick = () => finish(true);
  actions.append(cancel, confirm);
  dialog.append(heading, text, actions);
  dialog.addEventListener("close", () => finish(false));
  document.body.append(dialog);
  dialog.showModal();
  cancel.focus();
});

// Returns the remaining projects, or null when the user cancels.
export const deleteProject = async (project) => {
  if (!(await confirmDelete(project))) return null;
  await flushProject().catch(() => {});
  const result = await projectRequest(`/api/projects/${encodeURIComponent(project.id)}/delete`, {});
  // Patches still queued for the deleted project can never land; drop them.
  for (let index = unsaved.length - 1; index >= 0; index -= 1) {
    if (unsaved[index].id === project.id) unsaved.splice(index, 1);
  }
  if (!unsaved.length) failure = undefined;
  const wasActive = sessionStorage.getItem("clipmaker.active-match") === project.id;
  if (wasActive) sessionStorage.removeItem("clipmaker.active-match");
  document.dispatchEvent(new CustomEvent("vizorplay:project-deleted",
    { detail: { id: project.id, wasActive, projects: result.projects } }));
  return result;
};

export const openProjects = async () => {
  await flushProject();
  const { projects, directory } = await projectRequest("/api/projects");
  const dialog = document.createElement("dialog");
  dialog.className = "projects-dialog";
  const heading = document.createElement("h2");
  heading.textContent = "Local projects";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "project-close";
  close.setAttribute("aria-label", "Close projects");
  close.textContent = "\u00d7";
  close.onclick = () => dialog.close();
  const list = document.createElement("div");
  list.className = "project-list";
  projects.forEach((project) => {
    const link = document.createElement("a");
    link.href = `/?project=${encodeURIComponent(project.id)}`;
    const name = document.createElement("strong");
    name.textContent = project.project_name || `${project.home_team} vs ${project.away_team}`;
    const metadata = document.createElement("small");
    metadata.textContent = `${Number(project.event_count || 0).toLocaleString()} events | ${new Date(project.updated_at).toLocaleString()}`;
    link.append(name, metadata);
    const row = document.createElement("div");
    row.className = "project-row";
    row.append(link, deleteButton(project, () => row.remove()));
    list.append(row);
  });
  const location = document.createElement("p");
  location.className = "project-location";
  location.textContent = directory;
  dialog.append(heading, close, list, location);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
};

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-open-projects]")) {
    openProjects().catch((error) => showSaveState(error.message, true));
  }
});

document.addEventListener("click", async (event) => {
  const link = event.target.closest("a[data-project-navigation]");
  if (!link) return;
  event.preventDefault();
  try {
    await flushProject();
    window.location.href = link.href;
  } catch (error) {
    showSaveState(error.message, true);
  }
});

// Pages without their own project list: leave a deleted open project for Intake.
document.addEventListener("vizorplay:project-deleted", (event) => {
  if (event.detail.wasActive && !document.querySelector("[data-recent-list]")) window.location.href = "/";
});

window.addEventListener("beforeunload", (event) => {
  if (unsaved.length || operations.size || failure) { event.preventDefault(); event.returnValue = ""; }
});
