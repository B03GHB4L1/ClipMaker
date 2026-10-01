"""Homebrew-friendly launcher that maintains ClipMaker's private Python runtime."""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import time
import venv
import webbrowser
from pathlib import Path


def runtime_root() -> Path:
    override = os.environ.get("CLIPMAKER_RUNTIME_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "ClipMaker" / "runtime"


def venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until_ready(port: int, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def main() -> int:
    install_root = Path(__file__).resolve().parent
    requirements = install_root / "requirements.txt"
    server = install_root / "clipmaker_api_server.py"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()

    root = runtime_root()
    env_dir = root / "venv"
    stamp = root / "requirements.sha256"
    python = venv_python(env_dir)

    if not python.exists():
        root.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)

    if not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != digest:
        print("Preparing ClipMaker. This one-time step can take a few minutes...")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "playwright", "install", "chromium-headless-shell"],
            check=True,
        )
        stamp.write_text(digest, encoding="utf-8")

    port = available_port()
    data_dir = root / "data"
    process = subprocess.Popen(
        [str(python), str(server), "--port", str(port), "--data-dir", str(data_dir)]
    )
    try:
        if not wait_until_ready(port):
            process.terminate()
            raise RuntimeError("ClipMaker did not start within 90 seconds")
        webbrowser.open(f"http://127.0.0.1:{port}")
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
