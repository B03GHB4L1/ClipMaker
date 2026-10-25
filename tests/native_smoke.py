"""CI-only installed Tauri window test; Windows/Linux, never a browser substitute."""
import argparse
import faulthandler
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import fixture_csv, request
from analysis_server import wait_for_process_exit


def export_finished(driver):
    # WebDriver .text applies CSS text-transform; textContent is the actual label.
    label = driver.find_element("css selector", "[data-job-state]").get_attribute("textContent").strip()
    if label in {"Export failed", "Job cancelled", "Could not build plan", "Setup needs attention"}:
        logs = driver.find_element("css selector", "[data-job-logs]").get_attribute("textContent")
        raise AssertionError(f"{label}: {logs}")
    return label == "Export complete"


def stage(evidence, message):
    print(f"Native E2E: {message}", flush=True)
    with (evidence / "stages.log").open("a", encoding="utf-8") as output:
        output.write(f"{time.time():.3f} {message}\n")


def verify_shutdown(health, evidence, launch):
    result = {}
    for key in ("desktop_owner_pid", "pid", "parent_pid"):
        pid = health.get(key)
        if not isinstance(pid, int) or pid <= 0:
            raise AssertionError(f"Missing native process identity: {key}")
        result[key] = {"pid": pid, "exited": wait_for_process_exit(pid, timeout=30)}
        (evidence / f"shutdown-{launch}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        assert result[key]["exited"], f"Native process still running after window close: {result}"


def package_lifecycle(app, package, uninstall=False):
    if sys.platform == "win32":
        if uninstall:
            candidates = list(app.parent.glob("*ninstall*.exe"))
            if len(candidates) != 1:
                raise RuntimeError("Expected exactly one installed NSIS uninstaller")
            command = [str(candidates[0]), "/S"]
        else:
            command = [str(package), "/S", f"/D={app.parent}"]
    else:
        if uninstall:
            name = subprocess.run(["dpkg-deb", "--field", str(package), "Package"],
                                  check=True, capture_output=True, text=True, timeout=15).stdout.strip()
            if not name or name[0] not in "abcdefghijklmnopqrstuvwxyz0123456789" or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789+-." for char in name):
                raise RuntimeError("Invalid Debian package name")
            command = ["sudo", "apt-get", "remove", "-y", name]
        else:
            command = ["sudo", "apt-get", "install", "--reinstall", "-y", str(package)]
    subprocess.run(command, check=True, timeout=120,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)


def wait_for_driver(process, port, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("tauri-driver exited; see driver.log")
        try:
            with urlopen(f"http://127.0.0.1:{port}/status", timeout=1) as response:
                status = json.load(response)
            if status.get("value", {}).get("ready"):
                return
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    raise TimeoutError("The native WebDriver did not report ready")


def ready_element(driver, wait, selector):
    target = wait.until(lambda current: current.find_element("css selector", selector))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'})", target)
    def clickable(current):
        target = current.find_element("css selector", selector)
        return target if target.is_displayed() and target.is_enabled() else False
    return wait.until(clickable)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--package", type=Path, help="CI-only NSIS/DEB reinstall and uninstall acceptance")
    parser.add_argument("--evidence", type=Path, default=ROOT / "build/native-evidence")
    args = parser.parse_args()
    if sys.platform not in {"win32", "linux"}:
        parser.error("This native Tauri driver test supports only Windows/Linux; macOS uses the Homebrew browser workflow")
    if not args.app.is_file():
        parser.error("Installed application executable not found")
    if args.package:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            parser.error("Package lifecycle testing is restricted to disposable GitHub runners")
        args.package = args.package.resolve()
        if not args.package.is_file() or args.package.suffix != (".exe" if sys.platform == "win32" else ".deb"):
            parser.error("Expected an existing package for this platform")
    args.app = args.app.resolve()
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.options import ArgOptions
    from selenium.webdriver.remote.client_config import ClientConfig
    from selenium.webdriver.remote.remote_connection import RemoteConnection
    from selenium.webdriver.support.ui import WebDriverWait
    import imageio_ffmpeg

    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "result.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    faulthandler.dump_traceback_later(600, exit=True)
    options = ArgOptions()
    options.set_capability("browserName", "wry")
    options.set_capability("tauri:options", {"application": str(args.app.resolve())})
    driver = None
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        env = {**os.environ, "VIZORPLAY_DATA_DIR": str(root / "projects")}
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        video = root / "fixture.mp4"
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                        "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
                       check=True, capture_output=True, timeout=60)
        with (evidence / "driver.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(["tauri-driver", "--port", str(port)], env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                wait_for_driver(process, port)
                project_id = None
                project_path = None
                for launch in range(2):
                    stage(evidence, f"launch {launch + 1}: create native session")
                    address = f"http://127.0.0.1:{port}"
                    connection = RemoteConnection(client_config=ClientConfig(remote_server_addr=address, timeout=45))
                    driver = webdriver.Remote(command_executor=connection, options=options)
                    driver.set_page_load_timeout(45)
                    driver.set_script_timeout(30)
                    wait = WebDriverWait(driver, 120)
                    def element(selector):
                        return ready_element(driver, wait, selector)
                    wait.until(lambda current: current.current_url.startswith("http://127.0.0.1:"))
                    parsed = urlparse(driver.current_url)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                    wait.until(lambda current: current.find_element(By.CSS_SELECTOR, '[data-engine-state]').text == "Engine ready")
                    assert driver.find_element(By.CSS_SELECTOR, '.cm-logo').text == "VizorPlay"
                    assert "Version 1.0" in driver.find_element(By.CSS_SELECTOR, 'footer').text
                    if launch == 0:
                        stage(evidence, "create and seed isolated project")
                        previous_url = driver.current_url
                        element('[data-new-project]').click()
                        wait.until(lambda current: current.current_url != previous_url and "project=" in current.current_url)
                        from urllib.parse import parse_qs
                        project_id = parse_qs(urlparse(driver.current_url).query)["project"][0]
                        request(base, f"/api/files/upload?project={project_id}", raw=fixture_csv(),
                                headers={"Content-Type": "application/octet-stream", "X-File-Name": "fixture.csv"})
                        request(base, f"/api/projects/{project_id}", {"video_path": str(video), "video_name": video.name,
                                "markers": {"1H": "00:00:00", "2H": "00:00:00"}})
                        driver.refresh()
                        stage(evidence, "verify installed webview decodes and plays footage")
                        element('.play-button').click()
                        wait.until(lambda current: current.execute_script(
                            "const v=document.querySelector('[data-match-video]'); return v.videoWidth > 0 && v.currentTime > 0"))
                        element('.play-button').click()
                        stage(evidence, "open filters and build clip plan")
                        element('[data-continue]').click()
                        element('#actions summary').click()
                        checkbox = driver.find_element(By.CSS_SELECTOR, 'input[name="action"][value="Goal"]')
                        checkbox.find_element(By.XPATH, "..").click()
                        element('button.filter-preview-button').click()
                        wait.until(lambda current: current.find_element(By.CSS_SELECTOR, '[data-preview-count]').text == "1")
                        element('.clip-preview summary').click()
                        endpoint = element('.clip-editor label:nth-child(2) input')
                        endpoint.send_keys(Keys.CONTROL, "a")
                        endpoint.send_keys("3.5", Keys.TAB)
                        stage(evidence, "render edited preview in the installed webview")
                        element('.clip-editor > button:first-of-type').click()
                        wait.until(lambda current: current.execute_script(
                            "const v=document.querySelector('.clip-preview video'); return v && !v.hidden && v.videoWidth > 0"))
                        duration = driver.execute_script("return document.querySelector('.clip-preview video').duration")
                        assert 3.3 <= duration <= 3.7, duration
                        stage(evidence, "export edited clip")
                        element('[data-export-button]').click()
                        wait.until(export_finished)
                        stage(evidence, "export complete: download and decode")
                        link = element('[data-export-files] a')
                        output = evidence / "native-export.mp4"
                        with urlopen(link.get_attribute("href"), timeout=30) as response:
                            output.write_bytes(response.read())
                        assert output.stat().st_size > 0
                        subprocess.run([ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-"],
                                       check=True, capture_output=True, timeout=60)
                    else:
                        stage(evidence, "verify project survived native shutdown and relaunch")
                        saved = request(base, f"/api/projects/{project_id}")["project"]
                        assert saved["preview_windows"] and saved["filter_settings"]["filter_types"] == ["Goal"]
                        assert saved["preview_windows"][0]["end"] == 3.5
                        driver.get(f"{base}/filters.html?match={project_id}")
                        wait.until(lambda current: current.find_element(By.CSS_SELECTOR, '[data-preview-count]').text == "1")
                    wait.until(lambda current: current.find_element(By.CSS_SELECTOR, '[data-project-status]').get_attribute("textContent") == "Saved locally")
                    project_path = Path(request(base, "/api/projects")["directory"]) / project_id / "project.json"
                    assert project_path.resolve().is_relative_to(root.resolve()), project_path
                    stage(evidence, f"launch {launch + 1}: capture evidence and close")
                    driver.save_screenshot(str(evidence / f"native-launch-{launch + 1}.png"))
                    health = request(base, "/api/health")
                    driver.quit()
                    driver = None
                    stage(evidence, f"launch {launch + 1}: wait for shell and backend exit")
                    verify_shutdown(health, evidence, launch + 1)
                    if launch == 0 and args.package:
                        stage(evidence, "reinstall same-version package before relaunch")
                        preserved = project_path.read_bytes()
                        package_lifecycle(args.app, args.package)
                        assert project_path.read_bytes() == preserved, "Reinstall changed saved project data"
                if args.package:
                    stage(evidence, "uninstall package and verify saved project data remains")
                    preserved = project_path.read_bytes()
                    package_lifecycle(args.app, args.package, uninstall=True)
                    deadline = time.monotonic() + 30
                    while args.app.exists() and time.monotonic() < deadline:
                        time.sleep(.2)
                    assert not args.app.exists(), "Uninstall did not remove the application"
                    assert project_path.read_bytes() == preserved, "Uninstall removed or changed saved project data"
                result = {"status": "passed", "native_launches": 2,
                    "reinstall_and_uninstall": bool(args.package), "shutdown_verified": True}
            except BaseException:
                print(traceback.format_exc(), flush=True)
                (evidence / "result.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
                (evidence / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
                if driver:
                    try:
                        stage(evidence, "capture failure HTML before screenshot")
                        (evidence / "failure.html").write_text(driver.page_source, encoding="utf-8")
                        driver.save_screenshot(str(evidence / "failure.png"))
                    except Exception:
                        (evidence / "diagnostics-failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
                raise
            finally:
                try:
                    if driver:
                        try:
                            driver.quit()
                        except Exception:
                            (evidence / "cleanup-failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    faulthandler.cancel_dump_traceback_later()
    (evidence / "result.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
