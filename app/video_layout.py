"""Spot match videos that load slowly in the player, and rearrange them losslessly.

Videos saved from web streams (Dailymotion, HLS downloaders) often hold their
picture and sound in thousands of small `mdat` pieces, one per second or so.
The player then walks the file piece by piece: a full match took 18-20 s and
about 2,000 requests to become playable. The same streams in one piece, with
the index (`moov`) first, are ready in a fraction of a second.

`prepare` rewrites the file with FFmpeg's stream copy: no re-encoding, the
picture and sound are bit-for-bit the same. The new file is checked against the
original (length and track count) before it replaces it under the same name.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
import threading
import time
from typing import Callable

MP4_SUFFIXES = {".mp4", ".m4v", ".mov"}
# A normal MP4 has one or two mdat boxes. A web-stream download has one per segment.
MANY_PIECES = 100
PART_SUFFIX = ".vizorplay-part"


class PrepareCancelled(RuntimeError):
    """The user stopped the preparation; the original file is unchanged."""


def _boxes(handle, start: int, end: int):
    """Yield (kind, offset, size, header) for the boxes between start and end."""
    position = start
    while position + 8 <= end:
        handle.seek(position)
        header = handle.read(16)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header[:8])
        header_size = 8
        if size == 1:
            if len(header) < 16:
                return
            size = struct.unpack(">Q", header[8:16])[0]
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size:
            return  # damaged: stop rather than loop
        yield kind.decode("latin-1"), position, size, header_size
        position += size


def layout(path: str | os.PathLike) -> dict:
    """The top-level shape of an MP4: how many mdat pieces, and whether the index comes first.

    Reads box headers only, and stops once the file is known to be in many pieces."""
    path = Path(path)
    result = {"mp4": path.suffix.lower() in MP4_SUFFIXES, "pieces": 0, "index_first": False}
    if not result["mp4"]:
        return result
    size = path.stat().st_size
    with path.open("rb") as handle:
        for kind, _, _, _ in _boxes(handle, 0, size):
            if kind == "moov" and result["pieces"] == 0:
                result["index_first"] = True
            elif kind == "mdat":
                result["pieces"] += 1
                if result["pieces"] > MANY_PIECES:
                    break
    return result


def needs_preparing(path: str | os.PathLike) -> bool:
    """True when the player would load this file slowly because it is in many pieces."""
    try:
        return layout(path)["pieces"] > MANY_PIECES
    except (OSError, struct.error):
        return False


def summary(path: str | os.PathLike) -> dict:
    """Length in seconds and number of tracks, read from the MP4 index (moov/mvhd)."""
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as handle:
        for kind, offset, box_size, header_size in _boxes(handle, 0, size):
            if kind != "moov":
                continue
            duration, tracks = None, 0
            for child, child_offset, _, child_header in _boxes(handle, offset + header_size, offset + box_size):
                if child == "trak":
                    tracks += 1
                elif child == "mvhd":
                    handle.seek(child_offset + child_header)
                    version = handle.read(1)[0]
                    if version == 1:
                        handle.seek(child_offset + child_header + 4 + 16)
                        timescale, units = struct.unpack(">IQ", handle.read(12))
                    else:
                        handle.seek(child_offset + child_header + 4 + 8)
                        timescale, units = struct.unpack(">II", handle.read(8))
                    duration = units / timescale if timescale else None
            return {"duration": duration, "tracks": tracks}
    raise ValueError(f"{path.name} has no MP4 index, so it cannot be prepared.")


def part_path(path: Path) -> Path:
    """Where the rearranged file is written: hidden next to the original, same drive."""
    return path.with_name(f".{path.stem}{PART_SUFFIX}{path.suffix}")


def prepare(path: str | os.PathLike, ffmpeg: str, progress: Callable[[float], None] | None = None,
            cancel: threading.Event | None = None, replace_attempts: int = 40) -> dict:
    """Rewrite `path` in one piece with the index first, then swap it in under the same name.

    Raises ValueError with a readable message on any problem; the original is untouched then."""
    path = Path(path)
    before = summary(path)
    if not before["duration"] or not before["tracks"]:
        raise ValueError(f"{path.name} has no readable length, so it cannot be prepared.")
    free = _free_space(path.parent)
    if free is not None and free < path.stat().st_size + 256 * 1024 * 1024:
        needed = path.stat().st_size / 1073741824
        raise ValueError(f"Not enough free space next to {path.name}: preparing needs about {needed:.1f} GB "
                         "while it works.")
    target = part_path(path)
    target.unlink(missing_ok=True)
    command = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(path), "-map", "0",
               "-c", "copy", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-f", "mp4", str(target)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, creationflags=flags)
    except OSError as error:
        raise ValueError(f"FFmpeg could not start: {error}") from error
    errors: list[str] = []
    reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
    reader.start()
    try:
        for line in process.stdout:
            if cancel is not None and cancel.is_set():
                process.terminate()
                break
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit() and progress is not None:
                # Writing the streams is most of the work; moving the index to the front is the rest.
                progress(min(0.95, int(value) / 1_000_000 / before["duration"] * 0.95))
        process.wait()
        reader.join(timeout=5)
        if cancel is not None and cancel.is_set():
            raise PrepareCancelled("Preparing was stopped. The video is unchanged.")
        if process.returncode != 0:
            detail = "".join(errors).strip().splitlines()[-1:] or [f"exit code {process.returncode}"]
            raise ValueError(f"FFmpeg could not rearrange {path.name}: {detail[0]}")
        after = summary(target)
        if after["tracks"] != before["tracks"] or abs((after["duration"] or 0) - before["duration"]) > 1.0:
            raise ValueError(f"The rearranged copy of {path.name} did not match the original "
                             f"({after['tracks']} tracks, {after['duration'] or 0:.1f} s against "
                             f"{before['tracks']} tracks, {before['duration']:.1f} s), so the original was kept.")
        if needs_preparing(target):
            raise ValueError(f"FFmpeg left {path.name} in pieces, so the original was kept.")
        _replace(target, path, replace_attempts)
        if progress is not None:
            progress(1.0)
        return {"duration": after["duration"], "tracks": after["tracks"], "size": path.stat().st_size}
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        target.unlink(missing_ok=True)


def _replace(source: Path, destination: Path, attempts: int) -> None:
    """os.replace, retried while a reader (the player's last request) still has the original open on Windows."""
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise ValueError(f"{destination.name} is open in another program, so it could not be replaced. "
                                 "Close it there and try again.") from None
            time.sleep(0.25)


def _free_space(folder: Path) -> int | None:
    import shutil
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


class Preparations:
    """Background preparation jobs, one at a time per video file."""

    def __init__(self, find_ffmpeg: Callable[[], str]):
        self._find_ffmpeg = find_ffmpeg
        self._jobs: dict[str, dict] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, path: Path) -> dict:
        import uuid
        path = Path(path)
        with self._lock:
            for job in self._jobs.values():
                if job["path"] == str(path) and job["status"] == "running":
                    return dict(job)
            ffmpeg = self._find_ffmpeg()
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "path": str(path), "name": path.name, "status": "running", "progress": 0.0,
                   "error": "", "started": time.time()}
            self._jobs[job_id] = job
            self._cancels[job_id] = threading.Event()
        threading.Thread(target=self._run, args=(job_id, path, ffmpeg), name=f"prepare-{job_id[:8]}",
                         daemon=True).start()
        return dict(job)

    def _run(self, job_id: str, path: Path, ffmpeg: str) -> None:
        def progress(value: float) -> None:
            with self._lock:
                self._jobs[job_id]["progress"] = round(value, 3)
        try:
            prepare(path, ffmpeg, progress, self._cancels[job_id])
            status, error = "done", ""
        except PrepareCancelled as stopped:
            status, error = "cancelled", str(stopped)
        except (ValueError, OSError) as failure:
            status, error = "failed", str(failure)
        with self._lock:
            self._jobs[job_id].update(status=status, error=error)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def cancel(self, job_id: str) -> dict | None:
        with self._lock:
            if job_id in self._cancels:
                self._cancels[job_id].set()
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def busy(self, path: Path) -> bool:
        with self._lock:
            return any(job["path"] == str(Path(path)) and job["status"] == "running" for job in self._jobs.values())
