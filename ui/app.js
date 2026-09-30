import * as THREE from "./vendor/three.module.js";

const body = document.body;
const drawerButton = document.querySelector("[data-drawer-toggle]");
const drawer = document.querySelector("#nav-drawer");
const overlay = document.querySelector("[data-drawer-overlay]");
const toast = document.querySelector("[data-toast]");
let toastTimer;

const showToast = (message) => {
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2600);
};

const setDrawer = (open) => {
  body.classList.toggle("drawer-open", open);
  drawerButton.setAttribute("aria-expanded", String(open));
  drawer.setAttribute("aria-hidden", String(!open));
};

drawerButton.addEventListener("click", () =>
  setDrawer(!body.classList.contains("drawer-open")),
);
overlay.addEventListener("click", () => setDrawer(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setDrawer(false);
});
document
  .querySelectorAll(".drawer-link")
  .forEach((link) => link.addEventListener("click", () => setDrawer(false)));

window.addEventListener("load", () =>
  requestAnimationFrame(() => body.classList.add("is-loaded")),
);

const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  },
  { rootMargin: "0px 0px -10% 0px", threshold: 0.08 },
);
document
  .querySelectorAll(".reveal")
  .forEach((element) => observer.observe(element));

document.querySelector("[data-fetch]").addEventListener("click", (event) => {
  const button = event.currentTarget;
  button.textContent = "···";
  document.querySelector("[data-match-ticket]").style.opacity = ".35";
  setTimeout(() => {
    button.textContent = "✓";
    document.querySelector("[data-match-ticket]").style.opacity = "1";
    showToast("Match data refreshed: 1,486 events found");
  }, 700);
});

document
  .querySelector("[data-dropzone]")
  .addEventListener("click", () =>
    document.querySelector("[data-video-input]").click(),
  );
const videoInput = document.querySelector("[data-video-input]");
const matchVideo = document.querySelector("[data-match-video]");
const matchFrame = document.querySelector(".match-frame");
const previewName = document.querySelector(".preview-top span:first-child");
const previewDuration = document.querySelector(".preview-top span:last-child");
let videoUrl;
videoInput.addEventListener("change", () => {
  const file = videoInput.files[0];
  if (!file) return;
  if (videoUrl) URL.revokeObjectURL(videoUrl);
  videoUrl = URL.createObjectURL(file);
  matchVideo.src = videoUrl;
  matchFrame.classList.add("has-video");
  document.querySelector("[data-file-row]").hidden = false;
  document.querySelector(".file-info strong").textContent = file.name;
  document.querySelector(".file-info small").textContent =
    `${(file.size / 1073741824).toFixed(1)} GB · local file`;
  previewName.textContent = file.name;
  showToast("Footage loaded locally. It never leaves this device.");
});
matchVideo.addEventListener("loadedmetadata", () => {
  previewDuration.textContent = formatTime(matchVideo.duration);
});
document.querySelector(".remove-button").addEventListener("click", () => {
  document.querySelector("[data-file-row]").hidden = true;
  matchVideo.pause();
  matchVideo.removeAttribute("src");
  matchFrame.classList.remove("has-video");
  if (videoUrl) URL.revokeObjectURL(videoUrl);
  videoUrl = undefined;
  videoInput.value = "";
  showToast("Video removed from this setup");
});
document
  .querySelector("[data-new-project]")
  .addEventListener("click", () => showToast("New project workspace ready"));
document
  .querySelector("[data-continue]")
  .addEventListener("click", () =>
    showToast("Timeline confirmed. Event filtering is next."),
  );

const timeline = document.querySelector("[data-timeline]");
const playhead = document.querySelector("[data-playhead]");
const timeLabels = document.querySelectorAll(
  "[data-time], [data-timeline-time]",
);
const scrubCursor = document.querySelector(".scrub-cursor");
let scrubbing = false;
const formatTime = (seconds) => {
  const safeSeconds = Number.isFinite(seconds)
    ? Math.max(0, Math.round(seconds))
    : 0;
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const secs = safeSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
};
const updateTimeline = (clientX) => {
  const bounds = timeline.getBoundingClientRect();
  const ratio = Math.max(
    0,
    Math.min(1, (clientX - bounds.left) / bounds.width),
  );
  playhead.style.left = `${ratio * 100}%`;
  const seconds =
    ratio * (Number.isFinite(matchVideo.duration) ? matchVideo.duration : 600);
  if (matchFrame.classList.contains("has-video"))
    matchVideo.currentTime = seconds;
  const value = formatTime(seconds);
  timeLabels.forEach((label) => {
    label.textContent = value;
  });
};
timeline.addEventListener("pointerdown", (event) => {
  scrubbing = true;
  timeline.setPointerCapture(event.pointerId);
  updateTimeline(event.clientX);
});
timeline.addEventListener("pointermove", (event) => {
  scrubCursor.style.left = `${event.clientX}px`;
  scrubCursor.style.top = `${event.clientY}px`;
  if (scrubbing) updateTimeline(event.clientX);
});
timeline.addEventListener("pointerup", () => {
  scrubbing = false;
});
timeline.addEventListener("pointerenter", () =>
  scrubCursor.classList.add("is-visible"),
);
timeline.addEventListener("pointerleave", () => {
  scrubbing = false;
  scrubCursor.classList.remove("is-visible");
});
document.querySelector(".text-button").addEventListener("click", () => {
  playhead.style.left = "32%";
  timeLabels.forEach((label) => {
    label.textContent = "00:03:18";
  });
  showToast("Kick-off marker reset");
});
document.querySelector(".play-button").addEventListener("click", (event) => {
  const playing = event.currentTarget.textContent === "Ⅱ";
  if (matchFrame.classList.contains("has-video")) {
    if (playing) matchVideo.pause();
    else matchVideo.play();
  }
  event.currentTarget.textContent = playing ? "▶" : "Ⅱ";
  event.currentTarget.setAttribute(
    "aria-label",
    playing ? "Play preview" : "Pause preview",
  );
});

const periodLabels = {
  "1H": "First-half kick-off",
  "2H": "Second-half kick-off",
  ET1: "Extra-time first-half kick-off",
  ET2: "Extra-time second-half kick-off",
  PEN: "First penalty kick",
};
document
  .querySelectorAll(".period-selector [data-period]")
  .forEach((button) => {
    button.addEventListener("click", () => {
      document
        .querySelectorAll(".period-selector [data-period]")
        .forEach((item) => {
          const selected = item === button;
          item.classList.toggle("is-active", selected);
          item.setAttribute("aria-selected", String(selected));
        });
      document.querySelector("[data-period-label]").textContent =
        periodLabels[button.dataset.period];
      timeLabels.forEach((label) => {
        label.textContent = button.dataset.marker;
      });
      const seconds = button.dataset.marker
        .split(":")
        .reduce((total, part) => total * 60 + Number(part), 0);
      if (Number.isFinite(matchVideo.duration)) {
        matchVideo.currentTime = Math.min(seconds, matchVideo.duration);
        playhead.style.left = `${(matchVideo.currentTime / matchVideo.duration) * 100}%`;
      }
    });
  });

const filterEvents = () => {
  const query = document
    .querySelector("[data-event-search]")
    .value.trim()
    .toLowerCase();
  const period = document.querySelector("[data-period-filter]").value;
  document.querySelectorAll("[data-event-body] tr").forEach((row) => {
    row.hidden = !(
      (period === "all" || row.dataset.period === period) &&
      row.textContent.toLowerCase().includes(query)
    );
  });
};
document
  .querySelector("[data-event-search]")
  .addEventListener("input", filterEvents);
document
  .querySelector("[data-period-filter]")
  .addEventListener("change", filterEvents);

const heroBall = document.querySelector("[data-hero-ball]");
const reducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)",
).matches;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
camera.position.z = 6.6;
const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(heroBall.clientWidth, heroBall.clientHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
heroBall.appendChild(renderer.domElement);

const textureCanvas = document.createElement("canvas");
textureCanvas.width = 1024;
textureCanvas.height = 512;
const textureContext = textureCanvas.getContext("2d");
textureContext.fillStyle = "#d9d9d5";
textureContext.fillRect(0, 0, 1024, 512);
textureContext.strokeStyle = "#60635e";
textureContext.lineWidth = 9;
for (let x = -100; x < 1124; x += 150) {
  for (let y = -70; y < 600; y += 130) {
    textureContext.beginPath();
    for (let side = 0; side < 6; side += 1) {
      const angle = (Math.PI / 3) * side;
      const px = x + (y % 260 ? 75 : 0) + Math.cos(angle) * 52;
      const py = y + Math.sin(angle) * 52;
      if (side === 0) textureContext.moveTo(px, py);
      else textureContext.lineTo(px, py);
    }
    textureContext.closePath();
    textureContext.stroke();
  }
}
const ballTexture = new THREE.CanvasTexture(textureCanvas);
ballTexture.colorSpace = THREE.SRGBColorSpace;
const ballGroup = new THREE.Group();
const sphere = new THREE.Mesh(
  new THREE.SphereGeometry(1.56, 96, 64),
  new THREE.MeshPhysicalMaterial({
    map: ballTexture,
    color: 0xf5f6ef,
    metalness: 0.72,
    roughness: 0.14,
    clearcoat: 1,
    clearcoatRoughness: 0.08,
  }),
);
ballGroup.add(sphere);
const badgeCanvas = document.createElement("canvas");
badgeCanvas.width = 768;
badgeCanvas.height = 320;
const badgeContext = badgeCanvas.getContext("2d");
badgeContext.fillStyle = "#10120e";
badgeContext.font = "800 210px Arial";
badgeContext.textAlign = "center";
badgeContext.fillText("CM", 330, 230);
badgeContext.fillStyle = "#c8f135";
badgeContext.font = "800 76px Arial";
badgeContext.fillText("1.3", 610, 112);
const badgeTexture = new THREE.CanvasTexture(badgeCanvas);
badgeTexture.colorSpace = THREE.SRGBColorSpace;
const badge = new THREE.Mesh(
  new THREE.PlaneGeometry(1.7, 0.71),
  new THREE.MeshBasicMaterial({ map: badgeTexture, transparent: true }),
);
badge.position.z = 1.68;
ballGroup.add(badge);
scene.add(ballGroup);
scene.add(new THREE.HemisphereLight(0xffffff, 0x575b50, 2.8));
const rimLight = new THREE.DirectionalLight(0xc8f135, 5);
rimLight.position.set(-3, 2, 4);
scene.add(rimLight);
const keyLight = new THREE.DirectionalLight(0xffffff, 7);
keyLight.position.set(4, 4, 5);
scene.add(keyLight);
const renderBall = () => {
  if (!reducedMotion) {
    ballGroup.rotation.y = Math.sin(performance.now() * 0.00022) * 0.12;
    ballGroup.rotation.x = Math.sin(performance.now() * 0.00035) * 0.06;
  }
  renderer.render(scene, camera);
  requestAnimationFrame(renderBall);
};
renderBall();
new ResizeObserver(() => {
  renderer.setSize(heroBall.clientWidth, heroBall.clientHeight);
}).observe(heroBall);
