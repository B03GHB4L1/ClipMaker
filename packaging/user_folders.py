"""Where VizorPlay puts exports by default, and opening a finished export's folder.

The default is a ``VizorPlay`` folder inside the user's own videos folder:

* Windows: the Videos known folder (wherever the user has moved it), via the shell.
* macOS: ``~/Movies``, the system's videos folder.
* Linux: the desktop's videos folder from ``xdg-user-dir VIDEOS`` / ``user-dirs.dirs``,
  else ``~/Videos``.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping

APP_FOLDER = "VizorPlay"
_VIDEOS_GUID = "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}"  # FOLDERID_Videos


def _windows_videos() -> Path | None:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

    guid = GUID()
    if ctypes.windll.ole32.CLSIDFromString(_VIDEOS_GUID, ctypes.byref(guid)):
        return None
    pointer = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)):
        return None
    try:
        return Path(pointer.value) if pointer.value else None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)


def _linux_videos(home: Path, env: Mapping[str, str], run: Callable[..., subprocess.CompletedProcess]) -> Path | None:
    try:
        found = run(["xdg-user-dir", "VIDEOS"], capture_output=True, text=True, timeout=5)
        text = found.stdout.strip() if found.returncode == 0 else ""
        # xdg-user-dir answers with $HOME itself when the folder is not configured.
        if text and Path(text) != home:
            return Path(text)
    except (OSError, subprocess.SubprocessError):
        pass
    config = Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
    try:
        for line in config.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("XDG_VIDEOS_DIR="):
                value = shlex.split(line.split("=", 1)[1])[0].replace("$HOME", str(home))
                if value and Path(value) != home:
                    return Path(value)
    except (OSError, ValueError, IndexError):
        pass
    return None


def videos_dir(platform: str = sys.platform, home: Path | None = None, env: Mapping[str, str] | None = None,
               run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
               windows_lookup: Callable[[], Path | None] = _windows_videos) -> Path:
    home = home or Path.home()
    env = os.environ if env is None else env
    found = None
    if platform == "win32":
        try:
            found = windows_lookup()
        except (OSError, AttributeError, ValueError):
            found = None
        return found or home / "Videos"
    if platform == "darwin":
        return home / "Movies"
    return _linux_videos(home, env, run) or home / "Videos"


def default_export_dir(**kwargs) -> Path:
    return videos_dir(**kwargs) / APP_FOLDER


def reveal_folder(path: Path, platform: str = sys.platform,
                  run: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
    """Show a folder in the system file manager."""
    path = Path(path)
    if not path.is_dir():
        raise ValueError("That export folder no longer exists.")
    if platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # Explorer, in the foreground
        return
    run(["open" if platform == "darwin" else "xdg-open", str(path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
