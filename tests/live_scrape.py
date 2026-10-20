"""Optional real-provider health check, separate from deterministic regression tests."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, request


def main():
    urls = {name: os.environ.get(name, "").strip() for name in ("SCORESWAY_URL", "WHOSCORED_URL")}
    if not any(urls.values()):
        raise SystemExit("No live provider URLs supplied; this is not a passed scrape test")
    evidence = ROOT / "build/live-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    result = {}
    with tempfile.TemporaryDirectory() as directory:
        with backend([sys.executable, str(ROOT / "packaging/clipmaker_api_server.py")], Path(directory), evidence) as base:
            for provider, url in urls.items():
                if not url:
                    result[provider] = "not configured"
                    continue
                project = request(base, "/api/projects", {"name": "Live provider check"})["project"]
                match = request(base, "/api/scrape", {"project_id": project["id"], "url": url})["match"]
                assert match["event_count"] > 0 and match["home_team"] and match["away_team"], match
                saved = request(base, "/api/projects/" + project["id"])["project"]
                assert saved["event_count"] == match["event_count"]
                result[provider] = {"status": "passed", "events": match["event_count"]}
    (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
