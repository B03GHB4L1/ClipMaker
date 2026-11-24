// Light or dark theme for every VizorPlay screen. Loaded as a plain (blocking)
// script in <head> so the page never flashes the wrong theme. The choice is
// "system" (follow the computer), "light" or "dark", kept per computer; the
// footer carries the switch. Pages listen for "vizorplay-theme" to redraw charts.
(() => {
  const KEY = "vizorplay-theme";
  const CHOICES = ["system", "light", "dark"];
  const LABELS = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const read = () => {
    try {
      const value = localStorage.getItem(KEY);
      return CHOICES.includes(value) ? value : "system";
    } catch {
      return "system";
    }
  };
  let choice = read();
  const resolve = () => (choice === "system" ? (media && media.matches ? "dark" : "light") : choice);
  let current = null;

  const apply = () => {
    const theme = resolve();
    const root = document.documentElement;
    root.dataset.theme = theme;
    root.dataset.themeChoice = choice;
    root.style.colorScheme = theme;
    document.querySelectorAll("[data-theme-switch]").forEach((button) => {
      button.textContent = LABELS[choice];
      button.setAttribute("aria-label", `${LABELS[choice]}. Change theme`);
    });
    if (theme !== current) {
      const first = current === null;
      current = theme;
      if (!first) window.dispatchEvent(new CustomEvent("vizorplay-theme", { detail: { theme } }));
    }
  };

  const set = (next) => {
    choice = CHOICES.includes(next) ? next : "system";
    try {
      localStorage.setItem(KEY, choice);
    } catch {
      // Private window or blocked storage: the theme still changes for this page.
    }
    apply();
  };

  window.vizorTheme = { get: resolve, choice: () => choice, set, isDark: () => resolve() === "dark" };
  apply();
  media?.addEventListener?.("change", () => { if (choice === "system") apply(); });
  // Another VizorPlay window changed the theme.
  window.addEventListener("storage", (event) => { if (event.key === KEY) { choice = read(); apply(); } });

  // Full screen for the whole window, next to the theme switch on every page. In the
  // desktop app the window itself goes full screen (src-tauri window_fullscreen, also
  // on F11, which the app window has no shortcut for); in a browser, the page does.
  const invoke = () => window.__TAURI__?.core?.invoke;
  let fullscreen = false;
  const showFullscreen = () => document.querySelectorAll("[data-fullscreen-switch]").forEach((button) => {
    button.textContent = fullscreen ? "Exit full screen" : "Full screen";
    button.setAttribute("aria-pressed", String(fullscreen));
    button.title = fullscreen ? "Leave full screen (F11)" : "Fill the whole screen (F11)";
  });
  const setFullscreen = async (full) => {
    try {
      if (invoke()) fullscreen = await invoke()("window_fullscreen", full === undefined ? {} : { full });
      else if (full && !document.fullscreenElement) await document.documentElement.requestFullscreen?.();
      else if (!full && document.fullscreenElement) await document.exitFullscreen?.();
    } catch {
      // The window stays as it is.
    }
    if (!invoke()) fullscreen = Boolean(document.fullscreenElement);
    showFullscreen();
  };
  document.addEventListener("fullscreenchange", () => { if (!invoke()) { fullscreen = Boolean(document.fullscreenElement); showFullscreen(); } });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "F11" || event.repeat || !invoke()) return; // a browser has its own F11
    event.preventDefault();
    setFullscreen(!fullscreen);
  });

  const mount = () => {
    document.querySelectorAll(".app-footer").forEach((footer) => {
      if (!footer.querySelector("[data-fullscreen-switch]") && (invoke() || document.fullscreenEnabled)) {
        const full = document.createElement("button");
        full.type = "button";
        full.className = "theme-switch fullscreen-switch";
        full.dataset.fullscreenSwitch = "";
        full.addEventListener("click", () => setFullscreen(!fullscreen));
        footer.append(full);
      }
      if (footer.querySelector("[data-theme-switch]")) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "theme-switch";
      button.dataset.themeSwitch = "";
      button.title = "Switch between following the computer, light and dark";
      button.addEventListener("click", () => set(CHOICES[(CHOICES.indexOf(choice) + 1) % CHOICES.length]));
      const full = footer.querySelector("[data-fullscreen-switch]");
      if (full) full.before(button);
      else footer.append(button);
    });
    apply();
    showFullscreen();
    if (invoke()) setFullscreen(); // the window may already be full screen from another page
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
