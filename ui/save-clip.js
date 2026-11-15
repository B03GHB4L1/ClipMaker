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
    show({
      title: `${what} saved`,
      file: saved.name,
      folder: saved.folder,
      onOpen: async () => {
        try {
          await post(`/api/saved/${encodeURIComponent(saved.id)}/reveal`);
          hide();
        } catch (error) {
          show({ title: "Could not open the folder", file: error.message, error: true });
        }
      },
    });
    return saved;
  } catch (error) {
    show({ title: `Could not save the ${what.toLowerCase()}`, file: error.message, error: true });
    return null;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = label;
    }
  }
};

/** A "Save clip" button for a watched clip ({url, name}). */
export const saveClipButton = (file, what = "Clip", className = "native-button") => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = `Save ${what.toLowerCase()}`;
  button.addEventListener("click", () => saveClip(file.url, file.name, button, what));
  return button;
};
