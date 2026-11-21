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

  const mount = () => {
    document.querySelectorAll(".app-footer").forEach((footer) => {
      if (footer.querySelector("[data-theme-switch]")) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "theme-switch";
      button.dataset.themeSwitch = "";
      button.title = "Switch between following the computer, light and dark";
      button.addEventListener("click", () => set(CHOICES[(CHOICES.indexOf(choice) + 1) % CHOICES.length]));
      footer.append(button);
    });
    apply();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
