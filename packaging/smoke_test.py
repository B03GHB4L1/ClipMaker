"""Exercise a source or frozen backend with real media, without user data."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def request(base, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    with urlopen(Request(base + path, data=data, headers={"Content-Type": "application/json", **(headers or {})}), timeout=90) as response:
        return json.loads(response.read())


def fixture_csv():
    return b"minute,second,type,period,team,playerName,x,y,endX,endY,xT\n0,2,Goal,1,Home,One,85,50,100,50,0.3\n0,5,Pass,1,Away,Two,20,20,40,25,0.1\n"


def finished_job(base, job):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        job = request(base, "/api/jobs/" + job["id"])["job"]
        if job["status"] in {"complete", "failed", "cancelled"}:
            break
        time.sleep(.1)
    assert job["status"] == "complete", job
    return job


@contextmanager
def backend(command, directory):
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "backend-process.log"
    stderr_log = log_path.open("w", encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen([*command, "--port", str(port), "--data-dir", str(directory)],
        stdout=subprocess.DEVNULL, stderr=stderr_log,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace"))
            try:
                request(base, "/api/health")
                break
            except (URLError, TimeoutError):
                time.sleep(.2)
        else:
            raise RuntimeError("Backend did not become ready: " + log_path.read_text(encoding="utf-8", errors="replace"))
        yield base
    finally:
        try:
            request(base, "/api/shutdown", {})
        except (OSError, ValueError):
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        stderr_log.close()


def run(base, root):
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    video = root / "fixture.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24", "-t", "8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True, timeout=60)
    project = request(base, "/api/projects", {"name": "Packaged smoke test"})["project"]
    imported = request(base, f"/api/files/upload?project={project['id']}", raw=fixture_csv(),
                       headers={"Content-Type": "application/octet-stream", "X-File-Name": "fixture.csv"})["match"]
    assert imported["event_count"] == 2
    request(base, f"/api/projects/{project['id']}", {"video_path": str(video), "video_name": video.name,
        "markers": {"1H": "00:00:00", "2H": "00:00:00"}, "filter_settings": {"filter_types": ["Goal"]}})
    for asset in ("/", "/filters.html", "/analysis.html", "/assets/cm-chrome-football.glb", "/vendor/loaders/GLTFLoader.js"):
        with urlopen(base + asset, timeout=5) as response:
            assert response.status == 200 and len(response.read()) > 0, asset
    options = {"filter_types": ["Goal"], "before_buffer": 1, "after_buffer": 1, "min_gap": 0}
    windows = request(base, "/api/previews", {"match_id": project["id"], "options": options})["windows"]
    assert len(windows) == 1, windows
    preview = request(base, "/api/previews/render", {"match_id": project["id"], **windows[0]})["file"]
    assert preview["size"] > 0
    with urlopen(Request(base + preview["url"], headers={"Range": "bytes=-32"})) as response:
        assert response.status == 206 and len(response.read()) == 32
    job = request(base, "/api/jobs", {"match_id": project["id"], "options": {
        **options, "dry_run": False, "clip_windows": windows, "output_dir": str(root / "exports"), "output_filename": "smoke.mp4"}})["job"]
    job = finished_job(base, job)
    output = root / "exports" / "smoke.mp4"
    assert output.is_file() and output.stat().st_size > 0
    probe = subprocess.run([ffmpeg, "-i", str(output), "-f", "null", "-"], capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, probe.stderr
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", probe.stderr)
    assert duration and 1.8 <= sum(float(value) * factor for value, factor in zip(duration.groups(), [3600, 60, 1])) <= 2.3
    repeated = finished_job(base, request(base, "/api/jobs", {"match_id": project["id"], "options": {
        **options, "dry_run": False, "clip_windows": windows, "output_dir": str(root / "exports"), "output_filename": "smoke.mp4"}})["job"])
    assert repeated["output_filename"] != "smoke.mp4" and output.is_file()
    extra = root / "extra.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=red:size=320x180:rate=24", "-t", "8",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(extra)], check=True, capture_output=True, timeout=60)
    request(base, f"/api/projects/{project['id']}", {"period_videos": {"ET1": str(extra)},
        "markers": {"1H": "00:00:00", "2H": "00:00:00", "ET1": "00:00:00"}})
    individual = finished_job(base, request(base, "/api/jobs", {"match_id": project["id"], "options": {
        **options, "dry_run": False, "individual_clips": True, "output_dir": str(root / "exports"),
        "clip_windows": [{"start": 1, "end": 3, "period": 3, "label": "Extra time"}]}})["job"])
    assert len(individual["files"]) == 1, individual
    exported = individual["files"][0]
    with urlopen(base + exported["url"], timeout=10) as response:
        assert response.read() == Path(exported["path"]).read_bytes()
    decoded = subprocess.run([ffmpeg, "-ss", "0.5", "-i", exported["path"], "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, timeout=30)
    assert decoded.returncode == 0, decoded.stderr.decode(errors="replace")
    pixel_frame = decoded.stdout
    assert len(pixel_frame) == 320 * 180 * 3
    assert sum(pixel_frame[0::3]) / (320 * 180) > 200 and sum(pixel_frame[1::3]) / (320 * 180) < 30, "Wrong period video exported"
    analysis = request(base, "/api/analysis", {"project_id": project["id"], "view": "analyst"})
    with urlopen(analysis["url"].split("/?", 1)[0] + "/_stcore/health", timeout=10) as response:
        assert response.status == 200
    print("PASS: local projects, CSV, shared assets, real preview, seeking, decoded reel, repeat-export protection, individual extra-time source/pixels, downloads, analytical startup")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path)
    args = parser.parse_args()
    command = [str(args.server.resolve())] if args.server else [sys.executable, str(ROOT / "packaging" / "clipmaker_api_server.py")]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with backend(command, root / "data") as base:
            run(base, root)


if __name__ == "__main__":
    main()
