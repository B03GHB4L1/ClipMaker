"""CI-only: an installed Windows VizorPlay updates itself from a signed release feed.

The feed is served over HTTPS on 127.0.0.1 with a throwaway certificate
authority trusted only on the disposable runner. The "update" is the tested
installer itself, announced as 1.0.1 and signed with VizorPlay's updater key.
The test proves, through the real footer button in the installed window:
an update signed for different bytes is refused and the app keeps working;
the genuine update is downloaded, verified and installed, VizorPlay reopens
by itself, and the saved project is untouched.
"""
import argparse
import faulthandler
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
sys.path.insert(0, str(ROOT / "tests"))
from smoke_test import request
from process_owner import wait_for_process_exit
from native_smoke import ready_element, stage, wait_for_driver

OLD_TIME = 978307200  # 2001-01-01: the installer must replace files carrying this time.


def run(command, **options):
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=120, **options)


def make_certificate(directory):
    """A throwaway CA, trusted on this runner only, and a 127.0.0.1 server certificate it signed."""
    openssl = shutil.which("openssl") or r"C:\Program Files\Git\usr\bin\openssl.exe"
    ca_key, ca_cert = directory / "ca.key", directory / "ca.pem"
    key, csr, cert = directory / "server.key", directory / "server.csr", directory / "server.pem"
    extensions = directory / "server.ext"
    extensions.write_text("subjectAltName=IP:127.0.0.1\nextendedKeyUsage=serverAuth\n"
                          "basicConstraints=critical,CA:FALSE\n", encoding="ascii")
    run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj",
         "/CN=VizorPlay update test CA", "-keyout", str(ca_key), "-out", str(ca_cert)])
    run([openssl, "req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=127.0.0.1",
         "-keyout", str(key), "-out", str(csr)])
    run([openssl, "x509", "-req", "-in", str(csr), "-CA", str(ca_cert), "-CAkey", str(ca_key),
         "-CAcreateserial", "-days", "1", "-extfile", str(extensions), "-out", str(cert)])
    run(["certutil", "-addstore", "-f", "Root", str(ca_cert)])
    return cert, key


def sign(file, version):
    """Sign with VizorPlay's updater key (TAURI_SIGNING_PRIVATE_KEY), binding the version."""
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    run([npx, "tauri", "signer", "sign", "--app-version", version, "--password", "", str(file)], cwd=ROOT)
    return Path(f"{file}.sig").read_text(encoding="ascii").strip()


def serve(directory, cert, key):
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def write_feed(directory, port, installer_name, signature):
    feed = {"version": "1.0.1", "notes": "Acceptance-test update", "pub_date": "2026-11-14T00:00:00Z",
            "platforms": {"windows-x86_64": {"signature": signature,
                                             "url": f"https://127.0.0.1:{port}/{installer_name}"}}}
    (directory / "latest.json").write_text(json.dumps(feed), encoding="utf-8")


def processes(image):
    output = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                            capture_output=True, text=True, timeout=30).stdout
    return [int(line.split('","')[1]) for line in output.splitlines() if line.startswith(f'"{image}"')]


def listening_ports(pid):
    output = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=30).stdout
    ports = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[3] == "LISTENING" and parts[4] == str(pid) and parts[1].startswith("127.0.0.1:"):
            ports.append(int(parts[1].rsplit(":", 1)[1]))
    return ports


def wait_until(condition, timeout, message):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(.5)
    raise TimeoutError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", required=True, type=Path, help="The tested NSIS installer (1.0.0)")
    parser.add_argument("--evidence", type=Path, default=ROOT / "build/update-evidence")
    args = parser.parse_args()
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This test changes the machine's trusted certificates; it runs only on disposable Windows CI runners")
    if not os.environ.get("TAURI_SIGNING_PRIVATE_KEY"):
        parser.error("TAURI_SIGNING_PRIVATE_KEY is required to sign the test update")
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.options import ArgOptions
    from selenium.webdriver.remote.client_config import ClientConfig
    from selenium.webdriver.remote.remote_connection import RemoteConnection
    from selenium.webdriver.support.ui import WebDriverWait

    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "result.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    faulthandler.dump_traceback_later(900, exit=True)
    driver = process = None
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        try:
            stage(evidence, "install the tested 1.0.0 package")
            destination = root / "installed"
            run([str(args.installer.resolve()), "/S", f"/D={destination}"])
            app = destination / "vizorplay.exe"
            assert app.is_file(), "Installer did not install vizorplay.exe"
            os.utime(app, (OLD_TIME, OLD_TIME))

            stage(evidence, "serve a signed 1.0.1 feed over trusted local HTTPS")
            feed_dir = root / "feed"
            feed_dir.mkdir()
            installer_name = "VizorPlay_1.0.1_x64-setup.exe"
            shutil.copy2(args.installer, feed_dir / installer_name)
            good_signature = sign(feed_dir / installer_name, "1.0.1")
            other = root / "other-file.exe"
            other.write_bytes(b"not the installer")
            bad_signature = sign(other, "1.0.1")
            cert, key = make_certificate(root)
            server = serve(feed_dir, cert, key)
            feed_port = server.server_address[1]
            write_feed(feed_dir, feed_port, installer_name, bad_signature)

            env = {**os.environ, "VIZORPLAY_DATA_DIR": str(root / "projects"),
                   "VIZORPLAY_UPDATE_URL": f"https://127.0.0.1:{feed_port}/latest.json"}
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                driver_port = listener.getsockname()[1]
            log = (evidence / "driver.log").open("w", encoding="utf-8")
            process = subprocess.Popen(["tauri-driver", "--port", str(driver_port)], env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            wait_for_driver(process, driver_port)
            options = ArgOptions()
            options.set_capability("browserName", "wry")
            options.set_capability("tauri:options", {"application": str(app)})
            connection = RemoteConnection(client_config=ClientConfig(
                remote_server_addr=f"http://127.0.0.1:{driver_port}", timeout=45))
            driver = webdriver.Remote(command_executor=connection, options=options)
            wait = WebDriverWait(driver, 120)
            wait.until(lambda current: current.current_url.startswith("http://127.0.0.1:"))
            parsed = urlparse(driver.current_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            wait.until(lambda current: current.find_element(By.CSS_SELECTOR, "[data-engine-state]").text == "Engine ready")
            health = request(base, "/api/health")
            project = request(base, "/api/projects", {})["project"]
            request(base, f"/api/projects/{project['id']}", {"project_name": "Survives the update",
                                                             "markers": {"1H": "00:01:00"}})
            project_file = Path(request(base, "/api/projects")["directory"]) / project["id"] / "project.json"
            saved = project_file.read_bytes()

            stage(evidence, "the footer offers 1.0.1; an update signed for other bytes is refused")
            update = request(base, "/api/update")["update"]
            assert update["available"] and update["latest"] == "1.0.1" and update["install"] == "in-app", update
            notice = "[data-update-notice]"
            ready_element(driver, wait, f"{notice} button").click()
            wait.until(lambda current: "did not install" in current.find_element(By.CSS_SELECTOR, notice).text)
            refusal = driver.find_element(By.CSS_SELECTOR, notice).text
            (evidence / "refusal.txt").write_text(refusal, encoding="utf-8")
            assert request(base, "/api/health")["status"] == "ok", "Engine stopped after a refused update"
            assert os.stat(app).st_mtime == OLD_TIME, "A refused update changed the installed app"
            driver.save_screenshot(str(evidence / "refused.png"))

            stage(evidence, "the genuine update installs and VizorPlay reopens by itself")
            write_feed(feed_dir, feed_port, installer_name, good_signature)
            button = ready_element(driver, wait, f"{notice} button")
            assert button.text == "Try again", button.text
            button.click()
            owner = health["desktop_owner_pid"]
            assert wait_for_process_exit(owner, timeout=180), "VizorPlay did not close for the installer"
            try:
                driver.quit()
            except Exception:  # the window it drove has closed
                pass
            driver = None
            wait_until(lambda: os.stat(app).st_mtime != OLD_TIME, 180, "The installer did not replace vizorplay.exe")
            reopened = wait_until(lambda: [pid for pid in processes("vizorplay.exe") if pid != owner], 120,
                                  "VizorPlay did not reopen after updating")
            engines = wait_until(lambda: processes("vizorplay-engine.exe"), 60, "The reopened app has no engine")
            ports = wait_until(lambda: [port for pid in engines for port in listening_ports(pid)], 60,
                               "The reopened engine is not listening")
            reopened_base = f"http://127.0.0.1:{ports[0]}"
            wait_until(lambda: request(reopened_base, "/api/health").get("status") == "ok", 60,
                       "The reopened engine did not answer")
            assert request(reopened_base, "/api/health")["desktop_owner_pid"] in reopened
            kept = request(reopened_base, f"/api/projects/{project['id']}")["project"]
            assert kept["project_name"] == "Survives the update" and kept["markers"] == {"1H": "00:01:00"}, kept
            assert project_file.read_bytes() == saved, "Updating changed the saved project"
            result = {"status": "passed", "update_installed": True, "bad_signature_rejected": True,
                      "reopened_automatically": True, "project_preserved": True,
                      "feed": "local HTTPS feed announcing 1.0.1, signed with the release updater key",
                      "refusal_message": refusal}
        except BaseException:
            print(traceback.format_exc(), flush=True)
            (evidence / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
            (evidence / "result.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            if driver:
                try:
                    driver.save_screenshot(str(evidence / "failure.png"))
                except Exception:
                    pass
            raise
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            if process:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
            subprocess.run(["taskkill", "/IM", "vizorplay.exe", "/T", "/F"], capture_output=True, timeout=30)
    faulthandler.cancel_dump_traceback_later()
    (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
