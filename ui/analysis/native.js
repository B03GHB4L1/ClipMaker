// Native analysis workspace shell (docs/ANALYSIS_MIGRATION_PLAN.md, Phase 1).
// Tabs whose native view is not built yet link to the classic workspace.
import { projectRequest, saveProject } from "../projects.js";

// Phase 2+ registers per-tab renderers here: slug -> async (panel, context) => {}.
export const renderers = {};

const element = (tag, attributes = {}, ...children) => {
  const node = document.createElement(tag);
  Object.entries(attributes).forEach(([key, value]) => {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  });
  node.append(...children);
  return node;
};

export async function startNativeWorkspace({ projectId, view, config, status, root }) {
  const tabs = config.views[view].tabs;
  const params = new URLSearchParams(location.search);
  let state = {};

  const setStatus = (text) => { status.textContent = text; };
  const classicUrl = (tab) => `/analysis.html?view=${view}&project=${encodeURIComponent(projectId)}&ui=classic${tab ? `&tab=${tab}` : ""}`;

  const showMessage = (kind, heading, text, action) => {
    root.replaceChildren(element("div", { class: `native-message native-${kind}`, role: kind === "error" ? "alert" : "status" },
      element("h2", { text: heading }), element("p", { text }), ...(action ? [action] : [])));
  };

  const load = async () => {
    root.setAttribute("aria-busy", "true");
    showMessage("loading", "Loading match data", "Preparing the analytical workspace...");
    setStatus("Loading match data...");
    try {
      const result = await projectRequest(`/api/analysis/summary?project=${encodeURIComponent(projectId)}`);
      state = result.analysis_state || {};
      render(result.summary);
      setStatus("Workspace ready");
    } catch (error) {
      setStatus("Setup needs attention");
      showMessage("error", "The workspace could not load", error.message,
        element("button", { type: "button", class: "native-retry", text: "Try again", onclick: load }));
    } finally {
      root.removeAttribute("aria-busy");
    }
  };

  const persist = (tab) => {
    state = { ...state, [view]: { ...(state[view] || {}), tab, controls: state[view]?.controls || {} } };
    // Save at once: the shared queue keeps writes ordered and its unload guard
    // covers pending saves, which a debounce timer would not.
    saveProject(projectId, { analysis_state: state }).catch(() => {});
  };

  const render = (summary) => {
    const known = new Set(tabs.map((tab) => tab.slug));
    const requested = params.get("tab");
    let active = known.has(requested) ? requested : known.has(state[view]?.tab) ? state[view].tab : tabs[0].slug;

    const heading = element("div", { class: "native-summary" },
      element("strong", { text: `${summary.home_team || "Home"} vs ${summary.away_team || "Away"}` }),
      element("span", { text: `${Number(summary.event_count || 0).toLocaleString()} events` }));
    const tablist = element("div", { class: "native-tabs", role: "tablist", "aria-label": config.views[view].label });
    const panel = element("section", { class: "native-panel", role: "tabpanel", tabindex: "0" });
    const buttons = tabs.map((tab) => element("button", {
      type: "button", role: "tab", id: `tab-${tab.slug}`, "aria-controls": "native-panel",
      "data-tab": tab.slug, text: tab.label, onclick: () => select(tab.slug, true),
    }));
    panel.id = "native-panel";
    tablist.append(...buttons);
    tablist.addEventListener("keydown", (event) => {
      const index = buttons.indexOf(document.activeElement);
      if (index < 0) return;
      const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: buttons.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      const target = buttons[(next + buttons.length) % buttons.length];
      target.focus();
      select(target.dataset.tab, true);
    });

    const select = async (slug, userAction = false) => {
      active = slug;
      buttons.forEach((button) => {
        const selected = button.dataset.tab === slug;
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
        // On narrow screens the strip scrolls; keep the active tab visible.
        if (selected) tablist.scrollLeft = Math.max(0, button.offsetLeft - tablist.offsetLeft - 12);
      });
      panel.setAttribute("aria-labelledby", `tab-${slug}`);
      const url = new URL(location.href);
      url.searchParams.set("tab", slug);
      history.replaceState(null, "", url);
      if (userAction) persist(slug);
      const tab = tabs.find((item) => item.slug === slug);
      const renderer = tab.native && renderers[slug];
      if (!renderer) {
        panel.replaceChildren(element("div", { class: "native-message native-empty", role: "status" },
          element("h2", { text: tab.label }),
          element("p", { text: "This view has not moved to the fast workspace yet." }),
          element("a", { class: "native-classic-link", href: classicUrl(slug), text: "Open in classic workspace" })));
        return;
      }
      panel.setAttribute("aria-busy", "true");
      try {
        await renderer(panel, { projectId, view, summary, state: state[view]?.controls?.[slug] || {} });
      } catch (error) {
        panel.replaceChildren(element("div", { class: "native-message native-error", role: "alert" },
          element("h2", { text: `${tab.label} could not load` }), element("p", { text: error.message })));
      } finally {
        panel.removeAttribute("aria-busy");
      }
    };

    root.replaceChildren(heading, tablist, panel);
    select(active);
  };

  await load();
}
