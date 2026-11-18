"""Fitting a followed player's box by hand: drag a corner of the dashed box (2026-11-18).

A loose box makes the tracker lose the player, so the analyst can tighten it: the dragged corner follows the
pointer, the opposite one stays, and on release the box becomes this frame's keyframe and the clip is tracked again.
"""
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"


class FollowBoxUiTests(unittest.TestCase):
    def setUp(self):
        self.script = (UI / "annotate.js").read_text(encoding="utf-8")
        self.html = (UI / "annotate.html").read_text(encoding="utf-8")

    def test_the_box_has_corner_handles_and_a_corner_can_be_dragged(self):
        self.assertIn("const boxCorners = ", self.script)
        for corner in ('"nw"', '"ne"', '"sw"', '"se"'):
            self.assertIn(corner, self.script)
        self.assertIn('gesture = { type: "resize"', self.script)
        self.assertIn('gesture.type === "resize"', self.script)
        self.assertIn('current.type === "resize"', self.script)

    def test_a_resized_box_becomes_a_keyframe_and_tracks_again_like_a_moved_foot(self):
        # Both edits go through one step, so they re-track the same way.
        self.assertIn("const keyTrack = (trackId, box) => {", self.script)
        self.assertIn("keyTrack(trackId, [at.box[0] + dx, at.box[1] + dy, at.box[2], at.box[3]]);", self.script)
        self.assertIn("keyTrack(current.trackId,", self.script)

    def test_a_corner_only_wins_over_the_foot_handle_when_it_is_nearer(self):
        # On a small player the corners and the foot handle overlap.
        self.assertIn("corner.distance <= handleDistance", self.script)

    def test_a_plain_click_only_selects_and_a_real_drag_edits(self):
        # A click used to count as "moved by 0": on a followed ring it made this frame a keyframe, which
        # locked in whatever box the tracker had there (even a swollen one) and tracked the clip again.
        self.assertIn("moved: false", self.script)
        self.assertIn("> 3 * (window.devicePixelRatio || 1)", self.script)
        self.assertIn('(current.moved || (current.type !== "move" && current.type !== "handle"))', self.script)

    def test_the_panel_says_how_to_fit_the_box(self):
        self.assertIn("Drag a corner of the dashed box to fit it tightly to the player", self.html)


if __name__ == "__main__":
    unittest.main()
