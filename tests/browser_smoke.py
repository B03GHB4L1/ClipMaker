"""CI-only browser regression for the shared desktop UI."""
import json
import argparse
from pathlib import Path
import sys
import tempfile
import subprocess
import imageio_ffmpeg
import traceback
import faulthandler
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, fixture_csv, request
from playwright.sync_api import sync_playwright, expect


def stage(message):
    print(f"E2E: {message}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--server", type=Path, help="Frozen backend executable")
    choice.add_argument("--launcher", type=Path, help="Installed Homebrew launcher")
    parser.add_argument("--evidence", type=Path, default=ROOT / "build" / "browser-evidence")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error("timeout must be positive")
    faulthandler.dump_traceback_later(args.timeout_seconds, exit=True)
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    command = ([str(args.server.resolve())] if args.server else
               [str(args.launcher.resolve()), "--no-browser"] if args.launcher else
               [sys.executable, str(ROOT / "packaging" / "clipmaker_api_server.py")])
    with tempfile.TemporaryDirectory() as directory:
        stage("starting isolated backend")
        with backend(command, Path(directory) / "data", evidence, startup_timeout=600 if args.launcher else 90) as base:
            stage("backend ready; launching Chromium")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chromium", timeout=60000)
                context = browser.new_context(viewport={"width": 1280, "height": 800},
                                              reduced_motion="reduce",
                                              record_video_dir=str(evidence / "video"),
                                              record_video_size={"width": 640, "height": 400})
                context.tracing.start(screenshots=True, snapshots=True, sources=False)
                page = context.new_page()
                page.set_default_timeout(60000)
                page.set_default_navigation_timeout(60000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def log_console(message):
                    with (evidence / "console.log").open("a", encoding="utf-8") as output:
                        output.write(f"{message.type}: {message.text}\n")
                page.on("console", log_console)
                # Save diagnostics even when an assertion or navigation times out.
                def save_evidence():
                    try:
                        stage("saving screenshot and trace")
                        page.screenshot(path=str(evidence / "last-screen.png"))
                        (evidence / "last-page.html").write_text(page.content(), encoding="utf-8")
                        context.tracing.stop(path=str(evidence / "trace.zip"))
                        stage("closing browser context and recording")
                        context.close()
                    finally:
                        browser.close()
                try:
                    exercise(page, base, Path(directory), evidence, errors)
                except BaseException:
                    print(traceback.format_exc(), flush=True)
                    (evidence / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
                    (evidence / "result.json").write_text(json.dumps({"errors": errors, "status": "failed"}), encoding="utf-8")
                    raise
                finally:
                    save_evidence()
    faulthandler.cancel_dump_traceback_later()
    stage("finished")


def exercise(page, base, root, evidence, errors):
    stage("open intake and create project")
    page.goto(base)
    page.locator('[data-project-name]').wait_for()
    assert page.locator('[data-workflow-progress]').count() == 0
    page.evaluate('document.fonts.load(\'400 13px "Geist Mono"\')')
    assert page.evaluate('document.fonts.check(\'400 13px "Geist Mono"\')')
    assert "Geist Mono" in page.locator('body').evaluate('(element) => getComputedStyle(element).fontFamily')
    assert page.locator('#nav-drawer').get_attribute('inert') is not None
    page.get_by_role("button", name="New project", exact=True).click()
    page.locator('[data-toast]').filter(has_text="New local project created").wait_for()
    page.get_by_role("textbox", name="Project name").fill("Browser test project")
    page.get_by_role("textbox", name="Project name").press("Tab")
    page.get_by_role("status").filter(has_text="Saved locally").wait_for()
    project_id = parse_qs(urlparse(page.url).query)["project"][0]
    video = root / "keyboard-fixture.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=24", "-t", "8", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
    csv = root / "fixture.csv"
    csv.write_bytes(fixture_csv())
    stage("upload CSV and footage")
    page.locator('[data-csv-input]').set_input_files(str(csv))
    page.get_by_text("2 events found", exact=True).wait_for()
    page.locator('[data-video-input]').set_input_files(str(video))
    page.get_by_role("button", name="Play preview", exact=True).wait_for()
    for period in ("2H", "1H"):
        page.get_by_role("tab", name=period, exact=True).click()
        page.get_by_role("textbox", name="Selected period kick-off time").fill("00:00:00")
        page.get_by_role("textbox", name="Selected period kick-off time").press("Tab")
    expect(page.locator('[data-project-status]')).to_have_text("Saved locally", timeout=30000)
    page.reload()
    stage("verify saved intake and keyboard menu")
    expect(page.get_by_role("textbox", name="Project name")).to_have_value("Browser test project")
    page.get_by_role("button", name="Play preview", exact=True).wait_for()
    menu = page.get_by_role("button", name="Open navigation", exact=True)
    menu.press("Space")
    expect(menu).to_have_attribute("aria-expanded", "true")
    page.keyboard.press("Escape")
    expect(menu).to_have_attribute("aria-expanded", "false")
    assert page.locator('video[data-match-video]').evaluate('(video) => video.paused')
    page.screenshot(path=str(evidence / "intake.png"))
    assert page.locator('.brand').inner_text().replace("\n", "").replace(" ", "") == "VizorPlay•••"
    page.get_by_role("button", name="Confirm & continue").click()
    stage("filter and build clip plan")
    page.wait_for_url("**/filters.html?match=*")
    page.locator('[data-match-name]').filter(has_text="Home vs Away").wait_for()
    page.locator('#actions summary').click()
    page.locator('input[name="action"][value="Goal"]').check()
    page.locator('#timing summary').click()
    page.get_by_role("spinbutton", name="Seconds before", exact=True).fill("1")
    page.get_by_role("spinbutton", name="Seconds after", exact=True).fill("1")
    page.get_by_role("spinbutton", name="Merge gap", exact=True).fill("0")
    page.get_by_role("button", name="Preview clip plan").click()
    page.locator('[data-preview-count]').filter(has_text="1").wait_for()
    # Rendering the list precedes the awaited project write; hard refresh must
    # wait for the same completion state a user sees after saving.
    expect(page.locator('[data-summary-note]')).to_have_text("1 clips ready to review.", timeout=30000)
    expect(page.locator('[data-project-status]')).to_have_text("Saved locally", timeout=30000)
    page.reload()
    page.locator('[data-preview-count]').filter(has_text="1").wait_for()
    assert page.locator('input[name="action"][value="Goal"]').is_checked()
    expect(page.locator('[data-summary-note]')).to_have_text("1 clips ready to review.")
    page.locator('.clip-preview summary').click()
    page.get_by_role("spinbutton", name="End (video seconds)", exact=True).fill("3.5")
    page.get_by_role("button", name="Render preview", exact=True).click()
    stage("render edited preview")
    page.get_by_text("Preview ready", exact=True).wait_for(timeout=60000)
    page.wait_for_function("document.querySelector('.clip-preview video')?.videoWidth > 0")
    duration = page.locator('.clip-preview video').evaluate('(video) => video.duration')
    assert 2.3 <= duration <= 2.7, duration
    with page.expect_download() as download:
        page.get_by_role("link", name="Download clip", exact=True).click()
    preview = evidence / "preview.mp4"
    download.value.save_as(str(preview))
    decoded = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(preview),
                              "-f", "null", "-"], capture_output=True, timeout=60)
    assert decoded.returncode == 0 and preview.stat().st_size > 0, decoded.stderr
    stage("export reel and decode download")
    with page.expect_response(lambda response: urlparse(response.url).path == "/api/jobs" and response.request.method == "POST") as started:
        page.get_by_role("button", name="Export reel", exact=True).click()
    job_id = started.value.json()["job"]["id"]
    page.locator('[data-job-state]').filter(has_text="Export complete").wait_for(timeout=90000)
    job = request(base, "/api/jobs/" + job_id)["job"]
    assert job["status"] == "complete" and job["files"], job
    with page.expect_download() as download:
        page.locator('[data-export-files] a').first.click()
    exported = evidence / "export.mp4"
    download.value.save_as(str(exported))
    assert exported.stat().st_size == job["files"][0]["size"]
    decoded = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(exported),
                              "-f", "null", "-"], capture_output=True, timeout=60)
    assert decoded.returncode == 0, decoded.stderr
    expect(page.locator('[data-project-status]')).to_have_text("Saved locally", timeout=30000)
    page.reload()
    page.locator('[data-preview-count]').filter(has_text="1").wait_for()
    page.locator('.clip-preview summary').click()
    expect(page.get_by_role("spinbutton", name="End (video seconds)", exact=True)).to_have_value("3.5")
    page.screenshot(path=str(evidence / "filters.png"))
    stage("open analyst workspace")
    page.goto(base + "/analysis.html?view=analyst&project=" + project_id)
    frame = page.frame_locator('[data-analysis-frame]')
    frame.get_by_role("tab", name="◉ Shot Map").wait_for(timeout=60000)
    frame.get_by_role("tab", name="⇄ Comparison").click()
    page.screenshot(path=str(evidence / "analysis.png"))
    stage("open tactical workspace")
    page.goto(base + "/analysis.html?view=tactical&project=" + project_id)
    page.frame_locator('[data-analysis-frame]').get_by_role("tab", name="Style Profile").wait_for(timeout=60000)
    page.screenshot(path=str(evidence / "tactical.png"))
    stage("check responsive layouts")
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


if __name__ == "__main__":
    main()
