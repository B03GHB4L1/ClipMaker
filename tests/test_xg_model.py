"""VizorPlay xG: the model, its weights, and where the app shows it."""
import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import xg_model  # noqa: E402


def shot(**values):
    row = {"type": "SavedShot", "team": "Home", "playerName": "A", "minute": 10, "second": 0, "period": "FirstHalf",
           "x": 90.0, "y": 50.0}
    row.update(values)
    return row


def xg_of(rows):
    return xg_model.add_xg(pd.DataFrame(rows))["xG"]


class WeightsTests(unittest.TestCase):
    def test_weights_ship_with_the_app_and_credit_statsbomb(self):
        weights = json.loads(Path(xg_model.WEIGHTS_PATH).read_text(encoding="utf-8"))
        self.assertEqual(weights["label"], "VizorPlay xG")
        self.assertIn("StatsBomb", weights["source"])
        self.assertEqual(set(weights["coefficients"]), set(xg_model.FEATURES))
        self.assertLess(Path(xg_model.WEIGHTS_PATH).stat().st_size, 4096)  # a few numbers, no data
        self.assertAlmostEqual(weights["penalty_xg"], 0.76)
        self.assertGreater(weights["big_chance"]["offset_yes"], 0)
        self.assertLess(weights["big_chance"]["offset_no"], 0)
        # The fit was checked out of sample and is in the same league as StatsBomb's own model.
        self.assertGreater(weights["check"]["vizorplay_cross_validated"]["auc"], 0.75)
        # The packaged engine bundles the whole app folder, config included, and imports the model.
        spec = (ROOT / "packaging/pyinstaller/clipmaker_server.spec").read_text(encoding="utf-8")
        self.assertIn('(str(ROOT / "app"), "app")', spec)
        self.assertIn('"xg_model"', spec)

    def test_readme_credits_statsbomb(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("VizorPlay xG", readme)
        self.assertIn("StatsBomb", readme)


class GeometryTests(unittest.TestCase):
    def test_distance_and_angle(self):
        distance, angle = xg_model.goal_geometry(11.0, 0.0)  # penalty spot
        self.assertAlmostEqual(float(distance), 11.0)
        self.assertAlmostEqual(float(angle), 2 * math.atan(3.66 / 11), places=6)
        # Off-centre and further out sees less of the goal.
        _, wide = xg_model.goal_geometry(11.0, 10.0)
        self.assertLess(float(wide), float(angle))
        # On the goal line, inside the posts, the whole mouth is open.
        _, line = xg_model.goal_geometry(0.0, 0.0)
        self.assertAlmostEqual(float(line), math.pi, places=4)

    def test_opta_coordinates_become_metres(self):
        distance, _ = xg_model.opta_geometry(pd.Series([100 - 11 / 1.05]), pd.Series([50.0]))
        self.assertAlmostEqual(float(distance[0]), 11.0, places=4)


class FeatureTests(unittest.TestCase):
    def test_flags_and_key_pass_kind(self):
        frame = pd.DataFrame([
            {"type": "Pass", "team": "Home", "is_key_pass": "True", "is_through_ball": "True", "x": 60, "y": 50},
            {"type": "Pass", "team": "Away", "is_key_pass": "True", "is_cross": "True", "x": 30, "y": 10},
            shot(is_header="True", is_big_chance_shot="True", is_fast_break="1"),
            {"type": "Pass", "team": "Home", "is_key_pass": True, "is_cross": True, "x": 80, "y": 5},
            shot(is_volley="True"),
            shot(is_freekick="True", is_penalty="False", x=75),
        ])
        features = xg_model.shot_features(frame)
        self.assertEqual(features.index.tolist(), [2, 4, 5])
        first, second, third = (features.loc[i] for i in (2, 4, 5))
        # The opponent's key pass in between is skipped; the shooter's team made the through ball.
        self.assertEqual((first["through_ball"], first["cross"]), (1.0, 0.0))
        self.assertEqual((first["header"], first["fast_break"], first["big_chance"]), (1.0, 1.0, True))
        self.assertEqual(first["header_distance"], first["distance"])
        self.assertEqual((second["cross"], second["volley"], second["header_distance"]), (1.0, 1.0, 0.0))
        self.assertEqual((third["direct_freekick"], third["through_ball"]), (1.0, 0.0))

    def test_nothing_to_score_without_shots_or_locations(self):
        self.assertTrue(xg_model.add_xg(pd.DataFrame([{"type": "Pass", "x": 1, "y": 2}]))["xG"].isna().all())
        self.assertTrue(xg_model.add_xg(pd.DataFrame([{"type": "Goal", "team": "A"}]))["xG"].isna().all())


class PredictionTests(unittest.TestCase):
    def test_closer_and_central_shots_are_better_chances(self):
        values = xg_of([shot(x=94, y=50), shot(x=80, y=50), shot(x=94, y=20), shot(x=94, y=50, is_header="True")])
        close, far, wide, header = values.tolist()
        self.assertGreater(close, far)
        self.assertGreater(close, wide)
        self.assertGreater(close, header)
        self.assertTrue(all(0 < value < 1 for value in values))

    def test_big_chance_flag_raises_the_value(self):
        plain, big = xg_of([shot(x=88, y=45), shot(x=88, y=45, is_big_chance_shot="True")]).tolist()
        self.assertGreater(big, plain * 1.5)

    def test_penalties_own_goals_and_shootouts(self):
        values = xg_of([
            shot(is_penalty="True", x=88.5),
            shot(type="Goal", is_own_goal="True"),
            shot(period="PenaltyShootout", is_penalty="True"),
            shot(period=5, is_penalty="True"),
            shot(x=None),
        ]).tolist()
        self.assertEqual(values[0], 0.76)
        self.assertTrue(all(np.isnan(value) for value in values[1:]))

    def test_missing_weights_say_so(self):
        original = xg_model.load_weights
        try:
            xg_model.load_weights = lambda: (_ for _ in ()).throw(OSError("no weights"))
            with self.assertRaisesRegex(RuntimeError, "VizorPlay xG could not be calculated"):
                xg_model.add_xg(pd.DataFrame([shot()]))
        finally:
            xg_model.load_weights = original

    def test_real_match_totals_are_plausible(self):
        """Every prepared match frame carries xG on its shots only."""
        from analysis_core.frames import build_analyst_frames
        from clipmaker_core import read_csv_safe
        from tests import analysis_golden
        with analysis_golden.fixture_inputs() as (csvs, _):
            frames = build_analyst_frames(read_csv_safe(str(csvs[0])), source=str(csvs[0]))
        self.assertTrue(frames.passes_df["xG"].isna().all())
        located = frames.shots_df[frames.shots_df["x"].notna()]
        self.assertGreater(located["xG"].notna().sum(), 0)
        self.assertTrue(((located["xG"].dropna() > 0) & (located["xG"].dropna() < 1)).all())


class AnalystViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from analysis_core.frames import build_analyst_frames
        from clipmaker_core import read_csv_safe
        from tests import analysis_golden
        with analysis_golden.fixture_inputs() as (csvs, _):
            cls.frames = build_analyst_frames(read_csv_safe(str(csvs[0])), source=str(csvs[0]))

    def test_shot_map_shows_vizorplay_xg(self):
        from analysis_core import shot_map
        frames = self.frames
        view = shot_map.build_view(frames, {})
        xg_cell = next(cell for cell in view["stats"] if cell["label"] == "xG")
        home = frames.shots_df[frames.shots_df["team"] == frames.home_team]["xG"].sum()
        self.assertEqual(xg_cell["home"], f"{home:.2f}")
        pitch, race = (component["args"] for component in view["components"])
        self.assertEqual(pitch["component_type"], "shot_map")
        self.assertTrue(all("xG" in item for item in pitch["shots"]))
        self.assertEqual((race["component_type"], race["filename_hint"]), ("echarts_option", "xg_race"))
        self.assertIn("StatsBomb", race["context_note"])
        # The race ends at each team's total and its markers select shots.
        scatter = [series for series in race["option"]["series"] if series["type"] == "scatter"]
        self.assertTrue(scatter[0]["name"].startswith(frames.home_team))
        self.assertIn(f"{home:.2f} xG", scatter[0]["name"])
        ids = {point["customdata"] for series in scatter for point in series["data"]}
        self.assertTrue(ids <= set(frames.shots_df.index))
        self.assertTrue(any(" · xG " in item["label"] for item in view["picker"]["items"]))
        located = frames.shots_df[frames.shots_df["xG"].notna()].index[0]
        team = frames.shots_df.at[located, "team"]
        picked = shot_map.build_view(frames, {"team": team, "selected": int(located)})
        field = next(f for f in picked["selected"]["fields"] if f["label"] == "VizorPlay xG")
        self.assertEqual(field["value"], f"{frames.shots_df.at[located, 'xG']:.2f}")

    def test_picking_a_shot_on_the_race_shows_its_team(self):
        from analysis_core import shot_map
        frames = self.frames
        away_shot = int(frames.shots_df[frames.shots_df["team"] == frames.away_team].index[0])
        view = shot_map.build_view(frames, {"team": frames.home_team, "selected": away_shot})
        self.assertEqual(view["controls"]["team"], frames.away_team)
        self.assertEqual(view["controls"]["selected"], away_shot)
        self.assertEqual(view["selected"]["id"], away_shot)

    def test_comparison_shows_shooting_and_xg(self):
        from analysis_core import comparison
        frames = self.frames
        shooters = frames.shots_df["playerName"].value_counts().index[:2].tolist()
        teams = [frames.shots_df[frames.shots_df["playerName"] == name]["team"].iloc[0] for name in shooters]
        view = comparison.build_view(frames, {"team1": teams[0], "player1": shooters[0],
                                              "team2": teams[1], "player2": shooters[1]})
        figure = next(item for item in view["figures"] if item["section"] == "Shooting & xG")
        self.assertEqual(view["figures"].index(figure), 3)  # drawn under the radar by index
        ev = frames.df_all[frames.df_all["playerName"] == shooters[0]]
        profile = comparison.shooting_profile(ev, frames.df_all)
        self.assertEqual(list(profile), ["Minutes", "Shots", "Goals", "xG", "Goals - xG", "xG per shot"])
        self.assertAlmostEqual(profile["Goals - xG"], round(profile["Goals"] - profile["xG"], 2), places=2)
        minutes = comparison.minutes_played(ev, frames.df_all)
        self.assertNotIn("xG per 90", profile)
        self.assertIn("StatsBomb", json.dumps(figure["figure"]))
        source = (ROOT / "ui/analysis/tabs/comparison.js").read_text(encoding="utf-8")
        self.assertIn('"data-figure": "3"', source)
        self.assertIn('panel.querySelector(`[data-figure="${index}"]`)', source)

    def test_shooting_profile_without_an_own_goal_column(self):
        from analysis_core import comparison
        ev = pd.DataFrame({"type": ["Goal", "SavedShot", "Pass"], "xG": [0.4, 0.1, np.nan], "minute": [10, 20, 30]})
        profile = comparison.shooting_profile(ev, ev)
        self.assertEqual((profile["Shots"], profile["Goals"], profile["xG"], profile["Goals - xG"]), (2, 1, 0.5, 0.5))
        ev["is_own_goal"] = ["True", "False", "False"]
        self.assertEqual(comparison.shooting_profile(ev, ev)["Shots"], 1)

    def test_minutes_come_from_substitutions(self):
        from analysis_core import comparison
        df_all = pd.DataFrame({"type": ["Pass", "SubstitutionOn", "Pass"], "minute": [0, 60, 94],
                               "playerName": ["X", "Sub", "Sub"]})
        self.assertEqual(comparison.minutes_played(df_all[df_all["playerName"] == "Sub"], df_all), 34)
        self.assertEqual(comparison.minutes_played(df_all[df_all["playerName"] == "X"], df_all), 94)
        swapped = pd.DataFrame({"type": ["SubstitutionOff", "SubstitutionOn"], "minute": [61, 61], "playerName": ["Y", "Y"]})
        self.assertEqual(comparison.minutes_played(swapped, df_all), 61)


class TacticalTests(unittest.TestCase):
    def test_style_profile_shows_xg_per_shot(self):
        from analysis_core import tactical_page
        team_df = pd.DataFrame({"type": ["Goal", "SavedShot", "Goal", "Pass"], "xG": [0.5, 0.1, 0.76, np.nan],
                                "is_penalty": ["False", "False", "True", "False"]})
        self.assertAlmostEqual(tactical_page.xg_per_shot(team_df), 0.3)
        self.assertIsNone(tactical_page.xg_per_shot(team_df[team_df["type"] == "Pass"]))
        source = (ROOT / "app/analysis_core/tactical_page.py").read_text(encoding="utf-8")
        self.assertIn('("xG / Shot", _fmt_metric(xg_per_shot(team_df), decimals=2)', source)

    def test_video_lab_ranks_shots_by_xg(self):
        from analysis_core import tactical_page
        from tests.test_tactical_acceptance import event
        frame = tactical_page._prepare_df(pd.DataFrame([
            event(1, 300, "SavedShot", x=85), event(2, 540, "Goal", x=95), event(3, 720, "Goal", x=95),
        ]))
        frame["xG"] = [0.08, 0.61, np.nan]  # fixed values; the last (an own goal, say) has none
        rows = tactical_page._playlist_rows(frame, "Home", 8, 8, 10, 8)
        shots = rows[rows["playlist"].eq("Shots By xG")]
        self.assertEqual(shots["id"].tolist(), [2, 1])
        self.assertEqual(shots["why"].tolist(), ["xG 0.61 · Goal", "xG 0.08"])

if __name__ == "__main__":
    unittest.main()
