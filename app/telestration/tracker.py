"""Follow one player through a clip (docs/TELESTRATION_PLAN.md, M3).

Frames are decoded by the bundled FFmpeg at no more than 540 pixels high, so
tracking is quick and memory stays flat. The OpenCV ViT tracker does the
following (chosen in docs/M0_TRACKING_SPIKE.md); if its model file is missing
the simpler MIL tracker is used and the result says so. A scene cut, or a
second of doubt, stops the span (see segments.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from . import segments

try:  # OpenCV is a runtime dependency; its absence is reported, never hidden.
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - exercised only in a broken installation
    cv2 = None
    np = None

TRACK_HEIGHT = 540
CUT_DISTANCE = 0.45  # Bhattacharyya distance between consecutive frames' colour histograms
EDGE_SHRINK = 0.7  # a box against the frame edge at under 70% of its seed area is leaving the picture
MODEL_NAME = "vittrack.onnx"
REDUCED_NOTICE = "Tracking quality is reduced: the ViT tracker model is missing, so a simpler tracker is used."


class TrackingUnavailable(ValueError):  # reported to the editor as a bad request
    pass


class Cancelled(Exception):
    pass


def model_path() -> Path | None:
    candidates = [Path(__file__).resolve().parent / "models" / MODEL_NAME]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:  # PyInstaller: the app folder is shipped as data
        candidates.append(Path(bundle) / "app" / "telestration" / "models" / MODEL_NAME)
    return next((path for path in candidates if path.is_file()), None)


def make_tracker(model: Path | None = None) -> tuple[Any, str | None]:
    """(tracker, notice); notice is set when quality is reduced."""
    if cv2 is None:
        raise TrackingUnavailable("Player tracking needs OpenCV, which is missing from this installation.")
    model = model if model is not None else model_path()
    if model is not None and model.is_file() and hasattr(cv2, "TrackerVit_create"):
        params = cv2.TrackerVit_Params()
        params.net = str(model)
        return cv2.TrackerVit_create(params), None
    return cv2.TrackerMIL_create(), REDUCED_NOTICE


def tracking_size(width: int, height: int) -> tuple[int, int]:
    """Even width and height, at most TRACK_HEIGHT high, same shape as the clip."""
    out_h = min(height, TRACK_HEIGHT)
    out_h -= out_h % 2
    out_w = max(2, round(width * out_h / height / 2) * 2)
    return out_w, out_h


def read_frames(ffmpeg: str, video: Path, fps: float, start: int, count: int, size: tuple[int, int]) -> Iterator[Any]:
    """`count` BGR frames from frame `start`, scaled to `size`."""
    width, height = size
    # Seek a quarter frame early: accurate seeking keeps frames at or after this time,
    # which is frame `start` and not the one before it.
    seek = max(0.0, (start - 0.25) / fps)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", f"{seek:.6f}", "-i", str(video),
               "-frames:v", str(count), "-vf", f"scale={width}:{height}", "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=flags)
    frame_bytes = width * height * 3
    try:
        for _ in range(count):
            data = process.stdout.read(frame_bytes)
            if len(data) < frame_bytes:
                break
            yield np.frombuffer(data, np.uint8).reshape(height, width, 3)
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.kill()
        process.wait()


def _scene_histogram(frame: Any) -> Any:
    small = cv2.resize(frame, (160, 90))
    hist = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def _shirt_histogram(frame: Any, box: tuple[int, int, int, int]) -> Any:
    """Colour of the upper body inside the box, grass masked out (None if too little is left)."""
    x, y, w, h = box
    region = frame[max(0, y + int(h * 0.2)):max(1, y + int(h * 0.55)), max(0, x + int(w * 0.2)):max(1, x + int(w * 0.8))]
    if region.size == 0:
        return None
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    keep = cv2.bitwise_not(cv2.inRange(hsv, (30, 40, 30), (90, 255, 255)))
    if cv2.countNonZero(keep) < 15:
        return None
    hist = cv2.calcHist([hsv], [0, 1], keep, [18, 4], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def to_pixels(box: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """[footX, footY, w, h] fractions → (x, y, w, h) pixels inside the frame."""
    width, height = size
    fx, fy, w, h = box
    bw = max(4, min(width, round(w * width)))
    bh = max(4, min(height, round(h * height)))
    x = min(max(0, round(fx * width - bw / 2)), width - bw)
    y = min(max(0, round(fy * height - bh)), height - bh)
    return x, y, bw, bh


def to_fractions(box: tuple[float, float, float, float], size: tuple[int, int]) -> tuple[float, float, float, float]:
    width, height = size
    x, y, w, h = box
    return (x + w / 2) / width, (y + h) / height, w / width, h / height


def read_frames_backwards(ffmpeg: str, video: Path, fps: float, first: int, last: int, size: tuple[int, int],
                          chunk: int = 48) -> Iterator[Any]:
    """Frames `last` down to `first`, decoded a short chunk at a time so memory stays flat."""
    top = last
    while top >= first:
        bottom = max(first, top - chunk + 1)
        frames = list(read_frames(ffmpeg, video, fps, bottom, top - bottom + 1, size))
        if not frames:
            return
        yield from reversed(frames)
        top = bottom - 1


def _follow(frames: Iterator[Any], seed: list[float], size: tuple[int, int], fps: float, model: Path | None,
            cancel: threading.Event | None, tick: Callable[[], None]) -> tuple[list[list[float]], str | None, str | None]:
    """One pass of the tracker over `frames`, seeded on the first: (rows, stop reason or None, notice)."""
    tracker, notice = make_tracker(model)
    flagger = segments.Flagger(fps)
    rows: list[list[float]] = []
    reference = previous = None
    seed_area = 1
    for index, frame in enumerate(frames):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        scene = _scene_histogram(frame)
        if index == 0:
            pixels = to_pixels(seed, size)
            tracker.init(frame, pixels)
            reference = _shirt_histogram(frame, pixels)
            seed_area = pixels[2] * pixels[3]
            kind, value = flagger.push(tuple(seed))
        else:
            ok, found = tracker.update(frame)
            x, y, w, h = (int(v) for v in found)
            confidence = float(tracker.getTrackingScore()) if hasattr(tracker, "getTrackingScore") else float(ok)
            shirt = _shirt_histogram(frame, (x, y, w, h)) if ok else None
            colour = (cv2.compareHist(reference, shirt, cv2.HISTCMP_BHATTACHARYYA)
                      if reference is not None and shirt is not None else None)
            against_edge = x <= 1 or y <= 1 or x + w >= size[0] - 1 or y + h >= size[1] - 1
            cut = cv2.compareHist(previous, scene, cv2.HISTCMP_BHATTACHARYYA) > CUT_DISTANCE
            kind, value = flagger.push(to_fractions((x, y, w, h), size), ok=bool(ok), confidence=confidence,
                                       colour=colour, edge=against_edge and w * h < EDGE_SHRINK * seed_area, cut=cut)
        if kind == "stop":
            return rows, value, notice
        rows.append(value)
        previous = scene
        tick()
    return rows, None, notice


def track_span(ffmpeg: str, video: Path, clip: dict[str, Any], start: int, end: int, seed: list[float],
               cancel: threading.Event | None = None, progress: Callable[[int, int], None] | None = None,
               model: Path | None = None, end_box: list[float] | None = None) -> dict[str, Any]:
    """Track from frame `start` (where the player is `seed`) to `end`, inclusive.

    With `end_box` (the player's keyframe on frame end + 1), the span is also tracked backwards from that
    keyframe and the two passes are blended (segments.finish), so the drawing reaches the next keyframe
    without a jump and a stretch one pass lost (a cut, a crowd) can be covered by the other.
    Returns {"start", "rows", "stopped": {"frame", "reason"} | None, "notice", "tracker"};
    rows may hold None for frames neither pass could follow.
    """
    size = tracking_size(clip["width"], clip["height"])
    count = end - start + 1
    work = count * (2 if end_box is not None else 1)
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(min(done, work), work)

    forward, reason, notice = _follow(read_frames(ffmpeg, video, clip["fps"], start, count, size), seed, size,
                                      clip["fps"], model, cancel, tick)
    if not forward:
        raise ValueError("This frame could not be read for tracking.")
    if reason is None and len(forward) < count:
        reason = "end-of-video"
    forward_stop = {"frame": start + len(forward), "reason": reason} if reason else None
    backward = None
    if end_box is not None:
        done = count  # the forward half is over, even if it stopped early
        frames = read_frames_backwards(ffmpeg, video, clip["fps"], start, end + 1, size)
        rows, _, _ = _follow(frames, end_box, size, clip["fps"], model, cancel, tick)
        backward = [None] * count
        for offset, value in enumerate(rows[1:]):  # rows[0] is the next keyframe itself
            backward[count - 1 - offset] = value
    after = segments.row(tuple(end_box), 1.0, segments.KEYFRAME) if end_box is not None else None
    rows, stopped = segments.finish(start, count, clip["fps"], forward, forward_stop, backward, after)
    if progress is not None:
        progress(work, work)
    return {"start": start, "rows": rows, "stopped": stopped, "notice": notice,
            "tracker": "mil" if notice else "vit"}


class TrackingJobs:
    """Tracking runs in the background, one thread per job, with progress and cancel."""

    KEEP = 30

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, work: Callable[[threading.Event, Callable[[int, int], None]], dict[str, Any]]) -> dict[str, Any]:
        import uuid
        job_id = uuid.uuid4().hex[:16]
        cancel = threading.Event()
        with self._lock:
            finished = [key for key, job in self._jobs.items() if job["status"] not in {"queued", "running"}]
            for key in finished[: max(0, len(finished) - self.KEEP)]:
                self._jobs.pop(key, None)
                self._cancels.pop(key, None)
            self._jobs[job_id] = {"id": job_id, "status": "running", "progress": 0.0, "result": None, "error": None}
            self._cancels[job_id] = cancel

        def update(done: int, total: int) -> None:
            with self._lock:
                self._jobs[job_id]["progress"] = round(done / max(1, total), 3)

        def run() -> None:
            try:
                result = work(cancel, update)
                outcome = {"status": "done", "result": result, "progress": 1.0}
            except Cancelled:
                outcome = {"status": "cancelled"}
            except Exception as error:  # reported to the editor, which shows it
                outcome = {"status": "failed", "error": str(error) or error.__class__.__name__}
            with self._lock:
                self._jobs[job_id].update(outcome)

        threading.Thread(target=run, daemon=True, name=f"tracking-{job_id}").start()
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            event = self._cancels.get(job_id)
        if event is None:
            return None
        event.set()
        return self.get(job_id)

    def cancel_all(self) -> None:
        with self._lock:
            events = list(self._cancels.values())
        for event in events:
            event.set()
