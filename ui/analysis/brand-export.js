// The VizorPlay credit on every exported chart picture: a footer strip under the
// chart, in the chart's own background colour, with the VizorPlay mark and
// wordmark in the bottom-right corner. Used by the Plotly save button
// (ui/save-clip.js) and by the map component's PNG and GIF exports.

const BRAND = "/assets/brand/";
const cache = new Map();

const loadImage = (src) => {
  if (!cache.has(src)) {
    cache.set(src, new Promise((resolve, reject) => {
      const image = new Image();
      image.decoding = "async";
      image.onload = () => resolve(image);
      image.onerror = () => { cache.delete(src); reject(new Error("Could not load the VizorPlay logo.")); };
      image.src = src;
    }));
  }
  return cache.get(src);
};

/** The mark and wordmark for light and dark backgrounds, loaded once. */
export const loadBrand = async () => {
  const [mark, word, markDark, wordDark] = await Promise.all(
    ["vizorplay-mark.svg", "vizorplay-wordmark.svg", "vizorplay-mark-on-dark.svg", "vizorplay-wordmark-on-dark.svg"]
      .map((name) => loadImage(BRAND + name)));
  return { light: { mark, word }, dark: { mark: markDark, word: wordDark } };
};

const toCanvas = async (source) => {
  if (source instanceof HTMLCanvasElement) return source;
  const url = typeof source === "string" ? source : URL.createObjectURL(source);
  try {
    const image = await loadImage(url);
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    canvas.getContext("2d").drawImage(image, 0, 0);
    return canvas;
  } finally {
    cache.delete(url);
    if (typeof source !== "string") URL.revokeObjectURL(url);
  }
};

// The chart's background: the colour of its bottom-left corner.
const backgroundOf = (canvas) => {
  const [r, g, b, a] = canvas.getContext("2d", { willReadFrequently: true }).getImageData(1, canvas.height - 2, 1, 1).data;
  if (a < 200) return { fill: "#ffffff", dark: false };
  const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  return { fill: `rgb(${r},${g},${b})`, dark: luminance < 0.5 };
};

/** A copy of `canvas` with the credit strip under it (synchronous, for GIF frames). */
export const brandCanvas = (canvas, brand) => {
  const { fill, dark } = backgroundOf(canvas);
  const { mark, word } = dark ? brand.dark : brand.light;
  const width = canvas.width;
  // The strip scales with the picture: about 4.5% of its width, never cramped or loud.
  const strip = Math.round(Math.min(110, Math.max(40, width * 0.045)));
  const out = document.createElement("canvas");
  out.width = width;
  out.height = canvas.height + strip;
  const ctx = out.getContext("2d");
  ctx.fillStyle = fill;
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(canvas, 0, 0);
  // A hairline separates the credit from the chart.
  ctx.fillStyle = dark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)";
  ctx.fillRect(Math.round(strip * 0.5), canvas.height, width - strip, Math.max(1, Math.round(strip / 60)));
  const markHeight = strip * 0.5;
  const markWidth = markHeight * (mark.naturalWidth / mark.naturalHeight || 2.19);
  const wordHeight = strip * 0.3;
  const wordWidth = wordHeight * (word.naturalWidth / word.naturalHeight || 4.71);
  const gap = strip * 0.18;
  const right = width - strip * 0.5;
  const middle = canvas.height + strip / 2;
  ctx.drawImage(word, right - wordWidth, middle - wordHeight / 2, wordWidth, wordHeight);
  ctx.drawImage(mark, right - wordWidth - gap - markWidth, middle - markHeight / 2, markWidth, markHeight);
  return out;
};

/** The PNG of `source` (a canvas, Blob or data/blob URL of a picture) with the credit strip. */
export const brandPicture = async (source) => {
  const [canvas, brand] = await Promise.all([toCanvas(await source), loadBrand()]);
  const branded = brandCanvas(canvas, brand);
  return new Promise((resolve, reject) => branded.toBlob(
    (blob) => (blob ? resolve(blob) : reject(new Error("Could not make the picture."))), "image/png"));
};
