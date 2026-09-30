"""Serve the shared ClipMaker frontend and its local application API."""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
UI_DIR = ROOT / "ui"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


class MatchStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "matches.json"
        self._lock = threading.Lock()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            return value if isinstance(value, list) else []

    def upsert(self, match: dict[str, Any]) -> dict[str, Any]:
        clean = {
            "id": str(match.get("id") or "").strip(),
            "home_team": str(match.get("home_team") or "").strip(),
            "away_team": str(match.get("away_team") or "").strip(),
            "source_url": str(match.get("source_url") or "").strip(),
            "source": str(match.get("source") or "").strip(),
            "event_count": int(match.get("event_count") or 0),
            "video_name": str(match.get("video_name") or "").strip(),
            "markers": match.get("markers") if isinstance(match.get("markers"), dict) else {},
            "status": str(match.get("status") or "in_progress"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not clean["id"]:
            parts = [clean["home_team"], clean["away_team"]]
            clean["id"] = "-vs-".join(part.lower().replace(" ", "-") for part in parts if part)
        if not clean["id"]:
            raise ValueError("A match id or team names are required")

        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            matches = []
            if self.path.exists():
                try:
                    loaded = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        matches = loaded
                except (OSError, json.JSONDecodeError):
                    matches = []
            matches = [item for item in matches if item.get("id") != clean["id"]]
            matches.insert(0, clean)
            fd, temporary_name = tempfile.mkstemp(dir=self.data_dir, prefix="matches-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as temporary:
                    json.dump(matches, temporary, indent=2)
                os.replace(temporary_name, self.path)
            finally:
                if os.path.exists(temporary_name):
                    os.unlink(temporary_name)
        return clean


def detect_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "scoresway.com" in host:
        return "scoresway"
    if "whoscored.com" in host:
        return "whoscored"
    raise ValueError("Paste a Scoresway or WhoScored match URL")


def json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and (value != value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def scrape_match(url: str, output_dir: Path) -> dict[str, Any]:
    from scoresway_scraper import scrape_scoresway
    from whoscored_scraper import save_scraped_match_csv, scrape_whoscored

    source = detect_source(url)
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    scraper = scrape_scoresway if source == "scoresway" else scrape_whoscored
    scraper(url, messages, str(APP_DIR))

    result = None
    errors = []
    while not messages.empty():
        message = messages.get_nowait()
        if message.get("type") == "data":
            result = message
        elif message.get("type") == "error":
            errors.append(str(message.get("msg") or "Unknown scraper error"))
    if result is None:
        raise RuntimeError(errors[-1] if errors else "The scraper returned no match data")

    frame = result["df"]
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = save_scraped_match_csv(
        frame,
        result.get("home_team", ""),
        result.get("away_team", ""),
        str(output_dir),
        source=result.get("source", source),
    )
    preferred_columns = ["minute", "second", "playerName", "type", "team", "period", "xT"]
    columns = [column for column in preferred_columns if column in frame.columns]
    preview = [
        {key: json_value(value) for key, value in row.items()}
        for row in frame[columns].head(200).to_dict(orient="records")
    ]
    return {
        "home_team": result.get("home_team", ""),
        "away_team": result.get("away_team", ""),
        "source": result.get("source", source),
        "source_url": url,
        "event_count": len(frame),
        "csv_path": csv_path,
        "events": preview,
    }


class ClipMakerHandler(SimpleHTTPRequestHandler):
    server_version = "ClipMaker/1.3"

    @property
    def store(self) -> MatchStore:
        return self.server.match_store  # type: ignore[attr-defined]

    @property
    def match_data_dir(self) -> Path:
        return self.server.match_data_dir  # type: ignore[attr-defined]

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        relative = parsed.lstrip("/") or "index.html"
        candidate = (UI_DIR / relative).resolve()
        if UI_DIR.resolve() not in candidate.parents and candidate != UI_DIR.resolve():
            return str(UI_DIR / "index.html")
        return str(candidate)

    def send_json(self, status: HTTPStatus, payload: Any) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("A JSON request body is required")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("The request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self.send_json(HTTPStatus.OK, {"status": "ok", "version": "1.3.0"})
            return
        if path == "/api/matches":
            self.send_json(HTTPStatus.OK, {"matches": self.store.list()})
            return
        if path.startswith("/api/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown API endpoint"})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self.read_json()
            if path == "/api/matches":
                saved = self.store.upsert(body)
                self.send_json(HTTPStatus.OK, {"match": saved})
                return
            if path == "/api/scrape":
                url = str(body.get("url") or "").strip()
                scraped = scrape_match(url, self.match_data_dir)
                self.send_json(HTTPStatus.OK, {"match": scraped})
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown API endpoint"})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

    def log_message(self, message: str, *args: Any) -> None:
        print(f"[clipmaker] {self.address_string()} {message % args}")


def create_server(host: str, port: int, data_dir: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), ClipMakerHandler)
    server.match_store = MatchStore(data_dir)  # type: ignore[attr-defined]
    server.match_data_dir = data_dir / "match-data"  # type: ignore[attr-defined]
    return server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / ".clipmaker-data")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.data_dir.resolve())
    print(f"ClipMaker shared UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
