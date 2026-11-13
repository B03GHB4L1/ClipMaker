let writes = Promise.resolve();
const unsaved = [];
const operations = new Set();
let failure;

export const projectRequest = async (path, body) => {
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
    list.append(link);
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

window.addEventListener("beforeunload", (event) => {
  if (unsaved.length || operations.size || failure) { event.preventDefault(); event.returnValue = ""; }
});
