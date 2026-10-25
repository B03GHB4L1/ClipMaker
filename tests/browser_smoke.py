"""CI-only browser regression for the shared desktop UI."""
import json
import argparse
import struct
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


def validate_chart_download(download, destination, image_format):
    """Accept a real browser download, including decoding when Pillow is installed."""
    assert download.failure() is None, f"{image_format} download failed"
    assert Path(download.suggested_filename).suffix.lower() == "." + image_format.lower(), download.suggested_filename
    download.save_as(str(destination))
    data = destination.read_bytes()
    assert len(data) > 1024, f"{destination.name}: suspiciously small ({len(data)} bytes)"
    if image_format == "PNG":
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"{destination.name}: invalid PNG signature"
        assert data[12:16] == b"IHDR", f"{destination.name}: missing PNG header"
        assert data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"), f"{destination.name}: incomplete PNG"
        dimensions = struct.unpack(">II", data[16:24])
    else:
        assert image_format == "GIF", image_format
        assert data[:6] in (b"GIF87a", b"GIF89a"), f"{destination.name}: invalid GIF signature"
        assert data.endswith(b";"), f"{destination.name}: incomplete GIF"
        dimensions = struct.unpack("<HH", data[6:10])
    assert min(dimensions) >= 200, f"{destination.name}: unexpected chart dimensions {dimensions}"
    result = {"filename": download.suggested_filename, "bytes": len(data), "dimensions": dimensions,
              "format": image_format, "pillow_decoded": False}
    try:
        from PIL import Image
    except ImportError:
        stage(f"{destination.name}: signature/size/dimensions passed; Pillow unavailable for decoding")
    else:
        with Image.open(destination) as image:
            assert image.format == image_format and image.size == dimensions, destination.name
            image.verify()
        # Reopen after verify(), then force every frame to decode, not just its header.
        with Image.open(destination) as image:
            frames = getattr(image, "n_frames", 1)
            if image_format == "GIF":
                assert frames >= 2, f"{destination.name}: expected a multi-frame GIF, got {frames}"
            for index in range(frames):
                image.seek(index)
                image.load()
            assert any(low < high for low, high in image.convert("RGB").getextrema()), f"{destination.name}: blank chart"
        result.update(pillow_decoded=True, frames=frames)
    return result


def exercise_event_tables(page):
    stage("search intake events and filter the full event dialog by period")
    page.locator('.event-browser summary').click()
    rows = page.locator('[data-event-body] tr:visible')
    expect(rows).to_have_count(2)
    page.locator('[data-event-search]').fill("  gOaL  ")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("One")
    page.locator('[data-period-filter]').select_option("2")
    expect(rows).to_have_count(0)
    page.locator('[data-period-filter]').select_option("1")
    expect(rows).to_have_count(1)
    page.locator('[data-event-search]').fill("")
    page.locator('[data-period-filter]').select_option("all")
    expect(rows).to_have_count(2)

    page.locator('[data-open-table]').click()
    dialog = page.locator('[data-event-dialog]')
    expect(dialog).to_be_visible()
    expect(dialog.locator('[data-table-title]')).to_have_text("Home vs Away")
    full_rows = dialog.locator('[data-full-event-body] tr:visible')
    count = dialog.locator('[data-full-row-count]')
    expect(count).to_have_text("2 rows shown", timeout=30000)
    expect(full_rows).to_have_count(2)
    dialog.locator('[data-full-event-search]').fill("  tWo  ")
    expect(full_rows).to_have_count(1)
    expect(full_rows.first).to_contain_text("Pass")
    expect(count).to_have_text("1 rows shown")
    dialog.locator('[data-full-period-filter]').select_option("2")
    expect(full_rows).to_have_count(0)
    expect(count).to_have_text("0 rows shown")
    dialog.locator('[data-full-period-filter]').select_option("1")
    expect(full_rows).to_have_count(1)
    dialog.locator('[data-full-event-search]').fill("no matching fixture event")
    expect(count).to_have_text("0 rows shown")
    expect(full_rows).to_have_count(0)
    dialog.locator('[data-full-event-search]').fill("")
    dialog.locator('[data-full-period-filter]').select_option("all")
    expect(full_rows).to_have_count(2)
    expect(count).to_have_text("2 rows shown")
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    page.locator('[data-open-table]').click()
    expect(count).to_have_text("2 rows shown")
    expect(full_rows).to_have_count(2)
    dialog.get_by_role("button", name="Done", exact=True).click()
    expect(dialog).not_to_be_visible()
    page.locator('.event-browser summary').click()


def exercise_snapshot_restore(page):
    stage("save filter snapshot, change selection/timing, and restore after reload")
    snapshot_name = "Browser goal timing"
    page.locator('#snapshots summary').click()
    page.locator('[data-snapshot-name]').fill(snapshot_name)
    page.locator('[data-save-snapshot]').click()
    expect(page.locator('[data-toast]')).to_have_text("Saved snapshot: " + snapshot_name)
    expect(page.locator('[data-snapshot-select]')).to_have_value(snapshot_name)
    page.locator('input[name="action"][value="Goal"]').uncheck()
    page.locator('input[name="action"][value="Pass"]').check()
    page.get_by_role("spinbutton", name="Seconds before", exact=True).fill("4")
    page.get_by_role("spinbutton", name="Seconds after", exact=True).fill("2")
    page.get_by_role("spinbutton", name="Merge gap", exact=True).fill("2")
    expect(page.locator('[data-summary-actions]')).to_have_text("Pass")
    expect(page.locator('[data-project-status]')).to_have_text("Saved locally", timeout=30000)
    page.reload()
    # Wait for project restoration as well as the snapshot library before using it.
    expect(page.locator('[data-summary-actions]')).to_have_text("Pass")
    expect(page.locator('input[name="action"][value="Pass"]')).to_be_checked()
    page.locator('#snapshots summary').click()
    page.locator('[data-snapshot-select]').select_option(snapshot_name)
    expect(page.locator('[data-load-snapshot]')).to_be_enabled()
    page.locator('[data-load-snapshot]').click()
    expect(page.locator('[data-toast]')).to_have_text("Loaded snapshot: " + snapshot_name)
    expect(page.locator('input[name="action"][value="Goal"]')).to_be_checked()
    expect(page.locator('input[name="action"][value="Pass"]')).not_to_be_checked()
    # Reload collapses the detailed controls; assert their saved values directly.
    expect(page.locator('[data-before-buffer]')).to_have_value("1")
    expect(page.locator('[data-after-buffer]')).to_have_value("1")
    expect(page.locator('[data-min-gap]')).to_have_value("0")
    expect(page.locator('[data-summary-actions]')).to_have_text("Goal")
    expect(page.locator('[data-project-status]')).to_have_text("Saved locally", timeout=30000)
    page.locator('#snapshots summary').click()


def exercise_analyst_chart(page, frame, evidence):
    stage("download and validate real Analyst chart PNG and multi-frame GIF")
    shots = frame.get_by_role("tabpanel", name="◉ Shot Map", exact=True)
    chart = shots.frame_locator('iframe[title="smp_component.analyst_room"]')
    plot = chart.locator('#plot')
    expect(plot.locator('canvas')).not_to_have_count(0, timeout=60000)
    png_button = chart.locator('[data-export="png"]')
    expect(png_button).to_be_visible(timeout=60000)
    results = []
    with page.expect_download(timeout=30000) as downloaded:
        png_button.click()
    results.append(validate_chart_download(downloaded.value, evidence / "analyst-shot-map.png", "PNG"))
    # Build exercises the worker encoder and frame capture through the actual UI.
    chart.locator('[data-export-animation]').select_option("build")
    gif_button = chart.locator('[data-export="gif"]')
    with page.expect_download(timeout=90000) as downloaded:
        gif_button.click()
    results.append(validate_chart_download(downloaded.value, evidence / "analyst-shot-map.gif", "GIF"))
    expect(gif_button).to_be_enabled()
    expect(gif_button).to_have_text("GIF")
    (evidence / "analyst-downloads.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    stage("click the plotted fixture goal and clear the Analyst selection")
    # Read ECharts' public coordinate API, then send a real mouse click. Do not
    # dispatch a synthetic chart action or inject Streamlit selection messages.
    position = plot.evaluate("""element => {
        const chart = window.echarts.getInstanceByDom(element);
        for (const [seriesIndex, series] of chart.getOption().series.entries()) {
            const point = (series.data || []).find(point => point && point.customdata === 0);
            if (point) {
                const [x, y] = chart.convertToPixel({seriesIndex}, point.value);
                return {x, y};
            }
        }
        throw new Error('Fixture goal missing from the rendered shot map');
    }""")
    plot.click(position=position)
    clear = shots.get_by_role("button", name="Clear selection", exact=True)
    expect(clear).to_be_visible(timeout=30000)
    expect(shots.locator('.cm-shot-panel')).to_contain_text("One")
    expect(shots.locator('.cm-shot-panel')).to_contain_text("Home")
    clear.click()
    expect(clear).not_to_be_visible(timeout=30000)
    expect(shots.locator('.cm-shot-panel')).to_have_count(0)


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
    exercise_event_tables(page)
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
    exercise_snapshot_restore(page)
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
    exercise_analyst_chart(page, frame, evidence)
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
