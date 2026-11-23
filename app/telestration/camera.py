"""Follow the camera through a clip (docs/CODING_AND_PITCH_PLAN.md, P2).

The analyst marks the pitch on a frame or two (P1). To keep the pitch known on
every other frame, this measures how the picture moves from one frame to the
next: corners in the picture (pitch lines, boards, the crowd) are followed with
optical flow, and a homography is fitted to them with RANSAC, so players running
across the picture are left out as outliers. A broadcast camera turns and zooms
from one place, so the whole picture moves by one homography, not just the grass.

The result is the camera's path: for every frame, the homography taking its
points (fractions of the frame) to the same points on the first frame of its
stretch. A stretch ends at a scene cut, or where the picture cannot be followed
(a fast whip pan, a blur); the next frame starts a new stretch. The editor chains
these from the frames the analyst marked (ui/annotate/camera.js).

Each row also carries how sure the step from the previous frame is (0 to 1):
the share of followed corners that agree with the fitted movement, lowered when
few corners were found. Low values are flagged for the analyst to check.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from . import tracker

try:  # OpenCV is a runtime dependency; its absence is reported, never hidden.
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - exercised only in a broken installation
    cv2 = None
    np = None

CORNERS = 500  # corners followed from each frame
MIN_CORNERS = 12  # fewer followed corners than this and the step is not trusted at all
FULL_CORNERS = 80  # this many agreeing corners or more counts as fully sure
RANSAC_PIXELS = 2.0  # at TRACK_HEIGHT; a corner further than this from the fit is an outlier
MAX_STEP_ZOOM = 1.25  # a frame-to-frame zoom beyond this is not a camera move but a cut or a failure
MAX_FRAMES = 4500  # 3 minutes at 25 fps per request
DIGITS = 7  # significant digits kept for each homography entry
REFERENCE_FRAMES = 50  # frames are measured against a reference frame up to 2 seconds back ...
PERSPECTIVE_CORNERS = 40  # a full homography needs this many agreeing corners ...
PERSPECTIVE_GAIN = 0.7  # ... and must fit them this much closer than a pan, tilt and zoom alone
STEADY_REACH = 2  # frames each side a frame is compared with ...
STEADY_JUMP = 0.003  # ... and how far (a fraction of the frame) it may stray from their median
REFERENCE_SHARE = 0.5  # ... while half its corners are still followed; then the frame becomes the reference


class CameraUnavailable(ValueError):  # reported to the editor as a bad request
    pass


def check_available() -> None:
    if cv2 is None:
        raise CameraUnavailable("Following the camera needs OpenCV, which is missing from this installation.")


def _round(value: float) -> float:
    return float(f"{value:.{DIGITS}g}")


def _to_fractions(matrix: Any, size: tuple[int, int]) -> Any:
    """A pixel homography as one on fractions of the frame."""
    width, height = size
    scale = np.diag([float(width), float(height), 1.0])
    return np.linalg.inv(scale) @ matrix @ scale


def _sensible(step: Any) -> bool:
    """A frame-to-frame move a real camera makes: no flip, no big jump in zoom or perspective."""
    if not np.all(np.isfinite(step)):
        return False
    linear = step[:2, :2]
    det = float(np.linalg.det(linear))
    if det <= 0:
        return False
    zoom = det ** 0.5
    return 1 / MAX_STEP_ZOOM <= zoom <= MAX_STEP_ZOOM and abs(step[2, 0]) < 0.5 and abs(step[2, 1]) < 0.5


def _fit(after: Any, before: Any, threshold: float) -> tuple[Any | None, Any | None]:
    """The camera's move taking `after` points to `before` points: (3x3 pixel matrix, inlier mask).

    A full homography can follow a camera turning far, but on a picture with little texture
    (grass only, the boards out of view) its perspective terms wander. A pan, tilt, zoom and roll
    (a similarity) is steadier, so the homography is used only when it fits clearly better."""
    simple, simple_in = cv2.estimateAffinePartial2D(after, before, method=cv2.RANSAC, ransacReprojThreshold=threshold)
    full, full_in = cv2.findHomography(after, before, cv2.RANSAC, threshold)
    simple = np.vstack([simple, [0.0, 0.0, 1.0]]) if simple is not None else None
    if full is None or full_in is None:
        return (simple, simple_in.reshape(-1).astype(bool)) if simple is not None else (None, None)
    full_in = full_in.reshape(-1).astype(bool)
    if simple is None or full_in.sum() < PERSPECTIVE_CORNERS:
        return (simple, simple_in.reshape(-1).astype(bool)) if simple is not None else (full, full_in)
    points = after[full_in].reshape(-1, 1, 2)
    targets = before[full_in].reshape(-1, 2)
    error = lambda matrix: float(np.median(np.linalg.norm(cv2.perspectiveTransform(points, matrix).reshape(-1, 2) - targets, axis=1)))
    if error(full) < PERSPECTIVE_GAIN * error(simple):
        return full, full_in
    return simple, simple_in.reshape(-1).astype(bool)


class Reference:
    """A frame the following frames are measured against, until they drift too far from it."""

    def __init__(self, gray: Any, path: Any, frame: int) -> None:
        self.gray = gray
        self.path = path  # this frame to the first frame of the stretch
        self.frame = frame
        self.corners = cv2.goodFeaturesToTrack(gray, maxCorners=CORNERS, qualityLevel=0.01, minDistance=7, blockSize=7)


def measure(reference: Reference, current: Any, guess: Any, size: tuple[int, int]) -> tuple[Any | None, float, float]:
    """(homography taking `current` fractions to the reference frame's, sureness 0..1, share of the
    reference corners still followed), or (None, 0, 0). `guess` is the last known such homography."""
    corners = reference.corners
    if corners is None or len(corners) < MIN_CORNERS:
        return None, 0.0, 0.0
    width, height = size
    scale = np.diag([float(width), float(height), 1.0])
    # Where the reference corners should be now if the camera kept still since the last frame: a head start
    # for the flow, so a long way from the reference is still found.
    back = scale @ np.linalg.inv(guess) @ np.linalg.inv(scale)
    start = cv2.perspectiveTransform(corners, back).astype(np.float32)
    moved, status, _ = cv2.calcOpticalFlowPyrLK(reference.gray, current, corners, start, winSize=(21, 21), maxLevel=3,
                                                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
                                                flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
    if moved is None:
        return None, 0.0, 0.0
    kept = status.reshape(-1).astype(bool)
    inside = (moved[:, 0, 0] >= 0) & (moved[:, 0, 0] < width) & (moved[:, 0, 1] >= 0) & (moved[:, 0, 1] < height)
    kept &= inside
    before, after = corners[kept], moved[kept]
    share = len(before) / len(corners)
    if len(before) < MIN_CORNERS:
        return None, 0.0, share
    threshold = RANSAC_PIXELS * height / tracker.TRACK_HEIGHT
    matrix, inliers = _fit(after, before, threshold)
    if matrix is None:
        return None, 0.0, share
    agreeing = int(inliers.sum())
    if agreeing < MIN_CORNERS:
        return None, 0.0, share
    step = _to_fractions(matrix, size)
    step = step / step[2, 2]
    if not _sensible(step @ np.linalg.inv(guess)):  # judged against the last frame: one frame's move
        return None, 0.0, share
    sure = (agreeing / len(before)) * min(1.0, agreeing / FULL_CORNERS)
    return step, round(sure, 3), share * agreeing / len(before)


GRID = np.array([[[0.25, 0.25]], [[0.75, 0.25]], [[0.75, 0.75]], [[0.25, 0.75]]], np.float64) if np is not None else None


def _steady(paths: list[Any], starts: list[int], sure: list[float]) -> None:
    """Replace a frame that jumps away from the frames either side (one bad fit) by their median.

    Each frame is measured against a reference frame, so one bad fit does not carry on; it is
    only a jolt on that frame, which this takes out. Changed in place; its sureness is halved."""
    breaks = set(starts)
    corners = [cv2.perspectiveTransform(GRID, path).reshape(-1, 2) for path in paths]
    for index in range(len(paths)):
        low, high = index - STEADY_REACH, index + STEADY_REACH
        if low < 0 or high >= len(paths) or any(frame in breaks for frame in range(low + 1, high + 1)):
            continue
        middle = np.median(np.stack([corners[i] for i in range(low, high + 1)]), axis=0)
        if np.abs(corners[index] - middle).max() > STEADY_JUMP:
            paths[index] = cv2.getPerspectiveTransform(GRID.reshape(-1, 2).astype(np.float32), middle.astype(np.float32))
            sure[index] = round(sure[index] / 2, 3)


def follow_camera(ffmpeg: str, video: Path, clip: dict[str, Any], start: int, end: int,
                  cancel: threading.Event | None = None,
                  progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
    """The camera's path over frames `start` to `end` (inclusive).

    Returns {"from": start, "rows": [[h11, h12, h13, h21, h22, h23, h31, h32, sure], ...], "starts": [...]}:
    row i is frame start + i; its homography takes that frame's points to the first frame of its stretch,
    and `starts` lists the frames that begin a stretch (the first frame always does). The first frame of a
    stretch has the identity and sureness 1.
    """
    check_available()
    size = tracker.tracking_size(clip["width"], clip["height"])
    count = end - start + 1
    paths: list[Any] = []
    sureness: list[float] = []
    starts: list[int] = []
    previous_gray = None
    reference: Reference | None = None
    guess = previous_scene = None
    for index, frame in enumerate(tracker.read_frames(ffmpeg, video, clip["fps"], start, count, size)):
        if cancel is not None and cancel.is_set():
            raise tracker.Cancelled()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        scene = tracker._scene_histogram(frame)
        step = None
        sure = 1.0
        if reference is not None and cv2.compareHist(previous_scene, scene, cv2.HISTCMP_BHATTACHARYYA) <= tracker.CUT_DISTANCE:
            step, sure, share = measure(reference, gray, guess, size)
            if step is None and reference.frame != index - 1:
                # Too far from the reference: measure from the frame before instead, which becomes the reference.
                reference = Reference(previous_gray, reference.path @ guess, index - 1)
                step, sure, share = measure(reference, gray, np.eye(3), size)
        if step is None:
            reference = Reference(gray, np.eye(3), index)
            starts.append(start + index)
            guess, sure = np.eye(3), 1.0
            path = reference.path
        else:
            guess = step
            path = reference.path @ step
            path = path / path[2, 2]
            if share < REFERENCE_SHARE or index - reference.frame >= REFERENCE_FRAMES:
                reference = Reference(gray, path, index)
                guess = np.eye(3)
        paths.append(path)
        sureness.append(sure)
        previous_gray, previous_scene = gray, scene
        if progress is not None:
            progress(index + 1, count)
    if not paths:
        raise ValueError("This clip could not be read to follow the camera.")
    _steady(paths, [frame - start for frame in starts], sureness)
    rows = [[_round(value) for value in (path / path[2, 2]).reshape(-1)[:8]] + [sure] for path, sure in zip(paths, sureness)]
    return {"from": start, "rows": rows, "starts": starts}
