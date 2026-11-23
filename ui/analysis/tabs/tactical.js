// Native Tactical Lab tabs. The server runs the classic tab code against a
// recorder (analysis_core.tactical) and returns its elements in order; this
// draws them and turns recorded controls back into inputs.
import { projectRequest } from "../../projects.js";
import { saveClipButton, plotlyConfig } from "../../save-clip.js";

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

// Tabs whose single pitch map sits beside its controls and stats, not under them.
const SIDE_BY_SIDE_TABS = new Set(["defensive-transitions", "attacking-transitions"]);

const isPitch = (figure) => figure.layout?.yaxis?.scaleanchor === "x";

// Pitch maps size from their width so the pitch fills the plot instead of sitting
// small in a wide strip. On narrow screens the legend moves under the pitch.
const NARROW_PITCH = 640;

const pitchLayout = (target, figure) => {
  const { layout } = figure;
  const narrow = target.clientWidth < NARROW_PITCH;
  const named = new Set(figure.data.filter((trace) => trace.name && trace.showlegend !== false).map((trace) => trace.name));
  const hasLegend = layout.showlegend !== false && named.size > 1;
  const margin = { l: 80, r: 80, t: 100, b: 80, ...layout.margin };
  // Maps with an "ATTACK ->" label above the pitch get extra room for it, never a smaller pitch.
  const labelRoom = (layout.annotations || []).some((note) => note.text === "ATTACK ->") ? 26 : 0;
  const adjusted = {
    ...layout,
    // Spare room goes to the page colour around the pitch, never to stretched grass.
    xaxis: { ...layout.xaxis, constrain: "domain" },
    yaxis: { ...layout.yaxis, constrain: "domain" },
  };
  let legendWidth = hasLegend ? 150 : 0;
  if (narrow) {
    legendWidth = 0;
    const rows = hasLegend ? Math.ceil(named.size / 2) : 0;
    Object.assign(adjusted, {
      margin: { ...margin, l: 8, r: 8, t: 64 + labelRoom, b: 24 + rows * 22 },
      legend: { ...layout.legend, orientation: "h", x: 0, xanchor: "left", y: -0.04, yanchor: "top" },
      title: layout.title && { ...layout.title, font: { ...layout.title.font, size: 13 } },
      // The hover hint does not apply to touch, and it runs off a phone screen.
      annotations: (layout.annotations || []).filter((note) => !(note.yref === "paper" && note.y < 0)),
    });
  }
  const used = adjusted.margin || margin;
  const span = (axis) => Math.abs((axis?.range?.[1] ?? 100) - (axis?.range?.[0] ?? 0)) || 100;
  const ratio = (layout.yaxis.scaleratio || 1) * span(layout.yaxis) / span(layout.xaxis);
  const plotWidth = Math.max(160, target.clientWidth - (used.l ?? 80) - (used.r ?? 80) - legendWidth);
  const natural = plotWidth * ratio + (used.t ?? 100) + (used.b ?? 80);
  // Capped so the whole pitch fits the window.
  adjusted.height = Math.round(Math.min(Math.max(natural, (narrow ? 240 : 360) + labelRoom), Math.max(420, window.innerHeight - 120) + labelRoom));
  return adjusted;
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
  let resizeWatch = null;
  // Video Lab: which ten-moment page is showing, per playlist (the Moment control's key).
  const momentPages = {};
  const MOMENTS_PER_PAGE = 10;
  // Video Lab reel: the moments ticked in the list (saved per playlist), and the
  // pieces that show how many are ticked, redrawn without reloading the tab.
  const reel = { key: null, rows: [], refreshers: [] };
  const reelPicks = () => {
    const known = new Set(reel.rows.map((row) => row.pick));
    return (Array.isArray(controls[reel.key]) ? controls[reel.key] : []).filter((pick) => known.has(pick));
  };
  const setReelPicks = (picks) => {
    controls[reel.key] = picks;
    context.save({ ...controls });
    reel.refreshers.forEach((refresh) => refresh());
  };
  const clipSeconds = () => Number(controls.vl_before ?? reel.before ?? 8) + Number(controls.vl_after ?? reel.after ?? 14);
  const formatLength = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;

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
    Object.assign(slot, { busy: true, error: null, file: null, picks: action === "vl_reel" ? JSON.stringify(reelPicks()) : null });
    renderMedia();
    try {
      const { file } = await projectRequest(`/api/analysis/${context.view}/${context.slug}/clip`, {
        project_id: context.projectId, match_id: context.matchId, controls, action,
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
        const stale = slot === media.reel && el("p", { class: "native-inline-message native-reel-stale", role: "status", hidden: true,
          text: "Your reel picks have changed since this reel was built. Build it again to include them." });
        if (stale) {
          const check = () => { stale.hidden = slot.picks === JSON.stringify(reelPicks()); };
          reel.refreshers.push(check);
          check();
        }
        blocks.push(el("div", { class: "native-watch" }, el("h4", { text: title }),
          el("video", { controls: true, preload: "metadata", src: slot.file.url, "aria-label": title }),
          ...(stale ? [stale] : []),
          el("div", { class: "native-actions" }, saveClipButton(slot.file, title === "Moment" ? "Clip" : "Reel"))));
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

  // Video Lab's ranked moments as a list. Clicking a row picks it for preview and
  // Cut Moment; its tick box adds it to the reel. Ten at a time.
  const momentList = (element, select) => {
    const rows = element.rows;
    const key = select ? select.key : "moments";
    const chosen = select ? select.values.findIndex((value) => JSON.stringify(value) === JSON.stringify(select.value)) : -1;
    const pages = Math.max(1, Math.ceil(rows.length / MOMENTS_PER_PAGE));
    if (momentPages[key] === undefined) momentPages[key] = Math.floor(Math.max(chosen, 0) / MOMENTS_PER_PAGE);
    momentPages[key] = Math.min(momentPages[key], pages - 1);
    const section = el("section", { class: "native-moment-list", "aria-label": "Moments" });
    const canPick = Boolean(reel.key);

    const toggle = (pick, on) => {
      const picks = reelPicks().filter((value) => value !== pick);
      setReelPicks(on ? [...picks, pick] : picks);
    };

    const reelBar = () => {
      const picks = reelPicks();
      const count = picks.length;
      const summary = el("p", { class: "native-reel-summary", role: "status", "aria-live": "polite" },
        el("strong", { text: "Reel" }),
        count
          ? el("span", { text: `${count} moment${count === 1 ? "" : "s"} · about ${formatLength(count * clipSeconds())} · plays in match order` })
          : el("span", { class: "native-muted", text: "Tick moments to add them to the reel" }));
      const top = Math.min(5, rows.length);
      const actions = el("div", { class: "native-reel-actions" },
        el("button", { type: "button", class: "text-button", text: `Add top ${top}`,
          disabled: rows.slice(0, top).every((row) => picks.includes(row.pick)),
          onclick: () => setReelPicks([...new Set([...picks, ...rows.slice(0, top).map((row) => row.pick)])]) }),
        el("button", { type: "button", class: "text-button", text: "Clear", disabled: !count, onclick: () => setReelPicks([]) }));
      return el("div", { class: "native-reel-bar" }, summary, actions);
    };

    const draw = () => {
      const picks = new Set(reelPicks());
      const first = momentPages[key] * MOMENTS_PER_PAGE;
      const head = el("div", { class: `native-moment-line native-moment-head${canPick ? " has-reel" : ""}`, "aria-hidden": "true" },
        ...(canPick ? [el("span", { class: "native-reel-head", text: "Reel" })] : []),
        el("div", { class: "native-moment-row" }, ...[["#", "native-moment-rank"], ["Time", ""], ["Player", "native-moment-player"],
          ["Moment", "native-moment-what"], ["Score", "native-moment-score"]].map(([text, className]) => el("span", { class: className, text }))));
      const list = el("ol", { class: "native-moment-rows", start: String(first + 1) });
      rows.slice(first, first + MOMENTS_PER_PAGE).forEach((row, offset) => {
        const index = first + offset;
        const described = `Moment ${index + 1}: ${row.time}, ${row.player}, ${row.moment}, score ${row.score.toFixed(2)}`;
        const button = el("button", { type: "button", class: "native-moment-row", "aria-pressed": String(index === chosen),
          "aria-label": described, title: "Preview this moment",
          onclick: () => { if (select && index !== chosen) update({ [select.key]: select.values[index] }); } },
          el("span", { class: "native-moment-rank", text: String(index + 1) }), el("span", { text: row.time }),
          el("span", { class: "native-moment-player", text: row.player }), el("span", { class: "native-moment-what", text: row.moment }),
          el("span", { class: "native-moment-score", text: row.score.toFixed(2) }));
        const picked = picks.has(row.pick);
        const line = el("li", { class: `native-moment-line${canPick ? " has-reel" : ""}${picked ? " is-in-reel" : ""}` });
        if (canPick) {
          const box = el("input", { type: "checkbox", checked: picked, "aria-label": `Add moment ${index + 1} to the reel` });
          box.addEventListener("change", () => toggle(row.pick, box.checked));
          line.append(el("label", { class: "native-reel-check", title: picked ? "Remove from the reel" : "Add to the reel" }, box));
        }
        line.append(button);
        list.append(line);
      });
      const pager = el("div", { class: "native-pager", role: "group", "aria-label": "Moment pages" });
      if (pages > 1) {
        for (let page = 0; page < pages; page += 1) {
          const label = `${page * MOMENTS_PER_PAGE + 1}–${Math.min(rows.length, (page + 1) * MOMENTS_PER_PAGE)}`;
          const inReel = rows.slice(page * MOMENTS_PER_PAGE, (page + 1) * MOMENTS_PER_PAGE).filter((row) => picks.has(row.pick)).length;
          pager.append(el("button", { type: "button", class: inReel ? "has-picks" : "", text: label,
            "aria-pressed": String(page === momentPages[key]),
            "aria-label": `Show moments ${label}${inReel ? `, ${inReel} in the reel` : ""}`,
            onclick: () => { momentPages[key] = page; draw(); } }));
        }
      }
      pager.append(el("span", { class: "native-muted", text: `${rows.length} moment${rows.length === 1 ? "" : "s"}` }));
      section.replaceChildren(pager, ...(canPick ? [reelBar()] : []), head, list);
    };
    if (canPick) reel.refreshers.push(() => {
      // Keep focus on the control the user just used.
      const focused = section.contains(document.activeElement) ? document.activeElement.getAttribute("aria-label") : null;
      draw();
      if (focused) section.querySelector(`[aria-label="${CSS.escape(focused)}"]`)?.focus();
    });
    draw();
    return section;
  };

  const renderElements = async () => {
    const momentSelect = view.elements.find((element) => element.kind === "Selectbox" && /^vl_selected_moment_/.test(element.key || ""));
    const momentRows = view.elements.find((element) => element.kind === "MomentList");
    reel.key = momentSelect && momentRows ? momentSelect.key.replace("vl_selected_moment_", "vl_reel_moments_") : null;
    reel.rows = momentRows ? momentRows.rows : [];
    reel.refreshers = [];
    for (const element of view.elements) {
      if (element.kind === "Slider" && element.key === "vl_before") reel.before = element.value;
      if (element.kind === "Slider" && element.key === "vl_after") reel.after = element.value;
    }
    const cutReady = !view.elements.some((element) => element.kind === "Button" && element.key === "vl_cut" && element.disabled);
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
        case "Markdown":
          if (!String(element.value).trim()) break;
          nodes.push(element.html ? el("div", { class: "native-html" }, sanitize(element.value)) : markdown(element.value)); break;
        case "MomentList": nodes.push(momentList(element, momentSelect)); break;
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
          if (element === momentSelect) break; // Picked from the moment list instead.
          if (!controlsRow) { controlsRow = el("div", { class: "native-control-grid native-tab-controls" }); nodes.push(controlsRow); }
          controlsRow.append(control(element));
          break;
        case "Button":
          if (!actions) { actions = el("div", { class: "native-actions" }); nodes.push(actions); }
          if (element.key === "vl_reel" && reel.key) {
            // Enabled once moments are ticked (and the footage is ready, as for Cut Moment).
            const build = el("button", { type: "button", class: "native-button", onclick: () => cut(element.key) });
            const refresh = () => {
              const count = reelPicks().length;
              build.textContent = count ? `Build reel · ${count}` : "Build reel";
              build.disabled = !count || !cutReady;
              build.title = count ? "" : "Tick moments in the list to add them to the reel";
            };
            reel.refreshers.push(refresh);
            refresh();
            actions.append(build);
            break;
          }
          actions.append(el("button", { type: "button", class: "native-button", text: element.label,
            disabled: element.disabled, onclick: () => cut(element.key) }));
          break;
        default: break;
      }
    }
    const pitchFigures = figures.filter(([, element]) => isPitch(element.figure));
    if (SIDE_BY_SIDE_TABS.has(context.slug) && figures.length === 1 && pitchFigures.length === 1) {
      const [target] = figures[0];
      const side = el("div", { class: "native-pitch-side" }, ...nodes.filter((node) => node !== target));
      body.replaceChildren(el("div", { class: "native-pitch-layout" }, side, el("div", { class: "native-pitch-main" }, target)));
    } else {
      body.replaceChildren(...nodes);
    }
    resizeWatch?.disconnect();
    if (figures.length) {
      const Plotly = await loadPlotly();
      await Promise.all(figures.map(([target, element]) => {
        if (isPitch(element.figure)) target.dataset.narrow = String(target.clientWidth < NARROW_PITCH);
        return Plotly.react(target, element.figure.data,
          isPitch(element.figure) ? pitchLayout(target, element.figure) : element.figure.layout,
          plotlyConfig({ ...element.config, responsive: true }, Plotly));
      }));
      if (pitchFigures.length && "ResizeObserver" in window) {
        let frame = 0;
        resizeWatch = new ResizeObserver(() => {
          cancelAnimationFrame(frame);
          frame = requestAnimationFrame(() => pitchFigures.forEach(([target, element]) => {
            if (!target.isConnected) return;
            const layout = pitchLayout(target, element.figure);
            const narrow = String(target.clientWidth < NARROW_PITCH);
            if (narrow !== target.dataset.narrow || Math.abs(layout.height - (target.layout?.height || 0)) > 4) {
              target.dataset.narrow = narrow;
              window.Plotly.react(target, element.figure.data, layout, plotlyConfig({ ...element.config, responsive: true }, window.Plotly));
            }
          }));
        });
        pitchFigures.forEach(([target]) => resizeWatch.observe(target));
      }
    }
  };

  const load = async () => {
    const ticket = ++request;
    panel.setAttribute("aria-busy", "true");
    try {
      const result = await projectRequest(`/api/analysis/${context.view}/${context.slug}`, { project_id: context.projectId, match_id: context.matchId, controls });
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
  return () => {
    resizeWatch?.disconnect();
    body.querySelectorAll(".native-figure").forEach((target) => window.Plotly && window.Plotly.purge(target));
  };
}
