"""Choose the H.264 encoder for clips: the graphics card when it works, x264 otherwise.

docs/EXPORT_SPEED_PLAN.md. NVIDIA NVENC measured 3x faster than x264
`veryfast` on a real 1080p50 match with equal or better quality (VMAF 97.8 vs
96.1) when its constant-quality level is the x264 CRF plus 7. Other hardware
encoders (Quick Sync, AMF, VideoToolbox) are not used until their quality
mapping has been measured on real hardware.

Detection runs a tiny test encode once per FFmpeg binary and is cached. A
working hardware encoder can still fail on a particular source (for example
10-bit or 4:2:2 video); callers fall back to x264 and say so in their log.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

SOFTWARE = "libx264"
NVENC = "h264_nvenc"
SETTINGS = ("auto", "software")
CQ_OFFSET = 7  # NVENC CQ = x264 CRF + 7 (measured; see the plan)
RETRY_AFTER = 300  # seconds before a failed probe is tried again (the card may have been busy)
_cache: dict[str, dict] = {}
_lock = threading.Lock()


class HardwareEncodeError(RuntimeError):
    """A hardware encode failed; the caller should redo the work with x264."""


def find_ffmpeg() -> str:
    """The FFmpeg every cut uses: the bundled, tested build first, then PATH.

    A system FFmpeg can be old or built without libx264, so it is only a
    fallback when the bundled one is missing."""
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and os.path.isfile(bundled):
            return bundled
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise ValueError("FFmpeg not found. Reinstall VizorPlay, or install FFmpeg.")


def _quiet(command: list[str], timeout: float = 30) -> bool:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                              creationflags=flags).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def probe(ffmpeg: str) -> dict:
    """{"encoder": NVENC or None, "cuda_decode": bool}, tested once per binary.

    A working encoder is remembered for the session. A failure is retried after
    RETRY_AFTER seconds, because other software (a game, a streaming app) can
    hold every encoder session for a while."""
    key = os.path.abspath(ffmpeg)
    with _lock:
        cached = _cache.get(key)
        if cached and (cached["encoder"] or time.monotonic() - cached["checked"] < RETRY_AFTER):
            return cached
        result = {"encoder": None, "cuda_decode": False, "checked": time.monotonic()}
        base = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
        with tempfile.TemporaryDirectory(prefix="vizorplay-encoder-") as name:
            sample = Path(name) / "sample.mp4"
            made = _quiet(base + ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=0.4",
                                  "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(sample)])
            if made and _quiet(base + ["-i", str(sample), "-c:v", NVENC, "-preset", "p5", "-f", "null", "-"]):
                result["encoder"] = NVENC
                result["cuda_decode"] = _quiet(base + ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
                                                       "-i", str(sample), "-c:v", NVENC, "-preset", "p5",
                                                       "-f", "null", "-"])
        _cache[key] = result
        return result


def resolve(setting: str, ffmpeg: str) -> str:
    """The encoder to use for a job: NVENC or libx264."""
    forced = (os.environ.get("VIZORPLAY_VIDEO_ENCODER") or "").strip().lower()
    if forced == "software" or setting == "software":
        return SOFTWARE
    return probe(ffmpeg)["encoder"] or SOFTWARE


def video_args(encoder: str, ffmpeg: str, crf: int, preset: str) -> tuple[list[str], list[str]]:
    """(arguments before -i, video output arguments) for one cut."""
    crf = max(16, min(30, int(crf)))
    if encoder == NVENC:
        before = ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if probe(ffmpeg)["cuda_decode"] else []
        return before, ["-c:v", NVENC, "-preset", "p5", "-rc", "vbr", "-cq", str(crf + CQ_OFFSET), "-b:v", "0",
                        "-spatial-aq", "1"]
    return [], ["-c:v", SOFTWARE, "-preset", preset, "-crf", str(crf), "-threads", "0"]


def label(encoder: str) -> str:
    return "graphics card (NVIDIA NVENC)" if encoder == NVENC else "software (x264)"


def workers(encoder: str) -> int:
    """Clips cut at once. x264 already uses every core (more workers measured
    no faster for 13 s clips and slower for long ones); NVENC gains a little
    from two, and consumer cards limit concurrent sessions."""
    return 2 if encoder == NVENC else 1
