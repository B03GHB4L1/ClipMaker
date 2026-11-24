"""The committed parity snapshot of the retired Streamlit analysis pages.

tests/golden/analysis/fixture.json.gz records, per view, tab and control
scenario, what the classic Analyst Room and Tactical Lab showed for the
synthetic fixture (tests/analysis_fixture.py): map payloads, Plotly figures,
metrics, tables, text and control options. It was captured with Streamlit's
AppTest in Phase 0 of docs/ANALYSIS_MIGRATION_PLAN.md (the recorder is in the
git history, last at commit 4c49a6b). Streamlit and those pages were removed in
Phase 5, so the snapshot is now a fixed oracle: tests/test_analyst_native.py
and tests/test_tactical_native.py check the native tabs against it.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "analysis" / "fixture.json.gz"


OLD_CREDIT = "@B03GHB4L1"


def without_chart_restyle(figure):
    """A Plotly figure without what VizorPlay deliberately restyled for both themes:
    the handle text credit (exported pictures carry the VizorPlay logo strip now,
    ui/analysis/brand-export.js), the radar's polar area (themed, not Plotly's white
    disc) and the radar trace colours (olive on light paper, where lime had no contrast).
    See tests/test_chart_theme.py."""
    layout = dict(figure.get("layout", {}))
    layout.pop("polar", None)
    if layout.get("annotations"):
        layout["annotations"] = [a for a in layout["annotations"] if OLD_CREDIT not in str(a.get("text", ""))]
        if not layout["annotations"]:
            del layout["annotations"]
    data = [{k: v for k, v in trace.items() if k not in {"line", "fillcolor", "marker"}}
            if trace.get("type") == "scatterpolar" else trace for trace in figure.get("data", [])]
    return {**figure, "data": data, "layout": layout}


def without_credit_graphic(option):
    """An ECharts option without the handle text credit it used to draw."""
    if not isinstance(option, dict) or not option.get("graphic"):
        return option
    graphic = [g for g in option["graphic"] if OLD_CREDIT not in str((g.get("style") or {}).get("text", ""))]
    option = {k: v for k, v in option.items() if k != "graphic"}
    return {**option, "graphic": graphic} if graphic else option


def _round(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return float(f"{value:.6g}")
    if isinstance(value, dict):
        return {str(k): _round(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


class Normalizer:
    """Replace machine-specific paths and generated identifiers."""

    def __init__(self, root: Path, project_ids):
        variants = {str(root), str(root).replace("\\", "/"), str(root.resolve()), str(root.resolve()).replace("\\", "/"),
                    os.path.normcase(str(root.resolve()))}
        self.paths = sorted((v for v in variants if v), key=len, reverse=True)
        self.ids = list(project_ids)

    def text(self, value: str) -> str:
        for path in self.paths:
            value = value.replace(path, "<DATA>").replace(path.replace("\\", "\\\\"), "<DATA>")
        for index, project_id in enumerate(self.ids):
            value = value.replace(project_id, f"<PROJECT{index}>")
        # Paths inside the data root use the OS separator; record them POSIX-style.
        return re.sub(r"<DATA>[^\s'\"<>|,;)]*",
                      lambda match: re.sub(r"\\+", "/", match.group(0)), value)

    def data(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(k)): self.data(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.data(v) for v in value]
        return value


def _make_projects(root: Path, csvs):
    sys.path.insert(0, str(ROOT))
    import pandas as pd
    from packaging.clipmaker_api_server import MatchStore
    store = MatchStore(root)
    ids = []
    for index, csv in enumerate(csvs):
        teams = pd.read_csv(csv, usecols=lambda c: c in {"homeTeam", "awayTeam", "team"}, nrows=50)
        home = str(teams["homeTeam"].dropna().iloc[0]) if "homeTeam" in teams else str(teams["team"].dropna().unique()[0])
        away = str(teams["awayTeam"].dropna().iloc[0]) if "awayTeam" in teams else str(teams["team"].dropna().unique()[-1])
        project = store.create(f"Parity match {index + 1}")
        store.upsert({"id": project["id"], "csv_path": str(csv), "home_team": home, "away_team": away,
                      "markers": {"1H": "00:00:00", "2H": "00:50:00"}})
        ids.append(project["id"])
    return ids


def load(path: Path):
    with gzip.open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


@contextlib.contextmanager
def fixture_inputs():
    sys.path.insert(0, str(ROOT))
    from tests.analysis_fixture import build_fixture
    with tempfile.TemporaryDirectory(prefix="vizorplay-golden-") as name:
        root = Path(name)
        first, second = root / "inputs" / "fixture_a.csv", root / "inputs" / "fixture_b.csv"
        first.parent.mkdir()
        build_fixture().to_csv(first, index=False, lineterminator="\n")
        build_fixture(events=900, seed=7, home="Eastfield", away="Northbridge").to_csv(second, index=False, lineterminator="\n")
        yield [first, second], root / "data"
