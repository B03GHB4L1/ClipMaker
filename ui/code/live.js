// Live recording on the Code screen (docs/CODING_AND_PITCH_PLAN.md, L1). The engine records
// 2-second MP4 segments; this plays them while recording continues, through Media Source
// Extensions, so the analyst can pause and rewind behind the live edge. Only the segments
// around the playhead are kept in memory: a 90-minute match does not fit in the browser's
// media buffer, so going back further fetches those segments again.
import { formatVideo } from "./clock.js";

export const AHEAD = 30;   // seconds buffered past the playhead
export const BEHIND = 90;  // seconds kept before it
export const RECORDING_STATES = new Set(["connecting", "waiting", "recording", "reconnecting"]);

/** Indexes of the segments that cover [time, time + ahead), in order. */
export const wanted = (segments, time, ahead = AHEAD) =>
  segments.filter((item) => item.start + item.duration > time && item.start < time + ahead).map((item) => item.i);

/** Where to jump when `time` sits in a hole under half a second wide before a buffered range; else null. */
export const holeEnd = (ranges, time) => {
  for (let index = 0; index < ranges.length; index += 1) {
    const start = ranges.start(index);
    if (time >= start) continue;
    const before = index === 0 ? 0 : ranges.end(index - 1);
    return time >= before - 0.05 && start - time < 0.5 ? start + 0.01 : null;
  }
  return null;
};

export const formatBytes = (bytes) => {
  const gb = bytes / 1024 ** 3;
  return gb >= 10 ? `${Math.round(gb)} GB` : gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(0, Math.round(bytes / 1024 ** 2))} MB`;
};

/** One line saying what the recording is doing, for the bar above the video. */
export const liveSummary = (live) => {
  const recorded = formatVideo(live.recorded_seconds || 0);
  const free = live.free_bytes ? ` · ${formatBytes(live.free_bytes)} free` : "";
  const gaps = (live.gaps || []).filter((gap) => gap.length != null);
  const breaks = gaps.length ? ` · ${gaps.length} ${gaps.length === 1 ? "break" : "breaks"} in the stream` : "";
  switch (live.state) {
    case "connecting": return `Connecting to ${live.source}...`;
    case "waiting": return `Waiting for a stream. In OBS or your phone app, send to ${live.push_address} (any stream key).`;
    case "recording": return `Recording ${recorded}${breaks}${free}`;
    case "reconnecting": return `The stream dropped at ${recorded}; recording resumes when it comes back${free}`;
    case "joining": return `Saving the recording (${recorded})...`;
    default: return live.error || "";
  }
};

const once = (target, name) => new Promise((resolve) => target.addEventListener(name, resolve, { once: true }));

export class LivePlayer {
  constructor(video, urlFor) {
    this.video = video;
    this.urlFor = urlFor; // (segment or {part, file}) -> URL
    this.segments = [];
    this.codecs = {};     // part -> "avc1...,mp4a.40.2"
    this.held = new Set(); // segment indexes in the media buffer
    this.initPart = null;
    this.busy = false;
    this.source = null;
    this.buffer = null;
  }

  get end() {
    const last = this.segments[this.segments.length - 1];
    return last ? last.start + last.duration : 0;
  }

  add(segments, codecs) {
    Object.assign(this.codecs, codecs || {});
    for (const item of segments) {
      if (item.i === this.segments.length) this.segments.push(item);
    }
  }

  mime(part) {
    return `video/mp4; codecs="${this.codecs[part] || "avc1.640028,mp4a.40.2"}"`;
  }

  async open() {
    const first = this.segments[0];
    if (!first) return false;
    const type = this.mime(first.part);
    if (!window.MediaSource || !MediaSource.isTypeSupported(type)) {
      throw new Error("This system cannot play the stream while it records. It is still being recorded and can be played once saved.");
    }
    this.source = new MediaSource();
    this.url = URL.createObjectURL(this.source);
    this.video.src = this.url;
    await once(this.source, "sourceopen");
    this.buffer = this.source.addSourceBuffer(type);
    this.buffer.mode = "sequence"; // each segment goes where timestampOffset says, whatever its own timestamps
    return true;
  }

  close() {
    this.video.removeAttribute("src");
    this.video.load();
    if (this.url) URL.revokeObjectURL(this.url);
    this.source = this.buffer = null;
  }

  async append(data) {
    this.buffer.appendBuffer(data);
    await once(this.buffer, "updateend");
  }

  async fetch(item) {
    const response = await fetch(this.urlFor(item));
    if (!response.ok) throw new Error("A piece of the recording could not be read.");
    return response.arrayBuffer();
  }

  async load(index) {
    const item = this.segments[index];
    if (item.part !== this.initPart) {
      if (this.initPart && this.codecs[item.part] !== this.codecs[this.initPart] && this.buffer.changeType) {
        this.buffer.changeType(this.mime(item.part));
      }
      await this.append(await this.fetch({ part: item.part, file: "init.mp4" }));
      this.initPart = item.part;
    }
    const data = await this.fetch(item);
    this.buffer.timestampOffset = item.start;
    try {
      await this.append(data);
    } catch (error) {
      if (error.name !== "QuotaExceededError") throw error;
      await this.evict(0);
      await this.append(data);
    }
    this.held.add(index);
  }

  /** Drop what is far from the playhead; `keep` seconds are kept behind it. */
  async evict(keep = BEHIND) {
    const time = this.video.currentTime;
    const ranges = [[0, time - keep], [time + AHEAD * 3, Infinity]];
    for (const [from, to] of ranges) {
      if (to <= from || to <= 0) continue;
      const buffered = this.buffer.buffered;
      if (!buffered.length || buffered.start(0) >= to || buffered.end(buffered.length - 1) <= from) continue;
      this.buffer.remove(Math.max(0, from), Math.min(to, this.source.duration || to));
      await once(this.buffer, "updateend");
      for (const index of [...this.held]) {
        const item = this.segments[index];
        if (item.start < to && item.start + item.duration > from) this.held.delete(index);
      }
    }
  }

  /** Called every second: buffer what the playhead needs next, drop what it does not. */
  async pump() {
    if (this.busy) return;
    this.busy = true;
    try {
      if (!this.buffer && !(await this.open())) return;
      if (!this.buffer.updating && this.source.readyState === "open" && !(this.source.duration >= this.end)) {
        this.source.duration = this.end;
      }
      for (const index of wanted(this.segments, this.video.currentTime)) {
        if (!this.held.has(index)) await this.load(index);
      }
      await this.evict();
      this.skipHole();
    } finally {
      this.busy = false;
    }
  }

  /** A segment's audio or video can end a few frames short of the next segment's start;
   * playback would stall in that hole, so step over it. */
  skipHole() {
    if (!this.buffer || this.source?.readyState !== "open") return;
    const time = this.video.currentTime;
    const next = holeEnd(this.buffer.buffered, time);
    if (next !== null) this.video.currentTime = next;
  }

  /** Back to the live edge, a segment behind so playback does not stall at once. */
  toEdge() {
    this.video.currentTime = Math.max(0, this.end - 3);
    this.video.play().catch(() => {});
  }
}
