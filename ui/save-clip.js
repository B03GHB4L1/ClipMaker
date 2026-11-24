// "Save clip" for clips VizorPlay cut for watching (Filter fallback, Analyst,
// Tactical). The engine copies the clip into the user's VizorPlay folder, so it
// works the same in the desktop windows (which ignore <a download>) and in a
// browser. A small pop-up then says where it went and offers to open the folder.

import { FULLSCREEN_ICON, openChartFullscreen } from "./chart-fullscreen.js";

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

// Every "Open folder" button goes through here: the engine opens the folder it
// owns (by id, never a path from the page) and says which one; the app then
// raises that Explorer window (src-tauri raise_folder_window).
export const revealFolder = async (apiPath) => {
  await allowForeground();
  const { folder } = await post(apiPath);
  if (folder) await window.__TAURI__?.core?.invoke("raise_folder_window", { folder }).catch(() => {});
};

// Plotly icon: a picture with an arrow into a film frame.
const SEND_ICON = { width: 24, height: 24, path: "M3 5h14v3h-2V7H5v10h10v-1h2v3H3V5zm12 3l5 4-5 4v-3H9v-2h6V8z" };

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
      await revealFolder(`/api/saved/${encodeURIComponent(saved.id)}/reveal`);
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

/** Add a chart picture (a Blob, data: URL or a promise of one) to the active project's pictures, for "Insert picture" in the clip editor. */
export const sendToClip = async (image, name) => {
  try {
    const project = activeProjectId();
    if (!project) throw new Error("Open a project first; pictures are kept with a project.");
    const picture = await image;
    const blob = typeof picture === "string" ? await (await fetch(picture)).blob() : picture;
    const response = await fetch(`/api/projects/${encodeURIComponent(project)}/pictures`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(name || "") },
      body: blob,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
    show({ title: "Sent to the clip editor", file: `${payload.picture?.name || "Picture"}: open a clip, then choose Insert picture.` });
    return payload.picture;
  } catch (error) {
    show({ title: "Could not send the picture", file: error.message, error: true });
    return null;
  }
};

// Hints such as "Hover points for event details." only make sense in the app.
const HOVER_HINT = /[^.]*\bhover\b[^.]*\.?/gi;
const NOTE_ROOM = 40; // bottom margin once a note under the chart is gone
// Pitch maps: the picture is cropped around the pitch, but stays a landscape frame
// at least this wide for its height, and wide enough for the title and note.
const PITCH_PICTURE_RATIO = 1.4;
const MIN_PICTURE_WIDTH = 760;
const SIDE = 36; // px of background beside the pitch at least
const TITLE_ROOM = 78; // title and scope line above the pitch

/** A pitch map cropped to the pitch: the app's wide frame leaves empty bands beside it. */
const cropToPitch = (chart, layout) => {
  const full = chart._fullLayout || {};
  const plot = full._size;
  const pitchWidth = full.xaxis?._length;
  const pitchHeight = full.yaxis?._length;
  if (!plot || !pitchWidth || !pitchHeight) return;
  const labelRoom = layout.annotations.some((note) => note.text === "ATTACK ->") ? 26 : 0;
  const note = layout.annotations.some((note) => note.yref === "paper" && note.y < 0);
  // A side legend widened the right margin; keep that room.
  const legendRoom = Math.max(0, plot.r - (chart.layout.margin?.r ?? 80));
  const top = TITLE_ROOM + labelRoom;
  const bottom = note ? Math.round(pitchHeight * 0.08) + 44 : SIDE;
  const height = Math.round(pitchHeight + top + bottom);
  const width = Math.round(Math.max(MIN_PICTURE_WIDTH, pitchWidth + 2 * SIDE + legendRoom, height * PITCH_PICTURE_RATIO));
  const side = Math.floor((width - legendRoom - pitchWidth) / 2);
  Object.assign(layout, {
    width,
    height,
    margin: { ...chart.layout.margin, l: side, r: side + legendRoom, t: top, b: bottom, autoexpand: false },
    // Plotly writes the on-screen shrunken domains back into the layout; the
    // cropped frame already has the pitch's shape, so the pitch gets all of it.
    xaxis: { ...layout.xaxis, domain: [0, 1] },
    yaxis: { ...layout.yaxis, domain: [0, 1] },
    // Pinned to the top in pixels, so it keeps its place in the shorter frame.
    title: layout.title && { ...layout.title, y: 1, yref: "container", yanchor: "top", pad: { t: 22 } },
  });
};

/** The chart as it is drawn in the app, minus hover hints; pitch maps cropped to the pitch. */
export const exportFigure = (chart) => {
  const full = chart._fullLayout || {};
  const layout = { ...chart.layout, width: Math.round(full.width || chart.clientWidth || 1200),
    height: Math.round(full.height || chart.clientHeight || 700) };
  let droppedBelow = false;
  layout.annotations = (chart.layout.annotations || []).flatMap((note) => {
    const text = String(note.text || "");
    if (!/\bhover\b/i.test(text)) return [note];
    const kept = text.replace(/<br\s*\/?>/gi, " ").replace(HOVER_HINT, "").replace(/\s{2,}/g, " ").trim();
    if (kept) return [{ ...note, text: kept }];
    if (note.yref === "paper" && note.y < 0) droppedBelow = true;
    return [];
  });
  if (chart.layout.yaxis?.scaleanchor === "x") {
    cropToPitch(chart, layout);
    return { data: chart.data, layout, config: { staticPlot: true } };
  }
  const below = layout.annotations.some((note) => note.yref === "paper" && note.y < 0);
  const bottom = full.margin?.b ?? chart.layout.margin?.b;
  if (droppedBelow && !below && bottom > NOTE_ROOM) {
    // The note's room goes too, so the picture keeps the chart's own size and shape.
    layout.margin = { ...chart.layout.margin, b: NOTE_ROOM };
    layout.height -= bottom - NOTE_ROOM;
  }
  return { data: chart.data, layout, config: { staticPlot: true } };
};

// Plotly's camera button downloads through <a download>, which the desktop
// windows ignore; swap it for one that saves through the engine. A "Full screen"
// button opens the chart over the whole window (chart-fullscreen.js).
export const plotlyConfig = (config = {}, Plotly = window.Plotly) => {
  if (!config.displayModeBar || !Plotly?.toImage) return config;
  const options = config.toImageButtonOptions || {};
  const fullscreen = {
    name: "fullscreen",
    title: "Full screen",
    icon: FULLSCREEN_ICON,
    // The copy keeps Plotly's own zoom and hover tools; save pictures from the chart on the page.
    click: (chart) => openChartFullscreen(chart, {
      ...config, modeBarButtonsToAdd: [],
      modeBarButtonsToRemove: [...(config.modeBarButtonsToRemove || []), "toImage"],
    }, Plotly),
  };
  return {
    ...config,
    modeBarButtonsToRemove: [...(config.modeBarButtonsToRemove || []), "toImage"],
    modeBarButtonsToAdd: [...(config.modeBarButtonsToAdd || []), fullscreen, {
      name: "sendToClip",
      title: "Send to clip",
      icon: SEND_ICON,
      click: (chart) => {
        const figure = exportFigure(chart);
        return sendToClip(import("./analysis/brand-export.js").then(({ brandPicture }) => brandPicture(Plotly.toImage(figure, {
          format: "png", scale: options.scale || 2,
          width: options.width || figure.layout.width, height: options.height || figure.layout.height }))),
        `${options.filename || "VizorPlay chart"}.png`);
      },
    }, {
      name: "saveImage",
      title: "Save as PNG",
      icon: Plotly.Icons.camera,
      // The picture is the chart as drawn in the app (Plotly's own default is a
      // 700px-wide box), without hover hints, plus the VizorPlay credit strip
      // (analysis/brand-export.js). A size set in the config still wins.
      click: (chart) => {
        const figure = exportFigure(chart);
        return saveImage(import("./analysis/brand-export.js").then(({ brandPicture }) => brandPicture(Plotly.toImage(figure, {
          format: "png", scale: options.scale || 2,
          width: options.width || figure.layout.width, height: options.height || figure.layout.height }))),
        `${options.filename || "VizorPlay chart"}.png`);
      },
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
