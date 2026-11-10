// Native Player Comparison: radar and zone charts (Plotly, bundled with the
// map component), Top 5 Moments tables and highlight reels cut server-side.
import { projectRequest } from "../../projects.js";

const el = (tag, attributes = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.filter(Boolean));
  return node;
};

let plotlyLoading = null;
const loadPlotly = () => {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  plotlyLoading ||= new Promise((resolve, reject) => {
    const script = el("script", { src: "/analysis-component/plotly-2.27.0.min.js" });
    script.onload = () => resolve(window.Plotly);
    script.onerror = () => { plotlyLoading = null; reject(new Error("Could not load the chart library.")); };
    document.head.append(script);
  });
  return plotlyLoading;
};

let uid = 0;

export async function renderComparison(panel, context) {
  const controls = { ...(context.state || {}) };
  const reels = { 1: {}, 2: {} };
  const id = `comparison-${++uid}`;
  let view = null;
  let request = 0;

  const filters = el("details", { class: "native-controls", open: true }, el("summary", { text: "Players" }));
  const filterBody = el("div", { class: "native-control-grid native-comparison-controls" });
  filters.append(filterBody);
  const message = el("p", { class: "native-inline-message", role: "status", hidden: true });
  const warning = el("p", { class: "native-inline-error native-warning", role: "alert", hidden: true });
  const radar = el("section", { class: "native-figure-section", "aria-label": "Performance radar" },
    el("h3", { text: "Performance Radar" }), el("div", { class: "native-figure", "data-figure": "0" }));
  const zones = el("section", { class: "native-figure-section", "aria-label": "Pitch zone activity" },
    el("h3", { text: "Pitch Zone Activity" }),
    el("div", { class: "native-figure-pair" }, el("div", { class: "native-figure", "data-figure": "1" }),
      el("div", { class: "native-figure", "data-figure": "2" })));
  const moments = el("section", { class: "native-figure-section", "aria-label": "Top 5 moments" },
    el("h3", { text: "Top 5 Moments" }), el("div", { class: "native-moments" }));
  panel.replaceChildren(filters, message, warning, radar, zones, moments);

  const change = (key, value) => {
    controls[key] = value;
    if (key.startsWith("team")) controls[`player${key.slice(-1)}`] = null;
    reels[1] = {}; reels[2] = {};
    context.save({ ...controls });
    load();
  };

  const field = (item) => {
    const fieldId = `${id}-${item.key}`;
    if (item.type === "segmented") {
      const group = el("div", { class: "native-segmented", role: "radiogroup", "aria-label": item.label });
      item.options.forEach((option, index) => {
        const input = el("input", { type: "radio", name: fieldId, value: option.value, id: `${fieldId}-${index}`, checked: option.value === item.value });
        input.addEventListener("change", () => change(item.key, option.value));
        group.append(el("label", { for: input.id }, input, el("span", { text: option.label })));
      });
      return el("div", { class: "native-field" }, el("span", { class: "native-field-label", text: item.label }), group);
    }
    const control = el("select", { id: fieldId });
    item.options.forEach((option) => control.append(el("option", { value: option.value, text: option.label, selected: option.value === item.value })));
    control.addEventListener("change", () => change(item.key, control.value));
    return el("div", { class: "native-field" }, el("label", { for: fieldId, class: "native-field-label", text: item.label }), control);
  };

  const drawFigures = async () => {
    const targets = panel.querySelectorAll("[data-figure]");
    if (!view.figures.length) { targets.forEach((target) => target.replaceChildren()); return; }
    const Plotly = await loadPlotly();
    await Promise.all(view.figures.map((item, index) => {
      const target = targets[index];
      return Plotly.react(target, item.figure.data, item.figure.layout, { ...item.config, responsive: true });
    }));
  };

  const generate = async (side) => {
    const reel = reels[side];
    Object.assign(reel, { busy: true, error: null, file: null });
    renderMoments();
    try {
      const { file } = await projectRequest(`/api/analysis/${context.view}/comparison/clip`, {
        project_id: context.projectId, controls: { ...controls, reel: side },
        before: view.clip_defaults.before, after: view.clip_defaults.after,
      });
      reel.file = file;
    } catch (error) {
      reel.error = error.message;
    } finally {
      reel.busy = false;
      renderMoments();
    }
  };

  const renderMoments = () => {
    const columns = view.moments.map((moment) => {
      const reel = reels[moment.reel];
      const heading = el("h4", { class: moment.reel === 1 ? "is-home" : "is-away", text: `${moment.player} · ${moment.role}` });
      if (moment.empty) return el("div", { class: "native-moment" }, heading, el("p", { class: "native-muted", text: moment.empty }));
      const table = el("table", { class: "native-table" },
        el("thead", {}, el("tr", {}, ...moment.columns.map((column) => el("th", { scope: "col", text: column })))),
        el("tbody", {}, ...moment.rows.map((row) => el("tr", {}, ...row.map((cell) => el("td", { text: String(cell) }))))));
      const actions = el("div", { class: "native-watch" });
      if (!view.has_video) {
        actions.append(el("p", { class: "native-muted", text: "Add the match video in Intake to generate a highlight reel." }));
      } else if (reel.busy) {
        actions.append(el("p", { class: "native-inline-message", role: "status", text: "Cutting clips..." }));
      } else if (reel.file) {
        actions.append(el("video", { controls: true, preload: "metadata", src: reel.file.url, "aria-label": `Top moments of ${moment.player}` }),
          el("div", { class: "native-actions" }, el("a", { class: "native-button", href: reel.file.url, download: reel.file.name, text: "Download reel" })));
      } else if (reel.error) {
        actions.append(el("p", { class: "native-inline-error", role: "alert", text: `Could not generate reel: ${reel.error}` }),
          el("button", { type: "button", class: "native-button", text: "Retry", onclick: () => generate(moment.reel) }));
      } else {
        actions.append(el("button", { type: "button", class: "native-button", text: "Show top moments", onclick: () => generate(moment.reel) }));
      }
      return el("div", { class: "native-moment" }, heading, el("div", { class: "native-table-wrap" }, table), actions);
    });
    moments.querySelector(".native-moments").replaceChildren(...columns);
  };

  const load = async () => {
    const ticket = ++request;
    panel.setAttribute("aria-busy", "true");
    try {
      const result = await projectRequest(`/api/analysis/${context.view}/comparison`, { project_id: context.projectId, controls });
      if (ticket !== request) return;
      view = result.view;
      Object.assign(controls, view.controls);
      filterBody.replaceChildren(...view.filters.map(field));
      const text = view.empty || view.notice;
      message.hidden = !text;
      message.textContent = text || "";
      warning.hidden = !view.warning;
      warning.textContent = view.warning || "";
      const hasFigures = view.figures.length > 0;
      radar.hidden = !hasFigures; zones.hidden = !hasFigures; moments.hidden = !view.moments.length;
      renderMoments();
      await drawFigures();
    } finally {
      if (ticket === request) panel.removeAttribute("aria-busy");
    }
  };

  await load();
  return () => panel.querySelectorAll("[data-figure]").forEach((target) => window.Plotly && window.Plotly.purge(target));
}
