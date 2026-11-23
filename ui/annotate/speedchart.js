// Speed over time for a followed player (docs/CODING_AND_PITCH_PLAN.md, P3c): the line the panel shows
// under "Speed on the pitch" and the picture that is saved or sent to the clip. Pure drawing on a canvas context.

/** The speeds as runs of [seconds, km/h] (a gap where the speed is unknown breaks the line) and the top of the scale. */
export const speedSeries = (motion, fps) => {
  const runs = [];
  let run = [];
  motion.speeds.forEach((kmh, index) => {
    if (kmh === null || kmh === undefined) {
      if (run.length) runs.push(run);
      run = [];
      return;
    }
    run.push([(motion.from + index) / fps, kmh]);
  });
  if (run.length) runs.push(run);
  const top = Math.max(0, ...runs.flat().map(([, kmh]) => kmh));
  return { runs, ceiling: Math.max(10, Math.ceil(top / 5) * 5) };
};

const PAPER = { background: "#f8f6f0", ink: "#2b2b2a", muted: "#6b6a66", rule: "#d9d6cc", line: "#2f6fd6", marker: "#c0392b" };

export const SPEED_PAPER = PAPER;

/**
 * Draw the chart in a `width` x `height` box. `colours` has background (or null for transparent), ink, muted,
 * rule, line and marker; `frame` puts a marker on the playhead; `title` and `scale` (text size) are for the saved picture.
 */
export const drawSpeedChart = (ctx, width, height, motion, fps, { colours = PAPER, frame = null, title = "", scale = 1 } = {}) => {
  const { runs, ceiling } = speedSeries(motion, fps);
  const text = Math.round(11 * scale);
  const left = Math.round(40 * scale);
  const right = Math.round(12 * scale);
  const top = Math.round((title ? 34 : 10) * scale);
  const bottom = Math.round(24 * scale);
  const [pw, ph] = [width - left - right, height - top - bottom];
  ctx.save();
  if (colours.background) { ctx.fillStyle = colours.background; ctx.fillRect(0, 0, width, height); } else ctx.clearRect(0, 0, width, height);
  ctx.font = `${text}px sans-serif`;
  if (title) { ctx.fillStyle = colours.ink; ctx.font = `600 ${Math.round(14 * scale)}px sans-serif`; ctx.textBaseline = "top"; ctx.fillText(title, left, Math.round(8 * scale)); ctx.font = `${text}px sans-serif`; }
  const points = runs.flat();
  const [t0, t1] = points.length ? [points[0][0], points[points.length - 1][0]] : [0, 1];
  const span = Math.max(t1 - t0, 0.5);
  const x = (seconds) => left + ((seconds - t0) / span) * pw;
  const y = (kmh) => top + ph - (kmh / ceiling) * ph;
  ctx.lineWidth = Math.max(1, scale);
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  for (let kmh = 0; kmh <= ceiling; kmh += ceiling / 5) {
    ctx.strokeStyle = colours.rule; ctx.beginPath(); ctx.moveTo(left, y(kmh)); ctx.lineTo(left + pw, y(kmh)); ctx.stroke();
    ctx.fillStyle = colours.muted; ctx.fillText(String(Math.round(kmh)), left - 6 * scale, y(kmh));
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const step = span > 20 ? 5 : span > 8 ? 2 : 1;
  for (let s = Math.ceil(t0 / step) * step; s <= t1; s += step) ctx.fillText(`${s}s`, x(s), top + ph + 6 * scale);
  ctx.textAlign = "left";
  ctx.fillStyle = colours.muted;
  ctx.fillText("km/h", 4 * scale, top - 2 * scale - text);
  if (!points.length) {
    ctx.fillStyle = colours.muted; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("No speed to show yet", left + pw / 2, top + ph / 2);
    ctx.restore();
    return;
  }
  ctx.strokeStyle = colours.line; ctx.lineWidth = 2 * scale; ctx.lineJoin = "round";
  runs.forEach((run) => {
    if (run.length < 2) return;
    ctx.beginPath();
    run.forEach(([s, kmh], i) => (i ? ctx.lineTo(x(s), y(kmh)) : ctx.moveTo(x(s), y(kmh))));
    ctx.stroke();
  });
  if (frame !== null) {
    const s = frame / fps;
    if (s >= t0 && s <= t1) { ctx.strokeStyle = colours.marker; ctx.lineWidth = Math.max(1, scale); ctx.beginPath(); ctx.moveTo(x(s), top); ctx.lineTo(x(s), top + ph); ctx.stroke(); }
  }
  ctx.restore();
};
