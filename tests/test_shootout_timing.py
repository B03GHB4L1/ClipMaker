"""Penalty shootout timing. The PEN marker is set on the first kick, not the
start of the period; the engine works back from that kick's match clock to the
period start, so every kick lands where it happened and the clip buffers apply
as in any other period."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from analysis_core import FrameCache  # noqa: E402
from analysis_core.video import clip_window  # noqa: E402
from clipmaker_core import assign_periods, find_penalty_shootout_anchor_clock, read_csv_safe, resolve_period_starts_for_video  # noqa: E402


def row(minute, second, kind, period, **extra):
    return {"minute": minute, "second": second, "type": kind, "period": period, "team": extra.pop("team", "A"),
            "playerName": "p", "x": 88.5, "y": 50, "outcomeType": "Successful", **extra}


ROWS = [
    row(0, 0, "Start", "FirstHalf"), row(10, 0, "Pass", "FirstHalf"), row(45, 0, "Pass", "SecondHalf"),
    row(120, 0, "Start", "PenaltyShootout"),
    row(120, 40, "Card", "PenaltyShootout"),  # logged before the first kick
    row(121, 10, "Goal", "PenaltyShootout", is_penalty=True),
    row(121, 40, "SavedShot", "PenaltyShootout", team="B", is_penalty=True),
]
MARKERS = {1: "0:01:00", 2: "0:50:00", 5: "2:00:00"}  # the first kick is 7200 s into the video


class ShootoutTimingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "match.csv"
        pd.DataFrame(ROWS).to_csv(self.path, index=False)

    def tearDown(self):
        self.folder.cleanup()

    def test_first_kick_is_the_anchor_not_an_earlier_card(self):
        frame = assign_periods(read_csv_safe(str(self.path)), "period", None)
        self.assertEqual(find_penalty_shootout_anchor_clock(frame), 121 * 60 + 10)
        starts = resolve_period_starts_for_video(frame, {1: 60, 2: 3000, 5: 7200})
        self.assertEqual(starts[5], 7200 - 70)  # the period start, worked back from the first kick

    def test_analyst_clips_land_on_the_kicks(self):
        frames = FrameCache().get(str(self.path))
        self.assertFalse((frames.df_all["period"] == "PenaltyShootout").any())  # the analyst table drops the shootout
        for (minute, second), kick in (((121, 10), 7200), ((121, 40), 7230)):
            period, start, duration = clip_window(frames.timing_frame, MARKERS, [], minute, second, "PenaltyShootout", 5, 8)
            self.assertEqual((period, start, duration), (5, kick - 5, 13))


if __name__ == "__main__":
    unittest.main()
