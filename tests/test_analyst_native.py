"""Native Analyst Room tabs versus the classic workspace's recorded snapshot.

For every recorded scenario of each migrated tab, the native view built from
the same controls must show the same map arguments, picker list, filter
options, stats values, prompts, empty messages and selected-event details.
"""
import html
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

from analysis_core import build_analyst_frames, build_up, event_maps, pressing, shot_map  # noqa: E402
from tests import analysis_golden  # noqa: E402

IGNORED_ARGS = {"key", "default"}
SPECS = {
    "◉ Shot Map": {
        "build": shot_map.build_view,
        "controls": {"smp_mode_radio": ("mode", {"Normal": "normal", "Penalty Shootout": "penalties"}),
                     "smp_team_radio": "team", "smp_player_sel": "player", "smp_pitch_zone_sel": "zone"},
        "pickers": ["smp_shot_sel", "smp_pso_shot_sel"],
    },
    "◎ Pass Map": {
        "build": event_maps.build_pass_view,
        "controls": {"pm_view_radio": "view", "pm_player_sel": "player", "pm_type_radio": "pass_type",
                     "pm_pitch_zone_sel": "zone", "pm_depth_zone_sel": "depth"},
        "pickers": ["pm_pass_sel"],
    },
    "■ Defensive Actions": {
        "build": event_maps.build_defensive_view,
        "controls": {"dm_team_radio": "team", "dm_player_sel": "player", "dm_pitch_zone_sel": "zone",
                     "dm_depth_zone_sel": "depth"},
        "pickers": ["dm_action_sel"],
    },
    "◈ Dribbles & Carries": {
        "build": event_maps.build_dribbles_view,
        "controls": {"dcm_team_radio": "team", "dcm_player_sel": "player", "dcm_pitch_zone_sel": "zone",
                     "dcm_depth_zone_sel": "depth"},
        "pickers": ["dcm_action_sel"],
    },
    "⊞ Goalkeeper": {
        "build": event_maps.build_goalkeeper_view,
        "controls": {"gk_team_radio": "team", "gk_player_sel": "player", "gk_mode_radio": "mode",
                     "gk_pitch_zone_sel": "zone", "gk_depth_zone_sel": "depth"},
        "pickers": ["gk_sf_sel", "gk_dist_sel", "gk_action_sel"],
    },
    # Classic Pressing shows metric cards, has no event list, and its map
    # clicks never selected anything (fixed alongside this migration).
    "◆ Pressing": {
        "build": pressing.build_view,
        "controls": {"press_team_radio": "team", "press_zone_radio": "zone"},
        "pickers": [], "stats": "metrics", "native_picker": True, "min_selected": 0, "min_records": 4,
    },
    # Entry modes use a select; chain modes list sequences as buttons and
    # select one by clicking. The native prompt is reworded (no left column
    # or play button in the native layout), so prompts are not compared.
    "↗ Build-Up": {
        "build": build_up.build_view,
        "controls": {"bu_team_radio": "team", "bu_mode_radio": "mode",
                     "bu_min_chain": ("min_chain", {n: str(n) for n in range(2, 7)})},
        "pickers": ["bu_entry_select_final_third", "bu_entry_select_box"],
        "button_picker": r"^bu_chain_\d+$", "scenario_select": {"bu_chain_0": 0},
        "stats": "metrics", "skip_notice": True, "min_records": 6,
    },
}


def text_of(markup):
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


class AnalystNativeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from clipmaker_core import read_csv_safe
        cls.golden = analysis_golden.load(analysis_golden.GOLDEN)["views"]["analyst"]
        with analysis_golden.fixture_inputs() as (csvs, _):
            cls.frames = build_analyst_frames(read_csv_safe(str(csvs[0])), source=str(csvs[0]))

    def native_controls(self, spec, record):
        controls = {}
        for classic_key, target in spec["controls"].items():
            if classic_key in record["controls"]:
                value = record["controls"][classic_key]
                if isinstance(target, tuple):
                    target, mapping = target
                    value = mapping[value]
                controls[target] = value
        for key, index in spec.get("scenario_select", {}).items():
            if key in record["scenario"]:
                controls["selected"] = index
        chosen = next((record["controls"][key] for key in spec["pickers"] if key in record["controls"]), None)
        if chosen and not chosen.startswith("—"):
            listing = spec["build"](self.frames, {**controls, "selected": None})["picker"]["items"]
            controls["selected"] = next(item["id"] for item in listing if item["label"] == chosen)
        return controls

    def check(self, tab, spec, record):
        elements = record["elements"]
        by_key = {element.get("key"): element for element in elements if element.get("key")}
        result = analysis_golden._round(spec["build"](self.frames, self.native_controls(spec, record)))

        # Filters: same options as the classic widgets, in order.
        reverse = {(target[0] if isinstance(target, tuple) else target): key for key, target in spec["controls"].items()}
        for item in result["filters"]:
            classic = by_key.get(reverse.get(item["key"]))
            if classic and classic["kind"] == "Slider":
                expected = [str(value) for value in range(int(classic["min"]), int(classic["max"]) + 1)]
                self.assertEqual([option["label"] for option in item["options"]], expected, item["key"])
            elif classic:
                self.assertEqual([option["label"] for option in item["options"]], classic["options"], item["key"])

        # Stats: same values in the same order.
        if spec.get("stats") == "metrics":
            self.assertEqual([(e["label"], e["value"]) for e in elements if e["kind"] == "Metric"],
                             [(cell["label"], str(cell["home"])) for cell in result["stats"] or []], "metrics")
        bars = [] if spec.get("stats") == "metrics" else [
            e["value"] for e in elements if e["kind"] == "Markdown" and "cm-stats-bar" in e["value"]]
        classic_stats = re.findall(r'class="cm-stats-(?:home|away)"[^>]*>([^<]*)<', bars[0]) if bars else []
        native_stats = ([f"{result['share']['home']}%", f"{result['share']['away']}%"] if result["share"] else [])
        for cell in [] if spec.get("stats") == "metrics" else result["stats"] or []:
            native_stats += [str(cell["home"])] + ([str(cell["away"])] if "away" in cell else [])
        self.assertEqual([value.strip() for value in classic_stats], native_stats, "stats")
        classic_labels = [html.unescape(label).strip() for label in
                          re.findall(r'class="cm-stats-label"[^>]*>([^<]*)<', bars[0])] if bars else []
        native_labels = [] if spec.get("stats") == "metrics" else (
            (["Shot share"] if result["share"] else []) + [cell["label"] for cell in result["stats"] or []])
        self.assertEqual([label.casefold() for label in classic_labels], [label.casefold() for label in native_labels],
                         "stats labels")

        markdown = " ".join(text_of(e["value"]) for e in elements if e["kind"] == "Markdown")
        infos = [e["value"] for e in elements if e["kind"] == "Info"]
        if result["notice"] and not spec.get("skip_notice"):
            self.assertIn(result["notice"], markdown)
        if result["empty"]:
            self.assertIn(result["empty"], infos)
        self.assertEqual([{k: v for k, v in e["args"].items() if k not in IGNORED_ARGS}
                          for e in elements if e["kind"] == "component"],
                         [component["args"] for component in result["components"]], "components")

        pickers = [by_key[key] for key in spec["pickers"] if key in by_key]
        buttons = [e["label"] for e in elements if e["kind"] == "Button" and spec.get("button_picker")
                   and re.match(spec["button_picker"], e.get("key") or "")]
        if result["picker"] and buttons and not pickers:
            self.assertEqual(buttons, [item["label"] for item in result["picker"]["items"]], "sequence list")
        elif result["picker"] and spec.get("native_picker"):
            self.assertEqual(pickers, [])  # A native addition; nothing to compare.
        elif result["picker"]:
            self.assertEqual(pickers[0]["options"],
                             [result["picker"]["placeholder"]] + [item["label"] for item in result["picker"]["items"]])
        else:
            self.assertEqual(pickers, [])

        panels = [text_of(e["value"]) for e in elements
                  if e["kind"] == "Markdown" and ("cm-event-panel" in e["value"] or "cm-shot-panel" in e["value"])]
        if result["selected"] is not None and result["selected"].get("kind") == "sequence":
            self.assertIn(result["selected"]["title"], [e["value"] for e in elements if e["kind"] == "Subheader"])
        elif result["selected"] is None:
            self.assertEqual(panels, [])
        else:
            selected = result["selected"]
            panel = " ".join(panels[0].split())
            for text in [selected["title"], selected["subtitle"], *[field["value"] for field in selected["fields"]]]:
                self.assertIn(" ".join(str(text).split()), panel)
            plain = re.sub(r"[\[\]]", "", panel).casefold()
            for item in selected["badges"]:
                self.assertIn(item["text"].casefold(), plain, "badge")

    def test_every_recorded_scenario_matches(self):
        for tab, spec in SPECS.items():
            records = self.golden[tab]
            with self.subTest(tab=tab):
                self.assertGreaterEqual(len(records), spec.get("min_records", 6))
                selected = 0
                for record in records:
                    with self.subTest(tab=tab, scenario=record["scenario"]):
                        self.check(tab, spec, record)
                        selected += any(key in record["controls"] and not str(record["controls"][key]).startswith("—")
                                        for key in spec["pickers"]) or any(
                            key in record["scenario"] for key in spec.get("scenario_select", {}))
                self.assertGreaterEqual(selected, spec.get("min_selected", 1), f"{tab}: no recorded scenario selects an event")

    def test_comparison_matches_every_recorded_scenario(self):
        from analysis_core import comparison
        keys = {"comp_team1": "team1", "comp_player1": "player1", "comp_team2": "team2",
                "comp_player2": "player2", "comp_role1": "role1", "comp_role2": "role2"}
        records = self.golden["⇄ Comparison"]
        keeper_vs_keeper = 0
        for record in records:
            with self.subTest(scenario=record["scenario"]):
                controls = {target: record["controls"][key] for key, target in keys.items() if key in record["controls"]}
                result = analysis_golden._round(comparison.build_view(self.frames, controls))
                elements = record["elements"]
                # Templates differ by design: Streamlit's is a placeholder its browser code replaces.
                strip = lambda figure: {**figure, "layout": {k: v for k, v in figure["layout"].items() if k != "template"}}
                figures = [strip(e["figure"]) for e in elements if e["kind"] == "plotly"]
                self.assertEqual(figures, [strip(analysis_golden._round(f["figure"])) for f in result["figures"]], "figures")
                tables = [(e["columns"], e["rows"]) for e in elements if e["kind"] == "Dataframe"]
                self.assertEqual(tables, [(m["columns"], m["rows"]) for m in result["moments"] if not m["empty"]], "top 5")
                captions = [e["value"] for e in elements if e["kind"] == "Caption"]
                for moment in result["moments"]:
                    if moment["empty"]:
                        self.assertIn(moment["empty"], captions)
                    if moment["is_gk"]:
                        self.assertIn(f"{moment['player']} — Goalkeeper", captions)
                warnings = [e["value"].replace("**", "") for e in elements if e["kind"] == "Warning"]
                self.assertEqual(warnings, [result["warning"]] if result["warning"] else [])
                by_key = {e.get("key"): e for e in elements if e.get("key")}
                for item in result["filters"]:
                    classic = by_key.get(f"comp_{item['key']}")
                    self.assertIsNotNone(classic, item["key"])
                    self.assertEqual([o["label"] for o in item["options"]], classic["options"], item["key"])
                    self.assertEqual(item["label"], classic["label"], item["key"])
                keeper_vs_keeper += all(m["is_gk"] for m in result["moments"]) and len(result["moments"]) == 2
        self.assertGreaterEqual(len(records), 15)
        self.assertGreater(keeper_vs_keeper, 0, "no keeper-vs-keeper scenario recorded")

    def test_invalid_controls_fall_back_safely(self):
        for tab, spec in SPECS.items():
            with self.subTest(tab=tab):
                result = spec["build"](self.frames, {"team": "Nobody", "player": "<script>", "zone": "Moon", "depth": 7,
                                                     "selected": "x", "mode": "?", "view": "?", "pass_type": "?"})
                for item in result["filters"]:
                    self.assertIn(item["value"], [option["value"] for option in item["options"]])
                self.assertIsNone(result["selected"])
                self.assertIsNone(spec["build"](self.frames, {"selected": 10 ** 9})["selected"])


if __name__ == "__main__":
    unittest.main()
