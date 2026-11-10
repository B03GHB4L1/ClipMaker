"""Native Shot Map parity against the classic workspace's recorded snapshot."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

from analysis_core import build_analyst_frames, shot_map  # noqa: E402
from tests import analysis_golden  # noqa: E402

TAB = "◉ Shot Map"
IGNORED_ARGS = {"key", "default"}


def classic_components(record):
    return [{k: v for k, v in element["args"].items() if k not in IGNORED_ARGS}
            for element in record["elements"] if element["kind"] == "component"]


def element_value(record, kind, key):
    return next((element for element in record["elements"] if element["kind"] == kind and element.get("key") == key), None)


class ShotMapParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from clipmaker_core import read_csv_safe
        cls.golden = analysis_golden.load(analysis_golden.GOLDEN)["views"]["analyst"][TAB]
        with analysis_golden.fixture_inputs() as (csvs, _):
            cls.frames = build_analyst_frames(read_csv_safe(str(csvs[0])), source=str(csvs[0]))

    def native_controls(self, record):
        controls = record["controls"]
        mode = "penalties" if controls.get("smp_mode_radio") == "Penalty Shootout" else "normal"
        native = {"mode": mode, "team": controls.get("smp_team_radio"),
                  "player": controls.get("smp_player_sel"), "zone": controls.get("smp_pitch_zone_sel")}
        chosen = controls.get("smp_pso_shot_sel" if mode == "penalties" else "smp_shot_sel")
        if chosen and not chosen.startswith("—"):
            listing = shot_map.build_view(self.frames, {**native, "selected": None})["shots"]
            native["selected"] = next(item["id"] for item in listing if item["label"] == chosen)
        return native

    def test_every_recorded_scenario_matches(self):
        self.assertGreaterEqual(len(self.golden), 8)
        modes = set()
        for record in self.golden:
            with self.subTest(scenario=record["scenario"]):
                view = analysis_golden._round(shot_map.build_view(self.frames, self.native_controls(record)))
                modes.add(view["mode"])
                infos = [element["value"] for element in record["elements"] if element["kind"] == "Info"]
                if view.get("empty"):
                    self.assertIn(view["empty"], infos)
                    continue
                expected = classic_components(record)
                actual = [args for args in (view["goalframe"], view["map"]) if args]
                self.assertEqual(expected, actual)

                select_key = "smp_pso_shot_sel" if view["mode"] == "penalties" else "smp_shot_sel"
                select = element_value(record, "Selectbox", select_key)
                self.assertEqual(select["options"], [view["placeholder"]] + [shot["label"] for shot in view["shots"]])

                if view["mode"] == "normal":
                    stats_html = next(e["value"] for e in record["elements"]
                                      if e["kind"] == "Markdown" and "cm-stats-bar" in e["value"])
                    numbers = [int(n) for n in re.findall(r"cm-stats-(?:home|away)\"[^>]*>(\d+)%?<", stats_html)]
                    stats = view["stats"]
                    expected_numbers = ([stats["share"]["home"], stats["share"]["away"]] if stats["share"] else []) + [
                        stats["home"]["shots"], stats["away"]["shots"], stats["home"]["on_target"],
                        stats["away"]["on_target"], stats["home"]["goals"], stats["away"]["goals"]]
                    self.assertEqual(numbers, expected_numbers)
                    self.assertEqual(element_value(record, "Radio", "smp_team_radio")["options"], view["controls"]["teams"])
                    self.assertEqual(element_value(record, "Selectbox", "smp_player_sel")["options"], view["controls"]["players"])

                panel = next((e["value"] for e in record["elements"]
                              if e["kind"] == "Markdown" and "cm-shot-panel" in e["value"]), None)
                if view["selected"] is None:
                    self.assertIsNone(panel)
                else:
                    detail = view["selected"]
                    for text in (detail["player"], detail["team"], detail["time"].replace('"', "&quot;")
                                 if "&quot;" in panel else detail["time"],
                                 " · ".join(detail["qualifiers"]) or "—"):
                        self.assertIn(text, panel)
        self.assertEqual(modes, {"normal", "penalties"})

    def test_invalid_controls_fall_back_safely(self):
        view = shot_map.build_view(self.frames, {"team": "Nobody", "player": "<script>", "zone": "Moon",
                                                 "selected": "not-a-number", "mode": "penalties!"})
        self.assertEqual(view["mode"], "normal")
        self.assertEqual(view["controls"]["team"], self.frames.home_team)
        self.assertEqual((view["controls"]["player"], view["controls"]["zone"], view["selected"]), ("All players", "", None))
        self.assertIsNone(shot_map.build_view(self.frames, {"selected": 10**9})["selected"])
        with self.assertRaises(ValueError):
            shot_map.clip_event(self.frames, "normal", None)


if __name__ == "__main__":
    unittest.main()
