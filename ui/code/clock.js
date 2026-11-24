// Video time to match clock for the Code screen's list, mirroring app/coding/to_events.py
// (the engine writes the event table; this only labels what the analyst sees).

export const PERIODS = [
  { number: 1, key: "1H", name: "1st half", offset: 0 },
  { number: 2, key: "2H", name: "2nd half", offset: 45 * 60 },
  { number: 3, key: "ET1", name: "Extra time 1", offset: 90 * 60 },
  { number: 4, key: "ET2", name: "Extra time 2", offset: 105 * 60 },
  { number: 5, key: "PEN", name: "Penalties", offset: 120 * 60 },
];

/** "1:02:03", "62:03" or "3723" as seconds; null when unset or unreadable. */
export const parseMarker = (value) => {
  const text = String(value ?? "").trim();
  if (!text) return null;
  const parts = text.split(":").map(Number);
  if (parts.length > 3 || parts.some((part) => !Number.isFinite(part) || part < 0)) return null;
  return parts.reduce((total, part) => total * 60 + part, 0);
};

/** The file each period plays from, as the engine's video_for_period chooses it. */
export const videoOf = (project, number) => {
  const videos = project.period_videos || {};
  if (number === 1) return project.video_path || "";
  const key = { 2: "2H", 3: "ET1", 4: "ET2", 5: "PEN" }[number];
  return videos[key] || (number === 4 ? videos.ET1 : "") || videos["2H"] || project.video_path || "";
};

/** Which videos the analyst can code on: the main file, then each period with a file of its own. */
export const sources = (project) => {
  const list = [{ key: "1H", path: project.video_path || "" }];
  for (const period of PERIODS.slice(1)) {
    const path = (project.period_videos || {})[period.key];
    if (path && !list.some((item) => item.path === path)) list.push({ key: period.key, path });
  }
  return list.filter((item) => item.path);
};

/** {period, clock} for a video time on source `src`, or null before the first kick-off on that file. */
export const place = (project, src, seconds) => {
  const source = videoOf(project, PERIODS.find((period) => period.key === src)?.number ?? 1);
  let best = null;
  for (const period of PERIODS) {
    const start = parseMarker((project.markers || {})[period.key]);
    if (start === null || start > seconds + 1e-6 || videoOf(project, period.number) !== source) continue;
    if (!best || start >= best.start) best = { period, start };
  }
  return best ? { period: best.period, clock: best.period.offset + Math.round(seconds - best.start) } : null;
};

export const formatClock = (clock) => `${Math.floor(clock / 60)}:${String(clock % 60).padStart(2, "0")}`;

export const formatVideo = (seconds) => {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const secs = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
};

/** Hotkeys never act while the analyst types in a field. */
export const isTyping = (target) => Boolean(target?.closest?.("input, textarea, select, [contenteditable=''], [contenteditable='true']"));
