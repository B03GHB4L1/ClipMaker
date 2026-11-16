// "Save clip" for clips VizorPlay cut for watching (Filter fallback, Analyst,
// Tactical). The engine copies the clip into the user's VizorPlay folder, so it
// works the same in the desktop windows (which ignore <a download>) and in a
// browser. A small pop-up then says where it went and offers to open the folder.

const post = async (path, body) => {
  const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
};

// In the Windows app, the folder window opens on the engine's behalf; the app
// first lets it come to the front (src-tauri allow_foreground). A no-op in a browser.
export const allowForeground = async () => {
  try {
    await window.__TAURI__?.core?.invoke("allow_foreground");
  } catch {
    // Without it the folder still opens; it may only flash on the taskbar.
  }
};

let popup;
let hideTimer;

const hide = () => {
  clearTimeout(hideTimer);
  popup?.classList.remove("is-visible");
};

// Stays up for 8 seconds, longer while the pointer or keyboard is on it.
const scheduleHide = () => {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(hide, 8000);
};

const ensurePopup = () => {
  if (popup) return popup;
  popup = document.createElement("div");
  popup.className = "saved-popup";
  popup.setAttribute("role", "status");
  popup.setAttribute("aria-live", "polite");
  popup.innerHTML = `
    <span class="saved-popup-mark" aria-hidden="true"></span>
    <div class="saved-popup-text">
      <strong data-saved-title></strong>
      <span class="saved-popup-file" data-saved-file></span>
      <span class="saved-popup-folder" data-saved-folder></span>
    </div>
    <div class="saved-popup-actions">
      <button type="button" data-saved-open>Open folder</button>
      <button type="button" class="saved-popup-close" data-saved-close aria-label="Close">&times;</button>
    </div>`;
  popup.addEventListener("pointerenter", () => clearTimeout(hideTimer));
  popup.addEventListener("pointerleave", scheduleHide);
  popup.addEventListener("focusin", () => clearTimeout(hideTimer));
  popup.addEventListener("focusout", scheduleHide);
  popup.querySelector("[data-saved-close]").addEventListener("click", hide);
  document.body.append(popup);
  return popup;
};

const show = ({ title, file, folder, onOpen, error }) => {
  const element = ensurePopup();
  element.classList.toggle("is-error", Boolean(error));
  element.querySelector("[data-saved-title]").textContent = title;
  element.querySelector("[data-saved-file]").textContent = file || "";
  const where = element.querySelector("[data-saved-folder]");
  where.textContent = folder ? `in ${folder}` : "";
  where.title = folder || "";
  const open = element.querySelector("[data-saved-open]");
  open.hidden = !onOpen;
  open.onclick = onOpen || null;
  // Restart the entrance so a second save is noticed.
  element.classList.remove("is-visible");
  void element.offsetWidth;
  element.classList.add("is-visible");
  scheduleHide();
};

/** The pop-up for a file the engine saved ({name, folder, id}). */
export const showSaved = (saved, what = "Clip") => show({
  title: `${what} saved`,
  file: saved.name,
  folder: saved.folder,
  onOpen: async () => {
    try {
      await allowForeground();
      await post(`/api/saved/${encodeURIComponent(saved.id)}/reveal`);
      hide();
    } catch (error) {
      show({ title: "Could not open the folder", file: error.message, error: true });
    }
  },
});

export const showSaveError = (message, what = "Clip") =>
  show({ title: `Could not save the ${what.toLowerCase()}`, file: message, error: true });

/** Save a chart picture (a Blob or data: URL, PNG or GIF, or a promise of one) as `name` in the VizorPlay folder. */
export const saveImage = async (image, name) => {
  try {
    const picture = await image;
    const blob = typeof picture === "string" ? await (await fetch(picture)).blob() : picture;
    const response = await fetch("/api/images/save", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(name || "") },
      body: blob,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    showSaved(payload.saved, "Picture");
    return payload.saved;
  } catch (error) {
    showSaveError(error.message, "Picture");
    return null;
  }
};

// Plotly's camera button downloads through <a download>, which the desktop
// windows ignore; swap it for one that saves through the engine.
export const plotlyConfig = (config = {}, Plotly = window.Plotly) => {
  if (!config.displayModeBar || !Plotly?.toImage) return config;
  const options = config.toImageButtonOptions || {};
  return {
    ...config,
    modeBarButtonsToRemove: [...(config.modeBarButtonsToRemove || []), "toImage"],
    modeBarButtonsToAdd: [...(config.modeBarButtonsToAdd || []), {
      name: "saveImage",
      title: "Save as PNG",
      icon: Plotly.Icons.camera,
      // Only sizes that are set: toImage never finishes when given width: undefined.
      click: (chart) => saveImage(Plotly.toImage(chart, { format: "png", scale: options.scale || 2,
        ...(options.width ? { width: options.width } : {}), ...(options.height ? { height: options.height } : {}) }),
      `${options.filename || "VizorPlay chart"}.png`),
    }],
  };
};

/** Save the clip behind `url` (an /api/media/<id> link) as `name`; `what` names it ("Clip", "Reel"). */
export const saveClip = async (url, name, button, what = "Clip") => {
  const id = String(url || "").split("/").pop();
  const label = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "Saving...";
  }
  try {
    const { saved } = await post(`/api/media/${encodeURIComponent(id)}/save`, { name });
    showSaved(saved, what);
    return saved;
  } catch (error) {
    showSaveError(error.message, what);
    return null;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = label;
    }
  }
};

/** Open the clip behind `url` in the analyst editor; it is first copied into the project. */
export const annotateClip = async (url, name, button, projectId = activeProjectId()) => {
  const media = String(url || "").split("/").pop();
  const label = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "Opening...";
  }
  try {
    if (!projectId) throw new Error("Open a saved project first.");
    const { clip } = await post("/api/editor/clips", { project_id: projectId, media, name });
    window.location.href = `/annotate.html?project=${encodeURIComponent(projectId)}&clip=${encodeURIComponent(clip.id)}`;
    return clip;
  } catch (error) {
    show({ title: "Could not open the editor", file: error.message, error: true });
    if (button) {
      button.disabled = false;
      button.textContent = label;
    }
    return null;
  }
};

const activeProjectId = () => new URLSearchParams(window.location.search).get("project")
  || sessionStorage.getItem("clipmaker.active-match") || "";

/** "Save clip" and "Annotate" buttons for a watched clip ({url, name}). */
export const saveClipButton = (file, what = "Clip", className = "native-button") => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = `Save ${what.toLowerCase()}`;
  button.addEventListener("click", () => saveClip(file.url, file.name, button, what));
  const annotate = document.createElement("button");
  annotate.type = "button";
  annotate.className = `${className} native-secondary`;
  annotate.textContent = "Annotate";
  annotate.title = `Draw on this ${what.toLowerCase()} in the analyst editor`;
  annotate.addEventListener("click", () => annotateClip(file.url, file.name, annotate));
  // Lays out as two siblings in whatever row holds it.
  const pair = document.createElement("span");
  pair.style.display = "contents";
  pair.append(button, annotate);
  return pair;
};
