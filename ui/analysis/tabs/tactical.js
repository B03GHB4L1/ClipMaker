// Native Tactical Lab tabs. The server runs the classic tab code against a
// recorder (analysis_core.tactical) and returns its elements in order; this
// draws them and turns recorded controls back into inputs.
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

// Classic panels use inline-styled HTML built from match data; keep only
// layout tags and plain styles so event text can never inject markup.
const ALLOWED = new Set(["DIV", "SPAN", "B", "STRONG", "I", "EM", "BR", "P", "SUP", "SUB", "SMALL", "CODE", "UL", "LI", "H4", "H5", "H6"]);
const sanitize = (html) => {
  const source = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html").body.firstChild;
  const copy = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.textContent);
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const children = [...node.childNodes].map(copy).filter(Boolean);
    if (!ALLOWED.has(node.tagName)) return children.length ? (() => { const f = document.createDocumentFragment(); f.append(...children); return f; })() : null;
    const clean = document.createElement(node.tagName.toLowerCase());
    const style = node.getAttribute("style");
    if (style && !/url\s*\(|expression|@import|javascript:/i.test(style)) clean.setAttribute("style", style);
    clean.append(...children);
    return clean;
  };
  const out = document.createDocumentFragment();
  [...source.childNodes].map(copy).filter(Boolean).forEach((node) => out.append(node));
  return out;
};

// Plain markdown used by the classic tabs: headings, **bold** and `code`.
const markdown = (text) => {
  const block = el("div", { class: "native-markdown" });
  String(text).split(/\n{2,}/).forEach((paragraph) => {
    const heading = paragraph.match(/^(#{1,6})\s+(.*)$/s);
    const node = el(heading ? "h4" : "p");
    const body = heading ? heading[2] : paragraph;
    body.split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach((part) => {
      if (/^\*\*.+\*\*$/.test(part)) node.append(el("strong", { text: part.slice(2, -2) }));
      else if (/^`.+`$/.test(part)) node.append(el("code", { text: part.slice(1, -1) }));
      else if (part) node.append(document.createTextNode(part));
    });
    block.append(node);
  });
  return block;
};

let uid = 0;

export async function renderTactical(panel, context) {
  const controls = { ...(context.state || {}) };
  const media = { cut: {}, reel: {} };
  const id = `tactical-${++uid}`;
  let view = null;
  let request = 0;

  const scope = el("details", { class: "native-controls", open: true }, el("summary", { text: "Match and team" }));
  const scopeBody = el("div", { class: "native-control-grid" });
  scope.append(scopeBody);
  const body = el("div", { class: "native-tactical" });
  const clips = el("section", { class: "native-tactical-media", "aria-label": "Clips", hidden: true });
  panel.replaceChildren(scope, body, clips);

  const update = (changes) => {
    Object.assign(controls, changes);
    media.cut = {}; media.reel = {};
    context.save({ ...controls });
    load();
  };

  const renderScope = () => {
    const fields = [];
    const multi = el("input", { type: "checkbox", id: `${id}-multi`, checked: view.scope.multi });
    multi.addEventListener("change", () => update({ multi: multi.checked, matches: multi.checked ? view.scope.matches : [] }));
    fields.push(el("div", { class: "native-field" }, el("span", { class: "native-field-label", text: "Match source" }),
      el("label", { class: "native-check", for: multi.id }, multi, el("span", { text: "Analyze across matches" }))));
    if (view.scope.multi) {
      const list = el("fieldset", { class: "native-match-list" }, el("legend", { class: "native-field-label", text: "Select matches (1-20)" }));
      view.scope.match_options.forEach((option, index) => {
        const box = el("input", { type: "checkbox", id: `${id}-match-${index}`, value: option.value,
          checked: view.scope.matches.includes(option.value) });
        box.addEventListener("change", () => {
          const chosen = [...list.querySelectorAll("input:checked")].map((input) => input.value).slice(0, 20);
          update({ matches: chosen });
        });
        list.append(el("label", { class: "native-check", for: box.id }, box, el("span", { text: option.label })));
      });
      fields.push(list);
    }
    if (view.teams.length) {
      const team = el("select", { id: `${id}-team` });
      view.teams.forEach((name) => team.append(el("option", { value: name, text: name, selected: name === view.team })));
      team.addEventListener("change", () => update({ team: team.value }));
      fields.push(el("div", { class: "native-field" }, el("label", { for: team.id, class: "native-field-label", text: "Team" }), team));
    }
    scopeBody.replaceChildren(...fields);
  };

  const cut = async (action) => {
    const slot = action === "vl_reel" ? media.reel : media.cut;
    Object.assign(slot, { busy: true, error: null, file: null });
    renderMedia();
    try {
      const { file } = await projectRequest(`/api/analysis/${context.view}/${context.slug}/clip`, {
        project_id: context.projectId, controls, action,
      });
      slot.file = file;
    } catch (error) {
      slot.error = error.message;
    } finally {
      slot.busy = false;
      renderMedia();
    }
  };

  const renderMedia = () => {
    const blocks = [];
    for (const [slot, title] of [[media.cut, "Moment"], [media.reel, "Playlist Reel"]]) {
      if (slot.busy) blocks.push(el("p", { class: "native-inline-message", role: "status", text: `Cutting ${title.toLowerCase()}...` }));
      else if (slot.error) blocks.push(el("p", { class: "native-inline-error", role: "alert", text: `Could not cut ${title.toLowerCase()}: ${slot.error}` }));
      else if (slot.file) {
        blocks.push(el("div", { class: "native-watch" }, el("h4", { text: title }),
          el("video", { controls: true, preload: "metadata", src: slot.file.url, "aria-label": title }),
          el("div", { class: "native-actions" }, el("a", { class: "native-button", href: slot.file.url, download: slot.file.name, text: `Download ${title.toLowerCase()}` }))));
      }
    }
    clips.replaceChildren(...blocks);
    clips.hidden = !blocks.length;
  };

  const control = (element) => {
    const fieldId = `${id}-${element.key}`.replace(/\W+/g, "-");
    if (element.kind === "Slider") {
      const input = el("input", { type: "range", id: fieldId, min: String(element.min), max: String(element.max), step: "1", value: String(element.value) });
      const output = el("output", { for: fieldId, text: String(element.value) });
      input.addEventListener("input", () => { output.textContent = input.value; });
      input.addEventListener("change", () => update({ [element.key]: Number(input.value) }));
      return el("div", { class: "native-field native-slider" }, el("label", { for: fieldId, class: "native-field-label", text: element.label }), input, output);
    }
    const select = el("select", { id: fieldId });
    element.options.forEach((label, index) => select.append(el("option", { value: String(index), text: label,
      selected: JSON.stringify(element.values[index]) === JSON.stringify(element.value) })));
    select.addEventListener("change", () => update({ [element.key]: element.values[Number(select.value)] }));
    return el("div", { class: "native-field" }, el("label", { for: fieldId, class: "native-field-label", text: element.label }), select);
  };

  const renderElements = async () => {
    const nodes = [];
    const figures = [];
    let metrics = null;
    let controlsRow = null;
    let actions = null;
    for (const element of view.elements) {
      if (element.kind !== "Metric") metrics = null;
      if (element.kind !== "Slider" && element.kind !== "Selectbox") controlsRow = null;
      if (element.kind !== "Button") actions = null;
      switch (element.kind) {
        case "Subheader": nodes.push(el("h3", { class: "native-section-title", text: element.value })); break;
        case "Caption": nodes.push(el("p", { class: "native-muted", text: element.value })); break;
        case "Markdown": nodes.push(element.html ? el("div", { class: "native-html" }, sanitize(element.value)) : markdown(element.value)); break;
        case "Info": case "Success": nodes.push(el("p", { class: "native-inline-message native-info", role: "status", text: element.value })); break;
        case "Warning": case "Error": nodes.push(el("p", { class: "native-inline-error native-warning", role: "alert", text: element.value })); break;
        case "Metric": {
          if (!metrics) { metrics = el("div", { class: "native-stats native-metrics" }); nodes.push(metrics); }
          metrics.append(el("div", { class: "native-stat", title: element.help || "" },
            el("span", { class: "native-stat-label", text: element.label }),
            el("span", { class: "native-stat-values" }, el("b", { text: element.value }))));
          break;
        }
        case "plotly": {
          const target = el("div", { class: "native-figure" });
          figures.push([target, element]);
          nodes.push(target);
          break;
        }
        case "Dataframe":
          nodes.push(el("div", { class: "native-table-wrap" }, el("table", { class: "native-table" },
            el("thead", {}, el("tr", {}, ...element.columns.map((c) => el("th", { scope: "col", text: c })))),
            el("tbody", {}, ...element.rows.map((row) => el("tr", {}, ...row.map((cell) => el("td", { text: cell === null ? "" : String(cell) }))))))));
          break;
        case "Slider": case "Selectbox":
          if (!controlsRow) { controlsRow = el("div", { class: "native-control-grid native-tab-controls" }); nodes.push(controlsRow); }
          controlsRow.append(control(element));
          break;
        case "Button":
          if (!actions) { actions = el("div", { class: "native-actions" }); nodes.push(actions); }
          actions.append(el("button", { type: "button", class: "native-button", text: element.label,
            disabled: element.disabled, onclick: () => cut(element.key) }));
          break;
        default: break;
      }
    }
    body.replaceChildren(...nodes);
    if (figures.length) {
      const Plotly = await loadPlotly();
      await Promise.all(figures.map(([target, element]) =>
        Plotly.react(target, element.figure.data, element.figure.layout, { ...element.config, responsive: true })));
    }
  };

  const load = async () => {
    const ticket = ++request;
    panel.setAttribute("aria-busy", "true");
    try {
      const result = await projectRequest(`/api/analysis/${context.view}/${context.slug}`, { project_id: context.projectId, controls });
      if (ticket !== request) return;
      view = result.view;
      Object.assign(controls, { team: view.team, multi: view.scope.multi, matches: view.scope.matches });
      renderScope();
      if (view.empty) body.replaceChildren(el("p", { class: "native-inline-message", role: "status", text: view.empty }));
      else await renderElements();
      renderMedia();
    } finally {
      if (ticket === request) panel.removeAttribute("aria-busy");
    }
  };

  await load();
  return () => body.querySelectorAll(".native-figure").forEach((target) => window.Plotly && window.Plotly.purge(target));
}
