"""Parity oracle for the analysis workspace migration (docs/ANALYSIS_MIGRATION_PLAN.md).

Fails when anything a user sees in the Analyst Room or Tactical Lab changes for
the committed synthetic fixture. Refresh deliberately with
``python -m tests.analysis_golden --write`` and review the diff.
"""
import unittest

from tests import analysis_golden


class AnalysisGoldenTests(unittest.TestCase):
    def test_fixture_is_deterministic(self):
        from tests.analysis_fixture import build_fixture
        self.assertTrue(build_fixture().equals(build_fixture()))

    def test_preserved_controls_do_not_show_streamlit_duplication_warning(self):
        import os
        from unittest.mock import patch
        from streamlit.elements.lib import policies
        from streamlit.testing.v1 import AppTest
        policies._shown_default_value_warning = False  # process-wide one-shot flag
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            ids = analysis_golden._make_projects(data, csvs[:1])
            with patch.dict(os.environ, {"CLIPMAKER_ANALYSIS_MODE": "1", "CLIPMAKER_DATA_DIR": str(data)}):
                app = AppTest.from_file(str(analysis_golden.ROOT / "app" / "analysis_entry.py"), default_timeout=180)
                app.query_params.update({"project": ids[0], "view": "analyst"})
                app.run()
                app.radio(key="smp_mode_radio").set_value("Penalty Shootout").run()
                box = app.selectbox(key="smp_pso_shot_sel")
                box.set_value(box.options[1]).run()
                self.assertEqual([], [w.value for w in app.warning])
                self.assertEqual([], [e.message for e in app.exception])

    def test_views_match_committed_golden(self):
        with analysis_golden.fixture_inputs() as (csvs, data):
            data.mkdir()
            actual = analysis_golden.capture(csvs, data, log=lambda *_: None)
        expected = analysis_golden.load(analysis_golden.GOLDEN)
        self.assertEqual(expected["inputs"], actual["inputs"], "fixture CSV bytes changed")
        self.assertEqual([], analysis_golden.compare(expected, actual))
        for view, tabs in actual["views"].items():
            for tab, records in tabs.items():
                with self.subTest(view=view, tab=tab):
                    self.assertTrue(records)
                    self.assertFalse([r["scenario"] for r in records if r["exceptions"]])


if __name__ == "__main__":
    unittest.main()
