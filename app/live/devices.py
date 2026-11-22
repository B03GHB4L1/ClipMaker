"""Capture devices and screen capture for live recording (L3), one adapter per system.

  - Windows: DirectShow for cameras, capture cards and microphones; GDI for the screen.
  - macOS:   AVFoundation for all three (screens are listed as "Capture screen N").
  - Linux:   Video4Linux2 for cameras; PulseAudio or ALSA for the default microphone;
             X11 for the screen (a Wayland session cannot be recorded this way).

The page only ever sees device names from a fresh listing. A recording names the device
it wants; the name is looked up again when it starts and turned into FFmpeg's own id
there, so nothing the page sends reaches FFmpeg unless it is in the listing.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

FRAME_RATE = 30
MAX_WIDTH = 1920  # screens are scaled down to this, keeping the shape
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_formats: dict[str, set[str]] = {}


def system() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _run(command: list[str], timeout: float = 20) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "") + (result.stderr or "")


def input_formats(ffmpeg: str) -> set[str]:
    """The capture inputs this FFmpeg build has (dshow, gdigrab, avfoundation, v4l2, ...)."""
    if ffmpeg not in _formats:
        found = set()
        for line in _run([ffmpeg, "-hide_banner", "-devices"]).splitlines():
            match = re.match(r"\s*D\S?\s+([\w,]+)\s", line)
            if match:
                found.update(match.group(1).split(","))
        _formats[ffmpeg] = found
    return _formats[ffmpeg]


def _unique(names: list[str]) -> list[str]:
    """Two identical cameras get "(2)" after the second name, so each name picks one device."""
    out, seen = [], {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return out


# ---------------------------------------------------------------------------
# Listing: {"video": {name: id}, "audio": {name: id}, "screens": {name: id}}
# ---------------------------------------------------------------------------
def parse_dshow(text: str) -> dict[str, dict[str, str]]:
    """FFmpeg's DirectShow listing. A name containing ":" cannot be passed as it is, so
    the device's alternative name is used for it instead."""
    found: dict[str, list[list[str]]] = {"video": [], "audio": []}
    last: list[list[str]] = []  # the entries of the device just read, to take its alternative name
    for line in text.splitlines():
        device = re.search(r'\]\s+"(.+)"\s+\(([\w, ]+)\)\s*$', line)
        if device:
            kinds = {kind.strip() for kind in device.group(2).split(",")}
            last = []
            for kind in ("video", "audio"):  # "(none)" is a device that is not ready, such as an idle virtual camera
                if kind in kinds:
                    entry = [device.group(1), device.group(1)]
                    found[kind].append(entry)
                    last.append(entry)
            continue
        alternative = re.search(r'\]\s+Alternative name\s+"(.+)"\s*$', line)
        if alternative:
            for entry in last:
                if ":" in entry[0]:
                    entry[1] = alternative.group(1)
            last = []
    return {kind: dict(zip(_unique([name for name, _ in items]), [native for _, native in items]))
            for kind, items in found.items()}


def parse_avfoundation(text: str) -> dict[str, dict[str, str]]:
    """AVFoundation lists cameras and screens together under video, by index."""
    video: list[tuple[str, str]] = []
    audio: list[tuple[str, str]] = []
    into = None
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            into = video
        elif "AVFoundation audio devices" in line:
            into = audio
        else:
            match = re.search(r"\]\s+\[(\d+)\]\s+(.+?)\s*$", line)
            if match and into is not None:
                into.append((match.group(2), match.group(1)))
    cameras = [(name, index) for name, index in video if not name.startswith("Capture screen")]
    screens = [(name, index) for name, index in video if name.startswith("Capture screen")]
    pack = lambda items: dict(zip(_unique([name for name, _ in items]), [index for _, index in items]))  # noqa: E731
    return {"video": pack(cameras), "audio": pack(audio), "screens": pack(screens)}


def v4l2_cameras(root: Path = Path("/sys/class/video4linux")) -> dict[str, str]:
    """Each camera's first capture node (a camera has extra nodes for metadata)."""
    items = []
    try:
        nodes = sorted(root.iterdir(), key=lambda path: int(re.sub(r"\D", "", path.name) or 0))
    except OSError:
        return {}
    for node in nodes:
        if not re.fullmatch(r"video\d+", node.name):
            continue
        try:
            if (node / "index").read_text().strip() not in ("", "0"):
                continue
        except OSError:
            pass
        try:
            name = (node / "name").read_text().strip() or node.name
        except OSError:
            name = node.name
        items.append((name, f"/dev/{node.name}"))
    return dict(zip(_unique([name for name, _ in items]), [path for _, path in items]))


def list_devices(ffmpeg: str) -> dict[str, Any]:
    """What can be recorded on this computer, and why anything cannot."""
    formats = input_formats(ffmpeg)
    where = system()
    listing: dict[str, Any] = {"system": where, "video": {}, "audio": {}, "screens": {},
                               "device_problem": "", "screen_problem": ""}
    if where == "windows":
        if "dshow" in formats:
            found = parse_dshow(_run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]))
            listing.update(video=found["video"], audio=found["audio"])
        else:
            listing["device_problem"] = "This copy of FFmpeg cannot read cameras (no DirectShow)."
        if "gdigrab" in formats:
            listing["screens"] = {"Whole desktop": "desktop"}
        else:
            listing["screen_problem"] = "This copy of FFmpeg cannot record the screen (no GDI grabber)."
    elif where == "macos":
        if "avfoundation" in formats:
            found = parse_avfoundation(_run([ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]))
            listing.update(video=found["video"], audio=found["audio"], screens=found["screens"])
            if not found["screens"]:
                listing["screen_problem"] = "No screen was listed. Allow VizorPlay under Screen Recording in System Settings."
        else:
            listing["device_problem"] = listing["screen_problem"] = "This copy of FFmpeg cannot read cameras or the screen (no AVFoundation)."
    else:
        if "v4l2" in formats or "video4linux2" in formats:
            listing["video"] = v4l2_cameras()
        else:
            listing["device_problem"] = "This copy of FFmpeg cannot read cameras (no Video4Linux2)."
        if "pulse" in formats:
            listing["audio"] = {"Default microphone": "pulse:default"}
        elif "alsa" in formats:
            listing["audio"] = {"Default microphone": "alsa:default"}
        display = os.environ.get("DISPLAY", "")
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or (os.environ.get("WAYLAND_DISPLAY") and not display):
            listing["screen_problem"] = "Recording the screen of a Wayland session is not supported. Log in with an X11 session to use it."
        elif "x11grab" not in formats:
            listing["screen_problem"] = "This copy of FFmpeg cannot record the screen (no X11 grabber)."
        elif not display:
            listing["screen_problem"] = "No X11 display was found to record."
        else:
            listing["screens"] = {"Whole screen": display}
    if not listing["device_problem"] and not listing["video"]:
        listing["device_problem"] = "No camera or capture card was found. Plug one in and look again."
    return listing


MAX_PIXELS = 1920 * 1080  # a 4K capture card is recorded at 1080p: encoding 4K live is too slow


def parse_dshow_modes(text: str) -> list[dict[str, Any]]:
    """A DirectShow camera's modes: codec or pixel format, size and frame-rate range."""
    modes = []
    for line in text.splitlines():
        match = re.search(r"(vcodec|pixel_format)=(\w+)\s+min s=(\d+)x(\d+) fps=([\d.]+)\s+max s=(\d+)x(\d+) fps=([\d.]+)", line)
        if match:
            kind, value, _, _, low, width, height, high = match.groups()
            modes.append({"option": "vcodec" if kind == "vcodec" else "pixel_format", "value": value,
                          "width": int(width), "height": int(height), "min_fps": float(low), "max_fps": float(high)})
    return modes


def best_mode(modes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The largest mode (up to 1080p) that keeps 25 frames a second or more; compressed
    before raw at the same size, since raw HD over USB often cannot keep up. None keeps
    the device's own default."""
    usable = [mode for mode in modes if mode["max_fps"] >= 25 and mode["width"] * mode["height"] <= MAX_PIXELS]
    if not usable:
        return None
    best = max(usable, key=lambda mode: (mode["width"] * mode["height"], mode["option"] == "vcodec", -abs(mode["max_fps"] - FRAME_RATE)))
    rate = FRAME_RATE if best["min_fps"] <= FRAME_RATE <= best["max_fps"] else best["max_fps"]
    return {**best, "fps": rate}


def dshow_mode(ffmpeg: str, video_id: str) -> dict[str, Any] | None:
    return best_mode(parse_dshow_modes(_run([ffmpeg, "-hide_banner", "-list_options", "true", "-f", "dshow",
                                             "-i", f"video={video_id}"])))


def public(listing: dict[str, Any]) -> dict[str, Any]:
    """The listing as the page sees it: names only."""
    return {"system": listing["system"], "video": list(listing["video"]), "audio": list(listing["audio"]),
            "screens": list(listing["screens"]), "device_problem": listing["device_problem"],
            "screen_problem": listing["screen_problem"]}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def check(source: dict[str, Any], listing: dict[str, Any], ffmpeg: str = "") -> dict[str, Any]:
    """A device or screen source with FFmpeg's ids filled in from a fresh listing, and on
    Windows the camera's best mode."""
    kind = source.get("kind")
    audio = str(source.get("audio") or "")
    if audio and audio not in listing["audio"]:
        raise ValueError(f'The microphone "{audio[:80]}" is no longer connected. Look for devices again.')
    if kind == "device":
        if listing["device_problem"] and not listing["video"]:
            raise ValueError(listing["device_problem"])
        video = str(source.get("video") or "")
        if video not in listing["video"]:
            raise ValueError("Choose a camera or capture card from the list." if not video
                             else f'"{video[:80]}" is no longer connected. Look for devices again.')
        checked = {"kind": "device", "video": video, "audio": audio, "system": listing["system"],
                   "video_id": listing["video"][video], "audio_id": listing["audio"].get(audio, "")}
        if listing["system"] == "windows" and ffmpeg:
            mode = dshow_mode(ffmpeg, checked["video_id"])
            if mode:
                checked["mode"] = {key: mode[key] for key in ("option", "value", "width", "height", "fps")}
        return checked
    screen = str(source.get("screen") or "")
    if listing["screen_problem"] and not listing["screens"]:
        raise ValueError(listing["screen_problem"])
    if screen not in listing["screens"]:
        raise ValueError("Choose a screen to record.")
    return {"kind": "screen", "screen": screen, "audio": audio, "system": listing["system"],
            "video_id": listing["screens"][screen], "audio_id": listing["audio"].get(audio, "")}


def describe(source: dict[str, Any]) -> str:
    what = "Screen" if source["kind"] == "screen" else "Camera"
    name = source["screen"] if source["kind"] == "screen" else source["video"]
    return f"{what}: {name}" + (f", sound from {source['audio']}" if source["audio"] else ", no sound")


def _audio_input(source: dict[str, Any]) -> list[str]:
    """A separate input for the microphone (Windows and Linux), or nothing."""
    audio = source["audio_id"]
    if not audio:
        return []
    if source["system"] == "windows":
        return ["-thread_queue_size", "1024", "-f", "dshow", "-audio_buffer_size", "50", "-i", f"audio={audio}"]
    backend, name = audio.split(":", 1)
    return ["-thread_queue_size", "1024", "-f", backend, "-i", name]


def input_args(source: dict[str, Any]) -> tuple[list[str], str]:
    """FFmpeg's input options, and where the sound comes from ("0:a:0?" or "1:a:0")."""
    where = source["system"]
    rate = str(FRAME_RATE)
    if where == "macos":
        audio = source["audio_id"] or "none"
        extra = ["-capture_cursor", "1"] if source["kind"] == "screen" else []
        return ["-thread_queue_size", "1024", "-f", "avfoundation", "-framerate", rate, *extra,
                "-i", f"{source['video_id']}:{audio}"], "0:a:0?"
    if source["kind"] == "device":
        if where == "windows":  # camera and microphone as one input keeps them in step
            audio = f":audio={source['audio_id']}" if source["audio_id"] else ""
            mode = source.get("mode")
            chosen = (["-" + mode["option"], mode["value"], "-video_size", f"{mode['width']}x{mode['height']}",
                       "-framerate", f"{mode['fps']:g}"] if mode else [])
            return ["-thread_queue_size", "1024", "-f", "dshow", "-rtbufsize", "256M", "-audio_buffer_size", "50",
                    *chosen, "-i", f"video={source['video_id']}{audio}"], "0:a:0?"
        else:
            video = ["-thread_queue_size", "1024", "-f", "v4l2", "-i", source["video_id"]]
    elif where == "windows":
        video = ["-thread_queue_size", "1024", "-f", "gdigrab", "-framerate", rate, "-draw_mouse", "1", "-i", "desktop"]
    else:
        video = ["-thread_queue_size", "1024", "-f", "x11grab", "-framerate", rate, "-draw_mouse", "1",
                 "-i", source["video_id"]]
    sound = _audio_input(source)
    return [*video, *sound], ("1:a:0" if sound else "0:a:0?")


def video_filter(source: dict[str, Any]) -> list[str]:
    """Even sizes for H.264, and screens no wider than 1920 pixels."""
    width = f"trunc(min({MAX_WIDTH}\\,iw)/2)*2" if source["kind"] == "screen" else "trunc(iw/2)*2"
    return ["-vf", f"scale={width}:-2,format=yuv420p"]
