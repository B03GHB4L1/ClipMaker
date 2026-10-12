"""CI-only browser regression for the shared desktop UI."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, fixture_csv, request
from playwright.sync_api import sync_playwright, expect


def main():
    evidence = ROOT / "build" / "browser-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        with backend([sys.executable, str(ROOT / "packaging" / "clipmaker_api_server.py")], Path(directory)) as base:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base)
                page.locator('[data-project-name]').wait_for()
                assert page.locator('[data-workflow-progress]').count() == 0
                assert page.locator('#nav-drawer').get_attribute('inert') is not None
                page.get_by_role("button", name="New project", exact=True).click()
                page.locator('[data-toast]').filter(has_text="New local project created").wait_for()
                page.get_by_role("textbox", name="Project name").fill("Browser test project")
                page.get_by_role("textbox", name="Project name").press("Tab")
                page.get_by_role("status").filter(has_text="Saved locally").wait_for()
                project_id = page.url.split("project=", 1)[1]
                request(base, f"/api/files/upload?project={project_id}", raw=fixture_csv(),
                        headers={"Content-Type": "application/octet-stream", "X-File-Name": "fixture.csv"})
                request(base, f"/api/projects/{project_id}", {"markers": {"1H": "00:00:00", "2H": "00:00:00"}})
                page.reload()
                expect(page.get_by_role("textbox", name="Project name")).to_have_value("Browser test project")
                page.screenshot(path=str(evidence / "intake.png"))
                assert page.locator('.brand').inner_text().replace("\n", "").replace(" ", "") == "CM1.3•••"
                page.get_by_role("button", name="Confirm & continue").click()
                page.wait_for_url("**/filters.html?match=*")
                page.locator('[data-match-name]').filter(has_text="Home vs Away").wait_for()
                page.locator('#actions summary').click()
                page.locator('input[name="action"][value="Goal"]').check()
                page.get_by_role("button", name="Preview clip plan").click()
                page.locator('[data-preview-count]').filter(has_text="1").wait_for()
                page.reload()
                page.locator('[data-preview-count]').filter(has_text="1").wait_for()
                assert page.locator('input[name="action"][value="Goal"]').is_checked()
                page.screenshot(path=str(evidence / "filters.png"))
                page.goto(base + "/analysis.html?view=analyst&project=" + project_id)
                frame = page.frame_locator('[data-analysis-frame]')
                frame.get_by_role("tab", name="◉ Shot Map").wait_for(timeout=60000)
                frame.get_by_role("tab", name="⇄ Comparison").click()
                page.screenshot(path=str(evidence / "analysis.png"))
                page.goto(base + "/analysis.html?view=tactical&project=" + project_id)
                page.frame_locator('[data-analysis-frame]').get_by_role("tab", name="Style Profile").wait_for(timeout=60000)
                page.screenshot(path=str(evidence / "tactical.png"))
                for width, height in ((1021, 572), (614, 542), (390, 700)):
                    page.set_viewport_size({"width": width, "height": height})
                    page.goto(base + "/?project=" + project_id)
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    assert page.locator('.app-footer').is_visible()
                    page.screenshot(path=str(evidence / f"intake-{width}.png"))
                    page.goto(base + "/filters.html?match=" + project_id)
                    page.locator('[data-match-name]').filter(has_text="Home vs Away").wait_for()
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    expect(page.get_by_role("navigation", name="Workflow").get_by_role("link")).to_have_count(4)
                    page.locator('#export-settings summary').click()
                    page.screenshot(path=str(evidence / f"filters-{width}.png"))
                assert not errors, errors
                (evidence / "result.json").write_text(json.dumps({"errors": errors, "status": "passed"}), encoding="utf-8")
                browser.close()


if __name__ == "__main__":
    main()
