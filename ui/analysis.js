import { projectRequest, newProject, rememberProject } from "./projects.js";

const params = new URLSearchParams(location.search);
const projectId = params.get("project") || sessionStorage.getItem("clipmaker.active-match");
const view = params.get("view") === "tactical" ? "tactical" : "analyst";
const menu = document.querySelector("#analysis-menu");
const menuButton = document.querySelector("[data-analysis-menu]");
const setMenu = (open) => { menu.hidden = !open; menuButton.setAttribute("aria-expanded", String(open)); };
menuButton.onclick = () => setMenu(menu.hidden);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") setMenu(false); });
document.addEventListener("click", (event) => { if (!event.target.closest("#analysis-menu, [data-analysis-menu]")) setMenu(false); });
document.querySelector("[data-new-project]").onclick = async () => {
  try { const project = await newProject(); location.href = `/?project=${project.id}`; }
  catch (error) { document.querySelector("[data-analysis-status]").textContent = error.message; }
};
document.querySelectorAll("[data-view]").forEach((link) => {
  link.classList.toggle("is-active", link.dataset.view === view);
  link.href = `/analysis.html?view=${link.dataset.view}&project=${encodeURIComponent(projectId || "")}`;
});
const connect = async () => {
  try {
    if (!projectId) throw new Error("Open a project in Intake first.");
    const { project } = await projectRequest(`/api/projects/${encodeURIComponent(projectId)}`);
    rememberProject(project);
    document.querySelector("[data-analysis-project]").textContent = project.project_name || `${project.home_team} vs ${project.away_team}`;
    const result = await projectRequest("/api/analysis", { project_id: projectId, view });
    const frame = document.querySelector("[data-analysis-frame]");
    frame.src = result.url;
    frame.hidden = false;
    frame.addEventListener("load", () => { document.querySelector("[data-analysis-status]").textContent = "Workspace ready"; });
  } catch (error) {
    document.querySelector("[data-analysis-status]").textContent = "Setup needs attention";
    const output = document.querySelector("[data-analysis-error]");
    output.textContent = error.message;
    output.hidden = false;
  }
};
connect();
