"""Headers (2026-11-22). Feeds mark headed passes with HeadPass (Opta 3) and
headed shots and clearances with Head (Opta 15). The scrapers used to read only
Head, so the pass-scoped Headers filter never matched; shots get their own
Headed shots qualifier, and Filter's counts follow the same type scopes."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from packaging.clipmaker_api_server import load_filter_options  # first: it puts app/ on the path
import clipmaker_core as core  # noqa: E402
from app.scoresway_scraper import apply_qualifier_flags, make_empty_row, normalize_qualifiers  # noqa: E402
from app.whoscored_scraper import _is_header  # noqa: E402


class ScraperTests(unittest.TestCase):
    def test_whoscored_reads_both_header_qualifiers(self):
        self.assertTrue(_is_header({"HeadPass", "Zone"}))
        self.assertTrue(_is_header({"Head", "RegularPlay"}))
        self.assertFalse(_is_header({"RightFoot", "LongBall"}))

    def test_scoresway_reads_both_header_qualifiers(self):
        for qualifiers, event_type in (([{"qualifierId": 3}], "Pass"), ([{"qualifierId": 15}], "Goal")):
            with self.subTest(event_type=event_type):
                row = make_empty_row()
                apply_qualifier_flags(row, normalize_qualifiers(qualifiers), event_type, "Successful", "Home")
                self.assertTrue(row["is_header"])
        row = make_empty_row()
        apply_qualifier_flags(row, normalize_qualifiers([{"qualifierId": 72}]), "Pass", "Successful", "Home")
        self.assertFalse(row["is_header"])


ROWS = [
    {"id": "headed pass", "type": "Pass", "is_header": True},
    {"id": "foot pass", "type": "Pass", "is_header": False},
    {"id": "headed goal", "type": "Goal", "is_header": True},
    {"id": "headed miss", "type": "MissedShots", "is_header": True},
    {"id": "foot shot", "type": "SavedShot", "is_header": False},
    {"id": "headed clearance", "type": "Clearance", "is_header": True},
]


def frame():
    rows = [{"minute": 1, "second": i, "period": 1, "team": "Home", "playerName": "One",
             "outcomeType": "Successful", **row} for i, row in enumerate(ROWS)]
    return pd.DataFrame(rows, index=[10 + 3 * i for i in range(len(rows))])


class FilterTests(unittest.TestCase):
    def selected(self, config):
        result, _removed = core.apply_filters(frame(), config)
        return result["id"].tolist()

    def test_headers_keep_headed_passes_and_headed_shots_keep_headed_shots(self):
        shots = sorted(core.SHOT_TYPES)
        self.assertEqual(self.selected({"headers_only": True, "filter_types": ["Pass"]}), ["headed pass"])
        self.assertEqual(self.selected({"headed_shots_only": True, "filter_types": shots}), ["headed goal", "headed miss"])
        self.assertEqual(self.selected({"headers_only": True, "headed_shots_only": True, "filter_types": ["Pass", *shots]}),
                         ["headed pass", "headed goal", "headed miss"])

    def test_filter_counts_follow_each_qualifiers_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.csv"
            frame().to_csv(path, index=False)
            options = load_filter_options({"id": "headers", "csv_path": str(path)})
        counts = {item["flag"]: item["count"] for item in options["qualifiers"]}
        self.assertEqual((counts["headers_only"], counts["headed_shots_only"]), (1, 2))


if __name__ == "__main__":
    unittest.main()
