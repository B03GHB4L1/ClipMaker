"""Watch the process that owns the backend (the desktop shell) and react when it exits.

Moved from the retired analysis_server module, which also launched the
classic Streamlit workspace.
"""
from __future__ import annotations

import errno
import os
import sys
import threading
import time


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
