import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from packaging.clipmaker_api_server import MatchStore

ROOT = Path(__file__).resolve().parents[1]


class AnalysisViewsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        types = ["Pass", "Goal", "SavedShot", "Tackle", "Interception", "BallRecovery", "Carry", "TakeOn", "Claim", "KeeperPickup", "Clearance", "Aerial"]
        rows = []
        for index in range(60):
            team = "Home" if index % 4 < 2 else "Away"
            rows.append({"minute": index + 1, "second": index % 50, "period": 1 if index < 45 else 2,
                         "type": types[index % len(types)], "team": team, "homeTeam": "Home", "awayTeam": "Away",
                         "playerName": f"{team} Player {index % 3}", "playerId": index % 6,
                         "outcomeType": "Successful" if index % 3 else "Unsuccessful",
                         "x": 20 + index % 65, "y": 10 + index % 75, "endX": 35 + index % 60,
                         "endY": 20 + index % 60, "xT": .02, "prog_pass": 10,
                         "is_key_pass": index % 7 == 0, "is_cross": index % 9 == 0,
                         "is_own_goal": False, "is_big_chance": False, "is_penalty": False,
                         "is_gk_save": False, "is_corner": False, "is_freekick": False})
        csv = self.root / "events.csv"
        pd.DataFrame(rows).to_csv(csv, index=False)
        store = MatchStore(self.root)
        self.project = store.create("Analysis fixture")
        store.upsert({"id": self.project["id"], "csv_path": str(csv), "home_team": "Home", "away_team": "Away",
                      "markers": {"1H": "00:00:00", "2H": "00:50:00"}})

    def tearDown(self):
        self.temporary.cleanup()

    def run_view(self, view):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {"CLIPMAKER_ANALYSIS_MODE": "1", "CLIPMAKER_DATA_DIR": str(self.root)}):
            app = AppTest.from_file(str(ROOT / "app" / "analysis_entry.py"))
            app.query_params["project"] = self.project["id"]
            app.query_params["view"] = view
            app.run(timeout=60)
            for tab in list(app.tabs):
                app.session_state[f"{view}_tabs"] = tab.label
                app.run(timeout=60)
                self.assertEqual(len(app.exception), 0, [entry.message for entry in app.exception])
            self.assertEqual(len(app.exception), 0, [entry.message for entry in app.exception])
            self.assertEqual(len(app.error), 0, [entry.value for entry in app.error])
            return app

    def test_analyst_room_renders_all_original_views(self):
        app = self.run_view("analyst")
        self.assertEqual(len(app.tabs), 8)
        self.assertEqual(app.session_state["csv_path"], str(self.root / "events.csv"))

    def test_tactical_lab_renders_all_original_views(self):
        app = self.run_view("tactical")
        self.assertEqual(len(app.tabs), 5)

    def test_analyst_secondary_modes_do_not_crash(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {"CLIPMAKER_ANALYSIS_MODE": "1", "CLIPMAKER_DATA_DIR": str(self.root)}):
            app = AppTest.from_file(str(ROOT / "app" / "analysis_entry.py"))
            app.query_params.update({"project": self.project["id"], "view": "analyst"})
            app.run(timeout=60)
            for key, choices in {
                "pm_view_radio": ["Home", "Away", "Pass Network"],
                "gk_mode_radio": ["Shots Faced", "Distribution", "GK Actions"],
                "bu_mode_radio": ["Possession Chains", "Final 3rd Entries", "Box Entries", "Progressive Chains"],
            }.items():
                for choice in choices:
                    with self.subTest(key=key, choice=choice):
                        app.session_state["analyst_tabs"] = {"pm_view_radio": "◎ Pass Map", "gk_mode_radio": "⊞ Goalkeeper", "bu_mode_radio": "↗ Build-Up"}[key]
                        app.session_state[key] = choice
                        app.run(timeout=60)
                        self.assertEqual(len(app.exception), 0, [entry.message for entry in app.exception])
                        self.assertEqual(app.radio(key=key).value, choice)
