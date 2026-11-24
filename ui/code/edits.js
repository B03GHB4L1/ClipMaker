// Editing coded events on the Code screen: interval start and stop, nudging,
// and undo. Pure functions, so tests/code.test.mjs can check them.

const round = (seconds) => Math.round(seconds * 1000) / 1000;

/** Undo and redo of steps; a step is [{id, prev, next}] with a label for the status line. */
export class History {
  constructor(limit = 200) { this.limit = limit; this.done = []; this.undone = []; }
  push(steps, label) {
    this.done.push({ steps, label });
    if (this.done.length > this.limit) this.done.shift();
    this.undone = [];
  }
  undo() { const step = this.done.pop(); if (step) this.undone.push(step); return step || null; }
  redo() { const step = this.undone.pop(); if (step) this.done.push(step); return step || null; }
  get canUndo() { return this.done.length > 0; }
  get canRedo() { return this.undone.length > 0; }
}

/** Running intervals of a group (an interval code's group defaults to its own id). */
export const runningIn = (events, codes, group) => events.filter((event) => event.end === null
  && (codes.find((code) => code.id === event.code)?.group || event.code) === group);

/**
 * Press an interval code at video time `at`: stop it if it runs for this team,
 * otherwise stop whatever runs in its group and start it.
 * Returns {changes: [{id, next}], started: event | null}.
 */
export const toggleInterval = (events, codes, code, team, src, at, newId) => {
  const stop = (event) => ({ id: event.id, next: { ...event, end: event.src === src ? round(Math.max(event.t, at)) : event.t } });
  const mine = events.find((event) => event.code === code.id && event.team === team && event.end === null);
  if (mine) return { changes: [stop(mine)], started: null };
  const changes = runningIn(events, codes, code.group || code.id).map(stop);
  const started = { id: newId(), code: code.id, team, src, t: round(at), end: null };
  changes.push({ id: started.id, next: started });
  return { changes, started };
};

/**
 * What a code's links do when it is pressed at `at` for `team` (C3): it stops
 * the intervals it names (whoever they run for) and starts others for the same
 * or the other team, stopping what runs in their group. A start for an interval
 * already running for that team changes nothing. Returns [{id, next}].
 */
export const linkedChanges = (events, codes, code, team, src, at, newId) => {
  const changes = new Map();
  const current = () => events.map((event) => changes.get(event.id) || event).concat(
    [...changes.values()].filter((event) => !events.some((item) => item.id === event.id)));
  const stopIt = (event) => changes.set(event.id, { ...event, end: event.src === src ? round(Math.max(event.t, at)) : event.t });
  for (const target of code.stops || []) {
    current().filter((event) => event.code === target && event.end === null).forEach(stopIt);
  }
  const other = team === "home" ? "away" : team === "away" ? "home" : "";
  for (const link of code.starts || []) {
    const target = codes.find((item) => item.id === link.code);
    const side = link.team === "other" ? other : team;
    if (!target || target.kind !== "interval") continue;
    if (current().some((event) => event.code === target.id && event.team === side && event.end === null)) continue;
    runningIn(current(), codes, target.group || target.id).forEach(stopIt);
    const started = { id: newId(), code: target.id, team: side, src, t: round(at), end: null };
    changes.set(started.id, started);
  }
  return [...changes.entries()].map(([id, next]) => ({ id, next }));
};

/** The tag list with `tagId` switched on or off; switching one on drops the others of its group. */
export const toggledTags = (current, tags, tagId) => {
  const list = current || [];
  if (list.includes(tagId)) return list.filter((id) => id !== tagId);
  const group = tags.find((tag) => tag.id === tagId)?.group;
  const kept = group ? list.filter((id) => tags.find((tag) => tag.id === id)?.group !== group) : list;
  return [...kept, tagId];
};

/** Tags a new event starts with: its code's own, then the armed ones (a later tag of a group wins). */
export const startingTags = (code, armed, tags) => {
  let list = [];
  for (const id of [...(code.tags || []), ...armed]) {
    if (!list.includes(id)) list = toggledTags(list, tags, id);
  }
  return list;
};

/** "9 Saka" lines (or "9, Saka", "9 - Saka") to [{number, name}]; throws with the line that is wrong. */
export const parseSquad = (text) => {
  const players = [];
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const match = line.match(/^#?(\d{1,2})\s*[,.\-:]?\s*(.*)$/);
    if (!match) throw new Error(`"${line.slice(0, 30)}": start each line with a shirt number.`);
    const number = Number(match[1]);
    if (players.some((player) => player.number === number)) throw new Error(`Shirt number ${number} is listed twice.`);
    players.push({ number, name: match[2].trim().slice(0, 40) });
  }
  return players.sort((a, b) => a.number - b.number);
};

export const squadText = (players) => (players || []).map((player) => `${player.number} ${player.name}`.trim()).join("\n");

/** The event with its start (`edge` "t") or end moved by `seconds`, or null when that is not possible. */
export const nudged = (event, edge, seconds, duration = Infinity) => {
  if (edge === "end") {
    if (event.end == null) return null;
    const end = round(Math.min(duration, Math.max(event.t, event.end + seconds)));
    return end === event.end ? null : { ...event, end };
  }
  const t = round(Math.min(event.end ?? duration, Math.max(0, event.t + seconds)));
  return t === event.t ? null : { ...event, t };
};
