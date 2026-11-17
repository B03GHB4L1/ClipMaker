"""Find the players on one frame, and split them into two teams (docs/TELESTRATION_PLAN.md, M7).

Measured in the M6 spike (docs/M6_BOARD_SPIKE.md): YOLOX-Nano on a 3 x 2 grid of
tiles finds about 93% of players on wide broadcast shots in about half a second
on a laptop CPU, through OpenCV's DNN module (no other runtime). Teams come from
shirt colour, no model.

The model is an optional download (3.7 MB, Apache 2.0, from the official YOLOX
release), checked against a fixed SHA-256 before it is used. Without it the
editor says so and offers the download; nothing is skipped silently.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterable

from .tracker import Cancelled  # the job runner reports this as "cancelled", not "failed"

MODEL_NAME = "yolox_nano.onnx"
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
MODEL_SHA256 = "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d"
MODEL_BYTES = 3_659_407
MODEL_LABEL = "Player finder (YOLOX-Nano, Apache 2.0)"
INPUT = 416  # the model's input size
TILES = (3, 2)  # columns, rows
OVERLAP = 0.15
SCORE = 0.3
NMS_IOU = 0.45
GRASS_LOW, GRASS_HIGH = (30, 40, 40), (90, 255, 255)


class ModelMissing(LookupError):
    """The player finder has not been downloaded yet."""


# ---------------------------------------------------------------------------
# The model file
# ---------------------------------------------------------------------------
def model_path(folder: Path) -> Path:
    return folder / MODEL_NAME


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def status(folder: Path) -> dict[str, Any]:
    path = model_path(folder)
    return {"installed": path.is_file() and path.stat().st_size == MODEL_BYTES, "bytes": MODEL_BYTES,
            "label": MODEL_LABEL, "source": MODEL_URL}


def _open_url(url: str) -> Any:
    from urllib.request import Request, urlopen
    return urlopen(Request(url, headers={"User-Agent": "VizorPlay model download"}), timeout=30)  # noqa: S310 - fixed https URL


def install(folder: Path, cancel: threading.Event, progress: Callable[[int, int], None],
            opener: Callable[[str], Any] = _open_url) -> dict[str, Any]:
    """Download the model, check its SHA-256, then move it into place. Nothing is kept on any failure."""
    folder.mkdir(parents=True, exist_ok=True)
    target = model_path(folder)
    partial = target.with_suffix(".part")
    sha = hashlib.sha256()
    received = 0
    try:
        with opener(MODEL_URL) as response, partial.open("wb") as output:
            while True:
                if cancel.is_set():
                    raise Cancelled()
                block = response.read(1 << 16)
                if not block:
                    break
                received += len(block)
                if received > MODEL_BYTES:
                    raise ValueError("The player finder download is larger than expected; it was not kept.")
                sha.update(block)
                output.write(block)
                progress(received, MODEL_BYTES)
        if received != MODEL_BYTES or sha.hexdigest() != MODEL_SHA256:
            raise ValueError("The player finder download did not match its checksum; it was not kept.")
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return status(folder)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
class Detector:
    def __init__(self, path: Path) -> None:
        import cv2
        import numpy as np
        if not path.is_file():
            raise ModelMissing("Download the player finder first.")
        if _digest(path) != MODEL_SHA256:
            raise ModelMissing("The player finder file is damaged. Download it again.")
        self.net = cv2.dnn.readNetFromONNX(str(path))
        grids, strides = [], []
        for stride in (8, 16, 32):
            n = INPUT // stride
            ys, xs = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
            grids.append(np.stack((xs, ys), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), stride))
        self.grids, self.strides = np.concatenate(grids), np.concatenate(strides)

    def _detect(self, image: Any) -> tuple[Any, Any]:
        import cv2
        import numpy as np
        h, w = image.shape[:2]
        r = min(INPUT / h, INPUT / w)
        canvas = np.full((INPUT, INPUT, 3), 114, np.uint8)
        resized = cv2.resize(image, (max(1, int(round(w * r))), max(1, int(round(h * r)))))
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        self.net.setInput(canvas.transpose(2, 0, 1)[None].astype(np.float32))
        out = self.net.forward()[0]
        xy = (out[:, :2] + self.grids) * self.strides
        wh = np.exp(out[:, 2:4]) * self.strides
        score = out[:, 4] * out[:, 5]  # objectness x person
        keep = score > SCORE
        boxes = np.concatenate((xy[keep] - wh[keep] / 2, wh[keep]), 1) / r
        return boxes, score[keep]

    def people(self, frame: Any, cancel: threading.Event | None = None) -> list[list[float]]:
        """[x, y, w, h] pixel boxes of people standing on the grass."""
        import cv2
        import numpy as np
        h, w = frame.shape[:2]
        found, scores = [], []
        for x0, y0, x1, y1 in tiles(w, h):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            boxes, score = self._detect(frame[y0:y1, x0:x1])
            boxes[:, 0] += x0
            boxes[:, 1] += y0
            found.append(boxes)
            scores.append(score)
        boxes, score = np.concatenate(found), np.concatenate(scores)
        if not len(boxes):
            return []
        keep = np.array(cv2.dnn.NMSBoxes(boxes.tolist(), score.tolist(), SCORE, NMS_IOU), dtype=int).reshape(-1)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        return [[float(v) for v in boxes[i]] for i in keep if boxes[i][3] >= 8 and on_grass(hsv, boxes[i])]


def tiles(width: int, height: int, grid: tuple[int, int] = TILES, overlap: float = OVERLAP) -> Iterable[tuple[int, int, int, int]]:
    """Overlapping tiles covering the frame, so small far-away players are big enough for the model."""
    cols, rows = grid
    tw, th = width / (cols - (cols - 1) * overlap), height / (rows - (rows - 1) * overlap)
    for j in range(rows):
        for i in range(cols):
            x, y = int(i * tw * (1 - overlap)), int(j * th * (1 - overlap))
            right = width if i == cols - 1 else min(width, int(round(x + tw)))  # the last tile reaches the edge
            bottom = height if j == rows - 1 else min(height, int(round(y + th)))
            yield x, y, right, bottom


def on_grass(hsv: Any, box: Any) -> bool:
    """Feet on the pitch: the strip under the box is mostly grass. Removes most of the crowd and staff."""
    import cv2
    x, y, w, h = box
    height, width = hsv.shape[:2]
    x0, x1 = int(max(0, x - w * 0.5)), int(min(width, x + w * 1.5))
    y0, y1 = int(min(height - 1, y + h * 0.9)), int(min(height, y + h * 1.15 + 2))
    strip = hsv[y0:y1, x0:x1]
    if strip.size == 0:
        return True  # feet at the bottom edge of the frame
    return cv2.inRange(strip, GRASS_LOW, GRASS_HIGH).mean() / 255 > 0.35


# ---------------------------------------------------------------------------
# Teams by shirt colour
# ---------------------------------------------------------------------------
def shirt(frame: Any, box: Any) -> tuple[Any, Any] | None:
    """(hue direction in Lab a*b*, mean BGR) of the shirt, or None when too little of it shows.

    Only the direction of the colour counts: bright sun washes a blue shirt out to
    pale blue, but it stays blue. White sleeves, shorts and skin carry little colour
    and are left out.
    """
    import cv2
    import numpy as np
    x, y, w, h = [int(round(v)) for v in box]
    x0, x1 = max(0, x + w // 5), min(frame.shape[1], x + w - w // 5)
    y0, y1 = max(0, y + int(h * 0.24)), min(frame.shape[0], y + int(h * 0.48))
    patch = frame[y0:y1, x0:x1]
    if patch.size == 0:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    keep = (cv2.inRange(hsv, GRASS_LOW, GRASS_HIGH) == 0).reshape(-1)
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB).reshape(-1, 3)[keep]
    bgr = patch.reshape(-1, 3)[keep]
    if len(lab) < 6:
        return None
    ab = lab[:, 1:].astype(np.float32) - 128
    coloured = np.linalg.norm(ab, axis=1) > 4
    if coloured.sum() < 4:
        return None
    direction = np.median(ab[coloured], 0)
    return 30 * direction / (np.linalg.norm(direction) + 1e-6), bgr[coloured].mean(0)


def split_teams(frame: Any, boxes: list[list[float]]) -> tuple[list[int], list[str]]:
    """Team per box (0, 1, or 2 for "other": referees, often goalkeepers) and the two teams' colours."""
    import cv2
    import numpy as np
    samples = [shirt(frame, box) for box in boxes]
    usable = [i for i, sample in enumerate(samples) if sample is not None]
    teams = [2] * len(boxes)
    colours = ["#d6262e", "#1f5fd1"]
    if len(usable) < 2:
        return teams, colours
    data = np.array([samples[i][0] for i in usable], np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
    _, labels, centres = cv2.kmeans(data, 2, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(-1)
    distance = np.linalg.norm(data - centres[labels], axis=1)
    labels[distance > max(12.0, 3.5 * (np.median(distance) + 1e-3))] = 2
    # The bigger team first, so the order does not flip between frames of the same match.
    sizes = [(labels == k).sum() for k in (0, 1)]
    order = [0, 1] if sizes[0] >= sizes[1] else [1, 0]
    for i, label in zip(usable, labels):
        teams[i] = order.index(int(label)) if label < 2 else 2
    for team, k in enumerate(order):
        members = [samples[usable[j]][1] for j in range(len(usable)) if labels[j] == k]
        if members:
            colours[team] = token_colour(np.mean(members, 0))
    return teams, colours


def token_colour(bgr: Any) -> str:
    """A clear version of a shirt's average colour for a token: sun and shadow average out to a dull tone."""
    import cv2
    import numpy as np
    pixel = np.uint8([[np.clip(bgr, 0, 255)]])
    h, s, v = cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0, 0]
    if s >= 40:  # a real colour: make it vivid
        s, v = max(int(s), 170), max(int(v), 200)
    b, g, r = cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def find_players(ffmpeg: str, video: Path, record: dict[str, Any], frame_index: int, folder: Path,
                 cancel: threading.Event, progress: Callable[[int, int], None]) -> dict[str, Any]:
    """Players on one frame: feet and box as fractions of the frame, team, and the teams' shirt colours."""
    from .tracker import read_frames
    detector = Detector(model_path(folder))
    progress(1, 4)
    width, height = record["width"], record["height"]
    frame = next(read_frames(ffmpeg, video, record["fps"], frame_index, 1, (width, height)), None)
    if frame is None:
        raise ValueError("That frame of the clip could not be read.")
    progress(2, 4)
    boxes = detector.people(frame, cancel)
    progress(3, 4)
    teams, colours = split_teams(frame, boxes)
    players = [{"box": [round((x + w / 2) / width, 5), round((y + h) / height, 5), round(w / width, 5), round(h / height, 5)],
                "team": team} for (x, y, w, h), team in zip(boxes, teams)]
    return {"frame": frame_index, "players": players, "teams": colours}
