"""CI-only controlled Homebrew upgrade; preserve an actual on-disk project."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, fixture_csv, request


def brew_version():
    result = subprocess.run(["brew", "list", "--versions", "clipmaker"],
                            check=True, capture_output=True, text=True, timeout=60)
    return result.stdout.split()[1:]


def launcher_command(launcher):
    # Keep Homebrew's stable bin symlink: its Cellar target changes on upgrade.
    return [str(launcher.absolute()), "--no-browser"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--formula", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--launcher", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin" or os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("Only disposable macOS GitHub runners may modify this test tap")
    formula = args.formula.resolve()
    tap = Path(subprocess.run(["brew", "--repository", "local/vizorplay"], check=True,
                             capture_output=True, text=True, timeout=60).stdout.strip()).resolve()
    if formula != tap / "Formula/clipmaker.rb":
        parser.error("Refusing to modify a formula outside the disposable local/vizorplay tap")
    evidence = ROOT / "build/homebrew-upgrade"
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"status": "running", "upgrade_fixture": "same-source predecessor formula"}
    output = evidence / "result.json"
    output.write_text(json.dumps(result), encoding="utf-8")
    try:
        assert brew_version() == ["0.9.0"], brew_version()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            command = launcher_command(args.launcher)
            with backend(command, data, evidence / "before", startup_timeout=1200) as base:
                project = request(base, "/api/projects", {"name": "Homebrew upgrade fixture"})["project"]
                project_id = project["id"]
                request(base, f"/api/files/upload?project={project_id}", raw=fixture_csv(),
                        headers={"Content-Type": "application/octet-stream", "X-File-Name": "fixture.csv"})
                request(base, f"/api/projects/{project_id}", {
                    "markers": {"1H": "00:00:03", "2H": "00:50:00", "ET2": "01:50:00"},
                    "filter_settings": {"filter_types": ["Goal"], "before_buffer": 1,
                                        "after_buffer": 1, "video_crf": 24}})
                saved = request(base, f"/api/projects/{project_id}")["project"]
            project_path = data / "projects" / project_id / "project.json"
            preserved = project_path.read_bytes()
            shutil.copyfile(args.candidate.resolve(), formula)
            subprocess.run(["brew", "upgrade", "--build-from-source", "local/vizorplay/clipmaker"],
                           check=True, timeout=600)
            assert brew_version() == ["1.0.0"], brew_version()
            assert project_path.read_bytes() == preserved, "Homebrew upgrade changed the project"
            with backend(command, data, evidence / "after", startup_timeout=180) as base:
                reopened = request(base, f"/api/projects/{project_id}")["project"]
                for key in ("project_name", "csv_path", "event_count", "markers", "filter_settings"):
                    assert reopened.get(key) == saved.get(key), key
                windows = request(base, "/api/previews", {"match_id": project_id,
                                  "options": saved["filter_settings"]})["windows"]
                assert len(windows) == 1 and windows[0]["start"] == 4, windows
            result.update(status="passed", installed_versions=["0.9.0", "1.0.0"],
                          project_sha256=hashlib.sha256(preserved).hexdigest())
    except BaseException as error:
        result.update(status="failed", error=str(error))
        raise
    finally:
        output.write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
