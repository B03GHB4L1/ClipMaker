"""Lifecycle of the local analytical server, owned by the desktop backend."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen


class AnalysisServer:
    def __init__(self, root: Path, data_dir: Path):
        self.root = root
        self.data_dir = data_dir
        self.process = None
        self.port = None
        self._lock = threading.Lock()

    def start(self) -> int:
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return self.port
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                self.port = listener.getsockname()[1]
            environment = {**os.environ, "CLIPMAKER_ANALYSIS_MODE": "1", "CLIPMAKER_DATA_DIR": str(self.data_dir), "CLIPMAKER_OWNER_PID": str(os.getpid())}
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--analysis-port", str(self.port)]
            else:
                entry = self.root / "packaging" / "clipmaker_api_server.py"
                if not entry.is_file():
                    entry = self.root / "clipmaker_api_server.py"
                command = [sys.executable, str(entry), "--analysis-port", str(self.port)]
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with (self.data_dir / "analysis.log").open("ab") as log:
                self.process = subprocess.Popen(command, env=environment, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and self.process.poll() is None:
                try:
                    with urlopen(f"http://127.0.0.1:{self.port}/_stcore/health", timeout=1) as response:
                        if response.status == 200:
                            return self.port
                except OSError:
                    time.sleep(.2)
            self.close()
            raise RuntimeError("Analytical workspace did not start. Check analysis.log in the local data directory.")

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


def run_analysis(root: Path, port: int) -> int:
    from streamlit.web import cli
    parent_pid = os.getppid()

    def watch_parent(parent_pid):
        # A forced desktop-shell exit skips Python's atexit hooks.
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, parent_pid)
            if handle:
                result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
                kernel.CloseHandle(handle)
                if result == 0:
                    os._exit(0)
        else:
            while os.getppid() == parent_pid:
                time.sleep(1)
            os._exit(0)

    owners = {parent_pid, int(os.environ.get("CLIPMAKER_OWNER_PID", parent_pid))}
    for owner in owners:
        threading.Thread(target=watch_parent, args=(owner,), daemon=True).start()
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    sys.argv = ["streamlit", "run", str(root / "app" / "analysis_entry.py"),
                "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=true",
                "--browser.gatherUsageStats=false", "--server.fileWatcherType=none",
                "--global.developmentMode=false", "--theme.base=light"]
    return int(cli.main() or 0)
