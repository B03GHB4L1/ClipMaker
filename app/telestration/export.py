"""Export an annotated clip with its drawings and freezes burned in (docs/TELESTRATION_PLAN.md, M4).

The editor draws each overlay with the same code as its live preview
(ui/annotate/shapes.js) at the clip's own size and, for every output frame
where the drawings change, sends the pixels of the box that holds them
(straight-alpha RGBA, as a canvas gives them; no picture encoding, which
browsers slow to a crawl in a hidden window). This module lays those
overlays over the clip's frames, holds each freeze frame for its length,
puts silence under freezes so the sound stays in step, and encodes the result.
Drawings therefore look the same in the export as on screen, and no fonts or
drawing code are duplicated in Python.

An export session lives in its own folder under the data directory:

    editor-exports/<id>/overlay-000123-40-30-200-90.rgba   from output frame 123: a 200x90 box at (40, 30)
    editor-exports/<id>/overlay-000456.clear                the drawings are gone from frame 456
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Callable

from . import parts as cuts, timeline
from .tracker import Cancelled, read_frames  # Cancelled: the job runner reports it as cancelled

AUDIO_RATE = 48_000
AUDIO_CHANNELS = 2
OVERLAY_LIMIT = 4096 * 2160 * 4  # a whole 4K frame of RGBA pixels
BATCH_LIMIT = 64_000_000  # bytes in one request
BATCH_ENTRIES = 1000
SKIP_FRAMES = 100  # decode through a gap this small; a bigger jump seeks again
MAX_TILES = 4096  # tiles in one patch: a 4K frame in 64 px tiles is 2040
MAX_OUTPUT_FRAMES = 20 * 60 * 60  # 20 minutes at 60 fps
SESSION_TTL = 6 * 3600


def output_frames(record: dict[str, Any], freezes: list[dict[str, Any]], parts: list[dict[str, int]] | None = None) -> int:
    """How many frames the finished clip has: its parts plus freezes, at the clip's frame rate."""
    cut = cuts.cut_clip(record, parts)
    return max(1, round(timeline.total_seconds(cut["duration"], freezes) * record["fps"]))


def source_frames(record: dict[str, Any], freezes: list[dict[str, Any]], count: int,
                  parts: list[dict[str, int]] | None = None) -> list[int]:
    """The source frame shown on each output frame. It only goes forwards within a part; parts may be
    reordered or repeated, so it can jump."""
    fps = record["fps"]
    cut = cuts.cut_clip(record, parts)
    return [cuts.cut_to_source(
        timeline.output_to_source(n / fps, fps, cut["duration"], cut["frames"], freezes)["frame"], parts, record["frames"])
        for n in range(count)]


def silence_plan(record: dict[str, Any], freezes: list[dict[str, Any]], rate: int = AUDIO_RATE) -> list[tuple[int, int]]:
    """(sample where a freeze starts in the source sound, samples of silence to insert), in order."""
    return [(round(f["atFrame"] / record["fps"] * rate), round(f["seconds"] * rate))
            for f in sorted(freezes, key=lambda f: f["atFrame"])]


# ---------------------------------------------------------------------------
# Sessions: the overlays arrive one request at a time, then the render runs as a job.
# ---------------------------------------------------------------------------
class ExportSessions:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, project_id: str, clip_id: str, record: dict[str, Any], video: Path,
               document: dict[str, Any]) -> dict[str, Any]:
        self.prune()
        freezes = document.get("freezes") or []
        parts = document.get("parts") or None
        count = output_frames(record, freezes, parts)
        if count > MAX_OUTPUT_FRAMES:
            raise ValueError("Exports can be up to 20 minutes long.")
        session_id = uuid.uuid4().hex[:16]
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True)
        session = {"id": session_id, "project": project_id, "clip": clip_id, "record": record, "video": video,
                   "freezes": freezes, "parts": parts, "frames": count, "folder": folder, "last": -1, "started": False,
                   "created": time.time()}
        with self._lock:
            self._sessions[session_id] = session
        return {"id": session_id, "frames": count, "fps": record["fps"], "width": record["width"],
                "height": record["height"]}

    def get(self, session_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(r"[a-f0-9]{16}", session_id or ""):
            return None
        with self._lock:
            return self._sessions.get(session_id)

    def add_overlay(self, session_id: str, frame: Any, data: bytes, box: Any = None, tiles: Any = None) -> None:
        """Store the overlay from output frame `frame` on: RGBA pixels of `box` (x, y, width, height).
        Empty data means no drawings from that frame. With `tiles` instead, `data` holds the pixels
        of those boxes, laid over the overlay before (a patch: moving board tokens, M8)."""
        session = self.get(session_id)
        if session is None:
            raise LookupError("This export is no longer open. Start it again.")
        if session["started"]:
            raise ValueError("This export is already rendering.")
        if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < session["frames"]:
            raise ValueError("Overlay frames must be frames of the export.")
        if frame <= session["last"]:
            raise ValueError("Overlays must arrive in order.")
        record = session["record"]
        if tiles is not None:
            if box is not None or session["last"] < 0:
                raise ValueError("A patch goes over an earlier overlay.")
            if not isinstance(tiles, list) or not 1 <= len(tiles) <= MAX_TILES:
                raise ValueError("A patch needs between 1 and 4096 tiles.")
            size = 0
            for tile in tiles:
                if (not isinstance(tile, list) or len(tile) != 4
                        or any(isinstance(v, bool) or not isinstance(v, int) for v in tile)):
                    raise ValueError("Each tile needs x, y, width and height.")
                x, y, w, h = tile
                if not (0 <= x and 0 <= y and w >= 1 and h >= 1 and x + w <= record["width"] and y + h <= record["height"]):
                    raise ValueError("A tile must be inside the frame.")
                size += w * h * 4
            if len(data) != size:
                raise ValueError("The patch's size does not match its tiles.")
            header = json.dumps(tiles).encode("utf-8")
            data = len(header).to_bytes(4, "big") + header + data
            name = f"overlay-{frame:06d}.patch"
        elif data:
            if (not isinstance(box, (list, tuple)) or len(box) != 4
                    or any(isinstance(v, bool) or not isinstance(v, int) for v in box)):
                raise ValueError("Overlays need their box: x, y, width and height.")
            x, y, w, h = box
            if not (0 <= x and 0 <= y and w >= 1 and h >= 1 and x + w <= record["width"] and y + h <= record["height"]):
                raise ValueError("The overlay's box must be inside the frame.")
            if len(data) != w * h * 4:
                raise ValueError("The overlay's size does not match its box.")
            name = f"overlay-{frame:06d}-{x}-{y}-{w}-{h}.rgba"
        if tiles is None and not data:
            name = f"overlay-{frame:06d}.clear"
        target = session["folder"] / name
        temporary = target.with_suffix(".part")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        session["last"] = frame

    def add_batch(self, session_id: str, body: bytes) -> int:
        """Store several overlays sent in one request (see unpack_batch); returns how many."""
        entries = unpack_batch(body)
        for frame, box, pixels, tiles in entries:
            self.add_overlay(session_id, frame, pixels, box, tiles)
        return len(entries)

    def take(self, session_id: str) -> dict[str, Any]:
        """Mark the session as rendering and hand it over (only once)."""
        session = self.get(session_id)
        if session is None:
            raise LookupError("This export is no longer open. Start it again.")
        with self._lock:
            if session["started"]:
                raise ValueError("This export is already rendering.")
            session["started"] = True
        return session

    def discard(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            shutil.rmtree(session["folder"], ignore_errors=True)
        return session is not None

    def prune(self) -> None:
        """Forget sessions nobody finished, and remove leftover folders from earlier runs."""
        now = time.time()
        with self._lock:
            stale = [key for key, s in self._sessions.items() if not s["started"] and now - s["created"] > SESSION_TTL]
        for key in stale:
            self.discard(key)
        if self.root.is_dir():
            with self._lock:
                live = set(self._sessions)
            for folder in self.root.iterdir():
                if folder.is_dir() and folder.name not in live and now - folder.stat().st_mtime > SESSION_TTL:
                    shutil.rmtree(folder, ignore_errors=True)


def unpack_batch(body: bytes) -> list[tuple[Any, Any, bytes, Any]]:
    """A batch is a 4-byte big-endian length, a JSON list of {"frame", "box": [x, y, w, h] | null}
    or {"frame", "tiles": [[x, y, w, h], ...]}, then each entry's RGBA pixels (w * h * 4 bytes per
    box or tile, in order; none when box is null). One request carries many frames because each
    request is a new connection here."""
    if len(body) < 4:
        raise ValueError("The overlays did not arrive in full.")
    size = int.from_bytes(body[:4], "big")
    if size > 200_000 or 4 + size > len(body):
        raise ValueError("The overlays did not arrive in full.")
    try:
        header = json.loads(body[4:4 + size].decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("The overlays could not be read.") from None
    if not isinstance(header, list) or not 1 <= len(header) <= BATCH_ENTRIES:
        raise ValueError("Send between 1 and 1000 overlays at a time.")
    entries, offset = [], 4 + size
    for entry in header:
        if not isinstance(entry, dict):
            raise ValueError("The overlays could not be read.")
        box, tiles = entry.get("box"), entry.get("tiles")
        length = 0
        if tiles is not None:
            if box is not None or not isinstance(tiles, list) or not 1 <= len(tiles) <= MAX_TILES:
                raise ValueError("A patch needs between 1 and 4096 tiles.")
            for tile in tiles:
                if (not isinstance(tile, list) or len(tile) != 4
                        or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in tile)):
                    raise ValueError("Each tile needs x, y, width and height.")
                length += tile[2] * tile[3] * 4
            if not length:
                raise ValueError("A tile must be inside the frame.")
        elif box is not None:
            if (not isinstance(box, list) or len(box) != 4
                    or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in box)):
                raise ValueError("Overlays need their box: x, y, width and height.")
            length = box[2] * box[3] * 4
            if not length:
                raise ValueError("The overlay's box must be inside the frame.")
        if offset + length > len(body):
            raise ValueError("The overlays did not arrive in full.")
        entries.append((entry.get("frame"), box, body[offset:offset + length], tiles))
        offset += length
    if offset != len(body):
        raise ValueError("The overlays did not arrive in full.")
    return entries


OVERLAY_NAME = re.compile(r"overlay-(\d{6})(?:-(\d+)-(\d+)-(\d+)-(\d+)\.rgba|\.clear|\.patch)")


def overlay_schedule(folder: Path) -> dict[int, Path | None]:
    """Output frame -> overlay or patch file (None: no drawings) where the overlay changes."""
    schedule: dict[int, Path | None] = {}
    for path in folder.iterdir():
        match = OVERLAY_NAME.fullmatch(path.name)
        if match:
            schedule[int(match[1])] = path if match[2] is not None or path.suffix == ".patch" else None
    return schedule


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def has_audio(ffmpeg: str, video: Path) -> bool:
    result = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(video)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, errors="replace", timeout=30, creationflags=_flags())
    return bool(re.search(r"Stream #\S+.*?Audio:", result.stderr))


def write_audio(ffmpeg: str, video: Path, record: dict[str, Any], freezes: list[dict[str, Any]], target: Path,
                cancel: threading.Event | None = None, parts: list[dict[str, int]] | None = None) -> None:
    """The clip's sound as a WAV file: its parts in order, with silence inserted under every freeze."""
    raw = target.with_suffix(".pcm")
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(video), "-vn",
               "-ac", str(AUDIO_CHANNELS), "-ar", str(AUDIO_RATE), "-f", "s16le", str(raw)]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                            timeout=600, creationflags=_flags())
    if result.returncode != 0:
        raise ValueError(f"Could not read the clip's sound: {(result.stderr or '')[-300:]}")
    sample_bytes = 2 * AUDIO_CHANNELS
    try:
        with raw.open("rb") as source, wave.open(str(target), "wb") as output:
            output.setnchannels(AUDIO_CHANNELS)
            output.setsampwidth(2)
            output.setframerate(AUDIO_RATE)
            for step, first, last in cuts.audio_plan(parts, freezes, record["fps"], AUDIO_RATE, record["frames"]):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if step == "silence":
                    output.writeframes(bytes(first * sample_bytes))
                    continue
                source.seek(first * sample_bytes)
                remaining = None if last < 0 else max(0, last - first) * sample_bytes
                while remaining is None or remaining > 0:
                    chunk = source.read(1 << 20 if remaining is None else min(1 << 20, remaining))
                    if not chunk:
                        break  # the sound ran out before the picture did
                    output.writeframes(chunk)
                    if remaining is not None:
                        remaining -= len(chunk)
    finally:
        raw.unlink(missing_ok=True)


class Overlay:
    """An overlay: the box of pixels that has drawings in it."""

    def __init__(self, path: Path | None, width: int, height: int) -> None:
        import numpy as np
        if path is None:  # nothing drawn yet: a clear frame, for patches to go over
            self.box = (slice(0, height), slice(0, width))
            self.alpha = np.zeros((height, width, 1), np.float32)
            self.colour = np.zeros((height, width, 3), np.float32)
            return
        match = OVERLAY_NAME.fullmatch(path.name)
        x, y, w, h = (int(v) for v in match.groups()[1:])
        pixels = np.fromfile(str(path), np.uint8)
        if pixels.size != w * h * 4 or x + w > width or y + h > height:
            raise ValueError("An overlay could not be read.")
        region = pixels.reshape(h, w, 4)
        self.box = (slice(y, y + h), slice(x, x + w))
        self.alpha = region[:, :, 3:4].astype(np.float32) / 255.0
        self.colour = region[:, :, 2::-1].astype(np.float32)  # RGBA -> BGR, the frames' order

    def patched(self, path: Path, width: int, height: int) -> "Overlay":
        """This overlay with a patch's tiles laid in (they replace the pixels under them)."""
        import numpy as np
        body = path.read_bytes()
        size = int.from_bytes(body[:4], "big")
        tiles = json.loads(body[4:4 + size].decode("utf-8"))
        whole = self if self.box == (slice(0, height), slice(0, width)) else self._whole(width, height)
        offset = 4 + size
        for x, y, w, h in tiles:
            if x + w > width or y + h > height or offset + w * h * 4 > len(body):
                raise ValueError("An overlay could not be read.")
            region = np.frombuffer(body, np.uint8, w * h * 4, offset).reshape(h, w, 4)
            whole.alpha[y:y + h, x:x + w] = region[:, :, 3:4].astype(np.float32) / 255.0
            whole.colour[y:y + h, x:x + w] = region[:, :, 2::-1].astype(np.float32)
            offset += w * h * 4
        return whole

    def _whole(self, width: int, height: int) -> "Overlay":
        """A copy covering the whole frame, so patches can land anywhere."""
        whole = Overlay(None, width, height)
        whole.alpha[self.box] = self.alpha
        whole.colour[self.box] = self.colour
        return whole

    def apply(self, frame: Any) -> Any:
        """The frame with the overlay laid over it (straight alpha, as a canvas exports it)."""
        out = frame.copy()
        base = out[self.box].astype(self.alpha.dtype)
        out[self.box] = (base + (self.colour - base) * self.alpha + 0.5).astype(frame.dtype)
        return out


def render(ffmpeg: str, video: Path, record: dict[str, Any], freezes: list[dict[str, Any]], count: int,
           schedule: dict[int, Path | None], target: str, encoder: str,
           cancel: threading.Event | None = None, progress: Callable[[int, int], None] | None = None,
           parts: list[dict[str, int]] | None = None) -> None:
    """Write the finished clip to `target` (an .mp4 written whatever its name)."""
    import video_encoder as encoders

    width, height, fps = record["width"], record["height"], record["fps"]
    shown = source_frames(record, freezes, count, parts)
    with tempfile.TemporaryDirectory(prefix="vizorplay-export-") as scratch:
        audio = Path(scratch) / "sound.wav"
        sound = has_audio(ffmpeg, video)
        if sound:
            write_audio(ffmpeg, video, record, freezes, audio, cancel, parts)
        _, video_args = encoders.video_args(encoder, ffmpeg, 18, "veryfast")
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-"]
        if sound:
            command += ["-i", str(audio)]
        command += ["-map", "0:v:0", *(["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"] if sound else []),
                    *video_args, "-pix_fmt", "yuv420p", "-t", f"{count / fps:.6f}",
                    "-movflags", "+faststart", "-f", "mp4", target]
        errors = Path(scratch) / "encoder.log"
        with errors.open("wb") as log:
            encoder_process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                                               creationflags=_flags())
            frames = None
            current_index, current = -1, None
            overlay = None
            try:
                for n, wanted in enumerate(shown):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    if frames is None or wanted < current_index or wanted > current_index + SKIP_FRAMES:
                        # The first frame, or a cut, reorder or repeat: decode again from here.
                        if frames is not None:
                            frames.close()
                        frames = read_frames(ffmpeg, video, fps, wanted, record["frames"] - wanted + 2, (width, height))
                        current_index, current = wanted - 1, None
                    while current_index < wanted:
                        following = next(frames, None)
                        if following is None:
                            break  # the clip ran out a frame early: keep showing its last frame
                        current, current_index = following, current_index + 1
                    if current is None:
                        raise ValueError("The clip's frames could not be read.")
                    if n in schedule:
                        path = schedule[n]
                        if path is not None and path.suffix == ".patch":
                            overlay = (overlay or Overlay(None, width, height)).patched(path, width, height)
                        else:
                            overlay = Overlay(path, width, height) if path is not None else None
                    picture = overlay.apply(current) if overlay is not None else current
                    try:
                        encoder_process.stdin.write(picture.tobytes())
                    except (BrokenPipeError, OSError):
                        break  # the encoder stopped; its log says why
                    if progress is not None and (n % 5 == 0 or n == count - 1):
                        progress(n + 1, count)
            except BaseException:
                encoder_process.kill()
                encoder_process.wait()  # Windows keeps the half-written file locked until it has gone
                raise
            finally:
                if frames is not None:
                    frames.close()
                try:
                    encoder_process.stdin.close()
                except OSError:
                    pass
            code = encoder_process.wait()
        if code != 0:
            message = errors.read_text(errors="replace")[-500:]
            if encoder != encoders.SOFTWARE:
                raise encoders.HardwareEncodeError(message)
            raise ValueError(f"Could not encode the video: {message}")


# ---------------------------------------------------------------------------
# Sequences: a session's clips, each rendered as above, joined into one video (T2)
# ---------------------------------------------------------------------------
def _even(value: int) -> int:
    return max(2, int(value) // 2 * 2)


def join_plan(pieces: list[dict[str, Any]]) -> dict[str, Any]:
    """How to join rendered pieces [{width, height, fps, seconds, sound}]: the first clip sets the size and
    frame rate; when every piece already matches (and all or none have sound) they are copied, not re-encoded."""
    if not pieces:
        raise ValueError("A sequence needs at least one clip.")
    first = pieces[0]
    width, height, fps = _even(first["width"]), _even(first["height"]), float(first["fps"])
    sound = any(piece["sound"] for piece in pieces)
    same = all(piece["width"] == width and piece["height"] == height and abs(float(piece["fps"]) - fps) < 1e-3
               for piece in pieces)
    copy = same and len({bool(piece["sound"]) for piece in pieces}) == 1
    return {"width": width, "height": height, "fps": fps, "sound": sound, "copy": copy,
            "seconds": sum(float(piece["seconds"]) for piece in pieces)}


def join_filter(pieces: list[dict[str, Any]], plan: dict[str, Any]) -> str:
    """The ffmpeg filter graph that scales, pads and joins the pieces, with silence for a piece without sound.
    The frame rate is set on the output (-r): an fps filter on each piece drops its last frame."""
    width, height = plan["width"], plan["height"]
    chains, labels = [], []
    for index, piece in enumerate(pieces):
        chains.append(f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                      f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{index}]")
        labels.append(f"[v{index}]")
        if plan["sound"]:
            if piece["sound"]:
                chains.append(f"[{index}:a]aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{index}]")
            else:
                chains.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=duration={float(piece['seconds']):.6f},"
                              f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]")
            labels.append(f"[a{index}]")
    audio = 1 if plan["sound"] else 0
    chains.append(f"{''.join(labels)}concat=n={len(pieces)}:v=1:a={audio}[v]" + ("[a]" if audio else ""))
    return ";".join(chains)


def join(ffmpeg: str, pieces: list[dict[str, Any]], target: str, encoder: str, scratch: Path,
         cancel: threading.Event | None = None, progress: Callable[[float], None] | None = None) -> None:
    """Join the rendered pieces (each {path, width, height, fps, seconds, sound}) into `target` (.mp4)."""
    import video_encoder as encoders

    plan = join_plan(pieces)
    if plan["copy"]:
        listing = scratch / "pieces.txt"
        listing.write_text("".join(f"file '{Path(piece['path']).as_posix()}'\n" for piece in pieces), encoding="utf-8")
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "concat", "-safe", "0",
                   "-i", str(listing), "-c", "copy", "-movflags", "+faststart", "-f", "mp4", target]
    else:
        _, video_args = encoders.video_args(encoder, ffmpeg, 18, "veryfast")
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin"]
        for piece in pieces:
            command += ["-i", str(piece["path"])]
        command += ["-filter_complex", join_filter(pieces, plan), "-map", "[v]"]
        if plan["sound"]:
            command += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
        command += ["-r", f"{plan['fps']:g}", *video_args, "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", target]
    command[1:1] = ["-progress", "pipe:1", "-nostats"]
    errors = scratch / "join.log"
    with errors.open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log,
                                   creationflags=_flags())
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                key, _, value = line.decode("ascii", "replace").strip().partition("=")
                if key == "out_time_us" and value.isdigit() and progress is not None and plan["seconds"] > 0:
                    progress(min(1.0, int(value) / 1e6 / plan["seconds"]))
        except BaseException:
            process.kill()
            process.wait()
            raise
        code = process.wait()
    if code != 0:
        message = errors.read_text(errors="replace")[-500:]
        if encoder != encoders.SOFTWARE and not plan["copy"]:
            raise encoders.HardwareEncodeError(message)
        raise ValueError(f"Could not join the clips: {message}")


JOIN_SHARE = 0.1  # of a sequence's progress bar: the join, after every clip is rendered


def run_sequence(ffmpeg: str, sessions: list[dict[str, Any]], folder: Path, name: str, save: Callable[..., Path],
                 register: Callable[[Path], str], cancel: threading.Event, progress: Callable[[int, int], None],
                 encoder_setting: str = "auto") -> dict[str, Any]:
    """Render each export session (a clip of the sequence, in order) and join them into one video in the
    user's folder. Removes the sessions' overlays and every piece afterwards, also when cancelled."""
    import video_encoder as encoders
    total = sum(session["frames"] for session in sessions)
    if total > MAX_OUTPUT_FRAMES:
        raise ValueError("Exports can be up to 20 minutes long.")
    scale = 1000
    try:
        with tempfile.TemporaryDirectory(prefix="vizorplay-sequence-") as scratch_name:
            scratch = Path(scratch_name)
            encoder = encoders.resolve(encoder_setting, ffmpeg)
            pieces, done = [], 0
            for index, session in enumerate(sessions):
                schedule = overlay_schedule(session["folder"])
                target = str(scratch / f"piece-{index:03d}.mp4")
                record = session["record"]

                def report(n: int, count: int, base: int = done) -> None:
                    progress(int((base + n) / total * (1 - JOIN_SHARE) * scale), scale)

                try:
                    render(ffmpeg, session["video"], record, session["freezes"], session["frames"],
                           schedule, target, encoder, cancel, report, session.get("parts"))
                except encoders.HardwareEncodeError:
                    encoder = encoders.SOFTWARE
                    render(ffmpeg, session["video"], record, session["freezes"], session["frames"],
                           schedule, target, encoder, cancel, report, session.get("parts"))
                shutil.rmtree(session["folder"], ignore_errors=True)
                pieces.append({"path": target, "width": record["width"], "height": record["height"],
                               "fps": record["fps"], "seconds": session["frames"] / record["fps"],
                               "sound": has_audio(ffmpeg, Path(target))})
                done += session["frames"]

            def joined(share: float) -> None:
                progress(int(((1 - JOIN_SHARE) + share * JOIN_SHARE) * scale), scale)

            def write(temporary: str) -> None:
                try:
                    join(ffmpeg, pieces, temporary, encoder, scratch, cancel, joined)
                except encoders.HardwareEncodeError:
                    join(ffmpeg, pieces, temporary, encoders.SOFTWARE, scratch, cancel, joined)

            saved = save(folder, name, ".mp4", write, fallback="VizorPlay annotated sequence")
        return {"saved": {"name": saved.name, "folder": str(saved.parent), "id": register(saved)},
                "frames": total, "clips": len(sessions), "encoder": encoders.label(encoder)}
    finally:
        for session in sessions:
            shutil.rmtree(session["folder"], ignore_errors=True)


def run_export(ffmpeg: str, session: dict[str, Any], folder: Path, name: str, save: Callable[..., Path],
               register: Callable[[Path], str], cancel: threading.Event, progress: Callable[[int, int], None],
               encoder_setting: str = "auto") -> dict[str, Any]:
    """Render a session into the user's folder; always removes the session's overlays afterwards.
    `save` is the server's atomic save_to_user_folder; `register` gives the saved file an id the page can
    use to open its folder (the page never sees or sends paths)."""
    import video_encoder as encoders
    try:
        schedule = overlay_schedule(session["folder"])
        encoder = encoders.resolve(encoder_setting, ffmpeg)

        def write(temporary: str) -> None:
            try:
                render(ffmpeg, session["video"], session["record"], session["freezes"], session["frames"],
                       schedule, temporary, encoder, cancel, progress, session.get("parts"))
            except encoders.HardwareEncodeError:
                render(ffmpeg, session["video"], session["record"], session["freezes"], session["frames"],
                       schedule, temporary, encoders.SOFTWARE, cancel, progress, session.get("parts"))

        saved = save(folder, name, ".mp4", write, fallback="VizorPlay annotated clip")
        return {"saved": {"name": saved.name, "folder": str(saved.parent), "id": register(saved)},
                "frames": session["frames"], "encoder": encoders.label(encoder)}
    finally:
        shutil.rmtree(session["folder"], ignore_errors=True)
