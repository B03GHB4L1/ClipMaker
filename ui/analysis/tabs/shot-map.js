// Native Shot Map tab. Data comes from POST /api/analysis/analyst/shot-map,
// which runs the same analysis_core code as the classic workspace.
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

// "[GOAL] GOAL" -> "GOAL": the bracketed token is a classic-page icon code.
const badgeText = (label) => String(label || "").replace(/^\[[A-Z]+\]\s*/, "");

let uid = 0;

export async function renderShotMap(panel, context) {
  const saved = context.state || {};
  const controls = {
    mode: saved.mode === "penalties" ? "penalties" : "normal",
    team: saved.team || null, player: saved.player || null, zone: saved.zone || "",
    selected: Number.isInteger(saved.selected) ? saved.selected : null,
  };
  const clip = { before: null, after: null, file: null, error: null, key: null, busy: false };
  let view = null;
  let request = 0;
  const id = `shot-${++uid}`;

  // Persistent layout: hosts keep their iframes between updates.
  const filters = el("details", { class: "native-controls", open: true }, el("summary", { text: "Filters" }));
  const filterBody = el("div", { class: "native-control-grid" });
  filters.append(filterBody);
  const stats = el("div", { class: "native-stats", role: "group", "aria-label": "Shot totals" });
  const message = el("p", { class: "native-inline-message", role: "status", hidden: true });
  const goalframeHolder = el("div", { class: "native-goalframe", hidden: true });
  const mapHolder = el("div", { class: "native-map" });
  const legend = el("p", { class: "native-legend" });
  const pickerRow = el("div", { class: "native-picker" });
  const detail = el("section", { class: "native-detail", "aria-label": "Selected shot", hidden: true });
  panel.replaceChildren(filters, stats, message, goalframeHolder, mapHolder, legend, pickerRow, detail);

  const onPick = (value) => {
    const picked = Array.isArray(value) ? value[0] : value;
    if (Number.isInteger(picked) && picked !== controls.selected) select(picked);
  };
  const goalframe = new ComponentHost(goalframeHolder, { title: "Selected shot placement", onValue: () => {} });
  const map = new ComponentHost(mapHolder, { title: "Shot map", onValue: onPick });

  const save = () => context.save({ ...controls });

  const select = (value) => {
    controls.selected = value;
    clip.file = null; clip.error = null; clip.key = null;
    save();
    load();
  };
  const changeFilter = (key, value) => {
    controls[key] = value;
    controls.selected = null;
    clip.file = null; clip.error = null; clip.key = null;
    if (key === "mode") { controls.team = null; controls.player = null; controls.zone = ""; }
    if (key === "team") controls.player = null;
    save();
    load();
  };

  const radioGroup = (label, name, options, current, onChange) => {
    const group = el("div", { class: "native-segmented", role: "radiogroup", "aria-label": label });
    options.forEach(({ value, text }) => {
      const input = el("input", { type: "radio", name, value, id: `${id}-${name}-${value}`.replace(/\W+/g, "-"), checked: value === current });
      input.addEventListener("change", () => onChange(value));
      group.append(el("label", { for: input.id }, input, el("span", { text })));
    });
    return el("div", { class: "native-field" }, el("span", { class: "native-field-label", text: label }), group);
  };
  const selectField = (label, options, current, onChange) => {
    const select = el("select", { id: `${id}-${label}`.replace(/\W+/g, "-") });
    options.forEach(({ value, text }) => select.append(el("option", { value, text, selected: value === current })));
    select.addEventListener("change", () => onChange(select.value));
    return el("div", { class: "native-field" }, el("label", { for: select.id, class: "native-field-label", text: label }), select);
  };

  const renderFilters = () => {
    const fields = [];
    if (view.has_pso) {
      fields.push(radioGroup("Mode", `${id}-mode`, [{ value: "normal", text: "Normal" }, { value: "penalties", text: "Penalty Shootout" }],
        view.mode, (value) => changeFilter("mode", value)));
    }
    if (view.mode === "normal" && view.controls) {
      const c = view.controls;
      fields.push(radioGroup("Team", `${id}-team`, c.teams.map((t) => ({ value: t, text: t })), c.team, (value) => changeFilter("team", value)));
      fields.push(selectField("Player", c.players.map((p) => ({ value: p, text: p })), c.player, (value) => changeFilter("player", value)));
      fields.push(selectField("Pitch zone", c.zones.map((z) => ({ value: z.value, text: z.label })), c.zone, (value) => changeFilter("zone", value)));
    }
    filterBody.replaceChildren(...fields);
    filters.hidden = !fields.length;
  };

  const renderStats = () => {
    stats.hidden = !view.stats || view.mode !== "normal";
    if (stats.hidden) return;
    const { home, away, share } = view.stats;
    const cell = (label, homeValue, awayValue) => el("div", { class: "native-stat" },
      el("span", { class: "native-stat-label", text: label }),
      el("span", { class: "native-stat-values" }, el("b", { class: "is-home", text: String(homeValue) }),
        el("span", { "aria-hidden": "true", text: "–" }), el("b", { class: "is-away", text: String(awayValue) })));
    const cells = [];
    if (share) {
      cells.push(el("div", { class: "native-stat native-share" },
        el("span", { class: "native-stat-label", text: "Shot share" }),
        el("div", { class: "native-share-bar", role: "img", "aria-label": `Home ${share.home}%, away ${share.away}%` },
          el("span", { style: `width:${share.home}%` })),
        el("span", { class: "native-stat-values" }, el("b", { class: "is-home", text: `${share.home}%` }),
          el("b", { class: "is-away", text: `${share.away}%` }))));
    }
    cells.push(cell("Shots", home.shots, away.shots), cell("On target", home.on_target, away.on_target), cell("Goals", home.goals, away.goals));
    stats.replaceChildren(...cells);
  };

  const renderPicker = () => {
    const picker = el("select", { id: `${id}-pick`, "aria-label": view.mode === "penalties" ? "Select a penalty" : "Select a shot" });
    picker.append(el("option", { value: "", text: view.placeholder }));
    view.shots.forEach((shot) => picker.append(el("option", { value: String(shot.id), text: shot.label, selected: shot.id === controls.selected })));
    picker.addEventListener("change", () => (picker.value === "" ? select(null) : onPick(Number(picker.value))));
    const clear = controls.selected === null ? null
      : el("button", { type: "button", class: "native-button native-secondary", text: "Clear selection", onclick: () => select(null) });
    pickerRow.replaceChildren(picker, clear);
  };

  const clipKey = () => `${controls.mode}:${controls.selected}:${clip.before}:${clip.after}`;

  const cutClip = async () => {
    const key = clipKey();
    clip.busy = true; clip.error = null; clip.key = key;
    renderDetail();
    try {
      const { file } = await projectRequest(`/api/analysis/${context.view}/shot-map/clip`, {
        project_id: context.projectId, controls: { mode: controls.mode, selected: controls.selected },
        before: clip.before, after: clip.after,
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
    const shot = view && view.selected;
    detail.hidden = !shot;
    if (!shot) { detail.replaceChildren(); return; }
    const info = el("div", { class: "native-shot-panel" },
      el("h3", { class: shot.is_home ? "is-home" : "is-away", text: shot.player }),
      el("p", { class: "native-muted", text: `${shot.team} · ${shot.time}` }),
      el("span", { class: `native-badge native-badge-${shot.type}`, text: badgeText(shot.badge) }),
      el("dl", {}, el("dt", { text: "Qualifier" }), el("dd", { text: shot.qualifiers.join(" · ") || "—" })));
    const watch = el("div", { class: "native-watch" },
      el("p", { class: "native-clip-label", text: `Clip · ${shot.player} · ${shot.time}` }),
      el("div", { class: "native-slider-row" }, slider("Before (s)", "before"), slider("After (s)", "after")));
    if (clip.busy) {
      watch.append(el("p", { class: "native-inline-message", role: "status", text: "Cutting clip..." }));
    } else if (clip.file && clip.key === clipKey()) {
      const video = el("video", { controls: true, preload: "metadata", src: clip.file.url, "aria-label": `Clip of ${shot.player}` });
      watch.append(video,
        el("div", { class: "native-actions" },
          el("a", { class: "native-button", href: clip.file.url, download: clip.file.name, text: "Download clip" }),
          el("button", { type: "button", class: "native-button native-secondary", text: "Clear preview", onclick: () => { clip.file = null; clip.key = null; renderDetail(); } })));
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
      const result = await projectRequest(`/api/analysis/${context.view}/shot-map`, { project_id: context.projectId, controls });
      if (ticket !== request) return; // A newer request superseded this one.
      view = result.view;
      if (clip.before === null) { clip.before = view.clip_defaults.before; clip.after = view.clip_defaults.after; }
      // Server-validated values replace anything stale (e.g. a removed player).
      if (view.controls) Object.assign(controls, { team: view.controls.team, player: view.controls.player, zone: view.controls.zone });
      controls.mode = view.mode;
      controls.selected = view.selected ? view.selected.id : null;
      renderFilters();
      renderStats();
      message.hidden = !view.empty;
      message.textContent = view.empty || "";
      const showMap = !view.empty;
      mapHolder.hidden = !showMap; legend.hidden = !showMap; pickerRow.hidden = !showMap;
      if (showMap) {
        legend.textContent = view.legend;
        map.render(view.map);
        renderPicker();
      }
      goalframeHolder.hidden = !view.goalframe;
      if (view.goalframe) goalframe.render(view.goalframe);
      renderDetail();
    } finally {
      if (ticket === request) panel.removeAttribute("aria-busy");
    }
  };

  await load();
  return () => { goalframe.destroy(); map.destroy(); };
}
