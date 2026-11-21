// The Annotate tab: the project's annotate sessions (groups of clips drawn on
// together), and the strip of a session's clips shown above the editor.
// Sessions live in the project (app/telestration/clips.py, sessions.json).
import { projectRequest } from "../projects.js";

const enc = encodeURIComponent;
export const editorUrl = (projectId, clipId) => `/annotate.html?project=${enc(projectId)}&clip=${enc(clipId)}`;
const sessionsPath = (projectId) => `/api/editor-sessions/${enc(projectId)}`;

export const loadSessions = async (projectId) => (await projectRequest(sessionsPath(projectId))).sessions;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const seconds = (value) => {
  const total = Math.max(0, Math.round(Number(value) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

const day = (iso) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
};

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

/** "3 clips · 12 drawings · edited 2 Nov" */
export const sessionSummary = (session) => {
  const drawings = session.clips.reduce((sum, clip) => sum + (clip.drawings || 0), 0);
  const single = session.clips.length === 1;
  const parts = [single ? seconds(session.clips[0].duration) : plural(session.clips.length, "clip"), plural(drawings, "drawing")];
  const edited = day(session.updated_at);
  if (edited) parts.push(`edited ${edited}`);
  return parts.join(" · ");
};

/** List the project's sessions in `root`, with open, rename, remove and delete. */
export async function showLibrary(root, projectId, onStatus = () => {}) {
  const list = root.querySelector("[data-library-list]");
  const empty = root.querySelector("[data-library-empty]");
  const error = root.querySelector("[data-library-error]");
  root.hidden = false;
  const fail = (message) => { error.textContent = message; error.hidden = !message; };

  const render = (sessions) => {
    list.replaceChildren(...sessions.map((session) => sessionCard(session)));
    empty.hidden = sessions.length > 0;
    onStatus(sessions.length ? plural(sessions.length, "session") : "No sessions yet");
  };

  const act = async (action, body, button) => {
    if (button) button.disabled = true;
    fail("");
    try {
      render((await projectRequest(`${sessionsPath(projectId)}/${action}`, body)).sessions);
    } catch (problem) {
      fail(problem.message);
      if (button) button.disabled = false;
    }
  };

  const sessionCard = (session) => {
    const card = el("li", "annotate-session");
    const head = el("div", "annotate-session-head");
    const title = el("h3", "annotate-session-name", session.name);
    const meta = el("p", "annotate-session-meta", sessionSummary(session));
    const open = el("a", "annotate-primary annotate-session-open", session.clips.length > 1 ? "Open session" : "Open");
    open.href = editorUrl(projectId, session.clips[0].id);
    const rename = el("button", "annotate-session-tool", "Rename");
    rename.type = "button";
    rename.onclick = () => renameInline(title, session, rename);
    const remove = el("button", "annotate-session-tool annotate-danger", "Delete");
    remove.type = "button";
    remove.title = "Delete this session and its clips";
    remove.onclick = () => {
      const what = session.clips.length > 1 ? `${session.clips.length} clips and their drawings` : "its clip and drawings";
      if (window.confirm(`Delete "${session.name}"? ${what[0].toUpperCase()}${what.slice(1)} move to the project's editor-trash folder.`)) {
        act("delete", { session_id: session.id }, remove);
      }
    };
    const titleBlock = el("div", "annotate-session-title");
    titleBlock.append(title, meta);
    const tools = el("div", "annotate-session-tools");
    tools.append(open, rename, remove);
    head.append(titleBlock, tools);
    card.append(head);
    if (session.clips.length === 1) return card; // one clip: the header already says it all

    const clips = el("ol", "annotate-session-clips");
    for (const clip of session.clips) {
      const row = el("li", "annotate-session-clip");
      const link = el("a", "annotate-session-clip-link");
      link.href = editorUrl(projectId, clip.id);
      link.append(el("span", "annotate-session-clip-name", clip.name),
        el("span", "annotate-session-clip-meta", `${seconds(clip.duration)} · ${plural(clip.drawings || 0, "drawing")}`));
      const drop = el("button", "annotate-session-drop");
      drop.type = "button";
      drop.setAttribute("aria-label", `Remove ${clip.name} from the session`);
      drop.title = "Remove this clip (it moves to the project's editor-trash folder)";
      drop.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg>';
      drop.onclick = () => {
        if (window.confirm(`Remove "${clip.name}" and its drawings from this session?`)) act("remove-clip", { clip_id: clip.id }, drop);
      };
      row.append(link, drop);
      clips.append(row);
    }
    card.append(clips);
    return card;
  };

  const renameInline = (title, session, button) => {
    const input = el("input", "annotate-session-rename");
    input.type = "text";
    input.maxLength = 120;
    input.value = session.name;
    input.setAttribute("aria-label", "Session name");
    title.replaceChildren(input);
    button.disabled = true;
    input.focus();
    input.select();
    let done = false;
    const finish = (keep) => {
      if (done) return;
      done = true;
      const name = input.value.trim();
      if (keep && name && name !== session.name) act("rename", { session_id: session.id, name });
      else { title.textContent = session.name; button.disabled = false; }
    };
    input.onkeydown = (event) => {
      if (event.key === "Enter") finish(true);
      if (event.key === "Escape") finish(false);
    };
    input.onblur = () => finish(true);
  };

  onStatus("Loading sessions...");
  try {
    render(await loadSessions(projectId));
  } catch (problem) {
    onStatus("Sessions need attention");
    fail(problem.message);
  }
}

/** Show the other clips of the session holding `clipId` above the editor, as links (saving waits on leaving). */
export async function showClipStrip(strip, projectId, clipId) {
  let sessions;
  try {
    sessions = await loadSessions(projectId);
  } catch {
    return null; // the strip is a convenience; the editor works without it
  }
  const session = sessions.find((entry) => entry.clips.some((clip) => clip.id === clipId));
  if (!session || session.clips.length < 2) return session || null;
  const label = el("span", "annotate-strip-name", session.name);
  const links = session.clips.map((clip, index) => {
    const link = el("a", "annotate-strip-clip");
    link.href = editorUrl(projectId, clip.id);
    link.title = clip.name;
    link.append(el("span", "annotate-strip-index", String(index + 1)), el("span", "annotate-strip-label", clip.name));
    if (clip.id === clipId) link.setAttribute("aria-current", "page");
    return link;
  });
  strip.replaceChildren(label, ...links);
  strip.hidden = false;
  return session;
}
