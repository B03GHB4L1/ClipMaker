// A chart filling the whole window (Analyst Room, Tactical Lab): the chart toolbar's
// "Full screen" button (save-clip.js plotlyConfig) opens a copy of the chart in a
// dialog over the page. Esc or the close button returns. The copy redraws to the
// window's size, so press F11 first for the whole screen.

/** Plotly toolbar icon: four corner brackets. */
export const FULLSCREEN_ICON = {
  width: 1000,
  height: 1000,
  path: "M0 0H380V110H110V380H0Z M620 0H1000V380H890V110H620Z M0 620H110V890H380V1000H0Z M890 620H1000V1000H620V890H890Z",
};

let styled = false;
const addStyle = () => {
  if (styled) return;
  styled = true;
  const style = document.createElement("style");
  style.textContent = `
.chart-fullscreen { width: 100vw; height: 100vh; max-width: none; max-height: none; margin: 0; padding: 0;
  border: 0; background: var(--cm-paper, #f5f0e8); color: var(--cm-ink, #151916); }
.chart-fullscreen::backdrop { background: rgba(0, 0, 0, 0.6); }
.chart-fullscreen-bar { display: flex; justify-content: flex-end; gap: 8px; padding: 8px 12px; }
.chart-fullscreen-close { padding: 6px 14px; border: 1px solid currentColor; border-radius: 999px;
  background: transparent; color: inherit; font: inherit; font-size: 12px; cursor: pointer; }
.chart-fullscreen-close:focus-visible { outline: 2px solid var(--cm-accent, #4d6b00); outline-offset: 2px; }
.chart-fullscreen-plot { width: 100%; height: calc(100vh - 52px); }`;
  document.head.append(style);
};

/** Open `chart` (a drawn Plotly element) over the whole window. `config` is the toolbar to keep. */
export const openChartFullscreen = (chart, config = {}, Plotly = window.Plotly) => {
  if (!Plotly || !chart?.data) return null;
  addStyle();
  const dialog = document.createElement("dialog");
  dialog.className = "chart-fullscreen";
  dialog.setAttribute("aria-label", "Chart, full screen");
  const bar = document.createElement("div");
  bar.className = "chart-fullscreen-bar";
  const close = document.createElement("button");
  close.type = "button";
  close.className = "chart-fullscreen-close";
  close.textContent = "Close full screen (Esc)";
  close.onclick = () => dialog.close();
  bar.append(close);
  const plot = document.createElement("div");
  plot.className = "chart-fullscreen-plot";
  dialog.append(bar, plot);
  document.body.append(dialog);
  dialog.addEventListener("close", () => { Plotly.purge(plot); dialog.remove(); });
  dialog.showModal();
  // A fixed width and height in the layout would keep the chart small: let it fill the dialog.
  const layout = { ...chart.layout, width: undefined, height: undefined, autosize: true };
  const buttons = (config.modeBarButtonsToAdd || []).filter((button) => button?.name !== "fullscreen");
  Plotly.newPlot(plot, chart.data, layout, { ...config, modeBarButtonsToAdd: buttons, responsive: true });
  close.focus();
  return dialog;
};
