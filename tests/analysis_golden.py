"""Capture what the Streamlit Analyst Room and Tactical Lab show, as parity snapshots.

Phase 0 of docs/ANALYSIS_MIGRATION_PLAN.md. Each snapshot records, per view,
tab and control scenario, the data a user sees: map payloads sent to the JS
component, Plotly figures, metrics, tables, text panels and control options.
The native implementation must reproduce these for the same scenarios.

Usage:
  python -m tests.analysis_golden --write            # refresh committed fixture golden
  python -m tests.analysis_golden --check            # compare against it
  python -m tests.analysis_golden --csv a.csv b.csv --out build/golden/local.json.gz
                                                     # local real-match baseline (not committed)
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import itertools
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "analysis" / "fixture.json.gz"
SCHEMA = 1
MAX_SCENARIOS_PER_TAB = 80
TAB_KEYS = {"analyst": "analyst_tabs", "tactical": "tactical_tabs"}
# Buttons that start video work need footage; snapshots cover data views only.
SAFE_BUTTON = re.compile(r"^bu_chain_0$")
SKIP_KEYS = re.compile(r"(_active_match_csv$|^tl_selected_matches$)")


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


def _leaves(node):
    children = getattr(node, "children", None)
    if children:
        for child in children.values():
            yield from _leaves(child)
    else:
        yield node


def _element(node, norm: Normalizer):
    kind = type(node).__name__
    proto_type = str(getattr(node, "type", ""))
    key = getattr(node, "key", None)
    if kind in {"Tab", "Divider", "SpecialBlock"} or proto_type in {"iframe", "empty"}:
        return None
    if kind == "Markdown" and str(node.value).lstrip().startswith("<style"):
        # Styling only; recorded as size + digest so font payload changes stay visible.
        raw = str(node.value).encode("utf-8")
        return {"kind": "style", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()[:16]}
    if kind in {"Markdown", "Caption", "Subheader", "Header", "Title", "Text", "Info", "Warning", "Error", "Success", "Exception"}:
        return {"kind": kind, "value": norm.text(str(node.value))}
    if kind == "Metric":
        return {"kind": kind, "label": node.label, "value": norm.text(str(node.value)), "delta": str(node.delta or "")}
    if kind == "Dataframe":
        frame = node.value
        return {"kind": kind, "columns": [str(c) for c in frame.columns],
                "rows": norm.data(_round(json.loads(frame.to_json(orient="values", date_format="iso"))))}
    if kind in {"Radio", "Selectbox", "Multiselect"}:
        options = [] if key and SKIP_KEYS.search(key) else [norm.text(str(o)) for o in node.options]
        return {"kind": kind, "key": key, "label": node.label, "options": options,
                "value": norm.data(_round(node.value if not isinstance(node.value, tuple) else list(node.value)))}
    if kind in {"Slider", "Toggle", "Checkbox", "NumberInput"}:
        value = node.value
        return {"kind": kind, "key": key, "label": node.label,
                "value": _round(list(value) if isinstance(value, tuple) else value),
                "min": _round(getattr(node, "min", None)), "max": _round(getattr(node, "max", None))}
    if kind in {"Button", "DownloadButton"}:
        return {"kind": kind, "key": key, "label": norm.text(str(getattr(node, "label", "")))}
    if proto_type == "component_instance":
        proto = getattr(node.proto, "component_instance", node.proto)
        args = json.loads(proto.json_args or "{}")
        return {"kind": "component", "args": norm.data(_round(args))}
    if proto_type == "plotly_chart":
        spec = json.loads(getattr(node.proto, "plotly_chart", node.proto).spec or "{}")
        for trace in spec.get("data", []):
            trace.pop("uid", None)
        return {"kind": "plotly", "figure": norm.data(_round(spec))}
    return {"kind": kind, "type": proto_type}


def _snapshot(app, norm):
    elements = [item for item in (_element(node, norm) for node in _leaves(app.main)) if item]
    return {"exceptions": [norm.text(e.message) for e in app.exception], "elements": elements}


def _controls(app):
    values = {}
    for kind in ("radio", "selectbox", "slider", "toggle", "multiselect"):
        for widget in getattr(app, kind):
            if widget.key and not widget.key.startswith(("analyst_tabs", "tactical_tabs")) and not SKIP_KEYS.search(widget.key):
                value = widget.value
                values[widget.key] = (kind, list(value) if isinstance(value, tuple) else value)
    return values


class Explorer:
    def __init__(self, app, view, norm, deadline):
        self.app, self.view, self.norm, self.deadline = app, view, norm, deadline
        self.tab_key = TAB_KEYS[view]
        self.tab = None
        self.records = []
        self.seen = set()

    labels = None

    def run(self):
        self.app.session_state[self.tab_key] = self.tab
        if self.labels:
            install_labels(self.app, self.labels)
        try:
            self.app.run(timeout=180)
        except IndexError:
            # AppTest re-applies format_func to a stale Video Lab moment id after
            # the playlist rows change; the browser sends an index instead.
            stale = [box for box in self.app.selectbox if (box.key or "").startswith("vl_selected_moment_")]
            if not stale:
                raise
            for box in stale:
                box.set_value(None)  # send no value, as a fresh browser widget would
            self.app.run(timeout=180)

    def record(self, scenario):
        if len(self.records) >= MAX_SCENARIOS_PER_TAB:
            return
        snapshot = _snapshot(self.app, self.norm)
        controls = {k: v[1] for k, v in _controls(self.app).items()}
        # Clicks change what is shown without changing any control value.
        clicks = sorted(key for key, value in scenario.items() if value == "click")
        identity = json.dumps([controls, clicks], sort_keys=True, default=str)
        if identity in self.seen:
            return
        self.seen.add(identity)
        self.records.append({"scenario": scenario, "controls": _round(controls), **snapshot})

    def set(self, kind, key, value):
        getattr(self.app, kind)(key=key).set_value(value)
        self.run()

    def explore(self, tab):
        self.tab = tab
        self.records, self.seen = [], set()
        self.run()
        self.record({})
        base = _controls(self.app)
        for key, (kind, value) in base.items():
            if kind != "radio":
                continue
            for option in self.app.radio(key=key).options:
                if option == value:
                    continue
                self.set("radio", key, option)
                self.record({key: option})
                self._explore_selects({key: option}, exclude=set(), limit=1)
            self.set("radio", key, value)
        self._explore_selects({}, exclude=set())
        for key, (kind, value) in base.items():
            if kind == "slider":
                slider = self.app.slider(key=key)
                for edge in (slider.min, slider.max):
                    if edge != value:
                        self.set("slider", key, edge)
                        self.record({key: edge})
                self.set("slider", key, value)
            elif kind == "toggle" and key != "tl_multi_mode":
                self.set("toggle", key, not value)
                self.record({key: not value})
                self.set("toggle", key, value)
        for button in list(self.app.button):
            if button.key and SAFE_BUTTON.search(button.key):
                button.click()
                self.run()
                self.record({button.key: "click"})
                break
        self._keeper_comparisons(base)
        return self.records

    def _keeper_comparisons(self, base):
        """Comparison: keeper vs outfield (role warning) and keeper vs keeper (GK axes)."""
        controls = _controls(self.app)
        if "comp_player1" not in controls or "comp_team2" not in controls:
            return
        keeper = lambda key: next((o for o in self.app.selectbox(key=key).options if "Keeper" in str(o)), None)
        first = keeper("comp_player1")
        if not first:
            return
        self.set("selectbox", "comp_player1", first)
        self.record({"comp_player1": first})
        team1 = self.app.radio(key="comp_team1").value
        other = [team for team in self.app.radio(key="comp_team2").options if team != team1]
        if other:
            self.set("radio", "comp_team2", other[0])
            second = keeper("comp_player2")
            if second:
                self.set("selectbox", "comp_player2", second)
                self.record({"comp_player1": first, "comp_team2": other[0], "comp_player2": second})
            self.set("radio", "comp_team2", base["comp_team2"][1])
        self.set("selectbox", "comp_player1", base["comp_player1"][1])

    def _explore_selects(self, scenario, exclude, limit=2, depth=2):
        """Try the first real options of each select; follow selects they reveal."""
        before = _controls(self.app)
        for key, (kind, value) in before.items():
            if kind != "selectbox" or key in exclude:
                continue
            options = self.app.selectbox(key=key).options
            candidates = [o for o in options[:3] if o != value]
            for option in candidates[:limit]:
                self.set("selectbox", key, option)
                self.record({**scenario, key: option})
                revealed = set(_controls(self.app)) - set(before)
                if depth > 1 and revealed:
                    self._explore_selects({**scenario, key: option}, exclude=set(before) | {key},
                                          limit=1, depth=depth - 1)
            self.set("selectbox", key, value)


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


def select_matches(app, paths):
    """Pick matches in the multiselect.

    AppTest evaluates format_func outside the script, where session state is
    unavailable, so labels are mapped from the options the page rendered.
    """
    from streamlit.testing.v1.element_tree import TESTING_KEY
    box = app.multiselect(key="tl_selected_matches")
    options = list(box.options)
    if len(set(options)) != len(options) or len(options) != len(paths):
        raise RuntimeError(f"Match options are not distinct: {options}")
    labels = dict(zip(paths, options))
    install_labels(app, labels)
    # The page lists projects in folder (random id) order; select by file name
    # so the merged frame and default team are stable between runs.
    box.set_value(sorted(paths, key=lambda path: Path(path).name))
    app.run()
    return labels


def install_labels(app, labels):
    from streamlit.testing.v1.element_tree import TESTING_KEY
    for box in app.multiselect:
        if box.key == "tl_selected_matches":
            app.session_state[TESTING_KEY][box.id] = labels.__getitem__


def capture(csvs, root: Path, log=print):
    from streamlit.testing.v1 import AppTest
    ids = _make_projects(root, csvs)
    norm = Normalizer(root.parent, ids)
    result = {"schema": SCHEMA, "inputs": [], "views": {}, "timings": {}}
    for csv in csvs:
        result["inputs"].append({"name": Path(csv).name, "sha256": hashlib.sha256(Path(csv).read_bytes()).hexdigest()})
    env = {"CLIPMAKER_ANALYSIS_MODE": "1", "CLIPMAKER_DATA_DIR": str(root)}
    with patch.dict(os.environ, env):
        for view in ("analyst", "tactical"):
            app = AppTest.from_file(str(ROOT / "app" / "analysis_entry.py"), default_timeout=180)
            app.query_params.update({"project": ids[0], "view": view})
            started = time.monotonic()
            app.run()
            result["timings"][f"{view}:first_run_s"] = round(time.monotonic() - started, 3)
            explorer = Explorer(app, view, norm, None)
            tabs = {}
            for tab in [t.label for t in app.tabs]:
                started = time.monotonic()
                tabs[tab] = explorer.explore(tab)
                result["timings"][f"{view}:{tab}"] = round(time.monotonic() - started, 3)
                log(f"  {view} / {tab}: {len(tabs[tab])} scenarios")
            if view == "tactical" and len(ids) > 1:
                app.toggle(key="tl_multi_mode").set_value(True).run()
                explorer.labels = select_matches(app, list(app.session_state["multi_scraped_csv_paths"]))
                if not any(box.key == "tactical_team" for box in app.selectbox):
                    raise RuntimeError("Multi-match mode did not load: " + "; ".join(
                        str(e.value) for e in [*app.info, *app.error, *app.exception]))
                explorer.seen = set()
                multi = {}
                for tab in [t.label for t in app.tabs]:
                    multi[f"multi:{tab}"] = explorer.explore(tab)
                    log(f"  {view} / multi / {tab}: {len(multi[f'multi:{tab}'])} scenarios")
                tabs.update(multi)
            result["views"][view] = tabs
    return result


def save(result, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0) as handle:
        handle.write(payload)


def load(path: Path):
    with gzip.open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def differences(expected, actual, path="$"):
    """Yield human-readable differences between two snapshots."""
    if type(expected) is not type(actual):
        yield f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
    elif isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                yield f"{path}.{key}: present only in {'actual' if key not in expected else 'expected'}"
            else:
                yield from differences(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            yield f"{path}: length {len(expected)} != {len(actual)}"
        else:
            for index, (left, right) in enumerate(zip(expected, actual)):
                yield from differences(left, right, f"{path}[{index}]")
    elif expected != actual:
        yield f"{path}: {str(expected)[:120]!r} != {str(actual)[:120]!r}"


def compare(expected, actual, limit=20):
    """Return up to ``limit`` human-readable differences, ignoring timings."""
    expected = {k: v for k, v in expected.items() if k != "timings"}
    actual = {k: v for k, v in actual.items() if k != "timings"}
    return list(itertools.islice(differences(expected, actual), limit))


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="refresh the committed fixture golden")
    mode.add_argument("--check", action="store_true", help="compare current pages against the committed golden")
    mode.add_argument("--csv", nargs="+", type=Path, help="capture local match CSVs instead of the fixture")
    parser.add_argument("--out", type=Path, help="output path for --csv")
    args = parser.parse_args(argv)
    if args.csv:
        if not args.out:
            parser.error("--csv requires --out")
        with tempfile.TemporaryDirectory(prefix="vizorplay-golden-") as name:
            result = capture([p.resolve() for p in args.csv], Path(name) / "data")
        save(result, args.out)
        print(f"Wrote {args.out}")
        return 0
    with fixture_inputs() as (csvs, data):
        data.mkdir()
        result = capture(csvs, data)
    if args.write:
        save(result, GOLDEN)
        print(f"Wrote {GOLDEN} ({GOLDEN.stat().st_size} bytes)")
        return 0
    problems = compare(load(GOLDEN), result)
    for problem in problems:
        print("DIFF", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
