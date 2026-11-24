"""The editor's markup and script for parts: cut, reorder, repeat (docs/TELESTRATION_PLAN.md, M9)."""
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"


class PartsUiTests(unittest.TestCase):
    def setUp(self):
        self.html = (UI / "annotate.html").read_text(encoding="utf-8")
        self.script = (UI / "annotate.js").read_text(encoding="utf-8")
        self.css = (UI / "annotate.css").read_text(encoding="utf-8")

    def test_parts_lane_split_and_list_are_in_the_markup(self):
        for hook in ("data-parts-lane", "data-split", "data-parts-panel", "data-parts-list", "data-parts-count", "data-parts-empty"):
            self.assertIn(hook, self.html, hook)
        self.assertIn('title="Cut the clip into two parts at the playhead (X)"', self.html)
        self.assertIn(">Video</span>", self.html)  # the timeline row is named, as in a video editor

    def test_every_part_action_has_a_button_with_words_and_a_key_where_it_has_one(self):
        # Dragging is the quick route; the buttons are the keyboard and screen-reader route.
        for label in ("Earlier", "Later", "Repeat", "Remove"):
            self.assertIn(f'"{label}"', self.script)
        self.assertIn("partAction(", self.script)
        self.assertIn('key === "x"', self.script)  # split at the playhead
        self.assertIn("removePart(selectedPart)", self.script)  # Delete on a selected part
        self.assertIn("go.setAttribute(\"aria-pressed\"", self.script)

    def test_the_timeline_works_on_the_cut_clip_never_the_source_clip(self):
        self.assertIn("const total = () => totalSeconds(timing, doc.freezes);", self.script)
        self.assertIn("const source = () => outputToSource(outTime, timing, doc.freezes);", self.script)
        self.assertNotIn(", clip, doc.freezes", self.script)  # every timeline call takes `timing`
        # The picture and the tracks use the source frame.
        self.assertIn("const frameNow = () => realFrame(source().frame);", self.script)
        self.assertIn("const cutFrameNow = () => source().frame;", self.script)

    def test_a_clip_with_cuts_is_not_the_blank_state(self):
        self.assertIn("!(doc?.value.parts?.length > 1)", self.script)

    def test_parts_are_drawn_selected_and_dragged(self):
        for selector in (".annotate-part {", ".annotate-part.is-selected", ".annotate-part.is-dragging", ".annotate-part.is-drop", ".annotate-part-edge"):
            self.assertIn(selector, self.css, selector)


if __name__ == "__main__":
    unittest.main()
