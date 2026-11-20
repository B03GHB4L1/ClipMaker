// One or more players across every saved match (Filter page): pick the players, find their clips in
// each match with the engine's own filter, watch any clip, and export one reel per match.
// Uses the same engine calls as the Filter page; nothing here reads files directly.
import { annotateClip, revealFolder, saveClip } from "./save-clip.js";

const request = async (path, body) => {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
};

const element = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
};

const fold = (name) => name.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const matchTitle = (match) => match.project_name || `${match.home_team || "Home"} vs ${match.away_team || "Away"}`;

/** Every player of every saved match: [{key, name, teams, matches: [{id, title}]}], A to Z. Pure, for tests. */
export const indexPlayers = (entries) => {
  const players = new Map();
  entries.forEach(({ match, options }) => {
    Object.entries(options?.team_players || {}).forEach(([team, names]) => names.forEach((name) => {
      const key = fold(name);
      const entry = players.get(key) || { key, name, teams: new Set(), matches: [] };
      entry.teams.add(team);
      if (!entry.matches.some((each) => each.id === match.id)) entry.matches.push({ id: match.id, title: matchTitle(match), names: [] });
      entry.matches.find((each) => each.id === match.id).names.push(name); // the spelling this match uses
      players.set(key, entry);
    }));
  });
  return [...players.values()].sort((a, b) => a.name.localeCompare(b.name));
};

/** The players in `index` whose name holds every word of `query` (accents and case ignored). */
export const searchPlayers = (index, query, limit = 40) => {
  const words = fold(query).split(/\s+/).filter(Boolean);
  return index.filter((player) => words.every((word) => player.key.includes(word))).slice(0, limit);
};

let dialog;
let state;

const loadIndex = async () => {
  const { matches = [] } = await request("/api/matches");
  const saved = matches.filter((match) => match.csv_path);
  const entries = [];
  // A few at a time: each reads one match's event table.
  for (let index = 0; index < saved.length; index += 4) {
    const batch = saved.slice(index, index + 4);
    const loaded = await Promise.all(batch.map((match) => request("/api/filter-options", { match_id: match.id })
      .then((options) => ({ match, options })).catch(() => null)));
    entries.push(...loaded.filter(Boolean));
    status(`Reading saved matches: ${Math.min(index + 4, saved.length)} of ${saved.length}`);
  }
  return { matches: saved, players: indexPlayers(entries) };
};

const status = (text, problem = false) => {
  const line = dialog?.querySelector("[data-ps-status]");
  if (!line) return;
  line.textContent = text;
  line.classList.toggle("is-problem", problem);
};

const renderChosen = () => {
  const list = dialog.querySelector("[data-ps-chosen]");
  list.replaceChildren(...state.chosen.map((player) => {
    const remove = element("button", { type: "button", className: "ps-chip-remove", textContent: "×", title: `Remove ${player.name}` });
    remove.setAttribute("aria-label", `Remove ${player.name}`);
    remove.onclick = () => { state.chosen = state.chosen.filter((each) => each.key !== player.key); renderChosen(); renderSuggestions(); };
    return element("span", { className: "ps-chip" }, `${player.name} `, element("small", { textContent: `${player.matches.length}` }), remove);
  }));
  dialog.querySelector("[data-ps-find]").disabled = !state.chosen.length || state.busy;
  const matches = new Set(state.chosen.flatMap((player) => player.matches.map((match) => match.id)));
  dialog.querySelector("[data-ps-scope]").textContent = state.chosen.length
    ? `${matches.size} saved match${matches.size === 1 ? "" : "es"} with ${state.chosen.length === 1 ? "this player" : "these players"}`
    : "Pick one or more players.";
};

const renderSuggestions = () => {
  const box = dialog.querySelector("[data-ps-suggestions]");
  const query = dialog.querySelector("[data-ps-search]").value;
  if (!state.players) return box.replaceChildren();
  const chosen = new Set(state.chosen.map((player) => player.key));
  const found = searchPlayers(state.players, query).filter((player) => !chosen.has(player.key));
  box.replaceChildren(...found.map((player) => {
    const button = element("button", { type: "button", className: "ps-suggestion" },
      element("strong", { textContent: player.name }),
      element("span", { textContent: `${[...player.teams].join(" / ")} · ${player.matches.length} match${player.matches.length === 1 ? "" : "es"}` }));
    button.onclick = () => {
      state.chosen.push(player);
      dialog.querySelector("[data-ps-search]").value = "";
      renderChosen();
      renderSuggestions();
      dialog.querySelector("[data-ps-search]").focus();
    };
    return element("li", {}, button);
  }));
  if (!found.length) box.append(element("li", { className: "ps-empty", textContent: query ? "No player by that name in your saved matches." : "No more players." }));
};

// The page's own filters (actions, qualifiers, timing), with the team and players set per match here.
const optionsFor = (match) => {
  const page = state.pageOptions();
  const base = dialog.querySelector("[data-ps-use-filters]").checked ? page : {
    before_buffer: page.before_buffer, after_buffer: page.after_buffer, min_gap: page.min_gap,
  };
  const names = state.chosen.flatMap((player) => player.matches.find((each) => each.id === match.id)?.names || []);
  return { ...base, dry_run: true, team_filter: "", player_filters: names };
};

const find = async () => {
  if (state.busy || !state.chosen.length) return;
  state.busy = true;
  renderChosen();
  const wanted = new Set(state.chosen.flatMap((player) => player.matches.map((match) => match.id)));
  const matches = state.matches.filter((match) => wanted.has(match.id));
  state.results = [];
  renderResults();
  try {
    for (const [index, match] of matches.entries()) {
      status(`Finding clips: match ${index + 1} of ${matches.length}`);
      const options = optionsFor(match);
      try {
        const { windows } = await request("/api/previews", { match_id: match.id, options });
        state.results.push({ match, options, windows });
      } catch (error) {
        state.results.push({ match, options, windows: [], error: error.message });
      }
      renderResults();
    }
    const total = state.results.reduce((sum, result) => sum + result.windows.length, 0);
    status(total ? `${total} clip${total === 1 ? "" : "s"} in ${state.results.filter((result) => result.windows.length).length} match${matches.length === 1 ? "" : "es"}.`
      : "No clips found. Try without this page's action filters, or check that each match has footage and kickoff times in Intake.");
  } finally {
    state.busy = false;
    renderChosen();
  }
};

const playClip = async (result, clip, button) => {
  const viewer = dialog.querySelector("[data-ps-viewer]");
  const video = viewer.querySelector("video");
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Loading...";
  try {
    const { file } = await request("/api/previews/render", { match_id: result.match.id, start: clip.start, end: clip.end, period: clip.period });
    viewer.hidden = false;
    viewer.querySelector("[data-ps-now]").textContent = `${clip.label} · ${matchTitle(result.match)}`;
    video.src = file.url;
    video.play().catch(() => {});
    const save = viewer.querySelector("[data-ps-save]");
    save.onclick = () => saveClip(file.url, clip.label, save);
    const annotate = viewer.querySelector("[data-ps-annotate]");
    annotate.onclick = () => annotateClip(file.url, clip.label, annotate, result.match.id);
  } catch (error) {
    status(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
};

const renderResults = () => {
  const box = dialog.querySelector("[data-ps-results]");
  box.replaceChildren(...state.results.map((result) => {
    const head = element("div", { className: "ps-match-head" },
      element("strong", { textContent: matchTitle(result.match) }),
      element("span", { textContent: result.error ? result.error : `${result.windows.length} clip${result.windows.length === 1 ? "" : "s"}` }));
    const list = element("ol", { className: "ps-clips" }, ...result.windows.map((clip) => {
      const play = element("button", { type: "button", className: "ps-play", textContent: "Watch" });
      play.onclick = () => playClip(result, clip, play);
      return element("li", {}, element("span", { textContent: clip.label }), play);
    }));
    const section = element("section", { className: `ps-match${result.error ? " is-problem" : ""}` }, head, list);
    return section;
  }));
  const total = state.results.reduce((sum, result) => sum + result.windows.length, 0);
  dialog.querySelector("[data-ps-export]").disabled = !total || state.exporting;
};

// One reel per match, one export at a time; saved where the Filter page saves exports.
const exportAll = async () => {
  const todo = state.results.filter((result) => result.windows.length);
  if (!todo.length || state.exporting) return;
  state.exporting = true;
  renderResults();
  const who = state.chosen.map((player) => player.name).join(", ").slice(0, 60);
  const page = state.pageOptions();
  let saved = 0;
  let lastJob = null;
  try {
    for (const [index, result] of todo.entries()) {
      const name = `${who} - ${matchTitle(result.match)}`.replace(/[\\/:*?"<>|]+/g, " ").slice(0, 110);
      const options = { ...result.options, dry_run: false, individual_clips: false, export_scope: "all",
        output_filename: `${name}.mp4`, output_dir: page.output_dir, output_format: page.output_format, clip_windows: result.windows };
      const { job } = await request("/api/jobs", { match_id: result.match.id, options });
      for (;;) {
        const { job: now } = await request(`/api/jobs/${job.id}`);
        const share = now.progress?.total ? Math.round((now.progress.current / now.progress.total) * 100) : 0;
        status(`Exporting reel ${index + 1} of ${todo.length} (${matchTitle(result.match)}): ${share}%`);
        if (now.status === "complete") { saved += 1; lastJob = now; break; }
        if (now.status === "failed" || now.status === "cancelled") throw new Error(`${matchTitle(result.match)}: ${(now.logs || []).slice(-1)[0] || now.status}`);
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
    status(`${saved} reel${saved === 1 ? "" : "s"} saved${lastJob?.output_dir ? ` in ${lastJob.output_dir}` : ""}.`);
    if (lastJob) {
      const open = dialog.querySelector("[data-ps-open-folder]");
      open.hidden = false;
      open.onclick = () => revealFolder(`/api/jobs/${lastJob.id}/reveal`);
    }
  } catch (error) {
    status(`${saved} reel${saved === 1 ? "" : "s"} saved, then the export stopped: ${error.message}`, true);
  } finally {
    state.exporting = false;
    renderResults();
  }
};

const build = () => {
  dialog = element("dialog", { className: "player-search" });
  dialog.setAttribute("aria-labelledby", "player-search-title");
  dialog.innerHTML = `
    <div class="ps-head">
      <h2 id="player-search-title">Players across matches</h2>
      <button type="button" class="ps-close" data-ps-close aria-label="Close">×</button>
    </div>
    <div class="ps-body">
      <div class="ps-pick">
        <label class="ps-search-label">Player <input type="search" data-ps-search placeholder="Type a name" autocomplete="off" /></label>
        <ul class="ps-suggestions" data-ps-suggestions aria-label="Players in your saved matches"></ul>
        <div class="ps-chosen" data-ps-chosen aria-live="polite"></div>
        <p class="ps-scope" data-ps-scope></p>
        <label class="ps-check"><input type="checkbox" data-ps-use-filters checked /> Use this page's action and qualifier filters</label>
        <div class="ps-actions">
          <button type="button" class="ps-primary" data-ps-find disabled>Find clips</button>
          <button type="button" data-ps-export disabled title="One reel per match, saved where exports go">Export reels</button>
          <button type="button" data-ps-open-folder hidden>Open folder</button>
        </div>
        <p class="ps-status" data-ps-status role="status"></p>
      </div>
      <div class="ps-out">
        <div class="ps-viewer" data-ps-viewer hidden>
          <video controls playsinline></video>
          <div class="ps-viewer-bar"><span data-ps-now></span><button type="button" data-ps-save>Save clip</button><button type="button" data-ps-annotate>Annotate</button></div>
        </div>
        <div class="ps-results" data-ps-results></div>
      </div>
    </div>`;
  document.body.append(dialog);
  dialog.querySelector("[data-ps-close]").onclick = () => dialog.close();
  dialog.addEventListener("close", () => dialog.querySelector("video").pause());
  dialog.querySelector("[data-ps-search]").addEventListener("input", renderSuggestions);
  dialog.querySelector("[data-ps-search]").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); dialog.querySelector(".ps-suggestion")?.click(); }
  });
  dialog.querySelector("[data-ps-find]").onclick = find;
  dialog.querySelector("[data-ps-export]").onclick = exportAll;
};

/** Open the dialog. `pageOptions()` gives the Filter page's current options (collectOptions). */
export const openPlayerSearch = async ({ pageOptions, preset = [] } = {}) => {
  if (!dialog) build();
  if (!state) state = { players: null, matches: [], chosen: [], results: [], busy: false, exporting: false };
  state.pageOptions = pageOptions || (() => ({}));
  dialog.showModal();
  dialog.querySelector("[data-ps-search]").focus();
  if (!state.players) {
    try {
      Object.assign(state, await loadIndex());
      status(`${state.players.length} players in ${state.matches.length} saved match${state.matches.length === 1 ? "" : "es"}.`);
    } catch (error) {
      status(`Could not read the saved matches: ${error.message}`, true);
      return;
    }
  }
  // Players already ticked on the page start chosen.
  preset.forEach((name) => {
    const player = state.players.find((each) => each.key === fold(name));
    if (player && !state.chosen.some((each) => each.key === player.key)) state.chosen.push(player);
  });
  renderChosen();
  renderSuggestions();
};
