"""Optional real-provider health check, separate from deterministic regression tests."""
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
from smoke_test import backend, request


def check_providers(base, urls, evidence):
    result = {}
    for provider, url in urls.items():
        if not url:
            result[provider] = {"status": "not configured"}
            continue
        try:
            project = request(base, "/api/projects", {"name": "Live provider check"})["project"]
            match = request(base, "/api/scrape", {"project_id": project["id"], "url": url})["match"]
            assert match["event_count"] > 0 and match["home_team"] and match["away_team"], match
            saved = request(base, "/api/projects/" + project["id"])["project"]
            assert saved["event_count"] == match["event_count"]
            result[provider] = {"status": "passed", "events": match["event_count"]}
        except HTTPError as error:
            with error:
                result[provider] = {"status": "failed", "http_status": error.code,
                                    "error": error.read().decode("utf-8", errors="replace")}
        except Exception as error:
            result[provider] = {"status": "failed", "error": str(error)}
        # Preserve earlier successes and diagnose both providers even if one fails.
        (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"{provider}: {json.dumps(result[provider])}", flush=True)
    return result


def main():
    urls = {name: os.environ.get(name, "").strip() for name in ("SCORESWAY_URL", "WHOSCORED_URL")}
    if not any(urls.values()):
        raise SystemExit("No live provider URLs supplied; this is not a passed scrape test")
    evidence = ROOT / "build/live-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        with backend([sys.executable, str(ROOT / "packaging/clipmaker_api_server.py")], Path(directory), evidence) as base:
            result = check_providers(base, urls, evidence)
    (evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    assert not any(item["status"] == "failed" for item in result.values()), result


if __name__ == "__main__":
    main()
