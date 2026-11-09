// Hosts the original map component (app/smp_component/frontend) without
// Streamlit. The component talks to its parent with three postMessage types:
// componentReady, setFrameHeight and setComponentValue; the host answers with
// "streamlit:render" carrying the same args the Python wrappers sent.

const COMPONENT_URL = "/analysis-component/index.html";

export class ComponentHost {
  constructor(container, { onValue = () => {}, title = "Match map" } = {}) {
    this.onValue = onValue;
    this.ready = false;
    this.pendingArgs = null;
    this.frame = document.createElement("iframe");
    this.frame.className = "analysis-component";
    this.frame.title = title;
    this.frame.setAttribute("scrolling", "no");
    this.frame.style.height = "120px";
    this.listener = (event) => this.receive(event);
    window.addEventListener("message", this.listener);
    this.readyPromise = new Promise((resolve) => { this.resolveReady = resolve; });
    this.frame.src = COMPONENT_URL;
    container.append(this.frame);
  }

  receive(event) {
    // Accept messages only from this host's own frame.
    if (event.source !== this.frame.contentWindow) return;
    const message = event.data;
    if (!message || typeof message !== "object" || !message.isStreamlitMessage) return;
    if (message.type === "streamlit:componentReady") {
      this.ready = true;
      this.resolveReady();
      if (this.pendingArgs) this.post(this.pendingArgs);
    } else if (message.type === "streamlit:setFrameHeight") {
      const height = Number(message.height);
      if (Number.isFinite(height) && height > 0) this.frame.style.height = `${Math.ceil(height)}px`;
    } else if (message.type === "streamlit:setComponentValue") {
      this.onValue(message.value);
    }
  }

  post(args) {
    this.frame.contentWindow.postMessage({ type: "streamlit:render", args, dataframes: [], disabled: false }, location.origin);
  }

  render(args) {
    this.pendingArgs = args;
    if (this.ready) this.post(args);
    return this.readyPromise;
  }

  destroy() {
    window.removeEventListener("message", this.listener);
    this.frame.remove();
  }
}
