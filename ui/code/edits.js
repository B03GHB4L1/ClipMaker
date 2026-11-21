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
