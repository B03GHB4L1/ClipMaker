"""Record a live stream into short segments, play behind the live edge, join at the end (L1).

FFmpeg writes 2-second fragmented-MP4 segments and a growing playlist per "part". A part
lasts as long as one connection: when the source drops, the recording keeps going with
a new part once the source is back, and the gap is noted. The page plays the segments
through Media Source Extensions while recording continues; a crash loses at most the
segment being written. Stop joins the parts into one MP4 without re-encoding.

Sources (each checked against what this copy of FFmpeg can read; a missing protocol is
reported, never skipped):
  - a stream address the user supplies: rtmp(s)://, srt://, rtsp(s)://, http(s)://
  - a push on this computer only (127.0.0.1): RTMP or SRT, for OBS or a phone app.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

SEGMENT_SECONDS = 2
URL_SCHEMES = {"rtmp", "rtmps", "srt", "rtsp", "rtsps", "http", "https"}
LISTEN_PORTS = {"rtmp": 1935, "srt": 9000}
LOW_DISK = 2 * 1024 ** 3      # warn below 2 GB free
STOP_DISK = 300 * 1024 ** 2   # stop below 300 MB free, before the disk fills
RETRY_SECONDS = 2
PART = re.compile(r"^part\d{2}$")
SEGMENT_FILE = re.compile(r"^(init\.mp4|seg_\d{5}\.m4s)$")
PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
META = "recording.json"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
_protocols: dict[str, set[str]] = {}


def protocols(ffmpeg: str) -> set[str]:
    """The input protocols this FFmpeg build can read (rtmp, srt, https, ...)."""
    if ffmpeg not in _protocols:
        try:
            text = subprocess.run([ffmpeg, "-hide_banner", "-protocols"], capture_output=True, text=True,
                                  timeout=20, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError):
            text = ""
        inputs = text.split("Input:", 1)[-1].split("Output:", 1)[0]
        _protocols[ffmpeg] = {line.strip() for line in inputs.splitlines() if line.strip()}
    return _protocols[ffmpeg]


def _needs(scheme: str) -> str:
    """The FFmpeg protocol a URL scheme reads through. RTSP is a demuxer over TCP or TLS."""
    return {"rtsp": "tcp", "rtsps": "tls"}.get(scheme, scheme)


def check_source(source: Any, available: set[str]) -> dict[str, Any]:
    """A source the recorder accepts, or ValueError with what to change."""
    if not isinstance(source, dict):
        raise ValueError("Choose a stream address, or receive a stream on this computer.")
    kind = source.get("kind")
    if kind == "url":
        url = str(source.get("url") or "").strip()
        if not url or len(url) > 2048 or any(ch.isspace() or ord(ch) < 32 for ch in url):
            raise ValueError("Paste the stream address on its own, with no spaces.")
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in URL_SCHEMES or not parts.hostname:
            raise ValueError("Use an rtmp://, srt://, rtsp:// or https:// stream address.")
        if _needs(scheme) not in available:
            raise ValueError(f"This copy of FFmpeg cannot read {scheme}:// streams.")
        return {"kind": "url", "url": url}
    if kind == "listen":
        protocol = str(source.get("protocol") or "")
        if protocol not in LISTEN_PORTS:
            raise ValueError("Receive the stream over RTMP or SRT.")
        if protocol not in available:
            raise ValueError(f"This copy of FFmpeg cannot receive {protocol.upper()}. Use RTMP instead.")
        try:
            port = int(source.get("port") or LISTEN_PORTS[protocol])
        except (TypeError, ValueError):
            raise ValueError("The port must be a number.") from None
        if not 1024 <= port <= 65535:
            raise ValueError("Use a port between 1024 and 65535.")
        return {"kind": "listen", "protocol": protocol, "port": port}
    raise ValueError("Choose a stream address, or receive a stream on this computer.")


def push_address(source: dict[str, Any]) -> str:
    """What to type into OBS or a phone app for a listening source ("" for an address)."""
    if source["kind"] != "listen":
        return ""
    if source["protocol"] == "rtmp":
        return f"rtmp://127.0.0.1:{source['port']}/live"
    return f"srt://127.0.0.1:{source['port']}"


def describe(source: dict[str, Any]) -> str:
    """The source without any stream key or password, for the page and the saved notes."""
    if source["kind"] == "listen":
        return f"{source['protocol'].upper()} on this computer, port {source['port']}"
    parts = urlsplit(source["url"])
    return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")


def input_args(source: dict[str, Any]) -> list[str]:
    wait = str(15_000_000)  # microseconds without data before a drop counts as one
    if source["kind"] == "listen":
        if source["protocol"] == "rtmp":
            return ["-listen", "1", "-i", f"rtmp://127.0.0.1:{source['port']}/live/vizorplay"]
        return ["-i", f"srt://127.0.0.1:{source['port']}?mode=listener"]
    url = source["url"]
    scheme = urlsplit(url).scheme.lower()
    if scheme.startswith("rtmp"):
        return ["-rw_timeout", wait, "-i", url]
    if scheme.startswith("rtsp"):
        return ["-rtsp_transport", "tcp", "-timeout", wait, "-i", url]
    if scheme.startswith("http"):
        return ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-rw_timeout", wait, "-i", url]
    return ["-i", url]


def output_args(transcode: bool) -> list[str]:
    """Segments in the part's own folder (FFmpeg runs there). H.264 is kept as it is;
    anything else is encoded to H.264 so the page can play it while it records."""
    video = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
              "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_SECONDS})"] if transcode else ["-c:v", "copy"])
    return ["-map", "0:v:0", "-map", "0:a:0?", *video, "-c:a", "aac", "-b:a", "128k",
            "-f", "hls", "-hls_time", str(SEGMENT_SECONDS), "-hls_list_size", "0", "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4", "-hls_segment_filename", "seg_%05d.m4s",
            "-hls_flags", "independent_segments+temp_file", "live.m3u8"]


# ---------------------------------------------------------------------------
# Segments on disk
# ---------------------------------------------------------------------------
def read_playlist(part: Path) -> list[tuple[str, float]]:
    """(file, seconds) for each finished segment of a part, in order."""
    try:
        lines = (part / "live.m3u8").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out, duration = [], None
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            try:
                duration = float(line[8:].split(",", 1)[0])
            except ValueError:
                duration = None
        elif line and not line.startswith("#") and duration is not None:
            if SEGMENT_FILE.match(line) and (part / line).is_file():
                out.append((line, duration))
            duration = None
    return out


def parts_of(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.is_dir() and PART.match(path.name))


def segments(folder: Path) -> list[dict[str, Any]]:
    """Every finished segment in recording order, placed end to end (gaps are not time)."""
    out, start = [], 0.0
    for part in parts_of(folder):
        for name, duration in read_playlist(part):
            out.append({"part": part.name, "file": name, "start": round(start, 6), "duration": duration})
            start += duration
    return out


def codecs(init: Path) -> str:
    """The MIME codecs string for a part's init segment, e.g. avc1.64001f,mp4a.40.2."""
    try:
        data = init.read_bytes()
    except OSError:
        return ""
    found = []
    at = data.find(b"avcC")
    if at >= 0 and len(data) > at + 8:
        found.append("avc1.%02x%02x%02x" % (data[at + 5], data[at + 6], data[at + 7]))
    if b"mp4a" in data:
        found.append("mp4a.40.2")
    return ",".join(found)


def read_meta(folder: Path) -> dict[str, Any]:
    try:
        meta = json.loads((folder / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def write_meta(folder: Path, meta: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f"{META}.tmp"
    temporary.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(temporary, folder / META)


def free_bytes(folder: Path) -> int:
    probe = folder if folder.exists() else folder.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# One recording
# ---------------------------------------------------------------------------
class Recording:
    """FFmpeg writing one part per connection, restarted after a drop until stop()."""

    def __init__(self, ffmpeg: str, folder: Path, source: dict[str, Any]) -> None:
        self.ffmpeg = ffmpeg
        self.folder = folder
        self.source = source
        # connecting, waiting, recording, reconnecting, stopped, failed
        self.state = "waiting" if source["kind"] == "listen" else "connecting"
        self.error = ""
        self.transcode = False
        self.video_codec = ""
        self.gaps: list[dict[str, float]] = []
        self.started = time.time()
        self._stop = threading.Event()
        self._process: subprocess.Popen | None = None
        self._connected = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="live-recording", daemon=True)

    # -- control ------------------------------------------------------------
    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._save_meta()
        self._thread.start()

    def stop(self, timeout: float = 15) -> None:
        """Ask FFmpeg to finish its segment and end the playlist; force it after a wait."""
        with self._lock:
            self._stop.set()
            process = self._process
        if process and process.poll() is None:
            if self._connected and process.stdin:
                try:
                    process.stdin.write(b"q")
                    process.stdin.flush()
                except OSError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.kill()  # still waiting for a push, or stuck: nothing more to save
        self._thread.join(timeout)

    @property
    def active(self) -> bool:
        return self._thread.is_alive()

    # -- status -------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        found = segments(self.folder)
        recorded = found[-1]["start"] + found[-1]["duration"] if found else 0.0
        free = free_bytes(self.folder)
        return {"state": self.state, "error": self.error, "recorded_seconds": round(recorded, 3),
                "segments": len(found), "gaps": list(self.gaps), "transcode": self.transcode,
                "video_codec": self.video_codec, "free_bytes": free, "low_disk": free < LOW_DISK,
                "source": describe(self.source), "push_address": push_address(self.source)}

    # -- the loop -----------------------------------------------------------
    def _save_meta(self) -> None:
        write_meta(self.folder, {"source": describe(self.source), "started": self.started,
                                 "gaps": self.gaps, "transcode": self.transcode})

    def _recorded(self) -> float:
        found = segments(self.folder)
        return found[-1]["start"] + found[-1]["duration"] if found else 0.0

    def _next_part(self) -> Path:
        existing = parts_of(self.folder)
        part = self.folder / f"part{len(existing) + 1:02d}"
        part.mkdir()
        return part

    def _run(self) -> None:
        listening = self.source["kind"] == "listen"
        try:
            while not self._stop.is_set():
                self.state = "waiting" if listening and not self.gaps and not self._recorded() else self.state
                part = self._next_part()
                outcome, last_lines = self._record_part(part)
                if outcome == "transcode" and not self._stop.is_set():
                    shutil.rmtree(part, ignore_errors=True)
                    self.transcode = True
                    self._save_meta()
                    continue
                if not read_playlist(part):
                    shutil.rmtree(part, ignore_errors=True)  # nothing came in: keep the parts numbered in order
                if self._stop.is_set() or self.state == "failed":
                    break
                recorded = self._recorded()
                if not recorded and not listening and not self.gaps:
                    self.state = "failed"
                    self.error = _explain(last_lines)
                    break
                if not recorded and listening and _bind_failed(last_lines):
                    self.state = "failed"
                    self.error = f"Port {self.source['port']} is in use by another program. Choose another port."
                    break
                if recorded and (not self.gaps or "length" in self.gaps[-1]):
                    self.gaps.append({"at": round(recorded, 3), "dropped": time.time()})
                    self._save_meta()
                self.state = "reconnecting"
                self._stop.wait(RETRY_SECONDS)
        except Exception as error:  # noqa: BLE001 - surface any failure to the page
            self.state = "failed"
            self.error = f"Recording stopped: {error}"
        finally:
            if self.gaps and "length" not in self.gaps[-1]:
                self.gaps.pop()  # a drop the recording never came back from is just the end
            if self.state != "failed":
                self.state = "stopped"
            self._save_meta()

    def _record_part(self, part: Path) -> tuple[str, list[str]]:
        command = [self.ffmpeg, "-hide_banner", "-nostats", "-loglevel", "info",
                   *input_args(self.source), *output_args(self.transcode)]
        with self._lock:  # stop() takes the same lock, so it either sees this FFmpeg or prevents it
            if self._stop.is_set():
                return "ended", []
            process = subprocess.Popen(command, cwd=part, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
            self._process = process
        self._connected = False
        last: list[str] = []
        in_input = False
        outcome = "ended"
        disk = threading.Thread(target=self._watch_disk, args=(process,), daemon=True)
        disk.start()
        assert process.stderr is not None
        for raw in process.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            last = (last + [line])[-12:]
            if line.startswith("Input #0"):
                in_input = True
                self._connected = True
                self.state = "recording"
                if self.gaps and "length" not in self.gaps[-1]:
                    self.gaps[-1] = {"at": self.gaps[-1]["at"],
                                     "length": round(time.time() - self.gaps[-1]["dropped"], 1)}
                    self._save_meta()
            elif line.startswith(("Output #0", "Stream mapping")):
                in_input = False
            elif in_input and not self.video_codec:
                match = re.search(r"Stream #0:\d+.*?: Video: (\w+)", line)
                if match:
                    self.video_codec = match.group(1)
                    if match.group(1) != "h264" and not self.transcode:
                        outcome = "transcode"
                        process.kill()
        process.wait()
        for pipe in (process.stdin, process.stderr):
            try:
                pipe.close()
            except OSError:
                pass  # already broken when FFmpeg was stopped
        with self._lock:
            self._process = None
        return outcome, last

    def _watch_disk(self, process: subprocess.Popen) -> None:
        while process.poll() is None:
            if free_bytes(self.folder) < STOP_DISK:
                self.error = "Recording stopped: less than 300 MB is left on the disk."
                self._stop.set()
                if process.stdin:
                    try:
                        process.stdin.write(b"q")
                        process.stdin.flush()
                    except OSError:
                        process.kill()
                return
            time.sleep(5)


def _explain(lines: list[str]) -> str:
    text = " ".join(lines).lower()
    if "connection refused" in text or "cannot open connection" in text:
        return "Could not connect: nothing is answering at that address."
    if "401" in text or "403" in text or "unauthorized" in text or "forbidden" in text:
        return "The stream refused the connection. Check the address and its key or password."
    if "404" in text or "not found" in text:
        return "No stream was found at that address."
    if "timed out" in text or "timeout" in text:
        return "The stream did not answer in time."
    detail = next((line.strip() for line in reversed(lines) if line.strip()), "")
    return f"Could not record that stream. FFmpeg said: {detail[-200:]}" if detail else "Could not record that stream."


def _bind_failed(lines: list[str]) -> bool:
    text = " ".join(lines).lower()
    return "address already in use" in text or "bind" in text and "fail" in text


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------
def join(ffmpeg: str, folder: Path, output: Path, run: Callable[..., Any] = subprocess.run) -> float:
    """Join every part into one MP4 without re-encoding; returns its length in seconds.
    Written next to the target and moved into place, so a failed join leaves no file."""
    parts = [part for part in parts_of(folder) if read_playlist(part)]
    if not parts:
        raise ValueError("Nothing was recorded.")
    output.parent.mkdir(parents=True, exist_ok=True)
    pieces = []
    for part in parts:
        # A closed playlist of the finished segments: a part cut off by a drop or crash
        # has no end tag, and FFmpeg would otherwise wait for it to grow.
        lines = ["#EXTM3U", "#EXT-X-VERSION:7", f"#EXT-X-TARGETDURATION:{SEGMENT_SECONDS + 1}",
                 "#EXT-X-MEDIA-SEQUENCE:0", '#EXT-X-MAP:URI="init.mp4"']
        for name, duration in read_playlist(part):
            lines += [f"#EXTINF:{duration:.6f},", name]
        (part / "join.m3u8").write_text("\n".join(lines + ["#EXT-X-ENDLIST", ""]), encoding="utf-8")
        piece = folder / f"{part.name}.mp4"
        _ffmpeg(run, [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-allowed_extensions", "ALL",
                      "-i", "join.m3u8", "-c", "copy", str(piece)], cwd=part)
        pieces.append(piece)
    temporary = output.with_name(output.stem + ".joining.mp4")
    if len(pieces) == 1:
        _ffmpeg(run, [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(pieces[0]), "-c", "copy",
                      "-movflags", "+faststart", str(temporary)])
    else:
        listing = folder / "join.txt"
        listing.write_text("".join(f"file '{piece.name}'\n" for piece in pieces), encoding="utf-8")
        _ffmpeg(run, [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                      "-i", listing.name, "-c", "copy", "-movflags", "+faststart", str(temporary)], cwd=folder)
    length = media_seconds(ffmpeg, temporary)
    if length <= 0:
        temporary.unlink(missing_ok=True)
        raise ValueError("The joined recording could not be read back.")
    os.replace(temporary, output)
    for piece in pieces:
        piece.unlink(missing_ok=True)
    return length


CLIP_LIMIT = 300  # seconds: a clip, not a half


def cut(ffmpeg: str, folder: Path, start: float, end: float, output: str,
        run: Callable[..., Any] = subprocess.run) -> tuple[float, float]:
    """Cut [start, end) of a recording still in segments into an MP4 at ``output`` (L2: clips
    during the match). Re-encoded so it starts on the exact frame; a clip stays inside one
    part, so one that runs into a break in the stream ends where the break starts.
    Returns the (start, end) actually cut."""
    if not (isinstance(start, (int, float)) and isinstance(end, (int, float))) or start != start or end != end:
        raise ValueError("A clip needs a start and an end in seconds.")
    start = max(0.0, float(start))
    if end - start < 0.2:
        raise ValueError("The clip is too short.")
    if end - start > CLIP_LIMIT:
        raise ValueError("Clips during a recording can be up to 5 minutes long.")
    found = segments(folder)
    recorded = found[-1]["start"] + found[-1]["duration"] if found else 0.0
    if start >= recorded:
        raise ValueError("That moment has not been recorded yet.")
    if end > recorded + 0.05:
        raise ValueError(f"The end of this clip is recorded in {max(1, round(end - recorded))} s. Try again then.")
    first = next(item for item in found if item["start"] + item["duration"] > start)
    chosen = [item for item in found if item["part"] == first["part"]
              and item["start"] < end and item["start"] + item["duration"] > start]
    end = min(end, chosen[-1]["start"] + chosen[-1]["duration"])
    part = folder / first["part"]
    playlist = part / f"clip-{os.getpid()}-{threading.get_ident()}.m3u8"
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", f"#EXT-X-TARGETDURATION:{SEGMENT_SECONDS + 1}",
             "#EXT-X-MEDIA-SEQUENCE:0", '#EXT-X-MAP:URI="init.mp4"']
    for item in chosen:
        lines += [f"#EXTINF:{item['duration']:.6f},", item["file"]]
    playlist.write_text("\n".join(lines + ["#EXT-X-ENDLIST", ""]), encoding="utf-8")
    try:
        _ffmpeg(run, [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-allowed_extensions", "ALL",
                      "-i", playlist.name, "-ss", f"{start - chosen[0]['start']:.3f}", "-t", f"{end - start:.3f}",
                      "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                      "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                      "-f", "mp4", str(output)], cwd=part)
    finally:
        playlist.unlink(missing_ok=True)
    return round(start, 3), round(end, 3)


def _ffmpeg(run: Callable[..., Any], command: list[str], cwd: Path | None = None) -> None:
    result = run(command, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                 timeout=3600, creationflags=_NO_WINDOW)
    if result.returncode != 0:
        raise ValueError(f"Joining the recording failed: {(result.stderr or '').strip()[-300:]}")


def media_seconds(ffmpeg: str, path: Path) -> float:
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=60, creationflags=_NO_WINDOW)
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", result.stderr or "")
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


# ---------------------------------------------------------------------------
# The engine's recordings: one at a time, one folder per project
# ---------------------------------------------------------------------------
class LiveRecordings:
    """Start, watch, stop and join recordings. A folder with parts but no running
    recording (the app closed or crashed) is "interrupted" and can still be joined."""

    def __init__(self, root: Path, find_ffmpeg: Callable[[], str], output_dir: Callable[[], Path],
                 on_joined: Callable[[str, Path, list[dict[str, float]]], None]) -> None:
        self.root = root
        self.find_ffmpeg = find_ffmpeg
        self.output_dir = output_dir
        self.on_joined = on_joined
        self.recordings: dict[str, Recording] = {}
        self.joining: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        # Asking FFmpeg for its protocols takes a few seconds the first time: do it now, not when the page asks.
        threading.Thread(target=self._warm, name="live-protocols", daemon=True).start()

    def _warm(self) -> None:
        try:
            protocols(self.find_ffmpeg())
        except Exception:  # noqa: BLE001 - the page asks again and reports the error
            pass

    def folder(self, project_id: str) -> Path:
        if not PROJECT_ID.match(project_id):
            raise ValueError("Project not found")
        return self.root / project_id

    def capabilities(self) -> dict[str, Any]:
        available = protocols(self.find_ffmpeg())
        return {"url": sorted(scheme for scheme in URL_SCHEMES if _needs(scheme) in available),
                "listen": [name for name in LISTEN_PORTS if name in available], "ports": LISTEN_PORTS,
                "segment_seconds": SEGMENT_SECONDS}

    def start(self, project_id: str, source: Any) -> dict[str, Any]:
        ffmpeg = self.find_ffmpeg()
        checked = check_source(source, protocols(ffmpeg))
        folder = self.folder(project_id)
        with self._lock:
            busy = next((key for key, item in self.recordings.items() if item.active), None)
            if busy:
                raise ValueError("Another project is recording. Stop it first." if busy != project_id
                                 else "This project is already recording.")
            if project_id in self.joining and self.joining[project_id]["state"] == "joining":
                raise ValueError("The last recording is still being saved.")
            if segments(folder):
                raise ValueError("This project has an unfinished recording. Save it first.")
            shutil.rmtree(folder, ignore_errors=True)  # what is left of a recording that never received anything
            if free_bytes(folder) < STOP_DISK:
                raise ValueError("Less than 300 MB is free on the disk. Free some space first.")
            recording = Recording(ffmpeg, folder, checked)
            self.recordings[project_id] = recording
            self.joining.pop(project_id, None)
            recording.start()
        return self.status(project_id)

    def stop(self, project_id: str, project_name: str) -> dict[str, Any]:
        """Stop recording (if it runs) and join the parts in the background."""
        folder = self.folder(project_id)
        with self._lock:
            recording = self.recordings.get(project_id)
            if project_id in self.joining and self.joining[project_id]["state"] == "joining":
                return self.status(project_id)
            if not segments(folder) and not (recording and recording.active):
                raise ValueError("There is no recording to save.")
            self.joining[project_id] = {"state": "joining", "error": ""}
        threading.Thread(target=self._finish, args=(project_id, recording, folder, project_name),
                         name="live-join", daemon=True).start()
        return self.status(project_id)

    def _finish(self, project_id: str, recording: Recording | None, folder: Path, project_name: str) -> None:
        try:
            if recording:
                recording.stop()
            gaps = [gap for gap in read_meta(folder).get("gaps", []) if isinstance(gap, dict) and "length" in gap]
            if not segments(folder):
                # Stopped before any stream arrived: nothing to save, so back to the start, not "saving failed".
                shutil.rmtree(folder, ignore_errors=True)
                self.joining[project_id] = {"state": "failed", "error": (recording.error if recording and recording.error
                                                                         else "Stopped before any stream arrived. Nothing was recorded.")}
                return
            output = self._output_path(project_name)
            join(self.find_ffmpeg(), folder, output)
            self.on_joined(project_id, output, gaps)
            shutil.rmtree(folder, ignore_errors=True)  # the MP4 now holds everything the segments did
            self.joining[project_id] = {"state": "done", "error": "", "video_path": str(output), "video_name": output.name}
        except Exception as error:  # noqa: BLE001
            self.joining[project_id] = {"state": "join_failed", "error": str(error)}
        finally:
            with self._lock:
                self.recordings.pop(project_id, None)

    def _output_path(self, project_name: str) -> Path:
        safe = re.sub(r"\s+", " ", re.sub(r"[^\w\- ]+", "", project_name)).strip()[:60] or "Live recording"
        base = f"{safe} live {datetime.now().strftime('%Y-%m-%d %H%M')}"
        folder = self.output_dir()
        candidate = folder / f"{base}.mp4"
        number = 2
        while candidate.exists():
            candidate = folder / f"{base} ({number}).mp4"
            number += 1
        return candidate

    def status(self, project_id: str, after: int = 0) -> dict[str, Any]:
        folder = self.folder(project_id)
        recording = self.recordings.get(project_id)
        if recording:
            status = recording.status()
        else:
            meta = read_meta(folder)
            found = segments(folder)
            status = {"state": "interrupted" if found else "idle", "error": "",
                      "recorded_seconds": round(found[-1]["start"] + found[-1]["duration"], 3) if found else 0.0,
                      "segments": len(found), "gaps": meta.get("gaps", []), "transcode": bool(meta.get("transcode")),
                      "free_bytes": free_bytes(folder), "source": meta.get("source", ""), "push_address": ""}
            status["low_disk"] = status["free_bytes"] < LOW_DISK
        joined = self.joining.get(project_id)
        if joined:
            status.update({key: value for key, value in joined.items() if key != "state"})
            status["state"] = joined["state"] if joined["state"] != "join_failed" else "join_failed"
        found = segments(folder)
        status["new_segments"] = [{**item, "i": index} for index, item in enumerate(found)][max(0, after):]
        inits = {}
        for part in {item["part"] for item in status["new_segments"]}:
            inits[part] = codecs(folder / part / "init.mp4")
        status["codecs"] = inits
        return status

    def clip(self, project_id: str, start: Any, end: Any, output: str) -> tuple[float, float]:
        """A clip of a recording still in progress (or not yet saved)."""
        folder = self.folder(project_id)
        if self.joining.get(project_id, {}).get("state") == "joining":
            raise ValueError("The recording is being saved. Cut clips from it on Filter once it is.")
        if not segments(folder):
            raise ValueError("Nothing has been recorded yet.")
        return cut(self.find_ffmpeg(), folder, start, end, output)

    def close(self) -> None:
        """Stop every recording when the engine shuts down; the segments stay to be joined."""
        for recording in list(self.recordings.values()):
            recording.stop(timeout=5)
