// The sequence track (docs/CODING_AND_PITCH_PLAN.md, T2): the session's clips in play order on one strip,
// each block as long as the clip plays once exported. Click a block to open that clip, drag it (or Alt+arrow)
// to reorder, add a clip from another session, and export the whole sequence as one video.
// Sessions live in the project (app/telestration/clips.py, sessions.json).
import { projectRequest } from "../projects.js";
import { editorUrl, loadSessions } from "./library.js";

const enc = encodeURIComponent;
const sessionsPath = (projectId) => `/api/editor-sessions/${enc(projectId)}`;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** "1:05" */
export const clock = (value) => {
  const total = Math.max(0, Math.round(Number(value) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

/** How long a clip of a session plays: its exported length, or its video's when that is not known. */
export const clipSeconds = (clip) => Math.max(0.1, Number(clip.seconds ?? clip.duration) || 0.1);

/** Each clip's block as fractions of the strip: [{id, start, width}], end to end in order. */
export const sequenceLayout = (clips) => {
  const total = clips.reduce((sum, clip) => sum + clipSeconds(clip), 0) || 1;
  let at = 0;
  return clips.map((clip) => {
    const width = clipSeconds(clip) / total;
    const block = { id: clip.id, start: at, width };
    at += width;
    return block;
  });
};

/** `order` with the entry at `from` moved to `to` (indexes into the new order). */
export const moveInOrder = (order, from, to) => {
  const next = [...order];
  const [moved] = next.splice(from, 1);
  next.splice(Math.max(0, Math.min(next.length, to)), 0, moved);
  return next;
};

/** Where a block dropped at fraction `x` of the strip lands: the index whose block's middle it passed. */
export const dropIndex = (layout, from, x) => {
  const others = layout.filter((_, index) => index !== from);
  return others.filter((block) => block.start + block.width / 2 < x).length;
};

/**
 * Show the sequence of the session holding `clipId` in `root` ([data-sequence]).
 * `onExport(session)` exports it; `beforeLeave()` saves the open clip before another opens.
 * Returns the session (or null), and keeps it current as the analyst reorders or adds clips.
 */
export async function showSequence(root, projectId, clipId, { onExport, beforeLeave, onError }) {
  const lane = root.querySelector("[data-sequence-lane]");
  const add = root.querySelector("[data-sequence-add]");
  const exportButton = root.querySelector("[data-sequence-export]");
  const name = root.querySelector("[data-sequence-name]");
  let sessions;
  let session;

  const request = async (action, body) => {
    try {
      sessions = (await projectRequest(`${sessionsPath(projectId)}/${action}`, body)).sessions;
      render();
    } catch (problem) {
      onError(problem.message);
      render();
    }
  };

  const open = async (event, clip) => {
    event.preventDefault();
    if (clip.id === clipId) return;
    await beforeLeave();
    location.href = editorUrl(projectId, clip.id);
  };

  const render = () => {
    session = sessions.find((entry) => entry.clips.some((clip) => clip.id === clipId)) || null;
    root.hidden = !session;
    if (!session) return;
    name.textContent = session.name;
    const layout = sequenceLayout(session.clips);
    const blocks = session.clips.map((clip, index) => {
      const item = el("li", "annotate-sequence-item");
      item.style.left = `${layout[index].start * 100}%`;
      item.style.width = `${layout[index].width * 100}%`;
      const block = el("a", "annotate-sequence-block");
      block.href = editorUrl(projectId, clip.id);
      block.title = `${clip.name} · ${clock(clipSeconds(clip))}. Drag, or Alt and an arrow key, to move it.`;
      block.dataset.index = String(index);
      block.draggable = false; // a pointer drag reorders; the browser's link drag would not
      if (clip.id === clipId) block.setAttribute("aria-current", "page");
      block.append(el("span", "annotate-sequence-index", String(index + 1)),
        el("span", "annotate-block-label", `${clip.name} · ${clock(clipSeconds(clip))}`));
      block.onclick = (event) => { if (block.dataset.dragged) { event.preventDefault(); delete block.dataset.dragged; } else open(event, clip); };
      block.onkeydown = (event) => {
        if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const to = index + (event.key === "ArrowLeft" ? -1 : 1);
        if (to < 0 || to >= session.clips.length) return;
        reorder(index, to, clip.id);
      };
      wireDrag(block, index, layout);
      item.append(block);
      return item;
    });
    lane.replaceChildren(...blocks);
    exportButton.disabled = session.clips.length < 2;
    exportButton.title = session.clips.length < 2 ? "Add another clip to export a sequence" : `Export all ${session.clips.length} clips, in this order, as one video`;
    const others = sessions.filter((entry) => entry.id !== session.id).flatMap((entry) => entry.clips.map((clip) => ({ clip, from: entry })));
    const choices = others.map(({ clip, from }) => {
      const option = el("option", "", from.clips.length > 1 ? `${clip.name} (from ${from.name})` : clip.name);
      option.value = clip.id;
      return option;
    });
    const placeholder = el("option", "", others.length ? "Add clip…" : "No other clips");
    placeholder.value = "";
    add.replaceChildren(placeholder, ...choices);
    add.disabled = !others.length;
  };

  const reorder = (from, to, focusId) => {
    const order = moveInOrder(session.clips.map((clip) => clip.id), from, to);
    // Show the new order at once; the engine's answer replaces it.
    session.clips = order.map((id) => session.clips.find((clip) => clip.id === id));
    render();
    lane.querySelector(`[href$="${enc(focusId)}"]`)?.focus();
    request("reorder", { session_id: session.id, clips: order }).then(() => lane.querySelector(`[href$="${enc(focusId)}"]`)?.focus());
  };

  const wireDrag = (block, index, layout) => {
    let drag = null;
    block.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      drag = { x: event.clientX, moved: false, pointer: event.pointerId };
    });
    block.addEventListener("pointermove", (event) => {
      if (!drag || event.pointerId !== drag.pointer) return;
      if (!drag.moved && Math.abs(event.clientX - drag.x) < 5) return;
      if (!drag.moved) { drag.moved = true; block.setPointerCapture(event.pointerId); block.classList.add("is-dragging"); }
      block.style.transform = `translateX(${event.clientX - drag.x}px)`;
    });
    const finish = (event) => {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      block.classList.remove("is-dragging");
      block.style.transform = "";
      if (!moved) return;
      block.dataset.dragged = "1"; // the click that follows a drag does not open the clip
      const rect = lane.getBoundingClientRect();
      const to = dropIndex(layout, index, (event.clientX - rect.left) / Math.max(1, rect.width));
      if (to !== index) reorder(index, to, session.clips[index].id);
    };
    block.addEventListener("pointerup", finish);
    block.addEventListener("pointercancel", finish);
  };

  add.onchange = () => {
    const chosen = add.value;
    if (chosen) request("move-clip", { session_id: session.id, clip_id: chosen });
  };
  exportButton.onclick = () => { if (session) onExport(session); };

  try {
    sessions = await loadSessions(projectId);
  } catch {
    return null; // the sequence is a convenience; the editor works without it
  }
  render();
  return session;
}
