// Keeps the sound output open while someone is working with video.
//
// After a pause longer than about 30 seconds, the browser engine has closed its
// audio output, and on some computers reopening it takes 2-3 seconds. Pressing
// play then froze the picture until the sound caught up. A running but silent
// audio stream keeps the output open, so play starts at once.
//
// It starts on the first play on a page, stops when the page is hidden, and
// stops after IDLE_MS without any play, pause or seek, so it never keeps the
// sound device busy for long when nobody is watching.
const IDLE_MS = 5 * 60 * 1000;
let context = null;
let idleTimer = null;
const mark = (state) => { document.documentElement.dataset.audioWarm = state; };

const release = () => {
  clearTimeout(idleTimer);
  idleTimer = null;
  if (context) context.close().catch(() => {});
  context = null;
  mark("off");
};

const touch = () => {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(release, IDLE_MS);
};

const hold = async () => {
  if (context || typeof AudioContext === "undefined") return;
  try {
    const opened = new AudioContext();
    // Far below hearing, and below the level the browser counts as sound, but
    // not exact silence, which some engines skip rendering.
    const gain = opened.createGain();
    gain.gain.value = 0.00001;
    const tone = opened.createOscillator();
    tone.connect(gain).connect(opened.destination);
    tone.start();
    await opened.resume();
    if (opened.state !== "running") { opened.close().catch(() => {}); return; }
    context = opened;
    mark("on");
  } catch {
    // No audio output: the video still plays as before.
  }
};

// Media events do not bubble, so listen while they travel down to the video.
document.addEventListener("play", (event) => {
  if (!(event.target instanceof HTMLMediaElement)) return;
  touch();
  if (!document.hidden) hold();
}, true);
for (const name of ["pause", "seeked"]) {
  document.addEventListener(name, (event) => {
    if (event.target instanceof HTMLMediaElement && context) touch();
  }, true);
}
document.addEventListener("visibilitychange", () => { if (document.hidden) release(); });
window.addEventListener("pagehide", release);
mark("off");
