// Renders any map-style Analyst tab from the server's view description
// (app/analysis_core/views.py): filters, stats, map components, picker,
// selected-event details and a Watch panel that cuts clips server-side.
import { projectRequest } from "../../projects.js";
import { ComponentHost } from "../component-host.js";

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

let uid = 0;

export function eventTab(slug, title) {
  return async function render(panel, context) {
    const controls = { ...(context.state || {}) };
    const clip = { before: null, after: null, file: null, error: null, key: null, busy: false };
    const id = `${slug}-${++uid}`;
    let view = null;
    let request = 0;

    const filters = el("details", { class: "native-controls", open: true }, el("summary", { text: "Filters" }));
    const filterBody = el("div", { class: "native-control-grid" });
    filters.append(filterBody);
    const stats = el("div", { class: "native-stats", role: "group", "aria-label": `${title} totals` });
    const message = el("p", { class: "native-inline-message", role: "status", hidden: true });
    const componentsBox = el("div", { class: "native-components" });
    const legend = el("p", { class: "native-legend" });
    const pickerRow = el("div", { class: "native-picker" });
    const detail = el("section", { class: "native-detail", "aria-label": "Selected event", hidden: true });
    panel.replaceChildren(filters, stats, message, componentsBox, legend, pickerRow, detail);

    const resetClip = () => Object.assign(clip, { file: null, error: null, key: null, busy: false });
    const save = () => context.save({ ...controls });

    const select = (value) => {
      controls.selected = value;
      resetClip();
      save();
      load();
    };
    const onPick = (value) => {
      const picked = Array.isArray(value) ? value[0] : value;
      if (Number.isInteger(picked) && picked !== controls.selected) select(picked);
    };
    const changeFilter = (key, value) => {
      controls[key] = value;
      controls.selected = null; // Like the classic tabs: new filters clear the selection.
      resetClip();
      save();
      load();
    };

    const field = (item) => {
      const fieldId = `${id}-${item.key}`;
      if (item.type === "segmented") {
        const group = el("div", { class: "native-segmented", role: "radiogroup", "aria-label": item.label });
        item.options.forEach((option, index) => {
          const input = el("input", { type: "radio", name: fieldId, value: option.value, id: `${fieldId}-${index}`,
            checked: option.value === item.value });
          input.addEventListener("change", () => changeFilter(item.key, option.value));
          group.append(el("label", { for: input.id }, input, el("span", { text: option.label })));
        });
        return el("div", { class: "native-field" }, el("span", { class: "native-field-label", text: item.label }), group);
      }
      const control = el("select", { id: fieldId });
      item.options.forEach((option) => control.append(el("option", { value: option.value, text: option.label, selected: option.value === item.value })));
      control.addEventListener("change", () => changeFilter(item.key, control.value));
      return el("div", { class: "native-field" }, el("label", { for: fieldId, class: "native-field-label", text: item.label }), control);
    };

    const renderStats = () => {
      const cells = [];
      if (view.share) {
        cells.push(el("div", { class: "native-stat native-share" },
          el("span", { class: "native-stat-label", text: "Shot share" }),
          el("div", { class: "native-share-bar", role: "img", "aria-label": `Home ${view.share.home}%, away ${view.share.away}%` },
            el("span", { style: `width:${view.share.home}%` })),
          el("span", { class: "native-stat-values" }, el("b", { class: "is-home", text: `${view.share.home}%` }),
            el("b", { class: "is-away", text: `${view.share.away}%` }))));
      }
      (view.stats || []).forEach((cell) => cells.push(el("div", { class: "native-stat" },
        el("span", { class: "native-stat-label", text: cell.label }),
        el("span", { class: "native-stat-values" }, el("b", { class: "is-home", text: String(cell.home) }),
          ...("away" in cell ? [el("span", { "aria-hidden": "true", text: "–" }), el("b", { class: "is-away", text: String(cell.away) })] : [])))));
      stats.replaceChildren(...cells);
      stats.hidden = !cells.length;
    };

    // Detail views ("aux") always sit above clickable maps. Separate, stable
    // containers per role mean an iframe is never moved (moving reloads it).
    const boxes = { aux: el("div", { class: "native-aux-box" }), map: el("div", { class: "native-map-box" }) };
    componentsBox.append(boxes.aux, boxes.map);
    const pools = { aux: [], map: [] };
    const renderComponents = () => {
      for (const role of ["aux", "map"]) {
        const wanted = (view.components || []).filter((component) => component.role === role);
        const pool = pools[role];
        while (pool.length > wanted.length) {
          const entry = pool.pop();
          entry.host.destroy();
          entry.holder.remove();
        }
        wanted.forEach((component, index) => {
          if (!pool[index]) {
            const holder = el("div", { class: `native-component native-${role}` });
            boxes[role].append(holder);
            pool[index] = { holder, host: new ComponentHost(holder, {
              title: role === "map" ? `${title} map` : `${title} detail`, onValue: role === "map" ? onPick : () => {},
            }) };
          }
          pool[index].host.render(component.args);
        });
      }
    };

    const renderPicker = () => {
      if (!view.picker) { pickerRow.replaceChildren(); pickerRow.hidden = true; return; }
      pickerRow.hidden = false;
      const choice = el("select", { id: `${id}-pick`, "aria-label": view.picker.label });
      choice.append(el("option", { value: "", text: view.picker.placeholder }));
      view.picker.items.forEach((item) => choice.append(el("option", { value: String(item.id), text: item.label, selected: item.id === controls.selected })));
      choice.addEventListener("change", () => (choice.value === "" ? select(null) : onPick(Number(choice.value))));
      const clear = controls.selected === null || controls.selected === undefined ? null
        : el("button", { type: "button", class: "native-button native-secondary", text: "Clear selection", onclick: () => select(null) });
      pickerRow.replaceChildren(choice, clear);
    };

    const clipKey = () => `${controls.selected}:${clip.before}:${clip.after}`;
    const cutClip = async () => {
      const key = clipKey();
      Object.assign(clip, { busy: true, error: null, key });
      renderDetail();
      try {
        const { file } = await projectRequest(`/api/analysis/${context.view}/${slug}/clip`, {
          project_id: context.projectId, controls, before: clip.before, after: clip.after,
        });
        if (clip.key === key) clip.file = file;
      } catch (error) {
        if (clip.key === key) clip.error = error.message;
      } finally {
        if (clip.key === key) { clip.busy = false; renderDetail(); }
      }
    };

    const slider = (label, key) => {
      const input = el("input", { type: "range", min: "0", max: "60", step: "1", value: String(clip[key]), id: `${id}-${key}` });
      const output = el("output", { for: input.id, text: `${clip[key]}s` });
      input.addEventListener("input", () => { output.textContent = `${input.value}s`; });
      input.addEventListener("change", () => {
        clip[key] = Number(input.value);
        // Like the classic panel: a showing clip is re-cut for new buffers.
        if (clip.file || clip.error) cutClip(); else renderDetail();
      });
      return el("div", { class: "native-field native-slider" }, el("label", { for: input.id, class: "native-field-label", text: label }), input, output);
    };

    const renderDetail = () => {
      const item = view && view.selected;
      detail.hidden = !item;
      if (!item) { detail.replaceChildren(); return; }
      const info = el("div", { class: "native-shot-panel" },
        el("h3", { class: item.is_home ? "is-home" : "is-away", text: item.title }),
        el("p", { class: "native-muted", text: item.subtitle }),
        el("div", { class: "native-badges" }, ...item.badges.map((b) => el("span", { class: `native-badge native-tone-${b.tone}`, text: b.text }))),
        el("dl", {}, ...item.fields.flatMap((f) => [el("dt", { text: f.label }), el("dd", { text: String(f.value) })])));
      const watch = el("div", { class: "native-watch" },
        el("p", { class: "native-clip-label", text: `Clip · ${item.title} · ${item.subtitle.split(" · ").pop()}` }),
        el("div", { class: "native-slider-row" }, slider("Before (s)", "before"), slider("After (s)", "after")));
      if (clip.busy) {
        watch.append(el("p", { class: "native-inline-message", role: "status", text: "Cutting clip..." }));
      } else if (clip.file && clip.key === clipKey()) {
        watch.append(el("video", { controls: true, preload: "metadata", src: clip.file.url, "aria-label": `Clip of ${item.title}` }),
          el("div", { class: "native-actions" },
            el("a", { class: "native-button", href: clip.file.url, download: clip.file.name, text: "Download clip" }),
            el("button", { type: "button", class: "native-button native-secondary", text: "Clear preview", onclick: () => { resetClip(); renderDetail(); } })));
      } else if (clip.error) {
        watch.append(el("p", { class: "native-inline-error", role: "alert", text: `Could not cut clip: ${clip.error}` }),
          el("button", { type: "button", class: "native-button", text: "Retry", onclick: cutClip }));
      } else {
        watch.append(el("button", { type: "button", class: "native-button", text: "Watch", onclick: cutClip }));
      }
      detail.replaceChildren(info, watch);
    };

    const load = async () => {
      const ticket = ++request;
      panel.setAttribute("aria-busy", "true");
      try {
        const result = await projectRequest(`/api/analysis/${context.view}/${slug}`, { project_id: context.projectId, controls });
        if (ticket !== request) return; // A newer request superseded this one.
        view = result.view;
        if (clip.before === null) Object.assign(clip, { before: view.clip_defaults.before, after: view.clip_defaults.after });
        // Server-validated values replace stale ones (e.g. a player missing from a new team).
        Object.assign(controls, view.controls);
        filterBody.replaceChildren(...view.filters.map(field));
        filters.hidden = !view.filters.length;
        renderStats();
        const text = view.empty || view.notice;
        message.hidden = !text;
        message.textContent = text || "";
        message.classList.toggle("native-notice", Boolean(view.notice));
        renderComponents();
        legend.hidden = !view.legend;
        legend.textContent = view.legend || "";
        renderPicker();
        renderDetail();
      } finally {
        if (ticket === request) panel.removeAttribute("aria-busy");
      }
    };

    await load();
    return () => [...pools.aux, ...pools.map].forEach((entry) => entry.host.destroy());
  };
}
