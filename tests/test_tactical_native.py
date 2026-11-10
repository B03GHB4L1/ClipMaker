"""Native Tactical Lab versus the classic workspace's recorded snapshot.

The native tabs run the classic tab code (copied verbatim into
analysis_core.tactical_page) against a recorder; this checks the recorded
output matches what Streamlit showed for every recorded scenario.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

from analysis_core import TABS, tactical  # noqa: E402
from packaging.clipmaker_api_server import MatchStore  # noqa: E402
from analysis_core.plotly_theme import replace_placeholders  # noqa: E402
from tests import analysis_golden  # noqa: E402

COMPARED = {"Subheader", "Caption", "Markdown", "Info", "Warning", "Error", "Success", "Metric", "plotly",
            "Dataframe", "Selectbox", "Slider", "Button"}


def normal(element, norm):
    kind = element["kind"]
    if kind == "Markdown" and element["value"].lstrip().startswith("<style"):
        return None
    if kind in {"Subheader", "Caption", "Markdown", "Info", "Warning", "Error", "Success"}:
        return (kind, norm.text(element["value"]))
    if kind == "Metric":
        return (kind, element["label"], norm.text(element["value"]), element.get("delta") or "")
    if kind == "plotly":
        # Classic figures carry Streamlit's placeholder colours, swapped for its
        # light palette in the browser; compare the colours users saw.
        figure = replace_placeholders(analysis_golden._round(element["figure"]))
        layout = {k: v for k, v in figure.get("layout", {}).items() if k != "template"}
        return (kind, norm.data({**figure, "layout": layout}))
    if kind == "Dataframe":
        return (kind, element["columns"], norm.data(analysis_golden._round(element["rows"])))
    if kind in {"Selectbox", "Slider"}:
        values = (element["options"],) if kind == "Selectbox" else (element["min"], element["max"])
        return (kind, element["key"], element["label"], *map(norm.data, values),
                norm.data(analysis_golden._round(element["value"])))
    if kind == "Button":
        return (kind, element["key"], element["label"])
    return None


class TacticalNativeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = analysis_golden.load(analysis_golden.GOLDEN)["views"]["tactical"]
        cls.slugs = {tab["classic"]: tab["slug"] for tab in TABS["tactical"]}

    def test_every_recorded_scenario_matches(self):
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs)
            norm = analysis_golden.Normalizer(data.parent, ids)
            projects = MatchStore(data).list()
            project = next(item for item in projects if item["id"] == ids[0])
            by_csv = {item["csv_path"]: item["id"] for item in projects}
            multi_ids = [by_csv[str(path)] for path in sorted(csvs, key=lambda path: path.name)]
            checked = 0
            for name, records in self.golden.items():
                multi = name.startswith("multi:")
                slug = self.slugs[name.split(":", 1)[-1]]
                for record in records:
                    with self.subTest(tab=name, scenario=record["scenario"]):
                        controls = {key: value for key, value in record["controls"].items()
                                    if key not in {"tactical_team", "tl_multi_mode"}}
                        controls["team"] = record["controls"].get("tactical_team")
                        if multi:
                            controls.update(multi=True, matches=multi_ids)
                        view, _ = tactical.render(slug, controls, project, projects)
                        elements = record["elements"]
                        start = next(i for i, e in enumerate(elements) if e.get("key") == "tactical_team") + 1
                        expected = [n for n in (normal(e, analysis_golden.Normalizer(Path("/nonexistent"), []))
                                                for e in elements[start:]) if n]
                        actual = [n for n in (normal(e, norm) for e in view["elements"]) if n]
                        self.assertEqual(expected, actual)
                        team_select = elements[start - 1]
                        self.assertEqual(team_select["options"], view["teams"])
                        self.assertEqual(team_select["value"], view["team"])
                        checked += 1
            self.assertGreaterEqual(checked, 40)

    def test_fast_detectors_match_the_originals(self):
        import pandas as pd
        from analysis_core import tactical_fast, tactical_page
        with analysis_golden.fixture_inputs() as (csvs, _):
            frames = [tactical_page._prepare_df(tactical_page.read_csv_safe(str(path))) for path in csvs]
        merged = []
        for index, frame in enumerate(frames):
            frame = frame.copy()
            frame["match_id"] = index
            merged.append(frame)
        cases = [frames[0], tactical_page._prepare_df(pd.concat(merged, ignore_index=True))]
        cases.append(cases[1][cases[1]["match_id"].eq(1)].copy())  # a scoped subset keeps its event ids
        checked = 0
        for frame in cases:
            for team in frame["team"].dropna().unique():
                for seconds, events in ((4, 3), (8, 8), (15, 12), (10, 5)):
                    for name in ("detect_defensive_transitions", "detect_attacking_transitions"):
                        with self.subTest(team=team, seconds=seconds, events=events, detector=name):
                            expected = tactical_fast._original[name](frame, team, seconds, events)
                            actual = getattr(tactical_fast, name)(frame, team, seconds, events)
                            pd.testing.assert_frame_equal(expected.reset_index(drop=True), actual.reset_index(drop=True))
                            checked += 1
        self.assertGreater(checked, 40)

    def test_unknown_control_keys_never_reach_the_session(self):
        with tempfile.TemporaryDirectory() as name, analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            projects = MatchStore(data).list()
            controls = {"match_setup_by_csv": {"x": {}}, "vl_clip_path": "/etc/passwd", "video_path": "/tmp/x",
                        "dt_seconds": 6}
            _, state = tactical.render("defensive-transitions", controls, projects[0], projects)
            self.assertNotEqual(state.get("vl_clip_path"), "/etc/passwd")
            self.assertNotEqual(state["match_setup_by_csv"], {"x": {}})
            self.assertEqual(state["video_path"], projects[0].get("video_path", ""))
            self.assertEqual(state["dt_seconds"], 6)


if __name__ == "__main__":
    unittest.main()
