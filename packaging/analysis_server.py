"""Lifecycle of the local analytical server, owned by the desktop backend."""
from __future__ import annotations

import os
import errno
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen


def _wait_for_kqueue_exit(pid: int, timeout: float | None) -> bool:
    import select
    queue = select.kqueue()
    try:
        event = select.kevent(pid, filter=select.KQ_FILTER_PROC,
                              flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                              fflags=select.KQ_NOTE_EXIT)
        try:
            events = queue.control([event], 1, timeout)
        except ProcessLookupError:
            return True
        if not events:
            return False
        event = events[0]
        if event.flags & select.KQ_EV_ERROR:
            if event.data == errno.ESRCH:
                return True
            raise OSError(event.data, os.strerror(event.data))
        return bool(event.fflags & select.KQ_NOTE_EXIT)
    finally:
        queue.close()


def wait_for_process_exit(pid: int, timeout: float | None = None) -> bool:
    if pid <= 0:
        raise ValueError("Owner PID must be positive")
    if timeout is not None and timeout < 0:
        raise ValueError("Timeout must not be negative")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # PID no longer exists.
                return True
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF if timeout is None else int(timeout * 1000))
            if result == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            return result == 0
        finally:
            kernel.CloseHandle(handle)
    if sys.platform == "darwin":
        return _wait_for_kqueue_exit(pid, timeout)
    if sys.platform == "linux" and hasattr(os, "pidfd_open"):
        import select
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            return True
        except OSError as error:
            if error.errno not in {errno.ENOSYS, errno.EINVAL}:
                raise
        else:
            try:
                poller = select.poll()
                poller.register(descriptor, select.POLLIN)
                return bool(poller.poll(None if timeout is None else int(timeout * 1000)))
            finally:
                os.close(descriptor)
    is_parent = os.getppid() == pid
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        if is_parent and os.getppid() != pid:
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(.05)


def watch_process_owner(pid: int, on_exit) -> threading.Thread:
    def watch():
        if wait_for_process_exit(pid):
            on_exit()
    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


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

    owners = {parent_pid, int(os.environ.get("CLIPMAKER_OWNER_PID", parent_pid))}
    if os.environ.get("VIZORPLAY_OWNER_PID"):
        owners.add(int(os.environ["VIZORPLAY_OWNER_PID"]))
    for owner in owners:
        # A forced desktop-shell exit skips Python's atexit hooks.
        watch_process_owner(owner, lambda: os._exit(0))
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    sys.argv = ["streamlit", "run", str(root / "app" / "analysis_entry.py"),
                "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=true",
                "--browser.gatherUsageStats=false", "--server.fileWatcherType=none",
                "--global.developmentMode=false", "--theme.base=light"]
    return int(cli.main() or 0)
