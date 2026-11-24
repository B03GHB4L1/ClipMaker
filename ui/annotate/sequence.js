// The Clips track of the Annotate timeline (docs/CODING_AND_PITCH_PLAN.md, T2): every clip and card of the session
// in play order, on the same time scale as the tracks below it. Click a block to move the playhead there, drag it
// (or Alt+arrow) to reorder, add a clip from another session or a picture / text card. The editor (annotate.js)
// owns the playhead, playback and export; this module keeps the session's order (sessions.json, through the engine).
import { projectRequest } from "../projects.js";
import { editorUrl, loadSessions } from "./library.js";

const enc = encodeURIComponent;
const sessionsPath = (projectId) => `/api/editor-sessions/${enc(projectId)}`;
const picturesPath = (projectId) => `/api/projects/${enc(projectId)}/pictures`;
export const CARD_SECONDS = [0.5, 30];
export const CARD_TEXT = 200;

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

/** How long an entry plays: a clip's exported length (its video's when that is not known) or a card's seconds. */
export const clipSeconds = (clip) => Math.max(0.1, Number(clip.seconds ?? clip.duration) || 0.1);

/** Each block as fractions of the track: [{id, start, width}], end to end in order. */
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

/** Where a block dropped at fraction `x` of the track lands: the index whose block's middle it passed. */
export const dropIndex = (layout, from, x) => {
  const others = layout.filter((_, index) => index !== from);
  return others.filter((block) => block.start + block.width / 2 < x).length;
};

/** The entry of `layout` ([{start, length}], seconds) under time `t`: the last one at the very end. */
export const entryAt = (layout, t) => layout.find((entry) => t < entry.start + entry.length - 1e-6) || layout[layout.length - 1] || null;

/** The text of a card as lines that fit `width` pixels (words kept whole; one long word is cut by the canvas edge). */
export const wrapLines = (measure, text, width) => {
  const lines = [];
  String(text).split(/\r?\n/).forEach((paragraph) => {
    let line = "";
    paragraph.split(/\s+/).filter(Boolean).forEach((word) => {
      const trial = line ? `${line} ${word}` : word;
      if (line && measure(trial) > width) { lines.push(line); line = word; } else line = trial;
    });
    lines.push(line);
  });
  return lines;
};

/** The picture of a text card at the sequence's frame size: light words centred on dark green. Resolves a PNG blob. */
export const drawTextCard = (text, width, height) => {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#10201b";
  ctx.fillRect(0, 0, width, height);
  const size = Math.max(18, Math.round(height / 12));
  ctx.font = `600 ${size}px system-ui, "Segoe UI", sans-serif`;
  ctx.fillStyle = "#f4f7f2";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const lines = wrapLines((value) => ctx.measureText(value).width, text, width * 0.82);
  const gap = size * 1.3;
  lines.forEach((line, index) => ctx.fillText(line, width / 2, height / 2 + (index - (lines.length - 1) / 2) * gap, width * 0.9));
  return new Promise((resolve, reject) => canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("The card could not be drawn."))), "image/png"));
};

/** A card's short name: its words, or its picture's name. */
export const cardName = (card, pictures = []) => (card.type === "picture"
  ? pictures.find((picture) => picture.id === card.picture_id)?.name || "Picture"
  : `“${card.text}”`);

/**
 * Show the Clips track of the session holding `clipId`. `root` is the timeline; it holds [data-sequence] (the track
 * row), [data-sequence-tools] and [data-card-form].
 * `onItems(items, session)`: the order changed (or first loaded). `onSeek(id)`: the analyst chose a block.
 * Returns {session(), setLayout(layout), setCurrent(id), pictures()} or null when the sessions cannot be read.
 */
export async function showSequence(root, projectId, startClipId, { onItems, onSeek, onError }) {
  const row = root.querySelector("[data-sequence]");
  const lane = root.querySelector("[data-sequence-lane]");
  const tools = root.querySelector("[data-sequence-tools]");
  const add = root.querySelector("[data-sequence-add]");
  const name = root.querySelector("[data-sequence-name]");
  const cardButton = root.querySelector("[data-sequence-card]");
  const form = root.querySelector("[data-card-form]");
  let clipId = startClipId;
  let sessions;
  let session;
  let pictures = [];
  let editing = null; // the card being edited, or "new"
  let layout = null; // the editor's layout: [{id, start, length}] in seconds, with the open clip's live length

  const request = async (action, body) => {
    try {
      sessions = (await projectRequest(`${sessionsPath(projectId)}/${action}`, body)).sessions;
      render(true);
      return true;
    } catch (problem) {
      onError(problem.message);
      render(true);
      return false;
    }
  };

  // Block positions as fractions of the track: the editor's live layout, or the saved lengths until it gives one.
  const positions = () => {
    const items = session.items;
    const all = layout?.reduce((sum, entry) => sum + entry.length, 0);
    if (!layout || !all || layout.length !== items.length || layout.some((entry, index) => entry.id !== items[index].id)) return sequenceLayout(items);
    return layout.map((entry) => ({ id: entry.id, start: entry.start / all, width: entry.length / all }));
  };

  const render = (changed = false) => {
    session = sessions.find((entry) => entry.clips.some((clip) => clip.id === clipId)) || null;
    row.hidden = !session;
    tools.hidden = !session;
    if (!session) return;
    if (changed) onItems(session.items, session);
    name.textContent = session.name;
    const items = session.items;
    const places = positions();
    lane.replaceChildren(...items.map((item, index) => {
      const holder = el("li", "annotate-sequence-item");
      holder.style.left = `${places[index].start * 100}%`;
      holder.style.width = `${places[index].width * 100}%`;
      const card = item.kind === "card";
      const seconds = layout?.find((entry) => entry.id === item.id)?.length ?? clipSeconds(item);
      const label = card ? cardName(item, pictures) : item.name;
      const block = el(card ? "button" : "a", `annotate-sequence-block${card ? " is-card" : ""}`);
      if (card) block.type = "button"; else block.href = editorUrl(projectId, item.id);
      block.title = `${card ? `${item.type === "picture" ? "Picture" : "Text"} card` : "Clip"} ${index + 1}: ${label} · ${clock(seconds)}. `
        + `Click to go to it${card ? " and edit it" : ""}; drag, or Alt and an arrow key, to move it.`;
      block.dataset.index = String(index);
      block.draggable = false; // a pointer drag reorders; the browser's link drag would not
      if (item.id === clipId) block.setAttribute("aria-current", "true");
      if (card && editing === item.id) block.setAttribute("aria-pressed", "true");
      block.append(el("span", "annotate-sequence-index", String(index + 1)), el("span", "annotate-block-label", label));
      block.onclick = (event) => {
        event.preventDefault();
        if (block.dataset.dragged) { delete block.dataset.dragged; return; }
        onSeek(item.id);
        if (card) editCard(item);
      };
      block.onkeydown = (event) => {
        if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const to = index + (event.key === "ArrowLeft" ? -1 : 1);
        if (to < 0 || to >= items.length) return;
        reorder(index, to, item.id);
      };
      wireDrag(block, index, places);
      holder.append(block);
      return holder;
    }));
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

  // ----- cards -----------------------------------------------------------
  const field = (key) => form.querySelector(`[data-card-${key}]`);
  const syncKind = () => {
    const picture = field("kind").value === "picture";
    field("text").closest("label").hidden = picture;
    field("picture").closest("label").hidden = !picture;
  };
  const showForm = () => {
    form.hidden = editing === null;
    form.querySelector("[data-card-remove]").hidden = editing === "new" || editing === null;
    form.querySelector("[data-card-save]").textContent = editing === "new" ? "Add card" : "Save card";
    cardButton.setAttribute("aria-expanded", String(editing === "new"));
  };
  const loadPictures = async () => {
    try { pictures = (await projectRequest(picturesPath(projectId))).pictures || []; } catch { pictures = []; }
    const options = pictures.map((picture) => Object.assign(el("option", "", picture.name), { value: picture.id }));
    field("picture").replaceChildren(...(options.length ? options : [Object.assign(el("option", "", "No pictures in the project"), { value: "" })]));
  };
  const openForm = async (card) => {
    await loadPictures();
    editing = card ? card.id : "new";
    field("kind").value = card ? card.type : "text";
    field("kind").disabled = Boolean(card); // a card keeps its kind; make a new one to change it
    field("text").value = card?.text || "";
    if (card?.picture_id) field("picture").value = card.picture_id;
    field("seconds").value = String(card?.seconds ?? 3);
    field("error").textContent = "";
    syncKind();
    showForm();
    render();
    (card?.type === "picture" ? field("picture") : field("text")).focus();
  };
  const editCard = (card) => (editing === card.id ? closeForm() : openForm(card));
  const closeForm = () => { editing = null; showForm(); render(); };
  const fail = (text) => { field("error").textContent = text; };

  field("kind").onchange = syncKind;
  form.onsubmit = async (event) => {
    event.preventDefault();
    const kind = field("kind").value;
    const seconds = Number(field("seconds").value);
    const text = field("text").value.trim();
    if (!(seconds >= CARD_SECONDS[0] && seconds <= CARD_SECONDS[1])) return fail(`Show a card for ${CARD_SECONDS[0]} to ${CARD_SECONDS[1]} seconds.`);
    if (kind === "text" && !text) return fail("Type the words the card shows.");
    if (kind === "picture" && !field("picture").value) return fail("Add a picture to the project first, in the picture panel.");
    const card = kind === "picture" ? { kind, picture_id: field("picture").value, seconds } : { kind, text, seconds };
    // A new card goes straight after the open clip.
    const after = session.items.findIndex((item) => item.id === clipId);
    const ok = editing === "new"
      ? await request("add-card", { session_id: session.id, card, index: after < 0 ? session.items.length : after + 1 })
      : await request("update-card", { session_id: session.id, card_id: editing, card });
    if (ok) closeForm();
  };
  form.querySelector("[data-card-cancel]").onclick = closeForm;
  form.querySelector("[data-card-remove]").onclick = async () => { if (await request("remove-card", { session_id: session.id, card_id: editing })) closeForm(); };
  form.onkeydown = (event) => { if (event.key === "Escape") { event.stopPropagation(); closeForm(); } };
  cardButton.onclick = () => (editing === "new" ? closeForm() : openForm(null));

  // ----- reordering -------------------------------------------------------
  const reorder = (from, to, focusId) => {
    const order = moveInOrder(session.items.map((item) => item.id), from, to);
    // Show the new order at once; the engine's answer replaces it.
    session.items = order.map((id) => session.items.find((item) => item.id === id));
    session.clips = session.items.filter((item) => item.kind === "clip");
    onItems(session.items, session);
    render();
    const focus = () => lane.querySelector(`[data-index="${order.indexOf(focusId)}"]`)?.focus();
    focus();
    request("reorder", { session_id: session.id, clips: order }).then(focus);
  };

  const wireDrag = (block, index, places) => {
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
      block.dataset.dragged = "1"; // the click that follows a drag does not move the playhead
      const rect = lane.getBoundingClientRect();
      const to = dropIndex(places, index, (event.clientX - rect.left) / Math.max(1, rect.width));
      if (to !== index) reorder(index, to, session.items[index].id);
    };
    block.addEventListener("pointerup", finish);
    block.addEventListener("pointercancel", finish);
  };

  add.onchange = () => {
    const chosen = add.value;
    if (chosen) request("move-clip", { session_id: session.id, clip_id: chosen });
  };

  try {
    sessions = await loadSessions(projectId);
  } catch {
    return null; // the editor works on this clip alone without it
  }
  render(true);
  loadPictures().then(() => render());
  return {
    session: () => session,
    pictures: () => pictures,
    /** The editor's live layout ([{id, start, length}], seconds): blocks follow the open clip's edits. */
    setLayout: (value) => { layout = value; if (session) render(); },
    /** Another clip of the session is open now. */
    setCurrent: (id) => { clipId = id; if (sessions) render(); },
  };
}
