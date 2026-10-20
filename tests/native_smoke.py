"""CI-only installed Tauri window test; Windows/Linux, never a browser substitute."""
import argparse
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--evidence", type=Path, default=ROOT / "build/native-evidence")
    args = parser.parse_args()
    if sys.platform not in {"win32", "linux"}:
        parser.error("This native Tauri driver test supports only Windows/Linux; macOS uses the Homebrew browser workflow")
    if not args.app.is_file():
        parser.error("Installed application executable not found")
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.options import ArgOptions
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import imageio_ffmpeg

    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
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
                for launch in range(2):
                    driver = webdriver.Remote(command_executor=f"http://127.0.0.1:{port}", options=options)
                    wait = WebDriverWait(driver, 120)
                    def element(selector):
                        return wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    wait.until(lambda current: current.current_url.startswith("http://127.0.0.1:"))
                    parsed = urlparse(driver.current_url)
                    base = f"{parsed.scheme}://{parsed.netloc}"
                    wait.until(lambda current: current.find_element(By.CSS_SELECTOR, '[data-engine-state]').text == "Engine ready")
                    assert driver.find_element(By.CSS_SELECTOR, '.cm-logo').text == "VizorPlay"
                    assert "Version 1.0" in driver.find_element(By.CSS_SELECTOR, 'footer').text
                    if launch == 0:
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
                        element('[data-export-button]').click()
                        wait.until(lambda current: current.find_element(By.CSS_SELECTOR, '[data-job-state]').text == "Export complete")
                        link = element('[data-export-files] a')
                        output = evidence / "native-export.mp4"
                        with urlopen(link.get_attribute("href"), timeout=30) as response:
                            output.write_bytes(response.read())
                        assert output.stat().st_size > 0
                        subprocess.run([ffmpeg, "-v", "error", "-i", str(output), "-f", "null", "-"],
                                       check=True, capture_output=True, timeout=60)
                    else:
                        saved = request(base, f"/api/projects/{project_id}")["project"]
                        assert saved["preview_windows"] and saved["filter_settings"]["filter_types"] == ["Goal"]
                        assert saved["preview_windows"][0]["end"] == 3.5
                        driver.get(f"{base}/filters.html?match={project_id}")
                        wait.until(lambda current: current.find_element(By.CSS_SELECTOR, '[data-preview-count]').text == "1")
                    driver.save_screenshot(str(evidence / f"native-launch-{launch + 1}.png"))
                    driver.quit()
                    driver = None
                (evidence / "result.json").write_text(json.dumps({"status": "passed", "native_launches": 2}), encoding="utf-8")
            except BaseException:
                (evidence / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
                if driver:
                    try:
                        driver.save_screenshot(str(evidence / "failure.png"))
                        (evidence / "failure.html").write_text(driver.page_source, encoding="utf-8")
                    except Exception:
                        pass
                raise
            finally:
                try:
                    if driver:
                        driver.quit()
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    main()
