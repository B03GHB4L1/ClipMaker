// Clip timeline rules shared by the Filter page editor. No DOM here, so the
// browser test can check them directly.

export const MIN_CLIP = 1; // seconds
export const MAX_CLIP = 600; // the engine refuses longer preview renders

export const round1 = (value) => Math.round(value * 10) / 10;

// Give every saved clip a stable id and remember the engine's original window,
// so a trimmed clip can be reset. Older projects saved neither.
export const normaliseClips = (windows = []) => {
  const used = new Set();
  let next = Math.max(0, ...windows.map((clip) => Number(clip?.id) || 0)) + 1;
  return windows
    .filter((clip) => clip && Number.isFinite(Number(clip.start)) && Number.isFinite(Number(clip.end)))
    .map((clip) => {
      let id = Number(clip.id);
      if (!Number.isInteger(id) || id < 1 || used.has(id)) id = next++;
      used.add(id);
      const start = Number(clip.start);
      const end = Number(clip.end);
      return {
        id,
        start,
        end,
        label: String(clip.label || "Edited clip"),
        period: Number(clip.period) || 1,
        source_start: Number.isFinite(Number(clip.source_start)) ? Number(clip.source_start) : start,
        source_end: Number.isFinite(Number(clip.source_end)) ? Number(clip.source_end) : end,
      };
    });
};

// Move one edge of a clip, keeping it at least MIN_CLIP long, inside the
// footage (0 .. limit) and no longer than MAX_CLIP.
export const trimClip = (clip, edge, seconds, limit = Infinity) => {
  const ceiling = Number.isFinite(limit) && limit > 0 ? limit : Infinity;
  if (edge === "start") {
    const earliest = Math.max(0, clip.end - MAX_CLIP);
    const start = round1(Math.min(Math.max(seconds, earliest), clip.end - MIN_CLIP));
    return { ...clip, start: Math.max(0, start) };
  }
  const latest = Math.min(ceiling, clip.start + MAX_CLIP);
  return { ...clip, end: round1(Math.max(Math.min(seconds, latest), clip.start + MIN_CLIP)) };
};

export const isTrimmed = (clip) =>
  Math.abs(clip.start - clip.source_start) > 0.05 || Math.abs(clip.end - clip.source_end) > 0.05;

export const duration = (clip) => Math.max(0, clip.end - clip.start);

export const totalDuration = (clips) => clips.reduce((total, clip) => total + duration(clip), 0);

// The windows sent to the export job. Each keeps its timeline number, so a
// selected set saved as separate files is named like the clips on screen.
export const exportWindows = (clips, scope = "all", selected = new Set()) =>
  clips
    .map((clip, index) => ({ clip, number: index + 1 }))
    .filter(({ clip }) => scope !== "selected" || selected.has(clip.id))
    .map(({ clip, number }) => ({
      start: clip.start,
      end: clip.end,
      label: clip.label,
      period: clip.period,
      number,
    }));

// Older projects saved a first/last range instead of a set of clips.
export const restoreSelection = (saved = {}, clips = []) => {
  const ids = new Set(clips.map((clip) => clip.id));
  if (Array.isArray(saved.selected)) {
    return new Set(saved.selected.map(Number).filter((id) => ids.has(id)));
  }
  const first = Number(saved.first) || 1;
  const last = Number(saved.last) || clips.length;
  if (first <= 1 && last >= clips.length) return new Set();
  return new Set(clips.slice(Math.max(0, first - 1), last).map((clip) => clip.id));
};

export const formatClock = (seconds, tenths = true) => {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const rest = value % 60;
  const secs = tenths ? rest.toFixed(1).padStart(4, "0") : String(Math.floor(rest)).padStart(2, "0");
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}`
    : `${minutes}:${secs}`;
};

// Accepts 54:31.5, 1:02:03 or plain seconds.
export const parseClock = (text) => {
  const value = String(text).trim();
  if (/^\d+(\.\d+)?$/.test(value)) return Number(value);
  if (!/^\d+(:\d{1,2}){1,2}(\.\d+)?$/.test(value)) return NaN;
  const parts = value.split(":").map(Number);
  if (parts.slice(1).some((part) => part >= 60)) return NaN;
  return parts.reduce((total, part) => total * 60 + part, 0);
};
