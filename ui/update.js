// Footer notice for a newer VizorPlay release, on every screen.
// The engine checks the release feed (GET /api/update). Windows, Linux and
// Mac disk-image desktop installs update in the app: navigating to INSTALL_PATH is intercepted by
// the desktop shell, which downloads, verifies and installs the signed
// installer, then reports back through window.vizorplayUpdateStatus.
const INSTALL_PATH = "/__vizorplay__/install-update";
const footer = document.querySelector(".app-footer");
const notice = document.createElement("span");
notice.className = "update-notice";
notice.setAttribute("role", "status");
notice.dataset.updateNotice = "";
notice.hidden = true;
footer?.insertBefore(notice, footer.lastElementChild);

const message = document.createElement("span");
let action = null;
let latest = "";

const setMessage = (text) => {
  message.textContent = text;
};
const actionButton = (label, onClick) => {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
};
const startInstall = () => {
  action.disabled = true;
  setMessage(`Downloading VizorPlay ${latest}…`);
  window.location.assign(INSTALL_PATH);
};
const openReleasePage = async () => {
  try {
    // Let the browser window the engine opens come to the front (Windows app).
    await window.__TAURI__?.core?.invoke("allow_foreground").catch(() => {});
    const response = await fetch("/api/update/open-release", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!response.ok) throw new Error();
    setMessage(`VizorPlay ${latest} download page opened in your browser.`);
  } catch {
    setMessage(`VizorPlay ${latest} is available at github.com/B03GHB4L1/ClipMaker/releases.`);
  }
};

// Called by the Windows desktop shell while it installs.
window.vizorplayUpdateStatus = (state, detail = "") => {
  if (!action) return;
  if (state === "downloading") setMessage(`Downloading VizorPlay ${latest}…`);
  else if (state === "installing") setMessage(`Installing VizorPlay ${latest}. It will reopen by itself.`);
  else if (state === "error") {
    setMessage(`The update did not install: ${detail}`);
    action.textContent = "Try again";
    action.disabled = false;
  }
};

const render = (status) => {
  latest = status.latest;
  setMessage(`VizorPlay ${latest} is available.`);
  if (status.install === "in-app") {
    action = actionButton("Update and restart", startInstall);
  } else if (status.install === "homebrew") {
    action = document.createElement("code");
    action.textContent = "brew upgrade vizorplay";
    setMessage(`VizorPlay ${latest} is available. To update, run`);
  } else {
    action = actionButton("Download", openReleasePage);
  }
  notice.replaceChildren(message, action);
  notice.hidden = false;
};

const checkForUpdate = async () => {
  try {
    const response = await fetch("/api/update");
    if (!response.ok) return;
    const { update } = await response.json();
    if (update?.available) render(update);
  } catch {
    // Offline or no engine: the notice simply stays hidden.
  }
};

if (footer) checkForUpdate();
