"""Optional real-provider batch UI acceptance, including an invalid URL."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, request
from playwright.sync_api import sync_playwright, expect


def main():
    source_url = os.environ.get("SCORESWAY_URL", "").strip() or os.environ.get("WHOSCORED_URL", "").strip()
    if not source_url:
        raise SystemExit("A real provider URL is required; this is not a passed batch test")
    evidence = ROOT / "build/live-evidence/batch"
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"status": "running"}
    try:
        with tempfile.TemporaryDirectory() as directory:
            with backend([sys.executable, str(ROOT / "packaging/clipmaker_api_server.py")], Path(directory), evidence) as base:
                original = request(base, "/api/projects", {"name": "Preserve existing batch project"})["project"]
                request(base, f"/api/projects/{original['id']}", {"markers": {"1H": "00:00:11"}})
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    context = browser.new_context(viewport={"width": 1280, "height": 800})
                    page = context.new_page()
                    try:
                        page.goto(f"{base}/?project={original['id']}")
                        expect(page.locator('[data-project-name]')).to_have_value("Preserve existing batch project")
                        page.locator('.batch-import summary').click()
                        # The failure comes first: processing must continue to the real scrape.
                        page.locator('[data-batch-urls]').fill("https://example.com/not-a-provider\n" + source_url)
                        page.locator('[data-batch-fetch]').click()
                        expect(page.locator('[data-batch-fetch]')).to_be_enabled(timeout=240000)
                        expect(page.locator('[data-batch-status]')).to_contain_text("1 matches saved.")
                        expect(page.locator('[data-batch-status]')).to_contain_text("1:")
                        projects = request(base, "/api/projects")["projects"]
                        successful = [item for item in projects if item.get("source_url") == source_url and item.get("event_count", 0) > 0]
                        assert len(successful) == 1, projects
                        saved = request(base, f"/api/projects/{original['id']}")["project"]
                        assert saved["project_name"] == "Preserve existing batch project"
                        assert saved["markers"]["1H"] == "00:00:11"
                        assert original["id"] != successful[0]["id"]
                        expect(page).to_have_url(f"{base}/?project={successful[0]['id']}")
                        page.reload()
                        expect(page.locator('[data-event-count]')).to_contain_text("events found")
                        result = {"status": "passed", "events": successful[0]["event_count"],
                                  "partial_failure_reported": True, "prior_project_preserved": True}
                    finally:
                        page.screenshot(path=str(evidence / "last-screen.png"))
                        (evidence / "last-page.html").write_text(page.content(), encoding="utf-8")
                        context.close()
                        browser.close()
    except BaseException as error:
        result.update(status="failed", error=str(error))
        raise
    finally:
        (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
