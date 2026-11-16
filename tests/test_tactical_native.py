"""Native Tactical Lab versus the classic workspace's recorded snapshot.

The native tabs run the classic tab code (copied verbatim into
analysis_core.tactical_page) against a recorder; this checks the recorded
output matches what Streamlit showed for every recorded scenario.
"""
import html
import json
import re
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
from analysis_core.st_shim import _plain_arrays  # noqa: E402
from tests import analysis_golden  # noqa: E402

COMPARED = {"Subheader", "Caption", "Markdown", "Info", "Warning", "Error", "Success", "Metric", "plotly",
            "Dataframe", "Selectbox", "Slider", "Button"}


# The classic centre circle was drawn oval (y units are 0.68 of x units).
OVAL_CIRCLE = {"x0": 41.5, "y0": 35, "x1": 58.5, "y1": 65}
ROUND_CIRCLE = {"x0": 41.3, "y0": 37.2, "x1": 58.7, "y1": 62.8}


def deliberate_fixes(figure):
    """The classic figure with VizorPlay's deliberate fixes applied: binary arrays
    decoded to the plain lists the bundled Plotly.js can draw, and a round circle."""
    figure = _plain_arrays(figure)
    shapes = figure.get("layout", {}).get("shapes")
    if shapes:
        figure["layout"]["shapes"] = [
            {**shape, **ROUND_CIRCLE} if shape.get("type") == "circle"
            and all(shape.get(key) == value for key, value in OVAL_CIRCLE.items()) else shape
            for shape in shapes]
    return figure


ATTACK_LABEL = "ATTACK ->"
XG_PLAYLIST = "Shots By xG"
NEW_STYLE_CHARTS = re.compile(r"Pass Directness - |Possession Length - median")
REMOVED_STYLE_CHARTS = re.compile(r"Progression Funnel Per Match")
NEW_STYLE_CAPTIONS = {"No passes with end locations for this team.", "No possessions found for this team."}
MOMENT_CELL = re.compile(r'<div style="padding:9px 10px[^"]*">([^<]*)</div>')


def normal(element, norm):
    kind = element["kind"]
    # Video Lab's ten-row HTML table became a pickable, paged list of every moment;
    # its first ten rows must still be the classic table's rows.
    if kind == "MomentList":
        return ("Moments", [[row["time"], row["player"], row["moment"], f"{row['score']:.2f}"] for row in element["rows"][:10]])
    if kind == "Markdown" and 'grid-template-columns:72px 1.4fr 1fr 58px' in element["value"]:
        cells = [html.unescape(cell).strip() for cell in MOMENT_CELL.findall(element["value"])][4:]
        return ("Moments", [cells[i:i + 4] for i in range(0, len(cells), 4)])
    if kind == "Markdown" and not element["value"].strip():
        return None
    if kind == "Selectbox" and element["key"].startswith("vl_selected_moment_"):
        return None  # Picked from the moment list instead; see test_video_lab_moment_list_drives_the_picker.
    if kind == "Slider" and element["key"] == "vl_reel_count":
        return None  # The reel is the moments ticked in the list now; see test_video_lab_reel_is_the_ticked_moments.
    if kind == "Markdown" and element["value"].lstrip().startswith("<style"):
        return None
    if kind in {"Subheader", "Caption", "Markdown", "Info", "Warning", "Error", "Success"}:
        return (kind, norm.text(element["value"]))
    if kind == "Metric" and element["label"] == "xG / Shot":
        return None  # VizorPlay xG is new; see test_style_profile_shows_xg_per_shot.
    if kind == "Selectbox" and element["key"] == "vl_playlist":
        element = {**element, "options": [o for o in element["options"] if o != XG_PLAYLIST]}
    if kind == "Metric":
        return (kind, element["label"], norm.text(element["value"]), element.get("delta") or "")
    if kind == "plotly" and REMOVED_STYLE_CHARTS.search(json.dumps(element["figure"].get("layout", {}))):
        return None  # Taken out of Style Profile; see test_style_profile_has_no_progression_funnel.
    if kind == "plotly" and NEW_STYLE_CHARTS.search(json.dumps(element["figure"].get("layout", {}))):
        return None  # Added to Style Profile; see test_style_profile_directness_and_possession_length.
    if kind == "Caption" and element["value"] in NEW_STYLE_CAPTIONS:
        return None
    if kind == "plotly":
        # Classic figures carry Streamlit's placeholder colours, swapped for its
        # light palette in the browser; compare the colours users saw.
        figure = replace_placeholders(analysis_golden._round(deliberate_fixes(element["figure"])))
        layout = {k: v for k, v in figure.get("layout", {}).items() if k != "template"}
        # The attack-direction label is new on the pitch maps; see test_pitch_maps_show_the_attack_direction.
        # The label gets 26px of its own at the top; the chart grows by the same so the pitch keeps its size.
        if "Territory Heatmap" in json.dumps(layout.get("title")):
            # Axis titles (raw column names) dropped and the note moved under the labels.
            for axis in ("xaxis", "yaxis"):
                layout[axis] = {k: v for k, v in (layout.get(axis) or {}).items() if k != "title"}
            layout["annotations"] = [{k: v for k, v in a.items() if k != "yshift"} for a in layout.get("annotations") or []]
        if any(a.get("text") == ATTACK_LABEL for a in layout.get("annotations") or []):
            layout["annotations"] = [a for a in layout["annotations"] if a.get("text") != ATTACK_LABEL]
            layout["margin"] = {**layout["margin"], "t": layout["margin"]["t"] - 26}
            layout["height"] = layout["height"] - 26
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
                        # Plotly.js 2.27 cannot read binary arrays; it drew empty maps.
                        self.assertNotIn('"bdata"', json.dumps(view))
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

    def test_style_profile_has_no_progression_funnel(self):
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            projects = MatchStore(data).list()
            project = next(item for item in projects if item["id"] == ids[0])
            view, _ = tactical.render("style-profile", {}, project, projects)
            text = json.dumps(view)
            self.assertNotIn("Progression Funnel", text)
            self.assertIn("Territory Heatmap", text)

    def test_pitch_maps_show_the_attack_direction(self):
        """Transition maps, the restart map and the event trace say which way the team attacks."""
        import plotly.graph_objects as go
        from analysis_core import tactical_page
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            projects = MatchStore(data).list()
            project = next(item for item in projects if item["id"] == ids[0])
            wanted = {"Loss Locations By Transition Outcome": "defensive-transitions",
                      "Recovery Locations By Attack Outcome": "attacking-transitions",
                      "Restart Delivery Map": "set-pieces", "Event Trace": "video-lab"}
            for title, slug in wanted.items():
                controls = {"vl_playlist": "Restarts"} if slug == "video-lab" else {}
                view, _ = tactical.render(slug, controls, project, projects)
                figures = [e["figure"] for e in view["elements"] if e["kind"] == "plotly" and title in json.dumps(e["figure"])]
                with self.subTest(map=title):
                    self.assertTrue(figures, title)
                    labels = [a for a in figures[0]["layout"].get("annotations", []) if a.get("text") == ATTACK_LABEL]
                    self.assertEqual(len(labels), 1)
                    # Just above the pitch's top-left corner, in pitch coordinates.
                    self.assertEqual((labels[0]["x"], labels[0]["y"], labels[0]["xanchor"], labels[0]["yanchor"]),
                                     (0, 100, "left", "bottom"))
                    # Clear of the subtitle, and the pitch area is no smaller than before the label.
                    layout = figures[0]["layout"]
                    self.assertEqual(layout["margin"]["t"], 118)
                    plain = tactical_page._pitch_layout(go.Figure(), title, height=layout["height"] - 26).to_plotly_json()["layout"]
                    self.assertEqual(layout["height"] - layout["margin"]["t"], plain["height"] - plain["margin"]["t"])
            # Other pitch charts are unchanged.
            view, _ = tactical.render("style-profile", {}, project, projects)
            self.assertNotIn(ATTACK_LABEL, json.dumps(view))

    def test_style_profile_directness_and_possession_length(self):
        import pandas as pd
        from analysis_core import tactical_page as page

        def event(team, kind, x=50, y=50, end=None, outcome="Successful", second=0):
            row = {"team": team, "type": kind, "x": x, "y": y, "outcomeType": outcome,
                   "period_order": 1, "minute": 1, "second": second}
            row["endX"], row["endY"] = end if end else (None, None)
            return row

        # Directness: 2 forward (one long), 1 sideways, 1 backward.
        passes = pd.DataFrame([
            event("A", "Pass", 20, 50, (60, 50)),              # 42m forward
            event("A", "Pass", 50, 50, (60, 55)),              # forward (10.5m along, 3.4m across)
            event("A", "Pass", 50, 20, (52, 60), "Unsuccessful"),  # sideways
            event("A", "Pass", 50, 50, (40, 50)),              # backward
        ])
        profile = page.pass_directness(passes)
        shares = {row["group"]: row["share"] for row in profile["direction"]}
        self.assertEqual(shares, {"Forward": 50.0, "Sideways": 25.0, "Backward": 25.0})
        self.assertEqual({row["group"]: row["count"] for row in profile["length"]},
                         {"Short (<15m)": 2, "Medium (15-30m)": 1, "Long (30m+)": 1})
        self.assertEqual(next(r for r in profile["direction"] if r["group"] == "Sideways")["completion"], 0.0)
        self.assertIsNone(page.pass_directness(passes.iloc[0:0]))

        # Possessions: A passes 3 times and shoots; B touches it; A passes once; period change; A passes once.
        rows = [event("A", "Pass", second=1), event("A", "Pass", second=2), event("A", "Pass", second=3),
                event("A", "Goal", second=4), event("B", "Pass", second=5), event("A", "Tackle", second=6),
                event("A", "Pass", second=7)]
        later = event("A", "Pass", second=1)
        later["period_order"] = 2
        lengths = page.possession_lengths(pd.DataFrame(rows + [later]), "A")
        self.assertEqual(lengths["possessions"], 3)
        bands = {row["group"]: (row["count"], row["shot_rate"]) for row in lengths["bands"]}
        self.assertEqual(bands["1-2 passes"], (2, 0.0))
        self.assertEqual(bands["3-5 passes"], (1, 100.0))
        self.assertIsNone(page.possession_lengths(pd.DataFrame(rows), "C"))

        # Both charts appear on the Style Profile tab of a real match.
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            projects = MatchStore(data).list()
            project = next(item for item in projects if item["id"] == ids[0])
            view, _ = tactical.render("style-profile", {}, project, projects)
            titles = json.dumps([e["figure"]["layout"] for e in view["elements"] if e["kind"] == "plotly"])
            self.assertRegex(titles, r"Pass Directness - \d+% forward, avg [\d.]+m")
            self.assertRegex(titles, r"Possession Length - median \d+ passes")

    def test_video_lab_moment_list_drives_the_picker(self):
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            projects = MatchStore(data).list()
            project = next(item for item in projects if item["id"] == ids[0])
            checked = 0
            for playlist in ("Restarts", "Attacking Transition", "xT Passes And Carries"):
                view, _ = tactical.render("video-lab", {"vl_playlist": playlist}, project, projects)
                lists = [e for e in view["elements"] if e["kind"] == "MomentList"]
                select = next((e for e in view["elements"] if e["kind"] == "Selectbox"
                               and e["key"].startswith("vl_selected_moment_")), None)
                if select is None:
                    continue
                with self.subTest(playlist=playlist):
                    self.assertEqual(len(lists), 1)
                    # Every ranked moment (not just ten), in the picker's order, so a row picks it.
                    self.assertEqual([row["id"] for row in lists[0]["rows"]], select["values"])
                    self.assertTrue(all(row["time"] and row["moment"] for row in lists[0]["rows"]))
                    checked += 1
            self.assertGreater(checked, 0)

    def test_video_lab_reel_is_the_ticked_moments(self):
        """Build Reel cuts exactly the moments ticked in the list, in match order."""
        from unittest.mock import patch
        from analysis_core import tactical_page
        with tempfile.TemporaryDirectory() as name, analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            projects = MatchStore(data).list()
            project = next(item for item in projects if item["id"] == ids[0])
            playlist = "xT Passes And Carries"
            view, _ = tactical.render("video-lab", {"vl_playlist": playlist}, project, projects)
            rows = next(e for e in view["elements"] if e["kind"] == "MomentList")["rows"]
            self.assertGreaterEqual(len(rows), 4)
            self.assertEqual(len({row["pick"] for row in rows}), len(rows), "every moment has its own pick key")
            self.assertFalse(any(e["kind"] == "Slider" and e["key"] == "vl_reel_count" for e in view["elements"]))
            build = next(e for e in view["elements"] if e["kind"] == "Button" and e["key"] == "vl_reel")
            self.assertTrue(build["disabled"], "nothing ticked, nothing to build")

            cut = []
            reel = Path(name) / "reel.mp4"
            reel.write_bytes(b"reel")

            def fake_cut(moment, before=0, after=0):
                cut.append(moment)
                return str(reel)

            # Ranked 4th, 1st and 3rd, plus a pick from another playlist and junk that must be ignored.
            picks = [rows[3]["pick"], rows[0]["pick"], rows[2]["pick"], "9-999999", {"x": 1}]
            controls = {"vl_playlist": playlist, f"vl_reel_moments_{playlist}": picks}
            with (patch.object(tactical_page, "_video_ready", lambda *a, **k: True),
                  patch.object(tactical_page, "_cut_tactical_clip", fake_cut),
                  patch.object(tactical_page, "_concat_tactical_clips", lambda made: str(reel))):
                path, file_name = tactical.clip("video-lab", controls, project, projects, "vl_reel")
            self.assertEqual(path, str(reel))
            self.assertTrue(file_name.endswith("_reel.mp4"))
            chosen = {rows[i]["pick"] for i in (0, 2, 3)}
            self.assertEqual(sorted(f"{m.get('match_id', 0)}-{m['event_id']}" for m in cut), sorted(chosen))
            clock = [(m.get("period"), m.get("event_seconds", m.get("minute", 0) * 60 + m.get("second", 0))) for m in cut]
            self.assertEqual(clock, sorted(clock), "the reel plays in match order")

    def test_reel_picks_only_take_short_text_lists(self):
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            projects = MatchStore(data).list()
            key = "vl_reel_moments_Restarts"
            _, state = tactical.render("video-lab", {key: ["0-1", "0-1", 7] + [f"0-{n}" for n in range(100)],
                                                     "vl_reel_moments_../x": ["0-1"]}, projects[0], projects)
            self.assertEqual(state[key][:3], ["0-1", "7", "0-0"])
            self.assertEqual(len(state[key]), tactical.MAX_REEL)
            self.assertNotIn("vl_reel_moments_../x", state)
            _, state = tactical.render("video-lab", {key: "0-1"}, projects[0], projects)
            self.assertNotIn(key, state)

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
