// The sequence track (docs/CODING_AND_PITCH_PLAN.md, T2): the session's clips and cards in play order on one strip,
// each block as long as it plays once exported. Click a clip to open it, a card to edit it, drag a block (or
// Alt+arrow) to reorder, add a clip from another session or a picture / text card, play the whole run, and export it
// as one video. Sessions live in the project (app/telestration/clips.py, sessions.json).
import { projectRequest } from "../projects.js";
import { editorUrl, loadSessions } from "./library.js";

const enc = encodeURIComponent;
const sessionsPath = (projectId) => `/api/editor-sessions/${enc(projectId)}`;
const picturesPath = (projectId) => `/api/projects/${enc(projectId)}/pictures`;
export const CARD_SECONDS = [0.5, 30];
export const CARD_TEXT = 200;
const PLAY_KEY = "vizorplay.sequence-play";
const PLAY_FRESH_MS = 20000; // a hand-over to the next clip must arrive within this

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

/** Each block as fractions of the strip: [{id, start, width}], end to end in order. */
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

/** What follows `id` in the session's items, or null at the end: [{kind: "clip"|"card", ...}]. */
export const itemAfter = (items, id) => {
  const at = items.findIndex((item) => item.id === id);
  return at >= 0 ? items[at + 1] || null : null;
};

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

/** The picture of a text card, drawn at the sequence's frame size: light text centred on dark green. Resolves a PNG blob. */
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

/** Hand the play-through on to the clip `clipId`: it starts by itself when it opens (within a few seconds). */
export const handOver = (projectId, sessionId, clipId) => {
  try { sessionStorage.setItem(PLAY_KEY, JSON.stringify({ projectId, sessionId, clipId, at: Date.now() })); } catch { /* no storage: no hand-over */ }
};
const handedOver = (projectId, clipId) => {
  try {
    const value = JSON.parse(sessionStorage.getItem(PLAY_KEY) || "null");
    if (value && value.projectId === projectId && value.clipId === clipId && Date.now() - value.at < PLAY_FRESH_MS) return value;
  } catch { /* nothing handed over */ }
  return null;
};
const stopHandOver = () => { try { sessionStorage.removeItem(PLAY_KEY); } catch { /* nothing to remove */ } };

/**
 * Show the sequence of the session holding `clipId` in `root` ([data-sequence]).
 * `onExport(session)` exports it; `beforeLeave()` saves the open clip before another opens;
 * `stage` is the element a card is shown over while a play-through is on a card.
 * Returns {session(), resumed, endOfClip(), stop()}: the session (null when none), whether this page was opened by a
 * play-through, and the hook the editor calls when its clip has played to the end.
 */
export async function showSequence(root, projectId, clipId, { onExport, beforeLeave, onError, stage, onPlay }) {
  const lane = root.querySelector("[data-sequence-lane]");
  const add = root.querySelector("[data-sequence-add]");
  const exportButton = root.querySelector("[data-sequence-export]");
  const playButton = root.querySelector("[data-sequence-play]");
  const name = root.querySelector("[data-sequence-name]");
  const cardButton = root.querySelector("[data-sequence-card]");
  const form = root.querySelector("[data-card-form]");
  let sessions;
  let session;
  let pictures = [];
  let editing = null; // the card being edited, or "new"
  let playing = false;
  let timer = null;
  let shown = null;

  const request = async (action, body) => {
    try {
      sessions = (await projectRequest(`${sessionsPath(projectId)}/${action}`, body)).sessions;
      render();
      return true;
    } catch (problem) {
      onError(problem.message);
      render();
      return false;
    }
  };

  const open = async (event, clip) => {
    event.preventDefault();
    if (clip.id === clipId) return;
    stopHandOver();
    await beforeLeave();
    location.href = editorUrl(projectId, clip.id);
  };

  const pictureName = (id) => pictures.find((picture) => picture.id === id)?.name || "Picture";
  const cardLabel = (card) => (card.type === "picture" ? pictureName(card.picture_id) : `“${card.text}”`);
  const cardTitle = (card) => `${card.type === "picture" ? "Picture" : "Text"} card · ${cardLabel(card)} · ${clock(card.seconds)}`;

  const render = () => {
    session = sessions.find((entry) => entry.clips.some((clip) => clip.id === clipId)) || null;
    root.hidden = !session;
    if (!session) return;
    name.textContent = session.name;
    const items = session.items;
    const layout = sequenceLayout(items);
    const blocks = items.map((item, index) => {
      const holder = el("li", "annotate-sequence-item");
      holder.style.left = `${layout[index].start * 100}%`;
      holder.style.width = `${layout[index].width * 100}%`;
      const card = item.kind === "card";
      const block = el(card ? "button" : "a", `annotate-sequence-block${card ? " is-card" : ""}`);
      if (card) block.type = "button"; else block.href = editorUrl(projectId, item.id);
      block.title = `${card ? cardTitle(item) : `${item.name} · ${clock(clipSeconds(item))}`}. ${card ? "Click to edit it. " : ""}Drag, or Alt and an arrow key, to move it.`;
      block.dataset.index = String(index);
      block.draggable = false; // a pointer drag reorders; the browser's link drag would not
      if (item.id === clipId) block.setAttribute("aria-current", "page");
      if (card && editing === item.id) block.setAttribute("aria-pressed", "true");
      block.append(el("span", "annotate-sequence-index", String(index + 1)),
        el("span", "annotate-block-label", card ? `${cardLabel(item)} · ${clock(item.seconds)}` : `${item.name} · ${clock(clipSeconds(item))}`));
      block.onclick = (event) => {
        if (block.dataset.dragged) { event.preventDefault(); delete block.dataset.dragged; return; }
        if (card) editCard(item); else open(event, item);
      };
      block.onkeydown = (event) => {
        if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
        event.preventDefault();
        const to = index + (event.key === "ArrowLeft" ? -1 : 1);
        if (to < 0 || to >= items.length) return;
        reorder(index, to, item.id);
      };
      wireDrag(block, index, layout);
      holder.append(block);
      return holder;
    });
    lane.replaceChildren(...blocks);
    exportButton.disabled = items.length < 2;
    exportButton.title = items.length < 2 ? "Add another clip or a card to export a sequence" : `Export all ${items.length} entries, in this order, as one video`;
    playButton.disabled = items.length < 2 && !playing;
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

  form.querySelector("[data-card-kind]").onchange = syncKind;
  form.onsubmit = async (event) => {
    event.preventDefault();
    const kind = field("kind").value;
    const seconds = Number(field("seconds").value);
    const text = field("text").value.trim();
    if (!(seconds >= CARD_SECONDS[0] && seconds <= CARD_SECONDS[1])) return fail(`Show a card for ${CARD_SECONDS[0]} to ${CARD_SECONDS[1]} seconds.`);
    if (kind === "text" && !text) return fail("Type the words the card shows.");
    if (kind === "picture" && !field("picture").value) return fail("Add a picture to the project first, in the picture panel.");
    const card = kind === "picture" ? { kind, picture_id: field("picture").value, seconds } : { kind, text, seconds };
    const ok = editing === "new"
      ? await request("add-card", { session_id: session.id, card, index: session.items.length })
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
    render();
    const focus = () => lane.querySelector(`[data-index="${order.indexOf(focusId)}"]`)?.focus();
    focus();
    request("reorder", { session_id: session.id, clips: order }).then(focus);
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
      if (to !== index) reorder(index, to, session.items[index].id);
    };
    block.addEventListener("pointerup", finish);
    block.addEventListener("pointercancel", finish);
  };

  add.onchange = () => {
    const chosen = add.value;
    if (chosen) request("move-clip", { session_id: session.id, clip_id: chosen });
  };
  exportButton.onclick = () => { if (session) onExport(session); };

  // ----- play across the sequence (T2 step 4) -------------------------------
  const clearShown = () => {
    clearTimeout(timer);
    timer = null;
    shown?.remove();
    shown = null;
    stage?.classList.remove("is-card");
  };
  const setPlaying = (value) => {
    playing = value;
    playButton.setAttribute("aria-pressed", String(value));
    playButton.querySelector("[data-play-label]").textContent = value ? "Stop" : "Play";
    playButton.title = value ? "Stop playing the sequence" : "Play every clip and card in this order, from this clip";
    render();
  };
  const stop = () => {
    stopHandOver();
    clearShown();
    if (playing) setPlaying(false);
  };
  const showCard = (card, then) => {
    clearShown();
    shown = el("div", "annotate-card-show");
    if (card.type === "picture") {
      const picture = pictures.find((item) => item.id === card.picture_id);
      if (picture) shown.append(Object.assign(el("img"), { src: picture.url, alt: "" }));
    } else {
      shown.append(el("p", "", card.text));
    }
    stage?.append(shown);
    stage?.classList.add("is-card");
    timer = setTimeout(then, card.seconds * 1000);
  };
  // Play on from the entry after `id`: a card is shown for its seconds; a clip is opened (and starts by itself).
  const goOn = async (id) => {
    const next = itemAfter(session.items, id);
    if (!next) { stop(); return; }
    if (next.kind === "card") { showCard(next, () => goOn(next.id)); return; }
    handOver(projectId, session.id, next.id);
    await beforeLeave();
    location.href = editorUrl(projectId, next.id);
  };
  playButton.onclick = async () => {
    if (!session) return;
    if (playing) { stop(); return; }
    await loadPictures();
    setPlaying(true);
    onPlay();
  };

  try {
    sessions = await loadSessions(projectId);
  } catch {
    return null; // the sequence is a convenience; the editor works without it
  }
  render();
  loadPictures().then(render);
  const resumed = Boolean(session && handedOver(projectId, clipId));
  if (resumed) { stopHandOver(); setPlaying(true); }
  return {
    session: () => session,
    resumed,
    playing: () => playing,
    /** The editor's clip has played to its end: go on to the next entry when a play-through is on. */
    endOfClip: () => { if (playing && session) goOn(clipId); },
    stop,
  };
}
